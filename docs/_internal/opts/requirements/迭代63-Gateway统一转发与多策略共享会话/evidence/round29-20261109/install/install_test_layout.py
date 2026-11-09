from pathlib import Path
import json,os
T=Path('/tmp/iter63-r29-sdk-install-20261109-pht8FUZ4');link=T/'sdk-tests/bt_api_py';target=T/'install/src/bt_api_py'
if link.exists() or link.is_symlink():raise RuntimeError('refuse existing link')
link.symlink_to('../install/src/bt_api_py',target_is_directory=True)
if link.resolve()!=target.resolve() or not (target/'__init__.py').is_file():raise RuntimeError('wrong layout')
row={'link':str(link),'literal_target':os.readlink(link),'resolved_target':str(link.resolve()),'reason':'retired-entrypoint test resolves package relative to tests root; target is installed wheel'}
(T/'test-layout.json').write_text(json.dumps(row,indent=2)+'\n');print(json.dumps(row,sort_keys=True))
