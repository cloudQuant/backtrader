import ast,json
from pathlib import Path
T=Path('/tmp/iter63-r30-install-20261109-ySExhdil');P=Path('/tmp/iter63-r30-primary/selectors-DRAFT.json');SDK=Path('/Users/yunjinqi/Documents/new_projects/bt_api_py');BT=SDK.parent/'backtrader';repos={'base':SDK/'bt_api/bt_api_base','gateway':SDK/'bt_api/bt_api_gateway','ctp':SDK/'bt_api/bt_api_ctp','sdk':SDK,'bt':BT}
plan=json.loads(P.read_text())
for kind,items in plan.items():
 missing=[s for s in items if not (repos[kind]/s.split('::',1)[0]).is_file()]
 print(kind,len(items),'MISSING',missing)
for p in list(T.glob('*.py'))+list((T/'bootstrap').glob('*.py')):ast.parse(p.read_text(),filename=str(p))
print('SCRIPT_AST_OK')
