"""No model calls or native measurements: fake CLI protocol, real bounded files."""
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from owner.measurement import MeasurementCoordinator
from runtime.workspace import WorkspaceRouter, SUPERVISOR, tool_specs, COMMAND_RESPONSE_GRACE_SECONDS
from runtime.transport import StdioRPC


def digest(data): return hashlib.sha256(data).hexdigest()


class FakeRPC:
    def __init__(self):
        self.calls = []
        self.received = asyncio.Event()
        self.finish = asyncio.Event(); self.finish.set()
        self.code = 0
        self.mutate = lambda receipt, capture: None
        self.output = b'ordinary stdout\n'
        self.cancelled = False
        self.error = None

    async def request(self, method, params, *, timeout='default'):
        self.calls.append((method, params, timeout))
        raw = base64.b64decode(params['command'][-1])
        spec = json.loads(raw)
        capture = Path(spec['output_directory'])
        self.capture = capture
        self.received.set()
        try: await self.finish.wait()
        except asyncio.CancelledError:
            self.cancelled = True; raise
        if self.error: raise self.error
        files = {}
        for name, data in [('stdout.bin', self.output), ('stderr.bin', b'ordinary stderr\n')]:
            (capture/name).write_bytes(data)
            files[name] = {'bytes': len(data), 'observed_bytes': len(data), 'discarded_bytes': 0, 'sha256': digest(data)}
        receipt = {'schema_version': 1, 'invocation_id': spec['invocation_id'], 'spec_sha256': digest(raw),
                   'supervisor_sha256': digest(SUPERVISOR.read_bytes()), 'process_started': True,
                   'root_exit_code': self.code, 'reason': 'command_completed', 'cleanup_complete': True,
                   'subreaper_verified': True, 'sigchld_default_verified': True,
                   'remaining_direct_children': [], 'output_drained': True, 'output_files': files}
        self.mutate(receipt, capture)
        return {'exitCode': 0, 'stdout': json.dumps(receipt), 'stderr': ''}


class WorkspaceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.campaign = self.root/'campaign'; self.campaign.mkdir()
        self.actor = self.campaign/'scratch'/'agent-1'; self.actor.mkdir(parents=True)
        self.other = self.campaign/'scratch'/'agent-2'; self.other.mkdir()
        self.public = self.root/'contract'; self.public.mkdir()
        self.evidence = self.campaign/'development'; self.evidence.mkdir()
        self.rpc = FakeRPC(); self.coordinator = MeasurementCoordinator()
        self.agent = SimpleNamespace(agent_id='agent-1', role='implementation', thread_id='thread', turn_id='turn',
                                     spec=SimpleNamespace(cwd=self.actor, writable_roots=(self.actor,)))
        self.router = WorkspaceRouter(self.rpc, self.coordinator, self.campaign,
                                      public_roots=(self.public,), evidence_roots=(self.evidence,))

    async def asyncTearDown(self):
        await self.router.close()
        self.temp.cleanup()

    async def call(self, name, **args):
        return await self.router.dispatch(self.agent, 'study_workspace_'+name, args)

    def test_exact_schemas(self):
        self.assertEqual(len(tool_specs()), 5)
        self.assertTrue(all(t['inputSchema']['additionalProperties'] is False for t in tool_specs()))
        self.assertEqual(self.router.schemas(), tool_specs())

    async def test_bounded_read_and_durable_exact_request(self):
        (self.actor/'large').write_bytes(b'abcdefgh')
        result = await self.call('read', path='large', max_bytes=3, offset=2)
        self.assertEqual((result['content'], result['next_offset'], result['truncated']), ('cde', 5, True))
        self.assertEqual(result['slice_sha256'], digest(b'cde'))
        request = json.loads((Path(result['artifact_directory'])/'request.json').read_text())
        self.assertEqual(request['arguments'], {'path': 'large', 'max_bytes': 3, 'offset': 2})
        self.assertEqual(self.coordinator.snapshot()['completed_leases'], 0)

    async def test_rejects_outside_paths_symlinks_fifo_and_hardlinks(self):
        (self.other/'secret').write_text('other actor')
        (self.actor/'link').symlink_to(self.other/'secret')
        (self.actor/'linked-dir').symlink_to(self.other, target_is_directory=True)
        os.mkfifo(self.actor/'pipe')
        os.link(self.other/'secret', self.actor/'hard')
        for path in [str(self.other/'secret'), '../agent-2/secret', 'link', 'linked-dir/secret', 'pipe', 'hard', '/dev/zero']:
            with self.subTest(path=path):
                result = await asyncio.wait_for(self.call('read', path=path), 1)
                self.assertEqual(result['status'], 'request_error')

    async def test_fifo_is_inspected_without_opening_its_contents(self):
        os.mkfifo(self.actor/'pipe')
        for name, args in [('read', {'path':'pipe'}), ('write', {'path':'pipe','content':'x'})]:
            with mock.patch('runtime.workspace.os.open', wraps=os.open) as opened:
                result=await self.call(name, **args)
            self.assertEqual(result['status'],'request_error')
            self.assertFalse(any(str(call.args[0]).startswith('/proc/self/fd/') for call in opened.call_args_list))
            final_opens=[call for call in opened.call_args_list if call.args[0]=='pipe']
            self.assertTrue(final_opens[-1].args[1] & os.O_PATH)

    async def test_read_public_evidence_but_write_only_actor(self):
        for root in [self.public, self.evidence]:
            (root/'allowed').write_text('readable')
            self.assertEqual((await self.call('read', path=str(root/'allowed')))['content'], 'readable')
            self.assertEqual((await self.call('write', path=str(root/'new'), content='no'))['status'], 'request_error')
        result = await self.call('write', path='src/file.cc', content='a', mkdir_parents=True)
        self.assertEqual(result['status'], 'ok')
        await self.call('write', path='src/file.cc', content='b', append=True)
        self.assertEqual((self.actor/'src/file.cc').read_text(), 'ab')
        self.assertEqual(self.coordinator.snapshot()['completed_leases'], 4)

    async def test_write_does_not_truncate_unsafe_target(self):
        target = self.other/'secret'; target.write_text('preserve')
        os.link(target, self.actor/'hard')
        os.mkfifo(self.actor/'pipe')
        (self.actor/'symlink').symlink_to(target)
        for path in ['hard', 'pipe', 'symlink']:
            result = await asyncio.wait_for(self.call('write', path=path, content='bad'), 1)
            self.assertEqual(result['status'], 'request_error')
        self.assertEqual(target.read_text(), 'preserve')

    async def test_list_cursor_rejects_cross_actor_and_handles_unsafe(self):
        for n in range(5): (self.actor/f'file{n}').write_text(str(n))
        (self.actor/'unsafe').symlink_to(self.other)
        seen = []; cursor = None
        while True:
            result = await self.call('list', path='.', max_entries=2, **({'cursor': cursor} if cursor else {}))
            self.assertEqual(result['status'], 'ok')
            seen.extend(result['entries']); cursor = result['cursor']
            if not cursor: break
        self.assertEqual(len(seen), 6)
        self.assertEqual(sum(e['type'].startswith('rejected') for e in seen), 1)
        result = await self.call('list', path='.', max_entries=1)
        other_agent = SimpleNamespace(**{**vars(self.agent), 'agent_id': 'agent-2'})
        rejected = await self.router.dispatch(other_agent, 'study_workspace_list', {'path': str(self.actor), 'cursor': result['cursor']})
        self.assertEqual(rejected['status'], 'request_error')

    async def test_search_byte_bounds_continuation_and_cross_chunk_literal(self):
        (self.actor/'text').write_bytes(b'xxneedle xxneedle needle!')
        (self.actor/'pipe').touch(); (self.actor/'pipe').unlink(); os.mkfifo(self.actor/'pipe')
        (self.actor/'link').symlink_to(self.other)
        matches = []; cursor = None
        for _ in range(100):
            result = await self.call('search', path='.', query='needle', max_bytes=4, max_files=2, max_matches=1,
                                     **({'cursor': cursor} if cursor else {}))
            self.assertEqual(result['status'], 'ok')
            self.assertLessEqual(result['scanned_bytes'], 4)
            self.assertLessEqual(result['scanned_entries'], 8)
            matches.extend(r['byte_offset'] for r in result['matches'])
            cursor = result['cursor']
            if not cursor: break
        self.assertIsNone(cursor)
        self.assertEqual(matches, [2, 11, 18])

    async def test_search_changed_file_is_repairable(self):
        path=self.actor/'text'; path.write_text('needle '*10)
        first = await self.call('search', path='text', query='needle', max_bytes=10)
        path.write_text('changed')
        next_page = await self.call('search', path='text', query='needle', cursor=first['cursor'])
        self.assertEqual(next_page['status'], 'request_error')

    async def test_read_bypasses_lease_write_and_exec_queue(self):
        (self.actor/'file').write_text('content')
        lease = self.coordinator.acquire('bench', actor_id='native')
        pending = asyncio.create_task(self.call('write', path='file', content='changed'))
        for _ in range(100):
            if self.coordinator.snapshot()['queued']: break
            await asyncio.sleep(.001)
        self.assertFalse(pending.done())
        self.assertEqual((await self.call('read', path='file'))['content'], 'content')
        self.coordinator.release(lease)
        self.assertEqual((await pending)['status'], 'ok')

    async def test_exec_uses_sandbox_not_owner_execution_and_durable_output(self):
        command = 'g++ candidate.cc -o program && ./program; valgrind ./program'
        result = await self.call('exec', command=command, timeout_seconds=7200)
        self.assertEqual(result['status'], 'ok')
        method, params, timeout = self.rpc.calls[0]
        self.assertEqual(method, 'command/exec'); self.assertEqual(timeout,7200+COMMAND_RESPONSE_GRACE_SECONDS)
        self.assertTrue(params['disableTimeout'])
        self.assertFalse(params['sandboxPolicy']['networkAccess'])
        self.assertEqual(params['sandboxPolicy']['writableRoots'], [str(self.actor)])
        spec=json.loads(base64.b64decode(params['command'][-1]))
        self.assertEqual((spec['command'], spec['timeout_seconds']), (command, 7200))
        stdout = result['outputs']['stdout']
        self.assertEqual(Path(stdout['artifact']).read_bytes(), self.rpc.output)
        self.assertFalse(Path(stdout['artifact']).is_relative_to(self.actor))
        self.assertEqual(self.coordinator.snapshot()['completed_leases'], 1)

    async def test_nonzero_and_verified_prelaunch_are_repairable(self):
        self.rpc.code = 7
        failed=await self.call('exec', command='exit 7')
        self.assertEqual((failed['status'], failed['exit_code']), ('command_failed', 7))
        def prelaunch(row, capture): row.update(process_started=False, root_exit_code=None, reason='command_launch_failure')
        self.rpc.mutate=prelaunch
        failed=await self.call('exec', command='irrelevant')
        self.assertEqual(failed['status'], 'command_failed')
        self.assertTrue(failed['cleanup_complete'])
        self.assertIsNone(self.coordinator.snapshot()['quarantine'])

    async def test_output_bound_and_capture_symlink_rejected_without_reading(self):
        self.rpc.output=b'x'*10000
        result=await self.call('exec', command='verbose')
        self.assertEqual(len(result['outputs']['stdout']['excerpt']),8192)
        self.assertTrue(result['outputs']['stdout']['excerpt_truncated'])
        outside=self.other/'do-not-read'; outside.write_text('private')
        def replace_capture(row, capture):
            (capture/'stdout.bin').unlink(); (capture/'stdout.bin').symlink_to(outside)
        self.rpc.mutate=replace_capture
        result=await self.call('exec', command='output changed')
        self.assertEqual(result['status'],'artifact_error')
        self.assertTrue(result['cleanup_complete'])
        self.assertFalse((Path(result['artifact_directory'])/'stdout.bin').exists())

    async def test_invalid_receipt_quarantines_even_claimed_empty(self):
        self.rpc.mutate=lambda row,capture: row.update(spec_sha256='wrong')
        result=await self.call('exec', command='true')
        self.assertEqual(result['status'],'resource_quarantined')
        self.assertIsNotNone(self.coordinator.snapshot()['quarantine'])
        self.assertIsNone(self.coordinator.snapshot()['active'])

    async def test_rpc_failure_quarantines_resources(self):
        self.rpc.error=RuntimeError('transport failed')
        result=await self.call('exec', command='true')
        self.assertEqual(result['status'],'resource_quarantined')
        self.assertIsNotNone(self.coordinator.snapshot()['quarantine'])

    async def test_silent_lost_response_hits_derived_deadline_and_quarantines(self):
        self.rpc.finish.clear()
        original=self.rpc.request
        async def timed_request(method,params,*,timeout):
            return await asyncio.wait_for(original(method,params,timeout=timeout),timeout)
        self.rpc.request=timed_request
        with mock.patch('runtime.workspace.COMMAND_RESPONSE_GRACE_SECONDS',.02):
            result=await asyncio.wait_for(self.call('exec',command='true',timeout_seconds=.01),1)
        self.assertEqual(result['status'],'resource_quarantined')
        self.assertAlmostEqual(self.rpc.calls[0][2],.03)
        self.assertIsNotNone(self.coordinator.snapshot()['quarantine'])
        self.assertIsNone(self.coordinator.snapshot()['active'])
        self.assertEqual(len(self.rpc.calls),1)

    async def test_repeated_cancellation_keeps_original_rpc_and_lease(self):
        self.rpc.finish.clear()
        task=asyncio.create_task(self.call('exec',command='long task'))
        await self.rpc.received.wait()
        task.cancel(); await asyncio.sleep(.01); task.cancel(); await asyncio.sleep(.01)
        self.assertTrue((self.rpc.capture/'cancel-requested').exists())
        self.assertFalse(task.done()); self.assertFalse(self.rpc.cancelled)
        self.assertEqual(self.coordinator.snapshot()['active']['kind'],'workspace_exec')
        self.rpc.finish.set()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertIsNone(self.coordinator.snapshot()['active'])
        self.assertEqual(len(self.rpc.calls),1)
        results=[json.loads(p.read_text()) for p in self.router.operations.glob('*/result.json')]
        self.assertEqual(results[0]['status'],'cancelled')

    async def test_close_waits_for_cleanup_before_returning(self):
        self.rpc.finish.clear()
        task=asyncio.create_task(self.call('exec',command='long task'))
        await self.rpc.received.wait()
        closing=asyncio.create_task(self.router.close())
        await asyncio.sleep(.02)
        self.assertFalse(closing.done()); self.assertFalse(self.rpc.cancelled)
        self.assertTrue((self.rpc.capture/'cancel-requested').exists())
        self.rpc.finish.set()
        report=await closing
        self.assertTrue(report['drained']); self.assertIsNone(report['quarantine'])
        self.assertEqual((await task)['status'],'cancelled')

    async def test_invalid_schema_does_not_acquire_lease(self):
        for args in [{'path':'x','max_bytes':True},{'path':'x','max_bytes':0},{'path':'x','extra':1}]:
            result=await self.router.dispatch(self.agent,'study_workspace_read',args)
            self.assertEqual(result['status'],'request_error')
        self.assertEqual(self.coordinator.snapshot()['completed_leases'],0)

    async def test_nonfinite_and_invalid_unicode_are_repairable(self):
        for args in [{'command':'true','timeout_seconds':float('nan')}, {'command':'\ud800'}]:
            result=await self.router.dispatch(self.agent,'study_workspace_exec',args)
            self.assertEqual(result['status'],'request_error')
        self.assertEqual(self.rpc.calls,[])
        self.assertEqual(self.coordinator.snapshot()['completed_leases'],0)


class TransportTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_none_overrides_only_this_rpc_admission_timeout(self):
        rpc=StdioRPC([],'.',request_timeout=.01)
        async def send(message):
            async def reply():
                await asyncio.sleep(.04)
                future=rpc.pending.get(message['id'])
                if future is not None and not future.done(): future.set_result({'ok':True})
            asyncio.create_task(reply())
        rpc.send=send
        self.assertEqual(await rpc.request('command/exec',{},timeout=None),{'ok':True})
        with self.assertRaisesRegex(Exception,'rpc_admission_timeout'):
            await rpc.request('thread/start',{})


if __name__=='__main__': unittest.main()
