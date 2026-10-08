> Repository packaging note (2026-10-08): the archives described below are retained separately, not included in this Git repository. No external deposit is published yet. The historical release receipt below is preserved as provenance; its local delivery commands require the separately supplied archive.

# V3 verified evidence release

Both bundles pass exact manifests and independent raw-pair numerical replay: 52
comparisons, 357 campaign operations, 22 final operations, and eight checkpoint
ledgers. The full and lean scientific outputs are identical. Eighteen synthetic
integrity tests pass. No native/model work or endpoint reselection was performed.

| Delivery | Compressed bytes | Unpacked file bytes | Evidence files |
|---|---:|---:|---:|
| Full archive | 69,265,218 | 455,275,286 | 82,658 |
| Lean Git transport | 22,327,392 | 353,883,442 | 61,087 |

The lean transport is below the 25,000,000-byte Git ceiling. Its selected
evidence is 332,880,312 bytes; complete manifest and receipt add 21,003,130 bytes.
The separately approved 350 MB planning ceiling counts selected evidence, not
manifest overhead. Nothing has been staged, uploaded, committed or pushed.

## Exact identities

- Full tar.gz: `2561ed87f5fa3988b3817e9e939fed49b2d37f097a0bfeec5c34a94ab8962e87`
- Lean tar.gz: `3b53371632c8010336be846232f0a73090baa8700fb6ab5ade9fa15ddfef5dae`
- Full internal manifest: `f8b5013ee087ac80e35d669c0155bac468cc05a40ff20f2a175838c90ae1ef0f`
- Lean internal manifest: `2a8127785f5d5e2f2c42e8d1cf8061da344b174db7014907145bccc902f290aa`
- Shared complete inventory: `7398101410c730075d9555fbeee99858bd16c9ba7332e03ccb7f98f69c724fca`
- Freeze: `a28a9e9984aa03a1a28c950bfd846e0d179202f719a43982a27c72a69c934178`
- Canonical final report: `4c0da852efa41ae3440c09a9faf2e6de0797ac1036ebbbdfc052b4f658f66227`

## Verify and reproduce

Use a new directory and Python 3.12 (the release used 3.12.14). The internal
manifest is included inside each transport; a separate copy is also supplied.

```sh
sha256sum v3-lean-evidence.tar.gz
tar -xzf v3-lean-evidence.tar.gz
PYTHONDONTWRITEBYTECODE=1 python3 v3-lean-evidence/study/analysis/reproduction/evidence.py \
  --native-measurements-finished verify --bundle v3-lean-evidence \
  --manifest-sha256 2a8127785f5d5e2f2c42e8d1cf8061da344b174db7014907145bccc902f290aa
PYTHONDONTWRITEBYTECODE=1 python3 v3-lean-evidence/study/analysis/reproduction/replay_numeric.py \
  --native-measurements-finished --bundle v3-lean-evidence \
  --manifest-sha256 2a8127785f5d5e2f2c42e8d1cf8061da344b174db7014907145bccc902f290aa \
  --out reproduced-numerics.json
```

For the full archive substitute its filename, directory and manifest hash.
The complete source README inside each archive explains checks and source-only
tests. Compare numerical report fields `workflows`, `comparisons`, `final`, and
`usage`; byte-verification coverage intentionally differs. `SHA256SUMS` covers
the delivered transports, plans, verification reports, numerical reports and
review artifacts.

## Boundaries

Archives contain only declared V3 formal evidence and sources, including all
retained attempts and allowed filtered ordinary reports. Full-only omissions have
exact hashes, sizes, executable flags and reasons in the lean manifest. No auth,
session, private reasoning, raw provider streams, participant scratch or unrelated
repositories were traversed/copied. A finite privacy scan cannot prove arbitrary
prose safe; see the independent release review and inventory report.

Original absolute paths are unchanged in immutable files. Both relocated replays
passed under a Python file-open guard rejecting resolved original-study paths.
This is not OS isolation. External native dependencies are pinned metadata, not a
hermetic environment; native timing reproducibility is untested here. Observed
usage arithmetic is reproduced, but provider billing, cache-write verification,
failed-request cost and remote-compaction cost remain incomplete. Bootstrap
bounds are descriptive after adaptive selection.

`analysis/manuscript-draft` is historical preparation. The current paper, rendered
figures, and any later post-hoc large-array memory diagnostics are separate
deliverables and are not added to these stable original-evidence manifests.
