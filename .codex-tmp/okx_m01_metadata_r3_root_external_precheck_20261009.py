"""Root-only bounded external precheck; no metadata write or account operation."""
import ast
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

ROOT = Path('D:/source_code/backtrader')
CALLER = ROOT / '.codex-tmp/okx_m01_protected_rebind_r3_root_actual_candidate_20261009.py'
RESULT = ROOT / '.codex-tmp/okx_m01_metadata_r3_root_external_precheck_20261009.json'
HEAD = '934e30b55c078a42517c1c758a45eacb09a2b740'

def win(path):
    return '\\\\?\\' + str(path.absolute())

def ancestors(path):
    current = path
    while True:
        info = os.lstat(win(current))
        assert stat.S_ISDIR(info.st_mode) and not info.st_file_attributes & 0x400
        if current.parent == current:
            break
        current = current.parent

def read(path, cap, digest, size=None):
    ancestors(path.parent)
    info = os.lstat(win(path))
    assert stat.S_ISREG(info.st_mode) and not info.st_file_attributes & 0x400
    assert 0 < info.st_size <= cap
    if size is not None:
        assert info.st_size == size
    with open(win(path), 'rb') as stream:
        raw = stream.read(cap + 1)
    assert len(raw) == info.st_size and hashlib.sha256(raw).hexdigest() == digest
    return raw

raw = read(CALLER, 2*1024*1024, 'f80890de30021dc9751a439a247c0549afca7303fb13f8f8bb27019e6c193fd6', 55093)
# Evaluate only the pinned public caller's finite constant assignments, never
# its imports, definitions, run function, or actual invocation.
tree = ast.parse(raw)
assignments = [node for node in tree.body if isinstance(node, ast.Assign) and node.lineno < 159]
namespace = {'Path': Path, 'str': str}
exec(compile(ast.Module(body=assignments, type_ignores=[]), '<root-public-constants>', 'exec'), namespace)
review = ROOT / namespace['EVIDENCE'] / 'iteration41-okx-m01-v3-protected-rebind-r3-root-caller-independent-review-r1-2026-10-09/review.md'
review_raw = read(review, 2*1024*1024, '3d601ad9c094015139baad5e7d72f64e20e89d2d1aa20bdd4cf97b8f2c0a29f3', 4412)
assert b'GO_ROOT_CALLER_STATIC_ONLY' in review_raw
source_map = json.loads(read(ROOT/namespace['MAP_RELATIVE'], 2*1024*1024, namespace['MAP_SHA256'], namespace['MAP_SIZE']))
assert source_map['schema'] == 'iteration41.okx.m01.case-source-map.v3'
pins = dict(source_map['source_pins'])
assert len(pins) == 19
rows = []
for relative, digest in pins.items():
    data = read(ROOT/relative, 2*1024*1024, digest)
    rows.append({'path': relative, 'bytes': len(data), 'sha256': digest})
for relative, (size, digest) in namespace['SUPPORT_PINS'].items():
    read(ROOT/relative, 2*1024*1024, digest, size)
    pins[relative] = digest
    rows.append({'path': relative, 'bytes': size, 'sha256': digest})
pins[CALLER.relative_to(ROOT).as_posix()] = hashlib.sha256(raw).hexdigest()
assert len(pins) == 33
software = []
for filename, digest in namespace['SOFTWARE'].items():
    path = Path(filename)
    cap = 2*1024*1024 if path == namespace['CU'] else 8*1024*1024
    size = 5991424 if path.name == 'python311.dll' else None
    data = read(path, cap, digest, size)
    software.append({'path': filename, 'bytes': len(data), 'sha256': digest})
for path in (namespace['OUT'], namespace['R3_BACKUP'], RESULT):
    ancestors(path.parent)
    assert not os.path.lexists(win(path))
git = ['C:/Program Files/Git/cmd/git.exe', '-c', 'core.fsmonitor=false']
assert subprocess.check_output(git+['rev-parse', 'HEAD'], cwd=ROOT).decode().strip() == HEAD
assert subprocess.check_output(git+['branch', '--show-current'], cwd=ROOT).decode().strip() == 'dev'
assert not subprocess.check_output(git+['diff', '--cached', '--name-only'], cwd=ROOT)
record = {'status':'ROOT_EXTERNAL_PIN_HEAD_INDEX_FRESH_PASS', 'head':HEAD,
          'branch':'dev', 'index_empty':True, 'public_pin_count':len(pins),
          'public_source_rows':rows, 'caller_pin':{'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()},
          'software_rows':software, 'software_pin_count':len(software),
          'fixed_output_absent':True,'fixed_r3_backup_absent':True,
          'ancestors_nonreparse':True,'protected_metadata_read':False,
          'credentials_or_account_operation':False}
with open(win(RESULT),'xb') as stream:
    stream.write((json.dumps(record,sort_keys=True,indent=2)+'\n').encode('utf8'))
print(json.dumps({key:record[key] for key in ('status','head','public_pin_count','software_pin_count','fixed_output_absent','fixed_r3_backup_absent')},sort_keys=True))
