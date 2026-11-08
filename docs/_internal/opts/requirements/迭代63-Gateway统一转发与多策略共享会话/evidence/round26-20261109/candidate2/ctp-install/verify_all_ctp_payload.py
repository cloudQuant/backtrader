"""Bind all CTP wheel members to frozen public source or verified native payload."""
import hashlib,json,zipfile
from pathlib import Path
T=Path('/tmp/iter63-r26-ctp-final-v2-20261109-UFGxjkbS');lookup={r['copy']:r for r in json.loads((T/'source-manifest.json').read_text())};native=json.loads((T/'ctp-native-reuse-manifest.json').read_text());native_rows={r['member']:r for r in native['members']};old=Path(native['source_wheel']);new,=list((T/'wheels').glob('bt_api_ctp-*.whl'));prefix='bt_api_ctp/';root=T/'source/ctp/src/bt_api_ctp';target=T/'install/src'
with zipfile.ZipFile(old) as a,zipfile.ZipFile(new) as b:
    members=[n for n in b.namelist() if n.startswith(prefix) and not n.endswith('/')]
    for n in members:
        data=b.read(n)
        if data!=(target/n).read_bytes():raise RuntimeError(('installed payload mismatch',n))
        if n in native_rows:
            if data!=a.read(n) or hashlib.sha256(data).hexdigest()!=native_rows[n]['sha256']:raise RuntimeError(('native payload mismatch',n))
        else:
            copy=root/Path(n[len(prefix):]);row=lookup.get(str(copy))
            if row is None or data!=copy.read_bytes() or data!=Path(row['source']).read_bytes() or hashlib.sha256(data).hexdigest()!=row['sha256']:raise RuntimeError(('public CTP payload mismatch',n))
    if not set(native_rows).issubset(members):raise RuntimeError('missing native members')
print('ALL_CTP_WHEEL_MEMBERS_VERIFIED',len(members),'native_reused',len(native_rows),'wheel_sha256',hashlib.sha256(new.read_bytes()).hexdigest(),flush=True)
