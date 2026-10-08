#!/usr/bin/env python3
"""Isolated correctness/resource gate; no timing results or scoring here.

Every planned case runs in a fresh process and receives the same fixed limits.
All cases are attempted regardless of earlier failures. Stateful and concurrent
probes deliberately make several invocations within one isolated process.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import ctypes as C
import hashlib
import json
import mmap
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import threading
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'oracle'))
from cases import plan, build, randomized
from reference import ALL, U64, I32_MAX, direct, decode_input, decode_expected, sha256

class Event(C.Structure):
    _fields_ = [('timestamp', C.c_uint64), ('stream', C.c_uint32), ('value', C.c_int32)]
class Query(C.Structure):
    _fields_ = [('lo', C.c_uint64), ('hi', C.c_uint64), ('stream', C.c_uint32), ('reserved', C.c_uint32)]
class Result(C.Structure):
    _fields_ = [('count', C.c_uint64), ('sum', C.c_int64), ('minimum', C.c_int32), ('maximum', C.c_int32)]
assert (C.sizeof(Event), C.sizeof(Query), C.sizeof(Result)) == (16, 24, 24)


def raw(obj):
    return C.string_at(C.addressof(obj), C.sizeof(obj))


class Prepared:
    def __init__(self, case):
        self.case = case
        self.n = case.get('event_count_override', len(case['events']))
        self.q = case.get('query_count_override', len(case['queries']))
        self.events = (Event * (self.n + 2))()
        self.queries = (Query * (self.q + 2))()
        self.results = (Result * (self.q + 2))()
        for obj in [self.events, self.queries, self.results]:
            C.memset(C.addressof(obj), 0xA5, C.sizeof(obj))
        # Interior defaults are legal records, including oversized invalid-count
        # arrays: no test relies on inaccessible or insufficient pointer storage.
        C.memset(C.addressof(self.events) + 16, 0, 16*self.n)
        C.memset(C.addressof(self.queries) + 24, 0, 24*self.q)
        for i, e in enumerate(case['events']): self.events[i+1] = Event(*e)
        for i, q in enumerate(case['queries']): self.queries[i+1] = Query(*q)
        self.ep = C.cast(C.byref(self.events, 16), C.POINTER(Event))
        self.qp = C.cast(C.byref(self.queries, 24), C.POINTER(Query))
        self.rp = C.cast(C.byref(self.results, 24), C.POINTER(Result))

    def call(self, function):
        case = self.case
        C.memset(C.addressof(self.results), 0xA5, C.sizeof(self.results))
        before_e, before_q, before_r = raw(self.events), raw(self.queries), raw(self.results)
        rc = function(None if case.get('null_events') else self.ep, self.n,
                      None if case.get('null_queries') else self.qp, self.q,
                      None if case.get('null_results') else self.rp)
        after_e, after_q, after_r = raw(self.events), raw(self.queries), raw(self.results)
        actual = [] if case.get('null_results') else [list((r.count, r.sum, r.minimum, r.maximum)) for r in self.results[1:self.q+1]]
        issues = []
        if rc != case['return_code']: issues.append('return_code')
        if before_e != after_e: issues.append('event_input_or_guard_mutation')
        if before_q != after_q: issues.append('query_input_or_guard_mutation')
        if before_r[:24] != after_r[:24] or before_r[-24:] != after_r[-24:]: issues.append('output_canary')
        if case['return_code'] == 1 and before_r != after_r: issues.append('invalid_output_changed')
        expected = case.get('expected')
        if rc == 0 and case['return_code'] == 0 and expected is not None and actual != [list(x) for x in expected]:
            issues.append('result_mismatch')
        return {'status': 'resource_failure' if rc == 2 else ('semantic_failure' if issues else 'pass'),
                'return_code': rc, 'expected_return_code': case['return_code'], 'issues': issues,
                'event_count': self.n, 'query_count': self.q,
                'inputs_unchanged': before_e == after_e and before_q == after_q,
                'output_canaries_intact': before_r[:24] == after_r[:24] and before_r[-24:] == after_r[-24:],
                'invalid_output_unchanged': before_r == after_r if case['return_code'] == 1 else None,
                'expected': expected, 'actual': actual,
                'output_sha256': sha256(after_r), 'output_before_sha256': sha256(before_r)}


def fixture_case(spec, suite, fixture_root):
    manifest = json.loads((fixture_root / 'manifest.json').read_text())
    entry = next(e for e in manifest['suites'][suite] if e['shape'] == spec['shape'])
    inp, out = (fixture_root / entry['input']).read_bytes(), (fixture_root / entry['expected']).read_bytes()
    if sha256(inp) != entry['sha256_input'] or sha256(out) != entry['sha256_expected']:
        raise ValueError('immutable fixture hash mismatch')
    events, queries = decode_input(inp)
    expected = decode_expected(out)
    if len(events) != entry['event_count'] or len(queries) != entry['query_count'] or len(queries) != len(expected):
        raise ValueError('fixture count mismatch')
    return {'events': events, 'queries': queries, 'expected': expected, 'return_code': 0}


def run_special(spec, suite, function, case_seed):
    kind = spec['kind']
    if kind in ('oversized_events_unbacked', 'oversized_queries_unbacked'):
        # Contract: excessive counts must be rejected before any array access;
        # backing storage for those counts is deliberately not promised.
        region = mmap.mmap(-1, mmap.PAGESIZE, prot=mmap.PROT_READ | mmap.PROT_WRITE)
        buffer = (C.c_char * mmap.PAGESIZE).from_buffer(region)
        address = C.addressof(buffer)
        libc = C.CDLL(None, use_errno=True)
        libc.mprotect.argtypes = [C.c_void_p, C.c_size_t, C.c_int]
        libc.mprotect.restype = C.c_int
        results = (Result * 3)()
        C.memset(C.addressof(results), 0xA5, C.sizeof(results))
        before = raw(results)
        if libc.mprotect(address, mmap.PAGESIZE, 0) != 0:
            raise OSError(C.get_errno(), 'guard-page protection failed')
        try:
            n, q = (1000001, 1) if kind == 'oversized_events_unbacked' else (1, 4097)
            rc = function(C.cast(address, C.POINTER(Event)), n,
                          C.cast(address, C.POINTER(Query)), q,
                          C.cast(C.byref(results, C.sizeof(Result)), C.POINTER(Result)))
            unchanged = raw(results) == before
            return [{'status': 'pass' if rc == 1 and unchanged else 'semantic_failure',
                     'return_code': rc, 'expected_return_code': 1, 'output_unchanged': unchanged,
                     'storage': 'one inaccessible guard page shared by both input pointers; only one output slot plus canaries'}]
        finally:
            libc.mprotect(address, mmap.PAGESIZE, mmap.PROT_READ | mmap.PROT_WRITE)
            del buffer
            region.close()
    if kind == 'zero_null_variants':
        invocations = []
        for bits in range(8):
            invocations.append(Prepared({'events': [], 'queries': [], 'expected': [], 'return_code': 0,
                'null_events': bool(bits & 1), 'null_queries': bool(bits & 2), 'null_results': bool(bits & 4)}).call(function))
        invocations.append(Prepared({'events': [], 'queries': [(0, U64, ALL, 0), (5, 5, 3, 0)],
            'expected': [(0, 0, 0, 0)]*2, 'return_code': 0, 'null_events': True}).call(function))
        for bits in range(4):
            invocations.append(Prepared({'events': [(1, 2, -3)], 'queries': [], 'expected': [], 'return_code': 0,
                'null_queries': bool(bits & 1), 'null_results': bool(bits & 2)}).call(function))
        return invocations
    if kind in ('repeated_calls', 'same_pointer_changed_data'):
        events, queries = randomized(case_seed + 200000, 80, 12)
        case = {'events': events, 'queries': queries, 'expected': direct(events, queries), 'return_code': 0}
        prepared = Prepared(case)
        outputs = []
        for i in range(16):
            if kind == 'same_pointer_changed_data':
                events[0] = (100 + i, 0, I32_MAX - 733*i)
                queries[0] = (0, 1000 + i, ALL, 0)
                prepared.events[1] = Event(*events[0])
                prepared.queries[1] = Query(*queries[0])
                prepared.case['expected'] = direct(events, queries)
            outputs.append(prepared.call(function))
        return outputs
    if kind == 'concurrent_calls':
        barrier = threading.Barrier(8)
        def run_lane(lane):
            events, queries = randomized(case_seed + 300000 + lane, 1400, 40)
            case = {'events': events, 'queries': queries, 'expected': direct(events, queries), 'return_code': 0}
            prepared = Prepared(case)
            outputs = []
            for i in range(12):
                barrier.wait(timeout=5)
                result = prepared.call(function)
                result['lane'], result['round'] = lane, i
                outputs.append(result)
            return outputs
        with ThreadPoolExecutor(max_workers=8) as pool:
            lanes = list(pool.map(run_lane, range(8)))
        return [result for lane in lanes for result in lane]
    if kind == 'maximum_events':
        case = {'events': [], 'event_count_override': 1000000,
                'queries': [(0, 4, ALL, 0), (3, 4, 0, 0), (0, 3, ALL, 0), (0, U64, 1, 0)],
                'expected': [(1000000, 1000000*I32_MAX, I32_MAX, I32_MAX)]*2 + [(0, 0, 0, 0)]*2,
                'return_code': 0}
        prepared = Prepared(case)
        C.memmove(C.addressof(prepared.events)+16, bytes(Event(3, 0, I32_MAX))*1000000, 16000000)
        return [prepared.call(function)]
    if kind == 'maximum_queries':
        events, queries = randomized(case_seed + 400000, 30, 4096)
        return [Prepared({'events': events, 'queries': queries, 'expected': direct(events, queries), 'return_code': 0}).call(function)]
    return None


def worker(args):
    started = time.monotonic()
    spec = next(s for s in plan(args.suite) if s['id'] == args.worker_case)
    result = {'id': spec['id'], 'kind': spec['kind'], 'status': 'infra_error'}
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_AS, (args.memory_mib*1024*1024, args.memory_mib*1024*1024))
        resource.setrlimit(resource.RLIMIT_CPU, (args.cpu_seconds, args.cpu_seconds+1))
        library = C.CDLL(str(args.library.resolve()))
        function = library.engine_run
        function.argtypes = [C.POINTER(Event), C.c_size_t, C.POINTER(Query), C.c_size_t, C.POINTER(Result)]
        function.restype = C.c_int
        outputs = run_special(spec, args.suite, function, args.case_seed)
        if outputs is None:
            case = fixture_case(spec, args.suite, args.fixture_root) if spec['kind'] == 'workload' else build(spec, args.suite, args.case_seed)
            outputs = [Prepared(item).call(function) for item in case.get('invocations', [case])]
        status = 'pass'
        for category in ['infra_error', 'resource_failure', 'semantic_failure']:
            if any(output['status'] == category for output in outputs):
                status = category
                break
        result.update(status=status, invocations=outputs, invocation_count=len(outputs),
                      passed_invocations=sum(o['status'] == 'pass' for o in outputs))
    except MemoryError:
        result.update(status='resource_failure', reason='worker_or_candidate_memory_exhaustion')
    except Exception as exc:
        result.update(status='infra_error', reason=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc())
    usage = resource.getrusage(resource.RUSAGE_SELF)
    result.update(elapsed_seconds=time.monotonic()-started, max_rss_kib=usage.ru_maxrss,
                  cpu_seconds=usage.ru_utime+usage.ru_stime)
    args.output.write_text(json.dumps(result, sort_keys=True) + '\n')
    return 0


def evaluate(args):
    started = time.monotonic()
    specs = plan(args.suite)
    args.output = args.output.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    details = args.output.parent / (args.output.stem + '.cases')
    details.mkdir(exist_ok=True)
    library = args.library.resolve()
    library_hash = sha256(library.read_bytes()) if library.is_file() else None
    rows = []
    for spec in specs:
        case_out = details / (spec['id'] + '.json')
        stdout_path, stderr_path = details / (spec['id'] + '.stdout'), details / (spec['id'] + '.stderr')
        command = [sys.executable, str(Path(__file__).resolve()), '--library', str(library), '--output', str(case_out),
                   '--suite', args.suite, '--case-seed', str(args.case_seed), '--fixture-root', str(args.fixture_root), '--worker-case', spec['id'], '--memory-mib', str(args.memory_mib),
                   '--cpu-seconds', str(args.cpu_seconds)]
        begin = time.monotonic()
        result = {'id': spec['id'], 'kind': spec['kind'], 'status': 'infra_error'}
        if case_out.exists(): case_out.unlink()
        try:
            with stdout_path.open('wb') as stdout, stderr_path.open('wb') as stderr:
                # Children remain in the evaluator's process group. The outer
                # controller can terminate the entire group on its own timeout.
                process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
                try:
                    code = process.wait(timeout=args.timeout_seconds)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()
                    result.update(status='resource_failure', reason='wall_timeout')
                    code = None
            if code is not None:
                if code < 0:
                    result.update(status='resource_failure', reason='process_signal', signal=-code)
                elif code != 0:
                    result.update(status='infra_error', reason='worker_exit', exit_code=code)
                elif not case_out.exists():
                    result.update(status='infra_error', reason='missing_worker_result')
                else:
                    result = json.loads(case_out.read_text())
                    if stdout_path.stat().st_size or stderr_path.stat().st_size:
                        result.update(status='semantic_failure', reason='prohibited_output_printing')
        except Exception as exc:
            result.update(status='infra_error', reason=f'{type(exc).__name__}: {exc}')
        result['process_elapsed_seconds'] = time.monotonic()-begin
        case_out.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
        rows.append({key: value for key, value in result.items() if key not in ['invocations', 'traceback']})
        rows[-1]['output_path'] = str(case_out)
    counts = {status: sum(row['status'] == status for row in rows) for status in ['pass', 'semantic_failure', 'resource_failure', 'infra_error']}
    report = {'schema_version': 1, 'suite': args.suite, 'library': str(library), 'library_sha256': library_hash,
              'case_seed_namespace': args.case_seed, 'status': 'infra_error' if counts['infra_error'] else ('pass' if counts['pass'] == len(specs) else 'fail'),
              'planned_cases': len(specs), 'attempted_cases': len(rows), 'passed': counts['pass'],
              'failed': len(specs)-counts['pass'], 'semantic_failures': counts['semantic_failure'],
              'resource_failures': counts['resource_failure'], 'infra_failures': counts['infra_error'],
              'limits': {'wall_seconds_per_case': args.timeout_seconds, 'cpu_seconds_per_case': args.cpu_seconds,
                         'address_space_mib_per_case': args.memory_mib},
              'case_outputs_dir': str(details), 'elapsed_seconds': time.monotonic()-started, 'cases': rows,
              'limitations': ['Finite behavioral probes do not prove absence of persistent caches, all races, or arbitrary hostile behavior.',
                             'Worker memory/RSS includes Python, fixtures and oracle-side structures; resource failures are operational, not semantic proof.',
                             'Seed and oracle use different algorithms, but were initially implemented by the same setup worker.']}
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({k: report[k] for k in ['status', 'planned_cases', 'passed', 'failed', 'semantic_failures', 'resource_failures', 'infra_failures', 'elapsed_seconds']}))
    return 2 if counts['infra_error'] else (0 if report['status'] == 'pass' else 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--suite', required=True, help='owner-selected suite; NativeBackend enforces allowlist')
    parser.add_argument('--timeout-seconds', type=float, default=10.0)
    parser.add_argument('--cpu-seconds', type=int, default=8)
    parser.add_argument('--memory-mib', type=int, default=768)
    parser.add_argument('--case-seed', type=int, default=2026100144)
    parser.add_argument('--fixture-root', type=Path, required=True)
    parser.add_argument('--worker-case', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if min(args.timeout_seconds, args.cpu_seconds, args.memory_mib) <= 0:
        parser.error('all resource limits must be positive')
    return worker(args) if args.worker_case else evaluate(args)

if __name__ == '__main__':
    raise SystemExit(main())
