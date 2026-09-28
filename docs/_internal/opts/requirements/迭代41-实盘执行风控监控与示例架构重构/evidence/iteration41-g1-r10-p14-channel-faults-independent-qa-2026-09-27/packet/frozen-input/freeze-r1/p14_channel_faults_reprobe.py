import ctypes, json, os, subprocess, sys, time
from ctypes import wintypes
from pathlib import Path
if os.name != 'nt': raise SystemExit('Windows required')
K=ctypes.WinDLL('kernel32', use_last_error=True)
H=wintypes.HANDLE; D=wintypes.DWORD; B=wintypes.BOOL
K.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR]; K.CreateJobObjectW.restype=H
K.TerminateJobObject.argtypes=[H,D]; K.TerminateJobObject.restype=B
K.QueryInformationJobObject.argtypes=[H,ctypes.c_int,ctypes.c_void_p,D,ctypes.POINTER(D)]; K.QueryInformationJobObject.restype=B
K.DuplicateHandle.argtypes=[H,H,H,ctypes.POINTER(H),D,B,D]; K.DuplicateHandle.restype=B
K.GetCurrentProcess.argtypes=[]; K.GetCurrentProcess.restype=H
K.OpenProcess.argtypes=[D,B,D]; K.OpenProcess.restype=H
K.AssignProcessToJobObject.argtypes=[H,H]; K.AssignProcessToJobObject.restype=B
K.WaitForSingleObject.argtypes=[H,D]; K.WaitForSingleObject.restype=D
K.CloseHandle.argtypes=[H]; K.CloseHandle.restype=B
K.CreatePipe.argtypes=[ctypes.POINTER(H),ctypes.POINTER(H),ctypes.c_void_p,D]; K.CreatePipe.restype=B
K.SetHandleInformation.argtypes=[H,D,D]; K.SetHandleInformation.restype=B
PROCESS_TERMINATE=1; PROCESS_SET_QUOTA=0x100; PROCESS_QUERY_LIMITED_INFORMATION=0x1000; SYNCHRONIZE=0x100000
JOB_TERMINATE=8; PIPE_INHERIT=1; CREATE_NO_WINDOW=0x08000000
class Accounting(ctypes.Structure):
    _fields_=[('TotalUserTime',ctypes.c_longlong),('TotalKernelTime',ctypes.c_longlong),('ThisPeriodTotalUserTime',ctypes.c_longlong),('ThisPeriodTotalKernelTime',ctypes.c_longlong),('TotalPageFaultCount',D),('TotalProcesses',D),('ActiveProcesses',D),('TotalTerminatedProcesses',D)]
def timed(fn):
    ctypes.set_last_error(0); start=time.perf_counter_ns(); ok=bool(fn()); elapsed=time.perf_counter_ns()-start
    return {'return':ok,'last_error':ctypes.get_last_error(),'elapsed_ns':elapsed}
def query(h):
    a=Accounting(); n=D(0); ctypes.set_last_error(0); start=time.perf_counter_ns()
    ok=bool(K.QueryInformationJobObject(H(h),1,ctypes.byref(a),ctypes.sizeof(a),ctypes.byref(n)))
    return {'return':ok,'last_error':ctypes.get_last_error(),'elapsed_ns':time.perf_counter_ns()-start,'active':int(a.ActiveProcesses) if ok else None,'total':int(a.TotalProcesses) if ok else None,'bytes':int(n.value)}
def new_job():
    ctypes.set_last_error(0); h=K.CreateJobObjectW(None,None)
    if not h: raise OSError(ctypes.get_last_error(),'CreateJobObjectW')
    return int(h)
def wait_active(job,want,seconds=5):
    end=time.monotonic()+seconds; last=None
    while time.monotonic()<end:
        last=query(job)
        if last['return'] and last['active']==want:return last
        time.sleep(.01)
    return last
def run_wrapper_stall(kind,root):
    marker=root/f'{kind}-wrapper.marker';
    if marker.exists():marker.unlink()
    pipe_r=pipe_w=0
    api='ctypes.WinDLL("kernel32",use_last_error=True).TerminateJobObject(wintypes.HANDLE(0x12345678),0xE9FA)'
    if kind=='channel-close':
        r=H(); w=H()
        if not K.CreatePipe(ctypes.byref(r),ctypes.byref(w),None,4096):raise OSError(ctypes.get_last_error(),'CreatePipe')
        pipe_r,pipe_w=int(r.value),int(w.value)
        if not K.SetHandleInformation(H(pipe_w),PIPE_INHERIT,PIPE_INHERIT):raise OSError(ctypes.get_last_error(),'SetHandleInformation')
        api=f'ctypes.WinDLL("kernel32",use_last_error=True).CloseHandle(wintypes.HANDLE({pipe_w}))'
    target_handle=pipe_w if kind=='channel-close' else 0x12345678
    code=('import ctypes,pathlib,sys,time; from ctypes import wintypes; p=pathlib.Path(sys.argv[1]); h=int(sys.argv[2]); '
          'k=ctypes.WinDLL("kernel32",use_last_error=True); flags=wintypes.DWORD(); '
          'k.GetHandleInformation.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]; '
          'k.GetHandleInformation.restype=wintypes.BOOL; '
          'valid=bool(k.GetHandleInformation(wintypes.HANDLE(h),ctypes.byref(flags))); '
          'p.write_text("WRAPPER_ENTERED:"+str(time.perf_counter_ns())+":"+str(int(valid))+"\\n"); time.sleep(30); '
          'p.write_text(p.read_text()+"API_REACHED\\n"); '
          'ok=bool('+api+'); err=ctypes.get_last_error(); p.write_text(p.read_text()+"API_RETURNED:"+str(int(ok))+":"+str(err)+"\\n")')
    job=new_job(); child=None; ph=0
    try:
        child=subprocess.Popen([sys.executable,'-c',code,str(marker),str(target_handle)],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=CREATE_NO_WINDOW,close_fds=False)
        ctypes.set_last_error(0); ph=K.OpenProcess(PROCESS_TERMINATE|PROCESS_SET_QUOTA|PROCESS_QUERY_LIMITED_INFORMATION|SYNCHRONIZE,False,child.pid)
        if not ph:raise OSError(ctypes.get_last_error(),'OpenProcess')
        if not K.AssignProcessToJobObject(H(job),H(ph)):raise OSError(ctypes.get_last_error(),'AssignProcessToJobObject')
        deadline=time.monotonic()+5
        while time.monotonic()<deadline and not marker.exists():time.sleep(.005)
        if not marker.exists():
            try: out_text,err_text=child.communicate(timeout=1)
            except subprocess.TimeoutExpired: out_text,err_text=b'',b'child still alive without marker'
            raise RuntimeError(f'wrapper entry marker missing rc={child.returncode} stdout={out_text!r} stderr={err_text!r}; code={code!r}')
        marker_parts=marker.read_text(encoding='ascii').strip().split(':'); wrapper_entry_ns=int(marker_parts[1]); target_handle_valid=(marker_parts[2]=='1'); time.sleep(.1)
        if kind=='channel-close' and not target_handle_valid:raise RuntimeError('inherited channel handle was not valid in child')
        active_before=query(job)
        elapsed_to_call=time.perf_counter_ns()-wrapper_entry_ns
        outer=timed(lambda:K.TerminateJobObject(H(job),0xE9FB))
        waited=int(K.WaitForSingleObject(H(ph),5000)); active_after=wait_active(job,0)
        child.wait(timeout=3); marker_text=marker.read_text(encoding='ascii')
        return {'operation':kind,'classification':'user-mode wrapper sleep; target API not reached','marker':marker_text,'api_reached':'API_REACHED' in marker_text,'api_returned':'API_RETURNED' in marker_text,'target_handle_valid_at_wrapper_entry':target_handle_valid,'injected_wrapper_stall_ms':100,'wrapper_elapsed_to_outer_terminate_call_ns':elapsed_to_call,'outer_job_active_before':active_before,'outer_terminate':outer,'wait_result':waited,'outer_job_active_after':active_after,'child_exit_code':child.returncode}
    finally:
        if child is not None and child.poll() is None:
            K.TerminateJobObject(H(job),0xE9FC)
            try:child.wait(timeout=3)
            except subprocess.TimeoutExpired:child.kill(); child.wait(timeout=3)
        if ph:K.CloseHandle(H(ph))
        K.CloseHandle(H(job))
        if pipe_r:K.CloseHandle(H(pipe_r))
        if pipe_w:K.CloseHandle(H(pipe_w))
def main():
    out={'status':'FAKE_INERT_DIAGNOSTIC; G1 CLOSED','python':sys.executable,'api_returns':{}}
    a=out['api_returns']
    a['terminate_null']=timed(lambda:K.TerminateJobObject(H(0),0xE9F0))
    a['terminate_invalid_nonnull']=timed(lambda:K.TerminateJobObject(H(0x12345678),0xE9F0))
    a['query_null_current_job']=query(0)
    a['query_invalid_nonnull']=query(0x12345678)
    job=new_job(); limited=H(); ctypes.set_last_error(0)
    dup=bool(K.DuplicateHandle(K.GetCurrentProcess(),H(job),K.GetCurrentProcess(),ctypes.byref(limited),JOB_TERMINATE,False,0)); dup_error=ctypes.get_last_error()
    a['query_terminate_only_handle']={'duplicate_return':dup,'duplicate_error':dup_error}
    if dup:a['query_terminate_only_handle'].update(query(int(limited.value))); K.CloseHandle(limited)
    a['query_valid_empty_job']=query(job); a['job_control_close_first']=timed(lambda:K.CloseHandle(H(job))); a['job_control_close_repeat']=timed(lambda:K.CloseHandle(H(job)))
    job=new_job(); child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=CREATE_NO_WINDOW,close_fds=True)
    ph=0
    try:
        ctypes.set_last_error(0); ph=K.OpenProcess(PROCESS_TERMINATE|PROCESS_SET_QUOTA|PROCESS_QUERY_LIMITED_INFORMATION|SYNCHRONIZE,False,child.pid)
        if not ph:raise OSError(ctypes.get_last_error(),'OpenProcess')
        ctypes.set_last_error(0); assigned=bool(K.AssignProcessToJobObject(H(job),H(ph))); assign_error=ctypes.get_last_error()
        a['assign_inert_child']={'return':assigned,'last_error':assign_error,'pid':child.pid,'test_pid':os.getpid()}
        if not assigned:raise OSError(assign_error,'AssignProcessToJobObject')
        a['query_active_job']=wait_active(job,1)
        a['terminate_valid_job']=timed(lambda:K.TerminateJobObject(H(job),0xE9F1))
        a['process_wait']=int(K.WaitForSingleObject(H(ph),4000))
        a['query_empty_after_terminate']=wait_active(job,0)
    finally:
        if child.poll() is None:K.TerminateJobObject(H(job),0xE9F2); child.wait(timeout=4)
        if ph:K.CloseHandle(H(ph))
        K.CloseHandle(H(job))
    r=H(); w=H()
    if not K.CreatePipe(ctypes.byref(r),ctypes.byref(w),None,4096):raise OSError(ctypes.get_last_error(),'CreatePipe')
    a['pipe_close_first']=timed(lambda:K.CloseHandle(w)); a['pipe_close_repeat']=timed(lambda:K.CloseHandle(w)); a['pipe_read_close']=timed(lambda:K.CloseHandle(r))
    root=Path(__file__).resolve().parent
    out['wrapper_stalls']=[run_wrapper_stall('terminate',root),run_wrapper_stall('channel-close',root)]
    out['interpretation']=['Invalid/restricted handle probes record actual kernel32 BOOL/last-error results.','Valid job probe records actual nonzero then zero Job query around successful TerminateJobObject on a disposable Python sleeper.','Wrapper stall children sleep in user mode before calling the target API; outer Job termination kills them before API_REACHED.','No true kernel/API hang was injected; P14 hang and hard whole-command deadline remain unproved.','No CTP/native/provider, network, credential, private config, account, or default route was used.']
    p=root/'p14_channel_faults_reprobe.json'; p.write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8'); print(json.dumps(out,indent=2)); print('RESULT_FILE='+str(p))
if __name__=='__main__':main()
