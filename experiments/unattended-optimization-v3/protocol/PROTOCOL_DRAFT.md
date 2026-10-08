# Version 3 protocol change record

Status: 2026-10-01 UTC, corrective development candidate. No v3 measured campaign has started and no new freeze or readiness verdict is asserted here.

The complete candidate specification is [PROTOCOL.md](PROTOCOL.md). This file records the design decisions and unresolved implementation checks rather than maintaining a competing copy of the protocol. The older v2 source and evidence remain in the sibling experiment and historical manuscript checkpoint.

## User-directed revision

The user requested correcting the measurement workflow and rerunning all three campaigns from the original seed in fresh model contexts. The prior outcome is preserved. New measured participants must receive no earlier optimization histories, optimized endpoints, performance results, or algorithmic suggestions derived from those runs. The design team's exposure is disclosed; the rerun is not a randomized comparison of versions.

The requested role map is unchanged: Sol/high lead and independent reviewer, Luna/xhigh execution workers, with the exact model identifiers in the candidate protocol and deployment config. Research has no arbitrary wall-time, token, hypothesis, promotion, or recovery-attempt quota. Ordinary shell remains fully usable through a sandbox-preserving routed execution tool.

## Concrete protocol decisions

- One exclusive scheduler lane covers arbitrary shell and every native build, test, profile, memory-check, benchmark, and automatic trajectory job. Final assessment must use that same scheduling/recovery path. FIFO starts at coordinator admission; earlier metadata locks may change request arrival order.
- Bounded structured reads and model planning remain available while a benchmark is running. Read tools execute no code, enforce path/type/output limits, and do not acquire a benchmark-held metadata lock. Compact status does not dump the whole usage/evidence ledger.
- A timing request preserves an immutable series of attempts. Only an independently observed competing-command overlap during otherwise-passing execution or an owner-attested external preemption with confirmed cleanup authorizes an automatic repeat. Each repeat uses the same source, build, reference, fixtures, review binding, and frozen measurement procedure.
- Every failed or invalid attempt remains visible. The first complete valid attempt ends the request, regardless of gain, uncertainty bound, or under-target flag. A repeat rejoins the scheduler queue.
- Candidate timeouts/hangs, resource-limit failures, semantic or memory errors, unknown exceptions, user/owner cancellation, failed routing, or unresolved cleanup do not authorize measurement retries. Valid disappointing observations remain valid. Repaired-source and question-driven scientific follow-ups remain allowed, without replacing a binding nomination sample.
- A recoverable timing event does not revoke an already valid promotion or automatically close the campaign. Promotion, hypothesis verdict, trajectory availability, and task completion are separately reported.
- Compact summaries are navigational aids. Source, journal, and evidence details remain explicitly addressable with bounded retrieval and visible continuation. Independent review must inspect its required exact-source evidence; delivery alone is not comprehension.
- Keep the existing six-family, ten-block development gates and thirty-block final transfer/shift estimator in the candidate specification. These choices become authoritative only with the new validated freeze. No improvement is required for a truthful completed seed endpoint.

## Implementation checks still required before freeze

The candidate protocol is normative. At the time of this edit, scheduler/retry code was under review and the final evaluator had not yet been routed through the same recovery wrapper. Tool schemas for workspace execution and bounded reads were still being finalized. These are launch blockers until current evidence confirms their implementation.

Require a new realistic multiagent preflight, native integration controls, independent review, and freeze. The preflight must exercise concurrent role work, actual sandboxed arbitrary shell, background/detached descendants, timeout/cancel/disconnect cleanup or quarantine, nonblocking bounded reads, exact-artifact recovery, score-blind first-valid selection, and the final-evaluator route. Synthetic synchronization tests and earlier readiness records cannot replace these checks. All passed, failed and not-run setup controls remain labeled separately from measured outcomes.

The complete launch checklist, failure distinctions, accounting limits, and final-assessment embargo are in PROTOCOL.md §§8–13. Resolve implementation deviations in source and this candidate before freeze; after freeze, any substantive change requires an explicit versioned amendment.
