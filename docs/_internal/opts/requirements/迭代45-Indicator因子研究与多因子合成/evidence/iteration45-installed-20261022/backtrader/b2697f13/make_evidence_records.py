import base64,csv,hashlib,json,pathlib,sys,zipfile
from datetime import datetime,timezone
ext=pathlib.Path(sys.argv[1]); archive=pathlib.Path(sys.argv[2]); wheel=pathlib.Path(sys.argv[3]); out=pathlib.Path(sys.argv[4])
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def j(name): return json.loads((ext/name).read_text(encoding='utf-8-sig'))
with zipfile.ZipFile(wheel) as z:
 all_files={n:hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if not n.endswith('/')}
 package={n:h for n,h in all_files.items() if n.startswith(('backtrader/','backtrader_runtime/'))}
 metadata_name=next(n for n in all_files if n.endswith('.dist-info/METADATA'))
 metadata=z.read(metadata_name).decode('utf-8')
 version=next(line.split(':',1)[1].strip() for line in metadata.splitlines() if line.startswith('Version:'))
manifest={'commit':'b2697f13b99461f52c79b48ecf3b18ec6de19972','wheel_sha256':sha(wheel),'package_file_count':len(package),'package_payload_files':[{'path':n,'sha256':package[n]} for n in sorted(package)]}
(out/'wheel-payload-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
verifications={label:j(f'verify-{label}.json') for label in ('primary-dual','no-fincore','final-consumer')}
envs={}
for label,v in verifications.items():
 envs[label]={'status':v['status'],'interpreter':v['interpreter'],'prefix':v['prefix'],'python_version':v['python_version'],'include_system_site_packages':v['include_system_site_packages'],'site_packages_is_venv_local':v['site_packages_is_venv_local'],'backtrader_origin':v['backtrader_import_origins']['backtrader']['origin'],'research_origin':v['backtrader_import_origins']['backtrader.research']['origin'],'operators_origin':v['backtrader_import_origins']['backtrader.research.operators']['origin'],'representative_origin':v['backtrader_import_origins']['backtrader.research.representative']['origin'],'adapter_origin':v['backtrader_import_origins']['backtrader.research.fincore_adapter']['origin'],'fincore':v['fincore'],'repository_source_on_sys_path':v['repository_source_on_sys_path'],'package_payload_all_hash_match':v['wheel_package_payload_all_hash_match'],'record_rows':v['record_rows'],'record_hashed_rows_checked':v['record_hashed_rows_checked'],'record_hashes_and_sizes_match':v['record_hashes_and_sizes_match'],'tests_run':False}
pipchecks={}
freezes={}
for label in ('primary-dual','no-fincore','final-consumer'):
 p=out/f'pip-check-{label}.log'; text=p.read_text(encoding='utf-8-sig').strip()
 pipchecks[label]={'status':'PASS' if text=='No broken requirements found.' else 'FAIL','output':text,'sha256':sha(p)}
 p=out/f'pip-freeze-{label}.txt'; freezes[label]={'path':str(p),'line_count':len([x for x in p.read_text(encoding='utf-8-sig').splitlines() if x.strip()]),'sha256':sha(p)}
diff=json.loads((out/'payload-diff-vs-8c02.json').read_text(encoding='utf-8-sig'))
record={'status':'PASS_INSTALL_VERIFICATION','created_utc':datetime.now(timezone.utc).isoformat(),'source':{'repository':'D:\\source_code\\backtrader','branch':'dev','commit':'b2697f13b99461f52c79b48ecf3b18ec6de19972','parent':'92c006c0ad5a2eebc5a4dab51d3e7ce97169a440','tree_sha1':'c44453f0e787f62eb6ae8a7de224f387dda86c57','built_from_exact_git_archive':True,'archive_path':str(archive),'archive_size_bytes':archive.stat().st_size,'archive_sha256':sha(archive)},'wheel':{'path':str(wheel),'filename':wheel.name,'version':version,'size_bytes':wheel.stat().st_size,'sha256':sha(wheel),'package_payload_file_count':len(package),'package_payload_manifest':'wheel-payload-manifest.json'},'build_environment':{'interpreter':'D:\\temp\\iteration45-backtrader-builder-a01f472\\Scripts\\python.exe','python':'3.11.5','pip':'23.2.1','setuptools':'80.9.0','wheel':'0.45.1','setuptools_use_distutils':'stdlib','command':'pip wheel --no-deps --no-build-isolation'},'payload_diff_vs_8c02':{'baseline_wheel':'D:\\temp\\iteration45-backtrader-wheel-8c02e07f\\dist\\backtrader-1.4.0-py3-none-any.whl','baseline_sha256':'217eebc31b2d488d254d88c0c927bcbe2bfb507586610b0e79b0045647ea0742','package_added':diff['added'],'package_removed':diff['removed'],'package_changed':diff['changed_package_payload'],'dist_info_changed':diff['changed_dist_info'],'all_other_shared_package_payload_byte_identical':diff['only_adapter_package_payload_changed'] and diff['wheel_file_set_identical'],'wheel_file_set_identical':diff['wheel_file_set_identical']},'environments':envs,'pip_checks':pipchecks,'pip_freeze_snapshots':freezes,'tests_run_by_this_installation':False,'root_installed_acceptance':{'evidence_directory':'D:\\source_code\\backtrader\\docs\\_internal\\opts\\requirements\\迭代45-Indicator因子研究与多因子合成\\evidence\\iteration45-twenty-installed-20261022','status':'PASS','acceptance_wheel_commit':'8c02e07f242fbba6c1097c5e8edfbcf8a107448d','acceptance_wheel_sha256':'217eebc31b2d488d254d88c0c927bcbe2bfb507586610b0e79b0045647ea0742','note':'This separate Root acceptance artifact records the earlier tested install; this b2697f13 installer did not rerun the suite.'},'no_fincore_environment_remains_without_fincore':verifications['no-fincore']['fincore']['installed'] is False and verifications['no-fincore']['fincore_find_spec'] is None,'source_code_modified_by_this_install_task':False}
if not (all(v['status']=='PASS_INSTALL_VERIFICATION' and v['wheel_package_payload_all_hash_match'] and v['record_hashes_and_sizes_match'] and not v['include_system_site_packages'] and not v['repository_source_on_sys_path'] for v in verifications.values()) and all(x['status']=='PASS' for x in pipchecks.values()) and record['no_fincore_environment_remains_without_fincore'] and diff['only_adapter_package_payload_changed'] and diff['wheel_file_set_identical']):
 record['status']='FAIL_INSTALL_VERIFICATION'
(out/'install-record.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'status':record['status'],'archive_sha256':record['source']['archive_sha256'],'wheel_sha256':record['wheel']['sha256'],'package_file_count':len(package),'envs':{k:{'status':v['status'],'record_hashes_and_sizes_match':v['record_hashes_and_sizes_match'],'fincore':v['fincore']['installed']} for k,v in envs.items()},'payload_diff':record['payload_diff_vs_8c02']},indent=2))
if record['status']!='PASS_INSTALL_VERIFICATION': raise SystemExit(1)
