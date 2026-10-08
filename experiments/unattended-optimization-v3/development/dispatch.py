"""Authenticated runtime injects Agent -> immutable actor-bound service mapping."""
import asyncio
import copy
import stat
from pathlib import Path
from .schema import validate_arguments, RequestArgumentsError

STRING={'type':'string','minLength':1}
PURPOSES=('exploratory','official_review')
_SPECS = {
 'snapshot': ({'candidate':{**STRING,'description':'Absolute existing candidate directory under your own scratch root, normally candidate_directory from study_owner_checkout. Only ordinary files/directories are accepted, no symlinks/special files; nonempty tree within source_bytes from index.public_inputs. Snapshot again after edits; never edit retained snapshots.'}}, ['candidate']),
 'build': ({'source_hash':{**STRING,'description':'Exact immutable source_hash from snapshot/index/status.'}}, ['source_hash']),
 'test': ({'build_id':{**STRING,'description':'Successful recorded build operation_id from study_dev_build/index.'}}, ['build_id']),
 'profile': ({'build_id':dict(STRING),'fixture_id':{**STRING,'description':'Exact ID from study_owner_status.public_profile_ids or study_dev_index.public_inputs.profile_fixture_ids.'}}, ['build_id','fixture_id']),
 'memcheck': ({'build_id':dict(STRING),'fixture_id':{'type':['string','null'],'description':'Omit/null for the complete required suite. A selected profile fixture ID runs one probe only and cannot satisfy full official-review coverage.'}}, ['build_id']),
 'bench': ({'build_id':dict(STRING)}, ['build_id']),
 'journal': ({'text':{'type':'string','minLength':1,'pattern':r'\S','description':'Factual text; byte limit is discoverable in index.public_inputs.journal_entry_bytes.'},'evidence_ids':{'type':'array','items':dict(STRING),'description':'Recorded development operation IDs from results/index; omit for no references.'}}, ['text']),
 'index': ({}, []),
 'review_evidence': ({'build_id':{**STRING,'description':'Your own successful fresh official_review build under your current bound review_target plan. Requires your matching test/profile/full Memcheck/bench, unless a confirmed failure disqualifies the source.'}}, ['build_id']),
}
for _name in ('build','test','profile','memcheck','bench'):
    _SPECS[_name][0]['purpose']={'type':'string','enum':list(PURPOSES),'default':'exploratory',
      'description':'exploratory is ordinary investigation. official_review is reviewer-only, after study_owner_review_target, using its exact source and plan.'}
    if 'build_id' in _SPECS[_name][0] and 'description' not in _SPECS[_name][0]['build_id']:
        _SPECS[_name][0]['build_id']['description']='Successful recorded build operation_id from study_dev_build/index; official review requires your own plan-bound build.'
_SPECS['bench'][0]['reference_id']={'type':'string','default':'inherited',
  'description':'A bound alias from owner_status.benchmark_reference_ids or index.public_inputs.reference_ids, normally inherited or seed. This is NOT a build ID/source hash. Official review must use public_inputs.official_review_reference_id (inherited for this study).'}
DESCRIPTIONS={
 'snapshot':'Capture your candidate as an immutable source snapshot; returns source_hash for recorded builds.',
 'build':'Compile an immutable source. Ordinary compile failures remain evidence and may be repaired in your candidate then snapshotted again.',
 'test':'Execute the canonical correctness oracle on a recorded build.',
 'profile':'Run a public diagnostic profile; profile instruction counts are not benchmark timings.',
 'memcheck':'Run memory probes; omit fixture_id to execute the complete required suite for official review.',
 'bench':'Run a paired comparison against a bound reference alias. Coordinate a quiet window: wait for other workers ordinary commands to finish. Overlap-invalidated samples are retained and may be rerun after quieting workers; they are not candidate performance failures.',
 'journal':'Append a factual development record/correction with optional recorded operation IDs.',
 'index':'Discover recorded source hashes, operation IDs, artifacts, journal and exact bound reference/fixture selectors.',
 'review_evidence':'Collect your own exact-source official execution receipt, all official attempts, and first complete valid plan comparison. Never selects latest/best; confirmed semantic/memory failures remain disqualifying.'}


def tool_specs(role):
    result=[]
    for name,(props,required) in _SPECS.items():
        if name=='review_evidence' and role!='reviewer':continue
        props=copy.deepcopy(props)
        if 'purpose' in props and role!='reviewer':props['purpose']['enum']=['exploratory']
        result.append({'type':'function','name':'study_dev_'+name,'description':DESCRIPTIONS[name],
          'inputSchema':{'type':'object','additionalProperties':False,'properties':props,'required':list(required)}})
    return result


def public_inputs(service):
    grant=service.grant()
    backend=service.backend
    suite=getattr(getattr(backend,'config',None),'profile_suite','profile')
    fixtures=[row['id'] for row in backend.fixtures(suite)] if hasattr(backend,'fixtures') else []
    return {'reference_ids':['inherited',*[r.reference_id for r in grant.references]],
            'official_review_reference_id':grant.official_reference_id,
            'profile_fixture_ids':fixtures,'memcheck_full_suite':'omit fixture_id or use null',
            'candidate_roots':list(grant.candidate_roots),
            'journal_entry_bytes':service.limits.journal_entry_bytes,'source_bytes':service.limits.source_bytes}


def _invalid(tool,field,message,**details):
    raise RequestArgumentsError(tool,[{'field':field,'message':message,**details}])


def make_dispatcher(service_for_agent):
    """Validate repairable arguments before executing any native operation.

    Runtime identity/grants still supply authority. Retained source/evidence
    mutation and capture races remain integrity failures in the service.
    """
    locks={}
    async def dispatch(agent,tool,arguments):
        name=tool.removeprefix('study_dev_')
        specs={row['name']:row for row in tool_specs(agent.role)}
        if tool not in specs:
            _invalid(tool,'tool','Tool is not available to this runtime role.',allowed_tools=list(specs))
        validate_arguments(tool,specs[tool]['inputSchema'],arguments)
        lock=locks.setdefault(agent.agent_id,asyncio.Lock())
        async with lock:
            service=service_for_agent(agent)
            def execute():
                if name=='snapshot':
                    grant=service.grant();path=Path(arguments['candidate'])
                    if not path.is_absolute() or path.is_symlink() or not path.is_dir() or not any(path.resolve().is_relative_to(Path(p).resolve()) for p in grant.candidate_roots):
                        _invalid(tool,'candidate','Use the existing absolute candidate_directory returned by study_owner_checkout under your own scratch root; missing, symlink or outside-root paths are not accepted.',allowed_roots=list(grant.candidate_roots))
                    count=total=0
                    for item in path.rglob('*'):
                        mode=item.lstat().st_mode
                        if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                            _invalid(tool,'candidate','Candidate must contain only ordinary files/directories; remove symlinks or special files in your scratch copy before snapshotting.')
                        if stat.S_ISREG(mode):count+=1;total+=item.stat().st_size
                    if not count or total>service.limits.source_bytes:
                        _invalid(tool,'candidate','Candidate must contain a nonempty tree of ordinary files within the allowed source byte limit.',maximum_source_bytes=service.limits.source_bytes)
                    return service.snapshot(arguments['candidate'])
                if name=='journal':return service.append_journal(arguments['text'],arguments.get('evidence_ids',()))
                if name=='index':return {**service.index(),'public_inputs':public_inputs(service)}
                if name=='review_evidence':return service.review_evidence(arguments['build_id'])
                if name in ('bench','profile','memcheck'):
                    choices=public_inputs(service)
                    if name=='bench':
                        reference=arguments.get('reference_id','inherited')
                        allowed=[choices['official_review_reference_id']] if arguments.get('purpose','exploratory')=='official_review' else choices['reference_ids']
                        if reference not in allowed:
                            _invalid(tool,'reference_id','Choose a bound reference alias, not a build ID or source hash: '+', '.join(allowed)+'.',allowed_values=allowed)
                    fixture=arguments.get('fixture_id')
                    if name in ('profile','memcheck') and fixture is not None and fixture not in choices['profile_fixture_ids']:
                        _invalid(tool,'fixture_id','Use an exact public profile fixture ID; omit/null for complete-suite Memcheck.',allowed_values=choices['profile_fixture_ids'])
                result=service.run(name,**arguments)
                if result.get('measurement_invalidated')=='competing_study_command_execution':
                    result={**result,'recovery':'This is an infrastructure-invalid sample, not a candidate performance failure. Wait for other study ordinary commands to finish, ask workers to remain quiet, then rerun this benchmark. The invalid sample remains retained.'}
                return result
            return await asyncio.to_thread(execute)
    return dispatch
