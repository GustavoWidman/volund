"""Finite post-hoc memory diagnostics, excluded from all study outcomes.

No build, benchmarking, optimization, model call, acceptance decision, or canonical
assessment operation occurs here. Only this directory receives new evidence.
"""
from __future__ import annotations

import collections
import datetime
import json
from pathlib import Path
import re
import shutil
import struct
import sys

HERE = Path(__file__).resolve().parent
STUDY = HERE.parents[1]
sys.path.insert(0, str(STUDY))
from development.core import digest, encoded, file_hash, tree, write_new
from development.native_backend import NativeBackend, NativeConfig, ProcessLimits, run_process

SOURCE_HASH = '7d87f5bb7d2232ea7375b621a85cc76fc750f997ab92239c4be9d7c9e129c45a'
LIBRARY_HASH = 'bc13b95b6dcc0bae388f9efa3b83163a3ba1f89d7d9c436e2f5918d09d4f47cf'
SOURCE = STUDY / 'campaigns/campaign-3/development/snapshots' / SOURCE_HASH
BUILD = STUDY / 'assessment/final/campaign-3/build'
LIBRARY = BUILD / 'candidate.so'
CONFIG = STUDY / 'setup/native-validation-01/native-config.json'
ALL = (1 << 32) - 1


def load(path):
    return json.loads(Path(path).read_text())


def inspect_input(path):
    blob = Path(path).read_bytes()
    assert blob[:8] == b'RQENG001'
    n, q = struct.unpack_from('<QQ', blob, 8)
    assert len(blob) == 24 + n * 16 + q * 24
    events = list(struct.iter_unpack('<QIi', blob[24:24+n*16]))
    queries = list(struct.iter_unpack('<QQII', blob[24+n*16:]))
    requested = {s for lo, hi, s, reserved in queries if lo < hi}
    global_needed = ALL in requested
    buckets = collections.defaultdict(list)
    for timestamp, stream, value in events:
        if stream in requested:
            buckets[stream].append(timestamp)
    sorted_arrays = [('global', [e[0] for e in events])] if global_needed else [
        (f'stream-{stream}', times) for stream, times in sorted(buckets.items())]
    arrays = []
    for name, times in sorted_arrays:
        mask = 0
        if times:
            for timestamp in times:
                mask |= timestamp ^ times[0]
        active = [byte for byte in range(8) if (mask >> (byte*8)) & 255]
        arrays.append({'index': name, 'size': len(times), 'varying_bytes': active,
                       'radix_branch_forced_by_source': len(times) >= 32768,
                       'radix_passes_forced_by_source': len(active) if len(times) >= 32768 else 0,
                       'copy_back_forced_by_source': len(times) >= 32768 and bool(len(active) % 2)})
    return {'events': n, 'queries': q, 'nonempty_global_queries': sum(lo < hi and s == ALL for lo, hi, s, r in queries),
            'nonempty_stream_queries': sum(lo < hi and s != ALL for lo, hi, s, r in queries),
            'requested_stream_count': len(requested - {ALL}),
            'largest_requested_bucket': max(map(len, buckets.values()), default=0),
            'sorted_arrays': arrays,
            'global_sorted_order_reused_for_streams': global_needed and bool(requested - {ALL}),
            'coverage_method': 'Deterministic source and input analysis; no instruction/branch counter is added to the sealed binary.'}


def main():
    config_data = load(CONFIG)
    for key in ('ordinary', 'diagnostic'):
        config_data[key]['cpus'] = tuple(config_data[key]['cpus'])
        config_data[key] = ProcessLimits(**config_data[key])
    config_data['allowed_suites'] = tuple(config_data['allowed_suites'])
    backend = NativeBackend(NativeConfig(**config_data))
    frozen = load(STUDY / 'state/freeze.json')
    public = Path(backend.config.fixtures)
    items = {item['id']: item for item in backend.fixtures('development')}
    protected = {str(STUDY / p): h for p, h in frozen['manifest']['files'].items()}
    protected.update(frozen['runtime_artifacts'])
    protected.update(backend.config.pinned_files)
    for root in (SOURCE, BUILD, STUDY / 'assessment/final/campaign-3/memory', STUDY / 'campaigns/campaign-3/authority'):
        protected.update({str(root / p): h for p, h in tree(root).items()})
    for p in (CONFIG, HERE / 'run_diagnostic.py', STUDY / 'state/freeze.json'):
        protected[str(p)] = file_hash(p)
    build_record = load(BUILD / 'result.json')
    authority = load(STUDY / 'campaigns/campaign-3/authority/state.json')
    assert build_record['source_hash'] == authority['endpoint']['source_hash'] == SOURCE_HASH
    assert build_record['library_sha256'] == LIBRARY_HASH
    assert digest(encoded(tree(SOURCE))) == SOURCE_HASH
    assert file_hash(LIBRARY) == LIBRARY_HASH
    tool_root = Path(backend.config.debuginfo_root)
    for rel in ('usr/libexec/valgrind/memcheck-amd64-linux', 'usr/libexec/valgrind/vgpreload_memcheck-amd64-linux.so',
                'usr/libexec/valgrind/vgpreload_core-amd64-linux.so'):
        p = tool_root / rel
        protected[str(p)] = file_hash(p)

    historical = HERE / 'historical-evidence'
    historical.mkdir()
    old_ids = ('0d641e6e02d34dd196721171b458463f', 'd9303c9a6f4a4d9bab490970654d94f4',
               '5880da836a5e411383d9b0b4b043b7a3', 'f72d7e1deb894904b5aa016e3d138065')
    for ident in old_ids:
        root = STUDY / 'campaigns/campaign-3/workspace-operations' / ('workspace-' + ident)
        protected.update({str(root / p): h for p, h in tree(root).items()})
        shutil.copytree(root, historical / root.name)
    for role, actor, name in (('implementation', 'agent-4', 'h4_oracle_memcheck.log'),
                              ('reviewer', 'agent-5', 'h4_large_memcheck.log')):
        p = STUDY / 'campaigns/campaign-3/scratch' / role / actor / name
        protected[str(p)] = file_hash(p)
        shutil.copy2(p, historical / name)

    def integrity():
        mismatches = [p for p, h in protected.items() if not Path(p).is_file() or file_hash(p) != h]
        result = {'status': 'pass' if not mismatches else 'fail', 'mismatches': mismatches,
                  'source_tree_sha256': digest(encoded(tree(SOURCE))), 'library_sha256': file_hash(LIBRARY),
                  'native_backend_verification': backend.verify(), 'protected_file_count': len(protected),
                  'protected_manifest_sha256': digest(encoded(protected))}
        assert not mismatches, result
        return result

    write_new(HERE / 'protected-files.json', protected)
    write_new(HERE / 'integrity-before.json', integrity())
    projections = HERE / 'derived-public-inputs'
    projections.mkdir()
    selected = []
    for ident, purpose in (
        ('v2-global-mixed', 'Global radix plus many small stream buckets populated from global sorted order.'),
        ('v2-skewed', 'Global radix plus a large requested stream bucket populated from global sorted order.'),
        ('v2-high-cardinality', 'Global radix with many sparse requested stream indexes and their allocation lifetimes.'),
    ):
        item = items[ident]
        selected.append({'id': ident, 'input': str(public / item['input']), 'expected': str(public / item['expected']),
                         'purpose': purpose, 'origin': 'Unchanged existing public development fixture.'})
    source_item = items['v2-skewed']
    ib = (public / source_item['input']).read_bytes()
    eb = (public / source_item['expected']).read_bytes()
    n, q = struct.unpack_from('<QQ', ib, 8)
    assert eb[:8] == b'RQOUT001' and struct.unpack_from('<Q', eb, 8)[0] == q
    for suffix, want_global, purpose in (
        ('stream-only', False, 'Independent per-stream radix and preallocated reusable workspace; hot bucket exceeds cutoff.'),
        ('global-only', True, 'Global-only radix, workspace growth, and destruction without stream-map allocation.'),
    ):
        indices = [i for i in range(q) if (struct.unpack_from('<I', ib, 24+n*16+i*24+16)[0] == ALL) == want_global]
        ident = 'v2-skewed-' + suffix
        input_path = projections / (ident + '.input.bin')
        expected_path = projections / (ident + '.expected.bin')
        input_path.write_bytes(b'RQENG001' + struct.pack('<QQ', n, len(indices)) + ib[24:24+n*16] + b''.join(ib[24+n*16+i*24:24+n*16+(i+1)*24] for i in indices))
        expected_path.write_bytes(b'RQOUT001' + struct.pack('<Q', len(indices)) + b''.join(eb[16+i*24:16+(i+1)*24] for i in indices))
        selected.append({'id': ident, 'input': str(input_path), 'expected': str(expected_path), 'purpose': purpose,
                         'origin': 'Deterministic query/result projection of v2-skewed; event bytes and retained query/result bytes are unchanged.',
                         'parent_input': str(public / source_item['input']), 'parent_expected': str(public / source_item['expected']),
                         'retained_query_indices': indices})
    for item in selected:
        item.update(sha256_input=file_hash(item['input']), sha256_expected=file_hash(item['expected']), coverage=inspect_input(item['input']))
        assert any(x['radix_passes_forced_by_source'] > 0 for x in item['coverage']['sorted_arrays'])
    plan = {'classification': 'post_hoc_supplemental_memory_diagnostic',
            'excluded_from_original_performance_cost_acceptance_and_canonical_assessment': True,
            'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'source_hash': SOURCE_HASH, 'source_path': str(SOURCE), 'library_sha256': LIBRARY_HASH, 'library_path': str(LIBRARY),
            'native_config': str(CONFIG), 'native_config_file_sha256': file_hash(CONFIG),
            'native_config_sha256': backend.config_hash,
            'driver_sha256': file_hash(backend.config.driver), 'driver_source_sha256': file_hash(STUDY / 'development/native/driver.cpp'),
            'source_binding': 'Existing final canonical compilation and file seal; no rebuild or candidate edit.',
            'finite_plan': 'Five distinct predeclared probes, once each in verify mode; no outcome-selected repetition.',
            'limits': load(CONFIG)['diagnostic'], 'probes': selected,
            'limitations': ['Finite successful calls cannot prove memory safety for all inputs.',
                            'These public timestamp inputs exercise three active low bytes and odd-pass copy-back; not full-width, equal-timestamp, exact-cutoff, or allocation-failure cases.',
                            'Stream-only projection exercises one large radix bucket plus small buckets; it does not demonstrate workspace reuse across multiple large buckets.',
                            'Leak/error checking uses unchanged canonical flags; no suppression is added. Require zero live heap bytes, actual tracked allocations, and zero reported errors.',
                            'Tool/interpreter/system-library dependency closure is not hermetic.']}
    write_new(HERE / 'plan.json', plan)
    records = []
    try:
        for item in selected:
            command = [backend.config.callgrind, '--tool=memcheck', '--vgdb=no', '--error-exitcode=99', '--leak-check=full',
                       '--errors-for-leak-kinds=definite', '--show-leak-kinds=definite', '--extra-debuginfo-path=' + backend.config.debuginfo_root,
                       backend.config.driver, '--library', str(LIBRARY), '--input', item['input'], '--expected', item['expected'],
                       '--mode', 'verify', '--min-seconds', str(backend.config.minimum_sample_seconds),
                       '--max-repetitions', str(backend.config.maximum_repetitions), '--warmups', str(backend.config.warmups)]
            sub = HERE / ('memcheck-' + item['id'])
            result = run_process(command, sub, HERE, backend.config.diagnostic,
                                 {'check_active': lambda: None}, {'VALGRIND_LIB': backend.config.valgrind_lib})
            err = (sub / 'stderr.txt').read_text()
            out = (sub / 'stdout.txt').read_text()
            match = re.search(r'total heap usage: ([\d,]+) allocs, ([\d,]+) frees, ([\d,]+) bytes allocated', err)
            heap = [int(x.replace(',', '')) for x in match.groups()] if match else None
            data = json.loads(out) if out.strip().startswith('{') else None
            clean = bool(result['status'] == 'pass' and result.get('exit_code') == 0 and heap and heap[0] > 0 and heap[0] == heap[1]
                         and 'in use at exit: 0 bytes in 0 blocks' in err and 'ERROR SUMMARY: 0 errors from 0 contexts (suppressed: 0 from 0)' in err
                         and data and data['repetitions'] == data['verified_calls'] == 1)
            row = {'id': item['id'], 'verdict': 'pass' if clean else 'not_pass', 'native_status': result['status'],
                   'exit_code': result.get('exit_code'), 'tracked_allocations': heap[0] if heap else None,
                   'tracked_frees': heap[1] if heap else None, 'allocated_bytes': heap[2] if heap else None,
                   'verified_engine_calls': data.get('verified_calls') if data else None,
                   'command_record': str(sub.relative_to(HERE) / 'command.json'), 'stdout': str(sub.relative_to(HERE) / 'stdout.txt'),
                   'stderr': str(sub.relative_to(HERE) / 'stderr.txt'),
                   'input_hash_unchanged': file_hash(item['input']) == item['sha256_input'],
                   'expected_hash_unchanged': file_hash(item['expected']) == item['sha256_expected']}
            records.append(row)
            print(json.dumps(row), flush=True)
    finally:
        write_new(HERE / 'integrity-after.json', integrity())
        write_new(HERE / 'results.json', {'classification': plan['classification'],
                  'excluded_from_original_performance_cost_acceptance_and_canonical_assessment': True,
                  'status': 'pass' if len(records) == len(selected) and all(r['verdict'] == 'pass' and r['input_hash_unchanged'] and r['expected_hash_unchanged'] for r in records) else 'not_pass',
                  'planned_probes': len(selected), 'attempted_probes': len(records), 'records': records,
                  'limitations': plan['limitations']})


if __name__ == '__main__':
    main()
