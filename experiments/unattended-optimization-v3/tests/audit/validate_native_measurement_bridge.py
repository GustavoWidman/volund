"""Retained setup-only native bridge. Explicit execution flag; never model inference.

Use after the live preflight is parked and other native controls have finished.
The observer injects one declared fault after a successful real native comparison
in each route. It does not claim to observe or cause a real external preemption.
All production execution, retry, cleanup, ledger, read and assessment code remains
unchanged. A comment-only seed variant forces actual final timing without making
an optimization. Synthetic terminal seals exist only under this setup's root.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import fcntl
import json
from pathlib import Path
import shutil
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from development.core import IntegrityError, digest, encoded, file_hash, tree, write_new
from development.native_backend import NativeBackend
from evaluation.run import assess
from owner.measurement import CoordinatedBackend, MeasurementCoordinator
from owner.overlap import MeasurementInterrupted
from owner.readiness import check_manifest, code_manifest, native_configuration
from owner.service import OwnerService, load
from runtime.workspace import WorkspaceRouter


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def parked():
    require(load(ROOT / 'state/launch/status.json')['status'] ==
            'awaiting_exact_owner_readiness_no_inference',
            'native bridge requires the parked, inference-free launcher')


class NoRPC:
    async def request(self, *args, **kwargs):
        raise AssertionError('this setup bridge must not call a CLI or model RPC')


class ControlledObserver:
    """One score-blind fault per route, with real complete native evidence."""
    def __init__(self, route, coordinator):
        self.route, self.coordinator = route, coordinator
        self.calls = []
        self.injected = False
        self.read_callback = None
        self.read_observed = False

    def wrap(self, backend):
        observer = self

        class InstrumentedNative:
            def __getattr__(self, name):
                return getattr(backend, name)

            def execute(self, kind, context, output):
                parked()
                if kind != 'bench':
                    return backend.execute(kind, context, output)
                # Decide which attempt is injected before the native result exists.
                inject_this_attempt = not observer.injected
                original_check = context['check_active']

                def active():
                    original_check()
                    if observer.read_callback and not observer.read_observed:
                        # run_process opens stdout only after its pre-Popen check.
                        # Its next check occurs in the post-launch polling loop.
                        pending = [p for p in output.rglob('exec-spec.json')
                                   if p.with_name('stdout.txt').exists()
                                   and not p.with_name('command.json').exists()]
                        if pending:
                            observer.read_observed = True
                            observer.read_callback(output, pending[0])

                binding = {
                    'route': observer.route,
                    'source_sha256': digest(encoded(tree(context['source_directory']))),
                    'input_library_sha256': context['build']['library_sha256'],
                    'build_directory': str(context['build_directory']),
                    'reference': dict(context['baseline']),
                    'native_configuration_sha256': backend.config_hash,
                    'pinned_files_sha256': digest(encoded(backend.config.pinned_files)),
                }
                before = copy.deepcopy(binding)
                started = time.time()
                result = backend.execute(kind, {**context, 'check_active': active}, output)
                require(digest(encoded(tree(context['source_directory']))) == binding['source_sha256'],
                        'native attempt changed source')
                candidate = Path(context['build_directory']) / context['build']['library']
                require(file_hash(candidate) == binding['input_library_sha256'],
                        'native attempt changed candidate binary')
                require(file_hash(context['baseline']['path']) == binding['reference']['library_sha256'],
                        'native attempt changed reference binary')
                backend.verify()
                evidence = {'route': observer.route, 'native_result': result,
                            'binding': before, 'started_unix': started,
                            'finished_unix': time.time(),
                            'fault_selected_before_native_result': inject_this_attempt,
                            'fault_is_controlled_setup_injection': True,
                            'real_external_preemption_observed': False}
                write_new(output / 'setup-native-observation.json', evidence)
                observer.calls.append({'directory': str(output), **evidence})
                if inject_this_attempt and result['status'] == 'pass':
                    # Use the production validator rather than inventing cleanup.
                    clean = CoordinatedBackend(backend, observer.coordinator)._check_cleanup_receipts(output)
                    require(clean and observer.coordinator.snapshot()['quarantine'] is None,
                            'controlled injection requires native cleanup proof')
                    observer.injected = True
                    fault = {'observer': 'setup-controlled-observer-' + observer.route,
                             'event_id': observer.route + '-completed-native-injection-1',
                             'cause': 'controlled_test_injection_after_completed_native_attempt',
                             'real_external_preemption_observed': False,
                             'cleanup_confirmed': True, 'recorded_unix': time.time()}
                    write_new(output / 'setup-injected-observer-event.json', fault)
                    raise MeasurementInterrupted(observer=fault['observer'], event_id=fault['event_id'],
                                                 cleanup_confirmed=True)
                return result

        return InstrumentedNative()


def verify_series(first_directory, selected_directory, expected_attempt=2):
    first, selected = load(first_directory / 'result.json'), load(selected_directory / 'result.json')
    a, b = load(first_directory / 'setup-native-observation.json'), load(selected_directory / 'setup-native-observation.json')
    require(first['status'] == 'infra_error' and selected['status'] == 'pass',
            'series did not retain invalid attempt then first valid result')
    require(first['measurement_id'] == selected['measurement_id'], 'series identity changed')
    require(selected['measurement_attempt_number'] == expected_attempt, 'unexpected retry count')
    require(selected['measurement_prior_attempt_ids'] == [first['operation_id']], 'prior attempt link missing')
    require(first['measurement_invalidated'] == 'attested_external_interruption', 'wrong invalidity classifier')
    require(a['binding'] == b['binding'], 'retry changed native/source/binary/fixture bindings')
    require(selected['portfolio_speedup'] == b['native_result']['portfolio_speedup'], 'selected score changed')
    require(not (selected_directory / 'setup-injected-observer-event.json').exists(), 'valid result was reinjected')
    for directory in (first_directory, selected_directory):
        require((directory / 'raw.json').is_file() and (directory / 'paired.json').is_file(),
                'complete real native evidence missing')
        lease = load(directory / 'execution-lease.json')
        require(lease['released_monotonic'] >= lease['admitted_monotonic'], 'lease release missing')
    return {'status': 'pass', 'invalid_attempt': str(first_directory),
            'selected_attempt': str(selected_directory), 'binding': a['binding'],
            'selected_portfolio_speedup': selected['portfolio_speedup'],
            'score_used_to_decide_retry': False,
            'selected_result_sha256': file_hash(selected_directory / 'result.json')}


def setup_seal(directory, source=None, binary=None):
    directory.mkdir(parents=True)
    incomplete = source is None
    endpoint = {'stopping_reason': 'incomplete' if incomplete else 'task_complete',
                'sealed_unix': time.time(), 'final_assessment_released': False}
    if source is not None:
        source_hash = digest(encoded(tree(source)))
        destination = directory / 'development/snapshots' / source_hash
        destination.parent.mkdir(parents=True)
        shutil.copytree(source, destination)
        shutil.copy2(binary, directory / 'retained.so')
        endpoint.update(source_hash=source_hash, library_path=str(directory / 'retained.so'),
                        library_sha256=file_hash(directory / 'retained.so'))
    state = {'campaign_id': directory.name, 'stage': 'measured',
             'status': 'incomplete' if incomplete else 'complete',
             'incumbent': copy.deepcopy(endpoint), 'endpoint': endpoint,
             'setup_fixture_only': True, 'actual_model_campaign': False,
             'stop_reason': 'synthetic setup seal; never a measured campaign'}
    authority = directory / 'authority'
    (authority / 'events').mkdir(parents=True)
    event = {'sequence': 1, 'previous': None, 'state_hash': digest(encoded(state)),
             'setup_fixture_only': True}
    write_new(authority / 'events/00000001.json', event)
    write_new(authority / 'state.json', state)
    write_new(authority / 'anchor.json', {'count': 1,
              'head': file_hash(authority / 'events/00000001.json'), 'state_hash': event['state_hash']})


def run(output):
    parked()
    output = output.resolve()
    require(output.is_relative_to(ROOT / 'setup') and output != ROOT / 'setup',
            'all bridge artifacts must be confined to a new setup subdirectory')
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'stage': 'setup_only_native_measurement_bridge',
              'model_calls': 0, 'started_unix': time.time(), 'script_sha256': file_hash(__file__),
              'checks': {}, 'limitations': [
                  'Controlled observer injection is not an observed external preemption.',
                  'One complete comment-only endpoint and two unavailable incomplete seals are synthetic setup fixtures.',
                  'Synthetic existing controls establish unfavorable-score rejection; native scores are never selected or altered.',
                  'No model routing, hostile-code isolation, dedicated-host or full-provider-accounting claim.']}
    manifest = code_manifest(ROOT)
    report['execution_manifest'] = manifest
    coordinator = MeasurementCoordinator()
    workspace = None
    try:
        public = native_configuration(ROOT / 'setup/native-validation-01/native-config.json')
        configurations = {name: native_configuration(ROOT / 'setup' / f'final-evaluator-config-{name}.json')
                          for name in ('transfer', 'shift')}
        isolated = output / 'isolated-root'
        (isolated / 'task').mkdir(parents=True)
        shutil.copytree(ROOT / 'task/seed', isolated / 'task/seed')
        observer = ControlledObserver('development', coordinator)
        native = observer.wrap(NativeBackend(public))
        owner = OwnerService(isolated, output / 'development-probe',
                             CoordinatedBackend(native, coordinator), load(ROOT / 'owner/config.draft.json'), setup=True)
        seed = owner.bootstrap()
        scratch = owner.directory / 'scratch/setup-worker'
        scratch.mkdir()
        actor = SimpleNamespace(agent_id='setup-worker', role='measurement', parent_id='setup-lead',
                                thread_id='setup-no-model-thread', turn_id='setup-no-model-turn', state='running',
                                spec=SimpleNamespace(cwd=scratch, writable_roots=(scratch,)))
        owner.attach_host(SimpleNamespace(agents={actor.agent_id: actor}, threads={actor.thread_id: actor}, stopping=False))
        workspace = WorkspaceRouter(NoRPC(), coordinator, owner.directory,
                                    public_roots=(ROOT / 'task/contract',),
                                    evidence_roots=(owner.store / 'snapshots',), check_active=owner.validate_actor)
        candidate = scratch / 'candidate'
        shutil.copytree(isolated / 'task/seed', candidate)
        with (candidate / 'engine.cpp').open('a') as stream:
            stream.write('\n// Setup-only unchanged behavior; force a distinct source identity for final-route coverage.\n')
        service = owner.service_for_agent(actor)
        source_hash = service.snapshot(candidate)['source_hash']
        built = service.run('build', source_hash=source_hash)
        require(built['status'] == 'pass', 'comment-only setup source failed to build')

        def inspect_during_native(operation, execution_spec):
            started = time.monotonic()
            before = coordinator.snapshot()['active']
            require(before and before['kind'] == 'bench', 'read did not coexist with native bench lease')
            metadata_locked = False
            with (owner.store / '.metadata.lock').open('a+b') as probe:
                try:
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    metadata_locked = True
                else:
                    fcntl.flock(probe, fcntl.LOCK_UN)
            require(metadata_locked, 'development metadata lock was not held')
            result = asyncio.run(workspace.dispatch(actor, 'study_workspace_read',
                                 {'path': str(owner.store / 'snapshots' / source_hash / 'engine.cpp'), 'max_bytes': 512}))
            status = owner.status(actor)
            after = coordinator.snapshot()['active']
            require(result['status'] == 'ok' and result['bytes_read'] <= 512, 'bounded read failed')
            require(before['lease_id'] == after['lease_id'] == status['execution_lane']['active']['lease_id'],
                    'read/status escaped the active benchmark interval')
            require('total_tokens' not in status and 'agents' not in status, 'status exposed usage ledger')
            row = {'status': 'pass', 'native_postlaunch_poll_spec': str(execution_spec),
                   'benchmark_operation': str(operation), 'metadata_lock_held': metadata_locked,
                   'active_lease': before, 'bounded_read': result, 'compact_status': status,
                   'elapsed_seconds': time.monotonic() - started}
            write_new(output / 'read-during-real-benchmark.json', row)

        observer.read_callback = inspect_during_native
        print(json.dumps({'bridge_stage': 'development_native_recovery'}), flush=True)
        measured = service.run('bench', build_id=built['operation_id'])
        require(observer.read_observed and len(observer.calls) == 2, 'development bridge was not exercised exactly once')
        report['development_series'] = verify_series(Path(observer.calls[0]['directory']), Path(observer.calls[1]['directory']))
        report['checks']['real_native_read_and_compact_status_coexist'] = True
        report['checks']['development_retained_same_artifact_recovery'] = True
        report['checks']['development_first_valid_result_retained'] = measured['measurement_attempt_number'] == 2
        report['workspace_cleanup'] = asyncio.run(workspace.close())
        workspace = None

        final_paths = [isolated / 'campaigns' / f'campaign-{i}' for i in range(1, 4)]
        library = owner.store / 'operations' / built['operation_id'] / built['library']
        setup_seal(final_paths[0], owner.store / 'snapshots' / source_hash, library)
        for path in final_paths[1:]:
            setup_seal(path)
        final_observer = ControlledObserver('final', coordinator)

        def verify_setup_binding():
            parked()
            check_manifest(ROOT, manifest)
            require(code_manifest(ROOT)['sha256'] == manifest['sha256'], 'execution inventory drift')
            require(tree(isolated / 'task/seed') == tree(ROOT / 'task/seed'), 'setup seed differs from original')

        print(json.dumps({'bridge_stage': 'isolated_final_native_recovery'}), flush=True)
        with patch('evaluation.run.NativeBackend', lambda config: final_observer.wrap(NativeBackend(config))):
            final = assess(isolated, final_paths, configurations, isolated / 'assessment/final',
                           verify_frozen=verify_setup_binding, measurement_coordinator=coordinator)
        require(final['status'] == 'complete' and len(final_observer.calls) == 3,
                'final native recovery did not complete exactly three actual comparisons')
        report['final_series'] = verify_series(Path(final_observer.calls[0]['directory']),
                                               Path(final_observer.calls[1]['directory']))
        require(sum(row['status'] == 'measured' for row in final['rows']) == 2,
                'comment-only endpoint did not execute both final strata')
        unavailable = [row for row in final['rows'] if row['status'] == 'endpoint_unavailable']
        require(len(unavailable) == 4 and all(row['campaign_status'] == 'incomplete' for row in unavailable),
                'incomplete setup seals were relabeled or lost')
        report['checks'].update(final_retained_same_artifact_recovery=True,
                                final_both_strata_measured=True, final_incomplete_seals_preserved=True,
                                one_shared_coordinator_for_all_native_routes=True)
        report['final_report'] = str(isolated / 'assessment/final/report.json')
        report['final_report_sha256'] = file_hash(report['final_report'])
        report['coordinator'] = coordinator.snapshot()
        require(report['coordinator']['active'] is None and not report['coordinator']['queued']
                and report['coordinator']['quarantine'] is None, 'shared resource lane not clean')
        verify_setup_binding()
        report['status'] = 'pass' if all(report['checks'].values()) else 'fail'
    except BaseException as exc:
        report.update(status='fail', error_category=type(exc).__name__, error=str(exc))
        raise
    finally:
        if workspace is not None:
            report['workspace_cleanup'] = asyncio.run(workspace.close())
        report['finished_unix'] = time.time()
        report['coordinator'] = coordinator.snapshot()
        write_new(output / 'result.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'setup/native-measurement-bridge-01')
    parser.add_argument('--execute-native', action='store_true')
    arguments = parser.parse_args()
    if not arguments.execute_native:
        parser.error('--execute-native is required; run only after all other native setup jobs finish')
    result = run(arguments.output)
    print(json.dumps({'status': result['status'], 'checks': result['checks']}), flush=True)
    raise SystemExit(0 if result['status'] == 'pass' else 1)
