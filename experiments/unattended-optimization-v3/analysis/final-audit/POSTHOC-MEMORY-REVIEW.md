# Independent post-hoc C3 memory-diagnostic review

Reviewed 2026-10-02 UTC. This is a separate read-only evidence review after the original cohort and first canonical assessment had completed. The reviewer executed no native code. The diagnostic worker ran five explicitly authorized fixed-endpoint probes under `analysis/posthoc-memory-20261002`; they are excluded from original acceptance, performance, campaign usage, automated-process counts, and canonical final-assessment results.

## Verdict

The five retained probes provide clean finite Memcheck evidence on exercised large-array paths of the exact sealed C3 endpoint. They address part of the original supplemental instrumentation gap. They neither erase the original failed custom invocations nor retroactively make this work part of the unattended campaign. No candidate repair, optimization, rebuild, new performance comparison, or endpoint reselection was involved.

Each command exited zero in verify mode with exactly one successfully checked engine invocation. All five stderr logs show positive actual heap allocations matched by frees, zero heap bytes/blocks at exit, and `0 errors from 0 contexts (suppressed: 0 from 0)`. Therefore these are materially different from the historical static custom Memcheck log, whose zero tracked allocations made heap evidence unusable.

## Exact bindings checked

- Endpoint source inventory: `7d87f5bb7d2232ea7375b621a85cc76fc750f997ab92239c4be9d7c9e129c45a`
- Existing final canonical library: `bc13b95b6dcc0bae388f9efa3b83163a3ba1f89d7d9c436e2f5918d09d4f47cf`
- Existing final-assessment driver: `abe144bd69e01d3e1228a74f83d76b0a205939cf1f25a9c39d915d2a6c509438`
- Driver source: `016c2859a3df178d623bb72cdc5c904c8abeb30265dccf926b61704ac46ce05a`
- Diagnostic configuration file: `a0154d67630e6b38ad407e3b007549b8cdda9e339136fa8f31d3e2c5e770187e`
- Plan: `e29addba84964e0b80be0bb321a517641d61b809c9cb006fcf6281d8b8c2194e`
- Results: `a358e4e8a149e12cecc69bcda85496f19be68daa48056921d5685455b1a7f3a4`

The driver matches the frozen final evaluator's driver. The development `launch-native` driver has a different binary hash, so any precise prose should identify the reused binary as the final-assessment driver. Both use the pinned driver source, but binary identity should not be conflated.

I independently rehashed all 477 protected files against the manifest; no mismatch was found. The before/after integrity records are identical. I read the diagnostic script without executing it and verified that the finite five-probe plan was written before the first native invocation. All five distinct planned probes have one retained command record. It reuses the canonical `--extra-debuginfo-path` setting absent from the unsuccessful original dynamic custom probe. The new successful route also uses the existing final driver and public fixtures; the result should not be described as an isolated causal experiment proving that this single flag alone explains every previous instrumentation failure.

## Independently checked input and path coverage

I parsed the input/expected binary headers and records, recomputed their hashes, checked valid event/query metadata, and verified that projected event arrays and retained query/expected-result records are byte-identical subsets of the existing public skewed fixture. No held-out fixture is used.

| Probe | Events | Queries | Large sorted array | Allocations = frees |
| --- | ---: | ---: | --- | ---: |
| Public global mixed | 125,000 | 1,400 | Global, 125,000 | 1,666 |
| Public skewed | 250,000 | 1,000 | Global, 250,000 | 946 |
| Public high cardinality | 180,000 | 1,800 | Global, 180,000 | 3,245 |
| Skewed stream-only projection | 250,000 | 888 | Stream 0, 237,591 | 944 |
| Skewed global-only projection | 250,000 | 112 | Global, 250,000 | 66 |

Source plus actual input structure deterministically selects the C3 radix branch above the 32,768-event cutoff. All these large arrays vary in timestamp bytes 0, 1, and 2, hence exercise three radix passes and odd-pass copy-back. Mixed probes also create demanded stream buckets from sorted global order. The stream-only projection exercises one large bucket, preallocated workspace, and small fallback-sorted buckets; the global-only projection covers global sorting without stream-map construction. These are source/input-derived branch conclusions, not separately measured branch counters.

The observations do not cover full-width/eight-active-byte timestamps, all-equal timestamp behavior, exact cutoff boundaries, allocation failure, maximum contractual size, concurrent calls, or workspace reuse across multiple large radix buckets. They do not establish all-input memory safety, leak freedom, or memory-resource limits for every valid input. The dependency closure remains nonhermetic. Instrumented elapsed values printed by verify mode are diagnostic overhead, not performance evidence.

## Manuscript integration boundary

Keep the original campaign's six configured public Memcheck passes and the unsuccessful custom invocations as historical facts. State that separately authorized post-hoc validation later passed five large-array public/projection probes, with the above scope and limits. Do not add these five to the original 357 development operations, 22 final operations, 68 role turns, token-cost subtotal, promotion gates, or automatic campaign closure.

The derived machine-readable check is `analysis/final-audit/posthoc-memory-audit.json`. The original-evidence review remains `INDEPENDENT-RESULTS-REVIEW.md`; this addendum supplements it without rewriting the historical evidence or verdict.
