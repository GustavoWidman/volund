"""Actual native setup controls; never launches a model or optimizer campaign."""
from __future__ import annotations
import argparse
import dataclasses
import json
from pathlib import Path
import time

from development.core import digest, encoded, file_hash, tree, write_new
from development.native_backend import NativeBackend, NativeConfig, ProcessLimits
from development.prepare import pin_config


def read_config(path):
    raw = json.loads(Path(path).read_text())
    for key in ("ordinary", "diagnostic"):
        raw[key]["cpus"] = tuple(raw[key]["cpus"])
        raw[key] = ProcessLimits(**raw[key])
    raw["allowed_suites"] = tuple(raw["allowed_suites"])
    return NativeConfig(**raw)


def run(root, output):
    root, output = Path(root).resolve(strict=True), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    public = pin_config(read_config(root / "setup/native-validation-01/native-config.json"))
    fixtures = root / "setup/final-fixtures-preparation/fixtures"
    configs = {}
    for index, stratum in enumerate(("transfer", "shift")):
        configs[stratum] = pin_config(dataclasses.replace(public, fixtures=str(fixtures),
            benchmark_suite=stratum, correctness_suite=stratum,
            allowed_suites=("transfer", "shift", "profile"), paired_blocks=30,
            case_seed=2026104001 + index * 10000,
            order_seed=2026105001 + index * 10000))
        target = root / "setup" / f"final-evaluator-config-{stratum}.json"
        write_new(target, dataclasses.asdict(configs[stratum]))
    backends = {"public": NativeBackend(public), **{k: NativeBackend(v) for k, v in configs.items()}}
    source = root / "task/seed"
    source_files = tree(source)
    source_hash = digest(encoded(source_files))
    records = []
    report = {"stage": "setup_controls_not_campaign_results", "started_unix": time.time(),
              "status": "running", "operations": records, "checks": {}, "model_calls": 0}

    def operation(kind, label, *, backend="public", build=None, candidate=source, fixture_id=None, baseline=None):
        directory = output / label
        directory.mkdir(parents=True, exist_ok=False)
        context = {"source_directory": candidate, "build_directory": build["directory"] if build else None,
                   "build": build["result"] if build else None, "baseline": baseline,
                   "request": {"fixture_id": fixture_id}, "check_active": lambda: None}
        result = {"status": "infra_error", "operation": kind, "label": label, "configuration": backend}
        try:
            result.update(backends[backend].execute(kind, context, directory))
            if kind == "build" and result["status"] == "pass":
                result["library_sha256"] = file_hash(directory / result["library"])
            if tree(source) != source_files:
                raise RuntimeError("setup modified original seed")
        except BaseException as exc:
            result.update(status="infra_error", error_category=type(exc).__name__, error=str(exc))
            raise
        finally:
            write_new(directory / "result.json", result)
            records.append(result)
            print(json.dumps({"setup_operation": label, "status": result["status"]}), flush=True)
        return {"directory": directory, "result": result}

    try:
        seed = operation("build", "seed-build")
        if seed["result"]["status"] != "pass":
            raise RuntimeError("seed setup build failed")
        baseline = {"source_hash": source_hash, "library_sha256": seed["result"]["library_sha256"],
                    "path": str(seed["directory"] / seed["result"]["library"])}
        for suite in ("public", "transfer", "shift"):
            result = operation("test", "seed-correctness-" + suite, backend=suite, build=seed)
            report["checks"]["seed_correctness_" + suite] = result["result"]["status"] == "pass"
        memory = operation("memcheck", "seed-memory-all-public-profiles", build=seed)
        report["checks"]["all_memory_profiles"] = (memory["result"]["status"] == "pass"
            and memory["result"].get("coverage_complete") is True)
        profiles = []
        for fixture in backends["public"].fixtures("profile"):
            result = operation("profile", "seed-profile-" + fixture["id"], build=seed, fixture_id=fixture["id"])
            profiles.append(result["result"]["status"] == "pass")
        report["checks"]["all_callgrind_profiles"] = len(profiles) == 6 and all(profiles)
        wrong = output / "wrong-source"
        wrong.mkdir()
        original = (source / "engine.cpp").read_text()
        needle = "answer.sum += static_cast<std::int64_t>(it->value);"
        if original.count(needle) != 1:
            raise RuntimeError("wrong-result control no longer applies to declared seed")
        (wrong / "engine.cpp").write_text(original.replace(needle,
            "answer.sum += static_cast<std::int64_t>(it->value) + 1;"))
        mutant = operation("build", "wrong-result-build", candidate=wrong)
        if mutant["result"]["status"] != "pass":
            raise RuntimeError("wrong-result control did not compile")
        result = operation("test", "wrong-result-final-correctness", backend="transfer", build=mutant, candidate=wrong)
        report["checks"]["compiled_wrong_result_rejected"] = (
            result["result"]["status"] == "candidate_failure"
            and result["result"].get("summary", {}).get("semantic_failures", 0) > 0)
        aa = operation("bench", "public-aa-10-blocks", build=seed, baseline=baseline)
        aa_result = aa["result"]
        if aa_result["status"] == "pass":
            gate = (aa_result["portfolio_speedup"] >= 1.03
                and aa_result["descriptive_bootstrap"]["one_sided_lower_bound"] > 1.0
                and min(aa_result["family_speedups"].values()) >= 1 / 1.10)
            report["checks"]["aa_operational_improvement_rejected"] = not gate
            report["aa_screen"] = {"portfolio_speedup": aa_result["portfolio_speedup"],
                "nominal90_lower": aa_result["descriptive_bootstrap"]["one_sided_lower_bound"],
                "passed_improvement_gate": gate,
                "interpretation": "Single setup control; no threshold tuning or rerun-to-pass"}
        else:
            report["checks"]["aa_operational_improvement_rejected"] = False
        final_aa = operation("bench", "final-transfer-aa-30-blocks", backend="transfer", build=seed, baseline=baseline)
        report["checks"]["thirty_block_final_route_completed"] = final_aa["result"]["status"] == "pass"
        report["status"] = "pass" if all(report["checks"].values()) else "fail"
    except BaseException as exc:
        report.update(status="blocked", error_category=type(exc).__name__, error=str(exc))
        raise
    finally:
        report["finished_unix"] = time.time()
        write_new(output / "setup-controls.json", report)
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    result = run(Path(__file__).resolve().parents[1], args.output)
    print(json.dumps({"stage": result["stage"], "status": result["status"], "checks": result["checks"]}))
    raise SystemExit(0 if result["status"] == "pass" else 1)
