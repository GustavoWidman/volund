# Independent v3 scheduler review

Status at 2026-10-01 19:37 UTC: **38 independent checks passing; actual integrated
CLI-router probe verified; no runtime/scheduler blocker for the real model/native
setup gate. Measured launch still requires its declared setup and freeze gates**.
The user rejected the v2 coordination behavior and requested a corrected fresh
run. V2 evidence and its stopped outcome remain historical and unchanged. This
review covers only the new v3 implementation and its setup validation. No new
experimental participant session or measured campaign has been launched by this
reviewer.

## Required behavior

1. The requested lead/reviewer remain Sol with high effort and delegated workers
   Luna with xhigh effort; no scientific time/token/retry quota is introduced.
2. Native shell tools are actually disabled for participant threads. Arbitrary
   participant execution travels through the supported, sandboxed CLI command
   RPC and a single coordinator shared by compilation, tests, profiles, memory
   probes, development timing, automatic seed comparisons, and final evaluation.
3. Bounded source/evidence reads and model planning remain usable during timing.
   A legitimate source read must not invalidate a comparison or wait for the
   DevelopmentService metadata lock. File access is bounded in work and output,
   excludes nonregular files and path escape, and does not execute arbitrary code.
4. Known measurement contamination or a specifically attested external
   interruption retains its immutable attempt and can retry the same source,
   binary, reference, inputs and measurement procedure. The first valid result
   wins regardless of its score. Candidate/semantic/resource/source/ledger
   failures, explicit cancellation, unknown infrastructure faults, and valid
   unfavorable or under-target observations are not favorable-result retries.
5. A lease remains held until subprocess cleanup is proved within the supported
   implementation. Unknown cleanup quarantines new resource work. An early RPC
   acknowledgement is not proof of completion.

## Concrete pinned-CLI cleanup finding

The source for Codex `rust-v0.159.3` establishes a material boundary:

- [`command_exec.rs`](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/app-server/src/command_exec.rs#L493)
  acknowledges a terminate control after requesting termination. Its final
  command result contains only exit code and captured output and is sent before
  the process handle leaves scope. It is not a descendant-cleanup attestation.
- [`ProcessHandle`](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/utils/pty/src/process.rs#L205)
  requests a kill and ignores the kill error; dropping the handle initiates
  termination and helper-task cleanup, without returning a descendant-exit proof.
- [`pipe.rs`](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/utils/pty/src/pipe.rs#L136)
  starts a new session, waits for its root child, and directs Unix termination to
  that process group. A descendant that enters another session/group is outside
  the scope of group-only signaling.
- [`process_group.rs`](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/utils/pty/src/process_group.rs#L245)
  uses best-effort group signals; signal delivery is not a wait-for-exit barrier.

Consequently, successful command/exec return, terminate acknowledgement, an empty
output stream, or deletion of a process ID from the CLI session map is individually
insufficient to release the measurement lease. A trusted in-sandbox supervisor
and a reliable descendant-reaping/attestation mechanism are candidate solutions;
their actual implementation and real setup behavior still require verification.
Unexpected connection loss or missing cleanup evidence must not be silently
converted into an automatically retryable interruption.

## Review matrix awaiting implementation

| Area | Required evidence |
|---|---|
| Shell suppression | Pinned source/config mapping and actual setup confirmation that builtin shell/exec routes are absent; routed arbitrary shell remains available |
| RPC boundary | Exact argv/cwd/process ID, original workspace-write roots, explicit network policy and no broader permission profile; unsupported params fail visibly |
| Cleanup | Background descendant, detached-session descendant, timeout/cancel, lost response and disconnect cases; lease cannot release while descendants may remain |
| Shared coordinator | Lead/reviewer/worker contention, automatic seed-relative timing and final backend all use the same instance/lock |
| Read availability | Bounded ordinary source/evidence read completes during a blocked benchmark without acquiring the native or metadata lock |
| Lock ordering | No metadata/coordinator inversion; canceled waiters removed, acquired-but-abandoned ticket released only safely |
| Fairness | FIFO resource admission; repeatedly retrying benchmark rejoins queue rather than starving pending compile/review jobs |
| Retry identity | Source/library/reference/fixture bindings unchanged across attempts; every failed attempt remains addressable |
| Retry classification | Overlap cannot overwrite or launder semantic/candidate/resource failures; unknown faults remain gates |
| Score blindness | First valid poor/no-gain result returns immediately; no retry on lower-bound failure or under-target samples |
| Interruption | Typed external cause and observer evidence plus confirmed cleanup; explicit user/owner cancellation never automatically restarts |
| Quarantine | Admission blocked after uncertain cleanup, queued waiters receive a clear blocker, no implicit reset/retry |
| Accounting | Retried tool/native work retained; planning and setup/review usage not silently treated as zero |

This is an implementation acceptance matrix, not evidence that these properties
already hold. Real CLI/model setup must be distinguished from synthetic coordinator
tests, and both must precede a new frozen measured launch.

## Independent synthetic checks at 18:37 UTC

`tests/audit/test_scheduler_review.py` was authored independently of the scheduler
implementation tests. All nine checks pass on the current coordinator/audit code:

- Native and routed-shell jobs share FIFO admission
- Quarantine wakes queued waiters and blocks new work after the old lease ends
- Cancellation while queued leaves no ticket and never enters the job body
- Cancellation after admission but before the acquisition result reaches the
  async caller releases the abandoned lease
- Concurrent-command overlap does not overwrite candidate/semantic failure
- Concurrent-command overlap does not overwrite resource/timeout failure
- Valid unfavorable or under-target timing is not classified as retryable
- Otherwise-passing overlap is retained and explicitly invalidated
- An external-interruption object requires observer/event identity and confirmed
  cleanup

Command: `PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s
experiments/unattended-optimization-v3/tests/audit -p test_scheduler_review.py -v`.
These are tiny synchronization/fake-backend tests. They do not establish actual
shell suppression, CLI sandbox behavior, OS descendant cleanup, retry execution
through DevelopmentService, final-evaluator wiring, or real native isolation.

Additional risks sent to the implementation owners: an open unleased command
without a terminal event must become a visible health/quarantine state when the
thread/stream becomes terminal, not deadlock uncapped work forever; malformed or
failed native cleanup receipts must quarantine just as routed shell failures do.
The runtime supervisor must finish cleanup before its RPC/transport timeout, and
parent cancellation must shield the original response/cleanup path.

## Native receipt failures found and corrected

At 18:40 UTC two new independent regressions failed against the initial native
cleanup wrapper: an `exec-spec.json` without its completion receipt was accepted,
and an empty `command.json` was interpreted as proof that Popen never started.
Both allowed the lease to end without sufficient cleanup evidence.

The scheduler owner changed the validator to enumerate expected receipts for
every native execution spec and require either an explicit no-process marker or
validated started-process/root/exit/scan evidence. Both regressions now pass;
the independent suite is **11/11 passing** at 18:42 UTC. The native producer must
write the new `process_started`/`process_pid` markers and include its prelaunch
cancellation check inside receipt-writing cleanup; that companion integration
was still being prepared at this check.

Two scope distinctions remain important: FIFO is guaranteed once a job enters
the coordinator, not before native callers acquire existing ledger locks; and
the final evaluator's direct backend path needs explicit shared-coordinator and
same-source attempt handling because it does not call DevelopmentService.run.
The current scaffold alone is not evidence of that final integration.

## Final-evaluator and practical cleanup checks at 19:15 UTC

The persisted final evaluator now accepts a shared coordinator, wraps both final
strata with `CoordinatedBackend`, and retains same-input benchmark attempts in
separate sibling directories. Its retry classifier is the same infrastructure-
only classifier used by development measurements. This implementation was
inspected and independently exercised through the actual `assess()` loop with a
synthetic backend, without invoking model inference or native benchmarks.

`tests/audit/test_final_coordination_review.py` passes **8/8** checks:

- Every final build, test, memory check and benchmark uses the supplied lane;
  final work waits behind a held workspace command lease
- The first contaminated attempt remains addressable with its manifest and raw
  result; retry keeps source, built library, reference and configuration fixed
- The first valid poor score is selected immediately
- A pending workspace job enters before a retry that rejoins the FIFO queue
- Attested external interruption retains partial evidence and retries
- Overlap does not reclassify or retry confirmed candidate failure
- Unknown interruption and explicit cancellation stop without an automatic retry
- Unresolved native cleanup quarantines admission before a later final operation

`tests/audit/test_supervisor_review.py` passes **5/5** additional local process
checks: late cancellation marker; SIGTERM to the supervisor with a TERM-ignoring
child; five nested detached descendants during watchdog cleanup; foreground
SIGKILL with a surviving background process; and simultaneous stdout/stderr
output above each 8 MiB cap. Each successful receipt is checked for drained
streams, stored-byte hashes, the root exit, and no remaining direct children.
These tests do **not** establish actual CLI workspace/network sandbox behavior.

Commands, from the v3 root, with `PYTHONDONTWRITEBYTECODE=1`:

```text
python3 tests/audit/test_final_coordination_review.py -v   # 8 pass
python3 tests/audit/test_supervisor_review.py -v           # 5 pass
python3 tests/audit/test_scheduler_review.py              # 11 pass
python3 tests/owner/test_measurement.py                   # 24 pass
python3 tests/evaluation/test_final.py                    # 12 pass
```

At this checkpoint, the participant runner still used `AuditedBackend` directly;
the shared router/runner integration and actual bounded read API had not yet
landed. Thus this checkpoint is **not launch clearance**. The required next checks
are the final integrated dispatch/runner, bounded reads during real lease
contention without metadata waits, sandbox-preserving command RPC parameters,
lost-response/disconnect quarantine, and actual no-inference CLI setup evidence.

The general-command supervisor explicitly provides observed cleanup against
ordinary process trees, not hostile same-UID containment. Canonical native work
still uses `DescendantTracker`, which explicitly cannot observe a descendant
that reparents before its scan. The participant `check` path is setup-owner-only;
general participant execution must use the sandboxed subreaper route. This
distinction must remain visible rather than overstating native containment.

## Actual router review at 19:22 UTC

`runtime/workspace.py` now supplies bounded descriptor-based read/list/search,
leased writes, and supervised arbitrary Bash through the CLI command RPC. The
new transport timeout override leaves session-admission timeouts intact while
allowing the command's adjustable technical watchdog and cleanup path to own its
lifetime. No model/research quota is added.

`tests/audit/test_workspace_review.py` independently passes **11/11** checks:

- A real bounded read and paginated search complete while a benchmark lease and
  the development metadata file lock are both held
- Literal matches spanning a 64 KiB boundary survive continuation; match-limited
  overlapping matches and directory pages neither disappear nor duplicate
- Symlink files/directories, FIFOs, hard links and parent/outside paths are rejected
  without blocking or following them; explicitly public files remain readable
- Cursors bind actor/path/query and reject changed input; all pages remain usable
- Writes wait for the same lane and cannot truncate an unsafe hard-linked target
- General shell text reaches only `command/exec`, with exact original writable
  roots/network/tmp policy, a pinned supervisor and no per-RPC command timeout
- Repeated caller cancellation preserves the original RPC and active lease until
  the cleanup receipt arrives; a queued resource job cannot enter early
- Lost RPC response or invalid cleanup receipt quarantines future resource work;
  bounded source reads remain available
- Changed capture files cause an artifact error only after cleanup was established

These tests use a synthetic RPC peer and the actual router/coordinator. The
separate `setup/workspace-cli-probe-01/result.json` was inspected and records
**four actual CLI checks passing with zero requested model turns**: normal command,
background-child cleanup, denied outside-root write, and denied outbound socket.
It retains CLI 0.159.3 metadata with workspace-write, network disabled, excluded
temporary roots, approval never, clean protocol drain and exited tracked CLI
processes. Its shell-disabled field records the requested setting; it does not
itself enumerate the model-visible tool inventory.

The runner integration, current role prompts, compact status behavior and final
launch readiness still require their final checks. Copied v2 launch instructions
and old manual quiet-window retry wording were flagged for the integration owner.
No measured launch is authorized by this interim review.

## Integrated cancellation regression found at 19:25 UTC

The shared-coordinator/router path is now wired into the participant runner and
the same launch coordinator reaches setup, all campaigns and final assessment.
An independent integration test found one concrete stop-order defect:
`tests/audit/test_runner_cancellation_review.py` fails because finalization waits
for `workspace.close()` before calling `host.stop()`. While a command cleanup
receipt is delayed, no model `turn/interrupt` is sent. Setting `owner.cancelled`
does not by itself revoke Host delegation or satisfy `validate_actor`'s stop check.

The synthetic test holds a command receipt, cancels the workflow, and requires
model interruption while the resource lease remains held and transport remains
open. It releases the receipt in its cleanup, so the failed test leaves no live
process or pending fixture. The integration owner was asked to begin host stop
concurrently before waiting for workspace cleanup, while preserving the later
transport-close barrier. This regression is a pending blocker until rechecked.

## Integrated corrections verified at 19:31 UTC

The cancellation-order defect is fixed and its independent regression now passes:
the runner marks the host stopping and starts model interruption concurrently
before draining workspace jobs. The resource lease remains held until the
original command receipt arrives, the transport remains open for that receipt,
and interrupted-turn token accounting is retained.

`tests/audit/test_runner_contention_review.py` exercises the former harmless-read
failure through the actual Host, owner dispatch, DevelopmentService and workspace
router, with a synthetic native backend and CLI peer. A measurement worker holds
the benchmark lease and development metadata lock. The lead reads immutable
source and compact status while an arbitrary shell command waits in the shared
queue. After the benchmark is released, its first attempt is valid at a synthetic
ratio of 0.8, with no overlap and no retry; the queued shell command then runs.
The full test completes with clean resource drain and retained usage.

The router's response timeout is now derived from the requested command watchdog
plus a 90-second cleanup/transport allowance, superseding the earlier `None`
override. This avoids an indefinite wait if a connected app-server silently
loses the final response. The independent lost-response case uses the real
`StdioRPC.request` path with a synthetic silent sender and a shortened test-only
allowance; it proves quarantine, a retained abandoned request, no retry, and no
subsequent resource admission. Metadata RPC timeouts remain unchanged. This is
an infrastructure bound, not a campaign, token or retry quota.

The current independent suite is **38/38 passing**:

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/audit -p 'test_*.py' -v
```

Breakdown: coordinator/classification 11; final assessment 8; local supervisor
cleanup 5; workspace router 12; integrated cancellation 1; integrated contention 1.
The current role prompts also name the workspace tools, compact history access,
and automatic infrastructure-only first-valid timing recovery. No implementation
blocker remains from this review at this point. Actual no-inference CLI-router
probe evidence is still pending review; later model/native setup readiness is a
separate requirement before freezing and launching the three measured campaigns.

## First integrated CLI probe fixture outcome

`setup/workspace-router-probe-01/result.json` retains a failed no-inference probe
at 19:32 UTC: its synthetic actor omitted `thread_id` and `turn_id`, required by
workspace request provenance. It stopped with `AttributeError` immediately after
the existing-auth-mode check, before acquiring any resource lease or executing a
workspace command. Both router and transport cleanup completed without quarantine.
Real `Host.Agent` instances already supply these fields; this is a probe-fixture
defect, not evidence of a failed command sandbox. The omission was flagged to the
integration owner. A corrected probe must use a new output directory and preserve
this failed setup record. The cancellation probe should also confirm command start
with a task-local ready marker before requesting cancellation.

## Actual integrated CLI-router evidence verified at 19:37 UTC

The corrected `setup/workspace-router-probe-02/result.json` passes **9/9** checks,
with **zero requested model turns**. The earlier failed fixture record remains
preserved. Independent verification is written to
`analysis/INDEPENDENT-CLI-ROUTER-VERIFICATION.json`, with the input report hash,
five matching current implementation hashes, and checks of all six operation
records and every captured command-output hash.

The real CLI executed a C++ compile/run after it queued behind a held measurement
lane. A bounded source read completed without an execution lease while that lane
was held. An ordinary exit code 9 remained repairable, and a subsequent command
succeeded. The cancellation case waited for the child-created marker, then
retained a `process_started=true`, `reason=interrupted`, exit -15 cleanup receipt
with two reaped children and drained streams before lane release. All command
requests retained the actor's exact workspace-write roots, disabled network,
excluded temporary roots, and derived watchdog-plus-90-second response deadline.

Afterward the router was drained, the execution lane and queue were empty with
no quarantine, the protocol event stream was fully drained/processed, all tracked
CLI processes had exited, and process tracking recorded zero scan failures.
This establishes the actual integrated command/read path in addition to the
independent synthetic contention, cancellation, classification and final-evaluator
tests. **No remaining runtime/scheduler implementation blocker was found.**

This review clears proceeding to the real multiagent/native setup gate. It is
not itself evidence of a successful model setup or a measured campaign, and it
does not remove the declared readiness/freeze requirements. The observed-process
and external-host-load limitations documented above remain in force.
