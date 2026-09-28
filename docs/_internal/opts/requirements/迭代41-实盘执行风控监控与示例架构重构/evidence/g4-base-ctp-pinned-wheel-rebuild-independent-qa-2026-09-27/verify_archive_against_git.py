import tarfile,pathlib,subprocess,hashlib,json
root=pathlib.Path(r'D:\temp\iteration41-g4-base-ctp-pinned-wheel-rebuild-20260927')
configs=[('base','bt_api_base-0.15.5-73e860e2fd8086ec817db254d4c396c2a76eb7d6.tar',r'D:\c41sdkf\bt_api\bt_api_base','73e860e2fd8086ec817db254d4c396c2a76eb7d6'),('ctp','bt_api_ctp-i2-28157ce33009f932fbf8b3a78f7e77cb42c9cc4b.tar',r'D:\c41sdki2\bt_api_ctp','28157ce33009f932fbf8b3a78f7e77cb42c9cc4b')]
for label,archive,repo,rev in configs:
 repo=pathlib.Path(repo); p=root/'archives'/archive
 tree=subprocess.run(['git','-C',str(repo),'ls-tree','-r','--name-only',rev],check=True,capture_output=True).stdout.decode().splitlines()
 tree_set=set(tree); archive_items={}
 with tarfile.open(p) as tf:
  for m in tf.getmembers():
   if m.isfile(): archive_items[m.name]=tf.extractfile(m).read()
 extras=sorted(set(archive_items)-tree_set); missing=sorted(tree_set-set(archive_items))
 exact=normalized=bad=0; badlist=[]
 for rel,data in archive_items.items():
  q=subprocess.run(['git','-C',str(repo),'cat-file','blob',f'{rev}:{rel}'],capture_output=True)
  if q.returncode: bad+=1; badlist.append([rel,'no-git-blob']);continue
  blob=q.stdout
  if data==blob: exact+=1
  elif data.replace(b'\r\n',b'\n')==blob: normalized+=1
  else: bad+=1; badlist.append([rel,len(data),len(blob),hashlib.sha256(data).hexdigest(),hashlib.sha256(blob).hexdigest()])
 print(label,json.dumps({'tree_files':len(tree),'archive_files':len(archive_items),'exact_blob':exact,'crlf_normalized_blob':normalized,'other_mismatch':bad,'extra':extras[:30],'extra_count':len(extras),'missing':missing[:30],'missing_count':len(missing),'mismatch_sample':badlist[:20]},ensure_ascii=False))
