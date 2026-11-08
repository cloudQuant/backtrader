"""Check every Gateway package payload, including py.typed, across four sources."""
import hashlib,json,zipfile
from pathlib import Path
T=Path('/tmp/iter63-r22-e044-install-20261109-K3FbuXsv');source=T/'source/src/bt_api_gateway';target=T/'install/bt_api_gateway'
wheel,=list((T/'wheels').glob('bt_api_gateway-*.whl'));prefix='bt_api_gateway/'
with zipfile.ZipFile(wheel) as z:
    members={Path(n[len(prefix):]) for n in z.namelist() if n.startswith(prefix) and not n.endswith('/')}
    def files(root):return {p.relative_to(root) for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts and not p.name.endswith('.pyc')}
    if members!=files(source) or members!=files(target):raise RuntimeError('complete Gateway package path set differs')
    for p in members:
        data=z.read(prefix+p.as_posix())
        if data!=(source/p).read_bytes() or data!=(target/p).read_bytes():raise RuntimeError(('complete package bytes differ',str(p)))
        original=Path('/Users/yunjinqi/Documents/new_projects/bt_api_py/bt_api/bt_api_gateway/src/bt_api_gateway')/p
        if data!=original.read_bytes():raise RuntimeError(('working tree differs',str(p)))
print('COMPLETE_GATEWAY_PACKAGE_SOURCE_SNAPSHOT_WHEEL_TARGET_MATCH',len(members),'wheel_sha256',hashlib.sha256(wheel.read_bytes()).hexdigest())
