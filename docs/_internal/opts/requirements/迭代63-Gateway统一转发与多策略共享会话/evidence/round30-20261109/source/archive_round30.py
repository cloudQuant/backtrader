"""Archive only declared public R30 verification artifacts, without runtime state."""
import hashlib,json,shutil
from pathlib import Path
repo=Path('/Users/yunjinqi/Documents/new_projects/backtrader')
D=repo/'docs/_internal/opts/requirements/迭代63-Gateway统一转发与多策略共享会话'
E=D/'evidence/round30-20261109';E.mkdir(exist_ok=False)
roots=[(Path('/tmp/iter63-r30-primary'),'source'),(Path('/tmp/iter63-r30-primary-bt-v2'),'source-bt-v2'),(Path('/tmp/iter63-r30-install-20261109-ySExhdil'),'install')]
records=[]
def copy(source,relative):
 dest=E/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest)
 records.append({'path':relative.as_posix(),'source':str(source),'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'bytes':dest.stat().st_size})
for root,label in roots:
 for p in sorted(root.iterdir()):
  if p.is_file() and (p.suffix in {'.py','.json','.jsonl','.log','.xml','.txt'} or p.name=='SOURCE_FROZEN' or p.name.endswith('.json.v1')):
   copy(p,Path(label)/p.name)
 for sub in ('bootstrap','origin-logs','plans'):
  directory=root/sub
  if directory.is_dir():
   for p in sorted(directory.rglob('*')):
    if p.is_file() and '__pycache__' not in p.parts and p.suffix in {'.py','.json','.jsonl','.txt'}:
     copy(p,Path(label)/p.relative_to(root))
 if label=='install':
  for prefix in ('bt_api_base-','bt_api_gateway-','bt_api_ctp-','bt_api_py-','back_trader_python-'):
   wheel,=(root/'wheels').glob(prefix+'*.whl');copy(wheel,Path(label)/'wheels'/wheel.name)
for name in ('iter63-r30-sdk-stream.log','iter63-r30-sdk-stream-v2.log','iter63-r30-sdk-stream-regression.log','iter63-r30-sdk-stream-regression-final.log','iter63-r30-sdk-stream-junit-final.xml','r30-review-targeted.log','r30-review-gateway.log'):
 source=Path('/tmp')/name
 if source.is_file():copy(source,Path('worker')/name)
review={'type':'primary summary of independent reviewer messages, not raw original logs','issues':[
 {'id':'E071','finding':'metadata-only observation accepted without original trade correlation fields','fix':'Require trade key, quantity, price, side and venue key for metadata-only; ordinary incomplete observations unchanged','review_evidence':'Independent inline before/after checks; scripts/stdout not saved as separate files. Final product tests are included in primary source and install Base suites.'},
 {'id':'E072','finding':'Changing conflict reason to retained and removing conflict evidence could pass reopen','fix':'Audit retained conflicts against actual original conflict evidence and flags','review_evidence':'Independent inline SQLite reproducer and fixed recheck; no separate original artifacts. Final regression is in Gateway suite.'},
 {'id':'E073','finding':'Live read could return a metadata event as an ordinary fill after mutating reason','fix':'Verify applied pointer or metadata side-table/original-event links before returning effect','review_evidence':'Independent inline before/after checks; no saved original artifacts. Final regression is in Gateway suite.'}],
 'limitations':['Primary initial payload verifier incorrectly required all multi-platform CTP source files in one wheel; v2 then omitted declared public config YAML. Scripts and correction record retained, terminal failures have no separate raw log file.','Worker and reviewer assertions alone are not whole-iteration or real-account acceptance.']}
p=E/'review-summary.json';p.write_text(json.dumps(review,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
records.append({'path':'review-summary.json','source':'primary summary from this chat','sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size})
manifest={'round':'R30','date':'2026-11-09','evidence_level':'local synthetic source and isolated installed package checks','files':records,'exclusions':['runtime tmp/state databases and generated credential files','full source/test mirrors, recoverable from committed inputs','fixed dependency wheels, identified by prior R29 hashes','real account configuration or captures']}
(E/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('ARCHIVED',len(records)+1,'files',sum(x['bytes'] for x in records),'bytes')
