"""Synthetic integration only: actual ledgers/dispatch, fake native backend, no inference."""
import asyncio
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from owner.service import OwnerService,OwnerError,summarize_pairs,load
from owner.tools import make_dispatch,combined_specs
from owner.readiness import code_manifest,create_freeze,verify_authorization,REQUIRED_CHECKS
from owner.overlap import CommandIntervals,AuditedBackend
from development.core import IntegrityError,DevelopmentError,Cancelled,file_hash,write_new
from development.native_backend import paired_bootstrap


class FakeBackend:
    def __init__(self):self.ratios=[];self.calls=[]
    def fixtures(self,suite):return [{'id':'public-profile'}]
    def execute(self,kind,ctx,out):
        source=(ctx['source_directory']/'engine.cpp').read_text();self.calls.append((kind,ctx['grant'].actor_id,ctx['request']))
        (out/'stdout.txt').write_text('SYNTHETIC TEST OUTPUT; NOT A STUDY RESULT\n')
        result={'status':'pass','synthetic':True}
        if kind=='build':
            if '#error' in source:return {'status':'candidate_failure','synthetic':True,'summary':'intentional compile error'}
            (out/'candidate.so').write_text('FAKE BINARY '+source);result['library']='candidate.so'
        elif kind=='test' and 'WRONG' in source and not getattr(self,'ignore_wrong',False):return {'status':'candidate_failure','synthetic':True,'confirmed_semantic_failure':True}
        elif kind=='memcheck':result['coverage_complete']=True
        elif kind=='profile':(out/'annotation.txt').write_text('Synthetic profile instructions=10\n')
        elif kind=='bench':
            ratio=self.ratios.pop(0) if self.ratios else 1.2
            pairs={f'family-{k}':[{'baseline':ratio,'candidate':1.0} for _ in range(10)] for k in range(3)}
            write_new(out/'paired.json',pairs);result.update(portfolio_speedup=ratio,family_speedups={k:ratio for k in pairs})
        return result


class OwnerIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        (self.root/'task/seed').mkdir(parents=True);(self.root/'task/seed/engine.cpp').write_text('int engine = 1;\n')
        (self.root/'task/contract').mkdir();(self.root/'task/contract/SPEC.md').write_text('Synthetic contract')
        self.config=load(ROOT/'owner/config.draft.json');self.config['bootstrap_resamples']=100
        self.backend=FakeBackend();self.owner=OwnerService(self.root,self.root/'setup/campaign',self.backend,self.config,setup=True)
        self.owner.bootstrap();self.host=types.SimpleNamespace(agents={},threads={},stopping=False,failure=None,export=lambda:{'synthetic':True})
        self.owner.attach_host(self.host)
        self.lead=self.actor('lead');self.worker=self.actor('implementation');self.reviewer=self.actor('reviewer')
    def tearDown(self):self.tmp.cleanup()
    def actor(self,role):
        aid='agent-'+str(len(self.host.agents)+1);path=self.owner.directory/'scratch'/aid;path.mkdir()
        a=types.SimpleNamespace(agent_id=aid,role=role,parent_id=None if role=='lead' else 'agent-1',thread_id='thread-'+aid,turn_id='turn-1',state='running',spec=types.SimpleNamespace(cwd=path,writable_roots=(path,)))
        self.host.agents[aid]=a;self.host.threads[a.thread_id]=a;return a
    def call(self,actor,method,**args):return self.owner.dispatch(actor,method,args)
    def hypothesis(self):
        return self.call(self.lead,'hypothesis',mechanism='Synthetic mechanism',predictions='ratio >1',against='ratio <=1',metrics='paired ratio',risks='incorrect results',evidence_ids=[])
    def source(self,code):
        candidate=self.call(self.worker,'checkout')['candidate_directory'];Path(candidate,'engine.cpp').write_text(code)
        return self.owner.service_for_agent(self.worker).snapshot(candidate)['source_hash']
    def suite(self,reviewer,source):
        service=self.owner.service_for_agent(reviewer);build=service.run('build',source_hash=source,purpose='official_review')
        for kind in ('test','profile','memcheck','bench'):
            kw={'fixture_id':'public-profile'} if kind=='profile' else {}
            service.run(kind,build_id=build['operation_id'],purpose='official_review',**kw)
        return build,service.review_evidence(build['operation_id'])
    def inspect_suite(self,actor,source,receipt):
        self.call(actor,'inspect',target_kind='source',target_id=source)
        self.call(actor,'inspect',target_kind='evidence',target_id=receipt['execution_evidence']['profile'][0])
    def nomination(self,source):
        h=self.hypothesis();n=self.call(self.lead,'nominate',hypothesis_id=h['id'],source_hash=source,claim='Synthetic speedup',evidence_ids=[])
        self.call(self.reviewer,'review_target',target_kind='nomination',target_id=n['id']);return h,n

    def test_compile_failure_repair_preserves_both_snapshots_and_attempts(self):
        bad=self.source('#error broken\n');s=self.owner.service_for_agent(self.worker)
        failure=s.run('build',source_hash=bad);self.assertEqual(failure['status'],'candidate_failure')
        good=self.source('int repaired = 2;\n');success=s.run('build',source_hash=good)
        self.assertEqual(success['status'],'pass');self.assertNotEqual(bad,good)
        ops=s.index()['operations'];self.assertEqual(len([p for p in ops if p['operation']=='build' and p['actor_id']==self.worker.agent_id]),2)
        self.assertTrue((self.owner.store/'snapshots'/bad/'engine.cpp').exists())
    def test_missing_reviewer_execution_cannot_promote(self):
        source=self.source('int faster=2;\n');h,n=self.nomination(source)
        built=self.owner.service_for_agent(self.worker).run('build',source_hash=source)
        self.call(self.reviewer,'inspect',target_kind='source',target_id=source)
        with self.assertRaises(DevelopmentError):self.call(self.reviewer,'nomination_review',nomination_id=n['id'],build_id=built['operation_id'],recommendation='approve',explanation='Only assertion')
        self.assertEqual(self.owner.state['incumbent']['source_hash'],self.owner.state['seed']['source_hash'])
    def test_independent_exact_hash_promotion_and_seed_trajectory(self):
        source=self.source('int faster=2;\n');h,n=self.nomination(source)
        built,receipt=self.suite(self.reviewer,source);self.inspect_suite(self.reviewer,source,receipt)
        r=self.call(self.reviewer,'nomination_review',nomination_id=n['id'],build_id=built['operation_id'],recommendation='approve',explanation='Synthetic own reruns pass')
        self.assertTrue(r['promoted']);self.assertEqual(self.owner.state['incumbent']['source_hash'],source)
        self.assertEqual(self.owner.state['incumbent']['build_id'],receipt['official_comparison_build_id'])
        self.assertTrue(self.owner.state['trajectories'][0]['reused_first_seed_parent_comparison'])
        second=self.source('int fastest=3;\n');_,n2=self.nomination(second)
        b2,r2=self.suite(self.reviewer,second);self.inspect_suite(self.reviewer,second,r2)
        self.call(self.reviewer,'nomination_review',nomination_id=n2['id'],build_id=b2['operation_id'],recommendation='approve',explanation='Second synthetic improvement')
        trajectory=self.owner.state['trajectories'][-1]
        self.assertFalse(trajectory['reused_first_seed_parent_comparison'])
        ref=load(self.owner.store/'operations'/trajectory['operation_id']/'result.json')['reference']
        self.assertEqual(ref['source_hash'],self.owner.state['seed']['source_hash'])
    def test_nomination_and_plan_cannot_reset_first_comparison(self):
        source=self.source('int maybe=2;\n');h,n=self.nomination(source)
        plan=self.owner.state['review_targets'][self.reviewer.agent_id]
        again=self.call(self.reviewer,'review_target',target_kind='nomination',target_id=n['id'])
        self.assertEqual(again['id'],plan['id'])
        repeat=self.call(self.lead,'nominate',hypothesis_id=h['id'],source_hash=source,claim='Try again',evidence_ids=[])
        self.assertEqual(repeat['id'],n['id']);self.assertTrue(repeat['reused_existing_nomination'])
        replacement=self.actor('reviewer')
        with self.assertRaises(OwnerError):self.call(replacement,'review_target',target_kind='nomination',target_id=n['id'])
        self.backend.ratios=[.95,1.5]
        built,receipt=self.suite(self.reviewer,source)
        s=self.owner.service_for_agent(self.reviewer);s.run('bench',build_id=built['operation_id'],purpose='official_review')
        later=s.review_evidence(built['operation_id']);self.assertEqual(receipt['official_comparison_operation_id'],later['official_comparison_operation_id'])
        self.inspect_suite(self.reviewer,source,later)
        result=self.call(self.reviewer,'nomination_review',nomination_id=n['id'],build_id=built['operation_id'],recommendation='approve',explanation='Second looks better but cannot select it')
        self.assertFalse(result['promoted']);self.assertAlmostEqual(result['summary']['portfolio_speedup'],.95)
    def test_negative_hypothesis_can_close_with_seed_no_fake_promotion(self):
        source=self.owner.state['seed']['source_hash'];h=self.hypothesis();s=self.owner.service_for_agent(self.worker)
        build=s.run('build',source_hash=source);bench=s.run('bench',build_id=build['operation_id'])
        self.call(self.lead,'report_hypothesis',hypothesis_id=h['id'],disposition='contradicted',observations='The synthetic discriminating prediction failed',evidence_ids=[bench['operation_id']],source_hash=source,limits='Fake fixture only')
        self.call(self.reviewer,'review_target',target_kind='hypothesis',target_id=h['id'])
        rb,rr=self.suite(self.reviewer,source);self.inspect_suite(self.reviewer,source,rr)
        profile=rr['execution_evidence']['profile'][0];comparison=rr['execution_evidence']['bench'][0]
        self.call(self.reviewer,'inspect',target_kind='evidence',target_id=comparison)
        self.call(self.reviewer,'claim_review',hypothesis_id=h['id'],assessment='endorsed',evidence_ids=[profile,comparison],explanation='Own synthetic trace contradicts prediction')
        dossier=self.call(self.lead,'propose_closure',uncertainties='Synthetic only; no real scientific inference',branch_dispositions='No changes promoted',reason='Concrete fixture investigation closed')
        self.call(self.reviewer,'review_target',target_kind='closure',target_id=dossier['id'])
        final,receipt=self.suite(self.reviewer,source);self.inspect_suite(self.reviewer,source,receipt)
        self.call(self.reviewer,'inspect',target_kind='closure',target_id=dossier['id'])
        self.worker.state='completed'
        self.call(self.reviewer,'closure_review',closure_id=dossier['id'],decision='endorse',explanation='Fixture dossier complete',endpoint_build_id=final['operation_id'])
        self.assertEqual(self.owner.state['status'],'complete');self.assertEqual(self.owner.state['promotions'],[])
        self.assertEqual(self.owner.state['endpoint']['source_hash'],source)
    def test_failed_fresh_reviewer_test_can_reject_without_fake_success(self):
        source=self.source('int WRONG=2;\n');h,n=self.nomination(source);s=self.owner.service_for_agent(self.reviewer)
        build=s.run('build',source_hash=source,purpose='official_review');failed=s.run('test',build_id=build['operation_id'],purpose='official_review')
        self.call(self.reviewer,'inspect',target_kind='source',target_id=source);self.call(self.reviewer,'inspect',target_kind='evidence',target_id=failed['operation_id'])
        result=self.call(self.reviewer,'nomination_review',nomination_id=n['id'],build_id=build['operation_id'],recommendation='reject',explanation='Own correctness test failed',failed_evidence_ids=[failed['operation_id']])
        self.assertFalse(result['promoted']);self.assertEqual(self.owner.state['nominations'][n['id']]['status'],'rejected')
    def test_build_only_cannot_endorse_performance_claim(self):
        h=self.hypothesis();source=self.owner.state['seed']['source_hash']
        build=self.owner.service_for_agent(self.worker).run('build',source_hash=source)
        self.call(self.lead,'report_hypothesis',hypothesis_id=h['id'],disposition='inconclusive',observations='Only a build was observed',evidence_ids=[build['operation_id']],source_hash=source,limits='Missing actual performance evidence')
        self.call(self.reviewer,'review_target',target_kind='hypothesis',target_id=h['id'])
        own=self.owner.service_for_agent(self.reviewer).run('build',source_hash=source,purpose='official_review')
        self.call(self.reviewer,'inspect',target_kind='source',target_id=source);self.call(self.reviewer,'inspect',target_kind='evidence',target_id=own['operation_id'])
        with self.assertRaises(OwnerError):self.call(self.reviewer,'claim_review',hypothesis_id=h['id'],assessment='endorsed',evidence_ids=[own['operation_id']],explanation='Build alone is insufficient')
    def test_confirmed_negative_correctness_is_valid_empirical_claim(self):
        h=self.call(self.lead,'hypothesis',mechanism='Synthetic corrected code',predictions='Exact results',against='A wrong result',metrics='correctness',risks='WRONG fixture marker',evidence_ids=[],claim_kind='correctness')
        source=self.source('int WRONG=2;\n');worker=self.owner.service_for_agent(self.worker);b=worker.run('build',source_hash=source);f=worker.run('test',build_id=b['operation_id'])
        self.call(self.lead,'report_hypothesis',hypothesis_id=h['id'],disposition='contradicted',observations='Confirmed semantic mismatch',evidence_ids=[f['operation_id']],source_hash=source,limits='Synthetic fixture')
        self.call(self.reviewer,'review_target',target_kind='hypothesis',target_id=h['id']);review=self.owner.service_for_agent(self.reviewer)
        rb=review.run('build',source_hash=source,purpose='official_review');rf=review.run('test',build_id=rb['operation_id'],purpose='official_review')
        self.call(self.reviewer,'inspect',target_kind='source',target_id=source);self.call(self.reviewer,'inspect',target_kind='evidence',target_id=rf['operation_id'])
        result=self.call(self.reviewer,'claim_review',hypothesis_id=h['id'],assessment='endorsed',evidence_ids=[rf['operation_id']],explanation='Independent confirmed failure replicated')
        self.assertEqual(result['assessment'],'endorsed')
    def test_confirmed_official_failure_cannot_be_erased_by_later_pass(self):
        source=self.source('int WRONG=2;\n');_,n=self.nomination(source);s=self.owner.service_for_agent(self.reviewer)
        b=s.run('build',source_hash=source,purpose='official_review');f=s.run('test',build_id=b['operation_id'],purpose='official_review')
        self.backend.ignore_wrong=True
        s.run('test',build_id=b['operation_id'],purpose='official_review')
        self.call(self.reviewer,'inspect',target_kind='source',target_id=source)
        self.call(self.reviewer,'inspect',target_kind='evidence',target_id=f['operation_id'])
        result=self.call(self.reviewer,'nomination_review',nomination_id=n['id'],build_id=b['operation_id'],recommendation='approve',explanation='Later pass cannot erase official failure')
        self.assertFalse(result['promoted']);self.assertEqual(result['receipt']['status'],'disqualified')

    def test_source_mutation_detected_and_actor_spoofing_denied(self):
        source=self.source('int exact=2;\n');(self.owner.store/'snapshots'/source/'engine.cpp').write_text('tampered')
        with self.assertRaises(IntegrityError):self.owner.service_for_agent(self.worker).index()
        spoof=types.SimpleNamespace(**vars(self.lead))
        with self.assertRaises(Cancelled):self.call(spoof,'status')
    def test_invalid_journal_recoverable_through_real_dispatch(self):
        dispatch=make_dispatch(self.owner)
        bad=asyncio.run(dispatch(self.lead,'study_owner_journal',{'text':''}))
        self.assertEqual(bad['status'],'request_error');self.assertFalse(self.host.failure)
        good=asyncio.run(dispatch(self.lead,'study_owner_journal',{'text':'Corrected factual synthetic entry'}))
        self.assertEqual(good['status'],'participant_claim');self.assertTrue(self.owner.state['rejected_requests'])
    def test_shared_bootstrap_exactly_matches_native(self):
        pairs={'a':[{'baseline':v,'candidate':1.0} for v in (1,1.2,1.3,.9,1.05,1.07,.99,1.2,1.1,1.3)]}
        a=summarize_pairs(pairs,resamples=100,seed=42);b=paired_bootstrap(pairs,100,42,.9)
        self.assertEqual(a['nominal90_lower'],b['one_sided_lower_bound'])
    def test_review_plan_grant_stable_across_turn_but_old_call_revoked(self):
        source=self.source('int fast=2;\n');_,n=self.nomination(source)
        service=self.owner.service_for_agent(self.reviewer);old=service.grant();self.reviewer.turn_id='turn-2'
        new=self.owner.service_for_agent(self.reviewer).grant()
        self.assertEqual(old.job_id,new.job_id);self.assertEqual(old.authority_record_sha256,new.authority_record_sha256)
        with self.assertRaises(Cancelled):service.grant()


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        for p in ('owner','runtime','development','task','tools','protocol','evaluation','state','setup'):(self.root/p).mkdir()
        for p in ('owner','runtime','development','task','tools','protocol','evaluation'):(self.root/p/'marker.txt').write_text(p)
        shutil.copy(ROOT/'owner/config.draft.json',self.root/'owner/config.draft.json')
    def tearDown(self):self.tmp.cleanup()
    def ready(self):
        evidence=self.root/'setup/control.json';write_new(evidence,{'synthetic':True})
        item={'status':'pass','path':'setup/control.json','sha256':file_hash(evidence)}
        readiness={'status':'ready','campaign_count':3,'checks':{k:item for k in REQUIRED_CHECKS},'final_evaluator_manifest':item}
        ready=self.root/'state/readiness.json';write_new(ready,readiness)
        preflight=self.root/'setup/preflight.json';write_new(preflight,{'status':'pass','real_runtime_observed':True,'execution_manifest':code_manifest(self.root),'synthetic_test_only':True})
        with patch('owner.readiness.freeze_runtime_artifacts',return_value={str(evidence):file_hash(evidence)}):
            freeze=create_freeze(self.root,ready,preflight)
        authorization=self.root/'state/authorization.json';write_new(authorization,{'authorized':True,'action':'launch_three_fresh_campaigns','freeze_sha256':freeze['freeze_sha256'],'readiness_sha256':file_hash(ready),'preflight_sha256':file_hash(preflight)})
        return authorization
    def test_exact_gate_and_drift_failure(self):
        auth=self.ready();verify_authorization(self.root,auth)
        (self.root/'owner/marker.txt').write_text('drift')
        with self.assertRaises(IntegrityError):verify_authorization(self.root,auth)
    def test_final_deployment_path_bound_not_cwd_guess(self):
        manifest=code_manifest(ROOT);self.assertEqual(manifest['root'],str(ROOT))
        self.assertTrue(str(ROOT).endswith('/interno-study/experiments/unattended-optimization-v3'))
        self.assertIn('tools/study-v3',manifest['files'])
    def test_missing_final_evaluator_readiness_cannot_freeze(self):
        ready=self.root/'state/bad.json';write_new(ready,{'status':'ready','campaign_count':3,'checks':{}})
        preflight=self.root/'setup/p.json';write_new(preflight,{'status':'pass','real_runtime_observed':True,'execution_manifest':code_manifest(self.root)})
        with self.assertRaises(IntegrityError):create_freeze(self.root,ready,preflight)


class OverlapTests(unittest.TestCase):
    def test_ordinary_command_invalidates_official_timing(self):
        intervals=CommandIntervals()
        class Backend:
            def execute(self,kind,ctx,out):
                intervals.event({'method':'item/started','params':{'threadId':'worker','item':{'id':'shell','type':'commandExecution'}}})
                return {'status':'pass','synthetic':True}
        with tempfile.TemporaryDirectory() as tmp:
            result=AuditedBackend(Backend(),intervals).execute('bench',{},Path(tmp))
            self.assertEqual(result['status'],'infra_error');self.assertEqual(result['measurement_invalidated'],'competing_study_command_execution')
            self.assertTrue((Path(tmp)/'ordinary-command-overlap.json').exists())


if __name__=='__main__':unittest.main(verbosity=2)
