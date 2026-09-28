import tarfile,pathlib,hashlib
r=pathlib.Path(r'D:\temp\iteration41-g4-base-ctp-pinned-wheel-rebuild-20260927')
for tname,prefix in [('bt_api_ctp-i2-28157ce33009f932fbf8b3a78f7e77cb42c9cc4b.tar','src/bt_api_ctp/'),('bt_api_base-0.15.5-73e860e2fd8086ec817db254d4c396c2a76eb7d6.tar','')]:
 p=r/'archives'/tname
 print(tname,p.exists(),p.stat().st_size if p.exists() else None)
 if p.exists():
  with tarfile.open(p) as tf:
   names=tf.getnames()
   print('first',names[:5])
   for name in [n for n in names if n.endswith('__init__.py') and ('bt_api_ctp' in n or 'bt_api_base' in n)][:2]:
    data=tf.extractfile(name).read();print(name,len(data),hashlib.sha256(data).hexdigest(),'crlf',data.count(b'\r\n'),'lf',data.count(b'\n'))
   name=next((n for n in names if n.endswith('/bt_api_ctp/ctp/client.py')),None)
   if name:
    data=tf.extractfile(name).read();print(name,len(data),hashlib.sha256(data).hexdigest(),'crlf',data.count(b'\r\n'),'lf',data.count(b'\n'))
