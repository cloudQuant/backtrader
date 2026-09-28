import csv, hashlib, json, re, subprocess, zipfile
from email.parser import Parser
from pathlib import Path

root = Path(r'D:\temp\iteration41-unified-offline-wheelhouse-settlement-20260927-r1')
qa = Path(r'D:\temp\iteration41-unified-offline-wheelhouse-settlement-independent-qa-20260927')
def sha(raw): return hashlib.sha256(raw).hexdigest()
def file_sha(path): return sha(path.read_bytes())
errors=[]
# Candidate-level 150+ manifest and archive binding.
manifest_raw=(root/'candidate-files-manifest.json').read_bytes()
manifest=json.loads(manifest_raw)
archive_index=json.loads((root/'archive-index.json').read_text(encoding='utf-8'))
receipt=json.loads((root/'candidate-receipt.json').read_text(encoding='utf-8'))
if sha(manifest_raw).upper()!=archive_index['candidate_files_manifest_sha256']: errors.append('candidate manifest hash != archive index')
if file_sha(root/'candidate-receipt.json').upper()!=archive_index['candidate_receipt_sha256']: errors.append('receipt hash != archive index')
if len(manifest['files']) != manifest['file_count'] or len(manifest['files']) != 150: errors.append(f"manifest count {len(manifest['files'])}")
for ent in manifest['files']:
    path=root/Path(*ent['path'].split('/'))
    if not path.is_file(): errors.append('manifest file missing '+ent['path']); continue
    raw=path.read_bytes()
    if len(raw)!=ent['size_bytes'] or sha(raw).lower()!=ent['sha256'].lower(): errors.append('manifest file mismatch '+ent['path'])
zip_path=root/archive_index['raw_archive']['file']
if file_sha(zip_path).upper()!=archive_index['raw_archive']['sha256']: errors.append('archive zip hash mismatch')
with zipfile.ZipFile(zip_path) as z:
    if len(z.namelist())!=151 or len(set(z.namelist()))!=151: errors.append('archive entry count/duplicate mismatch')
    if z.testzip() is not None: errors.append('candidate zip CRC fail')
    if sha(z.read('candidate-files-manifest.json')).upper()!=archive_index['candidate_files_manifest_sha256']: errors.append('manifest ZIP member mismatch')
    zip_payload=set(z.namelist())-{'candidate-files-manifest.json'}
    declared={e['path'] for e in manifest['files']}
    if zip_payload!=declared: errors.append('ZIP member set != 150 declared files')
    for ent in manifest['files']:
        raw=z.read(ent['path'])
        if len(raw)!=ent['size_bytes'] or sha(raw).lower()!=ent['sha256'].lower(): errors.append('ZIP payload mismatch '+ent['path'])
# All wheelhouse files, metadata, lock and wheel RECORD envelopes.
wh=root/'wheelhouse'
wman=json.loads((root/'wheelhouse-manifest.json').read_text(encoding='utf-8'))
lock_lines=(root/'requirements-hashes.txt').read_text(encoding='utf-8').splitlines()
lock={}
for line in lock_lines:
    m=re.fullmatch(r'(.+)==(.+) --hash=sha256:([0-9a-f]{64})',line.strip())
    if not m: errors.append('bad lock line '+line); continue
    name=m.group(1).lower().replace('_','-')
    if name in lock: errors.append('duplicate requirement '+name)
    lock[name]=(m.group(2),m.group(3))
if len(lock_lines)!=52 or len(lock)!=52: errors.append(f'lock line count={len(lock_lines)} unique={len(lock)}')
if len(wman['wheels'])!=52: errors.append('wheel manifest count mismatch')
wheels={}
for item in wman['wheels']:
    p=wh/item['file']
    if not p.is_file(): errors.append('wheel missing '+item['file']); continue
    raw=p.read_bytes()
    if len(raw)!=item['size_bytes'] or sha(raw).lower()!=item['sha256'].lower(): errors.append('wheel manifest mismatch '+item['file'])
    with zipfile.ZipFile(p) as z:
        if z.testzip() is not None: errors.append('wheel CRC '+item['file'])
        meta_name=next(n for n in z.namelist() if n.endswith('.dist-info/METADATA'))
        md=Parser().parsestr(z.read(meta_name).decode('utf-8'))
        if (md['Name'],md['Version'])!=(item['name'],item['version']): errors.append('wheel metadata mismatch '+item['file'])
        rows=list(csv.reader(z.read(meta_name.split('/')[0]+'/RECORD').decode('utf-8').splitlines()))
        if not rows: errors.append('wheel RECORD is empty '+item['file'])
    norm=item['name'].lower().replace('_','-')
    if lock.get(norm)!=(item['version'],item['sha256'].lower()): errors.append('lock mismatch '+item['file'])
    wheels[norm]=item
if len(list(wh.glob('*.whl')))!=52: errors.append('wheelhouse file count mismatch')
collision=json.loads((root/'same-version-collision-report.json').read_text(encoding='utf-8'))
collision_hashes={x['sha256'].lower() for x in collision['diagnostic_only']}
if any(file_sha(p).lower() in collision_hashes for p in wh.glob('*.whl')): errors.append('old collision wheel found in final wheelhouse')
if any(h in (root/'requirements-hashes.txt').read_text(encoding='ascii').lower() for h in collision_hashes): errors.append('old collision hash found in final lock')
ctp=wheels.get('bt-api-ctp')
if not ctp or ctp['version']!='2.0.4+g4r2.settlement.probe.20260927': errors.append('final CTP version identity mismatch')
# Compare independent CTP build A/B and selected artifact.
ctp_build=root/'build-evidence'/'ctp-build'
a=root/'build-evidence'/'ctp-build'/'a'/'wheel-a.whl'; b=root/'build-evidence'/'ctp-build'/'b'/'wheel-b.whl'
ctp_hashes={'wheelhouse':ctp['sha256'].lower(),'build_a':file_sha(a).lower(),'build_b':file_sha(b).lower()}
if len(set(ctp_hashes.values()))!=1: errors.append('CTP dual build hashes do not all agree')
# Check parent optional extra is missing binance and is not represented in wheelhouse.
parent=wheels['bt-api-py']
with zipfile.ZipFile(wh/parent['file']) as z:
    meta_name=next(n for n in z.namelist() if n.endswith('.dist-info/METADATA'))
    md=Parser().parsestr(z.read(meta_name).decode('utf-8'))
    extra_lines=[x for x in md.get_all('Requires-Dist',[]) if 'bt_api_binance' in x.lower()]
    extras=md.get_all('Provides-Extra',[])
binance_present=any(x['name'].lower().replace('_','-')=='bt-api-binance' for x in wman['wheels'])
if not extra_lines or not any('core-reference' in x.lower() for x in extra_lines): errors.append('expected core-reference optional binance dependency not found')
if binance_present: errors.append('unexpected bt_api_binance wheel present')
# Compare clean base checkout's packaged .py payload (read-only source files, no imports).
base_source=Path(r'D:\temp\bt_api_i9_store_broker_src_20260926\bt_api_base')
base_head=subprocess.run(['git','-C',str(base_source),'rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
base_status=subprocess.run(['git','-C',str(base_source),'status','--porcelain'],capture_output=True,text=True,check=True).stdout.strip()
if base_head!='3de0fa4f6cfe8d1973e9f4b9b47b01254259524f' or base_status: errors.append('base source checkout is not clean expected detached revision')
base_src=base_source/'src'/'bt_api_base'
base_pkg={p.relative_to(base_source/'src').as_posix():p.read_bytes() for p in base_src.rglob('*.py')}
base_wheel=wh/'bt_api_base-0.15.4-py3-none-any.whl'
with zipfile.ZipFile(base_wheel) as z:
    package_py={n:z.read(n) for n in z.namelist() if n.startswith('bt_api_base/') and n.endswith('.py')}
if len(base_pkg)!=104 or len(package_py)!=104: errors.append(f'base file counts source={len(base_pkg)} wheel={len(package_py)}')
if base_pkg.keys()!=package_py.keys(): errors.append('base source/wheel paths differ')
base_diffs=[p for p,bts in base_pkg.items() if package_py.get(p)!=bts]
if base_diffs: errors.append('base source/wheel payload diffs '+repr(base_diffs[:5]))
# ConfirmDate field and readiness wiring gap from frozen sources only.
settlement_src=(root/'build-evidence'/'settlement-source'/'ctp_native_query_certificate.py').read_text(encoding='utf-8')
settle_test=(root/'build-evidence'/'settlement-source'/'test_ctp_settlement_query_evidence.py').read_text(encoding='utf-8')
readiness_path=Path(r'D:\source_code\backtrader\backtrader_runtime\ctp_simnow_native_readiness.py')
readiness=readiness_path.read_text(encoding='utf-8')
settle_start=settlement_src.find('def _require_exact_source')
settle_end=settlement_src.find('\n    @staticmethod',settle_start)
settle_window=settlement_src[settle_start:settle_end]
row_struct_absent=('"TradingDay" not in set(dir(response_type))' in settle_test)
helper_uses_confirm_date=('ConfirmDate' in settle_window and 'scope.trading_day' in settle_window)
readiness_has_settlement='settlement_confirmation' in readiness or 'verify_settlement_confirmation' in readiness
if not row_struct_absent: errors.append('settlement test did not assert CTP row has no TradingDay')
if not helper_uses_confirm_date: errors.append('settlement helper row comparison not located')
if readiness_has_settlement: errors.append('current readiness unexpectedly references settlement builder; review scope finding')
report={
 'schema':'iteration41.unified_offline_wheelhouse_settlement.independent_qa.r1.v1',
 'status':'FAKE_ONLY / NO_RELEASE / G1-G5_NOT_ACCEPTED',
 'errors':errors,
 'candidate_manifest_sha256':sha(manifest_raw),
 'manifest_payload_files_verified':len(manifest['files']),
 'candidate_archive_sha256':file_sha(zip_path),
 'candidate_archive_entries':151,
 'wheel_count':len(wheels),
 'requirements_lock_lines':len(lock_lines),
 'ctp_final':{'version':ctp['version'],'filename':ctp['file'],'sha256':ctp['sha256'],'build_a_sha256':ctp_hashes['build_a'],'build_b_sha256':ctp_hashes['build_b'],'same_hash':len(set(ctp_hashes.values()))==1,'old_collision_excluded':True},
 'base_source_comparison':{'git_head':base_head,'git_clean':not bool(base_status),'python_files_source':len(base_pkg),'python_files_wheel':len(package_py),'exact_byte_match_count':len(base_diffs)==0},
 'missing_optional_extra':{'bt_api_binance_in_wheelhouse':binance_present,'parent_requires_dist_lines':extra_lines,'parent_provides_extra':extras},
 'settlement_scope':{'response_row_has_no_TradingDay':row_struct_absent,'ConfirmDate_compared_to_query_source_trading_day':helper_uses_confirm_date,'main_readiness_references_settlement_builder':readiness_has_settlement},
 'native_imported_or_loaded':False,
 'provider_network_or_private_config':False,
}
(qa/'evidence').mkdir(exist_ok=True)
(qa/'evidence'/'artifact-static-audit.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k!='errors'},indent=2))
print('errors:',json.dumps(errors,indent=2))
if errors: raise SystemExit(1)

