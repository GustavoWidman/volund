"""Independent final-assessment integration checks; synthetic, no inference/timing."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests/evaluation'))

from development.core import Cancelled, file_hash
from evaluation.run import assess
from owner.measurement import MeasurementCoordinator
from owner.overlap import MeasurementInterrupted
import test_final as final_fixtures


def wait_until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError('synthetic synchronization did not reach expected state')
        time.sleep(.001)


class FinalCoordinationReviewTests(unittest.TestCase):
    def setUp(self):
        self.fixture = final_fixtures.FinalTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.coordinator = MeasurementCoordinator()
        self.bench_calls = []
        self.all_calls = []
        self.behaviors = []
        self.cancelled = False
        review = self

        class Backend(final_fixtures.FakeBackend):
            def execute(self, kind, context, output):
                lease = review.coordinator.snapshot()['active']
                review.all_calls.append((kind, self.config.benchmark_suite, copy.deepcopy(lease)))
                if kind == 'bench':
                    review.bench_calls.append({
                        'stratum': self.config.benchmark_suite,
                        'source': str(context['source_directory']),
                        'build': str(context['build_directory']),
                        'baseline': dict(context['baseline']),
                        'request': dict(context['request']),
                        'output': output,
                    })
                    if review.behaviors:
                        behavior = review.behaviors.pop(0)
                        if isinstance(behavior, BaseException):
                            raise behavior
                        if callable(behavior):
                            return behavior(context, output)
                        return behavior
                return super().execute(kind, context, output)

        self.backend = Backend

    def assess(self):
        def check_cancelled():
            if self.cancelled:
                raise Cancelled('synthetic explicit owner stop')

        with patch('evaluation.run.NativeBackend', self.backend):
            return assess(self.fixture.root, self.fixture.paths, self.fixture.configs,
                          self.fixture.root / 'assessment/final', verify_frozen=lambda: None,
                          check_cancelled=check_cancelled, measurement_coordinator=self.coordinator)

    def overlap(self, result=None):
        def behavior(context, output):
            identifier = str(len(self.bench_calls))
            for event in ('started', 'completed'):
                self.coordinator.commands.event({'method': 'item/' + event,
                    'params': {'threadId': 'synthetic-unleased-command',
                               'item': {'id': identifier, 'type': 'commandExecution'}}})
            return result or {'status': 'pass', 'portfolio_speedup': 100}
        return behavior

    def final_report(self):
        return json.loads((self.fixture.root / 'assessment/final/report.json').read_text())

    def test_all_final_operations_share_supplied_lane_and_wait_for_workspace_job(self):
        held = self.coordinator.acquire('workspace_exec', actor_id='lead')
        values, failures = [], []

        def run():
            try:
                values.append(self.assess())
            except BaseException as exc:
                failures.append(exc)

        worker = threading.Thread(target=run)
        worker.start()
        try:
            wait_until(lambda: self.coordinator.snapshot()['queued'])
            self.assertEqual(self.all_calls, [])
        finally:
            self.coordinator.release(held)
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])
        report, = values
        self.assertEqual(report['status'], 'complete')
        self.assertEqual({kind for kind, _, _ in self.all_calls}, {'build', 'test', 'memcheck', 'bench'})
        self.assertEqual({suite for _, suite, _ in self.all_calls}, {'transfer', 'shift'})
        for kind, _, active in self.all_calls:
            self.assertIsNotNone(active)
            self.assertEqual((active['kind'], active['actor_id']), (kind, 'final-assessment-owner'))
        for operation in report['operations']:
            lease = operation['execution_lease']
            self.assertIsNotNone(lease['released_monotonic'])
            self.assertGreaterEqual(lease['released_monotonic'], lease['admitted_monotonic'])
        self.assertIsNone(self.coordinator.snapshot()['active'])

    def test_retry_retains_attempt_and_first_valid_poor_score_unchanged_inputs(self):
        self.behaviors = [self.overlap(), {'status': 'pass', 'portfolio_speedup': .6}]
        report = self.assess()
        first = report['rows'][0]
        self.assertEqual(first['speedup'], .6)
        self.assertEqual(first['measurement_attempt_number'], 2)
        self.assertEqual(len(self.bench_calls), 7)
        previous, selected = self.bench_calls[:2]
        for key in ('stratum', 'source', 'build', 'baseline'):
            self.assertEqual(previous[key], selected[key])
        self.assertEqual(previous['request']['measurement_id'], selected['request']['measurement_id'])
        self.assertEqual(first['measurement_prior_attempt_ids'], ['campaign-1/bench-transfer'])
        self.assertEqual(first['evidence'], 'campaign-1/bench-transfer-attempt-000002')
        root = self.fixture.root / 'assessment/final'
        old = json.loads((previous['output'] / 'result.json').read_text())
        new = json.loads((selected['output'] / 'result.json').read_text())
        self.assertEqual(old['status'], 'infra_error')
        self.assertEqual(old['portfolio_speedup'], 100)
        for key in ('source_hash', 'input_library_sha256', 'reference', 'configuration_sha256'):
            self.assertEqual(old[key], new[key])
        for operation in report['operations']:
            self.assertEqual(file_hash(root / operation['files_manifest']), operation['files_manifest_sha256'])

    def test_retry_rejoins_fifo_behind_pending_workspace_job(self):
        admitted, thread = [], None

        def competitor():
            with self.coordinator.lease('workspace_exec', actor_id='worker'):
                admitted.append('worker')

        def first(context, output):
            nonlocal thread
            thread = threading.Thread(target=competitor)
            thread.start()
            wait_until(lambda: self.coordinator.snapshot()['queued'])
            return self.overlap()(context, output)

        def second(context, output):
            self.assertEqual(admitted, ['worker'])
            return {'status': 'pass', 'portfolio_speedup': .7}

        self.behaviors = [first, second]
        try:
            self.assertEqual(self.assess()['rows'][0]['speedup'], .7)
        finally:
            if thread is not None:
                thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_attested_interruption_retains_partial_evidence(self):
        def interrupted(context, output):
            (output / 'partial-synthetic.json').write_text('{"fixture":true}')
            raise MeasurementInterrupted(observer='independent-test', event_id='external-1', cleanup_confirmed=True)
        self.behaviors = [interrupted, {'status': 'pass', 'portfolio_speedup': .8}]
        row = self.assess()['rows'][0]
        self.assertEqual(row['measurement_attempt_number'], 2)
        prior = self.fixture.root / 'assessment/final' / row['measurement_prior_attempt_ids'][0]
        self.assertTrue((prior / 'partial-synthetic.json').is_file())
        self.assertEqual(json.loads((prior / 'result.json').read_text())['measurement_invalidated'],
                         'attested_external_interruption')

    def test_candidate_failure_with_overlap_is_not_retried_or_reclassified(self):
        self.behaviors = [self.overlap({'status': 'candidate_failure', 'confirmed_semantic_failure': True})]
        report = self.assess()
        self.assertEqual(len(self.bench_calls), 6)
        row = report['rows'][0]
        self.assertEqual(row['status'], 'measurement_failed')
        self.assertEqual(row['measurement_attempt_number'], 1)
        retained = json.loads((self.bench_calls[0]['output'] / 'result.json').read_text())
        self.assertEqual(retained['status'], 'candidate_failure')

    def test_unknown_interruption_blocks_and_preserves_single_attempt(self):
        self.behaviors = [RuntimeError('synthetic transport loss')]
        with self.assertRaisesRegex(RuntimeError, 'synthetic transport loss'):
            self.assess()
        self.assertEqual(len(self.bench_calls), 1)
        self.assertEqual(self.final_report()['status'], 'blocked')
        self.assertTrue((self.bench_calls[0]['output'] / 'result.json').is_file())
        self.assertIsNone(self.coordinator.snapshot()['active'])

    def test_explicit_cancellation_prevents_recovery(self):
        def interrupted(context, output):
            result = self.overlap()(context, output)
            self.cancelled = True
            return result
        self.behaviors = [interrupted]
        with self.assertRaises(Cancelled):
            self.assess()
        self.assertEqual(len(self.bench_calls), 1)
        self.assertEqual(self.final_report()['status'], 'blocked')
        self.assertIsNone(self.coordinator.snapshot()['active'])

    def test_unresolved_native_cleanup_prevents_later_admission(self):
        def unsealed(context, output):
            (output / 'exec-spec.json').write_text('{"fixture":true}')
            return {'status': 'pass', 'portfolio_speedup': 100}
        self.behaviors = [unsealed]
        with self.assertRaisesRegex(RuntimeError, 'measurement_resource_quarantined'):
            self.assess()
        self.assertEqual(len(self.bench_calls), 1)
        self.assertIsNotNone(self.coordinator.snapshot()['quarantine'])
        report = self.final_report()
        self.assertEqual(report['status'], 'blocked')
        row = report['rows'][0]
        self.assertEqual(row['status'], 'measurement_failed')
        self.assertEqual(row['measurement_attempt_number'], 1)


if __name__ == '__main__':
    unittest.main()
