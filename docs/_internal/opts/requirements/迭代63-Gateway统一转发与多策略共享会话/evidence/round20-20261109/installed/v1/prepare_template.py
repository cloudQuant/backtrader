from pathlib import Path
T=Path('/tmp/iter63-r20-install-20261109-x3vllCQQ')
p=T/'capture_selectors.py';s=p.read_text().replace("not {'base', 'gateway', 'ctp', 'sdk'}.issubset(plans) or set(plans) - {'base', 'gateway', 'ctp', 'sdk', 'bt'}", "set(plans) != {'sdk'}");p.write_text(s)
p=T/'prepare.py';s=p.read_text();a=s.index('def fixed():');b=s.index('\ndef plan(name):',a)
s=s[:a]+'''def fixed():
    if (T/'fixed-wheels.json').exists(): raise RuntimeError('fixed wheel staging exists')
    previous=Path('/tmp/iter63-r19-install-20261109-uQ78MEA5')
    old_rows=json.loads((previous/'source-manifest.json').read_text())
    new_rows=json.loads((T/'source-manifest.json').read_text())
    heads={'base':'f117c0bea16e77bee87451d8c1dbe3ba790f705c',
           'gateway':'ecb98a0d1f598dc33ae112829dc958a60846058b',
           'ctp':'abd8bf320f396ea271f974cf59659bfd0190a78c'}
    for name in ('base','gateway','ctp','bt'):
        repo,_=REPOS[name]
        head=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
        if name in heads and head!=heads[name]: raise RuntimeError(('fixed HEAD changed',name,head))
        old={r['relative']:r['sha256'] for r in old_rows if r['repo']==str(repo)}
        new={r['relative']:r['sha256'] for r in new_rows if r['repo']==str(repo)}
        if not old or old!=new: raise RuntimeError(('R19 source manifest mismatch',name,sorted(old.keys()^new.keys()),sorted(k for k in old.keys()&new.keys() if old[k]!=new[k])))
        for row in (r for r in old_rows if r['repo']==str(repo)):
            if hashlib.sha256(Path(row['copy']).read_bytes()).hexdigest()!=row['sha256']: raise RuntimeError(('R19 snapshot drift',row['copy']))
            blob=subprocess.run(['git','-C',str(repo),'show',head+':'+row['relative']],capture_output=True,check=False)
            if blob.returncode or hashlib.sha256(blob.stdout).hexdigest()!=row['sha256']: raise RuntimeError(('fixed commit/source mismatch',name,row['relative']))
        print('FIXED_R19_SOURCE_MANIFEST_HEAD_MATCH',name,head,len(old),flush=True)
    expected={
     'back_trader_python-':'792bad705c3f14a41c519322e6bee7c2cbae15faf33da622e895d9e2a743b4a7',
     'bt_api_base-':'67f2e489053c06cc154c8edb1f05015aa9ec8be77e9e723e270e9a726072671f',
     'bt_api_gateway-':'eca010352ae5bd4d1c9f134a70b5627641bde80d8b8af3add437fa29cfb67a30',
     'bt_api_ctp-':'56e9618be0202ea2c935d784179201f5ea9f79b9656398ad83727ad015485134',
     'bt_api_okx-':'2243f8427d282e53f08b50e88832b149dfde0729afcbd8b3e768eb7a81ce1c07',
     'bt_api_binance-':'703f312d1889052293b49c390855f2df50d38084ced8a80029f4794ca6e1c5be',}
    rows=[]
    for prefix,digest in expected.items():
        found=list((previous/'wheels').glob(prefix+'*.whl'))
        if len(found)!=1 or hashlib.sha256(found[0].read_bytes()).hexdigest()!=digest: raise RuntimeError(('R19 fixed wheel missing or mismatch',prefix))
        source=found[0];target=T/'wheels'/source.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        rows.append({'source':str(source),'filename':source.name,'sha256':digest,'provenance':'R19 verified wheel'})
        print('FIXED_R19',source.name,digest,flush=True)
    (T/'fixed-wheels.json').write_text(json.dumps(rows,indent=2)+'\\n')

''' +s[b:];p.write_text(s)
p=T/'run.py';s=p.read_text().replace("for kind in ('base', 'gateway', 'ctp', 'sdk'):","for kind in ('sdk',):").replace('if len(wheels) != 3:', 'if len(wheels) != 6:').replace('expected three fixed wheels before build','expected six fixed wheels before build').replace("for kind in ('base', 'gateway', 'ctp', 'sdk')]])","for kind in ('sdk',)]])").replace('expected three fixed and four rebuilt wheels','expected six fixed and one rebuilt wheel')
s=s.replace("    env.update({'TMPDIR':", "    for key in tuple(env):\n        if key.startswith(('CTP_', 'OKX_', 'BINANCE_', 'HTX_', 'IB_')):\n            env.pop(key, None)\n    env.update({'TMPDIR':")
p.write_text(s)
p=T/'verify.py';s=p.read_text().replace("'REUSED_R18' if staged == 'bt' else 'REBUILT'", "'REBUILT' if staged == 'sdk' else 'REUSED_R19'")
s=s.replace("if row['filename'].startswith('back_trader_python-'):", "if row['filename'].startswith(('back_trader_python-', 'bt_api_base-', 'bt_api_gateway-', 'bt_api_ctp-')):")
a=s.index("for row in json.loads((T/'ctp-relocation-manifest.json')");s=s[:a]+'''target = list((TARGET/'bt_api_ctp/ctp').glob('_ctp*.so'))
if len(target)!=1 or hashlib.sha256(target[0].read_bytes()).hexdigest()!='b49b009529b197025afe6561285fda428959240b9de515fa76bfa165719971f5':
    raise RuntimeError('CTP_R19_EXTENSION_MISMATCH')
print('CTP_REUSED_R19_EXTENSION_SHA256',hashlib.sha256(target[0].read_bytes()).hexdigest(),flush=True)
layout=json.loads((T/'sdk-layout-manifest.json').read_text())
for row in layout['links']:
    link=Path(row['link']);expected=Path(row['target']).resolve()
    if not link.is_symlink() or link.resolve()!=expected or not expected.is_relative_to(TARGET): raise RuntimeError(('SDK_LAYOUT_DRIFT',str(link)))
print('SDK_LAYOUT_LINKS_RESOLVE_INSTALLED_TARGET',len(layout['links']),flush=True)
print('GAP_SDK_ISOLATED_MINUS_I_CHILD_NO_SITECUSTOMIZE see sdk-minus-i-audit-gap.md',flush=True)
print('NO_FULL_RESOLVER_NO_ACCOUNT_CONNECTIONS',flush=True)
''';p.write_text(s)
p=T/'source-runner/run.py';s=p.read_text();s=s.replace("OUT=Path('","for key in tuple(os.environ):\n    if key.startswith(('CTP_', 'OKX_', 'BINANCE_', 'HTX_', 'IB_')):\n        os.environ.pop(key, None)\nOUT=Path('",1)
s=s.replace("    plan=Path(os.environ.get('R20_SELECTORS',str(OUT/'selectors.json')))","    if not (OUT/'SOURCE_FROZEN').is_file(): raise RuntimeError('SOURCE_FREEZE required')\n    plan=Path(os.environ.get('R20_SELECTORS',str(OUT/'selectors.json')))")
p.write_text(s)
print('R20 install/source harness adapted, no stage executed')
