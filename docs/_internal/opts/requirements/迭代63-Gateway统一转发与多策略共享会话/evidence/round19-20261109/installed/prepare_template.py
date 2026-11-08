from pathlib import Path
T=Path('/tmp/iter63-r19-install-20261109-uQ78MEA5')
p=T/'prepare.py';s=p.read_text()
a=s.index('NEW_RUNTIME = {'); b=s.index("PRIVATE =",a)
s=s[:a]+'''# Primary-supplied after freeze, explicit path lists, never scan-and-admit.
ALLOWLISTS = json.loads((T/'allowlists.json').read_text()) if (T/'allowlists.json').is_file() else {}
NEW_RUNTIME = {repo:set(ALLOWLISTS.get('runtime', {}).get(name, [])) for name,(repo,_) in REPOS.items()}
NEW_GATEWAY_TESTS = set(ALLOWLISTS.get('tests', {}).get('gateway', []))
NEW_BASE_TESTS = set(ALLOWLISTS.get('tests', {}).get('base', []))
''' +s[b:]
a=s.index('def fixed():');b=s.index('\ndef plan(name):',a)
s=s[:a]+'''def fixed():
    if (T/'fixed-wheels.json').exists():
        raise RuntimeError('fixed wheel staging already exists')
    previous=Path('/tmp/iter63-r18-install-20261109-GvDCI8TF')
    old_rows=json.loads((previous/'source-manifest.json').read_text())
    new_rows=json.loads((T/'source-manifest.json').read_text())
    old={r['relative']:r['sha256'] for r in old_rows if r['repo'] == str(BT)}
    new={r['relative']:r['sha256'] for r in new_rows if r['repo'] == str(BT)}
    if not old or old != new:
        raise RuntimeError(('BT differs from R18 source manifest',sorted(old.keys() ^ new.keys()),sorted(k for k in old.keys() & new.keys() if old[k] != new[k])))
    for row in (r for r in old_rows if r['repo'] == str(BT)):
        if hashlib.sha256(Path(row['copy']).read_bytes()).hexdigest() != row['sha256']:
            raise RuntimeError(('R18 BT source snapshot drift', row['copy']))
    print('R18_BT_SOURCE_MANIFEST_MATCH',len(old),flush=True)
    expected={
        'back_trader_python-':'792bad705c3f14a41c519322e6bee7c2cbae15faf33da622e895d9e2a743b4a7',
        'bt_api_okx-':'2243f8427d282e53f08b50e88832b149dfde0729afcbd8b3e768eb7a81ce1c07',
        'bt_api_binance-':'703f312d1889052293b49c390855f2df50d38084ced8a80029f4794ca6e1c5be',
    }
    rows=[]
    for prefix,digest in expected.items():
        found=list((previous/'wheels').glob(prefix+'*.whl'))
        if len(found)!=1 or hashlib.sha256(found[0].read_bytes()).hexdigest()!=digest:
            raise RuntimeError(('fixed R18 wheel missing or mismatched',prefix))
        source=found[0]; target=T/'wheels'/source.name; target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
        rows.append({'source':str(source),'filename':source.name,'sha256':digest,'provenance':'R18 verified wheel'})
        print('FIXED_R18',source.name,digest,flush=True)
    (T/'fixed-wheels.json').write_text(json.dumps(rows,indent=2)+'\\n')

''' +s[b:]
s=s.replace("    plans = {name: plan(name) for name in REPOS}", "    selector_groups = json.loads((T/'selectors.json').read_text())\n    plans = {name: plan(name) for name in selector_groups}")
s=s.replace("{x.split('::', 1)[0] for x in plans[name]} for name, (repo, _) in REPOS.items()", "{x.split('::', 1)[0] for x in plans.get(name, ())} for name, (repo, _) in REPOS.items()")
s=s.replace("allowed[CTP] = files(CTP, True, 'tests') | {x.split('::', 1)[0] for x in plans['ctp']}","allowed[CTP] |= set(ALLOWLISTS.get('tests', {}).get('ctp', []))")
s=s.replace("    for name, (repo, _) in REPOS.items():\n        for rel in plans[name]:", "    for name in plans:\n        repo, _ = REPOS[name]\n        for rel in plans[name]:")
s=s.replace("    queue.append(('bt', BT, copy('bt', BT, 'conftest.py')))\n", "    if 'bt' in plans:\n        queue.append(('bt', BT, copy('bt', BT, 'conftest.py')))\n")
s=s.replace("    bt_helpers = {x for x in allowed[BT] if x.startswith('tests/unit/live_state/') and x.endswith('.py')}\n    bt_helpers |= {'tests/integration/iter60_service_ledger_host_support.py'}", "    bt_helpers = {x for x in allowed[BT] if x.startswith('tests/unit/live_state/') and x.endswith('.py')} if 'bt' in plans else set()\n    if 'bt' in plans:\n        bt_helpers |= {'tests/integration/iter60_service_ledger_host_support.py'}\n    if 'base' in plans:\n        for rel in sorted(x for x in allowed[BASE] if x.startswith('tests/') and x.endswith('.py')):\n            queue.append(('base', BASE, copy('base', BASE, rel)))")
s=s.replace("    copy('sdk', CTP, 'tests/test_iter63_prepared_cancel.py', roots['sdk']/'bt_api/bt_api_ctp/tests/test_iter63_prepared_cancel.py')", "    copy('sdk', CTP, 'tests/test_iter63_prepared_cancel.py', roots['sdk']/'bt_api/bt_api_ctp/tests/test_iter63_prepared_cancel.py')\n    # Exactly the five tracked public sample files used by test_service_config_io.\n    for name in ('unconfigured-client.yaml','strategy-readonly.yaml','portfolio-analysis-client.yaml','account-service.yaml','portfolio-analysis-service.yaml'):\n        rel='examples/services/'+name\n        if rel not in files(SDK, True, rel):\n            raise RuntimeError(('public sample not tracked', rel))\n        allowed[SDK].add(rel)\n        copy('sdk', SDK, rel)")
p.write_text(s)
p=T/'capture_selectors.py';s=p.read_text().replace("set(plans) != {'base', 'gateway', 'ctp', 'sdk', 'bt'}", "not {'base', 'gateway', 'ctp', 'sdk'}.issubset(plans) or set(plans) - {'base', 'gateway', 'ctp', 'sdk', 'bt'}");p.write_text(s)
p=T/'run.py';s=p.read_text().replace('for kind in KINDS:\n            source =',"for kind in ('base', 'gateway', 'ctp', 'sdk'):\n            source =").replace('if len(wheels) != 2:', 'if len(wheels) != 3:').replace('expected exactly two fixed wheels before build','expected three fixed wheels before build').replace("for kind in KINDS]])","for kind in ('base', 'gateway', 'ctp', 'sdk')]])").replace('expected two fixed and five rebuilt wheels','expected three fixed and four rebuilt wheels');p.write_text(s)
p=T/'verify.py';s=p.read_text().replace("print('REBUILT', name,", "print('REUSED_R18' if staged == 'bt' else 'REBUILT', name,")
s=s.replace("for row in fixed:\n    wheel", "for row in fixed:\n    if row['filename'].startswith('back_trader_python-'):\n        wheel = T/'wheels'/row['filename']\n        if hashlib.sha256(wheel.read_bytes()).hexdigest() != row['sha256']:\n            raise RuntimeError(('fixed wheel hash mismatch', wheel.name))\n        continue\n    wheel")
p.write_text(s)
print('Draft prepared; requires explicit SOURCE_FROZEN, allowlists.json and primary selectors')
