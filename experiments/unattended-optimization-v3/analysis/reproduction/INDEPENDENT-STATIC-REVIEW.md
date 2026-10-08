# Independent static reproduction review

Reviewed 2026-10-01 during the measured-campaign embargo. This is a source review,
not a successful replay, packaging receipt, test result, or release approval.

## Scope and method

Inspected reproduction and figure-extraction source, synthetic test source, and
the frozen owner/runtime/development/evaluation writers. No tests were run and no
study execution modules were imported. No native workloads, packaging,
compression, rendering, campaign-result reads, held-out input/result reads,
credential/session reads, or private-reasoning reads were performed. Only this
review document is edited by the reviewer.

## Findings sent to the implementation owners

1. **Separate byte verification from scientific release.** A blocked canonical
   report was accepted by the archive gate and unconditionally returned
   `scientific_result_release: true`, bypassing the native replay refusal. A
   preserved partial record must retain its blocked status and be ineligible for
   released-science/native-remeasurement claims.
2. **Cross-check actual sample artifacts.** Numerical replay initially compared
   raw/paired/schedule values but omitted each writer-produced `measurement.json`,
   `command.json`, calibration, and separate bootstrap record. Add checks against
   exact archived configuration parameters without opening fixture inputs.
3. **Use actual profile output names.** The frozen profiler writes
   `annotation-NN/stdout.txt`; the lean selector used `annotate-`, dropping the
   promised profile annotations while also omitting raw profiles.
4. **Retain explicit blocked/missing stages.** A blocked final report can precede
   the seed build. Numerical audit must report this absence, not require a build
   that never ran or claim a complete replay. Inconsistent recorded artifacts
   must still refuse verification.
5. **Authenticate before executing pricing helpers.** The extractor executed
   pricing source from an arbitrary evidence root before authenticating its
   freeze or pricing-file pin. Optional helpers also came from that root. Bind
   frozen pricing bytes before execution; use trusted pinned analysis helpers;
   reject symlinks in every path component and ambiguous JSON.
6. **Ship synthetic portability fixtures.** The namespace policy initially
   excluded `analysis/figures/fixtures/host-export-checkpoint.json`, although the
   shipped figure tests depend on it. Admit the explicit synthetic fixture path,
   without recursively admitting generated analysis outputs.
7. **Harden archive names and nonconstant numerical fixtures.** Reject control
   characters in filenames and define portability restrictions. Add nonconstant
   paired samples: a constant 2:1 fixture cannot distinguish correct joint-block
   resampling from incorrect independent-family resampling.
8. **Bind final operations and outcome gates independently.** Configuration
   hashes initially matched only the report, and source/binary checks did not
   cover every build/test/memory operation. Bind report and integrity-receipt
   hashes to frozen final configs; bind each operation to its sealed subject and
   corresponding successful build. The final outcome must also agree with the
   frozen build/memory/both-strata-validation gate.

## Source disposition

The final focused reread confirms source fixes for all eight findings. Final
configuration, source, binary, endpoint-inventory and validation-gate checks now
match the frozen evaluator. No material static-review blocker remains in the
reviewed preparation; actual replay and reproduction tests remain deferred.
The full archive additionally preserves formal `workspace-operations` evidence,
and the lean subset retains calibration pilot output needed by numerical checks.

Both reproduction test files were read, including the new writer-shaped
`test_hardening.py`. They cover conflicting per-sample/command/calibration/
bootstrap records, driver-field mutations, anti-correlated temporal blocks and
a blocked assessment before any seed build. These tests remain unrun by this
reviewer. Eight explicit reproduction/extractor source files passed AST parsing;
the extractor-local pricing helper's SHA matches its pinned constant. AST parsing
and source inspection do not establish runtime correctness or actual-study replay.
The final revised replay and hardening-fixture files were parsed again after the
last source changes. The review was closed at 22:32 UTC on 2026-10-01.

## Writer contracts confirmed from source

- Checkpoint usage is raw `Host.export()` at the owner-chain absolute path and
  SHA. It has neither `runtime_source` nor `campaign_id`. The terminal runner adds
  `runtime_source` but still does not add `campaign_id`. Campaign attribution
  comes from canonical paths plus host start, artifact roots and agent identity.
- `freeze.manifest.root` is the sole historical origin. Rebase only canonical
  suffixes inside it. Keep original bytes and hashes; never open old host paths.
- Campaign native inputs bind through the recorded `build_id` and build library
  digest, with configuration integrity receipts. Do not demand final-evaluator
  fields that the campaign writer does not emit.
- Retry authorization and the first-valid rule agree with the frozen
  infrastructure-only predicate. Invalid retained timing fields must never
  become estimates, and a valid or nonretryable outcome ends its retry series.
- The estimator is the exponential of the equal-family mean of median paired
  log ratios. One bootstrap index sample is shared across every family; the
  one-sided 90% lower bound interpolates at `0.1 * (B - 1)`.
- Native replay is a separately labeled posthoc run, with new output/config
  paths and fixed archived sources. It must not invoke canonical assessment,
  change source/fixture pins, mutate seals, or reselect an endpoint.

## Deferred validation

After explicit release of historical measurements: run the small synthetic
reproduction/figure tests, including blocked/no-build outcomes, actual writer
schemas, per-sample contradictions, nonconstant joint-block arithmetic, foreign
origins, path escapes, symlink parents, malformed JSON and helper-pin tampering.
Then verify full and lean bundles independently, compare their numerical outputs,
and test relocation into a new directory with old host paths unavailable. Confirm
exact omission inventories and annotation/fixture preservation. Any fresh native
run remains optional posthoc evidence in a separately prepared environment.
