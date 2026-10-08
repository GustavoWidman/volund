"""Task-owned supervisor executed INSIDE the unchanged CLI command sandbox.

Only this process becomes a child subreaper. This is observed process cleanup,
not a hostile-code boundary against malicious same-UID process manipulation.
"""
from __future__ import annotations
import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

STOP = False
CAPTURE_BYTES = 8 * 1024 * 1024


def stop_signal(signum, frame):
    global STOP
    STOP = True


def children():
    # Some supported kernels omit /proc/.../children. Inspect only process
    # parent identities in this PID namespace; no command lines/environments.
    result = []
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            raw = (path / 'stat').read_text()
            fields = raw[raw.rfind(')') + 2:].split()
            if int(fields[1]) == os.getpid():
                result.append(int(path.name))
        except (FileNotFoundError, ProcessLookupError):
            continue
    return result


def signal_children(sig):
    for pid in children():
        try:
            fd = os.pidfd_open(pid)
            try:
                raw = Path(f'/proc/{pid}/stat').read_text()
                if int(raw[raw.rfind(')') + 2:].split()[1]) == os.getpid():
                    signal.pidfd_send_signal(fd, sig)
            finally:
                os.close(fd)
        except ProcessLookupError:
            pass
        except FileNotFoundError:
            pass


def execute(spec, spec_bytes):
    output = Path(spec['output_directory']).resolve(strict=True)
    cwd = Path(spec['cwd']).resolve(strict=False)
    actor = Path(spec['actor_root']).resolve(strict=True)
    if not cwd.is_relative_to(actor) or not output.is_relative_to(actor):
        raise ValueError('command workspace scope differs')
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), 'child subreaper unavailable')
    current = ctypes.c_int()
    if libc.prctl(37, ctypes.byref(current), 0, 0, 0) != 0 or current.value != 1:
        raise RuntimeError('child subreaper state unverified')
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, stop_signal)
    if spec.get('cpus'):
        os.sched_setaffinity(0, set(spec['cpus']))
    started, started_unix = time.monotonic(), time.time()
    child_env = {'PATH': spec['path'], 'LC_ALL': 'C', 'LANG': 'C', 'TZ': 'UTC',
                 'TMPDIR': str(output / 'tmp'), 'DEBUGINFOD_URLS': '', 'PYTHONDONTWRITEBYTECODE': '1'}
    if spec.get('valgrind_lib'):
        child_env['VALGRIND_LIB'] = spec['valgrind_lib']
    selector = selectors.DefaultSelector()
    files, hashes, observed, stored = {}, {}, {}, {}
    child, root_status, cleanup_started = None, None, None
    reaped, reaped_count = [], 0
    reason, error, clean = 'command_completed', None, False
    cancel_path = output / 'cancel-requested'

    def cancelled():
        return STOP or cancel_path.exists()

    def collect(timeout=0):
        # Bounded work per loop keeps timeout/cancellation responsive even if
        # a normal verbose command produces output faster than it is consumed.
        for key, _ in selector.select(timeout):
            name = key.data
            chunk = os.read(key.fd, 65536)
            if not chunk:
                selector.unregister(key.fileobj)
                key.fileobj.close()
                continue
            observed[name] += len(chunk)
            retained = chunk[:max(0, CAPTURE_BYTES-stored[name])]
            files[name].write(retained)
            hashes[name].update(retained)
            stored[name] += len(retained)

    def reap():
        nonlocal root_status, reaped_count
        while True:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                return True
            except InterruptedError:
                continue
            if not pid:
                return False
            code = os.waitstatus_to_exitcode(status)
            reaped_count += 1
            if len(reaped) < 4096:
                reaped.append({'pid': pid, 'exit_code': code, 'root': child is not None and pid == child.pid})
            if child is not None and pid == child.pid:
                root_status, child.returncode = code, code

    try:
        (output / 'tmp').mkdir(exist_ok=False)
        for name in ('stdout.bin', 'stderr.bin'):
            files[name] = (output / name).open('xb')
            hashes[name], observed[name], stored[name] = hashlib.sha256(), 0, 0
        if cancelled():
            reason = 'interrupted_before_launch'
        else:
            child = subprocess.Popen(['/bin/bash', '--noprofile', '--norc', '-c', spec['command']],
                                     cwd=cwd, env=child_env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     close_fds=True, start_new_session=True)
            for stream, name in ((child.stdout, 'stdout.bin'), (child.stderr, 'stderr.bin')):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            while True:
                no_children = reap()
                if no_children:
                    clean = root_status is not None
                    break
                now = time.monotonic()
                if cancelled() and cleanup_started is None:
                    cleanup_started, reason = now, 'interrupted'
                if now-started >= spec['timeout_seconds'] and cleanup_started is None:
                    cleanup_started, reason = now, 'command_watchdog'
                if root_status is not None and cleanup_started is None:
                    cleanup_started, reason = now, 'background_descendants_cleaned'
                if cleanup_started is not None:
                    signal_children(signal.SIGKILL if now-cleanup_started >= .5 else signal.SIGTERM)
                    if now-cleanup_started > 10:
                        reason = 'descendant_cleanup_unverified'
                        break
                collect(.01)
    except BaseException as exc:
        error = type(exc).__name__
        reason = 'command_launch_failure' if child is None else 'supervisor_operation_failure'
    finally:
        # Cleanup also runs after launch/collection exceptions. A prelaunch
        # failure with ECHILD is an ordinary tool failure, not a leaked process.
        cleanup_deadline = time.monotonic() + 10
        while True:
            no_children = reap()
            if no_children:
                clean = child is None or root_status is not None
                break
            signal_children(signal.SIGKILL)
            if time.monotonic() >= cleanup_deadline:
                clean = False
                break
            try:
                collect(.01)
            except (OSError, ValueError):
                time.sleep(.01)
        # With no live descendants, drain buffered final bytes to EOF.
        drain_deadline = time.monotonic() + 2
        while selector.get_map() and time.monotonic() < drain_deadline:
            try:
                collect(.01)
            except (OSError, ValueError):
                error = error or 'output_drain_error'
                break
        output_drained = not selector.get_map()
        selector.close()
        for stream in files.values():
            stream.flush()
            stream.close()
    result = {
        'schema_version': 1, 'invocation_id': spec['invocation_id'],
        'spec_sha256': hashlib.sha256(spec_bytes).hexdigest(),
        'supervisor_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'started_unix': started_unix, 'finished_unix': time.time(),
        'process_started': child is not None, 'root_exit_code': root_status,
        'reason': reason, 'error_category': error, 'cleanup_complete': clean,
        'subreaper_verified': True, 'sigchld_default_verified': True,
        'reaped_children': reaped, 'reaped_count': reaped_count,
        'reaped_details_truncated': reaped_count > len(reaped),
        'remaining_direct_children': children(), 'output_drained': output_drained,
        'output_files': {name: {'bytes': stored[name], 'observed_bytes': observed[name],
                              'discarded_bytes': observed[name]-stored[name],
                              'sha256': hashes[name].hexdigest()}
                         for name in files},
        'per_stream_capture_limit_bytes': CAPTURE_BYTES,
        'environment_scope': 'minimal task environment; no inherited credentials',
        'containment_limit': 'Observed process cleanup, not a hostile same-UID security boundary',
    }
    return result


def main():
    spec_bytes = base64.b64decode(sys.argv[1], validate=True)
    spec = json.loads(spec_bytes)
    result = execute(spec, spec_bytes)
    print(json.dumps(result, separators=(',', ':')), flush=True)
    return 0 if result['cleanup_complete'] else 70


if __name__ == '__main__':
    raise SystemExit(main())
