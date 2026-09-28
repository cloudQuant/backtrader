from __future__ import annotations
import ast,re,xml.etree.ElementTree as ET
from pathlib import Path
root=Path(r"D:\temp\iteration41-ctp-account-actor-main-store-wiring-r2b-independent-qa-20260927-v1\candidate")
old=ET.parse(root/'evidence/r2a-legacy-ctp-compatibility-delta.junit.xml').getroot()
old_fail={c.attrib['name'] for s in old.iter('testsuite') for c in s.findall('testcase') if c.find('failure') is not None and c.attrib.get('classname','').endswith('test_managed_ctp_store_adapter')}
md=(root/'evidence/r2b-old-ctp-21-migration.md').read_text(encoding='utf-8')
rows=[]
for line in md.splitlines():
 if line.startswith('| `test_'):
  m=re.match(r'^\| `([^`]+)` \| ([^|]+) \| ([^|]+) \| ([^|]+) \|$',line)
  if not m: raise AssertionError(line)
  rows.append((m.group(1),m.group(2).strip(),m.group(3).strip(),m.group(4).strip()))
assert len(old_fail)==21,len(old_fail)
row_names={x[0] for x in rows}
old_missing=sorted(old_fail-row_names); row_extra=sorted(row_names-old_fail)
assert not old_missing and not row_extra,(old_missing,row_extra)
source=root/'tests/unit/stores/test_managed_ctp_store_adapter.py'
tree=ast.parse(source.read_text(encoding='utf-8'))
constants=None
for node in tree.body:
 if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='_LEGACY_CTP_STORE_CASES' for t in node.targets):
  constants=ast.literal_eval(node.value)
assert constants is not None and len(constants)==21
const_names={x[0] for x in constants}
assert const_names==row_names,(len(const_names),len(row_names),sorted(const_names^row_names))
cur=ET.parse(Path(r"D:\temp\iteration41-ctp-account-actor-main-store-wiring-r2b-independent-qa-20260927-v1\run-artifacts\junit\candidate-focus.xml")).getroot()
cur_names={c.attrib['name'] for s in cur.iter('testsuite') for c in s.findall('testcase')}
expected={f"test_legacy_ctp_store_composition_is_now_explicitly_fail_closed[{name}]" for name in row_names}
missing=sorted(expected-cur_names)
assert not missing,missing
assert all(description and disposition and future for _,description,disposition,future in rows)
counts={}
for _,_,disp,_ in rows:
 key='current fail-closed assertion' if disp.startswith('current') else 'future external Actor'
 counts[key]=counts.get(key,0)+1
print('LEGACY_MIGRATION_MAP_OK')
print(f'old_r2a_candidate_failures={len(old_fail)} migration_rows={len(rows)} current_parameterized_cases={len(expected)} missing={len(missing)}')
print(f'disposition_counts={counts}')
print(f'old_failure_names={sorted(old_fail)}')