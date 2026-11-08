"""Refresh only the primary-approved SDK test; archive prior copy and manifest."""
import hashlib
import json
import shutil
from pathlib import Path
T=Path('/tmp/iter63-r17-install-20261109-oNtWsjp3')
rel='tests/unit/test_iter63_gateway_cancel_return_ingestion.py'
expected='4d621562764a75fc7791e6074cdf939eb4ccdc1690b578a4fe608a282cd8afec'
source=Path('/Users/yunjinqi/Documents/new_projects/bt_api_py')/rel
copy=T/'sdk-tests'/rel
manifest=T/'test-manifest.json'
old_manifest=T/'test-manifest-before-sdk-fixture.json'
old_copy=T/'sdk-tests-before-fixture'/rel
supplement=T/'sdk-fixture-refresh-manifest.json'
if old_manifest.exists() or old_copy.exists() or supplement.exists():
    raise RuntimeError('refusing refresh overwrite')
new_bytes=source.read_bytes()
if hashlib.sha256(new_bytes).hexdigest()!=expected:
    raise RuntimeError('approved source hash mismatch')
old_bytes=copy.read_bytes()
rows=json.loads(manifest.read_text())
matches=[row for row in rows if row['source']==str(source) and row['copy']==str(copy)]
if len(matches)!=1 or hashlib.sha256(old_bytes).hexdigest()!=matches[0]['sha256']:
    raise RuntimeError('old snapshot or manifest mismatch')
shutil.copyfile(manifest,old_manifest)
old_copy.parent.mkdir(parents=True,exist_ok=True)
old_copy.write_bytes(old_bytes)
copy.write_bytes(new_bytes)
matches[0]['sha256']=expected
manifest.write_text(json.dumps(rows,indent=2)+'\n')
supplement.write_text(json.dumps({'source':str(source),'copy':str(copy),'sha256':expected,
    'old_copy':str(old_copy),'old_sha256':hashlib.sha256(old_bytes).hexdigest(),
    'old_manifest':str(old_manifest)},indent=2)+'\n')
print('SDK_FIXTURE_TEST_REFRESHED_EXACT',expected,flush=True)
