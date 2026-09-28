from __future__ import annotations
import hashlib
import json
import zipfile
from pathlib import Path, PurePosixPath

root = Path(r'D:\source_code\backtrader\docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\evidence\ctp-g6s-artifact-first-sdk-binding-r2-author-candidate-2026-09-27\candidate')
manifest_path = root / 'candidate-source-manifest.json'
zip_path = root.parent / 'artifact-first-r2-loader-identity-candidate.zip'
expected_manifest_sha = '4ee9f0258b6b2e575fb2039fe3f31a049d918f2f86f3c5707365d3d37e48b916'
expected_zip_sha = 'dbbcbd8a5de4daf5265ae10b5eb114cbd6b2a429dc4ff9535aca5c3de8779d14'
sha = lambda b: hashlib.sha256(b).hexdigest()
manifest_raw = manifest_path.read_bytes()
manifest = json.loads(manifest_raw)
zip_raw = zip_path.read_bytes()
assert sha(manifest_raw) == expected_manifest_sha
assert sha(zip_raw) == expected_zip_sha
assert manifest['schema'] == 'iteration41.g6s.artifact_first_sdk_binding.r2_manifest.v1'
with zipfile.ZipFile(zip_path) as zf:
    assert zf.testzip() is None
    names = set(zf.namelist())
    missing = []
    mismatched = []
    for row in manifest['payload_files']:
        rel = PurePosixPath(row['path'])
        assert not rel.is_absolute() and '..' not in rel.parts
        local = root.joinpath(*rel.parts)
        if not local.is_file():
            missing.append(row['path']); continue
        data = local.read_bytes()
        if len(data) != row['size'] or sha(data) != row['sha256']:
            mismatched.append(row['path'])
        zname = rel.as_posix()
        if zname not in names or zf.read(zname) != data:
            mismatched.append('zip:' + row['path'])
    result = {
        'manifest_sha256': sha(manifest_raw),
        'zip_sha256': sha(zip_raw),
        'payload_count': len(manifest['payload_files']),
        'zip_entries': len(names),
        'zip_crc': 'clean' if zf.testzip() is None else 'bad',
        'missing': missing,
        'mismatched': mismatched,
        'base_r1_manifest_sha256': manifest['base']['r1_manifest_sha256'],
        'base_r1_archive_sha256': manifest['base']['r1_archive_sha256'],
        'r2_binder_sha256': manifest['candidate_changes']['files']['backtrader_runtime/ctp_sdk_artifact_binding.py']['sha256'],
        'r2_custody_test_sha256': manifest['payload_files'][-1]['sha256'],
    }
    print(json.dumps(result, sort_keys=True, indent=2))
    if missing or mismatched:
        raise SystemExit(1)
