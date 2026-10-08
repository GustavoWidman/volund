"""Bind inspected v3 setup evidence. Does not authorize launch or call a model."""
from __future__ import annotations
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from development.core import IntegrityError, file_hash, write_new
from owner.readiness import code_manifest, check_manifest, native_configuration
from development.native_backend import NativeBackend


def load(name):
    return json.loads((ROOT / name).read_text())


def evidence(name, scope=None):
    result = {'path': name, 'sha256': file_hash(ROOT / name)}
    if scope:
        result['scope'] = scope
    return result


def passed(name, *, checks=True):
    row = load(name)
    declared = row.get('checks', {})
    valid = (all(value is True for value in declared.values()) if isinstance(declared, dict)
             else isinstance(declared, list) and all(value.get('pass') is True for value in declared))
    if row.get('status') != 'pass' or (checks and not valid):
        raise IntegrityError('setup evidence is not passing: ' + name)
    return row


def main():
    if load('state/launch/status.json')['status'] != 'awaiting_exact_owner_readiness_no_inference':
        raise IntegrityError('readiness requires parked launcher')
    preflight = passed('state/launch/preflight.json')
    if preflight.get('real_runtime_observed') is not True or len(preflight['checks']) != 20:
        raise IntegrityError('actual full v3 preflight required')
    check_manifest(ROOT, preflight['execution_manifest'])
    if code_manifest(ROOT) != preflight['execution_manifest']:
        raise IntegrityError('execution inventory changed since actual preflight')
    native = passed('setup/evaluator-controls-01/setup-controls.json')
    guards = passed('setup/additional-guard-controls-01/controls.json')
    native_run = passed('setup/fresh-native-readiness-01/result.json')
    bridge = passed('setup/native-measurement-bridge-01/result.json')
    regressions = passed('setup/readiness-regressions-01/result.json', checks=False)
    if len(regressions['suites']) != 6 or any(x['status'] != 'pass' or not x['tests_reported'] for x in regressions['suites']):
        raise IntegrityError('current regression suite incomplete')
    lane = bridge['coordinator']
    if (bridge.get('model_calls') != 0 or lane.get('quarantine') is not None
            or lane.get('active') is not None or lane.get('queued')
            or bridge.get('workspace_cleanup', {}).get('drained') is not True):
        raise IntegrityError('native recovery bridge not clean')
    probe = passed('setup/workspace-router-probe-02/result.json')
    configurations = {}
    artifact_files = {}
    def bind_recorded(path, expected):
        path = Path(path)
        path = path if path.is_absolute() else ROOT / path
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT) or file_hash(path) != expected:
            raise IntegrityError('recorded setup binding changed: ' + str(path))
        artifact_files[str(path.resolve())] = expected
    for path, row, key in [
            ('analysis/validate_native_readiness.py', native_run, 'script_sha256'),
            ('tests/evaluation/validate_guard_controls.py', guards, 'source_sha256'),
            ('tests/audit/validate_native_measurement_bridge.py', bridge, 'script_sha256'),
            ('analysis/run_readiness_regressions.py', regressions, 'script_sha256')]:
        bind_recorded(path, row[key])
    for path, expected in probe['tested_source_sha256'].items():
        bind_recorded(path, expected)
    for row in regressions['suites'] + native_run['steps']:
        if 'log' in row:
            bind_recorded(row['log'], row['log_sha256'])
    bind_recorded(bridge['final_report'], bridge['final_report_sha256'])
    for key in ('development_series', 'final_series'):
        series = bridge[key]
        bind_recorded(Path(series['selected_attempt']) / 'result.json', series['selected_result_sha256'])
    for name in ('transfer', 'shift'):
        relative = 'setup/final-evaluator-config-' + name + '.json'
        config = native_configuration(ROOT / relative)
        NativeBackend(config).verify()
        if config.paired_blocks != 30 or config.benchmark_suite != name:
            raise IntegrityError('final configuration mismatch')
        configurations[name] = evidence(relative)
        artifact_files.update(config.pinned_files)
    # Pin only task-owned source and numeric validation evidence, never auth,
    # unrelated repository contents, private model reasoning, or runtime state.
    extra = ['protocol/PROTOCOL.md', 'evaluation/PLAN.md', 'evaluation/run.py',
             'evaluation/prepare.py', 'evaluation/validate_setup.py',
             'analysis/INDEPENDENT-SCHEDULER-REVIEW.md',
             'analysis/INDEPENDENT-CLI-ROUTER-VERIFICATION.json',
             'analysis/INDEPENDENT-LAUNCH-PROTOCOL-REVIEW.md',
             'analysis/validate_native_readiness.py', 'analysis/run_readiness_regressions.py',
             'analysis/record_verified_readiness.py', 'analysis/reprice_observed_usage.py',
             'analysis/preflight-observed-usage-reanalysis.json',
             'setup/final-fixtures-preparation/preparation.json',
             'setup/final-fixtures-preparation/definitions.json',
             'setup/fresh-native-readiness-01/result.json',
             'setup/evaluator-controls-01/setup-controls.json',
             'setup/additional-guard-controls-01/controls.json',
             'setup/native-measurement-bridge-01/result.json',
             'setup/readiness-regressions-01/result.json',
             'setup/workspace-cli-probe-01/result.json',
             'setup/workspace-router-probe-02/result.json']
    extra += [str(p.relative_to(ROOT)) for p in sorted((ROOT / 'tests').rglob('*.py'))]
    extra += [row['log'] for row in regressions['suites']]
    for name in extra:
        path = ROOT / name
        artifact_files[str(path)] = file_hash(path)
    timestamp = datetime.now(timezone.utc).isoformat()
    final = {'schema_version': 3, 'status': 'ready', 'recorded_utc': timestamp,
             'scope': 'Current v3 final implementation, real native controls, and isolated recovery-route setup; not optimized endpoint results',
             'configurations': configurations, 'artifact_files': artifact_files,
             'control_evidence': {
                 'native': evidence('setup/evaluator-controls-01/setup-controls.json',
                     'Direct NativeBackend primitives: all correctness strata, six diagnostic families, wrong-result rejection and 10/30-block A/A'),
                 'guards': evidence('setup/additional-guard-controls-01/controls.json'),
                 'native_retry_bridge': evidence('setup/native-measurement-bridge-01/result.json',
                     'Real native development/final routes and bounded read during real timing, with explicitly controlled observer fault injection; no actual external preemption'),
                 'regressions': evidence('setup/readiness-regressions-01/result.json',
                     'Synthetic orchestration, policy, source binding, embargo, accounting, scheduler and cleanup regressions')},
             'model_inference_run': False, 'optimized_endpoint_assessment_run': False,
             'limitations': ['Finite process supervision and role-based read rules are not hostile-code containment.',
                 'Shared host is not exclusive; dependency closure is not hermetic.',
                 'Injected invalidity is an explicit setup observer control, not observed external preemption.',
                 'Observed CLI accounting does not attest cache writes, immutable model snapshots, provider billing tier, or remote-compaction cost.']}
    write_new(ROOT / 'evaluation/readiness.json', final)
    mappings = {
        'real_multiagent_preflight': 'state/launch/preflight.json',
        'native_aa': 'setup/evaluator-controls-01/setup-controls.json',
        'wrong_result_mutants': 'setup/evaluator-controls-01/setup-controls.json',
        'input_mutation': 'setup/additional-guard-controls-01/controls.json',
        'resource_and_timeout_controls': 'setup/additional-guard-controls-01/controls.json',
        'reviewer_reexecution': 'state/launch/preflight.json',
        'source_binding': 'setup/readiness-regressions-01/result.json',
        'journal_corrections': 'state/launch/preflight.json',
        'descendant_accounting': 'state/launch/preflight.json',
        'endpoint_embargo': 'setup/readiness-regressions-01/result.json',
        'final_evaluator_verified': 'evaluation/readiness.json'}
    ready = {'schema_version': 3, 'status': 'ready', 'recorded_utc': timestamp, 'campaign_count': 3,
             'checks': {key: {'status': 'pass', **evidence(path)} for key, path in mappings.items()},
             'final_evaluator_manifest': evidence('evaluation/readiness.json'),
             'observed_accounting_scope': 'All registered lead/worker/reviewer CLI totals reconcile; provider/cache-write/compaction coverage limitations remain explicit.',
             'fresh_seed': evidence('task/seed/engine.cpp'),
             'historical_task_labels': 'Copied original task bytes retain v2 provenance labels; current v3 protocol/prompts/controller govern execution.',
             'generic_infrastructure_relaunches': 0,
             'timing_recovery': 'Two classified immutable-attempt causes, no score-based or generic restart; first valid observation retained.'}
    write_new(ROOT / 'setup/owner-readiness-v3.json', ready)
    print(json.dumps({'status': 'ready', 'readiness': 'setup/owner-readiness-v3.json',
                      'sha256': file_hash(ROOT / 'setup/owner-readiness-v3.json')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
