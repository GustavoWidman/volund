"""No inference: isolated fake deployment proves detached lifecycle and exclusion."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from owner.deployment import assert_fresh,DeploymentError,start
from owner.runner import require_completed_turns
from owner.prompts import LEAD
from runtime.contracts import RuntimeFailure


def wait_json(path,predicate=lambda row:True):
    end=time.monotonic()+10
    while time.monotonic()<end:
        if path.exists():
            row=json.loads(path.read_text())
            if predicate(row):return row
        time.sleep(.025)
    raise AssertionError('fixture status not observed: '+str(path))


class DeploymentTests(unittest.TestCase):
    def test_duplicate_artifacts_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ('state/start-attempt','state/launch','setup/live-preflight','setup/launch-native','assessment/final','campaigns/campaign-1'):
                path=root/name;path.mkdir(parents=True)
                with self.assertRaises(DeploymentError):assert_fresh(root)
                path.rmdir()
            self.assertIsNone(assert_fresh(root))

    def test_detached_child_survives_launch_terminal_hangup_and_retains_status(self):
        with tempfile.TemporaryDirectory(prefix='v2-isolated-fake-deployment-') as tmp:
            root=Path(tmp);(root/'owner').mkdir();(root/'tools').mkdir()
            # This test-only deployment is separate from the reviewed production
            # root. Production has no --command, --root, or environment override.
            (root/'owner/deployment.py').write_text(
                f'import sys\nfrom pathlib import Path\nsys.path.insert(0,{str(ROOT)!r})\n'
                'from owner.deployment import _supervise\n'
                f'raise SystemExit(_supervise(Path({str(root)!r}),Path({str(root/"state/start-attempt")!r})))\n')
            (root/'tools/study-v3').write_text(
                'import os,sys,time,json\nfrom pathlib import Path\n'
                'assert sys.argv[1:]==["launch","--direct-terminal-authorized"]\n'
                'print("FAKE STDOUT",flush=True)\nprint("FAKE STDERR",file=sys.stderr,flush=True)\n'
                'Path("fake-child.json").write_text(json.dumps({"pid":os.getpid(),"sid":os.getsid(0)}))\n'
                'while not Path("finish-fake-child").exists():time.sleep(.025)\n'
                'print("FAKE COMPLETE",flush=True)\nsys.exit(7)\n')
            parent_code=(f'import sys,time\nfrom pathlib import Path\nfrom unittest.mock import patch\nsys.path.insert(0,{str(ROOT)!r})\n'
                         'from owner.deployment import start\n'
                         f'with patch("owner.deployment._check_claimed",return_value={{"status":"synthetic_check_only"}}): start(Path({str(root)!r}))\n'
                         'time.sleep(30)\n')
            parent=subprocess.Popen([sys.executable,'-c',parent_code],cwd='/tmp',stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,start_new_session=True)
            attempt=root/'state/start-attempt'
            try:
                child=wait_json(root/'fake-child.json')
                status=wait_json(attempt/'status.json',lambda row:row['status']=='running')
                self.assertEqual(child['sid'],status['supervisor_pid'])
                self.assertNotEqual(child['sid'],parent.pid)
                os.killpg(parent.pid,signal.SIGHUP);parent.wait(timeout=5)
                os.kill(child['pid'],0)
                with self.assertRaises(DeploymentError):start(root)
                # One already-claimed supervisor cannot start a second child.
                duplicate=subprocess.run([sys.executable,str(root/'owner/deployment.py')],cwd='/tmp',capture_output=True,timeout=5)
                self.assertNotEqual(duplicate.returncode,0)
                (root/'finish-fake-child').touch()
                status=wait_json(attempt/'status.json',lambda row:row['status']=='exited')
                self.assertEqual(status['exit_code'],7)
                self.assertIn('FAKE COMPLETE',(attempt/'stdout.log').read_text())
                self.assertIn('FAKE STDERR',(attempt/'stderr.log').read_text())
                self.assertFalse(status['automatic_restart'])
            finally:
                (root/'finish-fake-child').touch()
                if (root/'fake-child.json').exists():
                    wait_json(attempt/'status.json',lambda row:row['status'] in ('exited','failed'))
                if parent.poll() is None:parent.terminate();parent.wait(timeout=5)
                parent.stderr.close()

    def test_sigterm_targets_workflow_only_and_repeated_signal_does_not_cancel_reader(self):
        with tempfile.TemporaryDirectory(prefix='v2-fake-signal-flow-') as tmp:
            root=Path(tmp)
            code=(f'import sys,asyncio,json\nfrom pathlib import Path\nsys.path.insert(0,{str(ROOT)!r})\n'
                  'from owner.runner import with_stop_signals\n'
                  f'root=Path({str(root)!r})\n'
                  'async def factory(stop):\n'
                  ' async def reader():\n'
                  '  await asyncio.sleep(.2)\n'
                  '  (root/"reader-drained").touch()\n'
                  ' reading=asyncio.create_task(reader())\n'
                  ' (root/"ready").touch()\n'
                  ' try:await asyncio.Event().wait()\n'
                  ' except asyncio.CancelledError:\n'
                  '  (root/"stop-observed").touch()\n'
                  '  assert stop.is_set()\n'
                  '  await reading\n'
                  ' return 1\n'
                  'raise SystemExit(asyncio.run(with_stop_signals(factory)))\n')
            process=subprocess.Popen([sys.executable,'-c',code],cwd='/tmp',stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
            try:
                end=time.monotonic()+5
                while not (root/'ready').exists() and time.monotonic()<end:time.sleep(.01)
                self.assertTrue((root/'ready').exists())
                process.send_signal(signal.SIGTERM)
                while not (root/'stop-observed').exists() and time.monotonic()<end:time.sleep(.01)
                process.send_signal(signal.SIGTERM)
                out,err=process.communicate(timeout=5)
                self.assertEqual(process.returncode,130,err.decode())
                self.assertTrue((root/'reader-drained').exists())
            finally:
                if process.poll() is None:process.terminate();process.wait(timeout=5)
                process.stdout.close();process.stderr.close()

    def test_hard_emergency_interruption_is_incomplete_not_normal_abandonment(self):
        host=SimpleNamespace(agents={'worker':SimpleNamespace(state='interrupted')})
        with self.assertRaisesRegex(RuntimeFailure,'emergency_cancelled_turn_stops_campaign_incomplete'):
            require_completed_turns(host,{'accounting_complete':True})
        with self.assertRaisesRegex(RuntimeFailure,'required_role_usage_incomplete'):
            require_completed_turns(host,{'accounting_complete':False})
        self.assertIn('study_cancel to request cooperative wrap-up',LEAD)
        self.assertIn('A request acknowledgement is not termination',LEAD)
        host.agents['worker'].state='completed'
        self.assertIsNone(require_completed_turns(host,{'accounting_complete':True}))


if __name__=='__main__':unittest.main(verbosity=2)
