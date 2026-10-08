# v2 development tools and runtime contract

Status: implemented setup infrastructure, not a frozen or launched experiment. Lead and independent reviewer use Sol/high; workers use Luna/xhigh. There is no fixed research wall/token budget or proposal limit. Task-based completion may conclude without an improvement. Technical process watchdogs detect hangs and runtime cancellation remains available. Full child-telemetry preflight and owner approval are required before any inference or experiment.

## Workflow and public API

The lead delegates benchmark/profile work, records an evidence-grounded hypothesis, delegates implementation/investigation, and produces a report. Workers can repeatedly edit/build/test/profile/benchmark/repair/delegate. Ordinary candidate errors are retained feedback, not consumed one-shot proposals. Repeated identical-source measurements are allowed and retained. Exact command compliance is not the scientific outcome.

`development.dispatch.tool_specs(role)` supplies authenticated runtime dynamic-tool schemas. `make_dispatcher(service_for_agent)` returns `async dispatch(verified_agent, tool_name, arguments)`. It runs work in a thread under a per-actor lock. The Host owns authentication of Agent and supplies an actor-bound service; participant arguments never supply actor, role, authority, reference hashes, or resource configuration.

- `study_dev_snapshot(candidate)` captures immutable source
- `study_dev_build(source_hash, purpose='exploratory')` creates a fresh fixed-flag build operation
- `study_dev_test(build_id, purpose='exploratory')` runs independent canonical correctness
- `study_dev_profile(build_id, fixture_id, purpose='exploratory')` profiles any recorded passing build
- `study_dev_memcheck(build_id, fixture_id=None, purpose='exploratory')` probes all public profile families by default; a selected family never claims full coverage
- `study_dev_bench(build_id, reference_id='inherited', purpose='exploratory')` compares against an owner-approved reference
- `study_dev_journal(text, evidence_ids=[])` appends an immutable entry
- `study_dev_index()` returns compact summaries and artifact pointers
- Reviewer-only `study_dev_review_evidence(build_id)` returns empirical execution provenance, never a promotion decision

All profile and Memcheck commands use separate diagnostic limits; their elapsed times are never speed evidence. Normal terminal tools remain available for worker-owned extra tests, custom compilers and debugging inside the runtime-assigned sandbox. Arbitrary argv is deliberately NOT exposed as a host dynamic tool. The internal `run('check', ...)` path is restricted to `setup_owner` for controlled setup only; ActorGrant is not a filesystem sandbox.

## Service and authority

`DevelopmentService(store, authority, NativeBackend(config), Limits(...))` provides `snapshot`, `run`, `append_journal`, `index` and `review_evidence`. A store can be shared across an investigation; its metadata lock serializes mutations and backend operations. Separate stores share one global native lock. Model work and editing may continue concurrently.

Authority implements:

1. `active_grant() -> ActorGrant`, raising `Cancelled` when cancelled
2. `expected_head(store_key) -> SHA256 | None`
3. `commit_head(store_key, old, new)`, durable compare-and-swap outside participant writable roots

ActorGrant contains investigation, actor/job/parent, role, authority-record hash, boot identity, allowed candidate roots, inherited baseline source/library hash/path, and optional `ReferenceLibrary` records (e.g. seed). Optional per-operation watchdog deadlines default to None. They are technical hang safeguards, not research caps. The runtime must bind each service to the verified actor; a self-authored JSON file or `--actor reviewer` is not sufficient. `active_grant` is checked while queueing and supplied to native supervision for cancellation. Cancelling an asyncio await alone does not terminate its native thread.

Every source snapshot, operation request, command output, profile and result gets retained hashes. Completed artifact trees and snapshots are rehashed before/after work. Append-only event nodes are hash-chained and anchored externally through authority. Direct modification/deletion, injected entries and truncation fail verification. Source disappearance during an operation still creates terminal failure evidence before the integrity exception. An unsealed crash requires explicit owner reconciliation; nothing silently deletes or retries it.

The journal consists of immutable entries. Corrections append references to earlier entries. Any presentation/rendering is derived, not authoritative. Raw compiler/test/profile stdout/stderr are full ordinary output artifacts; concise summaries go to the lead. No private model reasoning is requested or stored. Runtime owns model usage and ordinary terminal-command telemetry.

`audit_store(store, independently_persisted_expected_head)` is a read-only owner helper returning verified events, snapshots and completed operations. It requires no active participant grant and creates no files. Owner must still enforce actor ancestry, nomination, plan and endpoint policy.

## Independent review and prospective comparison selection

Owner supplies `review_plan_id`, `review_source_hash`, and `official_reference_id` in the reviewer grant. `purpose='official_review'` cannot be self-authorized by workers or pointed at another source. A nomination's immutable plan/source/reference binding must survive repeated binds and replacement reviewer contexts. Owner must not mint a new plan to discard an earlier result.

A review receipt requires the current reviewer to execute its own fresh official build and successful test, profile, complete-suite Memcheck and benchmark on that exact build. The receipt returns all official attempts across the plan, including failures. Its gate comparison is deterministically the FIRST complete valid official comparison across that plan/source/reference, across all actors/jobs/builds; never best or last. That selected comparison's exact binary must itself have passing canonical correctness, profile and full Memcheck records. Fields expose both current review build/binary and selected comparison build/binary/actor, without assuming independently rebuilt binaries are identical. A confirmed official semantic failure (including an isolated guard-page count-contract violation) or Memcheck error-exitcode 99 disqualifies that exact source under the nomination plan. Later passing reruns cannot erase it. A disqualified receipt returns the prior invalidating operation IDs; exploratory reproduction stays available, while repair requires a new source and linked nomination. Unexplained timeouts or incomplete diagnostics are not labelled semantic proof. The owner evaluates scientific claims, negative/no-code reports, technical recovery and promotion gates separately.

## Native preparation and reuse

`development.prepare.prepare_native(root, fresh_destination, definitions=None, tool_root=..., compiler=...) -> NativeBackend` generates public fixtures, compiles the driver and records configuration/pins. Existing output directories are refused. It never calls a model, profiles or benchmarks. Owner serializes this setup with all other native load. Explicit deployed tool paths are used; repository nesting is not used to guess runtime locations.

`pin_config(config)` prepares pins after an owner selects an alternative fixture/suite configuration. `NativeConfig` defaults to public development/profile suites and 10 paired blocks. Owner-only fields `benchmark_suite`, `correctness_suite`, `profile_suite`, `allowed_suites` and `case_seed` support genuinely named final strata at 30 blocks without relabelling them development. Participant tool arguments cannot change them. `case_seed` propagates to random, metamorphic, repeated, concurrent and maximum-query correctness probes. Named semantic/manual/invalid probes may intentionally overlap.

The copied native driver and independent oracle algorithms have provenance in `native/provenance.json`. No old campaign lifecycle, optimized artifact, outcome, journal, fixture bytes or held-out input was copied. `task/` is supplied separately by the owner. New correctness includes isolated inaccessible-page oversized-count probes, checking that no input element is touched and a small output sentinel remains unchanged.

Native subprocesses use explicit argv, fixed two-CPU affinity, CPU/address-space/output limits, zero core dumps, private TMPDIR and offline Valgrind. A small exec wrapper avoids unsafe Python preexec_fn in a threaded host. Group cleanup and observed pidfd-bound descendant cleanup run before releasing the global lock. Fast reparenting can evade observation; there is no cgroup/hostile-code containment claim.

The default draft ordinary limits are 1 GiB address space, 512 MiB observed RSS, 64 MiB per output file, 30 CPU/wall seconds per measured driver command. Compile gets 120 CPU/wall seconds, correctness 150 CPU/180 wall seconds; oracle cases get 8 CPU/10 wall seconds and 768 MiB address space, with 512 MiB observed RSS required. Diagnostics get 4 GiB address space, 2 GiB observed RSS and 180 CPU/200 wall seconds per process. These are explicit technical/validity settings pending freeze, not investigation budgets.

Pins cover selected Python source, contract header, driver, compiler executable, Valgrind launcher/annotation and fixture files. Compiler subprocesses, system shared libraries, Valgrind inner executables/lib/debug directories and interpreter dependency closure are NOT all individually pinned. Integrity reports state this limitation. This is not a hermetic build or security sandbox.

## Fixtures and measurement

`native/generate_public.py` exports `make(spec)` and `generate(definitions_path, fresh_destination, suites=('development','profile'))`. Owner can explicitly supply final suite names. No old fixture is read.

Each spec has id/shape/seed/event_count/query_count, stream_cardinality, timestamp_max (inclusive), timestamp_distribution (`uniform` or `clustered`), hot_event_fraction, hot_query_fraction, all_stream_query_fraction, empty_query_fraction, absent_query_fraction, and either query_width_fraction `[min,max]` relative to timestamp_max+1 or integer narrow_width_max. `force_first_global_query` explicitly controls a full-span/all-stream first query. Manifest records actual all-stream/empty counts. `direct_crosscheck` selects all queries or predeclared sampled indices; the exact checked indices are retained.

Canonical draft development sizes (events/queries): small 1,000/16; sparse 160,000/1,800; dense 220,000/500; global 125,000/1,400; skewed 250,000/1,000; high-cardinality 180,000/1,800. All use fresh v2 seeds. Profiles cover all six families at 1k–16k events and 16–256 queries. `definitions.smoke.json` is explicitly smaller setup-only scale; its correctness smoke is not canonical-scale validation.

Benchmarking uses balanced AB/BA within each family, shuffled family order per temporal block, and calibration fixed before scored samples. Common repetitions use the faster arm's larger pilot requirement. Native driver validates every result/input/canary and times the full engine invocation including index construction. It sums individually timed calls with validation between them; batching does not eliminate timer overhead. Instrumented durations never enter speed ratios.

Portfolio speedup is exp(mean of family medians of paired log ratios). Deterministic 10,000-resample bootstrap resamples complete joint temporal blocks, with linear-interpolated lower one-sided 90% quantile. Raw samples/calibration/schedule and each partial sample are retained. Driver JSON must agree on exact fixed repetitions, verified-call count, elapsed/per-call normalization, finite positive measurements and RSS. A genuinely under-target scored batch after valid calibration is retained and explicitly flagged; there is no adaptive retry or batch change. These exploratory repeated-use statistics do not establish confirmatory agent-efficacy significance. NativeBackend never promotes or rolls back. Owner applies its prospectively frozen gate to the selected official comparison.

All executable backend load, including benchmark/profile/Memcheck/build/correctness, takes the same global lock across actors/stores. Queue time is recorded separately. Lock waiting responds to cancellation and optional technical watchdogs, without imposing a research deadline.

## Verification limits

Fake/synthetic tests exercise actor/reference binding, repeated repair, journal/evidence mutation/deletion/truncation, cancellation/queueing, cross-build/cross-context selection, reviewer execution, suite isolation, correctness-report consistency, whole-profile-family Memcheck coverage and deterministic statistics. Native setup tests compile real code, verify the unchanged seed, reject wrong results and test an overcount scan-before-check mutant against guard pages. All records live under tests/development.

No native benchmark, native profiler/Memcheck or model inference has been run by this development task. Canonical-scale workload generation/validation, native timing/profile preflight, full authenticated owner/runtime integration and child usage preflight remain required before launch. Hashes do not prove meaningful hypotheses, substantive delegation, sound reviewer reasoning or complete ordinary-terminal instrumentation.
