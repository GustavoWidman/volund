"""No-inference final-path integration of the actual workspace router and lane."""
from __future__ import annotations
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime.transport import StdioRPC
from runtime.contracts import initialize_params,RoleSpec
from runtime.workspace import WorkspaceRouter
from owner.measurement import MeasurementCoordinator

def setup_actor(actor_path):
    return SimpleNamespace(agent_id='setup-agent', role='implementation',
        thread_id=None, turn_id=None,
        spec=RoleSpec('gpt-6-luna','xhigh',actor_path,(actor_path,),'No inference'))

async def main():
    out=ROOT/'setup/workspace-router-probe-02';out.mkdir(parents=True,exist_ok=False)
    actor_path=out/'scratch/agent-1';actor_path.mkdir(parents=True)
    evidence=out/'evidence';evidence.mkdir()
    actor=setup_actor(actor_path)
    lane=MeasurementCoordinator();rpc=StdioRPC.official(actor_path,direct_terminal_authorized=True)
    router=WorkspaceRouter(rpc,lane,out,public_roots=(ROOT/'task/contract',),evidence_roots=(evidence,),
                           command_path=os.pathsep.join([str(Path(sys.executable).parent),os.defpath]))
    report={'status':'running','model_turns_requested':0,'started_unix':time.time(),'checks':[], 'actor_ids_are_setup_placeholders_not_model_threads':True, 'tested_source_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('runtime/workspace.py','runtime/command_supervisor.py','runtime/transport.py','owner/measurement.py','runtime/contracts.py')}}
    def check(name,condition):
        report['checks'].append({'name':name,'pass':bool(condition)})
        if not condition:raise RuntimeError('check_failed_'+name)
    try:
        await rpc.open();await rpc.request('initialize',initialize_params());await rpc.send({'method':'initialized','params':{}})
        account=await rpc.request('account/read',{'refreshToken':False})
        check('existing_auth_mode',(account.get('account') or {}).get('type')=='chatgpt')
        wrote=await router.dispatch(actor,'study_workspace_write',{'path':'sample.cpp','content':'int main(){return 0;}\n'})
        check('sandbox_workspace_write_tool',wrote['status']=='ok')
        async with lane.async_lease('bench',actor_id='setup-measurement'):
            read=await asyncio.wait_for(router.dispatch(actor,'study_workspace_read',{'path':'sample.cpp','max_bytes':4096}),1)
            check('bounded_read_during_measurement_lane',read['status']=='ok' and 'int main' in read['content'])
            queued=asyncio.create_task(router.dispatch(actor,'study_workspace_exec',{'command':'g++ -std=c++20 sample.cpp -o sample && ./sample','timeout_seconds':30}))
            await asyncio.sleep(.1)
            check('compile_queues_behind_measurement',not queued.done())
        compiled=await queued
        check('queued_compile_runs_after_lane_release',compiled['status']=='ok' and compiled['cleanup_complete'])
        failed=await router.dispatch(actor,'study_workspace_exec',{'command':'exit 9','timeout_seconds':3})
        check('ordinary_failure_repairable',failed['status']=='command_failed' and failed['cleanup_complete'] and lane.snapshot()['quarantine'] is None)
        repeated=await router.dispatch(actor,'study_workspace_exec',{'command':'printf recovered','timeout_seconds':3})
        check('followup_after_command_failure',repeated['status']=='ok')
        slow_command='printf ready > child-started.marker; sleep 30 & wait'
        slow=asyncio.create_task(router.dispatch(actor,'study_workspace_exec',{'command':slow_command,'timeout_seconds':60}))
        deadline=time.monotonic()+20
        while not (actor_path/'child-started.marker').exists() and not slow.done() and time.monotonic()<deadline:
            await asyncio.sleep(.02)
        check('cancellation_target_really_started',(actor_path/'child-started.marker').exists())
        slow.cancel();await asyncio.gather(slow,return_exceptions=True)
        await asyncio.sleep(0)
        receipts=[]
        for req in router.operations.glob('*/request.json'):
            request=json.loads(req.read_text())
            if request.get('arguments',{}).get('command')==slow_command:
                receipts.append(json.loads((req.parent/'supervisor-receipt.json').read_text()))
        check('cancellation_cleanup_before_lane_release',len(receipts)==1 and receipts[0]['process_started'] is True and receipts[0]['reason']=='interrupted' and lane.snapshot()['active'] is None and lane.snapshot()['quarantine'] is None)
        report['status']='pass'
    except BaseException as exc:
        report['status']='failed';report['error_category']=type(exc).__name__
        report['safe_error']=str(exc) if isinstance(exc,RuntimeError) else None
    finally:
        report['router_cleanup']=await router.close();report['rpc_cleanup']=await rpc.close()
        report['coordinator']=lane.snapshot();report['finished_unix']=time.time()
        (out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({'status':report['status'],'result':str(out/'result.json'),'model_turns_requested':0}))
    return 0 if report['status']=='pass' else 1
if __name__=='__main__':raise SystemExit(asyncio.run(main()))
