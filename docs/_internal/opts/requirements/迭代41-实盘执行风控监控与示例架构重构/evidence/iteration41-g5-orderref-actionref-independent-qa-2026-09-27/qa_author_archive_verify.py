from __future__ import annotations
import hashlib,json,zipfile
from pathlib import Path
root=Path(r'D:\temp\iteration41-g5-order-authority-independent-qa-20260927')
base=Path(r'D:\source_code\backtrader\docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\evidence\iteration41-g5-orderref-actionref-author-candidate-2026-09-27')
zip_path=base/'iteration41-g5-orderref-actionref-author-candidate-2026-09-27.raw.zip'
index_path=base/'iteration41-g5-orderref-actionref-author-candidate-2026-09-27.index.json'
index=json.loads(index_path.read_text(encoding='utf-8'))
assert index.get('format')=='iteration41-g5-author-candidate-archive-index.v1'
with zipfile.ZipFile(zip_path) as z:
    assert z.testzip() is None
    names=set(z.namelist()); rows=index['zip_members']; assert len(rows)==111 and names=={r['path'] for r in rows}
    bad=[]
    for row in rows:
        data=z.read(row['path'])
        if len(data)!=row['bytes'] or hashlib.sha256(data).hexdigest().lower()!=row['sha256'].lower(): bad.append(row['path'])
assert not bad,bad
result={'status':'PASS','archive':str(zip_path),'archive_sha256':hashlib.sha256(zip_path.read_bytes()).hexdigest().upper(),'index':str(index_path),'index_sha256':hashlib.sha256(index_path.read_bytes()).hexdigest().upper(),'zip_members':len(rows),'zip_testzip':None,'member_hash_mismatches':bad}
out=root/'evidence'/'candidate-author-archive-verification.json'; out.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf-8'); print(json.dumps(result,indent=2,sort_keys=True))
