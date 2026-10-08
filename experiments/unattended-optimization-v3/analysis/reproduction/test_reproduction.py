"""Tiny synthetic-only regressions. No live study, native process, or model access.

Prepared during measurements; do not run until the owner releases validation.
"""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import evidence
from evidence import (Refusal, CAMPAIGNS, FROZEN_AREAS, digest, encoded, historical_relative,
                      make_plan, package, read, release_gate, sha, verify_bundle, write_new)
from replay_numeric import (Archive, audit_usage, measurement_eligible, numeric_operation,
                            reduce_pairs, select_measurements, validate_raw)
from remap_native_config import PATH_FIELDS, remap, require_outside_historical
from native_replay import validate_replay_config


def put(root, relative, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded(value))
    return path


def fixture(root):
    for area in FROZEN_AREAS:
        (root / area).mkdir(parents=True, exist_ok=True)
    put(root, "owner/config.json", {"test_only": True})
    put(root, "setup/readiness.json", {"test_only": True})
    put(root, "setup/preflight.json", {"test_only": True})
    files = {"owner/config.json": sha(root / "owner/config.json")}
    freeze = {"status": "frozen", "campaign_count": 3,
              "manifest": {"root": "/historical/study", "files": files, "sha256": digest(encoded(files))},
              "runtime_artifacts": {"/usr/bin/example-compiler": "a"*64},
              "readiness_path": "/historical/study/setup/readiness.json", "readiness_sha256": sha(root / "setup/readiness.json"),
              "preflight_path": "/historical/study/setup/preflight.json", "preflight_sha256": sha(root / "setup/preflight.json")}
    put(root, "state/freeze.json", freeze)
    for name in CAMPAIGNS:
        put(root, f"campaigns/{name}/authority/state.json", {"campaign_id": name, "stage": "measured", "status": "complete",
            "endpoint": {"sealed_unix": 1, "stopping_reason": "task_complete"}})
        put(root, f"campaigns/{name}/telemetry.json", {"sealed": True})
    put(root, "assessment/final/report.json", {"status": "complete", "finished_unix": 2,
        "planned_campaigns": list(CAMPAIGNS), "fixed_source_no_reselection": True, "operations": []})
    put(root, "state/launch/status.json", {"status": "complete"})
    return sha(root / "state/freeze.json")


def attempt(number, *, status="pass", previous=(), reason=None):
    row = {"operation_id": f"b{number}", "operation": "bench", "status": status, "finish_sequence": number,
           "measurement_id": "m1", "measurement_attempt_number": number, "measurement_prior_attempt_ids": list(previous),
           "measurement_retry_reason": reason, "measurement_retry_policy": "infrastructure_only_first_valid_v1",
           "measurement_selection_rule": "first_complete_valid_attempt", "source_hash": "a"*64,
           "build_id": "build", "reference": {"source_hash": "b"*64}, "purpose": "exploratory"}
    if status == "infra_error":
        row.update(measurement_retry_authorized=True, measurement_invalidated="competing_study_command_execution",
                   ordinary_command_overlap_audit={"status": "invalid_overlap", "ordinary_command_overlaps": [{"id": "cmd1"}]})
    return row


def pairs_fixture():
    pairs = {f"f{i}": [{"baseline": 2.0, "candidate": 1.0} for _ in range(10)] for i in range(6)}
    raw, schedule = [], []
    for block in range(10):
        order = ["baseline", "candidate"] if block % 2 == 0 else ["candidate", "baseline"]
        schedule.append({"block": block, "families": list(pairs), "orders": {name: order for name in pairs}})
        for name in pairs:
            for arm in order:
                raw.append({"family": name, "block": block, "arm": arm,
                            "driver": {"seconds_per_call": pairs[name][block][arm], "sample_target_met": False}})
    return pairs, raw, schedule


class PackagingTests(unittest.TestCase):
    def test_gate_refuses_before_final_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = fixture(root)
            put(root, "state/launch/status.json", {"status": "running"})
            seen = []
            def guarded(root, relative):
                seen.append(relative)
                return read(root, relative)
            with patch.object(evidence, "read", side_effect=guarded), self.assertRaises(Refusal):
                release_gate(root, expected)
            self.assertNotIn("assessment/final/report.json", seen)

    def test_full_and_lean_have_shared_commitment_and_distinct_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "study"
            expected = fixture(root)
            binary = root / "campaigns/campaign-1/development/operations/b/candidate.so"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"test binary placeholder")
            put(root, "campaigns/campaign-1/development/operations/b/result.json", {"status": "candidate_failure"})
            plans = [make_plan(root, expected, mode=mode) for mode in ("archive", "git")]
            self.assertEqual(plans[0]["complete_allowed_inventory_sha256"], plans[1]["complete_allowed_inventory_sha256"])
            self.assertIn(binary.relative_to(root).as_posix(), plans[1]["omitted_full_archive_files"])
            self.assertIn("campaigns/campaign-1/development/operations/b/result.json", plans[1]["files"])
            for index, plan in enumerate(plans):
                path = put(base, f"plan-{index}.json", plan)
                bundle = base / f"bundle-{index}"
                package(root, path, bundle, sha(path), expected_freeze=expected)
                result = verify_bundle(bundle, sha(path), expected_freeze=expected)
                self.assertEqual(result["status"], "verified_present_bytes")
                put(bundle / "study", "setup/preflight.json", {"changed": True})
                with self.assertRaises(Refusal):
                    verify_bundle(bundle, sha(path), expected_freeze=expected)

    def test_blocked_final_record_never_authorizes_native_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "study"
            expected = fixture(root)
            report = read(root, "assessment/final/report.json")
            report["status"] = "blocked"
            put(root, "assessment/final/report.json", report)
            path = put(base, "plan.json", make_plan(root, expected))
            bundle = base / "bundle"
            result = package(root, path, bundle, sha(path), expected_freeze=expected)
            self.assertFalse(result["scientific_result_release"])

    def test_private_and_raw_subtrees_not_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = fixture(root)
            for relative in ("setup/.codex/auth.json", "setup/raw-remotes/response.json", "campaigns/campaign-1/scratch/private.txt"):
                put(root, relative, {"not_read": True})
            plan = make_plan(root, expected)
            self.assertFalse(any(".codex" in p or "raw-remotes" in p or "/scratch/" in p for p in plan["files"]))

    def test_extra_file_private_stream_and_wrong_freeze_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "study"
            expected = fixture(root)
            plan = make_plan(root, expected)
            path = put(base, "plan.json", plan)
            bundle = base / "bundle"
            with self.assertRaises(Refusal):
                package(root, path, bundle, sha(path))
            package(root, path, bundle, sha(path), expected_freeze=expected)
            put(bundle / "study", "unrelated.json", {})
            with self.assertRaises(Refusal):
                verify_bundle(bundle, sha(path), expected_freeze=expected)
            trace = put(root, "campaigns/campaign-1/runtime/agent-1.jsonl", {"thread_id": "t", "turn_id": "u",
                "item": {"type": "reasoning", "text": "synthetic marker"}})
            with self.assertRaises(Refusal):
                evidence.trace_check(trace)

    def test_canonical_relocation_no_path_guessing(self):
        self.assertEqual(historical_relative("/old/study/campaigns/campaign-1/a.json", "/old/study"), "campaigns/campaign-1/a.json")
        self.assertIsNone(historical_relative("/elsewhere/study/campaigns/campaign-1/a.json", "/old/study"))
        self.assertIsNone(historical_relative("/public-tools/node_modules/example/bin/tool", "/old/study"))
        for path in ("/old/study/../a.json", "/old/study//a.json", "/old/study/./a.json", "/old/study/.codex/a.json", "/external/.codex/auth.json", "/old/study/node_modules/example/tool", "/old/study/new\nline", "/old/study/C:drive"):
            with self.assertRaises(Refusal):
                historical_relative(path, "/old/study")

    def test_duplicate_json_and_budget_refused(self):
        with self.assertRaises(Refusal):
            evidence.loads('{"a":1,"a":2}')
        with self.assertRaises(Refusal):
            evidence.loads('{"a":NaN}')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = fixture(root)
            with self.assertRaises(Refusal):
                make_plan(root, expected, mode="git", max_git_bytes=1)


class ReplayTests(unittest.TestCase):
    def test_invalid_attempt_retained_and_first_valid_selected(self):
        a = attempt(1, status="infra_error")
        a["portfolio_speedup"] = 900
        b = attempt(2, previous=("b1",), reason="competing_study_command_execution")
        b["portfolio_speedup"] = .5
        result = select_measurements({"b1": a, "b2": b})
        self.assertFalse(result["b1"]["selected_for_scoring"])
        self.assertTrue(result["b2"]["selected_for_scoring"])
        self.assertIsNone(numeric_operation(None, "unopened", result["b1"], 10))

    def test_retry_cannot_change_inputs_or_follow_valid_observation(self):
        a = attempt(1, status="infra_error")
        b = attempt(2, previous=("b1",), reason="competing_study_command_execution")
        for key, value in (("source_hash", "changed"), ("build_id", "changed"), ("measurement_prior_attempt_ids", [])):
            changed = copy.deepcopy(b)
            changed[key] = value
            with self.assertRaises(Refusal):
                select_measurements({"b1": copy.deepcopy(a), "b2": changed})
        with self.assertRaises(Refusal):
            select_measurements({"b1": attempt(1), "b2": b})
        a["confirmed_semantic_failure"] = True
        with self.assertRaises(Refusal):
            select_measurements({"b1": a, "b2": b})

    def test_raw_pair_schedule_and_bootstrap(self):
        pairs, raw, schedule = pairs_fixture()
        validate_raw(pairs, raw, schedule, 10)
        replay = reduce_pairs(pairs, 13, 1, .9)
        self.assertEqual(replay["portfolio_speedup"], 2.0)
        self.assertEqual(replay["one_sided_lower_bound"], 2.0)
        raw[0]["driver"]["seconds_per_call"] = 99
        with self.assertRaises(Refusal):
            validate_raw(pairs, raw, schedule, 10)

    def test_raw_temporal_order_and_arm_balance(self):
        pairs, raw, schedule = pairs_fixture()
        raw[0], raw[1] = raw[1], raw[0]
        with self.assertRaises(Refusal):
            validate_raw(pairs, raw, schedule, 10)
        pairs, raw, schedule = pairs_fixture()
        schedule[0]["families"].append("f0")
        with self.assertRaises(Refusal):
            validate_raw(pairs, raw, schedule, 10)

    def test_unknown_cache_writes_and_missing_usage_never_zero_filled(self):
        from replay_numeric import COUNTERS, sum_counters
        total = dict(zip(COUNTERS, (10, 3, None, 5, 2, 15)))
        update = {"total": total, "delta": total, "duplicate": False, "classification": "cumulative_usage_change"}
        a = {"agent_id": "a", "thread_id": "t", "role": "lead", "token_usage": {"total": total, "updates": [update], "issues": [], "turns_without_usage": []}}
        missing = {"agent_id": "b", "thread_id": "u", "role": "lead", "token_usage": {"total": None}}
        aggregate = sum_counters([total, None])
        ledger = {"agents": [a, missing], "known_thread_totals": aggregate, "total_tokens": aggregate,
                  "per_role_tokens": {"lead": aggregate}, "accounting_complete": False}
        result = audit_usage(ledger)
        self.assertEqual(result["observed_subtotal_tokens"], 15)
        self.assertIsNone(result["all_admitted_thread_counters"]["totalTokens"])
        self.assertIsNone(result["threads"][0]["reported_counters"]["cacheWriteInputTokens"])
        self.assertIsNone(result["threads"][0]["unknown_remote_compaction_cost"])

    def test_source_and_fixture_pins_cannot_be_rehashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            new = Path(tmp)
            source = new / "source.py"
            source.write_text("# source\n")
            config = {key: "/old/" + key for key in PATH_FIELDS}
            config.update(ordinary={"cpus": [4, 5]}, diagnostic={"cpus": [4, 5]}, paired_blocks=30,
                          pinned_files={"/old/source.py": sha(source)})
            mapped, receipt = remap(config, [{"from": "/old", "to": str(new)}], [1, 2], immutable_pins=config["pinned_files"])
            self.assertEqual(mapped["paired_blocks"], 30)
            self.assertEqual(len(receipt["immutable_source_and_fixture_pins_verified"]), 1)
            source.write_text("# changed\n")
            with self.assertRaises(Refusal):
                remap(config, [{"from": "/old", "to": str(new)}], [1, 2], rehash=True, immutable_pins=config["pinned_files"])


if __name__ == "__main__":
    unittest.main()
