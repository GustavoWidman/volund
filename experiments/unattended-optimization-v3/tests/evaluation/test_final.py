"""Synthetic embargo/provenance/failure tests; no inference or native timing."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from development.core import IntegrityError, digest, encoded, file_hash, tree
from evaluation.run import assess, audit_endpoint, verify_embargo
from evaluation.prepare import definitions, SHIFTS


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded(value))


class FakeBackend:
    calls = []
    fail = None
    mutate = False
    mutate_binary = False
    failing_correctness_suite = None

    def __init__(self, config):
        self.config = config
        self.config_hash = "test-" + config.benchmark_suite

    def verify(self):
        return {"status": "pass"}

    def execute(self, kind, context, output):
        self.calls.append((kind, self.config.benchmark_suite))
        context["check_active"]()
        if self.fail == kind:
            raise RuntimeError("synthetic execution failure")
        if kind == "build":
            (output / "candidate.so").write_bytes(b"synthetic-build")
            return {"status": "pass", "library": "candidate.so"}
        if kind == "bench":
            if self.mutate:
                (context["source_directory"] / "engine.cpp").write_text("changed")
            if self.mutate_binary and self.config.benchmark_suite == "shift":
                (context["build_directory"] / context["build"]["library"]).write_bytes(b"changed-binary")
            return {"status": "pass", "portfolio_speedup": 1.1,
                    "family_speedups": {"example": 1.1}, "descriptive_bootstrap": {}}
        if (kind == "test" and self.config.correctness_suite == self.failing_correctness_suite
                and (context["source_directory"] / "engine.cpp").read_text().startswith("candidate")):
            return {"status": "candidate_failure"}
        return {"status": "pass"}


class FinalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.seed = self.root / "task/seed"
        self.seed.mkdir(parents=True)
        (self.seed / "engine.cpp").write_text("seed")
        self.paths = []
        for i in range(1, 4):
            campaign = self.root / "campaigns" / f"campaign-{i}"
            work = campaign / "work"
            work.mkdir(parents=True)
            (work / "engine.cpp").write_text("candidate-" + str(i))
            h = digest(encoded(tree(work)))
            source = campaign / "development/snapshots" / h
            source.parent.mkdir(parents=True)
            work.rename(source)
            library = campaign / "retained.so"
            library.write_bytes(b"retained-" + str(i).encode())
            endpoint = {"source_hash": h, "library_path": str(library),
                        "library_sha256": file_hash(library), "sealed_unix": 1,
                        "stopping_reason": "task_complete", "final_assessment_released": False}
            state = {"campaign_id": campaign.name, "stage": "measured", "status": "complete",
                     "incumbent": copy.deepcopy(endpoint), "endpoint": endpoint}
            self.state(campaign, state)
            self.paths.append(campaign)
        self.configs = {name: SimpleNamespace(benchmark_suite=name, correctness_suite=name,
             paired_blocks=30, compiler="fixed", contract_directory="fixed", driver="fixed",
             ordinary="fixed", diagnostic="fixed") for name in ("transfer", "shift")}
        FakeBackend.calls, FakeBackend.fail, FakeBackend.mutate = [], None, False
        FakeBackend.mutate_binary, FakeBackend.failing_correctness_suite = False, None

    def tearDown(self):
        self.tmp.cleanup()

    def state(self, campaign, value):
        h = digest(encoded(value))
        event = {"sequence": 1, "previous": None, "state_hash": h}
        path = campaign / "authority/events/00000001.json"
        write(path, event)
        write(campaign / "authority/state.json", value)
        write(campaign / "authority/anchor.json", {"count": 1, "head": file_hash(path), "state_hash": h})

    def run_assessment(self):
        with patch("evaluation.run.NativeBackend", FakeBackend):
            return assess(self.root, self.paths, self.configs, self.root / "assessment/final",
                          verify_frozen=lambda: None)

    def test_requires_all_campaigns_before_any_candidate_execution(self):
        with self.assertRaises(IntegrityError):
            verify_embargo(self.paths[:2], self.root)
        self.assertFalse(FakeBackend.calls)

    def test_missing_seal_blocks_without_output(self):
        p = self.paths[-1]
        state = json.loads((p / "authority/state.json").read_text())
        state["endpoint"].pop("sealed_unix")
        self.state(p, state)
        with self.assertRaises(IntegrityError):
            self.run_assessment()
        self.assertFalse(FakeBackend.calls)
        self.assertFalse((self.root / "assessment/final").exists())

    def test_changed_source_or_binary_rejected(self):
        record = audit_endpoint(self.paths[0])
        (Path(record["source_directory"]) / "engine.cpp").write_text("changed")
        with self.assertRaises(IntegrityError):
            self.run_assessment()

    def test_six_fresh_comparisons_preserve_incomplete_status(self):
        p = self.paths[1]
        state = json.loads((p / "authority/state.json").read_text())
        state["status"] = "incomplete"
        state["endpoint"]["stopping_reason"] = "incomplete"
        self.state(p, state)
        report = self.run_assessment()
        self.assertEqual(report["status"], "complete")
        self.assertEqual(len(report["rows"]), 6)
        self.assertEqual(sum(kind == "bench" for kind, _ in FakeBackend.calls), 6)
        self.assertTrue(all(r["campaign_status"] == "incomplete" for r in report["rows"] if r["campaign_id"] == p.name))
        with self.assertRaises(FileExistsError):
            self.run_assessment()

    def test_backend_failure_retains_terminal_report_and_operation(self):
        FakeBackend.fail = "build"
        with self.assertRaises(RuntimeError):
            self.run_assessment()
        output = self.root / "assessment/final"
        report = json.loads((output / "report.json").read_text())
        result = json.loads((output / "seed/build/result.json").read_text())
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(result["status"], "infra_error")

    def test_mutation_during_measurement_blocks_and_preserves_failure(self):
        FakeBackend.mutate = True
        with self.assertRaises(IntegrityError):
            self.run_assessment()
        report = json.loads((self.root / "assessment/final/report.json").read_text())
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["operations"][-1]["status"], "infra_error")

    def test_unequal_program_treatment_rejected(self):
        self.configs["shift"].compiler = "other"
        with self.assertRaises(IntegrityError):
            self.run_assessment()
        self.assertFalse(FakeBackend.calls)

    def test_transfer_changes_only_seed_and_identifier(self):
        public = json.loads((ROOT / "development/native/definitions.draft.json").read_text())
        before = copy.deepcopy(public)
        final = definitions(public)
        self.assertEqual(public, before)
        for a, b in zip(public["development"], final["transfer"]):
            self.assertNotEqual(a["seed"], b["seed"])
            self.assertEqual({k: v for k, v in a.items() if k not in ("id", "seed")},
                             {k: v for k, v in b.items() if k not in ("id", "seed")})
        self.assertEqual({x["shape"] for x in final["shift"]}, set(SHIFTS))

    def test_changed_fresh_binary_blocks_final_output(self):
        FakeBackend.mutate_binary = True
        with self.assertRaises(IntegrityError):
            self.run_assessment()
        report = json.loads((self.root / "assessment/final/report.json").read_text())
        self.assertEqual(report["status"], "blocked")
        self.assertIn("binary changed", report["error"])

    def test_any_stratum_invalidates_whole_endpoint_before_timing(self):
        FakeBackend.failing_correctness_suite = "shift"
        report = self.run_assessment()
        self.assertEqual(len(report["rows"]), 6)
        self.assertTrue(all(r["status"] == "endpoint_validation_failed" for r in report["rows"]))
        self.assertFalse(any(kind == "bench" for kind, _ in FakeBackend.calls))

    def test_alternate_output_cannot_repeat_same_cohort(self):
        self.run_assessment()
        before = list(FakeBackend.calls)
        with patch("evaluation.run.NativeBackend", FakeBackend), self.assertRaises(IntegrityError):
            assess(self.root, self.paths, self.configs, self.root / "assessment/again",
                   verify_frozen=lambda: None)
        self.assertEqual(FakeBackend.calls, before)

    def test_nested_archived_campaigns_cannot_satisfy_embargo(self):
        archive = self.root / "campaigns/archive"
        archive.mkdir()
        nested = []
        for old in self.paths:
            target = archive / old.name
            old.rename(target)
            nested.append(target)
        with self.assertRaises(IntegrityError):
            verify_embargo(nested, self.root)


if __name__ == "__main__":
    unittest.main()
