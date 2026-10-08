"""One direct-terminal deployment: actual setup -> no-inference idle gate -> campaigns."""
from __future__ import annotations
import argparse
import asyncio
import dataclasses
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path
from development.core import IntegrityError, write_new
from development.prepare import prepare_native
from development.core import audit_store
from runtime.contracts import APPROVED_MODELS, RoleSpec, Safeguards, RuntimeFailure
from runtime.multiagent import Host, TERMINAL, wait_for_completion
from runtime.transport import StdioRPC, CLI, AUTH_HOME
from runtime.pricing import price_ledger,PricingFailure
from runtime.workspace import WorkspaceRouter, tool_specs as workspace_specs
from .service import OwnerService, load, replace_json
from .tools import combined_specs,make_dispatch
from .prompts import instructions,PREFLIGHT_TASK,MEASURED_TASK,CONTINUATION
from .overlap import CommandIntervals,AuditedBackend
from .measurement import MeasurementCoordinator,CoordinatedBackend,MeasurementCoordinationError
from .readiness import code_manifest,check_manifest,create_freeze,verify_authorization,final_configurations,authorize_freeze

ROOT=Path(__file__).resolve().parents[1]


def roles_for(directory):
    roles={}
    for role,(model,effort) in APPROVED_MODELS.items():
        path=Path(directory)/'scratch'/role;path.mkdir(parents=True,exist_ok=False)
        roles[role]=RoleSpec(model,effort,path,(path,),instructions(role))
    return roles


def require_completed_turns(host, export):
    """Emergency cancellation never silently becomes normal branch abandonment."""
    if not export['accounting_complete']:
        raise RuntimeFailure('required_role_usage_incomplete')
    if any(a.state in ('interrupted', 'cancelled') for a in host.agents.values()):
        raise RuntimeFailure('emergency_cancelled_turn_stops_campaign_incomplete')
    if any(a.state != 'completed' for a in host.agents.values()):
        raise RuntimeFailure('role_turn_failed_or_interrupted')


async def run_workflow(root,directory,backend,config,*,setup=False,rpc_factory=None,measurement_coordinator=None):
    """No arbitrary completion turn cap; every continuation preserves lead context."""
    coordinator=measurement_coordinator or MeasurementCoordinator()
    intervals=coordinator.commands
    owner=OwnerService(root,directory,CoordinatedBackend(backend,coordinator),config,setup=setup)
    owner.bootstrap();roles=roles_for(directory)
    rpc=(rpc_factory(roles['lead'].cwd) if rpc_factory else StdioRPC.official(roles['lead'].cwd,direct_terminal_authorized=True))
    native_config=getattr(backend,'config',None)
    public_roots=[root/'task/contract']
    fixture_root=Path(native_config.fixtures) if native_config else None
    if fixture_root and fixture_root.is_dir():public_roots.append(fixture_root)
    native_cpus=set(native_config.ordinary.cpus) if native_config else set()
    execution_cpus=tuple(sorted(set(os.sched_getaffinity(0))-native_cpus))
    command_path=os.pathsep.join(dict.fromkeys([str(Path(sys.executable).parent),
        str(Path(native_config.callgrind).parent) if native_config else '/usr/bin',*os.defpath.split(os.pathsep)]))
    workspace=WorkspaceRouter(rpc,coordinator,Path(directory),public_roots=public_roots,
        evidence_roots=(owner.store/'events',owner.store/'snapshots',owner.store/'operations',
                        owner.private/'events',owner.private/'checkpoint-usage'),
        check_active=owner.validate_actor,command_path=command_path,cpus=execution_cpus,
        valgrind_lib=native_config.valgrind_lib if native_config else None)
    host=Host(rpc,roles,Safeguards(),Path(directory)/'runtime',
              additional_tools={role:combined_specs(role,workspace_specs(role)) for role in roles},
              tool_dispatch=make_dispatch(owner,workspace),
              artifact_roots=(owner.store,owner.private,workspace.operations))
    owner.attach_host(host)
    def events(msg):intervals.event(msg);host.on_event(msg)
    rpc.on_event=events
    failure=None;telemetry=None
    try:
        await rpc.open();await host.initialize()
        await host.spawn('lead',PREFLIGHT_TASK if setup else MEASURED_TASK)
        while True:
            await wait_for_completion(host)
            export=host.export()
            require_completed_turns(host, export)
            if owner.state['status']=='complete':break
            await host.continue_lead(CONTINUATION)
    except BaseException as exc:
        failure=('owner_stop_requested' if isinstance(exc,asyncio.CancelledError) else
                 str(exc) if isinstance(exc,(RuntimeFailure,IntegrityError,MeasurementCoordinationError)) else type(exc).__name__)
    finally:
        async def finalize():
            nonlocal failure,telemetry
            stop_task=None
            if failure:
                owner.cancelled=True
                host.stopping=True
                stop_task=asyncio.create_task(host.stop(failure))
            workspace_cleanup=await workspace.close()
            if not workspace_cleanup['drained']:failure=failure or 'workspace_cleanup_not_drained'
            if workspace_cleanup.get('quarantine'):failure=failure or 'measurement_resource_quarantined'
            if failure:
                if stop_task is None:
                    owner.cancelled=True;host.stopping=True
                    stop_task=asyncio.create_task(host.stop(failure))
                try:await stop_task
                except Exception:pass
                try:await asyncio.to_thread(owner.stop,failure)
                except Exception:host.failure=host.failure or 'owner_stop_state_write_failed'
            # Native work runs in executor threads, which cancelling an await
            # alone cannot stop. Revoke grants above and await actual lane exit
            # before closing transport or sealing telemetry.
            while coordinator.snapshot()['active'] or coordinator.snapshot()['queued']:
                await asyncio.sleep(.01)
            cleanup=await rpc.close()
            if not cleanup.get('event_stream_drained',False):failure=failure or 'shutdown_event_stream_not_drained'
            if not cleanup.get('event_processing_complete',False):failure=failure or 'shutdown_event_processing_incomplete'
            if not cleanup.get('tracked_processes_exited',False):failure=failure or 'process_cleanup_incomplete'
            if failure:host.failure=host.failure or failure
            if all(a.state in TERMINAL for a in host.agents.values()):host.seal()
            telemetry=host.export()
            telemetry['cleanup']=cleanup
            telemetry['workspace_cleanup']=workspace_cleanup
            telemetry['measurement_coordinator']=coordinator.snapshot()
            telemetry['owner_status']=owner.state['status'];telemetry['failure']=failure or telemetry['failure']
            telemetry['turn_counts']={a.agent_id:len(a.all_turns) for a in host.agents.values()}
            telemetry['runtime_source']='injected_test' if rpc_factory else 'official_direct_terminal_appserver'
            try:telemetry['api_equivalent_cost']=price_ledger(telemetry)
            except PricingFailure as exc:
                telemetry['api_equivalent_cost']={'status':'unavailable','reason':str(exc),'actual_billed_cost':None}
                telemetry['failure']=telemetry['failure'] or 'pricing_partition_validation_failed'
            if telemetry['failure'] or not telemetry['accounting_complete']:
                if owner.state['status']!='incomplete':
                    try:owner.stop(telemetry['failure'] or 'accounting_incomplete_at_shutdown')
                    except Exception:telemetry['stop_state_record_failure']='owner_stop_state_write_failed'
                telemetry['owner_status']=owner.state['status']
            write_new(Path(directory)/'telemetry.json',telemetry)
            write_new(Path(directory)/'summary.json',{'status':'complete' if owner.state['status']=='complete' and not telemetry['failure'] and telemetry['accounting_complete'] else 'incomplete',
                      'stage':'setup' if setup else 'measured','failure':telemetry['failure'],'endpoint':owner.state.get('endpoint'),
                      'telemetry_path':str(Path(directory)/'telemetry.json')})
        finalizing=asyncio.create_task(finalize())
        while True:
            try:
                await asyncio.shield(finalizing)
                break
            except asyncio.CancelledError:
                if finalizing.cancelled():raise RuntimeFailure('owner_finalization_cancelled')
                # Repeated owner stop requests must not cancel protocol drain.
                failure=failure or 'owner_stop_requested'
    return owner,telemetry


def inspect_preflight(owner,telemetry,execution_manifest):
    audit=audit_store(owner.store,load(owner.private/'development-heads.json').get(str(owner.store)))
    events,snapshots,ops=audit['events'],audit['snapshots'],audit['operations']
    rows=list(ops.values());roles={a['role'] for a in telemetry['agents']}
    sequence={e['payload']['operation_id']:e['sequence'] for e in events if e['kind']=='operation_finished'}
    actor_roles={a['agent_id']:a['role'] for a in telemetry['agents']}
    repairs=[]
    for failed in rows:
        if failed['operation']=='build' and failed['status']=='candidate_failure' and actor_roles.get(failed['actor_id'])=='implementation':
            later=[p for p in rows if p['operation']=='build' and p['status']=='pass' and p['actor_id']==failed['actor_id'] and p['source_hash']!=failed['source_hash'] and sequence[p['operation_id']]>sequence[failed['operation_id']]]
            repairs.extend(later)
    repaired_executed=any(all(any(p['operation']==kind and p['build_id']==b['operation_id'] and p['actor_id']==b['actor_id'] and p['status']=='pass' and sequence[p['operation_id']]>sequence[b['operation_id']] for p in rows) for kind in ('test','profile')) for b in repairs)
    measurement_actors={a['agent_id'] for a in telemetry['agents'] if a['role']=='measurement'}
    baseline_measured=any(all(any(p['actor_id']==actor and p['source_hash']==owner.state['seed']['source_hash'] and p['operation']==kind and p['status']=='pass' for p in rows) for kind in ('bench','profile')) for actor in measurement_actors)
    full_review=False
    for r in owner.state['reviews'].values():
        receipt=r.get('receipt') or {}
        evidence=receipt.get('execution_evidence') or {}
        if all(any(i in ops and ops[i]['operation']==kind and ops[i]['status']=='pass' and ops[i]['actor_id']==receipt.get('actor_id') and ops[i]['source_hash']==receipt.get('source_hash') and ops[i].get('purpose')=='official_review' for i in evidence.get(kind,[])) for kind in ('build','test','profile','memcheck','bench')):
            full_review=True
    workspace_rows=[]
    for request_path in (owner.directory/'workspace-operations').glob('*/request.json'):
        result_path=request_path.with_name('result.json')
        if result_path.exists():workspace_rows.append((load(request_path),load(result_path)))
    unleased_commands=0
    for trace in (owner.directory/'runtime').glob('agent-*.jsonl'):
        for line in trace.read_text().splitlines():
            if json.loads(line).get('item',{}).get('type')=='commandExecution':unleased_commands+=1
    checks={'lead_worker_reviewer_roles_observed':{'lead','measurement','implementation','reviewer'}<=roles,
            'actual_all_role_usage':telemetry['accounting_complete'],
            'shutdown_event_stream_drained':telemetry.get('cleanup',{}).get('event_stream_drained') is True,
            'shutdown_event_processing_complete':telemetry.get('cleanup',{}).get('event_processing_complete') is True,
            'all_spawned_processes_exited':telemetry.get('cleanup',{}).get('tracked_processes_exited') is True,
            'implementation_compile_failure_repaired':bool(repairs),
            'repaired_candidate_tested_and_profiled':repaired_executed,
            'measurement_worker_baseline_benchmark_and_profile':baseline_measured,
            'existing_worker_followup':any(telemetry['turn_counts'].get(a['agent_id'],0)>1 for a in telemetry['agents'] if a['role'] in ('measurement','implementation','investigation')),
            'reviewer_executed_full_official_suite':full_review,
            'negative_or_exact_seed_no_code_reviewed':any(h['review_id'] and (h['disposition'] in ('contradicted','inconclusive') or (h['disposition']=='supported' and h.get('source_hash')==owner.state['seed']['source_hash'])) for h in owner.state['hypotheses'].values()),
            'unchanged_source_rejected':any(n['status']=='rejected' and n['source_hash']==n['parent']['source_hash'] for n in owner.state['nominations'].values()),
            'journal_recovery':bool(owner.state.get('rejected_requests')) and bool(owner.state['journal']),
            'source_sealed_with_task_closure':owner.state['status']=='complete','runtime_failure_absent':not telemetry['failure'],
            'participant_bounded_workspace_read_observed':any(q['tool']=='study_workspace_read' and r['status']=='ok' for q,r in workspace_rows),
            'participant_sandboxed_workspace_exec_observed':any(q['tool']=='study_workspace_exec' and r['status']=='ok' and r.get('cleanup_complete') is True for q,r in workspace_rows),
            'no_unleased_builtin_command_execution':unleased_commands==0,
            'workspace_cleanup_drained':telemetry.get('workspace_cleanup',{}).get('drained') is True,
            'measurement_lane_idle_not_quarantined':telemetry.get('measurement_coordinator',{}).get('active') is None and not telemetry.get('measurement_coordinator',{}).get('queued') and telemetry.get('measurement_coordinator',{}).get('quarantine') is None}
    return {'status':'pass' if all(checks.values()) else 'fail','checks':checks,'real_runtime_observed':telemetry.get('runtime_source')=='official_direct_terminal_appserver',
            'execution_manifest':execution_manifest,'campaign_directory':str(owner.directory),
            'telemetry_path':str(owner.directory/'telemetry.json'),'setup_only':True}


async def launch(root=ROOT,*,direct_terminal_authorized=False,cancelled=None):
    root=Path(root).resolve(strict=True)
    if not direct_terminal_authorized:raise RuntimeFailure('explicit_user_direct_terminal_launch_required')
    launch_dir=root/'state/launch';launch_dir.mkdir(parents=True,exist_ok=False)
    config=load(root/'owner/config.draft.json')
    state={'status':'setup_starting','started_unix':time.time(),'root':str(root),'automatic_restart':False,
           'cli_path':str(CLI),'cli_version_required':'0.159.3','auth_home_path':str(AUTH_HOME)}
    def checkpoint(**values):
        state.update(values);replace_json(launch_dir/'status.json',state)
        print(json.dumps({k:state.get(k) for k in ('status','active_campaign','failure')}),flush=True)
    checkpoint()
    cancelled=cancelled or threading.Event()
    coordinator=MeasurementCoordinator()
    try:
        native=prepare_native(root,root/'setup/launch-native')
        before=code_manifest(root)
        checkpoint(status='actual_multiagent_preflight')
        owner,telemetry=await run_workflow(root,root/'setup/live-preflight',native,config,setup=True,measurement_coordinator=coordinator)
        preflight=inspect_preflight(owner,telemetry,before)
        write_new(launch_dir/'preflight.json',preflight)
        if preflight['status']!='pass':raise RuntimeFailure('actual_preflight_failed_no_measured_launch')
        checkpoint(status='awaiting_exact_owner_readiness_no_inference',preflight_path=str(launch_dir/'preflight.json'))
        authorization=launch_dir/'authorization.json'
        # No rpc or model sessions run during this readiness wait. No time budget.
        while not authorization.exists():await asyncio.sleep(config['readiness_poll_seconds'])
        freeze=verify_authorization(root,authorization)
        checkpoint(status='frozen_authorized',freeze_sha256=load(authorization)['freeze_sha256'])
        campaign_directories=[]
        for index in range(1,freeze['campaign_count']+1):
            verify_authorization(root,authorization)
            name=f'campaign-{index}';checkpoint(status='investigating',active_campaign=name)
            campaign,usage=await run_workflow(root,root/'campaigns'/name,native,freeze['config'],measurement_coordinator=coordinator)
            if campaign.state['status']!='complete' or usage['failure'] or not usage['accounting_complete']:
                raise RuntimeFailure('campaign_incomplete_no_replacement_or_resume')
            campaign_directories.append(campaign.directory)
        checkpoint(status='all_endpoints_sealed_final_assessment_owner_only',active_campaign=None)
        from evaluation.run import assess
        from development.core import Cancelled
        def check_cancelled():
            if cancelled.is_set():raise Cancelled('owner cancelled final assessment')
        configurations=final_configurations(root)
        result=await asyncio.to_thread(assess,root,campaign_directories,configurations,root/'assessment/final',
                    verify_frozen=lambda:verify_authorization(root,authorization),check_cancelled=check_cancelled,
                    measurement_coordinator=coordinator)
        checkpoint(status='complete',assessment_status=result['status'],finished_unix=time.time())
        return 0
    except BaseException as exc:
        cancelled.set()
        checkpoint(status='stopped_incomplete',failure=str(exc) if isinstance(exc,(RuntimeFailure,IntegrityError)) else type(exc).__name__)
        return 130 if isinstance(exc,(KeyboardInterrupt,asyncio.CancelledError)) else 1


async def with_stop_signals(factory):
    """Cancel only the workflow task once; readers/cleanup keep their event loop."""
    loop=asyncio.get_running_loop();cancelled=threading.Event();task=None
    old={sig:signal.getsignal(sig) for sig in (signal.SIGTERM,signal.SIGHUP,signal.SIGINT)}
    def request_stop():
        if cancelled.is_set():return
        cancelled.set()
        if task is not None and not task.done():task.cancel()
    for sig in old:loop.add_signal_handler(sig,request_stop)
    try:
        task=asyncio.create_task(factory(cancelled))
        try:result=await task
        except asyncio.CancelledError:result=130
        return 130 if cancelled.is_set() else result
    finally:
        for sig,handler in old.items():
            loop.remove_signal_handler(sig);signal.signal(sig,handler)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);subs=parser.add_subparsers(dest='command',required=True)
    run=subs.add_parser('launch');run.add_argument('--direct-terminal-authorized',action='store_true')
    ready=subs.add_parser('freeze');ready.add_argument('--readiness',type=Path,required=True);ready.add_argument('--preflight',type=Path,required=True)
    authorize=subs.add_parser('authorize')
    for key in ('freeze','readiness','preflight'):authorize.add_argument('--'+key+'-sha256',required=True)
    verify=subs.add_parser('verify');verify.add_argument('--authorization',type=Path,required=True)
    args=parser.parse_args(argv)
    if args.command=='launch':
        return asyncio.run(with_stop_signals(lambda cancelled:launch(direct_terminal_authorized=args.direct_terminal_authorized,cancelled=cancelled)))
    if args.command=='freeze':result=create_freeze(ROOT,args.readiness,args.preflight)
    elif args.command=='authorize':result=authorize_freeze(ROOT,args.freeze_sha256,args.readiness_sha256,args.preflight_sha256)
    else:result=verify_authorization(ROOT,args.authorization)
    print(json.dumps(result,indent=2));return 0
