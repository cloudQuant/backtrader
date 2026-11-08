"""Freeze public CTP source/selected tests; use only R25 fixed wheel bytes."""
import ast,hashlib,json,shutil,subprocess
from pathlib import Path
T=Path('/tmp/iter63-r26-ctp-acceptance-20261109-7xzFjES1');repo=Path('/Users/yunjinqi/Documents/new_projects/bt_api_py/bt_api/bt_api_ctp')
if not (T/'SOURCE_FROZEN').is_file():raise SystemExit('CTP freeze required')
head=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
def gitfiles(*args):return set(filter(None,subprocess.check_output(['git','-C',str(repo),'ls-files','-z',*args]).decode().split('\0')))
def copy(rel,dst,rows):
    p=Path(rel)
    if p.is_absolute() or '..' in p.parts or any(x.startswith('.env') or x in ('config.yaml','account_config.yaml') for x in p.parts):raise RuntimeError(('private path',rel))
    src=repo/p
    if src.is_symlink() or not src.is_file():raise RuntimeError(('invalid public path',rel))
    data=src.read_bytes();dst.parent.mkdir(parents=True,exist_ok=True)
    if dst.exists() and dst.read_bytes()!=data:raise RuntimeError(('copy collision',str(dst)))
    dst.write_bytes(data);rows.append({'repo':str(repo),'source':str(src),'copy':str(dst),'relative':rel,'snapshot_head':head,'sha256':hashlib.sha256(data).hexdigest()})
if __import__('sys').argv[1]=='snapshot':
    if (T/'source').exists():raise RuntimeError('source exists')
    original=json.loads(Path('/tmp/iter63-r26-acceptance/ctp-frozen-inputs.json').read_text())
    for row in original:
        if hashlib.sha256(Path(row['path']).read_bytes()).hexdigest()!=row['sha256']:raise RuntimeError(('primary frozen SHA drift',row['path']))
    paths=gitfiles('--','src/bt_api_ctp','pyproject.toml','setup.py','setup.cfg','README.md','LICENSE','MANIFEST.in')
    extra=gitfiles('--others','--exclude-standard','--','src/bt_api_ctp')
    if extra!={'src/bt_api_ctp/gateway_instrument_query.py'}:raise RuntimeError(('unexpected CTP untracked runtime',sorted(extra)))
    rows=[]
    for rel in sorted(paths|extra):copy(rel,T/'source/ctp'/rel,rows)
    (T/'source-manifest.json').write_text(json.dumps(rows,indent=2)+'\n');print('CTP_SOURCE_ROWS',len(rows),'HEAD',head,flush=True)
elif __import__('sys').argv[1]=='tests':
    if (T/'test-manifest.json').exists():raise RuntimeError('test manifest exists')
    selectors=json.loads((T/'selectors.json').read_text())['ctp'];tracked=gitfiles('--','tests');extra={'tests/test_iter63_async_instrument_query.py','tests/test_iter63_gateway_instrument_query.py','tests/test_iter63_gateway_connection_state.py'}
    allowed=tracked|extra
    if len(selectors)!=19 or len(set(selectors))!=19:raise RuntimeError('unexpected selector count')
    queue=list(selectors)+(['tests/conftest.py'] if 'tests/conftest.py' in allowed else []);seen=set();rows=[]
    while queue:
        rel=queue.pop()
        if rel in seen:continue
        if rel not in allowed:raise RuntimeError(('unapproved test helper',rel))
        seen.add(rel);copy(rel,T/'ctp-tests'/rel,rows)
        for node in ast.walk(ast.parse((repo/rel).read_text(encoding='utf-8'))):
            names=[]
            if isinstance(node,ast.Import):names=[a.name for a in node.names if a.name.startswith('test_')]
            elif isinstance(node,ast.ImportFrom) and not node.level and node.module and node.module.startswith('test_'):names=[node.module]
            for name in names:
                helper='tests/'+name.replace('.','/')+'.py'
                if helper not in allowed:raise RuntimeError(('unknown test helper',name))
                queue.append(helper)
    (T/'test-manifest.json').write_text(json.dumps(rows,indent=2)+'\n');(T/'ctp-tests/selected-tests.txt').write_text('\n'.join(selectors)+'\n');print('CTP_TEST_ROWS',len(rows),'SELECTED',len(selectors),flush=True)
elif __import__('sys').argv[1]=='fixed':
    prior=Path('/tmp/iter63-r25-install-20261109-jsTH40Ui/wheels'); expected={'back_trader_python-':'5b24542e50cfb5d78234a7345dad52e961531a5da5768c5870a576eb0d65c227','bt_api_base-':'67f2e489053c06cc154c8edb1f05015aa9ec8be77e9e723e270e9a726072671f','bt_api_gateway-':'52a4ac9f1b3c671eada2b3314f7a1766afccef78051109d02070e7b820abe685','bt_api_py-':'b879552e944bacec1eb3e72e1fbb54b497e153fa44fb13885a5f1422fd327439','bt_api_okx-':'2243f8427d282e53f08b50e88832b149dfde0729afcbd8b3e768eb7a81ce1c07','bt_api_binance-':'703f312d1889052293b49c390855f2df50d38084ced8a80029f4794ca6e1c5be','msgpack-':'a4b47ec7422bef149223786a87df80067ac65bfc7c0565e5cf1dfbdc40acee50'}
    if (T/'wheels').exists():raise RuntimeError('wheels already staged')
    (T/'wheels').mkdir();rows=[]
    for prefix,sha in expected.items():
        source,=list(prior.glob(prefix+'*.whl'))
        if hashlib.sha256(source.read_bytes()).hexdigest()!=sha:raise RuntimeError(('fixed wheel mismatch',source.name))
        shutil.copyfile(source,T/'wheels'/source.name);rows.append({'source':str(source),'filename':source.name,'sha256':sha,'provenance':'R25 verified wheel'})
    (T/'fixed-wheels.json').write_text(json.dumps(rows,indent=2)+'\n');print('FIXED_R25_WHEELS',len(rows),flush=True)
else:raise SystemExit('usage: prepare.py snapshot|tests|fixed')
