#!/usr/bin/env python3
"""Create a replay-only path/CPU map with immutable source and fixture pins.

Prepared external tools/driver may receive explicitly requested new dependency
hashes. Archived source and input bytes never receive replacement pins.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path, PurePosixPath
import sys
from evidence import (Refusal, PRIVATE_PARTS, PRIVATE_NAMES, sha, write_new, loads,
                      read, verify_bundle, outside_study)

PATH_FIELDS = {"contract_directory", "compiler", "driver", "fixtures", "callgrind", "annotate", "valgrind_lib", "debuginfo_root"}


def absolute(value):
    if (not isinstance(value, str) or not value.startswith("/") or "\\" in value or any(ord(c) < 32 or ord(c) == 127 for c in value) or ":" in value
            or any(p in ("", ".", "..") for p in value.split("/")[1:])):
        raise Refusal("Mapping requires canonical absolute paths")
    p = PurePosixPath(value)
    if any(x.lower() in PRIVATE_PARTS or x.lower() in PRIVATE_NAMES or x.lower().startswith(".env.") for x in p.parts):
        raise Refusal("Replay must never refer to authentication/private directories")
    return p


def translate(value, mappings):
    path = absolute(value)
    matches = []
    for row in mappings:
        try:
            suffix = path.relative_to(absolute(row["from"]))
        except ValueError:
            continue
        matches.append((len(PurePosixPath(row["from"]).parts), absolute(row["to"]) / suffix))
    if not matches:
        raise Refusal("No explicit mapping for " + value)
    matches.sort(key=lambda row: row[0], reverse=True)
    if len(matches) > 1 and matches[0][0] == matches[1][0]:
        raise Refusal("Ambiguous mapping")
    return str(matches[0][1])


def no_symlink_path(path):
    path = Path(path)
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise Refusal("Replay path contains a symlink; map the resolved target explicitly")
    return path


def prepared_file(path):
    path = no_symlink_path(path)
    if not path.is_file():
        raise Refusal("Prepared replay dependency missing: " + str(path))
    return path


def remap(original, mappings, cpus, *, rehash=False, immutable_pins=None):
    if not isinstance(mappings, list) or not mappings:
        raise Refusal("Explicit nonempty from/to mappings required")
    for row in mappings:
        if set(row) != {"from", "to"}:
            raise Refusal("Mapping rows must have exactly from and to fields")
        absolute(row["from"])
        absolute(row["to"])
    if len(cpus) != 2 or len(set(cpus)) != 2 or any(type(x) is not int or x < 0 for x in cpus):
        raise Refusal("Exactly two unique logical CPU numbers required")
    immutable_pins = immutable_pins or {}
    result = loads(json.dumps(original))
    changes, differences, source_checks = [], [], []
    for field in sorted(PATH_FIELDS):
        result[field] = translate(original[field], mappings)
        no_symlink_path(result[field])
        changes.append({"field": field, "historical": original[field], "replay": result[field]})
    for kind in ("ordinary", "diagnostic"):
        changes.append({"field": kind + ".cpus", "historical": original[kind]["cpus"], "replay": cpus})
        result[kind]["cpus"] = cpus
    pins = {}
    for old_path, old_hash in original["pinned_files"].items():
        new_path = translate(old_path, mappings)
        if new_path in pins:
            raise Refusal("Remapping collapses distinct pinned artifacts")
        expected = old_hash
        immutable = old_path in immutable_pins or PurePosixPath(old_path).is_relative_to(absolute(original["fixtures"]))
        if old_path in immutable_pins and old_hash != immutable_pins[old_path]:
            raise Refusal("Config source pin differs from original freeze")
        if rehash or immutable:
            actual = sha(prepared_file(new_path))
            if immutable and actual != old_hash:
                raise Refusal("Prepared source/fixture differs; it cannot be repinned")
            expected = actual
        if immutable:
            source_checks.append({"historical_path": old_path, "replay_path": new_path, "sha256": expected})
        pins[new_path] = expected
        if expected != old_hash:
            differences.append({"historical_path": old_path, "replay_path": new_path,
                                "historical_sha256": old_hash, "replay_sha256": expected})
    result["pinned_files"] = pins
    return result, {"status": "posthoc_replay_only_not_historical_freeze", "paths_and_cpu_changes": changes,
                    "new_dependency_hashes_computed": rehash, "changed_dependency_pins": differences,
                    "immutable_source_and_fixture_pins_verified": source_checks,
                    "preserved_nonpath_parameters": True, "native_execution_performed": False,
                    "limitation": "New dependency hashes document new materials, not equivalence to the measured host"}


def require_outside_historical(path):
    path = Path(path).absolute()
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise Refusal("Output/config path contains a symlink")
        if (parent / "state/freeze.json").exists():
            raise Refusal("Replay output/config must be outside historical study trees")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--stratum", choices=("transfer", "shift"), required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--cpus", type=int, nargs=2, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rehash-prepared-dependencies", action="store_true")
    parser.add_argument("--native-measurements-finished", action="store_true", required=True)
    args = parser.parse_args()
    try:
        outside_study(args.out, args.bundle)
        require_outside_historical(args.out)
        if args.out.exists() or Path(str(args.out) + ".receipt.json").exists():
            raise Refusal("Use fresh config and receipt paths")
        verify_bundle(args.bundle, args.manifest_sha256)
        root = args.bundle / "study"
        freeze = read(root, "state/freeze.json")
        config_path = root / f"setup/final-evaluator-config-{args.stratum}.json"
        original = loads(config_path.read_bytes())
        immutable = {freeze["manifest"]["root"] + "/" + path: value for path, value in freeze["manifest"]["files"].items()}
        result, receipt = remap(original, loads(args.mapping.read_bytes()), args.cpus,
                                rehash=args.rehash_prepared_dependencies, immutable_pins=immutable)
        receipt.update(archive_manifest_sha256=args.manifest_sha256, historical_config_sha256=sha(config_path), mapping_sha256=sha(args.mapping))
        write_new(args.out, result)
        receipt["replay_config_sha256"] = sha(args.out)
        write_new(str(args.out) + ".receipt.json", receipt)
        print(json.dumps(receipt, indent=2))
    except (Refusal, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "refused", "reason": str(exc)}), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
