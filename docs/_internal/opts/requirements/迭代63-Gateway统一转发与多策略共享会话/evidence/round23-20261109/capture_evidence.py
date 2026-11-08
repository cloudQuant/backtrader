from pathlib import Path
import gzip, hashlib, json, shutil
ROOT=Path('/Users/yunjinqi/Documents/new_projects/backtrader/docs/_internal/opts/requirements/迭代63-Gateway统一转发与多策略共享会话')
OUT=ROOT/'evidence/round23-20261109'
OUT.mkdir(parents=True,exist_ok=True)
rows=[]
def save(source, rel):
    source=Path(source)
    if not source.is_file() or source.is_symlink(): return
    data=source.read_bytes(); dest=OUT/rel
    if source.suffix in {'.log','.jsonl','.diff'}:
        dest=dest.with_name(dest.name+'.gz');stored=gzip.compress(data,mtime=0)
    else: stored=data
    dest.parent.mkdir(parents=True,exist_ok=True)
    if dest.exists() and dest.read_bytes()!=stored: raise RuntimeError(('archive changed',str(dest)))
    dest.write_bytes(stored)
    rows.append({'source':str(source),'archive':str(dest.relative_to(OUT)),'source_sha256':hashlib.sha256(data).hexdigest(),'archive_sha256':hashlib.sha256(stored).hexdigest(),'bytes':len(stored)})
for label, directory in (
 ('source-v1','/tmp/iter63-r23-primary'),
 ('source-v2','/tmp/iter63-r23-primary-v2'),
 ('installed-v1','/tmp/iter63-r23-install-20261109-s5p4b4ec'),
 ('installed-v2','/tmp/iter63-r23-install-v2-20261109-vGLghOFU'),
):
    base=Path(directory)
    for p in sorted(base.iterdir()):
        if p.is_file() and (p.suffix in {'.py','.json','.jsonl','.log','.txt','.md'} or p.name=='SOURCE_FROZEN'):
            save(p,Path(label)/p.name)
    for folder in ('bootstrap','plans','origin-logs'):
        root=base/folder
        if root.exists():
            for p in sorted(root.rglob('*')):
                if '__pycache__' not in p.parts and p.suffix in {'.py','.json','.jsonl','.txt'}:
                    save(p,Path(label)/p.relative_to(base))
for p in sorted(Path('/tmp').glob('iter63-r23*.log')):
    save(p,Path('development')/p.name)
for folder in ('iter63-r23-client','iter63-r23-assembly'):
    for p in sorted((Path('/tmp')/folder).glob('*.log')):
        save(p,Path('development')/folder/p.name)
(OUT/'capture-manifest.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('ARCHIVED_PUBLIC_ARTIFACTS',len(rows),'BYTES',sum(r['bytes'] for r in rows))
