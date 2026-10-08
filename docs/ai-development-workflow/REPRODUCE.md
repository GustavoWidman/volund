# Reproducing the manuscript

The manuscript uses Typst 0.15.1, `@preview/charged-ieee:0.1.4`, and bundled TeX Gyre fonts. From the repository root, with Typst installed and the package available in the standard Typst package cache:

```sh
typst compile --font-path docs/ai-development-workflow/fonts docs/ai-development-workflow/main.typ docs/ai-development-workflow/ai-development-workflow-draft.pdf
typst compile --font-path docs/ai-development-workflow/fonts docs/ai-development-workflow/extended-methods.typ docs/ai-development-workflow/ai-development-workflow-supplement.pdf
mkdir -p preview
pdftoppm -r 120 -png docs/ai-development-workflow/ai-development-workflow-draft.pdf preview/main-page
pdftoppm -r 110 -png docs/ai-development-workflow/ai-development-workflow-supplement.pdf preview/supplement-page
```

`TYPST_PACKAGE_CACHE_PATH` or local tool paths may be adjusted for the build environment. The editable scientific text remains in the two `.typ` files. Main figure copies originate from `experiments/unattended-optimization-v3/analysis/figures/measured-assets-01`; their generation sources, extracted data, manifests, and QA are in the sibling analysis directories. The October 8 revision does not change the figure data or assets.

Offline evidence reproduction is documented at `experiments/unattended-optimization-v3/analysis/reproduction/README.md`. It can inspect retained bytes and recompute arithmetic without native remeasurement or model calls. The manuscript-source package alone is not the complete experimental evidence bundle. Keep the original final report and freeze bytes unchanged. A native rerun, if separately authorized in a fresh environment, is a new replication, never a replacement score for the first valid final assessment.

The claim/source ledger maps each reported result to its authoritative artifact. The supplement documents source/inventory digest distinctions, paired estimator, time origins, resource coverage and remaining model/host reproduction limits. Rendering verifies presentation and cannot substitute for scientific or author review.
