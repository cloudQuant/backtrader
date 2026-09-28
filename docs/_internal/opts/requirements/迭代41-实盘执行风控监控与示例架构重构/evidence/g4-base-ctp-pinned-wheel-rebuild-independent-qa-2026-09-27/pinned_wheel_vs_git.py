import pathlib,zipfile,subprocess,json,hashlib
configs=[('base',pathlib.Path(r'D:\c41sdkf_audit\wheels\bt_api_base-0.15.5-py3-none-any.whl'),pathlib.Path(r'D:\c41sdkf\bt_api\bt_api_base'),'73e860e2fd8086ec817db254d4c396c2a76eb7d6','src/'),('ctp',pathlib.Path(r'D:\c41sdki2_audit\wheels\bt_api_ctp-2.0.3+iteration41.i2-cp311-cp311-win_amd64.whl'),pathlib.Path(r'D:\c41sdki2\bt_api_ctp'),'28157ce33009f932fbf8b3a78f7e77cb42c9cc4b','src/')]
for label,wheel,repo,rev,prefix in configs:
 exact=norm=bad=0; mism=[]; n=0
 with zipfile.ZipFile(wheel) as z:
  for name in z.namelist():
   if not name.endswith('.py'): continue
   n+=1; rel=prefix+name
   q=subprocess.run(['git','-C',str(repo),'cat-file','blob',f'{rev}:{rel}'],capture_output=True)
   if q.returncode: bad+=1;mism.append([name,'no blob']);continue
   actual=z.read(name); expected=q.stdout
   if actual==expected: exact+=1
   elif actual.replace(b'\r\n',b'\n')==expected: norm+=1
   else: bad+=1;mism.append([name,len(actual),len(expected),hashlib.sha256(actual).hexdigest(),hashlib.sha256(expected).hexdigest()])
 print(label,json.dumps({'python_members':n,'exact_blob':exact,'crlf_normalized':norm,'mismatch':bad,'mismatch_sample':mism[:20]},ensure_ascii=False))
