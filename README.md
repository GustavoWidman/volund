# Volund

An empirical study of unattended multiagent program optimization: three completed
campaigns on one synthetic C++20 event range-statistics task. The primary transfer
portfolio speedups are 2.240×, 4.547× and 5.445× over the original seed.

Code and supporting evidence will be made publicly available upon publication at
https://github.com/GustavoWidman/volund. This repository is currently private for
validation; no public archive deposit, publication or open-source license is
implied.

## Start here

- [Main paper](paper/volund.pdf) and [supplement](paper/supplement.pdf)
- [Reproduce and verify](REPRODUCE.md)
- [Claim/source index](paper/SOURCE-LEDGER.md)
- [Scientific protocol](experiments/unattended-optimization-v3/protocol/PROTOCOL.md)
- [Evidence availability and exact pins](audit/evidence-availability.json)
- [Import provenance](audit/import-provenance.json) and [cleanup provenance](audit/cleanup-provenance.json)

## Organization and reproduction

- `paper/`: manuscript sources, PDFs, bibliography, fonts, figures and source index
- `experiments/unattended-optimization-v3/`: frozen source-relative protocols,
  controller/runtime, tests, analysis, selected tables and scientific review records
- `data/`: 156 pinned raw-arithmetic inputs for all 52 comparisons and curated plot data
- `scripts/`: offline verification and arithmetic entry points
- `audit/`: provenance, availability, current-tree manifest and verification receipts

This checkout supports all 52 paired arithmetic comparisons, 17-figure regeneration,
18 reproduction tests, 29 figure tests and manuscript builds. Full source/build,
attempt and command provenance verification requires the separately retained
immutable lean archive: 61,087 evidence files plus a declaration of 21,571 full-only
omissions. Absent bytes cannot be reverified here. See [REPRODUCE.md](REPRODUCE.md)
for exact commands, dependencies and distinctions.

## Interpretation limits

Three adaptive campaigns on one synthetic task provide descriptive endpoint
results, not evidence of general superiority or confirmatory campaign-wide effects.
There is no matched comparator. C1's shifted sparse family regressed (0.911×
speedup). Failures, invalid attempts and first-valid retry rules remain part of
the scientific record. Observed model usage is incomplete: remote compaction,
failed-request costs, cache-write reporting and actual billing remain unknown;
no whole-run cost bound or actual-bill claim follows.

Native dependencies are pinned metadata, not a hermetic environment. Offline
arithmetic and plot replay do not constitute new native measurements or campaign
replication. The manuscript-only revision tightened the six-page main paper and
corrected bibliography metadata; frozen execution source and measured evidence
are unchanged. See the [current manuscript verification](audit/manuscript-verification.json).

## Historical records

[Cleanup provenance](audit/cleanup-provenance.json) links the pre-cleanup commit and
hashes of the earlier manuscript and superseded notes removed from the current
tree. Original scientific reviews, failed-attempt/post-hoc records, frozen runtime
documents and release/build receipts retain their historical scope, wording and
paths. Use [REPRODUCE.md](REPRODUCE.md) for current checkout instructions.
