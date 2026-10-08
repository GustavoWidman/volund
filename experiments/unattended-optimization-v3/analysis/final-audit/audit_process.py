#!/usr/bin/env python3
"""Read-only bounded audit of v3 measured evidence. Writes derived JSON beside this file.
Does not execute study binaries or inspect private reasoning/auth/session files.
"""
import collections, datetime, hashlib, json, math, random, statistics
from decimal import Decimal
from pathlib import Path
R=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
D=lambda p:json.loads(p.read_text())
H=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
C=lambda x:(json.dumps(x,sort_keys=True,separators=(',',':'))+'\n').encode()
def cnt(xs):return dict(collections.Counter(xs))
def utc(x):return datetime.datetime.fromtimestamp(x,datetime.timezone.utc).isoformat()
audit={'scope':'Bounded authoritative event, source, result and observable workspace-request audit; no private reasoning, credential/auth/session files and no new native execution.', 'inputs':{},'campaigns':{},'endpoint_rows':[], 'findings':[]}
freeze=D(R/'state/freeze.json');report=D(R/'assessment/final/report.json')
for rel in ['state/freeze.json','state/launch/status.json','assessment/final/report.json']:
 audit['inputs'][rel]=H(R/rel)
assert audit['inputs']['state/freeze.json']=='a28a9e9984aa03a1a28c950bfd846e0d179202f719a43982a27c72a69c934178'
assert audit['inputs']['assessment/final/report.json']=='4c0da852efa41ae3440c09a9faf2e6de0797ac1036ebbbdfc052b4f658f66227'
# Independent check of every relative frozen source/config/document file, no runtime credential roots.
changed=[rel for rel,h in freeze['manifest']['files'].items() if H(R/rel)!=h]
audit['frozen_relative_files_checked']=len(freeze['manifest']['files']);audit['changed_frozen_relative_files']=changed
assert not changed
for c in sorted((R/'campaigns').iterdir()):
 s=D(c/'authority/state.json'); t=D(c/'telemetry.json');a=D(c/'authority/anchor.json')
 es=[];prev=None
 for seq,p in enumerate(sorted((c/'authority/events').glob('*.json')),1):
  e=D(p);assert e['sequence']==seq and e['previous']==prev;prev=H(p);es.append(e)
 assert a['count']==len(es) and a['head']==prev and a['state_hash']==hashlib.sha256(C(s)).hexdigest()
 ops={p.parent.name:D(p) for p in (c/'development/operations').glob('*/result.json')}
 dev=[D(p) for p in sorted((c/'development/events').glob('*.json'))]
 assert len([e for e in dev if e['kind']=='operation_finished'])==len(ops)
 requests=[D(p) for p in (c/'workspace-operations').glob('*/request.json')]
 results={p.parent.name:D(p) for p in (c/'workspace-operations').glob('*/result.json')}
 models=[]
 for ag in t['agents']:
  assert ag['state']=='completed' and set(ag['terminal_turn_statuses'].values())=={'completed'}
  m=ag['thread_start_metadata'];want='gpt-6.1-sol' if ag['role'] in ('lead','reviewer') else 'gpt-6-luna'
  assert ag['model']==m['model']==want
  assert ag['effort']==m['reasoningEffort']==('high' if ag['role'] in ('lead','reviewer') else 'xhigh')
  models.append({'id':ag['agent_id'],'role':ag['role'],'model':ag['model'],'effort':ag['effort'],'turns':t['turn_counts'][ag['agent_id']]})
 reviewers={a['agent_id'] for a in t['agents'] if a['role']=='reviewer'}
 claim_checks=[]
 for k,h in s['hypotheses'].items():
  rev=s['reviews'][h['review_id']]; assert rev['kind']=='claim' and rev['hypothesis_id']==k and rev['source_hash']==h['source_hash'] and rev['assessment']=='endorsed' and rev['actor_id'] in reviewers
  ev=[ops[x] for x in rev['evidence_ids'] if x in ops]; own=[o for o in ev if o['actor_id']==rev['actor_id'] and o['source_hash']==h['source_hash']]
  assert {'build','bench','profile'}<=set(o['operation'] for o in own)
  registered=next(e for e in es if e['kind']=='hypothesis_registered' and e['payload']['id']==k)
  source_started=min(e['wall_time'] for e in dev if e['kind']=='operation_started' and e['payload']['source_hash']==h['source_hash'])
  assert registered['time_unix']<source_started
  claim_checks.append({'hypothesis':k,'disposition':h['disposition'],'review':rev['id'],'review_actor':rev['actor_id'],'own_source_bound_operation_kinds':cnt(o['operation'] for o in own),'registration_to_current_source_first_operation_seconds':source_started-registered['time_unix']})
 promotion_checks=[]
 for k,rev in s['reviews'].items():
  if rev['kind']!='nomination':continue
  rec=rev['receipt'];assert rev['promoted'] and all(rev['gates'].values()) and rec['status']=='execution_verified'
  selected=ops[rec['official_comparison_operation_id']]; assert selected['source_hash']==rev['source_hash'] and selected['status']=='pass' and selected['actor_id'] in reviewers
  for kind,ids in rec['selected_build_execution_evidence'].items():
   for oid in ids: assert ops[oid]['status']=='pass' and ops[oid]['operation']==kind and ops[oid]['source_hash']==rev['source_hash']
  promotion_checks.append({'review':k,'nomination':rev['nomination_id'],'source':rev['source_hash'],'selected_comparison':selected['operation_id'],'portfolio':selected['portfolio_speedup'],'reference_source':selected['reference']['source_hash']})
 scope=[]
 for q in requests:
  aa=q['arguments'];ss=json.dumps(aa,sort_keys=True)
  patterns=[x for x in ['assessment/','final-fixtures','final-evaluator','unattended-optimization-v2','FerriSync','.codex','/sessions','/proc','state/freeze','authority/state','owner/','runtime/'] if x in ss]
  others=[f'campaign-{n}' for n in range(1,4) if f'campaign-{n}'!=c.name and f'campaign-{n}' in ss]
  if any('..' in Path(str(aa.get(k,''))).parts for k in ('path','cwd')): patterns.append('parent_path_component')
  if patterns or others:scope.append({'id':q['operation_id'],'patterns':patterns,'other_campaigns':others})
 req_fail=[{'id':q['operation_id'],'actor':q['actor_id'],'tool':q['tool'],'arguments':q['arguments'],'result':{k:v for k,v in results[q['operation_id']].items() if k in ('status','reason','exit_code','error','repair','correctable')}} for q in requests if results[q['operation_id']]['status']!='ok']
 commands=[{'id':q['operation_id'],'actor':q['actor_id'],'role':q['role'],'command':q['arguments']['command'],'cwd':q['arguments'].get('cwd'),'status':results[q['operation_id']]['status'],'exit_code':results[q['operation_id']].get('exit_code')} for q in requests if q['tool']=='study_workspace_exec']
 costs=D(R/'analysis/checkpoints'/f'{c.name}-usage-reanalysis.json'); assert costs['source_telemetry_sha256']==H(c/'telemetry.json')
 seal=s['endpoint']['sealed_unix'];last_usage=max(o.get('observed_unix_seconds',0) for ag in t['agents'] for o in ag['token_usage']['request_observations'])
 ca={'status':s['status'],'authority_events':len(es),'authority_chain_valid':True,'event_types':cnt(e['kind'] for e in es),'hypotheses':cnt(h['disposition'] for h in s['hypotheses'].values()),'hypothesis_reviews':claim_checks,'reviews':cnt(x['kind'] for x in s['reviews'].values()),'promotions':promotion_checks,'queue_status':cnt(q['status'] for q in s['queue'].values()),'closure_status':[x['status'] for x in s['closures'].values()], 'models':models,'agents':len(models),'turns':sum(t['turn_counts'].values()),'native_operations':cnt(o['operation'] for o in ops.values()),'native_operation_status':cnt(o['status'] for o in ops.values()),'native_by_role':{role:cnt(o['operation'] for o in ops.values() if o['role']==role) for role in sorted({o['role'] for o in ops.values()})},'native_outer_seconds':sum(o.get('outer_elapsed_seconds',0) for o in ops.values()),'native_queue_seconds':sum(o.get('queue_seconds',0) for o in ops.values()),'native_failed_operations':[{k:o.get(k) for k in ('operation_id','operation','source_hash','status','summary')} for o in ops.values() if o['status']!='pass'],'benchmark_attempt_numbers':cnt(o.get('measurement_attempt_number') for o in ops.values() if o['operation']=='bench'),'short_scored_batches':sum(len(o.get('scored_under_target_batches',[])) for o in ops.values() if o['operation']=='bench'),'workspace_requests':len(requests),'workspace_tools':cnt(q['tool'] for q in requests),'workspace_status':cnt(x['status'] for x in results.values()),'workspace_failures':req_fail,'workspace_commands':commands,'scope_pattern_matches':scope,'owner_started_unix':s['started_unix'],'host_started_unix':t['started_unix_seconds'],'source_sealed_unix':seal,'owner_to_source_seal_seconds':seal-s['started_unix'],'host_wall_including_closing_cleanup_seconds':t['campaign_wall_seconds'],'host_elapsed_stop_estimate':t['started_unix_seconds']+t['campaign_wall_seconds'],'last_usage_observed_unix':last_usage,'last_usage_seconds_after_source_seal':last_usage-seal,'cleanup':{k:v for k,v in t['cleanup'].items() if k!='tracked_processes'},'workspace_cleanup':t['workspace_cleanup'],'observed_subtotal_interval_usd':costs['observed_subtotal_interval_usd'],'cost_coverage':costs['coverage']}
 command_records=[D(p) for p in (c/'development/operations').glob('**/command.json')]
 assert len({x['process_pid'] for x in command_records})==len(command_records)
 ca['native_command_records']={'count':len(command_records),'elapsed_seconds_sum':sum(x.get('elapsed_seconds',0) for x in command_records),'user_system_cpu_seconds_sum':sum(x.get('user_cpu_seconds',0)+x.get('system_cpu_seconds',0) for x in command_records),'max_recorded_peak_rss_kib':max(x.get('peak_rss_kib',0) for x in command_records)}
 first_registration=min(e['time_unix'] for e in es if e['kind']=='hypothesis_registered')
 baseline_finished=[e for e in dev if e['kind']=='operation_finished' and e['actor']['role']=='measurement' and e['wall_time']<first_registration]
 ca['delegated_baseline_operations_before_first_hypothesis']=len(baseline_finished)
 ca['delegated_baseline_kinds_before_first_hypothesis']=cnt(e['payload'].get('result',e['payload']).get('operation') for e in baseline_finished)
 audit['campaigns'][c.name]=ca
# Independent numeric spot-check all portfolio/family point estimates; bootstrap two diverse endpoints only.
for row in report['rows']:
 p=R/'assessment/final'/row['evidence'];raw=D(p/'raw.json');pairs=collections.defaultdict(dict)
 for x in raw:pairs[(x['family'],x['block'])][x['arm']]=x['driver']['seconds_per_call']
 assert len(pairs)==180 and all(set(v)=={'baseline','candidate'} for v in pairs.values())
 fam={f:[math.log(pairs[(f,b)]['baseline']/pairs[(f,b)]['candidate']) for b in range(30)] for f in sorted({f for f,b in pairs})}
 fs={f:math.exp(statistics.median(v)) for f,v in fam.items()};point=math.exp(statistics.mean(math.log(v) for v in fs.values()))
 assert abs(point-row['speedup'])<1e-12 and all(abs(fs[f]-row['family_speedups'][f])<1e-12 for f in fs)
 result={'campaign':row['campaign_id'],'stratum':row['stratum'],'point':point,'families':fs,'raw_records':len(raw),'point_reproduced':True,'descriptive_one_sided90_lower':row['descriptive_bootstrap']['one_sided_lower_bound']}
 if (row['campaign_id'],row['stratum']) in [('campaign-1','shift'),('campaign-3','transfer')]:
  rng=random.Random(2026100302);samples=[]
  for _ in range(10000):
   idx=rng.choices(range(30),k=30);samples.append(math.exp(statistics.mean(statistics.median(v[i] for i in idx) for v in fam.values())))
  samples.sort();at=.1*(len(samples)-1);j=int(at);bound=samples[j]*(1-(at-j))+samples[j+1]*(at-j)
  assert abs(bound-result['descriptive_one_sided90_lower'])<1e-12; result['bootstrap_spot_reproduced']=True
 audit['endpoint_rows'].append(result)
for e in report['endpoints']:
 c=R/'campaigns'/e['campaign_id'];s=D(c/'authority/state.json')
 assert H(c/'authority/state.json')==e['state_sha256'] and H(c/'authority/anchor.json')==e['anchor_sha256']
 assert s['endpoint']==e['endpoint']
 for f,h in e['source_files'].items():assert H(Path(e['source_directory'])/f)==h
 assert s['endpoint']['source_hash']==s['promotions'][-1]['source_hash']
for op in report['operations']:
 assert op['status']=='pass'
 if op['operation']=='test':assert op['summary']['passed']==op['summary']['planned_cases']==89 and op['summary']['failed']==0
 if op['operation']=='memcheck':assert op['coverage_complete'] and not op['confirmed_memory_error'] and len(op['probe_records'])==6
 if op['operation']=='bench':assert op['measurement_attempt_number']==1 and op['ordinary_command_overlap_audit']['status']=='no_observed_overlap'
audit['final_operations']=cnt(x['operation'] for x in report['operations']);audit['final_started_utc']=utc(report['started_unix']);audit['final_finished_utc']=utc(report['finished_unix'])
audit['observed_subtotal_sum_usd']=[str(sum(Decimal(c['observed_subtotal_interval_usd'][i]) for c in audit['campaigns'].values())) for i in range(2)]
(OUT/'process-audit.json').write_text(json.dumps(audit,indent=2)+'\n')
print(json.dumps({k:v for k,v in audit.items() if k not in ('campaigns','endpoint_rows')},indent=2))
for k,c in audit['campaigns'].items():print(k,{x:c[x] for x in ['agents','turns','hypotheses','reviews','native_operations','native_by_role','native_outer_seconds','workspace_tools','workspace_status','scope_pattern_matches','benchmark_attempt_numbers','short_scored_batches','owner_to_source_seal_seconds','host_wall_including_closing_cleanup_seconds','last_usage_seconds_after_source_seal']})
