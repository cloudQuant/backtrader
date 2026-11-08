"""Point SDK test-derived paths only at verified target; document -I child gap."""
import ast
import hashlib
import json
import os
from pathlib import Path

T=Path('/tmp/iter63-r20-install-20261109-v3-0mIL2v0a')
if not (T/'SOURCE_FROZEN').is_file(): raise SystemExit('SOURCE_FREEZE required')
root=T/'sdk-tests'; target=(T/'install/src').resolve()
if not root.is_dir() or not target.is_dir(): raise RuntimeError('snapshot/install missing')
manifest=T/'sdk-layout-manifest.json'
if manifest.exists(): raise RuntimeError('layout already exists')
links=[(root/'bt_api_py',target/'bt_api_py'), (root/'bt_api/bt_api_base/src',target)]
rows=[]
for link,dest in links:
    if link.exists() or link.is_symlink() or not dest.is_dir() or not dest.resolve().is_relative_to(target): raise RuntimeError(('invalid layout',str(link)))
    link.parent.mkdir(parents=True,exist_ok=True)
    os.symlink(dest,link,target_is_directory=True)
    rows.append({'link':str(link),'target':str(dest.resolve())})
manifest.write_text(json.dumps({'links':rows},indent=2)+'\n')
test=root/'tests/unit/test_service_market_monitor_import_isolation.py'
source=test.read_text(encoding='utf-8');tree=ast.parse(source)
assignment=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='_ISOLATED_IMPORT' for t in n.targets))
script=ast.literal_eval(assignment.value)
func=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='test_service_market_monitor_import_isolated_from_domain_packages')
segment=ast.get_source_segment(source,func)
if not isinstance(script,str) or '"-I"' not in segment or 'sys.executable' not in segment or 'check=False' not in segment or 'completed.returncode == 0' not in segment:
    raise RuntimeError('SDK_MINUS_I_STATIC_PROBE_CHANGED')
(root.parent/'sdk-minus-i-audit-gap.md').write_text(
    'GAP: test_service_market_monitor_import_isolated_from_domain_packages starts a Python -I -c child. '
    '-I ignores PYTHONPATH, so test bootstrap sitecustomize/origin/offline guards are not injected. '
    'The original test derives sdk_root from the copied test and explicitly inserts that path and its base src. '
    'Both paths are symlinks to the verified install target, as recorded in sdk-layout-manifest.json. '
    'A passing original assertion establishes the child exit code was 0 and its script-reported module path '
    'matched the installed layout; it does not establish independent child guard coverage.\n'
    'isolated_script_sha256='+hashlib.sha256(script.encode()).hexdigest()+'\n'
    'copied_test_sha256='+hashlib.sha256(test.read_bytes()).hexdigest()+'\n'
    'Source script is retained verbatim in the copied public test file for review.\n')
print('SDK_SRC_LINKS_RESOLVE_TO_INSTALLED_TARGET',len(rows),flush=True)
print('GAP_SDK_MINUS_I_CHILD_GUARD_UNAVAILABLE',flush=True)
