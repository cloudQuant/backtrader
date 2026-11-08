from pathlib import Path
T=Path('/tmp/iter63-r18-install-20261109-GvDCI8TF')
p=T/'prepare.py'; s=p.read_text()
s=s.replace("CTP: {'src/bt_api_ctp/gateway_cancel_return_projection.py', 'src/bt_api_ctp/gateway_cancel_source.py'},\n    SDK: set(),", "CTP: set(),\n    SDK: {'bt_api_py/gateway_strategy_client.py'},")
s=s.replace("NEW_GATEWAY_TESTS = {'tests/test_iter63_cancel_error_attribution.py'}",'NEW_GATEWAY_TESTS = set()')
s=s.replace("NEW_BASE_TESTS = {'tests/test_gateway_execution_cancel_attribution.py', 'tests/test_prepared_cancel_source.py'}",'NEW_BASE_TESTS = set()')
s=s.replace("{'tests/unit/live_state/test_gateway_pending_cancel.py'}", "{'tests/unit/live_state/test_gateway_pending_enumeration.py'}")
s=s.replace("allowed[BT].add('conftest.py')", "allowed[BT].update({'conftest.py', 'pytest.ini'})")
s=s.replace("queue.append(('bt', BT, copy('bt', BT, 'conftest.py')))", "queue.append(('bt', BT, copy('bt', BT, 'conftest.py')))\n    copy('bt', BT, 'pytest.ini')\n    # Copy all tracked Base Python helpers so dynamic relative imports are captured.\n    for rel in sorted(x for x in allowed[BASE] if x.startswith('tests/') and x.endswith('.py')):\n        queue.append(('base', BASE, copy('base', BASE, rel)))")
a=s.index('def fixed():'); b=s.index('\ndef plan(name):',a)
s=s[:a]+'''def fixed():
    if (T/'fixed-wheels.json').exists():
        raise RuntimeError('fixed wheel staging already exists')
    previous = Path('/tmp/iter63-r17-install-20261109-oNtWsjp3')
    commits = json.loads(Path('/tmp/iter63-r17-primary/product-commits.json').read_text())
    old_rows = json.loads((previous/'source-manifest.json').read_text())
    new_rows = json.loads((T/'source-manifest.json').read_text())
    for name in ('base', 'gateway', 'ctp'):
        repo, _ = REPOS[name]
        expected = {'base':'1b08a6a0124b89df6024968a2a9f8f0351831028',
                    'gateway':'fc54afc8893e9fd9ca009c183999baa4811a9ff3',
                    'ctp':'1f3d00eab6c53a4ae6e6a72f932dd191d06a64f5'}[name]
        head = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
        if head != expected:
            raise RuntimeError(('fixed package HEAD changed', name, head))
        old = {r['relative']:r['sha256'] for r in old_rows if r['repo'] == str(repo)}
        new = {r['relative']:r['sha256'] for r in new_rows if r['repo'] == str(repo)}
        if not old or old != new:
            raise RuntimeError(('fixed package R17 source manifest mismatch', name, sorted(old.keys() ^ new.keys()), sorted(k for k in old.keys() & new.keys() if old[k] != new[k])))
        for row in (r for r in old_rows if r['repo'] == str(repo)):
            if hashlib.sha256(Path(row['copy']).read_bytes()).hexdigest() != row['sha256']:
                raise RuntimeError(('R17 source snapshot drift', row['copy']))
        print('R17_FIXED_SOURCE_MANIFEST_MATCH', name, head, len(old), flush=True)
    expected_wheels = {
        'bt_api_base-':'0a0cd2c19c4873d1a866589794cade29116fa503d0d9341bc8be1dcb66e5a187',
        'bt_api_gateway-':'6e62c242317527892d7bb8dadc511f13d733863eb8e477e810d25be108d63159',
        'bt_api_ctp-':'9a55436a1b392e5957675bfdcd2ee37239d3860b948f1931f13290c995c56402',
        'bt_api_okx-':'2243f8427d282e53f08b50e88832b149dfde0729afcbd8b3e768eb7a81ce1c07',
        'bt_api_binance-':'703f312d1889052293b49c390855f2df50d38084ced8a80029f4794ca6e1c5be',
    }
    rows=[]
    for prefix, expected in expected_wheels.items():
        found = list((previous/'wheels').glob(prefix+'*.whl'))
        if len(found) != 1: raise RuntimeError(('R17 wheel missing or ambiguous', prefix))
        source=found[0]; digest=hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != expected: raise RuntimeError(('R17 wheel hash mismatch', source.name))
        destination=T/'wheels'/source.name; destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,destination)
        rows.append({'source':str(source),'filename':source.name,'sha256':digest,'provenance':'R17 verified wheel'})
        print('FIXED_R17',source.name,digest,flush=True)
    (T/'fixed-wheels.json').write_text(json.dumps(rows,indent=2)+'\\n')

''' +s[b:]
s=s.replace("    commits = json.loads(Path('/tmp/iter63-r17-primary/product-commits.json').read_text())\n",'')
p.write_text(s)
p=T/'run.py';s=p.read_text().replace('for kind in KINDS:\n            source =',"for kind in ('sdk', 'bt'):\n            source =").replace('if len(wheels) != 2:', 'if len(wheels) != 5:').replace('expected exactly two fixed wheels before build','expected exactly five fixed wheels before build').replace("for kind in KINDS]])","for kind in ('sdk', 'bt')]])").replace('expected two fixed and five rebuilt wheels','expected five fixed and two rebuilt wheels');p.write_text(s)
p=T/'verify.py';s=p.read_text().replace("print('REBUILT', name,", "print('REUSED_R17' if staged in {'base','gateway','ctp'} else 'REBUILT', name,")
s=s.replace("for row in fixed:\n    wheel", "for row in fixed:\n    if row['filename'].startswith(('bt_api_base-', 'bt_api_gateway-', 'bt_api_ctp-')):\n        wheel = T/'wheels'/row['filename']\n        if hashlib.sha256(wheel.read_bytes()).hexdigest() != row['sha256']:\n            raise RuntimeError(('fixed wheel hash mismatch', wheel.name))\n        continue\n    wheel")
a=s.index("compiled = list((T/'source/ctp/build')");b=s.index("layout = json.loads",a)
s=s[:a]+'''target = list((TARGET/'bt_api_ctp/ctp').glob('_ctp*.so'))
if len(target) != 1 or hashlib.sha256(target[0].read_bytes()).hexdigest() != 'b49b009529b197025afe6561285fda428959240b9de515fa76bfa165719971f5':
    raise RuntimeError('CTP_R17_EXTENSION_MISMATCH')
print('CTP_REUSED_R17_EXTENSION_SHA256', hashlib.sha256(target[0].read_bytes()).hexdigest(), flush=True)
''' +s[b:];p.write_text(s)
print('R18 preparation edits written; execution remains freeze-gated')
