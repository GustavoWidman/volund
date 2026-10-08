# Instrumented multiagent runtime, draft v2

This implementation launches **real independently executing Codex threads** through
Codex 0.159.3 app-server. The lead decides whether to delegate, what to investigate,
when to review, and how to use results. The host is an instrumented transport and
policy boundary, not an optimization or measurement script pretending to be agents.
No model inference has been executed during implementation. Fake-server outcomes
and old numeric replay are software tests, not experimental results.

## Current approved roles and stopping

- Lead orchestrator: `gpt-6.1-sol`, `high`
- Independent empirical reviewer: `gpt-6.1-sol`, `high`
- Measurement, implementation, deeper-investigation workers: `gpt-6-luna`, `xhigh`

There are no campaign, reviewer, per-agent time or token budgets, and no fixed
hypothesis, turn, agent-count, or concurrency quota. Waiting up to 60 seconds in
one `study_wait` call is a tool response interval, not a worker deadline. RPC
admission timeout is an infrastructure watchdog, not an agent reasoning limit.
The owner controller determines scientific workflow closure. A lead final message
only completes a turn. `continue_lead(fixed_reminder)` allows the owner to continue
an unfinished workflow in the same context with cumulative accounting intact.

## Public Python interface

Use these imports with the v2 directory on `sys.path`:

```python
from runtime.contracts import RoleSpec, Safeguards
from runtime.multiagent import Host, wait_for_completion
from runtime.transport import StdioRPC

rpc = StdioRPC.official(cwd, direct_terminal_authorized=True)
await rpc.open()
host = Host(
    rpc, role_templates, Safeguards(), fresh_evidence_dir,
    role_factory=role_factory,
    additional_tools=tool_specs_by_role,
    tool_dispatch=dispatch,
    artifact_roots=(owner_development_root, owner_authority_root),
)
await host.initialize()
lead = await host.spawn("lead", task)
await wait_for_completion(host)
# If owner workflow is still open, supply only its predeclared continuation:
# await host.continue_lead(fixed_reminder)
# await wait_for_completion(host)
# After owner workflow closure:
report = host.export()
cleanup = await rpc.close()
report = host.seal()
```

`RoleSpec(model, effort, cwd, writable_roots, instructions)` uses existing absolute
`Path` directories. `role_templates` contains all five roles and the fixed models.
`role_factory(agent_id, role, parent_agent_or_None)` is a synchronous owner callback
returning a `RoleSpec`. The host verifies the fixed model, approved template roots,
and absence of overlap with any other agent's writable roots, including finished
agents. The default factory creates fresh per-agent directories. The owner factory
may materialize a verified source snapshot in that actor's own writable candidate.
`Agent.spec` is the exact admitted spec; do not bind authority from the template.
`artifact_roots` contains existing owner-approved directories whose paths may be
referenced in compact reports. It only validates artifact pointers: it does not
grant writes, change sandbox roots, or read the referenced files. Symlink escapes
outside the approved roots remain rejected.

`additional_tools` is a role-to-dynamic-spec mapping, such as the concatenation of
`development.dispatch.tool_specs(role)` and the owner service's tool specs.
`tool_dispatch(agent, tool, arguments)` is async and receives the identity resolved
from the invoking protocol `threadId` and `turnId`. No actor/role input is trusted.
The owner must bind each DevelopmentService to an immutable ActorGrant derived
from that identity, and make its cancellation check reject `host.stopping` or an
actor in `cancelling`/terminal state. The host cannot stop a native backend process
by merely cancelling an asyncio wrapper around `to_thread`; the backend owns that
process's cooperative cancellation and process cleanup.

`stop(reason)` first revokes new work, interrupts active turns, and cancels pending
host handlers. Always close the transport in an owner's `finally` block. Success
requires both `cleanup.tracked_processes_exited` and `cleanup.event_stream_drained`.
The transport drains stdout/stderr to EOF before the final export. Known idle,
unloaded, closed, and exact duplicate terminal/usage notifications are benign after
sealing. New late usage is retained and invalidates the sealed result; new tool
activity also invalidates it. The reader continues to drain subsequent usage.
`close()` is idempotent and shields its cleanup task against caller cancellation.
The owner's signal callback must cancel only the workflow task, never raise out
of the event loop and trigger cancellation of the protocol readers. Emergency
`Host.stop()` revokes tool work and allows a five-second technical shutdown grace
for interrupt acknowledgments and terminal notifications before process cleanup.
This is a cleanup watchdog, not a research budget. Its exported `shutdown` record
identifies agents still incomplete before transport close. Final agent states and
numeric usage are exported only after the stream drains.

Canceled or timed-out RPC replies are discarded by their known request IDs while
later usage notifications continue. A malformed event records an explicit stream
processing error and invalidates success, but does not discard subsequent valid
numeric usage. Cleanup separately reports `event_stream_drained` and
`event_processing_complete`; a reader already canceled cannot establish either.
An interrupted turn remains incomplete even if its observed token total is known.
The owner
can remain idle at a readiness gate after all turns are terminal. A fresh official
transport per experimental phase is preferred. If reusing a connection, initialize
it only once, retire old thread subscriptions, retain late-event detection, and do
not erase old ledgers. Do not replace a live Host's callbacks.

`runtime.launch.run_manifest` is a minimal integration-preflight convenience
runner; it deliberately does not authorize or run a measured campaign. The full
owner launcher is responsible for readiness/freeze checks and scientific closure.

## Exact supported event flow

1. `initialize` opts into `experimentalApi`, with reasoning-delta opt-outs;
   `initialized` completes the handshake. `account/read(refreshToken=false)` uses
   only the account-type discriminator and requires ChatGPT authentication.
2. `thread/start` registers an ephemeral fresh role thread. It requests the exact
   model/effort, `allowProviderModelFallback=false`, standard requested tier,
   write sandbox roots, and host dynamic tools. No history is forked or resumed.
3. The host verifies returned model/effort/provider, CLI version, ephemeral flag,
   cwd, sandbox, and approval policy; then registers that thread before `turn/start`.
4. The lead's `study_spawn` arrives as the server request `item/tool/call` with
   `threadId`, `turnId`, `callId`, `namespace`, `tool`, `arguments`. The independent
   reader continues dispatching every thread's events while tool handlers await.
5. A child gets its own `thread/start` and `turn/start`. The host replies with
   `success` and `contentItems: [{type: "inputText", text: ...}]` after admission.
   Workers run actual native shell/edit tools and authorized development tools.
6. Lead tools `study_status`, `study_wait`, and `study_message` expose compact
   reports and artifact pointers. Active messages use `turn/steer` with
   `expectedTurnId`; idle followups use another `turn/start` on that thread.
   Reviewers can receive followups in their own independent context.
7. Public `study_cancel` is cooperative branch abandonment. It uses `turn/steer`
   with a fixed instruction to stop investigating, preserve work/evidence, and
   return a factual abandoned or inconclusive report. Its acknowledgment does not
   imply completion. The worker remains running until its terminal event. A worker
   already terminal is returned as-is, with no extra turn or request.
8. Owner-only `Host.cancel` uses `turn/interrupt` for technical/emergency stops.
   Its RPC acknowledgment also does not establish termination. The owner verifies
   terminal events and cleanup; interrupted/failed turns remain incomplete usage.

Each incoming dynamic call is deduplicated by `(threadId, callId)` and exact payload
fingerprint so retransmission cannot launch duplicate children or measurements.
Unanticipated approval, input, auth, or other server requests are not approved.
Dynamic argument validation uses the advertised schema itself: fields, types,
role enum, task character bounds/nonblank content, array limits, and finite wait
range. Errors return that exact schema, field diagnostics, owned child IDs and
repair guidance. Child-addressed tools only accept children of the invoking lead.
A child whose startup failed before it acquired a thread cannot be messaged; the
error explicitly requests a replacement. Running/terminal reviewer followups
use the reviewer's independent context, with the same access rules.

## Native subagents and limits of isolation

The 0.159.3 config schema says `agents.enabled` disables multiagent tools, while
`features.multi_agent_v2=true` takes precedence. This client explicitly sets
`agents.enabled=false`, `features.multi_agent=false`, and
`features.multi_agent_v2=false`. The installed CLI's non-inference `features list`
confirms both feature names. An observed native collab/subAgentActivity item,
native child thread, or unregistered-thread usage fails closed; campaign totals
become unknown rather than treating unobserved children as zero.

The native schema does expose `parentThreadId`, child thread IDs, role and requested
model/effort metadata. It does not establish that every child's usage is delivered
before observer subscription. Thread/Turn read snapshots have no token-usage
field. Thus this host uses explicitly registered independent sessions, not native
ancestry, and records its own parent mapping accurately as host-managed delegation.

Native workspace-write enforces writes; it is not read isolation. Reviewer source
snapshots and owner evidence are outside reviewer writable roots; only reviewer
scratch is writable. Prompts prohibit credentials, session/auth files, unrelated
sources, nested Codex/API launches, and external communication. Those instructions
are not a hostile-code security boundary. The global development lock and native
backend handle actual execution integrity and process resources.

## Evidence and accounting

See [ACCOUNTING.md](ACCOUNTING.md). The evidence sink projects only ordinary
commands, outputs, patches, task messages, and compact final reports into actor
JSONL files. It never writes arbitrary protocol events. Native development tools
save full executable command/stdout/stderr evidence through their own service.
The protocol's `aggregatedOutput` can be truncated by Codex; shell evidence is
therefore exportable output, not a claim to recover omitted bytes. Reasoning
items, summaries, deltas, raw response items, authentication data, generic errors,
and session logs are never retained.

Compact model reports have exactly four required fields: `summary`, `artifacts`,
`checks`, and `limitations`. Artifact strings can be IDs, hashes, paths, or prose.
They remain inert and unverified: report parsing never resolves a symlink, opens
a file, or grants access. `report_diagnostics` labels each reference and any
schema errors; owner/development tools retain all authoritative evidence checks.
The earlier hidden whole-report byte limit and path-only requirement are removed.
Schema violations retain a bounded ordinary summary plus explicit diagnostics;
the complete known ordinary fields or unparsed final text remain in JSONL
evidence. Unknown structured fields are not copied. A repaired valid report
clears the current report-format issue, preserving prior diagnostics in evidence.

The official binary is pinned at
`/workspace/scratch/eeae3ae186b3/build-tools/codex-stable/node_modules/.bin/codex`.
The PATH binary is a different alpha version. The authentication runtime is used
only as a path in the official process environment; its contents are never opened.
Inherited runtime/security environment variables are preserved. The known nested
runtime restriction is not bypassed: actual launch is a user-direct-terminal step.

## Checks and remaining integration gates

Run from the repository root:

```sh
python3 -m unittest discover -s experiments/unattended-optimization-v2/tests/runtime -p 'test_*.py' -v
```

Fake-process tests exercise real stdin/stdout JSON-RPC, interleaved dynamic calls,
lead/measurement/reviewer streams, event-before-response ordering, duplicate usage,
missing/late events, compact reports, cancellation, cleanup, context bookkeeping,
role identity, no native delegation, independent workspaces, and reasoning-sentinel
exclusion. `v1-numeric-replay.json` records read-only replay of 16 frozen old turns
and 241 numeric notifications, all matching their original endpoints.

Still required before campaign use: real user-launched supported-runtime preflight;
actual tool exposure/role-model acceptance; real per-role token streams; native
child command execution and write boundaries; owner workflow closure and review
provenance; interruption and cleanup against real processes. Fake tests do not
prove these integrations. Exact billed dollar totals remain unavailable without
verified request cache-write, actual billing tier, and context price class.
