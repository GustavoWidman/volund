# Range statistics engine contract

Build and optimize a portable C++20 in-memory event-query engine. The complete implementation and data structure may be redesigned. The public C ABI is fixed by engine.h. The workload models batched event analytics; building any index and answering all queries are part of each measured invocation.

## Exact behavior

`engine_run(events, event_count, queries, query_count, results)` returns 0 on success. For query j, include every input event whose timestamp satisfies `lo <= timestamp < hi` and whose stream equals the query stream. Query stream UINT32_MAX means all streams. Return count, exact signed sum, minimum and maximum in results[j]. For no matching events all four result fields are zero. Duplicate events count separately. Input order is arbitrary and must not affect the answer. Empty intervals (lo == hi) are valid. Event values span int32_t and timestamps span uint64_t. Sums fit int64_t under the size limit.

Return 1 for invalid input: event_count >1,000,000; query_count >4,096; null events with positive event_count; null queries or results with positive query_count; any event stream ==UINT32_MAX; any query lo > hi; or nonzero query.reserved. For return 1, all provided output slots must remain unchanged. Zero-length arrays may have null pointers. Counts above either limit must be rejected before accessing any array element; no backing storage for an excessive count is promised, and any actually provided output memory must remain unchanged. For counts within limits, other non-null pointers identify valid nonoverlapping arrays of the indicated lengths; arbitrary invalid pointers are outside the contract. Allocation/runtime failure may return 2 and leaves output unspecified; such a result on an in-budget valid evaluation is an operational failure. No exception may cross the ABI.

Inputs must remain byte-for-byte unchanged. The implementation must be reentrant and safe for concurrent invocations on disjoint outputs. It must not retain input pointers, input-dependent indexes, previous results or benchmark-specific answers between invocations. Immutable constants and ordinary allocator reuse are allowed. Every call must compute its results from its current arguments. Persistent mutable caches of input data or computed answers are prohibited even when keyed by input content.

## Program boundary

Implementation workers may edit the source in their assigned candidate workspaces
and create additional tests and diagnostic scripts in their own scratch areas.
The interface, this contract, public development fixtures and tests, inherited
prototype, their own campaign's sources, tool evidence and factual records are
available to them. Official tests and measurement tools remain immutable; workers
may add their own tests without replacing the official ones. Other campaigns and
the independent assessment inputs and results are not participant inputs.

Workers may compile, test, profile, benchmark and repair repeatedly. The public
development tools produce reproducible evidence; ordinary compilers, tests and
diagnostic tools are also available for investigation. A failed local check does
not exhaust a submission opportunity or end an investigation. Canonical native
measurements use the shared measurement lease so competing study jobs do not
contaminate them. Exploratory checks outside the canonical settings must state
their commands and limitations. The shared host is not a hostile-code sandbox;
role boundaries and hash checks have stated limitations.

C++20 standard library only. Canonical comparison builds use fixed flags:
`-std=c++20 -O3 -g -DNDEBUG -fPIC -shared -pthread -march=x86-64 -mtune=generic`.
No inline assembly, architecture-target attributes/pragmas, target-specific
intrinsics, external libraries or dynamically generated implementation code.
Algorithms, layout, allocation strategy, batching and parallel work may be
redesigned. Workers may use additional debug or diagnostic builds, but those
results do not replace canonical comparison measurements. Canonical benchmark
children use the same two available logical CPUs; these CPUs are not dedicated.
Program resource ceilings and technical process watchdogs will be fixed in the
version 2 configuration before measurement. They are not research time/token caps.

No network, subprocess creation, filesystem access, environment inspection, clocks, randomness, output printing or benchmark/harness introspection from engine_run. The evaluator and profile driver perform their own I/O outside the candidate invocation. Correctness tests, source/integrity checks and observed traces are finite probes, not a proof against malicious behavior.

## Optimization and evidence

The objective is to investigate whether a complete redesign or smaller changes
can improve measured performance while meeting the exact behavior and resource
requirements. The lead orchestrator delegates baseline measurement, implementation
and empirical verification to workers. It formulates a falsifiable hypothesis
from evidence and can request repeated investigations, revisions or specialist
help. Edited candidates can be profiled and benchmarked before they are proposed
as verified checkpoints. Do not specialize to fixture identities, memorize their
answers or exploit the evaluator.

Each hypothesis report distinguishes supported, contradicted and inconclusive
claims and retains failed attempts and uncertain evidence. A negative finding is
a valid result. The independent reviewer actually rebuilds and runs the candidate,
examines tests, native timings and profiles, and challenges unsupported claims.
The hypothesis verdict and whether code is promoted are separate decisions.
Exact checkpoint promotion and stopping rules are specified in the version 2
protocol before execution; a separate frozen final assessment remains withheld.

Use the mediated factual record tools for observations, commands, source hashes,
evidence references, outcomes and lessons. They append records without rewriting
earlier entries. Preserve full ordinary tool evidence outside the lead's context;
summaries should point to it. Do not export private reasoning or invent results.
Lead and worker contexts are part of one campaign, not independent experimental
replicates. Independent campaigns start from the seed and do not share learned
solutions or journals.

No adaptive human optimization hints are supplied during a measured campaign.
Requirements changes or necessary human interventions become explicit deviations.
Automatic tools, agent delegation, empirical review and predefined recovery rules
are part of the workflow. Task completion is evidence-based; there is no fixed
campaign time/token quota or requirement to force a successful optimization.
