"""Bridge Base test src layout to verified isolated installed target, never source."""
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil

T=Path('/tmp/iter63-r18-install-20261109-GvDCI8TF')
if not (T/'SOURCE_FROZEN').is_file():
    raise SystemExit('SOURCE_FREEZE required')
root=T/'base-tests'
target=(T/'install/src').resolve()
if not root.is_dir() or not target.is_dir():
    raise RuntimeError('snapshot or installation missing')
link=root/'src'
manifest=T/'base-layout-manifest.json'
if link.exists() or link.is_symlink() or manifest.exists():
    raise RuntimeError('refusing existing base test layout')
os.symlink(target,link,target_is_directory=True)
rows=[]
for source,dest in [(T/'source/base/pyproject.toml',root/'pyproject.toml'),
                    *[(T/'bootstrap'/name,target/name) for name in ('sitecustomize.py','origin_guard.py','offline_guard.py')]]:
    if not source.is_file() or dest.exists():
        raise RuntimeError(('missing source or existing support file',str(source),str(dest)))
    shutil.copyfile(source,dest)
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    if hashlib.sha256(dest.read_bytes()).hexdigest()!=digest:
        raise RuntimeError('layout byte mismatch')
    rows.append({'source':str(source),'copy':str(dest),'sha256':digest})
manifest.write_text(json.dumps({'src_link':str(link),'resolved_target':str(target),'files':rows},indent=2)+'\n')
test_path = root/'tests/test_service_protocol.py'
tree = ast.parse(test_path.read_text(encoding='utf-8'))
func = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
            and node.name == 'test_transport_protocols_are_structural_and_service_protocol_import_is_stdlib_only')
assignment = next(node for node in ast.walk(func) if isinstance(node, ast.Assign)
                  and any(isinstance(target, ast.Name) and target.id == 'script' for target in node.targets))
script = ast.literal_eval(assignment.value)
expected = ("import sys; import bt_api_base.service_protocol; "
            "assert not {'zmq', 'pydantic', 'numpy'} & set(sys.modules)")
if script != expected or '"-S"' not in ast.get_source_segment(test_path.read_text(), func):
    raise RuntimeError('BASE_MINUS_S_STATIC_PROBE_CHANGED')
(T/'base-minus-s-audit-gap.md').write_text(
    'GAP: test_transport_protocols_are_structural_and_service_protocol_import_is_stdlib_only '
    'uses sys.executable -S -c; -S suppresses sitecustomize so child origin/offline audit '
    'is unavailable. Static exact script: '+repr(script)+'\n'
    'script_sha256='+hashlib.sha256(script.encode('utf-8')).hexdigest()+'\n'
    'The test uses subprocess.run(check=True): a passing test establishes child exit code 0, '
    'not a child-origin audit. The exact script contains no native factory or network call.\n')
print('BASE_SRC_LINK_RESOLVES_TO_INSTALL',link.resolve(),flush=True)
print('BASE_LAYOUT_COPIES_SHA_MATCH',len(rows),flush=True)
