"""Independent bounded-read and command-protocol checks; no CLI/model execution."""
from __future__ import annotations

import asyncio
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from owner.measurement import MeasurementCoordinator, MeasurementCoordinationError
from runtime.contracts import RoleSpec, RuntimeFailure, sandbox
from runtime.transport import StdioRPC
from runtime.workspace import COMMAND_RESPONSE_GRACE_SECONDS, READ_CAP, SUPERVISOR, WorkspaceRouter


class ReceiptRPC:
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.calls = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.failure = None
        self.receipt_mutator = None
        self.capture_mutator = None

    async def request(self, method, params, *, timeout='default'):
        self.calls.append((method, params, timeout))
        self.active_at_entry = self.coordinator.snapshot()['active']
        raw = base64.b64decode(params['command'][-1], validate=True)
        self.spec = json.loads(raw)
        self.capture = Path(self.spec['output_directory'])
        self.entered.set()
        await self.release.wait()
        if self.failure:
            raise self.failure
        streams = {'stdout.bin': b'synthetic output\n', 'stderr.bin': b''}
        for name, content in streams.items():
            (self.capture / name).write_bytes(content)
        receipt = {
            'schema_version': 1, 'invocation_id': self.spec['invocation_id'],
            'spec_sha256': hashlib.sha256(raw).hexdigest(),
            'supervisor_sha256': hashlib.sha256(SUPERVISOR.read_bytes()).hexdigest(),
            'cleanup_complete': True, 'remaining_direct_children': [],
            'subreaper_verified': True, 'sigchld_default_verified': True,
            'output_drained': True, 'process_started': True, 'root_exit_code': 0,
            'reason': 'command_completed',
            'output_files': {name: {'bytes': len(content), 'observed_bytes': len(content),
                                   'discarded_bytes': 0, 'sha256': hashlib.sha256(content).hexdigest()}
                             for name, content in streams.items()},
        }
        if self.receipt_mutator:
            self.receipt_mutator(receipt)
        if self.capture_mutator:
            self.capture_mutator(self.capture)
        return {'exitCode': 0, 'stdout': json.dumps(receipt), 'stderr': ''}


class WorkspaceReviewTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='v3-independent-workspace-')
        self.root = Path(self.tmp.name)
        self.campaign = self.root / 'campaign'
        self.actor = self.campaign / 'scratch/lead'
        self.evidence = self.campaign / 'development'
        self.public = self.root / 'public'
        for path in (self.actor, self.evidence, self.public):
            path.mkdir(parents=True)
        self.agent = SimpleNamespace(agent_id='lead-1', role='lead', thread_id='thread-1', turn_id='turn-1',
            spec=RoleSpec('gpt-6.1-sol', 'high', self.actor, (self.actor,), 'Synthetic test actor'))
        self.coordinator = MeasurementCoordinator()
        self.rpc = ReceiptRPC(self.coordinator)
        self.router = WorkspaceRouter(self.rpc, self.coordinator, self.campaign,
            public_roots=(self.public,), evidence_roots=(self.evidence,))

    async def asyncTearDown(self):
        self.rpc.release.set()
        await self.router.close()
        self.tmp.cleanup()

    async def call(self, name, **args):
        return await self.router.dispatch(self.agent, 'study_workspace_' + name, args)

    async def queued(self):
        for _ in range(2000):
            if self.coordinator.snapshot()['queued']:
                return
            await asyncio.sleep(.001)
        self.fail('synthetic waiter did not enter queue')

    async def test_read_and_search_work_during_benchmark_and_metadata_lock(self):
        path = self.evidence / 'source.cpp'
        content = b'a' * (READ_CAP - 2) + b'needle' + b'z' * READ_CAP
        path.write_bytes(content)
        held = self.coordinator.acquire('bench', actor_id='reviewer')
        with (self.evidence / '.metadata.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                result = await asyncio.wait_for(self.call('read', path=str(path)), 1)
                self.assertEqual(result['status'], 'ok')
                self.assertEqual(result['bytes_read'], READ_CAP)
                self.assertEqual(result['slice_sha256'], hashlib.sha256(content[:READ_CAP]).hexdigest())
                first = await asyncio.wait_for(self.call('search', path=str(path), query='needle',
                                                        max_bytes=READ_CAP, max_files=1), 1)
                self.assertEqual(first['status'], 'ok')
                self.assertEqual(first['matches'], [])
                self.assertTrue(first['truncated'])
                second = await asyncio.wait_for(self.call('search', path=str(path), query='needle',
                                                         cursor=first['cursor'], max_bytes=READ_CAP, max_files=1), 1)
                self.assertEqual([m['byte_offset'] for m in second['matches']], [READ_CAP - 2])
                self.assertLessEqual(second['scanned_bytes'], READ_CAP)
                self.assertEqual(self.coordinator.snapshot()['active']['lease_id'], held['lease_id'])
                self.assertEqual(self.coordinator.snapshot()['completed_leases'], 0)
                self.assertEqual(self.rpc.calls, [])
                self.assertEqual(self.coordinator.commands.active(), [])
            finally:
                self.coordinator.release(held)

    async def test_all_read_kinds_reject_escape_and_do_not_follow_unsafe_entries(self):
        outside = self.root / 'outside.txt'
        outside.write_text('unrelated-file')
        (self.actor / 'symlink').symlink_to(outside)
        (self.actor / 'linkdir').symlink_to(self.public, target_is_directory=True)
        os.mkfifo(self.actor / 'fifo')
        os.link(outside, self.actor / 'hardlink')
        (self.public / 'public.txt').write_text('allowed public')
        for path in (str(outside), '../lead/symlink', 'symlink', 'linkdir/public.txt', 'fifo', 'hardlink'):
            with self.subTest(path=path):
                result = await asyncio.wait_for(self.call('read', path=path), 1)
                self.assertEqual(result['status'], 'request_error')
        rows = await self.call('list', path=str(self.actor))
        self.assertEqual(rows['status'], 'ok')
        self.assertEqual(len(rows['entries']), 4)
        self.assertTrue(all(r['type'].startswith('rejected_') for r in rows['entries']))
        found = await self.call('search', path=str(self.actor), query='unrelated-file')
        self.assertEqual(found['status'], 'ok')
        self.assertEqual(found['matches'], [])
        self.assertEqual(found['rejected_entries'], 4)
        self.assertEqual((await self.call('read', path=str(self.public / 'public.txt')))['content'], 'allowed public')

    async def test_directory_listing_continuation_covers_more_than_one_page(self):
        for n in range(29):
            (self.actor / f'file-{n:02d}').write_text('example')
        names, cursor = [], None
        while True:
            args = {'path': str(self.actor), 'max_entries': 7}
            if cursor:
                args['cursor'] = cursor
            page = await self.call('list', **args)
            self.assertEqual(page['status'], 'ok')
            self.assertLessEqual(len(page['entries']), 7)
            names.extend(Path(entry['path']).name for entry in page['entries'])
            cursor = page['cursor']
            if not cursor:
                break
        self.assertEqual(len(names), 29)
        self.assertEqual(len(set(names)), 29)
        self.assertEqual(self.router.cursors, {})

    async def test_search_match_cap_resumes_without_loss_or_duplicate_matches(self):
        (self.actor / 'matches').write_text('aaaaa')
        offsets, cursor = [], None
        while True:
            args = {'path': 'matches', 'query': 'aa', 'max_matches': 1, 'max_bytes': 3}
            if cursor:
                args['cursor'] = cursor
            page = await self.call('search', **args)
            self.assertEqual(page['status'], 'ok')
            self.assertLessEqual(page['scanned_bytes'], 3)
            offsets.extend(row['byte_offset'] for row in page['matches'])
            cursor = page['cursor']
            if not cursor:
                break
        self.assertEqual(offsets, [0, 1, 2, 3])

    async def test_cursor_is_actor_bound_and_file_changes_reject_continuation(self):
        source = self.actor / 'source'
        source.write_bytes(b'abcdef')
        page = await self.call('search', path='source', query='f', max_bytes=2)
        second = SimpleNamespace(**vars(self.agent))
        second.agent_id = 'other'
        denied = await self.router.dispatch(second, 'study_workspace_search',
            {'path': 'source', 'query': 'f', 'cursor': page['cursor'], 'max_bytes': 2})
        self.assertEqual(denied['status'], 'request_error')
        source.write_bytes(b'changed')
        changed = await self.call('search', path='source', query='f', cursor=page['cursor'], max_bytes=2)
        self.assertEqual(changed['status'], 'request_error')
        self.assertEqual(self.router.cursors, {})

    async def test_write_waits_for_lane_and_rejects_hardlink_before_truncation(self):
        original = self.root / 'original'
        original.write_text('must remain')
        os.link(original, self.actor / 'hardlink')
        held = self.coordinator.acquire('bench', actor_id='reviewer')
        writing = asyncio.create_task(self.call('write', path='new/path.txt', content='hello', mkdir_parents=True))
        try:
            await self.queued()
            self.assertFalse((self.actor / 'new').exists())
        finally:
            self.coordinator.release(held)
        self.assertEqual((await writing)['status'], 'ok')
        self.assertEqual((self.actor / 'new/path.txt').read_text(), 'hello')
        rejected = await self.call('write', path='hardlink', content='changed')
        self.assertEqual(rejected['status'], 'request_error')
        self.assertEqual(original.read_text(), 'must remain')

    async def test_arbitrary_shell_uses_original_sandbox_and_derived_response_deadline(self):
        command = 'printf hello; for value in 1 2; do printf "$value"; done'
        result = await self.call('exec', command=command, timeout_seconds=900)
        self.assertEqual(result['status'], 'ok')
        method, params, timeout = self.rpc.calls[0]
        self.assertEqual(method, 'command/exec')
        self.assertEqual(timeout, 900 + COMMAND_RESPONSE_GRACE_SECONDS)
        self.assertEqual(params['sandboxPolicy'], sandbox(self.agent.spec))
        self.assertEqual(params['cwd'], str(self.actor))
        self.assertEqual(params['command'][:3], [sys.executable, '-B', str(SUPERVISOR)])
        self.assertTrue(params['disableTimeout'])
        self.assertEqual(self.rpc.spec['command'], command)
        self.assertEqual(self.rpc.spec['timeout_seconds'], 900)
        self.assertEqual(self.rpc.active_at_entry['kind'], 'workspace_exec')
        self.assertEqual(self.rpc.active_at_entry['actor_id'], self.agent.agent_id)
        lease = json.loads((Path(result['artifact_directory']) / 'execution-lease.json').read_text())
        self.assertIsNotNone(lease['released_monotonic'])
        self.assertIsNone(self.coordinator.snapshot()['active'])

    async def test_repeated_cancellation_keeps_lease_until_original_receipt(self):
        self.rpc.release.clear()
        command = asyncio.create_task(self.call('exec', command='sleep 30'))
        await asyncio.wait_for(self.rpc.entered.wait(), 1)
        active = self.coordinator.snapshot()['active']['lease_id']
        admitted = []

        async def later_job():
            async with self.coordinator.async_lease('build', actor_id='worker'):
                admitted.append('worker')

        later = asyncio.create_task(later_job())
        await self.queued()
        command.cancel()
        for _ in range(2000):
            if (self.rpc.capture / 'cancel-requested').exists():
                break
            await asyncio.sleep(.001)
        self.assertTrue((self.rpc.capture / 'cancel-requested').exists())
        command.cancel()
        await asyncio.sleep(.01)
        self.assertFalse(command.done())
        self.assertEqual(admitted, [])
        self.assertEqual(self.coordinator.snapshot()['active']['lease_id'], active)
        self.assertEqual(len(self.rpc.calls), 1)
        self.rpc.release.set()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(command, 1)
        await asyncio.wait_for(later, 1)
        self.assertEqual(admitted, ['worker'])
        self.assertIsNone(self.coordinator.snapshot()['quarantine'])
        result = json.loads(next(self.router.operations.glob('*/result.json')).read_text())
        self.assertEqual(result['status'], 'cancelled')
        self.assertTrue(result['cleanup_complete'])

    async def test_rpc_loss_quarantines_future_resource_work(self):
        self.rpc.failure = RuntimeFailure('synthetic_connection_lost')
        result = await self.call('exec', command='example command')
        self.assertEqual(result['status'], 'resource_quarantined')
        self.assertEqual(len(self.rpc.calls), 1)
        self.assertIsNotNone(self.coordinator.snapshot()['quarantine'])
        with self.assertRaises(MeasurementCoordinationError):
            self.coordinator.acquire('bench', actor_id='reviewer')
        (self.actor / 'source').write_text('source remains readable')
        self.assertEqual((await self.call('read', path='source'))['status'], 'ok')

    async def test_silent_missing_response_times_out_actual_transport_and_quarantines(self):
        rpc = StdioRPC([], self.actor, request_timeout=.001)
        sent = []

        async def silent_send(message):
            sent.append(message)
            # Connection remains alive but this command never receives a result.

        rpc.send = silent_send
        self.router.rpc = rpc
        with patch('runtime.workspace.COMMAND_RESPONSE_GRACE_SECONDS', .03):
            result = await asyncio.wait_for(self.call('exec', command='synthetic missing result',
                                                       timeout_seconds=.02), 1)
        self.assertEqual(result['status'], 'resource_quarantined')
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]['method'], 'command/exec')
        self.assertEqual(rpc.pending, {})
        self.assertEqual(len(rpc.abandoned_requests), 1)
        self.assertIsNotNone(self.coordinator.snapshot()['quarantine'])
        policy = json.loads((Path(result['artifact_directory']) / 'rpc-policy.json').read_text())
        self.assertAlmostEqual(policy['response_timeout_seconds'], .05)
        self.assertEqual(policy['timeout_action'], 'quarantine resources; never retry an unattested command')
        with self.assertRaises(MeasurementCoordinationError):
            self.coordinator.acquire('build', actor_id='worker')

    async def test_invalid_cleanup_receipt_quarantines(self):
        self.rpc.receipt_mutator = lambda receipt: receipt.update(cleanup_complete=False)
        result = await self.call('exec', command='example command')
        self.assertEqual(result['status'], 'resource_quarantined')
        self.assertIsNotNone(self.coordinator.snapshot()['quarantine'])

    async def test_changed_capture_is_an_artifact_error_after_verified_cleanup(self):
        self.rpc.capture_mutator = lambda capture: (capture / 'stdout.bin').write_bytes(b'changed')
        result = await self.call('exec', command='example command')
        self.assertEqual(result['status'], 'artifact_error')
        self.assertTrue(result['cleanup_complete'])
        self.assertIsNone(self.coordinator.snapshot()['quarantine'])
        self.assertIsNone(self.coordinator.snapshot()['active'])


if __name__ == '__main__':
    unittest.main()
