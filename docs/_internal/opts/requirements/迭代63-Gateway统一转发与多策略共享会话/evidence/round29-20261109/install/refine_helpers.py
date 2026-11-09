from pathlib import Path
p=Path('/tmp/iter63-r29-sdk-install-20261109-pht8FUZ4/setup_harness.py');s=p.read_text()
a=s.index(' # Known dynamic CTP helpers:');b=s.index(' seen=set()',a)
s=s[:a]+''' # Copy CTP helpers only when an SDK helper imports them; recurse locally.
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
''' + s[b:]
s=s.replace("elif len(found)==0 and ct in ctests:pass", "elif len(found)==0 and ct in ctests:ctpcopy(ct)")
a=s.index(' # Explicitly public tracked sample fixtures');b=s.index(" (T/'sdk-tests/selected-tests.txt')",a);s=s[:a]+s[b:]
s=s.replace("'CTP_FROZEN_HELPERS',len(ctests)","'CTP_FROZEN_HELPERS',sum(x.get('repo')==str(C) for x in rows)")
p.write_text(s)
