"""Stage primary-frozen R28 inputs only after explicit parent release."""
from pathlib import Path
import hashlib,json,shutil,sys
T=Path('/tmp/iter63-r28-candidate3-20261109-ijqQ26LC')
PRIMARY=Path('/tmp/iter63-r28-primary-v3')
sha=lambda data:hashlib.sha256(data).hexdigest()
if sys.argv[1:]!=['--source-frozen-by-primary']:
 raise SystemExit('DO NOT RUN BEFORE explicit parent SOURCE_FROZEN; require --source-frozen-by-primary')
if (T/'SOURCE_FROZEN').exists() or (T/'source').exists() or (T/'wheels').exists():
 raise RuntimeError('release already staged or nonempty source; retain evidence')
primary_files=('selectors.json','bt-owned-files.json','bt-frozen-inputs.json')
raw={name:(PRIMARY/name).read_bytes() for name in primary_files}
selectors=json.loads(raw['selectors.json']); owned=json.loads(raw['bt-owned-files.json']); frozen=json.loads(raw['bt-frozen-inputs.json'])
assert list(selectors)==['bt'] and len(selectors['bt'])==58 and len(set(selectors['bt']))==58
assert isinstance(owned,list) and len(owned)==len(set(owned))
rows={row['relative_path']:row for row in frozen}; assert len(rows)==len(frozen)
assert set(owned).issubset(rows) and set(selectors['bt']).issubset(rows)
for rel,row in rows.items():
 if '..' in Path(rel).parts or Path(rel).is_absolute():raise RuntimeError(('invalid primary path',rel))
 p=Path(row['path'])
 if not p.is_file() or p.is_symlink() or sha(p.read_bytes())!=row['sha256']:raise RuntimeError(('primary freeze mismatch',rel))
for item in selectors['bt']:
 if not item.startswith('tests/') or not item.endswith('.py'):raise RuntimeError(('invalid selector',item))
(new_sel:=T/'selectors.json').write_bytes(raw['selectors.json'])
(T/'primary-owned-files.json').write_bytes(raw['bt-owned-files.json'])
(T/'primary-frozen-inputs.json').write_bytes(raw['bt-frozen-inputs.json'])
(T/'plans').mkdir(); (T/'plans/bt.txt').write_text('\n'.join(selectors['bt'])+'\n')
(T/'allowlists.json').write_text(json.dumps({'runtime':{'bt':[p for p in owned if p.startswith('backtrader/') and p.endswith('.py')]},'tests':{'bt':[p for p in owned if p.startswith('tests/') and p.endswith('.py')]}},indent=2)+'\n')
fixed=json.loads(Path('/tmp/iter63-r26-sdk-install-20261109-xAIrOrDl/fixed-wheels.json').read_text());fixed=[r for r in fixed if not r['filename'].startswith('back_trader_python-')]
fixed.append({'source':'/tmp/iter63-r26-sdk-install-20261109-xAIrOrDl/wheels/bt_api_py-0.16.0.dev63-py3-none-any.whl','filename':'bt_api_py-0.16.0.dev63-py3-none-any.whl','sha256':'f53cc1428ccc77d9143a615c36e52439326cd2170d70b5b491fc0ab7f8d132fe'})
expected={'bt_api_base-':'67f2e489053c06cc154c8edb1f05015aa9ec8be77e9e723e270e9a726072671f','bt_api_gateway-':'52a4ac9f1b3c671eada2b3314f7a1766afccef78051109d02070e7b820abe685','bt_api_ctp-':'bf25c4c171ffbcf5e4cca872ce8f9d4d5454210f311ba28de2bb9947defbbc6a','bt_api_py-':'f53cc1428ccc77d9143a615c36e52439326cd2170d70b5b491fc0ab7f8d132fe','bt_api_okx-':'2243f8427d282e53f08b50e88832b149dfde0729afcbd8b3e768eb7a81ce1c07','bt_api_binance-':'703f312d1889052293b49c390855f2df50d38084ced8a80029f4794ca6e1c5be','msgpack-':'a4b47ec7422bef149223786a87df80067ac65bfc7c0565e5cf1dfbdc40acee50'}
assert len(fixed)==len(expected)
for prefix,digest in expected.items():
 matches=[r for r in fixed if r['filename'].startswith(prefix)]; assert len(matches)==1 and matches[0]['sha256']==digest
for row in fixed:
 p=Path(row['source']); assert sha(p.read_bytes())==row['sha256'],p
(T/'wheels').mkdir()
for row in fixed:shutil.copyfile(row['source'],T/'wheels'/row['filename'])
(T/'fixed-wheels.json').write_text(json.dumps(fixed,indent=2)+'\n')
(T/'SOURCE_FROZEN').write_text(json.dumps({'release':'explicit parent SOURCE_FROZEN','primary_files_sha256':{k:sha(v) for k,v in raw.items()}},indent=2)+'\n')
print('RELEASE_STAGED',len(selectors['bt']),'selectors',len(frozen),'frozen inputs',len(fixed),'wheels',flush=True)
