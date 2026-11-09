import ast,hashlib,json,os,shutil,subprocess,sys
from pathlib import Path
T=Path('/tmp/iter63-r29-sdk-install-20261109-pht8FUZ4'); S=Path('/Users/yunjinqi/Documents/new_projects/bt_api_py'); C=S/'bt_api/bt_api_ctp'; P=Path(os.environ.get('R29_FREEZE_DIR',str(T/'primary-freeze'))); A=Path('/tmp/iter63-r26-ctp-acceptance-20261109-7xzFjES1'); OLD=Path('/tmp/iter63-r25-install-20261109-jsTH40Ui/wheels')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def files(repo,*args):return set(filter(None,subprocess.check_output(['git','-C',str(repo),'ls-files','-z',*args]).decode().split('\0')))
def safe(src,dst,rows,repo,relative,head,extra=None):
 p=Path(relative)
 if p.is_absolute() or '..' in p.parts or any(x.startswith('.env') or x in ('config.yaml','account_config.yaml') for x in p.parts) or src.is_symlink() or not src.is_file():raise RuntimeError(('invalid/private',str(src)))
 data=src.read_bytes();dst.parent.mkdir(parents=True,exist_ok=True)
 if dst.exists() and dst.read_bytes()!=data:raise RuntimeError(('collision',str(dst)))
 if not dst.exists():dst.write_bytes(data)
 item={'repo':str(repo),'source':str(src),'copy':str(dst),'relative':relative,'snapshot_head':head,'sha256':hashlib.sha256(data).hexdigest()};item.update(extra or {});rows.append(item)
cmd=sys.argv[1]; head=subprocess.check_output(['git','-C',str(S),'rev-parse','HEAD'],text=True).strip()
if cmd=='freeze':
 if (T/'SOURCE_FROZEN').exists():raise RuntimeError('already frozen')
 frozen=json.loads((P/'sdk-frozen-inputs.json').read_text()); assert frozen
 for x in frozen:
  p=S/x['path']
  if sha(p)!=x['sha256']:raise RuntimeError(('frozen mismatch',x['path']))
 selectors=json.loads((P/'selectors.json').read_text())['sdk'];assert len(selectors)==len(set(selectors))==14
 for name in ('sdk-frozen-inputs.json','sdk-owned-files.json','selectors.json'):shutil.copyfile(P/name,T/name)
 (T/'SOURCE_FROZEN').write_text('R29 SDK frozen inputs checked; 14 SDK selectors; fixed CTP final\n');print('FREEZE_CHECKED',len(frozen),len(selectors),'HEAD',head)
elif cmd=='snapshot':
 assert (T/'SOURCE_FROZEN').is_file() and not (T/'source').exists()
 tracked=files(S,'--','bt_api_py','pyproject.toml','setup.py','setup.cfg','README.md','MANIFEST.in','LICENSE')
 extra={x for x in files(S,'--others','--exclude-standard','--','bt_api_py') if x.endswith('.py')}
 allowed={'bt_api_py/gateway_api.py'}
 if extra-allowed:raise RuntimeError(('unexpected untracked runtime',sorted(extra-allowed)))
 rows=[]
 for rel in sorted(tracked|extra):safe(S/rel,T/'source/sdk'/rel,rows,S,rel,head)
 (T/'source-manifest.json').write_text(json.dumps(rows,indent=2)+'\n');print('SOURCE_ROWS',len(rows),'EXTRA',sorted(extra))
elif cmd=='tests':
 assert not (T/'test-manifest.json').exists()
 selected=json.loads((T/'selectors.json').read_text())['sdk'];tracked=files(S,'--','tests','conftest.py');allow=tracked|set(selected)
 # CTP helpers are copied from independently verified frozen acceptance mirror.
 crows=json.loads((A/'test-manifest.json').read_text());ctests={r['relative']:r for r in crows}
 ctphead=subprocess.check_output(['git','-C',str(C),'rev-parse','HEAD'],text=True).strip();rows=[];copied=set();queue=[]
 def sdkcopy(rel):
  if rel not in allow:raise RuntimeError(('unapproved SDK helper',rel))
  dst=T/'sdk-tests'/rel
  if rel not in copied:safe(S/rel,dst,rows,S,rel,head);copied.add(rel);queue.append(rel)
 for rel in selected+['conftest.py','tests/__init__.py','tests/conftest.py','tests/conftest_test_data.py','tests/unit/__init__.py','tests/unit/conftest.py','tests/integration/__init__.py','tests/integration/conftest.py']:
  if rel in allow and (S/rel).is_file():sdkcopy(rel)
 # Copy CTP helpers only when an SDK helper imports them; recurse locally.
 def ctpcopy(rel):
  r=ctests[rel];src=Path(r['copy']);original=Path(r['source']);dst=T/'sdk-tests/bt_api/bt_api_ctp'/rel
  if str(dst) in copied:return
  if sha(src)!=r['sha256'] or sha(original)!=r['sha256']:raise RuntimeError(('CTP helper drift',rel))
  safe(src,dst,rows,C,rel,ctphead,{'original':str(original),'upstream_ctp_manifest':str(A/'test-manifest.json')});copied.add(str(dst))
  for n in ast.walk(ast.parse(src.read_text(encoding='utf8'))):
   names=[]
   if isinstance(n,ast.Import):names=[x.name for x in n.names if x.name.startswith('test_')]
   elif isinstance(n,ast.ImportFrom) and not n.level and n.module and n.module.startswith('test_'):names=[n.module]
   elif isinstance(n,ast.Call) and n.args and isinstance(n.args[0],ast.Constant) and isinstance(n.args[0].value,str) and isinstance(n.func,ast.Attribute) and n.func.attr=='import_module' and n.args[0].value.startswith('test_'):names=[n.args[0].value]
   for name in names:
    child='tests/'+name+'.py'
    if child not in ctests:raise RuntimeError(('CTP helper missing frozen source',child))
    ctpcopy(child)
 seen=set()
 while queue:
  rel=queue.pop()
  if rel in seen:continue
  seen.add(rel)
  for node in ast.walk(ast.parse((S/rel).read_text(encoding='utf8'))):
   refs=[]
   if isinstance(node,ast.Import):refs=[x.name for x in node.names if x.name.startswith(('tests.','test_'))]
   elif isinstance(node,ast.ImportFrom) and not node.level and node.module:
    if node.module=='tests':refs=['tests.'+x.name for x in node.names]
    elif node.module.startswith('tests.'):
     path=Path(*node.module.split('.')).with_suffix('.py').as_posix()
     refs=[node.module] if path in allow else [node.module+'.'+x.name for x in node.names if (S/Path(*node.module.split('.'))/(x.name+'.py')).is_file()]
    elif node.module.startswith('test_'):refs=[node.module]
   elif isinstance(node,ast.Call) and node.args and isinstance(node.args[0],ast.Constant) and isinstance(node.args[0].value,str) and isinstance(node.func,ast.Attribute) and node.func.attr=='import_module' and node.args[0].value.startswith(('tests.','test_')):refs=[node.args[0].value]
   for ref in refs:
    if ref.startswith('tests.'):
     candidate=Path(*ref.split('.')).with_suffix('.py').as_posix()
     if candidate in allow:sdkcopy(candidate)
     else:raise RuntimeError(('unknown tests package helper',rel,ref))
    else:
     candidates=[(Path(p)/(ref+'.py')).as_posix() for p in ('tests/unit','tests','tests/integration')]; found=[x for x in candidates if x in allow and (S/x).is_file()];ct='tests/'+ref+'.py'
     if len(found)==1:sdkcopy(found[0])
     elif len(found)==0 and ct in ctests:ctpcopy(ct)
     else:raise RuntimeError(('ambiguous helper',rel,ref,found,ct in ctests))
 (T/'sdk-tests/selected-tests.txt').write_text('\n'.join(selected)+'\n');(T/'test-manifest.json').write_text(json.dumps(rows,indent=2)+'\n');print('TEST_ROWS',len(rows),'SDK_AST_FILES',len(seen),'CTP_FROZEN_HELPERS',sum(x.get('repo')==str(C) for x in rows))
elif cmd=='fixed':
 expected={'bt_api_base-':'67f2e489053c06cc154c8edb1f05015aa9ec8be77e9e723e270e9a726072671f','bt_api_gateway-':'52a4ac9f1b3c671eada2b3314f7a1766afccef78051109d02070e7b820abe685','bt_api_okx-':'2243f8427d282e53f08b50e88832b149dfde0729afcbd8b3e768eb7a81ce1c07','bt_api_binance-':'703f312d1889052293b49c390855f2df50d38084ced8a80029f4794ca6e1c5be','msgpack-':'a4b47ec7422bef149223786a87df80067ac65bfc7c0565e5cf1dfbdc40acee50'}
 (T/'wheels').mkdir();rows=[]
 for prefix,digest in expected.items():
  src,=OLD.glob(prefix+'*.whl')
  if sha(src)!=digest:raise RuntimeError(('wheel hash mismatch',src.name))
  shutil.copyfile(src,T/'wheels'/src.name);rows.append({'source':str(src),'filename':src.name,'sha256':digest})
 src,=Path('/tmp/iter63-r28-candidate3-20261109-ijqQ26LC/wheels').glob('back_trader_python-*.whl');digest='3435b1df02d50bdb5a6135605a86cc6de4b8a85c715d13885a8c04e7a7ba6981'
 if sha(src)!=digest:raise RuntimeError('R28 BT wheel hash mismatch')
 shutil.copyfile(src,T/'wheels'/src.name);rows.append({'source':str(src),'filename':src.name,'sha256':digest})
 src,=(A/'wheels').glob('bt_api_ctp-*.whl');digest='bf25c4c171ffbcf5e4cca872ce8f9d4d5454210f311ba28de2bb9947defbbc6a'
 if sha(src)!=digest:raise RuntimeError('CTP wheel hash mismatch')
 shutil.copyfile(src,T/'wheels'/src.name);rows.append({'source':str(src),'filename':src.name,'sha256':digest});(T/'fixed-wheels.json').write_text(json.dumps(rows,indent=2)+'\n');print('FIXED_WHEELS',len(rows))
else:raise SystemExit('invalid stage')
