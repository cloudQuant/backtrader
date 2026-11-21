import hashlib
import io
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

repo = Path('D:/source_code/backtrader')
root = Path('D:/temp/i71_r102_perf_26b6')
commit = '26b6a39db076a0e7a97d0074bc65fd41a7e9db6d'
old_commit = 'd02e3d75452c34ff915aebd1d631332ff7a44679'
root.mkdir(parents=True, exist_ok=False)
dirty = {name: (repo / ('backtrader/' + name)).read_bytes() for name in ('lineiterator.py', 'linebuffer.py')}
archive = subprocess.check_output(['git', 'archive', commit, 'backtrader', 'tests/datas/XAUUSD_M15.csv'], cwd=repo)
head = root / 'head_safe'
head.mkdir()
with tarfile.open(fileobj=io.BytesIO(archive)) as package:
    package.extractall(head, filter='data')
for name in ('head_old', 'wip_safe', 'wip_old'):
    shutil.copytree(head, root / name)
for label in ('wip_safe', 'wip_old'):
    for name, raw in dirty.items():
        (root / label / 'backtrader' / name).write_bytes(raw)
old_source = subprocess.check_output(['git', 'show', old_commit + ':backtrader/lineiterator.py'], cwd=repo)
start_marker = b'    def _factor_strict_context_for_callback(self):'
end_marker = b'    @staticmethod\n    def _inherit_factor_strict_context(obj, context):'

def split_source(raw):
    normalized = raw.replace(b'\r\n', b'\n')
    assert normalized.count(start_marker) == 1
    assert normalized.count(end_marker) == 1
    start = normalized.index(start_marker)
    end = normalized.index(end_marker, start)
    return normalized[:start], normalized[start:end], normalized[end:]

old_method = split_source(old_source)[1]
manifest = {'head': commit, 'old_method_commit': old_commit, 'paths': {}}
for label in ('head', 'wip'):
    safe_path = root / (label + '_safe') / 'backtrader/lineiterator.py'
    old_path = root / (label + '_old') / 'backtrader/lineiterator.py'
    pre, safe_method, post = split_source(safe_path.read_bytes())
    assert b'context = getattr(self, "_factor_strict_context", None)' in safe_method
    assert b'current = self\n        seen = set()' in old_method
    newline = b'\r\n' if b'\r\n' in safe_path.read_bytes() else b'\n'
    updated = (pre + old_method + post).replace(b'\n', newline)
    old_path.write_bytes(updated)
    xpre, method, xpost = split_source(updated)
    assert pre == xpre and post == xpost and method == old_method
for label in ('head_safe', 'head_old', 'wip_safe', 'wip_old'):
    manifest['paths'][label] = {}
    for name in ('backtrader/lineiterator.py', 'backtrader/linebuffer.py', 'tests/datas/XAUUSD_M15.csv'):
        raw = (root / label / name).read_bytes()
        manifest['paths'][label][name] = hashlib.sha256(raw).hexdigest()
for name, raw in dirty.items():
    assert (repo / ('backtrader/' + name)).read_bytes() == raw
(root / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf8')
print(json.dumps(manifest, indent=2))
