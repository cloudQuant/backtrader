"""R11 isolated staging; all operations require an explicit external freeze marker."""
from __future__ import annotations
import ast
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

T = Path('/tmp/iter63-r11-packaging-CoU48Q7B')
SDK = Path('/Users/yunjinqi/Documents/new_projects/bt_api_py')
BASE, GATEWAY, CTP = (SDK / 'bt_api' / name for name in ('bt_api_base', 'bt_api_gateway', 'bt_api_ctp'))
OLD = Path('/tmp/iter63-r10-packaging-Zc9un7t2')
NEW_RUNTIME = {BASE: {'src/bt_api_base/gateway_execution_protocol.py'}, GATEWAY: {'src/bt_api_gateway/direct_execution_journal.py'}}
NEW_TESTS = {BASE: {'tests/test_gateway_execution_protocol.py'}, GATEWAY: {'tests/test_iter63_direct_execution_journal.py', 'tests/test_iter63_execution_ledger_commit_faults.py'}, SDK: {'tests/integration/test_iter63_gateway_return_ledger.py'}, CTP: set()}
PRIVATE = {'.env', 'config.yaml', 'account_config.yaml'}


def tracked(repo, *paths):
    data = subprocess.check_output(['git', '-C', str(repo), 'ls-files', '-z', '--cached', '--', *paths])
    return set(filter(None, data.decode('utf-8').split('\0')))


def untracked(repo, *paths):
    data = subprocess.check_output(['git', '-C', str(repo), 'ls-files', '-z', '--others', '--exclude-standard', '--', *paths])
    return set(filter(None, data.decode('utf-8').split('\0')))


def safe_copy(repo, relative, dest, rows):
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts or any(p in PRIVATE or p.startswith('.env') for p in rel.parts):
        raise RuntimeError(('private or invalid path', relative))
    src = repo / rel
    if src.is_symlink() or not src.is_file():
        raise RuntimeError(('missing or non-regular file', str(src)))
    data = src.read_bytes()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.read_bytes() != data:
        raise RuntimeError(('copy collision', str(dest)))
    dest.write_bytes(data)
    rows.append({'source': str(src), 'copy': str(dest), 'sha256': hashlib.sha256(data).hexdigest()})


def snapshot():
    rows = []
    for name, repo, runtime in (('base', BASE, 'src/bt_api_base'), ('gateway', GATEWAY, 'src/bt_api_gateway')):
        paths = tracked(repo, 'pyproject.toml', 'setup.py', 'setup.cfg', 'README.md', 'MANIFEST.in', 'LICENSE', runtime)
        new = {x for x in untracked(repo, runtime) if x.endswith('.py')}
        if new - NEW_RUNTIME[repo]:
            raise RuntimeError((name, 'unapproved untracked runtime', sorted(new - NEW_RUNTIME[repo])))
        paths |= new
        if not NEW_RUNTIME[repo].issubset(paths):
            raise RuntimeError((name, 'required R11 source missing'))
        for relative in sorted(paths):
            safe_copy(repo, relative, T/'source'/name/relative, rows)
        print(name, 'HEAD', subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'], text=True).strip(), 'files', len(paths), flush=True)
    (T/'source-manifest.json').write_text(json.dumps(rows, indent=2)+'\n')


def fixed():
    wheel_rows = json.loads((OLD/'artifact.json').read_text())['wheels']
    prefixes = ('back_trader_python-', 'bt_api_py-', 'bt_api_ctp-', 'bt_api_okx-', 'bt_api_binance-')
    result = []
    for prefix in prefixes:
        selected = [r for r in wheel_rows if r['filename'].startswith(prefix)]
        if len(selected) != 1:
            raise RuntimeError(('invalid R10 wheel selection', prefix))
        row = selected[0]
        src = OLD/'wheels'/row['filename']
        digest = hashlib.sha256(src.read_bytes()).hexdigest()
        if digest != row['sha256']:
            raise RuntimeError(('R10 wheel hash mismatch', row['filename']))
        dest = T/'wheels'/src.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        result.append({'filename': src.name, 'sha256': digest, 'source': str(src)})
        print('REUSED_R10', src.name, digest, flush=True)
    (T/'fixed-wheels.json').write_text(json.dumps(result, indent=2)+'\n')


def plan(name):
    lines = (T/'plans'/f'{name}.txt').read_text().splitlines()
    return [x.strip() for x in lines if x.strip() and not x.startswith('#')]


def tests():
    rows = []
    unapproved_gateway = {
        path for path in untracked(GATEWAY, 'tests') if path.endswith('.py')
    } - NEW_TESTS[GATEWAY]
    if unapproved_gateway:
        raise RuntimeError(('unapproved untracked Gateway tests', sorted(unapproved_gateway)))
    allowed = {repo: tracked(repo, 'tests') | NEW_TESTS[repo] for repo in (SDK, CTP, BASE, GATEWAY)}
    roots = {'base': T/'base-tests', 'gateway': T/'gateway-tests', 'sdk': T/'sdk-tests'}
    sdk_queue = []
    seen = set()
    def copy(repo, relative, root, destination=None):
        rel = Path(relative)
        if rel.as_posix() not in allowed[repo]:
            raise RuntimeError(('untracked test/helper not approved', str(repo), str(rel)))
        dest = destination or root/rel
        if dest not in seen:
            safe_copy(repo, rel, dest, rows)
            seen.add(dest)
        return dest
    for rel in plan('base'):
        copy(BASE, rel, roots['base'])
    gateway_tests = sorted(x for x in allowed[GATEWAY] if x.startswith('tests/') and x.endswith('.py'))
    if not NEW_TESTS[GATEWAY].issubset(gateway_tests):
        raise RuntimeError('R11 Gateway test missing')
    for rel in gateway_tests:
        copy(GATEWAY, rel, roots['gateway'])
    (roots['gateway']/'selected-tests.txt').write_text('\n'.join(x for x in gateway_tests if Path(x).name.startswith('test_'))+'\n')
    for rel in plan('sdk'):
        sdk_queue.append((SDK, copy(SDK, rel, roots['sdk'])))
    for rel in ('tests/__init__.py', 'tests/conftest.py', 'tests/conftest_test_data.py', 'tests/unit/__init__.py', 'tests/unit/conftest.py', 'tests/integration/__init__.py', 'tests/integration/conftest.py'):
        if rel in allowed[SDK] and (SDK/rel).is_file():
            sdk_queue.append((SDK, copy(SDK, rel, roots['sdk'])))
    helper = 'tests/test_iter62_settlement_readback_on_write.py'
    if helper in allowed[CTP]:
        sdk_queue.append((CTP, copy(CTP, helper, roots['sdk'], roots['sdk']/'bt_api/bt_api_ctp'/helper)))
    visited = set()
    while sdk_queue:
        repo, path = sdk_queue.pop()
        if path in visited:
            continue
        visited.add(path)
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'), filename=str(path))):
            refs = []
            if isinstance(node, ast.Import):
                refs = [a.name for a in node.names if a.name.startswith(('tests.', 'test_'))]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                if node.module.startswith(('tests.', 'test_')):
                    refs = [node.module]
                elif node.module == 'tests':
                    refs = ['tests.'+a.name for a in node.names]
            elif (isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant)
                  and type(node.args[0].value) is str and isinstance(node.func, ast.Attribute)
                  and node.func.attr == 'import_module' and node.args[0].value.startswith(('tests.', 'test_'))):
                refs = [node.args[0].value]
            for name in refs:
                if name.startswith('tests.'):
                    rel = Path(*name.split('.')).with_suffix('.py')
                    candidates = [(repo, rel, roots['sdk']/rel)] if rel.as_posix() in allowed[repo] else []
                else:
                    candidates = []
                    for prefix in ('tests/unit', 'tests', 'tests/integration') if repo == SDK else ('tests',):
                        rel = Path(prefix)/(name+'.py')
                        if rel.as_posix() in allowed[repo] and (repo/rel).is_file():
                            candidates.append((repo, rel, roots['sdk']/rel))
                    if repo == SDK:
                        rel = Path('tests')/(name+'.py')
                        if rel.as_posix() in allowed[CTP] and (CTP/rel).is_file():
                            candidates.append((CTP, rel, roots['sdk']/'bt_api/bt_api_ctp'/rel))
                if len(candidates) != 1:
                    raise RuntimeError(('ambiguous or unapproved helper', name, len(candidates)))
                source, rel, dest = candidates[0]
                sdk_queue.append((source, copy(source, rel, roots['sdk'], dest)))
    (roots['sdk']/'selected-tests.txt').write_text('\n'.join(plan('sdk'))+'\n')
    (roots['base']/'selected-tests.txt').write_text('\n'.join(plan('base'))+'\n')
    (T/'test-manifest.json').write_text(json.dumps(rows, indent=2)+'\n')
    print('test_files', len(rows), 'sdk_ast_files', len(visited), 'gateway_collected_files', len(gateway_tests), flush=True)


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in {'snapshot', 'fixed', 'tests'}:
        raise SystemExit('usage: prepare.py snapshot|fixed|tests')
    if not (T/'SOURCE_FROZEN').is_file():
        raise SystemExit('SOURCE_FROZEN absent: no snapshot, test copy or wheel staging permitted')
    {'snapshot': snapshot, 'fixed': fixed, 'tests': tests}[sys.argv[1]]()

if __name__ == '__main__':
    main()
