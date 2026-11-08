"""Copy only frozen selected public tests and their tracked local helpers."""
import ast
import hashlib
import json
import subprocess
from pathlib import Path

T = Path('/tmp/iter63-r10-packaging-Zc9un7t2')
SDK = Path('/Users/yunjinqi/Documents/new_projects/bt_api_py')
CTP = SDK / 'bt_api/bt_api_ctp'
if not (T / 'SOURCE_FROZEN').is_file(): raise RuntimeError('source freeze not recorded')

def tracked(repo):
    return set(filter(None, subprocess.check_output(['git','-C',str(repo),'ls-files','-z','--cached','--','tests']).decode().split('\0')))

allowed = {SDK: tracked(SDK) | {'tests/unit/test_iter63_correlation_issuer_reopen.py'}, CTP: tracked(CTP)}
manifest = []
seen_copy = set()

def copy(repo, relative, dest):
    rel = relative.as_posix()
    if rel not in allowed[repo]: raise RuntimeError(('test/helper not tracked or explicitly approved',str(repo),rel))
    src = repo / relative
    if src.is_symlink() or not src.is_file(): raise RuntimeError(('test/helper missing or non-regular',rel))
    data = src.read_bytes()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.read_bytes() != data: raise RuntimeError(('destination collision', str(dest)))
    dest.write_bytes(data)
    if str(dest) not in seen_copy:
        manifest.append({'source':str(src),'copy':str(dest),'sha256':hashlib.sha256(data).hexdigest()})
        seen_copy.add(str(dest))
    return dest

def plan(name):
    path = T / 'plans' / (name + '.txt')
    if not path.is_file(): raise RuntimeError(('missing frozen test plan',name))
    result = [line.strip() for line in path.read_text().splitlines() if line.strip() and not line.startswith('#')]
    if not result or any(not x.startswith('tests/') or '..' in Path(x).parts for x in result):
        raise RuntimeError(('invalid test plan',name))
    return result

ctp_plan, sdk_plan = plan('ctp'), plan('sdk')
ctp_root, sdk_root = T/'install', T/'sdk-tests'
queue = []
for rel in ctp_plan: queue.append((CTP, copy(CTP, Path(rel), ctp_root/rel), ctp_root))
for rel in sdk_plan: queue.append((SDK, copy(SDK, Path(rel), sdk_root/rel), sdk_root))
for repo, root, names in (
    (CTP, ctp_root, ['tests/conftest.py']),
    (SDK, sdk_root, ['tests/__init__.py','tests/conftest.py','tests/conftest_test_data.py',
                     'tests/unit/__init__.py','tests/unit/conftest.py',
                     'tests/integration/__init__.py','tests/integration/conftest.py']),
):
    for rel in names:
        if rel in allowed[repo] and (repo/rel).is_file():
            queue.append((repo, copy(repo, Path(rel), root/rel), root))
# Existing SDK tests resolve this public helper by path.
helper = Path('tests/test_iter62_settlement_readback_on_write.py')
if helper.as_posix() in allowed[CTP]:
    queue.append((CTP,copy(CTP,helper,sdk_root/'bt_api/bt_api_ctp'/helper),sdk_root))
seen = set()
while queue:
    repo, path, root = queue.pop()
    if path in seen: continue
    seen.add(path)
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'), filename=str(path))):
        refs = []
        if isinstance(node, ast.Import): refs = [a.name for a in node.names if a.name.startswith(('tests.','test_'))]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module.startswith(('tests.','test_')): refs = [node.module]
            elif node.module == 'tests': refs = ['tests.'+a.name for a in node.names]
        elif (isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant)
              and type(node.args[0].value) is str and isinstance(node.func, ast.Attribute)
              and node.func.attr == 'import_module' and node.args[0].value.startswith(('tests.','test_'))):
            refs = [node.args[0].value]
        for name in refs:
            if name.startswith('tests.'):
                rel = Path(*name.split('.')).with_suffix('.py')
                candidates = [(repo, rel, root/rel)] if rel.as_posix() in allowed[repo] else []
            else:
                candidates = []
                prefixes = ('tests',) if repo == CTP else ('tests/unit','tests','tests/integration')
                for prefix in prefixes:
                    rel = Path(prefix)/(name+'.py')
                    if rel.as_posix() in allowed[repo] and (repo/rel).is_file(): candidates.append((repo,rel,root/rel))
                if repo == SDK:
                    rel = Path('tests')/(name+'.py')
                    if rel.as_posix() in allowed[CTP] and (CTP/rel).is_file(): candidates.append((CTP,rel,root/'bt_api/bt_api_ctp'/rel))
            if len(candidates) != 1: raise RuntimeError(('ambiguous or untracked test helper',name,len(candidates)))
            source_repo, relative, dest = candidates[0]
            queue.append((source_repo,copy(source_repo,relative,dest),root))
(T/'ctp-selected.txt').write_text('\n'.join(ctp_plan)+'\n')
(sdk_root/'selected-tests.txt').write_text('\n'.join(sdk_plan)+'\n')
(T/'test-manifest.json').write_text(json.dumps(sorted(manifest,key=lambda x:x['copy']),indent=2)+'\n')
print('test files',len(manifest),'AST visited',len(seen),flush=True)
