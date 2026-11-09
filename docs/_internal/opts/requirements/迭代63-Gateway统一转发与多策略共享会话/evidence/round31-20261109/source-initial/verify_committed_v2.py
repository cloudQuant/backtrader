"""Read-only Git verification, including public CTP test helpers in SDK tests."""
import hashlib,json,subprocess
from pathlib import Path
B=Path('/Users/yunjinqi/Documents/new_projects/backtrader');S=B.parent/'bt_api_py';C=S/'bt_api/bt_api_ctp';O=Path('/tmp/iter63-r31-primary');I=Path('/tmp/iter63-r31-install-20261109-mz1EwW5H')
sha=lambda b:hashlib.sha256(b).hexdigest()
rows=[]
for name in ['source-manifest.json','test-manifest.json']:rows+=json.loads((I/name).read_text())
heads={str(r):subprocess.check_output(['git','rev-parse','HEAD'],cwd=r).decode().strip() for r in (B,S,C)}
assert {row['repo'] for row in rows}==set(heads)
unique={}
for row in rows:
    for key in ('source','copy'):assert sha(Path(row[key]).read_bytes())==row['sha256'],row[key]
    key=(row['repo'],row['relative']);assert key not in unique or unique[key]==row['sha256'];unique[key]=row['sha256']
for repo,head in heads.items():
    entries=[(rel,digest) for (r,rel),digest in unique.items() if r==repo]
    assert all('\n' not in rel for rel,_ in entries)
    query=''.join(head+':'+rel+'\n' for rel,_ in entries).encode()
    payload=subprocess.check_output(['git','cat-file','--batch'],cwd=repo,input=query)
    pos=0
    for rel,digest in entries:
        end=payload.index(b'\n',pos);header=payload[pos:end].split();assert header[1]==b'blob',header
        size=int(header[2]);data=payload[end+1:end+1+size];assert sha(data)==digest,(repo,rel)
        pos=end+1+size;assert payload[pos:pos+1]==b'\n';pos+=1
    assert pos==len(payload)
report={'heads':heads,'source_rows':len(json.loads((I/'source-manifest.json').read_text())),'test_rows':len(json.loads((I/'test-manifest.json').read_text())),'unique_git_paths_verified':len(unique),'bt_owned_files':json.loads((O/'bt-owned-files.json').read_text()),'verification_correction':'v1 assumed all helpers belong to SDK or BT; 2 public CTP helpers also require their repository head. Initial v1 stderr was tool output only; no separate raw file.'}
(O/'product-commits.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
