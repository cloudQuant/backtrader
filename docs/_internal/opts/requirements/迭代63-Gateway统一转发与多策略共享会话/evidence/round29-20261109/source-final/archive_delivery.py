from pathlib import Path
import hashlib,json,shutil
B=Path('/Users/yunjinqi/Documents/new_projects/backtrader'); D=B/'docs/_internal/opts/requirements/迭代63-Gateway统一转发与多策略共享会话'; E=D/'evidence/round29-20261109'; E.mkdir(parents=True,exist_ok=False)
sha=lambda b:hashlib.sha256(b).hexdigest();rows=[]
def cp(src,relative):
 assert src.is_file() and not src.is_symlink(),str(src)
 assert not any(x.startswith('.env') or x in {'config.yaml','account_config.yaml'} for x in src.parts)
 dest=E/relative;dest.parent.mkdir(parents=True,exist_ok=True);data=src.read_bytes();dest.write_bytes(data)
 rows.append({'path':relative,'source':str(src),'sha256':sha(data),'bytes':len(data)})
roots={'source-attempt1':Path('/tmp/iter63-r29-primary'),'source-final':Path('/tmp/iter63-r29-primary-v2'),'install':Path('/tmp/iter63-r29-sdk-install-20261109-pht8FUZ4')}
for label,root in roots.items():
 for p in sorted(root.iterdir()):
  if p.is_file() and not p.is_symlink() and (p.suffix in {'.py','.log','.json','.jsonl','.xml','.txt'} or p.name=='SOURCE_FROZEN'):
   cp(p,label+'/'+p.name)
 for sub in ('bootstrap','origin-logs'):
  if (root/sub).exists():
   for p in sorted((root/sub).rglob('*')):
    if p.is_file() and not p.is_symlink() and p.suffix in {'.py','.jsonl'}:cp(p,label+'/'+p.relative_to(root).as_posix())
for name in ['iter63-r29-sdk-tests.log','iter63-r29-sdk-combined-tests.log','iter63-r29-sdk-gateway-tests.log','iter63-r29-sdk-legacy-tests.log','iter63-r29-sdk-ruff.log','iter63-r29-cleanup-combined-tests.log','iter63-r29-cleanup-ruff.log']:
 p=Path('/tmp')/name
 if p.exists():cp(p,'worker/'+name)
root=Path('/tmp/iter63-r29-gateway-api-process')
for p in sorted(root.rglob('*')):
 if p.is_file() and not p.is_symlink() and p.suffix in {'.txt','.xml','.sha256','.log'}:cp(p,'integration-worker/'+p.relative_to(root).as_posix())
wheel,=(roots['install']/'wheels').glob('bt_api_py-*.whl');cp(wheel,'wheels/'+wheel.name)
review={'scope':'R29 explicit GatewayBtApi, no full BT consumer or account acceptance','initial_product_sha256':'c8693a571f152b01acf0385e62bb01ad7f30338034a139089574922a2f46630e','finding':'E070 detected binding changes prevented owned facade from closing the original runtime','final_product_sha256':'70c8fa28d852df3a109515842d594ad2ad455ee2c9ed090f87b2936b8d480eb6','independent_recheck':'original-PID borrowed/owned cleanup reproduced with synthetic session; business calls still rejected; no further definite issue in limited scope','primary_acceptance':'source and installed same14 297 passed; primary reviewed diff and independently verified all manifests, package payload and Git bytes','account_tested':False}
p=E/'review-summary.json';p.write_text(json.dumps(review,indent=2)+'\n');rows.append({'path':p.relative_to(E).as_posix(),'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size,'source':'primary summary of independent review messages'})
(E/'manifest.json').write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps({'files':len(rows)+1,'bytes':sum(x['bytes'] for x in rows),'evidence':str(E)}))
