"""Validate primary-frozen public inputs before authorizing this isolated snapshot."""
from pathlib import Path
import hashlib,json,shutil,subprocess
T=Path('/tmp/iter63-r30-install-20261109-ySExhdil');P=Path('/tmp/iter63-r30-primary');SDK=Path('/Users/yunjinqi/Documents/new_projects/bt_api_py');repos={'base':SDK/'bt_api/bt_api_base','gateway':SDK/'bt_api/bt_api_gateway','ctp':SDK/'bt_api/bt_api_ctp','sdk':SDK,'bt':SDK.parent/'backtrader'}
if not (P/'SOURCE_FROZEN').is_file() or (T/'SOURCE_FROZEN').exists():raise RuntimeError('freeze state invalid')
selectors=json.loads((P/'selectors.json').read_text());expected={'base':5,'gateway':47,'ctp':6,'sdk':7,'bt':17};allow={'runtime':{},'tests':{}}
if {k:len(v) for k,v in selectors.items()}!=expected:raise RuntimeError('selector groups/count mismatch')
for name,repo in repos.items():
 frozen=json.loads((P/f'{name}-frozen-inputs.json').read_text());owned=json.loads((P/f'{name}-owned-files.json').read_text());mapping={r['path']:r['sha256'] for r in frozen}
 if len(mapping)!=len(frozen) or not set(owned).issubset(mapping):raise RuntimeError(('invalid frozen entries',name))
 for rel,sha in mapping.items():
  p=Path(rel)
  if p.is_absolute() or '..' in p.parts or any(x.startswith('.env') or x in ('config.yaml','account_config.yaml') for x in p.parts):raise RuntimeError(('private path',rel))
  src=repo/p
  if src.is_symlink() or not src.is_file() or hashlib.sha256(src.read_bytes()).hexdigest()!=sha:raise RuntimeError(('freeze SHA mismatch',name,rel))
 tracked=set(filter(None,subprocess.check_output(['git','-C',str(repo),'ls-files','-z','--',*owned]).decode().split('\0')));new=set(owned)-tracked
 allow['runtime'][name]=sorted(p for p in new if not p.startswith('tests/'))
 allow['tests'][name]=sorted(p for p in new if p.startswith('tests/'))
 for suffix in ('frozen-inputs.json','owned-files.json'):shutil.copyfile(P/f'{name}-{suffix}',T/f'{name}-{suffix}')
 print('INPUTS_OK',name,len(frozen),'OWNED',len(owned),'NEW_RUNTIME',allow['runtime'][name],'NEW_TESTS',allow['tests'][name],flush=True)
(T/'allowlists.json').write_text(json.dumps(allow,indent=2)+'\n');(T/'SOURCE_FROZEN').write_text('Validated R30 primary inputs and selectors before staging.\n')
