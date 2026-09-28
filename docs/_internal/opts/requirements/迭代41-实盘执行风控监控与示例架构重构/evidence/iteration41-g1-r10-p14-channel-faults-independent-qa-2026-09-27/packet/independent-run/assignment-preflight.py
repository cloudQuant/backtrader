import ctypes, json, os, subprocess, sys
from ctypes import wintypes
if os.name != 'nt': raise SystemExit('Windows required')
k=ctypes.WinDLL('kernel32',use_last_error=True)
H=wintypes.HANDLE; D=wintypes.DWORD; B=wintypes.BOOL
k.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR]; k.CreateJobObjectW.restype=H
k.OpenProcess.argtypes=[D,B,D]; k.OpenProcess.restype=H
k.AssignProcessToJobObject.argtypes=[H,H]; k.AssignProcessToJobObject.restype=B
k.TerminateJobObject.argtypes=[H,D]; k.TerminateJobObject.restype=B
k.CloseHandle.argtypes=[H]; k.CloseHandle.restype=B
PROCESS_TERMINATE=1; PROCESS_SET_QUOTA=0x100; PROCESS_QUERY_LIMITED_INFORMATION=0x1000; SYNCHRONIZE=0x100000
CREATE_NO_WINDOW=0x08000000
job=k.CreateJobObjectW(None,None)
if not job: raise OSError(ctypes.get_last_error(),'CreateJobObjectW')
child=None; ph=None; assigned=False; assign_error=0; cleanup=''
try:
    child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=CREATE_NO_WINDOW,close_fds=True)
    ph=k.OpenProcess(PROCESS_TERMINATE|PROCESS_SET_QUOTA|PROCESS_QUERY_LIMITED_INFORMATION|SYNCHRONIZE,False,child.pid)
    if not ph: raise OSError(ctypes.get_last_error(),'OpenProcess')
    ctypes.set_last_error(0); assigned=bool(k.AssignProcessToJobObject(job,ph)); assign_error=ctypes.get_last_error()
finally:
    if child is not None and child.poll() is None:
        if assigned:
            cleanup='terminated_by_test_job'; k.TerminateJobObject(job,0xE9FD)
        else:
            cleanup='terminated_directly_after_assignment_failure'; child.terminate()
        try: child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill(); child.wait(timeout=3); cleanup += '_kill_fallback'
    if ph: k.CloseHandle(ph)
    k.CloseHandle(job)
result={'assign_return':assigned,'assign_last_error':assign_error,'cleanup':cleanup,'child_exit_code':None if child is None else child.returncode,'scope':'inert child sleep; no SDK/provider/network'}
print(json.dumps(result,sort_keys=True))
if not assigned: raise SystemExit(2)