"""Fixed, candidate-independent correctness-suite definitions."""
import json
from pathlib import Path
import random
from reference import ALL, U64, I32_MIN, I32_MAX, direct

ROOT = Path(__file__).resolve().parents[1]
# Fresh v2 hand cases: direct expected values, independent of old fixture files.
MANUAL = [
    {'id': 'empty', 'events': [], 'queries': [(0, U64, ALL, 0)], 'expected': [(0, 0, 0, 0)]},
    {'id': 'bounds_duplicates', 'events': [(9, 2, -7), (9, 2, -7), (10, 2, 13), (8, 3, 4)],
     'queries': [(9, 10, 2, 0), (8, 11, ALL, 0), (9, 9, ALL, 0)],
     'expected': [(2, -14, -7, -7), (4, 3, -7, 13), (0, 0, 0, 0)]},
    {'id': 'unsigned_edges', 'events': [(U64, 0, I32_MIN), (U64-1, ALL-1, I32_MAX), (0, 0, -3)],
     'queries': [(U64-1, U64, ALL, 0), (0, U64, 0, 0)],
     'expected': [(1, I32_MAX, I32_MAX, I32_MAX), (1, -3, -3, -3)]},
]
INVALIDS = ['null_events', 'null_queries', 'null_results', 'event_count_limit', 'query_count_limit',
            'event_reserved_stream_first', 'event_reserved_stream_last', 'reverse_first', 'reverse_last',
            'reserved_first', 'reserved_last', 'reserved_all_bits', 'event_invalid_no_queries',
            'reverse_no_events', 'reserved_no_events', 'invalid_after_valid_output']


def plan(suite):
    specs = [{'id': 'hand_' + c['id'], 'kind': 'manual', 'index': i} for i, c in enumerate(MANUAL)]
    specs += [{'id': 'invalid_' + name, 'kind': 'invalid', 'name': name} for name in INVALIDS]
    specs += [{'id': f'random_{i:03d}', 'kind': 'random', 'index': i} for i in range(48)]
    specs += [{'id': f'metamorphic_{i:02d}', 'kind': 'metamorphic', 'index': i} for i in range(8)]
    specs += [{'id': name, 'kind': name} for name in ['zero_null_variants', 'repeated_calls', 'same_pointer_changed_data', 'concurrent_calls', 'maximum_events', 'maximum_queries', 'oversized_events_unbacked', 'oversized_queries_unbacked']]
    specs += [{'id': f'workload_{shape}', 'kind': 'workload', 'shape': shape}
              for shape in ['small_build', 'sparse_narrow', 'dense_wide', 'global_mixed', 'skewed', 'high_cardinality']]
    return specs


def randomized(seed, n=None, q=None):
    rng = random.Random(seed)
    n = rng.randrange(0, 130) if n is None else n
    q = rng.randrange(1, 55) if q is None else q
    events = []
    ts = [0, 1, 2, 8, 31, (1 << 63)-1, 1 << 63, U64-1, U64]
    streams = [0, 1, 7, 9001, ALL-1]
    for i in range(n):
        timestamp = rng.choice(ts) if i % 3 else rng.randrange(0, U64+1)
        value = rng.choice([I32_MIN, I32_MAX, -1, 0, 1]) if i % 4 else rng.randrange(I32_MIN, I32_MAX+1)
        events.append((timestamp, rng.choice(streams), value))
    queries = []
    for i in range(q):
        lo, hi = sorted(rng.sample(ts, 2)) if i % 4 else sorted([rng.randrange(U64+1), rng.randrange(U64+1)])
        if i % 9 == 0: hi = lo
        queries.append((lo, hi, rng.choice(streams + [ALL, 42]), 0))
    if q:
        queries[-1] = (0, U64, ALL, 0)
    rng.shuffle(events)
    return events, queries


def build(spec, suite, case_seed=2026100144):
    kind = spec['kind']
    if kind == 'manual':
        c = MANUAL[spec['index']]
        return {'events': c['events'], 'queries': c['queries'], 'expected': c['expected'], 'return_code': 0}
    if kind == 'random':
        events, queries = randomized(case_seed + spec['index'])
        return {'events': events, 'queries': queries, 'expected': direct(events, queries), 'return_code': 0}
    if kind == 'invalid':
        name = spec['name']
        events = [(0, 1, 5), (1, 2, -9), (2, 1, 7)]
        queries = [(0, 3, ALL, 0), (0, 2, 1, 0), (1, 3, 2, 0)]
        options = {}
        if name.startswith('null_'): options[name] = True
        elif name == 'event_count_limit': options['event_count_override'] = 1000001
        elif name == 'query_count_limit': options['query_count_override'] = 4097
        elif name.startswith('event_reserved_stream_'):
            pos = 0 if name.endswith('first') else -1
            events[pos] = (events[pos][0], ALL, events[pos][2])
        elif name.startswith('reverse_'):
            if name.endswith('no_events'): events = []
            pos = 0 if name.endswith('first') else -1
            queries[pos] = (5, 4, 1, 0)
        elif name.startswith('reserved_'):
            if name.endswith('no_events'): events = []
            pos = 0 if name.endswith('first') else -1
            queries[pos] = (0, 3, 1, ALL if name.endswith('all_bits') else 1)
        elif name == 'event_invalid_no_queries': events[-1] = (2, ALL, 7); queries = []
        elif name == 'invalid_after_valid_output': queries[-1] = (9, 2, 1, 0)
        return {'events': events, 'queries': queries, 'expected': None, 'return_code': 1, **options}
    if kind == 'metamorphic':
        # Fixed group: permutation, multiset duplication, stream relabeling,
        # timestamp translation, partition-additivity and irrelevant records.
        rng = random.Random(case_seed + 100000 + spec['index'])
        events = [(rng.randrange(200), rng.randrange(4), rng.randrange(-10000, 10001)) for _ in range(150)]
        queries = [(a, b, s, 0) for a, b in [(0, 200), (20, 99), (99, 100), (20, 20)] for s in [0, 1, ALL]]
        base = direct(events, queries)
        permuted = events[:]; rng.shuffle(permuted)
        relabeled = [(t, s+17, v) for t, s, v in events]
        relabel_q = [(lo, hi, s+17 if s != ALL else ALL, r) for lo, hi, s, r in queries]
        translated = [(t+1234567890123, s, v) for t, s, v in events]
        translate_q = [(lo+1234567890123, hi+1234567890123, s, r) for lo, hi, s, r in queries]
        double = [tuple([r[0]*2, r[1]*2, r[2], r[3]]) if r[0] else r for r in base]
        cases = [{'events': e, 'queries': q, 'expected': a, 'return_code': 0} for e, q, a in
                 [(events, queries, base), (permuted, queries, base), (events+events, queries, double),
                  (relabeled, relabel_q, base), (translated, translate_q, base),
                  (events+[(999, 42, I32_MIN)], queries, base)]]
        split_queries = [(0, 100, ALL, 0), (100, 200, ALL, 0)]
        split_answers = direct(events, split_queries)
        whole = direct(events, [(0, 200, ALL, 0)])[0]
        assert whole[0] == sum(r[0] for r in split_answers)
        assert whole[1] == sum(r[1] for r in split_answers)
        cases.append({'events': events, 'queries': split_queries, 'expected': split_answers, 'return_code': 0})
        return {'invocations': cases}
    raise ValueError(f'case requires custom worker handling: {kind}')
