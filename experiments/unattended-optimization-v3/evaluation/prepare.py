"""Prepare deterministic owner-only final fixtures; never executes candidates.

Freeze this source, the public definitions it reads, the generated definitions
and generator/oracle hashes before measured agents start. Do not expose generated
final fixtures to participants. Generation is a setup action, not an assessment.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHIFTS = {
    "small_build": (2400, 48, 61, "clustered", 1_000_000),
    "sparse_narrow": (280000, 2200, 512, "clustered", 4_000_000),
    "dense_wide": (350000, 720, 24, "clustered", 1_000_000),
    "global_mixed": (200000, 1800, 128, "uniform", (1 << 48) - 1),
    "skewed": (380000, 1400, 1024, "clustered", 8_000_000),
    "high_cardinality": (320000, 2400, 90000, "uniform", (1 << 48) - 1),
}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def definitions(public):
    if {x["shape"] for x in public["development"]} != set(SHIFTS):
        raise ValueError("expected exactly the six declared development families")
    if len(public["development"]) != 6:
        raise ValueError("duplicate development family")
    result = {
        "schema_version": 1,
        "status": "owner_only_final_fixture_definition_draft_until_protocol_freeze",
        "seed_namespace": "v2-final-20261001",
        "transfer": [], "shift": [], "profile": copy.deepcopy(public["profile"]),
    }
    for index, original in enumerate(public["development"]):
        shape = original["shape"]
        same = copy.deepcopy(original)
        same.update(id="v2-transfer-" + shape, seed=2026101001 + index)
        result["transfer"].append(same)
        shift = copy.deepcopy(original)
        n, q, streams, distribution, maximum = SHIFTS[shape]
        shift.update(id="v2-shift-" + shape, seed=2026102001 + index,
                     event_count=n, query_count=q, stream_cardinality=streams,
                     timestamp_distribution=distribution, timestamp_max=maximum)
        if shape == "sparse_narrow":
            shift["narrow_width_max"] = 4000
        if shape == "skewed":
            shift["hot_event_fraction"] = 0.97
            shift["hot_query_fraction"] = 0.80
        shift["direct_crosscheck"] = {
            "mode": "sampled", "query_indices": sorted({0, q // 4, q // 2, q - 1})}
        result["shift"].append(shift)
    # These public diagnostics intentionally overlap development; transfer and
    # shifted performance inputs plus final random correctness cases do not.
    return result


def prepare(output: Path, public_path: Path):
    public = json.loads(public_path.read_text())
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    spec_path = output / "definitions.json"
    spec_path.write_text(json.dumps(definitions(public), indent=2, sort_keys=True) + "\n")
    generator = ROOT / "development/native/generate_public.py"
    spec = importlib.util.spec_from_file_location("v2_final_generator", generator)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest = module.generate(spec_path, output / "fixtures",
                               suites=("transfer", "shift", "profile"))
    record = {
        "status": "generated_setup_inputs_not_candidate_assessment",
        "public_definitions_sha256": sha256(public_path),
        "final_definitions_sha256": sha256(spec_path),
        "generator_sha256": sha256(generator),
        "prepare_sha256": sha256(__file__),
        "fixture_manifest_sha256": sha256(output / "fixtures/manifest.json"),
        "counts": {key: len(value) for key, value in manifest["suites"].items()},
        "candidate_execution": False,
        "limitations": ["Shared generator and predicate implementations require setup controls",
                        "Role-based embargo is not proof of adversarial filesystem isolation"],
    }
    (output / "preparation.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--public-definitions", type=Path,
                        default=ROOT / "development/native/definitions.draft.json")
    args = parser.parse_args()
    print(json.dumps(prepare(args.output, args.public_definitions), sort_keys=True))
