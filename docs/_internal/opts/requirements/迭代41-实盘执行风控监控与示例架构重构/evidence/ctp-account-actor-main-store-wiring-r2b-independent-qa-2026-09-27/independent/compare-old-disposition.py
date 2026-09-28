from pathlib import Path
import re
old=Path(r"D:\source_code\backtrader\docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\evidence\ctp-account-actor-main-store-wiring-r1-legacy-delta-audit-2026-09-27\r1-test-delta-migration-review.md").read_text(encoding='utf-8')
new=Path(r"D:\temp\iteration41-ctp-account-actor-main-store-wiring-r2b-independent-qa-20260927-v1\candidate\evidence\r2b-old-ctp-21-migration.md").read_text(encoding='utf-8')
def parse(s, index):
 out={}
 for line in s.splitlines():
  if not line.startswith('| `test_'): continue
  cells=[x.strip() for x in line.strip().strip('|').split('|')]
  out[cells[0].strip('`')]=cells[index].strip('` ')
 return out
a=parse(old,1);b=parse(new,2)
assert len(a)==21 and len(b)==21 and set(a)==set(b)
def old_category(v): return 'FAIL_CLOSED_ASSERTION' if 'FAIL_CLOSED_ASSERTION' in v else 'EXTERNAL_ACTOR_MIGRATION'
def new_category(v): return 'FAIL_CLOSED_ASSERTION' if v.startswith('current') else 'EXTERNAL_ACTOR_MIGRATION'
changes=[(n,old_category(a[n]),new_category(b[n]),a[n],b[n]) for n in sorted(a) if old_category(a[n])!=new_category(b[n])]
print(f'NODEID_SET_PRESERVED={len(a)} CATEGORY_CHANGES={len(changes)}')
print('OLD_COUNTS', {key:sum(old_category(v)==key for v in a.values()) for key in ('FAIL_CLOSED_ASSERTION','EXTERNAL_ACTOR_MIGRATION')})
print('R2B_COUNTS', {key:sum(new_category(v)==key for v in b.values()) for key in ('FAIL_CLOSED_ASSERTION','EXTERNAL_ACTOR_MIGRATION')})
for row in changes: print('CATEGORY_CHANGE',*row,sep=' | ')