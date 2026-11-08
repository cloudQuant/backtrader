from pathlib import Path
import hashlib,json
T=Path('/tmp/iter63-r09-packaging-ySGAYCmv/final'); src=Path('/Users/yunjinqi/Documents/new_projects/bt_api_py/bt_api/bt_api_ctp/tests/test_iter62_settlement_readback_on_write.py'); dst=T/'install/tests'/src.name
b=src.read_bytes(); dst.write_bytes(b); p=T/'test-manifest.json'; rows=json.loads(p.read_text()); rows.append({'source':str(src),'copy':str(dst),'sha256':hashlib.sha256(b).hexdigest()}); p.write_text(json.dumps(sorted(rows,key=lambda r:r['copy']),indent=2)+'\n'); print('added CTP public helper',src,'->',dst)
