import hashlib, pathlib
from backtrader_runtime.ctp_windows_artifact_custody import WindowsArtifactCustody
root=pathlib.Path('C:/Users/yunji/Temp/iter41-custody-probe4')
root.mkdir(parents=True, exist_ok=False)
p=root/'x.py'
raw=b'value=1\n'
p.write_bytes(raw)
c=WindowsArtifactCustody.acquire(str(root),('x.py',),expected_sha256={'x.py':hashlib.sha256(raw).hexdigest()})
print('held',c.read('x.py'))
try:
 p.write_bytes(b'value=2\n')
 print('WRITE_ALLOWED')
except OSError as e:
 print('WRITE_BLOCKED',type(e).__name__,getattr(e,'winerror',None))
try:
 p.rename(root/'y.py')
 print('RENAME_ALLOWED')
except OSError as e:
 print('RENAME_BLOCKED',type(e).__name__,getattr(e,'winerror',None))
c.close()
