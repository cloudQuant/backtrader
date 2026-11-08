"""Copy only the unchanged wheels authenticated by the R09 manifest."""
import hashlib
import json
import shutil
from pathlib import Path
T = Path('/tmp/iter63-r10-packaging-Zc9un7t2')
old = Path('/tmp/iter63-r09-packaging-ySGAYCmv/final')
if not (T / 'SOURCE_FROZEN').is_file(): raise RuntimeError('source freeze not recorded')
out = T / 'wheels'
out.mkdir(exist_ok=True)
prefixes = ('back_trader_python-', 'bt_api_base-', 'bt_api_gateway-', 'bt_api_okx-', 'bt_api_binance-')
found = set()
for row in json.loads((old / 'artifact.json').read_text())['wheels']:
    if not row['filename'].startswith(prefixes): continue
    src = old / 'wheels' / row['filename']
    assert hashlib.sha256(src.read_bytes()).hexdigest() == row['sha256']
    shutil.copyfile(src, out / src.name)
    found.add(next(prefix for prefix in prefixes if src.name.startswith(prefix)))
    print(src.name, row['sha256'], flush=True)
assert found == set(prefixes)
