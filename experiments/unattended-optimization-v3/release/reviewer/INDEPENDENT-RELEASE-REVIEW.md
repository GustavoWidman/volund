# Independent V3 evidence release review

Reviewed 2026-10-02 after historical measurement ended. **No material blocker found for the authorized local full/lean materialization.** This review is not a completed bundle receipt, compressed-size result, or authorization to distribute.

## Concrete plans reviewed

- Full plan: `f8b5013ee087ac80e35d669c0155bac468cc05a40ff20f2a175838c90ae1ef0f`; 82,658 files, 436,452,741 bytes
- Lean plan: `2a8127785f5d5e2f2c42e8d1cf8061da344b174db7014907145bccc902f290aa`; 61,087 files, 332,880,312 bytes
- Shared complete inventory: `7398101410c730075d9555fbeee99858bd16c9ba7332e03ccb7f98f69c724fca`
- Lean omission inventory: 21,571 files, 103,572,429 bytes; every omitted pin exactly matches the full plan and the declared omission policy

The lean materialization is below the approved 350,000,000-byte ceiling. The separate 25,000,000-byte compressed transport limit remains unmeasured by this reviewer and must be checked before any future staging decision.

## Independent checks

1. Rehashed all 193 required frozen files with no differences. Freeze SHA is `a28a9e9984aa03a1a28c950bfd846e0d179202f719a43982a27c72a69c934178`; final report SHA is `4c0da852efa41ae3440c09a9faf2e6de0797ac1036ebbbdfc052b4f658f66227`. All three campaigns and the assessment are terminal and complete.
2. Checked every final-plan path and pin schema, disjoint present/omitted inventories, exact shared commitment, omission reasons and terminal metadata. No removed files relative to the provisional plan. Additions are precisely three formal readiness-revision JSON files; changed files are confined to five analysis files, including the figure README and plot source. Their current pins and content checks passed.
3. Validated all 25 full-only filtered runtime streams, comprising 254 ordinary items, against the strict type schema. Private/auth/session/raw-provider/node_modules/scratch namespaces remain excluded. Outside-origin public node_modules pins stay inert metadata; direct synthetic boundary checks confirm within-origin node_modules and external private path refusal. No external dependency was opened.
4. Reviewed source against the frozen retry predicate and temporal-block bootstrap writer. Replay preserves invalid/failed attempts without giving their retained timing fields scientific estimates, binds immutable source/build/configuration/reference identities, and keeps first-valid selection independent of scores. Final endpoint and validation gates remain anchored to canonical evidence.
5. Independently recomputed all six final paired-data point estimates and checked their six-family, 30-block, 360-sample inventories; all matched the canonical report. This reviewer did not repeat the 52-comparison bootstrap replay or the 18-test suite reported by the implementation owner.
6. Audited observed cumulative arithmetic for the three terminal ledgers and eight anchored checkpoint ledgers, and independently rederived the frozen telemetry invariant/issue rules. No unrecorded counter issues were found. All eight checkpoints truthfully retain incomplete accounting status. Terminal observed subtotals are 39,990,945; 44,941,304; and 43,953,952 tokens.
7. Lean data retain all declared raw/pair/schedule/calibration/bootstrap JSON artifacts, command/measurement receipts, failure metadata and 416 annotation stdout files. Aggregate filename counts include setup/test evidence as well as canonical campaigns and must not be presented as scientific comparison counts.

## Necessary limits and remaining checks

- `audit_usage` validates recorded cumulative arithmetic and preserves issues/completeness flags; it is not a proof of every provider response or bill. Every terminal thread records `cache_write_reporting_verified: false`. Reported zero cache-write counters do not prove zero cache-write usage or cost. Actual billing, remote-compaction and failed-request cost remain unknown.
- Eight public external dependency pins are metadata only. Neither bundle is a hermetic environment or a claim that original timings will reproduce on a new host.
- The full archive means all eligible formal evidence, not private streams or participant scratch. Finite privacy scanners and typed factual streams do not prove arbitrary prose safe for distribution. No blanket distribution/privacy approval is implied.
- A lean verification can establish present bytes and anchored absent-byte declarations; it cannot reverify omitted binaries. Hashes establish byte identity, not historical custody or correctness.
- Complete materialized byte verification, full/lean replay equality, original-root-blocked relocation replay, and actual compressed-size/hash receipts remain the implementation owner's next checks.

Only read-only review and analysis ran. Output files were written solely under the external reviewer directory. No study modification, native execution, model call, upload, staging, commit or push occurred.

Machine-readable supporting reports: `independent-checks.json`, `independent-numerical-crosschecks.json`, `independent-usage-issues.json`, and `final-plan-review.json` in this directory.

## External helper source skim

`compress_verified_bundle.py` writes only declared regular members, fixes tar ownership/time and gzip time, rereads every member, verifies its SHA/size/executable bit, rejects duplicates/unexpected members, and hashes the complete transport. This is source review; the actual output and compressed-size result remain pending. Its documented precondition is prior full/lean byte and numerical validation, enforced by the coordinating workflow rather than the helper itself.

`replay_with_origin_guard.py` imports the bundled analysis source and wraps replay in a Python audit hook for file opens under the canonical original root. At the reviewed version it uses lexical `Path.absolute()` comparison. It is not OS filesystem isolation and does not establish that arbitrary symlink or parent-directory aliases are inaccessible. Describe its eventual receipt narrowly as an actual replay with the canonical-origin Python open guard, or strengthen resolved-path checks before making a broader alias-resistance claim. The source replay's own rebasing and bundle path checks remain separately necessary.

## Resolved-origin guard addendum

Reviewed the revised external helper on 2026-10-02. It now resolves both the original study root and each string/bytes file-open path before containment checking. The earlier lexical `Path.absolute()` alias limitation is addressed for this guarded path comparison. Synthetic direct, parent-directory-alias and symlink-alias paths were refused; a separate path was accepted. The reviewed helper SHA-256 is `438b9c84871331983c841e3e8c1d5d55ed4508f5af7eaa201ea124d00995aeb2`.

The claim remains a Python file-open audit guard around the actual replay, not OS isolation, a proof covering every possible I/O mechanism, or a hermetic execution environment. The guard is installed after bundled analysis imports and manifest loading. The implementation owner reports that both copied bundles passed exact verification; full/lean replay outcomes and actual guard receipts were still pending at this addendum. No study files were changed by this review. See `resolved-origin-guard-review.json` for the bounded synthetic checks.
