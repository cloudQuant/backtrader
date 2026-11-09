"""Freeze the primary's selector list only after an explicit source freeze."""
import hashlib
import json
from pathlib import Path
T = Path('/tmp/iter63-r31-install-20261109-mz1EwW5H')
if not (T/'SOURCE_FROZEN').is_file():
    raise SystemExit('SOURCE_FREEZE required')
source = Path('/tmp/iter63-r31-primary/selectors.json')
raw = source.read_bytes()
plans = json.loads(raw)
if type(plans) is not dict or set(plans) != {'sdk', 'bt'}:
    raise ValueError('invalid plan groups')
if (T/'selectors.json').exists() or (T/'plans').exists():
    raise RuntimeError('refusing plan overwrite')
(T/'selectors.json').write_bytes(raw)
(T/'plans').mkdir()
for kind, selectors in plans.items():
    if type(selectors) is not list or not selectors or any(type(item) is not str or not item for item in selectors):
        raise ValueError('invalid selectors')
    (T/'plans'/f'{kind}.txt').write_text('\n'.join(selectors)+'\n')
print('SELECTORS_SHA256', hashlib.sha256(raw).hexdigest(), flush=True)
