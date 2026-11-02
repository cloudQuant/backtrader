import base64
import csv
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import sys
import zipfile

OUT = Path('D:/temp/i51-ctp-nojoin-consumer-20261027-r1')
PREFIX = (OUT / 'consumer').resolve()
assert Path(sys.prefix).resolve() == PREFIX and sys.flags.isolated
assert sys.prefix != sys.base_prefix
WHEELS = {
    'bt_api_base': Path('D:/temp/ac51-r0-sdk-20261026-r2/offline-wheelhouse/bt_api_base-0.15.8-py3-none-any.whl'),
    'bt_api_ctp': Path('D:/temp/i51-ctp-nojoin-wheel-20261027-r1/wheelhouse/bt_api_ctp-2.0.4+iteration41.i9-cp311-cp311-win_amd64.whl'),
}
def pin(path):
    raw = path.read_bytes()
    return {'path': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

rows = []
for dist in metadata.distributions():
    records = [p for p in (dist.files or []) if str(p).endswith('.dist-info/RECORD')]
    assert len(records) == 1
    record = Path(dist.locate_file(records[0])).resolve()
    assert record.is_relative_to(PREFIX)
    checked = 0
    with record.open(encoding='utf-8', newline='') as stream:
        for relative, encoded, size in csv.reader(stream):
            file = Path(dist.locate_file(relative)).resolve()
            assert file.is_relative_to(PREFIX), 'installed file outside consumer'
            if encoded:
                algo, expected = encoded.split('=', 1)
                raw = file.read_bytes()
                actual = base64.urlsafe_b64encode(hashlib.new(algo, raw).digest()).rstrip(b'=').decode()
                assert actual == expected and len(raw) == int(size), 'installed RECORD mismatch'
                checked += 1
    row = {'name': dist.metadata['Name'], 'version': dist.version, 'record': pin(record), 'hashed_entries_verified': checked}
    key = row['name'].replace('-', '_')
    if key in WHEELS:
        with zipfile.ZipFile(WHEELS[key]) as archive:
            members = [n for n in archive.namelist() if n.startswith(key+'/') and not n.endswith('/')]
            for name in members:
                installed = Path(dist.locate_file(name)).resolve()
                assert installed.is_relative_to(PREFIX)
                assert installed.read_bytes() == archive.read(name), 'wheel to installed payload mismatch'
            row['wheel'] = pin(WHEELS[key])
            row['wheel_payload_entries_verified'] = len(members)
    rows.append(row)
assert {r['name'].replace('-', '_') for r in rows if 'wheel' in r} == set(WHEELS)
client = PREFIX / 'Lib/site-packages/bt_api_ctp/ctp/client.py'
assert pin(client)['sha256'] == '14a8f80d0ee0f14d8e57affefdaf850a255d31ff6fa478962060d7b37e8b3264'
result = {'status': 'PASS_INSTALLED_ARTIFACT_ONLY', 'consumer': str(PREFIX), 'executable': sys.executable, 'isolated': True, 'client': pin(client), 'distributions': sorted(rows,key=lambda r:r['name']), 'native_import_or_api_creation': False, 'formal_account_acceptance': False}
(OUT / 'verification.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
print(json.dumps({'status': result['status'], 'distributions': len(rows), 'client': result['client'], 'sdk_records': [r for r in rows if 'wheel' in r]}))
