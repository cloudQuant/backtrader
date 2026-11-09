from pathlib import Path
import hashlib,json,subprocess,sys,zipfile
P=Path('/tmp/iter63-r28-primary-v3'); T=Path('/tmp/iter63-r28-candidate3-20261109-ijqQ26LC'); R=Path('/Users/yunjinqi/Documents/new_projects/backtrader')
sha=lambda b:hashlib.sha256(b).hexdigest()
owned=set(json.loads((P/'bt-owned-files.json').read_text())); all_git=sys.argv[1:]==['--committed']
counts={}; git_rows={}
for name in ['source-manifest.json','test-manifest.json','testcommon-fixtures-manifest.json']:
 rows=json.loads((T/name).read_text());counts[name]=len(rows)
 for row in rows:
  if 'source' not in row or 'copy' not in row:raise RuntimeError(('unexpected manifest',name,row.keys()))
  src=Path(row['source']);dst=Path(row['copy'])
  assert src.is_relative_to(R) and dst.is_relative_to(T)
  digest=row['sha256'];assert sha(src.read_bytes())==sha(dst.read_bytes())==digest,(name,src)
  rel=str(src.relative_to(R));assert '\n' not in rel
  if all_git or rel not in owned:git_rows[rel]=digest
proc=subprocess.run(['git','cat-file','--batch'],cwd=R,input=''.join('HEAD:'+rel+'\n' for rel in git_rows).encode(),stdout=subprocess.PIPE,check=True)
data=proc.stdout;offset=0
for rel,digest in git_rows.items():
 end=data.index(b'\n',offset);header=data[offset:end].split();assert len(header)==3 and header[1]==b'blob',(rel,header)
 size=int(header[2]);blob=data[end+1:end+1+size];assert sha(blob)==digest,rel;offset=end+1+size+1
assert offset==len(data)
for row in json.loads((P/'bt-frozen-inputs.json').read_text()):assert sha(Path(row['path']).read_bytes())==row['sha256'],row['relative_path']
wheel,=list((T/'wheels').glob('back_trader_python-*.whl'));payload=0;py=0
with zipfile.ZipFile(wheel) as z:
 for n in z.namelist():
  if n.startswith('backtrader/') and not n.endswith('/'):
   b=z.read(n);assert b==(R/n).read_bytes()==(T/'source/bt'/n).read_bytes()==(T/'install/src'/n).read_bytes(),n;payload+=1;py+=n.endswith('.py')
 md,=[n for n in z.namelist() if n.endswith('.dist-info/METADATA')]
 assert z.read(md).split(b'\n\n',1)[1].rstrip(b'\n')==(R/'README.md').read_bytes().rstrip(b'\n')
result={'git_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip(),'committed_mode':all_git,'manifest_counts':counts,'git_verified_unique_paths':len(git_rows),'primary_frozen_inputs':len(json.loads((P/'bt-frozen-inputs.json').read_text())),'wheel':wheel.name,'wheel_sha256':sha(wheel.read_bytes()),'bt_payload_members':payload,'bt_python_members':py,'readme_metadata_match':True}
print(json.dumps(result,indent=2));(P/('primary-delivery-committed.json' if all_git else 'primary-delivery-before-commit.json')).write_text(json.dumps(result,indent=2)+'\n')
