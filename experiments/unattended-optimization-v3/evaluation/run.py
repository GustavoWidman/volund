"""Owner-only final evaluation, after every planned endpoint is sealed.

No import-time execution. NativeBackend supplies the same canonical measurement
implementation through separately pinned final-suite configurations.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
import re
import time
from types import SimpleNamespace
import uuid

from development.core import DevelopmentService, IntegrityError, digest, encoded, file_hash, tree, write_new
from development.native_backend import NativeBackend
from owner.measurement import CoordinatedBackend, MeasurementCoordinator

EXPECTED_CAMPAIGNS = ("campaign-1", "campaign-2", "campaign-3")
STRATA = ("transfer", "shift")


def load(path):
    return json.loads(Path(path).read_text())


def audit_endpoint(directory):
    directory = Path(directory).resolve(strict=True)
    authority = directory / "authority"
    anchor, state = load(authority / "anchor.json"), load(authority / "state.json")
    previous, count, last_state = None, 0, None
    for count, path in enumerate(sorted((authority / "events").iterdir()), 1):
        if path.name != f"{count:08d}.json" or path.is_symlink():
            raise IntegrityError("final endpoint authority sequence changed")
        event = load(path)
        if event["sequence"] != count or event["previous"] != previous:
            raise IntegrityError("final endpoint authority chain changed")
        previous = file_hash(path)
        last_state = event.get("state_hash")
    if (count, previous) != (anchor["count"], anchor["head"]):
        raise IntegrityError("final endpoint authority anchor mismatch")
    if digest(encoded(state)) != anchor["state_hash"]:
        raise IntegrityError("final endpoint state hash mismatch")
    if count == 0 or last_state != anchor["state_hash"]:
        raise IntegrityError("final state is not anchored in last owner event")
    if state.get("stage") != "measured" or state.get("status") not in ("complete", "incomplete"):
        raise IntegrityError("assessment embargo: campaign not terminal and measured")
    endpoint = state.get("endpoint")
    if not isinstance(endpoint, dict) or "sealed_unix" not in endpoint:
        raise IntegrityError("assessment embargo: endpoint seal missing")
    if endpoint.get("final_assessment_released") is not False:
        raise IntegrityError("assessment already released or release state unknown")
    if state["campaign_id"] != directory.name:
        raise IntegrityError("campaign identity mismatch")
    if endpoint.get("source_hash") != (state.get("incumbent") or {}).get("source_hash"):
        raise IntegrityError("sealed source is not the retained incumbent")
    expected_reason = "task_complete" if state["status"] == "complete" else "incomplete"
    if endpoint.get("stopping_reason") != expected_reason:
        raise IntegrityError("completion and seal status disagree")
    source_hash = endpoint.get("source_hash")
    record = {
        "campaign_id": state["campaign_id"], "campaign_status": state["status"],
        "endpoint": endpoint, "state_sha256": file_hash(authority / "state.json"),
        "anchor_sha256": file_hash(authority / "anchor.json"),
        "source_directory": None, "source_files": None,
    }
    if source_hash:
        if not isinstance(source_hash, str) or re.fullmatch(r"[0-9a-f]{64}", source_hash) is None:
            raise IntegrityError("invalid sealed source hash")
        source = directory / "development/snapshots" / source_hash
        files = tree(source)
        if digest(encoded(files)) != source_hash:
            raise IntegrityError("sealed source snapshot changed")
        old_binary = Path(endpoint["library_path"])
        if (old_binary.is_symlink() or not old_binary.resolve().is_relative_to(directory)
                or file_hash(old_binary) != endpoint["library_sha256"]):
            raise IntegrityError("retained endpoint binary changed")
        record.update(source_directory=str(source), source_files=files)
    elif state["status"] != "incomplete":
        raise IntegrityError("normally completed campaign has no source")
    return record


def verify_embargo(campaign_directories, root):
    root = Path(root).resolve(strict=True)
    paths = [Path(p).resolve(strict=True) for p in campaign_directories]
    if len(paths) != 3 or {p.name for p in paths} != set(EXPECTED_CAMPAIGNS):
        raise IntegrityError("assessment requires all three planned campaign identities")
    expected = {(root / "campaigns" / name).resolve() for name in EXPECTED_CAMPAIGNS}
    if set(paths) != expected:
        raise IntegrityError("assessment requires exact canonical campaign directories")
    records = [audit_endpoint(p) for p in sorted(paths)]
    return records


def assess(root, campaign_directories, configurations, output, *, verify_frozen, check_cancelled=lambda: None,
           measurement_coordinator=None):
    """Run once after readiness/freeze and all seals; configurations are NativeConfig.

    verify_frozen is a required owner callback, invoked before and after each
    operation. This function never edits campaign state or releases data to agents.
    """
    root, output = Path(root).resolve(strict=True), Path(output).resolve()
    if set(configurations) != set(STRATA):
        raise IntegrityError("both declared final strata required")
    verify_frozen()
    endpoints = verify_embargo(campaign_directories, root)
    coordinator = measurement_coordinator or MeasurementCoordinator()
    final_owner = SimpleNamespace(actor_id='final-assessment-owner')
    backends = {key: CoordinatedBackend(NativeBackend(value), coordinator) for key, value in configurations.items()}
    for key, backend in backends.items():
        c = backend.config
        if c.benchmark_suite != key or c.correctness_suite != key or c.paired_blocks != 30:
            raise IntegrityError("final suite or thirty-block configuration mismatch")
        backend.verify()
    reference = configurations["transfer"]
    for key in ("compiler", "contract_directory", "driver", "ordinary", "diagnostic"):
        if getattr(reference, key) != getattr(configurations["shift"], key):
            raise IntegrityError("final strata use unequal program treatment")
    if output != (root / "assessment/final").resolve():
        raise IntegrityError("one canonical final assessment destination is required")
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "schema_version": 3, "status": "running", "started_unix": time.time(),
        "planned_campaigns": list(EXPECTED_CAMPAIGNS), "endpoints": endpoints,
        "rows": [], "operations": [], "fixed_source_no_reselection": True,
        "configuration_hashes": {k: b.config_hash for k, b in backends.items()},
        "measurement_retry_policy": "infrastructure_only_first_valid_v1",
        "interpretation": "fresh final comparisons; campaign completion status retained",
    }
    write_new(output / "initial.json", report)
    seed_dir = root / "task/seed"
    seed_files = tree(seed_dir)
    seed_hash = digest(encoded(seed_files))
    verified_builds = {}

    def check_sources():
        check_cancelled()
        verify_frozen()
        if tree(seed_dir) != seed_files:
            raise IntegrityError("original seed changed during final evaluation")
        current = verify_embargo(campaign_directories, root)
        if current != endpoints:
            raise IntegrityError("campaign endpoint changed during final evaluation")
        for path, expected in verified_builds.items():
            if path.is_symlink() or not path.is_file() or file_hash(path) != expected:
                raise IntegrityError("fresh assessment binary changed")

    def operation_attempt(kind, subdirectory, source, source_hash, *, stratum="transfer", build=None,
                          baseline=None, measurement=None):
        check_sources()
        before = tree(source)
        if digest(encoded(before)) != source_hash:
            raise IntegrityError("operation source hash mismatch")
        path = output / subdirectory
        path.mkdir(parents=True, exist_ok=False)
        context = {
            "source_directory": source, "build_directory": build["directory"] if build else None,
            "build": build["result"] if build else None, "baseline": baseline,
            "request": {"fixture_id": None, **(measurement or {})}, "check_active": check_cancelled,
            "grant": final_owner,
        }
        result = {"status": "infra_error", "operation": kind, "source_hash": source_hash,
                  "stratum": stratum, "artifact_directory": str(path.relative_to(output)),
                  "operation_id": str(path.relative_to(output)), "actor_id": final_owner.actor_id,
                  "configuration_sha256": backends[stratum].config_hash,
                  "input_library_sha256": build['result'].get('library_sha256') if build else None,
                  "reference": dict(baseline) if baseline else None, **(measurement or {})}
        try:
            result.update(backends[stratum].execute(kind, context, path))
            if kind == "build" and result.get("status") == "pass":
                library = path / result["library"]
                if library.is_symlink() or not library.resolve().is_relative_to(path) or not library.is_file():
                    raise IntegrityError("invalid final build library path")
                result["library_sha256"] = file_hash(library)
                verified_builds[library] = result["library_sha256"]
            if tree(source) != before:
                raise IntegrityError("final operation modified sealed source")
            check_sources()
        except BaseException as exc:
            result.update(status="infra_error", error_category=type(exc).__name__, error=str(exc))
            raise
        finally:
            write_new(path / "result.json", result)
            try:
                write_new(path / "files.json", {"files": tree(path)})
                report["operations"].append({**result,
                    "files_manifest": str((path / "files.json").relative_to(output)),
                    "files_manifest_sha256": file_hash(path / "files.json")})
            except BaseException as exc:
                report["operations"].append({**result, "status": "infra_error",
                    "manifest_error_category": type(exc).__name__})
                raise
        return {"directory": path, "result": result}

    def operation(kind, subdirectory, source, source_hash, *, stratum="transfer", build=None, baseline=None):
        """First assessment only; infrastructure recovery never changes its inputs."""
        if kind != 'bench':
            return operation_attempt(kind, subdirectory, source, source_hash,
                                     stratum=stratum, build=build, baseline=baseline)
        measurement_id = uuid.uuid4().hex
        prior_attempts = []
        reason = None
        while True:
            check_cancelled()
            number = len(prior_attempts) + 1
            # Siblings preserve earlier attempt trees and their file manifests.
            destination = subdirectory if number == 1 else f'{subdirectory}-attempt-{number:06d}'
            metadata = {'measurement_id': measurement_id, 'measurement_attempt_number': number,
                        'measurement_prior_attempt_ids': list(prior_attempts), 'measurement_retry_reason': reason,
                        'measurement_selection_rule': 'first_complete_valid_attempt',
                        'measurement_retry_policy': 'infrastructure_only_first_valid_v1'}
            attempt = operation_attempt(kind, destination, source, source_hash,
                        stratum=stratum, build=build, baseline=baseline, measurement=metadata)
            reason = DevelopmentService._retryable_measurement_reason(attempt['result'])
            if reason is None:
                return attempt
            prior_attempts.append(attempt['result']['operation_id'])

    try:
        seed = operation("build", "seed/build", seed_dir, seed_hash)
        if seed["result"]["status"] != "pass":
            raise IntegrityError("final seed build failed")
        baseline = {"source_hash": seed_hash, "path": str(seed["directory"] / seed["result"]["library"]),
                    "library_sha256": seed["result"]["library_sha256"]}
        for stratum in STRATA:
            result = operation("test", f"seed/test-{stratum}", seed_dir, seed_hash,
                               stratum=stratum, build=seed)
            if result["result"]["status"] != "pass":
                raise IntegrityError("final seed correctness failed")
        memory = operation("memcheck", "seed/memory", seed_dir, seed_hash, build=seed)
        if memory["result"]["status"] != "pass":
            raise IntegrityError("final seed memory diagnostic failed")
        for endpoint in endpoints:
            name, status = endpoint["campaign_id"], endpoint["campaign_status"]
            source_hash = endpoint["endpoint"].get("source_hash")
            if source_hash is None:
                report["rows"].extend({"campaign_id": name, "campaign_status": status,
                    "stratum": s, "status": "endpoint_unavailable", "speedup": None} for s in STRATA)
                continue
            source = Path(endpoint["source_directory"])
            built = operation("build", f"{name}/build", source, source_hash)
            memory = None
            tests = {}
            if built["result"]["status"] == "pass":
                memory = operation("memcheck", f"{name}/memory", source, source_hash, build=built)
                for stratum in STRATA:
                    tests[stratum] = operation("test", f"{name}/test-{stratum}", source, source_hash,
                                               stratum=stratum, build=built)
            valid = (built["result"]["status"] == "pass" and memory is not None
                     and memory["result"]["status"] == "pass"
                     and set(tests) == set(STRATA)
                     and all(value["result"]["status"] == "pass" for value in tests.values()))
            for stratum in STRATA:
                row = {"campaign_id": name, "campaign_status": status, "stratum": stratum,
                       "source_hash": source_hash, "seed_hash": seed_hash}
                if not valid:
                    row.update(status="endpoint_validation_failed", speedup=None)
                elif source_hash == seed_hash:
                    row.update(status="identical_source", algebraic_identity_ratio=1.0,
                               speedup=None, measured_performance=False)
                else:
                    measured = operation("bench", f"{name}/bench-{stratum}", source, source_hash,
                                         stratum=stratum, build=built, baseline=baseline)
                    result = measured["result"]
                    row.update(status="measured" if result["status"] == "pass" else "measurement_failed",
                               measured_performance=result["status"] == "pass",
                               speedup=result.get("portfolio_speedup") if result["status"] == "pass" else None,
                               family_speedups=result.get("family_speedups"),
                               descriptive_bootstrap=result.get("descriptive_bootstrap"),
                               evidence=result["artifact_directory"],
                               measurement_id=result['measurement_id'],
                               measurement_attempt_number=result['measurement_attempt_number'],
                               measurement_prior_attempt_ids=result['measurement_prior_attempt_ids'])
                report["rows"].append(row)
        check_sources()
        report["status"] = "complete"
    except BaseException as exc:
        report["status"] = "blocked"
        report["error_category"] = type(exc).__name__
        report["error"] = str(exc)
        raise
    finally:
        report["finished_unix"] = time.time()
        write_new(output / "report.json", report)
    return report
