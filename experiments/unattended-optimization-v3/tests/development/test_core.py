"""Non-inference tests: injected fake backends only; no real native workload."""
import dataclasses
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import sys

MODULE = Path(__file__).resolve().parents[2] / "development/core.py"
spec = importlib.util.spec_from_file_location("v2_development_core", MODULE)
c = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = c
spec.loader.exec_module(c)


class FakeAuthority:
    """Test-only authority. A production caller cannot choose its own grant."""
    def __init__(self, grant):
        self.current = grant
        self.heads = {}
        self.cancelled = False
    def active_grant(self):
        if self.cancelled:
            raise c.Cancelled("runtime cancelled job")
        return self.current
    def expected_head(self, key):
        return self.heads.get(key)
    def commit_head(self, key, old, new):
        if self.heads.get(key) != old:
            raise c.IntegrityError("authority compare-and-swap failed")
        self.heads[key] = new


class FakeBackend:
    def __init__(self):
        self.calls = []
        self.outcomes = []
        self.mutate = False
    def execute(self, kind, context, output_directory):
        self.calls.append((kind, context))
        (output_directory / "stdout.txt").write_text("fake output, not native timing\n")
        (output_directory / "stderr.txt").write_text("")
        if self.mutate:
            (context["source_directory"] / "engine.cpp").write_text("mutated")
        status = self.outcomes.pop(0) if self.outcomes else "pass"
        if isinstance(status, BaseException):
            raise status
        extra = status if isinstance(status, dict) else {}
        status = extra.get("status", status)
        result = {"status": status, "synthetic": True, **extra}
        if kind == "memcheck":
            result['coverage_complete'] = True
        if kind == "build" and status == "pass":
            (output_directory / "candidate.so").write_bytes(b"FAKE-NOT-AN-ELF-LIBRARY")
            result["library"] = "candidate.so"
        return result


class DevelopmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.candidate = self.root / "candidate"
        self.candidate.mkdir()
        (self.candidate / "engine.cpp").write_text("int candidate = 1;\n")
        g = c.ActorGrant("investigation-1", "worker-1", "job-1", "lead-job", "worker", "a" * 64,
                        "fake-boot", (str(self.candidate),),
                        "b" * 64, "c" * 64, "/fake/runtime-pinned-prototype.so")
        self.authority = FakeAuthority(g)
        self.backend = FakeBackend()
        self.limits = c.Limits(100_000, 10_000, str(self.root / "global.lock"))
        self.service = c.DevelopmentService(self.root / "evidence", self.authority, self.backend, self.limits)
    def tearDown(self):
        self.tmp.cleanup()
    def snap(self):
        return self.service.snapshot(self.candidate)["source_hash"]
    def build(self, **kwargs):
        return self.service.run("build", source_hash=self.snap(), **kwargs)


    def test_no_research_deadline_or_call_count_limit_by_default(self):
        self.assertIsNone(self.authority.current.watchdog_monotonic_deadline)
        self.assertIsNone(self.authority.current.watchdog_wall_deadline)
        self.assertEqual(self.authority.current.remaining(), float("inf"))
        key = self.snap()
        for _ in range(12):
            self.service.run("build", source_hash=key)
        self.assertEqual(len(self.service.index()["operations"]), 12)

    def test_runtime_cancellation_interrupts_global_lock_wait(self):
        key = self.snap()
        def cancel():
            time.sleep(0.025)
            self.authority.cancelled = True
        with c.bounded_lock(self.limits.global_native_lock, self.authority.current):
            thread = threading.Thread(target=cancel)
            thread.start()
            result = self.service.run("build", source_hash=key)
            thread.join()
        self.assertEqual(result["status"], "cancelled")
        self.assertGreater(result["queue_seconds"], 0)
        self.assertFalse(self.backend.calls)

    def test_failed_compile_can_be_repaired_and_repeated_same_investigation(self):
        self.backend.outcomes = ["candidate_failure", "pass", "pass"]
        bad = self.build()
        self.assertEqual(bad["status"], "candidate_failure")
        (self.candidate / "engine.cpp").write_text("int candidate = 2;\n")
        fixed = self.build()
        repeat = self.build()
        self.assertNotEqual(bad["source_hash"], fixed["source_hash"])
        self.assertEqual(fixed["source_hash"], repeat["source_hash"])
        self.assertNotEqual(fixed["operation_id"], repeat["operation_id"])
        self.assertEqual(len(self.service.index()["operations"]), 3)

    def test_failed_test_and_profile_do_not_consume_one_shot_submission(self):
        build = self.build()
        self.backend.outcomes = ["candidate_failure", "pass", "timeout", "pass"]
        statuses = [self.service.run(k, build_id=build["operation_id"], fixture_id="public-small")["status"]
                    for k in ("test", "test", "profile", "profile")]
        self.assertEqual(statuses, ["candidate_failure", "pass", "timeout", "pass"])

    def test_actor_and_baseline_are_runtime_bound_not_request_fields(self):
        build = self.build()
        result = self.service.run("bench", build_id=build["operation_id"])
        self.assertEqual(result["actor_id"], "worker-1")
        self.assertEqual(self.backend.calls[-1][1]["baseline"]["source_hash"], "b" * 64)
        with self.assertRaises(TypeError):
            self.service.run("bench", build_id=build["operation_id"], actor_id="reviewer")
        with self.assertRaises(TypeError):
            self.service.run("bench", build_id=build["operation_id"], baseline_build="other")


    def test_only_host_approved_reference_aliases_are_selectable(self):
        build = self.build()
        self.authority.current = dataclasses.replace(self.authority.current, references=(c.ReferenceLibrary("seed", "s"*64, "l"*64, "/owner/seed.so"),))
        measured = self.service.run("bench", build_id=build["operation_id"], reference_id="seed")
        self.assertEqual(measured["reference"]["path"], "/owner/seed.so")
        with self.assertRaises(c.DevelopmentError):
            self.service.run("bench", build_id=build["operation_id"], reference_id="arbitrary")
        with self.assertRaises(c.DevelopmentError):
            self.service.run("bench", build_id=build["operation_id"], purpose="official_review")

    def test_snapshot_and_evidence_mutations_fail_closed(self):
        key = self.snap()
        (self.service.store / "snapshots" / key / "engine.cpp").write_text("changed")
        with self.assertRaises(c.IntegrityError):
            self.service.index()

    def test_completed_raw_output_mutation_detected(self):
        result = self.build()
        (Path(result["artifact_directory"]) / "stdout.txt").write_text("changed")
        with self.assertRaises(c.IntegrityError):
            self.service.run("test", build_id=result["operation_id"])

    def test_journal_corrections_append_and_old_entry_cannot_be_changed(self):
        first = self.service.append_journal("Hypothesis: investigate sorted lookup")
        second = self.service.append_journal("Correction to earlier hypothesis: not yet tested")
        index = self.service.index()
        self.assertEqual(len(index["journal"]), 2)
        self.assertLess(first["sequence"], second["sequence"])
        p = self.service.store / "events" / "00000001.json"
        p.write_text(p.read_text().replace("sorted lookup", "fabricated result"))
        with self.assertRaises(c.IntegrityError):
            self.service.index()

    def test_chain_truncation_detected_by_external_head(self):
        self.service.append_journal("First")
        self.service.append_journal("Second")
        (self.service.store / "events" / "00000002.json").unlink()
        with self.assertRaises(c.IntegrityError):
            self.service.index()

    def test_extra_check_does_not_create_canonical_build(self):
        with self.assertRaises(c.DevelopmentError):
            self.service.run("check", source_hash=self.snap(), argv=["ordinary-compiler"])
        self.authority.current = dataclasses.replace(self.authority.current, role="setup_owner")
        result = self.service.run("check", source_hash=self.snap(), argv=["ordinary-compiler", "--version"])
        with self.assertRaises(c.DevelopmentError):
            self.service.run("test", build_id=result["operation_id"])
        self.assertEqual(self.backend.calls[-1][1]["request"]["argv"], ["ordinary-compiler", "--version"])

    def test_no_engine_execution_inferred_from_reviewer_report(self):
        lead_build = self.build()
        self.authority.current = dataclasses.replace(self.authority.current, actor_id="reviewer-1", job_id="reviewer-job", role="reviewer", authority_record_sha256="d"*64, review_plan_id="owner-plan-1", review_source_hash=lead_build["source_hash"])
        self.service.append_journal("I reviewed the code")
        with self.assertRaises(c.DevelopmentError):
            self.service.review_evidence(lead_build["operation_id"])
        reviewer_build = self.build(purpose="official_review")
        with self.assertRaises(c.DevelopmentError):
            self.service.review_evidence(reviewer_build["operation_id"])
        for kind in ("test", "profile", "memcheck", "bench", "bench"):
            self.service.run(kind, build_id=reviewer_build["operation_id"], fixture_id="public-small", purpose="official_review")
        receipt = self.service.review_evidence(reviewer_build["operation_id"])
        self.assertEqual(set(receipt["execution_evidence"]), {"build", "test", "profile", "memcheck", "bench"})
        self.assertEqual(receipt["official_comparison_operation_id"], receipt["execution_evidence"]["bench"][0])
        self.assertEqual(len(receipt["execution_evidence"]["bench"]), 2)
        self.assertFalse(receipt["endpoint_authorized"])

    def test_optional_technical_watchdog_prevents_hung_operation_start(self):
        key = self.snap()
        self.authority.current = dataclasses.replace(self.authority.current, watchdog_monotonic_deadline=time.monotonic()-1)
        with self.assertRaises(c.WatchdogExpired):
            self.service.run("build", source_hash=key)
        self.assertFalse(self.backend.calls)

    def test_queue_deadline_retains_attempt_without_backend_execution(self):
        key = self.snap()
        self.authority.current = dataclasses.replace(self.authority.current, watchdog_monotonic_deadline=time.monotonic()+0.04)
        holder = dataclasses.replace(self.authority.current, watchdog_monotonic_deadline=time.monotonic()+3)
        with c.bounded_lock(self.limits.global_native_lock, holder):
            result = self.service.run("build", source_hash=key)
        self.assertEqual(result["status"], "watchdog_expired")
        self.assertGreater(result["queue_seconds"], 0)
        self.assertFalse(self.backend.calls)
        self.assertTrue((Path(result["artifact_directory"]) / "result.json").exists())

    def test_all_backend_kinds_take_same_global_lock(self):
        key = self.snap()
        build = self.service.run("build", source_hash=key)
        for kind in ("profile", "memcheck", "bench", "test", "check"):
            if kind == "check":
                self.authority.current = dataclasses.replace(self.authority.current, role="setup_owner")
            acquired = threading.Event()
            def hold():
                with c.bounded_lock(self.limits.global_native_lock, self.authority.current):
                    acquired.set()
                    time.sleep(0.04)
            thread = threading.Thread(target=hold)
            thread.start()
            self.assertTrue(acquired.wait(1))
            result = self.service.run(kind, source_hash=key, build_id=build["operation_id"], fixture_id="public", argv=["extra-test"])
            thread.join()
            self.assertGreater(result["queue_seconds"], 0.01)

    def test_interruption_keeps_partial_output_and_terminal_record(self):
        self.backend.outcomes = [KeyboardInterrupt("fake interruption")]
        with self.assertRaises(KeyboardInterrupt):
            self.build()
        records = self.service.index()["operations"]
        self.assertEqual(records[0]["status"], "interrupted")
        self.assertEqual(len(self.backend.calls), 1)

    def test_backend_mutation_retains_failed_integrity_record(self):
        self.backend.mutate = True
        with self.assertRaises(c.IntegrityError):
            self.build()
        result = json.loads(next((self.service.store / "operations").glob("*/result.json")).read_text())
        self.assertEqual(result["status"], "infra_error")
        self.assertIn("mutated", result["integrity_error"])


    def test_source_deletion_still_retains_terminal_failure_evidence(self):
        import shutil
        original = self.backend.execute
        def mutate(kind, context, output):
            result = original(kind, context, output)
            shutil.rmtree(context['source_directory'])
            return result
        self.backend.execute = mutate
        with self.assertRaises(c.IntegrityError):
            self.build()
        result = json.loads(next((self.service.store / 'operations').glob('*/result.json')).read_text())
        self.assertEqual(result['status'], 'infra_error')
        events = [json.loads(p.read_text())['kind'] for p in sorted((self.service.store / 'events').glob('*.json'))]
        self.assertEqual(events[-1], 'operation_finished')

    def test_official_comparison_cannot_reset_across_builds_or_reviewer_contexts(self):
        source = self.snap()
        self.authority.current = dataclasses.replace(self.authority.current, actor_id='review-a', job_id='review-job-a', role='reviewer', review_plan_id='fixed-nomination-plan', review_source_hash=source)
        def review_round():
            built = self.build(purpose='official_review')
            for kind in ('test', 'profile', 'memcheck', 'bench'):
                self.service.run(kind, build_id=built['operation_id'], fixture_id='public', purpose='official_review')
            return self.service.review_evidence(built['operation_id'])
        first = review_round()
        second = review_round()
        self.assertEqual(second['official_comparison_operation_id'], first['official_comparison_operation_id'])
        self.assertNotEqual(second['current_review_build_id'], first['current_review_build_id'])
        self.authority.current = dataclasses.replace(self.authority.current, actor_id='review-b', job_id='review-job-b', authority_record_sha256='e'*64)
        third = review_round()
        self.assertEqual(third['official_comparison_operation_id'], first['official_comparison_operation_id'])
        self.assertEqual(third['official_comparison_actor_id'], 'review-a')
        self.assertEqual(third['actor_id'], 'review-b')
        self.assertEqual(len(third['all_official_attempts']), 15)


    def test_confirmed_official_failure_survives_later_passing_rerun(self):
        source = self.snap()
        self.authority.current = dataclasses.replace(self.authority.current, role='reviewer', review_plan_id='plan', review_source_hash=source)
        build = self.build(purpose='official_review')
        self.backend.outcomes = [{'status': 'candidate_failure', 'confirmed_semantic_failure': True}, 'pass']
        failed = self.service.run('test', build_id=build['operation_id'], purpose='official_review')
        self.service.run('test', build_id=build['operation_id'], purpose='official_review')
        receipt = self.service.review_evidence(build['operation_id'])
        self.assertEqual(receipt['status'], 'disqualified')
        self.assertEqual(receipt['invalidating_evidence'][0]['operation_id'], failed['operation_id'])
        self.assertFalse(receipt['endpoint_authorized'])

    def test_official_timeout_is_not_labeled_semantic_disqualification(self):
        source = self.snap()
        self.authority.current = dataclasses.replace(self.authority.current, role='reviewer', review_plan_id='plan', review_source_hash=source)
        build = self.build(purpose='official_review')
        self.backend.outcomes = ['timeout', 'pass']
        self.service.run('test', build_id=build['operation_id'], purpose='official_review')
        for kind in ('test', 'profile', 'memcheck', 'bench'):
            self.service.run(kind, build_id=build['operation_id'], fixture_id='public', purpose='official_review')
        receipt = self.service.review_evidence(build['operation_id'])
        self.assertEqual(receipt['status'], 'execution_verified')
        self.assertTrue(any(p['status'] == 'timeout' for p in receipt['all_official_attempts']))

    def test_snapshot_rejects_symlink_and_outside_authorized_root(self):
        (self.candidate / "link").symlink_to("engine.cpp")
        with self.assertRaises(c.IntegrityError):
            self.snap()
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "engine.cpp").write_text("not authorized")
        with self.assertRaises(c.IntegrityError):
            self.service.snapshot(outside)

    def test_journal_rejects_unknown_evidence_and_oversize(self):
        with self.assertRaises(c.DevelopmentError):
            self.service.append_journal("claim", ["invented-operation"])
        with self.assertRaises(c.DevelopmentError):
            self.service.append_journal("x" * 10_001)

    def test_backend_failure_is_retained_without_implicit_retry(self):
        self.backend.outcomes = [RuntimeError("fake tool failure")]
        with self.assertRaises(RuntimeError):
            self.build()
        self.assertEqual(self.service.index()["operations"][0]["status"], "infra_error")
        self.assertEqual(len(self.backend.calls), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
