# C3 post-hoc large-array Memcheck supplementation

**Verdict: all five finite probes passed.** Each run made exactly one oracle-verified call to the unchanged final-assessment C3 library, tracked real heap allocations, freed every tracked block, and reported zero errors from zero contexts with zero suppressions. This supports memory-error and leak coverage for the exercised large-array radix paths. It is not a proof of memory safety for every input.

This diagnostic was authorized and executed on 2026-10-02, after all three campaigns and the automatic final assessment had finished. It is **post-hoc supplementation**, not an optimization run, new acceptance decision, canonical assessment operation, or replacement for any historical failure. No candidate was edited or rebuilt. No model or benchmark call was made. All diagnostic durations, CPU usage, and memory measurements are excluded from the original performance and cost outcomes. The original cohort, acceptance decisions, configuration, and result claims remain unchanged.

## Why a supported route worked

The canonical NativeBackend invocation already used the installed official Valgrind 3.24.0 launcher and its matching library directory, the dynamically linked canonical driver, and `--extra-debuginfo-path=/workspace/scratch/eeae3ae186b3/profiling-tools/root`. The retained successful canonical final Memcheck invocation tracked allocations and freed all blocks, but its profile fixtures stopped below C3's 32,768-element radix cutoff.

The failed dynamic supplemental invocation (`workspace-0d641e6e02d34dd196721171b458463f`) omitted that debug-info search path and terminated before execution because the required `strcmp` redirection in `ld-linux-x86-64.so.2` could not be set up. The log explicitly identifies missing dynamic-loader debug information as a possible explanation. Reusing the complete already-working canonical command with the existing debug-info tree resolved the coverage gap here without installing software or changing any guard or platform setting. Because the historical custom executable also differed from the canonical driver, this is a supported resolution and a diagnosed command difference, not a controlled one-variable causal experiment.

The static supplemental executable (`workspace-d9303c9a6f4a4d9bab490970654d94f4`) completed 26 oracle cases but exited 99 with two pre-main libc/loader diagnostics in `__strcspn_sse42`/`strsep`/`_dl_init_paths` and zero tracked allocations. Its “all heap blocks freed” line could not establish candidate leak coverage. The LeakSanitizer-enabled attempt (`workspace-5880da836a5e411383d9b0b4b043b7a3`) was blocked by unsupported ptrace; the sanitizer attempt with leak detection disabled (`workspace-f72d7e1deb894904b5aa016e3d138065`) passed its exercised cases but did not supply leak checking. None of these original attempts proves an engine leak. Their original records remain untouched, and exact copies are retained under `historical-evidence/`.

## Fixed identity and safeguards

- Source snapshot tree SHA-256: `7d87f5bb7d2232ea7375b621a85cc76fc750f997ab92239c4be9d7c9e129c45a`
- Exact existing final-assessment library SHA-256: `bc13b95b6dcc0bae388f9efa3b83163a3ba1f89d7d9c436e2f5918d09d4f47cf`
- Canonical driver SHA-256: `abe144bd69e01d3e1228a74f83d76b0a205939cf1f25a9c39d915d2a6c509438`
- Canonical driver source SHA-256: `016c2859a3df178d623bb72cdc5c904c8abeb30265dccf926b61704ac46ce05a`
- Existing public NativeConfig file/configuration SHA-256: `a0154d67630e6b38ad407e3b007549b8cdda9e339136fa8f31d3e2c5e770187e`

The source tree hash was recomputed using the study's unchanged canonical `encoded(tree(source))` definition and matched both the completed authority endpoint and the existing final build result. The exact library matched its final build result and file seal. Before and after execution, 477 protected file hashes matched, including the frozen manifests/runtime artifacts, public backend pins, source snapshot, final build and memory records, C3 authority files, relevant original failed-operation records, original custom logs, the diagnostic script, and relevant Valgrind inner binaries. `integrity-before.json` and `integrity-after.json` both report pass with no mismatches. Input and expected-result hashes were also checked before and after every probe.

Execution used the unchanged NativeBackend `run_process` and `process_exec.py`, including CPU affinity `[0,1]`, 4 GiB address-space limit, 2 GiB observed peak-RSS ceiling, 64 MiB file-size limit, 180 CPU seconds, 200 wall seconds, core dumps disabled, descendant tracking, and cleanup. All tracked descendants exited. There were no suppressions, command retries, new security permissions, guard changes, or platform setting changes. The ordinary command environment was isolated as in the canonical runner, with matching `VALGRIND_LIB`, empty `DEBUGINFOD_URLS`, and UTC/C locale.

## Predeclared finite coverage

The five-probe plan was written before the first native invocation. Three probes use unchanged existing public development input and expected-result files. Two are deterministic query/result projections of the existing `v2-skewed` fixture: every event byte is unchanged, selected query bytes are unchanged, and the corresponding existing oracle result bytes are retained. Projection indices, hashes, and full per-input coverage descriptions are in `plan.json`. These are post-hoc diagnostic inputs, not additions to the frozen fixture suites.

| Probe | Events | Queries | Radix array exercised | Allocations = frees | Verdict |
|---|---:|---:|---|---:|---|
| `v2-global-mixed` | 125,000 | 1,400 | Global, 125,000; order reused for requested stream buckets | 1,666 | Pass |
| `v2-skewed` | 250,000 | 1,000 | Global, 250,000; order reused for the 237,591-event hot stream bucket | 946 | Pass |
| `v2-high-cardinality` | 180,000 | 1,800 | Global, 180,000; 1,590 requested stream indexes | 3,245 | Pass |
| `v2-skewed-stream-only` | 250,000 | 888 | Independent stream-0 radix, 237,591; preallocated sort workspace | 944 | Pass |
| `v2-skewed-global-only` | 250,000 | 112 | Global, 250,000; workspace growth without requested stream indexes | 66 | Pass |

In each selected radix array, timestamp bytes 0, 1, and 2 vary. The exact sealed source therefore enters the `size >= 32768` radix path, performs three distribution passes, and copies back after the odd pass count. Global-plus-stream probes exercise stream construction from the globally sorted sequence; the stream-only projection removes every global query and forces independent stream sorting. This path argument comes from the exact input and source, rather than added branch instrumentation or a changed executable.

The driver used `--mode verify`, which calls the engine once, checks its return code, compares every output with the retained oracle, verifies unmodified event/query buffers, and checks output canaries. All five stdout records show `repetitions=1` and `verified_calls=1`. Every stderr record reports positive allocations, equal frees, zero bytes/blocks in use at exit, and `ERROR SUMMARY: 0 errors from 0 contexts (suppressed: 0 from 0)`. The flags retain canonical definite-leak error handling; the stronger observed zero-live-heap result makes no leak-category exemption relevant to these completed processes.

## Evidence and reproduction

- `plan.json`: identities, fixed probe order/purposes, input/expected hashes, projections, coverage argument, and limitations
- `run_diagnostic.py`: exact preparation/verification/orchestration source; launched with `python -B experiments/unattended-optimization-v3/analysis/posthoc-memory-20261002/run_diagnostic.py` from the repository root
- `memcheck-*/exec-spec.json`: exact argv, environment, cwd, and resource limits
- `memcheck-*/command.json`: exit status, process/descendant cleanup, and diagnostic resource observations
- `memcheck-*/stdout.txt`: unmodified driver correctness output
- `memcheck-*/stderr.txt`: unmodified Memcheck logs
- `derived-public-inputs/`: preserved deterministic query/result projections
- `results.json`: machine-readable verdicts and allocation counts
- `protected-files.json`, `integrity-before.json`, `integrity-after.json`: before/after identity verification
- `historical-evidence/`: unchanged copies of the four relevant original supplemental operation records and two original Memcheck logs

The orchestration intentionally uses create-new evidence writes and will refuse to overwrite this run. A future replication must use a new explicitly labeled output directory and retain this record.

## Limits

These finite probes do not cover exact-cutoff neighbors, all-equal timestamps, high-byte/full-width timestamp distributions, allocation failure, or all valid combinations. The stream-only case contains one large radix bucket plus smaller buckets; it does not establish workspace reuse across multiple large radix buckets. The compiler/interpreter/system-library/debug-info dependency closure is not hermetic. Historical sanitizer and canonical memory checks keep their original scope. No general memory-safety theorem, universal leak guarantee, new acceptance claim, or performance conclusion follows from this supplement.
