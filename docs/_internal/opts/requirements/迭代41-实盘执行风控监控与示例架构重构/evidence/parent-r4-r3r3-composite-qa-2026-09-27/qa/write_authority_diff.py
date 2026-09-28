from pathlib import Path
import difflib
root=Path(r'D:\temp\iteration41-parent-r4-r3r3-composite-20260927-r1')
old=root/'provenance'/'r3r3-original'/'fake_dispatch_authority.py'
new=root/'parent-source'/'bt_api_py'/'runtime_plugins'/'fake_dispatch_authority.py'
diff=''.join(difflib.unified_diff(old.read_text(encoding='utf-8').splitlines(keepends=True),new.read_text(encoding='utf-8').splitlines(keepends=True),fromfile='R3r3/src/fake_dispatch_authority.py',tofile='R4-composite/bt_api_py/runtime_plugins/fake_dispatch_authority.py'))
p=root/'provenance'/'r3r3-authority-to-r4-stricter-source.diff'
p.write_text(diff,encoding='utf-8',newline='\n')
print('diff_bytes',len(diff.encode('utf-8')),'diff_lines',diff.count('\n'))
