import os,shutil,subprocess,hashlib,json
from pathlib import Path
T=Path('/tmp/iter63-r09-packaging-ySGAYCmv/final'); sdk=Path('/Users/yunjinqi/Documents/new_projects/bt_api_py')
items=[('gateway',sdk/'bt_api/bt_api_gateway','src/bt_api_gateway',{'src/bt_api_gateway/account_read_model.py'}),('ctp',sdk/'bt_api/bt_api_ctp','src/bt_api_ctp',set()),('sdk',sdk,'bt_api_py',set())]
manifest=[]
for name,repo,runtime,extra in items:
    base=['pyproject.toml','setup.py','setup.cfg','README.md','MANIFEST.in','LICENSE',runtime]
    get=lambda *a: subprocess.check_output(['git','-C',str(repo),'ls-files','-z',*a]).decode().split('\0')
    untracked={x for x in get('--others','--exclude-standard','--',runtime) if x.endswith('.py')}
    if untracked-extra: raise RuntimeError((name,'unreviewed runtime modules',sorted(untracked-extra)))
    paths={x for x in get('--cached','--',*base) if x}|extra
    for rel in sorted(paths):
        src=repo/rel
        if src.name.startswith('.env') or src.name in ('config.yaml','account_config.yaml') or not (src.is_file() or src.is_symlink()):
            if rel in extra: raise RuntimeError('missing explicit file '+rel)
            continue
        dst=T/'source'/name/rel; dst.parent.mkdir(parents=True,exist_ok=True)
        if src.is_symlink(): os.symlink(os.readlink(src),dst)
        else: shutil.copy2(src,dst)
        if src.is_file(): manifest.append({'package':name,'path':rel,'source':str(src),'snapshot':str(dst),'sha256':hashlib.sha256(src.read_bytes()).hexdigest()})
    print(name,'HEAD',subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip(),'files',sum(x['package']==name for x in manifest),flush=True)
(T/'source-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
