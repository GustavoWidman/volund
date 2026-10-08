from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import runpy
import copy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from runtime.contracts import (RuntimeFailure, Safeguards, RoleSpec, thread_start_metadata,
                               validate_thread_response, sandbox)
from runtime.diagnose_thread_start import diagnose
from runtime.multiagent import Host
from test_runtime import FakeRPC, roles_at


class DiagnosticRPC(FakeRPC):
    def __init__(self, widened=False):
        super().__init__()
        self.widened = widened
        self.opened = False
        self.closed = False

    async def open(self):
        self.opened = True

    async def close(self):
        self.closed = True
        return {'event_stream_drained': True, 'tracked_processes_exited': True}

    async def request(self, method, params):
        response = await super().request(method, params)
        if method == 'account/read':
            return {'account': {'type': 'chatgpt', 'email': 'PRIVATE_SENTINEL'}}
        if method == 'thread/start':
            response['thread']['preview'] = 'PRIVATE_SENTINEL'
            response['reasoning'] = 'PRIVATE_SENTINEL'
            if self.widened:
                response['sandbox']['writableRoots'].append('/tmp')
        if method == 'thread/unsubscribe':
            return {'status': 'unsubscribed'}
        return response


class StartupMetadataTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self, workspace):
        path = Path(__file__).parent/'fixtures/thread-start-normalized-cwd.json'
        response = json.loads(path.read_text())['response']
        response['cwd'] = str(workspace)
        # Ephemeral was already validated in the live failure before its sandbox
        # check. It is not part of the deliberately narrower recorded allowlist.
        response['thread']['ephemeral'] = True
        return response

    def test_actual_sanitized_empty_extra_roots_mean_writable_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            spec = RoleSpec('gpt-6.1-sol', 'high', root, (root,), 'fixture')
            response = self.fixture(root)
            self.assertEqual(response['sandbox']['writableRoots'], [])
            self.assertEqual(validate_thread_response(response, spec), response['thread']['id'])

    def test_equivalent_cwd_duplicates_and_root_order_are_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); other = root/'other'; other.mkdir()
            spec = RoleSpec('gpt-6.1-sol', 'high', root, (root, other), 'fixture')
            response = self.fixture(root)
            response['sandbox']['writableRoots'] = [str(other), str(root), str(other)]
            self.assertEqual(validate_thread_response(response, spec), response['thread']['id'])

    def test_broad_narrow_relative_alias_and_malformed_roots_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve(); root = base/'actor'; root.mkdir()
            other = base/'extra'; other.mkdir()
            child = root/'child'; child.mkdir()
            alias = base/'alias'; alias.symlink_to(root, target_is_directory=True)
            spec = RoleSpec('gpt-6.1-sol', 'high', root, (root, other), 'fixture')
            variants = [[], [str(base)], [str(child)], [str(root), str(base/'extra2')],
                        [str(root), '../extra'], [str(root), str(alias)],
                        [str(root), str(other)+'/../extra'], [str(root), None],
                        [str(root), 1], str(other), [str(root), '/'],
                        [str(root), str(other)+'\x00'], [str(root), {'path': str(other)}]]
            for roots in variants:
                with self.subTest(roots=roots):
                    response = self.fixture(root)
                    response['sandbox']['writableRoots'] = roots
                    with self.assertRaisesRegex(RuntimeFailure, 'sandbox_or_approval_mismatch'):
                        validate_thread_response(response, spec)

    def test_network_temp_approval_wrongcwd_and_unknown_fields_stay_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); spec=RoleSpec('gpt-6.1-sol', 'high', root, (root,), 'fixture')
            base=self.fixture(root)
            for key, value in [('networkAccess', True), ('networkAccess', 0),
                               ('excludeTmpdirEnvVar', False), ('excludeSlashTmp', False),
                               ('type', 'dangerFullAccess'), ('unknownPermission', True)]:
                with self.subTest(key=key, value=value):
                    row=copy.deepcopy(base); row['sandbox'][key]=value
                    with self.assertRaisesRegex(RuntimeFailure,'sandbox_or_approval_mismatch'):
                        validate_thread_response(row,spec)
            for key in base['sandbox']:
                row=copy.deepcopy(base); del row['sandbox'][key]
                with self.assertRaisesRegex(RuntimeFailure,'sandbox_or_approval_mismatch'):
                    validate_thread_response(row,spec)
            row=copy.deepcopy(base); row['approvalPolicy']='on-request'
            with self.assertRaisesRegex(RuntimeFailure,'sandbox_or_approval_mismatch'):
                validate_thread_response(row,spec)
            row=copy.deepcopy(base); row['cwd']=str(root/'wrong')
            with self.assertRaisesRegex(RuntimeFailure,'cwd_mismatch'):
                validate_thread_response(row,spec)

    async def test_diagnostic_never_starts_turn_and_discards_private_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            rpc = DiagnosticRPC()
            result = await diagnose(Path(tmp)/'diagnostic', rpc=rpc)
            self.assertEqual([method for method, _ in rpc.calls],
                             ['initialize', 'account/read', 'thread/start', 'thread/unsubscribe'])
            self.assertTrue(result['validation_passed'])
            self.assertFalse(result['turn_start_sent'])
            self.assertTrue(rpc.closed)
            self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))
            self.assertTrue((Path(tmp)/'diagnostic/diagnostic.json').is_file())

    async def test_mismatch_is_captured_and_unsubscribed_without_weakening_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            rpc = DiagnosticRPC(widened=True)
            result = await diagnose(Path(tmp)/'diagnostic', rpc=rpc)
            self.assertEqual(result['failure'], 'sandbox_or_approval_mismatch')
            self.assertFalse(result['validation_passed'])
            self.assertEqual(result['unsubscribe_status'], 'unsubscribed')
            self.assertIn('/tmp', result['thread_start_metadata']['sandbox']['writableRoots'])
            self.assertFalse(any(method.startswith('turn/') for method, _ in rpc.calls))

    async def test_host_retains_rejected_start_metadata_before_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            rpc = DiagnosticRPC(widened=True)
            host = Host(rpc, roles_at(base), Safeguards(), base/'evidence')
            with self.assertRaisesRegex(RuntimeFailure, 'sandbox_or_approval_mismatch'):
                await host.spawn('lead', 'fixture')
            row = host.export()['agents'][0]
            self.assertIsNone(row['thread_id'])
            self.assertEqual(row['thread_start_metadata']['thread']['id'], 'thread-1')
            self.assertFalse(any(method.startswith('turn/') for method, _ in rpc.calls))
            evidence = (base/'evidence/agent-1.jsonl').read_text()
            self.assertIn('threadStartMetadata', evidence)
            self.assertNotIn('PRIVATE_SENTINEL', evidence)

    async def test_implicit_real_launch_refused_before_filesystem_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'diagnostic'
            with self.assertRaisesRegex(RuntimeFailure, 'direct_terminal_launch_not_authorized'):
                await diagnose(path)
            self.assertFalse(path.exists())

    async def test_existing_diagnostic_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            rpc = DiagnosticRPC()
            with self.assertRaises(FileExistsError):
                await diagnose(Path(tmp), rpc=rpc)
            self.assertFalse(rpc.opened)

    def test_projection_rejects_unknown_nested_fields_and_preserves_missing_defaults(self):
        result = thread_start_metadata({'thread': {'id': 'a', 'cliVersion': '0.159.3',
                                                   'messages': ['PRIVATE_SENTINEL']},
            'approvalPolicy': {'granular': {'rules': False, 'secret': 'PRIVATE_SENTINEL'}},
            'sandbox': {'type': 'workspaceWrite', 'secret': 'PRIVATE_SENTINEL'}})
        self.assertEqual(result['sandbox'], {'type': 'workspaceWrite'})
        self.assertEqual(result['approvalPolicy'], {'granular': {'rules': False}})
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))

    def test_fixed_wrapper_supplies_only_owner_diagnostic_arguments(self):
        wrapper = ROOT/'tools/diagnose-thread-start'
        seen = []
        def fake_main():
            seen.extend(sys.argv)
            return 0
        with patch('runtime.diagnose_thread_start.main', side_effect=fake_main), patch.object(sys, 'argv', [str(wrapper)]):
            with self.assertRaises(SystemExit) as result:
                runpy.run_path(str(wrapper), run_name='__main__')
        self.assertEqual(result.exception.code, 0)
        self.assertEqual(seen[1:], ['--output-dir', str(ROOT/'setup/thread-start-diagnostic-01'),
                                    '--direct-terminal-authorized'])

    def test_fixed_wrapper_rejects_all_overrides_before_main(self):
        wrapper = ROOT/'tools/diagnose-thread-start'
        with patch('runtime.diagnose_thread_start.main') as main, patch.object(sys, 'argv', [str(wrapper), '--output-dir', '/tmp/other']):
            with self.assertRaises(SystemExit):
                runpy.run_path(str(wrapper), run_name='__main__')
        main.assert_not_called()


if __name__ == '__main__':
    unittest.main()
