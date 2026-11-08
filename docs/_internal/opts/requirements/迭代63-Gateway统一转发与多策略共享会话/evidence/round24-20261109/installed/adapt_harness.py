from pathlib import Path
T=Path('/tmp/iter63-r24-install-20261109-fEuNyr35');P=Path('/tmp/iter63-r24-primary')
p=T/'capture_selectors.py';s=p.read_text().replace("{'gateway', 'sdk'}","{'bt', 'sdk'}");p.write_text(s)
p=T/'prepare.py';s=p.read_text()
s=s.replace("    for name in ('base','bt','ctp'):","    for name in ('base','ctp'):")
old="    expected={\n     'back_trader_python-':'792bad705c3f14a41c519322e6bee7c2cbae15faf33da622e895d9e2a743b4a7',"
s=s.replace(old,"""    v1=Path('/tmp/iter63-r23-install-20261109-s5p4b4ec')
    v1_rows=json.loads((v1/'source-manifest.json').read_text())
    v1_gateway={r['relative']:r['sha256'] for r in v1_rows if r['repo']==str(GATEWAY)}
    current_gateway={r['relative']:r['sha256'] for r in new_rows if r['repo']==str(GATEWAY)}
    if not v1_gateway or v1_gateway!=current_gateway: raise RuntimeError('Gateway differs from R23 fixed source')
    for row in (r for r in v1_rows if r['repo']==str(GATEWAY)):
        if hashlib.sha256(Path(row['copy']).read_bytes()).hexdigest()!=row['sha256']: raise RuntimeError(('R23 Gateway snapshot drift',row['copy']))
        head=subprocess.check_output(['git','-C',str(GATEWAY),'rev-parse','HEAD'],text=True).strip()
        blob=subprocess.run(['git','-C',str(GATEWAY),'show',head+':'+row['relative']],capture_output=True,check=False)
        if blob.returncode or hashlib.sha256(blob.stdout).hexdigest()!=row['sha256']:raise RuntimeError(('Gateway commit drift',row['relative']))
    expected={""")
old="    rows=[]\n    ctp_source=Path("
new="""    rows=[]
    gateway_wheel,=list((v1/'wheels').glob('bt_api_gateway-*.whl'))
    gateway_sha='52a4ac9f1b3c671eada2b3314f7a1766afccef78051109d02070e7b820abe685'
    if hashlib.sha256(gateway_wheel.read_bytes()).hexdigest()!=gateway_sha:raise RuntimeError('R23 Gateway wheel mismatch')
    (T/'wheels').mkdir(exist_ok=True);shutil.copyfile(gateway_wheel,T/'wheels'/gateway_wheel.name)
    rows.append({'source':str(gateway_wheel),'filename':gateway_wheel.name,'sha256':gateway_sha,'provenance':'R23 verified Gateway wheel'})
    ctp_source=Path("""
if old not in s:raise RuntimeError('fixed anchor missing')
s=s.replace(old,new)
# explicit source selection already enumerates BT test paths; use allowlisted untracked new tests as well
s=s.replace("allowed[BT].add('conftest.py')", "allowed[BT].update({'conftest.py','pytest.ini'})")
s=s.replace("    if 'bt' in plans:\n        queue.append(('bt', BT, copy('bt', BT, 'conftest.py')))\n", """    if 'bt' in plans:
        queue.append(('bt', BT, copy('bt', BT, 'conftest.py')))
        copy('bt', BT, 'pytest.ini')
        direct_helpers={x for x in allowed[BT] if x.startswith('tests/unit/brokers/direct/') and x.endswith('.py')}
        direct_helpers.add('tests/unit/brokers/__init__.py')
        for rel in sorted(direct_helpers): queue.append(('bt', BT, copy('bt', BT, rel)))
""")
p.write_text(s)
p=T/'run.py';s=p.read_text().replace("KINDS = ('gateway', 'sdk')","KINDS = ('bt', 'sdk')").replace("for kind in ('gateway', 'sdk'):","for kind in ('bt', 'sdk'):").replace("for kind in ('gateway', 'sdk')]])","for kind in ('bt', 'sdk')]])")
s=s.replace("'final-gateway','final-sdk'", "'final-bt','final-sdk'")
p.write_text(s)
p=T/'verify.py';s=p.read_text().replace("'REBUILT' if staged in {'gateway','sdk'} else ('REUSED_R21' if staged == 'ctp' else 'REUSED_R19')", "'REBUILT' if staged in {'bt','sdk'} else ('REUSED_R23' if staged == 'gateway' else ('REUSED_R21' if staged == 'ctp' else 'REUSED_R19'))")
s=s.replace("('back_trader_python-', 'bt_api_base-', 'bt_api_ctp-')", "('bt_api_gateway-', 'bt_api_base-', 'bt_api_ctp-')")
p.write_text(s)
p=T/'capture_selectors.py';s=p.read_text().replace("{'gateway', 'sdk'}", "{'bt', 'sdk'}");p.write_text(s)
p=P/'run_source.py';s=p.read_text().replace("{'gateway','sdk'}", "{'bt','sdk'}").replace('gateway|sdk','bt|sdk')
old="    source=Path('/Users/yunjinqi/Documents/new_projects/bt_api_py/bt_api/bt_api_ctp/src/bt_api_ctp/ctp')/('_ctp'+sysconfig.get_config_var('EXT_SUFFIX'))"
new="    source=Path('/tmp/iter63-r24-install-20261109-fEuNyr35/source/ctp/src/bt_api_ctp/ctp')/('_ctp'+sysconfig.get_config_var('EXT_SUFFIX'))"
s=s.replace("if kind in {'ctp','sdk'}:", "if kind in {'bt','sdk'}:").replace(old,new)
p.write_text(s)
print('R24 dual wheel/test adaptation drafted')
