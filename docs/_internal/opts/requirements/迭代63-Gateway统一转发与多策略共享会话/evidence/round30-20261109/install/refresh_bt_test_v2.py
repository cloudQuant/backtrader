"""Refresh one primary-frozen BT test after preserving the complete v1 evidence."""
from pathlib import Path
import hashlib,json,shutil
T=Path('/tmp/iter63-r30-install-20261109-ySExhdil');P=Path('/tmp/iter63-r30-primary-bt-v2');repo=Path('/Users/yunjinqi/Documents/new_projects/backtrader');rel='tests/unit/live_state/test_iter63_gateway_trade_date_pending.py';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
old=json.loads((T/'bt-frozen-inputs.json').read_text());new=json.loads((P/'bt-frozen-inputs.json').read_text());a={x['path']:x['sha256'] for x in old};b={x['path']:x['sha256'] for x in new}
if set(a)!=set(b) or [k for k in a if a[k]!=b[k]]!=[rel] or sha(repo/rel)!=b[rel]:raise RuntimeError('expected exactly one BT test SHA update')
rows=json.loads((T/'test-manifest.json').read_text());affected=[x for x in rows if x['repo']==str(repo) and x['relative']==rel]
if len(affected)!=1 or affected[0]['sha256']!=a[rel] or sha(Path(affected[0]['copy']))!=a[rel]:raise RuntimeError('old BT test snapshot differs')
for name in ('test-manifest.json','bt-frozen-inputs.json'):
 dest=T/(name+'.v1');
 if dest.exists():raise RuntimeError('v1 manifest already backed up')
 shutil.copyfile(T/name,dest)
oldcopy=Path(affected[0]['copy']);shutil.copyfile(oldcopy,T/'bt-trade-date-test-v1.py');shutil.copyfile(repo/rel,oldcopy);affected[0]['sha256']=b[rel]
(T/'test-manifest.json').write_text(json.dumps(rows,indent=2)+'\n');shutil.copyfile(P/'bt-frozen-inputs.json',T/'bt-frozen-inputs.json')
print('BT_TEST_REFRESHED',rel,'OLD',a[rel],'NEW',b[rel],'NO_OTHER_INPUT_CHANGED')
