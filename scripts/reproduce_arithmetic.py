#!/usr/bin/env python3
"""Replay curated paired-data arithmetic, without inference/native timing."""
from pathlib import Path
import hashlib,json,sys
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'experiments/unattended-optimization-v3/analysis/reproduction'))
from replay_numeric import reduce_pairs,close
base=root/'data/raw-arithmetic'
manifest=json.loads((base/'MANIFEST.json').read_text())
expected=set(manifest['files'])
actual={str(p.relative_to(base)) for p in base.rglob('*') if p.is_file() and p.name!='MANIFEST.json'}
if actual!=expected:raise SystemExit('Curated inventory differs from manifest')
for rel,pin in manifest['files'].items():
 p=base/rel
 if p.is_symlink() or not p.is_file():raise SystemExit('Unsafe input')
 data=p.read_bytes()
 if len(data)!=pin['bytes'] or hashlib.sha256(data).hexdigest()!=pin['sha256']:raise SystemExit('Curated input hash mismatch')
pairs=sorted(base.rglob('paired.json'))
if len(pairs)!=52 or len(expected)!=156:raise SystemExit('Expected 52 comparisons with three exact inputs each')
for p in pairs:
 result=json.loads(p.with_name('result.json').read_text())
 boot=json.loads(p.with_name('descriptive-bootstrap.json').read_text())
 v=reduce_pairs(json.loads(p.read_text()),boot['resamples'],boot['seed'],boot['confidence'])
 close(v['portfolio_speedup'],result['portfolio_speedup'])
 close(v['one_sided_lower_bound'],boot['one_sided_lower_bound'])
 if set(v['family_speedups'])!=set(result['family_speedups']):raise SystemExit('Family set mismatch')
 for family,speedup in v['family_speedups'].items():close(speedup,result['family_speedups'][family])
print('PASS: all 52 paired comparisons reproduce. Arithmetic only; no full source/build/attempt/command audit, inference or native timing.')
