"""Synthetic command outputs only: exercises timing/profile logic without running it."""
import asyncio
import dataclasses
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from development.core import IntegrityError, file_hash
from development.dispatch import make_dispatcher, tool_specs
from development.native_backend import NativeBackend, NativeConfig, ProcessLimits, paired_bootstrap


class SyntheticNative(NativeBackend):
    def __init__(self, config):
        super().__init__(config)
        self.commands = []
        self.fail_at = None
    def verify(self):
        return {'status': 'pass', 'synthetic': True}
    def _command(self, command, output, context, diagnostic=False):
        output.mkdir(parents=True)
        self.commands.append({'command': command, 'diagnostic': diagnostic, 'path': output})
        status = 'candidate_failure' if self.fail_at == len(self.commands) else 'pass'
        record = {'status': status, 'synthetic': True}
        (output / 'command.json').write_text(json.dumps(record))
        (output / 'stderr.txt').write_text('')
        if '--library' in command:
            library = command[command.index('--library') + 1]
            candidate = str(library).endswith('candidate.so')
            reps = int(command[command.index('--repetitions') + 1]) if '--repetitions' in command else (8 if candidate else 4)
            seconds = 0.8 if candidate else 1.0
            d = {'seconds_per_call': seconds, 'elapsed_seconds': seconds*reps, 'verified_calls': reps+self.config.warmups, 'repetitions': reps, 'sample_target_met': True, 'peak_rss_kib': 128}
            (output / 'stdout.txt').write_text(json.dumps(d))
        else:
            (output / 'stdout.txt').write_text('Synthetic instruction counts, never measured\n')
        for token in command:
            if isinstance(token, str) and token.startswith('--callgrind-out-file='):
                Path(token.split('=', 1)[1] + '.1').write_text('synthetic profile data')
        return record


class SyntheticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fixtures = self.root / 'fixtures'
        self.fixtures.mkdir()
        entries = []
        for i in range(2):
            inp, exp = f'w{i}.in', f'w{i}.out'
            (self.fixtures / inp).write_bytes(b'synthetic input')
            (self.fixtures / exp).write_bytes(b'synthetic expected')
            entries.append({'id': f'w{i}', 'input': inp, 'expected': exp, 'sha256_input': file_hash(self.fixtures / inp), 'sha256_expected': file_hash(self.fixtures / exp)})
        (self.fixtures / 'manifest.json').write_text(json.dumps({'suites': {'development': entries, 'profile': entries}}))
        limits = ProcessLimits((0, 1), 1024**3, 512*1024, 64*1024**2, 30, 30)
        self.cfg = NativeConfig('/unused', '/unused', '/fake/driver', str(self.fixtures), '/fake/valgrind', '/fake/annotate', '/fake/vg', '/fake/debug', limits, limits, {}, paired_blocks=4)
        self.backend = SyntheticNative(self.cfg)
        self.build = self.root / 'build'
        self.build.mkdir()
        (self.build / 'candidate.so').write_bytes(b'fake candidate')
        self.baseline = self.root / 'baseline.so'
        self.baseline.write_bytes(b'fake inherited prototype')
        self.context = {'build_directory': self.build, 'build': {'library': 'candidate.so', 'library_sha256': file_hash(self.build / 'candidate.so')},
                        'baseline': {'path': str(self.baseline), 'library_sha256': file_hash(self.baseline)}, 'request': {'fixture_id': 'w0'}}
        self.out = self.root / 'operation'
        self.out.mkdir()
    def tearDown(self):
        self.tmp.cleanup()

    def test_balanced_pairs_common_batch_frozen_before_scored_commands(self):
        result = self.backend.execute('bench', self.context, self.out)
        self.assertAlmostEqual(result['portfolio_speedup'], 1.25)
        schedule = json.loads((self.out / 'schedule.json').read_text())
        for workload in ('w0', 'w1'):
            self.assertEqual(sum(b['orders'][workload][0] == 'baseline' for b in schedule), 2)
        commands = [c['command'] for c in self.backend.commands]
        self.assertEqual(len(commands), 4 + 4*2*2)
        self.assertTrue(all('--repetitions' not in c for c in commands[:4]))
        self.assertTrue(all(c[c.index('--repetitions')+1] == '8' for c in commands[4:]))
        self.assertFalse(any('accepted' == k for k in result))
        self.assertEqual(len(list(self.out.glob('*/block-*/measurement.json'))), 16)

    def test_profile_uses_diagnostic_limits_and_annotation_is_raw_artifact(self):
        result = self.backend.execute('profile', self.context, self.out)
        self.assertEqual(result['status'], 'pass')
        self.assertTrue(all(c['diagnostic'] for c in self.backend.commands))
        self.assertIn('--instr-atstart=no', self.backend.commands[0]['command'])
        self.assertIn('--auto=no', self.backend.commands[1]['command'])
        self.assertNotIn('portfolio_speedup', result)
        self.assertTrue((self.out / result['annotations'][0]).is_file())

    def test_profile_on_unknown_public_fixture_is_ordinary_failure(self):
        self.context['request']['fixture_id'] = 'assessment-secret'
        result = self.backend.execute('profile', self.context, self.out)
        self.assertEqual(result['status'], 'candidate_failure')
        self.assertFalse(self.backend.commands)

    def test_no_assessment_suite_exposed(self):
        with self.assertRaises(IntegrityError):
            self.backend.fixtures('assessment')

    def test_mutated_public_fixture_rejected_before_native_call(self):
        (self.fixtures / 'w0.in').write_bytes(b'changed')
        with self.assertRaises(IntegrityError):
            self.backend.execute('bench', self.context, self.out)
        self.assertFalse(self.backend.commands)

    def test_mutated_inherited_library_rejected(self):
        self.baseline.write_bytes(b'changed')
        with self.assertRaises(IntegrityError):
            self.backend.execute('bench', self.context, self.out)
        self.assertFalse(self.backend.commands)

    def test_failed_scored_command_retains_prior_measurement_files(self):
        self.backend.fail_at = 8
        result = self.backend.execute('bench', self.context, self.out)
        self.assertEqual(result['status'], 'candidate_failure')
        self.assertEqual(len(self.backend.commands), 8)
        self.assertEqual(len(list(self.out.glob('*/block-*/measurement.json'))), 3)


    def test_memcheck_covers_every_public_profile_family_not_only_smallest(self):
        self.context['request']['fixture_id'] = None
        result = self.backend.execute('memcheck', self.context, self.out)
        self.assertTrue(result['coverage_complete'])
        self.assertEqual(result['planned_fixture_ids'], ['w0', 'w1'])
        self.assertEqual(len(result['probe_records']), 2)
        self.assertTrue(all(c['diagnostic'] for c in self.backend.commands))
        self.assertTrue(all('--error-exitcode=99' in c['command'] for c in self.backend.commands))

    def test_partial_memcheck_never_claims_complete_coverage(self):
        self.context['request']['fixture_id'] = 'w1'
        result = self.backend.execute('memcheck', self.context, self.out)
        self.assertEqual(result['status'], 'pass')
        self.assertFalse(result['coverage_complete'])

    def test_owner_selected_suites_do_not_relabel_assessment_as_development(self):
        manifest = json.loads((self.fixtures / 'manifest.json').read_text())
        manifest['suites']['transfer'] = manifest['suites'].pop('development')
        (self.fixtures / 'manifest.json').write_text(json.dumps(manifest))
        self.backend.config = dataclasses.replace(self.cfg, allowed_suites=('transfer', 'profile'), benchmark_suite='transfer', correctness_suite='transfer', case_seed=2027100999)
        result = self.backend.execute('bench', self.context, self.out)
        self.assertEqual(result['suite'], 'transfer')
        with self.assertRaises(IntegrityError):
            self.backend.fixtures('development')

    def test_joint_block_bootstrap_is_deterministic(self):
        samples = {'one': [{'baseline': x, 'candidate': 1} for x in (1.2, 1.3, 1.1, 1.4)],
                   'two': [{'baseline': x, 'candidate': 1} for x in (0.9, 1.1, 1.2, 1.3)]}
        a = paired_bootstrap(samples, 1000, 123, .9)
        self.assertEqual(a, paired_bootstrap(samples, 1000, 123, .9))
        self.assertIn('complete temporal block', a['unit'])
        with self.assertRaises(IntegrityError):
            paired_bootstrap({'one': samples['one'], 'two': samples['two'][:2]}, 100, 123, .9)


    def test_oracle_status_counts_and_library_must_all_agree(self):
        # No library is loaded here. Deliberately fabricated reports test fail-closed logic.
        base = {'status': 'pass', 'suite': 'development', 'case_seed_namespace': self.cfg.case_seed,
                'library_sha256': self.context['build']['library_sha256'], 'planned_cases': 89, 'attempted_cases': 89,
                'passed': 89, 'failed': 0, 'semantic_failures': 0, 'resource_failures': 0, 'infra_failures': 0,
                'cases': [{'id': f'case{i}', 'status': 'pass', 'max_rss_kib': 100} for i in range(89)]}
        variants = [({'status': 'fail'}, 0), ({'passed': 86}, 0), ({'library_sha256': 'wrong'}, 0),
                    ({'attempted_cases': 86}, 0), ({'planned_cases': 0, 'cases': []}, 0), ({}, 1), ({'case_seed_namespace': -1}, 0)]
        for i, (changes, exit_code) in enumerate(variants):
            output = self.out / str(i)
            output.mkdir()
            report = {**base, **changes}
            def fake(command, directory, context, diagnostic=False, kind=None):
                (output / 'correctness.json').write_text(json.dumps(report))
                return {'status': 'pass', 'exit_code': exit_code}
            self.backend._command = fake
            result = self.backend.test(self.context, output)
            self.assertEqual(result['status'], 'infra_error', (changes, result))

    def test_arbitrary_host_check_not_exposed_to_any_participant_role(self):
        for role in ('lead', 'measurement', 'implementation', 'investigation', 'reviewer'):
            self.assertNotIn('study_dev_check', [s['name'] for s in tool_specs(role)])


    def test_scored_sample_schema_and_frozen_count_are_checked(self):
        valid = {'repetitions': 8, 'verified_calls': 9, 'elapsed_seconds': .08,
                 'seconds_per_call': .01, 'sample_target_met': True, 'peak_rss_kib': 128}
        self.assertTrue(self.backend._validate_sample(valid, 8))
        invalid = [{'repetitions': 1}, {'verified_calls': 8}, {'elapsed_seconds': float('nan')},
                   {'seconds_per_call': .02}, {'peak_rss_kib': float('inf')}, {'sample_target_met': False}]
        for changes in invalid:
            with self.assertRaises(IntegrityError):
                self.backend._validate_sample({**valid, **changes}, 8)

    def test_genuine_scored_under_target_is_flagged_without_adaptive_rerun(self):
        original = self.backend._command
        def under_target(command, output, context, diagnostic=False):
            result = original(command, output, context, diagnostic)
            if '--repetitions' in command:
                path = output / 'stdout.txt'
                row = json.loads(path.read_text())
                row.update(elapsed_seconds=.001, seconds_per_call=.001/row['repetitions'], sample_target_met=False)
                path.write_text(json.dumps(row))
            return result
        self.backend._command = under_target
        result = self.backend.execute('bench', self.context, self.out)
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(len(result['scored_under_target_batches']), 16)
        self.assertEqual(len(self.backend.commands), 20)
        self.assertEqual(result['scored_under_target_policy'], 'retain_and_flag_no_adaptive_retry')


    def test_memcheck_exit99_is_confirmed_error_not_timeout(self):
        self.context['request']['fixture_id'] = None
        original = self.backend._command
        def memory_error(command, output, context, diagnostic=False):
            result = original(command, output, context, diagnostic)
            return {**result, 'status': 'candidate_failure', 'exit_code': 99}
        self.backend._command = memory_error
        result = self.backend.execute('memcheck', self.context, self.out)
        self.assertTrue(result['confirmed_memory_error'])
        self.assertFalse(result['coverage_complete'])

    def test_guard_page_contract_violation_is_confirmed_but_timeout_is_not(self):
        for reason, signal_number, confirmed in [('process_signal', 11, True), ('wall_timeout', None, False)]:
            output = self.out / reason
            output.mkdir()
            cases = [{'id': f'case{i}', 'status': 'pass', 'max_rss_kib': 100} for i in range(88)]
            cases.append({'id': 'oversized_events_unbacked', 'status': 'resource_failure', 'reason': reason, 'signal': signal_number})
            report = {'status': 'fail', 'suite': 'development', 'case_seed_namespace': self.cfg.case_seed,
                      'library_sha256': self.context['build']['library_sha256'], 'planned_cases': 89, 'attempted_cases': 89,
                      'passed': 88, 'failed': 1, 'semantic_failures': 0, 'resource_failures': 1, 'infra_failures': 0, 'cases': cases}
            def fake(command, directory, context, diagnostic=False, kind=None):
                (output / 'correctness.json').write_text(json.dumps(report))
                return {'status': 'candidate_failure', 'exit_code': 1}
            self.backend._command = fake
            result = self.backend.test(self.context, output)
            self.assertEqual(result['confirmed_semantic_failure'], confirmed)

    def test_dispatcher_does_not_accept_actor_or_role_overrides(self):
        called = []
        dispatcher = make_dispatcher(lambda agent: called.append(agent))
        actor = SimpleNamespace(agent_id='worker-a', role='implementation')
        async def call():
            with self.assertRaises(ValueError):
                await dispatcher(actor, 'study_dev_build', {'source_hash': 'x', 'role': 'reviewer'})
            with self.assertRaises(ValueError):
                await dispatcher(actor, 'study_dev_review_evidence', {'build_id': 'x'})
        asyncio.run(call())
        self.assertFalse(called)
        self.assertNotIn('study_dev_review_evidence', [s['name'] for s in tool_specs(actor.role)])
        self.assertTrue(all(s['inputSchema']['additionalProperties'] is False for s in tool_specs('reviewer')))


if __name__ == '__main__':
    unittest.main(verbosity=2)
