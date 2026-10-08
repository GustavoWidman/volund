"""Real Host/owner/development/router contention with synthetic work and RPC."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests/owner'))

from owner.measurement import MeasurementCoordinator
from owner.runner import run_workflow
from owner.service import load
import test_owner as owner_fixtures
import test_runner as runner_fixtures
import test_workspace_review as workspace_fixtures


class HoldingBackend(owner_fixtures.FakeBackend):
    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.ratios = [.8]

    def execute(self, kind, context, output):
        if kind == 'bench':
            self.entered.set()
            for _ in range(500):
                context['check_active']()
                if self.release.wait(.01):
                    break
            else:
                raise RuntimeError('synthetic benchmark release not provided')
        return super().execute(kind, context, output)


class ContentionRPC(runner_fixtures.ScriptedRPC):
    def __init__(self, cwd, backend, coordinator):
        super().__init__(cwd)
        self.backend = backend
        self.coordinator = coordinator
        self.command_rpc = workspace_fixtures.ReceiptRPC(coordinator)
        self.checked = asyncio.Event()
        self.stop = asyncio.Event()

    async def request(self, method, params, *, timeout='default'):
        if method == 'command/exec':
            return await self.command_rpc.request(method, params, timeout=timeout)
        if method == 'turn/interrupt':
            self.stop.set()
            return {}
        return await super().request(method, params)

    def terminal(self, tid, turn, status):
        numeric = {'inputTokens': 100, 'cachedInputTokens': 20, 'cacheWriteInputTokens': 0,
                   'outputTokens': 30, 'reasoningOutputTokens': 10, 'totalTokens': 130}
        self.on_event({'method': 'thread/tokenUsage/updated', 'params': {
            'threadId': tid, 'turnId': turn, 'tokenUsage': {'last': numeric, 'total': numeric}}})
        if status == 'completed':
            report = json.dumps({'summary': 'Synthetic contention check completed', 'artifacts': [],
                                 'checks': ['source-bound fake benchmark'], 'limitations': ['No real timing']})
            self.on_event({'method': 'item/completed', 'params': {'threadId': tid, 'turnId': turn,
                'item': {'type': 'agentMessage', 'id': 'report', 'phase': 'final_answer', 'text': report}}})
        self.on_event({'method': 'turn/completed', 'params': {
            'threadId': tid, 'turn': {'id': turn, 'status': status}}})

    async def script(self, tid, turn, task):
        await asyncio.sleep(0)
        role = self.rows[tid]['role']
        try:
            if role == 'measurement':
                built = await self.tool(tid, 'study_dev_build', {'source_hash': self.shared['source']})
                self.shared['measurement'] = await self.tool(tid, 'study_dev_bench', {'build_id': built['operation_id']})
                self.terminal(tid, turn, 'completed')
                return
            status = await self.tool(tid, 'study_owner_status', {})
            self.shared['source'] = status['seed']['source_hash']
            child = await self.tool(tid, 'study_spawn', {'role': 'measurement', 'task': 'synthetic held measurement'})
            while not self.backend.entered.is_set():
                await asyncio.sleep(.001)
            command = asyncio.create_task(self.tool(tid, 'study_workspace_exec', {'command': 'arbitrary synthetic command'}))
            while not self.coordinator.snapshot()['queued']:
                await asyncio.sleep(.001)
            source = str(Path(status['development_store']) / 'snapshots' / self.shared['source'] / 'engine.cpp')
            self.shared['source_read'] = await asyncio.wait_for(self.tool(tid, 'study_workspace_read', {'path': source}), 1)
            self.shared['status_while_measuring'] = await asyncio.wait_for(self.tool(tid, 'study_owner_status', {}), 1)
            self.shared['queued_rpc_calls'] = len(self.command_rpc.calls)
            self.shared['active_while_reading'] = self.coordinator.snapshot()['active']['kind']
            self.backend.release.set()
            self.shared['command'] = await asyncio.wait_for(command, 2)
            await self.wait(tid, child['agent_id'])
            self.checked.set()
            await self.stop.wait()
            self.terminal(tid, turn, 'interrupted')
        except BaseException as exc:
            self.errors.append(repr(exc))
            self.backend.release.set()
            self.checked.set()
            self.failure = 'synthetic_contention_fixture_failed'
            self.terminal(tid, turn, 'failed')


class RunnerContentionReviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_harmless_source_read_and_status_during_worker_benchmark_preserve_first_attempt(self):
        with tempfile.TemporaryDirectory(prefix='v3-independent-contention-') as temporary:
            root = Path(temporary)
            (root / 'task/seed').mkdir(parents=True)
            (root / 'task/seed/engine.cpp').write_text('int source=1;\n')
            (root / 'task/contract').mkdir()
            (root / 'task/contract/SPEC.md').write_text('Synthetic contract')
            backend, coordinator, made = HoldingBackend(), MeasurementCoordinator(), []

            def factory(cwd):
                peer = ContentionRPC(cwd, backend, coordinator)
                made.append(peer)
                return peer

            running = asyncio.create_task(run_workflow(root, root / 'setup/contention', backend,
                load(ROOT / 'owner/config.draft.json'), setup=True, rpc_factory=factory,
                measurement_coordinator=coordinator))
            try:
                for _ in range(2000):
                    if made:
                        break
                    await asyncio.sleep(.001)
                self.assertTrue(made)
                peer = made[0]
                await asyncio.wait_for(peer.checked.wait(), 4)
                self.assertEqual(peer.errors, [])
                self.assertEqual(peer.shared['source_read']['content'], 'int source=1;\n')
                self.assertEqual(peer.shared['active_while_reading'], 'bench')
                self.assertEqual(peer.shared['queued_rpc_calls'], 0)
                self.assertEqual(peer.shared['status_while_measuring']['execution_lane']['active']['kind'], 'bench')
                self.assertEqual(peer.shared['command']['status'], 'ok')
                measured = peer.shared['measurement']
                self.assertEqual(measured['status'], 'pass')
                self.assertEqual(measured['portfolio_speedup'], .8)
                self.assertEqual(measured['measurement_attempt_number'], 1)
                self.assertEqual(measured['measurement_prior_attempt_ids'], [])
                self.assertEqual(measured['ordinary_command_overlap_audit']['ordinary_command_overlaps'], [])
                self.assertEqual(len(peer.command_rpc.calls), 1)
                self.assertEqual(sum(kind == 'bench' for kind, _, _ in backend.calls), 1)
            finally:
                backend.release.set()
                running.cancel()
                owner, telemetry = await asyncio.wait_for(running, 3)
            self.assertEqual(owner.state['status'], 'incomplete')
            self.assertTrue(telemetry['workspace_cleanup']['drained'])
            self.assertEqual(telemetry['total_tokens']['totalTokens'], 260)
            self.assertIsNone(coordinator.snapshot()['active'])
            self.assertIsNone(coordinator.snapshot()['quarantine'])


if __name__ == '__main__':
    unittest.main()
