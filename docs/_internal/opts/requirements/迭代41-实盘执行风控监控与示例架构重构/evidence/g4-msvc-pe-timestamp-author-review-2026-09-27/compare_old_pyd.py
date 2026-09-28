import hashlib,zipfile
from pathlib import Path
ps={'pin':Path(r'D:\c41sdki2_audit\wheels\bt_api_ctp-2.0.3+iteration41.i2-cp311-cp311-win_amd64.whl'),'old_a':Path(r'D:\temp\iteration41-g4-base-ctp-pinned-wheel-rebuild-20260927\build-a\wheelhouse\bt_api_ctp-2.0.3+iteration41.i2-cp311-cp311-win_amd64.whl'),'old_b':Path(r'D:\temp\iteration41-g4-base-ctp-pinned-wheel-rebuild-20260927\build-b\wheelhouse\bt_api_ctp-2.0.3+iteration41.i2-cp311-cp311-win_amd64.whl')}
for k,p in ps.items():
 with zipfile.ZipFile(p) as z:b=z.read('bt_api_ctp/ctp/_ctp.cp311-win_amd64.pyd')
 print(k,'wheel',hashlib.sha256(p.read_bytes()).hexdigest(),'pydlen',len(b),'pyd',hashlib.sha256(b).hexdigest())
 if k=='pin': pin=b
 else:
  ix=[i for i,(x,y) in enumerate(zip(pin,b)) if x!=y];print('common differing byte count',len(ix),'first',[(hex(i),pin[i:i+8].hex(),b[i:i+8].hex()) for i in ix[:20]],'length_delta',len(b)-len(pin))
