# Current v3 integration status

Updated 2026-10-02 UTC. The canonical manuscript now reports actual completed v3 evidence. The full staged claim/source ledger and correction history below are preserved verbatim as a historical audit, not as the current publication status. All statements below describing results as pending apply to the earlier source-only stage.

The current deliverables are `main.typ`, `extended-methods.typ`, the 15-entry `refs.bib`, and their compiled PDFs. No frozen experiment file or measured evidence was edited; no new optimization campaign, candidate change, model call, performance comparison, or canonical assessment was run for manuscript integration. Five separately authorized fixed-endpoint post-hoc Memcheck probes are outside the original campaign and assessment evidence; all passed with finite stated coverage. Earlier manuscript files were preserved outside the current source directory before replacement. Only v3 outcomes appear in the current paper.

Original-evidence independent review: `analysis/final-audit/INDEPENDENT-RESULTS-REVIEW.md` reports no material numerical or scientific-source blocker. Its reviewed source hashes are in `manuscript-review-identity.json`; the post-hoc memory addendum was separately checked against raw logs and protected hashes.

## Actual-result claim and source map

All paths in this section are relative to `experiments/unattended-optimization-v3`.

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
| Final single-column assets and numerical provenance | `analysis/figures/measured-assets-01`, `measured-data-01`, `qa-01/visual-qa.md`, and `qa-01/vector-font-metrics.json` |

Exact final report SHA-256: `4c0da852efa41ae3440c09a9faf2e6de0797ac1036ebbbdfc052b4f658f66227`.
Exact freeze SHA-256: `a28a9e9984aa03a1a28c950bfd846e0d179202f719a43982a27c72a69c934178`.

The main paper includes three 3.3-inch figures. Detailed timings, per-role counters, frozen/narrow cost scenarios, clock definitions, native resource coverage, supplemental execution limits and reproducibility bindings are in the supplement. Authorship approval, venue choice, declarations, public release, and submission remain pending.

---

# Preserved staged source-only ledger

# V3 manuscript claim and source ledger

Prepared 2026-10-01 UTC. This is a staged source-only manuscript, not a completed results paper. Canonical `docs/ai-development-workflow` files were read as a voice, bibliography, and format reference but were not edited. No measured v3 campaign outcomes, participant messages, held-out fixture contents, or canonical final-assessment results were inspected for this draft. No compilation, rendering, test execution, model launch, or campaign steering occurred.

## Files and integration status

- `main.typ`: condensed main paper, with introduction, related work, approximately 1,960 Method words, threats, and visibly pending results/discussion/conclusion
- `extended-methods.typ`: standalone supplementary source preserving detailed contract, compiler, estimator, selection, recovery, closure, telemetry, and provenance rules
- `refs.bib`: only the 15 references cited by the staged sources; metadata checked against primary sources, with the PIE byline corrected after independent review as described below
- `SOURCE-CHECK.json`: static content/reference checks and input/output hashes; this is not Typst compilation or visual QA

The main text keeps the existing English academic voice and the established IEEE Typst package. Author metadata is Gustavo Wagon Widman and Laiza Ribeiro Silva, Inteli, São Paulo, Brazil, provisionally awaiting author review. No venue, funding, ethics approval, publication status, public artifact URL, or author contribution statement was invented.

All figure hooks specify one column at 3.3 inches. The separate figure worker owns figure sources and final asset production. No preview, synthetic, or earlier-cohort graphic is imported. Canonical integration and rendering remain deferred until the parent releases the analysis lane and checks the final evidence.

## Freeze and provenance

Experiment root: `experiments/unattended-optimization-v3`.

- Whole freeze-record SHA-256: `a28a9e9984aa03a1a28c950bfd846e0d179202f719a43982a27c72a69c934178`
- Original seed SHA-256: `d32e6ec47c628378248720b38e3b6c1d63c9da867f72adb92bf836213e894414`
- Launch authorization identifies this freeze, preflight `47223bcf50f8525be9903daa87891a1cf7b28449dd77df6f9baedb868ecd92d3`, and readiness `0303c28d0a4c11c11531cac70d57245c17ee8920f687e6e0cb74ef238a2a3050`

The protocol's draft-status banner, draft-named configuration, and inherited historical task labels remain frozen bytes. Their text is not silently updated to report launch. The full freeze-file digest is distinct from hashes of internal inventories or individual execution artifacts. These details were moved out of the main paper at the parent's request.

Researcher exposure to preliminary work is disclosed once in the main design section. Earlier outcomes are excluded from current results, plots, and the campaign denominator. The draft does not compare versions or turn prior incomplete work into a v3 finding.

## Claim map

Paths in this table are relative to the experiment root. A protocol requirement is not by itself evidence that a measured participant followed it. Results integration must verify actual execution and retain deviations.

| Manuscript claim | Authoritative source and scope |
| --- | --- |
| Three serial fresh-seed campaigns; complete-workflow treatment; no matched comparator | `protocol/PROTOCOL.md` §§1–2; freeze configuration; `analysis/INDEPENDENT-LAUNCH-PROTOCOL-REVIEW.md`. Separate initialization is qualified, not called statistical independence |
| Exact portable range-statistics behavior and untuned indexed seed | `task/contract/SPEC.md`, `task/contract/engine.h`, `task/seed/engine.cpp`, `task/provenance.json`. Exact hash verified; baseline competitiveness is not claimed |
| Sol/high lead and reviewer; Luna/xhigh execution workers; fallback disabled | Protocol §4, `owner/prompts.py`, frozen runtime preflight bindings. Actual campaign routing still requires final evidence reconciliation |
| Flexible repeated investigations and falsifiable hypotheses | Protocol §§4–5; actual lead/worker/reviewer instructions in `owner/prompts.py`. A spawn/report is not treated as executed scientific work |
| Reviewer must independently rebuild/test/profile/Memcheck/benchmark, including material negative evidence | Protocol §4; reviewer instructions; nomination/claim review paths in `owner/service.py`. Six-family suite completion is distinguished from full size/branch coverage |
| Source-bound nomination, first valid official sample, semantic/memory disqualification, selected-build evidence | Protocol §6; `development/core.py` official-comparison report and selection; `owner/service.py` nomination review. Reruns do not erase an exact-source official defect |
| Ten development blocks, joint block bootstrap, 1.03 gate and 1/1.10 family floor | Protocol §§6,11; frozen `owner/config.draft.json`; `setup/launch-native/native-config.json`. Lower bound is one-sided, family observations are nested, and this is not a calibrated efficacy test |
| Shared shell/native lane, FIFO after admission, retained lease through cleanup | Protocol §8; `owner/measurement.py`; `runtime/workspace.py`; independent scheduler and launch reviews. Finite controls do not make the host dedicated |
| Bounded reads remain usable while native work holds its metadata lock | `runtime/workspace.py` read/list/search routes; `owner/service.py` cached compact views; independent launch-review native bridge evidence. No claim of measured context efficiency |
| Structured writes acquire the shared execution lane and target mutable scratch files separately from immutable snapshots | `runtime/workspace.py:304–312` uses `coordinator.async_lease` for the write route; `_write` validates paths. These are structured writes, not shell commands or unleased read operations |
| Two narrowly attested retry causes; immutable whole-comparison retries; first valid result regardless of score | Protocol §8; `owner/overlap.py`; `development/core.py`; independent scheduler/launch reviews. Generic session relaunch remains prohibited; unused retries field is not a timing-attempt quota |
| Mediated append-only factual history and compact status | Protocol §9; `owner/service.py::_change`, `_refresh_public_views`, `history`; `owner/public_api.py`. Corrections remain appended and full permitted records addressable |
| No research time/token quota; concrete queue and reviewed closure; incomplete status retained | Protocol §7; lead/reviewer instructions; `owner/service.py` closure transitions; launch review. No arbitrary iteration threshold is substituted |
| All endpoints sealed before final assessment; separate transfer/shift correctness and resource checks, shared public Memcheck; thirty blocks; no repair after outcomes | Protocol §10; `evaluation/run.py:227–254` runs both-stratum tests and one public-suite Memcheck per source; `development/native_backend.py:378–400` selects `profile_suite` for Memcheck. Canonical held-out data and current results were not opened. Unchanged seed endpoints are algebraic identity |
| Stopped endpoint is the last verified incumbent, with an unavailable endpoint permitted when none is verifiable | `owner/service.py:559–564` seals the incumbent or an empty source record. `evaluation/run.py:56–57,76–77,237–240` enforces retained-incumbent identity, permits absent source only for incomplete campaigns, and emits unavailable rows |
| Direct seed-relative development trajectories, completion-time axes, missing points and accounting coverage | Protocol §11; `analysis/figures/README.md`. Accepted visual style is 3.3-inch single-column assets with at least 8pt labels |
| Counter semantics, cache-write default, remote compaction gaps, hypothetical observed-token costs | Protocol §12; `runtime/ACCOUNTING.md`; `runtime/telemetry.py`; `analysis/reprice_observed_usage.py`; pinned primary runtime sources and official pricing. No actual bill or whole-run upper bound |

The source was checked against actual v3 protocol, prompts, scheduler/overlap, compact status/history, structured workspace, and accounting implementations. The initial pass used the pinned independent review for final-evaluator implementation detail. This correction pass also inspected the specific evaluator, native-backend, and workspace routing source spans identified by the independent manuscript review. No embargoed data was opened and no setup tests were repeated.

## Primary-reference verification

The cited research bibliography was previously audited in canonical `SOURCE-AUDIT.md`. This pass independently reopened the following primary records on 2026-10-01 and limited claims to their supported scope. No previous experimental results from the canonical manuscript were reused.

- PIE: [ICLR publisher PDF, page 1](https://proceedings.iclr.cc/paper_files/paper/2024/file/ce65173b994cf7c925c71b482ee14a8d-Paper-Conference.pdf) and [author-submitted arXiv v5](https://arxiv.org/abs/2302.07867v5), dated 26 April 2024, agree on ten authors. The [ICLR landing-page metadata](https://proceedings.iclr.cc/paper_files/paper/2024/hash/ce65173b994cf7c925c71b482ee14a8d-Abstract-Conference.html) additionally lists Yiming Yang; the bibliography follows the concordant paper bylines and omits that extra landing-page name. Title, ICLR 2024 venue, and the claims about C++ edits and measurement variability remain supported. The publisher PDF and v5 record were reopened during this correction pass
- AlphaEvolve: [arXiv v1](https://arxiv.org/abs/2506.13131v1), 18 authors, 2025 white-paper status, iterative evaluator feedback; no transferable gain claim
- POLO: [IJCAI publisher record](https://www.ijcai.org/proceedings/2025/814), six authors, 2025 proceedings, pages and DOI, profiling and collaborating-agent iteration
- PerfAgent: [arXiv v1](https://arxiv.org/abs/2607.19653v1), seven authors, 22 July 2026 preprint, profiler/verifier iterative refinement; no peer-reviewed status asserted
- SWE-Perf: [PMLR publisher record](https://proceedings.mlr.press/v306/he26y.html), nine authors, ICML 2026 volume 306/pages 41651–41666, real-repository optimization scope
- GSO: [NeurIPS publisher record](https://papers.nips.cc/paper_files/paper/2025/hash/ddd98389004161943e646322a16348c3-Abstract-Datasets_and_Benchmarks_Track.html), title/author/2025 track metadata and repository-optimization scope
- Compiler feedback: [arXiv v1](https://arxiv.org/abs/2403.14714v1), four authors, March 2024 preprint; used only to caution against assuming feedback is superior to sampling
- Kalibera and Jones: [Kent author repository](https://kar.kent.ac.uk/33611/) and [indexed corrected manuscript](https://kar.kent.ac.uk/id/document/3127886), 2013/DOI and repetition-level principles. Direct page opening failed once; the primary repository's indexed abstract and manuscript were retrieved. Its method is not claimed to validate this bootstrap or block count
- Mytkowicz et al.: [author-group publication record](https://sape.inf.usi.ch/publications/asplos09.html), 2009 ASPLOS metadata and sensitivity to incidental measurement conditions
- Cawley and Talbot: [JMLR publisher record](https://www.jmlr.org/papers/v11/cawley10a.html), 2010 volume/pages and selection-bias motivation. Application to adaptive program timings is explicitly an inference
- Callgrind: [official manual](https://valgrind.org/docs/manual/cl-manual.html), instruction/call diagnostics. Online manual identity is not evidence of the installed binary's version or options
- Cache-write provenance: [pinned response parser](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/codex-api/src/sse/responses.rs#L121), optional input-details default and cache-write field default verified
- Compaction: [pinned compaction source](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/core/src/compact_remote_v2.rs#L223); GitHub page retrieval failed, then the official [raw source](https://raw.githubusercontent.com/openai/codex/rust-v0.159.3/codex-rs/core/src/compact_remote_v2.rs) was inspected. It shows separately handled usage, compaction marker, history replacement, and context recomputation. Companion state/public-projection evidence is recorded in the runtime accounting source audit
- Pricing and formula: [official pricing](https://developers.openai.com/api/docs/pricing) and [prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching), retrieved 2026-10-01. Model-specific ordinary/cache-read/cache-write/output rate structure and replacement-charge treatment were verified. Actual tier and charges are not inferred

## Accepted independent review corrections

The source-only review in `INDEPENDENT-METHODS-CITATION-REVIEW.md` identified four corrections, all applied to the staged sources on 2026-10-01:

1. PIE now has the ten-author publisher-PDF/arXiv-v5 byline. The conflicting landing-page metadata is documented above
2. Main and supplement distinguish correctness/resource checks in both final strata from Memcheck on the shared six-family public diagnostic suite. The supplement explicitly excludes a claim of final-size or unexercised-branch instrumented-memory coverage
3. Main and supplement explicitly state that structured writes acquire the execution lane. Bounded read/list/search remain on their separate nonexecution route
4. Stopped endpoints retain the last verified incumbent, not an exploratory source. When no incumbent is verifiable, the truthful incomplete seal records an unavailable endpoint

These are descriptions of the unchanged frozen implementation. They add no test suite, endpoint selection rule, measured observation, or permission to resume/modify a campaign. Results placeholders, the three-campaign denominator, and the existing final integration gates remain intact.

## Required completion checks

1. Confirm all three current campaign identities, terminal states, immutable seals, source lineage, and final-assessment release eligibility before inserting empirical content
2. Reconcile actual delegated executions, hypothesis dispositions, reviewer reruns, selection rules, attempts, coverage, and interventions. Do not replace prescribed behavior with an assertion that it occurred
3. Populate transfer and shift separately, including every missing/invalid/identity cell and all three campaigns. Carry family and absolute-time evidence, with no earlier-cohort values
4. Reconcile requested/reported model settings, current host/toolchain/configuration, compile records, finite correctness/Memcheck coverage, and native resource evidence into the supplement
5. Choose and name the cost analysis actually used. Retain broad frozen bounds alongside any valid response-band reanalysis, plus cache-write, compaction, interruption, service-tier, setup, and whole-project gaps
6. Integrate only the figure worker's verified current assets. Compile and inspect the complete two-column manuscript and single-column figures after measurements end; source checks do not establish clean layout
7. Replace pending abstract/results/discussion/conclusion text with evidence-bound prose, obtain author review, and confirm any release, contribution, funding, or ethics statements before publication

No current scientific-result claim remains to be approved in this staged draft. The remaining scientific statements depend on evidence that has deliberately not been incorporated yet.


## Revision audit 2026-10-08

The current manuscript was revised from final commit `23cfd8448d819c8e9a245e9afef5869791abc484`. `REVISION-NOTES-2026-10-08.md` records the contribution-first framing, four verified orchestration/review citations, main-result tables, private availability and AI-use disclosures, cross-reference repair, and one prose rounding correction. Table I uses `analysis/figures/measured-data-01/heldout.csv`; Table II uses `analysis/final-audit/process-audit.json`. Frozen scientific evidence is unchanged. The older review and build records above retain their original historical scope.


### Publication-facing update after author naming decision

The study is now named lowercase `volund`, with main title “volund: An Empirical Study of Unattended Multiagent Program Optimization”. At the author’s explicit request, audience-facing status wording states that supporting code and evidence will be publicly available upon publication at https://github.com/GustavoWidman/volund. The repository URL was verified while private; no present public-access or completed-publication claim is made. Internal author/release checks are confined to separate notes, and author-review footer labels are removed. Scientific content and measurements remain unchanged.

The author’s final capitalization correction uses `Volund` in the publication titles and prose, while retaining lowercase `volund` in https://github.com/GustavoWidman/volund and other paths.
