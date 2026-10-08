#!/usr/bin/env python3
"""Opt-in native remeasurement in an explicitly prepared fresh environment.

This does not launch models or re-run the historical evaluator. It builds the
archived seed and the three fixed endpoints using replay-only configurations.
Never invoke on a host while the measured campaigns are active.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import time
from evidence import CAMPAIGNS, Refusal, digest, encoded, read, sha, verify_bundle, write_new, loads, outside_study
from remap_native_config import absolute, PATH_FIELDS, require_outside_historical, no_symlink_path


def validate_replay_config(root, freeze, original, row):
    """Only paths, two CPU IDs and declared dependency pins may differ."""
    if set(row) != set(original):
        raise Refusal("Replay config key inventory differs from archived configuration")
    for key in original:
        if key in PATH_FIELDS or key == "pinned_files":
            continue
        if key in {"ordinary", "diagnostic"}:
            cpus = row[key].get("cpus")
            if not isinstance(cpus, list) or len(cpus) != 2 or len(set(cpus)) != 2 or any(type(x) is not int or x < 0 for x in cpus):
                raise Refusal("Exactly two explicit replay CPUs required")
            if {k: v for k, v in row[key].items() if k != "cpus"} != {k: v for k, v in original[key].items() if k != "cpus"}:
                raise Refusal("Replay resource limits changed")
        elif row[key] != original[key]:
            raise Refusal("Replay changed a nonpath scientific parameter: " + key)
    if row["ordinary"]["cpus"] != row["diagnostic"]["cpus"]:
        raise Refusal("Replay CPU assignments differ")
    if len(row["pinned_files"]) != len(original["pinned_files"]):
        raise Refusal("Replay pin inventory changed")
    original_root = freeze["manifest"]["root"]
    for relative, expected in freeze["manifest"]["files"].items():
        if original_root + "/" + relative in original["pinned_files"]:
            mapped = str((root / relative).resolve())
            if row["pinned_files"].get(mapped) != expected:
                raise Refusal("Archived source pin missing or changed in replay configuration")
    for old_path, expected in original["pinned_files"].items():
        try:
            suffix = Path(old_path).relative_to(original["fixtures"])
        except ValueError:
            continue
        mapped = str(Path(row["fixtures"]) / suffix)
        if row["pinned_files"].get(mapped) != expected:
            raise Refusal("Fixture bytes may be relocated but not repinned")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--transfer-config", type=Path, required=True)
    parser.add_argument("--shift-config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--execute-in-prepared-fresh-environment", action="store_true", required=True)
    parser.add_argument("--native-measurements-finished", action="store_true", required=True)
    args = parser.parse_args()
    if not args.execute_in_prepared_fresh_environment:
        raise Refusal("Explicit native execution opt-in required")
    bundle, output = args.bundle.resolve(strict=True), args.out.resolve()
    outside_study(output, bundle)
    require_outside_historical(output)
    require_outside_historical(args.transfer_config)
    require_outside_historical(args.shift_config)
    if output.exists() or output.is_relative_to(bundle):
        raise Refusal("Native replay requires a new output directory outside the archive")
    verification = verify_bundle(bundle, args.manifest_sha256)
    if not verification["scientific_result_release"]:
        raise Refusal("A stopped public record cannot authorize full-cohort native final replay")
    root = bundle / "study"
    freeze = read(root, "state/freeze.json")
    # This import can define subprocess helpers, but no process starts until execute.
    # The explicitly selected archived code is verified above before importing it.
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(root))
    from development.core import tree, file_hash
    from development.native_backend import NativeBackend, NativeConfig, ProcessLimits
    configs = {}
    for stratum, path in (("transfer", args.transfer_config), ("shift", args.shift_config)):
        if path.resolve().is_relative_to(bundle):
            raise Refusal("Use a replay config outside historical evidence")
        row = loads(path.read_bytes())
        original = read(root, f"setup/final-evaluator-config-{stratum}.json")
        validate_replay_config(root, freeze, original, row)
        receipt = loads(Path(str(path) + ".receipt.json").read_bytes())
        if (receipt.get("archive_manifest_sha256") != args.manifest_sha256
                or receipt.get("historical_config_sha256") != sha(root / f"setup/final-evaluator-config-{stratum}.json")
                or receipt.get("replay_config_sha256") != sha(path)):
            raise Refusal("Replay configuration lacks its matching archive-bound remap receipt")
        for field in PATH_FIELDS:
            absolute(row[field])
            no_symlink_path(row[field])
        for pinned in row["pinned_files"]:
            absolute(pinned)
        for field in ("compiler", "driver", "callgrind", "annotate"):
            if Path(row[field]).resolve().is_relative_to(bundle):
                raise Refusal("Prepare fresh native dependencies outside the archive: " + field)
        for kind in ("ordinary", "diagnostic"):
            row[kind]["cpus"] = tuple(row[kind]["cpus"]); row[kind] = ProcessLimits(**row[kind])
        if "allowed_suites" in row: row["allowed_suites"] = tuple(row["allowed_suites"])
        config = NativeConfig(**row)
        if config.paired_blocks != 30 or config.benchmark_suite != stratum or config.correctness_suite != stratum:
            raise Refusal("Replay requires the archived final suite and thirty-block definition")
        backend = NativeBackend(config); backend.verify(); configs[stratum] = backend
    for field in ("compiler", "contract_directory", "driver", "ordinary", "diagnostic"):
        if getattr(configs["transfer"].config, field) != getattr(configs["shift"].config, field):
            raise Refusal("Transfer and shift use different program treatments")
    output.mkdir(parents=True)
    report = {"schema_version": 1, "kind": "posthoc_fresh_native_remeasurement_not_canonical_assessment", "status": "running",
              "archive_manifest_sha256": args.manifest_sha256, "started_unix": time.time(), "rows": [], "operations": [],
              "configuration_sha256": {"transfer": sha(args.transfer_config), "shift": sha(args.shift_config)},
              "no_model_execution": True, "endpoint_reselection": False,
              "historical_assessment_mutated": False, "posthoc_retries": "none; every attempted operation retained"}
    write_new(output / "initial.json", report)

    def operation(kind, name, source, source_hash, *, stratum="transfer", build=None, baseline=None):
        before = tree(source)
        if digest(encoded(before)) != source_hash:
            raise Refusal("Replay source hash differs from archived seal")
        directory = output / name; directory.mkdir(parents=True, exist_ok=False)
        context = {"source_directory": source, "build_directory": build["directory"] if build else None,
                   "build": build["result"] if build else None, "baseline": baseline,
                   "request": {"fixture_id": None}, "check_active": lambda: None}
        result = {"status": "infra_error", "operation": kind, "source_hash": source_hash, "stratum": stratum,
                  "configuration_sha256": configs[stratum].config_hash}
        try:
            result.update(configs[stratum].execute(kind, context, directory))
            if result["status"] == "pass" and kind == "build":
                result["library_sha256"] = file_hash(directory / result["library"])
            if tree(source) != before:
                raise Refusal("Replay source changed during native operation")
        except BaseException as exc:
            result.update(status="infra_error", error_category=type(exc).__name__, error=str(exc))
            raise
        finally:
            write_new(directory / "result.json", result)
            report["operations"].append({"directory": name, "result_sha256": sha(directory / "result.json"), **result})
        return {"directory": directory, "result": result}

    try:
        seed_dir = root / "task/seed"; seed_hash = digest(encoded(tree(seed_dir)))
        seed = operation("build", "seed/build", seed_dir, seed_hash)
        if seed["result"]["status"] != "pass": raise Refusal("Replay seed build failed")
        baseline = {"source_hash": seed_hash, "path": str(seed["directory"] / seed["result"]["library"]), "library_sha256": seed["result"]["library_sha256"]}
        for stratum in ("transfer", "shift"):
            if operation("test", "seed/test-" + stratum, seed_dir, seed_hash, stratum=stratum, build=seed)["result"]["status"] != "pass":
                raise Refusal("Replay seed semantic validation failed")
        if operation("memcheck", "seed/memory", seed_dir, seed_hash, build=seed)["result"]["status"] != "pass":
            raise Refusal("Replay seed memory validation failed")
        for name in CAMPAIGNS:
            state = read(root, f"campaigns/{name}/authority/state.json"); source_hash = state["endpoint"].get("source_hash")
            if source_hash is None:
                report["rows"].append({"campaign_id": name, "status": "endpoint_unavailable"}); continue
            source = root / "campaigns" / name / "development/snapshots" / source_hash
            built = operation("build", name + "/build", source, source_hash)
            valid = built["result"]["status"] == "pass"
            if valid:
                valid = operation("memcheck", name + "/memory", source, source_hash, build=built)["result"]["status"] == "pass"
                for stratum in ("transfer", "shift"):
                    ok = operation("test", name + "/test-" + stratum, source, source_hash, stratum=stratum, build=built)["result"]["status"] == "pass"
                    valid = valid and ok
            for stratum in ("transfer", "shift"):
                row = {"campaign_id": name, "stratum": stratum, "source_hash": source_hash, "speedup": None}
                if not valid: row["status"] = "endpoint_validation_failed"
                elif source_hash == seed_hash: row.update(status="identical_source", algebraic_identity_ratio=1.0)
                else:
                    result = operation("bench", name + "/bench-" + stratum, source, source_hash, stratum=stratum, build=built, baseline=baseline)["result"]
                    row.update(status=result["status"], speedup=result.get("portfolio_speedup") if result["status"] == "pass" else None)
                report["rows"].append(row)
        report["status"] = "complete"
    except BaseException as exc:
        report.update(status="blocked", error_category=type(exc).__name__, error=str(exc)); raise
    finally:
        report["finished_unix"] = time.time(); write_new(output / "report.json", report)
    print(json.dumps({"status": report["status"], "report_sha256": sha(output / "report.json")}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (Refusal, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "refused", "reason": str(exc)}), file=sys.stderr)
        raise SystemExit(2)
