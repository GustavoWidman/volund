#!/usr/bin/env python3
"""Verify deliverable bytes, plus tracked inventory/modes when Git is present."""
from pathlib import Path
import hashlib,json,subprocess
root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'audit/repository-manifest.json').read_text())
expected=set(manifest['sha256'])|{'audit/repository-manifest.json'}
if (root/'.git').exists():
 tracked={}
 for item in subprocess.check_output(['git','-C',str(root),'ls-files','--stage','-z']).decode().split('\0'):
  if item:
   meta,path=item.split('\t',1);mode,_,stage=meta.split()
   if stage!='0': raise SystemExit(f'Unmerged path: {path}')
   tracked[path]=mode
 if set(tracked)!=expected:
  raise SystemExit(f'Tracked inventory mismatch: missing={sorted(expected-set(tracked))}; extra={sorted(set(tracked)-expected)}')
 for rel,mode in manifest.get('git_modes',{}).items():
  if tracked[rel]!=mode:raise SystemExit(f'Git mode mismatch: {rel}')
for rel,sha in manifest['sha256'].items():
 p=root/rel
 if p.is_symlink() or not p.is_file(): raise SystemExit(f'Missing/unsafe: {rel}')
 if hashlib.sha256(p.read_bytes()).hexdigest()!=sha: raise SystemExit(f'Hash mismatch: {rel}')
print(f"Verified {len(manifest['sha256'])} files; manifest excludes itself. Git inventory/modes checked when available.")
