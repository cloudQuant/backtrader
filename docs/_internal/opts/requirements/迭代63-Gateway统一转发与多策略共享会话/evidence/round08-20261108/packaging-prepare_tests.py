import ast, hashlib, shutil, subprocess
from pathlib import Path
T=Path('/tmp/iter63-r08-packaging-j8KrE0I2'); BT=Path('/Users/yunjinqi/Documents/new_projects/backtrader'); SDK=Path('/Users/yunjinqi/Documents/new_projects/bt_api_py')
selected=['unit/test_iter63_gateway_host_contracts.py','unit/test_iter63_gateway_direct_client.py','unit/test_iter63_direct_identity_projection.py','test_iter63_direct_identity_keys.py','test_iter62_direct_write.py','test_iter63_direct_error_policy.py','integration/test_iter63_gateway_direct_dispatch.py','integration/test_iter63_gateway_client_processes.py']
manifest=[]
def copy(src,dst):
    b=src.read_bytes(); dst.parent.mkdir(parents=True,exist_ok=True); dst.write_bytes(b); manifest.append(f'{hashlib.sha256(b).hexdigest()} {src} -> {dst}')
for name,repo in [('bt',BT),('sdk',SDK)]:
    root=T/(name+'-tests'); (root/'tests').mkdir(parents=True,exist_ok=True)
    if name=='bt':
        raw=subprocess.check_output(['git','-C',str(repo),'ls-files','-z','--cached','--others','--exclude-standard','--','tests/unit/live_state','tests/unit/brokers/direct']).decode().split('\0')
        names={p for p in raw if p.endswith('.py')}
        names.update(p for p in ['tests/__init__.py','tests/conftest.py','tests/conftest_test_data.py','tests/unit/__init__.py','tests/unit/conftest.py','tests/unit/brokers/__init__.py'] if (repo/p).is_file())
    else:
        names={'tests/'+x for x in selected}
        names.update(p for p in ['tests/__init__.py','tests/conftest.py','tests/conftest_test_data.py','tests/unit/__init__.py','tests/unit/conftest.py','tests/integration/__init__.py','tests/integration/conftest.py'] if (repo/p).is_file())
    for name2 in sorted(names): copy(repo/name2,root/name2)
    queue=list((root/'tests').rglob('*.py')); visited=set(); imports=set(); unresolved=set()
    while queue:
        p=queue.pop()
        if p in visited: continue
        visited.add(p)
        tree=ast.parse(p.read_text(encoding='utf-8'),filename=str(p))
        refs=set()
        for node in ast.walk(tree):
            if isinstance(node,ast.Import): refs.update(a.name for a in node.names if a.name.startswith('tests.'))
            if isinstance(node,ast.ImportFrom) and node.level==0 and node.module:
                if node.module.startswith('tests.'): refs.add(node.module)
                if node.module=='tests': refs.update('tests.'+a.name for a in node.names)
            if isinstance(node,ast.Call) and node.args and isinstance(node.args[0],ast.Constant) and type(node.args[0].value) is str and isinstance(node.func,ast.Attribute) and node.func.attr=='import_module' and node.args[0].value.startswith('tests.'):
                refs.add(node.args[0].value)
        for ref in refs:
            imports.add(ref); rel=Path(*ref.split('.')).with_suffix('.py'); src=repo/rel; dst=root/rel
            if not src.is_file():
                if (repo/Path(*ref.split('.'))/'__init__.py').is_file(): continue
                unresolved.add(ref); continue
            if not dst.exists(): copy(src,dst)
            queue.append(dst)
    if unresolved: raise RuntimeError((name,'unresolved imports',sorted(unresolved)))
    (root/'imports.txt').write_text('\n'.join(sorted(imports))+'\n')
    paths=['tests/unit/live_state','tests/unit/brokers/direct'] if name=='bt' else ['tests/'+x for x in selected]
    (root/'selected-tests.txt').write_text('\n'.join(paths)+'\n')
    print(name,'python files',len(visited),'imports',len(imports),flush=True)
(T/'test-manifest.txt').write_text('\n'.join(sorted(manifest))+'\n')
