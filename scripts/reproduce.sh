#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/verify_repository.py
python3 - <<'PYTHON'
from pathlib import Path
import tarfile,hashlib,os
archive=os.environ.get('EVIDENCE_ARCHIVE')
if not archive: raise SystemExit('Set EVIDENCE_ARCHIVE to the separately supplied canonical lean archive; bulk evidence is not included in Git.')
src=Path(archive)
assert hashlib.sha256(src.read_bytes()).hexdigest()=='3b53371632c8010336be846232f0a73090baa8700fb6ab5ade9fa15ddfef5dae'
out=Path('.reproduction')
if out.exists(): raise SystemExit('Use a fresh checkout or move .reproduction aside before replay.')
out.mkdir()
with tarfile.open(src) as t:
 for m in t.getmembers():
  p=Path(m.name)
  if p.is_absolute() or '..' in p.parts or not (m.isfile() or m.isdir()): raise SystemExit('Unsafe archive member')
 t.extractall(out,filter='data')
PYTHON
BUNDLE=.reproduction/v3-lean-evidence
SHA=2a8127785f5d5e2f2c42e8d1cf8061da344b174db7014907145bccc902f290aa
python3 -B "$BUNDLE/study/analysis/reproduction/evidence.py" --native-measurements-finished verify --bundle "$BUNDLE" --manifest-sha256 "$SHA"
python3 -B "$BUNDLE/study/analysis/reproduction/replay_numeric.py" --native-measurements-finished --bundle "$BUNDLE" --manifest-sha256 "$SHA" --out .reproduction/replayed-numerics.json
