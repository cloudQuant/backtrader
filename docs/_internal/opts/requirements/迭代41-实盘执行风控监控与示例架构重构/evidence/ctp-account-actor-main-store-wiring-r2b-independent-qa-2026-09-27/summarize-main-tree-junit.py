import collections, hashlib, json, xml.etree.ElementTree as ET
from pathlib import Path
base=Path(r'D:\source_code\backtrader\docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\evidence\ctp-account-actor-main-store-wiring-r2b-independent-qa-2026-09-27')
main=Path(r'D:\source_code\backtrader\docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\evidence\ctp-account-actor-r2b-main-integration-2026-09-27')
patched=ET.parse(main/'patched-main-junit.xml').getroot()
reverted=ET.parse(main/'reverted-main-junit.xml').getroot()
def cases(root):
 out={}
 for tc in root.iter('testcase'):
  node=f"{tc.get('classname','')}::{tc.get('name','')}"
  f=tc.find('failure'); e=tc.find('error'); sk=tc.find('skipped')
  issue=f if f is not None else e
  status='failed' if issue is not None else ('skipped' if sk is not None else 'passed')
  out[node]={'status':status,'message':issue.get('message','') if issue is not None else '', 'text':(issue.text or '').strip() if issue is not None else ''}
 return out
pc=cases(patched); rc=cases(reverted)
failed=[(node,item) for node,item in pc.items() if item['status']=='failed']
byfile=collections.defaultdict(list)
for node,item in failed:
 file=node.split('::',1)[0]
 byfile[file].append({'nodeid':node,'message':item['message'],'error_text':item['text']})
classifications={
 'tests.unit.stores.test_btapistore_iteration22':{
   'label':'CTP fail-close preempts existing CTP offline/read/query/arm/recovery contracts',
   'detail':'All failures start at Store construction with external account actor unavailable. This is the candidate’s intentional no-Actor denial, but it blocks existing simulation/read-only/recovery tests; the suite cannot be accepted as passing.'},
 'tests.unit.stores.test_ctp_managed_projection_bridge':{
   'label':'CTP candidate/fake managed projection path unavailable without Actor',
   'detail':'First failure is external account actor unavailable. The new CTP projection tests are prevented from reaching local fake projection/receipt behavior.'},
 'tests.unit.stores.test_btapistore':{
   'label':'Mixed: 8 CTP/env fail-closed; 6 non-CTP compatibility failures',
   'detail':'First CTP session test fails with external account actor unavailable. Three generic Store factory tests (`btapi`/`outer`) fail with store route ambiguous despite no CTP route; three placeholder-provider tests (`futu`/`oanda`/`vc`) now raise store provider unsupported instead of their prior explicit unimplemented-provider contract.'},
 'tests.unit.stores.test_btapistore_normalized':{
   'label':'Mixed: 8 CTP/configured-CTP fail-closed; 2 generic btapi regressions',
   'detail':'First test constructs BtApiStore(provider=btapi) with no CTP exchange configuration and fails with store route ambiguous; public stop-callback has the same generic-route issue. Eight remaining failed tests explicitly use CTP or a CTP SDK route and are preempted by external account actor unavailable.'},
 'tests.unit.stores.test_btapistore_execution_evidence':{
   'label':'CTP evidence reader is preempted by constructor fail-close',
   'detail':'First failure is external account actor unavailable before managed-arm evidence can be inspected.'},
 'tests.unit.stores.test_btapistore_entry_approval_arm':{
   'label':'CTP approval/budget-capability cases are preempted by constructor fail-close',
   'detail':'First failure is external account actor unavailable while creating the test’s authorized CTP Store.'},
 'tests.unit.stores.test_credential_safety':{
   'label':'CTP credential repr checks no longer construct a Store',
   'detail':'First failure is external account actor unavailable before repr/str masking can be exercised. No credential leak is observed, but this security regression test is not satisfied or replaced by a new refusal-specific assertion.'},
 'tests.unit.runtime.test_iteration41_sa_ctp_replay_runtime':{
   'label':'Supported no-write 013_3 simulation/replay fixture is blocked',
   'detail':'First/only failure is external account actor unavailable. The test explicitly forbids network and provider writes; route rejection prevents the existing offline simulation/sandbox run from reaching its replay assertion.'}
}
summary=[]
for file,items in sorted(byfile.items(),key=lambda x:-len(x[1])):
 summary.append({'file':file,'failure_count':len(items),'first_failure':items[0],**classifications.get(file,{'label':'unclassified','detail':'See exact failure message and full JUnit.'}),'failed_nodes':items})
patched_ids=set(pc); reverted_ids=set(rc); additions=patched_ids-reverted_ids; removals=reverted_ids-patched_ids
new_fail=[n for n in additions if pc[n]['status']=='failed']
all_fail_existing=all(n in reverted_ids for n,_ in failed)
result={
 'status':'NOT_READY_FOR_MAIN_MERGE',
 'patched_junit':{'cases':len(pc),'failed':sum(x['status']=='failed' for x in pc.values()),'passed':sum(x['status']=='passed' for x in pc.values()),'skipped_or_xfailed':sum(x['status']=='skipped' for x in pc.values())},
 'reverted_junit':{'cases':len(rc),'failed':sum(x['status']=='failed' for x in rc.values()),'passed':sum(x['status']=='passed' for x in rc.values()),'skipped_or_xfailed':sum(x['status']=='skipped' for x in rc.values())},
 'node_identity_comparison':{'patched_unique_nodeids':len(patched_ids),'reverted_unique_nodeids':len(reverted_ids),'added':len(additions),'removed':len(removals),'new_nodes_failed':len(new_fail),'all_258_failures_are_existing_nodes':all_fail_existing},
 'failure_groups':summary,
 'warning':'pytest-config warning: asyncio_default_fixture_loop_scope is unknown in the selected interpreter environment.',
 'invocation':"python -m pytest -p no:asyncio tests/unit/stores tests/unit/runtime -q --tb=no --junitxml='D:\\temp\\iteration41-r2b-main-unit-store-runtime.xml' *> 'D:\\temp\\iteration41-r2b-main-unit-store-runtime.txt' (PowerShell, D:\\source_code\\backtrader).",
 'raw_evidence':{
   'patched_junit':'../ctp-account-actor-r2b-main-integration-2026-09-27/patched-main-junit.xml',
   'patched_junit_sha256':'6500223FE55136907A178996E3F0D5BE6DA71DD758B501BFEB9E232949B0EFFE',
   'patched_output':'../ctp-account-actor-r2b-main-integration-2026-09-27/patched-main-pytest.txt',
   'patched_output_sha256':'08871BE79BE93FC5E77509070EB9E64CAA28A62650DF4591D0B5C355B02B8761',
   'reverted_junit':'../ctp-account-actor-r2b-main-integration-2026-09-27/reverted-main-junit.xml',
   'reverted_junit_sha256':'35D8D144E8788BA0314CAA4601077209F5F7EB55FB15CD0C49F3DE33595076FF',
   'reverted_output':'../ctp-account-actor-r2b-main-integration-2026-09-27/reverted-main-pytest.txt',
   'reverted_output_sha256':'FBEF36C0AA126DAE38D13BAB7CF0B67301FDB235E8374A044D93DBEBA15BBADE',
   'main_tree_store_after_revert_sha256':'DBA2989252DB76FE010FBEE7CAACCDDBA34A9B951E3702724156482B67FAE826'
 }
}
if result['patched_junit']['cases'] != 2706 or result['patched_junit']['failed'] != 258: raise SystemExit(result['patched_junit'])
if result['reverted_junit']['cases'] != 2681 or result['reverted_junit']['failed'] != 0: raise SystemExit(result['reverted_junit'])
if not all_fail_existing or len(additions)!=46 or len(removals)!=21 or new_fail: raise SystemExit(result['node_identity_comparison'])
(base/'main-tree-failure-groups.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
print(json.dumps({k:result[k] for k in ('patched_junit','reverted_junit','node_identity_comparison')},indent=2))
for g in summary:
 print(g['file'],g['failure_count'],g['first_failure']['nodeid'],g['first_failure']['message'])

