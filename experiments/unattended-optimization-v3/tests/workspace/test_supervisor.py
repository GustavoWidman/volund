import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
SUPERVISOR = ROOT / 'runtime/command_supervisor.py'

class SupervisorTests(unittest.TestCase):
    def run_job(self, command, *, timeout=3, cancel=False, missing_cwd=False):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); output=root/'output'; output.mkdir()
            if cancel: (output/'cancel-requested').touch()
            spec={'invocation_id':'test','command':command,'cwd':str(root/'missing' if missing_cwd else root),
                  'actor_root':str(root),'output_directory':str(output),'timeout_seconds':timeout,
                  'path':os.defpath,'cpus':[]}
            raw=json.dumps(spec,sort_keys=True,separators=(',',':')).encode()
            proc=subprocess.run([sys.executable,'-B',str(SUPERVISOR),base64.b64encode(raw).decode()],
                                capture_output=True,timeout=timeout+15)
            self.assertEqual(proc.returncode,0,proc.stderr.decode())
            row=json.loads(proc.stdout)
            self.assertTrue(row['cleanup_complete']);self.assertTrue(row['subreaper_verified'])
            self.assertEqual(row['remaining_direct_children'],[])
            self.assertEqual(row['spec_sha256'],hashlib.sha256(raw).hexdigest())
            out=(output/'stdout.bin').read_bytes() if (output/'stdout.bin').exists() else b''
            err=(output/'stderr.bin').read_bytes() if (output/'stderr.bin').exists() else b''
            for name in row['output_files']:
                self.assertEqual(hashlib.sha256((output/name).read_bytes()).hexdigest(),row['output_files'][name]['sha256'])
            return row,out,err
    def test_normal(self):
        row,out,err=self.run_job('printf hello; printf error >&2')
        self.assertEqual((out,err),(b'hello',b'error'));self.assertEqual(row['root_exit_code'],0)
    def test_nonzero(self):
        row,_,_=self.run_job('exit 7');self.assertEqual(row['root_exit_code'],7)
    def test_background_open_stdout(self):
        row,_,_=self.run_job('sleep 30 & exit 0')
        self.assertEqual(row['root_exit_code'],0);self.assertGreaterEqual(row['reaped_count'],2)
    def test_background_closed_stdout(self):
        row,_,_=self.run_job('sleep 30 >/dev/null 2>&1 & exit 5')
        self.assertEqual(row['root_exit_code'],5);self.assertGreaterEqual(row['reaped_count'],2)
    def test_setsid_descendant(self):
        code="import os,time; p=os.fork();\nif p: os._exit(0)\nos.setsid(); p=os.fork();\nif p: os._exit(0)\ntime.sleep(30)"
        import shlex
        row,_,_=self.run_job('/usr/bin/python3 -c '+shlex.quote(code))
        self.assertGreaterEqual(row['reaped_count'],3)
    def test_ignores_term_watchdog(self):
        row,_,_=self.run_job("trap '' TERM; sleep 30",timeout=.15)
        self.assertEqual(row['reason'],'command_watchdog');self.assertNotEqual(row['root_exit_code'],0)
    def test_prelaunch_cancel(self):
        row,_,_=self.run_job('exit 0',cancel=True)
        self.assertFalse(row['process_started']);self.assertEqual(row['reason'],'interrupted_before_launch')
    def test_prelaunch_missing_directory(self):
        row,_,_=self.run_job('exit 0',missing_cwd=True)
        self.assertFalse(row['process_started']);self.assertEqual(row['reason'],'command_launch_failure')
    def test_output_capture_bounded(self):
        row,out,_=self.run_job("/usr/bin/python3 -c 'import sys; sys.stdout.write(\"x\"*9000000)'",timeout=5)
        self.assertEqual(len(out),8*1024*1024)
        self.assertEqual(row['output_files']['stdout.bin']['observed_bytes'],9000000)
        self.assertGreater(row['output_files']['stdout.bin']['discarded_bytes'],0)
    def test_inherited_environment_not_exposed(self):
        os.environ['STUDY_UNRELATED_TEST_DATA']='not-for-child'
        row,out,_=self.run_job("/usr/bin/python3 -c 'import os; print(os.environ.get(\"STUDY_UNRELATED_TEST_DATA\",\"absent\"))'")
        self.assertEqual(out.strip(),b'absent')

if __name__=='__main__': unittest.main()
