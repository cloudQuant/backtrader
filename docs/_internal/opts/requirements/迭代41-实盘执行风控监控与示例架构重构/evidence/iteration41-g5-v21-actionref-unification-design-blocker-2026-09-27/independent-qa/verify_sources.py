from __future__ import annotations
import hashlib, json, re, subprocess, sys
from pathlib import Path
root = Path(r'D:\temp\iteration41-g5-actionref-unification-design-blocker-20260927')
qa = Path(r'D:\temp\iteration41-g5-actionref-unification-independent-qa-20260927')
manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
checksums=[]
for line in (root/'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines():
    if not line.strip(): continue
    parts=line.split(None,2)
    if len(parts)!=3: raise SystemExit(f'bad checksum row: {line!r}')
    expected,size,rel=parts; p=root/rel; data=p.read_bytes(); actual=hashlib.sha256(data).hexdigest().upper()
    checksums.append({'path':rel,'expected_sha256':expected.upper(),'actual_sha256':actual,'expected_size':int(size),'actual_size':len(data),'ok':actual.upper()==expected.upper() and len(data)==int(size)})
source_rows=[]
for line in (root/'source-preimages.sha256').read_text(encoding='utf-8').splitlines():
    if not line.strip(): continue
    m=re.match(r'^([0-9A-Fa-f]{64})\s+(\d+)\s+(.*)$',line)
    if not m: raise SystemExit(f'bad source row: {line!r}')
    expected,size,path=m.groups(); p=Path(path); data=p.read_bytes(); actual=hashlib.sha256(data).hexdigest().upper()
    source_rows.append({'path':path,'expected_sha256':expected.upper(),'actual_sha256':actual,'expected_size':int(size),'actual_size':len(data),'ok':actual.upper()==expected.upper() and len(data)==int(size)})
run=subprocess.run([sys.executable,str(root/manifest['verifier'])],cwd=root,text=True,capture_output=True)
(root/'verification.json').read_bytes()  # frozen evidence input; read only
result={
 'manifest_sha256':hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest().upper(),
 'manifest_status':manifest.get('status'), 'manifest_patch':manifest.get('patch'), 'changed_trees':manifest.get('changed_trees'),
 'package_checksum_rows':checksums, 'package_checksum_ok':all(x['ok'] for x in checksums),
 'source_preimage_rows':source_rows, 'source_preimages_ok':all(x['ok'] for x in source_rows),
 'source_row_count':len(source_rows), 'verifier_exit':run.returncode, 'verifier_stdout':run.stdout.strip(), 'verifier_stderr':run.stderr.strip(),
 'scope':'Independent file hash/size validation and execution of frozen AST-only verifier; no project imports.'
}
(qa/'verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,indent=2))
if run.returncode or not result['package_checksum_ok'] or not result['source_preimages_ok']: raise SystemExit(1)
