#!/usr/bin/env python3
"""Read terminal, public study evidence into explicit, provenance-bound figure tables.

This module never executes study code, benchmarks, participants, or evaluators.
It never opens source snapshots, runtime message streams, or final fixture inputs.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import statistics
import sys
import types
from decimal import Decimal

HERE = Path(__file__).resolve().parent
FROZEN_SHA256 = "a28a9e9984aa03a1a28c950bfd846e0d179202f719a43982a27c72a69c934178"
TRUSTED_REPRICE_PATH = HERE.parent / "reprice_observed_usage.py"
TRUSTED_REPRICE_SHA256 = "0feb711675481377a2e994fe84b2c955bc44b93aa37979aa1199722ec1301da9"
PRIVATE_PATH_PARTS = {".git", ".aws", ".ssh", ".codex", ".study-codex-runtime", "auth", "credentials",
                      "sessions", "rollouts", "node_modules", "raw-remotes", "raw_remotes", "provider-logs",
                      "provider_logs", "remote-responses", "remote_responses"}
PRIVATE_PATH_NAMES = {"auth.json", "credentials.json", ".env", ".netrc", ".npmrc", "id_rsa", "id_ed25519"}
CAMPAIGNS = tuple(f"campaign-{i}" for i in range(1, 4))
STRATA = ("transfer", "shift")
COUNTERS = ("inputTokens", "cachedInputTokens", "cacheWriteInputTokens",
            "outputTokens", "reasoningOutputTokens", "totalTokens")
EVENT_TYPES = {
    "hypothesis_registered": "Hypothesis", "hypothesis_report": "Hypothesis",
    "nomination": "Nomination", "nomination_withdrawn": "Nomination",
    "nomination_review": "Independent review",
    "nomination_failed_execution_review": "Independent review",
    "nomination_disqualified": "Independent review", "claim_review": "Independent review",
    "queue_updated": "Investigation / repair", "closure_proposed": "Closure",
    "closure_review": "Closure", "stopped": "Interruption",
    "seed_relative_trajectory": "Direct seed comparison",
}


class EvidenceError(ValueError):
    pass


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise EvidenceError("Duplicate JSON object key")
            result[key] = value
        return result
    def constant(value):
        raise EvidenceError(f"Nonfinite JSON number: {value}")
    def number(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise EvidenceError("JSON number exceeds finite range")
        return parsed
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant, parse_float=number)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def historical_relative(value, original_root):
    """Translate a canonical historical name lexically; never open that path."""
    def absolute(text):
        if (not isinstance(text, str) or "\\" in text or "\x00" in text or "//" in text
                or any(part in PRIVATE_PATH_PARTS or part in PRIVATE_PATH_NAMES for part in text.split("/"))):
            raise EvidenceError("Historical artifact path is not canonical absolute")
        path = PurePosixPath(text)
        if not path.is_absolute() or any(part in (".", "..") for part in path.parts) or path.as_posix() != text:
            raise EvidenceError("Historical artifact path is not canonical absolute")
        return path
    path, origin = absolute(value), absolute(original_root)
    if not path.is_relative_to(origin) or path == origin:
        raise EvidenceError("Historical artifact lies outside the authenticated freeze root")
    return path.relative_to(origin).as_posix()


def no_symlink_path(value):
    """Reject every symlink component before resolving a file or selected root."""
    path = Path(value).absolute()
    cursor = Path(path.anchor)
    for part in path.parts[1:]:
        cursor = cursor / part
        if cursor.is_symlink():
            raise EvidenceError(f"Symlink component is not permitted: {cursor}")
    return path.resolve(strict=True)


def finite(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise EvidenceError(f"Invalid {label}")
    return value


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
            raise EvidenceError("V3 comparison has no immutable measurement identity")
        groups.setdefault(mid, []).append((op_id, op))
    for attempts in groups.values():
        attempts.sort(key=lambda pair: pair[1].get("finish_sequence", pair[1].get("measurement_attempt_number", 0)))
        prior, binding, previous_reason = [], None, None
        for number, (op_id, op) in enumerate(attempts, 1):
            if (op.get("measurement_attempt_number") != number
                    or op.get("measurement_prior_attempt_ids") != prior
                    or op.get("measurement_retry_reason") != previous_reason
                    or op.get("measurement_selection_rule") != "first_complete_valid_attempt"
                    or op.get("measurement_retry_policy") != "infrastructure_only_first_valid_v1"):
                raise EvidenceError("Comparison attempt chain or selection policy differs")
            current = {key: op.get(key) for key in ("source_hash", "build_id", "input_library_sha256",
                "configuration_sha256", "reference", "reference_id", "purpose", "review_plan_id", "stratum")}
            if binding is not None and current != binding:
                raise EvidenceError("Retried comparison changed its source, binary, reference or configuration")
            binding = current
            if prior and previous_reason is None:
                raise EvidenceError("Comparison retried after a binding valid or nonretryable result")
            op["selected_for_scoring"] = measurement_eligible(op)
            op["selection_basis"] = "first_valid_measurement_attempt" if op["selected_for_scoring"] else "invalid_or_failed_attempt"
            previous_reason = retry_reason(op)
            prior.append(op_id)
            if op["selected_for_scoring"] and op.get("purpose") == "official_review":
                key = (op.get("review_plan_id"), op.get("source_hash"), (op.get("reference") or {}).get("source_hash"))
                if not key[0]:
                    raise EvidenceError("Official comparison lacks review plan")
                official.setdefault(key, []).append((op_id, op))
    for attempts in official.values():
        attempts.sort(key=lambda pair: pair[1]["finish_sequence"])
        for _, op in attempts[1:]:
            op["selected_for_scoring"] = False
            op["selection_basis"] = "later_valid_official_rerun_process_only"
    return operations


def operation_row(campaign, op_id, op, started):
    eligible = op.get("operation") == "bench" and measurement_eligible(op) and op.get("selected_for_scoring", True)
    return {"campaign": campaign, "operation_id": op_id,
            **{k: op.get(k) for k in ("operation", "status", "role", "actor_id", "source_hash", "purpose", "reference_id", "started_unix", "finished_unix", "outer_elapsed_seconds", "queue_seconds")},
            "reference_hash": (op.get("reference") or {}).get("source_hash"),
            "measurement_eligible": eligible,
            **{key: op.get(key) for key in ("measurement_id", "measurement_attempt_number", "measurement_prior_attempt_ids",
                "measurement_retry_reason", "measurement_selection_rule", "measurement_retry_authorized", "selected_for_scoring", "selection_basis")},
            "measurement_invalidated": op.get("measurement_invalidated"),
            "ordinary_command_overlap_status": (op.get("ordinary_command_overlap_audit") or {}).get("status"),
            "portfolio_speedup": op.get("portfolio_speedup") if eligible else None,
            "one_sided90_lower": (op.get("descriptive_bootstrap") or {}).get("one_sided_lower_bound") if eligible else None,
            "elapsed_seconds": ((op["finished_unix"] or op["started_unix"]) - started)}


def output_directory(path):
    path = Path(path).resolve()
    if not path.is_relative_to(HERE) or path == HERE:
        raise EvidenceError("Outputs must be in a dedicated directory under analysis/figures")
    if path.exists() and any(path.iterdir()):
        raise EvidenceError("Output directory is not empty; use a new directory to preserve prior evidence")
    path.mkdir(parents=True, exist_ok=True)
    return path


class Reader:
    def __init__(self, root, *, expected_freeze=FROZEN_SHA256):
        self.root = no_symlink_path(root)
        self.sources = {}
        self.final_released = False
        self.expected_freeze = expected_freeze
        self.original_root = None
        self.freeze = None

    def authenticate_origin(self):
        if self.original_root is None:
            freeze = self.read("state/freeze.json")
            if (self.sources["state/freeze.json"]["sha256"] != self.expected_freeze
                    or freeze.get("status") != "frozen" or freeze.get("campaign_count") != 3):
                raise EvidenceError("Historical origin does not belong to the exact frozen v3 experiment")
            origin = (freeze.get("manifest") or {}).get("root")
            # Validate canonical form without resolving the old host's path.
            historical_relative(str(origin) + "/state/freeze.json", origin)
            self.original_root = origin
            self.freeze = freeze
        return self.original_root

    def historical_relative(self, value):
        return historical_relative(value, self.authenticate_origin())

    def local_path(self, path):
        path = Path(path)
        if not path.is_absolute():
            path = self.root / path
        if not path.is_relative_to(self.root) or any(part == ".." for part in path.parts):
            raise EvidenceError(f"Evidence path escapes study: {path}")
        if any(part.lower() in PRIVATE_PATH_PARTS or part.lower() in PRIVATE_PATH_NAMES
               for part in path.relative_to(self.root).parts):
            raise EvidenceError("Private paths are outside figure evidence access")
        resolved = no_symlink_path(path)
        if not resolved.is_relative_to(self.root):
            raise EvidenceError(f"Evidence path escapes study: {path}")
        return resolved

    def read(self, path):
        resolved = self.local_path(path)
        relative = resolved.relative_to(self.root).as_posix()
        # A second boundary prevents accidental expansion into fixtures or messages.
        allowed = ((relative.startswith("campaigns/") and
                    ("/authority/" in relative or "/development/events/" in relative or
                     "/development/operations/" in relative or relative.endswith("/telemetry.json")))
                   or relative in {"state/launch/status.json", "state/freeze.json"}
                   or (self.final_released and relative.startswith("assessment/final/")))
        if not allowed or "/snapshots/" in relative or not relative.endswith(".json"):
            raise EvidenceError(f"Not an allowed figure evidence JSON: {relative}")
        if "/development/operations/" in relative or relative.startswith("assessment/final/"):
            if resolved.name not in {"result.json", "paired.json", "raw.json", "schedule.json",
                                     "descriptive-bootstrap.json", "files.json", "report.json"}:
                raise EvidenceError(f"Not an allowed result file: {relative}")
        raw = resolved.read_bytes()
        self.sources[relative] = {"sha256": digest(raw), "bytes": len(raw)}
        return strict_json(raw)

    def release_final(self, states):
        """Check public completion metadata before opening any held-out artifact."""
        if set(states) != set(CAMPAIGNS) or not all(identity_check(s, c) for c, s in states.items()):
            raise EvidenceError("All three original measured endpoints must be sealed")
        path = self.root / "state/launch/status.json"
        status = self.read(path) if path.exists() else {}
        self.final_released = status.get("status") == "complete" and status.get("assessment_status") == "complete"
        return self.final_released

    def chain(self, directory, *, expected_head=None, expected_count=None):
        previous, rows = None, []
        for i, path in enumerate(sorted(directory.glob("*.json")), 1):
            if path.name != f"{i:08d}.json":
                raise EvidenceError("Non-contiguous event sequence")
            event = self.read(path)
            if event.get("sequence") != i or event.get("previous") != previous:
                raise EvidenceError("Event hash-chain mismatch")
            previous = self.sources[path.relative_to(self.root).as_posix()]["sha256"]
            rows.append(event)
        if expected_head != previous or (expected_count is not None and len(rows) != expected_count):
            raise EvidenceError("Event anchor mismatch")
        return rows


def identity_check(state, campaign):
    if state.get("stage") != "measured" or state.get("campaign_id") != campaign or state.get("synthetic") is True:
        raise EvidenceError("Setup or mismatched identity cannot enter measured figures")
    return state.get("status") in ("complete", "incomplete") and "sealed_unix" in (state.get("endpoint") or {})


def audit_authority(reader, campaign, state):
    directory = reader.root / "campaigns" / campaign / "authority"
    anchor = reader.read(directory / "anchor.json")
    events = reader.chain(directory / "events", expected_head=anchor["head"], expected_count=anchor["count"])
    if digest(canonical(state)) != anchor["state_hash"] or not events or events[-1]["state_hash"] != anchor["state_hash"]:
        raise EvidenceError("Owner projection hash mismatch")
    endpoint, incumbent = state["endpoint"], state.get("incumbent") or {}
    if endpoint.get("source_hash") != incumbent.get("source_hash"):
        raise EvidenceError("Endpoint is not the retained incumbent")
    return events


def audit_development(reader, campaign):
    base = reader.root / "campaigns" / campaign
    heads = reader.read(base / "authority/development-heads.json")
    # Use the sole original root authenticated by the exact freeze, not suffix search.
    key = reader.authenticate_origin() + f"/campaigns/{campaign}/development"
    if key not in heads:
        raise EvidenceError("Development anchor does not match the authenticated historical path")
    events = reader.chain(base / "development/events", expected_head=heads[key])
    starts, finishes = {}, {}
    for event in events:
        value = event["payload"]
        if event["kind"] == "operation_started":
            starts[value["operation_id"]] = event
        elif event["kind"] == "operation_finished":
            finishes[value["operation_id"]] = event
    operations = {}
    for op_id, started in starts.items():
        ended = finishes.get(op_id)
        if ended is None:
            operations[op_id] = {**started["payload"], "status": "unsealed_operation",
                                 "started_unix": started["wall_time"], "finished_unix": None}
            continue
        value = ended["payload"]
        path = base / "development/operations" / op_id / "result.json"
        result = reader.read(path)
        if result.get("operation_id") != op_id:
            raise EvidenceError("Operation identity differs from anchored directory")
        if reader.sources[path.relative_to(reader.root).as_posix()]["sha256"] != value["files"].get("result.json"):
            raise EvidenceError("Result differs from anchored operation evidence")
        operations[op_id] = {**result, "files": value["files"], "finish_sequence": ended["sequence"], "started_unix": started["wall_time"],
                             "finished_unix": ended["wall_time"]}
    if set(finishes) - set(starts):
        raise EvidenceError("Finished operation lacks start")
    return select_measurements(operations)


def observed_comparison(reader, directory, result, campaign, comparison_id, stratum, expected_blocks,
                        *, source_hash, reference_hash, context):
    """Validate raw pair coverage and recorded summaries without recomputing a bootstrap."""
    if not measurement_eligible(result):
        return [], [], None
    if result.get("source_hash") is not None and result["source_hash"] != source_hash:
        raise EvidenceError("Comparison result source mismatch")
    if result.get("reference") is not None and result["reference"].get("source_hash") != reference_hash:
        raise EvidenceError("Comparison result reference mismatch")
    pairs = reader.read(directory / "paired.json")
    if len(pairs) != 6 or any(len(rows) != expected_blocks for rows in pairs.values()):
        raise EvidenceError("Comparison does not contain six complete family blocks")
    raw, schedule = reader.read(directory / "raw.json"), reader.read(directory / "schedule.json")
    if len(raw) != expected_blocks * 12 or len(schedule) != expected_blocks:
        raise EvidenceError("Raw or schedule coverage mismatch")
    lookup = {(r["family"], r["block"], r["arm"]): r for r in raw}
    if len(lookup) != len(raw):
        raise EvidenceError("Duplicate raw sample")
    if [row["block"] for row in schedule] != list(range(expected_blocks)):
        raise EvidenceError("Temporal block schedule mismatch")
    samples, families, medians = [], [], {}
    for name, rows in sorted(pairs.items()):
        logs, base_times, cand_times = [], [], []
        orders = []
        for block, pair in enumerate(rows):
            planned = schedule[block]
            if set(planned["families"]) != set(pairs):
                raise EvidenceError("Schedule families differ from pairs")
            order = planned["orders"][name]
            if sorted(order) != ["baseline", "candidate"]:
                raise EvidenceError("Invalid pair arm order")
            orders.append(order[0])
            a, b = finite(pair["baseline"], "baseline time"), finite(pair["candidate"], "candidate time")
            if min(a, b) <= 0:
                raise EvidenceError("Nonpositive paired time")
            for arm, value in (("baseline", a), ("candidate", b)):
                raw_row = lookup.get((name, block, arm))
                if raw_row is None or not math.isclose(raw_row["driver"]["seconds_per_call"], value, rel_tol=1e-12):
                    raise EvidenceError("Paired and raw timing disagree")
            logs.append(math.log(a / b)); base_times.append(a); cand_times.append(b)
            samples.append({"campaign": campaign, "comparison_id": comparison_id, "stratum": stratum,
                            "context": context, "family": name, "block": block, "first_arm": order[0],
                            "baseline_seconds": a, "candidate_seconds": b, "paired_ratio": a / b,
                            "baseline_target_met": lookup[name, block, "baseline"]["driver"].get("sample_target_met"),
                            "candidate_target_met": lookup[name, block, "candidate"]["driver"].get("sample_target_met"),
                            "source_hash": source_hash, "reference_hash": reference_hash})
        if orders.count("baseline") != expected_blocks // 2:
            raise EvidenceError("Unbalanced arm schedule")
        medians[name] = math.exp(statistics.median(logs))
        reported = result.get("family_speedups", {}).get(name)
        if reported is None or not math.isclose(medians[name], reported, rel_tol=1e-10):
            raise EvidenceError("Recorded family estimator differs from raw pairs")
        families.append({"campaign": campaign, "comparison_id": comparison_id, "stratum": stratum,
                         "context": context, "family": name, "ratio": medians[name], "blocks": expected_blocks,
                         "baseline_median_seconds": statistics.median(base_times),
                         "candidate_median_seconds": statistics.median(cand_times),
                         "source_hash": source_hash, "reference_hash": reference_hash})
    estimate = math.exp(statistics.mean(math.log(v) for v in medians.values()))
    if not math.isclose(estimate, result["portfolio_speedup"], rel_tol=1e-10):
        raise EvidenceError("Recorded portfolio estimator differs from raw pairs")
    bootstrap = result.get("descriptive_bootstrap") or {}
    lower = bootstrap.get("one_sided_lower_bound")
    if bootstrap.get("confidence") != 0.9 or lower is None:
        raise EvidenceError("Frozen nominal 90% one-sided lower bound missing")
    if finite(lower, "bootstrap lower bound") <= 0:
        raise EvidenceError("Nonpositive bootstrap lower bound")
    for name in ("paired.json", "raw.json", "schedule.json"):
        expected = result.get("files", {}).get(name)
        if "files" in result and not expected:
            raise EvidenceError("Scored timing file lacks an anchored digest")
        if expected and reader.sources[(directory / name).relative_to(reader.root).as_posix()]["sha256"] != expected:
            raise EvidenceError("Comparison file differs from anchored digest")
    portfolio = {"campaign": campaign, "comparison_id": comparison_id, "stratum": stratum,
                 "context": context, "ratio": estimate, "one_sided90_lower": lower,
                 "blocks": expected_blocks, "source_hash": source_hash, "reference_hash": reference_hash,
                 "bootstrap_seed": bootstrap["seed"], "bootstrap_resamples": bootstrap["resamples"]}
    return samples, families, portfolio


def counter_partition(total):
    if not isinstance(total, dict):
        return None
    for key in COUNTERS:
        v = total.get(key)
        if key == "cacheWriteInputTokens" and v is None:
            continue
        if type(v) is not int or v < 0:
            raise EvidenceError("Invalid observed usage counter")
    if (total["inputTokens"] + total["outputTokens"] != total["totalTokens"] or
        total["cachedInputTokens"] > total["inputTokens"] or
        total["reasoningOutputTokens"] > total["outputTokens"] or
        (total.get("cacheWriteInputTokens") is not None and
         total["cacheWriteInputTokens"] + total["cachedInputTokens"] > total["inputTokens"])):
        raise EvidenceError("Invalid observed usage partition")
    return total


def audit_checkpoint_identity(ledger, terminal, campaign, *, original_root):
    """Bind a raw Host.export() snapshot to its canonical terminal host export.

    Neither export has a campaign_id field, and only the runner's terminal
    wrapper adds runtime_source. Campaign attribution instead comes from the
    canonical evidence paths and the host's campaign-specific artifact roots.
    A checkpoint may precede later admissions or a pending thread-start reply.
    """
    if terminal.get("runtime_source") != "official_direct_terminal_appserver":
        raise EvidenceError("Terminal checkpoint identity reference is not the measured native runtime")
    if ledger.get("schema_version") != 2 or terminal.get("schema_version") != 2:
        raise EvidenceError("Checkpoint or terminal export differs from frozen Host.export schema")
    started = finite(ledger.get("started_unix_seconds"), "checkpoint host start")
    if started != finite(terminal.get("started_unix_seconds"), "terminal host start"):
        raise EvidenceError("Checkpoint and terminal telemetry identify different host instances")
    expected = {f"campaigns/{campaign}/{name}" for name in ("development", "authority", "workspace-operations")}
    def roots(value):
        result = []
        for path in value.get("artifact_reference_roots", []):
            relative = historical_relative(path, original_root)
            if relative not in expected:
                raise EvidenceError("Checkpoint or terminal artifact root belongs to another campaign")
            result.append(relative)
        if len(result) != len(expected) or set(result) != expected:
            raise EvidenceError("Campaign artifact-root identities are missing or duplicated")
        return set(result)
    if roots(ledger) != roots(terminal):
        raise EvidenceError("Checkpoint and terminal campaign artifact roots differ")
    def agents(value):
        found, threads = {}, set()
        for agent in value.get("agents", []):
            identity, thread = agent.get("agent_id"), agent.get("thread_id")
            if not isinstance(identity, str) or not identity or identity in found:
                raise EvidenceError("Missing or duplicate host agent identity")
            if thread is not None:
                if not isinstance(thread, str) or not thread or thread in threads:
                    raise EvidenceError("Missing or duplicate host thread identity")
                threads.add(thread)
            found[identity] = agent
        return found
    checkpoint_agents, terminal_agents = agents(ledger), agents(terminal)
    for identity, agent in checkpoint_agents.items():
        final = terminal_agents.get(identity)
        if final is None or any(agent.get(key) != final.get(key)
                                for key in ("role", "model", "effort", "parent_agent_id")):
            raise EvidenceError("Checkpoint agent attribution differs from terminal campaign identity")
        if agent.get("thread_id") is not None and agent["thread_id"] != final.get("thread_id"):
            raise EvidenceError("Checkpoint thread differs from terminal campaign identity")
    return {"checkpoint_identity_status": "anchored_artifact_and_terminal_host_agents_verified",
            "checkpoint_agent_count": len(checkpoint_agents),
            "checkpoint_thread_identity_pending": sum(a.get("thread_id") is None for a in checkpoint_agents.values())}


def checkpoint_usage(reader, campaign, checkpoint, row, pricer, terminal_ledger=None):
    """Audit full v3 snapshots without treating observed subtotals as exact coordinates."""
    evidence = row.get("usage_evidence")
    if evidence is None:
        if row.get("usage_coordinate_complete"):
            raise EvidenceError("Exact checkpoint usage asserted without evidence")
        return {"usage_evidence_path": None, "usage_evidence_sha256": None,
                "checkpoint_observed_tokens": None, "checkpoint_observed_lower_usd": None,
                "checkpoint_observed_upper_usd": None}
    # Translate only a canonical path under the exact freeze's original root.
    relative = Path("campaigns") / campaign / "authority/checkpoint-usage" / f"{checkpoint:08d}.json"
    if reader.historical_relative(evidence["path"]) != relative.as_posix():
        raise EvidenceError("Checkpoint usage pointer does not identify its canonical artifact")
    ledger = reader.read(relative)
    observed_hash = reader.sources[relative.as_posix()]["sha256"]
    if observed_hash != evidence.get("sha256"):
        raise EvidenceError("Checkpoint usage artifact differs from anchored digest")
    terminal_path = Path("campaigns") / campaign / "telemetry.json"
    if terminal_ledger is None and (reader.root / terminal_path).exists():
        terminal_ledger = reader.read(terminal_path)
    if terminal_ledger is None:
        if row.get("usage_coordinate_complete"):
            raise EvidenceError("Exact checkpoint usage lacks terminal identity evidence")
        return {"usage_evidence_path": relative.as_posix(), "usage_evidence_sha256": observed_hash,
                "checkpoint_identity_status": "unverified_terminal_telemetry_unavailable",
                "checkpoint_observed_tokens": None, "checkpoint_observed_lower_usd": None,
                "checkpoint_observed_upper_usd": None}
    identity = audit_checkpoint_identity(ledger, terminal_ledger, campaign, original_root=reader.authenticate_origin())
    terminal_source = reader.sources.get(terminal_path.as_posix())
    if terminal_source is None:
        raise EvidenceError("Terminal identity ledger was not read through the evidence reader")
    threads, _, _, price = usage_tables(ledger, campaign, 0, pricer)
    known = [t for t in threads if t["usage_present"]]
    subtotal = sum(t["totalTokens"] for t in known) if known else None
    bounds = price.get("observed_subtotal_bounds") or {}
    value = {"usage_evidence_path": relative.as_posix(), "usage_evidence_sha256": observed_hash, **identity,
             "checkpoint_terminal_evidence_path": terminal_path.as_posix(),
             "checkpoint_terminal_evidence_sha256": terminal_source["sha256"],
             "checkpoint_observed_tokens": subtotal,
             "checkpoint_observed_lower_usd": bounds.get("lower_usd"),
             "checkpoint_observed_upper_usd": bounds.get("upper_usd"),
             "checkpoint_observed_accounting_complete": price["observed_accounting_complete"],
             "checkpoint_missing_usage_threads": len(price["missing_usage"])}
    if row.get("usage_coordinate_complete"):
        if ledger.get("accounting_complete") is not True or not price["observed_accounting_complete"]:
            raise EvidenceError("Checkpoint complete-usage assertion lacks complete ledger")
        total = counter_partition(ledger.get("total_tokens"))
        if total is None:
            raise EvidenceError("Checkpoint exact token coordinate is unavailable")
        value.update(tokens_coordinate=total["totalTokens"], cost_coordinate_lower=bounds.get("lower_usd"),
                     cost_coordinate_upper=bounds.get("upper_usd"))
    return value


def load_pricer(root):
    """Execute only the exact pricing bytes authenticated by the frozen manifest."""
    reader = root if isinstance(root, Reader) else Reader(root)
    reader.authenticate_origin()
    relative = "runtime/pricing.py"
    expected = (reader.freeze.get("manifest") or {}).get("files", {}).get(relative)
    if not isinstance(expected, str) or len(expected) != 64:
        raise EvidenceError("Frozen manifest does not pin the pricing implementation")
    path = reader.local_path(relative)
    raw = path.read_bytes()
    if digest(raw) != expected:
        raise EvidenceError("Pricing implementation differs from its authenticated frozen hash")
    module = types.ModuleType("frozen_study_pricing")
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module, {"path": relative, "sha256": digest(raw), "freeze_sha256": reader.expected_freeze}


def refined_pricing(root, telemetry_path, *, observed_complete=None):
    """Use the pinned extractor-local helper, never code from an evidence root."""
    reader = root if isinstance(root, Reader) else Reader(root)
    reader.authenticate_origin()
    if observed_complete is False:
        return None, "Incomplete observed ledger; frozen broad scenarios used"
    try:
        path = no_symlink_path(TRUSTED_REPRICE_PATH)
    except FileNotFoundError:
        return None, "Supported response-band reanalysis unavailable; frozen broad scenarios used"
    raw = path.read_bytes()
    if digest(raw) != TRUSTED_REPRICE_SHA256:
        raise EvidenceError("Extractor-local response-band implementation differs from its trusted source hash")
    telemetry_path = reader.local_path(telemetry_path)
    # Keep the existing JSON allowlist and bind the helper's second read to it.
    reader.read(telemetry_path)
    telemetry_key = telemetry_path.relative_to(reader.root).as_posix()
    module = types.ModuleType("post_analysis_pricing")
    exec(compile(raw, str(path), "exec"), module.__dict__)
    try:
        report = module.analyze(telemetry_path)
    except (ValueError, KeyError, TypeError) as exc:
        return None, f"Response-band reanalysis refused ({exc}); frozen broad scenarios used"
    if report.get("source_telemetry_sha256") != reader.sources[telemetry_key]["sha256"]:
        raise EvidenceError("Telemetry changed during response-band reanalysis")
    report["analysis_code_sha256"] = digest(raw)
    report["analysis_code_origin"] = "pinned trusted source beside the extractor"
    return report, None


def usage_tables(ledger, campaign, started, pricer):
    seen, threads, observations, curves = set(), [], [], []
    for agent in ledger.get("agents", []):
        tid = agent.get("thread_id")
        if tid is not None and tid in seen:
            raise EvidenceError("Duplicate usage thread")
        if tid:
            seen.add(tid)
        usage = agent.get("token_usage") or {}
        total = counter_partition(usage.get("total"))
        threads.append({"campaign": campaign, "role": agent["role"], "model": agent["model"],
                        "thread_id": tid, "agent_id": agent.get("agent_id"),
                        "status": agent.get("state"), "observed_complete": usage.get("observed_accounting_complete") is True,
                        "usage_present": total is not None, "cache_write_verified": usage.get("cache_write_reporting_verified") is True,
                        "remote_compaction_observed": "compaction_observed" in agent.get("issues", []),
                        "noncompleted_turn_count": sum(status != "completed" for status in agent.get("terminal_turn_statuses", {}).values()),
                        "turns_without_usage_count": len(usage.get("turns_without_usage", [])),
                        "interrupted_usage_tail_unknown": any(status != "completed" for status in agent.get("terminal_turn_statuses", {}).values()) or agent.get("state") in ("interrupted", "failed", "startup_failed"),
                        "whole_model_work_verified": False,
                        **{k: (total.get(k) if total else None) for k in COUNTERS}})
        for index, update in enumerate(usage.get("updates", [])):
            if update.get("classification") != "cumulative_usage_change":
                continue
            counter_partition(update["total"])
            observations.append({"campaign": campaign, "role": agent["role"], "model": agent["model"],
                                 "thread_id": tid, "observation_index": index,
                                 "observed_unix": update.get("observed_unix_seconds"),
                                 "host_elapsed_seconds": update.get("elapsed_from_host_start_seconds"),
                                 "host_started_unix": ledger.get("started_unix_seconds"),
                                 "owner_started_unix": started,
                                 "time_provenance": update.get("time_provenance"),
                                 **update["total"]})
    # Each timestamp updates one thread snapshot; sum each thread only once.
    # Curves are observed subtotals, never inferred exact usage between notifications.
    current = {}
    by_thread = {a["thread_id"]: a for a in ledger.get("agents", []) if a.get("thread_id")}
    for update in sorted((u for u in observations if u["observed_unix"] is not None),
                         key=lambda x: (x["observed_unix"], x["thread_id"], x["observation_index"])):
        tid = update["thread_id"]
        previous = current.get(tid)
        if previous and any(update[k] is not None and previous[k] is not None and update[k] < previous[k] for k in COUNTERS):
            raise EvidenceError("Cumulative usage regressed")
        current[tid] = update
        role = update["role"]
        role_values = [u for u in current.values() if u["role"] == role]
        subtotal = {k: sum(u[k] for u in role_values) if all(u[k] is not None for u in role_values) else None for k in COUNTERS}
        agents = [{"thread_id": u["thread_id"], "role": role, "model": u["model"],
                   "token_usage": {"total": {k: u[k] for k in COUNTERS},
                                   "cache_write_reporting_verified": by_thread[u["thread_id"]]["token_usage"].get("cache_write_reporting_verified") is True,
                                   "observed_accounting_complete": False}} for u in role_values]
        price = pricer.price_ledger({"agents": agents, "accounting_complete": False})
        bounds = price.get("observed_subtotal_bounds") or {}
        curves.append({"campaign": campaign, "role": role, "observed_unix": update["observed_unix"],
                       "elapsed_seconds": update["observed_unix"] - started, "scope": "observed_subtotal",
                       "clock_origin": "owner_state.started_unix", "owner_started_unix": started,
                       **subtotal, "api_equivalent_lower_usd": bounds.get("lower_usd"),
                       "api_equivalent_upper_usd": bounds.get("upper_usd"),
                       "actual_billed_cost": None})
    price = pricer.price_ledger(ledger)
    # Reconcile exposed aggregates when available; a null whole-campaign aggregate
    # can deliberately represent unregistered/missing work and is not replaced.
    for role, expected in (ledger.get("per_role_tokens") or {}).items():
        selected = [t for t in threads if t["role"] == role]
        for key in COUNTERS:
            observed = sum(t[key] for t in selected) if all(t[key] is not None for t in selected) else None
            if expected.get(key) != observed:
                raise EvidenceError("Observed per-role aggregate does not reconcile")
    known = ledger.get("known_thread_totals")
    if known is not None:
        for key in COUNTERS:
            observed = sum(t[key] for t in threads) if all(t[key] is not None for t in threads) else None
            if known.get(key) != observed:
                raise EvidenceError("Observed campaign subtotal does not reconcile")
    # Coalesce simultaneous receipts to the last state, preserving every original
    # observation in usage_observations.csv.
    curves = list({(r["role"], r["observed_unix"]): r for r in curves}.values())
    return threads, observations, curves, price


def assemble(reader, states):
    reader.authenticate_origin()
    tables = {key: [] for key in ("campaigns", "trajectories", "families", "raw_pairs", "operations",
                                 "process_events", "nominations", "hypotheses", "threads",
                                 "usage_observations", "usage_curves", "heldout", "cost_bounds", "final_attempts")}
    pricer, pricing_provenance = load_pricer(reader)
    notes, accounting_supplements = [], {}
    for campaign, state in states.items():
        base, started = reader.root / "campaigns" / campaign, state["started_unix"]
        events = audit_authority(reader, campaign, state)
        operations = audit_development(reader, campaign)
        telemetry_path = base / "telemetry.json"
        ledger = reader.read(telemetry_path) if telemetry_path.exists() else None
        if ledger is not None:
            if ledger.get("runtime_source") != "official_direct_terminal_appserver":
                raise EvidenceError("Only identified measured public-runtime telemetry may enter real figures")
            if ledger.get("owner_status") != state["status"]:
                raise EvidenceError("Terminal telemetry owner status differs from anchored campaign state")
        endpoint = state["endpoint"]
        tables["campaigns"].append({"campaign": campaign, "status": state["status"],
            "started_unix": started, "sealed_unix": endpoint["sealed_unix"],
            "elapsed_seconds": endpoint["sealed_unix"] - started, "promotions": len(state["promotions"]),
            "endpoint_hash": endpoint.get("source_hash"), "seed_hash": (state.get("seed") or {}).get("source_hash"),
            "stopping_reason": endpoint.get("stopping_reason"), "stop_reason": state.get("stop_reason"),
            "terminal_usage_available": False})
        for event in events:
            if event["kind"] not in EVENT_TYPES:
                continue
            payload = event["payload"]
            tables["process_events"].append({"campaign": campaign, "sequence": event["sequence"],
                "elapsed_seconds": event["time_unix"] - started, "kind": event["kind"],
                "lane": EVENT_TYPES[event["kind"]], "role": event["role"],
                "record_id": payload.get("id", payload.get("hypothesis_id", payload.get("operation_id"))),
                "status": payload.get("status", payload.get("disposition", payload.get("assessment", payload.get("recommendation")))),
                "promoted": payload.get("promoted"), "source_hash": payload.get("source_hash")})
        for key in ("nominations", "hypotheses"):
            for rid, row in state[key].items():
                tables[key].append({"campaign": campaign, "id": rid, "source_hash": row.get("source_hash"),
                                    "status": row.get("status", row.get("disposition")),
                                    "review_id": row.get("review_id"), "parent_hash": (row.get("parent") or {}).get("source_hash")})
        for op_id, op in operations.items():
            tables["operations"].append(operation_row(campaign, op_id, op, started))
            if op.get("operation") == "bench":
                tables["process_events"].append({"campaign": campaign, "sequence": op.get("finish_sequence"),
                    "elapsed_seconds": (op.get("finished_unix") or op["started_unix"]) - started,
                    "kind": "measurement_attempt", "lane": "Measurement attempt", "role": op.get("role"),
                    "record_id": op_id, "status": op["status"], "source_hash": op.get("source_hash"),
                    "measurement_id": op.get("measurement_id"), "attempt_number": op.get("measurement_attempt_number"),
                    "selected_for_scoring": op.get("selected_for_scoring"), "invalidated": op.get("measurement_invalidated")})
            if op.get("operation") == "bench" and measurement_eligible(op) and op.get("selected_for_scoring"):
                samples, families, _ = observed_comparison(reader, base / "development/operations" / op_id,
                    op, campaign, op_id, "development", 10, source_hash=op["source_hash"],
                    reference_hash=(op.get("reference") or {}).get("source_hash"), context="all_candidate_comparisons")
                tables["raw_pairs"].extend(samples); tables["families"].extend(families)
        seed_hash = (state.get("seed") or {}).get("source_hash")
        if seed_hash:
            tables["trajectories"].append({"campaign": campaign, "checkpoint": 0, "status": "algebraic_identity",
                "ratio": 1.0, "one_sided90_lower": None, "elapsed_seconds": 0.0,
                "promotion_elapsed_seconds": 0.0, "source_hash": seed_hash, "reference_hash": seed_hash,
                "measured": False, "tokens_coordinate": None, "cost_coordinate_lower": None,
                "cost_coordinate_upper": None, "usage_coordinate_complete": False})
        for index, row in enumerate(state["trajectories"], 1):
            op = operations.get(row["operation_id"])
            if op is None or row["seed_hash"] != seed_hash or op["source_hash"] != row["source_hash"] or (op.get("reference") or {}).get("source_hash") != seed_hash:
                raise EvidenceError("Trajectory is not directly bound to original seed and checkpoint")
            eligible = row["status"] == "pass" and measurement_eligible(op) and op.get("selected_for_scoring")
            if row["status"] == "pass" and not eligible:
                raise EvidenceError("Trajectory selected a nonbinding or invalid comparison")
            value = {"campaign": campaign, "checkpoint": index, "comparison_id": row["operation_id"],
                     "status": row["status"] if not op.get("measurement_invalidated") else "invalidated_measurement",
                     "owner_recorded_status": row["status"], "measurement_invalidated": op.get("measurement_invalidated"),
                     "ratio": None, "one_sided90_lower": None,
                     "source_hash": row["source_hash"], "reference_hash": seed_hash,
                     "elapsed_seconds": row["comparison_completed_unix"] - started,
                     "promotion_elapsed_seconds": row["promotion"]["time_unix"] - started,
                     "measured": eligible, "tokens_coordinate": None,
                     "cost_coordinate_lower": None, "cost_coordinate_upper": None,
                     "usage_coordinate_complete": row.get("usage_coordinate_complete") is True}
            if eligible:
                _, _, portfolio = observed_comparison(reader, base / "development/operations" / row["operation_id"],
                    op, campaign, row["operation_id"], "development", 10,
                    source_hash=row["source_hash"], reference_hash=seed_hash, context="direct_seed_trajectory")
                value.update(ratio=portfolio["ratio"], one_sided90_lower=portfolio["one_sided90_lower"])
                if (not math.isclose(row["summary"]["portfolio_speedup"], portfolio["ratio"], rel_tol=1e-10) or
                    not math.isclose(row["summary"]["nominal90_lower"], portfolio["one_sided90_lower"], rel_tol=1e-10)):
                    raise EvidenceError("Owner trajectory summary differs from direct comparison")
            value.update(checkpoint_usage(reader, campaign, index, row, pricer, terminal_ledger=ledger))
            tables["trajectories"].append(value)
        observed_reviews = {r["promotion"]["review_id"] for r in state["trajectories"]}
        for index, promotion in enumerate(state["promotions"], 1):
            if promotion["review_id"] not in observed_reviews:
                tables["trajectories"].append({"campaign": campaign, "checkpoint": index,
                    "status": "trajectory_observation_unavailable", "ratio": None, "one_sided90_lower": None,
                    "elapsed_seconds": None, "promotion_elapsed_seconds": promotion["time_unix"] - started,
                    "source_hash": promotion["source_hash"], "reference_hash": seed_hash, "measured": False,
                    "tokens_coordinate": None, "cost_coordinate_lower": None, "cost_coordinate_upper": None,
                    "usage_coordinate_complete": False})
        if ledger is not None:
            threads, observations, curves, price = usage_tables(ledger, campaign, started, pricer)
            tables["campaigns"][-1]["terminal_usage_available"] = True
            host_started = ledger.get("started_unix_seconds")
            observed_times = [r["observed_unix"] for r in observations if r["observed_unix"] is not None]
            tables["campaigns"][-1].update(usage_host_started_unix=host_started,
                usage_host_origin_offset_seconds=host_started-started if host_started is not None else None,
                usage_host_wall_seconds=ledger.get("campaign_wall_seconds"),
                last_usage_observed_unix=max(observed_times) if observed_times else None,
                last_usage_relative_to_seal_seconds=max(observed_times)-endpoint["sealed_unix"] if observed_times else None)
            supplement, unavailable_reason = refined_pricing(reader, telemetry_path, observed_complete=ledger.get("accounting_complete"))
            if unavailable_reason:
                notes.append(f"{campaign}: {unavailable_reason}")
            # Retain frozen broad bounds in every row, then prefer supported
            # delta-based context-band accounting when its replay reconciles.
            for curve in curves:
                curve["frozen_broad_lower_usd"] = curve["api_equivalent_lower_usd"]
                curve["frozen_broad_upper_usd"] = curve["api_equivalent_upper_usd"]
                curve["pricing_method"] = "frozen_unknown_short_long_band"
            if supplement:
                accounting_supplements[campaign] = supplement
                increments = []
                for thread in supplement["threads"]:
                    for obs in thread["observations"]:
                        if obs.get("observed_unix_seconds") is not None:
                            increments.append({**obs, "role": thread["role"]})
                for curve in curves:
                    observed = [r for r in increments if r["role"] == curve["role"] and r["observed_unix_seconds"] <= curve["observed_unix"]]
                    for bound in ("lower", "upper"):
                        cost = sum((Decimal(r[f"observed_subtotal_{bound}_usd"]) for r in observed), Decimal(0))
                        curve[f"api_equivalent_{bound}_usd"] = float(cost)
                        curve[f"api_equivalent_{bound}_usd_decimal"] = str(cost)
                    curve["pricing_method"] = ("source_grounded_interrupted_observed_bands" if supplement.get("analysis_kind") == "interrupted_run_observed_counters_only" else "source_grounded_complete_response_bands")
            tables["threads"].extend(threads); tables["usage_observations"].extend(observations); tables["usage_curves"].extend(curves)
            for role, entry in price["per_role"].items():
                bounds_row = {"campaign": campaign, "role": role,
                    **(entry.get("observed_subtotal_bounds") or {}), "missing_usage_threads": entry["missing_usage_threads"],
                    "observed_accounting_complete": price["observed_accounting_complete"],
                    "actual_billed_cost": None, "rates_as_of": price["rates_as_of"], "hypothetical_tier": "Standard",
                    "whole_model_work_verified": False,
                    "interrupted_usage_tail_unknown": any(t["interrupted_usage_tail_unknown"] for t in threads if t["role"] == role),
                    "remote_compaction_observed": any(t["remote_compaction_observed"] for t in threads if t["role"] == role)}
                bounds_row["frozen_broad_lower_usd"] = bounds_row.get("lower_usd")
                bounds_row["frozen_broad_upper_usd"] = bounds_row.get("upper_usd")
                if supplement:
                    for bound in ("lower", "upper"):
                        cost = sum((Decimal(t[f"observed_subtotal_{bound}_usd"]) for t in supplement["threads"] if t["role"] == role), Decimal(0))
                        bounds_row[f"{bound}_usd"], bounds_row[f"{bound}_usd_decimal"] = float(cost), str(cost)
                tables["cost_bounds"].append(bounds_row)
        else:
            notes.append(f"{campaign}: terminal telemetry unavailable; usage and cost are unknown")
    final_path = reader.root / "assessment/final/report.json"
    final_status = "not_available"
    if reader.final_released and final_path.exists():
        report = reader.read(final_path)
        final_status = report.get("status")
        if final_status != "complete":
            raise EvidenceError("Completion receipt disagrees with final assessment report")
        else:
            if set(report.get("planned_campaigns", [])) != set(CAMPAIGNS):
                raise EvidenceError("Final planned denominator mismatch")
            identities = set()
            final_ops = {}
            for sequence, record in enumerate(report.get("operations", []), 1):
                directory = final_path.parent / record["artifact_directory"]
                manifest = reader.read(directory / "files.json")
                manifest_key = (directory / "files.json").relative_to(reader.root).as_posix()
                if reader.sources[manifest_key]["sha256"] != record.get("files_manifest_sha256"):
                    raise EvidenceError("Final operation manifest differs from final report")
                result = reader.read(directory / "result.json")
                result_key = (directory / "result.json").relative_to(reader.root).as_posix()
                if reader.sources[result_key]["sha256"] != manifest["files"].get("result.json"):
                    raise EvidenceError("Final attempt result differs from manifest")
                final_ops[result["operation_id"]] = {**result, "files": manifest["files"], "finish_sequence": sequence}
            select_measurements(final_ops)
            for op_id, op in final_ops.items():
                tables["final_attempts"].append({"operation_id": op_id,
                    **{key: op.get(key) for key in ("operation", "source_hash", "stratum", "status",
                        "measurement_id", "measurement_attempt_number", "measurement_prior_attempt_ids",
                        "measurement_retry_reason", "measurement_invalidated", "selected_for_scoring", "selection_basis")},
                    "portfolio_speedup": op.get("portfolio_speedup") if op.get("selected_for_scoring") else None})
            for row in report["rows"]:
                campaign, stratum = row["campaign_id"], row["stratum"]
                if campaign not in CAMPAIGNS or stratum not in STRATA or (campaign, stratum) in identities:
                    raise EvidenceError("Final campaign/stratum identity invalid")
                identities.add((campaign, stratum))
                if row.get("source_hash") is not None and row["source_hash"] != states[campaign]["endpoint"].get("source_hash"):
                    raise EvidenceError("Final row differs from sealed endpoint")
                if row.get("seed_hash") is not None and row["seed_hash"] != (states[campaign].get("seed") or {}).get("source_hash"):
                    raise EvidenceError("Final row differs from original seed")
                value = {"campaign": campaign, "stratum": stratum, "status": row["status"],
                         "campaign_status": row["campaign_status"], "source_hash": row.get("source_hash"),
                         "reference_hash": row.get("seed_hash"), "ratio": row.get("algebraic_identity_ratio"),
                         "one_sided90_lower": None, "measured": row.get("measured_performance") is True}
                if row["status"] == "measured":
                    directory = final_path.parent / row["evidence"]
                    result = final_ops.get(row["evidence"])
                    if result is None or not result.get("selected_for_scoring"):
                        raise EvidenceError("Final endpoint did not use the first valid immutable attempt")
                    if any(row.get(key) != result.get(key) for key in ("measurement_id", "measurement_attempt_number", "measurement_prior_attempt_ids")):
                        raise EvidenceError("Final row retry lineage differs from selected result")
                    if row.get("source_hash") != states[campaign]["endpoint"].get("source_hash"):
                        raise EvidenceError("Final result source differs from sealed endpoint")
                    manifest = reader.read(directory / "files.json")
                    record = next((op for op in report["operations"] if op.get("artifact_directory") == row["evidence"]), None)
                    manifest_path = (directory / "files.json").relative_to(reader.root).as_posix()
                    if record is None or reader.sources[manifest_path]["sha256"] != record.get("files_manifest_sha256"):
                        raise EvidenceError("Final operation manifest differs from final report")
                    result_path = (directory / "result.json").relative_to(reader.root).as_posix()
                    if reader.sources[result_path]["sha256"] != manifest["files"].get("result.json"):
                        raise EvidenceError("Final result differs from its file manifest")
                    samples, families, portfolio = observed_comparison(reader, directory, {**result, "files": manifest["files"]},
                        campaign, f"{campaign}-{stratum}", stratum, 30, source_hash=row["source_hash"],
                        reference_hash=row["seed_hash"], context="heldout_endpoint")
                    tables["raw_pairs"].extend(samples); tables["families"].extend(families)
                    value.update(ratio=portfolio["ratio"], one_sided90_lower=portfolio["one_sided90_lower"])
                    if not math.isclose(row["speedup"], portfolio["ratio"], rel_tol=1e-10):
                        raise EvidenceError("Final report and raw portfolio estimates disagree")
                tables["heldout"].append(value)
            for campaign in CAMPAIGNS:
                for stratum in STRATA:
                    if (campaign, stratum) not in identities:
                        tables["heldout"].append({"campaign": campaign, "stratum": stratum,
                            "status": "assessment_incomplete", "campaign_status": states[campaign]["status"],
                            "ratio": None, "one_sided90_lower": None, "measured": False})
    if not reader.final_released:
        notes.append("Held-out evidence unopened: waiting for all seals and the final-assessment completion receipt")
    for campaign in CAMPAIGNS:
        for stratum in STRATA:
            if not any(r["campaign"] == campaign and r["stratum"] == stratum for r in tables["heldout"]):
                tables["heldout"].append({"campaign": campaign, "stratum": stratum, "status": "assessment_unavailable",
                    "campaign_status": states[campaign]["status"], "ratio": None, "one_sided90_lower": None, "measured": False})
    return {"schema_version": 3, "study_version": "unattended-optimization-v3", "synthetic": False, "cohort_terminal": True,
            "final_evidence_released": reader.final_released,
            "analysis_provenance": {"extractor_sha256": digest(Path(__file__).read_bytes()),
                "generic_source_reuse": "Earlier generic extraction source adapted; no earlier result data imported"},
            "relocation": {"original_root": reader.authenticate_origin(), "local_root": str(reader.root),
                "freeze_sha256": reader.expected_freeze,
                "method": "Canonical within-freeze-root paths mapped to local allowlisted relative evidence; raw bytes unchanged"},
            "clock_convention": {"common_origin": "Each campaign's owner state.started_unix",
                "development": "Comparison completion Unix timestamp minus owner start Unix timestamp",
                "usage": "Notification observation Unix timestamp minus owner start Unix timestamp; includes shutdown receipts",
                "host_clock": "Host start Unix timestamp and original host-relative counters are retained separately; never treated as identical to owner start",
                "checkpoint_costs": "No interpolation; missing exact checkpoint usage/cost coordinates remain null"},
            "final_assessment_status": final_status, "tables": tables, "notes": notes,
            "accounting_supplements": accounting_supplements,
            "pricing": {"rates_as_of": pricer.RATES_AS_OF, "rate_sources": list(pricer.SOURCES),
                        "rates_usd_per_million": pricer.STANDARD_RATES_USD_PER_MILLION,
                        "implementation": pricing_provenance},
            "limitations": ["Single task; three campaigns share task, host and service; descriptive outcomes only.",
                "Development checkpoints are adaptively selected; no campaign-wide confidence band.",
                "One-sided nominal 90% portfolio lower bounds are the frozen uncertainty summary; raw family-pair plots show within-comparison block variation, not confidence intervals.",
                "API-equivalent intervals cover observed token subtotals under hypothetical Standard rates, not actual billing or missing usage.",
                "Input includes cached input; output includes reasoning; do not add subsets again.",
                "Notification times are observation times; missing checkpoint usage has no invented coordinate."],
            "sources": reader.sources}


def write_tables(out, bundle):
    (out / "figure-data.json").write_text(json.dumps(bundle, indent=2, allow_nan=False) + "\n")
    for name, rows in bundle.get("tables", {}).items():
        keys = list(dict.fromkeys(k for row in rows for k in row))
        with (out / f"{name}.csv").open("w", newline="") as stream:
            if keys:
                writer = csv.DictWriter(stream, keys)
                writer.writeheader(); writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-root", type=Path, default=HERE.parent.parent)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    out = output_directory(args.out)
    reader = Reader(args.study_root)
    states, status = {}, []
    for campaign in CAMPAIGNS:
        path = reader.root / "campaigns" / campaign / "authority/state.json"
        state = reader.read(path) if path.exists() else None
        terminal = identity_check(state, campaign) if state else False
        status.append({"campaign": campaign, "status": state.get("status") if state else "not_started",
                       "terminal_seal_present": terminal})
        if terminal:
            states[campaign] = state
    if len(states) != 3:
        write_tables(out, {"schema_version": 3, "study_version": "unattended-optimization-v3", "synthetic": False, "cohort_terminal": False,
                          "status": "pending", "tables": {"campaigns": status}, "sources": reader.sources,
                          "reason": "All three planned terminal sealed endpoints are required before scientific figure extraction"})
        print("Pending: status tables only; no scientific outcome figures may be rendered")
        return 2
    reader.release_final(states)
    bundle = assemble(reader, states)
    write_tables(out, bundle)
    print(f"Extracted terminal evidence and retained tables: {out}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (EvidenceError, KeyError, ValueError, OSError) as exc:
        print(f"Figure extraction refused: {exc}", file=sys.stderr)
        sys.exit(2)
