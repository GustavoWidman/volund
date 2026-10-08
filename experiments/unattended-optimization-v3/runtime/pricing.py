"""Hypothetical Standard API-equivalent bounds for an observed token subtotal.

This is neither a ChatGPT subscription bill nor an estimate of unreported calls.
Use one final cumulative endpoint per unique thread. Request snapshots, cached
reads, cache writes, and reasoning are never charged a second time.
"""
from __future__ import annotations

import copy
from decimal import Decimal

RATES_AS_OF = '2026-10-01'
RATE_FIELDS = ('ordinary_input', 'cache_read', 'cache_write', 'output')
STANDARD_RATES_USD_PER_MILLION = {
    'gpt-6.1-sol': {
        'short': dict(zip(RATE_FIELDS, ('2.00', '0.10', '2.50', '10.00'))),
        'long': dict(zip(RATE_FIELDS, ('4.00', '0.20', '5.00', '15.00'))),
    },
    'gpt-6-luna': {
        'short': dict(zip(RATE_FIELDS, ('0.10', '0.01', '0.125', '0.50'))),
        'long': dict(zip(RATE_FIELDS, ('0.20', '0.02', '0.25', '0.75'))),
    },
}
SOURCES = (
    'https://developers.openai.com/api/docs/pricing',
    'https://developers.openai.com/api/docs/models/gpt-6.1-sol',
    'https://developers.openai.com/api/docs/models/gpt-6-luna',
    'https://developers.openai.com/api/docs/guides/prompt-caching',
)
MILLION = Decimal(1_000_000)


class PricingFailure(ValueError):
    """Invalid attribution/partition; never silently produce misleading money."""


def _integer(value):
    if type(value) is not int or value < 0:
        raise PricingFailure('invalid_token_counter')
    return value


def _partition(total):
    if not isinstance(total, dict):
        raise PricingFailure('invalid_token_partition')
    incoming = _integer(total.get('inputTokens'))
    read = _integer(total.get('cachedInputTokens'))
    output = _integer(total.get('outputTokens'))
    reasoning = _integer(total.get('reasoningOutputTokens'))
    combined = _integer(total.get('totalTokens'))
    writes = total.get('cacheWriteInputTokens')
    if writes is not None:
        writes = _integer(writes)
    if read > incoming or reasoning > output or combined != incoming + output:
        raise PricingFailure('invalid_token_partition')
    if writes is not None and read + writes > incoming:
        raise PricingFailure('invalid_token_partition')
    return incoming, read, writes, output


def _band_bounds(model, incoming, read, output, write_range, band):
    rates = {k: Decimal(v) for k, v in STANDARD_RATES_USD_PER_MILLION[model][band].items()}
    # Linear in W. Testing both endpoints is valid even if future rate schedules
    # reverse the relative ordinary/write rates.
    choices = [((incoming-read-writes) * rates['ordinary_input'] + read * rates['cache_read']
                + writes * rates['cache_write'] + output * rates['output']) / MILLION
               for writes in write_range]
    return min(choices), max(choices)


def _export_bound(lower, upper):
    # Arithmetic uses decimal prices. JSON numbers are presentation values; exact
    # decimal strings are retained for reproducible downstream sums.
    return {'lower_usd': float(lower), 'upper_usd': float(upper),
            'lower_usd_decimal': format(lower, 'f'), 'upper_usd_decimal': format(upper, 'f')}


def _sum_bound(rows):
    if not rows:
        return None  # No observed priceable usage is not evidence of zero spend.
    return _export_bound(sum((lo for lo, _ in rows), Decimal(0)),
                         sum((hi for _, hi in rows), Decimal(0)))


def price_ledger(ledger):
    """Price a Host.export() snapshot, without trusting cached aggregate totals.

    The interval covers only the subtotal in unique thread endpoint observations.
    Cache writes vary over [0, I-R] unless explicitly verified in that thread's
    usage record. The context band is always unknown here: evaluate both short and
    long. Actual billing tier is unknown; Standard is a hypothetical convention.
    Missing calls/threads have unknown cost, not zero and not this interval.
    """
    if not isinstance(ledger, dict) or not isinstance(ledger.get('agents'), list):
        raise PricingFailure('invalid_ledger')
    seen = set()
    threads, missing, incomplete, role_rows, bounds = [], [], [], {}, []
    all_observed_complete = bool(ledger['agents'])
    for agent in ledger['agents']:
        if not isinstance(agent, dict):
            raise PricingFailure('invalid_agent_record')
        thread_id, role, model = agent.get('thread_id'), agent.get('role'), agent.get('model')
        if not isinstance(role, str) or not role:
            raise PricingFailure('missing_role_attribution')
        if thread_id is not None:
            if not isinstance(thread_id, str) or not thread_id:
                raise PricingFailure('invalid_thread_id')
            if thread_id in seen:
                raise PricingFailure('duplicate_thread_id')
            seen.add(thread_id)
        role_info = role_rows.setdefault(role, {'bounds': [], 'missing': 0, 'priced_threads': 0})
        usage = agent.get('token_usage') or {}
        total = usage.get('total')
        if thread_id is None or total is None:
            missing.append({'agent_id': agent.get('agent_id'), 'thread_id': thread_id, 'role': role,
                            'reason': 'thread_identity_missing' if thread_id is None else 'usage_missing'})
            role_info['missing'] += 1
            all_observed_complete = False
            continue
        if model not in STANDARD_RATES_USD_PER_MILLION:
            raise PricingFailure('unsupported_model_price')
        if 'cumulative_counter_regression' in usage.get('issues', []):
            raise PricingFailure('regressed_cumulative_usage_not_priceable')
        incoming, read, reported_writes, output = _partition(total)
        write_verified = usage.get('cache_write_reporting_verified') is True
        if write_verified and reported_writes is None:
            raise PricingFailure('verified_cache_write_counter_missing')
        writes = (reported_writes, reported_writes) if write_verified else (0, incoming-read)
        band_bounds = {band: _band_bounds(model, incoming, read, output, writes, band)
                       for band in ('short', 'long')}
        lower = min(row[0] for row in band_bounds.values())
        upper = max(row[1] for row in band_bounds.values())
        row_complete = usage.get('observed_accounting_complete') is True
        all_observed_complete &= row_complete
        if not row_complete:
            incomplete.append({'thread_id': thread_id, 'role': role,
                               'issues': list(usage.get('issues', [])),
                               'turns_without_usage': list(usage.get('turns_without_usage', []))})
        rows = {'agent_id': agent.get('agent_id'), 'thread_id': thread_id, 'role': role,
                'model': model, 'observed_accounting_complete': row_complete,
                'cache_write_reporting_verified': write_verified,
                'reported_protocol_cache_write_tokens': reported_writes,
                'cache_write_tokens_considered': {'minimum': writes[0], 'maximum': writes[1]},
                'observed_token_total': dict(total),
                'context_band': 'unknown', 'actual_billing_tier': None,
                'short_context_bounds': _export_bound(*band_bounds['short']),
                'long_context_bounds': _export_bound(*band_bounds['long']),
                'observed_subtotal_bounds': _export_bound(lower, upper)}
        threads.append(rows)
        bounds.append((lower, upper))
        role_info['bounds'].append((lower, upper))
        role_info['priced_threads'] += 1
    roles = {role: {'priced_threads': info['priced_threads'], 'missing_usage_threads': info['missing'],
                    'observed_subtotal_bounds': _sum_bound(info['bounds'])}
             for role, info in role_rows.items()}
    return {
        'schema_version': 1,
        'label': 'Hypothetical Standard API-equivalent bounds for observed token subtotal',
        'currency': 'USD', 'hypothetical_api_tier': 'Standard',
        'rates_as_of': RATES_AS_OF, 'rate_sources': list(SOURCES),
        'rates_usd_per_million': copy.deepcopy(STANDARD_RATES_USD_PER_MILLION),
        'context_band_threshold_tokens': None, 'context_band_threshold_verified': False,
        'threads': threads, 'per_role': roles,
        'observed_subtotal_bounds': _sum_bound(bounds),
        'observed_accounting_complete': bool(all_observed_complete and ledger.get('accounting_complete') is True),
        'missing_usage': missing,
        'incomplete_usage_threads': incomplete,
        'whole_run_cost_bounds': None, 'unobserved_usage_cost': None,
        'actual_billed_cost': None, 'actual_billing_tier': None,
        'scope': 'Unique observed thread cumulative endpoints only; missing or unreported calls are excluded with unknown cost.',
        'sum_rule': 'Count each thread once; ordinary input = I-R-W; output already includes reasoning.',
        'limits': [
            'These bounds are not bounds on the whole run or the actual bill.',
            'Protocol cache-write zero is not authoritative unless reporting was independently verified.',
            'Short/long request mix and actual provider billing tier are unknown.',
            'No context threshold or provider request boundary is inferred from cumulative totals.',
        ],
    }
