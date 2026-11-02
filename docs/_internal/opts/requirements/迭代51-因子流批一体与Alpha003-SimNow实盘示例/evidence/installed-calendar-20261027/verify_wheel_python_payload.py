import hashlib
import json
from pathlib import Path
import sys
import zipfile

source_root = Path(sys.argv[1]).resolve()
wheel_path = Path(sys.argv[2]).resolve()
result_path = Path(sys.argv[3]).resolve()
archive_sha256 = sys.argv[4]
source = {}
for package in ('backtrader', 'backtrader_runtime'):
    root = source_root / package
    for path in root.rglob('*.py'):
        source[path.relative_to(source_root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
with zipfile.ZipFile(wheel_path) as wheel:
    members = [name for name in wheel.namelist() if name.endswith('.py') and name.split('/', 1)[0] in {'backtrader', 'backtrader_runtime'}]
    if len(members) != len(set(members)):
        raise SystemExit('duplicate Python paths in wheel')
    packaged = {name: hashlib.sha256(wheel.read(name)).hexdigest() for name in members}
missing = sorted(set(source) - set(packaged))
extra = sorted(set(packaged) - set(source))
mismatched = sorted(name for name in set(source) & set(packaged) if source[name] != packaged[name])
result = {
    'schema_version': 1,
    'status': 'PASS' if not (missing or extra or mismatched) else 'FAIL',
    'source_commit': 'ae218c04ca521aaad3ef8c6aa38f17f6c334444d',
    'source_archive_sha256': archive_sha256,
    'wheel': str(wheel_path),
    'wheel_sha256': hashlib.sha256(wheel_path.read_bytes()).hexdigest(),
    'source_python_count': len(source),
    'wheel_python_count': len(packaged),
    'missing_from_wheel': missing,
    'extra_in_wheel': extra,
    'hash_mismatches': mismatched,
}
result_path.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print(json.dumps(result, sort_keys=True))
if result['status'] != 'PASS':
    raise SystemExit(1)