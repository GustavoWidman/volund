"""Official Codex 0.159.3 payload builders. This module never starts a process."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import re

CLI_VERSION = '0.159.3'
ROLES = ('lead', 'measurement', 'implementation', 'investigation', 'reviewer')
CHILD_ROLES = ROLES[1:]
REASONING_NOTIFICATIONS = ('item/reasoning/textDelta', 'item/reasoning/summaryTextDelta',
                           'item/reasoning/summaryPartAdded')


class RuntimeFailure(Exception):
    """Fixed safe category, never an upstream message or exception body."""


def positive(value, label):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise RuntimeFailure('invalid_' + label)
    return value


@dataclass(frozen=True)
class RoleSpec:
    model: str
    effort: str
    cwd: Path
    writable_roots: tuple[Path, ...]
    instructions: str

    def __post_init__(self):
        if not self.model or self.effort not in ('low', 'medium', 'high', 'xhigh', 'max', 'ultra'):
            raise RuntimeFailure('invalid_model_spec')
        cwd = Path(self.cwd).resolve(strict=True)
        roots = tuple(Path(p).resolve(strict=True) for p in self.writable_roots)
        if not cwd.is_dir() or not roots or any(not p.is_dir() or p == Path(p.anchor) for p in roots):
            raise RuntimeFailure('invalid_workspace')
        if not any(cwd.is_relative_to(p) for p in roots):
            raise RuntimeFailure('cwd_outside_write_roots')
        object.__setattr__(self, 'cwd', cwd)
        object.__setattr__(self, 'writable_roots', roots)


@dataclass(frozen=True)
class Safeguards:
    # An RPC admission timeout is an infrastructure safeguard, never an agent
    # execution, reviewer allocation, campaign duration, or token budget.
    rpc_admission_timeout_seconds: float = 120.0
    shutdown_grace_seconds: float = 5.0

    def __post_init__(self):
        positive(self.rpc_admission_timeout_seconds, 'rpc_admission_timeout')
        positive(self.shutdown_grace_seconds, 'shutdown_grace')


APPROVED_MODELS = {
    'lead': ('gpt-6.1-sol', 'high'),
    'reviewer': ('gpt-6.1-sol', 'high'),
    'measurement': ('gpt-6-luna', 'xhigh'),
    'implementation': ('gpt-6-luna', 'xhigh'),
    'investigation': ('gpt-6-luna', 'xhigh'),
}


REPORT_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'properties': {
        'summary': {'type': 'string', 'maxLength': 3000},
        'artifacts': {'type': 'array', 'maxItems': 20, 'items': {'type': 'string'},
                      'description': 'Up to 20 inert artifact references: evidence IDs, hashes, paths, or short descriptions. References are unverified; owner evidence tools establish validity.'},
        'checks': {'type': 'array', 'maxItems': 20, 'items': {'type': 'string'}},
        'limitations': {'type': 'array', 'maxItems': 20, 'items': {'type': 'string'}},
    }, 'required': ['summary', 'artifacts', 'checks', 'limitations'],
}


def _tool(name, description, properties, required):
    return {'type': 'function', 'name': name, 'description': description,
            'inputSchema': {'type': 'object', 'additionalProperties': False,
                            'properties': properties, 'required': required}}


def dynamic_tools():
    """No model, effort, context-fork, arbitrary roots, or shell arguments exposed."""
    agent = {'type': 'string', 'minLength': 1,
             'description': 'agent_id returned by study_spawn for a direct child of this lead; not a thread ID or the lead ID'}
    agents = {'type': 'array', 'items': agent, 'minItems': 1, 'maxItems': 20}
    task = {'type': 'string', 'minLength': 1, 'maxLength': 16000, 'pattern': r'\S',
            'description': 'A nonblank task, at most 16000 characters'}
    return [
        _tool('study_spawn', 'Delegate a task to a real independent agent. Returns after admission; execution continues asynchronously.',
              {'role': {'type': 'string', 'enum': list(CHILD_ROLES)}, 'task': task}, ['role', 'task']),
        _tool('study_status', 'Get concise current states, completed reports, and artifact pointers.',
              {'agent_ids': agents}, ['agent_ids']),
        _tool('study_wait', 'Wait for any named agent to finish, without blocking other agents or event collection.',
              {'agent_ids': agents, 'timeout_seconds': {'type': 'number', 'minimum': 0, 'maximum': 60}},
              ['agent_ids', 'timeout_seconds']),
        _tool('study_message', 'Steer a running child, or start another turn in an idle child\'s existing context. Reviewer clarifications use that reviewer\'s independent context.',
              {'agent_id': agent, 'task': task}, ['agent_id', 'task']),
        _tool('study_cancel', 'Ask a worker to wrap up cooperatively, preserve evidence, and report abandoned or inconclusive findings. Acknowledgment is not completion; this does not interrupt the turn or restart a terminal worker.',
              {'agent_id': agent}, ['agent_id']),
    ]


def dynamic_argument_issues(name, arguments):
    """Validate the same small JSON Schema advertised to the model, no coercion."""
    spec = next((tool for tool in dynamic_tools() if tool['name'] == name), None)
    if spec is None:
        return ['unknown_tool']
    issues = []

    def check(value, schema, field):
        kind = schema.get('type')
        valid = {'object': isinstance(value, dict), 'array': isinstance(value, list),
                 'string': isinstance(value, str),
                 'number': type(value) is int or (type(value) is float and math.isfinite(value))}.get(kind, True)
        if not valid:
            issues.append(field + ':type_' + str(kind))
            return
        if 'enum' in schema and value not in schema['enum']:
            issues.append(field + ':enum')
        if kind == 'object':
            if set(value) - set(schema['properties']):
                issues.append(field + ':unknown_fields')
            for key in schema['required']:
                if key not in value:
                    issues.append(field + '.' + key + ':required')
            for key, child in schema['properties'].items():
                if key in value:
                    check(value[key], child, field + '.' + key)
        elif kind in ('array', 'string'):
            minimum = schema.get('minItems' if kind == 'array' else 'minLength', 0)
            maximum = schema.get('maxItems' if kind == 'array' else 'maxLength', float('inf'))
            if not minimum <= len(value) <= maximum:
                issues.append(field + ':length')
            if kind == 'array':
                for index, child in enumerate(value):
                    check(child, schema['items'], field + '[' + str(index) + ']')
            elif 'pattern' in schema and re.search(schema['pattern'], value) is None:
                issues.append(field + ':nonblank_required')
        elif kind == 'number' and not schema.get('minimum', float('-inf')) <= value <= schema.get('maximum', float('inf')):
            issues.append(field + ':range')

    check(arguments, spec['inputSchema'], 'arguments')
    return issues


def initialize_params():
    return {'clientInfo': {'name': 'optimization_study_v3', 'title': 'Optimization study v3', 'version': '3'},
            'capabilities': {'experimentalApi': True, 'requestAttestation': False,
                             'optOutNotificationMethods': list(REASONING_NOTIFICATIONS)}}


def sandbox(spec):
    return {'type': 'workspaceWrite', 'writableRoots': [str(p) for p in spec.writable_roots],
            'networkAccess': False, 'excludeTmpdirEnvVar': True, 'excludeSlashTmp': True}


def start_thread_params(role, spec):
    if role not in ROLES:
        raise RuntimeFailure('unknown_role')
    config = {'model_reasoning_effort': spec.effort, 'model_reasoning_summary': 'none',
              'history.persistence': 'none', 'hide_agent_reasoning': True,
              'show_raw_agent_reasoning': False, 'web_search': 'disabled',
              'agents.enabled': False, 'features.multi_agent': False,
              'features.multi_agent_v2': False, 'features.apps': False,
              'features.shell_tool': False,
              'sandbox_workspace_write': {'writable_roots': [str(p) for p in spec.writable_roots],
                'network_access': False, 'exclude_tmpdir_env_var': True, 'exclude_slash_tmp': True}}
    return {'model': spec.model, 'modelProvider': 'openai', 'allowProviderModelFallback': False,
            'serviceTier': 'default', 'cwd': str(spec.cwd),
            'runtimeWorkspaceRoots': [str(p) for p in spec.writable_roots],
            'approvalPolicy': 'never', 'sandbox': 'workspace-write', 'ephemeral': True,
            'experimentalRawEvents': False, 'config': config,
            'developerInstructions': spec.instructions,
            'dynamicTools': dynamic_tools() if role == 'lead' else []}


def turn_params(thread_id, task, spec):
    return {'threadId': thread_id, 'input': [{'type': 'text', 'text': task, 'text_elements': []}],
            'cwd': str(spec.cwd), 'runtimeWorkspaceRoots': [str(p) for p in spec.writable_roots],
            'model': spec.model, 'effort': spec.effort, 'summary': 'none',
            'serviceTierForTurn': 'default', 'approvalPolicy': 'never',
            'sandboxPolicy': sandbox(spec), 'outputSchema': REPORT_SCHEMA}


def thread_start_metadata(response):
    """Allowlisted non-content metadata, retained even when validation rejects it.

    Never copy the thread object, response body, account object, instructions,
    preview, history, or arbitrary sandbox extensions into evidence.
    """
    def safe_text(value):
        return value if (isinstance(value, str) and len(value) <= 4096
                         and not any(ord(char) < 32 for char in value)) else None

    thread = response.get('thread')
    thread = thread if isinstance(thread, dict) else {}
    result = {key: safe_text(response.get(key))
              for key in ('model', 'reasoningEffort', 'modelProvider', 'cwd')}
    result['thread'] = {key: safe_text(thread.get(key)) for key in ('id', 'cliVersion')}
    approval = response.get('approvalPolicy')
    result['approvalPolicy'] = approval if approval in ('never', 'untrusted', 'on-request') else None
    if isinstance(approval, dict) and isinstance(approval.get('granular'), dict):
        result['approvalPolicy'] = {'granular': {
            key: value for key, value in approval['granular'].items()
            if key in ('mcp_elicitations', 'request_permissions', 'rules', 'sandbox_approval', 'skill_approval')
            and type(value) is bool}}
    policy = response.get('sandbox')
    result['sandbox'] = None
    if isinstance(policy, dict):
        result['sandbox'] = {'type': safe_text(policy.get('type'))}
        for key in ('networkAccess', 'excludeTmpdirEnvVar', 'excludeSlashTmp'):
            if key in policy:
                value = policy[key]
                result['sandbox'][key] = value if type(value) is bool or value in ('restricted', 'enabled') else None
        if 'writableRoots' in policy:
            roots = policy['writableRoots']
            result['sandbox']['writableRoots'] = ([safe_text(p) for p in roots]
                                                   if isinstance(roots, list) else None)
    return result


def validate_thread_response(response, spec):
    thread = response.get('thread') or {}
    if (response.get('model'), response.get('reasoningEffort'), response.get('modelProvider')) != (spec.model, spec.effort, 'openai'):
        raise RuntimeFailure('model_or_effort_mismatch')
    if thread.get('cliVersion') != CLI_VERSION or thread.get('ephemeral') is not True:
        raise RuntimeFailure('cli_or_ephemeral_mismatch')
    if thread.get('parentThreadId') is not None or thread.get('forkedFromId') is not None:
        raise RuntimeFailure('fresh_independent_thread_required')
    if response.get('cwd') != str(spec.cwd):
        raise RuntimeFailure('cwd_mismatch')
    validate_sandbox_response(response.get('sandbox'), response.get('approvalPolicy'), spec)
    return thread['id']


def validate_sandbox_response(policy, approval, spec):
    """Compare effective roots without mistaking implicit writable cwd for loss.

    Codex rust-v0.159.3 protocol.rs get_writable_roots_with_cwd always adds cwd;
    permissions.rs legacy projection omits cwd from additional writable_roots.
    Only that redundancy, root order, and duplicates are normalized here. No
    containment-based relaxation, unknown fields, path alias, or flag coercion.
    """
    expected = sandbox(spec)
    if (approval != 'never' or not isinstance(policy, dict) or set(policy) != set(expected)
            or policy.get('type') != 'workspaceWrite'
            or policy.get('networkAccess') is not False
            or policy.get('excludeTmpdirEnvVar') is not True
            or policy.get('excludeSlashTmp') is not True):
        raise RuntimeFailure('sandbox_or_approval_mismatch')
    roots = policy.get('writableRoots')
    if not isinstance(roots, list) or any(not isinstance(p, str) for p in roots):
        raise RuntimeFailure('sandbox_or_approval_mismatch')
    # RoleSpec already resolves owner-approved paths to existing canonical dirs.
    # Compare their exact strings; never dereference untrusted response paths.
    expected_roots = {str(spec.cwd), *(str(p) for p in spec.writable_roots)}
    if {str(spec.cwd), *roots} != expected_roots:
        raise RuntimeFailure('sandbox_or_approval_mismatch')
