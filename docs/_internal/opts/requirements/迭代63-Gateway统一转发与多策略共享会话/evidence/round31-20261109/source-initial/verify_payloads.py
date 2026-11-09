"""Primary independent R31 wheel/member and fixed dependency verification."""
import hashlib,json,zipfile
from pathlib import Path
T=Path('/tmp/iter63-r31-install-20261109-mz1EwW5H')
O=Path('/tmp/iter63-r31-primary')
sha=lambda data:hashlib.sha256(data).hexdigest()
rows=json.loads((T/'source-manifest.json').read_text())
for row in rows:
    assert sha(Path(row['source']).read_bytes())==row['sha256'],row['source']
    assert sha(Path(row['copy']).read_bytes())==row['sha256'],row['copy']
results=[]
for kind,name,wheelname in [('sdk','bt_api_py','bt_api_py'),('bt','backtrader','back_trader_python')]:
    wheel,=(T/'wheels').glob(wheelname+'-*.whl')
    snap=T/'source'/kind/name;target=T/'install/src'/name
    with zipfile.ZipFile(wheel) as z:
        members={p for p in z.namelist() if p.startswith(name+'/') and not p.endswith('/')}
        assert len(members)==len([p for p in z.namelist() if p in members])
        def names(root):
            return {name+'/'+p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
        assert members==names(snap)==names(target),(kind,members^names(snap),members^names(target))
        for member in members:
            rel=member[len(name)+1:]
            assert z.read(member)==(snap/rel).read_bytes()==(target/rel).read_bytes(),member
        meta,=[p for p in z.namelist() if p.endswith('.dist-info/METADATA')]
        readme=(T/'source'/kind/'README.md').read_bytes()
        payload=z.read(meta).split(b'\n\n',1)[1]
        assert payload.rstrip(b'\n')==readme.rstrip(b'\n')
        results.append({'kind':kind,'members':len(members),'wheel':wheel.name,'sha256':sha(wheel.read_bytes()),'readme_exact':payload==readme})
fixed=json.loads((T/'fixed-wheels.json').read_text())
for row in fixed:
    original=Path(row['source']);wheel=T/'wheels'/row['filename']
    assert sha(original.read_bytes())==row['sha256']==sha(wheel.read_bytes())
    with zipfile.ZipFile(wheel) as z:
        for member in z.namelist():
            if member.endswith('/') or '.dist-info/' in member or '.data/' in member:continue
            assert z.read(member)==(T/'install/src'/member).read_bytes(),member
report={'source_rows':len(rows),'new_packages':results,'fixed_wheels':fixed}
(O/'primary-payload-verification.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'source_rows':len(rows),'new_packages':results,'fixed_wheels':len(fixed)},indent=2))
