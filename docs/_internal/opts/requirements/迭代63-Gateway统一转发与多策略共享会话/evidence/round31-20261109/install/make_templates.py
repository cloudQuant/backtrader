from pathlib import Path
import shutil
T=Path('/tmp/iter63-r31-install-20261109-mz1EwW5H');R=Path('/tmp/iter63-r30-install-20261109-ySExhdil')
for name in ('prepare.py','run.py','run_installed.py','capture_selectors.py','prepare_sdk_layout.py','guard_preflight.py','audit_run.py','capture_editable_deps.py'):
 s=(R/name).read_text().replace(str(R),str(T)).replace('R30_','R31_').replace('R30 ','R31 ').replace('/tmp/iter63-r30-primary/','/tmp/iter63-r31-primary/')
 if name=='prepare.py':
  s=s.replace("for name, (repo, runtime) in REPOS.items():\n        paths =", "for name, (repo, runtime) in REPOS.items():\n        if name not in {'sdk', 'bt'}: continue\n        paths =")
  a=s.index('def fixed():');b=s.index('\ndef plan(name):',a)
  s=s[:a]+'''def fixed():
    previous=Path('/tmp/iter63-r30-install-20261109-ySExhdil');wheels=previous/'wheels';old=json.loads((previous/'source-manifest.json').read_text());rows=[]
    expected={'bt_api_base-':'6adcaf19163bf8a020f3e39653b217280c8d7244c2f3903a4cb5b4b0d6ca70a0','bt_api_gateway-':'696966a55fe378189993c7f150a2fff2e2bc23ce25d3f8b5bdb792b9b7b7729c','bt_api_ctp-':'668e65387d088dd0994fab18c1e151a6e42011cfea4dc8c4275f5c014860b00f','bt_api_okx-':'2243f8427d282e53f08b50e88832b149dfde0729afcbd8b3e768eb7a81ce1c07','bt_api_binance-':'703f312d1889052293b49c390855f2df50d38084ced8a80029f4794ca6e1c5be','msgpack-':'a4b47ec7422bef149223786a87df80067ac65bfc7c0565e5cf1dfbdc40acee50'}
    if (T/'wheels').exists():raise RuntimeError('wheels already exist')
    (T/'wheels').mkdir()
    for name in ('base','gateway','ctp'):
        repo,_=REPOS[name];head=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip();selected=[r for r in old if r['repo']==str(repo)]
        if not selected:raise RuntimeError(('fixed source missing',name))
        for r in selected:
            source=Path(r['source']);blob=subprocess.run(['git','-C',str(repo),'show',head+':'+r['relative']],capture_output=True,check=False)
            if hashlib.sha256(source.read_bytes()).hexdigest()!=r['sha256'] or blob.returncode or hashlib.sha256(blob.stdout).hexdigest()!=r['sha256']:raise RuntimeError(('fixed source/commit drift',name,r['relative']))
        print('FIXED_COMMIT_SOURCE_R30_MATCH',name,head,len(selected),flush=True)
    for prefix,digest in expected.items():
        source,=wheels.glob(prefix+'*.whl')
        if hashlib.sha256(source.read_bytes()).hexdigest()!=digest:raise RuntimeError(('fixed wheel drift',prefix))
        shutil.copyfile(source,T/'wheels'/source.name);rows.append({'source':str(source),'filename':source.name,'sha256':digest})
    (T/'fixed-wheels.json').write_text(json.dumps(rows,indent=2)+'\\n')
    print('FIXED_WHEELS',len(rows),flush=True)

''' + s[b:]
  s=s.replace("if 'base' in plans:\n        for rel", "if 'base' in plans:\n        for rel")
 if name=='capture_selectors.py':s=s.replace("{'base', 'gateway', 'ctp', 'sdk', 'bt'}","{'sdk', 'bt'}")
 if name=='run.py':
  s=s.replace("for kind in ('base', 'gateway', 'sdk', 'bt'):","for kind in ('sdk', 'bt'):")
  s=s.replace("for kind in ('base', 'gateway', 'sdk', 'bt')]])","for kind in ('sdk', 'bt')]])")
  s=s.replace("if len(wheels) != 3:","if len(wheels) != 6:").replace('expected three fixed wheels before build','expected six fixed wheels before build')
  a=s.index("    if stage == 'build-ctp':");b=s.index("    if stage == 'install':",a);s=s[:a]+"    if stage == 'build-ctp':\n        raise RuntimeError('R31 reuses verified CTP wheel; no build')\n"+s[b:]
  s=s.replace('expected three fixed and five rebuilt wheels','expected six fixed and two rebuilt wheels')
 if name=='run_installed.py':s=s.replace("{'base', 'gateway', 'ctp', 'sdk', 'bt'}", "{'sdk', 'bt'}")
 (T/name).write_text(s)
shutil.copytree(R/'bootstrap',T/'bootstrap',ignore=shutil.ignore_patterns('__pycache__'))
for p in (T/'bootstrap').glob('*.py'):p.write_text(p.read_text().replace(str(R),str(T)).replace('R30_','R31_'))
