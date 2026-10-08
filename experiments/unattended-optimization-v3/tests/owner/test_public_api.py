"""Public-schema-driven integration: real dispatch/ledgers, synthetic native work."""
import asyncio
import inspect
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(Path(__file__).parent))
import test_owner as fixtures
from owner.service import OwnerService
from owner.tools import tool_specs,combined_specs,make_dispatch
from development.core import DevelopmentService


class PublicAPI(unittest.TestCase):
    setUp=fixtures.OwnerIntegration.setUp
    tearDown=fixtures.OwnerIntegration.tearDown
    actor=fixtures.OwnerIntegration.actor
    call=fixtures.OwnerIntegration.call
    hypothesis=fixtures.OwnerIntegration.hypothesis
    source=fixtures.OwnerIntegration.source
    suite=fixtures.OwnerIntegration.suite
    inspect_suite=fixtures.OwnerIntegration.inspect_suite
    nomination=fixtures.OwnerIntegration.nomination

    def invoke(self,actor,name,**payload):
        return asyncio.run(make_dispatch(self.owner)(actor,name,payload))
    def choices(self,actor,name,field):
        return next(s for s in combined_specs(actor.role) if s['name']==name)['inputSchema']['properties'][field]['enum']
    def ok(self,row):
        self.assertNotIn(row.get('status'),('request_error','integrity_stop','cancelled'),row)
        self.assertIsNone(self.host.failure)
        return row
    def claim_context(self):
        source=self.owner.state['seed']['source_hash'];h=self.hypothesis()
        b=self.owner.service_for_agent(self.worker).run('build',source_hash=source)
        self.call(self.lead,'report_hypothesis',hypothesis_id=h['id'],disposition='inconclusive',observations='Synthetic no-change evidence',evidence_ids=[b['operation_id']])
        self.ok(self.invoke(self.reviewer,'study_owner_review_target',target_kind='hypothesis',target_id=h['id']))
        build,receipt=self.suite(self.reviewer,source)
        self.inspect_suite(self.reviewer,source,receipt)
        ids=[receipt['execution_evidence'][k][0] for k in ('profile','bench')]
        self.call(self.reviewer,'inspect',target_kind='evidence',target_id=ids[1])
        return h,ids

    def test_required_fields_types_and_defaults_match_callable_signatures(self):
        for role in ('lead','reviewer','implementation','measurement','investigation'):
            for spec in tool_specs(role):
                name=spec['name'].removeprefix('study_owner_');schema=spec['inputSchema']
                params={k:p for k,p in inspect.signature(getattr(OwnerService,name)).parameters.items() if k not in ('self','agent')}
                self.assertEqual(set(schema['properties']),set(params))
                self.assertEqual(set(schema['required']),{k for k,p in params.items() if p.default is inspect.Parameter.empty})
                for field,rule in schema['properties'].items():
                    self.assertIn('type',rule)
                    if field not in schema['required']:self.assertEqual(rule['default'],params[field].default)
        self.assertEqual(self.choices(self.reviewer,'study_owner_queue','status'),['actionable'])
        self.assertEqual(self.choices(self.worker,'study_dev_build','purpose'),['exploratory'])

    def test_schema_enum_values_round_trip_through_real_handlers(self):
        source=self.owner.state['seed']['source_hash']
        build=self.owner.service_for_agent(self.worker).run('build',source_hash=source)
        for value in self.choices(self.lead,'study_owner_hypothesis','claim_kind'):
            row=self.ok(self.invoke(self.lead,'study_owner_hypothesis',mechanism='Synthetic',predictions='Falsifiable',against='Failure',metrics='Relevant',risks='Unknown',evidence_ids=[],claim_kind=value))
            self.assertEqual(row['claim_kind'],value)
        h=self.hypothesis()
        for value in self.choices(self.lead,'study_owner_report_hypothesis','disposition'):
            row=self.ok(self.invoke(self.lead,'study_owner_report_hypothesis',hypothesis_id=h['id'],disposition=value,observations='Synthetic observation',evidence_ids=[build['operation_id']]))
            self.assertEqual(row['disposition'],value)
        for value in self.choices(self.lead,'study_owner_queue','status'):
            row=self.ok(self.invoke(self.lead,'study_owner_queue',experiment='Synthetic',motivation='Check',observable='Evidence',decision_impact='Resolve',status=value,evidence_ids=[build['operation_id']]))
            self.assertEqual(row['status'],value)

    def test_all_actual_rejected_verdicts_are_repairable_without_lost_review(self):
        h,ids=self.claim_context();before=len(self.owner.state['reviews'])
        fixture=json.loads((ROOT/'tests/owner/fixtures/live-request-errors.json').read_text())
        case=next(c for c in fixture['cases'] if c['field']=='assessment')
        for value in case['rejected_values']:
            row=self.invoke(self.reviewer,case['tool'],hypothesis_id=h['id'],assessment=value,evidence_ids=ids,explanation='Synthetic independent conclusion')
            self.assertEqual(row['status'],'request_error')
            self.assertEqual(row['argument_issues'][0]['allowed_values'],self.choices(self.reviewer,case['tool'],'assessment'))
            self.assertEqual(len(self.owner.state['reviews']),before)
            self.assertIsNone(self.host.failure)
        # Discover accepted labels from the schema, then execute both actual paths.
        for value in reversed(self.choices(self.reviewer,case['tool'],'assessment')):
            row=self.ok(self.invoke(self.reviewer,case['tool'],hypothesis_id=h['id'],assessment=value,evidence_ids=ids,explanation='Own evidence and source inspected'))
            self.assertEqual(row['assessment'],value)
        self.assertIsNotNone(self.owner.state['hypotheses'][h['id']]['review_id'])

    def test_recommendation_schema_round_trips_without_consuming_invalid_nomination(self):
        for number,value in enumerate(self.choices(self.reviewer,'study_owner_nomination_review','recommendation')):
            source=self.source(f'int candidate_{number}=2;\n');_,n=self.nomination(source)
            b,r=self.suite(self.reviewer,source);self.inspect_suite(self.reviewer,source,r)
            bad=self.invoke(self.reviewer,'study_owner_nomination_review',nomination_id=n['id'],build_id=b['operation_id'],recommendation='looks good',explanation='Invalid vocabulary')
            self.assertEqual(bad['status'],'request_error');self.assertEqual(self.owner.state['nominations'][n['id']]['status'],'pending')
            good=self.ok(self.invoke(self.reviewer,'study_owner_nomination_review',nomination_id=n['id'],build_id=b['operation_id'],recommendation=value,explanation='Synthetic complete own suite'))
            self.assertEqual(good['recommendation'],value)

    def test_reference_fixture_path_and_type_typos_recover_without_native_attempts(self):
        service=self.owner.service_for_agent(self.worker);source=self.owner.state['seed']['source_hash']
        b=service.run('build',source_hash=source);before=len(service.index()['operations'])
        for payload in ({'source_hash':source,'purpose':'official_review'},{'source_hash':source,'role':'reviewer'}):
            self.assertEqual(self.invoke(self.worker,'study_dev_build',**payload)['status'],'request_error')
        wrong=self.invoke(self.worker,'study_dev_bench',build_id=b['operation_id'],reference_id=b['operation_id'])
        refs=wrong['argument_issues'][0]['allowed_values'];self.assertIn('inherited',refs)
        wrong_fixture=self.invoke(self.worker,'study_dev_profile',build_id=b['operation_id'],fixture_id='guess')
        fixtures=wrong_fixture['argument_issues'][0]['allowed_values']
        for candidate in (str(self.worker.spec.cwd/'missing'),str(self.root)):
            self.assertEqual(self.invoke(self.worker,'study_dev_snapshot',candidate=candidate)['status'],'request_error')
        checkout=self.call(self.worker,'checkout')['candidate_directory'];Path(checkout,'linked').symlink_to('/dev/null')
        self.assertEqual(self.invoke(self.worker,'study_dev_snapshot',candidate=checkout)['status'],'request_error')
        Path(checkout,'linked').unlink()
        self.assertEqual(len(service.index()['operations']),before)
        self.ok(self.invoke(self.worker,'study_dev_snapshot',candidate=checkout))
        self.ok(self.invoke(self.worker,'study_dev_profile',build_id=b['operation_id'],fixture_id=fixtures[0]))
        self.ok(self.invoke(self.worker,'study_dev_bench',build_id=b['operation_id'],reference_id=refs[0]))
        for field,value in (('source_hash',''),('source_hash','   ')):
            self.assertEqual(self.invoke(self.worker,'study_owner_checkout',**{field:value})['status'],'request_error')
        bad=self.invoke(self.lead,'study_owner_hypothesis',mechanism='x',predictions='x',against='x',metrics='x',risks='x',evidence_ids=[],exploratory='false')
        self.assertEqual(bad['argument_issues'][0]['expected_types'],['boolean'])
        missing=self.invoke(self.reviewer,'study_owner_claim_review',assessment='endorsed')
        self.assertEqual({r['field'] for r in missing['argument_issues']},{'hypothesis_id','evidence_ids','explanation'})
        self.assertIsNone(self.host.failure)

    def test_closure_disqualified_receipt_has_actionable_error_then_continue_is_valid(self):
        h,ids=self.claim_context()
        self.ok(self.invoke(self.reviewer,'study_owner_claim_review',hypothesis_id=h['id'],assessment='endorsed',evidence_ids=ids,explanation='Own checks'))
        dossier=self.call(self.lead,'propose_closure',uncertainties='Synthetic only',branch_dispositions='No promotion',reason='No queue')
        self.ok(self.invoke(self.reviewer,'study_owner_review_target',target_kind='closure',target_id=dossier['id']))
        self.ok(self.invoke(self.reviewer,'study_owner_inspect',target_kind='closure',target_id=dossier['id']))
        service=self.owner.service_for_agent(self.reviewer);b=service.run('build',source_hash=self.owner.state['seed']['source_hash'],purpose='official_review')
        original=self.backend.execute
        self.backend.execute=lambda kind,ctx,out: ({'status':'candidate_failure','confirmed_semantic_failure':True} if kind=='test' else original(kind,ctx,out))
        service.run('test',build_id=b['operation_id'],purpose='official_review')
        self.assertEqual(service.review_evidence(b['operation_id'])['status'],'disqualified')
        self.worker.state='completed'
        rejected=self.invoke(self.reviewer,'study_owner_closure_review',closure_id=dossier['id'],decision='endorse',explanation='Must not close',endpoint_build_id=b['operation_id'])
        self.assertEqual(rejected['status'],'request_error');self.assertIn('disqualified',rejected['error'])
        self.assertEqual(self.owner.state['status'],'investigating')
        row=self.ok(self.invoke(self.reviewer,'study_owner_closure_review',closure_id=dossier['id'],decision='continue',explanation='Repair required'))
        self.assertEqual(row['status'],'more_work')


if __name__=='__main__':unittest.main(verbosity=2)
