"""Offline numeric-only post-freeze reanalysis; never imports/starts the runtime.

Reads an explicit telemetry JSON path and prints a separate derived report.
It never edits input evidence or observes model/session/authentication content.
"""
from __future__ import annotations
import argparse
from collections import Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path

AS_OF = '2026-10-01'
SHORT_MAX_INPUT = 272000
COUNTERS = ('inputTokens', 'cachedInputTokens', 'cacheWriteInputTokens',
            'outputTokens', 'reasoningOutputTokens', 'totalTokens')
RATES = {
    'gpt-6.1-sol': {'short': ('2', '.10', '2.50', '10'), 'long': ('4', '.20', '5', '15')},
    'gpt-6-luna': {'short': ('.10', '.01', '.125', '.50'), 'long': ('.20', '.02', '.25', '.75')},
}
SOURCES = {
    'sol_threshold': 'https://developers.openai.com/api/docs/models/gpt-6.1-sol',
    'luna_threshold': 'https://developers.openai.com/api/docs/models/gpt-6-luna',
    'prices': 'https://developers.openai.com/api/docs/pricing',
    'cache_partition': 'https://developers.openai.com/api/docs/guides/prompt-caching',
    'completed_response_parser': 'https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/codex-api/src/sse/responses.rs#L395',
    'terminal_response_usage_append': 'https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/core/src/session/turn.rs#L2805',
    'append_semantics': 'https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/protocol/src/protocol.rs#L2152',
    'context_bookkeeping': 'https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/core/src/session/mod.rs#L4655',
    'cache_write_default': 'https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/codex-api/src/sse/responses.rs#L138',
    'compaction_v2_separate_record': 'https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/core/src/compact_remote_v2.rs#L446',
    'separate_record_vs_public_history': 'https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/core/src/state/session.rs#L201',
}


def checked(row):
    if any(type(row.get(k)) is not int or row[k] < 0 for k in COUNTERS):
        raise ValueError('integer counter required for this complete numeric replay')
    if row['inputTokens'] + row['outputTokens'] != row['totalTokens']:
        raise ValueError('input/output total mismatch')
    if row['cachedInputTokens'] + row['cacheWriteInputTokens'] > row['inputTokens']:
        raise ValueError('invalid cache partition')
    if row['reasoningOutputTokens'] > row['outputTokens']:
        raise ValueError('reasoning is not an output subset')
    return {k: row[k] for k in COUNTERS}


def interval(row, model, bands):
    # Protocol W=0 does not attest absence of provider cache writes. Never use it
    # as verified W for these bounds. The W endpoints exhaust [0,I-R].
    I, R, O = (Decimal(row[k]) for k in ('inputTokens', 'cachedInputTokens', 'outputTokens'))
    costs = []
    for band in bands:
        ordinary, read, write, output = map(Decimal, RATES[model][band])
        for W in (Decimal(0), I-R):
            costs.append(((I-R-W)*ordinary + R*read + W*write + O*output)/Decimal(1000000))
    return min(costs), max(costs)


def analyze(path):
    raw = Path(path).read_bytes(); data = json.loads(raw)
    seen = set(); rows = []; low = Decimal(0); high = Decimal(0)
    all_totals = Counter(); all_classes = Counter(); all_bands = Counter()
    for agent in data['agents']:
        tid = agent['thread_id']
        if not tid or tid in seen:
            raise ValueError('missing or repeated thread identity')
        seen.add(tid)
        usage = agent['token_usage']
        if not usage['observed_accounting_complete'] or usage['issues']:
            raise ValueError('this replay requires complete consistent observed cumulative usage')
        previous = dict.fromkeys(COUNTERS, 0)
        classes = Counter(); bands = Counter(); turns = {}; observations = []
        row_low = Decimal(0); row_high = Decimal(0)
        for update in usage['updates']:
            classes[update['classification']] += 1
            if update['classification'] == 'context_estimate_no_usage_increment':
                if checked(update['total']) != previous:
                    raise ValueError('context bookkeeping changed cumulative usage')
                continue
            total = checked(update['total'])
            delta = {key: total[key]-previous[key] for key in COUNTERS}
            if min(delta.values()) < 0:
                raise ValueError('counter regression')
            if not any(delta.values()):
                previous = total
                continue
            checked(delta)
            last = checked(update['last'])
            matches = delta == last
            # Source: cumulative positive increments append terminal response
            # usage, never streaming token installments. Even if an interval
            # aggregates multiple nonnegative complete reports, each input <=
            # its aggregate input. This proves short for small aggregate deltas.
            band = ('short' if delta['inputTokens'] <= SHORT_MAX_INPUT else
                    'long' if matches else 'unresolved_mixture')
            choices = (band,) if band != 'unresolved_mixture' else ('short', 'long')
            a, b = interval(delta, agent['model'], choices)
            row_low += a; row_high += b; bands[band] += 1
            turn = turns.setdefault(update['turn_id'], {'observations': 0, 'input_tokens': 0, 'max_delta_input': 0})
            turn['observations'] += 1; turn['input_tokens'] += delta['inputTokens']
            turn['max_delta_input'] = max(turn['max_delta_input'], delta['inputTokens'])
            observations.append({'turn_id': update['turn_id'], 'input_tokens': delta['inputTokens'],
                                 'delta_matches_last': matches, 'price_band': band,
                                 'tokens': delta,
                                 'observed_subtotal_lower_usd': str(a),
                                 'observed_subtotal_upper_usd': str(b),
                                 'observed_unix_seconds': update.get('observed_unix_seconds'),
                                 'elapsed_from_host_start_seconds': update.get('elapsed_from_host_start_seconds'),
                                 'time_provenance': 'notification_observation'})
            previous = total
        if previous != checked(usage['total']):
            raise ValueError('final endpoint does not reconcile')
        low += row_low; high += row_high
        all_totals.update(previous); all_classes.update(classes); all_bands.update(bands)
        rows.append({'agent_id': agent['agent_id'], 'thread_id': tid, 'role': agent['role'], 'model': agent['model'],
                     'notifications': len(usage['updates']), 'classifications': dict(classes), 'bands': dict(bands),
                     'max_observed_input': max(x['input_tokens'] for x in observations),
                     'total': previous, 'turn_segments': list(turns.values()), 'observations': observations,
                     'compaction_observed': 'compaction_observed' in agent.get('issues', []),
                     'observed_subtotal_lower_usd': str(row_low), 'observed_subtotal_upper_usd': str(row_high),
                     'short_or_resolved_band_cache_write_interval_usd': [str(row_low), str(row_high)]})
    return {'schema_version': 1, 'analysis_only': True, 'analysis_as_of': AS_OF,
            'source_telemetry_path': str(Path(path)), 'source_telemetry_sha256': hashlib.sha256(raw).hexdigest(),
            'counter_scope': 'Exact observed CLI counts, not verified complete provider billing',
            'hypothetical_tier': 'Standard', 'threshold_input_tokens': SHORT_MAX_INPUT,
            'threshold_boundary': 'short if input <=272000; long if input >272000',
            'threshold_provenance': 'Official Sol and Luna model pages retrieved 2026-10-01',
            'classification_provenance': 'Pinned complete-response append semantics plus numeric reconciliation; no provider response IDs',
            'totals': dict(all_totals), 'classifications': dict(all_classes), 'bands': dict(all_bands),
            'observed_subtotal_interval_usd': [str(low), str(high)], 'actual_bill': None,
            'coverage': {'frozen_observed_accounting_complete': data.get('accounting_complete'),
                         'compaction_observed': any(row['compaction_observed'] for row in rows),
                         'all_model_work_verified': False, 'cache_write_reporting_verified': False,
                         'provider_request_ids_available': False, 'billing_tier_verified': False,
                         'unobserved_cost_unknown': True, 'finite_whole_run_cost_bounds_available': False},
            'whole_run_cost_bounds': None, 'cache_write_reporting_verified': False,
            'unobserved_retry_or_compaction_cost': None, 'threads': rows, 'sources': SOURCES}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('telemetry', type=Path)
    print(json.dumps(analyze(parser.parse_args().telemetry), indent=2))
