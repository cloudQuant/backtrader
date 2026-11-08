from pathlib import Path
import json,hashlib,shutil
old=Path('/tmp/iter63-r08-packaging-j8KrE0I2'); out=Path('/tmp/iter63-r09-packaging-ySGAYCmv/final/wheels'); out.mkdir(parents=True,exist_ok=True)
data=json.loads((old/'artifact.json').read_text()); rows=data['changed_wheels']+data['fixed_wheels']
for row in rows:
 p=old/'wheels'/row['filename']
 if not p.name.startswith(('back_trader_python-','bt_api_base-','bt_api_okx-','bt_api_binance-')): continue
 assert hashlib.sha256(p.read_bytes()).hexdigest()==row['sha256']; shutil.copy2(p,out/p.name); print(p.name,row['sha256'])
