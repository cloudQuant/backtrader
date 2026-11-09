"""Accept four primary-frozen test-only updates while retaining candidate2 evidence."""
from pathlib import Path
import hashlib,json,os,shutil
T=Path('/tmp/iter63-r31-install-20261109-mz1EwW5H');P=Path(os.environ['R31_V2_PRIMARY']);repo=Path('/Users/yunjinqi/Documents/new_projects/backtrader');sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if not (P/'SOURCE_FROZEN').is_file():raise RuntimeError('v2 primary freeze absent')
old=json.loads((T/'bt-frozen-inputs.json').read_text());new=json.loads((P/'bt-frozen-inputs.json').read_text());a={x['path']:x['sha256'] for x in old};b={x['path']:x['sha256'] for x in new}
changed=[k for k in a if a[k]!=b.get(k)]
if set(a)!=set(b) or len(changed)!=4 or any(not k.startswith('tests/') or not k.endswith('.py') for k in changed):raise RuntimeError(('unexpected changed input set',changed))
rows=json.loads((T/'test-manifest.json').read_text());affected=[]
for rel in changed:
 matches=[r for r in rows if r['repo']==str(repo) and r['relative']==rel]
 if len(matches)!=1 or matches[0]['sha256']!=a[rel] or sha(Path(matches[0]['copy']))!=a[rel] or sha(repo/rel)!=b[rel]:raise RuntimeError(('test mismatch',rel))
 affected.append((rel,matches[0]))
for name in ('test-manifest.json','bt-frozen-inputs.json','bt-owned-files.json'):
 if (T/(name+'.candidate2')).exists():raise RuntimeError('candidate2 backup exists')
 shutil.copyfile(T/name,T/(name+'.candidate2'))
for rel,row in affected:
 oldcopy=Path(row['copy']);backup=T/'bt-tests-candidate2'/rel;backup.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(oldcopy,backup);shutil.copyfile(repo/rel,oldcopy);row['sha256']=b[rel]
(T/'test-manifest.json').write_text(json.dumps(rows,indent=2)+'\n');shutil.copyfile(P/'bt-frozen-inputs.json',T/'bt-frozen-inputs.json');shutil.copyfile(P/'bt-owned-files.json',T/'bt-owned-files.json')
print('REFRESHED_FOUR_TESTS',json.dumps(changed),'SOURCE_COUNT',len(b),'TEST_MANIFEST',len(rows),flush=True)
