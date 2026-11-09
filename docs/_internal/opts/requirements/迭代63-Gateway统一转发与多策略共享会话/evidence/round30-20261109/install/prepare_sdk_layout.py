"""Bind SDK test-derived paths to the verified wheel target, never source."""
from pathlib import Path
import json,os
T=Path('/tmp/iter63-r30-install-20261109-ySExhdil');root=T/'sdk-tests';target=(T/'install/src').resolve();manifest=T/'sdk-layout-manifest.json'
if not (T/'SOURCE_FROZEN').is_file() or not root.is_dir() or not target.is_dir() or manifest.exists():raise RuntimeError('freeze/root/target/layout invalid')
rows=[]
for link,dest in ((root/'bt_api_py',target/'bt_api_py'),(root/'bt_api/bt_api_base/src',target)):
 if link.exists() or link.is_symlink() or not dest.is_dir() or not dest.resolve().is_relative_to(target):raise RuntimeError(('invalid layout',str(link)))
 link.parent.mkdir(parents=True,exist_ok=True);os.symlink(dest,link,target_is_directory=True);rows.append({'link':str(link),'target':str(dest.resolve())})
manifest.write_text(json.dumps({'links':rows},indent=2)+'\n');print('SDK_LAYOUT_LINKS_TO_TARGET',len(rows),flush=True)
