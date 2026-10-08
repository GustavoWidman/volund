# Controlled optimization study: version 3

Status: all three campaigns and the first automatic final assessment completed
on 2026-10-02 UTC. The original seed and contract are retained. Earlier v2 source,
measurements and rejected manuscript are preserved separately and are not v3
results.

## Verified results and delivery

The final transfer portfolio speedups over the original seed are **2.240×,
4.547× and 5.445×** for C1–C3. Shifted-input portfolios are **2.236×, 5.186×
and 5.294×**. These are descriptive results for one synthetic task. C1's shifted
sparse family is slower (0.911×, approximately 9.7% higher latency), despite its
portfolio gain. All three endpoints passed the declared final validation.

The cohort retained 13 reviewed hypotheses, eight promotions, 21 role agents and
68 completed turns. Observed model tokens correspond to USD 17.075–18.230 under
the dated Standard API-equivalent scenario. Unreported compaction work and other
provider coverage limits prevent a whole-run cost bound or actual-bill claim.

The [main manuscript](../../docs/ai-development-workflow/ai-development-workflow-draft.pdf)
and [supplement](../../docs/ai-development-workflow/ai-development-workflow-supplement.pdf)
retain these limits. [Release instructions](release/DELIVERY-README.md) describe
the verified 22.33 MB compressed source/numerical evidence package. A separate
full archive preserves additional original bytes; it is not a Git payload.
[Post-hoc memory diagnostics](analysis/posthoc-memory-20261002/README.md) add five
finite clean large-array checks on the unchanged C3 endpoint, without changing
original acceptance, performance measurements or campaign counts.

The lead and independent empirical reviewer use `gpt-6.1-sol` with `high` reasoning;
execution workers use `gpt-6-luna` with `xhigh`. Three fresh contexts begin from the
original seed, with no previous optimization history. Research has no fixed time,
token, hypothesis or improvement quota. Technical process watchdogs and genuine
resource/integrity blockers remain explicit.

## Corrected execution and measurement

General shell, compilation, tests and profiling remain available through
`study_workspace_exec`, executed by the official CLI inside the actor's existing
workspace/network sandbox. One coordinator serializes resource-consuming work.
Bounded source/evidence reads and compact status remain available during timing.
Full factual records are selectively accessible; numeric token histories stay in
separate artifacts rather than being copied into every status response.

Each comparison retains immutable attempts. Independently attested recoverable
contamination or interruption can trigger a fresh comparison of the same source,
binary, reference and configuration. The first valid attempt is binding regardless
of its score. Valid unfavorable/under-target results and candidate correctness or
resource failures cannot justify a favorable retry. The same policy covers
reviewer comparisons, automatic original-seed checkpoints and final assessment.

The sandboxed command supervisor establishes observed descendant cleanup before
releasing its lease. Unknown cleanup quarantines resources instead of silently
continuing. This is a non-hostile research workflow, not a proof of security
against malicious same-UID code or an isolated physical host.

## Launch

Use `tools/start-study.sh --check` for a no-inference final-path check. The exact
launcher is `tools/start-study.sh`; it runs a real unscored multiagent preflight,
then waits without inference for reviewed readiness and a new freeze. Only then
can it start the three authorized campaigns and the first final assessment.
Read `owner/README.md` and `protocol/PROTOCOL.md` for the execution and selection
rules. No earlier readiness verdict is reused as proof of this implementation.

The current source freeze is
`a28a9e9984aa03a1a28c950bfd846e0d179202f719a43982a27c72a69c934178`.
It binds 68 source files and 151 runtime/setup artifacts. Fresh validation includes
20 real multiagent checks, 221 regression tests, native correctness/profile/memory
and failure controls, and seven native scheduler/recovery bridge checks. These
are setup observations, not optimization results. The terminal status is retained
in `state/launch/status.json`. The final report SHA-256 is
`4c0da852efa41ae3440c09a9faf2e6de0797ac1036ebbbdfc052b4f658f66227`.

Reported token counters are retained by role, including failures and retries.
Cache-write reporting, internal compaction usage and immutable provider model
versions remain limited by the native interface; observed API-equivalent cost
subtotals must not be represented as a complete bill.
