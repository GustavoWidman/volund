"""Real, bounded setup guards: input mutation, RSS rejection and escaped child cleanup."""
import dataclasses
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from development.core import file_hash, write_new
from development.native_backend import NativeBackend, run_process
from development.prepare import pin_config
from evaluation.validate_setup import read_config


def main():
    output = ROOT / "setup/additional-guard-controls-01"
    output.mkdir(parents=True, exist_ok=False)
    config = pin_config(read_config(ROOT / "setup/native-validation-01/native-config.json"))
    backend = NativeBackend(config)
    original = ROOT / "task/seed/engine.cpp"
    before = file_hash(original)
    mutant = output / "input-mutant"
    mutant.mkdir()
    text = original.read_text()
    needle = "        return 0;"
    assert text.count(needle) == 1
    (mutant / "engine.cpp").write_text(text.replace(needle,
        "        if (event_count) const_cast<Event*>(events)[0].value ^= 1;\n" + needle))
    context = {"source_directory": mutant, "build": None, "build_directory": None,
               "baseline": None, "request": {"fixture_id": None}, "check_active": lambda: None}
    builddir = output / "build"
    builddir.mkdir()
    build = backend.execute("build", context, builddir)
    assert build["status"] == "pass"
    build["library_sha256"] = file_hash(builddir / build["library"])
    write_new(builddir / "result.json", build)
    context.update(build=build, build_directory=builddir)
    testdir = output / "test"
    testdir.mkdir()
    tested = backend.execute("test", context, testdir)
    write_new(testdir / "result.json", tested)
    limit = dataclasses.replace(config.ordinary, wall_seconds=0.35, cpu_seconds=1)
    child = "import time; time.sleep(30)"
    program = ("import subprocess,sys,time; "
               "p=subprocess.Popen([sys.executable,'-c'," + repr(child) + "],start_new_session=True); "
               "print(p.pid,flush=True); time.sleep(30)")
    timed = run_process([sys.executable, "-B", "-c", program], output / "watchdog", output,
                        limit, {"check_active": lambda: None})
    rss_limit = dataclasses.replace(config.ordinary, observed_rss_kib=16384, wall_seconds=5)
    rss = run_process([sys.executable, "-B", "-c", "x=bytearray(64*1024*1024); print(len(x))"],
                      output / "rss", output, rss_limit, {"check_active": lambda: None})
    checks = {
        "compiled_input_mutation_rejected": tested["status"] == "candidate_failure"
             and tested.get("summary", {}).get("semantic_failures", 0) > 0,
        "technical_wall_watchdog_fired": timed["status"] == "timeout",
        "tracked_child_cleanup_complete": timed.get("cleanup", {}).get("tracked_processes_exited") is True,
        "rss_excess_rejected": rss["status"] == "candidate_failure" and rss["peak_rss_kib"] > 16384,
        "seed_unchanged": file_hash(original) == before,
    }
    report = {"stage": "native_setup_controls_not_campaign", "status": "pass" if all(checks.values()) else "fail",
              "checks": checks, "input_mutant": tested, "watchdog": timed, "rss": rss,
              "model_calls": 0, "native_benchmark_calls": 0, "source_sha256": file_hash(__file__),
              "configuration_sha256": backend.config_hash, "completed_unix": time.time()}
    write_new(output / "controls.json", report)
    print(json.dumps({"status": report["status"], "checks": checks}))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
