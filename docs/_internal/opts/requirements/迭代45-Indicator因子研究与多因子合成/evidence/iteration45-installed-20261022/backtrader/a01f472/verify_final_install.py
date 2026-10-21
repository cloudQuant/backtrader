import base64
import csv
import hashlib
import importlib
import importlib.metadata as md
import importlib.util
import json
import pathlib
import sys
import sysconfig
import zipfile
from email.parser import Parser

if len(sys.argv) != 5:
    raise SystemExit('usage: verify_final_install.py ENV_LABEL VENV_ROOT WHEEL REPO_ROOT')
label, env_root_raw, wheel_raw, repo_raw = sys.argv[1:]
env_root = pathlib.Path(env_root_raw).resolve()
wheel_path = pathlib.Path(wheel_raw).resolve()
repo_root = pathlib.Path(repo_raw).resolve()

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()

def under(path, root):
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False

with zipfile.ZipFile(wheel_path) as z:
    wheel_files={n:hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if not n.endswith('/')}
    metadata_name=next(n for n in z.namelist() if n.endswith('.dist-info/METADATA'))
    wheel_version=Parser().parsestr(z.read(metadata_name).decode('utf-8')).get('Version')

dist=md.distribution('backtrader')
modules={}
for name in ('backtrader','backtrader.research','backtrader.research.operators','backtrader.research.representative'):
    mod=importlib.import_module(name)
    modules[name]={'origin':str(pathlib.Path(mod.__file__).resolve()),'version':getattr(mod,'__version__',None)}
package_files={n:h for n,h in wheel_files.items() if n.startswith(('backtrader/','backtrader_runtime/'))}
package_hash_matches={}
for name,expected in package_files.items():
    installed=pathlib.Path(dist.locate_file(name))
    package_hash_matches[name]=installed.is_file() and sha(installed)==expected

record_rel=next(n for n in wheel_files if n.endswith('.dist-info/RECORD'))
record_path=pathlib.Path(dist.locate_file(record_rel))
with record_path.open('r',encoding='utf-8',newline='') as f:
    rows=list(csv.reader(f))
record_check=[]
for row in rows:
    if not row[1]:
        continue
    path, encoded, size=row
    alg, value=encoded.split('=',1)
    installed=pathlib.Path(dist.locate_file(path))
    digest=hashlib.new(alg,installed.read_bytes()).digest()
    actual=base64.urlsafe_b64encode(digest).decode('ascii').rstrip('=')
    record_check.append({'path':path,'hash_ok':actual==value,'size_ok':installed.stat().st_size==int(size)})

try:
    fincore_dist=md.distribution('fincore')
    fincore_distribution={'installed':True,'version':fincore_dist.version,'origin':str(pathlib.Path(fincore_dist.locate_file('fincore/__init__.py')).resolve())}
except md.PackageNotFoundError:
    fincore_distribution={'installed':False,'version':None,'origin':None}
fincore_spec=importlib.util.find_spec('fincore')
site=pathlib.Path(sysconfig.get_paths()['purelib']).resolve()
venv_cfg=(env_root/'pyvenv.cfg').read_text(encoding='utf-8').lower()
include_system=any(line.strip()=='include-system-site-packages = true' for line in venv_cfg.splitlines())
repo_sys_path=[p for p in sys.path if p and under(pathlib.Path(p),repo_root)]
record={'status':'PASS_INSTALL_VERIFICATION','environment_label':label,'interpreter':sys.executable,'python_version':sys.version,'prefix':sys.prefix,'base_prefix':sys.base_prefix,'include_system_site_packages':include_system,'pyvenv_system_site_setting':'true' if include_system else 'false','site_packages':str(site),'site_packages_is_venv_local':site==(env_root/'Lib'/'site-packages').resolve(),'backtrader_distribution_version':dist.version,'wheel_metadata_version':wheel_version,'backtrader_import_origins':modules,'fincore':fincore_distribution,'fincore_find_spec':None if fincore_spec is None else str(fincore_spec.origin),'repository_source_on_sys_path':bool(repo_sys_path),'repository_sys_path_entries':repo_sys_path,'wheel':str(wheel_path),'wheel_sha256':sha(wheel_path),'wheel_package_files':len(package_files),'wheel_package_payload_all_hash_match':all(package_hash_matches.values()),'wheel_package_hash_mismatches':[n for n,ok in package_hash_matches.items() if not ok],'record_path':str(record_path),'record_rows':len(rows),'record_hashed_rows_checked':len(record_check),'record_hashes_and_sizes_match':all(x['hash_ok'] and x['size_ok'] for x in record_check),'record_failures':[x for x in record_check if not (x['hash_ok'] and x['size_ok'])],'tests_run':False}
if include_system or not record['site_packages_is_venv_local'] or record['repository_source_on_sys_path'] or dist.version!=wheel_version or not record['wheel_package_payload_all_hash_match'] or not record['record_hashes_and_sizes_match']:
    record['status']='FAIL_INSTALL_VERIFICATION'
    print(json.dumps(record,indent=2))
    raise SystemExit(1)
print(json.dumps(record,indent=2))
