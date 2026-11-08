"""Verify manifested fixture additions and selector/harness freeze integrity."""
import hashlib
import json
import subprocess
from pathlib import Path
T=Path('/tmp/iter63-r17-install-20261109-oNtWsjp3')
P=Path('/tmp/iter63-r17-primary')
def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
for row in json.loads((P/'harness-freeze-sha256-v2.json').read_text()):
    if sha(row['path']) != row['sha256']:
        raise RuntimeError(('HARNESS_DRIFT',row['path']))
print('HARNESS_V2_SHA_MATCH',flush=True)
expanded=json.loads((P/'selectors-expanded.json').read_text())
for kind, expected in expanded.items():
    actual=(T/(kind+'-tests')/'selected-tests.txt').read_text().splitlines()
    if actual!=expected:
        raise RuntimeError(('SELECTOR_EXPANSION_MISMATCH',kind))
    print('EXPANDED_SELECTORS_MATCH',kind,len(actual),flush=True)
rows=json.loads((T/'base-test-helpers-manifest.json').read_text())
for row in rows:
    for name in ('source','copy'):
        if sha(row[name])!=row['sha256']:
            raise RuntimeError(('BASE_HELPER_DRIFT',row[name]))
base=Path('/Users/yunjinqi/Documents/new_projects/bt_api_py/bt_api/bt_api_base')
tracked=subprocess.check_output(['git','-C',str(base),'ls-files','--','tests'],text=True).splitlines()
missing=[name for name in tracked if name.endswith('.py') and not (T/'base-tests'/name).is_file()]
if missing:
    raise RuntimeError(('BASE_TRACKED_TEST_HELPERS_MISSING',missing))
print('BASE_TEST_HELPER_SHA_MATCH',len(rows),'ALL_TRACKED_TEST_PY_PRESENT',flush=True)
change=json.loads((T/'sdk-fixture-refresh-manifest.json').read_text())
for name in ('source','copy'):
    if sha(change[name])!=change['sha256']:
        raise RuntimeError(('SDK_FIXTURE_DRIFT',change[name]))
if sha(change['old_copy']) != change['old_sha256']:
    raise RuntimeError('SDK_OLD_TEST_ARCHIVE_DRIFT')
old=json.loads(Path(change['old_manifest']).read_text())
new=json.loads((T/'test-manifest-before-base-helpers.json').read_text())
if len(old)!=len(new):
    raise RuntimeError('TEST_MANIFEST_ROW_COUNT_CHANGED')
differences=[(left,right) for left,right in zip(old,new) if left!=right]
if (len(differences)!=1 or differences[0][0]['sha256']!=change['old_sha256']
        or differences[0][1]['sha256']!=change['sha256']
        or differences[0][1]['copy']!=change['copy']
        or {k:v for k,v in differences[0][0].items() if k!='sha256'}
           != {k:v for k,v in differences[0][1].items() if k!='sha256'}):
    raise RuntimeError('UNAPPROVED_TEST_MANIFEST_CHANGE')
print('SDK_FIXTURE_REFRESH_AND_ORIGINAL_MANIFEST_SHA_MATCH',flush=True)

final=json.loads((T/'test-manifest.json').read_text())
extra=json.loads((T/'base-test-helpers-manifest.json').read_text())
if final != new + extra:
    raise RuntimeError('BASE_HELPER_MANIFEST_MERGE_INVALID')
print('BASE_HELPERS_INCLUDED_IN_FINAL_TEST_MANIFEST',len(final),flush=True)
