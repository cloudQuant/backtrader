import pathlib,zipfile,struct,hashlib,json,shutil
root=pathlib.Path(r'D:\temp\iteration41-g4-base-ctp-pinned-wheel-rebuild-20260927')
base_a=root/'build-a/wheelhouse/bt_api_base-0.15.5-py3-none-any.whl'; pin=pathlib.Path(r'D:\c41sdkf_audit\wheels\bt_api_base-0.15.5-py3-none-any.whl')
out=root/'base-a-retimestamped-to-pinned-copy.whl'
src=bytearray(base_a.read_bytes())
with zipfile.ZipFile(base_a) as za, zipfile.ZipFile(pin) as zp:
 a={i.filename:i for i in za.infolist()}; p={i.filename:i for i in zp.infolist()}
 assert list(a)==list(p), 'member order mismatch'
 for n,ia in a.items():
  ip=p[n]
  assert za.read(n)==zp.read(n), f'payload differs: {n}'
  assert (ia.compress_type,ia.CRC,ia.file_size,ia.compress_size,ia.flag_bits,ia.external_attr,ia.create_system)==(ip.compress_type,ip.CRC,ip.file_size,ip.compress_size,ip.flag_bits,ip.external_attr,ip.create_system), f'non-time metadata differs: {n}'
  tm=ia.date_time; hh=((tm[3]<<11)|(tm[4]<<5)|(tm[5]//2)); dd=(((tm[0]-1980)<<9)|(tm[1]<<5)|tm[2])
  o=ia.header_offset
  assert src[o:o+4]==b'PK\x03\x04'
  struct.pack_into('<HH',src,o+10,((ip.date_time[3]<<11)|(ip.date_time[4]<<5)|(ip.date_time[5]//2)),(((ip.date_time[0]-1980)<<9)|(ip.date_time[1]<<5)|ip.date_time[2]))
 # patch central directory timestamps in order
 off=za.start_dir
 for ia in za.infolist():
  assert src[off:off+4]==b'PK\x01\x02',(off,src[off:off+4])
  nl,xl,cl=struct.unpack_from('<HHH',src,off+28)
  n=src[off+46:off+46+nl].decode('utf-8')
  assert n==ia.filename,(n,ia.filename)
  ip=p[n]
  struct.pack_into('<HH',src,off+12,((ip.date_time[3]<<11)|(ip.date_time[4]<<5)|(ip.date_time[5]//2)),(((ip.date_time[0]-1980)<<9)|(ip.date_time[1]<<5)|ip.date_time[2]))
  off+=46+nl+xl+cl
out.write_bytes(src)
print(json.dumps({'output':str(out),'sha256':hashlib.sha256(src).hexdigest(),'size':len(src),'pinned_sha256':hashlib.sha256(pin.read_bytes()).hexdigest(),'exact_match':src==pin.read_bytes()},indent=2))
