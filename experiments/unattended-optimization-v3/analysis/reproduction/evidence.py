#!/usr/bin/env python3
"""Offline, fail-closed release packaging. Never imports or runs the study runtime.

Only terminal v3 evidence may be read. The full preserved archive and the lean
Git subset are distinct byte inventories; neither launches native execution.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys

FROZEN_SHA256 = "a28a9e9984aa03a1a28c950bfd846e0d179202f719a43982a27c72a69c934178"
CAMPAIGNS = tuple(f"campaign-{n}" for n in range(1, 4))
FROZEN_AREAS = {"owner", "runtime", "development", "task", "tools", "protocol", "evaluation"}
FULL_KIND = "v3-preserved-evidence-archive"
LEAN_KIND = "v3-source-and-essential-data"
PRIVATE_PARTS = {".git", ".aws", ".ssh", ".codex", ".study-codex-runtime", "auth", "credentials", "sessions", "rollouts", "node_modules", "raw-remotes", "raw_remotes", "provider-logs", "provider_logs", "remote-responses", "remote_responses"}
PRIVATE_NAMES = {"auth.json", "credentials.json", ".env", ".netrc", ".npmrc", "id_rsa", "id_ed25519"}
RUNTIME_ITEM_KEYS = {
    "threadStartMetadata": {"type", "metadata"},
    "ownerTask": {"type", "text", "source"},
    "ownerMessage": {"type", "text", "purpose"},
    "commandExecution": {"id", "type", "command", "cwd", "status", "aggregatedOutput", "exitCode", "durationMs"},
    "fileChange": {"id", "type", "status", "changes"},
    "agentReport": {"type", "report", "diagnostics"},
    "agentReportUnparsedText": {"type", "text", "diagnostics"},
        "agentReportParseDiagnostics": {"type", "diagnostics"},
}
PRIVATE_LABEL = re.compile(r"(?i)(?:private[-_ ]?reasoning|chain[-_ ]?of[-_ ]?thought|provider[-_ ]?logs?|raw[-_ ]?(?:responses?|events?)|unrelated[-_ ]?personal)")
TEXT_SUFFIXES = {".py", ".sh", ".cpp", ".h", ".hpp", ".ipp", ".tpp", ".json", ".jsonl", ".txt", ".md", ".csv", ".tsv", ".svg", ".bib", ".typ", ".out", ".log"}
PRIVATE_JSON_KEYS = {"private_reasoning", "chain_of_thought", "encrypted_content", "raw_response", "rawresponse", "access_token", "refresh_token", "api_key", "password", "client_secret", "raw_remote", "raw_remote_response", "private_model_reasoning", "reasoning_content"}
SECRET = re.compile(rb"(?:sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{24,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|Bearer [A-Za-z0-9._-]{24,})")


class Refusal(ValueError):
    pass


def encoded(obj):
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def safe_relative(value):
    if not isinstance(value, str) or "\\" in value or any(ord(c) < 32 or ord(c) == 127 for c in value) or ":" in value:
        raise Refusal("Invalid relative artifact name")
    p = PurePosixPath(value)
    if PRIVATE_LABEL.search(value):
        raise Refusal("Private path is never packageable: " + value)
    if p.is_absolute() or not p.parts or any(x in ("", ".", "..") for x in value.split("/")):
        raise Refusal("Artifact must use a canonical relative path")
    if any(x.lower() in PRIVATE_PARTS for x in p.parts) or p.name.lower() in PRIVATE_NAMES or p.name.lower().startswith(".env."):
        raise Refusal("Private path is never packageable: " + value)
    return p


def local(root, relative, *, exists=True):
    rel = safe_relative(relative)
    root = Path(root).resolve(strict=True)
    path = root.joinpath(*rel.parts)
    cursor = root
    for part in rel.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise Refusal("Symlink is not evidence: " + relative)
    if not path.resolve().is_relative_to(root):
        raise Refusal("Artifact escapes its declared root")
    if exists and not path.is_file():
        raise Refusal("Required ordinary file missing: " + relative)
    return path


def read(root, relative):
    return loads(local(root, relative).read_bytes())


def write_new(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(encoded(obj))


def pin(root, relative):
    path = local(root, relative)
    if not stat.S_ISREG(path.stat().st_mode):
        raise Refusal("Special file is not evidence")
    return {"sha256": sha(path), "bytes": path.stat().st_size, "executable": bool(path.stat().st_mode & 0o111)}


def loads(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise Refusal("Duplicate JSON key")
            result[key] = value
        return result
    def constant(value):
        raise Refusal("Nonfinite JSON constant")
    return json.loads(raw, object_pairs_hook=unique, parse_constant=constant)


def outside_study(path, root):
    path = Path(path).absolute()
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise Refusal("Output path contains a symlink")
    if path.resolve().is_relative_to(Path(root).resolve()):
        raise Refusal("Output must be outside historical evidence")


def decoded_content_check(value, relative, *, private_blocks):
    """Inspect ordinary JSON decoding without printing any matched payload."""
    if isinstance(value, str):
        if SECRET.search(value.encode("utf-8")):
            raise Refusal("content_refused:decoded_credential_pattern:" + relative)
        if private_blocks and re.search(r"<(?:analysis|think|private_reasoning)>", value, re.I):
            raise Refusal("content_refused:decoded_private_reasoning_block:" + relative)
    elif isinstance(value, dict):
        for key, child in value.items():
            decoded_content_check(key, relative, private_blocks=private_blocks)
            decoded_content_check(child, relative, private_blocks=private_blocks)
    elif isinstance(value, list):
        for child in value: decoded_content_check(child, relative, private_blocks=private_blocks)


def content_check(path, relative):
    """Finite credential/private-payload refusal. Errors contain paths/categories only."""
    overlap = b""
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            sample = overlap + part
            if SECRET.search(sample):
                raise Refusal("content_refused:credential_pattern:" + relative)
            overlap = sample[-4096:]
    p = PurePosixPath(relative)
    is_source = p.parts[0] in FROZEN_AREAS | {"tests"} or p.suffix in {".py", ".sh", ".cpp", ".h", ".hpp", ".ipp", ".tpp", ".md", ".typ", ".bib"}
    if p.suffix in TEXT_SUFFIXES:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            raise Refusal("content_refused:text_encoding:" + relative) from None
        if not is_source and re.search(r"<(?:analysis|think|private_reasoning)>", text, re.I):
            raise Refusal("content_refused:private_reasoning_block:" + relative)
        if p.suffix == ".json":
            try:
                value = loads(text)
            except ValueError:
                raise Refusal("content_refused:invalid_json:" + relative) from None
            decoded_content_check(value, relative, private_blocks=not is_source)
            def inspect(value):
                if isinstance(value, dict):
                    if any(str(k).lower() in PRIVATE_JSON_KEYS for k in value):
                        raise Refusal("content_refused:private_or_credential_field:" + relative)
                    if type(value.get("type")) is str and value["type"] in {"reasoning", "rawResponse"}:
                        raise Refusal("content_refused:private_provider_item:" + relative)
                    for v in value.values(): inspect(v)
                elif isinstance(value, list):
                    for v in value: inspect(v)
            if not is_source: inspect(value)


def trace_check(path):
    """Strictly typed projection of ordinary command/patch/report items only."""
    references = []
    def fail():
        raise Refusal("content_refused:runtime_schema:" + path.as_posix() + ":" + str(n))
    def scalar(value, types, nullable=False):
        if not (nullable and value is None) and type(value) not in types: fail()
    def string_list(value):
        if not isinstance(value, list) or any(type(v) is not str for v in value): fail()
    def diagnostics(value):
        fields = {"schema_valid", "parse_issues", "artifact_references", "evidence_authority", "ordinary_report_evidence"}
        if not isinstance(value, dict) or not set(value) <= fields: fail()
        for key, v in value.items():
            if key == "schema_valid": scalar(v, (bool,))
            elif key == "parse_issues": string_list(v)
            elif key == "artifact_references":
                if not isinstance(v, list): fail()
                for row in v:
                    kinds = {"index": (int,), "kind": (str,), "verified": (bool,), "dereferenced": (bool,), "lexically_within_declared_roots": (bool,), "diagnostic": (str,)}
                    if not isinstance(row, dict) or not set(row) <= set(kinds): fail()
                    for k, child in row.items(): scalar(child, kinds[k])
            else: scalar(v, (str,))
    def safe_metadata_text(value):
        scalar(value, (str,), True)
        if isinstance(value, str) and (len(value) > 4096 or any(ord(c) < 32 for c in value)): fail()
    def start_metadata(value):
        fields = {"model", "reasoningEffort", "modelProvider", "cwd", "thread", "approvalPolicy", "sandbox"}
        if not isinstance(value, dict) or set(value) != fields: fail()
        for key in ("model", "reasoningEffort", "modelProvider", "cwd"): safe_metadata_text(value[key])
        if not isinstance(value["thread"], dict) or set(value["thread"]) != {"id", "cliVersion"}: fail()
        for child in value["thread"].values(): safe_metadata_text(child)
        approval = value["approvalPolicy"]
        if isinstance(approval, dict):
            if set(approval) != {"granular"} or not isinstance(approval["granular"], dict): fail()
            if not set(approval["granular"]) <= {"mcp_elicitations", "request_permissions", "rules", "sandbox_approval", "skill_approval"}: fail()
            for child in approval["granular"].values(): scalar(child, (bool,))
        elif approval is not None and approval not in ("never", "untrusted", "on-request"): fail()
        sandbox = value["sandbox"]
        if sandbox is not None:
            if not isinstance(sandbox, dict) or "type" not in sandbox or not set(sandbox) <= {"type", "networkAccess", "excludeTmpdirEnvVar", "excludeSlashTmp", "writableRoots"}: fail()
            safe_metadata_text(sandbox["type"])
            for key in ("networkAccess", "excludeTmpdirEnvVar", "excludeSlashTmp"):
                if key in sandbox and sandbox[key] is not None and type(sandbox[key]) is not bool and sandbox[key] not in ("restricted", "enabled"): fail()
            if "writableRoots" in sandbox and sandbox["writableRoots"] is not None:
                if not isinstance(sandbox["writableRoots"], list): fail()
                for child in sandbox["writableRoots"]: safe_metadata_text(child)
    with path.open("rb") as stream:
        for n, line in enumerate(stream, 1):
            if SECRET.search(line):
                raise Refusal("content_refused:credential_pattern:" + path.name)
            try: row = loads(line)
            except (ValueError, UnicodeError): fail()
            decoded_content_check(row, path.name, private_blocks=True)
            if not isinstance(row, dict) or set(row) != {"thread_id", "turn_id", "item"}: fail()
            scalar(row["thread_id"], (str,), True); scalar(row["turn_id"], (str,), True)
            item = row["item"]
            if not isinstance(item, dict): fail()
            kind = item.get("type")
            if not isinstance(kind, str) or kind not in RUNTIME_ITEM_KEYS or not set(item) <= RUNTIME_ITEM_KEYS[kind]: fail()
            for key in {"id", "command", "cwd", "status", "text"} & item.keys(): scalar(item[key], (str,))
            if "aggregatedOutput" in item: scalar(item["aggregatedOutput"], (str,), True)
            if "exitCode" in item: scalar(item["exitCode"], (int,), True)
            if "durationMs" in item: scalar(item["durationMs"], (int,), True)
            if "diagnostics" in item: diagnostics(item["diagnostics"])
            if kind == "threadStartMetadata":
                if set(item) != {"type", "metadata"}: fail()
                start_metadata(item["metadata"])
            if kind == "ownerTask":
                if set(item) != {"type", "text", "source"} or item["source"] != "owner_or_lead_delegation": fail()
            if kind == "ownerMessage":
                if not {"type", "text"} <= set(item) or "purpose" in item and item["purpose"] != "cooperative_wrap_up": fail()
            if kind == "fileChange":
                if not isinstance(item.get("changes"), list): fail()
                for change in item["changes"]:
                    if not isinstance(change, dict) or set(change) != {"path", "kind", "diff"}: fail()
                    for key in {"path", "diff"} & change.keys(): scalar(change[key], (str,))
                    value = change.get("kind")
                    if not isinstance(value, dict) or value.get("type") not in {"add", "delete", "update"}: fail()
                    allowed = {"type", "move_path"} if value["type"] == "update" else {"type"}
                    if not set(value) <= allowed: fail()
                    if "move_path" in value: scalar(value["move_path"], (str,), True)
            if kind == "agentReport":
                report = item.get("report")
                if not isinstance(report, dict) or set(report) != {"summary", "artifacts", "checks", "limitations"}: fail()
                scalar(report["summary"], (str,), True)
                for key in ("artifacts", "checks", "limitations"): string_list(report[key])
                references.extend({"line": n, "artifact_index": i, "reference": value} for i, value in enumerate(report["artifacts"]))
    return references


def release_gate(root, expected_freeze=FROZEN_SHA256):
    """Read launcher and all endpoint seals before opening any final material."""
    root = Path(root).resolve(strict=True)
    freeze = read(root, "state/freeze.json")
    if (sha(local(root, "state/freeze.json")) != expected_freeze or freeze.get("status") != "frozen"
            or freeze.get("campaign_count") != 3):
        raise Refusal("Wrong frozen v3 experiment")
    launch = read(root, "state/launch/status.json")
    if launch.get("status") not in ("complete", "stopped_incomplete"):
        raise Refusal("Native measurements may still be active")
    paths = ["state/freeze.json", "state/launch/status.json"]
    campaigns = []
    for name in CAMPAIGNS:
        prefix = "campaigns/" + name
        state = read(root, prefix + "/authority/state.json")
        endpoint = state.get("endpoint") or {}
        if (state.get("campaign_id") != name or state.get("stage") != "measured"
                or state.get("status") not in ("complete", "incomplete")
                or "sealed_unix" not in endpoint):
            raise Refusal("All three measured endpoints must be terminal and sealed")
        if endpoint.get("stopping_reason") != ("task_complete" if state["status"] == "complete" else "incomplete"):
            raise Refusal("Endpoint seal and terminal status disagree")
        if read(root, prefix + "/telemetry.json").get("sealed") is not True:
            raise Refusal("Runtime evidence is not sealed")
        campaigns.append({"campaign_id": name, "status": state["status"], "source_hash": endpoint.get("source_hash")})
        paths.extend([prefix + "/authority/state.json", prefix + "/telemetry.json"])
    report = read(root, "assessment/final/report.json")
    if (report.get("status") not in ("complete", "blocked") or "finished_unix" not in report
            or report.get("planned_campaigns") != list(CAMPAIGNS)
            or report.get("fixed_source_no_reselection") is not True):
        raise Refusal("Canonical final assessment has no terminal, fixed-source outcome")
    paths.append("assessment/final/report.json")
    return freeze, {"campaigns": campaigns, "assessment_status": report["status"],
                    "pins": {p: pin(root, p) for p in paths}}


def historical_relative(absolute, original_root):
    if not isinstance(absolute, str) or not isinstance(original_root, str):
        raise Refusal("Historical artifact pin must be a path string")
    for value in (absolute, original_root):
        if (not value.startswith("/") or "\\" in value or any(ord(c) < 32 or ord(c) == 127 for c in value) or ":" in value
                or any(part in ("", ".", "..") for part in value.split("/")[1:])):
            raise Refusal("Historical artifact pin is not canonical absolute")
        # An external node_modules path can name a pinned public executable.
        # Preserve that metadata without opening it; safe_relative below still
        # excludes every within-study node_modules path from rebasing/copying.
        if any(part.lower() in PRIVATE_PARTS - {"node_modules"} or part.lower() in PRIVATE_NAMES or part.lower().startswith(".env.")
               for part in PurePosixPath(value).parts):
            raise Refusal("Historical path refers to private authentication/session material")
    p, base = PurePosixPath(absolute), PurePosixPath(original_root)
    try:
        relative = p.relative_to(base).as_posix()
    except ValueError:
        return None
    safe_relative(relative)
    return relative


def exclusion(relative):
    """Prune private, raw, and unrelated namespaces before traversing or reading."""
    p = PurePosixPath(relative)
    try:
        safe_relative(relative)
    except Refusal:
        return "private, raw-provider or invalid path; not read"
    if "scratch" in p.parts:
        return "participant scratch; formal snapshots and filtered report references are authoritative"
    if "__pycache__" in p.parts or p.suffix == ".pyc" or p.name.endswith(".lock"):
        return "cache or coordination artifact"
    parts, area = p.parts, p.parts[0]
    if area in FROZEN_AREAS or relative in {"README.md", "VERSION-STATUS.md"}:
        return None
    if area == "campaigns":
        if len(parts) == 1 or parts[1] in CAMPAIGNS and (len(parts) == 2 or parts[2] in {
                "authority", "development", "runtime", "workspace-operations", "telemetry.json", "summary.json"}):
            return None
    if area == "assessment" and (len(parts) == 1 or parts[1] == "final"):
        return None
    if area == "state":
        if len(parts) == 1 or parts[1] in {"freeze.json", "start-attempt"}:
            return None
        if parts[1] == "launch" and (len(parts) == 2 or parts[2] in {"status.json", "authorization.json", "preflight.json"}):
            return None
    if area == "setup":
        if len(parts) == 1:
            return None
        known = {"failed-preflights", "live-preflight", "launch-native", "verification", "config-revisions",
                 "final-fixtures-preparation", "readiness-revisions", "host-preparation.json", "owner-readiness-v3.json", "readiness.json",
                 "preflight.json", "final-evaluator-config-transfer.json", "final-evaluator-config-shift.json"}
        if parts[1] in known or re.fullmatch(r"(?:native-validation|fresh-native-readiness|evaluator-controls|additional-guard-controls|native-measurement-bridge|readiness-regressions|workspace-cli-probe|workspace-router-probe|thread-start-diagnostic)-[0-9]+", parts[1]):
            return None
    if area == "tests":
        if len(parts) == 1 or parts[1] in {"owner", "runtime", "development", "evaluation", "workspace", "audit"}:
            return None
    if area == "analysis":
        if len(parts) == 1:
            return None
        if relative in {"analysis/figures/fixtures", "analysis/figures/fixtures/host-export-checkpoint.json"}:
            return None
        if parts[1] in {"reproduction", "figures", "manuscript-draft"}:
            if len(parts) == 2 or len(parts) == 3 and p.suffix in {".py", ".md", ".json", ".bib", ".typ"}:
                return None
        if parts[1] == "checkpoints" and (len(parts) == 2 or len(parts) == 3 and p.suffix == ".json"):
            return None
        if len(parts) == 2 and p.suffix in {".py", ".md", ".json"}:
            return None
    return "outside declared study evidence/source namespaces; not read"


def eligible_file(relative):
    if why := exclusion(relative):
        return why
    p = PurePosixPath(relative)
    workflow_runtime = p.parts[0] in {"setup", "campaigns"} and "runtime" in p.parts
    if p.suffix == ".jsonl" and not workflow_runtime:
        return "not a recognized filtered ordinary runtime stream; not read"
    if workflow_runtime and p.suffix != ".jsonl":
        return "not a filtered ordinary runtime item stream; not read"
    return None


def walk(root, area):
    base = Path(root) / area
    if why := exclusion(area):
        yield area, why
        return
    if base.is_symlink():
        raise Refusal("Symlink in evidence namespace")
    if not base.exists():
        return
    for directory, dirs, files in os.walk(base, followlinks=False):
        dirs.sort()
        for name in sorted(dirs + files):
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            why = exclusion(relative)
            if why:
                if name in dirs:
                    dirs.remove(name)
                yield relative, why
            elif path.is_symlink():
                raise Refusal("Symlink in evidence namespace: " + relative)
            elif name in files:
                yield relative, None


def inventory(root):
    files, excluded, references = {}, [], []
    for area in sorted(FROZEN_AREAS | {"setup", "state", "campaigns", "assessment", "analysis", "tests"}):
        for relative, why in walk(root, area):
            why = why or eligible_file(relative)
            if why:
                excluded.append({"path": relative, "reason": why})
                continue
            path = local(root, relative)
            content_check(path, relative)
            if path.suffix == ".jsonl":
                references.extend({"trace": relative, **row} for row in trace_check(path))
            files[relative] = pin(root, relative)
    for name in ("README.md", "VERSION-STATUS.md"):
        if (Path(root) / name).exists():
            content_check(local(root, name), name)
            files[name] = pin(root, name)
    return files, sorted(excluded, key=lambda r: r["path"]), sorted(references, key=lambda r: (r["trace"], r["line"], r["artifact_index"]))


def lean_exclusion(relative):
    """Retain sources, all attempts' metadata, pairs, profiles, and usage; omit bulky duplicates."""
    p = PurePosixPath(relative)
    if p.suffix in {".so", ".o", ".a", ".bin", ".gz", ".zip", ".tar", ".png", ".pdf"}:
        return "binary/generated input/render; retained in separate full archive"
    if p.suffix == ".jsonl":
        return "filtered factual command/report stream; retained in separate full archive"
    if p.name.startswith("callgrind.out"):
        return "raw instruction profile; annotation and result retained, complete profile in full archive"
    if "/operations/" in relative or relative.startswith("assessment/final/"):
        if "work" in p.parts:
            return "temporary copied/custom-check work tree; complete bytes in full archive"
        # Preserve raw/paired/schedule/calibration, per-sample command/measurement,
        # manifests, failures, diagnostics and annotations. Repeated stdout timing
        # is already represented in raw.json and per-sample measurement.json.
        if p.suffix == ".json" or p.suffix in {".cpp", ".h", ".py"}:
            return None
        if any(x.startswith("annotation-") for x in p.parts) and p.name in {"stdout.txt", "stderr.txt"}:
            return None
        if any(x in {"calibrate-baseline", "calibrate-candidate"} for x in p.parts) and p.name == "stdout.txt":
            return None
        if p.name in {"stderr.txt", "memcheck.txt", "memory.txt"}:
            return None
        return "duplicate native stdout or other bulky operation artifact; full archive retains exact bytes"
    if p.suffix in TEXT_SUFFIXES or p.name in {"Makefile", "CMakeLists.txt"}:
        return None
    return "nonessential binary/opaque dependency; full archive retains exact bytes"


def frozen_pins(freeze):
    manifest = freeze["manifest"]
    if digest(encoded(manifest["files"])) != manifest["sha256"]:
        raise Refusal("Frozen source manifest digest mismatch")
    required = dict(manifest["files"])
    if any(PurePosixPath(p).parts[0] not in FROZEN_AREAS for p in required):
        raise Refusal("Unexpected frozen source namespace")
    external = {}
    for absolute, expected in freeze.get("runtime_artifacts", {}).items():
        relative = historical_relative(absolute, manifest["root"])
        if relative is None:
            # Metadata only. Never open external tools, a home or unrelated checkout.
            external[absolute] = expected
        else:
            if relative in required and required[relative] != expected:
                raise Refusal("Conflicting frozen source/dependency pin")
            required[relative] = expected
    for key in ("readiness", "preflight"):
        relative = historical_relative(freeze[key + "_path"], manifest["root"])
        if relative is None:
            raise Refusal("Required readiness/preflight must be inside the study")
        required[relative] = freeze[key + "_sha256"]
    return required, external


def verify_frozen(root, files, omitted=None, expected_freeze=FROZEN_SHA256):
    if sha(local(root, "state/freeze.json")) != expected_freeze:
        raise Refusal("Historical freeze bytes differ")
    freeze = read(root, "state/freeze.json")
    required, external = frozen_pins(freeze)
    combined = {**files, **(omitted or {})}
    for relative, expected in required.items():
        record = combined.get(relative)
        if record is None or record["sha256"] != expected:
            raise Refusal("Frozen source/dependency missing or different: " + relative)
        if relative in files and sha(local(root, relative)) != expected:
            raise Refusal("Frozen material bytes differ: " + relative)
    actual = {p for p in combined if PurePosixPath(p).parts[0] in FROZEN_AREAS}
    if actual != set(freeze["manifest"]["files"]):
        raise Refusal("Frozen source inventory changed")
    return external


def make_plan(root, expected_freeze=FROZEN_SHA256, *, mode="archive", max_git_bytes=25_000_000):
    if mode not in {"archive", "git"}:
        raise Refusal("Unknown release mode")
    root = Path(root).resolve(strict=True)
    freeze, release = release_gate(root, expected_freeze)
    all_files, excluded, references = inventory(root)
    external = verify_frozen(root, all_files, expected_freeze=expected_freeze)
    selected, omitted = {}, {}
    for relative, record in sorted(all_files.items()):
        why = lean_exclusion(relative) if mode == "git" else None
        if why:
            omitted[relative] = {**record, "reason": why}
        else:
            selected[relative] = record
    if mode == "git" and sum(row["bytes"] for row in selected.values()) > max_git_bytes:
        raise Refusal("Git subset exceeds explicit byte budget; review scope, never silently drop evidence")
    for row in references:
        value = row.pop("reference")
        # Raw paths outside the study are not exported; do not propagate remotes.
        relative = None
        if value.startswith("/"):
            try:
                relative = historical_relative(value, freeze["manifest"]["root"])
            except Refusal:
                pass
        row.update(relative_path=relative, reference_sha256=digest(value.encode()),
                   archive_status="included" if relative in selected else "full_archive_only" if relative in omitted else "unresolved_or_excluded_not_dereferenced")
    if release_gate(root, expected_freeze)[1] != release:
        raise Refusal("Terminal metadata changed during inventory")
    return {"schema_version": 3, "kind": FULL_KIND if mode == "archive" else LEAN_KIND,
            "expected_freeze_sha256": expected_freeze, "original_study_root": freeze["manifest"]["root"],
            "release": release, "files": selected, "omitted_full_archive_files": omitted,
            "complete_allowed_inventory_sha256": digest(encoded(all_files)), "excluded": excluded,
            "report_artifact_references": references, "external_pins_not_shipped": external,
            "max_git_bytes": max_git_bytes if mode == "git" else None,
            "privacy": "Only declared study namespaces; private paths never entered; filtered runtime schema only; finite credential/private-payload detectors, plus owner review required before distribution.",
            "limits": ["Full archive means all eligible formal evidence, not scratch or private/raw model streams",
                       "External dependency pins are metadata only; this is not a hermetic machine image",
                       "Git omissions retain exact byte digests and sizes, not a claim to have verified absent bytes",
                       "Unknown cache-write reporting, remote-compaction and failed-request costs remain unknown",
                       "Hashes bind bytes, not historical custody, correctness, privacy or reproducible wall time"]}


def check_plan(root, plan, expected_freeze=FROZEN_SHA256):
    if plan.get("kind") not in {FULL_KIND, LEAN_KIND} or plan.get("schema_version") != 3:
        raise Refusal("Unsupported evidence plan")
    if plan.get("expected_freeze_sha256") != expected_freeze:
        raise Refusal("Plan does not identify the required frozen v3 experiment")
    regenerated = make_plan(root, expected_freeze, mode="archive" if plan["kind"] == FULL_KIND else "git",
                            max_git_bytes=plan.get("max_git_bytes") or 25_000_000)
    if regenerated != plan:
        raise Refusal("Eligible inventory, frozen materials or terminal metadata changed after planning")


def package(root, plan_path, output, reviewed_plan_sha256, *, expected_freeze=FROZEN_SHA256):
    root, plan_path, output = Path(root).resolve(strict=True), Path(plan_path), Path(output)
    outside_study(output, root)
    if output.exists():
        raise Refusal("Use a new bundle directory; never overwrite evidence")
    if sha(plan_path) != reviewed_plan_sha256:
        raise Refusal("Reviewed plan digest differs")
    plan = loads(plan_path.read_bytes())
    check_plan(root, plan, expected_freeze)
    output.mkdir(parents=True)
    for relative, record in sorted(plan["files"].items()):
        src = local(root, relative)
        dst = output / "study" / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        with src.open("rb") as r, dst.open("xb") as w:
            shutil.copyfileobj(r, w, 1024 * 1024)
        dst.chmod(0o755 if record["executable"] else 0o644)
        if pin(output / "study", relative) != record:
            raise Refusal("Artifact changed during byte copy: " + relative)
    check_plan(root, plan, expected_freeze)
    write_new(output / "manifest.json", plan)
    write_new(output / "receipt.json", {"status": "byte_copy_complete", "manifest_sha256": sha(output / "manifest.json"),
        "file_count": len(plan["files"]), "bytes": sum(x["bytes"] for x in plan["files"].values()),
        "actual_model_or_native_execution": False})
    return verify_bundle(output, reviewed_plan_sha256, expected_freeze=expected_freeze)


def verify_bundle(bundle, expected_manifest_sha256, *, expected_freeze=FROZEN_SHA256):
    bundle = Path(bundle).resolve(strict=True)
    if {p.name for p in bundle.iterdir()} != {"manifest.json", "receipt.json", "study"}:
        raise Refusal("Bundle outer inventory mismatch")
    if any(p.is_symlink() for p in bundle.iterdir()) or not (bundle / "study").is_dir():
        raise Refusal("Invalid bundle root entry")
    if sha(local(bundle, "manifest.json")) != expected_manifest_sha256:
        raise Refusal("Manifest differs from independently supplied digest")
    plan = read(bundle, "manifest.json")
    if (plan.get("schema_version") != 3 or plan.get("kind") not in {FULL_KIND, LEAN_KIND}
            or plan.get("expected_freeze_sha256") != expected_freeze):
        raise Refusal("Unsupported bundle or wrong freeze")
    files, omitted = plan["files"], plan["omitted_full_archive_files"]
    if set(files) & set(omitted) or plan["kind"] == FULL_KIND and omitted:
        raise Refusal("Invalid present/omitted file inventory")
    expected_receipt = {"status": "byte_copy_complete", "manifest_sha256": expected_manifest_sha256,
                        "file_count": len(files), "bytes": sum(x["bytes"] for x in files.values()),
                        "actual_model_or_native_execution": False}
    if read(bundle, "receipt.json") != expected_receipt:
        raise Refusal("Bundle receipt is inconsistent")
    full_inventory = {**files, **{p: {k: v for k, v in row.items() if k != "reason"} for p, row in omitted.items()}}
    if digest(encoded(full_inventory)) != plan["complete_allowed_inventory_sha256"]:
        raise Refusal("Complete allowed inventory commitment differs")
    expected_dirs = set()
    for relative, record in full_inventory.items():
        if eligible_file(relative):
            raise Refusal("Ineligible manifest entry")
        if set(record) != {"sha256", "bytes", "executable"} or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"]):
            raise Refusal("Invalid file pin")
        if type(record["bytes"]) is not int or record["bytes"] < 0 or type(record["executable"]) is not bool:
            raise Refusal("Invalid file size/mode")
        if relative in files:
            expected_dirs.update(str(p) for p in PurePosixPath(relative).parents if str(p) != ".")
        if plan["kind"] == LEAN_KIND and bool(lean_exclusion(relative)) != (relative in omitted):
            raise Refusal("Lean subset does not follow declared omission policy")
    actual = set()
    for directory, dirs, names in os.walk(bundle / "study", followlinks=False):
        for name in dirs + names:
            path = Path(directory) / name
            relative = path.relative_to(bundle / "study").as_posix()
            if path.is_symlink():
                raise Refusal("Symlink in bundle")
            if name in dirs and relative not in expected_dirs:
                raise Refusal("Unexpected bundle directory; not traversed")
            if name in names and relative not in files:
                raise Refusal("Unexpected bundle file; not read")
        for name in names:
            path = Path(directory) / name
            relative = path.relative_to(bundle / "study").as_posix()
            if pin(bundle / "study", relative) != files[relative]:
                raise Refusal("Packaged file differs: " + relative)
            content_check(path, relative)
            if path.suffix == ".jsonl":
                trace_check(path)
            actual.add(relative)
    if actual != set(files):
        raise Refusal("Bundle file inventory differs")
    freeze, release = release_gate(bundle / "study", expected_freeze)
    if release != plan["release"] or freeze["manifest"]["root"] != plan["original_study_root"]:
        raise Refusal("Bundle terminal metadata differs")
    external = verify_frozen(bundle / "study", files, omitted, expected_freeze)
    if external != plan["external_pins_not_shipped"]:
        raise Refusal("External dependency pin inventory differs")
    return {"status": "verified_present_bytes", "kind": plan["kind"], "file_count": len(files),
            "omitted_file_count": len(omitted), "omitted_bytes_verified": False if omitted else None,
            "scientific_result_release": release["assessment_status"] == "complete", "assessment_status": release["assessment_status"],
            "freeze_sha256": expected_freeze, "manifest_sha256": expected_manifest_sha256,
            "native_environment_reproduced": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-measurements-finished", action="store_true", required=True,
                        help="Owner confirmation that every historical native measurement has ended")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--study-root", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--mode", choices=("archive", "git"), required=True)
    p.add_argument("--max-git-bytes", type=int, default=25_000_000)
    p = sub.add_parser("package")
    p.add_argument("--study-root", type=Path, required=True)
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--reviewed-plan-sha256", required=True)
    p = sub.add_parser("verify")
    p.add_argument("--bundle", type=Path, required=True)
    p.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args()
    try:
        if args.command == "plan":
            outside_study(args.out, args.study_root)
            if args.max_git_bytes < 1:
                raise Refusal("Positive Git byte budget required")
            plan = make_plan(args.study_root, mode=args.mode, max_git_bytes=args.max_git_bytes)
            write_new(args.out, plan)
            result = {"status": "plan_ready_for_owner_review", "plan_sha256": sha(args.out),
                      "files": len(plan["files"]), "bytes": sum(x["bytes"] for x in plan["files"].values())}
        elif args.command == "package":
            result = package(args.study_root, args.plan, args.out, args.reviewed_plan_sha256)
        else:
            result = verify_bundle(args.bundle, args.manifest_sha256)
        print(json.dumps(result, indent=2))
    except (Refusal, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "refused", "reason": str(exc)}), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
