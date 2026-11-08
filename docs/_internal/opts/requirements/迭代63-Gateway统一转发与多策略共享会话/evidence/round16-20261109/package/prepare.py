"""Stage only approved R16 source, fixed wheels and tests after primary freeze."""
from __future__ import annotations
import ast
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

T = Path('/tmp/iter63-r16-install-20261109-IKmdXERW')
SDK = Path('/Users/yunjinqi/Documents/new_projects/bt_api_py')
CTP, BASE, GATEWAY = SDK/'bt_api/bt_api_ctp', SDK/'bt_api/bt_api_base', SDK/'bt_api/bt_api_gateway'
R11 = Path('/tmp/iter63-r11-packaging-CoU48Q7B')
REPOS = {'base': (BASE, 'src/bt_api_base'), 'gateway': (GATEWAY, 'src/bt_api_gateway'), 'ctp': (CTP, 'src/bt_api_ctp'), 'sdk': (SDK, 'bt_api_py')}
NEW_RUNTIME = {
    BASE: {'src/bt_api_base/gateway_cancel_protocol.py'},
    GATEWAY: set(),
    CTP: set(),
    SDK: set(),
}
NEW_GATEWAY_TESTS = set()
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
            raise RuntimeError(('expected R16 runtime missing', name))
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
    prior_dir = Path('/tmp/iter63-r15-install-20261109-0CwgPSqi')
    prior = json.loads((prior_dir/'fixed-wheels.json').read_text())
    rows = []
    for prefix in ('back_trader_python-', 'bt_api_okx-', 'bt_api_binance-'):
        found = [row for row in prior if row['filename'].startswith(prefix)]
        if len(found) != 1:
            raise RuntimeError(('R11 fixed manifest mismatch', prefix))
        rows.append({**found[0], 'wheel_dir': str(prior_dir/'wheels')})
    staged = []
    for row in rows:
        source = Path(row['wheel_dir'])/row['filename']
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != row['sha256']:
            raise RuntimeError(('fixed wheel hash mismatch', source.name))
        destination = T/'wheels'/source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        staged.append({'source': str(source), 'filename': source.name, 'sha256': digest})
        print('FIXED', source.name, digest, flush=True)
    (T/'fixed-wheels.json').write_text(json.dumps(staged, indent=2)+'\n')


def plan(name):
    path = T/'plans'/f'{name}.txt'
    if not path.is_file():
        raise RuntimeError(('missing primary test plan', name))
    result = [line.strip() for line in path.read_text().splitlines() if line.strip() and not line.startswith('#')]
    if name == 'gateway' and result in (['tests/'], ['tests']):
        unexpected = {x for x in files(GATEWAY, False, 'tests') if x.endswith('.py')} - NEW_GATEWAY_TESTS
        if unexpected:
            raise RuntimeError(('unapproved untracked Gateway tests', sorted(unexpected)))
        available = files(GATEWAY, True, 'tests') | NEW_GATEWAY_TESTS
        result = sorted(x for x in available if Path(x).name.startswith('test_') and x.endswith('.py'))
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
    plans = {name: plan(name) for name in REPOS}
    allowed = {repo: files(repo, True, 'tests') | {x.split('::', 1)[0] for x in plans[name]} for name, (repo, _) in REPOS.items()}
    allowed[CTP] = files(CTP, True, 'tests') | {x.split('::', 1)[0] for x in plans['ctp']}
    allowed[SDK].add('conftest.py')
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
    for name, (repo, _) in REPOS.items():
        for rel in plans[name]:
            queue.append((name, repo, copy(name, repo, rel.split('::', 1)[0])))
        for rel in ('tests/__init__.py', 'tests/conftest.py', 'tests/conftest_test_data.py', 'tests/unit/__init__.py', 'tests/unit/conftest.py', 'tests/integration/__init__.py', 'tests/integration/conftest.py'):
            if rel in allowed[repo] and (repo/rel).is_file():
                queue.append((name, repo, copy(name, repo, rel)))
        (roots[name]/'selected-tests.txt').write_text('\n'.join(plans[name])+'\n')
    queue.append(('sdk', SDK, copy('sdk', SDK, 'conftest.py')))
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
    (T/'test-manifest.json').write_text(json.dumps(rows, indent=2)+'\n')
    print('test_files', len(rows), 'ast_visited', len(visited), flush=True)


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in {'snapshot', 'fixed', 'tests'}:
        raise SystemExit('usage: prepare.py snapshot|fixed|tests')
    if not (T/'SOURCE_FROZEN').is_file():
        raise SystemExit('R16 freeze marker absent; refusing staging')
    {'snapshot':snapshot, 'fixed':fixed, 'tests':tests}[sys.argv[1]]()

if __name__ == '__main__':
    main()
