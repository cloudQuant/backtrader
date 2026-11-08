"""Append verified Base helper records without overwriting prior evidence."""
import hashlib,json,shutil
from pathlib import Path
T=Path('/tmp/iter63-r17-install-20261109-oNtWsjp3')
manifest=T/'test-manifest.json'
before=T/'test-manifest-before-base-helpers.json'
if before.exists():
    raise RuntimeError('refusing previous manifest overwrite')
rows=json.loads(manifest.read_text())
extra=json.loads((T/'base-test-helpers-manifest.json').read_text())
if len(extra)!=7 or any(row['copy'] in {r['copy'] for r in rows} for row in extra):
    raise RuntimeError('invalid base helper addition')
for row in extra:
    for field in ('source','copy'):
        if hashlib.sha256(Path(row[field]).read_bytes()).hexdigest()!=row['sha256']:
            raise RuntimeError(('helper drift',row[field]))
shutil.copyfile(manifest,before)
manifest.write_text(json.dumps(rows+extra,indent=2)+'\n')
print('TEST_MANIFEST_ADDED_BASE_HELPERS',len(extra),'TOTAL',len(rows)+len(extra),flush=True)
