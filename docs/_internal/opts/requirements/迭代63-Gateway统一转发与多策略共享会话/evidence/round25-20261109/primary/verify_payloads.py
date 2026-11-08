from pathlib import Path
import zipfile,hashlib,json
root=Path('/Users/yunjinqi/Documents/new_projects')
t=Path('/tmp/iter63-r25-install-20261109-jsTH40Ui')
results=[]
for package,repo,stage,pattern in [('backtrader','backtrader','bt','back_trader_python-*.whl'),('bt_api_py','bt_api_py','sdk','bt_api_py-*.whl')]:
 wheel,=t.joinpath('wheels').glob(pattern)
 with zipfile.ZipFile(wheel) as z:
  members=[name for name in z.namelist() if name.startswith(package+'/') and not name.endswith('/')]
  for name in members:
   payload=z.read(name)
   paths=[root/repo/name,t/'source'/stage/name,t/'install/src'/name]
   assert all(p.read_bytes()==payload for p in paths),name
  results.append({'package':package,'members':len(members),'wheel':wheel.name,'sha256':hashlib.sha256(wheel.read_bytes()).hexdigest(),'worktree_snapshot_wheel_target_match':True})
for name in ('source-manifest.json','test-manifest.json'):
 rows=json.loads((t/name).read_text())
 for row in rows:
  assert all(hashlib.sha256(Path(row[f]).read_bytes()).hexdigest()==row['sha256'] for f in ('source','copy')),row
 results.append({'manifest':name,'rows':len(rows),'worktree_copy_match':True})
print(json.dumps(results,indent=2))
