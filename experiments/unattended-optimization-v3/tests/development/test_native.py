"""Owner-requested non-inference native build/correctness smoke, no timings/profile.

Retains all setup and command records under tests/development/native-smoke-*.
"""
import dataclasses
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from development.core import ActorGrant, DevelopmentService, Limits, file_hash
from development.native_backend import NativeBackend, NativeConfig, ProcessLimits, run_process
spec = importlib.util.spec_from_file_location('generate_v2_public', ROOT / 'development/native/generate_public.py')
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class Authority:
    def __init__(self, grant):
        self.g = grant
        self.heads = {}
    def active_grant(self):
        return self.g
    def expected_head(self, key):
        return self.heads.get(key)
    def commit_head(self, key, old, new):
        if self.heads.get(key) != old:
            raise AssertionError('head mismatch')
        self.heads[key] = new


class NativeSmoke(unittest.TestCase):
    def test_build_repair_canonical_correctness_and_custom_check(self):
        out = ROOT / 'tests/development' / ('native-smoke-' + str(time.time_ns()))
        out.mkdir()
        print('RETAINED_NATIVE_SMOKE=' + str(out), flush=True)
        fixture_root = out / 'public-fixtures'
        generator.generate(ROOT / 'development/native/definitions.smoke.json', fixture_root)
        cpus = tuple(sorted(os.sched_getaffinity(0))[:2])
        limits = ProcessLimits(cpus, 1024**3, 512*1024, 64*1024**2, 120, 150)
        diag = ProcessLimits(cpus, 4*1024**3, 2*1024**2, 64*1024**2, 180, 200)
        vg = Path('/workspace/scratch/eeae3ae186b3/profiling-tools/root')
        driver = out / 'driver'
        driver_record = run_process(['/usr/bin/g++-14', '-std=c++20', '-O2', '-g', '-I', str(ROOT / 'task/contract'), '-I', str(vg / 'usr/include'), str(ROOT / 'development/native/driver.cpp'), '-ldl', '-o', str(driver)], out / 'driver-build', out, limits, {'check_active': lambda: None})
        self.assertEqual(driver_record['status'], 'pass')
        cfg = NativeConfig(str(ROOT / 'task/contract'), '/usr/bin/g++-14', str(driver), str(fixture_root), str(vg / 'usr/bin/valgrind'), str(vg / 'usr/bin/callgrind_annotate'), str(vg / 'usr/libexec/valgrind'), str(vg), limits, diag, {})
        unpinned = NativeBackend(cfg)
        cfg = dataclasses.replace(cfg, pinned_files={p: file_hash(p) for p in unpinned.required_pins()})
        backend = NativeBackend(cfg)
        (out / 'native-config.json').write_text(json.dumps(dataclasses.asdict(cfg), indent=2) + '\n')
        candidate = out / 'candidate'
        candidate.mkdir()
        (candidate / 'engine.cpp').write_text('this is a deliberate setup-only syntax error\n')
        grant = ActorGrant('setup-native-smoke', 'setup-owner', 'setup-native', None, 'setup_owner', 'a'*64, 'setup-boot', (str(candidate),), 'unconfigured-before-seed-build', 'unconfigured-before-seed-build', '/not-used-no-benchmark')
        authority = Authority(grant)
        service = DevelopmentService(out / 'evidence', authority, backend, Limits(10*1024**2, 64*1024, str(out / 'native.lock')))
        bad = service.run('build', source_hash=service.snapshot(candidate)['source_hash'])
        self.assertEqual(bad['status'], 'candidate_failure')
        shutil.copyfile(ROOT / 'task/seed/engine.cpp', candidate / 'engine.cpp')
        built = service.run('build', source_hash=service.snapshot(candidate)['source_hash'])
        self.assertEqual(built['status'], 'pass')
        result = service.run('test', build_id=built['operation_id'])
        self.assertEqual(result['status'], 'pass', result)
        self.assertEqual(result['summary']['passed'], result['summary']['planned_cases'])
        custom = service.run('check', source_hash=built['source_hash'], argv=['/usr/bin/g++-14', '--version'])
        self.assertEqual(custom['status'], 'pass')
        # A compiled wrong-result candidate must fail the actual independent oracle.
        (candidate / 'engine.cpp').write_text('#include "engine.h"\nextern "C" int engine_run(const Event*,size_t,const RangeQuery*,size_t,RangeResult*) { return 0; }\n')
        wrong = service.run('build', source_hash=service.snapshot(candidate)['source_hash'])
        self.assertEqual(wrong['status'], 'pass')
        rejected = service.run('test', build_id=wrong['operation_id'])
        self.assertEqual(rejected['status'], 'candidate_failure')
        self.assertGreater(rejected['summary']['failed'], 0)
        # Mutant scans invalid oversized inputs before checking bounds. Old
        # fully-backed overcount probes permit this; guard pages must catch it.
        original = (ROOT / 'task/seed/engine.cpp').read_text()
        marker = '    if (event_count > 1000000 || query_count > 4096 ||'
        unsafe = """    if (event_count > 1000000) {
        for (std::size_t i = 0; i < event_count; ++i) { volatile auto probe = events[i].stream; (void)probe; }
        return 1;
    }
    if (query_count > 4096) {
        for (std::size_t i = 0; i < query_count; ++i) { volatile auto probe = queries[i].lo; (void)probe; }
        return 1;
    }
"""
        self.assertIn(marker, original)
        (candidate / 'engine.cpp').write_text(original.replace(marker, unsafe + marker))
        guard_mutant = service.run('build', source_hash=service.snapshot(candidate)['source_hash'])
        self.assertEqual(guard_mutant['status'], 'pass')
        guard_result = service.run('test', build_id=guard_mutant['operation_id'])
        self.assertEqual(guard_result['status'], 'candidate_failure')
        guard_report = json.loads((Path(guard_result['artifact_directory']) / 'correctness.json').read_text())
        failures = {case['id']: case for case in guard_report['cases'] if case['status'] != 'pass'}
        self.assertEqual(set(failures), {'oversized_events_unbacked', 'oversized_queries_unbacked'})
        self.assertTrue(all(case.get('signal') == 11 for case in failures.values()))
        (out / 'guard-page-control.json').write_text(json.dumps({'status': 'pass', 'correct_seed_passed': result['summary'], 'scan_before_bounds_mutant': guard_result['summary'], 'failed_cases': failures}, indent=2) + '\n')
        service.append_journal('Setup-only compiler repair, seed correctness and wrong-result rejection verified. No native benchmarks or profiling performed.', [bad['operation_id'], result['operation_id'], rejected['operation_id']])
        (out / 'summary.json').write_text(json.dumps({'status': 'pass', 'seed_correctness': result['summary'], 'wrong_candidate': rejected['summary'], 'scan_before_bounds_mutant': guard_result['summary'], 'operations': service.index()['operations'], 'not_run': ['benchmark', 'profile', 'model inference']}, indent=2) + '\n')


if __name__ == '__main__':
    unittest.main(verbosity=2)
