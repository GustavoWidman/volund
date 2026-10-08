"""Official dynamic tool specs and actor-bound combined owner/development routing."""
import asyncio
from development.dispatch import tool_specs as development_specs, make_dispatcher
from development.core import DevelopmentError, IntegrityError, Cancelled
from .service import OwnerService, OwnerError, OWNER_METHODS
from .public_api import input_schema
from .measurement import MeasurementCoordinationError
from development.schema import validate_arguments, RequestArgumentsError

LEAD={'hypothesis','report_hypothesis','nominate','withdraw_nomination','propose_closure'}
REVIEW={'review_target','inspect','claim_review','nomination_review','closure_review'}
DESCRIPTIONS={
 'status':'Get compact current decisions, active work, incumbent, hypothesis summaries and evidence paths without waiting for native jobs. Full usage histories are never embedded.',
 'history':'Select a factual record by ID or page own-campaign history; use this for complete hypothesis/review detail omitted from compact status.',
 'checkout':'Copy an immutable source snapshot into YOUR isolated writable candidate directory for repeated investigation.',
 'journal':'Append a factual claim or correction; immutable prior entries remain. Link actual development evidence IDs.',
 'hypothesis':'Register a falsifiable hypothesis before discriminating measurements; include observations motivating it.',
 'report_hypothesis':'Record supported, contradicted or inconclusive observations with actual source-bound evidence.',
 'queue':'Maintain a concrete actionable investigation or evidence-backed disposition. Reviewer may add a concern.',
 'nominate':'Freeze an exact source hash against the current verified parent for independent empirical review.',
 'withdraw_nomination':'Retire pending or needs-work nomination with explanation and retained evidence; no deletion.',
 'review_target':'Reviewer binds its independent execution grant to a nomination, reported hypothesis or closure dossier.',
 'inspect':'Reviewer receives exact source or actual ordinary evidence output and a hash-bound inspection receipt.',
 'claim_review':'Independently assess a factual hypothesis report using your own executed and inspected evidence.',
 'nomination_review':'Record recommendation after your own official build,test,profile,complete Memcheck,benchmark. Owner applies mechanical gates.',
 'propose_closure':'Lead presents bounded uncertainties and branch dispositions after all hypotheses reviewed and actionable queue resolved.',
 'closure_review':'Independent reviewer endorses task completion or continues work after inspecting the complete dossier.'}


def tool_specs(role):
    tools=[]
    for name in OWNER_METHODS:
        if (name in LEAD and role!='lead') or (name in REVIEW and role!='reviewer') or (name=='queue' and role not in ('lead','reviewer')):continue
        schema=input_schema(name,getattr(OwnerService,name))
        if name=='queue' and role=='reviewer':schema['properties']['status']['enum']=['actionable']
        tools.append({'type':'function','name':'study_owner_'+name,'description':DESCRIPTIONS[name],
                      'inputSchema':schema})
    return tools


def combined_specs(role,workspace_specs=()):return development_specs(role)+tool_specs(role)+list(workspace_specs)


def make_dispatch(owner,workspace=None):
    development=make_dispatcher(owner.service_for_agent)
    async def dispatch(agent,tool,args):
        try:
            if tool.startswith('study_workspace_'):
                if workspace is None:raise OwnerError('workspace tools unavailable')
                owner.validate_actor(agent)
                result=await workspace.dispatch(agent,tool,args)
                if result.get('status')=='resource_quarantined' and owner.host:
                    owner.host.failure='workspace_resource_cleanup_unverified'
                    owner.host.changed.set()
                return result
            if tool.startswith('study_dev_'):return await development(agent,tool,args)
            if not tool.startswith('study_owner_'):raise OwnerError('unknown tool namespace')
            name=tool.removeprefix('study_owner_')
            permitted={t['name']:t for t in tool_specs(agent.role)}
            if tool not in permitted:raise OwnerError('role cannot use this owner tool')
            spec=permitted[tool]['inputSchema']
            validate_arguments(tool,spec,args)
            return await asyncio.to_thread(owner.dispatch,agent,name,args)
        except MeasurementCoordinationError as exc:
            if owner.host:
                owner.host.failure='measurement_resource_quarantined'
                owner.host.changed.set()
            return {'status':'infrastructure_blocked','error':str(exc),
                    'scope':'resource cleanup uncertainty; not candidate correctness or performance'}
        except IntegrityError:
            if owner.host:owner.host.failure='owner_or_development_integrity_failure'
            return {'status':'integrity_stop','error':'authoritative source/evidence binding failed; dependent work stopped'}
        except Cancelled:
            return {'status':'cancelled','error':'runtime actor or campaign cancelled'}
        except (OwnerError,DevelopmentError,ValueError,TypeError) as exc:
            # Normal malformed requests and candidate failures are repairable.
            if tool=='study_owner_journal':
                with owner.lock:
                    owner._audit()
                    rejected={'tool':tool,'actor_id':agent.agent_id,'error_category':type(exc).__name__}
                    owner.state.setdefault('rejected_requests',[]).append(rejected)
                    owner._change('correctable_request_rejected',rejected,agent)
            if isinstance(exc,RequestArgumentsError):return exc.response()
            return {'status':'request_error','error':str(exc),'correctable':True,
                    'repair':'Inspect study_owner_status or study_dev_index for current IDs and evidence, then correct this request and retry. A request error is not a scientific verdict.'}
    return dispatch
