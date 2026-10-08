# Independent v3 launch protocol review

Final review checkpoint: 2026-10-01 20:15 UTC. No measured-launch authorization is implied.

No unresolved implementation contradiction was found in the reviewed requested
workflow. The outstanding launch condition is completion and reconciliation of
the fresh setup evidence, followed by its exact immutable readiness/freeze. No
execution-area files were edited by this review.

## Findings

- The three serial campaigns obtain fresh Host sessions and workspaces and each
  OwnerService bootstrap snapshots the original seed. The seed SHA-256 is
  `d32e6ec47c628378248720b38e3b6c1d63c9da867f72adb92bf836213e894414`, matching the
  original experiment's seed file. “Independent” means separately initialized;
  the protocol correctly qualifies shared host, task and service dependence.
- Requested lead/reviewer routing is `gpt-6.1-sol/high`; execution workers use
  `gpt-6-luna/xhigh`, with provider fallback disabled. Configured scientific wall
  and token caps are null. Transport admission and adjustable native watchdogs
  are technical controls rather than research quotas.
- Dynamic delegation, repeated same-context follow-up, exploratory development,
  independent empirical hypothesis review (including negative/no-code findings),
  immutable nomination, first-valid official selection and reviewed task closure
  agree between protocol, prompts and implementation.
- Ordinary candidate failures, invalid tool arguments, malformed journal entries
  and compact-report schema errors remain repairable evidence. Runner aborts on
  actual runtime, observed-accounting or integrity incompleteness; this is not an
  ordinary participant-error cancellation rule. Stopped seals retain incomplete
  status. Final assessment cannot proceed without all three canonical seals.
- All routed shell/native work uses the shared resource coordinator. Bounded
  workspace reads and owner status avoid the long native/metadata locks. Retry
  classification is limited to the two attested invalidity causes; valid poor
  scores and under-target observations cannot authorize an automatic retry.
- Final assessment retains the canonical cohort identity, source/binary bindings,
  two separate strata, failed/missing observations and first-valid attempts.
  Same-source endpoints are labeled algebraic identity rather than measured A/A.
- Usage prose distinguishes reconciled observed counters from full provider or
  billing coverage and states interrupted-tail, compaction, cache-write, request
  partition and whole-project cost limitations.

The owner clarified two documentary carryovers in the protocol: historical v2
labels in the copied task do not supersede current v3 workflow instructions, and
the unused `infrastructure_automatic_retries: 0` field describes generic
infrastructure relaunches rather than the narrowly permitted timing-attempt
series. These clarifications do not require an execution-area edit or new model
preflight by themselves.

## Required fresh evidence and the native bridge

Fresh real multiagent preflight, native correctness/resource/A/A controls,
current synthetic orchestration checks and actual CLI-router evidence must all
be mapped explicitly to protocol section 13 in readiness. The fixed
`REQUIRED_CHECKS` names alone do not enumerate every section 13 subcontrol.
Record the evidence layers and their source hashes, including controls verified
through synthetic rather than native execution.

`evaluation/validate_setup.py` calls NativeBackend directly. Its
`thirty_block_final_route_completed` field establishes native 30-block timing;
it does not by itself exercise `evaluation.run.assess` or its retry orchestration.
Existing scheduler, DevelopmentService retry and final-assessment fault tests
use synthetic backends. Existing integrated real CLI checks establish the shell
route but not a bounded read during an actual native benchmark.

The authorized test-only bridge is
`tests/audit/validate_native_measurement_bridge.py`. It exercises the unchanged
OwnerService, DevelopmentService, CoordinatedBackend, WorkspaceRouter and final
`assess()` with a real NativeBackend. It retains source, binary, fixture/config,
lease and attempt records; tests bounded source/status reads while the actual
native post-launch poll and metadata lock are active; and injects one explicitly
labeled observer fault after a completed real comparison in each route. That is
a controlled setup injection, not an observed external preemption. The isolated
final root contains one behavior-preserving comment variant and two synthetic
incomplete/unavailable seals. No measured campaign or canonical v3 assessment
directory is used. Native work must run only after the parent signals that all
other setup native activity has finished and the launcher is parked.

The bridge passed syntax/import checks and an ephemeral synthetic-backend
full-driver smoke, including actual file-lock and API shapes. That smoke was
explicitly not native readiness evidence. After the live preflight was parked
and the other native readiness controls had ended, the parent authorized the
real bridge run. It completed at 20:12 UTC, **all seven checks passed, exit 0**, in
257.96 seconds. No failed native bridge attempt preceded this passing run.

The run retained two 10-block development comparisons and three 30-block final
comparisons, with unchanged build/correctness/Memcheck work. All 1,401 native
command receipts show completed tracked-process cleanup; the shared coordinator
ended with 16 released leases, no active/queued job and no quarantine. Workspace
cleanup reports drained. A 512-byte source read and compact status retrieval
completed in 1.18 ms while the real benchmark lease and development metadata
lock were held.

The first valid development observation was 1.00843 and the first valid final
transfer observation was 0.99329. Both were retained, showing that the native
bridge accepted observations below the 1.03 development improvement screen and
a final regression without score-driven retry. These are setup controls, not
campaign outcomes or estimates of optimizer efficacy. The injected first
attempts remain addressable; their complete native samples were not pooled into
the selected attempts. Both final strata ran for the comment-only source; the
other four rows retained incomplete/unavailable status.

Evidence: `setup/native-measurement-bridge-01/result.json`, SHA-256
`68c13b1c4676fb26733bcbb80b88c6306c4697980f852ce26b9650b635581c9d`.
Its isolated final report is
`setup/native-measurement-bridge-01/isolated-root/assessment/final/report.json`,
SHA-256 `eb59fb2a82d180b97b96cdf9b45d291d045d95fe2a0f620f27ee7a4db0305f99`.

The separate readiness recorder was reviewed for evidence scope. It creates
readiness records only and does not authorize launch. It correctly requires the
parked launcher and an unchanged real-preflight execution inventory, distinguishes
synthetic orchestration from native controls, and excludes auth/private content.
The owner added reported script/source, regression/native-control log and nested
bridge-report/result hash validation before record creation, plus explicit
drained-workspace and empty/nonquarantined-lane checks. The final recorder code
was inspected and all corresponding reported file hashes were independently
matched to current bytes. These are recorder-only checks, not changes to
experimental execution. No unresolved review blocker remains before the owner
creates readiness, binds the immutable freeze and explicitly releases launch.

The six current regression suites also passed: development core 24, native
synthetic 18, owner 58, runtime 71, independent audit 38, final evaluator 12
(221 total). Their evidence and hashed logs are retained in
`setup/readiness-regressions-01/`. This report is final for readiness binding and
will not be edited after freeze.

## Reviewed bindings

| File | SHA-256 at review |
| --- | --- |
| protocol/PROTOCOL.md | c5c7d2e9f04165f7938a5f763dfda63ff684d149773bda15e265b7b387d5c53f |
| evaluation/PLAN.md | 3a067c53cc275ed695853782746d3611d52a9967f80f0036706275b59ba814f0 |
| owner/config.draft.json | 1e1b0ad01eaba5732fd0923690bc68ecc990641098bd605026697c9af31ff3f9 |
| owner/runner.py | 176b849098c8a86d168de6c3fc5ce7dfb2caea679fdcf41eb4a25e3d65e327d9 |
| owner/readiness.py | b74d0f678a06d9105a64e1abc6f5fbae6f67a303fe712eb0c16e8cfaaa350678 |
| tests/audit/validate_native_measurement_bridge.py | 82131b2c0f64fc352970d3995b81648dd439538ae3c01a0c9847012657512ad6 |
