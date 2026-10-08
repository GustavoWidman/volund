# Volund

An empirical study of unattended multiagent program optimization.

The evidence and reproduction materials will be made publicly available upon
publication at https://github.com/GustavoWidman/volund. The repository is temporarily
private for validation; this statement does not claim current public access.

Study-only research repository. Imported from canonical source commit
`23cfd8448d819c8e9a245e9afef5869791abc484` on 2026-10-08 with a new, honest Git history.
No open-source license or public release is granted by this repository.

## Start here

- [Main paper](docs/ai-development-workflow/ai-development-workflow-draft.pdf) and [supplement](docs/ai-development-workflow/ai-development-workflow-supplement.pdf)
- [Reproduce and verify](REPRODUCE.md)
- [Claim/source ledger](docs/ai-development-workflow/SOURCE-LEDGER.md)
- [Scientific protocol](experiments/unattended-optimization-v3/protocol/PROTOCOL.md)
- [Import provenance and exclusions](audit/import-provenance.json)
- [Evidence release](experiments/unattended-optimization-v3/release/DELIVERY-README.md)

## Organization

`experiments/unattended-optimization-v3/` preserves source-relative paths needed by
frozen protocols, harness/runtime, source tests, task contract/seed, analysis and
figure generation. Selected small tables and scientific audit records are browsable.
`docs/ai-development-workflow/` contains the paper, supplement, bibliography,
fonts, figures and audit mapping. `audit/` records this import and performed checks.
`scripts/` provides safe offline verification entry points.

Bulk raw evidence is deliberately excluded from Git. A separate immutable lean
archive contains 61,087 evidence files; its manifest also declares 21,571 full-only
omissions. No release or external archive deposit is published yet. See
[audit/evidence-availability.json](audit/evidence-availability.json) for exact pins.
Full numerical replay requires that separately supplied archive. Source-only tests
and repository integrity checks work from this checkout alone. Public archive
hosting and final publication packaging remain pending.

## Interpretation limits

Three adaptive campaigns on one synthetic task give descriptive endpoint results,
not evidence of general superiority or confirmatory campaign-wide effects. The C1
shifted sparse family regressed (0.911× speedup). Failures, invalid attempts and
first-valid retry rules remain in the evidence. Observed model usage is incomplete:
remote compaction, failed-request costs, cache-write reporting and actual billing
remain unknown. No whole-run cost bound or actual-bill claim follows.

The full archive is not included here; its hashes and retrieval/reassembly records
are preserved. Absent bytes cannot be reverified. Native dependencies are pinned
metadata, not a hermetic environment. Offline arithmetic replay is not a fresh
native benchmark, campaign replication or model rerun. No paid inference, campaign
rerun or endpoint reselection was performed during this import.

Original files are identified in the import manifest. The revised paper is a
2026-10-08 derivative, not a silently replaced historical experiment record.
