"""New draft public fixtures only. No assessment route and no old input reads."""
import argparse
import json
from pathlib import Path
import random
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / 'oracle'))
from reference import ALL, I32_MIN, I32_MAX, direct, indexed, encode_input, encode_expected, sha256


def make(spec):
    rng = random.Random(spec['seed'])
    n, q = spec['event_count'], spec['query_count']
    streams = spec['stream_cardinality']
    span, kind = spec['timestamp_max'] + 1, spec['timestamp_distribution']
    if not 0 < n <= 1000000 or not 0 < q <= 4096 or not 0 < streams < ALL-1 or not 0 < span < 2**64-1:
        raise ValueError('invalid explicit public fixture dimensions')
    events = []
    for i in range(n):
        if kind == 'uniform':
            t = rng.randrange(span)
        elif kind == 'clustered':
            center = rng.choice([span//10, span//2, 9*span//10])
            t = min(span-1, max(0, center + rng.randrange(-max(1,span//1000), max(2,span//1000))))
        else:
            raise ValueError('unknown timestamp distribution')
        stream = 0 if rng.random() < spec.get('hot_event_fraction', 0) else rng.randrange(streams)
        value = rng.choice([I32_MIN, I32_MAX, -1, 0, 1]) if i % 31 == 0 else rng.randrange(-100000, 100001)
        events.append((t, stream, value))
    queries = []
    for i in range(q):
        lo = rng.randrange(span)
        if 'narrow_width_max' in spec:
            width = rng.randrange(1, spec['narrow_width_max'] + 1)
        else:
            lower, upper = spec['query_width_fraction']
            width = rng.randrange(max(1, int(lower*span)), max(2, int(upper*span)+1))
        if rng.random() < spec.get('empty_query_fraction', 0):
            width = 0
        stream = 0 if rng.random() < spec.get('hot_query_fraction', 0) else rng.randrange(streams)
        if rng.random() < spec.get('all_stream_query_fraction', 0):
            stream = ALL
        elif rng.random() < spec.get('absent_query_fraction', 0):
            stream = streams + 1
        queries.append((lo, min(span + 1, lo + width), stream, 0))
    if spec.get('force_first_global_query', True):
        queries[0] = (0, span, ALL, 0)
    rng.shuffle(events)
    return events, queries


def generate(definitions, destination, suites=('development', 'profile')):
    definitions = Path(definitions)
    config = json.loads(definitions.read_text())
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    requested_suites = tuple(suites)
    suites = {}
    for suite in requested_suites:
        entries = []
        for spec in config[suite]:
            events, queries = make(spec)
            answers = indexed(events, queries)
            crosscheck = spec['direct_crosscheck']
            indices = list(range(len(queries))) if crosscheck['mode'] == 'all' else sorted(set(i for i in crosscheck['query_indices'] if i < len(queries)))
            if [answers[i] for i in indices] != direct(events, [queries[i] for i in indices]):
                raise AssertionError('independent direct/indexed generation check failed')
            inp, expected = encode_input(events, queries), encode_expected(answers)
            i, e = spec['id'] + '.input.bin', spec['id'] + '.expected.bin'
            (destination / i).write_bytes(inp)
            (destination / e).write_bytes(expected)
            entries.append({**spec, 'actual_all_stream_queries': sum(q[2] == ALL for q in queries), 'actual_empty_queries': sum(q[0] == q[1] for q in queries), 'direct_crosscheck_query_indices': indices, 'input': i, 'expected': e, 'sha256_input': sha256(inp), 'sha256_expected': sha256(expected)})
        suites[suite] = entries
    manifest = {'schema_version': 1, 'status': config['status'], 'definitions_sha256': sha256(definitions.read_bytes()),
                'root_relative_paths': True, 'suites': suites}
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    return manifest


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--definitions', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(generate(args.definitions, args.output)))
