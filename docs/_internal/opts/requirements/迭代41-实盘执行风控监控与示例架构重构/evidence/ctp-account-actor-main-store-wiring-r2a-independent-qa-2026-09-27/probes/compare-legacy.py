import pathlib,re,xml.etree.ElementTree as ET
qa=pathlib.Path(r'D:\temp\iteration41-ctp-account-actor-main-store-wiring-r2a-independent-qa-20260927')
review=pathlib.Path(r'D:\source_code\backtrader\docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\evidence\ctp-account-actor-main-store-wiring-r1-legacy-delta-audit-2026-09-27\r1-test-delta-migration-review.md')
xmlp=qa/'candidate/evidence/r2a-independent-legacy.junit.xml'; root=ET.parse(xmlp).getroot(); failed=[]
for tc in root.iter('testcase'):
 if tc.find('failure') is not None or tc.find('error') is not None: failed.append((tc.get('classname'),tc.get('name')))
rows={}
for line in review.read_text(encoding='utf-8').splitlines():
 m=re.match(r'\| `([^`]+)` \| `(FAIL_CLOSED_ASSERTION|EXTERNAL_ACTOR_MIGRATION)` \|',line)
 if m: rows[m.group(1)]=m.group(2)
results=[]; unmatched=[]
for cls,name in failed:
 disp=rows.get(name) or rows.get(name.split('[',1)[0])
 if disp is None: unmatched.append(name)
 else: results.append((f'{cls}::{name}',disp))
counts={k:sum(1 for _,v in results if v==k) for k in ('FAIL_CLOSED_ASSERTION','EXTERNAL_ACTOR_MIGRATION')}
print('candidate_failure_nodes',len(failed),'migration_rows',len(rows),'unmatched',unmatched,'counts',counts)
for n,d in results: print(d,n)
if len(failed)!=21 or len(rows)!=21 or unmatched or counts!={'FAIL_CLOSED_ASSERTION':8,'EXTERNAL_ACTOR_MIGRATION':13}: raise SystemExit(2)
(qa/'legacy-disposition-comparison.txt').write_text('\n'.join([f'candidate_failure_nodes={len(failed)} migration_rows={len(rows)} unmatched={len(unmatched)} counts={counts}']+[f'{d} {n}' for n,d in results])+'\n',encoding='utf-8')
