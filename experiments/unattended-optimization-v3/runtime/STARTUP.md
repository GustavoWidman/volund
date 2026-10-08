# Thread startup validation

The owner-launched no-inference diagnostic on 2026-10-01 returned
`workspaceWrite` with no additional writable roots. Its cwd, approval policy,
network flag, and both temporary-directory exclusions exactly matched the
request. The request redundantly listed cwd as its sole extra root. Exact JSON
dictionary comparison incorrectly rejected this equivalent policy before any
`turn/start` call.

Pinned Codex `rust-v0.159.3` source explains both sides of the round trip:

- [`SandboxPolicy::get_writable_roots_with_cwd`](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/protocol/src/protocol.rs#L1163)
  includes cwd in effective writable roots, independently of the extra-root list
- [`FileSystemSandboxPolicy::to_legacy_sandbox_policy`](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/protocol/src/permissions.rs#L1727)
  marks a write entry equal to cwd as the workspace root, omitting it from extras

Inspected 2026-10-01. The generated local `ThreadStartResponse.json` defines the
legacy response fields. The original diagnostic remains unchanged at
`setup/thread-start-diagnostic-01/diagnostic.json`. The portable sanitized test
fixture replaces only its cwd; the test explicitly supplies the ephemeral bit,
which the live failure had already validated but the metadata allowlist omits.

Validation now compares the exact effective root sets: cwd plus extra roots.
Only duplicates, ordering, and redundant cwd entries are normalized. The owner
paths are canonicalized when creating `RoleSpec`; response paths must match
those exact strings. Validation does not dereference arbitrary response paths,
accept aliases or traversal, or relax equality to path containment. Additional
or missing roots, wrong cwd, changed policy type, network access, missing or
false temporary-directory exclusions, approval-policy changes, and unknown
sandbox fields are rejected.

`Host.spawn` records allowlisted metadata before validation, so a rejected
thread remains diagnosable without retaining a raw response, account details,
messages, instructions, or reasoning. The separate diagnostic initializes the
transport, checks only the account mode, creates one ephemeral thread, requests
`thread/unsubscribe`, and drains/cleans up the process. There is no inference
method in that script. The fixed `tools/diagnose-thread-start` wrapper accepts no
arguments and refuses an existing output directory. Subsequent diagnostics must
use a newly reviewed output path through the module interface; they must never
overwrite failed setup evidence.

All 57 runtime tests passed after this correction. Tests cover the actual
sanitized response, duplicate/order equivalence, broader/narrower/malformed
roots, symlink aliases, flags, approval and cwd mismatches, allowlist privacy,
no-inference call order, and failed-start metadata retention. This validates the
adapter correction; the actual multiagent preflight is still required.
