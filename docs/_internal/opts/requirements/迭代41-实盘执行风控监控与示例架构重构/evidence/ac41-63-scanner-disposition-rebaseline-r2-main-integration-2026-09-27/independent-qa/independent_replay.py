from __future__ import annotations
import hashlib,json,shutil,subprocess,sys
from pathlib import Path
repo=Path(r'D:\source_code\backtrader')
pkg=Path(r'D:\temp\ac41-63-writer-rebaseline-r1-20260927')
qa=Path(r'D:\temp\ac41-63-writer-rebaseline-independent-qa-20260927')
manifest_path=pkg/'rebaseline-patch-manifest.json'
manifest=json.loads(manifest_path.read_text(encoding='utf-8-sig'))
patch=pkg/manifest['patch_file']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest().upper()
assert sha(patch)==manifest['patch_sha256'].upper()
# Verify exact current-tree preimages, then copy only the four patch targets into a fresh scratch Git repo.
scratch=qa/'exact-current-base-replay'
if scratch.exists():shutil.rmtree(scratch)
scratch.mkdir(parents=True)
preimages={}
for rel,spec in manifest['changed_files'].items():
 src=repo/rel; got=sha(src)
 assert got==spec['preimage_sha256'].upper(),(rel,spec['preimage_sha256'],got)
 dst=scratch/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
 preimages[rel]={'sha256':got,'bytes':src.stat().st_size}
subprocess.run(['git','init','-q'],cwd=scratch,check=True)
subprocess.run(['git','-c','core.autocrlf=false','apply','--check','--whitespace=error',str(patch)],cwd=scratch,check=True)
subprocess.run(['git','-c','core.autocrlf=false','apply','--whitespace=error',str(patch)],cwd=scratch,check=True)
targets={}
for rel,spec in manifest['changed_files'].items():
 got=sha(scratch/rel); assert got==spec['target_sha256'].upper(),(rel,spec['target_sha256'],got)
 targets[rel]={'sha256':got,'bytes':(scratch/rel).stat().st_size}
result={'manifest_sha256':sha(manifest_path),'patch_sha256':sha(patch),'current_preimages':preimages,'isolated_exact_replay_targets':targets,'strict_apply_check':'PASS','isolated_apply':'PASS'}
(qa/'replay-identity.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,indent=2))
