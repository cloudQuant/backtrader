"""Check every rebuilt package wheel member against source copy, worktree and target."""
import hashlib,json,zipfile
from pathlib import Path
T=Path('/tmp/iter63-r24-install-20261109-fEuNyr35');manifest=json.loads((T/'source-manifest.json').read_text());lookup={r['copy']:r for r in manifest}
for kind,package,wheel_prefix in [('bt','backtrader','back_trader_python-'),('sdk','bt_api_py','bt_api_py-')]:
    wheel,=list((T/'wheels').glob(wheel_prefix+'*.whl'));prefix=package+'/';root=T/'source'/kind/package;target=T/'install/src'
    with zipfile.ZipFile(wheel) as z:
        members=[x for x in z.namelist() if x.startswith(prefix) and not x.endswith('/')]
        for member in members:
            rel=Path(member[len(prefix):]);copy=root/rel;row=lookup.get(str(copy))
            if row is None or not copy.is_file():raise RuntimeError(('member missing frozen source',member))
            data=z.read(member)
            if data!=copy.read_bytes() or data!=Path(row['source']).read_bytes() or data!=(target/member).read_bytes() or hashlib.sha256(data).hexdigest()!=row['sha256']:
                raise RuntimeError(('package payload mismatch',member))
    print('ALL_WHEEL_PAYLOAD_MEMBERS_MATCH',kind,len(members),hashlib.sha256(wheel.read_bytes()).hexdigest(),flush=True)
