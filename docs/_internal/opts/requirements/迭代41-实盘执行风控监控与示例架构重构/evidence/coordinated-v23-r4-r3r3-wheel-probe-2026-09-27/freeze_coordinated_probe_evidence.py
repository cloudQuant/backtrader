from __future__ import annotations
import collections, hashlib, json, pathlib, shutil, zipfile, xml.etree.ElementTree as ET
from datetime import datetime, timezone

ROOT=pathlib.Path(r'D:\temp\iteration41-coordinated-release-probe-20260927-r1')
CAND=ROOT/'candidate-v3'; RUN=ROOT/'installed-wheel-v3-clean-runs'
OUT=ROOT
EXCLUDE_DIRS={'.git','__pycache__','.pytest_cache','.ruff_cache','build','dist','.venv','venv'}
EXCLUDE_SUFFIXES={'.pyc','.pyo'}
def sha_bytes(b): return hashlib.sha256(b).hexdigest()
def sha_file(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def walk(root):
 root=pathlib.Path(root)
 for p in sorted(root.rglob('*')):
  rel=p.relative_to(root)
  if p.is_dir() or any(x in EXCLUDE_DIRS or x.endswith('.egg-info') for x in rel.parts) or p.suffix.lower() in EXCLUDE_SUFFIXES: continue
  yield p,rel.as_posix()
def fmap(root): return {r:{'sha256':sha_file(p),'size_bytes':p.stat().st_size} for p,r in walk(root)}
def load(path): return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))
def dump(path,obj): pathlib.Path(path).write_text(json.dumps(obj,indent=2,sort_keys=True,ensure_ascii=False)+'\n',encoding='utf-8',newline='\n')

# Keep the prior manifest artifact byte-for-byte for historical context, then refresh candidate copy.
old_candidate_manifest=CAND/'VERSIONED-SOURCE-MANIFEST.json'
old_copy=ROOT/'logs'/'VERSIONED-SOURCE-MANIFEST-pre-final.json'
if old_candidate_manifest.exists() and not old_copy.exists(): shutil.copyfile(old_candidate_manifest,old_copy)
source_manifest=OUT/'coordinated-probe-source-manifest-final.json'
if not source_manifest.exists(): raise SystemExit('missing final source manifest')
shutil.copyfile(source_manifest,old_candidate_manifest)
manifest_sha=sha_file(source_manifest)

# Verify versioned package sources exactly match the frozen dual build inputs.
input_path=ROOT/'build-input-manifest-v4.json'; build_inputs=load(input_path)
package_match={}
for key,candidate_name in [('execution','execution-project'),('parent','parent-source')]:
 expected={x['path']:x['sha256'] for x in build_inputs['packages'][key]['files']}
 actual=fmap(CAND/candidate_name)
 missing=sorted(set(expected)-set(actual)); extra=sorted(set(actual)-set(expected))
 changed=[{'path':p,'expected_sha256':expected[p],'actual_sha256':actual[p]['sha256']} for p in sorted(set(expected)&set(actual)) if expected[p]!=actual[p]['sha256']]
 package_match[key]={'source_file_count':len(actual),'build_input_file_count':len(expected),'missing':missing,'extra':extra,'changed':changed,'exact_match':not(missing or extra or changed)}

# Capture installed test invocation identities/counts and the cross-suite overlap.
junit_names=['main-bridge-installed-wheel-v3-clean.xml','main-cancel-control-installed-wheel-v3-clean.xml','main-artifact-set-installed-wheel-v3-clean.xml','parent-issuer-control-installed-wheel-v3-clean.xml']
suites=[]; all_nodes=[]
for name in junit_names:
 p=RUN/name; doc=ET.parse(p).getroot(); suite_nodes=[doc] if doc.tag=='testsuite' else list(doc.iter('testsuite'))
 cases=[]
 for tc in doc.iter('testcase'):
  key=(tc.attrib.get('classname',''),tc.attrib.get('name','')); all_nodes.append(key); cases.append({'classname':key[0],'name':key[1]})
 counts={key:sum(int(s.attrib.get(key,'0')) for s in suite_nodes) for key in ['tests','failures','errors','skipped']}
 stem=name[:-4]
 exit_code=int((RUN/(stem+'.exit.txt')).read_text().strip())
 suites.append({'junit':name,'sha256':sha_file(p),**counts,'exit':exit_code,'test_cases':cases})
node_counts=collections.Counter(all_nodes)
unique_nodes=len(node_counts)
duplicate_nodes=[{'classname':cls,'name':name,'executions':n} for (cls,name),n in sorted(node_counts.items()) if n>1]

# Final clean run guards only; earlier diagnostics are accounted separately below.
guard_counts=collections.Counter(); guard_files=[]; guard_prohibited=[]
final_prefixes=[x[:-4] for x in junit_names]
for stem in final_prefixes:
 gdir=RUN/(stem+'-guard')
 for p in sorted(gdir.glob('*.jsonl')):
  guard_files.append({'path':str(p),'sha256':sha_file(p),'size_bytes':p.stat().st_size})
  for line in p.read_text(encoding='utf-8').splitlines():
   if not line.strip(): continue
   ev=json.loads(line); kind=ev.get('kind','<missing>'); guard_counts[kind]+=1
   if kind in {'origin-rejected','native-import-blocked','network-blocked','private-config-blocked'}: guard_prohibited.append({'kind':kind,'log':p.name,'event':ev})
origins=[]; native_lines=[]
for s in suites:
 log=(RUN/s['junit'].replace('.xml','.log')).read_text(encoding='utf-8',errors='replace')
 for line in log.splitlines():
  if line.startswith('INSTALLED_ORIGINS_JSON '): origins.append({'suite':s['junit'],'origins':json.loads(line.split(' ',1)[1])})
  if line.startswith('NATIVE_MODULES_LOADED '): native_lines.append({'suite':s['junit'],'modules':json.loads(line.split(' ',1)[1])})

# Prior diagnostic failures are retained, not counted as final results.
prev=[]
def prior_test(rel, title):
 p=ROOT/rel
 if not p.exists(): return
 doc=ET.parse(p).getroot(); ss=[doc] if doc.tag=='testsuite' else list(doc.iter('testsuite'))
 totals={k:sum(int(x.attrib.get(k,'0')) for x in ss) for k in ['tests','failures','errors','skipped']}
 prev.append({'title':title,'junit':str(p),'junit_sha256':sha_file(p),'log':str(p.with_suffix('.log')),'log_sha256':sha_file(p.with_suffix('.log')) if p.with_suffix('.log').exists() else None,'exit':int(p.with_suffix('.exit.txt').read_text().strip()) if p.with_suffix('.exit.txt').exists() else None,**totals})
prior_test('installed-wheel-v3-clean-runs/main-bridge-73.xml','nonfinal main bridge run: origin guard caught installed bt_api_base shadowing expected source; 67 pass, 5 fail, 1 skip; one additional L2 runner failure; corrected clean venv run passed all 73')
prior_test('installed-wheel-v3-runs/parent-issuer-control-installed-wheel-v3.xml','nonfinal parent copied-test harness collection setup: exit 2; corrected v3b copy run passed 44')
prior_test('installed-wheel-v3-runs/parent-issuer-control-installed-wheel-v3b.xml','nonfinal corrected v3b parent issuer/control run: 44 pass; superseded by final clean installed-wheel rerun also 44')

# Exact command definitions inherited through the persisted PowerShell runner.
script_path=ROOT/'run_installed_suite_v3.ps1'
py=ROOT/'venv-installed-wheel-v3-clean'/'Scripts'/'python.exe'
runner=ROOT/'run_installed_wheel_pytest_v3.py'
command_files={
 'main-bridge':['tests/unit/runtime/test_managed_execution_bridge.py','tests/unit/runtime/test_iteration41_l2_fixture_package.py','tests/integration/test_iteration41_managed_cancellation_composition.py','tests/integration/test_iteration41_managed_execution_composition.py','tests/integration/test_iteration41_managed_replay_l2.py'],
 'main-cancel-control':['tests/test_cancellation_dispatch_resolution_control.py'],
 'main-artifact-set':['tests/unit/runtime/test_ctp_i9_candidate_artifact_set.py'],
 'parent-issuer-control':['tests/test_cancel_dispatch_resolution_proof.py','tests/test_cancel_dispatch_resolution_proof_store.py','tests/test_cancellation_dispatch_resolution_control.py']}
commands=[]
for suite,files in command_files.items():
 cwd=CAND/'main-overlay' if suite!='parent-issuer-control' else ROOT/'parent-installed-tests-v3b'
 junit=RUN/(suite+'-installed-wheel-v3-clean.xml')
 fixture=RUN/(suite+'-installed-wheel-v3-clean-fixtures')
 argv=[str(py),str(runner),'--import-mode=importlib','-q','--basetemp',str(fixture),'--junitxml='+str(junit),*files]
 commands.append({'powershell_command':f"& '{script_path}' {suite}",'cwd':str(cwd),'argv':argv,'env_contract':{'PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1','BT_API_TEST_SOURCE_ROOTS':str(ROOT/'source-roots-installed-wheel-v3.json'),'BT_API_TEST_GUARD_ROOT':r'D:\temp\iteration41-main-source-qa-20260926\origin-guard-r4','BT_API_TEST_METADATA_ROOT':str(ROOT/'dependency-source-only-metadata-v3'),'network':'origin guard loopback-only'}})

# Source maps, metadata, and immutable input manifest references.
source_map=ROOT/'source-roots-installed-wheel-v3.json'
metadata_root=ROOT/'dependency-source-only-metadata-v3'
external_manifests={
 'v23_execution':r'D:\temp\iteration41_v23_g1_owner_binding_freeze_20260927-r3\V23-SOURCE-MANIFEST.json',
 'v23_composite':r'D:\temp\iteration41_v23_g1_owner_binding_freeze_20260927-r3\COMPOSITE-SOURCE-MANIFEST.json',
 'parent_r4':r'D:\temp\iteration41-parent-r4-r3r3-composite-20260927-r1\provenance\r4-payload-manifest.json',
 'parent_r3r3':r'D:\temp\iteration41-parent-r4-r3r3-composite-20260927-r1\provenance\r3r3-original\snapshot-manifest.json',
 'parent_composite':r'D:\temp\iteration41-parent-r4-r3r3-composite-20260927-r1\qa\composite-source-manifest.json',
 'risk_cancel':r'D:\temp\iteration41_risk_cancel_resolution_20260927\risk-cancel-resolution-manifest.json',
}
input_hashes={}
for name,raw in external_manifests.items():
 p=pathlib.Path(raw); input_hashes[name]={'path':str(p),'sha256':sha_file(p) if p.exists() else None,'exists':p.exists()}
metadata_files=[{'path':str(p),'sha256':sha_file(p),'size_bytes':p.stat().st_size} for p in sorted(metadata_root.rglob('*')) if p.is_file()]
source_rootmap=load(source_map)
source_origin_constraints={
 'installed_wheels':['bt_api_py','bt_api_execution'],
 'source_only_actual_roots':['bt_api_base','bt_api_risk','bt_api_monitor','bt_api_ctp','bt_api_gateway','bt_api_transport_zmq','backtrader_agent','backtrader_skills','backtrader_mcp'],
 'ctp_source_root_was_on_test_path_but_no_bt_api_ctp_origin_was_loaded':True,
 'parent_execution_source_roots_are_installed_site_packages':True,
}

# Collision scan result and prior attempts.
collision=load(ROOT/'logs'/'version-collision-scan.json')
assert collision.get('exact_candidate_wheel_collisions')==[], 'chosen disposable wheel filename collision'
failed_builds=[
 {'name':'first build staging layout','exit':int((ROOT/'wheel-build-logs'/'build-a-execution.exit.txt').read_text().strip()),'stdout':str(ROOT/'wheel-build-logs'/'build-a-execution.stdout.log'),'stdout_sha256':sha_file(ROOT/'wheel-build-logs'/'build-a-execution.stdout.log'),'stderr':str(ROOT/'wheel-build-logs'/'build-a-execution.stderr.log'),'stderr_sha256':sha_file(ROOT/'wheel-build-logs'/'build-a-execution.stderr.log'),'diagnosis':'execution pyproject uses egg_base=src; initial staging lacked src/.'},
 {'name':'long wheel filename path attempt','exit':int((ROOT/'wheel-build-logs-v2'/'build-a-execution.exit.txt').read_text().strip()),'stdout':str(ROOT/'wheel-build-logs-v2'/'build-a-execution.stdout.log'),'stdout_sha256':sha_file(ROOT/'wheel-build-logs-v2'/'build-a-execution.stdout.log'),'stderr':str(ROOT/'wheel-build-logs-v2'/'build-a-execution.stderr.log'),'stderr_sha256':sha_file(ROOT/'wheel-build-logs-v2'/'build-a-execution.stderr.log'),'diagnosis':'long PEP 440 filename exceeded Windows temporary wheel path; final disposable tags shortened.'},
]

receipt={
 'schema':'iteration41-coordinated-release-probe-final-receipt-v2',
 'created_utc':datetime.now(timezone.utc).isoformat(),
 'candidate_root':str(CAND),
 'final_status':'offline disposable wheel coordination and fake-test evidence only; not a release, G1, G4, or G5 acceptance',
 'final_source_manifest':{'path':str(source_manifest),'sha256':manifest_sha,'file_count':len(load(source_manifest)['files']),'root_tree_summaries':load(source_manifest)['roots']},
 'evidence_generator':{'path':str(ROOT/'freeze_coordinated_probe_evidence.py'),'sha256':sha_file(ROOT/'freeze_coordinated_probe_evidence.py')},
 'source_diffs':{'path':str(ROOT/'coordinated-probe-source-diffs.json'),'sha256':sha_file(ROOT/'coordinated-probe-source-diffs.json'),'note':'13 main-overlay differences relative to its staging input are listed individually; this isolated candidate overlay does not alter the Backtrader working tree or default pins.'},
 'inputs':input_hashes,
 'source_map':{'path':str(source_map),'sha256':sha_file(source_map),'mapping':source_rootmap,'origin_constraints':source_origin_constraints},
 'source_only_metadata':{'path':str(metadata_root),'files':metadata_files,'manifest_sha256':sha_file(metadata_root/'SOURCE-ONLY-MANIFEST.json') if (metadata_root/'SOURCE-ONLY-MANIFEST.json').exists() else None,'meaning':'dependency metadata for source roots only; parent/execution metadata in installed-wheel test environment comes from installed wheel distributions'},
 'versions':{'bt_api_execution':'0.2.4.dev0+v23r3r3.f94b924e1e20','bt_api_py':'0.15.7.dev0+r4r3r3.67e54513','identity_status':'local disposable unique PEP 440 probe tags; no release tag or default pin allocated'},
 'version_collision_scan':{'path':str(ROOT/'logs'/'version-collision-scan.json'),'sha256':sha_file(ROOT/'logs'/'version-collision-scan.json'),'exact_collisions':collision['exact_candidate_wheel_collisions']},
 'wheel_build':{'run_manifest':str(ROOT/'wheel-build-runs-v4.json'),'run_manifest_sha256':sha_file(ROOT/'wheel-build-runs-v4.json'),'build_input_manifest_sha256':sha_file(input_path),'all_package_source_files_match_build_inputs':package_match,'dual_build_verification_sha256':sha_file(ROOT/'wheel-dual-build-verification.json'),'dual_build_verification':load(ROOT/'wheel-dual-build-verification.json'),'build_network_constraints':'pip wheel --no-deps --no-build-isolation --no-index; PIP_NO_INDEX=1; guarded loopback-only runtime; four build exit codes 0','preserved_failed_build_attempts':failed_builds},
 'installed_wheels':{'private_venv':str(ROOT/'venv-installed-wheel-v3-clean'),'python':'CPython 3.11.5 Anaconda Windows x64','install_log_sha256':sha_file(ROOT/'installed-wheel-v3-clean-install.log'),'record_verification_log_sha256':sha_file(ROOT/'installed-wheel-v3-clean-record-verification.log'),'record_verification_exit':int((ROOT/'installed-wheel-v3-clean-record-verification.exit.txt').read_text().strip()),'pip_check_log_sha256':sha_file(ROOT/'installed-wheel-v3-clean-source-metadata-pip-check.log'),'pip_check_exit':int((ROOT/'installed-wheel-v3-clean-source-metadata-pip-check.exit.txt').read_text().strip()),'pip_check_result':'No broken requirements found.','base_wheel_uninstalled_for_source-origin-proof':True,'no_system_site_packages':True},
 'tests':{'case_executions':sum(x['tests'] for x in suites),'unique_node_identities':unique_nodes,'repeated_node_executions':sum(n-1 for n in node_counts.values()),'passed':sum(x['tests']-x['failures']-x['errors']-x['skipped'] for x in suites),'failures':sum(x['failures'] for x in suites),'errors':sum(x['errors'] for x in suites),'skipped':sum(x['skipped'] for x in suites),'suites':suites,'duplicates':duplicate_nodes,'commands':commands,'prior_diagnostic_attempts':prev,'final_main_bridge_warning':'one existing Quandl DeprecationWarning; other final suites emitted no warnings'},
 'runtime_guards':{'final_clean_run_guard_files':guard_files,'event_counts':dict(sorted(guard_counts.items())),'prohibited_guard_events':guard_prohibited,'installed_origins':origins,'native_module_lines':native_lines,'native_modules_loaded_all_empty':all(x['modules']==[] for x in native_lines),'network_policy':'loopback-only guard; no network-blocked or provider attempts in final clean suites','ctp_source_root_mapped_but_unimported':True},
 'changed_file_audit':load(ROOT/'coordinated-probe-source-diffs.json')['roots'],
 'limitations':[
  'This is a unique-version feasibility/installed-wheel probe, not a product release or default pin change.',
  'Execution combines V23 process binding with R3r3 atomic cancellation evidence; the frozen source uses a fake attestor and does not prove OS-enforced G1/G5 isolation.',
  'Parent combines R4 cancellation control and the R3r3 fake proof issuer; this does not establish real provider or native CTP authority.',
  'No actual bt_api_ctp wheel was built or installed in this probe; the CTP candidate source root appeared in test PYTHONPATH/source map but no bt_api_ctp module origin was loaded.',
  'Absence of native imports is a guard result only and is not G4 acceptance.',
  'The test overlay uses a disposable artifact-set identifier and wheel hash; current main-repository default pins/production files were not edited in this probe.',
  'One final main bridge suite warning is the existing Quandl deprecation warning.',
 ],
}
receipt_path=OUT/'coordinated-probe-final-receipt.json'; dump(receipt_path,receipt)

# Human-readable pinned review, exact suite file lists are in receipt and runner.
review=f'''# Iteration 41 coordinated wheel probe — final receipt\n\n**Result:** both disposable wheels built twice byte-identically, passed installed RECORD/origin checks and clean `pip check`; the selected installed-wheel fake suites ran 143 cases (123 unique node IDs, 20 repeat executions), all passed, zero skips. This is not a release or G1/G4/G5 acceptance.\n\n## Exact inputs and identities\n\n- Final source manifest: `{source_manifest}` — SHA256 `{manifest_sha}` (843 files across parent source, execution project, main overlay and SOURCE-ONLY metadata).\n- Execution input: V23 manifest `f94b924e1e20fba6ccfe5bc028d88a0ad541022afb8e9c7a5f66a597687ab330`; distribution `{receipt['versions']['bt_api_execution']}`.\n- Parent input: base commit `76d5e0e60883263e0e79b67df321e7053ed46179`, R4 manifest `60b020202ed89169e24afca30b1b1b16680151a11c6f52c518d0f5bbfa7fab0d`, R3r3 issuer manifest `50b0d8b99afdacdaf2055246010e5766bbe630bc66d71c2aeeaca117baf3ce7a`; distribution `{receipt['versions']['bt_api_py']}`.\n- Dual-build source inputs: execution `{package_match['execution']['source_file_count']}/{package_match['execution']['build_input_file_count']}` files exact match; parent `{package_match['parent']['source_file_count']}/{package_match['parent']['build_input_file_count']}` exact match.\n- Wheel verifier: `{ROOT/'wheel-dual-build-verification.json'}` SHA256 `{sha_file(ROOT/'wheel-dual-build-verification.json')}`. Execution wheel SHA256 `b2a74d5ec4bce72db66ed5698709a8f986de02b54d72fb5e08a181c2983b6217`; parent wheel SHA256 `5e6e846d26b5038c0916fa15d3ce3f7a1c1334fd0aa160cd263d2d0397c07b0f`.\n- Private venv: `{ROOT/'venv-installed-wheel-v3-clean'}`; Python 3.11.5. Both wheels' installed origins are under that venv; installed RECORD payloads verified (Execution 17 members, parent 143 members). `pip check`: exit 0, “No broken requirements found.” `bt_api_base` remained SOURCE-ONLY metadata with an explicitly mapped source tree.\n\n## Installed-wheel fake suites\n\nRunner: `{script_path}` SHA256 `{sha_file(script_path)}`. It sets `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, explicit `BT_API_TEST_SOURCE_ROOTS`, fixture basetemp, guarded imports/network, then calls `pytest.main` with `--import-mode=importlib -q --basetemp ... --junitxml=...`. Exact per-suite argv and JUnit/log hashes are in the final JSON receipt.\n\n- Main bridge and L2: 73 passed, 0 skipped; 1 existing Quandl deprecation warning.\n- Main cancellation control: 20 passed.\n- Main artifact-set pin check: 6 passed.\n- Parent issuer/control: 44 passed.\n\nFour invocations total 143 test executions; 20 node IDs were repeated across main/parent cancellation-control packages, leaving 123 unique node IDs.\n\nFinal clean guard logs: {dict(sorted(guard_counts.items()))}. `NATIVE_MODULES_LOADED` was `[]` for each suite. No network-blocked, native-import-blocked, private-config-blocked, or origin-rejected event occurred in these final four suites. The candidate CTP source path was mapped but no `bt_api_ctp`, `_ctp`, or `ctp_wrap` module was loaded. Absence of native imports does not constitute G4 acceptance.\n\n## Preserved diagnostic failures\n\n- An earlier main bridge attempt had 67 pass, 5 fail, 1 skip; guard blocked a site-packages `bt_api_base` origin that shadowed its required source tree. A separate fixture L2 runner failed in that attempt. The clean isolated venv removed the installed base distribution, and the final installed-wheel run passed all 73 with the required mapped source origin.\n- The first copied parent suite failed collection (exit 2) because the copied test harness referenced missing root/fixture paths; the v3b installed-test copy corrected that setup, and final suite passed 44.\n- Two earlier wheel builds failed and are retained: one staging layout lacked required `src/`; a second used a PEP 440 tag whose wheel path exceeded Windows temporary-path limits. Final v4 builds used the required src layout and shorter unique disposable tags.\n\n## Limits\n\nThese are disposable local versions, not release tags: `{receipt['versions']['bt_api_execution']}` and `{receipt['versions']['bt_api_py']}`. Default production pins and tracked main source were not changed in this probe. The parent authority is fake-only; the Execution process-boundary implementation uses a fake attestor. There was no provider, credentials, native session, remote endpoint, or default CTP route. No G1/G4/G5 or release acceptance is implied.\n\nMachine-readable receipt: `{receipt_path}`\n'''
review_path=OUT/'coordinated-probe-final-review.md'; review_path.write_text(review,encoding='utf-8',newline='\n')

# Create a raw evidence ZIP. Exclude venvs/build trees/caches; include exact inputs, sources, logs, JUnit, wheels, guards and prior failures.
files={}
def add(p,alias=None):
 p=pathlib.Path(p)
 if p.exists() and p.is_file(): files[alias or p.relative_to(ROOT).as_posix()]=p
def addtree(p,alias):
 p=pathlib.Path(p)
 if p.exists():
  for f,r in walk(p): files[(pathlib.Path(alias)/r).as_posix()]=f
for n,p in [('parent-source',CAND/'parent-source'),('execution-project',CAND/'execution-project'),('main-overlay',CAND/'main-overlay'),('source-only-metadata',CAND/'source-only-metadata')]: addtree(p,'candidate-v3/'+n)
add(CAND/'VERSIONED-SOURCE-MANIFEST.json','candidate-v3/VERSIONED-SOURCE-MANIFEST.json'); add(CAND/'source-roots.json','candidate-v3/source-roots.json')
addtree(ROOT/'parent-installed-tests-v3b','parent-installed-tests-v3b')
addtree(ROOT/'dependency-source-only-metadata-v3','dependency-source-only-metadata-v3')
add(pathlib.Path(r'D:\temp\iteration41-main-source-qa-20260926\origin-guard-r4\sitecustomize.py'),'origin-guard-r4/sitecustomize.py')
# immutable upstream manifests
for key,p in input_hashes.items():
 if p['exists']: add(p['path'],'inputs/'+key+'.json')
# build and exact command/source maps
for raw,alias in [
 ('build-input-manifest-v4.json','build-input-manifest-v4.json'),('wheel-build-runs-v4.json','wheel-build-runs-v4.json'),('wheel-dual-build-verification.json','wheel-dual-build-verification.json'),('run_wheel_builds_v3.py','run_wheel_builds_v3.py'),('prepare_candidate_v3.py','prepare_candidate_v3.py'),('prepare_wheel_build_inputs_v4.py','prepare_wheel_build_inputs_v4.py'),('verify_dual_wheels_v2.py','verify_dual_wheels_v2.py'),('verify_installed_wheels_v3.py','verify_installed_wheels_v3.py'),('run_installed_suite_v3.ps1','run_installed_suite_v3.ps1'),('run_installed_wheel_pytest_v3.py','run_installed_wheel_pytest_v3.py'),('source-roots-installed-wheel-v3.json','source-roots-installed-wheel-v3.json'),('source-roots-v23.json','source-roots-v23.json'),('coordinated-probe-source-manifest-final.json','coordinated-probe-source-manifest-final.json'),('coordinated-probe-source-diffs.json','coordinated-probe-source-diffs.json'),('coordinated-probe-final-receipt.json','coordinated-probe-final-receipt.json'),('coordinated-probe-final-review.md','coordinated-probe-final-review.md'),('logs/version-collision-scan.json','logs/version-collision-scan.json'),('freeze_coordinated_probe_evidence.py','freeze_coordinated_probe_evidence.py')]: add(ROOT/raw,alias)
# final v4 wheels and build logs/guards
addtree(ROOT/'wheel-build-logs-v4','wheel-build-logs-v4')
# initial failed build logs, including exit markers
for d in ['wheel-build-logs','wheel-build-logs-v2']:
 for f in ['build-a-execution.exit.txt','build-a-execution.stderr.log','build-a-execution.stdout.log']:
  add(ROOT/d/f,d+'/'+f)
# installation and RECORD/pip proof
for f in ['installed-wheel-v3-clean-install.log','installed-wheel-v3-clean-install.exit.txt','installed-wheel-v3-clean-extra-deps.log','installed-wheel-v3-clean-extra-deps.exit.txt','installed-wheel-v3-clean-uninstall-base.log','installed-wheel-v3-clean-uninstall-base.exit.txt','installed-wheel-v3-clean-source-metadata-pip-check.log','installed-wheel-v3-clean-source-metadata-pip-check.exit.txt','installed-wheel-v3-clean-record-verification.log','installed-wheel-v3-clean-record-verification.exit.txt']:
 add(ROOT/f,f)
# final suites, JUnits, guard logs
for stem in final_prefixes:
 for ext in ['.xml','.log','.exit.txt']: add(RUN/(stem+ext),'installed-wheel-v3-clean-runs/'+stem+ext)
 addtree(RUN/(stem+'-guard'),'installed-wheel-v3-clean-runs/'+stem+'-guard')
# prior failing/non-final test runs and guard logs for accurate attribution
for d in ['installed-wheel-v3-clean-runs','installed-wheel-v3-runs']:
 base=ROOT/d
 for f in base.glob('*'):
  if f.is_file() and (f.suffix in {'.xml','.log','.txt'}): add(f,d+'/'+f.name)
 for guarddir in base.glob('*guard'):
  if guarddir.is_dir() and (guarddir.name.endswith('main-bridge-73-guard') or d=='installed-wheel-v3-runs'):
   addtree(guarddir,d+'/'+guarddir.name)
# unique wheel copies from both builds
for build in ['build-a','build-b']:
 for package in ['execution','parent']:
  addtree(ROOT/'wheel-build-logs-v4'/f'{build}-wheels'/package,f'wheel-build-logs-v4/{build}-wheels/{package}')

archive=OUT/'coordinated-probe-final-evidence-v2.zip'
idx=[]
for name,p in sorted(files.items()): idx.append({'path':name,'size_bytes':p.stat().st_size,'sha256':sha_file(p)})
index_obj={'schema':'iteration41-coordinated-probe-archive-index-v2','source_manifest_sha256':manifest_sha,'entry_count':len(idx),'files':idx}
index_bytes=(json.dumps(index_obj,indent=2,sort_keys=True,ensure_ascii=False)+'\n').encode('utf-8')
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
 for name,p in sorted(files.items()): z.write(p,name)
 z.writestr('ARCHIVE-INDEX.json',index_bytes)
with zipfile.ZipFile(archive) as z:
 bad=[]
 for e in idx:
  raw=z.read(e['path'])
  if len(raw)!=e['size_bytes'] or sha_bytes(raw)!=e['sha256']: bad.append(e['path'])
 if z.read('ARCHIVE-INDEX.json')!=index_bytes: bad.append('ARCHIVE-INDEX.json')
 if bad: raise SystemExit('zip integrity failed: '+str(bad))
archive_index_path=OUT/'coordinated-probe-archive-index-v2.json'; dump(archive_index_path,index_obj)
freeze={
 'schema':'iteration41-coordinated-probe-final-freeze-v2',
 'source_manifest_sha256':manifest_sha,'source_manifest_file_count':len(load(source_manifest)['files']),
 'receipt_sha256':sha_file(receipt_path),'review_sha256':sha_file(review_path),'diffs_sha256':sha_file(ROOT/'coordinated-probe-source-diffs.json'),
 'archive_path':str(archive),'archive_sha256':sha_file(archive),'archive_bytes':archive.stat().st_size,'archive_index_path':str(archive_index_path),'archive_index_sha256':sha_file(archive_index_path),'archive_indexed_files':len(idx),'archive_mismatches':bad,
 'build_inputs_exact_match':all(x['exact_match'] for x in package_match.values()),
 'test_invocations':sum(x['tests'] for x in suites),'unique_test_nodes':unique_nodes,'duplicate_executions':sum(n-1 for n in node_counts.values()),'all_selected_tests_passed':all(x['failures']==0 and x['errors']==0 and x['skipped']==0 and x['exit']==0 for x in suites),
 'final_clean_guard_events':dict(sorted(guard_counts.items())),'final_prohibited_guard_event_count':len(guard_prohibited),
}
dump(OUT/'coordinated-probe-freeze-summary-v2.json',freeze)
print(json.dumps(freeze,indent=2,sort_keys=True))
