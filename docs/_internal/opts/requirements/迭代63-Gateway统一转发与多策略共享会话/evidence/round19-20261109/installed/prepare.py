"""Stage only approved R17 source, fixed wheels and tests after primary freeze."""
from __future__ import annotations
import ast
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

T = Path('/tmp/iter63-r19-install-20261109-uQ78MEA5')
SDK = Path('/Users/yunjinqi/Documents/new_projects/bt_api_py')
CTP, BASE, GATEWAY = SDK/'bt_api/bt_api_ctp', SDK/'bt_api/bt_api_base', SDK/'bt_api/bt_api_gateway'
BT = SDK.parent/'backtrader'
R11 = Path('/tmp/iter63-r11-packaging-CoU48Q7B')
REPOS = {'base': (BASE, 'src/bt_api_base'), 'gateway': (GATEWAY, 'src/bt_api_gateway'), 'ctp': (CTP, 'src/bt_api_ctp'), 'sdk': (SDK, 'bt_api_py'), 'bt': (BT, 'backtrader')}
# Primary-supplied after freeze, explicit path lists, never scan-and-admit.
ALLOWLISTS = json.loads((T/'allowlists.json').read_text()) if (T/'allowlists.json').is_file() else {}
NEW_RUNTIME = {repo:set(ALLOWLISTS.get('runtime', {}).get(name, [])) for name,(repo,_) in REPOS.items()}
NEW_GATEWAY_TESTS = set(ALLOWLISTS.get('tests', {}).get('gateway', []))
NEW_BASE_TESTS = set(ALLOWLISTS.get('tests', {}).get('base', []))
PRIVATE = {'.env', 'config.yaml', 'account_config.yaml'}
CTP_WHEEL_SHA256 = '1bf7498a073231e6b0663fc45052e60f1b48c766530ffb18b7ea78c7cb2b9583'
R13 = Path('/tmp/iter63-r13-packaging-gjjgT6GX')
_HEADS = {}



def files(repo, tracked, *paths):
    flags = ['--cached'] if tracked else ['--others', '--exclude-standard']
    output = subprocess.check_output(['git', '-C', str(repo), 'ls-files', '-z', *flags, '--', *paths])
    return set(filter(None, output.decode('utf-8').split('\0')))


def safe_copy(repo, relative, destination, rows):
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts or any(p in PRIVATE or p.startswith('.env') for p in rel.parts):
        raise RuntimeError(('private or invalid path', relative))
    source = repo/rel
    if source.is_symlink() or not source.is_file():
        raise RuntimeError(('missing or non-regular source', str(source)))
    data = source.read_bytes()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.read_bytes() != data:
        raise RuntimeError(('test helper collision', str(destination)))
    destination.write_bytes(data)
    if repo not in _HEADS:
        _HEADS[repo] = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    rows.append({'source': str(source), 'copy': str(destination), 'sha256': hashlib.sha256(data).hexdigest(),
                 'repo': str(repo), 'relative': rel.as_posix(), 'snapshot_head': _HEADS[repo]})


def snapshot():
    if (T/'source').exists() or (T/'source-manifest.json').exists():
        raise RuntimeError('source snapshot must start empty; no stale build tree permitted')
    rows = []
    for name, (repo, runtime) in REPOS.items():
        paths = files(repo, True, 'pyproject.toml', 'setup.py', 'setup.cfg', 'README.md', 'MANIFEST.in', 'LICENSE', runtime)
        untracked = {x for x in files(repo, False, runtime) if x.endswith('.py')}
        if untracked - NEW_RUNTIME[repo]:
            raise RuntimeError(('unapproved runtime', name, sorted(untracked - NEW_RUNTIME[repo])))
        paths |= untracked
        paths = {p for p in paths if Path(p).name != '.DS_Store'}
        if not NEW_RUNTIME[repo].issubset(paths):
            raise RuntimeError(('expected R17 runtime missing', name))
        for relative in sorted(paths):
            if any(part in {'build', 'dist', '__pycache__'} or part.endswith('.egg-info') for part in Path(relative).parts):
                raise RuntimeError(('stale build artifact in source selection', relative))
            safe_copy(repo, relative, T/'source'/name/relative, rows)
        for forbidden in ('build', 'dist'):
            if (T/'source'/name/forbidden).exists():
                raise RuntimeError(('unexpected pre-existing build tree', name, forbidden))
        print(name, 'HEAD', subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'], text=True).strip(), 'selected', len(paths), flush=True)
    (T/'source-manifest.json').write_text(json.dumps(rows, indent=2)+'\n')


def fixed():
    if (T/'fixed-wheels.json').exists():
        raise RuntimeError('fixed wheel staging already exists')
    previous=Path('/tmp/iter63-r18-install-20261109-GvDCI8TF')
    old_rows=json.loads((previous/'source-manifest.json').read_text())
    new_rows=json.loads((T/'source-manifest.json').read_text())
    old={r['relative']:r['sha256'] for r in old_rows if r['repo'] == str(BT)}
    new={r['relative']:r['sha256'] for r in new_rows if r['repo'] == str(BT)}
    if not old or old != new:
        raise RuntimeError(('BT differs from R18 source manifest',sorted(old.keys() ^ new.keys()),sorted(k for k in old.keys() & new.keys() if old[k] != new[k])))
    for row in (r for r in old_rows if r['repo'] == str(BT)):
        if hashlib.sha256(Path(row['copy']).read_bytes()).hexdigest() != row['sha256']:
            raise RuntimeError(('R18 BT source snapshot drift', row['copy']))
    print('R18_BT_SOURCE_MANIFEST_MATCH',len(old),flush=True)
    expected={
        'back_trader_python-':'792bad705c3f14a41c519322e6bee7c2cbae15faf33da622e895d9e2a743b4a7',
        'bt_api_okx-':'2243f8427d282e53f08b50e88832b149dfde0729afcbd8b3e768eb7a81ce1c07',
        'bt_api_binance-':'703f312d1889052293b49c390855f2df50d38084ced8a80029f4794ca6e1c5be',
    }
    rows=[]
    for prefix,digest in expected.items():
        found=list((previous/'wheels').glob(prefix+'*.whl'))
        if len(found)!=1 or hashlib.sha256(found[0].read_bytes()).hexdigest()!=digest:
            raise RuntimeError(('fixed R18 wheel missing or mismatched',prefix))
        source=found[0]; target=T/'wheels'/source.name; target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
        rows.append({'source':str(source),'filename':source.name,'sha256':digest,'provenance':'R18 verified wheel'})
        print('FIXED_R18',source.name,digest,flush=True)
    (T/'fixed-wheels.json').write_text(json.dumps(rows,indent=2)+'\n')


def plan(name):
    path = T/'plans'/f'{name}.txt'
    if not path.is_file():
        raise RuntimeError(('missing primary test plan', name))
    result = [line.strip() for line in path.read_text().splitlines() if line.strip() and not line.startswith('#')]
    if name == 'base' and result in (['tests/'], ['tests']):
        unexpected = {x for x in files(BASE, False, 'tests') if x.endswith('.py')} - NEW_BASE_TESTS
        if unexpected:
            raise RuntimeError(('unapproved untracked Base tests', sorted(unexpected)))
        available = files(BASE, True, 'tests') | NEW_BASE_TESTS
        result = sorted(x for x in available if Path(x).name.startswith('test_') and x.endswith('.py'))
    if name == 'gateway' and result in (['tests/'], ['tests']):
        unexpected = {x for x in files(GATEWAY, False, 'tests') if x.endswith('.py')} - NEW_GATEWAY_TESTS
        if unexpected:
            raise RuntimeError(('unapproved untracked Gateway tests', sorted(unexpected)))
        available = files(GATEWAY, True, 'tests') | NEW_GATEWAY_TESTS
        result = sorted(x for x in available if Path(x).name.startswith('test_') and x.endswith('.py'))
    if name == 'bt':
        available = files(BT, True, 'tests') | {'tests/unit/live_state/test_gateway_pending_cancel.py'}
        expanded = []
        for item in result:
            if item == 'tests/unit/live_state':
                expanded.extend(sorted(x for x in available if x.startswith(item+'/') and Path(x).name.startswith('test_') and x.endswith('.py')))
            else:
                expanded.append(item)
        result = expanded
    if not result or len(result) != len(set(result)) or any(
        not x.startswith('tests/') or '..' in Path(x.split('::', 1)[0]).parts
        or not x.split('::', 1)[0].endswith('.py')
        or ('::' in x and not x.split('::', 1)[1])
        for x in result
    ):
        raise RuntimeError(('invalid or empty primary test plan', name))
    return result


def tests():
    if (T/'test-manifest.json').exists():
        raise RuntimeError('test snapshot already exists')
    rows, copied, queue = [], set(), []
    selector_groups = json.loads((T/'selectors.json').read_text())
    plans = {name: plan(name) for name in selector_groups}
    allowed = {repo: files(repo, True, 'tests') | {x.split('::', 1)[0] for x in plans.get(name, ())} for name, (repo, _) in REPOS.items()}
    allowed[CTP] |= set(ALLOWLISTS.get('tests', {}).get('ctp', []))
    allowed[SDK].add('conftest.py')
    allowed[BT].add('conftest.py')
    allowed[BT] |= {'tests/unit/live_state/test_gateway_pending_cancel.py'}
    roots = {name: T/(name+'-tests') for name in REPOS}
    def copy(name, repo, rel, dest=None):
        rel = Path(rel)
        if rel.as_posix() not in allowed[repo]:
            raise RuntimeError(('unapproved test/helper', str(repo), str(rel)))
        target = dest or roots[name]/rel
        if target not in copied:
            safe_copy(repo, rel, target, rows)
            copied.add(target)
        return target
    for name in plans:
        repo, _ = REPOS[name]
        for rel in plans[name]:
            queue.append((name, repo, copy(name, repo, rel.split('::', 1)[0])))
        for rel in ('tests/__init__.py', 'tests/conftest.py', 'tests/conftest_test_data.py', 'tests/unit/__init__.py', 'tests/unit/conftest.py', 'tests/integration/__init__.py', 'tests/integration/conftest.py'):
            if rel in allowed[repo] and (repo/rel).is_file():
                queue.append((name, repo, copy(name, repo, rel)))
        (roots[name]/'selected-tests.txt').write_text('\n'.join(plans[name])+'\n')
    queue.append(('sdk', SDK, copy('sdk', SDK, 'conftest.py')))
    if 'bt' in plans:
        queue.append(('bt', BT, copy('bt', BT, 'conftest.py')))
    # Include every tracked local helper and pytest fixture for the full BT
    # live-state directory, including relative imports and subprocess modules.
    bt_helpers = {x for x in allowed[BT] if x.startswith('tests/unit/live_state/') and x.endswith('.py')} if 'bt' in plans else set()
    if 'bt' in plans:
        bt_helpers |= {'tests/integration/iter60_service_ledger_host_support.py'}
    if 'base' in plans:
        for rel in sorted(x for x in allowed[BASE] if x.startswith('tests/') and x.endswith('.py')):
            queue.append(('base', BASE, copy('base', BASE, rel)))
    for rel in sorted(bt_helpers):
        queue.append(('bt', BT, copy('bt', BT, rel)))
    visited = set()
    while queue:
        name, repo, path = queue.pop()
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
            for ref in refs:
                candidates = []
                if ref.startswith('tests.'):
                    rel = Path(*ref.split('.')).with_suffix('.py')
                    if rel.as_posix() in allowed[repo] and (repo/rel).is_file():
                        candidates.append((repo, rel, roots[name]/rel))
                else:
                    prefixes = ('tests/unit','tests','tests/integration') if repo == SDK else ('tests',)
                    for prefix in prefixes:
                        rel = Path(prefix)/(ref+'.py')
                        if rel.as_posix() in allowed[repo] and (repo/rel).is_file():
                            candidates.append((repo, rel, roots[name]/rel))
                    if repo == SDK:
                        rel = Path('tests')/(ref+'.py')
                        if rel.as_posix() in allowed[CTP] and (CTP/rel).is_file():
                            candidates.append((CTP, rel, roots[name]/'bt_api/bt_api_ctp'/rel))
                if len(candidates) != 1:
                    raise RuntimeError(('ambiguous or unapproved helper', ref, len(candidates)))
                source, rel, dest = candidates[0]
                queue.append((name, source, copy(name, source, rel, dest)))
    copy('sdk', CTP, 'tests/test_iter63_prepared_cancel.py', roots['sdk']/'bt_api/bt_api_ctp/tests/test_iter63_prepared_cancel.py')
    # Exactly the five tracked public sample files used by test_service_config_io.
    for name in ('unconfigured-client.yaml','strategy-readonly.yaml','portfolio-analysis-client.yaml','account-service.yaml','portfolio-analysis-service.yaml'):
        rel='examples/services/'+name
        if rel not in files(SDK, True, rel):
            raise RuntimeError(('public sample not tracked', rel))
        allowed[SDK].add(rel)
        copy('sdk', SDK, rel)
    (T/'test-manifest.json').write_text(json.dumps(rows, indent=2)+'\n')
    print('test_files', len(rows), 'ast_visited', len(visited), flush=True)


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in {'snapshot', 'fixed', 'tests'}:
        raise SystemExit('usage: prepare.py snapshot|fixed|tests')
    if not (T/'SOURCE_FROZEN').is_file():
        raise SystemExit('R19 freeze marker absent; refusing staging')
    {'snapshot':snapshot, 'fixed':fixed, 'tests':tests}[sys.argv[1]]()

if __name__ == '__main__':
    main()
