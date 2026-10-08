# Offline reproduction

Use Python 3.12 (verified here with 3.12.14). From the repository root:

```sh
python3 scripts/verify_repository.py
EVIDENCE_ARCHIVE=/absolute/path/v3-lean-evidence.tar.gz bash scripts/reproduce.sh
```

The archive is NOT included in Git; no external deposit is published yet. Obtain
the separately retained archive before the second command. This verifies exact
repository hashes, safely extracts the pinned lean archive into
`.reproduction/`, verifies all present evidence bytes and replays numerical results.
It invokes no inference, native benchmark, campaign launcher or network request.
The 18 integrity tests and 29 figure tests can be run separately:

```sh
cd experiments/unattended-optimization-v3
python3 -B -m unittest discover -s analysis/reproduction -p 'test_*.py' -v
python3 -B -m unittest discover -s analysis/figures -p 'test_*.py' -v
```

The frozen execution modules also retain their original tests under `tests/`.
Those broader tests are not equivalent to the offline reproduction suite, and
are not claimed to have been rerun for this repository import.

See the study's `analysis/figures/README.md` for extraction/plotting. Point the
extractor at `.reproduction/v3-lean-evidence/study` using `--study-root`, and write
fresh output directories. Matplotlib and NumPy are needed for plotting. Figure
extraction verifies source bindings; it does not remeasure timings.

Paper builds require Typst 0.15.1, charged-ieee 0.1.4 and the bundled fonts:

```sh
typst compile --font-path docs/ai-development-workflow/fonts docs/ai-development-workflow/main.typ /tmp/main.pdf
typst compile --font-path docs/ai-development-workflow/fonts docs/ai-development-workflow/extended-methods.typ /tmp/supplement.pdf
```

See `docs/ai-development-workflow/REPRODUCE.md` for historical build receipts.
Replace machine-local tool/cache paths only; never rewrite archived evidence.
The main paper is 7 pages; the supplement 10 pages. Existing bundled fonts retain
their original license notice; that notice does not license the study itself.

## Lightweight arithmetic and plotting from this checkout

Run `python3 -B scripts/reproduce_arithmetic.py` to verify the 156 raw input pins
and reproduce all 52 portfolio/family/bootstrap calculations using Python only.
This is arithmetic verification, not full source/build/attempt provenance audit.

### Plotting

The committed data subset can render all 17 figures without the external archive.
It retains plotting rows unchanged and records curation/coverage limits. Install
Matplotlib and NumPy in your own environment, then choose a NEW output directory:

```sh
python3 -B experiments/unattended-optimization-v3/analysis/figures/plot.py --data data/plot-data.json --out experiments/unattended-optimization-v3/analysis/figures/local-render
```

This re-renders recorded data; it does not verify all original command/source
receipts, regenerate raw measurements, or run a new campaign.
