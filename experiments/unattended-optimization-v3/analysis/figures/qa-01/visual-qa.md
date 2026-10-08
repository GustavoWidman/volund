# Actual v3 figure QA

Status: complete for all 17 actual figure assets; manuscript page QA remains with the manuscript owner.

- Every actual PNG was inspected: workflow, development, endpoints, 2 family matrices, 6 role panels, and 6 paired-block panels
- Every PDF and SVG is exactly 3.3 inches wide; independent vector text extraction confirms 8 point minimum text
- Main figures are 3.3×1.8 inches (workflow), 3.3×2.2 inches (development), and 3.3×2.15 inches (endpoints)
- No internal titles, oversized dashboard, clipped labels, or overlapping text
- All eight direct seed checkpoint comparisons and six final endpoint comparisons match the authenticated bundle
- Lower stems are nominal one-sided 90% lower bounds; family-pair spread is descriptive, not a confidence interval
- C1 shift sparse_narrow=0.9113552309891593 displays as 0.91 with an outline marking regression
- Exact checkpoint resource coordinates remain null; observed accounting figures do not imply complete-run token or billing coverage

## Analysis-only fixes discovered in actual rendering

The clipping check initially included off-axis locator Text objects that Matplotlib does not draw. It now excludes only non-rendered tick labels outside each axis view interval. The family parser now recognizes frozen v2-{stratum}-{family} fixture names, preventing false duplicate family rows. Per-panel campaign labels were removed from role figures; campaign identity is in the caption, eliminating unnecessary internal titles. Development bottom whitespace was compacted when no missing observation markers are required. The one true family regression receives an outline. No source measurements or frozen experiment code were changed.

The failed/incomplete render attempts remain in render-attempt-01-partial and render-attempt-02-partial. The first complete rendering before final compacting/regression emphasis remains in render-attempt-03-pre-qa. Use only measured-assets-01 for the manuscript. Contact sheets here are diagnostic only and are not publication figures.

## Verification records

- tests.log: all 29 figure tests pass
- vector-font-metrics.json: independent PDF/SVG/PNG geometry, fonts, and product SHA verification
- numeric-verification.json: selected numerical equality checks and denominator/process counts
- ../measured-assets-01/render-manifest.json: final source/data/product digests and captions
