"""Tracked, explicitly scoped source snapshot; invoke only after root freeze."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

T = Path('/tmp/iter63-r10-packaging-Zc9un7t2')
SDK = Path('/Users/yunjinqi/Documents/new_projects/bt_api_py')
if not (T / 'SOURCE_FROZEN').is_file():
    raise RuntimeError('source freeze not recorded')
rows = []
for package, repo, runtime in (
    ('ctp', SDK / 'bt_api/bt_api_ctp', 'src/bt_api_ctp'),
    ('sdk', SDK, 'bt_api_py'),
):
    tracked = subprocess.check_output(['git', '-C', str(repo), 'ls-files', '-z', '--cached', '--',
        'pyproject.toml', 'setup.py', 'setup.cfg', 'README.md', 'MANIFEST.in', 'LICENSE', runtime]).decode().split('\0')
    untracked = subprocess.check_output(['git', '-C', str(repo), 'ls-files', '-z', '--others',
        '--exclude-standard', '--', runtime]).decode().split('\0')
    if any(x.endswith('.py') for x in untracked):
        raise RuntimeError((package, 'unreviewed runtime files'))
    count = 0
    for relative in sorted(set(filter(None, tracked))):
        src = repo / relative
        if src.is_symlink() or not src.is_file():
            raise RuntimeError((package, 'non-regular or missing tracked file', relative))
        if src.name.startswith('.env') or src.name in ('config.yaml', 'account_config.yaml'):
            raise RuntimeError((package, 'private path excluded', relative))
        dest = T / 'source' / package / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        digest = hashlib.sha256(src.read_bytes()).hexdigest()
        rows.append({'package': package, 'path': relative, 'source': str(src),
                     'snapshot': str(dest), 'sha256': digest})
        count += 1
    print(package, 'HEAD', subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip(), 'files', count, flush=True)
(T / 'source-manifest.json').write_text(json.dumps(rows, indent=2) + '\n')
