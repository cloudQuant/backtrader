"""Audit frozen source/test bytes and both wheel package payloads."""
import hashlib,importlib,importlib.metadata,json,sys,zipfile
from pathlib import Path
T=Path('/tmp/iter63-r22-e044-install-20261109-K3FbuXsv');target=(T/'install').resolve();sys.path[:0]=[str(target),str(T/'bootstrap')]
from offline_guard import install as offline
from origin_guard import audit,install as origin
origin('r22-verify');offline()
rows=json.loads((T/'manifest.json').read_text())
for row in rows:
    for field in ('source','copy'):
        if hashlib.sha256(Path(row[field]).read_bytes()).hexdigest()!=row['sha256']:raise RuntimeError(('source/test drift',row[field]))
print('MANIFEST_MATCH',len(rows),flush=True)
for name in ('bt_api_base','bt_api_gateway'):
    mod=importlib.import_module(name);dist=importlib.metadata.distribution(name);prefix=name+'/'
    if not Path(mod.__file__).resolve().is_relative_to(target) or not Path(dist._path).resolve().is_relative_to(target): raise RuntimeError(('origin outside target',name))
    wheels=list((T/'wheels').glob(name+'-*.whl'))
    if len(wheels)!=1: raise RuntimeError(('wheel cardinality',name))
    wheel=wheels[0]
    with zipfile.ZipFile(wheel) as z:
        members=[i for i in z.namelist() if i.startswith(prefix) and not i.endswith('/')]
        for item in members:
            if not (target/item).is_file() or z.read(item)!=(target/item).read_bytes(): raise RuntimeError(('wheel-target mismatch',item))
        if name=='bt_api_gateway':
            source=T/'source/src'/name
            w={Path(i[len(prefix):]) for i in members if i.endswith('.py')}
            s={p.relative_to(source) for p in source.rglob('*.py')}
            installed={p.relative_to(target/name) for p in (target/name).rglob('*.py')}
            if w!=s or w!=installed: raise RuntimeError('Gateway Python path set mismatch')
            for rel in w:
                if z.read(prefix+rel.as_posix())!=(source/rel).read_bytes(): raise RuntimeError(('wheel-source mismatch',str(rel)))
            readme=(T/'source/README.md').read_text()
            if dist.metadata.get_payload().rstrip('\n')!=readme.rstrip('\n'): raise RuntimeError('README metadata mismatch')
    print('VERIFIED',name,'origin',mod.__file__,'wheel',wheel.name,'sha256',hashlib.sha256(wheel.read_bytes()).hexdigest(),'payload_files',len(members),flush=True)
if not audit():raise RuntimeError('origin audit failed')
print('NO_FULL_RESOLVER_NO_ACCOUNT_NO_NATIVE_FACTORY',flush=True)
