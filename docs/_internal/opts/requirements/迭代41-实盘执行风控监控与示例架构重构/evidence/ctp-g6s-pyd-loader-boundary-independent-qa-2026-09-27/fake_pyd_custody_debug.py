from __future__ import annotations
import ctypes, hashlib, os, tempfile
from pathlib import Path
from ctypes import wintypes
k=ctypes.WinDLL('kernel32',use_last_error=True)
cf=k.CreateFileW; cf.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]; cf.restype=wintypes.HANDLE
ch=k.CloseHandle; ch.argtypes=[wintypes.HANDLE]; ch.restype=wintypes.BOOL
with tempfile.TemporaryDirectory() as d:
 p=Path(d)/'x.pyd'; p.write_bytes(b'1234567890')
 h=cf(str(p),0x80000000,1,None,3,0,None)
 print('first_handle_type',type(h),'repr',repr(h),'value',getattr(h,'value',None),'last_error',ctypes.get_last_error())
 hv=ctypes.cast(h,ctypes.c_void_p).value
 print('cast',hex(hv or 0))
 ctypes.set_last_error(0)
 h2=cf(str(p),0x40000000,1,None,3,0,None)
 print('second_write_handle',repr(h2),'cast',ctypes.cast(h2,ctypes.c_void_p).value,'last_error',ctypes.get_last_error())
 if ctypes.cast(h2,ctypes.c_void_p).value not in (None,ctypes.c_void_p(-1).value): ch(h2)
 try:
  with open(p,'r+b') as f:
   print('python_open_succeeded')
   n=f.write(b'ABC')
   print('python_write_return',n,'file_hash_in_scope',hashlib.sha256(p.read_bytes()).hexdigest())
 except BaseException as e:
  print('python_error',type(e).__name__,repr(e),'winerror',getattr(e,'winerror',None),'errno',getattr(e,'errno',None))
 print('after',p.read_bytes())
 ch(h)
