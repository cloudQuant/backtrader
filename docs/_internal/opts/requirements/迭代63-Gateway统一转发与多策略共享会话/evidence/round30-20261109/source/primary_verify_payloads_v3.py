"""Primary independent R30 package snapshot and installed payload verification."""
import hashlib,json,zipfile
from pathlib import Path
T=Path('/tmp/iter63-r30-install-20261109-ySExhdil');out=Path('/tmp/iter63-r30-primary')
sha=lambda b:hashlib.sha256(b).hexdigest()
rows=json.loads((T/'source-manifest.json').read_text())
for row in rows:
    assert sha(Path(row['source']).read_bytes())==row['sha256'],row['source']
    assert sha(Path(row['copy']).read_bytes())==row['sha256'],row['copy']
packages=[]
for kind,name,runtime in [('base','bt_api_base','src/bt_api_base'),('gateway','bt_api_gateway','src/bt_api_gateway'),('ctp','bt_api_ctp','src/bt_api_ctp'),('sdk','bt_api_py','bt_api_py'),('bt','backtrader','backtrader')]:
    wheel,=(T/'wheels').glob(('back_trader_python' if kind=='bt' else name)+'-*.whl')
    snap=T/'source'/kind/runtime;target=T/'install/src'/name
    with zipfile.ZipFile(wheel) as z:
        names={n for n in z.namelist() if n.startswith(name+'/') and not n.endswith('/')}
        assert len(names)==len([n for n in z.namelist() if n in names])
        sources={name+'/'+p.relative_to(snap).as_posix() for p in snap.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
        if kind=='ctp':
            native_manifest=json.loads((T/'ctp-native-reuse-manifest.json').read_text())
            expected={n for n in sources if n.endswith('.py') or (n.startswith('bt_api_ctp/configs/') and n.endswith('.yaml'))} | {r['member'] for r in native_manifest['members']}
            assert names==expected,(kind,'python plus selected native set difference',names^expected)
        else:
            assert names==sources,(kind,'snapshot set difference',names^sources)
        installed={name+'/'+p.relative_to(target).as_posix() for p in target.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
        assert names==installed,(kind,'install set difference',names^installed)
        for n in names:
            b=z.read(n);rel=n[len(name)+1:]
            assert b==(snap/rel).read_bytes()==(target/rel).read_bytes(),n
        meta,=[n for n in z.namelist() if n.endswith('.dist-info/METADATA')]
        readme=(T/'source'/kind/'README.md').read_bytes()
        payload=z.read(meta).split(b'\n\n',1)[1]
        assert payload.rstrip(b'\n')==readme.rstrip(b'\n'),(kind,'README')
        packages.append({'kind':kind,'members':len(names),'wheel':wheel.name,'sha256':sha(wheel.read_bytes()),'readme_sha256':sha(readme),'readme_metadata_exact':payload==readme})
native=json.loads((T/'ctp-native-reuse-manifest.json').read_text())
old=Path(native['source_wheel']);assert sha(old.read_bytes())==native['source_wheel_sha256']
new,=(T/'wheels').glob('bt_api_ctp-*.whl')
with zipfile.ZipFile(old) as a,zipfile.ZipFile(new) as b:
    for row in native['members']:
        data=a.read(row['member']);assert sha(data)==row['sha256']
        assert data==b.read(row['member'])==(T/'install/src'/row['member']).read_bytes()
report={'source_manifest_rows':len(rows),'packages':packages,'native_reused':len(native['members']),'native_origin_wheel_sha256':native['source_wheel_sha256']}
path=out/'primary-payload-verification.json';assert not path.exists();path.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
