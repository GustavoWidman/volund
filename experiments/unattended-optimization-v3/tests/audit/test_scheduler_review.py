"""Independent synthetic review tests; no model, compiler, or benchmark launch."""
from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from owner.measurement import CoordinatedBackend, MeasurementCoordinator, MeasurementCoordinationError
from owner.overlap import AuditedBackend, CommandIntervals, MeasurementInterrupted


def wait_until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("synthetic synchronization did not reach expected state")
        time.sleep(.001)


class CoordinatorReviewTests(unittest.TestCase):
    def test_native_and_workspace_jobs_share_fifo_admission(self):
        c = MeasurementCoordinator()
        lead = c.acquire("workspace_exec", actor_id="lead")
        admitted = []

        def request(kind, actor):
            with c.lease(kind, actor_id=actor):
                admitted.append(actor)

        reviewer = threading.Thread(target=request, args=("bench", "reviewer"))
        compiler = threading.Thread(target=request, args=("build", "worker"))
        reviewer.start()
        wait_until(lambda: len(c.snapshot()["queued"]) == 1)
        compiler.start()
        wait_until(lambda: len(c.snapshot()["queued"]) == 2)
        self.assertEqual(admitted, [])
        c.release(lead)
        reviewer.join(2)
        compiler.join(2)
        self.assertFalse(reviewer.is_alive() or compiler.is_alive())
        self.assertEqual(admitted, ["reviewer", "worker"])
        self.assertIsNone(c.snapshot()["active"])

    def test_quarantine_wakes_waiters_and_cannot_admit_a_new_job(self):
        c = MeasurementCoordinator()
        active = c.acquire("workspace_exec", actor_id="worker")
        errors = []

        def request():
            try:
                c.acquire("bench", actor_id="reviewer")
            except MeasurementCoordinationError as exc:
                errors.append(type(exc).__name__)

        waiter = threading.Thread(target=request)
        waiter.start()
        wait_until(lambda: len(c.snapshot()["queued"]) == 1)
        c.quarantine("synthetic cleanup unknown", {"fixture": True})
        waiter.join(2)
        self.assertFalse(waiter.is_alive())
        self.assertEqual(errors, ["MeasurementCoordinationError"])
        self.assertEqual(c.snapshot()["queued"], [])
        c.release(active)
        with self.assertRaises(MeasurementCoordinationError):
            c.acquire("build", actor_id="other")
        self.assertIsNotNone(c.snapshot()["quarantine"])


class AsyncCoordinatorReviewTests(unittest.IsolatedAsyncioTestCase):
    async def queued(self, c):
        for _ in range(2000):
            if c.snapshot()["queued"]:
                return
            await asyncio.sleep(.001)
        self.fail("async waiter did not queue")

    async def test_cancelled_waiter_never_runs_or_leaks_a_ticket(self):
        c = MeasurementCoordinator()
        held = c.acquire("bench", actor_id="reviewer")
        entered = []

        async def waiter():
            async with c.async_lease("workspace_exec", actor_id="lead"):
                entered.append(True)

        task = asyncio.create_task(waiter())
        await self.queued(c)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        self.assertEqual(entered, [])
        self.assertEqual(c.snapshot()["queued"], [])
        c.release(held)
        async with c.async_lease("workspace_exec", actor_id="next"):
            self.assertEqual(c.snapshot()["active"]["actor_id"], "next")

    async def test_cancellation_after_admission_releases_abandoned_lease(self):
        acquired = threading.Event()
        may_return = threading.Event()

        class DelayedReturn(MeasurementCoordinator):
            def acquire(self, *args, **kwargs):
                receipt = super().acquire(*args, **kwargs)
                acquired.set()
                if not may_return.wait(2):
                    raise AssertionError("synthetic return gate not opened")
                return receipt

        c = DelayedReturn()
        entered = []

        async def waiter():
            async with c.async_lease("workspace_exec", actor_id="lead"):
                entered.append(True)

        task = asyncio.create_task(waiter())
        for _ in range(2000):
            if acquired.is_set():
                break
            await asyncio.sleep(.001)
        self.assertTrue(acquired.is_set())
        task.cancel()
        may_return.set()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        self.assertEqual(entered, [])
        self.assertIsNone(c.snapshot()["active"])
        self.assertEqual(c.snapshot()["queued"], [])


class AuditClassificationReviewTests(unittest.TestCase):
    def run_backend(self, result, *, overlap=False):
        commands = CommandIntervals()

        class Backend:
            def execute(self, kind, context, out):
                if overlap:
                    now = time.time()
                    commands.rows[("synthetic", "command")] = {
                        "thread_id": "synthetic", "item_id": "command",
                        "start": now - .001, "end": now + .001,
                    }
                return dict(result)

        with tempfile.TemporaryDirectory(prefix="v3-independent-synthetic-") as tmp:
            return AuditedBackend(Backend(), commands).execute("bench", {}, Path(tmp))

    def test_overlap_does_not_launder_candidate_failure(self):
        row = self.run_backend({"status": "candidate_failure", "confirmed_semantic_failure": True}, overlap=True)
        self.assertEqual(row["status"], "candidate_failure")
        self.assertFalse(row.get("measurement_retry_authorized", False))

    def test_overlap_does_not_launder_resource_failure(self):
        row = self.run_backend({"status": "timeout", "technical_watchdog": True}, overlap=True)
        self.assertEqual(row["status"], "timeout")
        self.assertFalse(row.get("measurement_retry_authorized", False))

    def test_valid_unfavorable_under_target_result_is_not_retryable(self):
        row = self.run_backend({"status": "pass", "portfolio_speedup": .5,
                                "scored_under_target_batches": [{"fixture": True}]})
        self.assertEqual(row["status"], "pass")
        self.assertEqual(row["portfolio_speedup"], .5)
        self.assertFalse(row.get("measurement_retry_authorized", False))

    def test_only_otherwise_passing_overlap_is_retry_authorized(self):
        row = self.run_backend({"status": "pass", "portfolio_speedup": 10}, overlap=True)
        self.assertEqual(row["status"], "infra_error")
        self.assertEqual(row["measurement_invalidated"], "competing_study_command_execution")
        self.assertTrue(row["measurement_retry_authorized"])
        self.assertEqual(row["portfolio_speedup"], 10)  # retained invalid raw outcome

    def test_external_interruption_requires_cleanup_and_observer_identity(self):
        for args in ({"observer": "owner", "event_id": "event", "cleanup_confirmed": False},
                     {"observer": "", "event_id": "event", "cleanup_confirmed": True},
                     {"observer": "owner", "event_id": "", "cleanup_confirmed": True}):
            with self.assertRaises(ValueError):
                MeasurementInterrupted(**args)


class NativeCleanupReviewTests(unittest.TestCase):
    def check_incomplete_receipt(self, filename, contents):
        c = MeasurementCoordinator()

        class Backend:
            def execute(self, kind, context, out):
                (out / filename).write_text(contents)
                return {"status": "pass"}

        with tempfile.TemporaryDirectory(prefix="v3-independent-cleanup-") as tmp:
            context = {"grant": SimpleNamespace(actor_id="synthetic"),
                       "check_active": lambda: None}
            result = CoordinatedBackend(Backend(), c).execute("build", context, Path(tmp))
            self.assertIsNotNone(c.snapshot()["quarantine"])
            self.assertEqual(result["status"], "infra_error")
            self.assertTrue(result["resource_cleanup_unresolved"])

    def test_started_native_spec_without_completion_receipt_quarantines(self):
        self.check_incomplete_receipt("exec-spec.json", '{"synthetic":true}')

    def test_missing_fields_do_not_prove_native_process_was_never_started(self):
        self.check_incomplete_receipt("command.json", '{}')


if __name__ == "__main__":
    unittest.main()
