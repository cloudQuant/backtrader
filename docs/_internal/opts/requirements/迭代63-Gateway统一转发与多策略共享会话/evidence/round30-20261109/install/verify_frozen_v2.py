from pathlib import Path
import hashlib,json
T=Path('/tmp/iter63-r30-install-20261109-ySExhdil');P=Path('/tmp/iter63-r30-primary');S=Path('/Users/yunjinqi/Documents/new_projects/bt_api_py');repos={'base':S/'bt_api/bt_api_base','gateway':S/'bt_api/bt_api_gateway','ctp':S/'bt_api/bt_api_ctp','sdk':S,'bt':S.parent/'backtrader'}
for kind,repo in repos.items():
 for suffix in ('frozen-inputs.json','owned-files.json'):
  a=T/f'{kind}-{suffix}';b=(Path('/tmp/iter63-r30-primary-bt-v2') if kind=='bt' else P)/f'{kind}-{suffix}'
  if a.read_bytes()!=b.read_bytes():raise RuntimeError(('primary manifest drift',kind,suffix))
 rows=json.loads((T/f'{kind}-frozen-inputs.json').read_text())
 for row in rows:
  if hashlib.sha256((repo/row['path']).read_bytes()).hexdigest()!=row['sha256']:raise RuntimeError(('frozen input drift',kind,row['path']))
 print('FROZEN_INPUTS_MATCH',kind,len(rows))
if (T/'selectors.json').read_bytes()!=(P/'selectors.json').read_bytes():raise RuntimeError('selectors drift')
print('SELECTORS_MATCH',hashlib.sha256((T/'selectors.json').read_bytes()).hexdigest())
