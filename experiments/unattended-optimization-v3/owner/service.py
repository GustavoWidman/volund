"""Thread-bound authoritative research ledger and exact-source promotion gates."""
from __future__ import annotations
import dataclasses
import difflib
import hashlib
import json
import math
import random
import shutil
import statistics
import threading
import time
import uuid
from pathlib import Path
from development.core import (ActorGrant, ReferenceLibrary, DevelopmentService, DevelopmentError,
                              IntegrityError, Cancelled, Limits, bounded_lock, encoded, digest, file_hash, tree, write_new)
from development.native_backend import paired_bootstrap
from .public_api import allowed_value


class OwnerError(ValueError):
    """A correctable request error, never automatically a campaign integrity stop."""


def load(path):
    return json.loads(Path(path).read_text())


def replace_json(path, value):
    temp=Path(path).with_suffix('.tmp')
    with temp.open('wb') as f:f.write(encoded(value));f.flush()
    temp.replace(path)


def text(value, name='text'):
    if not isinstance(value,str) or not value.strip():raise OwnerError('nonempty '+name+' required')
    return value


def summarize_pairs(pairs, *, resamples=10000, seed=2026100302):
    if not isinstance(pairs,dict) or not pairs:raise IntegrityError('empty paired evidence')
    logs={}
    for family, rows in pairs.items():
        values=[]
        for row in rows:
            a,b=row['baseline'],row['candidate']
            if type(a) not in (int,float) or type(b) not in (int,float) or not math.isfinite(a+b) or min(a,b)<=0:
                raise IntegrityError('invalid paired timing')
            values.append(math.log(a/b))
        logs[family]=values
    sizes={len(v) for v in logs.values()}
    if len(sizes)!=1 or min(sizes)<2:raise IntegrityError('incomplete temporal blocks')
    n=next(iter(sizes));families={k:math.exp(statistics.median(v)) for k,v in logs.items()}
    ratio=math.exp(statistics.mean(statistics.median(v) for v in logs.values()))
    bound=paired_bootstrap(pairs,resamples,seed,.90)['one_sided_lower_bound']
    return {'portfolio_speedup':ratio,'family_speedups':families,'nominal90_lower':bound,
            'blocks':n,'bootstrap_resamples':resamples,'bootstrap_seed':seed,
            'method':'equal-family geometric mean of median paired log ratios; joint complete-block percentile bootstrap'}


class BoundAuthority:
    def __init__(self,owner,grant,agent=None):
        self.owner,self.current,self.agent=owner,grant,agent
        self.bound_turn=agent.turn_id if agent else None
    def active_grant(self):
        if self.agent is not None:
            self.owner.validate_actor(self.agent)
            if self.agent.turn_id!=self.bound_turn:raise Cancelled('originating tool turn changed')
        if self.owner.cancelled or (self.owner.host and self.owner.host.stopping):raise Cancelled('owner cancelled campaign')
        return self.current
    def expected_head(self,key):
        with self.owner.head_lock:return load(self.owner.private/'development-heads.json').get(key)
    def commit_head(self,key,old,new):
        with self.owner.head_lock:
            heads=load(self.owner.private/'development-heads.json')
            if heads.get(key)!=old:raise IntegrityError('development head changed')
            heads[key]=new;replace_json(self.owner.private/'development-heads.json',heads)


class OwnerService:
    """Authoritative state stays outside all participant write roots.

    Participants can inspect evidence, but only thread-bound dynamic tools append
    history and request transitions. This is audited workflow isolation, not an OS
    hostile-read sandbox. Existing campaign directories are never silently resumed.
    """
    def __init__(self,root,campaign_directory,backend,config, *, setup=False):
        self.root=Path(root).resolve(strict=True);self.directory=Path(campaign_directory).resolve()
        self.directory.mkdir(parents=True,exist_ok=False)
        self.private=self.directory/'authority';self.private.mkdir()
        (self.private/'events').mkdir();(self.private/'checkpoint-usage').mkdir();(self.directory/'scratch').mkdir()
        self.store=self.directory/'development';self.backend,self.config=backend,dict(config)
        self.lock=threading.RLock();self.head_lock=threading.RLock();self.host=None;self.cancelled=False
        self.boot_id=uuid.uuid4().hex;self.setup=setup
        write_new(self.private/'development-heads.json',{})
        self._public_views=({}, {})
        self._profile_ids=([x['id'] for x in backend.fixtures('profile')]
                           if hasattr(backend,'fixtures') else ['test-profile'])
        self.state={'schema_version':3,'campaign_id':self.directory.name,'stage':'setup' if setup else 'measured',
                    'status':'initializing','started_unix':time.time(),'seed':None,'incumbent':None,
                    'hypotheses':{},'queue':{},'nominations':{},'reviews':{},'review_targets':{},
                    'inspections':{},'closures':{},'promotions':[],'trajectories':[],'journal':[]}
        write_new(self.private/'anchor.json',{'count':0,'head':None,'state_hash':digest(encoded(self.state))})
        write_new(self.private/'state.json',self.state)
        self._append('initialized',{'setup':setup})

    def attach_host(self,host):self.host=host

    def validate_actor(self,agent):
        if (self.cancelled or self.host is None or self.host.agents.get(agent.agent_id) is not agent or
            not agent.thread_id or self.host.threads.get(agent.thread_id) is not agent or
            not agent.turn_id or agent.state not in ('running','starting') or self.host.stopping):
            raise Cancelled('runtime actor is not active')
        return agent

    def _audit(self):
        anchor=load(self.private/'anchor.json');head=None;count=0
        for count,path in enumerate(sorted((self.private/'events').iterdir()),1):
            if path.name!=f'{count:08d}.json' or path.is_symlink():raise IntegrityError('owner event sequence changed')
            record=load(path)
            if record['previous']!=head or record['sequence']!=count:raise IntegrityError('owner chain changed')
            head=file_hash(path)
        if count!=anchor['count'] or head!=anchor['head']:raise IntegrityError('owner anchored head changed')
        if digest(encoded(load(self.private/'state.json')))!=anchor['state_hash']:raise IntegrityError('owner projection changed')
        if digest(encoded(self.state))!=anchor['state_hash']:raise IntegrityError('owner memory projection mismatch')

    def _append(self,kind,payload,agent=None):
        self._audit();anchor=load(self.private/'anchor.json');n=anchor['count']+1
        record={'sequence':n,'previous':anchor['head'],'kind':kind,'payload':payload,'time_unix':time.time(),
                'actor_id':agent.agent_id if agent else 'owner','thread_id':agent.thread_id if agent else None,
                'turn_id':agent.turn_id if agent else None,'role':agent.role if agent else 'owner',
                'state_hash':digest(encoded(self.state))}
        path=self.private/'events'/f'{n:08d}.json';write_new(path,record)
        replace_json(self.private/'state.json',self.state)
        replace_json(self.private/'anchor.json',{'count':n,'head':file_hash(path),'state_hash':record['state_hash']})
        self._refresh_public_views(n,record['state_hash'])
        return {'event_id':f'owner-{n:08d}','event_sha256':file_hash(path)}

    def _change(self,kind,payload,agent=None):
        # Callers validate/audit before mutating state. Persisting a new state uses
        # the unchanged on-disk anchor as its predecessor.
        anchor=load(self.private/'anchor.json');n=anchor['count']+1
        record={'sequence':n,'previous':anchor['head'],'kind':kind,'payload':payload,'time_unix':time.time(),
                'actor_id':agent.agent_id if agent else 'owner','thread_id':agent.thread_id if agent else None,
                'turn_id':agent.turn_id if agent else None,'role':agent.role if agent else 'owner',
                'state_hash':digest(encoded(self.state))}
        path=self.private/'events'/f'{n:08d}.json';write_new(path,record)
        replace_json(self.private/'state.json',self.state)
        replace_json(self.private/'anchor.json',{'count':n,'head':file_hash(path),'state_hash':record['state_hash']})
        self._refresh_public_views(n,record['state_hash'])
        return {'event_id':f'owner-{n:08d}','event_sha256':file_hash(path)}

    def _refresh_public_views(self,sequence,state_hash):
        """Publish one immutable read snapshot after an authoritative transition.

        A status request never waits for the long execution/metadata lock and
        never copies token histories or raw benchmark evidence into context.
        Detailed factual records remain available by selective history reads.
        """
        history=json.loads(json.dumps(self.state))
        def short(row,fields):
            return {key:(value[:240]+'…' if isinstance(value,str) and len(value)>240 else value)
                    for key in fields if (value:=row.get(key)) is not None}
        def selected(name,fields,active):
            collection=history.get(name,{})
            rows=list(collection.values()) if isinstance(collection,dict) else list(collection)
            ordered=[r for r in rows if active(r)]+[r for r in reversed(rows) if not active(r)]
            return [short(r,fields) for r in ordered[:20]],max(0,len(rows)-20)
        hypotheses,more_h=selected('hypotheses',('id','source_hash','disposition','review_id','mechanism'),
                                    lambda r:r.get('disposition')=='open' or not r.get('review_id'))
        queue,more_q=selected('queue',('id','status','experiment','decision_impact'),lambda r:r.get('status')=='actionable')
        nominations,more_n=selected('nominations',('id','source_hash','status','hypothesis_id','review_id'),
                                     lambda r:r.get('status') in ('pending','needs_work'))
        reviews,_=selected('reviews',('id','nomination_id','hypothesis_id','assessment','promoted','recommendation','decision'),lambda r:False)
        closures,_=selected('closures',('id','source_hash','status','reason'),lambda r:r.get('status')!='endorsed')
        summary={'schema_version':3,'campaign_id':history['campaign_id'],'stage':history['stage'],
                 'status':history['status'],'as_of_event':sequence,'state_sha256':state_hash,
                 'seed':history.get('seed'),'incumbent':history.get('incumbent'),'endpoint':history.get('endpoint'),
                 'hypotheses':hypotheses,'queue':queue,'nominations':nominations,'recent_reviews':reviews[:5],
                 'closures':closures,'counts':{k:len(history.get(k,{})) for k in
                    ('hypotheses','queue','nominations','reviews','promotions','trajectories','journal')},
                 'omitted_summary_records':{'hypotheses':more_h,'queue':more_q,'nominations':more_n},
                 'history_tool':'study_owner_history: select collection, optional record_id, offset and limit',
                 'public_profile_ids':self._profile_ids,'task_contract':str(self.root/'task/contract/SPEC.md'),
                 'full_journal_directory':str(self.private/'events'),'development_store':str(self.store),
                 'no_research_time_or_token_caps':True,
                 'recent_journal':[short(r,('id','text','corrects')) for r in history.get('journal',[])[-5:]],
                 'recent_trajectories':[{'source_hash':r['source_hash'],'operation_id':r['operation_id'],'status':r['status'],
                    'portfolio_speedup':r.get('summary',{}).get('portfolio_speedup'),
                    'usage_evidence':r.get('usage_evidence')} for r in history.get('trajectories',[])[-5:]]}
        self._public_views=(summary,history)

    def _role(self,agent,*roles):
        self.validate_actor(agent)
        if agent.role not in roles:raise OwnerError('role not authorized for this transition')

    def grant(self,agent=None,*,override=None,review=None):
        if agent:self.validate_actor(agent)
        baseline=override or self.state['incumbent'] or {'source_hash':'uninitialized','library_sha256':'uninitialized','library_path':'/not-used-before-build'}
        review=review or (self.state['review_targets'].get(agent.agent_id) if agent else None)
        if review:baseline=review['baseline']
        seed=self.state['seed'];refs=() if not seed else (ReferenceLibrary('seed',seed['source_hash'],seed['library_sha256'],seed['library_path']),)
        job=(agent.thread_id+':review:'+review['id']) if agent and review else ((agent.thread_id+':'+agent.turn_id) if agent else 'owner-'+uuid.uuid4().hex)
        binding={'actor':agent.agent_id if agent else 'owner','thread':agent.thread_id if agent else None,
                 'job':job,'role':agent.role if agent else 'owner',
                 'baseline':baseline,'review_plan':review['id'] if review else None}
        return ActorGrant(self.directory.name,binding['actor'],job,
                agent.parent_id if agent else None,binding['role'],digest(encoded(binding)),self.boot_id,
                tuple(str(p) for p in agent.spec.writable_roots) if agent else (str(self.root/'task/seed'),),
                baseline['source_hash'],baseline['library_sha256'],baseline['library_path'],refs,
                review['id'] if review else None,review['source_hash'] if review else None,'inherited')

    def service_for_agent(self,agent):
        if self.state['status']=='complete':raise OwnerError('campaign complete; no new development execution')
        grant=self.grant(agent)
        return DevelopmentService(self.store,BoundAuthority(self,grant,agent),self.backend,
                                  Limits(10*1024**2,128*1024,str(self.root/'state/native.lock')))

    def owner_service(self,*,override=None):
        return DevelopmentService(self.store,BoundAuthority(self,self.grant(override=override)),self.backend,
                                  Limits(10*1024**2,128*1024,str(self.root/'state/native.lock')))

    def bootstrap(self):
        with self.lock:
            self._audit();service=self.owner_service();source=service.snapshot(self.root/'task/seed')['source_hash']
            built=service.run('build',source_hash=source)
            if built['status']!='pass':raise IntegrityError('fixed seed bootstrap build failed')
            tested=service.run('test',build_id=built['operation_id'])
            if tested['status']!='pass':raise IntegrityError('fixed seed bootstrap correctness failed')
            endpoint={'source_hash':source,'build_id':built['operation_id'],'library_sha256':built['library_sha256'],
                      'library_path':str(self.store/'operations'/built['operation_id']/built['library']),'review_id':None}
            self.state.update(seed=endpoint,incumbent=dict(endpoint),status='investigating')
            self._change('seed_verified',{'endpoint':endpoint,'test_id':tested['operation_id']})
            return endpoint

    def records(self,agent=None):
        service=self.service_for_agent(agent) if agent else self.owner_service();g=service.grant()
        with bounded_lock(self.store/'.metadata.lock',g,check_active=lambda:service._recheck(g)):
            return service._audit()

    def evidence(self,ids,agent=None):
        if not isinstance(ids,list) or not all(isinstance(x,str) for x in ids):raise OwnerError('evidence IDs must be a list')
        _,_,ops=self.records(agent)
        if any(x not in ops for x in ids):raise OwnerError('unknown evidence ID')
        return [ops[x] for x in ids]

    def status(self,agent):
        self.validate_actor(agent)
        result=json.loads(json.dumps(self._public_views[0]))
        result.update(scratch_directory=str(agent.spec.cwd),benchmark_reference_ids=['inherited','seed'],
                      official_review_reference_id='inherited')
        coordinator=getattr(self.backend,'coordinator',None)
        if coordinator:result['execution_lane']=coordinator.snapshot()
        if self.host:
            result['active_work']=[{'agent_id':a.agent_id,'role':a.role,'state':a.state}
                                   for a in list(self.host.agents.values()) if a.state not in ('completed','interrupted','cancelled','failed')]
        return result

    def history(self,agent,collection,record_id=None,offset=0,limit=5):
        self.validate_actor(agent);allowed_value('history','collection',collection)
        if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=20:
            raise OwnerError('history requires offset>=0 and limit from 1 to 20; additional pages remain available')
        view,history=self._public_views
        collection_value=history[collection]
        rows=list(collection_value.values()) if isinstance(collection_value,dict) else list(collection_value)
        if record_id is not None:
            rows=[row for row in rows if row.get('id')==record_id]
            if not rows:raise OwnerError('record_id does not exist in selected collection')
        selected=rows[offset:offset+limit]
        # Telemetry is separately persisted, never returned implicitly here.
        selected=[{k:v for k,v in row.items() if k!='observed_role_usage'} for row in selected]
        return {'collection':collection,'records':json.loads(json.dumps(selected)),
                'total_records':len(rows),'next_offset':offset+limit if offset+limit<len(rows) else None,
                'as_of_event':view['as_of_event'],'state_sha256':view['state_sha256']}

    def checkout(self,agent,source_hash=None):
        self.validate_actor(agent);self._audit();source_hash=source_hash or self.state['incumbent']['source_hash']
        _,snapshots,_=self.records(agent)
        if source_hash not in snapshots:raise OwnerError('unknown source hash')
        destination=agent.spec.cwd/('candidate-'+uuid.uuid4().hex[:10])
        shutil.copytree(self.store/'snapshots'/source_hash,destination)
        self._append('checkout',{'source_hash':source_hash,'path':str(destination)},agent)
        return {'source_hash':source_hash,'candidate_directory':str(destination),'files':snapshots[source_hash]['files']}

    def journal(self,agent,text,evidence_ids=None,corrects=None):
        self.validate_actor(agent);self._audit();text=globals()['text'](text)
        ids=evidence_ids or [];self.evidence(ids,agent)
        if corrects is not None and corrects not in [x['id'] for x in self.state['journal']]:raise OwnerError('unknown correction target')
        row={'id':'journal-'+str(len(self.state['journal'])+1),'text':text,'evidence_ids':ids,'corrects':corrects,
             'actor_id':agent.agent_id,'source_hash':self.state['incumbent']['source_hash'],'status':'participant_claim'}
        self.state['journal'].append(row);self._change('journal',row,agent);return row

    def hypothesis(self,agent,mechanism,predictions,against,metrics,risks,evidence_ids,exploratory=False,claim_kind='performance'):
        self._role(agent,'lead');self._audit();self.evidence(evidence_ids,agent)
        fields={k:text(v,k) for k,v in locals().copy().items() if k in ('mechanism','predictions','against','metrics','risks')}
        requirements={'performance':['bench','profile'],'correctness':['test'],'profile':['profile'],'resource':['memcheck'],'buildability':['build']}
        allowed_value('hypothesis','claim_kind',claim_kind)
        hid='hypothesis-'+str(len(self.state['hypotheses'])+1)
        row={'id':hid,**fields,'baseline_hash':self.state['incumbent']['source_hash'],'source_hash':self.state['incumbent']['source_hash'],
             'evidence_ids':evidence_ids,'claim_kind':claim_kind,'required_empirical_kinds':requirements[claim_kind],
             'exploratory':bool(exploratory),'disposition':'open','review_id':None,'versions':[]}
        self.state['hypotheses'][hid]=row;self._change('hypothesis_registered',row,agent);return row

    def report_hypothesis(self,agent,hypothesis_id,disposition,observations,evidence_ids,source_hash=None,limits=''):
        self._role(agent,'lead');self._audit()
        allowed_value('report_hypothesis','disposition',disposition)
        row=self.state['hypotheses'].get(hypothesis_id)
        if not row:raise OwnerError('unknown hypothesis')
        observed=self.evidence(evidence_ids,agent)
        if not observed:raise OwnerError('factual report needs executed evidence')
        source_hash=source_hash or row['baseline_hash'];_,snapshots,_=self.records(agent)
        if source_hash not in snapshots:raise OwnerError('unknown source hash')
        if not any(x['source_hash']==source_hash for x in observed):raise OwnerError('report source not bound to evidence')
        report={'disposition':disposition,'observations':text(observations),'evidence_ids':evidence_ids,'source_hash':source_hash,'limits':text(limits or 'No additional limits supplied')}
        row['versions'].append(report);row.update(report,review_id=None)
        self._change('hypothesis_report',{'hypothesis_id':hypothesis_id,**report},agent);return row

    def queue(self,agent,experiment,motivation,observable,decision_impact,queue_id=None,status='actionable',evidence_ids=None):
        self._role(agent,'lead','reviewer');self._audit();ids=evidence_ids or [];self.evidence(ids,agent)
        allowed_value('queue','status',status)
        if agent.role=='reviewer' and status!='actionable':raise OwnerError('reviewer can add concerns; lead records disposition')
        if status!='actionable' and not ids:raise OwnerError('queue disposition requires evidence')
        if queue_id and queue_id not in self.state['queue']:raise OwnerError('unknown queue item')
        qid=queue_id or 'queue-'+str(len(self.state['queue'])+1)
        row={'id':qid,'experiment':text(experiment),'motivation':text(motivation),'observable':text(observable),
             'decision_impact':text(decision_impact),'status':status,'evidence_ids':ids,'actor_id':agent.agent_id}
        self.state['queue'][qid]=row;self._change('queue_updated',row,agent);return row

    def nominate(self,agent,hypothesis_id,source_hash,claim,evidence_ids):
        self._role(agent,'lead');self._audit();self.evidence(evidence_ids,agent)
        if hypothesis_id not in self.state['hypotheses']:raise OwnerError('unknown hypothesis')
        events,snapshots,_=self.records(agent)
        if source_hash not in snapshots:raise OwnerError('unknown immutable source snapshot')
        for existing in self.state['nominations'].values():
            if (existing['source_hash'],existing['parent']['source_hash'])==(source_hash,self.state['incumbent']['source_hash']):
                return {**existing,'reused_existing_nomination':True}
        authors={e['actor']['actor_id'] for e in events if e['kind']=='snapshot' and e['payload']['source_hash']==source_hash and e['actor']['role']!='owner'}
        if any(e['actor']['role']=='reviewer' for e in events if e['kind']=='snapshot' and e['payload']['source_hash']==source_hash):raise OwnerError('reviewer-authored source requires an uncontaminated provenance route')
        nid='nomination-'+str(len(self.state['nominations'])+1)
        row={'id':nid,'hypothesis_id':hypothesis_id,'source_hash':source_hash,'parent':dict(self.state['incumbent']),
             'claim':text(claim),'evidence_ids':evidence_ids,'authors':sorted(authors|{agent.agent_id}),
             'files':snapshots[source_hash]['files'],'status':'pending','review_id':None}
        self.state['nominations'][nid]=row;self._change('nomination',row,agent);return row

    def review_target(self,agent,target_kind,target_id):
        self._role(agent,'reviewer');self._audit()
        if target_kind=='nomination':
            target=self.state['nominations'].get(target_id)
            if not target:raise OwnerError('unknown nomination')
            if agent.agent_id in target['authors']:raise OwnerError('source author cannot review own nomination')
            source,baseline=target['source_hash'],target['parent']
            assigned=target.get('review_plan')
            if assigned:
                if assigned['actor_id']!=agent.agent_id:raise OwnerError('nomination already assigned to an independent reviewer; no comparison reset')
                self.state['review_targets'][agent.agent_id]=assigned
                self._change('review_rebound',assigned,agent)
                return assigned
        elif target_kind=='hypothesis':
            target=self.state['hypotheses'].get(target_id)
            if not target or target['disposition']=='open':raise OwnerError('hypothesis needs factual report')
            source=target['source_hash'];baseline=self.state['incumbent']
        elif target_kind=='closure':
            target=self.state['closures'].get(target_id)
            if not target:raise OwnerError('unknown closure dossier')
            source=target['source_hash'];baseline=self.state['incumbent']
        else:allowed_value('review_target','target_kind',target_kind)
        revision=len(target.get('versions',[])) if target_kind=='hypothesis' else 0
        previous=self.state['review_targets'].get(agent.agent_id)
        if previous and (previous['target_kind'],previous['target_id'],previous['source_hash'],previous.get('target_revision',0))==(target_kind,target_id,source,revision):
            return previous
        row={'id':'review-plan-'+uuid.uuid4().hex,'target_kind':target_kind,'target_id':target_id,
             'source_hash':source,'baseline':dict(baseline),'actor_id':agent.agent_id,'thread_id':agent.thread_id,
             'turn_id':agent.turn_id,'target_revision':revision}
        self.state['review_targets'][agent.agent_id]=row
        if target_kind=='nomination':self.state['nominations'][target_id]['review_plan']=row
        self._change('review_bound',row,agent);return row

    def withdraw_nomination(self,agent,nomination_id,reason,evidence_ids):
        self._role(agent,'lead');self._audit();self.evidence(evidence_ids,agent)
        row=self.state['nominations'].get(nomination_id)
        if not row or row['status'] not in ('pending','needs_work'):raise OwnerError('nomination cannot be withdrawn')
        row.update(status='withdrawn',withdrawal_reason=text(reason),withdrawal_evidence=evidence_ids)
        self._change('nomination_withdrawn',row,agent);return row

    def inspect(self,agent,target_kind,target_id):
        self._role(agent,'reviewer');self._audit();plan=self.state['review_targets'].get(agent.agent_id)
        if not plan:raise OwnerError('bind review target first')
        events,snapshots,ops=self.records(agent);payload={};hashes={}
        if target_kind=='source':
            if target_id!=plan['source_hash']:raise OwnerError('inspection source differs from review plan')
            directory=self.store/'snapshots'/target_id;hashes=tree(directory)
            payload={'files':{name:(directory/name).read_text(errors='replace') for name in hashes},'source_hash':target_id}
        elif target_kind=='evidence':
            op=ops.get(target_id)
            if not op or op['source_hash']!=plan['source_hash']:raise OwnerError('evidence source differs from review plan')
            directory=self.store/'operations'/target_id;hashes=tree(directory)
            excerpts={}
            for name in hashes:
                if name.endswith(('.txt','.json')):
                    raw=(directory/name).read_bytes()
                    if len(raw)<=32768:excerpts[name]=raw.decode(errors='replace')
            payload={'operation':{k:v for k,v in op.items() if k!='files'},'ordinary_outputs':excerpts,
                     'artifact_directory':str(directory),'omitted_large_files':[name for name in hashes if name not in excerpts]}
        elif target_kind=='closure':
            if plan['target_kind']!='closure' or target_id!=plan['target_id']:raise OwnerError('closure target mismatch')
            payload=self.state['closures'][target_id];hashes={'dossier':digest(encoded(payload))}
        else:allowed_value('inspect','target_kind',target_kind)
        iid='inspection-'+str(len(self.state['inspections'])+1)
        receipt={'id':iid,'actor_id':agent.agent_id,'job_id':agent.thread_id+':'+agent.turn_id,'plan_id':plan['id'],
                 'target_kind':target_kind,'target_id':target_id,'hashes':hashes}
        self.state['inspections'][iid]=receipt;self._change('review_inspection',receipt,agent)
        return {'receipt':receipt,'content':payload,'limitation':'Delivery/receipt proves evidence was presented, not human-like comprehension'}

    def _inspected(self,agent,kind,target):
        plan=self.state['review_targets'].get(agent.agent_id)
        return any(r['actor_id']==agent.agent_id and r['plan_id']==plan['id'] and r['target_kind']==kind and r['target_id']==target for r in self.state['inspections'].values())

    def claim_review(self,agent,hypothesis_id,assessment,evidence_ids,explanation):
        self._role(agent,'reviewer');self._audit();plan=self.state['review_targets'].get(agent.agent_id)
        if not plan or (plan['target_kind'],plan['target_id'])!=('hypothesis',hypothesis_id):raise OwnerError('review plan mismatch')
        row=self.state['hypotheses'][hypothesis_id]
        allowed_value('claim_review','assessment',assessment)
        ops=self.evidence(evidence_ids,agent)
        own=[p for p in ops if p['actor_id']==agent.agent_id and p['job_id']==self.grant(agent).job_id and p['source_hash']==plan['source_hash']]
        if not own or not any(self._inspected(agent,'evidence',p['operation_id']) for p in own):raise OwnerError('independent executed and inspected claim evidence required')
        if assessment=='endorsed':
            for kind in row['required_empirical_kinds']:
                matching=[p for p in own if p['operation']==kind and self._inspected(agent,'evidence',p['operation_id'])]
                if not matching:raise OwnerError('claim requires independent executed and inspected '+kind+' evidence')
                valid=lambda p:(p['status']=='pass' or (kind=='test' and p.get('confirmed_semantic_failure') is True) or (kind=='memcheck' and p.get('confirmed_memory_error') is True))
                if kind!='build' and not any(valid(p) for p in matching):raise OwnerError('incomplete measurement does not establish empirical claim; request more work')
        if not self._inspected(agent,'source',plan['source_hash']):raise OwnerError('inspect exact claim source first')
        rid='review-'+str(len(self.state['reviews'])+1)
        review={'id':rid,'kind':'claim','hypothesis_id':hypothesis_id,'source_hash':plan['source_hash'],
                'actor_id':agent.agent_id,'assessment':assessment,'evidence_ids':evidence_ids,'explanation':text(explanation)}
        self.state['reviews'][rid]=review;row['review_id']=rid if assessment=='endorsed' else None
        self._change('claim_review',review,agent);return review

    def nomination_review(self,agent,nomination_id,build_id,recommendation,explanation,failed_evidence_ids=None):
        self._role(agent,'reviewer');self._audit();plan=self.state['review_targets'].get(agent.agent_id)
        if not plan or (plan['target_kind'],plan['target_id'])!=('nomination',nomination_id):raise OwnerError('review plan mismatch')
        n=self.state['nominations'][nomination_id]
        allowed_value('nomination_review','recommendation',recommendation)
        if n['status']!='pending':raise OwnerError('nomination already disposed')
        if not self._inspected(agent,'source',n['source_hash']):raise OwnerError('inspect exact nominated source first')
        if failed_evidence_ids:
            if recommendation=='approve':raise OwnerError('failed execution cannot authorize promotion')
            failed=self.evidence(failed_evidence_ids,agent);grant=self.grant(agent)
            if not failed or any(p['actor_id']!=agent.agent_id or p['job_id']!=grant.job_id or p['source_hash']!=n['source_hash'] or
                                p.get('purpose')!='official_review' or p.get('review_plan_id')!=plan['id'] or p['status']=='pass' for p in failed):
                raise OwnerError('failed review evidence must be own official exact-source execution')
            if not all(self._inspected(agent,'evidence',p['operation_id']) for p in failed):raise OwnerError('inspect failed execution evidence before reviewing')
            rid='review-'+str(len(self.state['reviews'])+1)
            review={'id':rid,'kind':'nomination','nomination_id':nomination_id,'source_hash':n['source_hash'],
                    'actor_id':agent.agent_id,'recommendation':recommendation,'explanation':text(explanation),
                    'failed_execution_evidence':failed_evidence_ids,'promoted':False,'gates':{'complete_successful_execution':False}}
            self.state['reviews'][rid]=review;n.update(review_id=rid,status='needs_work' if recommendation=='needs_work' else 'rejected')
            self._change('nomination_failed_execution_review',review,agent);return review
        receipt=self.service_for_agent(agent).review_evidence(build_id)
        if receipt['source_hash']!=n['source_hash']:raise IntegrityError('review receipt source mismatch')
        if receipt.get('status')=='disqualified':
            rid='review-'+str(len(self.state['reviews'])+1)
            review={'id':rid,'kind':'nomination','nomination_id':nomination_id,'source_hash':n['source_hash'],
                    'actor_id':agent.agent_id,'recommendation':'reject','requested_recommendation':recommendation,
                    'explanation':text(explanation),'receipt':receipt,'promoted':False,
                    'gates':{'confirmed_semantic_or_memory_failure':False}}
            self.state['reviews'][rid]=review;n.update(review_id=rid,status='rejected')
            self._change('nomination_disqualified',review,agent);return review
        profiles=receipt['execution_evidence']['profile']
        if not any(self._inspected(agent,'evidence',p) for p in profiles):raise OwnerError('inspect independent profile evidence first')
        _,_,ops=self.records(agent);comparison=ops[receipt['official_comparison_operation_id']]
        if comparison['source_hash']!=n['source_hash']:raise IntegrityError('comparison source mismatch')
        reference=comparison.get('reference') or {}
        if (reference.get('source_hash'),reference.get('library_sha256')) != (n['parent']['source_hash'],n['parent']['library_sha256']):
            raise IntegrityError('comparison is not bound to nominated parent')
        pairs=load(self.store/'operations'/comparison['operation_id']/'paired.json')
        summary=summarize_pairs(pairs,resamples=self.config['bootstrap_resamples'],seed=self.config['bootstrap_seed'])
        if summary['blocks']!=self.config['development_blocks']:raise IntegrityError('official block count mismatch')
        gates={'portfolio':summary['portfolio_speedup']>=self.config['minimum_portfolio'],
               'lower_bound':summary['nominal90_lower']>self.config['minimum_lower'],
               'family_floor':all(v>=self.config['family_floor'] for v in summary['family_speedups'].values()),
               'parent_current':self.state['incumbent']['source_hash']==n['parent']['source_hash'],
               'changed_source':n['source_hash']!=n['parent']['source_hash']}
        rid='review-'+str(len(self.state['reviews'])+1)
        review={'id':rid,'kind':'nomination','nomination_id':nomination_id,'source_hash':n['source_hash'],
                'actor_id':agent.agent_id,'recommendation':recommendation,'explanation':text(explanation),
                'receipt':receipt,'summary':summary,'gates':gates,'promoted':recommendation=='approve' and all(gates.values())}
        self.state['reviews'][rid]=review;n['review_id']=rid;n['status']='promoted' if review['promoted'] else ('needs_work' if recommendation=='needs_work' else 'rejected')
        if review['promoted']:
            selected_build_id=receipt['official_comparison_build_id'];build=ops[selected_build_id]
            if build['library_sha256']!=receipt['official_comparison_library_sha256']:raise IntegrityError('selected binary identity mismatch')
            self.state['incumbent']={'source_hash':n['source_hash'],'build_id':selected_build_id,'library_sha256':build['library_sha256'],
               'library_path':str(self.store/'operations'/selected_build_id/build['library']),'review_id':rid}
            self.state['promotions'].append({'nomination_id':nomination_id,'review_id':rid,'source_hash':n['source_hash'],'time_unix':time.time()})
        self._change('nomination_review',review,agent)
        if review['promoted']:self._trajectory(comparison,agent)
        return review

    def _trajectory(self,comparison,agent):
        endpoint=self.state['incumbent'];seed=self.state['seed'];promotion=self.state['promotions'][-1]
        nomination=self.state['nominations'][promotion['nomination_id']]
        if nomination['parent']['source_hash']==seed['source_hash']:
            observation=comparison;reuse=True
        else:
            observation=self.owner_service(override=seed).run('bench',build_id=endpoint['build_id'],reference_id='seed')
            reuse=False
        usage_evidence=None
        if self.host:
            usage_path=self.private/'checkpoint-usage'/f"{len(self.state['trajectories'])+1:08d}.json"
            write_new(usage_path,self.host.export())
            usage_evidence={'path':str(usage_path),'sha256':file_hash(usage_path)}
        row={'source_hash':endpoint['source_hash'],'seed_hash':seed['source_hash'],'promotion':promotion,
             'operation_id':observation['operation_id'],'status':observation['status'],'reused_first_seed_parent_comparison':reuse,
             'comparison_completed_unix':time.time(),'usage_evidence':usage_evidence,
             'usage_coordinate_complete':False,'usage_coordinate_note':'Ongoing request usage can arrive after this native comparison; never interpolate missing tokens'}
        if observation['status']=='pass':row['summary']=summarize_pairs(load(self.store/'operations'/observation['operation_id']/'paired.json'),resamples=self.config['bootstrap_resamples'],seed=self.config['bootstrap_seed'])
        self.state['trajectories'].append(row);self._change('seed_relative_trajectory',row)
        if observation['status']!='pass':raise IntegrityError('promoted endpoint trajectory incomplete; no rollback or reselection')

    def propose_closure(self,agent,uncertainties,branch_dispositions,reason):
        self._role(agent,'lead');self._audit()
        if any(h['disposition']=='open' or not h['review_id'] for h in self.state['hypotheses'].values()):raise OwnerError('unreviewed or open hypothesis remains')
        if any(q['status']=='actionable' for q in self.state['queue'].values()):raise OwnerError('actionable investigation remains')
        if any(n['status'] in ('pending','needs_work') for n in self.state['nominations'].values()):raise OwnerError('nomination needs disposition')
        if not self.state['hypotheses']:raise OwnerError('baseline investigation and reviewed factual report required')
        cid='closure-'+str(len(self.state['closures'])+1)
        row={'id':cid,'source_hash':self.state['incumbent']['source_hash'],'hypotheses':json.loads(json.dumps(self.state['hypotheses'])),
             'queue':json.loads(json.dumps(self.state['queue'])),'uncertainties':text(uncertainties),'branch_dispositions':text(branch_dispositions),
             'reason':text(reason),'status':'pending','state_fingerprint':self.closure_fingerprint()}
        self.state['closures'][cid]=row;self._change('closure_proposed',row,agent);return row

    def closure_fingerprint(self):
        return digest(encoded({k:self.state[k] for k in ('incumbent','hypotheses','queue','nominations','promotions','trajectories')}))

    def closure_review(self,agent,closure_id,decision,explanation,endpoint_build_id=None):
        self._role(agent,'reviewer');self._audit();plan=self.state['review_targets'].get(agent.agent_id)
        if not plan or (plan['target_kind'],plan['target_id'])!=('closure',closure_id):raise OwnerError('review plan mismatch')
        row=self.state['closures'][closure_id]
        allowed_value('closure_review','decision',decision)
        if row['state_fingerprint']!=self.closure_fingerprint():raise OwnerError('closure dossier stale')
        if not self._inspected(agent,'closure',closure_id):raise OwnerError('inspect complete closure dossier first')
        receipt=None
        if decision=='endorse':
            if any(a.agent_id!=agent.agent_id and a.role!='lead' and a.state not in ('completed','failed','interrupted','startup_failed') for a in self.host.agents.values()):
                raise OwnerError('execution/review workers still active; await their factual reports before closure')
            if any(q['status']=='actionable' for q in self.state['queue'].values()):raise OwnerError('actionable work remains')
            if self.state['incumbent']['review_id'] is None:
                if not endpoint_build_id:raise OwnerError('unpromoted seed endpoint needs independent full execution review')
                receipt=self.service_for_agent(agent).review_evidence(endpoint_build_id)
                if receipt['source_hash']!=row['source_hash']:raise IntegrityError('closure execution source mismatch')
                if receipt.get('status')=='disqualified':raise OwnerError('Endpoint source is disqualified by confirmed official correctness/memory failure; inspect invalidating_evidence in study_dev_review_evidence. Do not endorse closure: ask the lead to repair through a new source/nomination or stop incomplete.')
                if not any(self._inspected(agent,'evidence',p) for p in receipt['execution_evidence']['profile']):raise OwnerError('inspect closure profile first')
            self.state['status']='complete'
            self.state['endpoint']={**self.state['incumbent'],'closure_id':closure_id,'stopping_reason':'task_complete',
                                    'sealed_unix':time.time(),'final_assessment_released':False}
        row.update(status='endorsed' if decision=='endorse' else 'more_work',reviewer=agent.agent_id,explanation=text(explanation),execution_receipt=receipt)
        self._change('closure_review',row,agent);return row

    def stop(self,reason):
        self.cancelled=True  # Visible to native cancellation checks before waiting for owner.lock.
        with self.lock:
            self._audit();self.state['status']='incomplete';self.state['stop_reason']=reason
            self.state['endpoint']={**(self.state['incumbent'] or {}),'stopping_reason':'incomplete','sealed_unix':time.time(),'final_assessment_released':False}
            self._change('stopped',{'reason':reason})

    def dispatch(self,agent,method,arguments):
        if method in ('status','history'):
            return getattr(self,method)(agent,**arguments)
        with self.lock:
            self.validate_actor(agent);self._audit()
            if self.state['status'] not in ('investigating','complete'):raise OwnerError('workflow not active')
            if self.state['status']=='complete' and method!='status':raise OwnerError('campaign already complete')
            fn=getattr(self,method,None)
            if method not in OWNER_METHODS or fn is None:raise OwnerError('unknown owner tool')
            return json.loads(json.dumps(fn(agent,**arguments)))


OWNER_METHODS=('status','history','checkout','journal','hypothesis','report_hypothesis','queue','nominate','withdraw_nomination','review_target','inspect','claim_review','nomination_review','propose_closure','closure_review')
