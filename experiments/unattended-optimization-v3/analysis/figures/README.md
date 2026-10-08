# V3 evidence and single-column figures

The checkout retains 11 original CSV tables in `measured-data-01/` and all 17
paper PDF assets in repository-root `paper/figures/`. The full original
`figure-data.json`, `raw_pairs.csv` and `measured-assets-01/` are historical derived
outputs not included here and not assumed to be in the lean archive. Four selected
QA receipts are retained in `qa-01/`: tests, visual QA, numeric verification and
font/geometry metrics. Repository-root `data/plot-data.json` provides curated plotting rows;
`data/raw-arithmetic/` provides 156 byte-pinned inputs for 52 comparisons.
Use the [root reproduction guide](../../../../REPRODUCE.md) for current commands,
requirements and availability limits. No benchmark or model call is involved.

`extract.py` adapts the earlier generic extraction code. `plot.py` adapts the
accepted single-column visual system in the separate v3 design-preview source.
No earlier results, preview plots, or synthetic values belong in this directory's
measured outputs. There is no synthetic rendering switch or old-data default.

## Evidence boundaries

- Default input is this v3 experiment. Reads are limited to authority JSON,
  development operation result/sample JSON, terminal telemetry, the public launch
  status/freeze, and released final assessment result JSON. Source snapshots, participant
  message streams, hidden fixture inputs, and credentials are never opened
- All three original campaign identities must be measured, terminal, and sealed
  before scientific extraction. Missing campaigns remain in a three-row pending
  status table; setup/preflight cannot enter the measured denominator
- Held-out files cannot be opened through `Reader` until all three seals exist and
  `state/launch/status.json` says `status=complete` and
  `assessment_status=complete`. No override flag bypasses this boundary
- Authority state and event chains, anchored development results, raw paired
  times, final file manifests, seed/source hashes, and recorded estimators are
  checked. The extractor does not rerun benchmarks or resample a bootstrap
- Every v3 measurement-attempt chain retains its immutable source, build/reference,
  configuration, prior-attempt lineage, and infrastructure retry attestation.
  The first valid attempt is selected regardless of score. Later official
  review-plan measurements and invalid attempts remain process records with null
  scored values. Invalid raw timing files are not opened for scoring
- Development trajectories are direct comparisons to the original seed.
  Multiplication of selected promotion gains is never used. Missing trajectory
  observations remain rows and visible gaps
- Checkpoint usage is read from the canonical
  `authority/checkpoint-usage/NNNNNNNN.json` artifact and verified against its
  authority-bound SHA. Raw checkpoints are written by `Host.export()` and do not
  contain the runner-only `runtime_source` field. They are authenticated against
  canonical terminal telemetry through the host start time, campaign artifact
  roots, and matching agent/thread/role/model/effort identities. Neither raw nor
  terminal exports contain `campaign_id`; no such field is invented or required.
  Later agent admissions and pending thread-start identities are allowed. The
  checkpoint and terminal source paths/hashes and observed subtotal are retained.
  Missing terminal identity evidence keeps checkpoint usage unscored and unknown.
  `usage_coordinate_complete=false` keeps exact token/cost coordinates null;
  snapshots or later receipts are never interpolated into an exact checkpoint
- Final endpoints retain the complete three-campaign by two-stratum denominator.
  Identity, measurement failure, validation failure, and missing observations are
  distinct states. Identity at 1 is explicitly unmeasured
- Accounting counts each unique thread once. Cached input and reasoning output
  remain subsets. Missing usage is unknown, not zero. Frozen broad price bounds
  remain alongside an optional reconciled response-band reanalysis. An incomplete
  ledger uses observed broad bounds; no unpinned interrupted-analysis helper is
  executed. Cost intervals are hypothetical Standard API-equivalent subtotals,
  never complete-run bounds or actual charges

In the separately retained full extraction, `figure-data.json` and each CSV retain evidence hashes. `operations.csv`,
`process_events.csv`, and `final_attempts.csv` preserve failures and retries.
The historical full extraction’s `raw_pairs.csv` retains every selected temporal pair; `families.csv` retains the
frozen median-log family estimator. Read the bundle's notes and accounting
coverage fields before interpreting any totals.

## Reproduction

Current checkout-only tests and plot regeneration, plus optional archive extraction,
are documented once in the [root reproduction guide](../../../../REPRODUCE.md).
Never use the already populated `measured-data-01/` as an output directory.

The focused tests use temporary synthetic inputs only to test boundaries and
arithmetic; they do not produce measured outputs or render any plots. Extraction
uses the standard library plus the experiment's pure pricing helpers. Plotting
requires Matplotlib and NumPy. Outputs must be a new, empty directory beneath
`analysis/figures`; existing evidence is never overwritten. Portable archives can
use `--study-root` with their local copy, preserving canonical relative paths and
hashes. An absent completion receipt withholds final reads and rendering even if
an assessment directory happens to exist. A blocked assessment must be reported
as blocked; do not forge a complete receipt to render partial held-out results.

`fixtures/host-export-checkpoint.json` is an explicitly synthetic, focused writer
shape fixture. It mirrors the raw frozen `Host.export()` top-level fields and
the token/identity fields under test, with a valid cumulative notification; it
contains no measured results and deliberately omits terminal-only labels. The
terminal test counterpart adds those labels only as the runner does.

## Archive relocation contract

The only historical origin is `state/freeze.json` → `manifest.root`, authenticated
against the exact v3 freeze SHA-256
`a28a9e9984aa03a1a28c950bfd846e0d179202f719a43982a27c72a69c934178`.
There is no CLI origin or freeze override. Test-only readers use a separately
specified fixture digest without changing the production CLI contract.

Use the reproduction bundle verifier before extracting from an archive, then
pass its local `study` directory with `--study-root`. The figure reader translates
historical absolute names **lexically** into canonical relative paths under that
local study root. It never resolves or opens the original host's absolute paths.
Development-head keys must exactly equal the authenticated original root plus
the canonical campaign development path. Checkpoint pointers must map to their
exact campaign/ordinal artifact, and their local bytes must match the anchored
SHA. Checkpoint and terminal artifact-root metadata use the same mapping.

Only the original frozen root is translated. Similar suffixes under any other
root, `//`, `/./`, `/../`, backslashes, private path components, paths outside the
freeze root, and local paths outside the existing reader allowlist are rejected.
No measured JSON, absolute pointer, raw sample, or recorded digest is rewritten.
The extracted bundle records both roots and the freeze digest. This adapter
verifies figure inputs and their bindings; the separate reproduction verifier
remains responsible for validating the complete archive inventory.

Before executing any pricing code, the extractor authenticates that exact
freeze. It reads `runtime/pricing.py` once, verifies those bytes against
`freeze.manifest.files["runtime/pricing.py"]`, and only then compiles those verified
bytes. Every path component is checked for symlinks, including within-root links
and an aliased selected study root. The JSON reader also rejects duplicate keys,
nonfinite constants, and numbers that overflow to infinity.

Optional response-band analysis uses only the fixed helper next to this
extractor's source tree, `analysis/reprice_observed_usage.py`, pinned to SHA-256
`0feb711675481377a2e994fe84b2c955bc44b93aa37979aa1199722ec1301da9`.
It never executes an optional helper chosen from `--study-root`. An absent helper
falls back to frozen broad bounds; a changed hash or symlink is refused. The
helper's telemetry read must match the evidence reader's byte digest. The focused
trust tests use temporary sentinel code to verify refusal before execution and
that an evidence-root helper is ignored; see `execution-trust-verification.json`.

## Publication placement and QA

Every asset is authored at exactly **3.3 inches** wide with 8–8.5 point labels,
thin axes, sparse grids, and restrained blue/gray. There are no plot titles or
subtitles. Dynamic axis limits replace the old preview's study-specific ranges.
Token and cost ranges are shared across the three campaign panels; family
matrices share one log scale across the two strata.

Main figure choices are the compact workflow, development trajectory, six-cell
endpoint display, and individual campaign resource panels. Family matrices and
raw paired-block panels may be supplementary. Every figure, including every
supplement, remains one column wide. Do not combine the assets into a page-wide
dashboard or shrink them below their authored width.

Generated `captions.txt` supplies concise captions; move long caveats into nearby methods
prose. Preserve normal two-column text flow. No manuscript source is changed by
these scripts. Explain any † incomplete campaign marker, * accounting gap,
identity diamond, or × missing measurement at its first appearance.

The exporter checks the exact width, minimum 8-point type, and every visible text
bounding box. It records source/data digests, dimensions, font sizes, captions,
Matplotlib version, and each output digest. Those checks do not replace visual QA:
inspect every SVG/PNG and the compiled manuscript pages at final 3.3-inch size.
Verify long family/role labels, extreme result ranges, missing values, legend
placement, and caption/prose flow before sharing actual figures. Historical actual-figure visual QA was completed; a new render requires its own QA.
