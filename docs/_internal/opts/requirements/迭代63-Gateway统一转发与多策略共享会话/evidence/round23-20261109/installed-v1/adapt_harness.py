from pathlib import Path
T=Path('/tmp/iter63-r23-install-20261109-s5p4b4ec');P=Path('/tmp/iter63-r23-primary')
p=T/'prepare.py';s=p.read_text()
s=s.replace("    for name in ('base','bt'):","    for name in ('base','bt','ctp'):")
s=s.replace("        old={r['relative']:r['sha256'] for r in old_rows if r['repo']==str(repo)}", "        baseline_rows = json.loads(Path('/tmp/iter63-r21-install-20261109-QD2dgx3G/source-manifest.json').read_text()) if name == 'ctp' else old_rows\n        old={r['relative']:r['sha256'] for r in baseline_rows if r['repo']==str(repo)}")
s=s.replace("        for row in (r for r in old_rows if r['repo']==str(repo)):","        for row in (r for r in baseline_rows if r['repo']==str(repo)):")
s=s.replace("    rows=[]\n    for prefix,digest in expected.items():", """    rows=[]
    ctp_source=Path('/tmp/iter63-r21-install-20261109-QD2dgx3G/wheels/bt_api_ctp-2.1.0.dev63-cp311-cp311-macosx_11_0_arm64.whl')
    ctp_sha='74b01167b703b5b8e57418ef8dd9ce680b40bac35f1aa0d60a50f0bbe3e1d619'
    if hashlib.sha256(ctp_source.read_bytes()).hexdigest()!=ctp_sha: raise RuntimeError('R21 CTP wheel mismatch')
    (T/'wheels').mkdir(exist_ok=True);shutil.copyfile(ctp_source,T/'wheels'/ctp_source.name)
    rows.append({'source':str(ctp_source),'filename':ctp_source.name,'sha256':ctp_sha,'provenance':'R21 verified wheel with R19 native payload'})
    for prefix,digest in expected.items():""")
s=s.replace("    (T/'fixed-wheels.json').write_text(json.dumps(rows,indent=2)+'\\n')", """    (T/'fixed-wheels.json').write_text(json.dumps(rows,indent=2)+'\\n')
    msgpack=Path('/tmp/iter63-r22-e044-install-20261109-K3FbuXsv/dependency-wheels/msgpack-1.2.4-cp311-cp311-macosx_11_0_arm64.whl')
    sha='a4b47ec7422bef149223786a87df80067ac65bfc7c0565e5cf1dfbdc40acee50'
    if hashlib.sha256(msgpack.read_bytes()).hexdigest()!=sha: raise RuntimeError('R22 msgpack wheel mismatch')
    shutil.copyfile(msgpack,T/'wheels'/msgpack.name)
    (T/'msgpack-wheel-manifest.json').write_text(json.dumps({'source':str(msgpack),'filename':msgpack.name,'sha256':sha,'version':'1.2.4','provenance':'R22 verified wheel'},indent=2)+'\\n')""")
p.write_text(s)
p=T/'run.py';s=p.read_text().replace("KINDS = ('gateway', 'ctp', 'sdk')","KINDS = ('gateway', 'sdk')")
s=s.replace('if len(wheels) != 4:', 'if len(wheels) != 6:').replace('expected four fixed wheels before build','expected five fixed and msgpack wheels before build')
s=s.replace('if len(wheels) != 7:', 'if len(wheels) != 8:').replace('expected four fixed and three rebuilt wheels','expected five fixed, msgpack and two rebuilt wheels')
a=s.index("    if stage == 'build-ctp':");b=s.index("    if stage == 'install':",a);s=s[:a]+s[b:]
s=s.replace(",'build-ctp'}", "}")
p.write_text(s)
p=T/'capture_selectors.py';s=p.read_text().replace("{'gateway', 'ctp', 'sdk'}","{'gateway', 'sdk'}");p.write_text(s)
p=T/'verify.py';s=p.read_text().replace("staged in {'gateway','ctp','sdk'}", "staged in {'gateway','sdk'}")
a=s.index("native=json.loads((T/'ctp-native-reuse-manifest.json')");b=s.index('layout=json.loads',a)
s=s[:a]+'''native=next((TARGET/'bt_api_ctp/ctp').glob('_ctp*.so'))
if hashlib.sha256(native.read_bytes()).hexdigest()!='b49b009529b197025afe6561285fda428959240b9de515fa76bfa165719971f5': raise RuntimeError('R21_CTP_NATIVE_MISMATCH')
print('CTP_REUSED_R21_NATIVE_SHA256',hashlib.sha256(native.read_bytes()).hexdigest(),flush=True)
msgpack=json.loads((T/'msgpack-wheel-manifest.json').read_text());mp_wheel=T/'wheels'/msgpack['filename']
if hashlib.sha256(mp_wheel.read_bytes()).hexdigest()!=msgpack['sha256']: raise RuntimeError('MSGPACK_WHEEL_DRIFT')
import msgpack as mp
mp_dist=importlib.metadata.distribution('msgpack')
if mp_dist.version!='1.2.4' or not Path(mp.__file__).resolve().is_relative_to(TARGET) or not Path(mp_dist._path).resolve().is_relative_to(TARGET): raise RuntimeError('MSGPACK_ORIGIN_OR_VERSION')
with zipfile.ZipFile(mp_wheel) as archive:
    for item in (x for x in archive.namelist() if x.startswith('msgpack/') and not x.endswith('/')):
        if (TARGET/item).read_bytes()!=archive.read(item): raise RuntimeError(('MSGPACK_TARGET_DRIFT',item))
print('TEMP_MSGPACK_VERIFIED',mp_dist.version,mp.__file__,msgpack['sha256'],flush=True)
''' +s[b:];p.write_text(s)
p=T/'run_installed.py';s=p.read_text();old="    import pytest\n    paths =";new="""    import importlib.metadata
    import msgpack
    version=importlib.metadata.version('msgpack')
    if version!='1.2.4' or not Path(msgpack.__file__).resolve().is_relative_to(TARGET.resolve()): raise RuntimeError('MSGPACK_TARGET_REQUIRED')
    print('TEMP_MSGPACK',version,msgpack.__file__,flush=True)
    import pytest
    paths ="""
if old not in s:raise RuntimeError('installed runner marker absent')
p.write_text(s.replace(old,new))
p=P/'run.py';s=p.read_text().replace("if KIND not in {'gateway','ctp','sdk'}:","if KIND not in {'gateway','sdk'}:")
s=s.replace("paths=[BOOT,ROOT,*roots,*extra]", "paths=[BOOT,OUT/'dependencies',ROOT,*roots,*extra]")
old="    import pytest\n    plugins=";new="""    import importlib.metadata
    import msgpack
    if importlib.metadata.version('msgpack')!='1.2.4' or not Path(msgpack.__file__).resolve().is_relative_to((OUT/'dependencies').resolve()): raise RuntimeError('SOURCE_TEMP_MSGPACK_REQUIRED')
    print('TEMP_MSGPACK',importlib.metadata.version('msgpack'),msgpack.__file__,flush=True)
    import pytest
    plugins="""
if old not in s:raise RuntimeError('source runner marker absent')
p.write_text(s.replace(old,new))
p=P/'run_source.py';s=p.read_text().replace("{'gateway','ctp','sdk'}", "{'gateway','sdk'}").replace('gateway|ctp|sdk','gateway|sdk');p.write_text(s)
print('R23 draft reuse CTP and msgpack plan wired; no snapshot/build/test')
