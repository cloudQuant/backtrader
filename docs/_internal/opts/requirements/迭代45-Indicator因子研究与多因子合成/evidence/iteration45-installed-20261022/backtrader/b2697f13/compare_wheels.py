import hashlib, json, pathlib, sys, zipfile
old=pathlib.Path(sys.argv[1]); new=pathlib.Path(sys.argv[2]); out=pathlib.Path(sys.argv[3])
def files(path):
    with zipfile.ZipFile(path) as z:
        return {n:hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if not n.endswith('/')}
a=files(old); b=files(new)
keys=sorted(set(a)|set(b)); changed=[k for k in keys if a.get(k)!=b.get(k)]
package=[k for k in changed if k.startswith(('backtrader/','backtrader_runtime/'))]
dist=[k for k in changed if '.dist-info/' in k]
result={'baseline_wheel':str(old),'candidate_wheel':str(new),'baseline_file_count':len(a),'candidate_file_count':len(b),'added':[k for k in keys if k not in a],'removed':[k for k in keys if k not in b],'changed_files':changed,'changed_package_payload':package,'changed_dist_info':dist,'only_adapter_package_payload_changed':package==['backtrader/research/fincore_adapter.py'],'wheel_file_set_identical':set(a)==set(b)}
out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,indent=2))
if not result['only_adapter_package_payload_changed'] or not result['wheel_file_set_identical']:
    raise SystemExit(1)
