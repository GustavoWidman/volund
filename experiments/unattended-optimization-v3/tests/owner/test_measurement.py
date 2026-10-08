"""Synthetic scheduling/recovery tests; no models or measured native work."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from development.core import ActorGrant, Cancelled, DevelopmentService, IntegrityError, Limits
from development.native_backend import ProcessLimits, run_process
from owner.measurement import CoordinatedBackend, MeasurementCoordinator, MeasurementCoordinationError
from owner.overlap import CommandIntervals, MeasurementInterrupted
import test_owner as owner_fixtures


def command(intervals, method, item='unleased-command'):
    intervals.event({'method': 'item/' + method,
                     'params': {'threadId': 'lead', 'item': {'id': item, 'type': 'commandExecution'}}})


class Authority:
    def __init__(self, root):
        self.current = ActorGrant('campaign', 'worker', 'job', 'lead', 'worker', 'a' * 64,
                                 'boot', (str(root),), 'b' * 64, 'c' * 64, '/synthetic/seed.so')
        self.heads = {}
        self.cancelled = False

    def active_grant(self):
        if self.cancelled:
            raise Cancelled('explicit campaign stop')
        return self.current

    def expected_head(self, key):
        return self.heads.get(key)

    def commit_head(self, key, old, new):
        if self.heads.get(key) != old:
            raise IntegrityError('changed head')
        self.heads[key] = new


class ScriptedBackend:
    def __init__(self):
        self.behaviors = []
        self.bench_calls = 0

    def execute(self, kind, context, out):
        (out / 'stdout.txt').write_text('Synthetic only; not benchmark evidence\n')
        if kind == 'build':
            (out / 'candidate.so').write_text('FAKE BINARY')
            return {'status': 'pass', 'library': 'candidate.so'}
        if kind == 'bench':
            self.bench_calls += 1
            behavior = self.behaviors.pop(0) if self.behaviors else {'status': 'pass', 'portfolio_speedup': .8}
            if isinstance(behavior, BaseException):
                raise behavior
            if callable(behavior):
                return behavior(context, out)
            return behavior
        return {'status': 'pass'}


class MeasurementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        candidate = self.root / 'candidate'
        candidate.mkdir()
        (candidate / 'engine.cpp').write_text('int engine = 1;\n')
        self.authority = Authority(candidate)
        self.intervals = CommandIntervals()
        self.coordinator = MeasurementCoordinator(self.intervals)
        self.raw = ScriptedBackend()
        self.service = DevelopmentService(self.root / 'evidence', self.authority,
                    CoordinatedBackend(self.raw, self.coordinator),
                    Limits(100000, 10000, str(self.root / 'native.lock')))
        source = self.service.snapshot(candidate)['source_hash']
        self.build = self.service.run('build', source_hash=source)

    def bench(self):
        return self.service.run('bench', build_id=self.build['operation_id'])

    def contaminated(self, result=None):
        def execute(context, out):
            command(self.intervals, 'started', str(self.raw.bench_calls))
            command(self.intervals, 'completed', str(self.raw.bench_calls))
            return result or {'status': 'pass', 'portfolio_speedup': 99}
        return execute

    def test_retained_overlap_attempt_retries_same_binding_and_accepts_first_valid_bad_score(self):
        self.raw.behaviors = [self.contaminated(), {'status': 'pass', 'portfolio_speedup': .6},
                              {'status': 'pass', 'portfolio_speedup': 2}]
        final = self.bench()
        self.assertEqual(self.raw.bench_calls, 2)
        self.assertEqual(final['portfolio_speedup'], .6)
        self.assertEqual(final['measurement_attempt_number'], 2)
        prior_id, = final['measurement_prior_attempt_ids']
        prior = json.loads((self.service.store / 'operations' / prior_id / 'result.json').read_text())
        self.assertEqual(prior['status'], 'infra_error')
        self.assertEqual(prior['measurement_id'], final['measurement_id'])
        for key in ('source_hash', 'build_id', 'reference', 'reference_id', 'authority_record_sha256'):
            self.assertEqual(prior[key], final[key])
        self.assertEqual(final['measurement_retry_reason'], 'competing_study_command_execution')
        self.assertEqual(len(self.service.index()['operations']), 3)

    def test_many_invalid_attempts_have_no_arbitrary_retry_cap(self):
        self.raw.behaviors = [self.contaminated() for _ in range(7)] + [{'status': 'pass'}]
        final = self.bench()
        self.assertEqual(final['measurement_attempt_number'], 8)
        self.assertEqual(len(final['measurement_prior_attempt_ids']), 7)

    def test_attested_interruption_retains_partial_output_and_retries_after_cleanup(self):
        def interrupted(context, out):
            (out / 'partial-pairs.json').write_text('{"synthetic":true}')
            raise MeasurementInterrupted(observer='synthetic-owner-monitor', event_id='preemption-1', cleanup_confirmed=True)
        self.raw.behaviors = [interrupted, {'status': 'pass', 'portfolio_speedup': .9}]
        final = self.bench()
        prior = self.service.store / 'operations' / final['measurement_prior_attempt_ids'][0]
        self.assertTrue((prior / 'partial-pairs.json').exists())
        audit = json.loads((prior / 'ordinary-command-overlap.json').read_text())
        self.assertTrue(audit['external_interruption']['cleanup_confirmed'])
        self.assertEqual(final['measurement_retry_reason'], 'attested_external_interruption')

    def test_candidate_resource_and_valid_under_target_outcomes_never_retry(self):
        for outcome in ({'status': 'candidate_failure'}, {'status': 'timeout'},
                        {'status': 'watchdog_expired'}, {'status': 'infra_error'},
                        {'status': 'pass', 'portfolio_speedup': .5, 'scored_under_target_batches': [{'block': 1}]}):
            with self.subTest(outcome=outcome):
                before = self.raw.bench_calls
                self.raw.behaviors = [dict(outcome)]
                result = self.bench()
                self.assertEqual(self.raw.bench_calls, before + 1)
                self.assertEqual(result['status'], outcome['status'])

    def test_overlap_cannot_hide_candidate_or_confirmed_correctness_failure(self):
        for outcome in ({'status': 'candidate_failure'}, {'status': 'timeout'},
                        {'status': 'candidate_failure', 'confirmed_semantic_failure': True},
                        {'status': 'candidate_failure', 'confirmed_memory_error': True}):
            with self.subTest(outcome=outcome):
                before = self.raw.bench_calls
                self.raw.behaviors = [self.contaminated(outcome)]
                result = self.bench()
                self.assertEqual(self.raw.bench_calls, before + 1)
                self.assertEqual(result['status'], outcome['status'])
                self.assertNotIn('measurement_retry_authorized', result)

    def test_source_integrity_failure_still_raises_without_retry(self):
        def mutate(context, out):
            self.contaminated()(context, out)
            (context['source_directory'] / 'engine.cpp').write_text('changed immutable source')
            return {'status': 'pass'}
        self.raw.behaviors = [mutate]
        with self.assertRaises(IntegrityError):
            self.bench()
        self.assertEqual(self.raw.bench_calls, 1)
        self.assertIsNone(self.coordinator.snapshot()['active'])

    def test_unknown_interruption_is_retained_then_raised_without_retry(self):
        self.raw.behaviors = [RuntimeError('unknown backend failure')]
        with self.assertRaisesRegex(RuntimeError, 'unknown backend failure'):
            self.bench()
        self.assertEqual(self.raw.bench_calls, 1)
        rows = self.service.index()['operations']
        self.assertEqual(rows[-1]['status'], 'infra_error')
        self.assertTrue((Path(rows[-1]['artifact_directory']) / 'execution-lease.json').exists())

    def test_explicit_stop_after_invalid_attempt_prevents_retry(self):
        def stop(context, out):
            result = self.contaminated()(context, out)
            self.authority.cancelled = True
            return result
        self.raw.behaviors = [stop]
        with self.assertRaises(Cancelled):
            self.bench()
        self.assertEqual(self.raw.bench_calls, 1)
        results = list((self.service.store / 'operations').glob('*/result.json'))
        self.assertEqual(len(results), 2)

    def test_unattested_flags_cannot_authorize_retry(self):
        self.raw.behaviors = [{'status': 'infra_error', 'measurement_retry_authorized': True,
                               'measurement_invalidated': 'competing_study_command_execution'}]
        self.assertEqual(self.bench()['status'], 'infra_error')
        self.assertEqual(self.raw.bench_calls, 1)

    def test_native_cleanup_failure_quarantines_without_retry(self):
        def cleanup_failed(context, out):
            (out / 'command.json').write_text(json.dumps({'exit_code': 0, 'cleanup': {
                'tracked_processes_exited': False, 'tracking_scan_failures': 0}}))
            return self.contaminated()(context, out)
        self.raw.behaviors = [cleanup_failed]
        result = self.bench()
        self.assertTrue(result['resource_cleanup_unresolved'])
        self.assertFalse(result['measurement_retry_authorized'])
        self.assertEqual(self.raw.bench_calls, 1)
        self.assertEqual(self.coordinator.snapshot()['quarantine']['reason'], 'native process cleanup unresolved')
        with self.assertRaises(MeasurementCoordinationError):
            self.bench()

    def test_missing_native_receipt_after_exec_spec_quarantines(self):
        def missing(context, out):
            (out / 'exec-spec.json').write_text('{"synthetic":true}')
            return {'status': 'infra_error'}
        self.raw.behaviors = [missing]
        self.assertTrue(self.bench()['resource_cleanup_unresolved'])
        self.assertIsNotNone(self.coordinator.snapshot()['quarantine'])

    def test_malformed_native_receipt_is_not_assumed_failed_popen(self):
        def malformed(context, out):
            (out / 'command.json').write_text('{}')
            return {'status': 'infra_error'}
        self.raw.behaviors = [malformed]
        self.assertTrue(self.bench()['resource_cleanup_unresolved'])

    def test_explicit_failed_popen_receipt_does_not_quarantine(self):
        def failed_popen(context, out):
            (out / 'exec-spec.json').write_text('{"synthetic":true}')
            (out / 'command.json').write_text(json.dumps({'process_started': False,
                                                         'status': 'infra_error', 'error': 'synthetic Popen failure'}))
            return {'status': 'infra_error'}
        self.raw.behaviors = [failed_popen]
        self.assertEqual(self.bench()['status'], 'infra_error')
        self.assertIsNone(self.coordinator.snapshot()['quarantine'])


class CoordinatorTests(unittest.TestCase):
    def test_compile_lead_and_reviewer_jobs_wait_fifo_while_bounded_source_read_continues(self):
        coordinator = MeasurementCoordinator()
        admitted = []
        threads = []
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'engine.cpp'
            path.write_text('source available during timing')
            with coordinator.lease('bench', actor_id='measurement'):
                for actor in ('lead', 'reviewer', 'implementation'):
                    def run(actor=actor):
                        with coordinator.lease('workspace_exec', actor_id=actor):
                            admitted.append(actor)
                    thread = threading.Thread(target=run)
                    thread.start(); threads.append(thread)
                    deadline = time.monotonic() + 2
                    while len(coordinator.snapshot()['queued']) != len(threads) and time.monotonic() < deadline:
                        time.sleep(.005)
                    self.assertEqual(len(coordinator.snapshot()['queued']), len(threads))
                with path.open() as source:
                    self.assertEqual(source.read(100), 'source available during timing')
                self.assertFalse(admitted)
            for thread in threads:
                thread.join(2)
                self.assertFalse(thread.is_alive())
        self.assertEqual(admitted, ['lead', 'reviewer', 'implementation'])

    def test_benchmark_waits_for_observed_unleased_command_to_finish(self):
        intervals = CommandIntervals()
        coordinator = MeasurementCoordinator(intervals)
        command(intervals, 'started')
        acquired = threading.Event()
        def run():
            with coordinator.lease('bench', actor_id='reviewer'):
                acquired.set()
        thread = threading.Thread(target=run); thread.start()
        self.assertFalse(acquired.wait(.04))
        command(intervals, 'completed')
        self.assertTrue(acquired.wait(2)); thread.join(2)

    def test_quarantine_blocks_new_resource_jobs_but_keeps_reason(self):
        coordinator = MeasurementCoordinator()
        with coordinator.lease('workspace_exec', actor_id='lead'):
            coordinator.quarantine('unconfirmed descendant exit', {'process_id': 'synthetic'})
        with self.assertRaises(MeasurementCoordinationError):
            with coordinator.lease('bench', actor_id='reviewer'):
                self.fail('must not admit uncertain timing')
        self.assertEqual(coordinator.snapshot()['quarantine']['reason'], 'unconfirmed descendant exit')
        self.assertFalse(coordinator.snapshot()['queued'])

    def test_unleased_command_missing_completion_at_thread_end_quarantines(self):
        intervals = CommandIntervals(); coordinator = MeasurementCoordinator(intervals)
        command(intervals, 'started')
        intervals.event({'method': 'turn/completed', 'params': {'threadId': 'lead', 'turn': {'status': 'completed'}}})
        with self.assertRaisesRegex(MeasurementCoordinationError, 'unleased command cleanup unresolved'):
            with coordinator.lease('bench', actor_id='reviewer'):
                self.fail('missing completion must not hang or permit timing')
        self.assertEqual(len(coordinator.snapshot()['quarantine']['evidence']['commands']), 1)

    def test_async_cancelled_waiter_does_not_leak_queue_or_lease(self):
        async def exercise():
            coordinator = MeasurementCoordinator()
            held = coordinator.acquire('bench', actor_id='measurement')
            async def waiting():
                async with coordinator.async_lease('workspace_exec', actor_id='lead'):
                    self.fail('cancelled waiter was admitted')
            task = asyncio.create_task(waiting())
            while not coordinator.snapshot()['queued']:
                await asyncio.sleep(.005)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertFalse(coordinator.snapshot()['queued'])
            coordinator.release(held)
            async with coordinator.async_lease('bench', actor_id='reviewer'):
                self.assertEqual(coordinator.snapshot()['active']['actor_id'], 'reviewer')
            self.assertIsNone(coordinator.snapshot()['active'])
        asyncio.run(exercise())

    def test_async_body_cleanup_finishes_before_lease_released(self):
        async def exercise():
            coordinator = MeasurementCoordinator()
            entered = asyncio.Event(); cleaned = asyncio.Event()
            async def running():
                async with coordinator.async_lease('workspace_exec', actor_id='lead'):
                    entered.set()
                    try:
                        await asyncio.Event().wait()
                    finally:
                        await asyncio.sleep(.01)
                        self.assertIsNotNone(coordinator.snapshot()['active'])
                        cleaned.set()
            task = asyncio.create_task(running()); await entered.wait(); task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(cleaned.is_set())
            self.assertIsNone(coordinator.snapshot()['active'])
        asyncio.run(exercise())

    def test_async_cancellation_after_admission_before_delivery_releases_abandoned_lease(self):
        acquired = threading.Event(); return_receipt = threading.Event()
        class PausedDelivery(MeasurementCoordinator):
            def acquire(self, *args, **kwargs):
                receipt = super().acquire(*args, **kwargs)
                acquired.set()
                if not return_receipt.wait(2):
                    self.release(receipt)
                    raise RuntimeError('synthetic test delivery timeout')
                return receipt
        async def exercise():
            coordinator = PausedDelivery()
            async def running():
                async with coordinator.async_lease('workspace_exec', actor_id='lead'):
                    self.fail('cancelled acquisition must not enter caller body')
            task = asyncio.create_task(running())
            self.assertTrue(await asyncio.to_thread(acquired.wait, 2))
            task.cancel(); return_receipt.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertIsNone(coordinator.snapshot()['active'])
            self.assertFalse(coordinator.snapshot()['queued'])
        asyncio.run(exercise())


class AutomaticTrajectoryTests(unittest.TestCase):
    def test_second_promotion_trajectory_retries_without_rollback_or_reselection(self):
        fixture = owner_fixtures.OwnerIntegration(methodName='test_independent_exact_hash_promotion_and_seed_trajectory')
        fixture.setUp(); self.addCleanup(fixture.tearDown)
        intervals = CommandIntervals(); coordinator = MeasurementCoordinator(intervals)
        original = fixture.backend.execute
        invalidated = []
        def execute(kind, context, out):
            result = original(kind, context, out)
            if kind == 'bench' and context['grant'].role == 'owner' and not invalidated:
                command(intervals, 'started', 'lead-unleased-compile')
                command(intervals, 'completed', 'lead-unleased-compile')
                invalidated.append(context['request']['operation_id'])
            return result
        fixture.backend.execute = execute
        fixture.owner.backend = CoordinatedBackend(fixture.backend, coordinator)
        fixture.test_independent_exact_hash_promotion_and_seed_trajectory()
        trajectory = fixture.owner.state['trajectories'][-1]
        result = json.loads((fixture.owner.store / 'operations' / trajectory['operation_id'] / 'result.json').read_text())
        self.assertEqual(result['measurement_attempt_number'], 2)
        self.assertEqual(result['measurement_prior_attempt_ids'], invalidated)
        self.assertEqual(fixture.owner.state['status'], 'investigating')
        self.assertEqual(len(fixture.owner.state['promotions']), 2)


class NativeReceiptTests(unittest.TestCase):
    """Mock subprocesses only; verifies actual native-wrapper receipt schema."""
    def limits(self):
        return ProcessLimits((0,), 1024**3, 512*1024, 64*1024**2, 30, 30)

    def test_native_failed_popen_receipt_explicitly_has_no_started_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'failed'
            with patch('development.native_backend.subprocess.Popen', side_effect=OSError('synthetic launch failure')):
                with self.assertRaises(OSError):
                    run_process(['synthetic-command'], out, Path(tmp), self.limits(), {'check_active': lambda: None})
            record = json.loads((out / 'command.json').read_text())
            self.assertIs(record['process_started'], False)
            self.assertNotIn('process_pid', record)
            wrapper = CoordinatedBackend(ScriptedBackend(), MeasurementCoordinator())
            self.assertTrue(wrapper._check_cleanup_receipts(Path(tmp)))

    def test_cancellation_before_popen_retains_no_process_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'cancelled'
            def cancelled():
                raise Cancelled('explicit stop before launch')
            with patch('development.native_backend.subprocess.Popen') as popen:
                result = run_process(['synthetic-command'], out, Path(tmp), self.limits(), {'check_active': cancelled})
                popen.assert_not_called()
            self.assertEqual(result['status'], 'cancelled')
            self.assertIs(result['process_started'], False)
            wrapper = CoordinatedBackend(ScriptedBackend(), MeasurementCoordinator())
            self.assertTrue(wrapper._check_cleanup_receipts(Path(tmp)))

    def test_native_started_process_receipt_contains_root_and_clean_exit_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'started'
            process = SimpleNamespace(pid=424242, returncode=None)
            cleanup = {'tracked_processes_exited': True, 'tracking_scan_failures': 0,
                       'tracked_processes': [{'pid': process.pid, 'start_time_ticks': 123,
                                              'exit_observed': True, 'signal_denied': False}]}
            tracker = SimpleNamespace(refresh=lambda **kw: None, signal_all=lambda sig: None,
                                      all_exited=lambda: True, finish=lambda: cleanup)
            usage = SimpleNamespace(ru_maxrss=100, ru_utime=.01, ru_stime=.01)
            with patch('development.native_backend.subprocess.Popen', return_value=process), \
                 patch('development.native_backend.DescendantTracker', return_value=tracker), \
                 patch('development.native_backend.os.wait4', return_value=(process.pid, 0, usage)), \
                 patch('development.native_backend.os.killpg'):
                result = run_process(['synthetic-command'], out, Path(tmp), self.limits(), {'check_active': lambda: None})
            self.assertEqual(result['status'], 'pass')
            self.assertIs(result['process_started'], True)
            self.assertEqual(result['process_pid'], process.pid)
            wrapper = CoordinatedBackend(ScriptedBackend(), MeasurementCoordinator())
            self.assertTrue(wrapper._check_cleanup_receipts(Path(tmp)))


if __name__ == '__main__':
    unittest.main(verbosity=2)
