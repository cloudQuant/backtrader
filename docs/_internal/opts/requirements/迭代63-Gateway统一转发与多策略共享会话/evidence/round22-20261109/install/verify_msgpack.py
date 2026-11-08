"""Verify selected msgpack version, wheel bytes and actual installed origin."""
import hashlib,importlib.metadata,json,sys,zipfile
from pathlib import Path
from packaging.version import Version
T=Path('/tmp/iter63-r22-e044-install-20261109-K3FbuXsv');target=(T/'install').resolve();sys.path.insert(0,str(target))
import msgpack
manifest=json.loads((T/'msgpack-wheel-manifest.json').read_text());wheel=Path(manifest['source'])
if hashlib.sha256(wheel.read_bytes()).hexdigest()!=manifest['sha256']:raise RuntimeError('msgpack wheel SHA changed')
dist=importlib.metadata.distribution('msgpack');version=dist.version
if version!=manifest['version'] or Version(version)<Version('1.1'):raise RuntimeError('msgpack version mismatch')
if not Path(msgpack.__file__).resolve().is_relative_to(target) or not Path(dist._path).resolve().is_relative_to(target):raise RuntimeError('msgpack not installed in target')
with zipfile.ZipFile(wheel) as z:
    names=[n for n in z.namelist() if n.startswith('msgpack/') and not n.endswith('/')]
    if not names:raise RuntimeError('empty msgpack wheel')
    for name in names:
        if not (target/name).is_file() or (target/name).read_bytes()!=z.read(name):raise RuntimeError(('msgpack payload mismatch',name))
print('MSGPACK_VERSION',version,'ORIGIN',msgpack.__file__,'DIST',dist._path,'WHEEL_SHA256',manifest['sha256'],'PAYLOAD_FILES',len(names),flush=True)
