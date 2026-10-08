"""Independent local process-cleanup tests, not actual CLI sandbox attestation."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
SUPERVISOR = ROOT / 'runtime/command_supervisor.py'


class SupervisorReviewTests(unittest.TestCase):
    def job(self, command, *, timeout=3, action=None):
        with tempfile.TemporaryDirectory(prefix='v3-independent-supervisor-') as td:
            root = Path(td)
            output = root / 'output'
            output.mkdir()
            spec = {'invocation_id': 'independent-synthetic', 'command': command,
                    'cwd': str(root), 'actor_root': str(root), 'output_directory': str(output),
                    'timeout_seconds': timeout, 'path': os.defpath, 'cpus': []}
            raw = json.dumps(spec, sort_keys=True, separators=(',', ':')).encode()
            started = time.monotonic()
            proc = subprocess.Popen([sys.executable, '-B', str(SUPERVISOR), base64.b64encode(raw).decode()],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                if action is not None:
                    deadline = time.monotonic() + 3
                    while not (root / 'ready').exists():
                        self.assertIsNone(proc.poll(), 'supervisor exited before synthetic child ready')
                        if time.monotonic() >= deadline:
                            self.fail('synthetic child never became ready')
                        time.sleep(.001)
                    action(proc, output)
                stdout, stderr = proc.communicate(timeout=timeout + 12)
            finally:
                if proc.poll() is None:
                    # Ask the task-owned supervisor to clean up its own children.
                    (output / 'cancel-requested').touch()
                    stdout, stderr = proc.communicate(timeout=12)
            self.assertEqual(proc.returncode, 0, stderr.decode())
            result = json.loads(stdout)
            self.assertTrue(result['cleanup_complete'])
            self.assertTrue(result['subreaper_verified'])
            self.assertTrue(result['sigchld_default_verified'])
            self.assertTrue(result['output_drained'])
            self.assertEqual(result['remaining_direct_children'], [])
            self.assertEqual(result['spec_sha256'], hashlib.sha256(raw).hexdigest())
            self.assertIsNotNone(result['root_exit_code'])
            self.assertTrue(any(row['root'] for row in result['reaped_children']))
            streams = {}
            for name, receipt in result['output_files'].items():
                content = (output / name).read_bytes()
                self.assertEqual(len(content), receipt['bytes'])
                self.assertEqual(hashlib.sha256(content).hexdigest(), receipt['sha256'])
                self.assertEqual(receipt['observed_bytes'], receipt['bytes'] + receipt['discarded_bytes'])
                streams[name] = content
            return result, streams, time.monotonic() - started

    def test_late_cancel_marker_cleans_stubborn_foreground_and_child(self):
        result, _, elapsed = self.job("trap '' TERM; touch ready; while :; do sleep 30; done",
                                      action=lambda proc, out: (out / 'cancel-requested').touch())
        self.assertEqual(result['reason'], 'interrupted')
        self.assertLess(elapsed, 4)
        self.assertGreaterEqual(result['reaped_count'], 2)

    def test_signal_to_supervisor_drains_and_cleans_stubborn_child(self):
        def stop(proc, output):
            descriptor = os.pidfd_open(proc.pid)
            try:
                signal.pidfd_send_signal(descriptor, signal.SIGTERM)
            finally:
                os.close(descriptor)
        result, streams, elapsed = self.job("trap '' TERM; printf started; touch ready; sleep 30", action=stop)
        self.assertEqual(result['reason'], 'interrupted')
        self.assertEqual(streams['stdout.bin'], b'started')
        self.assertLess(elapsed, 4)

    def test_nested_detached_descendants_are_reaped_after_watchdog(self):
        code = """import os,time
for depth in range(5):
    child=os.fork()
    if child:
        os.waitpid(child,0)
        os._exit(0)
    os.setsid()
open('ready','w').close()
time.sleep(30)
"""
        result, _, elapsed = self.job('/usr/bin/python3 -c ' + shlex.quote(code), timeout=.2)
        self.assertEqual(result['reason'], 'command_watchdog')
        self.assertGreaterEqual(result['reaped_count'], 6)
        self.assertLess(elapsed, 4)

    def test_foreground_signal_exit_is_retained_while_background_cleanup_finishes(self):
        result, _, _ = self.job('sleep 30 >/dev/null 2>&1 & kill -KILL $$')
        self.assertEqual(result['root_exit_code'], -signal.SIGKILL)
        self.assertGreaterEqual(result['reaped_count'], 2)

    def test_both_streams_exceed_capture_limit_without_pipe_deadlock(self):
        code = "import os; [(os.write(1,b'a'*65536),os.write(2,b'b'*65536)) for _ in range(140)]"
        result, streams, _ = self.job('/usr/bin/python3 -c ' + shlex.quote(code), timeout=5)
        self.assertEqual(result['root_exit_code'], 0)
        for name, char in (('stdout.bin', b'a'), ('stderr.bin', b'b')):
            self.assertEqual(len(streams[name]), 8 * 1024 * 1024)
            self.assertEqual(streams[name][:1] + streams[name][-1:], char + char)
            self.assertEqual(result['output_files'][name]['observed_bytes'], 140 * 65536)
            self.assertGreater(result['output_files'][name]['discarded_bytes'], 0)


if __name__ == '__main__':
    unittest.main()
