"""Per-thread public usage accounting and an explicit ordinary-content boundary."""
from __future__ import annotations
from dataclasses import dataclass, field
import copy
import math
from .contracts import RuntimeFailure

COUNTERS = ('inputTokens', 'cachedInputTokens', 'cacheWriteInputTokens',
            'outputTokens', 'reasoningOutputTokens', 'totalTokens')


def zero():
    return dict.fromkeys(COUNTERS, 0)


def breakdown(raw):
    if not isinstance(raw, dict):
        raise RuntimeFailure('invalid_usage')
    result = {}
    for key in COUNTERS:
        value = raw.get(key, None)
        if key == 'cacheWriteInputTokens' and value is None:
            result[key] = None  # Omission is unknown, never fabricated zero.
        elif type(value) is not int or value < 0:
            raise RuntimeFailure('invalid_usage_counter')
        else:
            result[key] = value
    return result


@dataclass
class ThreadUsage:
    total: dict | None = None
    updates: list = field(default_factory=list)
    turns_seen: set = field(default_factory=set)
    issues: set = field(default_factory=set)
    duplicates: int = 0

    def add(self, turn_id, raw, *, observed_unix_seconds=None, elapsed_from_host_start_seconds=None):
        timing = {'observed_unix_seconds': observed_unix_seconds,
                  'elapsed_from_host_start_seconds': elapsed_from_host_start_seconds,
                  'time_provenance': 'notification_observation'}
        for value in (observed_unix_seconds, elapsed_from_host_start_seconds):
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                raise RuntimeFailure('invalid_usage_observation_time')
        total, last = breakdown(raw.get('total')), breakdown(raw.get('last'))
        previous = self.total or zero()
        def total_only(row):
            return row['totalTokens'] > 0 and all(row[k] in (0, None) for k in COUNTERS if k != 'totalTokens')
        # Source-confirmed recompute_token_usage preserves cumulative totals and
        # replaces only last with a local estimate. It is NOT a model response.
        if total == previous and total_only(last):
            self.updates.append({**timing, 'turn_id': turn_id, 'total': total, 'last': last,
                                 'delta': zero(), 'duplicate': True,
                                 'classification': 'context_estimate_no_usage_increment'})
            self.duplicates += 1
            return
        # Context-capacity errors can replace even cumulative totals with a
        # sentinel. Preserve the last valid observation and make the gap explicit.
        if total_only(total):
            self.issues.add('context_capacity_replaced_usage')
            self.updates.append({**timing, 'turn_id': turn_id, 'total': total, 'last': last,
                                 'delta': None, 'duplicate': False,
                                 'classification': 'unreconciled_context_capacity_sentinel'})
            return
        for row in (total, last):
            if row['totalTokens'] != row['inputTokens'] + row['outputTokens']:
                self.issues.add('total_not_input_plus_output')
            if row['cachedInputTokens'] > row['inputTokens']:
                self.issues.add('cache_read_exceeds_input')
            if row['reasoningOutputTokens'] > row['outputTokens']:
                self.issues.add('reasoning_exceeds_output')
            if row['cacheWriteInputTokens'] is not None and row['cacheWriteInputTokens'] + row['cachedInputTokens'] > row['inputTokens']:
                self.issues.add('cache_partition_exceeds_input')
        previous = self.total or zero()
        delta = {k: total[k] - previous[k] if total[k] is not None and previous[k] is not None else None for k in COUNTERS}
        duplicate = total == self.total
        if duplicate:
            self.duplicates += 1
        else:
            if any(v is not None and v < 0 for v in delta.values()):
                self.issues.add('cumulative_counter_regression')
            # A missed notification can still leave a usable cumulative endpoint,
            # but cannot support a claim to observe every upstream response.
            if any(delta[k] != last[k] for k in COUNTERS if delta[k] is not None and last[k] is not None):
                self.issues.add('increment_does_not_match_last')
        self.total = total
        if not duplicate and any(value is not None and value > 0 for value in delta.values()):
            self.turns_seen.add(turn_id)
        self.updates.append({**timing, 'turn_id': turn_id, 'total': total, 'last': last,
                             'delta': delta, 'duplicate': duplicate,
                             'classification': 'duplicate_snapshot' if duplicate else 'cumulative_usage_change'})

    def export(self, completed_turns, terminal):
        missing = sorted(set(completed_turns) - self.turns_seen)
        return {'total': copy.deepcopy(self.total), 'updates': copy.deepcopy(self.updates),
                'duplicates': self.duplicates, 'issues': sorted(self.issues),
                'turns_without_usage': missing,
                'observed_accounting_complete': bool(terminal and self.total is not None and not missing and not self.issues),
                'provider_billing_completeness_verified': False,
                'cache_write_reporting_verified': False,
                'cache_write_provenance': 'Protocol field defaults to zero; presence alone does not attest upstream reporting.',
                'provider_service_tier': None,
                'request_long_context_price_class': None,
                'exact_priceable_partition': None,
                'request_observations': [dict(u, boundary_provenance='Unique cumulative change; not a verified provider response ID') for u in self.updates if u.get('classification') == 'cumulative_usage_change'],
                'provider_response_ids_available': False,
                'unreported_failed_request_usage': None,
                'sum_rule': 'One final cumulative total per fresh thread across all turns; cached and reasoning are subsets, not additions.'}


def sum_totals(rows):
    """Return None for any counter missing from any admitted thread."""
    rows = list(rows)
    return {key: (sum(row[key] for row in rows) if all(row is not None and row[key] is not None for row in rows) else None)
            for key in COUNTERS}


def public_item(item):
    """Select public command/output/patch evidence; NEVER serialize raw events."""
    kind = item.get('type')
    if kind == 'commandExecution':
        keys = ('id', 'type', 'command', 'cwd', 'status', 'aggregatedOutput', 'exitCode', 'durationMs')
    elif kind == 'fileChange':
        result = {k: copy.deepcopy(item[k]) for k in ('id', 'type', 'status') if k in item}
        result['changes'] = [{k: copy.deepcopy(row[k]) for k in ('path', 'kind', 'diff') if k in row}
                             for row in item.get('changes', [])]
        return result
    else:
        return None
    return {k: copy.deepcopy(item[k]) for k in keys if k in item}
