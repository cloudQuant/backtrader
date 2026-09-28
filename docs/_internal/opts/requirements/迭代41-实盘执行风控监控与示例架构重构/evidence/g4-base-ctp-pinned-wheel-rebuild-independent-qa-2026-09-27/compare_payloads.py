import hashlib, json, zipfile, pathlib, difflib, struct
root=pathlib.Path(r'D:\temp\iteration41-g4-base-ctp-pinned-wheel-rebuild-20260927')
paths={
 'base_a':root/'build-a/wheelhouse/bt_api_base-0.15.5-py3-none-any.whl',
 'base_b':root/'build-b/wheelhouse/bt_api_base-0.15.5-py3-none-any.whl',
 'base_pin':pathlib.Path(r'D:\c41sdkf_audit\wheels\bt_api_base-0.15.5-py3-none-any.whl'),
 'ctp_a':root/'build-a/wheelhouse/bt_api_ctp-2.0.3+iteration41.i2-cp311-cp311-win_amd64.whl',
 'ctp_b':root/'build-b/wheelhouse/bt_api_ctp-2.0.3+iteration41.i2-cp311-cp311-win_amd64.whl',
 'ctp_pin':pathlib.Path(r'D:\c41sdki2_audit\wheels\bt_api_ctp-2.0.3+iteration41.i2-cp311-cp311-win_amd64.whl'),
}
print('wheel_exists', {k:v.exists() for k,v in paths.items()})
for k,p in paths.items():
 if p.exists():
  data=p.read_bytes(); print('wheel',k,len(data),hashlib.sha256(data).hexdigest())
# target py members compare git-source build A vs pin
for member in ['bt_api_ctp/__init__.py','bt_api_ctp/ctp/client.py']:
 print('\nMEMBER',member)
 vals={}
 for k in ('ctp_a','ctp_b','ctp_pin'):
  with zipfile.ZipFile(paths[k]) as z: vals[k]=z.read(member)
  print(k,len(vals[k]),hashlib.sha256(vals[k]).hexdigest(), 'crlf',vals[k].count(b'\r\n'),'lf',vals[k].count(b'\n'))
 if vals['ctp_a']!=vals['ctp_pin']:
  aa=vals['ctp_a'].decode('utf-8','replace').splitlines()
  bb=vals['ctp_pin'].decode('utf-8','replace').splitlines()
  print('line_counts',len(aa),len(bb))
  for line in list(difflib.unified_diff(aa,bb,fromfile='build-source',tofile='pinned-wheel',n=2))[:100]: print(line)
# pyd binary compare: hashes and first mismatch offsets; PE COFF timestamp if MZ/PE
member='bt_api_ctp/ctp/_ctp.cp311-win_amd64.pyd'
bins={}
for k in ('ctp_a','ctp_b','ctp_pin'):
 with zipfile.ZipFile(paths[k]) as z: bins[k]=z.read(member)
 print('pyd',k,len(bins[k]),hashlib.sha256(bins[k]).hexdigest())
for k in ('ctp_a','ctp_b'):
 a,b=bins[k],bins['ctp_pin']; diffs=[i for i,(x,y) in enumerate(zip(a,b)) if x!=y]
 print('pyd_diff',k,'bytes',len(diffs),'first',diffs[:10])
 if len(a)>=0x40 and a[:2]==b'MZ':
  pe=struct.unpack_from('<I',a,0x3c)[0]; q=struct.unpack_from('<I',b,0x3c)[0]
  print('pe_offsets',hex(pe),hex(q),'signatures',a[pe:pe+4],b[q:q+4])
  if a[pe:pe+4]==b'PE\0\0' and b[q:q+4]==b'PE\0\0': print('coff_timestamp',hex(struct.unpack_from('<I',a,pe+8)[0]),hex(struct.unpack_from('<I',b,q+8)[0]))

