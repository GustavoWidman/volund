#!/usr/bin/env python3
"""Independent offline replay of sealed v3 sources, lineages and raw timing blocks.

No execution-module imports, final fixture payload reads, compilation, profiling, model
execution, endpoint selection, or mutation of the historical assessment.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import sys
from evidence import (CAMPAIGNS, FROZEN_SHA256, Refusal, digest, encoded,
                      historical_relative, local, read, release_gate, sha,
                      write_new, verify_bundle, outside_study, loads, safe_relative)

def measurement_eligible(result):
    """Retained timing fields do not survive an invalidation as scientific values."""
    return (result.get("status") == "pass" and not result.get("measurement_invalidated")
            and not result.get("integrity_error")
            and not result.get("confirmed_semantic_failure")
            and not result.get("confirmed_memory_error")
            and (result.get("ordinary_command_overlap_audit") or {}).get("status") != "invalid_overlap")


def retry_reason(result):
    """Read-only mirror of the frozen infrastructure-only attestation predicate."""
    if (result.get("status") != "infra_error" or result.get("measurement_retry_authorized") is not True
            or result.get("measurement_retry_policy") != "infrastructure_only_first_valid_v1"
            or result.get("confirmed_semantic_failure") is True
            or result.get("confirmed_memory_error") is True or result.get("integrity_error")):
        return None
    audit = result.get("ordinary_command_overlap_audit") or {}
    if audit.get("backend_exception") is not None:
        return None
    reason = result.get("measurement_invalidated")
    if (reason == "competing_study_command_execution" and audit.get("status") == "invalid_overlap"
            and audit.get("ordinary_command_overlaps")):
        return reason
    interrupted = audit.get("external_interruption") or {}
    if (reason == "attested_external_interruption" and interrupted.get("cleanup_confirmed") is True
            and interrupted.get("cause") == "external_preemption"
            and isinstance(interrupted.get("observer"), str) and interrupted["observer"].strip()
            and isinstance(interrupted.get("event_id"), str) and interrupted["event_id"].strip()):
        return reason
    return None


def select_measurements(operations):
    """Bind every retry and select first valid attempts; never inspect their scores."""
    groups, official = {}, {}
    for op_id, op in operations.items():
        op["selected_for_scoring"] = False
        if op.get("operation") != "bench" or op.get("status") == "unsealed_operation":
            continue
        mid = op.get("measurement_id")
        if not isinstance(mid, str) or not mid:
            raise Refusal("V3 comparison has no immutable measurement identity")
        groups.setdefault(mid, []).append((op_id, op))
    for attempts in groups.values():
        attempts.sort(key=lambda pair: pair[1]["finish_sequence"])
        prior, binding, previous_reason = [], None, None
        for number, (op_id, op) in enumerate(attempts, 1):
            if (op.get("measurement_attempt_number") != number
                    or op.get("measurement_prior_attempt_ids") != prior
                    or op.get("measurement_retry_reason") != previous_reason
                    or op.get("measurement_selection_rule") != "first_complete_valid_attempt"
                    or op.get("measurement_retry_policy") != "infrastructure_only_first_valid_v1"):
                raise Refusal("Comparison attempt chain or selection policy differs")
            current = {key: op.get(key) for key in ("source_hash", "build_id", "input_library_sha256",
                "configuration_sha256", "reference", "reference_id", "purpose", "review_plan_id", "stratum")}
            if binding is not None and current != binding:
                raise Refusal("Retried comparison changed its source, binary, reference or configuration")
            binding = current
            if prior and previous_reason is None:
                raise Refusal("Comparison retried after a binding valid or nonretryable result")
            op["selected_for_scoring"] = measurement_eligible(op)
            op["selection_basis"] = "first_valid_measurement_attempt" if op["selected_for_scoring"] else "invalid_or_failed_attempt"
            previous_reason = retry_reason(op)
            prior.append(op_id)
            if op["selected_for_scoring"] and op.get("purpose") == "official_review":
                key = (op.get("review_plan_id"), op.get("source_hash"), (op.get("reference") or {}).get("source_hash"))
                if not key[0]:
                    raise Refusal("Official comparison lacks review plan")
                official.setdefault(key, []).append((op_id, op))
    for attempts in official.values():
        attempts.sort(key=lambda pair: pair[1]["finish_sequence"])
        for _, op in attempts[1:]:
            op["selected_for_scoring"] = False
            op["selection_basis"] = "later_valid_official_rerun_process_only"
    return operations


def close(actual, expected):
    if type(expected) not in (int, float) or not math.isfinite(expected) or not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12):
        raise Refusal("Archived statistic does not match replay")


def reduce_pairs(pairs, resamples, seed, confidence):
    logs = {}
    for name, rows in pairs.items():
        if not isinstance(name, str) or not isinstance(rows, list):
            raise Refusal("Invalid paired-data schema")
        values = []
        for row in rows:
            a, b = row["baseline"], row["candidate"]
            if type(a) not in (int, float) or type(b) not in (int, float) or not math.isfinite(a + b) or min(a, b) <= 0:
                raise Refusal("Invalid paired timing")
            values.append(math.log(a / b))
        logs[name] = values
    sizes = {len(v) for v in logs.values()}
    if len(sizes) != 1 or not sizes or min(sizes) < 2 or type(resamples) is not int or resamples < 1 or type(confidence) not in (int, float) or not 0 < confidence < 1 or type(seed) is not int:
        raise Refusal("Incomplete block/bootstrap definition")
    n = next(iter(sizes))
    families = {name: math.exp(statistics.median(values)) for name, values in logs.items()}
    portfolio = math.exp(statistics.mean(statistics.median(values) for values in logs.values()))
    rng, distribution = random.Random(seed), []
    for _ in range(resamples):
        indices = rng.choices(range(n), k=n)
        distribution.append(math.exp(statistics.mean(statistics.median([values[i] for i in indices]) for values in logs.values())))
    distribution.sort()
    q = (1 - confidence) * (resamples - 1); lo, hi = math.floor(q), math.ceil(q)
    lower = distribution[lo] + (q - lo) * (distribution[hi] - distribution[lo])
    return {"blocks": n, "family_speedups": families, "portfolio_speedup": portfolio, "one_sided_lower_bound": lower}


class Archive:
    """A previously byte-verified archive plus explicit absent-byte declarations."""
    def __init__(self, root, plan):
        self.root, self.plan = Path(root), plan
        self.present = plan["files"]
        self.omitted = plan["omitted_full_archive_files"]
        self.pins = {**self.present, **self.omitted}

    def read(self, relative):
        if relative not in self.present:
            raise Refusal("Required numerical/source artifact omitted: " + relative)
        value = read(self.root, relative)
        if sha(local(self.root, relative)) != self.present[relative]["sha256"]:
            raise Refusal("Archived bytes changed during replay: " + relative)
        return value

    def hash(self, relative):
        record = self.pins.get(relative)
        if record is None:
            raise Refusal("Missing evidence pin: " + relative)
        if relative in self.present and sha(local(self.root, relative)) != record["sha256"]:
            raise Refusal("Archived bytes changed during replay: " + relative)
        return record["sha256"]

    def tree(self, relative):
        prefix = relative.rstrip("/") + "/"
        return {p[len(prefix):]: row["sha256"] for p, row in self.pins.items() if p.startswith(prefix)}

    def chain(self, relative, expected_head, expected_count=None):
        names = sorted(self.tree(relative))
        head, rows = None, []
        for number, name in enumerate(names, 1):
            if name != f"{number:08d}.json":
                raise Refusal("Noncontiguous event chain: " + relative)
            path = relative + "/" + name
            row = self.read(path)
            if row.get("sequence") != number or row.get("previous") != head:
                raise Refusal("Event chain mismatch: " + path)
            head = self.hash(path)
            rows.append(row)
        if head != expected_head or expected_count is not None and len(rows) != expected_count:
            raise Refusal("Event anchor mismatch: " + relative)
        return rows


def audit_workflow(archive, campaign, original_root):
    prefix = "campaigns/" + campaign
    state = archive.read(prefix + "/authority/state.json")
    anchor = archive.read(prefix + "/authority/anchor.json")
    owner = archive.chain(prefix + "/authority/events", anchor["head"], anchor["count"])
    if digest(encoded(state)) != anchor["state_hash"] or not owner or owner[-1]["state_hash"] != anchor["state_hash"]:
        raise Refusal("Unanchored owner state")
    heads = archive.read(prefix + "/authority/development-heads.json")
    key = original_root.rstrip("/") + "/" + prefix + "/development"
    if key not in heads:
        raise Refusal("Canonical development anchor missing")
    events = archive.chain(prefix + "/development/events", heads[key])
    snapshots, starts, ends, finish_times = {}, {}, {}, {}
    for event in events:
        p = event["payload"]
        if event["kind"] == "snapshot":
            existing = snapshots.get(p["source_hash"])
            if existing is not None and existing["files"] != p["files"]:
                raise Refusal("Conflicting source snapshot")
            snapshots[p["source_hash"]] = p
        elif event["kind"] == "operation_started":
            op = p["operation_id"]
            if op in starts:
                raise Refusal("Duplicate operation start")
            starts[op] = p
        elif event["kind"] == "operation_finished":
            op = p["operation_id"]
            if op in ends:
                raise Refusal("Duplicate operation finish")
            ends[op] = {**p, "finish_sequence": event["sequence"]}
            finish_times[op] = finite(event["wall_time"])
    for source_hash, snapshot in snapshots.items():
        if (digest(encoded(snapshot["files"])) != source_hash
                or archive.tree(prefix + "/development/snapshots/" + source_hash) != snapshot["files"]):
            raise Refusal("Snapshot differs from anchored source")
    snapshot_names = {p.split("/", 1)[0] for p in archive.tree(prefix + "/development/snapshots")}
    if snapshot_names != set(snapshots):
        raise Refusal("Unrecorded or missing source snapshot")
    if set(ends) - set(starts):
        raise Refusal("Finished operation lacks start")
    for op_id, request in starts.items():
        if request.get("source_hash") not in snapshots:
            raise Refusal("Started operation source has no recorded snapshot")
    for op_id, result in ends.items():
        directory = prefix + "/development/operations/" + op_id
        if archive.tree(directory) != result["files"]:
            raise Refusal("Operation file inventory differs from immutable event")
        recorded = archive.read(directory + "/result.json")
        if recorded != {k: v for k, v in result.items() if k not in {"files", "finish_sequence"}}:
            raise Refusal("Result contradicts operation-finished event")
        if any(result.get(k) != v for k, v in starts[op_id].items()):
            raise Refusal("Operation-started metadata contradicts finished result")
        if result.get("operation") == "build" and result.get("status") == "pass":
            library = result.get("library")
            if (not isinstance(library, str) or library not in result["files"]
                    or archive.hash(directory + "/" + library) != result.get("library_sha256")):
                raise Refusal("Build library differs from anchored digest")
        build_id = result.get("build_id")
        if result.get("operation") != "build" and build_id is not None:
            built = ends.get(build_id) or {}
            if (built.get("operation") != "build" or built.get("status") != "pass"
                    or built.get("source_hash") != result["source_hash"]
                    or result.get("input_library_sha256") is not None and result["input_library_sha256"] != built.get("library_sha256")):
                raise Refusal("Operation source/build/binary binding differs")
    operation_names = {p.split("/", 1)[0] for p in archive.tree(prefix + "/development/operations")}
    if operation_names - set(starts) or set(ends) - operation_names:
        raise Refusal("Unrecorded or missing operation directory")
    unsealed = sorted(set(starts) - set(ends))
    if state["status"] == "complete" and unsealed:
        raise Refusal("Complete campaign contains unfinished native operations")
    config_hash = archive.hash("setup/launch-native/native-config.json")
    for op in ends.values():
        directory = prefix + "/development/operations/" + op["operation_id"]
        for name in ("integrity-before.json", "integrity-after.json"):
            if name in op["files"]:
                if archive.read(directory + "/" + name).get("configuration_sha256") != config_hash:
                    raise Refusal("Campaign operation native configuration differs from frozen pin")
            elif op["status"] == "pass" or retry_reason(op):
                raise Refusal("Valid/retryable native attempt lacks its configuration-integrity receipt")
        # Frozen DevelopmentService binds these through build_id and NativeBackend
        # integrity receipts; unlike final operations it does not repeat the fields.
        op["configuration_sha256"] = config_hash
        if op.get("build_id") in ends:
            op["input_library_sha256"] = ends[op["build_id"]].get("library_sha256")
    select_measurements(ends)
    reviews = []
    for review_id, review in state.get("reviews", {}).items():
        receipt = review.get("receipt") or {}
        if receipt.get("status") != "execution_verified":
            continue
        reviews.append(audit_review(receipt, review_id, review, state, owner, ends, finish_times))
    endpoint = state.get("endpoint") or {}
    if endpoint.get("source_hash"):
        if endpoint["source_hash"] != (state.get("incumbent") or {}).get("source_hash") or endpoint["source_hash"] not in snapshots:
            raise Refusal("Endpoint is not the retained source")
        path = historical_relative(endpoint["library_path"], original_root)
        if path is None or not path.startswith(prefix + "/") or archive.hash(path) != endpoint["library_sha256"]:
            raise Refusal("Endpoint binary digest differs from seal")
    return {"campaign_id": campaign, "status": state["status"], "source_snapshots": len(snapshots),
            "started_operations": len(starts), "finished_operations": len(ends),
            "unsealed_operations": unsealed, "reviews": reviews}, state, ends


def finite(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise Refusal("Expected finite number")
    return value


def audit_review(receipt, review_id, review, state, owner_events, ends, finish_times):
    matching = [e for e in owner_events if e.get("kind") == "nomination_review" and (e.get("payload") or {}).get("id") == review_id]
    if len(matching) != 1 or matching[0]["payload"] != review:
        raise Refusal("Receipt lacks an exact owner review event")
    cutoff = finite(matching[0]["time_unix"])
    pool = [p for p in ends.values() if p.get("role") == "reviewer" and p.get("source_hash") == receipt["source_hash"]
            and p.get("purpose") == "official_review" and p.get("review_plan_id") == receipt["review_plan_id"]]
    chosen = receipt["official_comparison_operation_id"]
    declared = receipt["all_official_attempts"]
    ids = [p["operation_id"] for p in declared]
    if not ids or len(set(ids)) != len(ids) or not set(ids) <= {p["operation_id"] for p in pool} or chosen not in ids:
        raise Refusal("Receipt attempt inventory differs")
    selected = [p for p in pool if p["operation"] == "bench" and p["selected_for_scoring"]]
    if not selected or selected[0]["operation_id"] != chosen:
        raise Refusal("Review did not select the first complete valid observation")
    last_sequence = max(ends[x]["finish_sequence"] for x in ids)
    earlier = [p for p in pool if p["finish_sequence"] <= last_sequence]
    if any(finish_times[p["operation_id"]] > cutoff for p in earlier):
        raise Refusal("Review cutoff contradicts immutable completion order")
    through_cutoff = [p for p in pool if p["finish_sequence"] <= last_sequence or finish_times[p["operation_id"]] <= cutoff]
    if ids != [p["operation_id"] for p in through_cutoff]:
        raise Refusal("Receipt omits an official attempt through its cutoff")
    for item in declared:
        if any(ends[item["operation_id"]].get(k) != v for k, v in item.items()):
            raise Refusal("Receipt attempt metadata contradicts event")
    op = ends[chosen]
    built = ends[op["build_id"]]
    if (receipt["official_comparison_build_id"] != op["build_id"]
            or receipt["official_comparison_library_sha256"] != built["library_sha256"]
            or receipt["official_comparison_reference"] != op["reference"]):
        raise Refusal("Receipt selected source/binary/reference differs")
    nomination = state["nominations"][review["nomination_id"]]
    if any(op["reference"][key] != nomination["parent"][key] for key in ("source_hash", "library_sha256")):
        raise Refusal("Official reference differs from nominated parent")
    if any(p.get("confirmed_semantic_failure") or p.get("confirmed_memory_error") for p in through_cutoff):
        raise Refusal("Verified receipt contains confirmed disqualifying evidence")
    return {"review_id": review_id, "operation_id": chosen, "first_valid_verified": True,
            "attempts_through_cutoff": ids, "selection_basis": "immutable completion order; no score-based retries"}


def validate_raw(pairs, raw, schedule, expected_blocks):
    if (len(pairs) != 6 or expected_blocks not in (10, 30)
            or any(len(rows) != expected_blocks for rows in pairs.values())
            or len(raw) != expected_blocks * 12 or len(schedule) != expected_blocks):
        raise Refusal("Expected six complete families and the frozen block count")
    lookup = {(r["family"], r["block"], r["arm"]): r for r in raw}
    if len(lookup) != len(raw) or [r["block"] for r in schedule] != list(range(expected_blocks)):
        raise Refusal("Duplicate sample or incorrect temporal block schedule")
    expected_order = []
    for block, row in enumerate(schedule):
        if (len(row["families"]) != 6 or set(row["families"]) != set(pairs)
                or set(row["orders"]) != set(pairs)):
            raise Refusal("Scheduled family inventory differs")
        for name in row["families"]:
            order = row["orders"][name]
            if sorted(order) != ["baseline", "candidate"]:
                raise Refusal("Invalid pair arm order")
            for arm in order:
                expected_order.append((name, block, arm))
                sample = lookup.get((name, block, arm))
                if sample is None:
                    raise Refusal("Missing raw sample")
                value = finite(sample["driver"]["seconds_per_call"])
                if value <= 0:
                    raise Refusal("Nonpositive raw timing")
                if value != finite(pairs[name][block][arm]):
                    raise Refusal("Raw and paired timing bytes decode to different numbers")
    if [(r["family"], r["block"], r["arm"]) for r in raw] != expected_order:
        raise Refusal("Raw sample order differs from recorded schedule")
    for name in pairs:
        if sum(row["orders"][name][0] == "baseline" for row in schedule) != expected_blocks // 2:
            raise Refusal("Unbalanced paired arm schedule")


def validate_driver_sample(data, config, repetitions=None):
    count = data.get("repetitions")
    if type(count) is not int or not 1 <= count <= config["maximum_repetitions"]:
        raise Refusal("Invalid native repetition count")
    if repetitions is not None and count != repetitions:
        raise Refusal("Scored repetitions differ from frozen calibration")
    if type(data.get("verified_calls")) is not int or data["verified_calls"] != count + config["warmups"]:
        raise Refusal("Native verified-call count differs")
    elapsed, per_call, rss = (finite(data[k]) for k in ("elapsed_seconds", "seconds_per_call", "peak_rss_kib"))
    if min(elapsed, per_call, rss) <= 0 or rss > config["ordinary"]["observed_rss_kib"]:
        raise Refusal("Native sample elapsed/RSS limit differs")
    if not math.isclose(per_call, elapsed / count, rel_tol=1e-9, abs_tol=1e-15):
        raise Refusal("Elapsed time and normalized measurement disagree")
    target = data.get("sample_target_met")
    if type(target) is not bool or target != (elapsed >= config["minimum_sample_seconds"]):
        raise Refusal("Native sample target flag is inconsistent")
    return target


def audit_sample_files(archive, directory, result, pairs, raw, schedule):
    """Cross-check redundant native receipts; read fixture manifests, never payloads."""
    origin = archive.plan["original_study_root"]
    if directory.startswith("campaigns/"):
        config_path = "setup/launch-native/native-config.json"
        campaign = directory.split("/")[1]
        build_directory = f"campaigns/{campaign}/development/operations/{result['build_id']}"
    else:
        config_path = f"setup/final-evaluator-config-{result['stratum']}.json"
        campaign = result["operation_id"].split("/", 1)[0]
        build_directory = f"assessment/final/{campaign}/build"
    config = archive.read(config_path)
    if config["paired_blocks"] != result["paired_blocks"]:
        raise Refusal("Paired blocks differ from archived native configuration")
    for key, config_key in (("resamples", "bootstrap_resamples"), ("seed", "bootstrap_seed"), ("confidence", "bootstrap_one_sided_confidence")):
        if result["descriptive_bootstrap"][key] != config[config_key]:
            raise Refusal("Bootstrap definition differs from archived native configuration")
    if archive.read(directory + "/descriptive-bootstrap.json") != result["descriptive_bootstrap"]:
        raise Refusal("Bootstrap artifact contradicts result")
    fixture_dir = historical_relative(config["fixtures"], origin)
    if fixture_dir is None:
        raise Refusal("Frozen fixture manifest lies outside the study")
    manifest_path = fixture_dir + "/manifest.json"
    if archive.hash(manifest_path) != config["pinned_files"].get(config["fixtures"] + "/manifest.json"):
        raise Refusal("Fixture manifest differs from native pin")
    manifest = archive.read(manifest_path)
    items = manifest["suites"][config["benchmark_suite"]]
    by_id = {item["id"]: item for item in items}
    if len(by_id) != len(items) or set(by_id) != set(pairs):
        raise Refusal("Scored families differ from frozen fixture manifest")
    for item in items:
        for field in ("input", "expected"):
            name = str(safe_relative(item[field]))
            if config["pinned_files"].get(config["fixtures"] + "/" + name) != item["sha256_" + field]:
                raise Refusal("Fixture manifest input pin differs from native configuration")
    built = archive.read(build_directory + "/result.json")
    libraries = {"candidate": origin + "/" + build_directory + "/" + built["library"],
                 "baseline": result["reference"]["path"]}
    for arm, path in libraries.items():
        relative = historical_relative(path, origin)
        expected = built["library_sha256"] if arm == "candidate" else result["reference"]["library_sha256"]
        if relative is None or archive.hash(relative) != expected:
            raise Refusal("Sample library binding differs")
    calibration = archive.read(directory + "/calibration.json")
    if set(calibration) != set(pairs):
        raise Refusal("Calibration family inventory differs")

    def command_record(relative, item, arm, repetitions=None):
        command = archive.read(directory + "/" + relative)
        expected = [config["driver"], "--library", libraries[arm],
                    "--input", config["fixtures"] + "/" + str(safe_relative(item["input"])),
                    "--expected", config["fixtures"] + "/" + str(safe_relative(item["expected"])),
                    "--mode", "benchmark", "--min-seconds", str(config["minimum_sample_seconds"]),
                    "--max-repetitions", str(config["maximum_repetitions"]), "--warmups", str(config["warmups"])]
        if repetitions is not None:
            expected += ["--repetitions", str(repetitions)]
        if (command.get("command") != expected or command.get("status") != "pass" or command.get("exit_code") != 0
                or command.get("process_started") is not True
                or (command.get("cleanup") or {}).get("tracked_processes_exited") is not True
                or not 0 < finite(command["peak_rss_kib"]) <= config["ordinary"]["observed_rss_kib"]):
            raise Refusal("Native command treatment/status/cleanup contradicts scored sample")
        if command.get("limits") != config["ordinary"]:
            raise Refusal("Scored command limits differ from frozen configuration")
        return command

    orders = {}
    for name, item in by_id.items():
        entry = calibration[name]
        counts = entry["pilot_repetitions"]
        if (set(counts) != {"baseline", "candidate"} or any(type(v) is not int or v < 1 for v in counts.values())
                or entry["common_repetitions"] != max(counts.values())):
            raise Refusal("Common repetitions differ from two-arm calibration")
        for arm in ("baseline", "candidate"):
            sub = name + "/calibrate-" + arm
            command_record(sub + "/command.json", item, arm)
            data_path = directory + "/" + sub + "/stdout.txt"
            if data_path not in archive.present:
                raise Refusal("Essential pilot output omitted")
            archive.hash(data_path)
            data = loads(local(archive.root, data_path).read_bytes())
            if not validate_driver_sample(data, config, counts[arm]):
                raise Refusal("Calibration did not attain its frozen sample target")
        sequence = [["baseline", "candidate"], ["candidate", "baseline"]] * (config["paired_blocks"] // 2)
        random.Random(config["order_seed"] + int(hashlib.sha256(name.encode()).hexdigest()[:8], 16)).shuffle(sequence)
        orders[name] = sequence
    rng, expected_schedule = random.Random(config["order_seed"]), []
    for block in range(config["paired_blocks"]):
        families = list(by_id)
        rng.shuffle(families)
        expected_schedule.append({"block": block, "families": families, "orders": {name: orders[name][block] for name in families}})
    if schedule != expected_schedule:
        raise Refusal("Recorded schedule differs from frozen randomization seed")
    under_target = []
    for row in raw:
        name, block, arm = row["family"], row["block"], row["arm"]
        sub = f"{name}/block-{block:02d}-{arm}"
        if row["command"] != sub + "/command.json" or archive.read(directory + "/" + sub + "/measurement.json") != row:
            raise Refusal("Per-sample measurement contradicts aggregate raw sample")
        command_record(row["command"], by_id[name], arm, calibration[name]["common_repetitions"])
        if not validate_driver_sample(row["driver"], config, calibration[name]["common_repetitions"]):
            under_target.append({"block": block, "family": name, "arm": arm, "elapsed_seconds": row["driver"]["elapsed_seconds"]})
    if (result.get("scored_under_target_policy") != "retain_and_flag_no_adaptive_retry"
            or result.get("scored_under_target_batches") != under_target):
        raise Refusal("Under-target samples were dropped or relabeled")


def numeric_operation(archive, directory, result, expected_blocks):
    if result.get("operation") != "bench" or not result.get("selected_for_scoring"):
        return None  # Invalid/failed attempt fields remain evidence, never estimates.
    if not measurement_eligible(result):
        raise Refusal("Selected comparison is invalid")
    pairs = archive.read(directory + "/paired.json")
    raw = archive.read(directory + "/raw.json")
    schedule = archive.read(directory + "/schedule.json")
    validate_raw(pairs, raw, schedule, expected_blocks)
    audit_sample_files(archive, directory, result, pairs, raw, schedule)
    if result.get("paired_blocks") != expected_blocks:
        raise Refusal("Recorded paired-block count differs")
    bootstrap = result["descriptive_bootstrap"]
    if bootstrap["confidence"] != .9:
        raise Refusal("Frozen one-sided confidence differs")
    replay = reduce_pairs(pairs, bootstrap["resamples"], bootstrap["seed"], bootstrap["confidence"])
    close(replay["portfolio_speedup"], result["portfolio_speedup"])
    close(replay["one_sided_lower_bound"], bootstrap["one_sided_lower_bound"])
    if set(replay["family_speedups"]) != set(result["family_speedups"]):
        raise Refusal("Family estimator inventory differs")
    for name, speed in replay["family_speedups"].items():
        close(speed, result["family_speedups"][name])
    return {"directory": directory, "measurement_id": result["measurement_id"],
            "attempt_number": result["measurement_attempt_number"], "prior_attempt_ids": result["measurement_prior_attempt_ids"],
            "raw_sample_validation_performed": True,
            "artifact_hashes": {name: archive.hash(directory + "/" + name) for name in ("raw.json", "paired.json", "schedule.json", "result.json")},
            "resamples": bootstrap["resamples"], "seed": bootstrap["seed"], "confidence": bootstrap["confidence"], **replay}
COUNTERS = ("inputTokens", "cachedInputTokens", "cacheWriteInputTokens", "outputTokens", "reasoningOutputTokens", "totalTokens")


def counters(total):
    if total is None:
        return None
    if not isinstance(total, dict):
        raise Refusal("Invalid token counters")
    for key in COUNTERS:
        value = total.get(key)
        if key == "cacheWriteInputTokens" and value is None:
            continue
        if type(value) is not int or value < 0:
            raise Refusal("Invalid observed token counter")
    return {k: total.get(k) for k in COUNTERS}


def sum_counters(rows):
    rows = list(rows)
    return {key: sum(row[key] for row in rows) if all(row is not None and row[key] is not None for row in rows) else None
            for key in COUNTERS}


def audit_usage(ledger):
    """Replay observed cumulative counters without inventing missing usage or costs."""
    threads, totals, seen, per_role = [], [], set(), {}
    for agent in ledger["agents"]:
        tid = agent.get("thread_id")
        if tid is not None:
            if not isinstance(tid, str) or not tid or tid in seen:
                raise Refusal("Duplicate/invalid usage thread identity")
            seen.add(tid)
        usage = agent.get("token_usage") or {}
        total = counters(usage.get("total"))
        previous = None
        for update in usage.get("updates", []):
            current = counters(update["total"])
            kind = update.get("classification")
            if kind == "unreconciled_context_capacity_sentinel":
                if update.get("delta") is not None:
                    raise Refusal("Unreconciled sentinel has an invented token delta")
                continue
            if kind == "context_estimate_no_usage_increment":
                if current != (previous or dict.fromkeys(COUNTERS, 0)) or update.get("delta") != dict.fromkeys(COUNTERS, 0):
                    raise Refusal("Context estimate was charged as model usage")
                continue
            if kind not in {"cumulative_usage_change", "duplicate_snapshot"}:
                raise Refusal("Unknown observed usage classification")
            prior = previous or dict.fromkeys(COUNTERS, 0)
            delta = {k: current[k] - prior[k] if current[k] is not None and prior[k] is not None else None for k in COUNTERS}
            if (update.get("delta") != delta or update.get("duplicate") is not (current == previous)
                    or kind != ("duplicate_snapshot" if current == previous else "cumulative_usage_change")):
                raise Refusal("Observed token delta/duplicate differs from cumulative snapshots")
            previous = current
        if usage.get("updates") and total != previous:
            raise Refusal("Thread total differs from last valid cumulative observation")
        if usage.get("observed_accounting_complete") and (total is None or usage.get("issues") or usage.get("turns_without_usage")):
            raise Refusal("Complete observed accounting claim contradicts missing counters")
        totals.append(total)
        per_role.setdefault(agent["role"], []).append(total)
        threads.append({"thread_id": tid, "agent_id": agent.get("agent_id"), "role": agent["role"],
                        "state": agent.get("state"), "reported_counters": total,
                        "observed_accounting_complete": usage.get("observed_accounting_complete") is True,
                        "cache_write_reporting_verified": usage.get("cache_write_reporting_verified") is True,
                        "issues": list(usage.get("issues", [])), "turns_without_usage": list(usage.get("turns_without_usage", [])),
                        "remote_compaction_observed": "compaction_observed" in agent.get("issues", []),
                        "unknown_remote_compaction_cost": None, "unknown_failed_request_cost": None,
                        "actual_billed_cost": None})
    aggregate = sum_counters(totals)
    if ledger.get("known_thread_totals") != aggregate:
        raise Refusal("Known-thread token aggregate differs")
    uncontrolled = ledger.get("failure") in {"uncontrolled_native_delegation", "unregistered_native_child", "event_from_unregistered_thread", "uncontrolled_external_tool"}
    expected_total = dict.fromkeys(COUNTERS, None) if uncontrolled else aggregate
    if ledger.get("total_tokens") != expected_total:
        raise Refusal("Ledger token total differs from admitted thread totals")
    for role, value in ledger.get("per_role_tokens", {}).items():
        if value != sum_counters(per_role.get(role, [])):
            raise Refusal("Role token aggregate differs")
    known = [row for row in totals if row is not None]
    return {"threads": threads, "observed_subtotal_tokens": sum(row["totalTokens"] for row in known) if known else None,
            "all_admitted_thread_counters": aggregate, "missing_thread_counters": sum(row is None for row in totals),
            "accounting_complete_recorded": ledger.get("accounting_complete") is True,
            "actual_billed_cost": None, "whole_model_work_verified": False,
            "scope": "One observed cumulative endpoint per thread; cached input and reasoning output are subsets, never added twice"}


def audit_checkpoints(archive, campaign, state, operations, original_root, numeric, terminal):
    rows = []
    for number, row in enumerate(state.get("trajectories", []), 1):
        op = operations.get(row["operation_id"])
        seed = (state.get("seed") or {}).get("source_hash")
        if (op is None or row["seed_hash"] != seed or op["source_hash"] != row["source_hash"]
                or (op.get("reference") or {}).get("source_hash") != seed):
            raise Refusal("Trajectory is not a direct original-seed comparison")
        if row["status"] == "pass":
            if not op["selected_for_scoring"] or row["operation_id"] not in numeric:
                raise Refusal("Trajectory selected an invalid/nonbinding attempt")
            close(numeric[row["operation_id"]]["portfolio_speedup"], row["summary"]["portfolio_speedup"])
            close(numeric[row["operation_id"]]["one_sided_lower_bound"], row["summary"]["nominal90_lower"])
        evidence = row.get("usage_evidence")
        checkpoint = {"number": number, "operation_id": row["operation_id"], "usage_evidence_path": None,
                      "tokens_coordinate": None, "cost_coordinate": None}
        if evidence is not None:
            relative = f"campaigns/{campaign}/authority/checkpoint-usage/{number:08d}.json"
            if historical_relative(evidence["path"], original_root) != relative or archive.hash(relative) != evidence["sha256"]:
                raise Refusal("Checkpoint usage path/hash is not its anchored immutable artifact")
            # The frozen host.export() writer does not emit runtime_source here.
            # Provenance is the exact owner-chain pointer plus terminal campaign identity.
            ledger = archive.read(relative)
            if (ledger.get("started_unix_seconds") != terminal.get("started_unix_seconds")
                    or ledger.get("artifact_reference_roots") != terminal.get("artifact_reference_roots")):
                raise Refusal("Checkpoint host identity differs from terminal telemetry")
            for path in ledger.get("artifact_reference_roots", []):
                if historical_relative(path, original_root) is None:
                    raise Refusal("Checkpoint artifact root escapes frozen study")
            final_agents = {a["agent_id"]: a for a in terminal["agents"]}
            if len(final_agents) != len(terminal["agents"]):
                raise Refusal("Duplicate terminal agent identity")
            for agent in ledger["agents"]:
                matched = final_agents.get(agent["agent_id"])
                if matched is None or any(agent.get(k) != matched.get(k) for k in ("role", "model", "effort")):
                    raise Refusal("Checkpoint agent differs from terminal identity")
                if agent.get("thread_id") is not None and agent["thread_id"] != matched.get("thread_id"):
                    raise Refusal("Checkpoint thread differs from terminal identity")
            usage = audit_usage(ledger)
            checkpoint.update(usage_evidence_path=relative, usage_evidence_sha256=evidence["sha256"], usage=usage)
            if row.get("usage_coordinate_complete"):
                if not usage["accounting_complete_recorded"] or usage["missing_thread_counters"]:
                    raise Refusal("Exact checkpoint usage lacks complete counters")
                checkpoint["tokens_coordinate"] = usage["all_admitted_thread_counters"]["totalTokens"]
        elif row.get("usage_coordinate_complete"):
            raise Refusal("Exact checkpoint usage asserted without immutable evidence")
        rows.append(checkpoint)
    return rows


def audit_final(archive, states):
    report = archive.read("assessment/final/report.json")
    expected_configs = {stratum: archive.hash(f"setup/final-evaluator-config-{stratum}.json") for stratum in ("transfer", "shift")}
    if report.get("configuration_hashes") != expected_configs:
        raise Refusal("Final report configuration hashes differ from frozen configs")
    seed_hash = digest(encoded(archive.tree("task/seed")))
    endpoints = {row["campaign_id"]: row for row in report["endpoints"]}
    if set(endpoints) != set(CAMPAIGNS) or len(report["endpoints"]) != len(CAMPAIGNS):
        raise Refusal("Final report endpoint inventory differs")
    for campaign in CAMPAIGNS:
        row = endpoints[campaign]
        if (row["endpoint"] != states[campaign]["endpoint"] or row["campaign_status"] != states[campaign]["status"]
                or row["state_sha256"] != archive.hash(f"campaigns/{campaign}/authority/state.json")
                or row["anchor_sha256"] != archive.hash(f"campaigns/{campaign}/authority/anchor.json")):
            raise Refusal("Final report endpoint seal differs from canonical campaign")
        source_hash = states[campaign]["endpoint"].get("source_hash")
        snapshot = f"campaigns/{campaign}/development/snapshots/{source_hash}"
        if source_hash is not None:
            if (row.get("source_files") != archive.tree(snapshot)
                    or historical_relative(row["source_directory"], archive.plan["original_study_root"]) != snapshot):
                raise Refusal("Final report endpoint source inventory differs")
        elif row.get("source_directory") is not None or row.get("source_files") is not None:
            raise Refusal("Unavailable endpoint has a fabricated source inventory")
        if (states[campaign].get("seed") or {}).get("source_hash") not in (None, seed_hash):
            raise Refusal("Campaign seed differs from frozen original source")
    operations, groups = {}, {}
    for sequence, record in enumerate(report.get("operations", []), 1):
        op_id = record["operation_id"]
        if op_id in operations or record["artifact_directory"] != op_id:
            raise Refusal("Duplicate/inconsistent final operation identity")
        directory = "assessment/final/" + op_id
        if record["files_manifest"] != op_id + "/files.json":
            raise Refusal("Final file manifest path differs")
        if archive.hash(directory + "/files.json") != record["files_manifest_sha256"]:
            raise Refusal("Final operation manifest differs from report")
        files = archive.read(directory + "/files.json")["files"]
        expected = archive.tree(directory)
        expected.pop("files.json", None)
        if files != expected:
            raise Refusal("Final operation file inventory differs")
        result = archive.read(directory + "/result.json")
        if result != {k: v for k, v in record.items() if k not in {"files_manifest", "files_manifest_sha256"}}:
            raise Refusal("Final result differs from immutable report entry")
        subject = op_id.split("/", 1)[0]
        expected_source = seed_hash if subject == "seed" else (states.get(subject, {}).get("endpoint") or {}).get("source_hash")
        if expected_source is None or result.get("source_hash") != expected_source:
            raise Refusal("Final operation source differs from its frozen seed/sealed endpoint")
        for name in ("integrity-before.json", "integrity-after.json"):
            if name in files:
                if archive.read(directory + "/" + name).get("configuration_sha256") != expected_configs.get(result["stratum"]):
                    raise Refusal("Final operation integrity receipt differs from frozen config")
            elif result["status"] == "pass" or retry_reason(result):
                raise Refusal("Valid/retryable final operation lacks configuration-integrity receipt")
        if result.get("configuration_sha256") != report["configuration_hashes"].get(result["stratum"]):
            raise Refusal("Final operation configuration differs")
        operations[op_id] = {**result, "files": files, "finish_sequence": sequence}
        if result["operation"] == "bench":
            identity = (op_id.split("/", 1)[0], result["stratum"])
            prior = groups.setdefault(identity, result["measurement_id"])
            if prior != result["measurement_id"]:
                raise Refusal("Second final measurement identity for the same sealed endpoint/stratum")
    if "seed/build" in operations:
        if operations["seed/build"].get("source_hash") != seed_hash:
            raise Refusal("Final seed build differs from frozen original source")
    elif report["status"] == "complete" or operations:
        raise Refusal("Final operation record lacks its fixed-source seed build")
    select_measurements(operations)
    numeric = {}
    for op_id, op in operations.items():
        if op["operation"] != "build":
            subject = op_id.split("/", 1)[0]
            built = operations.get(subject + "/build", {})
            if (built.get("status") != "pass" or built.get("operation") != "build"
                    or built.get("source_hash") != op["source_hash"]
                    or op.get("input_library_sha256") != built.get("library_sha256")):
                raise Refusal("Final nonbuild source/binary differs from its successful recorded build")
        if op["operation"] == "build" and op["status"] == "pass":
            if archive.hash("assessment/final/" + op_id + "/" + op["library"]) != op["library_sha256"]:
                raise Refusal("Final build library hash differs")
        if op["operation"] == "bench":
            campaign = op_id.split("/", 1)[0]
            if campaign not in CAMPAIGNS or op["source_hash"] != states[campaign]["endpoint"].get("source_hash"):
                raise Refusal("Final comparison source differs from sealed endpoint")
            built, seed = operations.get(campaign + "/build", {}), operations.get("seed/build", {})
            if (op.get("input_library_sha256") != built.get("library_sha256")
                    or (op.get("reference") or {}).get("library_sha256") != seed.get("library_sha256")
                    or (op.get("reference") or {}).get("source_hash") != seed.get("source_hash")):
                raise Refusal("Final benchmark binary/reference differs from fixed builds")
        value = numeric_operation(archive, "assessment/final/" + op_id, op, 30)
        if value:
            numeric[op_id] = value
    def validation_gate(subject):
        expected = {"build": "build", "memory": "memcheck", "test-transfer": "test", "test-shift": "test"}
        for suffix, kind in expected.items():
            op = operations.get(subject + "/" + suffix, {})
            if op.get("operation") != kind or op.get("status") != "pass":
                return False
            if suffix.startswith("test-") and op.get("stratum") != suffix[len("test-"):]:
                return False
            if op.get("confirmed_semantic_failure") or op.get("confirmed_memory_error") or op.get("integrity_error"):
                return False
        return True

    seed_valid = validation_gate("seed")
    if (report.get("rows") or any(not key.startswith("seed/") for key in operations)) and not seed_valid:
        raise Refusal("Final endpoint stage was reached without successful seed validation")
    seen, public_rows = set(), []
    for row in report.get("rows", []):
        campaign, stratum = row["campaign_id"], row["stratum"]
        if campaign not in CAMPAIGNS or stratum not in {"transfer", "shift"} or (campaign, stratum) in seen:
            raise Refusal("Invalid final campaign/stratum row")
        seen.add((campaign, stratum))
        if row.get("campaign_status") != states[campaign]["status"]:
            raise Refusal("Final row campaign completion status differs")
        if row.get("seed_hash") is not None and row["seed_hash"] != seed_hash:
            raise Refusal("Final row reference is not the frozen original seed")
        valid = validation_gate(campaign)
        source = states[campaign]["endpoint"].get("source_hash")
        if row["status"] in {"measured", "measurement_failed", "identical_source"} and not valid:
            raise Refusal("Final scientific row contradicts endpoint build/correctness/memory validation")
        if row["status"] == "endpoint_unavailable":
            if source is not None or campaign + "/build" in operations:
                raise Refusal("Unavailable endpoint row contradicts retained source/build")
        elif row["status"] == "endpoint_validation_failed":
            built = operations.get(campaign + "/build", {})
            if source is None or valid or not built:
                raise Refusal("Endpoint validation-failed row contradicts recorded gate")
            if built.get("status") == "pass" and any(campaign + "/" + key not in operations for key in ("memory", "test-transfer", "test-shift")):
                raise Refusal("Endpoint validation-failed row omits an expected diagnostic stage")
        elif row["status"] not in {"measured", "measurement_failed", "identical_source"}:
            raise Refusal("Unknown final outcome status")
        if row.get("source_hash") is not None and row["source_hash"] != states[campaign]["endpoint"].get("source_hash"):
            raise Refusal("Final row differs from sealed endpoint")
        if row["status"] == "measured":
            op_id = row["evidence"]
            op = operations.get(op_id, {})
            if op_id not in numeric or op.get("stratum") != stratum or not op_id.startswith(campaign + "/"):
                raise Refusal("Final row selected invalid or wrong-stratum attempt")
            for key in ("measurement_id", "measurement_attempt_number", "measurement_prior_attempt_ids"):
                if row.get(key) != op.get(key):
                    raise Refusal("Final row retry lineage differs")
            close(numeric[op_id]["portfolio_speedup"], row["speedup"])
            if row.get("family_speedups") != op.get("family_speedups") or row.get("descriptive_bootstrap") != op.get("descriptive_bootstrap"):
                raise Refusal("Final row family/bootstrap summaries differ from selected result")
        elif row["status"] == "measurement_failed":
            op_id = row.get("evidence")
            op = operations.get(op_id, {})
            if (not op or op.get("selected_for_scoring") or op.get("stratum") != stratum
                    or not op_id.startswith(campaign + "/") or row.get("speedup") is not None):
                raise Refusal("Failed final row lacks its actual failed immutable attempt")
            for key in ("measurement_id", "measurement_attempt_number", "measurement_prior_attempt_ids"):
                if row.get(key) != op.get(key):
                    raise Refusal("Failed final row retry lineage differs")
        elif row["status"] == "identical_source":
            if row.get("source_hash") != row.get("seed_hash") or row.get("speedup") is not None or row.get("measured_performance") is not False:
                raise Refusal("Source identity was presented as a measured speedup")
        elif row.get("speedup") is not None:
            raise Refusal("Invalid/failed final attempt has a scientific estimate")
        public = dict(row)
        if row["status"] != "measured":
            public.update(speedup=None, family_speedups=None, descriptive_bootstrap=None)
        public_rows.append(public)
    if report["status"] == "complete" and len(seen) != 6:
        raise Refusal("Complete final report lacks all six endpoint/stratum outcomes")
    return {"status": report["status"], "seed_build_recorded": "seed/build" in operations, "rows": public_rows,
            "attempts": [attempt_record(op_id, op) for op_id, op in operations.items()]}, list(numeric.values())


def attempt_record(op_id, op):
    return {"operation_id": op_id, **{k: op.get(k) for k in ("operation", "status", "measurement_id",
            "measurement_attempt_number", "measurement_prior_attempt_ids", "measurement_retry_reason",
            "measurement_invalidated", "selected_for_scoring", "selection_basis")},
            "portfolio_speedup": op.get("portfolio_speedup") if op.get("selected_for_scoring") else None}


def replay(bundle, manifest_sha256, expected_freeze=FROZEN_SHA256):
    verification = verify_bundle(bundle, manifest_sha256, expected_freeze=expected_freeze)
    bundle = Path(bundle)
    plan = read(bundle, "manifest.json")
    archive = Archive(bundle / "study", plan)
    _, release = release_gate(archive.root, expected_freeze)
    workflows, comparisons, usages, states = [], [], [], {}
    for campaign in CAMPAIGNS:
        workflow, state, operations = audit_workflow(archive, campaign, plan["original_study_root"])
        states[campaign] = state
        numeric = {}
        for op_id, op in operations.items():
            result = numeric_operation(archive, f"campaigns/{campaign}/development/operations/{op_id}", op, 10)
            if result:
                numeric[op_id] = result
                comparisons.append(result)
        for review in state.get("reviews", {}).values():
            if review.get("summary"):
                selected = numeric[review["receipt"]["official_comparison_operation_id"]]
                close(selected["portfolio_speedup"], review["summary"]["portfolio_speedup"])
                close(selected["one_sided_lower_bound"], review["summary"]["nominal90_lower"])
        workflow["attempts"] = [attempt_record(op_id, op) for op_id, op in operations.items()]
        path = f"campaigns/{campaign}/telemetry.json"
        ledger = archive.read(path)
        workflow["checkpoints"] = audit_checkpoints(archive, campaign, state, operations, plan["original_study_root"], numeric, ledger)
        workflows.append(workflow)
        if ledger.get("runtime_source") != "official_direct_terminal_appserver":
            raise Refusal("Terminal measured telemetry source is not official runtime")
        usages.append({"campaign_id": campaign, "telemetry_sha256": archive.hash(path), **audit_usage(ledger)})
    final, final_numeric = audit_final(archive, states)
    comparisons.extend(final_numeric)
    if release_gate(archive.root, expected_freeze)[1] != release:
        raise Refusal("Terminal metadata changed during replay")
    return {"schema_version": 3, "status": "archived_numeric_replay_passed" if final["status"] == "complete" else "partial_terminal_record_numeric_audit_passed", "freeze_sha256": expected_freeze,
            "archive_manifest_sha256": manifest_sha256, "archive_verification": verification,
            "workflows": workflows, "comparisons": comparisons, "final": final, "usage": usages,
            "new_native_execution": False, "endpoint_reselection": False, "raw_sample_validation_performed": True,
            "limits": ["First-valid selection uses immutable completion order, not scores or a trusted-clock attestation",
                       "Invalid and failed attempt bytes remain archived; their retained timing fields are excluded from estimates",
                       "Descriptive bootstrap under adaptive selection, not campaign-wide confirmatory inference",
                       "Omitted binaries are checked against anchored digests only; absent bytes are not reverified",
                       "Token replay covers observed cumulative arithmetic; pricing reanalysis is a separate, labeled source-pinned calculation",
                       "Unknown cache writes, remote-compaction costs, failed-request costs and actual bill remain unknown"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--native-measurements-finished", action="store_true", required=True)
    args = parser.parse_args()
    try:
        outside_study(args.out, args.bundle)
        result = replay(args.bundle, args.manifest_sha256)
        write_new(args.out, result)
        print(json.dumps({"status": result["status"], "comparisons": len(result["comparisons"]), "report_sha256": sha(args.out)}))
    except (Refusal, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "refused", "reason": str(exc)}), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
