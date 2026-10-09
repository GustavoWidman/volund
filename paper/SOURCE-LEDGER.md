# Current v3 integration status

Current index, updated 2026-10-09. The manuscript reports completed v3 evidence. The [original staged ledger and correction history](https://github.com/GustavoWidman/volund/blob/4114e6cf6108d80920e0c46ad50c90c5ff6e8d37/docs/ai-development-workflow/SOURCE-LEDGER.md) remain in Git history. Historical pending-result wording describes the earlier source-only stage.

The current deliverables are `main.typ`, `extended-methods.typ`, the 19-entry `refs.bib`, and `volund.pdf` / `supplement.pdf`. No frozen experiment file or measured evidence was edited; no new optimization campaign, candidate change, model call, performance comparison, or canonical assessment was run for manuscript integration. Five separately authorized fixed-endpoint post-hoc Memcheck probes are outside the original campaign and assessment evidence; all passed with finite stated coverage. Earlier manuscript files were preserved outside the current source directory before replacement. Only v3 outcomes appear in the current paper.

Original-evidence independent review: `analysis/final-audit/INDEPENDENT-RESULTS-REVIEW.md` reports no material numerical or scientific-source blocker. Its reviewed source hashes are in `manuscript-review-identity.json`; the post-hoc memory addendum was separately checked against raw logs and protected hashes.

## Actual-result claim and source map

Paths in the scientific map below are relative to the original study root, preserved locally as `experiments/unattended-optimization-v3/`. Many campaign, assessment, launcher-status and QA records are **archive-only**, not files in this checkout. Consult [evidence availability](../audit/evidence-availability.json); no archive is currently published. The [root reproduction guide](../REPRODUCE.md) describes the complete checkout-only workflow.

The checkout contains all 156 raw-arithmetic inputs for 52 comparisons in `data/raw-arithmetic/`, the curated `data/plot-data.json`, 11 tables under `analysis/figures/measured-data-01/`, paper figure PDFs in `paper/figures/`, and selected reviews/setup records. The two `data/` paths and `paper/` are relative to the repository root. Scientific provenance audit requires the separate archive; arithmetic/plot reproduction does not establish missing provenance.

| Current claim | Evidence |
| --- | --- |
| Three completed campaigns, no runtime failure, automatic first final assessment | `campaigns/campaign-{1,2,3}/summary.json`; `state/launch/status.json`; `state/start-attempt/status.json` |
| Last promoted endpoints and reviewed closure | Each `campaigns/campaign-N/authority/state.json`, immutable anchors, promotion and closure records; final report `endpoints` |
| Transfer 2.239900/4.547377/5.444520 and shift 2.235983/5.185989/5.294481 with all six first attempts | `assessment/final/report.json` rows, source-bound `campaign-N/bench-{transfer,shift}` reports and retained pairs |
| Final validation: 22 operations passed; seed and each endpoint have 89/89 tests in each stratum and six shared public memory probes | Final report `operations`, individual correctness/Memcheck records; no final-size instrumented-memory claim |
| C1 sparse shift ratio 0.911355 and 9.7267% latency regression | Final report C1/shift `family_speedups`; latency change `(1/ratio-1)*100`, not `1-ratio` |
| Eight direct seed-relative promotions/checkpoints | Each authority state `promotions`/`trajectories`; source-bound direct comparisons; `analysis/figures/measured-data-01/trajectories.csv` |
| 13 hypotheses: 9 supported, 3 contradicted, 1 inconclusive; 22 review records and 3 separate closure endorsements | Authority state current hypothesis dispositions, review IDs, reviews, and closures. Fourteen claim reviews include C1 H3 twice; eight nomination reviews. No pending/rejected nominations |
| Actual model/effort routing, 21 threads and 68 completed turns | Campaign telemetry `agents`, `thread_start_metadata`, terminal statuses and `turn_counts` |
| C1 branch losses, sparse metadata, conditional builder, and repaired tag/sentinel width defect | Current hypothesis records, independent claim reviews, immutable candidate sources and the failed H5 canonical test; final source uses consistent `size_t` widths |
| C2/C3 shared-sort/summaries/radix trajectories and distinct cutoffs | Current hypotheses/reviews and immutable source snapshots. C2 cutoff 2048; C3 cutoff 32768. Public reduced profiles alone do not establish radix-path timing attribution |
| C3 remaining large-path memory instrumentation gap | Routed workspace command records and stdout/stderr; failed Memcheck/LeakSanitizer probes are retained, and a later ASan/UBSan pass with leak checks disabled does not establish leak or large-path Memcheck coverage |
| 357 official operations and 46 development first-attempt benchmarks | Campaign development operation records, reconciled against authoritative state; native command sums use unique `operations/**/command.json` and exclude separately reported oracle-case CPU |
| Native resource sums and peak coverage | Per-command elapsed/user/system/wait4 RSS fields. RSS includes spawned-command launch/interpreter lifecycle, not isolated engine heap. No remote-model or whole-host resource claim |
| Clock origins and closing work | Authority `started_unix`, seal times, telemetry host start/wall, last public usage observations. Bootstrap and closing intervals are not silently discarded |
| Observed tokens and narrow USD17.07544846–18.230435610 scenario | `analysis/checkpoints/campaign-{1,2,3}-usage-reanalysis.json`, reconciled to terminal telemetry; cached input/reasoning subsets counted once |
| Frozen broad USD17.07544846–34.83287297 scenario | Terminal telemetry `api_equivalent_cost`; separate from response-band post-freeze reanalysis |
| C1/C3 compaction, cache-write, request-ID, actual-tier and whole-cost gaps | Each reanalysis `coverage` and individual thread compaction markers; no finite whole-run upper bound |
| Workload dimensions and public diagnostic/final distinction | `setup/launch-native/public-fixtures/manifest.json`; `setup/final-fixtures-preparation/definitions.json`; final evaluator implementation and configuration |
| No operator optimization steering; ordinary observer activity on nonexclusive host | Study operator's explicit 2026-10-02 declaration relayed in the independent process audit. This does not assert absence of all external host activity |
| Five clean fixed-endpoint post-hoc C3 memory probes, excluded from original acceptance/performance/cost | `analysis/posthoc-memory-20261002/plan.json`, `results.json`, command/stdout/stderr records and `analysis/final-audit/POSTHOC-MEMORY-REVIEW.md`; unchanged C3 binary/final-assessment driver, finite large-array coverage only |
| Final single-column assets and numerical provenance | Original `analysis/figures/measured-assets-01/` is an absent historical derived output, not assumed to be in the lean archive. Four selected historical QA receipts are retained in `analysis/figures/qa-01/`. Committed PDF copies are `paper/figures/` (repository-relative); the 11 retained CSVs are `analysis/figures/measured-data-01/` |

Exact final report SHA-256: `4c0da852efa41ae3440c09a9faf2e6de0797ac1036ebbbdfc052b4f658f66227`.
Exact freeze SHA-256: `a28a9e9984aa03a1a28c950bfd846e0d179202f719a43982a27c72a69c934178`.

The main paper includes three 3.3-inch figures. Detailed timings, per-role counters, frozen/narrow cost scenarios, clock definitions, native resource coverage, supplemental execution limits and reproducibility bindings are in the supplement. The publication name is **Volund**; the repository path is lowercase `volund`. The paper promises public code/evidence upon publication, not present public access. This private repository cleanup does not establish publication or submission.

## Bibliography and review provenance

All 19 entries in `refs.bib` are cited by the main article. The [independent methods/citation review](INDEPENDENT-METHODS-CITATION-REVIEW.md) retains its original staged scope. The four later primary-source citations and metadata correction are recorded in the [historical revision notes](https://github.com/GustavoWidman/volund/blob/4114e6cf6108d80920e0c46ad50c90c5ff6e8d37/docs/ai-development-workflow/REVISION-NOTES-2026-10-08.md). The historical build receipt `FINAL-BUILD-VERIFICATION.json` records the old PDF names and old ledger hash; it is not a current-tree manifest. Current repository hashes are in `audit/repository-manifest.json` (repository-relative).

## Editorial tightening on 2026-10-09

The main article combines Discussion, Threats to Validity, and Conclusion into one section; availability and AI disclosure are unnumbered end matter. Methods summarize implementation details already retained in the unchanged supplement. Numerical results, tables, figure assets, and frozen scientific evidence are unchanged. The historical build receipt above predates this editorial revision.

The PIE bibliography author field follows the ten-author list on page 1 of the [published conference PDF](https://proceedings.iclr.cc/paper_files/paper/2024/file/ce65173b994cf7c925c71b482ee14a8d-Paper-Conference.pdf), also present in [arXiv v5](https://arxiv.org/abs/2302.07867v5). The conference landing-page metadata additionally lists Yiming Yang; that extra name was removed from the bibliography to match the paper itself.
