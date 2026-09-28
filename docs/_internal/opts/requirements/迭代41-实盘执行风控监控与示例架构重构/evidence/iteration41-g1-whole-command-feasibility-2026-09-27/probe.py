from __future__ import annotations
import ctypes
import json
import math
import os
import subprocess
import sys
import time
import uuid
from ctypes import wintypes
from pathlib import Path

K = ctypes.WinDLL('kernel32', use_last_error=True)
INFINITE = 0xFFFFFFFF
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x102
CREATE_SUSPENDED = 0x00000004
CREATE_NO_WINDOW = 0x08000000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
EVENT_MODIFY_STATE = 0x0002
SYNCHRONIZE = 0x00100000

class IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in (
        'ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
        'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]

class BASIC_LIMIT(ctypes.Structure):
    _fields_ = [
        ('PerProcessUserTimeLimit', ctypes.c_longlong),
        ('PerJobUserTimeLimit', ctypes.c_longlong),
        ('LimitFlags', wintypes.DWORD),
        ('MinimumWorkingSetSize', ctypes.c_size_t),
        ('MaximumWorkingSetSize', ctypes.c_size_t),
        ('ActiveProcessLimit', wintypes.DWORD),
        ('Affinity', ctypes.c_size_t),
        ('PriorityClass', wintypes.DWORD),
        ('SchedulingClass', wintypes.DWORD),
    ]

class EXTENDED_LIMIT(ctypes.Structure):
    _fields_ = [
        ('BasicLimitInformation', BASIC_LIMIT),
        ('IoInfo', IO_COUNTERS),
        ('ProcessMemoryLimit', ctypes.c_size_t),
        ('JobMemoryLimit', ctypes.c_size_t),
        ('PeakProcessMemoryUsed', ctypes.c_size_t),
        ('PeakJobMemoryUsed', ctypes.c_size_t),
    ]

class JOB_ACCOUNTING(ctypes.Structure):
    _fields_ = [
        ('TotalUserTime', ctypes.c_longlong),
        ('TotalKernelTime', ctypes.c_longlong),
        ('ThisPeriodTotalUserTime', ctypes.c_longlong),
        ('ThisPeriodTotalKernelTime', ctypes.c_longlong),
        ('TotalPageFaults', wintypes.DWORD),
        ('TotalProcesses', wintypes.DWORD),
        ('ActiveProcesses', wintypes.DWORD),
        ('TotalTerminatedProcesses', wintypes.DWORD),
    ]

class STARTUPINFO(ctypes.Structure):
    _fields_ = [
        ('cb', wintypes.DWORD), ('lpReserved', wintypes.LPWSTR),
        ('lpDesktop', wintypes.LPWSTR), ('lpTitle', wintypes.LPWSTR),
        ('dwX', wintypes.DWORD), ('dwY', wintypes.DWORD),
        ('dwXSize', wintypes.DWORD), ('dwYSize', wintypes.DWORD),
        ('dwXCountChars', wintypes.DWORD), ('dwYCountChars', wintypes.DWORD),
        ('dwFillAttribute', wintypes.DWORD), ('dwFlags', wintypes.DWORD),
        ('wShowWindow', wintypes.WORD), ('cbReserved2', wintypes.WORD),
        ('lpReserved2', ctypes.c_void_p), ('hStdInput', wintypes.HANDLE),
        ('hStdOutput', wintypes.HANDLE), ('hStdError', wintypes.HANDLE),
    ]

class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [('hProcess', wintypes.HANDLE), ('hThread', wintypes.HANDLE),
                ('dwProcessId', wintypes.DWORD), ('dwThreadId', wintypes.DWORD)]

K.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
K.OpenProcess.restype = wintypes.HANDLE
K.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
K.QueryFullProcessImageNameW.restype = wintypes.BOOL
K.GetCurrentProcessId.argtypes = []
K.GetCurrentProcessId.restype = wintypes.DWORD
K.QueryPerformanceCounter.argtypes = [ctypes.POINTER(ctypes.c_longlong)]
K.QueryPerformanceCounter.restype = wintypes.BOOL
K.QueryPerformanceFrequency.argtypes = [ctypes.POINTER(ctypes.c_longlong)]
K.QueryPerformanceFrequency.restype = wintypes.BOOL
K.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
K.CreateEventW.restype = wintypes.HANDLE
K.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
K.OpenEventW.restype = wintypes.HANDLE
K.SetEvent.argtypes = [wintypes.HANDLE]
K.SetEvent.restype = wintypes.BOOL
K.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
K.WaitForSingleObject.restype = wintypes.DWORD
K.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
K.CreateJobObjectW.restype = wintypes.HANDLE
K.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
K.SetInformationJobObject.restype = wintypes.BOOL
K.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
K.AssignProcessToJobObject.restype = wintypes.BOOL
K.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
K.TerminateJobObject.restype = wintypes.BOOL
K.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
K.QueryInformationJobObject.restype = wintypes.BOOL
K.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
                              wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
                              ctypes.POINTER(STARTUPINFO), ctypes.POINTER(PROCESS_INFORMATION)]
K.CreateProcessW.restype = wintypes.BOOL
K.ResumeThread.argtypes = [wintypes.HANDLE]
K.ResumeThread.restype = wintypes.DWORD
K.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
K.GetExitCodeProcess.restype = wintypes.BOOL
K.CloseHandle.argtypes = [wintypes.HANDLE]
K.CloseHandle.restype = wintypes.BOOL


def qpc() -> int:
    value = ctypes.c_longlong()
    if not K.QueryPerformanceCounter(ctypes.byref(value)):
        raise ctypes.WinError(ctypes.get_last_error())
    return value.value


def qpc_freq() -> int:
    value = ctypes.c_longlong()
    if not K.QueryPerformanceFrequency(ctypes.byref(value)):
        raise ctypes.WinError(ctypes.get_last_error())
    return value.value


def win_bool(name, ok):
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error(), name)


def close_handle(h, label):
    if h:
        win_bool(label, K.CloseHandle(h))


def make_event(name):
    h = K.CreateEventW(None, True, False, name)
    if not h:
        raise ctypes.WinError(ctypes.get_last_error(), 'CreateEventW')
    return h


def wait_until(h, deadline, freq):
    now = qpc()
    remaining = deadline - now
    if remaining <= 0:
        return WAIT_TIMEOUT
    ms = max(1, min(0xFFFFFFFE, math.ceil(remaining * 1000 / freq)))
    return K.WaitForSingleObject(h, ms)


def job_active(job):
    info = JOB_ACCOUNTING()
    win_bool('QueryInformationJobObject', K.QueryInformationJobObject(
        job, JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION, ctypes.byref(info), ctypes.sizeof(info), None))
    return int(info.ActiveProcesses)

def image_for_pid(pid):
    h = K.OpenProcess(0x1000, False, pid)
    if not h: return {'pid': pid, 'error': int(ctypes.get_last_error())}
    try:
        buf = ctypes.create_unicode_buffer(1024); n = wintypes.DWORD(len(buf))
        if not K.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return {'pid': pid, 'error': int(ctypes.get_last_error())}
        return {'pid': pid, 'image': buf.value}
    finally: K.CloseHandle(h)

def job_pids(job):
    size = 8 + 64 * ctypes.sizeof(ctypes.c_size_t)
    buf = ctypes.create_string_buffer(size)
    win_bool('QueryInformationJobObject(BasicProcessIdList)', K.QueryInformationJobObject(
        job, 3, ctypes.byref(buf), size, None))
    assigned, returned = ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD * 2)).contents
    values = ctypes.cast(ctypes.byref(buf, 8), ctypes.POINTER(ctypes.c_size_t * int(returned))).contents
    pids = [int(x) for x in values]
    return {'assigned': int(assigned), 'returned': int(returned), 'pids': pids, 'images': [image_for_pid(x) for x in pids]}


def worker(mode, entered_name, wrapper_name, returned_name, gate_name, result_path):
    entered = K.OpenEventW(EVENT_MODIFY_STATE | SYNCHRONIZE, False, entered_name)
    wrapper = K.OpenEventW(EVENT_MODIFY_STATE | SYNCHRONIZE, False, wrapper_name)
    returned = K.OpenEventW(EVENT_MODIFY_STATE | SYNCHRONIZE, False, returned_name)
    gate = K.OpenEventW(EVENT_MODIFY_STATE | SYNCHRONIZE, False, gate_name)
    if not all((entered, wrapper, returned, gate)):
        raise ctypes.WinError(ctypes.get_last_error(), 'OpenEventW')
    try:
        if mode == 'wrapper_sleep':
            win_bool('SetEvent(wrapper_sleep_begin)', K.SetEvent(wrapper))
            time.sleep(1.2)  # Deliberately user-mode, before the target API.
        win_bool('SetEvent(api_call_begin)', K.SetEvent(entered))
        # Real Win32 wait call against an unsignaled event. It should not return
        # until signaled; parent deliberately never signals it before the D check.
        result = K.WaitForSingleObject(gate, INFINITE)
        with open(result_path, 'w', encoding='utf-8') as f:
            f.write(json.dumps({'wait_result': int(result)}) + '\n')
        win_bool('SetEvent(api_call_return)', K.SetEvent(returned))
    finally:
        for h, label in ((gate, 'CloseHandle(gate)'), (returned, 'CloseHandle(returned)'),
                         (wrapper, 'CloseHandle(wrapper)'), (entered, 'CloseHandle(entered)')):
            close_handle(h, label)
    return 0


def one_trial(mode, budget_ms, root):
    freq = qpc_freq()
    t0 = qpc()  # Start before request-local event, Job, and process setup.
    deadline = t0 + int(freq * budget_ms / 1000)
    token = uuid.uuid4().hex
    event_names = {n: 'Local\\g1deadline_' + token + '_' + n for n in ('entered', 'wrapper', 'returned', 'gate')}
    handles = {k: make_event(v) for k, v in event_names.items()}
    job = None
    pi = PROCESS_INFORMATION()
    result_path = str(root / f'{mode}-worker-return.json')
    trial = {'mode': mode, 'budget_ms': budget_ms, 'controller_pid': int(K.GetCurrentProcessId()), 'qpc_frequency': freq, 't0_qpc': t0,
             'deadline_qpc': deadline, 'events': event_names, 'worker_result_path': result_path}
    try:
        job = K.CreateJobObjectW(None, None)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error(), 'CreateJobObjectW')
        limits = EXTENDED_LIMIT()
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win_bool('SetInformationJobObject(KILL_ON_JOB_CLOSE)', K.SetInformationJobObject(
            job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits), ctypes.sizeof(limits)))
        argv = [sys.executable, str(Path(__file__).resolve()), '--worker', mode,
                event_names['entered'], event_names['wrapper'], event_names['returned'],
                event_names['gate'], result_path]
        cmd = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
        si = STARTUPINFO(); si.cb = ctypes.sizeof(si)
        win_bool('CreateProcessW(CREATE_SUSPENDED)', K.CreateProcessW(
            sys.executable, cmd, None, None, False, CREATE_SUSPENDED | CREATE_NO_WINDOW,
            None, str(root), ctypes.byref(si), ctypes.byref(pi)))
        trial['worker_pid'] = int(pi.dwProcessId)
        win_bool('AssignProcessToJobObject', K.AssignProcessToJobObject(job, pi.hProcess))
        resumed = K.ResumeThread(pi.hThread)
        if resumed == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error(), 'ResumeThread')
        close_handle(pi.hThread, 'CloseHandle(thread)'); pi.hThread = None
        trial['resume_previous_suspend_count'] = int(resumed)
        marker = wait_until(handles['wrapper'] if mode == 'wrapper_sleep' else handles['entered'], deadline, freq)
        trial['first_marker_wait_result'] = int(marker)
        trial['first_marker'] = 'wrapper_sleep_begin' if mode == 'wrapper_sleep' else 'api_call_begin'
        if marker == WAIT_TIMEOUT:
            trial['marker_seen_by_deadline'] = False
        elif marker == WAIT_OBJECT_0:
            trial['marker_seen_by_deadline'] = True
        else:
            trial['marker_wait_winerror'] = int(ctypes.get_last_error())
        process_wait = wait_until(pi.hProcess, deadline, freq)
        trial['process_wait_at_deadline'] = int(process_wait)
        trial['api_return_marker_before_cleanup'] = K.WaitForSingleObject(handles['returned'], 0) == WAIT_OBJECT_0
        trial['worker_alive_at_deadline'] = K.WaitForSingleObject(pi.hProcess, 0) == WAIT_TIMEOUT
        trial['job_active_at_deadline'] = job_active(job)
        trial['job_process_ids_at_deadline'] = job_pids(job)
        trial['caller_result'] = 'UNKNOWN' if process_wait == WAIT_TIMEOUT else 'PROCESS_EXITED_BEFORE_D'
        trial['bounded_function_return_qpc'] = qpc()
        trial['bounded_function_return_delta_ms'] = (trial['bounded_function_return_qpc'] - t0) * 1000 / freq

        cleanup_start = qpc()
        term_ok = K.TerminateJobObject(job, 91)
        trial['post_deadline_terminate_job_bool'] = bool(term_ok)
        trial['post_deadline_terminate_job_error'] = 0 if term_ok else int(ctypes.get_last_error())
        wait_cleanup = K.WaitForSingleObject(pi.hProcess, 3000)
        trial['post_deadline_process_wait'] = int(wait_cleanup)
        trial['post_deadline_job_active'] = job_active(job)
        trial['post_deadline_job_process_ids'] = job_pids(job)
        exit_code = wintypes.DWORD()
        if K.GetExitCodeProcess(pi.hProcess, ctypes.byref(exit_code)):
            trial['worker_exit_code'] = int(exit_code.value)
        trial['post_deadline_cleanup_delta_ms'] = (qpc() - cleanup_start) * 1000 / freq
        return trial
    finally:
        if pi.hThread:
            K.TerminateThread(pi.hThread, 92)
            K.CloseHandle(pi.hThread)
        if pi.hProcess:
            # Last-resort bounded teardown of this inert test child.
            K.TerminateProcess(pi.hProcess, 93)
            K.WaitForSingleObject(pi.hProcess, 3000)
            K.CloseHandle(pi.hProcess)
        if job:
            # Closing the KILL_ON_JOB_CLOSE test handle is final cleanup only.
            K.CloseHandle(job)
        for h in handles.values():
            if h:
                K.CloseHandle(h)


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == '--worker':
        _, _, mode, entered, wrapper, returned, gate, result_path = sys.argv
        raise SystemExit(worker(mode, entered, wrapper, returned, gate, result_path))
    root = Path(__file__).resolve().parent
    freq = qpc_freq()
    result = {'status': 'FEASIBILITY_ONLY; G1 CLOSED', 'platform': sys.platform,
              'python': sys.version, 'qpc_frequency': freq, 'trials': []}
    for mode in ('api_wait', 'wrapper_sleep'):
        result['trials'].append(one_trial(mode, 700, root))
    (root / 'results.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    main()
