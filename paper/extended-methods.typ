// Current v3 supplement, compiled only after campaign and assessment completion.
#set page(paper: "us-letter", margin: 0.75in, footer: context align(center, text(size: 8pt)[Supplement · #counter(page).display()]))
#set text(font: "TeX Gyre Termes", size: 10pt, lang: "en")
#set par(justify: false)
#show raw: set text(font: "TeX Gyre Cursor", size: 8.5pt)

#align(center, text(size: 16pt, weight: "bold")[Volund: Extended Methods and Reproducibility Details])
#v(8pt)

This supplement records the frozen v3 procedure, actual execution bindings, family-level results, process outcomes, and resource coverage. All three campaigns and their first automatic final assessment completed. The findings concern one synthetic task; workload families remain nested conditions. Repository paths below are relative to `experiments/unattended-optimization-v3` unless otherwise stated.

= Frozen materials and provenance

The full `state/freeze.json` file has SHA-256 `a28a9e9984aa03a1a28c950bfd846e0d179202f719a43982a27c72a69c934178`. This is the whole-record file digest, not a digest substituted from an internal inventory. `state/launch/authorization.json` names that freeze and the new preflight/readiness bindings. The companion `SOURCE-LEDGER.md` maps manuscript claims to the protocol, implementation, and supporting source review.

Some pinned files retain pre-freeze draft-status text. The copied original task also retains historical version labels, so that its declared source bytes remain traceable. Those documentary carryovers do not change the current v3 scheduling and recovery instructions. Launch state is established by the freeze and authorization records, not by rewriting historical text in frozen files.

The original seed SHA-256 is `d32e6ec47c628378248720b38e3b6c1d63c9da867f72adb92bf836213e894414`. Each campaign bootstrapped from that source. Optimized endpoints and earlier campaign histories are not initialization inputs. The public contract, ABI header, binary format, seed, role instructions, native driver, relevant tools, and evaluator bindings remain separately identifiable in the freeze.

= Exact task and compiler treatment

Events have unsigned 64-bit timestamps, a 32-bit stream identifier, and signed 32-bit values. Query stream `UINT32_MAX` selects all streams; input events cannot use that identifier. Queries use `lo <= timestamp < hi`, with `lo == hi` allowed. Sums fit signed 64-bit integers under the event-count limit. Successful calls return zero and preserve both input arrays byte for byte.

Invalid input returns one and preserves every provided output slot. It includes counts above 1,000,000 events or 4,096 queries; a null events pointer with positive event count; null queries/results with positive query count; an event using the reserved stream identifier; a reversed query interval; or a nonzero reserved query field. Excessive counts must be rejected before array access because backing storage is not promised for them. Zero-length arrays may have null pointers. Other non-null pointers within the limits denote valid nonoverlapping arrays. Allocation/runtime failure may return two, which remains an operational failure for an in-budget valid evaluation. No exception may cross the ABI.

Invocations must be reentrant and safe on disjoint outputs. Immutable constants and ordinary allocator reuse are allowed; input-dependent persistent state is prohibited even when keyed by input content. Candidate invocations cannot use network, subprocesses, filesystem access, environment inspection, clocks, randomness, output printing, or evaluator introspection. These restrictions apply to the optimized function; the evaluator performs its own I/O outside it.

The exact canonical compiler flags are:

```text
-std=c++20 -O3 -g -DNDEBUG -fPIC -shared -pthread
-march=x86-64 -mtune=generic
```

The fixed treatment permits the C++20 standard library, without inline assembly, architecture-target attributes/pragmas, target-specific intrinsics, external libraries, or dynamically generated implementation code. Debug builds and additional local diagnostics are exploratory evidence. Official builds and source hashes determine promotion and final assessment.

The archived deployment verification identifies g++ 14.2.0 (Debian 14.2.0-19), Valgrind/Callgrind 3.24.0, and Codex 0.159.3. Canonical command records bind the flags above, including the contract header through `-include`, to their exact source and binary. The fixed affinity is logical CPUs 0 and 1 on a shared host; this is not a dedicated-machine or hermetic-toolchain claim. Top-level tools and selected files are pinned, while compiler subprocesses, system-library closure, Valgrind internal dependencies, and interpreter dependencies are not fully pinned.

The native launch configuration fixes a 120-second compile wall/CPU ceiling and correctness wall/CPU ceilings of 180/150 seconds. Public oracle children have 10-second wall, 8-second CPU, and 768 MiB limits. Ordinary children have 30-second wall/CPU, 1 GiB address-space, and 512 MiB observed-RSS ceilings; diagnostic children have 200-second wall, 180-second CPU, 4 GiB address-space, and 2 GiB observed-RSS ceilings. Both use a 64 MiB output-file ceiling. These are operation safeguards, not research budgets. The exact final-stratum configurations are retained separately.


= Paired estimator and development selection

The native order seed is 2026100301. Realized family and arm schedules are archived; a seed alone is insufficient provenance. Development uses ten temporal blocks, with five reference-first and five candidate-first pairs per family. Final changed-endpoint comparisons use thirty blocks, with fifteen pairs in each order. The configured minimum sample target is 0.05 seconds, with a maximum of 65,536 repetitions. Each family calibrates both arms and uses the larger count for both. Calibration and warmup do not enter scored samples; completed under-target samples remain scored and flagged.

For each family, speedup is the exponential of the median paired log reference/candidate time ratio. The portfolio is the exponential of the equal-family mean of these medians. It is neither the ratio of marginal medians nor a deployment-weighted time-saving estimate. The family floor of `1/1.10` corresponds to no more than a 10% latency increase under this estimator.

The 10,000 bootstrap draws use seed 2026100302. A draw resamples complete temporal blocks and uses the same indices for every family, retaining their within-block dependence. The nominal one-sided 90% portfolio lower bound uses linear interpolation at zero-based sorted index `0.1 × (10000 − 1)`. It is not a symmetric interval. The frozen procedure produces a portfolio lower bound; raw paired-block variation must not be relabeled a family confidence interval. The development screens are operational thresholds and do not supply campaign-wide false-positive control.

An immutable review plan selects the first complete valid official comparison for its exact source/reference pair across actors, jobs, and builds. Re-nominating the same source against the same parent reuses its nomination; a new report, reviewer, or build does not reset the sample. A later build cannot substitute correctness or resource evidence for the selected comparison's actual build. Current-reviewer independent reruns remain additionally required. Actual repairs create linked sources; behaviorally equivalent cosmetic changes do not establish independent scientific attempts.

= Review coverage and scientific closure

New claims require appropriate direct reviewer checks, including negative or no-code claims. Already verified properties of an unchanged exact hash may cite their evidence IDs. Full configured Memcheck completion covers the six diagnostic families, not all sizes, branches, or concurrency behaviors. Reduced profiles and maximum-size correctness tests do not establish maximum-size Memcheck coverage. Candidate-specific thresholds and materially different allocation/control-flow paths determine relevant supplemental probes. Their motivation, actual coverage, result, and remaining concern are archived. Making an added probe a mandatory campaign-wide gate requires an explicit evaluation-rule change.

The closure dossier names the current verified source, every hypothesis and disposition, factual reports and review outcomes, unresolved uncertainty and its consequence, failed/unfinished branch dispositions, and the complete actionable queue. An inconclusive item explains why further available work is not expected to discriminate the claim or change a decision. A review request for more work must identify the concrete investigation, evidence, observable outcome, and decision relevance. Closure establishes the workflow's stopping judgment, not exhaustive search.

Cooperative branch abandonment requests factual wrap-up and normal turn completion. A request acknowledgement does not establish termination. Emergency interruption, lost model sessions, or incomplete cleanup retain their technical status and any accounting gaps. Process watchdogs cannot silently become scientific stopping quotas.

= Execution lane and immutable recovery

The shared execution lane covers routed arbitrary shell, native compilation, tests, profiles, memory diagnostics, development benchmarks, automatic trajectories, and final native work. Its FIFO guarantee begins at coordinator admission; metadata locks may affect arrival. A retry releases its previous lease and rejoins the queue. Recorded queue, execution, cleanup, and release identities distinguish waiting from native work.

Bounded structured read/list/search functions do not execute shell and remain usable while native work holds its metadata lock. They reject path escape, symlinks, and nonregular files and expose continuation. A page with no matches is not necessarily an exhaustive negative search. Structured writes also acquire the execution lane and are restricted to mutable granted scratch files; immutable measurement artifacts are separate. These routes do not make the entire host exclusive to the experiment.

Recoverable timing invalidity has exactly two categories: an observed competing study-command overlap or an owner-observed external preemption/interruption with an identified observer and event. Participant assertions, generic exceptions, a score, or uncertain cleanup cannot authorize a retry. Every attempt retains source/binary/fixture identities, calibration and procedure, raw output, resource status, cleanup evidence, and its series link. The invalid attempt contributes no scored samples to its replacement.

The retained configuration value `infrastructure_automatic_retries: 0` concerns generic infrastructure/session relaunches; it is not a counter limiting the separately implemented eligible timing-attempt series. Valid poor scores and candidate failures do not enter that recovery series. Unknown failures remain blockers. If an attested condition persists, the request remains waiting or blocked with its history and continuous clock, unless explicitly canceled.

= Final endpoint and trajectory record

All three canonical seals are required before final candidate assessment or release. A normal seal identifies the last promoted source, or the unchanged seed; a stopped-state seal preserves the last verified incumbent with truthful noncompletion, or records an unavailable endpoint when no incumbent is verifiable. All three truthful seals remain required. Before timing, the evaluator checks correctness and resource compliance in both final strata and reruns Memcheck on the shared six-family public diagnostic suite. Every required check must pass. Final Memcheck uses the public profile-suite fixtures, not the transfer or shifted performance inputs. Its completion does not establish instrumented-memory coverage at final workload sizes or on unexercised branches. A failed endpoint is not replaced with earlier code. Same-source seed endpoints use explicit algebraic identity rather than a fabricated measured gain.

The final cohort and assessment identity persist across output paths and evaluator invocations. No completed valid comparison is repeated for a better score. An unrecoverable interruption retains a terminal report and missing values; a later amended execution must be labeled separately. Transfer and shift remain two six-family portfolios, not one twelve-family score.

Development checkpoints record exact seed/checkpoint hashes, promotion/review IDs, paired samples, workload/build identities, comparison start/end, promotion time, elapsed time, and accounting coverage. A seed-parent promotion can reuse its selected independent seed comparison; later checkpoints need a direct seed comparison. A trajectory measurement is observational and cannot retroactively become an extra promotion gate. Integrity or correctness defects still follow their own declared failure policy.

Figures use one-column vector assets with at least 8pt labels. Only observed checkpoints and explicit unmeasured seed identity are plotted. Completion-time axes include the work used to establish a point. Per-point lower bounds do not form a simultaneous band over selected development history. Figure sources, data bindings, and rendering QA are retained with the analysis artifacts.

= Public usage and API-equivalent scenarios

The pinned public notification stream contains thread/turn identities, cumulative and last counters, and optional model-context-window information. A positive cumulative increment matching the last-usage object supports a response-shaped observation, but the public stream does not attest a provider response ID. Model maximum context capacity does not determine an individual request's price band. Local context recomputation without a cumulative increment is bookkeeping; total-only context-capacity sentinels or unexplained regressions retain a gap rather than fabricated replacement usage.

#block(breakable: false)[
For input $I$, cache reads $R$, cache writes $C$, and output $O$, with rates per million tokens, the scenario cost is

$ ((I-R-C)p_I + R p_R + C p_C + O p_O) / 1000000. $
]

Cache reads are already included in input, and reasoning is already included in output. Cache-write charges replace ordinary-input charges. Where write provenance is unverified, feasible $C$ ranges from zero through $I-R$, even if the protocol reports zero. The pinned parser and remote-compaction implementation motivate those coverage qualifications @openai2026codexusagefields @openai2026codexcompaction. Dated official pricing and cache rules define hypothetical Standard scenarios @openai2026pricing @openai2026promptcaching.

Frozen broad bounds remain separate from any post-freeze numeric response-band reanalysis. A narrower band needs the pinned append semantics, consistent nonnegative increments, matching final totals, and an explicit account of unresolved response mixtures. It does not recover missing request IDs or actual billing tiers. Neither broad nor narrower observed-token intervals bound unreported work. Compaction, interrupted tails, unregistered activity, setup, interpretation, and other missing coverage must retain their scope and reason.

Notification coordinates are receipt times. Checkpoint usage requires its authority-bound snapshot and coverage; later receipts cannot be interpolated into exact consumption at a benchmark endpoint. Source sealing and runtime cleanup/closing-turn completion are separate times. Role resource sums can exceed elapsed campaign time when model work overlaps. Available native resources, setup, final assessment, and interpretation remain separately identified.


= Observed execution and provenance

The three campaign summaries report `complete`, `task_complete`, and no runtime failure. Each authority state contains an endorsed closure, a last promoted endpoint, and no remaining pending nomination. The launch status reports automatic assessment completion; the supervisor exited with status zero. All twenty-two final operation records passed. Final timing consisted of six complete first attempts without prior-attempt records. These are execution observations; the procedure descriptions above are not substituted for evidence that an operation occurred.

The exact final report SHA-256 is `4c0da852efa41ae3440c09a9faf2e6de0797ac1036ebbbdfc052b4f658f66227`. The frozen final-evaluator manifest digest is `dd22eacda30b2af678f4c1fb4dd345f67623438dc2a6292a2bd07ebebd6736cb`. The snapshot identity for the unchanged seed is `affa5519e8824d3a22eb1f31a6187b8fc3fcb4bc0dba72fa10ddd07145d7935b`; this hashes a source inventory and is distinct from the original `engine.cpp` file digest given above.

*C1 endpoint.* Snapshot `ed93394218ee71c59c9525cc9ed3e4d0fc2280ddbabf8f54c4aca22e3d0c8b22`. Its `engine.cpp` SHA-256 is `e2dab7480f19922b2f155b2e6e1312452d9f0ef1710ccd30aa67ccde6588c6a3`. The sealed development build is `9e3b10952436435d8bb5795d0fdfe789`. Final assessment rebuilt the same source independently.

*C2 endpoint.* Snapshot `34a784991a3f9dd341ea06191a715f5f45678ae7ca3d0f994360d21818fc877d`. Its `engine.cpp` SHA-256 is `009dc4f845ae6ebb2a7fbc04f0d6c8e21b3e796ce2dfd4b90b801b58e1b0cf30`. The sealed development build is `c96c834b490b4dfc86b32d2d266b2696`. Final assessment rebuilt the same source independently.

*C3 endpoint.* Snapshot `7d87f5bb7d2232ea7375b621a85cc76fc750f997ab92239c4be9d7c9e129c45a`. Its `engine.cpp` SHA-256 is `dcded107345997e1c46219a8e01e2648d76ccb8ed43ec18e8088c1ef3590cf94`. The sealed development build is `c885bfb8c2ac40bdaa1c9de7d474190e`. Final assessment rebuilt the same source independently.

All checked frozen relative files retain their original bytes. Historical prefixes in fixture identifiers describe retained bytes, not another results cohort. Every empirical table here uses only the current three campaigns and this final report.

== Workload dimensions

#block(breakable: true)[
#set text(size: 9pt)
#table(columns: (1.15fr, 1.35fr, 0.8fr, 0.7fr, 0.8fr, 1fr), inset: (x: 5pt, y: 4pt), stroke: 0.25pt + rgb("cccccc"), align: left,
 table.header([*Suite*], [*Family*], [*Events*], [*Queries*], [*Streams*], [*Timestamps*]),
[Development], [Small], [1,000], [16], [64], [uniform],
[Development], [Sparse], [160,000], [1,800], [4,096], [uniform],
[Development], [Dense], [220,000], [500], [16], [clustered],
[Development], [Global mix], [125,000], [1,400], [128], [uniform],
[Development], [Skewed], [250,000], [1,000], [512], [clustered],
[Development], [High cardinality], [180,000], [1,800], [180,000], [uniform],
[Transfer], [Small], [1,000], [16], [64], [uniform],
[Transfer], [Sparse], [160,000], [1,800], [4,096], [uniform],
[Transfer], [Dense], [220,000], [500], [16], [clustered],
[Transfer], [Global mix], [125,000], [1,400], [128], [uniform],
[Transfer], [Skewed], [250,000], [1,000], [512], [clustered],
[Transfer], [High cardinality], [180,000], [1,800], [180,000], [uniform],
[Shift], [Small], [2,400], [48], [61], [clustered],
[Shift], [Sparse], [280,000], [2,200], [512], [clustered],
[Shift], [Dense], [350,000], [720], [24], [clustered],
[Shift], [Global mix], [200,000], [1,800], [128], [uniform],
[Shift], [Skewed], [380,000], [1,400], [1,024], [clustered],
[Shift], [High cardinality], [320,000], [2,400], [90,000], [uniform],
[Diagnostics], [Small], [1,000], [16], [64], [uniform],
[Diagnostics], [Sparse], [12,000], [256], [4,096], [uniform],
[Diagnostics], [Dense], [16,000], [64], [16], [clustered],
[Diagnostics], [Global mix], [12,000], [192], [128], [uniform],
[Diagnostics], [Skewed], [16,000], [128], [512], [clustered],
[Diagnostics], [High cardinality], [12,000], [256], [180,000], [uniform],
)
]

Transfer retains the development family definitions with new input seeds. Shift changes the declared sizes and distribution parameters; complete width, wildcard, empty, absent-stream, hot-stream, seed, and fixture-digest fields are archived in `setup/final-fixtures-preparation/definitions.json` and its preparation manifest. The diagnostics suite is shared public evidence, with smaller inputs in most families. Cardinality is a generator parameter, not a guarantee that every possible stream appears. The input files and expectations remain frozen.

== Final portfolio estimates

#block(breakable: true)[
#set text(size: 9pt)
#table(columns: (1fr, 1fr, 1fr, 1fr, 1fr, 1fr), inset: (x: 5pt, y: 4pt), stroke: 0.25pt + rgb("cccccc"), align: left,
 table.header([*Campaign*], [*Stratum*], [*Speedup*], [*Lower bound*], [*Blocks*], [*Attempt*]),
[C1], [Transfer], [2.239900], [2.221658], [30], [1],
[C1], [Shift], [2.235983], [2.214096], [30], [1],
[C2], [Transfer], [4.547377], [4.506898], [30], [1],
[C2], [Shift], [5.185989], [5.113856], [30], [1],
[C3], [Transfer], [5.444520], [5.389702], [30], [1],
[C3], [Shift], [5.294481], [5.235481], [30], [1],
)
]

All estimates are measured comparisons. The lower bound is the nominal one-sided 90% complete-block bootstrap bound. There are no algebraic-identity endpoints, missing comparisons, or replacements in this final cohort. Each changed source and the seed passed 89 correctness cases in both strata and six public Memcheck probes. Final Memcheck does not use shifted or transfer timing fixtures.

== Family effects and absolute times

The following entries give medians of each arm’s per-invocation native elapsed time in milliseconds, calculated across the thirty scored blocks, alongside the frozen median-log paired ratio. The ratio need not equal the ratio of the displayed marginal medians. Warmup, calibration, and process-launch time are outside these scored invocation times. Full pairs, schedules, repetitions, under-target flags, and command records remain in the final comparison artifacts.

=== Transfer

#block(breakable: true)[
#set text(size: 9pt)
#table(columns: (0.8fr, 1.65fr, 1fr, 1.1fr, 1fr), inset: (x: 5pt, y: 4pt), stroke: 0.25pt + rgb("cccccc"), align: left,
 table.header([*Campaign*], [*Family*], [*Seed ms*], [*Endpoint ms*], [*Speedup*]),
[C1], [Dense], [18.7210], [12.1203], [1.518090],
[C1], [Global mix], [38.0204], [8.7088], [4.369835],
[C1], [High cardinality], [39.5010], [13.2920], [2.935276],
[C1], [Skewed], [55.5051], [16.6802], [3.300069],
[C1], [Small], [0.0307], [0.0167], [1.840772],
[C1], [Sparse], [12.8904], [12.0599], [1.067670],
[C2], [Dense], [18.4395], [4.6802], [3.953253],
[C2], [Global mix], [38.2029], [3.9001], [9.885183],
[C2], [High cardinality], [40.9322], [5.5491], [7.160338],
[C2], [Skewed], [55.8623], [8.1561], [6.820896],
[C2], [Small], [0.0315], [0.0167], [1.871396],
[C2], [Sparse], [12.9715], [5.1258], [2.475629],
[C3], [Dense], [17.7293], [3.1719], [5.656329],
[C3], [Global mix], [37.7417], [2.5835], [14.607005],
[C3], [High cardinality], [38.2064], [5.0985], [7.354160],
[C3], [Skewed], [55.4595], [6.9481], [8.101123],
[C3], [Small], [0.0306], [0.0165], [1.866911],
[C3], [Sparse], [12.8681], [4.4090], [2.834393],
)
]

=== Shift

#block(breakable: true)[
#set text(size: 9pt)
#table(columns: (0.8fr, 1.65fr, 1fr, 1.1fr, 1fr), inset: (x: 5pt, y: 4pt), stroke: 0.25pt + rgb("cccccc"), align: left,
 table.header([*Campaign*], [*Family*], [*Seed ms*], [*Endpoint ms*], [*Speedup*]),
[C1], [Dense], [34.5285], [20.5172], [1.673065],
[C1], [Global mix], [78.7188], [15.0536], [5.271101],
[C1], [High cardinality], [66.3613], [25.5539], [2.579078],
[C1], [Skewed], [116.6998], [30.7574], [3.740786],
[C1], [Small], [0.0640], [0.0397], [1.611691],
[C1], [Sparse], [19.5131], [21.7337], [0.911355],
[C2], [Dense], [32.7549], [7.6077], [4.329881],
[C2], [Global mix], [75.8101], [6.3634], [11.906948],
[C2], [High cardinality], [65.4344], [9.9654], [6.503250],
[C2], [Skewed], [112.2722], [9.3228], [12.181787],
[C2], [Small], [0.0611], [0.0345], [1.783435],
[C2], [Sparse], [18.5936], [7.0270], [2.670632],
[C3], [Dense], [32.5456], [5.1876], [6.311769],
[C3], [Global mix], [75.7533], [5.4379], [13.788461],
[C3], [High cardinality], [64.2743], [10.4418], [5.998326],
[C3], [Skewed], [111.0401], [12.0839], [9.357700],
[C3], [Small], [0.0608], [0.0478], [1.277585],
[C3], [Sparse], [18.8807], [5.3775], [3.529269],
)
]

C1 shifted sparse has speedup 0.911355 and latency change `(1 / 0.911355 − 1) × 100 = 9.7267%`. The final assessment has no promotion gate. This regression remains a result even though the portfolio improves. Family ratios describe six conditions within the same task and do not provide six independent replications.

== Process counts and source trajectories

Main-article Table II presents the campaign process counts: twenty-one role threads, sixty-eight completed turns, thirteen closed hypotheses, twenty-two claim/nomination review records, and eight promotions across C1–C3.

S, C, and I mean supported, contradicted, and inconclusive. A thread can span several turns. Review counts are claim and nomination records (fourteen plus eight overall), excluding three separate closure endorsements. C1 H3 has two claim reviews. Counts do not represent independently sampled reviewers or optimization trials. C1 and C2 each used two reviewer threads; C3 used one. All eight nominations were promoted. Exploratory branches were rejected or abandoned before nomination, so no rejected-nomination count is inferred from negative hypotheses.

#block(breakable: true)[
#set text(size: 9pt)
#table(columns: (1fr, 1fr, 1fr, 1fr, 1fr, 1fr), inset: (x: 5pt, y: 4pt), stroke: 0.25pt + rgb("cccccc"), align: left,
 table.header([*Campaign*], [*Point*], [*Measured min*], [*Promoted min*], [*Speedup*], [*Lower bound*]),
[C1], [0], [0.000], [0.000], [1.000000], [Identity],
[C1], [1], [28.264], [28.264], [1.706202], [1.676788],
[C1], [2], [73.979], [73.349], [2.291221], [2.241056],
[C2], [0], [0.000], [0.000], [1.000000], [Identity],
[C2], [1], [22.631], [22.631], [1.284195], [1.253739],
[C2], [2], [46.387], [45.768], [2.152699], [2.138509],
[C2], [3], [70.083], [69.253], [4.550809], [4.478193],
[C3], [0], [0.000], [0.000], [1.000000], [Identity],
[C3], [1], [17.614], [17.614], [1.277474], [1.267541],
[C3], [2], [39.598], [38.935], [2.233783], [2.187677],
[C3], [3], [78.397], [77.290], [5.596247], [5.525487],
)
]

Times use owner initialization as the origin. “Measured min” is comparison completion, including the work needed to establish that point; promotion time is reported separately. Point zero is unmeasured source identity. All later points directly compare the exact checkpoint with the original seed. Public checkpoint usage snapshots do not establish complete usage at those benchmark endpoints, so no exact checkpoint token or dollar coordinate is assigned.

= Observed resource coverage

== Clock boundaries

#block(breakable: true)[
#set text(size: 9pt)
#table(columns: (0.8fr, 1fr, 1.1fr, 1fr, 1.15fr, 1.05fr), inset: (x: 5pt, y: 4pt), stroke: 0.25pt + rgb("cccccc"), align: left,
 table.header([*Campaign*], [*Bootstrap s*], [*Owner to seal min*], [*Host wall min*], [*Owner to usage min*], [*Post-seal usage s*]),
[C1], [8.008], [80.566], [84.799], [84.931], [261.861],
[C2], [8.219], [73.704], [74.249], [74.384], [40.764],
[C3], [8.094], [84.654], [86.755], [86.887], [134.008],
)
]

Bootstrap is the offset from owner initialization to the runtime host’s start. Host wall is the archived host interval through its closing/cleanup accounting; owner-to-usage ends at the last public usage notification receipt. Source sealing fixes the endpoint while later turns and receipts can still consume resources. Receipt time is not provider execution time. These intervals overlap and must not be added as independent resource costs. Final assessment ran for 14.468 minutes, starting after all campaign seals and host summaries. The broader launch interval includes live preflight and preparation/verification work and is not a measured-campaign duration.

== Tokens and scenario costs

#block(breakable: true)[
#set text(size: 9pt)
#table(columns: (0.7fr, 1.1fr, 1.1fr, 0.9fr, 0.9fr, 1.6fr), inset: (x: 5pt, y: 4pt), stroke: 0.25pt + rgb("cccccc"), align: left,
 table.header([*Campaign*], [*Input*], [*Cache reads*], [*Output*], [*Reasoning*], [*USD scenario*]),
[C1], [39,707,486], [37,997,184], [283,459], [166,465], [5.491245–5.904279],
[C2], [44,684,641], [43,397,632], [256,663], [143,600], [5.654548–5.986751],
[C3], [43,673,816], [42,166,400], [280,136], [157,384], [5.929655–6.339405],
)
]

The combined input, cache-read, output, reasoning, and total counters are 128,065,943; 123,561,216; 820,258; 467,449; and 128,886,201. Cache reads are part of input, and reasoning is part of output. The exact sum of the three response-band scenario intervals is USD 17.07544846–18.230435610. No additional charge is assigned to already-included subsets.

The response-band reanalysis is a post-freeze interpretation of observed public counters, not a change to measurements or the frozen accounting. It reconciles 443, 477, and 452 positive cumulative increments with endpoint totals and the pinned append semantics. All were assigned to the short-input band, whose official threshold was at most 272,000 input tokens per response-shaped observation. The four no-increment context recomputations in C1/C3 and duplicate snapshots are not additional usage. No provider request IDs are exposed, so response-shaped increments are not claimed to be provider-attested request records.

#block(breakable: true)[
#set text(size: 9pt)
#table(columns: (0.8fr, 1.7fr, 1.7fr), inset: (x: 5pt, y: 4pt), stroke: 0.25pt + rgb("cccccc"), align: left,
 table.header([*Campaign*], [*Frozen broad USD scenario*], [*Compaction contexts*]),
[C1], [5.49124498–11.20908531], [Implementation + reviewer],
[C2], [5.65454828–11.51593666], [None observed],
[C3], [5.92965520–12.10785100], [Implementation + reviewer],
)
]

The frozen broad observed-token interval sums to USD 17.07544846–34.83287297. It preserves an unknown short/long mix. The narrower reanalysis changes that mix assumption using observed increments but leaves cache-write provenance unknown. For each model and band, cache-write tokens range from zero through input minus cache reads. C1 and C3 each had an implementation and reviewer context with a remote-compaction marker, whose separately handled usage is not recovered. Absence of a C2 marker does not establish complete provider billing. Actual bill, service tier, provider IDs, and a finite whole-run upper bound remain unavailable.

Dated Standard rates per million tokens are: Sol short ordinary input/cache read/cache write/output = USD 2.00/0.10/2.50/10.00 and long = 4.00/0.20/5.00/15.00; Luna short = 0.10/0.01/0.125/0.50 and long = 0.20/0.02/0.25/0.75. The source snapshot is 2026-10-01. These hypothetical rates are used only to transform the observed counters under stated assumptions.

== Role-level observed tokens

#block(breakable: true)[
#set text(size: 9pt)
#table(columns: (0.7fr, 1.35fr, 1fr, 1fr, 0.85fr, 1fr), inset: (x: 5pt, y: 4pt), stroke: 0.25pt + rgb("cccccc"), align: left,
 table.header([*Campaign*], [*Role*], [*Input*], [*Cache reads*], [*Output*], [*Total*]),
[C1], [Lead], [14,741,429], [14,449,664], [67,490], [14,808,919],
[C1], [Measurement], [777,946], [644,608], [10,197], [788,143],
[C1], [Investigation], [1,015,358], [833,024], [34,589], [1,049,947],
[C1], [Implementation], [12,021,436], [11,406,336], [127,387], [12,148,823],
[C1], [Reviewer], [11,151,317], [10,663,552], [43,796], [11,195,113],
[C2], [Lead], [18,735,347], [18,488,832], [43,597], [18,778,944],
[C2], [Measurement], [718,823], [629,248], [20,603], [739,426],
[C2], [Investigation], [1,951,849], [1,685,504], [56,293], [2,008,142],
[C2], [Implementation], [8,308,668], [8,009,216], [96,946], [8,405,614],
[C2], [Reviewer], [14,969,954], [14,584,832], [39,224], [15,009,178],
[C3], [Lead], [16,500,869], [16,201,728], [61,043], [16,561,912],
[C3], [Measurement], [405,352], [348,672], [10,470], [415,822],
[C3], [Investigation], [1,520,256], [1,390,848], [20,932], [1,541,188],
[C3], [Implementation], [10,664,114], [10,126,080], [143,276], [10,807,390],
[C3], [Reviewer], [14,583,225], [14,099,072], [44,415], [14,627,640],
)
]

Roles have different models and workloads. These descriptive totals do not show that one role is more efficient, nor can they be substituted for a randomized role ablation. The sum counts unique thread endpoints once; snapshots and role aggregates are not charged again.

== Local command records

Unique command records under each campaign’s official development operations contain 2,395, 2,425, and 2,137 spawned commands, respectively. Their summed recorded elapsed times are 698.297, 707.217, and 691.267 seconds; summed user-plus-system CPU is 488.645, 478.118, and 470.520 seconds. Each has a distinct recorded process ID within its campaign, and oracle subprocess work is already included in the enclosing correctness command’s child-resource accounting. Oracle case-level CPU is not added again. The maximum recorded `wait4` peak RSS is 136,488 KiB in each campaign; it includes the spawned command’s launch/interpreter lifecycle and is not isolated endpoint heap demand. Peaks are not additive. These command sums exclude model-service resources, routed participant workspace commands, setup, final assessment, and any unobserved processes. They are not total host utilization or campaign elapsed time.

At the official operation level there were 117, 125, and 115 records in C1–C3: 38 builds, 40 tests, 36 memory operations, 197 profile operations, and 46 benchmarks overall. One canonical test operation failed, on C1’s original H5 implementation; its repaired source is distinct. All 46 development benchmark operations used attempt one. Each final comparison also used attempt one. The 22 final operations comprised four builds, eight correctness tests, four memory operations, and six benchmarks.

== Supplemental execution and coverage limits

The bounded request audit identified 941 routed workspace requests, including fifty arbitrary executions, with twelve request errors and nine command records marked failed. Routine address/path errors and exploratory command failures remain distinct from a campaign runtime failure. A C1 `diff` exit status one reported source differences; a C2 supplemental test harness had a syntax error that was repaired. C3 supplemental work encountered wrong include paths, unavailable timing tooling, Memcheck startup/instrumentation errors, and a LeakSanitizer ptrace incompatibility. A static Memcheck execution completed twenty-six oracle cases but reported two pre-main libc diagnostics with zero allocations tracked; it is not clean memory evidence. The subsequent address/undefined-behavior sanitizer run with leak checks disabled passed its exercised cases. At campaign closure, neither this run nor the configured public Memcheck suite supplied clean large-array Memcheck or leak coverage for C3’s radix path.

The source/request audit did not find literal requests for other-campaign, held-out, earlier-cohort, or private-runtime paths in these routed records. This is a bounded observable-path check, not a proof of adversarial isolation or absence of every information channel. Requested models and reasoning settings match all twenty-one archived thread-start records, with no visible model substitution. Immutable provider model versions remain unavailable.

C2 and C3 used different radix thresholds: 2,048 and 32,768 events. C2 sorts the retained union once. C3 reuses a global timestamp order when wildcard demand requires one and otherwise sorts each demanded stream. These source differences are retained even where the broad mechanism labels coincide.

The study operator reports no optimization steering, participant/lead/reviewer messages, measured-protocol edits, candidate or journal repair, model or criteria changes, campaign restarts, or additional native benchmark/profile/test work during the cohort. Ordinary observer/source-preparation activity continued on the nonexclusive host: bounded reads, JSON arithmetic, manuscript/analysis writes, repository operations including a branch push pinned to logical CPU 2, and three figure metadata checks of 0.006–0.021 seconds. Rendering, broader tests, and archive scans began after final assessment. This statement distinguishes absence of optimization intervention from absence of all external host activity; unrelated system contention remains possible.

== Separately authorized post-hoc memory diagnostics

After final assessment, five fixed-endpoint Memcheck probes on 2026-10-02 supplemented C3's original instrumentation gap. They reused the exact unchanged final C3 library, final-assessment driver, and canonical flags with the existing extra-debug-information path. Three used retained large public fixtures; two used byte-exact stream-only/global-only query and expected-result projections of the public skewed fixture. No candidate source, threshold, performance comparison, or canonical assessment was changed.

#block(breakable: true)[
#set text(size: 9pt)
#table(columns: (1.8fr, 1.2fr, 1fr, 1fr), inset: (x: 5pt, y: 4pt), stroke: 0.25pt + rgb("cccccc"),
 table.header([*Probe*], [*Large radix input*], [*Allocations / frees*], [*Verified calls*]),
 [Global mix], [125,000 events], [1,666 / 1,666], [1],
 [Skewed], [250,000 events], [946 / 946], [1],
 [High cardinality], [180,000 events], [3,245 / 3,245], [1],
 [Skewed stream-only], [237,591-event bucket], [944 / 944], [1],
 [Skewed global-only], [250,000 events], [66 / 66], [1],
)
]

Each probe returned the oracle-verified result, tracked positive allocations, freed every block, and reported zero live heap bytes, errors, and suppressions. Source and input analysis establishes execution above the 32,768-event cutoff with three active low timestamp bytes, including odd-pass copy-back. The stream-only projection exercises one large bucket plus small buckets, not workspace reuse across multiple large buckets. Full-width timestamps, equal-timestamp cases, exact-cutoff boundaries, allocation failures, and all-input memory safety are not established by these five calls.

The retained plan, commands, stdout/stderr, inputs/projections, and `results.json` are under `analysis/posthoc-memory-20261002`. Independent review checked all five probes and 477 protected hashes. This supplementation is excluded from original acceptance, performance, campaign usage/cost totals, and the twenty-two-operation canonical final assessment. The earlier unsuccessful supplemental attempts remain part of the historical record.

== Setup and unmeasured project work

Live preflight is setup work and is not one of the three optimization campaigns. Its separate observed-token reanalysis and runtime summary are retained in `analysis/preflight-observed-usage-reanalysis.json` and `setup/live-preflight/telemetry.json`. Preflight exercises delegation, actual baseline work, compile failure and repair, reviewer execution, factual-history recovery, usage collection, structured reads, the routed execution lane, cleanup, and closure. The launch preflight lists twenty passing checks; they are not optimization outcomes.

Harness design, earlier engineering exploration, native readiness controls, installation, orchestration outside campaign role telemetry, manuscript preparation, and interpretation are not completely metered by campaign counters. Available setup evidence is retained separately. Native CPU, wall, and memory records cover local commands only and exclude the remote model service. Consequently neither the campaign token subtotal nor available local command records constitute total project resource accounting.

= Reproduction

The artifact sources include the immutable protocol and controller, exact source snapshots and builds, paired measurements, family schedules, raw command records, authoritative hypotheses/reviews/closures, public runtime telemetry, post-freeze counter reanalysis, and reproducible figure data. `SOURCE-LEDGER.md` preserves the full claim/source map and its correction history. The independent methods/citation review remains alongside it. Exact absolute paths in evidence reflect the original workspace and may require the documented allowlisted relocation for offline analysis; they must not be rewritten in the frozen files.

Offline analysis can verify report/configuration hashes and recompute the estimates from retained pairs without model calls. Native remeasurement, if undertaken elsewhere, is a new replication under its recorded host conditions and must not replace the first final report. No new optimization campaign, candidate change, performance comparison, or canonical assessment was run during manuscript integration. The five fixed-endpoint memory probes above are separately labeled post-hoc. The manuscript revision of 2026-10-08 changes presentation, related work, and disclosures only; the frozen experiment and measured evidence are unchanged. The editable sources use Typst 0.15.1 with the pinned `charged-ieee:0.1.4` package and bundled fonts; all main figures are single-column vector assets.

== Data and code availability

The study code, frozen protocol, paired measurements, process records, and analysis scripts will be publicly available upon publication in the accompanying Volund repository: #link("https://github.com/GustavoWidman/volund")[github.com/GustavoWidman/volund]. The paths and hashes in this supplement identify the supporting artifacts and their provenance. The repository will provide the retained evidence and instructions for offline reproduction.

== Disclosure of AI use

OpenAI generative AI tools assisted the manuscript, supporting software, analysis scripts, and visualizations, in addition to the measured campaign roles described above. The campaign accounting excludes manuscript and supporting preparation work. The authors are responsible for the content, source attribution, and conclusions.


#bibliography("refs.bib", style: "ieee")
