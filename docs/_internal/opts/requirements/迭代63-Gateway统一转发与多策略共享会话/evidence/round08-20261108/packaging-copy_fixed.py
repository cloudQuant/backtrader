from pathlib import Path
import json, hashlib, shutil
old=Path('/tmp/iter63-r07-final-packaging-5t99PHD1'); out=Path('/tmp/iter63-r08-packaging-j8KrE0I2/wheels'); out.mkdir(exist_ok=True)
for row in json.loads((old/'artifact.json').read_text())['wheels']:
 p=old/row['filename']
 if p.name.startswith('bt_api_py-'): continue
 assert hashlib.sha256(p.read_bytes()).hexdigest()==row['sha256']
 shutil.copy2(p,out/p.name); print(p.name,row['sha256'])
