import os, shutil, subprocess
from pathlib import Path
T=Path('/tmp/iter63-r08-packaging-j8KrE0I2')
items=[('bt',Path('/Users/yunjinqi/Documents/new_projects/backtrader'),'backtrader',{'backtrader/live_state/gateway_pending.py'}),('sdk',Path('/Users/yunjinqi/Documents/new_projects/bt_api_py'),'bt_api_py',set())]
for name,repo,runtime,extra in items:
    base=['pyproject.toml','setup.py','setup.cfg','README.md','MANIFEST.in','LICENSE',runtime]
    get=lambda *args: subprocess.check_output(['git','-C',str(repo),'ls-files','-z',*args]).decode().split('\0')
    untracked={x for x in get('--others','--exclude-standard','--',runtime) if x.endswith('.py')}
    assert not untracked-extra, (name,sorted(untracked-extra))
    paths={x for x in get('--cached','--',*base) if x}|extra
    n=0
    for rel in sorted(paths):
        src=repo/rel
        if src.name.startswith('.env') or src.name in ('config.yaml','account_config.yaml') or not (src.is_file() or src.is_symlink()):
            if rel in extra: raise RuntimeError('missing explicit file '+rel)
            continue
        dst=T/'source'/name/rel; dst.parent.mkdir(parents=True,exist_ok=True)
        if src.is_symlink(): os.symlink(os.readlink(src),dst)
        else: shutil.copy2(src,dst)
        n+=1
    print(name,'files',n,'HEAD',subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip(),flush=True)
