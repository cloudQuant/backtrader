"""Check every BT wheel member against worktree, frozen copy and installed target."""
import hashlib,json,zipfile
from pathlib import Path
T=Path('/tmp/iter63-r25-install-20261109-jsTH40Ui');manifest=json.loads((T/'source-manifest.json').read_text());lookup={r['copy']:r for r in manifest};wheel,=list((T/'wheels').glob('back_trader_python-*.whl'));root=T/'source/bt/backtrader';target=T/'install/src';prefix='backtrader/'
with zipfile.ZipFile(wheel) as z:
    members=[x for x in z.namelist() if x.startswith(prefix) and not x.endswith('/')]
    for member in members:
        copy=root/Path(member[len(prefix):]);row=lookup.get(str(copy))
        if row is None or not copy.is_file():raise RuntimeError(('member missing frozen source',member))
        data=z.read(member)
        if data!=copy.read_bytes() or data!=Path(row['source']).read_bytes() or data!=(target/member).read_bytes() or hashlib.sha256(data).hexdigest()!=row['sha256']:
            raise RuntimeError(('package payload mismatch',member))
print('ALL_BT_WHEEL_PAYLOAD_MEMBERS_MATCH',len(members),'SHA256',hashlib.sha256(wheel.read_bytes()).hexdigest(),flush=True)
