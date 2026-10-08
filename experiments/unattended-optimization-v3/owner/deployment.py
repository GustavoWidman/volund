"""Fixed-command terminal detachment and non-inference deployment checks.

No production command/root overrides, credential reads, environment dumps, model
calls in --check, retries, or resumptions. The supervisor is ordinary process
lifecycle management; it does not alter inherited sandbox/security variables.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from runtime.transport import CLI, AUTH_HOME
from development.core import file_hash
from development.prepare import DEFAULT_COMPILER, DEFAULT_TOOL_ROOT

VERSION = '0.159.3'
ATTEMPT = 'state/start-attempt'
BLOCKERS = ('state/launch', 'state/freeze.json', 'setup/launch-native',
            'setup/live-preflight', 'assessment/final')


class DeploymentError(Exception):
    pass


def _write(path, row):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('x') as stream:
        json.dump(row, stream, sort_keys=True, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def assert_fresh(root, *, attempt_allowed=False):
    names = list(BLOCKERS) + ([] if attempt_allowed else [ATTEMPT])
    for name in names:
        path = root / name
        if path.exists() or path.is_symlink():
            raise DeploymentError('existing artifact blocks launch: ' + name)
    campaigns = root / 'campaigns'
    if campaigns.exists() and any(campaigns.iterdir()):
        raise DeploymentError('existing campaign artifacts block launch')


def official_artifacts():
    """Resolve the Linux x64 package selected by the installed official wrapper."""
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise DeploymentError('reviewed deployment requires Linux x86_64')
    wrapper = CLI.resolve(strict=True)
    package = wrapper.parent.parent
    if json.loads((package / 'package.json').read_text()).get('version') != VERSION:
        raise DeploymentError('official CLI package version mismatch')
    native_package = package.parent / 'codex-linux-x64'
    if json.loads((native_package / 'package.json').read_text()).get('version') != VERSION + '-linux-x64':
        raise DeploymentError('official native package version mismatch')
    binary = native_package / 'vendor/x86_64-unknown-linux-musl/bin/codex'
    companion = binary.with_name('codex-code-mode-host')
    files = [wrapper, package/'package.json', native_package/'package.json', binary, companion]
    for path in (wrapper, binary, companion):
        if not path.is_file() or not os.access(path, os.X_OK):
            raise DeploymentError('required official executable unavailable: ' + str(path))
    return {str(path.resolve(strict=True)): file_hash(path) for path in files}


def _version(command, cwd, *, env=None, exact=None, expected_code=0, version_on_stderr=False):
    result = subprocess.run(command, cwd=cwd, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=20, check=False, env=env)
    if result.returncode != expected_code:
        # Do not export arbitrary diagnostic stderr or environment contents.
        raise DeploymentError('non-inference command failed: ' + str(command[0]))
    output = (result.stderr if version_on_stderr else result.stdout).decode('utf-8', errors='replace').strip()
    if exact is not None and output != exact:
        raise DeploymentError('official executable version mismatch')
    return output.splitlines()[0] if output else 'successful_exit'


def check_deployment(root=ROOT, *, _claimed=False):
    root = Path(root).resolve(strict=True)
    assert_fresh(root, attempt_allowed=_claimed)
    if not AUTH_HOME.is_dir():  # Deliberately no listing/opening of auth home.
        raise DeploymentError('task authentication directory does not exist')
    artifacts = official_artifacts()
    native = next(Path(p) for p in artifacts if p.endswith('/bin/codex'))
    for relative in ('tools/study-v3', 'task/seed', 'task/contract',
                     'development/native/driver.cpp', 'development/native/definitions.draft.json'):
        if not (root/relative).exists():
            raise DeploymentError('deployment dependency missing: ' + relative)
    if not os.access(root/'tools/study-v3', os.X_OK):
        raise DeploymentError('workflow wrapper is not executable')
    tool_root = DEFAULT_TOOL_ROOT.resolve(strict=True)
    profiler = tool_root/'usr/bin/valgrind'
    annotate = tool_root/'usr/bin/callgrind_annotate'
    native_tools = [Path(DEFAULT_COMPILER), profiler, profiler.with_name('valgrind.bin'), annotate,
                    tool_root/'usr/libexec/valgrind/callgrind-amd64-linux',
                    tool_root/'usr/libexec/valgrind/memcheck-amd64-linux']
    for path in native_tools:
        if not path.is_file() or not os.access(path, os.X_OK):
            raise DeploymentError('native/profiling executable unavailable: ' + str(path))
    if len(os.sched_getaffinity(0)) < 2:
        raise DeploymentError('two allowed logical CPUs required')
    writable = []
    for relative in ('state', 'setup', 'campaigns', 'assessment'):
        target = root/relative
        parent = target
        while not parent.exists():
            parent = parent.parent
        if not parent.is_dir() or not parent.resolve().is_relative_to(root):
            raise DeploymentError('invalid writable deployment parent')
        with tempfile.TemporaryFile(dir=parent) as probe:
            probe.write(b'deployment-write-check\n');probe.flush()
        writable.append(str(target))
    env = os.environ.copy();env['CODEX_HOME'] = str(AUTH_HOME)
    profile_env = os.environ.copy();profile_env['VALGRIND_LIB'] = str(tool_root/'usr/libexec/valgrind')
    with tempfile.TemporaryDirectory(prefix='study-v3-path-check-') as unrelated:
        versions = {
            'official_cli': _version([str(CLI), '--version'], unrelated, env=env, exact='codex-cli '+VERSION),
            'official_native': _version([str(native), '--version'], unrelated, env=env, exact='codex-cli '+VERSION),
            'compiler': _version([DEFAULT_COMPILER, '--version'], unrelated),
            'valgrind': _version([str(profiler), '--version'], unrelated, env=profile_env),
            'callgrind_annotate': _version([str(annotate), '--version'], unrelated, expected_code=255, version_on_stderr=True, exact='callgrind_annotate-3.24.0'),
        }
        _version([sys.executable, str(root/'tools/study-v3'), '--help'], unrelated)
    return {'status':'pass', 'model_inference_run':False, 'root':str(root),
            'official_artifacts':artifacts, 'versions':versions,
            'auth_directory_exists':True, 'auth_content_inspected':False,
            'native_executables':[str(p.resolve()) for p in native_tools],
            'writable_deployment_directories':writable,
            'wrapper_import_and_help_from_unrelated_cwd':True,
            'environment_preserved':True}


def _supervise(root, attempt):
    """Private fixed-workflow supervisor; tests use an isolated fake deployment."""
    root, attempt = Path(root), Path(attempt)
    with (attempt/'supervisor-claim.json').open('x') as claim:
        json.dump({'pid':os.getpid(), 'claimed_unix':time.time()}, claim)
    child = None
    interrupted = None
    status = {'status':'supervisor_starting', 'root':str(root), 'supervisor_pid':os.getpid(),
              'supervisor_session_id':os.getsid(0), 'started_unix':time.time(),
              'automatic_restart':False}
    def checkpoint(**items):
        status.update(items);_write(attempt/'status.json', status)
    def stop(signum, frame):
        nonlocal interrupted
        interrupted = signum
        if child is not None and child.poll() is None:
            child.send_signal(signal.SIGTERM)  # Owned unreaped child only.
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        assert_fresh(root, attempt_allowed=True)
        checkpoint()
        with (attempt/'stdout.log').open('xb') as stdout, (attempt/'stderr.log').open('xb') as stderr:
            child = subprocess.Popen([sys.executable, str(root/'tools/study-v3'), 'launch',
                                      '--direct-terminal-authorized'], cwd=root,
                                     stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
            checkpoint(status='running', launcher_pid=child.pid)
            if interrupted is not None:child.send_signal(signal.SIGTERM)
            code = child.wait()
        checkpoint(status='exited', exit_code=code, interrupted_signal=interrupted,
                   finished_unix=time.time(), workflow_status_path=str(root/'state/launch/status.json'))
        return 0 if code == 0 else 1
    except BaseException as exc:
        if child is not None and child.poll() is None:
            child.terminate();child.wait()  # Let the workflow's own cleanup finish.
        checkpoint(status='failed', failure=type(exc).__name__, finished_unix=time.time())
        return 1


def start(root=ROOT):
    root = Path(root).resolve(strict=True)
    assert_fresh(root)
    (root/'state').mkdir(exist_ok=True)
    attempt = root/ATTEMPT
    attempt.mkdir(exist_ok=False)  # Atomic duplicate-start exclusion, retained forever.
    try:
        # The attempt is already claimed, so check the remaining fresh targets.
        assert_fresh(root, attempt_allowed=True)
        _write(attempt/'claim.json', {'root':str(root), 'claimed_unix':time.time(),
                                     'automatic_restart':False})
        # --check separately verifies freshness; avoid exempting it publicly.
        report = _check_claimed(root)
        _write(attempt/'check.json', report)
        with (attempt/'supervisor.log').open('xb') as log:
            process = subprocess.Popen([sys.executable, str(root/'owner/deployment.py'), '--supervise'],
                                       cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       start_new_session=True, close_fds=True)
        _write(attempt/'detached.json', {'supervisor_pid':process.pid, 'started_unix':time.time()})
        # Only wait for admission, never impose a research/preflight deadline.
        end = time.monotonic()+10
        while time.monotonic()<end:
            path = attempt/'status.json'
            if path.exists():
                status=json.loads(path.read_text())
                if status['status'] in ('running','exited'):
                    return {'status':'detached', 'root':str(root), 'supervisor_pid':process.pid,
                            'attempt_directory':str(attempt), 'workflow_status_path':str(root/'state/launch/status.json')}
                if status['status']=='failed':raise DeploymentError('detached supervisor failed; inspect retained status')
            if process.poll() is not None:raise DeploymentError('detached supervisor exited before admission')
            time.sleep(.05)
        raise DeploymentError('detached admission uncertain; inspect retained status; do not restart')
    except BaseException as exc:
        _write(attempt/'start-error.json', {'status':'start_failed_or_uncertain', 'failure':type(exc).__name__,
                                          'automatic_restart':False, 'recorded_unix':time.time()})
        raise


def _check_claimed(root):
    # A fixed internal flag keeps production entry points incapable of retrying
    # existing attempts while reusing precisely the no-inference checks.
    return check_deployment(root, _claimed=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--check',action='store_true',help='version/import/path checks only; no inference')
    group.add_argument('--supervise',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args(argv)
    if args.supervise:
        attempt=ROOT/ATTEMPT
        if not (attempt/'claim.json').is_file() or not (attempt/'check.json').is_file() or (attempt/'status.json').exists():
            raise DeploymentError('supervisor requires one fresh checked attempt')
        return _supervise(ROOT,attempt)
    try:
        result=check_deployment() if args.check else start()
        print(json.dumps(result,sort_keys=True,indent=2));return 0
    except Exception as exc:
        print(json.dumps({'status':'blocked','failure':str(exc) if isinstance(exc,DeploymentError) else type(exc).__name__,
                          'automatic_restart':False}),file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
