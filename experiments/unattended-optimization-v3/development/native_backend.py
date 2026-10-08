"""Concrete draft native development tools, with no model or promotion route."""
from __future__ import annotations
import dataclasses
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import signal
import statistics
import subprocess
import sys
import time
from .core import Cancelled, IntegrityError, WatchdogExpired, encoded, file_hash, tree, write_new
from runtime.process_tree import DescendantTracker

NATIVE = Path(__file__).resolve().parent / 'native'
COMPILER_FLAGS = ('-std=c++20', '-O3', '-g', '-DNDEBUG', '-fPIC', '-shared', '-pthread', '-march=x86-64', '-mtune=generic')


@dataclasses.dataclass(frozen=True)
class ProcessLimits:
    cpus: tuple[int, ...]
    address_space_bytes: int
    observed_rss_kib: int
    file_size_bytes: int
    cpu_seconds: int | None
    wall_seconds: float | None


@dataclasses.dataclass(frozen=True)
class NativeConfig:
    contract_directory: str
    compiler: str
    driver: str
    fixtures: str
    callgrind: str
    annotate: str
    valgrind_lib: str
    debuginfo_root: str
    ordinary: ProcessLimits
    diagnostic: ProcessLimits
    pinned_files: dict[str, str]
    oracle_expected_cases: int = 89
    oracle_child_seconds: float = 10
    oracle_child_cpu_seconds: int = 8
    oracle_child_memory_mib: int = 768
    paired_blocks: int = 10
    minimum_sample_seconds: float = 0.05
    maximum_repetitions: int = 65536
    warmups: int = 1
    order_seed: int = 2026100301
    case_seed: int = 2026100144
    compile_wall_seconds: float = 120
    compile_cpu_seconds: int = 120
    correctness_wall_seconds: float = 180
    correctness_cpu_seconds: int = 150
    benchmark_suite: str = 'development'
    correctness_suite: str = 'development'
    profile_suite: str = 'profile'
    allowed_suites: tuple[str, ...] = ('development', 'profile')
    scored_under_target_policy: str = 'retain_and_flag_no_adaptive_retry'
    bootstrap_resamples: int = 10000
    bootstrap_seed: int = 2026100302
    bootstrap_one_sided_confidence: float = 0.90


def _load(path):
    return json.loads(Path(path).read_text())


def _source_policy(source):
    """Finite transparent screen, never a security or semantic proof."""
    violations = []
    bans = [r'\b(?:system|popen|fork|vfork|execve|dlopen|dlsym|getenv|setenv|fopen|freopen|openat|socket|syscall)\s*\(',
            r'\b(?:asm|__asm__|__asm)\b', r'#\s*pragma\s+(?:GCC|clang)', r'__attribute__\s*\(.*target',
            r'#\s*include\s*[<"](?:immintrin|x86intrin|unistd|dlfcn|filesystem|fstream|chrono|random)',
            r'\b(?:printf|fprintf|puts|cout|cerr)\b']
    for name in tree(source):
        p = source / name
        if p.name == 'engine.h':
            violations.append({'file': name, 'rule': 'immutable engine.h cannot be replaced'})
        if p.suffix not in {'.cpp', '.h', '.hpp', '.ipp', '.tpp'}:
            continue  # Extra test scripts can be snapshotted but are not engine inputs.
        text = p.read_text()
        for token in re.findall(r'^\s*#\s*include\s+(.+)$', text, re.M):
            match = re.match(r'([<"])([^>"]+)[>"]', token.strip())
            if not match:
                violations.append({'file': name, 'rule': 'computed include'}); continue
            delimiter, include = match.groups()
            if include == 'engine.h':
                continue
            target = (p.parent / include).resolve()
            if (delimiter == '"' and (not target.is_relative_to(source) or not target.is_file())) or (delimiter == '<' and ('/' in include or include.startswith('.'))):
                violations.append({'file': name, 'rule': 'external source include'})
        for rule in bans:
            if re.search(rule, text):
                violations.append({'file': name, 'rule': rule})
    return violations


def run_process(command, directory, cwd, limits, context, environment=None):
    """Recorded native command; ordinary child cleanup uses pidfd identities."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    tmp = directory / 'tmp'
    tmp.mkdir()
    env = {'PATH': os.defpath, 'LC_ALL': 'C', 'TZ': 'UTC', 'TMPDIR': str(tmp), 'DEBUGINFOD_URLS': '', 'PYTHONDONTWRITEBYTECODE': '1', **(environment or {})}
    spec = {'command': [str(v) for v in command], 'cwd': str(cwd), 'limits': dataclasses.asdict(limits), 'environment': env}
    write_new(directory / 'exec-spec.json', spec)
    started = time.monotonic()
    record = {**spec, 'started_unix': time.time(), 'stdout': 'stdout.txt', 'stderr': 'stderr.txt',
              'technical_watchdog': True, 'process_started': False}
    proc = tracker = None
    usage = None
    error = None
    status = 'infra_error'
    try:
        context['check_active']()
        with (directory / 'stdout.txt').open('xb') as out, (directory / 'stderr.txt').open('xb') as err:
            proc = subprocess.Popen([sys.executable, '-B', str(NATIVE / 'process_exec.py'), str(directory / 'exec-spec.json')], stdout=out, stderr=err, start_new_session=True)
            record.update(process_started=True, process_pid=proc.pid)
            tracker = DescendantTracker(proc.pid)
            while True:
                tracker.refresh()
                context['check_active']()
                pid, code, usage = os.wait4(proc.pid, os.WNOHANG)
                if pid:
                    proc.returncode = os.waitstatus_to_exitcode(code)
                    break
                if limits.wall_seconds is not None and time.monotonic() - started >= limits.wall_seconds:
                    raise WatchdogExpired('native process technical wall watchdog')
                time.sleep(0.01)
            record['exit_code'] = proc.returncode
            record['peak_rss_kib'] = usage.ru_maxrss
            record['user_cpu_seconds'], record['system_cpu_seconds'] = usage.ru_utime, usage.ru_stime
            status = 'pass' if proc.returncode == 0 and usage.ru_maxrss <= limits.observed_rss_kib else 'candidate_failure'
    except (WatchdogExpired, Cancelled) as exc:
        status = 'cancelled' if isinstance(exc, Cancelled) else 'timeout'
        record['error'] = str(exc)
    except BaseException as exc:
        error = exc
        record['error'] = type(exc).__name__ + ': ' + str(exc)
    finally:
        if proc:
            if tracker:
                tracker.refresh(force=True)
                tracker.signal_all(signal.SIGKILL)
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if proc.returncode is None:
                try:
                    _, code, usage = os.wait4(proc.pid, 0)
                    proc.returncode = os.waitstatus_to_exitcode(code)
                except ChildProcessError:
                    pass
            record.setdefault('exit_code', proc.returncode)
            if tracker:
                until = time.monotonic() + 2
                while not tracker.all_exited() and time.monotonic() < until:
                    time.sleep(0.01)
                record['cleanup'] = tracker.finish()
                if not record['cleanup']['tracked_processes_exited']:
                    status = 'infra_error'
            if usage:
                record.setdefault('peak_rss_kib', usage.ru_maxrss)
        record.update(status=status, elapsed_seconds=time.monotonic() - started)
        write_new(directory / 'command.json', record)
    if error:
        raise error
    return record


def paired_bootstrap(samples, resamples, seed, confidence):
    """Deterministic complete-block bootstrap; descriptive after repeated selection."""
    logs = {name: [math.log(p['baseline'] / p['candidate']) for p in pairs] for name, pairs in samples.items()}
    counts = {len(v) for v in logs.values()}
    if len(counts) != 1 or not counts or next(iter(counts)) < 1 or resamples < 1 or not 0 < confidence < 1:
        raise IntegrityError('invalid complete-block bootstrap inputs')
    n = next(iter(counts))
    rng, dist = random.Random(seed), []
    for _ in range(resamples):
        indices = rng.choices(range(n), k=n)
        dist.append(math.exp(statistics.mean(statistics.median([v[i] for i in indices]) for v in logs.values())))
    dist.sort()
    q = (1 - confidence) * (resamples - 1)
    lo, hi = math.floor(q), math.ceil(q)
    return {'one_sided_lower_bound': dist[lo] + (q-lo)*(dist[hi]-dist[lo]), 'confidence': confidence,
            'resamples': resamples, 'seed': seed, 'unit': 'complete temporal block across all families',
            'quantile': 'linear interpolation at p*(B-1)',
            'interpretation': 'descriptive uncertainty only; repeated exploratory selection is not confirmatory evidence of agent efficacy'}


class NativeBackend:
    def __init__(self, config):
        self.config = config
        self.config_hash = hashlib.sha256(encoded(dataclasses.asdict(config))).hexdigest()

    def required_pins(self):
        c = self.config
        paths = [Path(__file__), Path(__file__).parent / 'core.py', Path(__file__).parent / 'dispatch.py',
                 Path(__file__).parents[1] / 'runtime/process_tree.py', Path(__file__).parents[1] / 'runtime/contracts.py',
                 NATIVE / 'process_exec.py', NATIVE / 'driver.cpp',
                 *(NATIVE / 'oracle' / x for x in ('evaluate.py', 'cases.py', 'reference.py')),
                 Path(c.contract_directory) / 'engine.h', Path(c.compiler).resolve(), Path(c.driver),
                 Path(c.callgrind).resolve(), Path(c.annotate).resolve(), Path(c.fixtures) / 'manifest.json']
        manifest = _load(Path(c.fixtures) / 'manifest.json')
        if set(manifest['suites']) - set(c.allowed_suites):
            raise IntegrityError('manifest contains unauthorized suites')
        for suite in (c.benchmark_suite, c.correctness_suite, c.profile_suite):
            if suite not in c.allowed_suites or suite not in manifest['suites']:
                raise IntegrityError('configured suite missing or unauthorized')
        for items in manifest['suites'].values():
            for item in items:
                for k in ('input', 'expected'):
                    path = Path(c.fixtures) / item[k]
                    if path.is_symlink() or not path.resolve().is_relative_to(Path(c.fixtures).resolve()):
                        raise IntegrityError('fixture path escapes configured root')
                    paths.append(path)
        return {str(p.resolve()) for p in paths}

    def verify(self):
        if not self.required_pins().issubset(self.config.pinned_files):
            raise IntegrityError('required native inputs are not pinned')
        if hashlib.sha256(encoded(dataclasses.asdict(self.config))).hexdigest() != self.config_hash:
            raise IntegrityError('native configuration mutated')
        for p, expected in self.config.pinned_files.items():
            if not Path(p).is_file() or Path(p).is_symlink() or file_hash(p) != expected:
                raise IntegrityError('native pinned input changed: ' + p)
        return {'status': 'pass', 'configuration_sha256': self.config_hash, 'pinned_file_count': len(self.config.pinned_files),
                'pin_scope_limitations': ['Top-level compiler, Valgrind launcher/annotation, driver, contract, selected Python source and fixture files are pinned.', 'Compiler subprocesses, system shared libraries, Valgrind inner executables/lib/debug directories and interpreter dependency closure are not all individually pinned; this is not a hermetic build or security sandbox.']}

    def fixtures(self, suite):
        if suite not in self.config.allowed_suites:
            raise IntegrityError('suite not authorized by owner configuration')
        root = Path(self.config.fixtures).resolve()
        manifest = _load(root / 'manifest.json')
        if set(manifest['suites']) - set(self.config.allowed_suites):
            raise IntegrityError('public fixture manifest contains unexpected suite')
        items = manifest['suites'][suite]
        if not items or len({x['id'] for x in items}) != len(items):
            raise IntegrityError('empty or duplicate fixture portfolio')
        for item in items:
            for name in ('input', 'expected'):
                p = root / item[name]
                if p.is_symlink() or not p.resolve().is_relative_to(root) or file_hash(p) != item['sha256_' + name]:
                    raise IntegrityError('public fixture mismatch')
        return items

    def _command(self, command, output, context, diagnostic=False, kind=None):
        limits = self.config.diagnostic if diagnostic else self.config.ordinary
        if kind in ('compile', 'correctness'):
            limits = dataclasses.replace(limits, wall_seconds=getattr(self.config, kind + '_wall_seconds'), cpu_seconds=getattr(self.config, kind + '_cpu_seconds'))
        return run_process(command, output, output.parent, limits,
                           context, {'VALGRIND_LIB': self.config.valgrind_lib})

    def _library(self, context):
        lib = context['build_directory'] / context['build']['library']
        if file_hash(lib) != context['build']['library_sha256']:
            raise IntegrityError('input build library changed')
        return lib

    def _driver(self, library, item, mode='benchmark', repetitions=None):
        c = self.config
        cmd = [c.driver, '--library', str(library), '--input', str(Path(c.fixtures) / item['input']), '--expected', str(Path(c.fixtures) / item['expected']), '--mode', mode,
               '--min-seconds', str(c.minimum_sample_seconds), '--max-repetitions', str(c.maximum_repetitions), '--warmups', str(c.warmups)]
        if repetitions is not None:
            cmd += ['--repetitions', str(repetitions)]
        return cmd

    def execute(self, kind, context, output):
        write_new(output / 'integrity-before.json', self.verify())
        try:
            if kind == 'build':
                result = self.build(context, output)
            elif kind == 'test':
                result = self.test(context, output)
            elif kind == 'profile':
                result = self.profile(context, output)
            elif kind == 'memcheck':
                result = self.memcheck(context, output)
            elif kind == 'bench':
                result = self.bench(context, output)
            elif kind == 'check':
                work = output / 'work'
                shutil.copytree(context['source_directory'], work)
                result = run_process(context['request']['argv'], output / 'check', work, self.config.ordinary, context)
                result = {'status': result['status'], 'summary': 'exploratory custom check; not canonical correctness', 'work_tree_after': tree(work)}
            else:
                raise ValueError('unsupported native operation')
            return result
        finally:
            write_new(output / 'integrity-after.json', self.verify())

    def build(self, context, output):
        source = context['source_directory']
        violations = _source_policy(source)
        cpp = [str(source / p) for p in tree(source) if p.endswith('.cpp')]
        write_new(output / 'source-policy.json', {'violations': violations, 'limitation': 'finite lexical screen, not sandbox'})
        if violations or not cpp:
            return {'status': 'candidate_failure', 'summary': 'source policy failure or missing C++ source'}
        contract = Path(self.config.contract_directory)
        command = [self.config.compiler, *COMPILER_FLAGS, '-I', str(contract), '-include', str(contract / 'engine.h'), *cpp, '-o', str(output / 'candidate.so')]
        result = self._command(command, output / 'compile', context, kind='compile')
        return {'status': result['status'], 'library': 'candidate.so', 'summary': 'canonical fixed-flag compilation', 'command_record': 'compile/command.json'}

    def test(self, context, output):
        self.fixtures(self.config.correctness_suite)
        command = [sys.executable, '-B', str(NATIVE / 'oracle/evaluate.py'), '--library', str(self._library(context)), '--output', str(output / 'correctness.json'), '--suite', self.config.correctness_suite, '--case-seed', str(self.config.case_seed), '--fixture-root', self.config.fixtures,
                   '--timeout-seconds', str(self.config.oracle_child_seconds), '--cpu-seconds', str(self.config.oracle_child_cpu_seconds), '--memory-mib', str(self.config.oracle_child_memory_mib)]
        result = self._command(command, output / 'evaluate', context, kind='correctness')
        if not (output / 'correctness.json').is_file():
            return {'status': result['status'] if result['status'] != 'pass' else 'infra_error', 'summary': 'correctness evaluator missing final report'}
        report = _load(output / 'correctness.json')
        cases = report.get('cases', [])
        categories = ('pass', 'semantic_failure', 'resource_failure', 'infra_error')
        counts = {name: sum(case.get('status') == name for case in cases) for name in categories}
        valid_counts = (report.get('planned_cases') == self.config.oracle_expected_cases
                        and report.get('attempted_cases') == self.config.oracle_expected_cases
                        and len(cases) == self.config.oracle_expected_cases
                        and len({case.get('id') for case in cases}) == len(cases)
                        and sum(counts.values()) == len(cases)
                        and report.get('passed') == counts['pass']
                        and report.get('failed') == len(cases) - counts['pass']
                        and report.get('semantic_failures') == counts['semantic_failure']
                        and report.get('resource_failures') == counts['resource_failure']
                        and report.get('infra_failures') == counts['infra_error'])
        process_pass = result['status'] == 'pass' and result.get('exit_code') == 0
        passing_report = report.get('status') == 'pass' and counts['pass'] == len(cases) and valid_counts
        consistency = (valid_counts and report.get('library_sha256') == context['build']['library_sha256']
                       and report.get('suite') == self.config.correctness_suite
                       and report.get('case_seed_namespace') == self.config.case_seed
                       and (report.get('status') != 'pass' or passing_report)
                       and (result['status'] != 'pass' or (passing_report and process_pass)))
        if not consistency:
            return {'status': 'infra_error', 'summary': 'inconsistent oracle exit/status/count/suite/seed/library evidence', 'report': 'correctness.json'}
        status = 'pass' if process_pass and passing_report else ('infra_error' if report['status'] == 'infra_error' else result['status'])
        if status == 'pass':
            rss = [case.get('max_rss_kib') for case in cases]
            if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in rss):
                return {'status': 'infra_error', 'summary': 'passing oracle case missing valid RSS evidence', 'report': 'correctness.json'}
            if any(v > self.config.ordinary.observed_rss_kib for v in rss):
                status = 'candidate_failure'
        confirmed = [case['id'] for case in cases if case['status'] == 'semantic_failure'
                     or (case['id'] in {'oversized_events_unbacked', 'oversized_queries_unbacked'}
                         and case.get('reason') == 'process_signal' and case.get('signal') == 11)]
        return {'status': status, 'confirmed_semantic_failure': bool(confirmed),
                'confirmed_contract_failure_ids': confirmed,
                'summary': {k: report[k] for k in ('planned_cases', 'passed', 'failed', 'semantic_failures', 'resource_failures', 'infra_failures')}, 'report': 'correctness.json'}

    def profile(self, context, output):
        item = next((x for x in self.fixtures(self.config.profile_suite) if x['id'] == context['request']['fixture_id']), None)
        if item is None:
            return {'status': 'candidate_failure', 'summary': 'unknown public profile fixture'}
        raw = output / 'callgrind.out'
        command = [self.config.callgrind, '--tool=callgrind', '--vgdb=no', '--instr-atstart=no', '--collect-atstart=yes', '--extra-debuginfo-path=' + self.config.debuginfo_root, '--callgrind-out-file=' + str(raw), *self._driver(self._library(context), item, 'profile')]
        result = self._command(command, output / 'profile', context, True)
        if result['status'] != 'pass':
            return {'status': result['status'], 'summary': 'Callgrind invocation failed'}
        profiles = sorted(output.glob('callgrind.out*'))
        if not profiles:
            return {'status': 'infra_error', 'summary': 'Callgrind output missing'}
        # Client-triggered dump normally appears as .1; annotate all non-empty outputs.
        annotations = []
        for i, path in enumerate(profiles):
            sub = output / f'annotation-{i:02d}'
            result = self._command([self.config.annotate, '--auto=no', str(path)], sub, context, True)
            if result['status'] != 'pass':
                return {'status': 'infra_error', 'summary': 'Callgrind annotation failed'}
            annotations.append(str(sub.relative_to(output) / 'stdout.txt'))
        return {'status': 'pass', 'summary': 'instruction counts only; instrumented duration is not performance', 'profiles': [p.name for p in profiles], 'annotations': annotations}

    def memcheck(self, context, output):
        all_items = self.fixtures(self.config.profile_suite)
        selected = context['request'].get('fixture_id')
        items = [x for x in all_items if selected is None or x['id'] == selected]
        if not items:
            return {'status': 'candidate_failure', 'summary': 'unknown public memory-probe fixture'}
        records = []
        for item in items:
            command = [self.config.callgrind, '--tool=memcheck', '--vgdb=no', '--error-exitcode=99',
                       '--leak-check=full', '--errors-for-leak-kinds=definite', '--show-leak-kinds=definite',
                       '--extra-debuginfo-path=' + self.config.debuginfo_root,
                       *self._driver(self._library(context), item, 'verify')]
            result = self._command(command, output / ('memcheck-' + item['id']), context, True)
            records.append({'fixture_id': item['id'], 'status': result['status'], 'exit_code': result.get('exit_code'),
                            'command_record': 'memcheck-' + item['id'] + '/command.json'})
            if result['status'] in {'timeout', 'cancelled', 'infra_error'}:
                break
        passed = all(row['status'] == 'pass' for row in records) and len(records) == len(items)
        return {'status': 'pass' if passed else next(row['status'] for row in records if row['status'] != 'pass'),
                'summary': 'finite memory-error probes, not a proof of memory safety',
                'coverage_complete': passed and len(items) == len(all_items),
                'confirmed_memory_error': any(row.get('exit_code') == 99 for row in records),
                'planned_fixture_ids': [x['id'] for x in all_items], 'probe_records': records}

    def _validate_sample(self, data, expected_repetitions=None):
        c = self.config
        repetitions = data.get('repetitions')
        if type(repetitions) is not int or not 1 <= repetitions <= c.maximum_repetitions:
            raise IntegrityError('invalid native repetition count')
        if expected_repetitions is not None and repetitions != expected_repetitions:
            raise IntegrityError('scored repetitions differ from frozen calibration')
        if type(data.get('verified_calls')) is not int or data['verified_calls'] != repetitions + c.warmups:
            raise IntegrityError('native verified-call count mismatch')
        elapsed, per_call, rss = (data.get(k) for k in ('elapsed_seconds', 'seconds_per_call', 'peak_rss_kib'))
        if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in (elapsed, per_call, rss)):
            raise IntegrityError('invalid native elapsed/per-call/RSS measurement')
        if rss > c.ordinary.observed_rss_kib:
            raise IntegrityError('native measured RSS exceeds frozen limit')
        if not math.isclose(per_call, elapsed / repetitions, rel_tol=1e-9, abs_tol=1e-15):
            raise IntegrityError('elapsed time and normalized measurement disagree')
        if type(data.get('sample_target_met')) is not bool or data['sample_target_met'] != (elapsed >= c.minimum_sample_seconds):
            raise IntegrityError('native sample target flag inconsistent')
        return data['sample_target_met']

    def bench(self, context, output):
        c = self.config
        if c.scored_under_target_policy != 'retain_and_flag_no_adaptive_retry':
            raise IntegrityError('unknown fixed-batch under-target policy')
        if c.paired_blocks < 2 or c.paired_blocks % 2:
            raise IntegrityError('paired blocks must be positive even count')
        base = Path(context['baseline']['path'])
        if file_hash(base) != context['baseline']['library_sha256']:
            raise IntegrityError('inherited prototype library hash mismatch')
        proposal = self._library(context)
        items = self.fixtures(c.benchmark_suite)
        libraries = {'baseline': base, 'candidate': proposal}
        calibration, orders, samples, raw = {}, {}, {x['id']: [] for x in items}, []
        for item in items:
            counts = {}
            for label, library in libraries.items():
                sub = output / item['id'] / ('calibrate-' + label)
                result = self._command(self._driver(library, item), sub, context)
                if result['status'] != 'pass':
                    return {'status': result['status'], 'summary': 'calibration failed'}
                data = _load(sub / 'stdout.txt')
                if not self._validate_sample(data):
                    return {'status': 'candidate_failure', 'summary': 'calibration repetition cap reached'}
                counts[label] = data['repetitions']
            calibration[item['id']] = {'pilot_repetitions': counts, 'common_repetitions': max(counts.values())}
            sequence = [['baseline', 'candidate'], ['candidate', 'baseline']] * (c.paired_blocks // 2)
            random.Random(c.order_seed + int(hashlib.sha256(item['id'].encode()).hexdigest()[:8], 16)).shuffle(sequence)
            orders[item['id']] = sequence
        write_new(output / 'calibration.json', calibration)
        rng = random.Random(c.order_seed)
        schedule = []
        for b in range(c.paired_blocks):
            shuffled = list(items)
            rng.shuffle(shuffled)
            schedule.append({'block': b, 'families': [x['id'] for x in shuffled], 'orders': {x['id']: orders[x['id']][b] for x in shuffled}})
        write_new(output / 'schedule.json', schedule)
        byid = {x['id']: x for x in items}
        under_target = []
        for block in schedule:
            for name in block['families']:
                pair = {}
                for label in block['orders'][name]:
                    sub = output / name / f"block-{block['block']:02d}-{label}"
                    result = self._command(self._driver(libraries[label], byid[name], repetitions=calibration[name]['common_repetitions']), sub, context)
                    if result['status'] != 'pass':
                        return {'status': result['status'], 'summary': 'paired sample failed; retain partial data'}
                    data = _load(sub / 'stdout.txt')
                    if not self._validate_sample(data, calibration[name]['common_repetitions']):
                        under_target.append({'block': block['block'], 'family': name, 'arm': label, 'elapsed_seconds': data['elapsed_seconds']})
                    pair[label] = data['seconds_per_call']
                    row = {'block': block['block'], 'family': name, 'arm': label, 'driver': data, 'command': str(sub.relative_to(output) / 'command.json')}
                    raw.append(row)
                    write_new(sub / 'measurement.json', row)
                if any(not math.isfinite(v) or v <= 0 for v in pair.values()):
                    raise IntegrityError('invalid native timing')
                samples[name].append(pair)
        write_new(output / 'raw.json', raw)
        write_new(output / 'paired.json', samples)
        speedups = {name: math.exp(statistics.median(math.log(p['baseline'] / p['candidate']) for p in pairs)) for name, pairs in samples.items()}
        if file_hash(base) != context['baseline']['library_sha256']:
            raise IntegrityError('inherited prototype changed during benchmark')
        bootstrap = paired_bootstrap(samples, c.bootstrap_resamples, c.bootstrap_seed, c.bootstrap_one_sided_confidence)
        write_new(output / 'descriptive-bootstrap.json', bootstrap)
        return {'status': 'pass', 'suite': c.benchmark_suite, 'descriptive_bootstrap': bootstrap, 'portfolio_speedup': math.exp(statistics.mean(math.log(v) for v in speedups.values())), 'family_speedups': speedups,
                'summary': 'exploratory repeated-use comparison, no acceptance/promotion or confirmatory significance', 'paired_blocks': c.paired_blocks, 'raw': 'raw.json', 'scored_under_target_policy': c.scored_under_target_policy, 'scored_under_target_batches': under_target}
