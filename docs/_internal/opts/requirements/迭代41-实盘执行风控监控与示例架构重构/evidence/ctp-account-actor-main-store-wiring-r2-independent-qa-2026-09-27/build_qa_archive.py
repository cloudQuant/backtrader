import hashlib,json,pathlib,zipfile
pkg=pathlib.Path(r'D:\temp\iteration41-store-actor-r2-independent-qa-20260927b\package'); payload=pkg/'payload'; archive=pkg/'r2-independent-qa.raw.zip'
files=sorted(p for p in payload.rglob('*') if p.is_file())
records=[]
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
 for p in files:
  rel=p.relative_to(payload).as_posix(); data=p.read_bytes(); digest=hashlib.sha256(data).hexdigest()
  records.append({'path':rel,'sha256':digest,'size_bytes':len(data)})
  zi=zipfile.ZipInfo(rel,date_time=(2026,9,27,0,0,0)); zi.compress_type=zipfile.ZIP_DEFLATED; zi.external_attr=0o100644<<16
  z.writestr(zi,data,compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
zip_sha=hashlib.sha256(archive.read_bytes()).hexdigest()
index={'status':'INDEPENDENT_QA_RAW_ARCHIVE','payload_count':len(records),'zip_member_count':len(records),'zip_sha256':zip_sha,'zip_size_bytes':archive.stat().st_size,'source_candidate_archive_sha256':'1b6c0a9d03295d9c96548ee63342a6931d7ab7a23e214161c2cde8661739f98a','candidate_manifest_sha256':'5b68f9ed2a457e51941bbd60052a100d2e045907b9b2e3bb454482304badd27a','payloads':records}
indexp=pkg/'archive-index.json'; indexp.write_text(json.dumps(index,sort_keys=True,indent=2)+'\n',encoding='utf-8')
for p in [archive,indexp]:
 (pkg/(p.name+'.sha256')).write_text(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n',encoding='ascii')
with zipfile.ZipFile(archive) as z:
 assert z.testzip() is None
 assert len(z.namelist())==len(records)
 for rec in records:
  data=z.read(rec['path']); assert len(data)==rec['size_bytes'] and hashlib.sha256(data).hexdigest()==rec['sha256']
print('payload_count',len(records),'zip_members',len(records),'zip_testzip',None)
print('zip_sha256',zip_sha,'zip_size_bytes',archive.stat().st_size)
print('index_sha256',hashlib.sha256(indexp.read_bytes()).hexdigest())
