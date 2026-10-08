# Version 3 owner workflow

Status: executable prototype, not frozen or measured. Synthetic service and full
Host/dispatcher integration tests have run. They do not establish real provider
routing, permissions, native timing, or the deployment preflight.

## One user-started direct-terminal launch

From any directory, the deployed executable is:

`/workspace/scratch/eeae3ae186b3/interno-study/experiments/unattended-optimization-v3/tools/start-study.sh`

The wrapper resolves its own deployment directory, performs non-inference checks,
then starts one detached supervisor in a new session with closed terminal input.
Closing the initiating terminal does not send its hangup to the workflow.
`state/start-attempt/` exclusively retains the check, process identity, stdout,
stderr, and supervisor exit status; detailed progress remains in
`state/launch/status.json`. Any prior attempt, launch, preflight, freeze, campaign
or assessment artifacts block a duplicate start. Nothing is automatically
restarted after failure. Machine shutdown, external hard kills, and filesystem
loss are not recovered by this ordinary detached process.

Append `--check` to the same command to run only executable/version/import/path
and deployment-writability checks. It performs no model calls, creates no launch
attempt, and only checks whether the fixed authentication directory exists. It
checks both the official wrapper and actual native executable; those files,
package manifests and the native companion are also pinned by the later freeze.

Do not execute the launch from nested model tools or change security environment to
make it run. The runtime preserves inherited restriction variables, uses only
the already-authenticated runtime path, and pins official CLI 0.159.3. No
credentials or session logs are read by the owner.

The launch prepares fresh public native fixtures and driver, then runs the actual
multiagent setup scenario through official app-server threads. The lead chooses
and follows up with real workers; compile failure/repair, profiling, independent
review, journal correction, a reviewed negative/no-change result and source closure
must all leave attributable evidence. No measurements from this scenario enter
campaign results.

After preflight the runtime is closed. The launcher parks without inference at
`state/launch/status.json`, status `awaiting_exact_owner_readiness_no_inference`.
It does not guess that passing unit tests authorize a campaign. Existing launch,
preflight or campaign directories cannot be silently overwritten or resumed.

The owner reviews the actual record and all native/evaluator controls, prepares
a readiness document with every `REQUIRED_CHECKS` entry pointing to its exact
passing evidence file, and binds `final_evaluator_manifest` to
`evaluation/readiness.json`. Then:

- `tools/study-v3 freeze --readiness <owner-readiness.json> --preflight state/launch/preflight.json`
- `tools/study-v3 authorize --freeze-sha256 <exact> --readiness-sha256 <exact> --preflight-sha256 <exact>`

These are owner handoff operations under the requested workflow, not additional
model runs. An exact source/inventory drift after real preflight blocks freeze;
any drift after freeze blocks the measured gate. Later changes require an
explicitly reviewed new setup/version rather than silently accepting new hashes.

The same waiting process then launches three fresh-seed campaigns sequentially.
No research time, reviewer time, token or attempt cap is inserted. A lead ending
a turn without scientific closure receives a fixed continuation in its same
context. Normal completion requires reviewed hypothesis dispositions, no concrete
remaining actionable queue, branch dispositions, and independent closure review.
Ordinary branch abandonment uses cooperative `study_cancel` or a wrap-up message;
its acknowledgement does not claim the worker has terminated. The worker returns
a normal completed turn with retained evidence and usage. Owner emergency
interruption and technical failures retain an incomplete endpoint and stop
dependent launches without substitution; missing partial-call usage is never
assumed complete.

After all three normally completed endpoints are sealed, the owner invokes the
separate final evaluator for transfer/shift strata. It freshly builds and checks
those sources and uses 30 complete paired blocks. It never feeds results back to
optimizers. User cancellation uses a cheap event check inside native work; full
hash verification occurs outside operations. The assessment remains a separate
owner-controlled phase with its own evidence and status.

## Readiness and artifact contract

The final evaluator supplies:

- `evaluation/readiness.json` with status `ready`
- `configurations.transfer` and `.shift`, each `{path, sha256}` for its root-relative serialized NativeConfig
- `artifact_files`, mapping absolute prepared artifact paths to hashes
- Its declared control-test evidence

The freeze independently loads/verifies both NativeConfigs, every required
source/tool/fixture pin, the actual generated fixture manifest and all its input
and expected-output files. It also pins the direct launch's native configuration,
its required artifacts, exact executable materials, official CLI wrapper, native
CLI executable, native companion and installed package manifests.
This is a declared dependency boundary, not a hermetic compiler/OS image.

## Services and protocol

`OwnerService(root, fresh_campaign_directory, backend, config, setup=False)` owns
its authoritative event chain and projection. `attach_host(host)` binds actual
runtime Agent/thread/turn objects. `service_for_agent(agent)` returns a
DevelopmentService with an owner-issued ActorGrant and externally anchored event
heads. Caller-supplied role/model/actor/hash claims cannot replace this binding.

The Host receives `combined_specs(role)` and `make_dispatch(owner)` for
`study_owner_*` and `study_dev_*`. Expected malformed journal/tool requests return
correctable errors. Authoritative source/evidence integrity failures stop dependent
work. Role prompts are in `prompts.py`; they guide flexible investigations rather
than forcing a fixed worker pipeline.

Owner state includes hypotheses and versions, explicit claim kinds, actionable
queue, journals/corrections, immutable nominations, independent inspections/reviews,
promotions, direct seed-relative trajectory observations and closure dossiers.
All prior attempts remain in the development and owner event chains.

Promotion uses the prospectively first complete valid official comparison under
the immutable source/parent nomination plan. Rebinding a reviewer target or
renominating the same source/parent cannot reset selection. The exact selected
comparison binary becomes incumbent; a later build cannot borrow an earlier
binary's score. Confirmed official semantic/Memcheck defects disqualify that
source/plan, even if a later attempt passes. Failed/incomplete execution can still
be reviewed and rejected without manufacturing successful gates.

The quantitative default is G >= 1.03, nominal one-sided 90% lower > 1, and every
family >= 1/1.10, using 10 complete paired development blocks. Owner and backend
share one joint-complete-block bootstrap implementation and explicit seed
2026100302, with 10,000 resamples. These are operational gates, not campaign-wide
significance guarantees. All official attempts are retained; later exploratory
work remains possible without replacing the selected observation.

A negative/no-code hypothesis requires the registered kind of independent actual
execution. Performance claims need a benchmark and profile; a build-only claim
cannot substitute. Confirmed correctness or memory failures may support the
corresponding negative claim; transport failures/timeouts cannot. Source and
ordinary evidence inspection receipts prove delivery, not comprehension.

Every promoted checkpoint gets a direct seed comparison. The first promotion can
reuse the same independently measured seed-parent comparison; later promotions
get a new owner-controlled seed comparison, not a product of selected ratios.
Usage at a comparison time may still be incomplete while a model request is open;
those coordinates remain explicitly incomplete rather than interpolated.

## Timing coordination limits

Every official development operation uses the shared native lease. Ordinary
sandbox shell commands are additionally observed through commandExecution
start/end events. Any observed overlap invalidates a canonical benchmark and
retains its raw samples. This is conservative study-command auditing, not proof
that external host load or missed events cannot affect timing. Participant reads
are instructed boundaries; workspace-write is not hostile-read isolation.

## Verification

- `python3 tests/owner/test_owner.py`: ledger/gate/repair/claim/closure/readiness and overlap tests, injected native backend
- `python3 tests/owner/test_runner.py`: actual Host and both real dispatch layers with a scripted fake JSON-RPC peer; seven synthetic turns, all usage counted once, no real model/native workload

No test fixture is labeled a measured campaign or real telemetry preflight.

## Public interface repair and stop behavior

All owner finite verdict/state fields now carry explicit typed enums. Required
fields/defaults are checked against callable signatures, and public validation
returns field-specific allowed values and repair instructions before any native
operation or scientific transition. `claim_review.assessment=endorsed` endorses
the reported conclusion; it does not mean the hypothesis itself was supported.
Reviewer queue schemas permit only actionable concerns; non-reviewers cannot
select official-review execution. Status/index expose exact bound reference
aliases and public fixture IDs, with full-suite Memcheck omission documented.
Malformed candidate paths/selectors are correctable. Mutating sealed evidence
or changing source during capture remains an integrity stop. The execution scheduler retains independently invalidated timing attempts and
automatically requeues the same immutable comparison; the first valid result
remains binding regardless of score. Bounded source/status reads do not require
a quiet-window workaround. Ordinary candidate and command failures remain
repairable; unresolved cleanup or source integrity is a distinct blocker.

SIGTERM/SIGHUP/SIGINT request one workflow-task cancellation via the event loop.
The protocol readers stay active through shielded stop, drain, usage export and
status persistence. Repeated signals do not cancel that cleanup. Interrupted
partial-call usage is retained and never reclassified as complete accounting.
