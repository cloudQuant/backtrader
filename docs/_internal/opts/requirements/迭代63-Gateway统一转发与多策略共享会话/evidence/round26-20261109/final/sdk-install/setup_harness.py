import ast,hashlib,json,os,shutil,subprocess,sys
from pathlib import Path
T=Path('/tmp/iter63-r26-sdk-install-20261109-xAIrOrDl'); S=Path('/Users/yunjinqi/Documents/new_projects/bt_api_py'); C=S/'bt_api/bt_api_ctp'; P=Path('/tmp/iter63-r26-sdk-acceptance'); A=Path('/tmp/iter63-r26-ctp-acceptance-20261109-7xzFjES1'); OLD=Path('/tmp/iter63-r25-install-20261109-jsTH40Ui/wheels')
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
 frozen=json.loads((P/'sdk-frozen-inputs.json').read_text()); assert len(frozen)==55
 for x in frozen:
  p=S/x['path']
  if sha(p)!=x['sha256']:raise RuntimeError(('frozen mismatch',x['path']))
 selectors=json.loads((P/'selectors.json').read_text())['sdk'];assert len(selectors)==len(set(selectors))==42
 for name in ('sdk-frozen-inputs.json','sdk-owned-files.json','selectors.json'):shutil.copyfile(P/name,T/name)
 (T/'SOURCE_FROZEN').write_text('R26 SDK 55 frozen input hashes checked; 42 SDK selectors; fixed CTP final\n');print('FREEZE_CHECKED',len(frozen),len(selectors),'HEAD',head)
elif cmd=='snapshot':
 assert (T/'SOURCE_FROZEN').is_file() and not (T/'source').exists()
 tracked=files(S,'--','bt_api_py','pyproject.toml','setup.py','setup.cfg','README.md','MANIFEST.in','LICENSE')
 extra={x for x in files(S,'--others','--exclude-standard','--','bt_api_py') if x.endswith('.py')}
 allowed={'bt_api_py/gateway_instrument_service.py','bt_api_py/gateway_instrument_spec_codec.py','bt_api_py/gateway_strategy_instrument.py','bt_api_py/gateway_settlement.py'}
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
 # Known dynamic CTP helpers: include all 22 prior frozen CTP test files, preserving public bytes.
 for rel,r in sorted(ctests.items()):
  src=Path(r['copy']); original=Path(r['source'])
  if sha(src)!=r['sha256'] or sha(original)!=r['sha256']:raise RuntimeError(('CTP helper drift',rel))
  safe(src,T/'sdk-tests/bt_api/bt_api_ctp'/rel,rows,C,rel,ctphead,{'original':str(original),'upstream_ctp_manifest':str(A/'test-manifest.json')})
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
     elif len(found)==0 and ct in ctests:pass
     else:raise RuntimeError(('ambiguous helper',rel,ref,found,ct in ctests))
 # Explicitly public tracked sample fixtures, no glob or real config.
 for name in ('unconfigured-client.yaml','strategy-readonly.yaml','portfolio-analysis-client.yaml','account-service.yaml','portfolio-analysis-service.yaml'):
  rel='examples/services/'+name
  if rel not in files(S,'--',rel):raise RuntimeError(('not tracked',rel))
  safe(S/rel,T/'sdk-tests'/rel,rows,S,rel,head)
 (T/'sdk-tests/selected-tests.txt').write_text('\n'.join(selected)+'\n');(T/'test-manifest.json').write_text(json.dumps(rows,indent=2)+'\n');print('TEST_ROWS',len(rows),'SDK_AST_FILES',len(seen),'CTP_FROZEN_HELPERS',len(ctests))
elif cmd=='fixed':
 expected={'back_trader_python-':'5b24542e50cfb5d78234a7345dad52e961531a5da5768c5870a576eb0d65c227','bt_api_base-':'67f2e489053c06cc154c8edb1f05015aa9ec8be77e9e723e270e9a726072671f','bt_api_gateway-':'52a4ac9f1b3c671eada2b3314f7a1766afccef78051109d02070e7b820abe685','bt_api_okx-':'2243f8427d282e53f08b50e88832b149dfde0729afcbd8b3e768eb7a81ce1c07','bt_api_binance-':'703f312d1889052293b49c390855f2df50d38084ced8a80029f4794ca6e1c5be','msgpack-':'a4b47ec7422bef149223786a87df80067ac65bfc7c0565e5cf1dfbdc40acee50'}
 (T/'wheels').mkdir();rows=[]
 for prefix,digest in expected.items():
  src,=OLD.glob(prefix+'*.whl')
  if sha(src)!=digest:raise RuntimeError(('wheel hash mismatch',src.name))
  shutil.copyfile(src,T/'wheels'/src.name);rows.append({'source':str(src),'filename':src.name,'sha256':digest})
 src,=(A/'wheels').glob('bt_api_ctp-*.whl');digest='bf25c4c171ffbcf5e4cca872ce8f9d4d5454210f311ba28de2bb9947defbbc6a'
 if sha(src)!=digest:raise RuntimeError('CTP wheel hash mismatch')
 shutil.copyfile(src,T/'wheels'/src.name);rows.append({'source':str(src),'filename':src.name,'sha256':digest});(T/'fixed-wheels.json').write_text(json.dumps(rows,indent=2)+'\n');print('FIXED_WHEELS',len(rows))
else:raise SystemExit('invalid stage')
