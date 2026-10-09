import hashlib
import json
from pathlib import Path, PurePosixPath
import runpy

root = Path('D:/source_code/backtrader')
evidence = 'docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/'
packet = evidence + 'iteration41-optional16-r4-root-actual-caller-preparation-r3-2026-10-09/'
index_raw = (root / (packet + 'source-index.json')).read_bytes()
assert len(index_raw) == 35595
assert hashlib.sha256(index_raw).hexdigest() == 'ee2f7095862d5ffedca11f0e3ed2b5708637f1cdb0f70017f42c7b2c73eb6c52'
value = json.loads(index_raw)
assert len(value['post_pins']) == 76 and len(value['sourcefake_artifacts']) == 8
for row in value['post_pins'] + value['sourcefake_artifacts']:
    relative = PurePosixPath(row['path'])
    assert not relative.is_absolute() and '..' not in relative.parts
    assert relative.suffix in ('.py', '.json', '.md', '.txt', '.zip')
    assert row['bytes'] <= 2097152
    raw = root.joinpath(*relative.parts).read_bytes()
    assert len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'], row['path']
addendum = (root / (packet + 'final-packet-identity-r1.json')).read_bytes()
assert len(addendum) == 4441 and hashlib.sha256(addendum).hexdigest() == 'de2051d2642820da7157fd05a502345f2605c8d45936422c85bbbc14fa7fed52'
git = runpy.run_path(str(root / '.codex-tmp/stage_okx_m01_r4_source_close_support_r2_20261009.py'), run_name='root_public_git_utilities')['git']
assert git('branch', '--show-current') == b'dev\n'
head = git('rev-parse', 'HEAD').decode().strip()
assert head == 'e0b45398f7f7ff8fcae7931b1fbb28886ee05d7b'
assert git('diff', '--cached', '--name-only', '-z') == b''
output = root / (evidence + 'iteration41-optional16-preparation-source-reconciliation-root-actual-r4-r5-2026-10-09')
assert not output.exists()
receipt = {'status':'PUBLIC_CALLER_PRECHECK_PASSED', 'branch':'dev', 'head':head, 'index_empty':True, 'public_pins_verified':84, 'final_identity_addendum_verified':True, 'output_namespace_absent':True, 'host_metadata_tool':'cf9cb4', 'host_id':25932, 'actual_reconciliation_invoked':False, 'tests_repeated':False}
(root / '.codex-tmp/optional16_r4_r3_root_precheck_20261009.json').open('x', encoding='utf-8').write(json.dumps(receipt, indent=2)+'\n')
print(json.dumps(receipt))
