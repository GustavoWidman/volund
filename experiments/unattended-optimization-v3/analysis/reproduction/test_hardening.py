"""Writer-shaped, synthetic consistency checks; no native processes or live reads."""
import copy
import hashlib
import random
import tempfile
from pathlib import Path
import unittest
from evidence import Refusal, digest, encoded, pin, read
from replay_numeric import Archive, audit_final, audit_sample_files, reduce_pairs
from test_reproduction import put


def native_fixture(root):
    origin = "/historical/study"
    directory = "campaigns/campaign-1/development/operations/bench"
    build_dir = "campaigns/campaign-1/development/operations/build"
    base_dir = "campaigns/campaign-1/development/operations/seed"
    for path in (build_dir, base_dir):
        target = root / path / "candidate.so"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"synthetic library")
        put(root, path + "/result.json", {"library": "candidate.so", "library_sha256": digest(b"synthetic library")})
    fixtures = "setup/launch-native/public-fixtures"
    items = [{"id": f"f{i}", "input": f"f{i}.bin", "expected": f"f{i}-expected.bin",
              "sha256_input": "a"*64, "sha256_expected": "b"*64} for i in range(6)]
    manifest = put(root, fixtures + "/manifest.json", {"suites": {"development": items}})
    config = {"driver": origin + "/setup/launch-native/driver", "fixtures": origin + "/" + fixtures,
              "paired_blocks": 10, "maximum_repetitions": 8, "minimum_sample_seconds": .05, "warmups": 1,
              "ordinary": {"observed_rss_kib": 1024, "cpus": [1, 2]}, "order_seed": 5,
              "benchmark_suite": "development", "bootstrap_resamples": 19, "bootstrap_seed": 11,
              "bootstrap_one_sided_confidence": .9, "pinned_files": {origin + "/" + fixtures + "/manifest.json": pin(root, fixtures + "/manifest.json")["sha256"]}}
    for item in items:
        for field in ("input", "expected"):
            config["pinned_files"][config["fixtures"] + "/" + item[field]] = item["sha256_" + field]
    put(root, "setup/launch-native/native-config.json", config)
    libraries = {"baseline": origin + "/" + base_dir + "/candidate.so", "candidate": origin + "/" + build_dir + "/candidate.so"}
    def driver(arm, count):
        per_call = .05 if arm == "baseline" else .025
        return {"repetitions": count, "verified_calls": count + 1, "elapsed_seconds": per_call * count,
                "seconds_per_call": per_call, "peak_rss_kib": 100, "sample_target_met": per_call * count >= .05}
    def command(sub, item, arm, count=None):
        argv = [config["driver"], "--library", libraries[arm], "--input", config["fixtures"] + "/" + item["input"],
                "--expected", config["fixtures"] + "/" + item["expected"], "--mode", "benchmark", "--min-seconds", ".05",
                "--max-repetitions", "8", "--warmups", "1"]
        argv[argv.index("--min-seconds") + 1] = str(config["minimum_sample_seconds"])
        if count is not None:
            argv.extend(["--repetitions", str(count)])
        put(root, directory + "/" + sub + "/command.json", {"command": argv, "status": "pass", "exit_code": 0,
            "process_started": True, "peak_rss_kib": 100, "cleanup": {"tracked_processes_exited": True}, "limits": config["ordinary"]})
    orders, calibration = {}, {}
    for item in items:
        name = item["id"]
        calibration[name] = {"pilot_repetitions": {"baseline": 2, "candidate": 2}, "common_repetitions": 2}
        for arm in libraries:
            sub = name + "/calibrate-" + arm
            put(root, directory + "/" + sub + "/stdout.txt", driver(arm, 2))
            command(sub, item, arm)
        sequence = [["baseline", "candidate"], ["candidate", "baseline"]] * 5
        random.Random(5 + int(hashlib.sha256(name.encode()).hexdigest()[:8], 16)).shuffle(sequence)
        orders[name] = sequence
    put(root, directory + "/calibration.json", calibration)
    rng, schedule = random.Random(5), []
    for block in range(10):
        families = [item["id"] for item in items]
        rng.shuffle(families)
        schedule.append({"block": block, "families": families, "orders": {name: orders[name][block] for name in families}})
    raw, pairs = [], {item["id"]: [] for item in items}
    by_id = {item["id"]: item for item in items}
    for row in schedule:
        block = row["block"]
        for name in row["families"]:
            pairs[name].append({"baseline": .05, "candidate": .025})
            for arm in row["orders"][name]:
                sub = f"{name}/block-{block:02d}-{arm}"
                record = {"family": name, "block": block, "arm": arm, "driver": driver(arm, 2), "command": sub + "/command.json"}
                raw.append(record)
                put(root, directory + "/" + sub + "/measurement.json", record)
                command(sub, by_id[name], arm, 2)
    bootstrap = {"resamples": 19, "seed": 11, "confidence": .9, "one_sided_lower_bound": 2.0}
    put(root, directory + "/descriptive-bootstrap.json", bootstrap)
    result = {"build_id": "build", "paired_blocks": 10, "descriptive_bootstrap": bootstrap,
              "reference": {"path": libraries["baseline"], "library_sha256": digest(b"synthetic library")},
              "scored_under_target_policy": "retain_and_flag_no_adaptive_retry", "scored_under_target_batches": []}
    return directory, result, pairs, raw, schedule


def archive(root):
    files = {p.relative_to(root).as_posix(): pin(root, p.relative_to(root).as_posix()) for p in root.rglob("*") if p.is_file()}
    return Archive(root, {"files": files, "omitted_full_archive_files": {}, "original_study_root": "/historical/study"})


def final_fixture(root, *, wrong_source=False, wrong_binary=False, foreign_configuration=False):
    put(root, "task/seed/source.json", {"synthetic": True})
    seed = digest(encoded({"source.json": pin(root, "task/seed/source.json")["sha256"]}))
    states, endpoints, configurations = {}, [], {}
    for i in range(1, 4):
        campaign = f"campaign-{i}"
        state = {"status": "incomplete", "endpoint": {"source_hash": None}, "seed": None}
        states[campaign] = state
        state_path = f"campaigns/{campaign}/authority/state.json"
        anchor_path = f"campaigns/{campaign}/authority/anchor.json"
        put(root, state_path, state)
        put(root, anchor_path, {"test_only": True})
        endpoints.append({"campaign_id": campaign, "campaign_status": "incomplete", "endpoint": state["endpoint"],
                          "state_sha256": pin(root, state_path)["sha256"], "anchor_sha256": pin(root, anchor_path)["sha256"]})
    for stratum in ("transfer", "shift"):
        relative = f"setup/final-evaluator-config-{stratum}.json"
        put(root, relative, {"synthetic": stratum})
        configurations[stratum] = pin(root, relative)["sha256"]
    if foreign_configuration:
        configurations["transfer"] = "e"*64
    operations = []
    library_hash = digest(b"synthetic binary")
    for op_id, kind in (("seed/build", "build"), ("seed/memory", "memcheck")):
        directory = "assessment/final/" + op_id
        if kind == "build":
            path = root / directory / "candidate.so"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic binary")
        row = {"operation_id": op_id, "artifact_directory": op_id, "operation": kind, "status": "pass",
               "source_hash": "f"*64 if wrong_source and kind == "memcheck" else seed,
               "stratum": "transfer", "configuration_sha256": configurations["transfer"],
               "input_library_sha256": None if kind == "build" else "c"*64 if wrong_binary else library_hash,
               "reference": None}
        if kind == "build":
            row.update(library="candidate.so", library_sha256=library_hash)
        for name in ("integrity-before.json", "integrity-after.json"):
            put(root, directory + "/" + name, {"configuration_sha256": configurations["transfer"]})
        put(root, directory + "/result.json", row)
        files = {p.relative_to(root / directory).as_posix(): pin(root, p.relative_to(root).as_posix())["sha256"]
                 for p in (root / directory).iterdir()}
        put(root, directory + "/files.json", {"files": files})
        operations.append({**row, "files_manifest": op_id + "/files.json",
                           "files_manifest_sha256": pin(root, directory + "/files.json")["sha256"]})
    put(root, "assessment/final/report.json", {"status": "blocked", "operations": operations, "rows": [], "endpoints": endpoints,
                                               "configuration_hashes": configurations})
    return states


class NativeReceiptTests(unittest.TestCase):
    def test_writer_shaped_consistency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = native_fixture(root)
            audit_sample_files(archive(root), *args)

    def test_conflicting_redundant_files_are_not_hidden_by_fresh_hashes(self):
        mutations = ("measurement", "command", "calibration", "bootstrap", "verified_calls", "rss", "target_flag")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                directory, result, pairs, raw, schedule = native_fixture(root)
                first = raw[0]
                if mutation in {"measurement", "verified_calls", "rss", "target_flag"}:
                    relative = directory + "/" + first["command"].replace("command.json", "measurement.json")
                    value = read(root, relative)
                    if mutation == "measurement":
                        value["driver"]["seconds_per_call"] *= 2
                    else:
                        key, changed = {"verified_calls": ("verified_calls", 999), "rss": ("peak_rss_kib", 999999), "target_flag": ("sample_target_met", False)}[mutation]
                        value["driver"][key] = changed
                        first["driver"][key] = changed
                    put(root, relative, value)
                elif mutation == "command":
                    relative = directory + "/" + first["command"]
                    value = read(root, relative)
                    value["exit_code"] = 1
                    put(root, relative, value)
                elif mutation == "calibration":
                    relative = directory + "/calibration.json"
                    value = read(root, relative)
                    value["f0"]["common_repetitions"] = 3
                    put(root, relative, value)
                else:
                    put(root, directory + "/descriptive-bootstrap.json", {**result["descriptive_bootstrap"], "seed": 99})
                with self.assertRaises(Refusal):
                    audit_sample_files(archive(root), directory, result, pairs, raw, schedule)

    def test_final_config_source_and_nonbuild_library_bindings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            states = final_fixture(root)
            result, _ = audit_final(archive(root), states)
            self.assertTrue(result["seed_build_recorded"])
        for field in ("wrong_source", "wrong_binary", "foreign_configuration"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                states = final_fixture(root, **{field: True})
                with self.assertRaises(Refusal):
                    audit_final(archive(root), states)

    def test_blocked_before_seed_build_is_explicit_not_run_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            put(root, "task/seed/source.json", {"synthetic": True})
            states, endpoints = {}, []
            for i in range(1, 4):
                campaign = f"campaign-{i}"
                state = {"status": "incomplete", "endpoint": {"source_hash": None}, "seed": None}
                states[campaign] = state
                state_path = f"campaigns/{campaign}/authority/state.json"
                anchor_path = f"campaigns/{campaign}/authority/anchor.json"
                put(root, state_path, state)
                put(root, anchor_path, {"test_only": True})
                endpoints.append({"campaign_id": campaign, "campaign_status": "incomplete", "endpoint": state["endpoint"],
                                  "state_sha256": pin(root, state_path)["sha256"], "anchor_sha256": pin(root, anchor_path)["sha256"]})
            configurations = {}
            for stratum in ("transfer", "shift"):
                relative = f"setup/final-evaluator-config-{stratum}.json"
                put(root, relative, {"synthetic": stratum})
                configurations[stratum] = pin(root, relative)["sha256"]
            put(root, "assessment/final/report.json", {"status": "blocked", "operations": [], "rows": [], "endpoints": endpoints,
                                                       "configuration_hashes": configurations})
            result, comparisons = audit_final(archive(root), states)
            self.assertEqual(result["status"], "blocked")
            self.assertFalse(result["seed_build_recorded"])
            self.assertEqual(comparisons, [])

    def test_joint_temporal_block_resampling_preserves_anticorrelation(self):
        pairs = {"a": [{"baseline": x, "candidate": 1} for x in (.5, 1, 2)],
                 "b": [{"baseline": x, "candidate": 1} for x in (2, 1, .5)]}
        result = reduce_pairs(pairs, 101, 123, .9)
        self.assertEqual(result["portfolio_speedup"], 1.0)
        self.assertEqual(result["one_sided_lower_bound"], 1.0)


if __name__ == "__main__":
    unittest.main()
