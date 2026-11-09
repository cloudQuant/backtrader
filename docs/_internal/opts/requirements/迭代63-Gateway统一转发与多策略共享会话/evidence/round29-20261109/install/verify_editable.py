from pathlib import Path
import hashlib,json,subprocess
T=Path('/tmp/iter63-r29-sdk-install-20261109-pht8FUZ4');now=json.loads((T/'editable-deps-manifest.json').read_text());old=json.loads(Path('/tmp/iter63-r26-sdk-install-20261109-xAIrOrDl/editable-deps-manifest.json').read_text())
for a,b in zip(old,now):
 if a['package']!=b['package'] or a['head']!=b['head'] or [(r['relative'],r['sha256']) for r in a['files']]!=[(r['relative'],r['sha256']) for r in b['files']]:raise RuntimeError(('R26 editable mismatch',b['package']))
 repo=Path(b['repo']);head=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
 if head!=b['head']:raise RuntimeError(('HEAD changed',b['package']))
 for x in b['files']:
  if hashlib.sha256(Path(x['source']).read_bytes()).hexdigest()!=x['sha256']:raise RuntimeError(('editable drift',x['source']))
 print('EDITABLE_MATCH_R26_AND_CURRENT',b['package'],head,len(b['files']))
