# Reproduce and build Volund

Run from the repository root. Python 3.12 (verified with 3.12.14) is required;
plotting additionally uses Matplotlib and NumPy. These commands are offline:
no inference, native timing, campaign execution or endpoint reselection occurs.

## Checks available from this checkout

```sh
python3 -B scripts/verify_repository.py
python3 -B scripts/reproduce_arithmetic.py
(
  cd experiments/unattended-optimization-v3
  python3 -B -m unittest discover -s analysis/reproduction -p 'test_*.py' -v
  python3 -B -m unittest discover -s analysis/figures -p 'test_*.py' -v
)
```

Expected: repository inventory/hashes/modes, 156 raw input pins and all 52
portfolio/family/bootstrap comparisons, 18 reproduction tests and 29 figure tests.
The 52-comparison replay verifies arithmetic, not all original source/build,
attempt, command or model provenance. The broader frozen execution tests under
`experiments/unattended-optimization-v3/tests/` are retained historical suites;
these commands do not run them or replicate the native environment.

## Regenerate all 17 figures

The committed `data/plot-data.json` contains all rows consumed by the plotter.
The 11 retained original CSVs are under
`experiments/unattended-optimization-v3/analysis/figures/measured-data-01/`.
That directory is input evidence, never an output target. Choose a NEW, empty
output directory under the figure source directory; this example refuses reuse:

```sh
FIGURE_OUT=experiments/unattended-optimization-v3/analysis/figures/local-render
test ! -e "$FIGURE_OUT"
python3 -B experiments/unattended-optimization-v3/analysis/figures/plot.py \
  --data data/plot-data.json --out "$FIGURE_OUT"
```

The output contains 17 figures in PDF/PNG/SVG plus captions and manifest. Original
paper PDF copies are in `paper/figures/`. Rendering recorded data does not verify
absent command/source receipts or regenerate measurements. The full extraction's
`figure-data.json`, `raw_pairs.csv` and `measured-assets-01/` are historical derived
outputs not included in this checkout; they are not assumed to be inside the lean
archive. Four selected QA receipts remain in
`experiments/unattended-optimization-v3/analysis/figures/qa-01/` (tests, visual QA,
numeric verification and font/geometry metrics). See [figure contracts](experiments/unattended-optimization-v3/analysis/figures/README.md).

## Build and render the paper

Use Typst 0.15.1, `@preview/charged-ieee:0.1.4`, and the bundled fonts.
Page rendering also requires Poppler (`pdftoppm`). The package
must already be in the standard Typst cache (or supplied via
`TYPST_PACKAGE_CACHE_PATH`) for an offline build. Use an untracked output folder:

```sh
mkdir -p .reproduction/paper
typst compile --font-path paper/fonts paper/main.typ .reproduction/paper/volund.pdf
typst compile --font-path paper/fonts paper/extended-methods.typ .reproduction/paper/supplement.pdf
pdftoppm -r 120 -png .reproduction/paper/volund.pdf .reproduction/paper/volund-page
pdftoppm -r 110 -png .reproduction/paper/supplement.pdf .reproduction/paper/supplement-page
```

Expected: seven main-paper pages and ten supplement pages. Inspect all rendered
pages for clipping, overlap, broken references and readable figures. The checked-in
PDFs are `paper/volund.pdf` and `paper/supplement.pdf`. The bundled GUST font license
licenses the fonts only, not the study. [Claim/source index](paper/SOURCE-LEDGER.md)
and [historical provenance](audit/cleanup-provenance.json) distinguish current
packaging from original scientific and manuscript-build receipts.

## Optional complete evidence verification

The immutable lean archive is NOT included in Git and no external deposit is
published yet. The following command is only runnable after separately obtaining
that exact archive. It refuses to reuse `.reproduction/`; use a separate clean
checkout from the paper-build example above. Replace the example absolute path:

```sh
EVIDENCE_ARCHIVE=/absolute/path/v3-lean-evidence.tar.gz bash scripts/reproduce.sh
```

This authenticates archive SHA-256
`3b53371632c8010336be846232f0a73090baa8700fb6ab5ade9fa15ddfef5dae`, safely extracts
to `.reproduction/v3-lean-evidence/`, verifies the exact 61,087 present files and
replays source-bound numerical results. The 21,571 declared full-only omissions
cannot be byte-verified from the lean archive. The current cleanup does not
claim to rerun this unavailable-archive verification.

After successful verification, optional full figure extraction uses that
archive's study root and NEW output directories, not the committed CSV directory:

```sh
python3 -B experiments/unattended-optimization-v3/analysis/figures/extract.py \
  --study-root .reproduction/v3-lean-evidence/study \
  --out experiments/unattended-optimization-v3/analysis/figures/local-extraction
python3 -B experiments/unattended-optimization-v3/analysis/figures/plot.py \
  --data experiments/unattended-optimization-v3/analysis/figures/local-extraction/figure-data.json \
  --out experiments/unattended-optimization-v3/analysis/figures/local-archive-render
```

The extractor checks archived completion receipts and source bindings before
reading held-out results. `state/launch/status.json`, campaign authority records,
and the complete final report are archive-only. Never fabricate absent receipts,
rewrite measured paths/hashes, or treat this partial checkout as a complete live
study deployment. Details: [archive verification contract](experiments/unattended-optimization-v3/analysis/reproduction/README.md)
and [evidence availability](audit/evidence-availability.json).
