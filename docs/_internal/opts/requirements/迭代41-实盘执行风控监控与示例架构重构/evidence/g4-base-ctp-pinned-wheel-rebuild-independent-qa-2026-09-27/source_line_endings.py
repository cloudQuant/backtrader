import subprocess,pathlib,hashlib
repo=pathlib.Path(r'D:\c41sdki2\bt_api_ctp'); build=pathlib.Path(r'D:\temp\iteration41-g4-base-ctp-pinned-wheel-rebuild-20260927\build-a\src\ctp')
rev='28157ce33009f932fbf8b3a78f7e77cb42c9cc4b'
for rel in ['src/bt_api_ctp/__init__.py','src/bt_api_ctp/ctp/client.py']:
 blob=subprocess.run(['git','-C',str(repo),'show',f'{rev}:{rel}'],capture_output=True,check=True).stdout
 fs=(repo/rel).read_bytes(); archived=(build/rel).read_bytes()
 print(rel)
 for name,b in [('git_blob',blob),('source_worktree',fs),('archive_extract',archived)]: print(name,len(b),hashlib.sha256(b).hexdigest(),'crlf',b.count(b'\r\n'),'lf',b.count(b'\n'))
