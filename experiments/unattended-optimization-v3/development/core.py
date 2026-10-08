"""Draft attributable development evidence API. No native/runtime adapter supplied."""
from __future__ import annotations

import contextlib
import dataclasses
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import time
import uuid


class DevelopmentError(RuntimeError):
    pass


class IntegrityError(DevelopmentError):
    pass


class WatchdogExpired(DevelopmentError):
    pass


class Cancelled(DevelopmentError):
    pass


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tree(path):
    path = Path(path)
    if path.is_symlink() or not path.is_dir():
        raise IntegrityError(f"invalid evidence directory: {path}")
    result = {}
    for p in sorted(path.rglob("*")):
        if p.is_symlink():
            raise IntegrityError(f"symlink prohibited: {p}")
        if p.is_file():
            result[p.relative_to(path).as_posix()] = file_hash(p)
        elif not p.is_dir():
            raise IntegrityError(f"special file prohibited: {p}")
    return result


def write_new(path, obj):
    path = Path(path)
    with path.open("xb") as f:
        f.write(encoded(obj))
        f.flush()
        os.fsync(f.fileno())


@dataclasses.dataclass(frozen=True)
class ReferenceLibrary:
    reference_id: str
    source_hash: str
    library_sha256: str
    path: str


@dataclasses.dataclass(frozen=True)
class ActorGrant:
    investigation_id: str
    actor_id: str
    job_id: str
    parent_job_id: str | None
    role: str
    authority_record_sha256: str
    boot_id: str
    candidate_roots: tuple[str, ...]
    baseline_source_hash: str
    baseline_library_sha256: str
    baseline_library_path: str
    references: tuple[ReferenceLibrary, ...] = ()
    review_plan_id: str | None = None
    review_source_hash: str | None = None
    official_reference_id: str = 'inherited'
    watchdog_monotonic_deadline: float | None = None
    watchdog_wall_deadline: float | None = None

    def remaining(self):
        values = [(self.watchdog_monotonic_deadline, time.monotonic()),
                  (self.watchdog_wall_deadline, time.time())]
        if any(v is not None and not math.isfinite(v) for v, _ in values):
            raise IntegrityError("non-finite technical watchdog deadline")
        return min([v - now for v, now in values if v is not None], default=math.inf)


@dataclasses.dataclass(frozen=True)
class Limits:
    source_bytes: int
    journal_entry_bytes: int
    global_native_lock: str
    lock_poll_seconds: float = 0.01


@contextlib.contextmanager
def bounded_lock(path, grant, poll=0.01, check_active=None):
    """Wait until available, cancelled, or an optional technical watchdog expires."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with path.open("a+b") as f:
        while True:
            if check_active:
                check_active()
            if grant.remaining() <= 0:
                raise WatchdogExpired("technical watchdog expired while queueing")
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(min(poll, max(0, grant.remaining())))
        try:
            yield time.monotonic() - started
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


class DevelopmentService:
    """Authority owns actor binding and durable chain heads outside this store.

    Backend is injected by the owner/runtime, never selected by a participant.
    Native processes must be bounded/killed by that backend. This layer records
    evidence and catches mutations; it is not an executable-code sandbox.
    """
    KINDS = {"build", "test", "profile", "memcheck", "bench", "check"}
    STATUSES = {"pass", "candidate_failure", "timeout", "infra_error", "watchdog_expired", "cancelled"}

    def __init__(self, store, authority, backend, limits):
        self.store = Path(store).resolve()
        self.authority, self.backend, self.limits = authority, backend, limits
        self.store.mkdir(parents=True, exist_ok=True)
        for d in ("events", "snapshots", "operations"):
            (self.store / d).mkdir(exist_ok=True)
        self.key = str(self.store)

    def grant(self):
        g = self.authority.active_grant()
        if not isinstance(g, ActorGrant):
            raise IntegrityError("runtime did not supply an ActorGrant")
        if g.remaining() <= 0:
            raise WatchdogExpired("technical operation watchdog expired")
        return g

    def _recheck(self, expected):
        current = self.grant()
        if current != expected:
            raise IntegrityError("runtime identity changed during operation")

    def _events(self):
        head = None
        records = []
        for i, p in enumerate(sorted((self.store / "events").iterdir()), 1):
            if p.name != f"{i:08d}.json" or p.is_symlink() or not p.is_file():
                raise IntegrityError("evidence sequence changed")
            raw = p.read_bytes()
            obj = json.loads(raw)
            if obj["previous"] != head or obj["sequence"] != i:
                raise IntegrityError("evidence chain changed")
            records.append(obj)
            head = digest(raw)
        if head != self.authority.expected_head(self.key):
            raise IntegrityError("runtime-anchored evidence head mismatch")
        return records

    def _append(self, kind, payload, grant):
        events = self._events()
        previous = self.authority.expected_head(self.key)
        obj = {"sequence": len(events) + 1, "previous": previous, "kind": kind,
               "actor": dataclasses.asdict(grant), "wall_time": time.time(), "payload": payload}
        path = self.store / "events" / f"{len(events)+1:08d}.json"
        write_new(path, obj)
        self.authority.commit_head(self.key, previous, file_hash(path))
        return {"sequence": obj["sequence"], "event_sha256": file_hash(path)}

    def _audit(self):
        events = self._events()
        snapshots = {}
        started, finished = {}, {}
        for event in events:
            p = event["payload"]
            if event["kind"] == "snapshot":
                snapshots[p["source_hash"]] = p
            elif event["kind"] == "operation_started":
                started[p["operation_id"]] = p
            elif event["kind"] == "operation_finished":
                finished[p["operation_id"]] = p
        if set(x.name for x in (self.store / "snapshots").iterdir()) != set(snapshots):
            raise IntegrityError("snapshot inventory changed")
        for name, item in snapshots.items():
            if tree(self.store / "snapshots" / name) != item["files"]:
                raise IntegrityError("immutable source snapshot changed")
        if set(x.name for x in (self.store / "operations").iterdir()) != set(started):
            raise IntegrityError("operation inventory changed")
        for name, item in finished.items():
            if name not in started or tree(self.store / "operations" / name) != item["files"]:
                raise IntegrityError("immutable operation evidence changed")
        if set(started) != set(finished):
            raise IntegrityError("unsealed operation requires explicit runtime reconciliation")
        return events, snapshots, finished

    def snapshot(self, candidate):
        g = self.grant()
        candidate = Path(candidate)
        if candidate.is_symlink():
            raise IntegrityError("symlink candidate prohibited")
        candidate = candidate.resolve()
        if not candidate.is_dir() or not any(candidate.is_relative_to(Path(p).resolve()) for p in g.candidate_roots):
            raise IntegrityError("candidate outside runtime-authorized roots")
        with bounded_lock(self.store / ".metadata.lock", g, check_active=lambda: self._recheck(g)):
            self._audit()
            files = tree(candidate)
            if not files or sum((candidate / p).stat().st_size for p in files) > self.limits.source_bytes:
                raise DevelopmentError("empty or oversized source snapshot")
            key = digest(encoded(files))
            destination = self.store / "snapshots" / key
            if destination.exists():
                return {"source_hash": key, "reused": True}
            shutil.copytree(candidate, destination)
            if tree(destination) != files or tree(candidate) != files:
                # Do not conceal an incomplete capture; explicit owner reconciliation required.
                raise IntegrityError("source changed during snapshot capture")
            receipt = self._append("snapshot", {"source_hash": key, "files": files}, g)
            return {"source_hash": key, "reused": False, **receipt}

    def _build(self, build_id, finished):
        item = finished.get(build_id)
        if not item or item["operation"] != "build" or item["status"] != "pass":
            raise DevelopmentError("a successful recorded build is required")
        return item

    def run(self, kind, *, source_hash=None, build_id=None, fixture_id=None, argv=None, reference_id="inherited", purpose="exploratory"):
        """Run one request; retry only explicitly attested invalid timing attempts.

        A valid result ends this request regardless of score. Every retry is a
        new immutable operation with the same runtime-bound grant and inputs.
        Each attempt releases metadata, native and execution leases before the
        next attempt queues. No retry-count, token or research-time cap applies.
        """
        arguments = dict(source_hash=source_hash, build_id=build_id, fixture_id=fixture_id,
                         argv=argv, reference_id=reference_id, purpose=purpose)
        if kind != 'bench':
            return self._run_once(kind, **arguments)
        grant = self.grant()
        measurement_id = uuid.uuid4().hex
        prior_attempts = []
        retry_reason = None
        while True:
            self._recheck(grant)  # Explicit cancellation always wins over retry.
            measurement = {'measurement_id': measurement_id,
                           'measurement_attempt_number': len(prior_attempts) + 1,
                           'measurement_prior_attempt_ids': list(prior_attempts),
                           'measurement_retry_reason': retry_reason,
                           'measurement_selection_rule': 'first_complete_valid_attempt',
                           'measurement_retry_policy': 'infrastructure_only_first_valid_v1'}
            result = self._run_once(kind, _bound_grant=grant, _measurement=measurement, **arguments)
            retry_reason = self._retryable_measurement_reason(result)
            if retry_reason is None:
                return result
            prior_attempts.append(result['operation_id'])

    @staticmethod
    def _retryable_measurement_reason(result):
        """Ignore scores; accept only a retained owner audit of an allowed cause."""
        if (result.get('status') != 'infra_error' or result.get('measurement_retry_authorized') is not True
                or result.get('measurement_retry_policy') != 'infrastructure_only_first_valid_v1'
                or result.get('confirmed_semantic_failure') is True
                or result.get('confirmed_memory_error') is True or result.get('integrity_error')):
            return None
        audit = result.get('ordinary_command_overlap_audit') or {}
        if audit.get('backend_exception') is not None:
            return None
        reason = result.get('measurement_invalidated')
        if (reason == 'competing_study_command_execution' and audit.get('status') == 'invalid_overlap'
                and audit.get('ordinary_command_overlaps')):
            return reason
        interruption = audit.get('external_interruption') or {}
        if (reason == 'attested_external_interruption' and interruption.get('cleanup_confirmed') is True
                and interruption.get('cause') == 'external_preemption'
                and isinstance(interruption.get('observer'), str) and interruption['observer'].strip()
                and isinstance(interruption.get('event_id'), str) and interruption['event_id'].strip()):
            return reason
        return None

    def _run_once(self, kind, *, source_hash=None, build_id=None, fixture_id=None, argv=None,
                  reference_id="inherited", purpose="exploratory", _bound_grant=None, _measurement=None):
        if kind not in self.KINDS:
            raise DevelopmentError("unknown operation")
        g = _bound_grant or self.grant()
        self._recheck(g)
        with bounded_lock(self.store / ".metadata.lock", g, check_active=lambda: self._recheck(g)):
            _, snapshots, finished = self._audit()
            build = self._build(build_id, finished) if kind in {"test", "profile", "memcheck", "bench"} else None
            if build:
                source_hash = build["source_hash"]
            if source_hash not in snapshots:
                raise DevelopmentError("unknown source snapshot")
            if purpose not in {"exploratory", "official_review"}:
                raise DevelopmentError("unknown request purpose")
            if purpose == "official_review" and (g.role != "reviewer" or not g.review_plan_id or source_hash != g.review_source_hash):
                raise DevelopmentError("official review requires runtime-bound plan and source")
            references = {r.reference_id: dataclasses.asdict(r) for r in g.references}
            if len(references) != len(g.references) or 'inherited' in references:
                raise IntegrityError("ambiguous runtime reference aliases")
            references['inherited'] = {"reference_id": "inherited", "source_hash": g.baseline_source_hash,
                                      "library_sha256": g.baseline_library_sha256, "path": g.baseline_library_path}
            if reference_id not in references:
                raise DevelopmentError("reference is not approved by runtime")
            if kind == "bench" and purpose == "official_review" and reference_id != g.official_reference_id:
                raise DevelopmentError("official reference differs from owner review plan")
            if kind == "check" and g.role != "setup_owner":
                raise DevelopmentError("host arbitrary commands are setup-owner-only; use worker sandbox exec for extra tests")
            if kind == "check" and (not isinstance(argv, list) or not argv or not all(isinstance(x, str) and "\x00" not in x for x in argv)):
                raise DevelopmentError("check requires a nonempty argument vector")
            if kind == "profile" and not isinstance(fixture_id, str):
                raise DevelopmentError("profile requires a public fixture ID")
            op = uuid.uuid4().hex
            out = self.store / "operations" / op
            out.mkdir()
            request = {"operation_id": op, "operation": kind, "source_hash": source_hash,
                       "build_id": build_id, "fixture_id": fixture_id, "argv": argv, "reference_id": reference_id,
                       "reference": references[reference_id] if kind == "bench" else None, "purpose": purpose,
                       "review_plan_id": g.review_plan_id if purpose == "official_review" else None}
            if _measurement is not None:
                request.update(_measurement)
            write_new(out / "request.json", request)
            self._append("operation_started", request, g)
            started = time.monotonic()
            queue = None
            error = None
            try:
                context = {"grant": g, "source_directory": self.store / "snapshots" / source_hash,
                           "build": build, "build_directory": self.store / "operations" / build_id if build else None,
                           "baseline": references[reference_id], "request": request,
                           "check_active": lambda: self._recheck(g)}
                with bounded_lock(self.limits.global_native_lock, g, self.limits.lock_poll_seconds, lambda: self._recheck(g)) as queue:
                    # Every backend call, including custom checks and profiler, takes this lock.
                    self.grant()
                    result = self.backend.execute(kind, context, out)
                if result.get("status") not in self.STATUSES:
                    raise IntegrityError("backend returned unknown status")
                if g.remaining() <= 0:
                    result = {**result, "status": "watchdog_expired", "late_backend_result": True}
                if kind == "build" and result["status"] == "pass":
                    relative = result.get("library")
                    if not isinstance(relative, str) or Path(relative).is_absolute():
                        raise IntegrityError("backend build missing relative library")
                    lib = out / relative
                    if lib.is_symlink() or not lib.resolve().is_relative_to(out) or not lib.is_file():
                        raise IntegrityError("invalid backend build library")
                    result = {**result, "library_sha256": file_hash(lib)}
            except (WatchdogExpired, Cancelled) as exc:
                if queue is None:
                    queue = time.monotonic() - started
                result = {"status": "cancelled" if isinstance(exc, Cancelled) else "watchdog_expired", "error": str(exc)}
            except BaseException as exc:
                error = exc
                result = {"status": "interrupted" if isinstance(exc, KeyboardInterrupt) else "infra_error", "error": str(exc)}
            result = {**result, **request, "actor_id": g.actor_id, "job_id": g.job_id, "role": g.role,
                      "authority_record_sha256": g.authority_record_sha256, "queue_seconds": queue,
                      "outer_elapsed_seconds": time.monotonic() - started, "exploratory": purpose == "exploratory"}
            try:
                if tree(context["source_directory"]) != snapshots[source_hash]["files"]:
                    raise IntegrityError("backend mutated immutable source")
            except BaseException as exc:
                error = IntegrityError("immutable source unavailable or changed: " + str(exc))
                result["status"], result["integrity_error"] = "infra_error", str(error)
            write_new(out / "result.json", result)
            self._append("operation_finished", {**result, "files": tree(out)}, g)
            # Check every historical seal again, including input build evidence.
            self._audit()
            if error:
                raise error
            return {**result, "artifact_directory": str(out)}

    def append_journal(self, text, evidence_ids=()):
        g = self.grant()
        if not isinstance(text, str) or not text.strip() or len(text.encode()) > self.limits.journal_entry_bytes:
            raise DevelopmentError("empty or oversized journal entry")
        with bounded_lock(self.store / ".metadata.lock", g, check_active=lambda: self._recheck(g)):
            _, _, finished = self._audit()
            if any(op not in finished for op in evidence_ids):
                raise DevelopmentError("journal references unknown operation")
            return self._append("journal", {"text": text, "evidence_ids": list(evidence_ids)}, g)

    def index(self):
        g = self.grant()
        with bounded_lock(self.store / ".metadata.lock", g, check_active=lambda: self._recheck(g)):
            events, snapshots, finished = self._audit()
            keys = ("operation_id", "operation", "source_hash", "library_sha256", "status", "actor_id", "job_id", "role", "outer_elapsed_seconds", "queue_seconds", "purpose", "review_plan_id", "reference_id", "summary", "portfolio_speedup", "family_speedups")
            return {"source_hashes": list(snapshots), "operations": [{**{k: p[k] for k in keys if k in p}, "artifact_directory": str(self.store / "operations" / p["operation_id"])} for p in finished.values()],
                    "journal": [{"sequence": e["sequence"], "actor_id": e["actor"]["actor_id"], **e["payload"]} for e in events if e["kind"] == "journal"],
                    "evidence_head": self.authority.expected_head(self.key)}

    def review_evidence(self, build_id):
        """Return every own official attempt and first valid comparison, not a verdict."""
        g = self.grant()
        if g.role != "reviewer" or not g.review_plan_id or not g.review_source_hash:
            raise DevelopmentError("runtime-bound reviewer plan required")
        with bounded_lock(self.store / ".metadata.lock", g, check_active=lambda: self._recheck(g)):
            _, _, finished = self._audit()
            build = self._build(build_id, finished)
            def own(p):
                return (p["job_id"] == g.job_id and p["actor_id"] == g.actor_id and p["role"] == "reviewer"
                        and p["authority_record_sha256"] == g.authority_record_sha256
                        and p["source_hash"] == g.review_source_hash
                        and p["purpose"] == "official_review" and p["review_plan_id"] == g.review_plan_id)
            if not own(build):
                raise DevelopmentError("reviewer must execute its own official fresh build")
            attempts = [p for p in finished.values() if own(p)]
            plan_attempts = [p for p in finished.values() if p["role"] == "reviewer"
                             and p["source_hash"] == g.review_source_hash and p["purpose"] == "official_review"
                             and p["review_plan_id"] == g.review_plan_id]
            invalidating = [p for p in plan_attempts if p.get("confirmed_semantic_failure") is True or p.get("confirmed_memory_error") is True]
            if invalidating:
                return {"status": "disqualified", "source_hash": g.review_source_hash,
                        "review_plan_id": g.review_plan_id, "endpoint_authorized": False,
                        "invalidating_evidence": [{"operation_id": p["operation_id"], "operation": p["operation"],
                                                   "actor_id": p["actor_id"], "job_id": p["job_id"], "build_id": p.get("build_id"),
                                                   "confirmed_semantic_failure": p.get("confirmed_semantic_failure", False),
                                                   "confirmed_memory_error": p.get("confirmed_memory_error", False),
                                                   "artifact_directory": str(self.store / "operations" / p["operation_id"])} for p in invalidating],
                        "reason": "confirmed official semantic or memory error under this source/nomination plan; later passing reruns cannot erase it"}
            references = {r.reference_id: dataclasses.asdict(r) for r in g.references}
            references['inherited'] = {"reference_id": "inherited", "source_hash": g.baseline_source_hash,
                                      "library_sha256": g.baseline_library_sha256, "path": g.baseline_library_path}
            reference = references[g.official_reference_id]
            comparisons = [p for p in plan_attempts if p["operation"] == "bench"]
            if any(p["reference_id"] != g.official_reference_id or p["reference"] != reference for p in comparisons):
                raise IntegrityError("immutable review plan changed reference binding")
            valid = [p for p in comparisons if p["status"] == "pass"]
            if not valid:
                raise DevelopmentError("no complete valid official comparison in review plan")
            selected = valid[0]  # global append order, across every actor/job/build
            selected_build = self._build(selected["build_id"], finished)
            if selected_build["source_hash"] != g.review_source_hash or selected_build["review_plan_id"] != g.review_plan_id:
                raise IntegrityError("selected comparison has wrong source/build plan")
            def evidence_for(build_identifier, pool):
                evidence = {"build": [build_identifier]}
                for kind in ("test", "profile", "memcheck", "bench"):
                    matches = [p for p in pool if p["operation"] == kind and p["status"] == "pass"
                               and p["build_id"] == build_identifier
                               and (kind != "memcheck" or p.get("coverage_complete") is True)
                               and (kind != "bench" or p["reference_id"] == g.official_reference_id)]
                    if not matches:
                        raise DevelopmentError(f"review build has no successful fresh official {kind} execution")
                    evidence[kind] = [p["operation_id"] for p in matches]
                return evidence
            evidence = evidence_for(build_id, attempts)
            selected_evidence = evidence_for(selected["build_id"], plan_attempts)
            return {"status": "execution_verified", "source_hash": g.review_source_hash, "actor_id": g.actor_id, "job_id": g.job_id,
                    "review_plan_id": g.review_plan_id, "execution_evidence": evidence,
                    "current_review_build_id": build_id, "current_review_library_sha256": build["library_sha256"],
                    "all_official_attempts": [{"operation_id": p["operation_id"], "operation": p["operation"], "status": p["status"], "actor_id": p["actor_id"], "job_id": p["job_id"], "build_id": p.get("build_id")} for p in plan_attempts],
                    "official_comparison_operation_id": selected["operation_id"],
                    "official_comparison_build_id": selected["build_id"],
                    "official_comparison_library_sha256": selected_build["library_sha256"],
                    "official_comparison_actor_id": selected["actor_id"], "official_comparison_job_id": selected["job_id"],
                    "official_comparison_reference": selected["reference"],
                    "selected_build_execution_evidence": selected_evidence,
                    "selection_rule": "first complete valid official comparison in immutable plan/source/reference append order across all actors/jobs/builds; never best or last",
                    "endpoint_authorized": False, "review_content_assessed": False}


def audit_store(store, expected_head):
    """Read-only owner verification with an independently persisted expected head.

    No active participant grant is needed and no directory/file is created.
    The owner still checks semantic role, ancestry, plan and nomination links.
    """
    class ReadOnlyAnchor:
        def expected_head(self, key):
            return expected_head
    service = object.__new__(DevelopmentService)
    service.store = Path(store).resolve()
    service.key = str(service.store)
    service.authority = ReadOnlyAnchor()
    events, snapshots, operations = service._audit()
    return {"events": events, "snapshots": snapshots, "operations": operations,
            "evidence_head": expected_head}
