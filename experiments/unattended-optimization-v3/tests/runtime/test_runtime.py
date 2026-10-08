from __future__ import annotations
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from runtime.contracts import APPROVED_MODELS, RoleSpec, Safeguards, RuntimeFailure, start_thread_params, sandbox, turn_params, initialize_params
from runtime.multiagent import Host, wait_for_completion
from runtime.telemetry import ThreadUsage, public_item
from runtime.transport import StdioRPC
from runtime.launch import run_manifest


def counts(n=1):
    return {'inputTokens': 100*n, 'cachedInputTokens': 20*n, 'cacheWriteInputTokens': 0,
            'outputTokens': 30*n, 'reasoningOutputTokens': 10*n, 'totalTokens': 130*n}


def usage(n=1):
    return {'total': counts(n), 'last': counts(), 'modelContextWindow': 200000}


def roles_at(base):
    roles = {}
    for role, (model, effort) in APPROVED_MODELS.items():
        path = base / role
        path.mkdir()
        roles[role] = RoleSpec(model, effort, path, (path,), 'Fixture scope only')
    return roles


class FakeRPC:
    failure = None
    def __init__(self):
        self.calls = []
        self.sequence = 0
        self.turns = {}
    async def request(self, method, params):
        self.calls.append((method, params))
        if method == 'thread/start':
            self.sequence += 1
            tid = 'thread-'+str(self.sequence)
            self.turns[tid] = 0
            return {'thread': {'id': tid, 'cliVersion': '0.159.3', 'ephemeral': True},
                    'model': params['model'], 'modelProvider': 'openai',
                    'reasoningEffort': params['config']['model_reasoning_effort'],
                    'approvalPolicy': 'never', 'cwd': params['cwd'],
                    'sandbox': {'type': 'workspaceWrite', 'writableRoots': params['runtimeWorkspaceRoots'],
                        'networkAccess': False, 'excludeTmpdirEnvVar': True, 'excludeSlashTmp': True}}
        if method == 'turn/start':
            tid = params['threadId']; self.turns[tid] += 1
            return {'turn': {'id': 'turn-'+str(self.turns[tid])}}
        return {}
    async def send(self, msg):
        pass


class LedgerTests(unittest.TestCase):
    def test_duplicates_and_multiple_turns_do_not_double_count(self):
        ledger = ThreadUsage()
        ledger.add('a', usage()); ledger.add('a', usage()); ledger.add('b', usage(2))
        result = ledger.export(['a', 'b'], True)
        self.assertEqual(result['total']['totalTokens'], 260)
        self.assertEqual(result['duplicates'], 1)
        self.assertTrue(result['observed_accounting_complete'])

    def test_missing_usage_and_cache_write_are_unknown(self):
        ledger = ThreadUsage()
        row = usage(); del row['total']['cacheWriteInputTokens']; del row['last']['cacheWriteInputTokens']
        ledger.add('a', row)
        self.assertIsNone(ledger.total['cacheWriteInputTokens'])
        self.assertFalse(ledger.export(['a','b'], True)['observed_accounting_complete'])
        self.assertFalse(ledger.export(['a'], True)['provider_billing_completeness_verified'])

    def test_counter_reset_is_not_added_as_new_request(self):
        ledger = ThreadUsage(); ledger.add('a', usage(2)); ledger.add('a', usage())
        self.assertIn('cumulative_counter_regression', ledger.issues)
        self.assertFalse(ledger.export(['a'], True)['observed_accounting_complete'])

    def test_compaction_context_estimate_preserves_cumulative_usage(self):
        ledger = ThreadUsage(); ledger.add('a', usage())
        row = usage(); row['last'] = dict.fromkeys(counts(), 0); row['last']['totalTokens'] = 12345
        ledger.add('a', row)
        self.assertEqual(ledger.total, counts())
        self.assertEqual(ledger.updates[-1]['classification'], 'context_estimate_no_usage_increment')
        self.assertTrue(ledger.export(['a'], True)['observed_accounting_complete'])
        ledger.add('a', usage(2))
        self.assertEqual(ledger.total, counts(2))
        self.assertFalse(ledger.issues)

    def test_capacity_sentinel_is_not_model_usage(self):
        ledger = ThreadUsage(); ledger.add('a', usage())
        row = {k: 0 for k in counts()}; row['totalTokens'] = 200000
        ledger.add('a', {'total': row, 'last': row})
        self.assertEqual(ledger.total, counts())
        self.assertIn('context_capacity_replaced_usage', ledger.issues)
        self.assertFalse(ledger.export(['a'], True)['observed_accounting_complete'])

    def test_previous_turn_duplicate_is_not_new_turn_usage(self):
        ledger=ThreadUsage(); ledger.add('a',usage()); ledger.add('b',usage())
        self.assertEqual(ledger.export(['a','b'],True)['turns_without_usage'],['b'])

    def test_no_private_reasoning_even_unexpected_fields(self):
        self.assertIsNone(public_item({'type':'reasoning', 'content':'secret'}))
        item = public_item({'type':'commandExecution', 'command':'echo test', 'reasoning':'secret'})
        self.assertNotIn('reasoning', item)


class HostTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.roles = roles_at(self.base)
        self.rpc = FakeRPC()
        self.now = 1000.0
        self.host = Host(self.rpc, self.roles, Safeguards(), self.base/'evidence', clock=lambda:self.now)
        self.lead = (await self.host.spawn('lead', 'Orchestrate fixture'))['agent_id']
    async def asyncTearDown(self):
        self.tmp.cleanup()
    def event(self, agent_id, method, **params):
        a = self.host.agents[agent_id]
        self.host.on_event({'method':method, 'params':{'threadId':a.thread_id, 'turnId':a.turn_id, **params}})
    def finish(self, agent_id, with_usage=True):
        a = self.host.agents[agent_id]
        if with_usage:
            self.event(agent_id, 'thread/tokenUsage/updated', tokenUsage=usage(len(a.all_turns)))
        self.event(agent_id, 'turn/completed', turn={'id':a.turn_id,'status':'completed'})
    async def test_dynamic_real_thread_admission_and_async_wait(self):
        child = (await self.host.spawn('measurement','Measure fixture',self.lead))['agent_id']
        waiting = asyncio.create_task(self.host.wait([child], 1))
        await asyncio.sleep(0)
        self.assertFalse(waiting.done())
        self.finish(child)
        self.assertEqual((await waiting)[0]['state'], 'completed')
        methods = [x[0] for x in self.rpc.calls]
        self.assertEqual(methods.count('thread/start'), 2)
        self.assertEqual(methods.count('turn/start'), 2)
    async def test_cancel_ack_does_not_imply_terminal(self):
        child = (await self.host.spawn('implementation','Implement fixture',self.lead))['agent_id']
        result = await self.host.cancel(child)
        self.assertEqual(result['state'], 'cancelling')
        with self.assertRaisesRegex(RuntimeFailure,'cannot_seal'):
            self.host.seal()
        a=self.host.agents[child]
        self.event(child,'turn/completed',turn={'id':a.turn_id,'status':'interrupted'})
        self.assertFalse(self.host.export()['accounting_complete'])

    async def test_public_cancel_steers_cooperative_wrap_up_without_interrupt(self):
        child=(await self.host.spawn('implementation','Implement fixture',self.lead))['agent_id']
        lead=self.host.agents[self.lead]
        before=len(self.rpc.calls)
        result=await self.host.on_request({'threadId':lead.thread_id,'turnId':lead.turn_id,
            'namespace':None,'callId':'wrap-up','tool':'study_cancel','arguments':{'agent_id':child}})
        self.assertTrue(result['success'])
        reply=json.loads(result['contentItems'][0]['text'])
        self.assertTrue(reply['wrap_up_request_acknowledged'])
        self.assertFalse(reply['terminal_event_observed'])
        self.assertFalse(reply['interruption_requested'])
        self.assertEqual(reply['state'],'running')
        calls=self.rpc.calls[before:]
        self.assertEqual([method for method,_ in calls],['turn/steer'])
        self.assertEqual(calls[0][1]['expectedTurnId'],self.host.agents[child].turn_id)
        self.assertIn('Preserve work and evidence',calls[0][1]['input'][0]['text'])
        self.finish(child);self.finish(self.lead)
        self.assertTrue(self.host.export()['accounting_complete'])

    async def test_public_cancel_does_not_restart_terminal_worker(self):
        child=(await self.host.spawn('measurement','Measure fixture',self.lead))['agent_id']
        self.finish(child)
        before=len(self.rpc.calls)
        reply=await self.host.request_wrap_up(child)
        self.assertEqual(reply['state'],'completed')
        self.assertFalse(reply['wrap_up_request_sent'])
        self.assertFalse(reply['wrap_up_request_acknowledged'])
        self.assertTrue(reply['terminal_event_observed'])
        self.assertEqual(len(self.rpc.calls),before)
        self.assertEqual(len(self.host.agents[child].all_turns),1)

    async def test_emergency_interrupt_with_observed_usage_is_still_incomplete(self):
        child=(await self.host.spawn('implementation','Implement fixture',self.lead))['agent_id']
        self.event(child,'thread/tokenUsage/updated',tokenUsage=usage())
        await self.host.cancel(child)
        actor=self.host.agents[child]
        self.event(child,'turn/completed',turn={'id':actor.turn_id,'status':'interrupted'})
        self.finish(self.lead)
        export=self.host.export()
        row=next(a for a in export['agents'] if a['agent_id']==child)
        self.assertEqual(row['token_usage']['total']['totalTokens'],130)
        self.assertFalse(row['token_usage']['observed_accounting_complete'])
        self.assertIsNone(row['token_usage']['unreported_failed_request_usage'])
        self.assertFalse(export['accounting_complete'])
    async def test_review_elapsed_no_cap_and_fresh_context(self):
        child = (await self.host.spawn('reviewer','Review snapshot A',self.lead))['agent_id']
        self.now += 100000
        await self.host.enforce_safeguards()
        self.assertEqual(self.host.status(child)['state'],'running')
        self.finish(child)
        next_review = (await self.host.spawn('reviewer','Review snapshot B',self.lead))['agent_id']
        self.now += 30; self.finish(next_review)
        self.assertEqual(self.host.export()['reviewer_cumulative_seconds'],100030)
        self.assertFalse(any(x[0]=='thread/fork' for x in self.rpc.calls))
        await self.host.message(child,'Clarify evidence in your own independent context')
        self.assertEqual(self.host.status(child)['state'], 'running')
    async def test_multi_turn_usage_and_late_events(self):
        child = (await self.host.spawn('investigation','Investigate',self.lead))['agent_id']
        self.finish(child)
        await self.host.message(child,'Follow up')
        self.finish(child)
        self.finish(self.lead)
        self.assertEqual(self.host.export()['total_tokens']['totalTokens'],390)
        self.host.seal()
        self.event(child,'thread/tokenUsage/updated',tokenUsage=usage(3))
        self.assertEqual(self.host.failure,'late_usage_after_seal')
        self.assertEqual(self.host.export()['total_tokens']['totalTokens'],520)
        self.assertFalse(self.host.export()['accounting_complete'])
    async def test_missing_usage_then_late_usage_before_seal(self):
        child = (await self.host.spawn('measurement','Measure',self.lead))['agent_id']
        self.finish(child,False); self.finish(self.lead)
        self.assertFalse(self.host.export()['accounting_complete'])
        self.event(child,'thread/tokenUsage/updated',tokenUsage=usage())
        self.assertTrue(self.host.export()['accounting_complete'])
    async def test_compaction_marker_alone_is_not_accounting_failure(self):
        self.event(self.lead,'item/completed',item={'type':'contextCompaction','id':'c'})
        self.finish(self.lead)
        self.assertTrue(self.host.export()['accounting_complete'])
    async def test_worker_cannot_delegate_or_choose_model(self):
        child=(await self.host.spawn('measurement','Measure',self.lead))['agent_id']
        a=self.host.agents[child]
        result=await self.host.on_request({'threadId':a.thread_id,'turnId':a.turn_id,'namespace':None,
            'callId':'test-call', 'tool':'study_spawn','arguments':{'role':'reviewer','task':'Review'}})
        self.assertFalse(result['success'])
        lead=self.host.agents[self.lead]
        result=await self.host.on_request({'threadId':lead.thread_id,'turnId':lead.turn_id,'namespace':None,
            'callId':'test-call', 'tool':'study_spawn','arguments':{'role':'reviewer','task':'Review','model':'anything'}})
        self.assertFalse(result['success'])

    async def test_worker_workspaces_are_distinct(self):
        one = (await self.host.spawn('implementation','A',self.lead))['agent_id']
        two = (await self.host.spawn('implementation','B',self.lead))['agent_id']
        self.assertNotEqual(self.host.agents[one].spec.cwd, self.host.agents[two].spec.cwd)
        self.assertFalse(self.host.agents[one].spec.cwd.is_relative_to(self.host.agents[two].spec.cwd))

    async def test_duplicate_dynamic_call_is_idempotent(self):
        lead = self.host.agents[self.lead]
        params = {'threadId':lead.thread_id,'turnId':lead.turn_id,'namespace':None,
                  'callId':'once','tool':'study_spawn','arguments':{'role':'measurement','task':'A'}}
        first, second = await asyncio.gather(self.host.on_request(params), self.host.on_request(params))
        self.assertEqual(first, second)
        self.assertEqual(len(self.host.agents), 2)

    async def test_unknown_usage_and_native_spawn_are_not_counted_as_zero(self):
        with self.assertRaisesRegex(RuntimeFailure, 'event_from_unregistered_thread'):
            self.host.on_event({'method':'thread/tokenUsage/updated','params':{
                'threadId':'rogue','turnId':'rogue-turn','tokenUsage':usage()}})
        self.assertIsNone(self.host.export()['total_tokens']['totalTokens'])
        self.host.failure = None
        self.event(self.lead,'item/started',item={'type':'collabAgentToolCall','id':'native'})
        await self.host.enforce_safeguards()
        self.assertEqual(self.host.status(self.lead)['state'],'cancelling')
        self.assertIsNone(self.host.export()['total_tokens']['totalTokens'])

    async def test_owner_continues_lead_without_resetting_usage(self):
        self.finish(self.lead)
        await self.host.continue_lead('Fixed closure reminder')
        self.finish(self.lead)
        self.assertEqual(self.host.export()['total_tokens']['totalTokens'],260)
        self.assertEqual(len(self.host.agents),1)

    async def test_injected_tool_identity_is_thread_bound(self):
        received=[]
        async def dispatch(agent,tool,args):
            received.append((agent.agent_id,agent.role,tool,args)); return {'ok':True}
        self.host.development_tools={'lead':[{'name':'study_owner_status'}]}
        self.host.development_dispatch=dispatch
        lead=self.host.agents[self.lead]
        result=await self.host.on_request({'threadId':lead.thread_id,'turnId':lead.turn_id,
            'namespace':None,'callId':'owner-status','tool':'study_owner_status','arguments':{}})
        self.assertTrue(result['success'])
        self.assertEqual(received[0][:2],(self.lead,'lead'))

    async def test_payloads_match_generated_pinned_schema(self):
        import jsonschema
        spec=self.host.agents[self.lead].spec
        samples=[('ThreadStartParams.json',start_thread_params('lead',spec)),
                 ('TurnStartParams.json',turn_params('thread-test','Task',spec))]
        for filename,value in samples:
            schema=json.loads((ROOT/'runtime/protocol-0.159.3'/filename).read_text())
            jsonschema.Draft7Validator(schema).validate(value)

    async def test_owner_artifact_references_do_not_expand_write_permissions(self):
        owner_root = self.base / 'owner-evidence'
        owner_root.mkdir()
        before = start_thread_params('lead', self.host.agents[self.lead].spec)
        self.host.artifact_roots = (owner_root,)
        report = {'summary': 'Evidence available', 'artifacts': [str(owner_root / 'result.json')],
                  'checks': [], 'limitations': []}
        self.event(self.lead, 'item/completed', item={'type': 'agentMessage', 'phase': 'final_answer',
                   'text': json.dumps(report)})
        self.assertEqual(self.host.status(self.lead)['report'], report)
        self.assertEqual(start_thread_params('lead', self.host.agents[self.lead].spec), before)
        self.assertNotIn(str(owner_root), before['runtimeWorkspaceRoots'])
        self.assertNotIn(str(owner_root), before['config']['sandbox_workspace_write']['writable_roots'])

    async def test_unapproved_or_escaping_artifact_text_has_no_authority(self):
        owner_root = self.base / 'owner-evidence'
        owner_root.mkdir()
        outside = self.base / 'outside'
        outside.mkdir()
        (owner_root / 'escape').symlink_to(outside, target_is_directory=True)
        self.host.artifact_roots = (owner_root,)
        for path in (outside / 'result.json', owner_root / 'escape' / 'result.json'):
            report = {'summary': 'Invalid reference', 'artifacts': [str(path)], 'checks': [], 'limitations': []}
            self.event(self.lead, 'item/completed', item={'type': 'agentMessage', 'phase': 'final_answer',
                       'text': json.dumps(report)})
            result=self.host.status(self.lead)
            self.assertEqual(result['report'],report)
            self.assertTrue(result['report_diagnostics']['schema_valid'])
            ref=result['report_diagnostics']['artifact_references'][0]
            self.assertFalse(ref['verified'])
            self.assertFalse(ref['dereferenced'])
            self.assertNotIn('invalid_compact_report', result['issues'])

    async def test_usage_timestamps_are_notification_observations(self):
        self.host.wall_clock = lambda: 1234567890.25
        self.now += 2.5
        self.event(self.lead, 'thread/tokenUsage/updated', tokenUsage=usage())
        self.now += 1.25
        self.event(self.lead, 'thread/tokenUsage/updated', tokenUsage=usage())
        updates = self.host.export()['agents'][0]['token_usage']['updates']
        self.assertEqual(updates[0]['observed_unix_seconds'], 1234567890.25)
        self.assertEqual(updates[0]['elapsed_from_host_start_seconds'], 2.5)
        self.assertEqual(updates[1]['elapsed_from_host_start_seconds'], 3.75)
        self.assertEqual(updates[1]['time_provenance'], 'notification_observation')
        self.assertTrue(updates[1]['duplicate'])

    async def test_scope_factory_cannot_reuse_worker_directory(self):
        child=(await self.host.spawn('implementation','A',self.lead))['agent_id']
        self.host.role_factory=lambda *_: self.host.agents[child].spec
        before=len(self.rpc.calls)
        with self.assertRaisesRegex(RuntimeFailure,'agent_write_scopes_overlap'):
            await self.host.spawn('implementation','B',self.lead)
        self.assertEqual(len(self.rpc.calls),before)

    async def test_sealed_known_lifecycle_duplicates_are_benign(self):
        self.finish(self.lead)
        self.host.seal()
        for state in ('idle', 'notLoaded'):
            self.event(self.lead, 'thread/status/changed', status={'type': state})
        self.event(self.lead, 'thread/closed')
        self.event(self.lead, 'turn/completed', turn={'id': 'turn-1', 'status': 'completed'})
        self.event(self.lead, 'thread/tokenUsage/updated', tokenUsage=usage())
        self.assertTrue(self.host.export()['accounting_complete'])
        self.assertIsNone(self.host.failure)

    async def test_sealed_new_activity_invalidates_without_stopping_numeric_drain(self):
        self.finish(self.lead)
        self.host.seal()
        self.event(self.lead, 'item/started', item={'type': 'commandExecution', 'id': 'late'})
        self.assertEqual(self.host.failure, 'late_event_after_seal')
        self.event(self.lead, 'thread/tokenUsage/updated', tokenUsage=usage(2))
        self.assertEqual(self.host.export()['total_tokens']['totalTokens'],260)
        self.assertFalse(self.host.export()['accounting_complete'])


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_drains_late_numeric_usage_and_invalidates_sealed_result(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder); roles=roles_at(base)
            rpc=StdioRPC([sys.executable,str(Path(__file__).with_name('fake_app_server.py')),
                          '--late-usage-on-shutdown'],base,request_timeout=5)
            host=Host(rpc,roles,Safeguards(),base/'evidence')
            await rpc.open()
            try:
                await host.initialize()
                await host.spawn('lead','Fixture')
                await asyncio.wait_for(wait_for_completion(host),5)
                self.assertTrue(host.seal()['accounting_complete'])
            finally:
                cleanup=await rpc.close()
            result=host.export()
            self.assertTrue(cleanup['event_stream_drained'])
            self.assertTrue(cleanup['tracked_processes_exited'])
            self.assertEqual(result['total_tokens']['totalTokens'],520)
            self.assertEqual(result['failure'],'late_usage_after_seal')
            self.assertFalse(result['accounting_complete'])

    async def test_shutdown_benign_lifecycle_preserves_sealed_result(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder); roles=roles_at(base)
            rpc=StdioRPC([sys.executable,str(Path(__file__).with_name('fake_app_server.py'))],base,request_timeout=5)
            host=Host(rpc,roles,Safeguards(),base/'evidence')
            await rpc.open()
            try:
                await host.initialize()
                await host.spawn('lead','Fixture')
                await asyncio.wait_for(wait_for_completion(host),5)
                host.seal()
            finally:
                cleanup=await rpc.close()
            self.assertTrue(cleanup['event_stream_drained'])
            self.assertTrue(host.export()['accounting_complete'])

    async def test_faithful_fake_process_interleaves_real_json_rpc(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder); roles=roles_at(base)
            config={'phase':'integration-preflight','owner_approved':True,'evidence_dir':str(base/'evidence'),
                'task':'Orchestrate synthetic fixture',
                'roles':{role:{'model':spec.model,'effort':spec.effort,'cwd':str(spec.cwd),
                    'writable_roots':[str(x) for x in spec.writable_roots], 'instructions':spec.instructions}
                    for role,spec in roles.items()}}
            rpc=StdioRPC([sys.executable,str(Path(__file__).with_name('fake_app_server.py'))],base,request_timeout=5)
            result=await asyncio.wait_for(run_manifest(config,rpc=rpc),10)
            self.assertTrue(result['accounting_complete'],result)
            self.assertEqual(len(result['agents']),3)
            self.assertEqual(result['total_tokens']['totalTokens'],390)
            self.assertTrue(result['cleanup']['tracked_processes_exited'])
            self.assertTrue(result['cleanup']['event_stream_drained'])
            text=''.join(p.read_text() for p in (base/'evidence').iterdir())
            self.assertIn('ordinary fixture output',text)
            self.assertNotIn('PRIVATE_REASONING_SENTINEL',text)
            self.assertNotIn('DO_NOT_EXPORT',text)
    async def test_real_transport_requires_direct_terminal_authorization(self):
        with self.assertRaisesRegex(RuntimeFailure,'direct_terminal_launch_not_authorized'):
            StdioRPC.official(Path('/tmp'))
    async def test_unresponsive_rpc_has_infrastructure_timeout(self):
        with tempfile.TemporaryDirectory() as folder:
            rpc=StdioRPC([sys.executable,'-c','import time;time.sleep(30)'],folder,request_timeout=.05)
            await rpc.open()
            try:
                with self.assertRaisesRegex(RuntimeFailure,'rpc_admission_timeout'):
                    await rpc.request('initialize',{})
            finally:
                result=await rpc.close()
            self.assertTrue(result['tracked_processes_exited'])


if __name__=='__main__':
    unittest.main()
