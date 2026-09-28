import hashlib, json
from pathlib import Path
candidate=Path(r'D:\temp\iteration41-g5-order-authority-20260927-candidate')
main=Path(r'D:\source_code\backtrader')
manifest=json.loads((candidate/'frozen-input-manifest.json').read_text(encoding='utf-8'))
rows=[]
for item in manifest:
    rel=Path(item['path'])
    if rel.parts and rel.parts[0]=='inputs' and len(rel.parts)>1 and rel.parts[1]=='backtrader':
        source=candidate/rel; repo=main/Path(*rel.parts[2:])
        a=hashlib.sha256(source.read_bytes()).hexdigest().upper(); b=hashlib.sha256(repo.read_bytes()).hexdigest().upper() if repo.is_file() else None
        rows.append({'manifest_path':item['path'],'main_path':str(repo),'candidate_sha256':a,'main_sha256':b,'matches':a==b})
print(json.dumps({'main_frozen_inputs_checked':len(rows),'all_match':all(x['matches'] for x in rows),'files':rows},indent=2))
