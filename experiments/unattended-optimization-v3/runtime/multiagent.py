"""Host-mediated, model-directed delegation using official app-server sessions.

No fixed optimization pipeline is encoded here. The lead chooses tasks, workers,
parallelism, messages, and empirical review checkpoints. The host owns permissions,
model routing, evidence, deadlines, and usage. No import-time model calls.
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field, replace
import hashlib
import json
from pathlib import Path
import time
from .contracts import (RuntimeFailure, CHILD_ROLES, ROLES, initialize_params, APPROVED_MODELS,
                        start_thread_params, turn_params, validate_thread_response, thread_start_metadata, RoleSpec,
                        dynamic_tools, dynamic_argument_issues)
from .telemetry import ThreadUsage, sum_totals, public_item

TERMINAL = ('completed', 'failed', 'interrupted', 'startup_failed')
COOPERATIVE_WRAP_UP = (
    'Stop this investigation. Preserve work and evidence. Return a factual abandoned '
    'or inconclusive report in the required JSON format. Do not begin new investigations.'
)


@dataclass
class Agent:
    agent_id: str
    role: str
    parent_id: str | None
    created: float
    state: str = 'starting'
    thread_id: str | None = None
    turn_id: str | None = None
    completed_turns: list = field(default_factory=list)
    all_turns: list = field(default_factory=list)
    started_at: float | None = None
    ended: float | None = None
    usage: ThreadUsage = field(default_factory=ThreadUsage)
    report: dict | None = None
    report_diagnostics: dict | None = None
    issues: set = field(default_factory=set)
    pending_turn: bool = False
    spec: RoleSpec | None = None
    active_intervals: list = field(default_factory=list)
    terminal_statuses: dict = field(default_factory=dict)
    thread_start_metadata: dict | None = None


class Host:
    def __init__(self, rpc, roles, safeguards, evidence_dir, *, clock=time.monotonic,
                 development_tools=None, development_dispatch=None, role_factory=None,
                 additional_tools=None, tool_dispatch=None, artifact_roots=(), wall_clock=time.time):
        if set(roles) != set(ROLES):
            raise RuntimeFailure('explicit_all_role_models_required')
        if any((spec.model, spec.effort) != APPROVED_MODELS[role] for role, spec in roles.items()):
            raise RuntimeFailure('unapproved_role_model')
        # Reviewer must have its own writable build/evidence scratch. Workspace-write
        # prevents writes elsewhere but does not impose a read-access boundary.
        review_roots = roles['reviewer'].writable_roots
        for role in ('lead', 'implementation', 'measurement', 'investigation'):
            if any(a.is_relative_to(b) or b.is_relative_to(a)
                   for a in review_roots for b in roles[role].writable_roots):
                raise RuntimeFailure('reviewer_write_scope_overlaps_execution')
        self.rpc, self.roles, self.safeguards, self.clock = rpc, roles, safeguards, clock
        self.role_factory = role_factory or self._allocate_spec
        if development_tools is not None and additional_tools is not None:
            raise RuntimeFailure('duplicate_tool_registry')
        if development_dispatch is not None and tool_dispatch is not None:
            raise RuntimeFailure('duplicate_tool_dispatch')
        self.development_tools = additional_tools or development_tools or {}
        self.development_dispatch = tool_dispatch or development_dispatch
        self.started = clock()
        self.wall_clock = wall_clock
        self.started_unix_seconds = wall_clock()
        self.artifact_roots = tuple(Path(p).resolve(strict=True) for p in artifact_roots)
        if any(not p.is_dir() or p == Path(p.anchor) for p in self.artifact_roots):
            raise RuntimeFailure('invalid_artifact_reference_root')
        self.evidence_dir = Path(evidence_dir)
        self.evidence_dir.mkdir(parents=True, exist_ok=False)
        self.agents, self.threads = {}, {}
        self.admission = asyncio.Lock()
        self.changed = asyncio.Event()
        self.sequence = 0
        self.tool_calls = {}
        self.failure = None
        self.sealed = False
        self.stopping = False
        self.shutdown = None
        self.rpc.on_event, self.rpc.on_request = self.on_event, self.on_request

    def _allocate_spec(self, agent_id, role, parent_agent):
        template = self.roles[role]
        roots = tuple(root / agent_id for root in template.writable_roots)
        containing = next(i for i, root in enumerate(template.writable_roots) if template.cwd.is_relative_to(root))
        cwd = roots[containing] / template.cwd.relative_to(template.writable_roots[containing])
        for root in roots:
            root.mkdir(parents=True, exist_ok=False)
        cwd.mkdir(parents=True, exist_ok=True)
        return replace(template, cwd=cwd, writable_roots=roots)

    def _validate_spec(self, agent, spec):
        if not isinstance(spec, RoleSpec) or (spec.model, spec.effort) != APPROVED_MODELS[agent.role]:
            raise RuntimeFailure('unapproved_role_model')
        if any(self.evidence_dir.resolve().is_relative_to(root) or root.is_relative_to(self.evidence_dir.resolve())
               for root in spec.writable_roots):
            raise RuntimeFailure('agent_write_scope_overlaps_runtime_evidence')
        permitted = self.roles[agent.role].writable_roots
        if any(not any(root.is_relative_to(base) for base in permitted) for root in spec.writable_roots):
            raise RuntimeFailure('role_factory_widened_write_scope')
        for other in self.agents.values():
            if other.agent_id == agent.agent_id or other.spec is None:
                continue
            if any(a.is_relative_to(b) or b.is_relative_to(a)
                   for a in spec.writable_roots for b in other.spec.writable_roots):
                raise RuntimeFailure('agent_write_scopes_overlap')
        return spec

    async def initialize(self):
        await self.rpc.request('initialize', initialize_params())
        await self.rpc.send({'method': 'initialized', 'params': {}})
        # Official account API; only the auth-mode discriminator is used.
        result = await self.rpc.request('account/read', {'refreshToken': False})
        if (result.get('account') or {}).get('type') != 'chatgpt':
            raise RuntimeFailure('chatgpt_auth_required')

    def _review_seconds(self):
        now = self.clock()
        return sum((end if end is not None else now) - start
                   for agent in self.agents.values() if agent.role == 'reviewer'
                   for start, end in agent.active_intervals)

    def _check_admission(self, role):
        if self.sealed or self.stopping or self.failure or self.rpc.failure:
            raise RuntimeFailure('runtime_not_accepting_work')

    def _task(self, task):
        if not isinstance(task, str) or not task.strip() or len(task) > 16000:
            raise RuntimeFailure('invalid_task')
        return task

    async def spawn(self, role, task, parent_id=None):
        if role not in ROLES or (role == 'lead' and (self.agents or parent_id is not None)):
            raise RuntimeFailure('invalid_role_or_lead')
        if role != 'lead' and (parent_id not in self.agents or self.agents[parent_id].role != 'lead'):
            raise RuntimeFailure('only_lead_can_delegate')
        task = self._task(task)
        # Reserve before awaiting: concurrent model tool calls cannot oversubscribe.
        async with self.admission:
            self._check_admission(role)
            self.sequence += 1
            agent = Agent('agent-' + str(self.sequence), role, parent_id, self.clock())
            self.agents[agent.agent_id] = agent
        try:
            spec = self._validate_spec(agent, self.role_factory(agent.agent_id, role, self.agents.get(parent_id)))
            agent.spec = spec
            params = start_thread_params(role, spec)
            params['dynamicTools'].extend(self.development_tools.get(role, []))
            response = await self.rpc.request('thread/start', params)
            agent.thread_start_metadata = thread_start_metadata(response)
            self._evidence(agent, {'type': 'threadStartMetadata', 'metadata': agent.thread_start_metadata})
            thread_id = validate_thread_response(response, spec)
            if thread_id in self.threads:
                raise RuntimeFailure('duplicate_thread_id')
            agent.thread_id = thread_id
            self.threads[thread_id] = agent
            await self._start_turn(agent, task)
            return self.status(agent.agent_id)
        except Exception:
            agent.state, agent.ended = 'startup_failed', self.clock()
            if agent.active_intervals and agent.active_intervals[-1][1] is None:
                agent.active_intervals[-1][1] = agent.ended
            agent.issues.add('startup_or_admission_failure')
            self.changed.set()
            raise

    async def _start_turn(self, agent, task):
        self._check_admission(agent.role)
        spec = agent.spec
        agent.state, agent.ended, agent.report = 'starting', None, None
        agent.report_diagnostics = None
        agent.pending_turn, agent.turn_id = True, None
        agent.started_at = self.clock()
        self._evidence(agent, {'type': 'ownerTask', 'text': task, 'source': 'owner_or_lead_delegation'})
        agent.active_intervals.append([agent.created if not agent.all_turns else agent.started_at, None])
        result = await self.rpc.request('turn/start', turn_params(agent.thread_id, task, spec))
        turn_id = result['turn']['id']
        self._bind_turn(agent, turn_id)
        agent.pending_turn = False
        # Notifications may complete a very short turn before its RPC response.
        if turn_id not in agent.completed_turns:
            agent.state = 'running'
        self.changed.set()

    def _bind_turn(self, agent, turn_id):
        if not isinstance(turn_id, str) or not turn_id:
            raise RuntimeFailure('invalid_turn_id')
        if agent.turn_id not in (None, turn_id):
            raise RuntimeFailure('unexpected_turn_id')
        agent.turn_id = turn_id
        if turn_id not in agent.all_turns:
            if not agent.pending_turn:
                raise RuntimeFailure('unrequested_turn')
            agent.all_turns.append(turn_id)

    async def message(self, agent_id, task):
        agent = self.agents[agent_id]
        self._task(task)
        # Reviewers can receive clarifications in their own independent context.
        # Initial review creation always uses a fresh thread, never lead history.
        if agent.role == 'lead':
            raise RuntimeFailure('message_requires_execution_worker')
        if agent.thread_id is None:
            raise RuntimeFailure('child_has_no_resumable_thread_spawn_replacement')
        async with self.admission:
            self._check_admission(agent.role)
            if agent.state in TERMINAL:
                await self._start_turn(agent, task)
            elif agent.state == 'running':
                self._evidence(agent, {'type': 'ownerMessage', 'text': task})
                await self.rpc.request('turn/steer', {'threadId': agent.thread_id,
                    'expectedTurnId': agent.turn_id,
                    'input': [{'type': 'text', 'text': task, 'text_elements': []}]})
            else:
                raise RuntimeFailure('agent_not_messageable')
        return self.status(agent_id)

    async def continue_lead(self, task):
        """Owner-supplied fixed continuation when workflow closure is still open.

        A final response ends a turn, not the scientific workflow. This keeps the
        same independent lead context and cumulative ledger across all turns.
        """
        task = self._task(task)
        lead = next((a for a in self.agents.values() if a.role == 'lead'), None)
        if lead is None or lead.state not in TERMINAL:
            raise RuntimeFailure('lead_not_idle')
        async with self.admission:
            self._check_admission('lead')
            await self._start_turn(lead, task)
        return self.status(lead.agent_id)

    async def cancel(self, agent_id):
        """Owner-only technical/emergency interruption, not the public lead tool."""
        agent = self.agents[agent_id]
        if agent.state in TERMINAL:
            return self.status(agent_id)
        if agent.turn_id is None:
            raise RuntimeFailure('agent_admission_in_progress')
        agent.state = 'cancelling'
        await self.rpc.request('turn/interrupt', {'threadId': agent.thread_id, 'turnId': agent.turn_id})
        return self.status(agent_id)  # Never claim success from the RPC ACK alone.

    async def request_wrap_up(self, agent_id):
        """Public cooperative abandonment: steer only; never start or interrupt."""
        agent = self.agents[agent_id]
        requested = acknowledged = False
        async with self.admission:
            self._check_admission(agent.role)
            if agent.role == 'lead':
                raise RuntimeFailure('wrap_up_requires_child_worker')
            if agent.state not in TERMINAL:
                if agent.state != 'running':
                    raise RuntimeFailure('agent_not_messageable')
                self._evidence(agent, {'type': 'ownerMessage', 'text': COOPERATIVE_WRAP_UP,
                                       'purpose': 'cooperative_wrap_up'})
                requested = True
                try:
                    await self.rpc.request('turn/steer', {'threadId': agent.thread_id,
                        'expectedTurnId': agent.turn_id,
                        'input': [{'type': 'text', 'text': COOPERATIVE_WRAP_UP, 'text_elements': []}]})
                    acknowledged = True
                except RuntimeFailure as exc:
                    # The turn may finish between validation and steer admission.
                    # Never retry by starting a fresh turn just to deliver a stop.
                    if not (str(exc) == 'rpc_request_failed' and agent.state in TERMINAL
                            and not self.rpc.failure):
                        raise
        return {**self.status(agent_id), 'wrap_up_request_sent': requested,
                'wrap_up_request_acknowledged': acknowledged,
                'terminal_event_observed': agent.state in TERMINAL,
                'interruption_requested': False}

    def status(self, agent_id):
        agent = self.agents[agent_id]
        return {'agent_id': agent.agent_id, 'role': agent.role, 'state': agent.state,
                'report': agent.report, 'report_diagnostics': agent.report_diagnostics,
                'issues': sorted(agent.issues),
                'usage_reported': agent.usage.total is not None}

    async def wait(self, agent_ids, seconds):
        if type(seconds) not in (int, float) or not 0 <= seconds <= 60:
            raise RuntimeFailure('invalid_wait_duration')
        finish = self.clock() + seconds
        while not any(self.agents[i].state in TERMINAL for i in agent_ids):
            self.changed.clear()
            remaining = finish - self.clock()
            if remaining <= 0:
                break
            try:
                await asyncio.wait_for(self.changed.wait(), remaining)
            except asyncio.TimeoutError:
                break
        return [self.status(i) for i in agent_ids]

    async def on_request(self, params):
        # A retransmitted call must never launch a second agent or measurement.
        call_id = params.get('callId')
        if not isinstance(call_id, str) or not call_id:
            return {'success': False, 'contentItems': [{'type': 'inputText', 'text': 'missing_call_id'}]}
        key = (params.get('threadId'), call_id)
        fingerprint = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
        previous = self.tool_calls.get(key)
        if previous:
            if previous[0] != fingerprint:
                self.failure = 'dynamic_call_id_reused_with_different_payload'
                return {'success': False, 'contentItems': [{'type': 'inputText', 'text': self.failure}]}
            return await asyncio.shield(previous[1])
        task = asyncio.create_task(self._dispatch_request(params))
        self.tool_calls[key] = (fingerprint, task)
        return await asyncio.shield(task)

    async def _dispatch_request(self, params):
        argument_issues = []
        try:
            lead = self.threads.get(params.get('threadId'))
            if (lead is None or params.get('turnId') != lead.turn_id
                    or lead.state not in ('running', 'starting') or self.stopping):
                raise RuntimeFailure('unauthorized_tool_caller')
            if params.get('namespace') is not None:
                raise RuntimeFailure('unsupported_dynamic_namespace')
            tool_name = params.get('tool', '')
            if tool_name.startswith(('study_dev_', 'study_owner_', 'study_workspace_')):
                if self.development_dispatch is None or tool_name not in {t['name'] for t in self.development_tools.get(lead.role, [])}:
                    raise RuntimeFailure('unauthorized_development_tool')
                result = await self.development_dispatch(lead, tool_name, params.get('arguments'))
                return {'success': True, 'contentItems': [{'type': 'inputText', 'text': json.dumps(result)}]}
            if lead.role != 'lead':
                raise RuntimeFailure('unauthorized_delegation_caller')
            if params.get('namespace') is not None:
                raise RuntimeFailure('unsupported_dynamic_namespace')
            args, tool = params.get('arguments'), params.get('tool')
            argument_issues = dynamic_argument_issues(tool, args)
            if argument_issues:
                raise RuntimeFailure('invalid_dynamic_arguments')
            ids = args.get('agent_ids', [args.get('agent_id')]) if tool != 'study_spawn' else []
            if not isinstance(ids, list) or (tool != 'study_spawn' and not 1 <= len(ids) <= 20):
                raise RuntimeFailure('invalid_agent_ids')
            if any(i not in self.agents or self.agents[i].parent_id != lead.agent_id for i in ids):
                raise RuntimeFailure('unowned_agent')
            if tool == 'study_spawn':
                if args['role'] not in CHILD_ROLES:
                    raise RuntimeFailure('invalid_child_role')
                result = await self.spawn(args['role'], args['task'], lead.agent_id)
            elif tool == 'study_status':
                result = [self.status(i) for i in ids]
            elif tool == 'study_wait':
                result = await self.wait(ids, args['timeout_seconds'])
            elif tool == 'study_message':
                result = await self.message(args['agent_id'], args['task'])
            else:
                result = await self.request_wrap_up(args['agent_id'])
            return {'success': True, 'contentItems': [{'type': 'inputText', 'text': json.dumps(result)}]}
        except (RuntimeFailure, KeyError, TypeError) as exc:
            category = str(exc) if isinstance(exc, RuntimeFailure) else 'invalid_dynamic_arguments'
            spec = next((t for t in dynamic_tools() if t['name'] == params.get('tool')), None)
            caller = self.threads.get(params.get('threadId'))
            children = ([{'agent_id': a.agent_id, 'state': a.state,
                          'has_resumable_thread': a.thread_id is not None}
                         for a in self.agents.values() if a.parent_id == caller.agent_id]
                        if caller is not None and caller.role == 'lead' else [])
            error = {'error': category, 'argument_issues': argument_issues,
                     'tool': spec['name'] if spec else None,
                     'expected_arguments': spec['inputSchema'] if spec else None,
                     'owned_child_agents': children,
                     'repair': ('Correct arguments using the exact schema; use an owned child agent_id. '
                                'Messages require a running or terminal child with a thread. '
                                'Wait for starting/cancelling children; spawn a replacement for a child without a thread. '
                                'Cooperative cancel is a terminal no-op and its acknowledgment is not completion.')}
            return {'success': False, 'contentItems': [{'type': 'inputText', 'text': json.dumps(error)}]}

    def _evidence(self, agent, item):
        # Ordinary commands/output/patches are deliberately retained separately.
        # Whitelisted projection excludes extra fields, private reasoning, and raw events.
        path = self.evidence_dir / (agent.agent_id + '.jsonl')
        with path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'thread_id': agent.thread_id, 'turn_id': agent.turn_id,
                                     'item': item}) + '\n')

    def _report(self, agent, text):
        """Keep ordinary findings; a report reference never grants file access.

        The advertised four-field schema is the complete format contract. IDs,
        hashes and prose are valid artifact strings. Path classification below
        is lexical only, never resolution, opening, existence or evidence proof.
        """
        diagnostics = {'schema_valid': False, 'parse_issues': [], 'artifact_references': [],
                       'evidence_authority': 'unverified_report_only',
                       'ordinary_report_evidence': str(self.evidence_dir / (agent.agent_id + '.jsonl'))}
        agent.report_diagnostics = diagnostics
        agent.report = None
        issues = diagnostics['parse_issues']
        try:
            if not isinstance(text, str):
                issues.append('report_text_not_string')
                raise ValueError
            report = json.loads(text)
            if not isinstance(report, dict):
                issues.append('report_not_object')
                raise ValueError
            if set(report) != {'summary', 'artifacts', 'checks', 'limitations'}:
                issues.append('report_fields_mismatch')
            summary = report.get('summary')
            if not isinstance(summary, str):
                issues.append('summary_not_string')
            elif len(summary) > 3000:
                issues.append('summary_exceeds_advertised_3000_characters')
            projected = {'summary': summary if isinstance(summary, str) else None}
            for key in ('artifacts', 'checks', 'limitations'):
                value = report.get(key)
                if not isinstance(value, list):
                    issues.append(key + '_not_array')
                    projected[key] = []
                else:
                    if len(value) > 20:
                        issues.append(key + '_exceeds_advertised_20_items')
                    if any(not isinstance(x, str) for x in value):
                        issues.append(key + '_contains_non_string')
                    projected[key] = [x for x in value if isinstance(x, str)]
            diagnostics['schema_valid'] = not issues
            # Keep the complete ordinary known-field payload in evidence. For a
            # schema violation only, return a bounded projection with explicit
            # diagnostics, retaining any useful summary instead of dropping it.
            agent.report = {'summary': projected['summary'][:3000] if projected['summary'] is not None else '',
                            **{key: projected[key][:20] for key in ('artifacts', 'checks', 'limitations')}}
            allowed = tuple(p for spec in self.roles.values() for p in spec.writable_roots) + self.artifact_roots
            for index, value in enumerate(agent.report['artifacts']):
                row = {'index': index, 'kind': 'id_or_description', 'verified': False,
                       'dereferenced': False}
                if value.startswith('/'):
                    row['kind'] = 'absolute_path_text'
                    path = Path(value)
                    row['lexically_within_declared_roots'] = (
                        '\x00' not in value and '..' not in path.parts
                        and any(path.is_relative_to(root) for root in allowed))
                    row['diagnostic'] = 'path_unverified_even_if_lexically_in_scope'
                else:
                    row['diagnostic'] = 'inert_reference_resolve_with_owner_evidence_tools'
                diagnostics['artifact_references'].append(row)
            self._evidence(agent, {'type': 'agentReport', 'report': projected,
                                   'diagnostics': diagnostics})
        except (ValueError, TypeError):
            if not issues:
                issues.append('invalid_json')
            if isinstance(text, str):
                agent.report = {'summary': text[:3000], 'artifacts': [], 'checks': [], 'limitations': []}
                self._evidence(agent, {'type': 'agentReportUnparsedText', 'text': text,
                                       'diagnostics': diagnostics})
            self._evidence(agent, {'type': 'agentReportParseDiagnostics', 'diagnostics': diagnostics})
        if issues:
            agent.issues.add('invalid_compact_report')
        else:
            agent.issues.discard('invalid_compact_report')

    def on_event(self, msg):
        method, params = msg.get('method'), msg.get('params') or {}
        # Drop content before any recording. No reasoning hashes, text, summaries,
        # rawResponse events, auth fields, generic error bodies, or rollouts saved.
        if method.startswith('item/reasoning/') or method.startswith('rawResponse'):
            return
        thread_id = params.get('threadId')
        if self.sealed:
            agent = self.threads.get(thread_id)
            if agent is not None:
                if method == 'thread/closed':
                    return
                if method == 'thread/status/changed' and (params.get('status') or {}).get('type') in ('idle', 'notLoaded'):
                    return
                turn = params.get('turn') or {}
                if (method == 'turn/completed' and turn.get('id') in agent.terminal_statuses
                        and agent.terminal_statuses[turn['id']] == turn.get('status')
                        and params.get('turnId') in (None, turn['id'])):
                    return
                if method == 'thread/tokenUsage/updated':
                    # Preserve all late numeric observations before classifying
                    # their effect. Exact duplicates/context bookkeeping add no
                    # spend; genuinely new usage invalidates the sealed result.
                    before, issues = agent.usage.total, set(agent.usage.issues)
                    agent.usage.add(params.get('turnId'), params.get('tokenUsage') or {},
                                    observed_unix_seconds=self.wall_clock(),
                                    elapsed_from_host_start_seconds=self.clock() - self.started)
                    if (params.get('turnId') in agent.terminal_statuses
                            and agent.usage.total == before and agent.usage.issues == issues):
                        return
                    self.failure = 'late_usage_after_seal'
                    self.changed.set()
                    return
            # Routine global notifications without a study thread are not model
            # activity. Native child creation is a relevant exception.
            if thread_id is None and method != 'thread/started':
                return
            self.failure = 'late_event_after_seal'
            self.changed.set()
            return  # Keep the reader running so shutdown drains subsequent usage.
        if method == 'thread/started':
            # Created threads are registered by their non-inference start response.
            # Native children are forbidden; they have a real parentThreadId.
            if (params.get('thread') or {}).get('parentThreadId'):
                self.failure = 'unregistered_native_child'
            return
        if thread_id is None:
            return
        agent = self.threads.get(thread_id)
        if agent is None and method == 'thread/status/changed':
            return  # A non-inference lifecycle event can precede thread/start response.
        if agent is None:
            self.failure = 'event_from_unregistered_thread'
            raise RuntimeFailure(self.failure)
        turn_id = params.get('turnId') or (params.get('turn') or {}).get('id')
        if turn_id:
            if turn_id in agent.completed_turns and turn_id != agent.turn_id:
                if method == 'thread/tokenUsage/updated':
                    agent.issues.add('late_usage_from_previous_turn')
                    agent.usage.issues.add('late_usage_from_previous_turn')
                return
            self._bind_turn(agent, turn_id)
        if method == 'thread/tokenUsage/updated':
            agent.usage.add(turn_id, params.get('tokenUsage') or {},
                            observed_unix_seconds=self.wall_clock(),
                            elapsed_from_host_start_seconds=self.clock() - self.started)
        elif method in ('item/started', 'item/completed'):
            item = params.get('item') or {}
            if item.get('type') in ('collabAgentToolCall', 'subAgentActivity'):
                self.failure = 'uncontrolled_native_delegation'
            elif item.get('type') in ('mcpToolCall', 'webSearch', 'imageGeneration'):
                self.failure = 'uncontrolled_external_tool'
            elif item.get('type') == 'contextCompaction':
                # A lifecycle marker alone proves neither lost nor preserved usage.
                agent.issues.add('compaction_observed')
            elif method == 'item/completed':
                evidence = public_item(item)
                if evidence:
                    self._evidence(agent, evidence)
                elif item.get('type') == 'agentMessage' and item.get('phase') in ('final_answer', None):
                    self._report(agent, item.get('text'))
        elif method == 'turn/completed':
            status = (params.get('turn') or {}).get('status')
            if status not in ('completed', 'failed', 'interrupted'):
                raise RuntimeFailure('invalid_terminal_status')
            agent.state, agent.ended = status, self.clock()
            agent.terminal_statuses[turn_id] = status
            if agent.active_intervals and agent.active_intervals[-1][1] is None:
                agent.active_intervals[-1][1] = agent.ended
            if turn_id not in agent.completed_turns:
                agent.completed_turns.append(turn_id)
        elif method == 'model/rerouted':
            agent.issues.add('model_rerouted')
            self.failure = 'model_rerouted'
        self.changed.set()

    async def enforce_safeguards(self):
        """Stop only for infrastructure/integrity failures, never token/time spend."""
        if self.failure or self.rpc.failure:
            await self.stop(self.failure or self.rpc.failure)

    async def stop(self, reason='owner_stop'):
        """Revoke new work, interrupt active turns, and cancel outstanding handlers.

        Owner development authorities must check host.stopping so in-process native
        operations are cancelled through their own backend cleanup as well.
        """
        self.stopping = True
        if self.shutdown is None:
            self.shutdown = {'reason': reason, 'interrupt_grace_seconds': self.safeguards.shutdown_grace_seconds,
                             'observation_scope': 'interrupt grace before transport close; final states and usage exported after drain',
                             'interrupt_acknowledged_agents': [], 'interrupt_failed_agents': [],
                             'terminal_events_observed': False, 'incomplete_agents': []}
        # Cancel host tools immediately so no queued work can continue spending.
        # The event pump and server-response handlers stay alive during the grace.
        handlers = [task for _, task in self.tool_calls.values() if not task.done()]
        for task in handlers:
            task.cancel()
        pending_interrupts = {}
        attempted = set()
        deadline = asyncio.get_running_loop().time() + self.safeguards.shutdown_grace_seconds
        try:
            while True:
                for agent in list(self.agents.values()):
                    if agent.state not in TERMINAL and agent.turn_id and agent.agent_id not in attempted:
                        attempted.add(agent.agent_id)
                        pending_interrupts[asyncio.create_task(self.cancel(agent.agent_id))] = agent.agent_id
                for task, agent_id in list(pending_interrupts.items()):
                    if task.done():
                        del pending_interrupts[task]
                        key = 'interrupt_failed_agents' if task.cancelled() or task.exception() else 'interrupt_acknowledged_agents'
                        self.shutdown[key].append(agent_id)
                active = [a.agent_id for a in self.agents.values() if a.state not in TERMINAL]
                remaining = deadline - asyncio.get_running_loop().time()
                if not active or remaining <= 0 or self.rpc.failure:
                    break
                self.changed.clear()
                try:
                    await asyncio.wait_for(self.changed.wait(), min(remaining, .05))
                except asyncio.TimeoutError:
                    pass
        finally:
            for task in pending_interrupts:
                task.cancel()
            await asyncio.gather(*pending_interrupts, *handlers, return_exceptions=True)
            self.shutdown['incomplete_agents'] = [a.agent_id for a in self.agents.values() if a.state not in TERMINAL]
            self.shutdown['terminal_events_observed'] = not self.shutdown['incomplete_agents']
        self.changed.set()
        return dict(self.shutdown)

    def export(self):
        agents = []
        for agent in self.agents.values():
            agents.append({**self.status(agent.agent_id), 'thread_id': agent.thread_id,
                           'parent_agent_id': agent.parent_id, 'model': self.roles[agent.role].model,
                           'effort': self.roles[agent.role].effort,
                           'requested_service_tier': 'default',
                           'provider_billing_service_tier': None,
                           'cwd': str(agent.spec.cwd) if agent.spec else None,
                           'writable_roots': [str(p) for p in agent.spec.writable_roots] if agent.spec else [],
                           'terminal_turn_statuses': dict(agent.terminal_statuses),
                           'thread_start_metadata': agent.thread_start_metadata,
                           'token_usage': agent.usage.export(agent.all_turns,
                               agent.state == 'completed' and all(agent.terminal_statuses.get(t) == 'completed'
                                                                  for t in agent.all_turns))})
        return {'schema_version': 2, 'delegation': 'host-managed official ephemeral threads; not native collab ancestry',
                'failure': self.failure or self.rpc.failure, 'sealed': self.sealed,
                'campaign_wall_seconds': self.clock() - self.started,
                'started_unix_seconds': self.started_unix_seconds,
                'usage_time_provenance': 'Notification observation time; not provider execution or billing time.',
                'artifact_reference_roots': [str(p) for p in self.artifact_roots],
                'reviewer_cumulative_seconds': self._review_seconds(),
                'reviewer_time_includes_admission_queue_and_execution': True,
                'agents': agents,
                'per_role_tokens': {role: sum_totals(a.usage.total for a in self.agents.values() if a.role == role) for role in ROLES},
                'known_thread_totals': sum_totals(a.usage.total for a in self.agents.values()),
                'total_tokens': (dict.fromkeys(('inputTokens', 'cachedInputTokens', 'cacheWriteInputTokens', 'outputTokens', 'reasoningOutputTokens', 'totalTokens'), None)
                                 if self.failure in ('uncontrolled_native_delegation', 'unregistered_native_child', 'event_from_unregistered_thread', 'uncontrolled_external_tool')
                                 else sum_totals(a.usage.total for a in self.agents.values())),
                'unregistered_activity_usage': None,
                'shutdown': self.shutdown,
                'accounting_complete': bool(agents and all(a['token_usage']['observed_accounting_complete'] for a in agents)
                                            and not self.failure and not self.rpc.failure),
                'raw_reasoning_retained': False,
                'budgets': {'campaign_wall': None, 'reviewer_wall': None, 'tokens': None},
                'completion_rule': 'All admitted turns terminal; scientific workflow closure remains the owner controller responsibility.'}

    def seal(self):
        if any(a.state not in TERMINAL for a in self.agents.values()):
            raise RuntimeFailure('cannot_seal_active_agents')
        self.sealed = True
        return self.export()


async def wait_for_completion(host):
    """Task-based completion; transport remains open for owner-controlled phases."""
    while True:
        await host.enforce_safeguards()
        if host.failure or host.rpc.failure:
            raise RuntimeFailure(host.failure or host.rpc.failure)
        if host.agents and all(a.state in TERMINAL for a in host.agents.values()):
            return host.export()
        host.changed.clear()
        try:
            await asyncio.wait_for(host.changed.wait(), .1)
        except asyncio.TimeoutError:
            pass
