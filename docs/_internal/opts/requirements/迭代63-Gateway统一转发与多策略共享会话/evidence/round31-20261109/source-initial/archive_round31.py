"""Archive only known public R31 review, verification and synthetic-test artifacts."""
from pathlib import Path
import hashlib,json,shutil
ROOT=Path('/Users/yunjinqi/Documents/new_projects/backtrader')
BASE=ROOT/'docs/_internal/opts/requirements/迭代63-Gateway统一转发与多策略共享会话'
DEST=BASE/'evidence/round31-20261109'
assert not DEST.exists()
DEST.mkdir(parents=True)
exts={'.py','.json','.jsonl','.log','.xml','.txt','.sha256','.stdout','.stderr'}
manifest=[]
def copy(src,rel):
    assert src.is_file() and not src.is_symlink(),src
    target=DEST/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,target)
    manifest.append({'archive':str(rel),'source':str(src),'bytes':src.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
def group(src,label,recursive=False):
    for p in sorted(src.rglob('*') if recursive else src.glob('*')):
        if p.is_file() and not p.is_symlink() and p.suffix in exts and '__pycache__' not in p.parts:
            copy(p,Path(label)/p.relative_to(src))
source=Path('/tmp/iter63-r31-primary');v2=Path('/tmp/iter63-r31-primary-bt-v2');install=Path('/tmp/iter63-r31-install-20261109-mz1EwW5H')
for folder,label in [(source,'source-initial'),(v2,'source-final-bt'),(install,'install')]:
    group(folder,label)
    for name in ('bootstrap','origin-logs'):
        if (folder/name).is_dir():group(folder/name,Path(label)/name,True)
for folder,label in [('iter63-r31-review-edge','review-notification'),('iter63-r31-review-pending','review-pending'),('iter63-r31-review-stream','review-stream'),('iter63-r31-stream-process','process-integration'),('iter63-r31-resume-hook','resume-hook'),('iter63-r31-fixture-validation','fixture-validation'),('r31-execution-time.p5lejT','execution-time')]:
    group(Path('/tmp')/folder,label,True)
for name in ['iter63-r31-metadata-unit.log','iter63-r31-metadata-unit.xml','iter63-r31-metadata-checkpoint.log','iter63-r31-notification-regression-before.log','iter63-r31-notification-review-v2.log','iter63-r31-notification-review-v2.xml','iter63-r31-order-bootstrap-pytest.log','iter63-r31-order-ref-collision-pytest.log','iter63-r31-order-ref-collision-repro.log','iter63-r31-e078-pending-pytest.log']:
    p=Path('/tmp')/name
    if p.is_file():copy(p,Path('worker-logs')/name)
for name in ['bt-frozen-inputs.json.candidate2','bt-owned-files.json.candidate2','test-manifest.json.candidate2']:
    copy(install/name,Path('install')/(name+'.json'))
for name in ['tests/unit/brokers/test_iter63_gateway_metadata_checkpoint.py','tests/unit/brokers/test_iter63_gateway_stream_consumer.py','tests/unit/live_state/test_iter63_gateway_order_bootstrap.py','tests/unit/test_iter63_gateway_notification_resume_hook.py']:
    copy(install/'bt-tests-candidate2'/name,Path('candidate2-fixture-inputs')/name)
for kind,root in [('bt',ROOT),('sdk',ROOT.parent/'bt_api_py')]:
    files=json.loads((source/f'{kind}-owned-files.json').read_text())
    for file in files:copy(root/file,Path('final-owned-inputs')/kind/file)
(DEST/'manifest.json').write_text(json.dumps({'scope':'public source, explicit synthetic tests, verification and review only','files':manifest},indent=2)+'\n')
print(json.dumps({'archived_files':len(manifest)+1,'bytes':sum(x['bytes'] for x in manifest),'destination':str(DEST)},indent=2))
