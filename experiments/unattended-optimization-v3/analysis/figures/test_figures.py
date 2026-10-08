"""Fast boundary and numeric tests; no native work, model calls or real outcomes."""
import json
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess
import sys

from extract import (EvidenceError, Reader, canonical, counter_partition, digest,
                     identity_check, load_pricer, measurement_eligible, observed_comparison,
                     operation_row, refined_pricing, usage_tables, checkpoint_usage,
                     select_measurements, audit_checkpoint_identity, historical_relative, strict_json, CAMPAIGNS)

HERE = Path(__file__).resolve().parent


def counters(n):
    return {"inputTokens": n, "cachedInputTokens": n//2, "cacheWriteInputTokens": 0,
            "outputTokens": n//5, "reasoningOutputTokens": n//10, "totalTokens": n+n//5}


def host_export_fixture():
    """Focused raw Host.export schema; runner-only labels are deliberately absent."""
    checkpoint = json.loads((HERE/'fixtures/host-export-checkpoint.json').read_text())
    terminal = copy.deepcopy(checkpoint)
    terminal.update(runtime_source='official_direct_terminal_appserver', owner_status='complete',
                    sealed=True, accounting_complete=True)
    terminal['agents'][0]['state'] = 'completed'
    terminal['agents'][0]['token_usage']['observed_accounting_complete'] = True
    return checkpoint, terminal


def fixture_reader(root, files=None):
    """Authenticate a synthetic freeze only in tests; production CLI has no override."""
    freeze = {'status': 'frozen', 'campaign_count': 3, 'manifest': {'root': '/archive', 'files': files or {}}}
    raw = canonical(freeze); path = root/'state/freeze.json'; path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return Reader(root, expected_freeze=digest(raw))


class FigureEvidenceTests(unittest.TestCase):
    def test_counter_subsets_are_not_additions(self):
        total = counters(100)
        self.assertEqual(counter_partition(total)["totalTokens"], 120)
        total["totalTokens"] += 50
        with self.assertRaises(EvidenceError):
            counter_partition(total)

    def test_setup_cannot_enter_measured_cohort(self):
        state = {"stage": "setup", "campaign_id": "campaign-1", "status": "complete", "endpoint": {"sealed_unix": 1}}
        with self.assertRaises(EvidenceError):
            identity_check(state, "campaign-1")
        state["stage"] = "measured"; state["status"] = "investigating"
        self.assertFalse(identity_check(state, "campaign-1"))
        state["status"] = "incomplete"
        self.assertTrue(identity_check(state, "campaign-1"))

    def test_overlap_invalidation_suppresses_retained_scores(self):
        op = {"operation": "bench", "status": "infra_error", "portfolio_speedup": 99,
              "descriptive_bootstrap": {"one_sided_lower_bound": 90},
              "measurement_invalidated": "competing_study_command_execution",
              "ordinary_command_overlap_audit": {"status": "invalid_overlap"},
              "started_unix": 1, "finished_unix": 2}
        self.assertFalse(measurement_eligible(op))
        row = operation_row("campaign-3", "synthetic-invalidated", op, 0)
        self.assertIsNone(row["portfolio_speedup"])
        self.assertIsNone(row["one_sided90_lower"])
        self.assertEqual(row["measurement_invalidated"], "competing_study_command_execution")
        op["status"] = "pass"
        self.assertFalse(measurement_eligible(op))
        # No reader call: retained raw files cannot supply an invalidated value.
        self.assertEqual(observed_comparison(None, None, op, "campaign-3", "synthetic", "development", 10,
            source_hash="synthetic", reference_hash="seed", context="test"), ([], [], None))

    def test_incomplete_replay_falls_back_without_invented_complete_cost(self):
        total = counters(100)
        update = {"classification": "cumulative_usage_change", "total": total, "delta": total, "last": total,
                  "turn_id": "synthetic-turn", "observed_unix_seconds": 2, "elapsed_from_host_start_seconds": 1}
        ledger = {"accounting_complete": False, "total_tokens": total, "known_thread_totals": total,
                  "per_role_tokens": {"lead": total}, "agents": [{"agent_id": "synthetic-agent", "thread_id": "synthetic-thread",
                    "role": "lead", "model": "gpt-6.1-sol", "state": "interrupted", "terminal_turn_statuses": {"synthetic-turn": "interrupted"},
                    "token_usage": {"total": total, "updates": [update], "issues": [], "turns_without_usage": [], "observed_accounting_complete": False}}]}
        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            path = Path(tmp)/"synthetic-telemetry.json"; path.write_text(json.dumps(ledger))
            report, reason = refined_pricing(HERE.parent.parent, path, observed_complete=False)
            self.assertIsNone(report)
            self.assertIn("frozen broad scenarios used", reason)

    def test_reader_rejects_hidden_inputs_and_messages(self):
        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            root = Path(tmp)
            for name in ("evaluation/hidden/input.json", "campaigns/campaign-1/messages.json"):
                path = root/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text("{}")
                with self.assertRaises(EvidenceError):
                    Reader(root).read(path)

    def test_pending_cohort_writes_status_only(self):
        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            root = Path(tmp); study = root/"empty-study"; study.mkdir()
            out = root/"status-output"
            result = subprocess.run([sys.executable, str(HERE/"extract.py"), "--study-root", str(study), "--out", str(out)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            data = json.loads((out/"figure-data.json").read_text())
            self.assertFalse(data["cohort_terminal"])
            self.assertEqual(set(data["tables"]), {"campaigns"})
            self.assertEqual(len(data["tables"]["campaigns"]), 3)

    def test_event_chain_rejects_changed_payload(self):
        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            root = Path(tmp); directory = root/"campaigns/campaign-1/authority/events"
            directory.mkdir(parents=True)
            row = {"sequence": 1, "previous": None, "payload": {"status": "pass"}}
            encoded = canonical(row); (directory/"00000001.json").write_bytes(encoded)
            reader = Reader(root)
            self.assertEqual(len(reader.chain(directory, expected_head=digest(encoded))), 1)
            row["payload"]["status"] = "fail"
            (directory/"00000001.json").write_bytes(canonical(row))
            with self.assertRaises(EvidenceError):
                reader.chain(directory, expected_head=digest(encoded))

    def test_duplicate_thread_is_not_double_counted(self):
        pricer, _ = load_pricer(HERE.parent.parent)
        agent = {"thread_id": "fixture-thread", "role": "lead", "model": "gpt-6.1-sol", "token_usage": {"total": counters(100)}}
        with self.assertRaises(EvidenceError):
            usage_tables({"agents": [agent, agent]}, "campaign-1", 0, pricer)

    def test_missing_usage_is_unknown(self):
        pricer, _ = load_pricer(HERE.parent.parent)
        ledger = {"agents": [{"thread_id": "known", "role": "lead", "model": "gpt-6.1-sol", "token_usage": {"total": counters(100)}},
                             {"thread_id": "missing", "role": "reviewer", "model": "gpt-6.1-sol", "token_usage": {"total": None}}]}
        threads, _, _, price = usage_tables(ledger, "campaign-1", 0, pricer)
        self.assertIsNone(threads[1]["totalTokens"])
        self.assertFalse(threads[1]["usage_present"])
        self.assertFalse(price["observed_accounting_complete"])
        self.assertIsNone(price["whole_run_cost_bounds"])
        self.assertEqual(len(price["missing_usage"]), 1)

    def test_plotting_guard_refuses_pending_and_unacknowledged_synthetic(self):
        from plot import render
        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            for data in ({"synthetic": False, "cohort_terminal": False}, {"synthetic": True, "cohort_terminal": True}):
                with self.assertRaises(EvidenceError):
                    render(data, Path(tmp))
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_duplicate_snapshot_and_context_estimate_do_not_increment(self):
        pricer, _ = load_pricer(HERE.parent.parent)
        total = counters(100)
        updates = [{"classification": kind, "total": total, "observed_unix_seconds": i+1}
                   for i, kind in enumerate(("cumulative_usage_change", "duplicate_snapshot", "context_estimate_no_usage_increment"))]
        ledger = {"agents": [{"thread_id": "fixture-thread", "role": "lead", "model": "gpt-6.1-sol",
                              "issues": ["compaction_observed"],
                              "token_usage": {"total": total, "updates": updates, "observed_accounting_complete": True}}],
                  "accounting_complete": True}
        threads, observations, curves, price = usage_tables(ledger, "campaign-1", 0, pricer)
        self.assertEqual(len(observations), 1)
        self.assertEqual(curves[-1]["totalTokens"], 120)
        self.assertTrue(threads[0]["remote_compaction_observed"])
        self.assertFalse(threads[0]["whole_model_work_verified"])
        self.assertIsNone(price["actual_billed_cost"])
        self.assertIsNone(price["whole_run_cost_bounds"])

    def test_complete_pair_evidence_and_rejection_of_missing_block(self):
        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            root = Path(tmp); directory = root/"campaigns/campaign-1/development/operations/synthetic"
            directory.mkdir(parents=True)
            pairs = {f"f{i}": [{"baseline": 2, "candidate": 1} for _ in range(10)] for i in range(6)}
            raw = [{"family": family, "block": block, "arm": arm, "driver": {"seconds_per_call": value, "sample_target_met": True}}
                   for family, rows in pairs.items() for block, pair in enumerate(rows) for arm, value in pair.items()]
            schedule = [{"block": b, "families": list(pairs), "orders": {f: (["baseline", "candidate"] if b%2 else ["candidate", "baseline"]) for f in pairs}} for b in range(10)]
            for name, value in (("paired.json", pairs), ("raw.json", raw), ("schedule.json", schedule)):
                (directory/name).write_text(json.dumps(value))
            result = {"status": "pass", "portfolio_speedup": 2, "family_speedups": {f:2 for f in pairs},
                      "descriptive_bootstrap": {"confidence": .9, "one_sided_lower_bound": 2, "seed": 1, "resamples": 1}}
            args = (Reader(root), directory, result, "campaign-1", "synthetic", "development", 10)
            samples, families, point = observed_comparison(*args, source_hash="fixture-source", reference_hash="fixture-seed", context="test")
            self.assertEqual((len(samples), len(families), point["ratio"]), (60, 6, 2))
            pairs["f0"].pop(); (directory/"paired.json").write_text(json.dumps(pairs))
            with self.assertRaises(EvidenceError):
                observed_comparison(*args, source_hash="fixture-source", reference_hash="fixture-seed", context="test")

    def test_final_artifacts_are_unreadable_until_complete_receipt(self):
        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            root = Path(tmp); path = root/'assessment/final/report.json'
            path.parent.mkdir(parents=True); path.write_text('{"status":"complete"}')
            reader = Reader(root)
            with self.assertRaises(EvidenceError): reader.read(path)
            states = {c: {'stage': 'measured', 'campaign_id': c, 'status': 'complete',
                          'endpoint': {'sealed_unix': 1}} for c in CAMPAIGNS}
            launch = root/'state/launch/status.json'; launch.parent.mkdir(parents=True)
            launch.write_text('{"status":"all_endpoints_sealed_final_assessment_owner_only"}')
            self.assertFalse(reader.release_final(states))
            with self.assertRaises(EvidenceError): reader.read(path)
            launch.write_text('{"status":"complete","assessment_status":"complete"}')
            self.assertTrue(reader.release_final(states))
            self.assertEqual(reader.read(path)['status'], 'complete')

    def test_checkpoint_artifact_hash_is_required_but_not_an_exact_coordinate(self):
        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            root = Path(tmp); relative = Path('campaigns/campaign-1/authority/checkpoint-usage/00000001.json')
            path = root/relative; path.parent.mkdir(parents=True)
            ledger, terminal = host_export_fixture()
            self.assertNotIn('runtime_source', ledger)
            self.assertNotIn('campaign_id', ledger)
            terminal_path = root/'campaigns/campaign-1/telemetry.json'
            terminal_path.write_bytes(canonical(terminal))
            raw = canonical(ledger); path.write_bytes(raw)
            row = {'usage_coordinate_complete': False, 'usage_evidence': {'path': '/archive/'+relative.as_posix(), 'sha256': digest(raw)}}
            pricer, _ = load_pricer(HERE.parent.parent)
            reader = fixture_reader(root)
            value = checkpoint_usage(reader, 'campaign-1', 1, row, pricer)
            self.assertEqual(value['checkpoint_observed_tokens'], 120)
            self.assertNotIn('tokens_coordinate', value)
            self.assertEqual(value['usage_evidence_sha256'], digest(raw))
            self.assertEqual(value['checkpoint_terminal_evidence_sha256'], digest(canonical(terminal)))
            self.assertEqual(value['checkpoint_identity_status'], 'anchored_artifact_and_terminal_host_agents_verified')
            row['usage_evidence']['sha256'] = 'wrong'
            with self.assertRaises(EvidenceError): checkpoint_usage(reader, 'campaign-1', 1, row, pricer)

    def test_checkpoint_identity_rejects_foreign_host_campaign_role_or_thread(self):
        checkpoint, terminal = host_export_fixture()
        for field, changed in (('started_unix_seconds', 1001), ('runtime_source', 'injected_test')):
            wrong = copy.deepcopy(terminal); wrong[field] = changed
            with self.assertRaises(EvidenceError): audit_checkpoint_identity(checkpoint, wrong, 'campaign-1', original_root='/archive')
        for field, changed in (('role', 'reviewer'), ('thread_id', 'other-thread'), ('model', 'other-model')):
            wrong = copy.deepcopy(terminal); wrong['agents'][0][field] = changed
            with self.assertRaises(EvidenceError): audit_checkpoint_identity(checkpoint, wrong, 'campaign-1', original_root='/archive')
        wrong = copy.deepcopy(terminal)
        wrong['artifact_reference_roots'] = [p.replace('campaign-1', 'campaign-2') for p in wrong['artifact_reference_roots']]
        with self.assertRaises(EvidenceError): audit_checkpoint_identity(checkpoint, wrong, 'campaign-1', original_root='/archive')

    def test_checkpoint_allows_later_agents_and_pending_thread_identity(self):
        checkpoint, terminal = host_export_fixture()
        extra = copy.deepcopy(terminal['agents'][0])
        extra.update(agent_id='agent-2', thread_id='fixture-thread-2', role='reviewer', parent_agent_id='agent-1')
        terminal['agents'].append(extra)
        checkpoint['agents'][0]['thread_id'] = None
        result = audit_checkpoint_identity(checkpoint, terminal, 'campaign-1', original_root='/archive')
        self.assertEqual(result['checkpoint_agent_count'], 1)
        self.assertEqual(result['checkpoint_thread_identity_pending'], 1)

    def test_missing_terminal_checkpoint_identity_retains_hash_without_scoring_usage(self):
        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            root = Path(tmp); relative = Path('campaigns/campaign-1/authority/checkpoint-usage/00000001.json')
            path = root/relative; path.parent.mkdir(parents=True)
            ledger, _ = host_export_fixture(); raw = canonical(ledger); path.write_bytes(raw)
            row = {'usage_coordinate_complete': False, 'usage_evidence': {'path': '/archive/'+relative.as_posix(), 'sha256': digest(raw)}}
            pricer, _ = load_pricer(HERE.parent.parent)
            value = checkpoint_usage(fixture_reader(root), 'campaign-1', 1, row, pricer)
            self.assertEqual(value['usage_evidence_sha256'], digest(raw))
            self.assertEqual(value['checkpoint_identity_status'], 'unverified_terminal_telemetry_unavailable')
            self.assertIsNone(value['checkpoint_observed_tokens'])

    def test_relocation_uses_authenticated_origin_and_preserves_evidence_bytes(self):
        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            root = Path(tmp); reader = fixture_reader(root)
            relative = 'campaigns/campaign-1/authority/checkpoint-usage/00000001.json'
            path = root/relative; path.parent.mkdir(parents=True)
            payload = b'{ "unchanged_spacing": true }\n'; path.write_bytes(payload)
            self.assertNotEqual(str(root), '/archive')
            self.assertEqual(reader.historical_relative('/archive/'+relative), relative)
            self.assertEqual(reader.read(reader.historical_relative('/archive/'+relative)), {'unchanged_spacing': True})
            self.assertEqual(path.read_bytes(), payload)
            self.assertEqual(reader.sources[relative]['sha256'], digest(payload))
            with self.assertRaises(EvidenceError): reader.historical_relative('/untrusted/'+relative)
            with self.assertRaises(EvidenceError): Reader(root).authenticate_origin()

    def test_relocation_refuses_noncanonical_private_or_outside_paths(self):
        for path in ('//archive/campaigns/x', '/archive//campaigns/x', '/archive/./campaigns/x',
                     '/archive/../campaigns/x', '/archive\\campaigns/x', '/archive/.aws/x',
                     '/archive/sessions/x', '/archive/auth.json', '/archive-other/campaigns/x', 'campaigns/x'):
            with self.subTest(path=path):
                with self.assertRaises(EvidenceError): historical_relative(path, '/archive')

    def test_pricer_authenticates_freeze_and_code_bytes_before_execution(self):
        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            root = Path(tmp); target = root/'runtime/pricing.py'; target.parent.mkdir()
            trusted = b'FIXTURE_VALUE = 7\n'
            reader = fixture_reader(root, {'runtime/pricing.py': digest(trusted)})
            marker = root/'untrusted-executed'
            target.write_text(f'from pathlib import Path\nPath({str(marker)!r}).write_text("executed")\n')
            with self.assertRaises(EvidenceError): load_pricer(reader)
            self.assertFalse(marker.exists())
            target.write_bytes(trusted)
            with self.assertRaises(EvidenceError): load_pricer(Reader(root))
            module, provenance = load_pricer(reader)
            self.assertEqual(module.FIXTURE_VALUE, 7)
            self.assertEqual(provenance['sha256'], digest(trusted))
            self.assertEqual(provenance['freeze_sha256'], reader.expected_freeze)

    def test_pricer_rejects_parent_directory_symlink(self):
        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            root = Path(tmp); real = root/'real-runtime'; real.mkdir()
            code = b'FIXTURE_VALUE = 7\n'; (real/'pricing.py').write_bytes(code)
            (root/'runtime').symlink_to(real, target_is_directory=True)
            reader = fixture_reader(root, {'runtime/pricing.py': digest(code)})
            with self.assertRaises(EvidenceError): load_pricer(reader)

    def test_reader_rejects_parent_symlink_even_with_target_inside_allowlist(self):
        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            root = Path(tmp); directory = root/'campaigns/campaign-1/authority'; real = directory/'real'; real.mkdir(parents=True)
            (real/'anchor.json').write_text('{}')
            (directory/'alias').symlink_to(real, target_is_directory=True)
            with self.assertRaises(EvidenceError): Reader(root).read(directory/'alias/anchor.json')
            (root/'aliased-study').symlink_to(root, target_is_directory=True)
            with self.assertRaises(EvidenceError): Reader(root/'aliased-study')

    def test_refined_pricing_ignores_evidence_root_code(self):
        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            root = Path(tmp); reader = fixture_reader(root)
            telemetry = root/'campaigns/campaign-1/telemetry.json'; telemetry.parent.mkdir(parents=True); telemetry.write_text('{}')
            marker = root/'untrusted-executed'; untrusted = root/'analysis/reprice_observed_usage.py'; untrusted.parent.mkdir()
            untrusted.write_text(f'from pathlib import Path\nPath({str(marker)!r}).write_text("executed")\n')
            trusted = root/'trusted-helper.py'
            code = (b'from pathlib import Path\nimport hashlib\ndef analyze(path):\n'
                    b'    return {"source_telemetry_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(), "used_trusted_fixture": True}\n')
            trusted.write_bytes(code)
            with patch('extract.TRUSTED_REPRICE_PATH', trusted), patch('extract.TRUSTED_REPRICE_SHA256', digest(code)):
                result, reason = refined_pricing(reader, telemetry, observed_complete=True)
            self.assertIsNone(reason)
            self.assertTrue(result['used_trusted_fixture'])
            self.assertFalse(marker.exists())
            self.assertEqual(result['analysis_code_sha256'], digest(code))

    def test_refined_pricing_rejects_changed_trusted_helper_before_execution(self):
        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            root = Path(tmp); reader = fixture_reader(root)
            marker = root/'untrusted-executed'; helper = root/'helper.py'
            helper.write_text(f'from pathlib import Path\nPath({str(marker)!r}).write_text("executed")\n')
            with patch('extract.TRUSTED_REPRICE_PATH', helper):
                with self.assertRaises(EvidenceError): refined_pricing(reader, root/'missing.json', observed_complete=True)
            self.assertFalse(marker.exists())

    def test_strict_json_rejects_duplicate_keys_and_nonfinite_numbers(self):
        for raw in ('{"status":"pass","status":"fail"}', '{"value":NaN}', '{"value":Infinity}', '{"value":1e999}'):
            with self.assertRaises(EvidenceError): strict_json(raw)

    @staticmethod
    def attempt(number, *, status='pass', source='candidate', mid='measurement'):
        row = {'operation_id': f'op-{number}', 'operation': 'bench', 'status': status,
            'source_hash': source, 'build_id': 'build', 'reference': {'source_hash': 'seed', 'library_sha256': 'seed-binary'},
            'measurement_id': mid, 'measurement_attempt_number': number, 'finish_sequence': number,
            'measurement_prior_attempt_ids': [f'op-{n}' for n in range(1, number)],
            'measurement_retry_reason': 'competing_study_command_execution' if number > 1 else None,
            'measurement_selection_rule': 'first_complete_valid_attempt',
            'measurement_retry_policy': 'infrastructure_only_first_valid_v1'}
        if status == 'infra_error':
            row.update(measurement_retry_authorized=True, measurement_invalidated='competing_study_command_execution',
                       ordinary_command_overlap_audit={'status': 'invalid_overlap', 'ordinary_command_overlaps': ['other']},
                       portfolio_speedup=99, descriptive_bootstrap={'one_sided_lower_bound': 90})
        return row

    def test_retry_selects_first_valid_even_when_unfavorable(self):
        first, second = self.attempt(1, status='infra_error'), self.attempt(2)
        second['portfolio_speedup'] = .6
        result = select_measurements({'op-1': first, 'op-2': second})
        self.assertFalse(result['op-1']['selected_for_scoring'])
        self.assertTrue(result['op-2']['selected_for_scoring'])
        first.update(started_unix=0, finished_unix=1)
        self.assertIsNone(operation_row('campaign-1', 'op-1', first, 0)['portfolio_speedup'])

    def test_retry_cannot_change_binding_or_follow_valid_result(self):
        for ops in ({'op-1': self.attempt(1, status='infra_error'), 'op-2': self.attempt(2, source='different')},
                    {'op-1': self.attempt(1), 'op-2': self.attempt(2)}):
            with self.assertRaises(EvidenceError): select_measurements(ops)

    def test_later_official_measurement_remains_process_only(self):
        first = self.attempt(1, mid='a'); later = self.attempt(1, mid='b')
        for row in (first, later): row.update(purpose='official_review', review_plan_id='plan')
        later.update(operation_id='later', finish_sequence=2)
        result = select_measurements({'op-1': first, 'later': later})
        self.assertTrue(result['op-1']['selected_for_scoring'])
        self.assertFalse(result['later']['selected_for_scoring'])

    def test_plotter_refuses_old_version_even_if_real_and_terminal(self):
        from plot import validate_bundle
        with self.assertRaises(EvidenceError):
            validate_bundle({'synthetic': False, 'cohort_terminal': True,
                             'study_version': 'unattended-optimization-v2'})


if __name__ == "__main__":
    unittest.main()
