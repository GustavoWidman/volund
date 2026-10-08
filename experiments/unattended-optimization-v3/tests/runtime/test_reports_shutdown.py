from __future__ import annotations
import asyncio
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from runtime.contracts import REPORT_SCHEMA, Safeguards, RuntimeFailure, dynamic_tools, dynamic_argument_issues
from runtime.multiagent import Host
from runtime.transport import StdioRPC
from test_runtime import FakeRPC, roles_at


class ReportAndToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.rpc=FakeRPC();self.host=Host(self.rpc,roles_at(self.base),Safeguards(),self.base/'evidence')
        self.lead=(await self.host.spawn('lead','fixture'))['agent_id']

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def call(self,name,args,call_id='fixture'):
        lead=self.host.agents[self.lead]
        result=await self.host.on_request({'threadId':lead.thread_id,'turnId':lead.turn_id,
            'namespace':None,'callId':call_id,'tool':name,'arguments':args})
        return result['success'],json.loads(result['contentItems'][0]['text'])

    def test_actual_reports_match_model_schema_and_keep_findings(self):
        import jsonschema
        for role in ('implementation','reviewer'):
            report=json.loads((Path(__file__).parent/f'fixtures/rejected-{role}-report.json').read_text())['report']
            jsonschema.Draft7Validator(REPORT_SCHEMA).validate(report)
            with patch.object(Path,'resolve',side_effect=AssertionError('must not dereference references')):
                self.host._report(self.host.agents[self.lead],json.dumps(report))
            status=self.host.status(self.lead)
            self.assertEqual(status['report'],report)
            self.assertTrue(status['report_diagnostics']['schema_valid'])
            self.assertTrue(all(not row['verified'] and not row['dereferenced']
                                for row in status['report_diagnostics']['artifact_references']))

    def test_no_hidden_total_json_byte_limit(self):
        report={'summary':'fixture','artifacts':['description: '+'x'*17000],'checks':[],'limitations':[]}
        self.host._report(self.host.agents[self.lead],json.dumps(report))
        self.assertEqual(self.host.status(self.lead)['report'],report)
        self.assertTrue(self.host.status(self.lead)['report_diagnostics']['schema_valid'])

    def test_partial_summary_and_schema_diagnostics_retained_without_unknown_fields(self):
        report={'summary':'Useful ordinary finding','artifacts':['id']*21,'checks':[17,'checked'],
                'limitations':[],'private_reasoning':'DO_NOT_EXPORT'}
        self.host._report(self.host.agents[self.lead],json.dumps(report))
        status=self.host.status(self.lead)
        self.assertEqual(status['report']['summary'],report['summary'])
        self.assertFalse(status['report_diagnostics']['schema_valid'])
        self.assertEqual(len(status['report']['artifacts']),20)
        evidence=(self.base/'evidence/agent-1.jsonl').read_text()
        self.assertNotIn('DO_NOT_EXPORT',evidence)
        self.assertIn('checks_contains_non_string',evidence)
        self.host._report(self.host.agents[self.lead],json.dumps({'summary':'repaired','artifacts':[],'checks':[],'limitations':[]}))
        self.assertNotIn('invalid_compact_report',self.host.status(self.lead)['issues'])

    def test_unparsed_ordinary_final_findings_remain_in_evidence(self):
        self.host._report(self.host.agents[self.lead],'Observed measurement, ordinary final text')
        self.assertEqual(self.host.status(self.lead)['report']['summary'],'Observed measurement, ordinary final text')
        self.assertEqual(self.host.status(self.lead)['report_diagnostics']['parse_issues'],['invalid_json'])
        self.assertIn('agentReportUnparsedText',(self.base/'evidence/agent-1.jsonl').read_text())

    async def test_invalid_arguments_return_schema_and_repair_without_side_effects(self):
        child=(await self.host.spawn('reviewer','fixture',self.lead))['agent_id']
        cases=[('study_spawn',{'role':'lead','task':'x'}),('study_spawn',{'role':'measurement','task':'  '}),
               ('study_spawn',{'role':'measurement','task':'x'*16001}),
               ('study_status',{'agent_ids':[child]*21}),('study_status',{'agent_ids':[]}),
               ('study_status',{'agent_ids':[{}]}),('study_status',{'agent_ids':[child],'actor':'fake'}),
               ('study_wait',{'agent_ids':[child],'timeout_seconds':True}),
               ('study_wait',{'agent_ids':[child],'timeout_seconds':float('nan')}),
               ('study_wait',{'agent_ids':[child],'timeout_seconds':61}),
               ('study_message',{'agent_id':child,'task':None}),('study_cancel',{})]
        for index,(tool,args) in enumerate(cases):
            before=len(self.rpc.calls)
            success,reply=await self.call(tool,args,str(index))
            self.assertFalse(success)
            self.assertEqual(reply['error'],'invalid_dynamic_arguments')
            self.assertTrue(reply['argument_issues'])
            self.assertEqual(reply['expected_arguments'],next(t['inputSchema'] for t in dynamic_tools() if t['name']==tool))
            self.assertEqual(reply['owned_child_agents'][0]['agent_id'],child)
            self.assertEqual(len(self.rpc.calls),before)

    async def test_permissions_and_startup_failure_repair_are_explicit(self):
        success,reply=await self.call('study_status',{'agent_ids':[self.lead]})
        self.assertFalse(success);self.assertEqual(reply['error'],'unowned_agent')
        child=(await self.host.spawn('reviewer','fixture',self.lead))['agent_id']
        agent=self.host.agents[child];agent.state='startup_failed';agent.thread_id=None
        before=len(self.rpc.calls)
        success,reply=await self.call('study_message',{'agent_id':child,'task':'clarify'},'no-thread')
        self.assertFalse(success)
        self.assertEqual(reply['error'],'child_has_no_resumable_thread_spawn_replacement')
        self.assertEqual(len(self.rpc.calls),before)

    def test_model_tool_schemas_and_local_validation_agree(self):
        import jsonschema
        samples={'study_spawn':{'role':'reviewer','task':'clarify'},'study_status':{'agent_ids':['agent-2']},
                 'study_wait':{'agent_ids':['agent-2'],'timeout_seconds':60},
                 'study_message':{'agent_id':'agent-2','task':'clarify'},'study_cancel':{'agent_id':'agent-2'}}
        for tool in dynamic_tools():
            jsonschema.Draft7Validator(tool['inputSchema']).validate(samples[tool['name']])
            self.assertFalse(dynamic_argument_issues(tool['name'],samples[tool['name']]))


class ShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def run_case(self,*flags,grace=.25,cancel_close=False):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);rpc=StdioRPC([sys.executable,str(Path(__file__).with_name('fake_shutdown_server.py')),*flags],base,request_timeout=2)
            host=Host(rpc,roles_at(base),Safeguards(shutdown_grace_seconds=grace),base/'evidence')
            await rpc.open()
            try:
                await host.initialize()
                lead=(await host.spawn('lead','fixture'))['agent_id']
                await host.spawn('measurement','fixture',lead)
                await host.spawn('reviewer','fixture',lead)
                stop=await host.stop('operator_signal_SIGTERM')
                if '--delay-interrupt-ack' in flags:
                    await asyncio.sleep(.15)
                if cancel_close:
                    closing=asyncio.create_task(rpc.close());await asyncio.sleep(.02)
                    closing.cancel();cleanup=await closing
                else:
                    cleanup=await rpc.close()
                second=await rpc.close()
                self.assertEqual(cleanup,second)
                return host.export(),cleanup,stop,rpc.failure
            finally:
                await rpc.close()

    async def test_active_child_interrupts_and_shutdown_usage_drain(self):
        result,cleanup,stop,failure=await self.run_case()
        self.assertTrue(cleanup['event_stream_drained'])
        self.assertTrue(cleanup['event_processing_complete'])
        self.assertTrue(cleanup['tracked_processes_exited'])
        self.assertTrue(stop['terminal_events_observed'])
        self.assertEqual(result['total_tokens']['totalTokens'],1170)
        self.assertFalse(result['accounting_complete'])
        self.assertTrue(all(a['state']=='interrupted' for a in result['agents']))
        self.assertIsNone(failure)

    async def test_cancelled_rpc_ack_does_not_kill_later_numeric_stream(self):
        result,cleanup,_,failure=await self.run_case('--delay-interrupt-ack')
        self.assertEqual(cleanup['late_rpc_responses_ignored'],3)
        self.assertTrue(cleanup['event_stream_drained'])
        self.assertEqual(result['total_tokens']['totalTokens'],1170)
        self.assertIsNone(failure)

    async def test_close_survives_caller_cancellation_and_stays_incomplete(self):
        result,cleanup,_,failure=await self.run_case('--delay-shutdown',cancel_close=True)
        self.assertTrue(cleanup['event_stream_drained'])
        self.assertTrue(cleanup['cleanup_caller_cancellation_observed'])
        self.assertEqual(failure,'shutdown_caller_cancelled')
        self.assertEqual(result['total_tokens']['totalTokens'],1170)
        self.assertFalse(result['accounting_complete'])

    async def test_missing_partial_usage_stays_unknown_after_successful_drain(self):
        result,cleanup,_,_=await self.run_case('--missing-child-usage')
        self.assertTrue(cleanup['event_stream_drained'])
        self.assertIsNone(result['total_tokens']['totalTokens'])
        child=result['agents'][1]
        self.assertIsNone(child['token_usage']['total'])
        self.assertEqual(child['token_usage']['turns_without_usage'],['turn-1'])

    async def test_processing_error_does_not_drop_subsequent_usage(self):
        result,cleanup,_,failure=await self.run_case('--bad-event-before-usage')
        self.assertTrue(cleanup['event_stream_drained'])
        self.assertFalse(cleanup['event_processing_complete'])
        self.assertEqual(failure,'invalid_terminal_status')
        self.assertEqual(result['total_tokens']['totalTokens'],1170)
        self.assertFalse(result['accounting_complete'])

    async def test_unresponsive_interrupt_uses_cleanup_watchdog_not_admission_timeout(self):
        start=asyncio.get_running_loop().time()
        result,cleanup,stop,_=await self.run_case('--unresponsive-interrupt',grace=.08)
        self.assertLess(asyncio.get_running_loop().time()-start,1.5)
        self.assertTrue(cleanup['event_stream_drained'])
        self.assertFalse(stop['terminal_events_observed'])
        self.assertEqual(len(stop['incomplete_agents']),3)
        self.assertFalse(result['accounting_complete'])

    async def test_already_cancelled_reader_cannot_claim_a_complete_stream(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);rpc=StdioRPC([sys.executable,str(Path(__file__).with_name('fake_shutdown_server.py'))],base,request_timeout=2)
            host=Host(rpc,roles_at(base),Safeguards(shutdown_grace_seconds=.05),base/'evidence')
            await rpc.open()
            try:
                await host.initialize()
                lead=(await host.spawn('lead','fixture'))['agent_id']
                await host.spawn('measurement','fixture',lead)
                observed=host.export()['total_tokens']['totalTokens']
                rpc.reader.cancel();await asyncio.gather(rpc.reader,return_exceptions=True)
                await host.stop('operator_signal_SIGTERM')
                cleanup=await rpc.close()
                result=host.export()
                self.assertTrue(cleanup['tracked_processes_exited'])
                self.assertFalse(cleanup['event_stream_drained'])
                self.assertFalse(cleanup['event_processing_complete'])
                self.assertEqual(result['total_tokens']['totalTokens'],observed)
                self.assertFalse(result['accounting_complete'])
                self.assertEqual(rpc.failure,'protocol_reader_cancelled')
            finally:
                await rpc.close()


if __name__=='__main__':unittest.main()
