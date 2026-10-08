"""Independent integrated cancellation-order check with synthetic CLI/native work."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests/owner'))

from owner.measurement import MeasurementCoordinator
from owner.runner import run_workflow
from owner.service import load
from runtime.workspace import SUPERVISOR
import test_owner as owner_fixtures
import test_runner as runner_fixtures


class DelayedCleanupRPC(runner_fixtures.ScriptedRPC):
    def __init__(self, cwd):
        super().__init__(cwd)
        self.command_started = asyncio.Event()
        self.release_receipt = asyncio.Event()
        self.interrupted = asyncio.Event()
        self.closed = False

    async def request(self, method, params, *, timeout='default'):
        if method == 'turn/interrupt':
            self.interrupted.set()
            return {}
        if method != 'command/exec':
            return await super().request(method, params)
        raw = base64.b64decode(params['command'][-1])
        spec = json.loads(raw)
        capture = Path(spec['output_directory'])
        self.command_started.set()
        await self.release_receipt.wait()
        streams = {'stdout.bin': b'synthetic\n', 'stderr.bin': b''}
        for name, content in streams.items():
            (capture / name).write_bytes(content)
        receipt = {
            'schema_version': 1, 'invocation_id': spec['invocation_id'],
            'spec_sha256': hashlib.sha256(raw).hexdigest(),
            'supervisor_sha256': hashlib.sha256(SUPERVISOR.read_bytes()).hexdigest(),
            'cleanup_complete': True, 'remaining_direct_children': [],
            'subreaper_verified': True, 'sigchld_default_verified': True,
            'output_drained': True, 'process_started': True, 'root_exit_code': -15,
            'reason': 'interrupted', 'output_files': {
                name: {'bytes': len(content), 'observed_bytes': len(content), 'discarded_bytes': 0,
                       'sha256': hashlib.sha256(content).hexdigest()}
                for name, content in streams.items()},
        }
        return {'exitCode': 0, 'stdout': json.dumps(receipt), 'stderr': ''}

    async def script(self, tid, turn, task):
        await asyncio.sleep(0)
        try:
            await self.tool(tid, 'study_workspace_exec', {'command': 'synthetic long command'})
        except BaseException:
            pass  # The test deliberately cancels this command's caller.
        await self.interrupted.wait()
        numeric = {'inputTokens': 90, 'cachedInputTokens': 30, 'cacheWriteInputTokens': 0,
                   'outputTokens': 7, 'reasoningOutputTokens': 3, 'totalTokens': 97}
        self.on_event({'method': 'thread/tokenUsage/updated', 'params': {
            'threadId': tid, 'turnId': turn, 'tokenUsage': {'last': numeric, 'total': numeric}}})
        self.on_event({'method': 'turn/completed', 'params': {
            'threadId': tid, 'turn': {'id': turn, 'status': 'interrupted'}}})

    async def close(self):
        result = await super().close()
        self.closed = True
        return result


class RunnerCancellationReviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_interrupts_model_before_waiting_for_command_cleanup_receipt(self):
        with tempfile.TemporaryDirectory(prefix='v3-independent-stop-') as temporary:
            root = Path(temporary)
            (root / 'task/seed').mkdir(parents=True)
            (root / 'task/seed/engine.cpp').write_text('int source=1;\n')
            (root / 'task/contract').mkdir()
            (root / 'task/contract/SPEC.md').write_text('Synthetic test contract')
            coordinator = MeasurementCoordinator()
            made = []

            def factory(cwd):
                peer = DelayedCleanupRPC(cwd)
                made.append(peer)
                return peer

            running = asyncio.create_task(run_workflow(root, root / 'setup/cancellation',
                owner_fixtures.FakeBackend(), load(ROOT / 'owner/config.draft.json'), setup=True,
                rpc_factory=factory, measurement_coordinator=coordinator))
            try:
                for _ in range(2000):
                    if made:
                        break
                    await asyncio.sleep(.001)
                self.assertTrue(made)
                peer = made[0]
                await asyncio.wait_for(peer.command_started.wait(), 2)
                lease_id = coordinator.snapshot()['active']['lease_id']
                running.cancel()
                await asyncio.wait_for(peer.interrupted.wait(), .5)
                self.assertFalse(running.done())
                self.assertFalse(peer.closed)
                self.assertEqual(coordinator.snapshot()['active']['lease_id'], lease_id)
            finally:
                if made:
                    made[0].release_receipt.set()
                owner, telemetry = await asyncio.wait_for(running, 3)
            self.assertEqual(owner.state['status'], 'incomplete')
            self.assertEqual(telemetry['failure'], 'owner_stop_requested')
            self.assertTrue(telemetry['workspace_cleanup']['drained'])
            self.assertEqual(telemetry['total_tokens']['totalTokens'], 97)
            self.assertIsNone(coordinator.snapshot()['active'])


if __name__ == '__main__':
    unittest.main()
