from __future__ import annotations
import hashlib, json, pathlib, sys, tomllib, xml.etree.ElementTree as ET
from collections import Counter

root=pathlib.Path(r'D:\temp\iteration41-parent-r4-r3r3-composite-20260927-r1')
qa=root/'qa'; parent=root/'parent-source'; overlay=root/'main-overlay'

def sha_bytes(data:bytes)->str: return hashlib.sha256(data).hexdigest()
def sha_file(path:pathlib.Path)->str: return sha_bytes(path.read_bytes())
def tree_entries(base:pathlib.Path):
    rows=[]
    for p in sorted(base.rglob('*')):
        if not p.is_file(): continue
        rel=p.relative_to(base)
        if any(x in {'__pycache__','.pytest_cache','.ruff_cache','.mypy_cache'} for x in rel.parts) or p.suffix=='.pyc':
            continue
        data=p.read_bytes()
        rows.append({'path':rel.as_posix(),'size':len(data),'sha256':sha_bytes(data)})
    tree_digest=sha_bytes(''.join(f"{r['sha256']}  {r['path']}\n" for r in rows).encode())
    return rows,tree_digest

def package_tree(root_path:pathlib.Path,module:str):
    path=root_path/module
    entries,digest=tree_entries(path)
    return {'root':str(root_path.resolve()),'package':str(path.resolve()),'file_count':len(entries),'tree_sha256':digest}

# Verify R4 payload copy; only the deliberate additional policy-negative test may differ.
pre=json.loads((root/'provenance'/'premerge-input-audit.json').read_text(encoding='utf-8'))
r4=pre['r4']; r4_mismatches=[]; r4_exact=0
for entry in r4['copied']:
    rel=pathlib.Path(entry['path'])
    target=parent/rel
    actual=sha_file(target)
    if actual.lower()==entry['sha256'].lower():
        r4_exact+=1
    else:
        r4_mismatches.append({'path':rel.as_posix(),'expected':entry['sha256'],'actual':actual})
allowed={'tests/test_cancellation_dispatch_resolution_control.py'}
if {m['path'] for m in r4_mismatches} != allowed:
    raise SystemExit(f'unexpected R4 payload diff: {r4_mismatches!r}')
if r4_exact + len(r4_mismatches) != len(r4['copied']):
    raise SystemExit('R4 copied payload count mismatch')

# Verify the preserved R3r3 immutable source/test copies against its manifest.
r3dir=root/'provenance'/'r3r3-original'
r3manifest=json.loads((r3dir/'snapshot-manifest.json').read_text(encoding='utf-8'))
r3_expected={e['path'].replace('\\','/'):e['sha256'] for e in r3manifest['files']}
r3_original_checks={}
for rel in ['src/fake_dispatch_authority.py','tests/test_cancel_dispatch_resolution_proof.py',
            'tests/test_cancel_dispatch_resolution_proof_store.py','tests/fixtures/fake_dispatch_authority_v2.py']:
    local={'src/fake_dispatch_authority.py':'fake_dispatch_authority.py',
           'tests/test_cancel_dispatch_resolution_proof.py':'test_cancel_dispatch_resolution_proof.py',
           'tests/test_cancel_dispatch_resolution_proof_store.py':'test_cancel_dispatch_resolution_proof_store.py',
           'tests/fixtures/fake_dispatch_authority_v2.py':'fake_dispatch_authority_v2.py'}[rel]
    expected=r3_expected[rel]
    actual=sha_file(r3dir/local)
    if actual.lower()!=expected.lower(): raise SystemExit(f'R3r3 provenance mismatch {rel}: {actual} != {expected}')
    r3_original_checks[rel]={'sha256':actual,'matches_frozen_manifest':True}

parent_rows,parent_tree=tree_entries(parent)
overlay_rows,overlay_tree=tree_entries(overlay)
source_map_path=qa/'source-roots.json'; source_map=json.loads(source_map_path.read_text(encoding='utf-8'))
module_names={'parent':'bt_api_py','base':'bt_api_base','ctp':'bt_api_ctp','execution':'bt_api_execution',
'risk':'bt_api_risk','monitor':'bt_api_monitor','gateway':'bt_api_gateway','transport_zmq':'bt_api_transport_zmq',
'agent':'backtrader_agent','skills':'backtrader_skills','mcp':'backtrader_mcp'}
metadata=json.loads((qa/'source-only-metadata-manifest.json').read_text(encoding='utf-8'))
imported={'parent','base','execution','risk','monitor'}
package_sources={k:package_tree(pathlib.Path(source_map[k]).resolve(strict=True),module_names[k])
                 for k in sorted(imported)}

# Guard log analysis on each successful guarded invocation.
guard_labels=['origin-guard-parent-focus-r3','origin-guard-original-three-r1','origin-guard-five-r1','origin-guard-cancel-control-r1']
guard_reports={}
for label in guard_labels:
    rows=[]
    for log in sorted((qa/label).glob('*.jsonl')):
        for line in log.read_text(encoding='utf-8').splitlines():
            if line.strip(): rows.append(json.loads(line))
    expected_denials={'origin-rejected','native-import-blocked','network-blocked','private-config-blocked'}
    denials=[r for r in rows if r.get('kind') in expected_denials]
    top_imports=sorted({r['fullname'] for r in rows if r.get('kind')=='source-import' and '.' not in r.get('fullname','')})
    parent_origins=sorted({r['origin'] for r in rows if r.get('kind')=='source-import' and r.get('fullname')=='bt_api_py'})
    expected_parent=str((pathlib.Path(source_map['parent'])/'bt_api_py'/'__init__.py').resolve())
    if denials or parent_origins != [expected_parent]:
        raise SystemExit(f'guard verification failed {label}: denials={denials!r}, origins={parent_origins!r}')
    guard_reports[label]={'process_count':len(list((qa/label).glob('*.jsonl'))),'record_count':len(rows),
                          'kind_counts':dict(Counter(r.get('kind') for r in rows)),
                          'top_package_imports':top_imports,'parent_origin':parent_origins[0],
                          'native_network_config_or_origin_denials':0}

# Parse test outcomes.
def junit(path):
    tree=ET.parse(path)
    cases=list(tree.iter('testcase'))
    return {'path':str(path),'sha256':sha_file(path),'tests':len(cases),
            'failures':sum(1 for x in tree.iter('failure')),'errors':sum(1 for x in tree.iter('error')),
            'skipped':sum(1 for x in tree.iter('skipped')),
            'nodes':[{'classname':c.get('classname'),'name':c.get('name')} for c in cases]}
results={
 'parent_focus_guarded':junit(qa/'parent-focus-guarded-r3.xml'),
 'main_original_three':junit(qa/'original-three-r1.xml'),
 'main_five_file_focus':junit(qa/'five-file-focus-r1.xml'),
 'main_cancel_control_additional':junit(qa/'main-cancel-control-r1.xml'),
 'main_three_layout_retry_extra_parameter':junit(qa/'main-three-r2.xml'),
 'main_three_initial_layout_failure':junit(qa/'main-three-r1.xml'),
}
for k in ['parent_focus_guarded','main_original_three','main_five_file_focus','main_cancel_control_additional']:
    v=results[k]
    if v['failures'] or v['errors'] or v['skipped']:
        raise SystemExit(f'final focused suite not clean {k}: {v}')

# Capture evidence file hashes without recursively including the receipts being written.
evidence_names=[
 'parent-focus-guarded-r3.log','parent-focus-guarded-r3.xml','parent-focus-guarded-r3.exit.txt',
 'original-three-r1.log','original-three-r1.xml','original-three-r1.exit.txt',
 'five-file-focus-r1.log','five-file-focus-r1.xml','five-file-focus-r1.exit.txt',
 'main-cancel-control-r1.log','main-cancel-control-r1.xml','main-cancel-control-r1.exit.txt',
 'main-three-r1.log','main-three-r1.xml','main-three-r1.exit.txt',
 'main-three-r2.log','main-three-r2.xml','main-three-r2.exit.txt',
 'ruff-r1.log','ruff-r1.exit.txt','ruff-source-r1.log','ruff-source-r1.exit.txt',
 'source-roots.json','source-only-metadata-manifest.json','summarize_guard_all.py','commands.txt',
 'finalize_composite.py','write_test_diffs.py','write_authority_diff.py','prepare_main_overlay.py',
]
evidence={}
for name in evidence_names:
    p=qa/name
    if p.is_file(): evidence[name]={'size':p.stat().st_size,'sha256':sha_file(p)}
for label in guard_labels:
    for p in sorted((qa/label).glob('*.jsonl')):
        evidence[f'{label}/{p.name}']={'size':p.stat().st_size,'sha256':sha_file(p)}
for p in sorted((root/'provenance').glob('*.diff')):
    evidence[f'provenance/{p.name}']={'size':p.stat().st_size,'sha256':sha_file(p)}

# Main source input and composite lock.
source_manifest={
 'schema':'iteration41-parent-r4-r3r3-composite-source-manifest.v1',
 'disposable_snapshot_id':'iteration41-parent-r4-r3r3-composite-20260927-r1',
 'classification':'isolated source-only composition QA; no distribution build/install; not release acceptance',
 'parent_base':{'repo':pre['parent_base']['repo'],'head':pre['parent_base']['commit'],'tree':pre['parent_base']['tree'],
   'git_archive_sha256':pre['parent_base']['git_archive_sha256'],'git_status':pre['parent_base']['git_status_at_capture'],
   'premerge_audit_sha256':sha_file(root/'provenance'/'premerge-input-audit.json'),
  'archive_scope':'pyproject.toml + bt_api_py only; dirty nested gitlinks excluded'},
 'frozen_inputs':{
   'parent_r4':{'path':r4['frozen_path'],'payload_manifest_sha256':r4['payload_manifest_sha256'],
      'declared_payload_count':r4['payload_count'],'source_test_files_verified':r4_exact,
      'only_difference':r4_mismatches[0],'generated_pyc_excluded':r4['excluded_generated_bytecode']},
   'parent_r3r3_issuer':{'path':str(r3dir),'snapshot_manifest_sha256':sha_file(r3dir/'snapshot-manifest.json'),
      'original_fake_authority_sha256':r3_expected['src/fake_dispatch_authority.py'],
      'frozen_r3r3_module_sha256_reused_in_candidate':False,
      'preserved_original_checks':r3_original_checks,
      'conflict_resolution':'R3r3 carried the atomic issuer implementation but its constructor binding was weaker; use the stricter R4 fake authority implementation and adapt only tests/fixtures to its exact offline allowlist.'},
   'execution':{'source_root':source_map['execution'],'manifest_sha256':r3manifest['source_context']['execution_manifest_sha256']},
   'risk':{'source_root':source_map['risk'],'manifest_sha256':r3manifest['source_context']['risk_manifest_sha256']},
 },
 'candidate_parent':{'root':str(parent.resolve()),'source_file_count':len(parent_rows),'source_tree_sha256':parent_tree,
   'files':parent_rows,'pyproject_version':tomllib.loads((parent/'pyproject.toml').read_text(encoding='utf-8'))['project']['version'],
   'version_status':'inherited 0.15.5; no unique package distribution version assigned. This is a release/pin blocker because source differs from the prior 0.15.5 identity.',
   'r4_payload_exact_files':r4_exact,'r4_test_only_delta_count':len(r4_mismatches),
   'r4_changed_module_hashes':{
     name:sha_file(parent/'bt_api_py'/'runtime_plugins'/name)
     for name in ['cancellation_control.py','fake_dispatch_authority.py','managed.py']},
   'effective_fake_authority_sha256':sha_file(parent/'bt_api_py'/'runtime_plugins'/'fake_dispatch_authority.py'),
   'r3r3_tests_adapted_test_only':[
     {'path':'tests/test_cancel_dispatch_resolution_proof.py','diff':str(root/'provenance'/'r3r3-issuer-proof-adapted-to-r4.diff'),'sha256':sha_file(root/'provenance'/'r3r3-issuer-proof-adapted-to-r4.diff')},
     {'path':'tests/test_cancel_dispatch_resolution_proof_store.py','diff':str(root/'provenance'/'r3r3-issuer-store-adapted-to-r4.diff'),'sha256':sha_file(root/'provenance'/'r3r3-issuer-store-adapted-to-r4.diff')},
     {'path':'tests/test_cancellation_dispatch_resolution_control.py','diff':str(root/'provenance'/'r4-wrong-policy-negative-test.diff'),'sha256':sha_file(root/'provenance'/'r4-wrong-policy-negative-test.diff')},
   ],
   'authority_source_diff':{'path':str(root/'provenance'/'r3r3-authority-to-r4-stricter-source.diff'),
     'sha256':sha_file(root/'provenance'/'r3r3-authority-to-r4-stricter-source.diff'),
     'summary':'R3r3 fake authority is preserved as provenance; composite uses R4 authority with stricter registered-offline fake contract/policy enforcement.'}},
 'main_overlay':{'root':str(overlay.resolve()),'source_file_count':len(overlay_rows),'source_tree_sha256':overlay_tree,
    'files':overlay_rows,
    'parent_source_embedded':False,'parent_source_map':str(source_map_path),'source_map_sha256':sha_file(source_map_path),
    'metadata_root':metadata['metadata_root'],'metadata_manifest_sha256':sha_file(qa/'source-only-metadata-manifest.json'),
    'source_only_versions':{k:v['version'] for k,v in metadata['packages'].items()},
    'metadata_not_installed_artifact':True,
    'source_hashes':package_sources,
    'explicit_test_only_layout_and_origin_changes':['three integration test files restored under tests/integration/','R4 cancellation-control test origin assertion resolves explicit parent source map'],
    'main_origin_test_diff':{'path':str(root/'provenance'/'main-overlay-origin-map-test.diff'),
      'sha256':sha_file(root/'provenance'/'main-overlay-origin-map-test.diff')}},
 'results':results,
 'guard':{'guard_module':r'D:\temp\iteration41-main-source-qa-20260926\origin-guard-r4\sitecustomize.py',
          'guard_module_sha256':sha_file(pathlib.Path(r'D:\temp\iteration41-main-source-qa-20260926\origin-guard-r4\sitecustomize.py')),
          'network_policy':'loopback-only; no non-loopback/DNS connection permitted',
          'fixture_root_policy':'synthetic pytest config/files allowed only inside per-run temp fixture root; protected runtime config denied',
          'runs':guard_reports},
 'ruff':{'runner':r'C:\anaconda3\Scripts\ruff.exe','version':'0.16.2','pytest_venv_ruff':'not installed',
         'selected_EFI_check_exit':1,'selected_EFI_check_findings':3,
         'selected_findings':['test_cancel_dispatch_resolution_proof_store.py:28 E402','test_cancel_dispatch_resolution_proof_store.py:28 I001','test_cancellation_dispatch_resolution_control.py:25 I001'],
         'production_files_in_selected_check_findings':0,
         'default_source_check_exit':1,'default_source_check_findings':['cancellation_control.py:1814 S110','cancellation_control.py:1819 S110'],
         'scope_note':'No formatter or production lint fixes were made in frozen source.'},
 'release_limitations':['No wheel was built or installed.','Parent distribution still declares 0.15.5; this composite has distinct source bytes under an occupied version identity.','No default pins or main production routes changed.','Fake/source-only test acceptance only; no real provider, native SDK, credentials, private config, network, or release authorization.','Four dirty nested parent gitlinks were not archived; execution/risk/base/monitor were supplied as explicit separate source roots.'],
}
source_manifest_path=qa/'composite-source-manifest.json'
source_manifest_path.write_text(json.dumps(source_manifest,indent=2,sort_keys=True)+'\n',encoding='utf-8')
source_manifest_sha=sha_file(source_manifest_path)
receipt={
 'schema':'iteration41-parent-r4-r3r3-composite-qa-receipt.v1',
 'disposable_snapshot_id':source_manifest['disposable_snapshot_id'],
 'classification':source_manifest['classification'],
 'source_manifest_path':str(source_manifest_path),'source_manifest_sha256':source_manifest_sha,
 'commands_path':str(qa/'commands.txt'),'commands_sha256':sha_file(qa/'commands.txt'),
 'parent_focus':'44 passed, 0 skipped, one existing pytest config warning (guarded r2 run)',
 'main_original_three':'3 passed, 0 skipped, one existing Backtrader Quandl deprecation warning',
 'main_five_file_focus':'73 passed, 0 skipped, one existing Backtrader Quandl deprecation warning',
 'main_cancel_control_additional':'20 passed, 0 skipped, no warnings',
 'setup_failure_preserved':'main-three-r1 had 4 failures because flattened test overlay gave child process wrong cwd/project root; corrected layout reruns passed; this was test harness packaging, not product behavior.',
 'r4_r3r3_merge':'R4 stricter authority retained; R3r3 original module/tests preserved in provenance; test-only fixture adaptations are diff-bound.',
 'parent_version':'0.15.5 inherited and unallocated for this composite; no wheel/pin change; release blocked.',
 'fake_only_no_provider_native_network_credentials_private_config':True,
 'artifact_files':evidence,
}
receipt_path=qa/'composite-qa-receipt.json'
receipt_path.write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n',encoding='utf-8')
receipt_text=f'''# Parent R4 + R3r3 composite QA\n\n- Snapshot: `{source_manifest["disposable_snapshot_id"]}`\n- Source manifest SHA-256: `{source_manifest_sha}`\n- Parent fake issuer/control focus: **44 passed**, 0 skipped.\n- Main bridge original nodes: **3 passed**, 0 skipped.\n- Main bridge five-file focus: **73 passed**, 0 skipped.\n- Additional main cancellation-control file: **20 passed**, 0 skipped.\n- R4 implementation retained; R3r3 source and unmodified tests preserved under `provenance/r3r3-original`. Only test/fixture adaptations are present in the candidate, with unified diffs under `provenance`.\n- Source-origin/native/network guard recorded no rejection, native import, non-loopback network attempt, or protected-config read in successful runs. Imported packages were parent, base, execution, risk, and monitor from the explicit map.\n- Parent package still says `0.15.5`; this composite has unique source bytes under that occupied distribution version. No package version, default pin, wheel, or production route was changed. **Release remains blocked.**\n- Initial flattened-overlay setup failure is retained in `main-three-r1.*`; corrected exact reruns pass.\n- Ruff: selected EFI check reports three test import-order findings; default source check reports two existing `S110` findings in `cancellation_control.py`. No frozen production edits were made.\n\nSee `commands.txt` for exact run commands/environment. See `composite-source-manifest.json` for source identities, package hashes, JUnit/log hashes, guard counts, source-only metadata versions, and limitations.\n'''
(qa/'composite-qa-receipt.md').write_text(receipt_text,encoding='utf-8')
print(json.dumps({'source_manifest':str(source_manifest_path),'source_manifest_sha256':source_manifest_sha,
                  'receipt':str(receipt_path),'parent_tree_sha256':parent_tree,'overlay_tree_sha256':overlay_tree,
                  'r4_exact':r4_exact,'r4_test_deltas':r4_mismatches,
                  'result_counts':{k:(v['tests'],v['failures'],v['errors'],v['skipped']) for k,v in results.items()},
                  'guard':{k:v['process_count'] for k,v in guard_reports.items()}},indent=2))
