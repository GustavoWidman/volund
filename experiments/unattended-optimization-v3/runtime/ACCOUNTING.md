# Public usage accounting and provenance

The source is Codex 0.159.3's public `thread/tokenUsage/updated` notification. It
contains `threadId`, `turnId`, `tokenUsage.total`, `tokenUsage.last`, and optional
`modelContextWindow`. The five required numeric counters are input, cached input,
output, reasoning output, and total. Cache-write input is optional in JSON and has
a protocol default of zero. The generated schema is checked in with file hashes
under `protocol-0.159.3/`; no app-server or model was started to generate it.

## Counter rules

For each fresh, owner-registered thread, preserve every numeric snapshot and count
one valid final cumulative endpoint across all its turns. Repeated snapshots are
not new usage. Sum thread endpoints for role and campaign totals. Input includes
cached input; reasoning is a subset of output. Neither is added again.

Request-shaped observations are unique cumulative increments. When the increment
matches `last`, the source's append operation supports a response-usage interpretation.
There is still no public provider response ID in this stream, so these are not
attested request records. Do not assign a precise billing tier or long-context
price class based only on an endpoint or the model's maximum context window.

Absent cache-write fields remain null. A present protocol zero is preserved as an
observed zero while `cache_write_reporting_verified=false`: it may be the default,
not upstream reporting. `provider_service_tier`, `request_long_context_price_class`,
and `exact_priceable_partition` remain null until independently verified. These
fields prevent an attractive but unsupported exact-dollar estimate.

If authoritative I/R/W/O partition and price class are available elsewhere through
a supported authorized route, ordinary input is I-R-W, and output already includes
reasoning. The host checks nonnegative counters, I+O=total, R<=I, R+W<=I when W is
present, and reasoning<=O. Current `observed_accounting_complete` means complete,
consistent observed cumulative telemetry for each admitted turn. It never means
that all failed/interrupted provider work was billable or fully reported.

## Context bookkeeping is not a model call

The pinned source distinguishes two mechanisms:

- `recompute_token_usage` retains cumulative usage and changes only `last` to a
  local estimated context count with other counters zero. The reducer recognizes
  that pattern when cumulative totals are unchanged, retains the estimate as
  bookkeeping, and charges no new usage. A compaction item alone is not a failure.
- `fill_to_context_window`, used by context-capacity error handling, can replace
  cumulative counters with a total-only sentinel. The reducer preserves the last
  known valid observation, records the sentinel and an unresolved accounting gap,
  and does not fabricate replacement usage. An unexplained cumulative regression
  is likewise incomplete, never silently converted to a new epoch.

Compaction inference that arrives as ordinary cumulative usage is counted in the
owning thread. Compaction summaries and hidden reasoning are never exported.
A duplicate total attributed to a new turn does not prove new-turn usage; that
turn remains missing until an actual positive cumulative increment is observed.

Interrupted, failed, or missing-report requests may have unreported usage. Missing
usage is unknown, never zero. If native or unregistered activity appears, known
thread totals remain available separately, while whole-campaign totals are null.
An interrupted or failed turn keeps the thread's observed accounting incomplete
even if it emitted some usage or a later turn completes. Public branch abandonment
therefore requests a cooperative wrap-up rather than forcibly interrupting a call.
Late usage before sealing is incorporated. After sealing, known idle/unloaded/closed
lifecycle and exact duplicate terminal/usage events are benign. New usage is retained
and invalidates the sealed result, as does new tool activity. Shutdown drains the
protocol stream before final export. A reconnect/restart requires a new reconciliation design; this
prototype does not silently restart and pretend the stream remained complete.

## Observation times and hypothetical prices

Every live usage notification carries `observed_unix_seconds`,
`elapsed_from_host_start_seconds`, and `time_provenance=notification_observation`.
These are receipt times, not provider execution or billing times. Both ordinary
usage and duplicate/context snapshots retain their observation coordinates.
Do not interpolate a token count for a native comparison that happened between
notifications. A standalone/replayed reducer without original times records null.

`runtime.pricing.price_ledger(host.export())` computes hypothetical Standard
API-equivalent bounds for the observed token subtotal. It uses each unique thread's
final cumulative endpoint once and sums by role; duplicate thread IDs, regressed
counters, and invalid partitions are rejected. Cached tokens are part of input;
reasoning is part of output. No aggregate or repeated snapshot is charged again.

With I=input, R=cache reads, W=cache writes, O=output, the formula is
`((I-R-W)*ordinary_rate + R*read_rate + W*write_rate + O*output_rate)/1,000,000`.
If cache-write reporting is unverified, W ranges from zero through I-R even when
the protocol field is zero. The utility considers both short and long prices;
it does not infer a context threshold or request price band. It emits per-thread,
per-role, and combined `observed_subtotal_bounds`, using decimal arithmetic and
retaining exact decimal strings alongside chart-friendly numeric values.

Missing usage is listed explicitly. A partial observed subtotal interval is not
a bound on the whole run, and the utility always leaves `whole_run_cost_bounds`,
`actual_billed_cost`, and actual provider billing tier null. Subscription usage
cannot be equated with a pay-as-you-go API charge.

Standard rates were retrieved on 2026-10-01 from the official
[pricing page](https://developers.openai.com/api/docs/pricing), with model references
for [Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol) and
[Luna](https://developers.openai.com/api/docs/models/gpt-6-luna). Per million tokens,
ordinary/read/write/output rates are Sol short 2/.10/2.50/10 and long 4/.20/5/15;
Luna short .10/.01/.125/.50 and long .20/.02/.25/.75 USD. The partition follows the
official [prompt-caching guide](https://developers.openai.com/api/docs/guides/prompt-caching).

## Official source anchors, inspected 2026-10-01

- [Pinned config schema](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/core/config.schema.json):
  `AgentsToml.enabled` documents the multi-agent disable and v2 precedence
- [Protocol definitions](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/protocol/src/protocol.rs):
  `TokenUsageInfo::append_last_usage`, `fill_to_context_window`, and
  `TokenUsageRecord` (approximately lines2087–2178)
- [Session usage handling](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/core/src/session/mod.rs):
  `record_token_usage_info`, `recompute_token_usage`, `send_token_count_event`, and
  `set_total_tokens_full` (approximately lines4564–4737)
- [Public notification mapping](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/app-server/src/bespoke_event_handling.rs):
  `handle_token_count_event` maps TokenCountEvent into the public thread usage
  notification (approximately lines1553–1568)
- [Context replacement](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/core/src/context_manager/history.rs):
  `replace_compacted` and `update_token_info` preserve/append usage independently
  of the message history replacement
- [Current official app-server guide](https://developers.openai.com/codex/app-server/):
  dynamic tool request/reply flow and read versus resume subscription behavior

The generated schema also contains `rawResponse/completed` with response IDs and
usage, but marks it internal-only. This client does not enable raw events or use
internal rollout records to bridge public observability gaps. General web docs can
drift from 0.159.3; generated pinned schemas determine payload shapes.
