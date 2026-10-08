# V3 reproducibility and evidence packaging

For current checkout commands, use [the root reproduction guide](../../../../REPRODUCE.md). This document describes the optional separately supplied archive and its historical scientific verification contract; placeholder commands below require that archive.

These owner-side tools are outside the immutable execution freeze. All historical
native measurement finished on 2026-10-02. The source-only regression suite and
an initial actual-data numerical audit passed after that release; final bundle
receipts are separate deliverables, not claims established by this README.

The required freeze is
`a28a9e9984aa03a1a28c950bfd846e0d179202f719a43982a27c72a69c934178`.
The canonical terminal final report is
`4c0da852efa41ae3440c09a9faf2e6de0797ac1036ebbbdfc052b4f658f66227`.
Production commands have no freeze override. Fixture-only tests use synthetic
identities. No old campaign outcomes or candidate data were imported; inherited
`v2-` fixture names are the actual files pinned by the V3 freeze.

## Verify and replay a delivered bundle

Use Python 3.12 and retain the independently delivered manifest hash. Substitute
`BUNDLE`, `MANIFEST_SHA`, and `OUTPUT` with the received directory, hash, and a new
output path outside that directory. Neither command invokes native/model work.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 BUNDLE/study/analysis/reproduction/evidence.py \
  --native-measurements-finished verify --bundle BUNDLE \
  --manifest-sha256 MANIFEST_SHA
PYTHONDONTWRITEBYTECODE=1 python3 BUNDLE/study/analysis/reproduction/replay_numeric.py \
  --native-measurements-finished --bundle BUNDLE \
  --manifest-sha256 MANIFEST_SHA --out OUTPUT
```

For either the full or lean bundle, this checks exact present-file bytes and
executable bits, the freeze, terminal launcher and endpoint seals, and the one
canonical final report. Numerical replay independently checks:

- Owner/development hash chains, formal source snapshots, operation inventories,
  source/build/reference/configuration bindings, and endpoint validation gates
- Every immutable retry lineage and official first-valid observation; invalid
  or failed attempts remain evidence but never become estimates
- Six-family raw pairs, balanced temporal schedules, calibration, per-sample
  command/measurement receipts, fixture-manifest pins, repetitions, verified
  calls, RSS, target flags, and separate bootstrap artifacts
- Equal-family median-log point estimates and the one-sided 90% lower bound from
  10,000 joint temporal-block bootstrap resamples
- Anchored checkpoint ledgers and observed cumulative token accounting without
  double-counting cached/reasoning subsets or filling unknown costs with zero

The full and lean numerical reports must have identical `workflows`,
`comparisons`, `final`, and `usage`. Manifest/byte-verification coverage differs.

## Source-only tests

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s analysis/reproduction -p 'test_*.py' -v
```

The 18 tests use tiny synthetic data and cover tampering, strict paths, private
streams, blocked final records, contradictory sample receipts, retry boundaries,
nonconstant joint-block resampling, and unknown usage. They do not execute native
workloads or import study execution modules. See `SOURCE-CHECK.json` for source
pins and the dated static-review record for the pre-release review.

## Full archive and lean transport

The full archive retains every eligible frozen/source file and formal operation
artifact, including failed attempts, setup/readiness revisions, profile outputs,
filtered ordinary runtime reports/tool outputs, usage records, and final evidence.
The lean subset retains all numerical/source/receipt evidence used by replay;
binaries, binary fixtures, raw profiles, repeated native stdout, and full filtered
runtime streams remain in the separate full archive. Every omitted file keeps
its exact SHA-256, size, executable bit, and reason. Both manifests commit to the
same complete allowed inventory. Absent bytes are never claimed as reverified.

The original 25,000,000-byte *unpacked* lean default is intentionally fail-closed.
Actual receipt-rich evidence exceeds it. This release uses an explicitly approved
350,000,000-byte unpacked planning ceiling outside Git and a separate unchanged
25,000,000-byte ceiling for the compressed Git transport. Check the delivered
size report; a compressed file over that ceiling must not be staged silently.
The full archive has its own separately preserved destination.

From the original study root, write plans and bundles outside the study:

```sh
python3 analysis/reproduction/evidence.py --native-measurements-finished plan \
  --study-root . --mode archive --out /new/path/archive-plan.json
python3 analysis/reproduction/evidence.py --native-measurements-finished plan \
  --study-root . --mode git --max-git-bytes 350000000 \
  --out /new/path/lean-plan.json
python3 analysis/reproduction/evidence.py --native-measurements-finished package \
  --study-root . --plan /new/path/PLAN.json \
  --reviewed-plan-sha256 REVIEWED_PLAN_SHA --out /new/path/BUNDLE
```

Review concrete plans before packaging. Compress only after manifest verification
and both numerical replays pass. The transport hash identifies the compressed
file; the internal manifest independently identifies evidence. This tool does
not upload, commit, stage, publish, or push anything.

## Privacy and portability limits

Only the frozen `manifest.root` authenticates original absolute paths. Rebasing
maps canonical within-root suffixes without opening old host paths or rewriting
any archived bytes. Reject traversal, symlinks, control characters, ambiguous
JSON, private names, and malformed runtime schemas. External public tool paths,
including package-managed binaries, are metadata only and are never traversed.
The package does not include credentials, authentication/session directories,
private reasoning, raw provider streams, participant scratch, or unrelated repos.
Finite secret/private-payload scans cannot prove arbitrary prose safe; review the
concrete report before distribution. Ordinary report references are inert; all
unresolved/excluded references stay recorded without being opened.

`analysis/manuscript-draft` refers to historical preparation in the separately
retained evidence; it is absent from this checkout. The current paper is
maintained in repository-root `paper/`. Nested figure outputs and generated manuscript files are separate
derived deliverables, outside the evidence inventory.

These tools use the Python standard library. The release records the actual
Python version and source hashes and checks primary Python documentation.
External compiler, profiler, interpreter, and runtime pins are provenance, not
shipped dependencies: this is not a hermetic machine image. Random-library
version changes can affect replay, so preserve the recorded Python version.
Bootstrap bounds describe selected comparisons; they are not confirmatory
campaign-wide evidence. Missing cache-write reporting, failed-request costs,
remote compaction, actual billing tier, and whole-run bills remain unknown.

`remap_native_config.py` and `native_replay.py` document an optional later native
rebuild in a prepared environment, requiring explicit mappings and two CPU IDs.
That opt-in was not used for this release. It must keep source/fixture pins exact,
label new timings posthoc, preserve archived bytes, and never invoke the canonical
evaluator, reopen assessment, launch models, or reselect endpoints.
