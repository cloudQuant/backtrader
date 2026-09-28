import ctypes
import hashlib
import json
import msvcrt
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXE = ROOT / "r9_custodian.exe"
BUILD_BAT = ROOT / "r9_build.bat"
BUILD_LOG = ROOT / "r9_build.log"
TRIALS = ROOT / "r9_trials.json"
FINDINGS = ROOT / "R9_FINDINGS.md"
MANIFEST = ROOT / "r9_manifest.json"
RECEIPT = ROOT / "r9_receipt.json"
R8_SOURCE = Path(r"D:\temp\iteration41-g1-r8-independent-custodian-20260927")
EXPECTED_R8_MANIFEST_SHA = "f1ce63cf08ec620c7a4ca09fac55bc26a7553f88796cfb3e2a768f7bb008cdeb"
EXPECTED_R8_TRIALS_SHA = "4c412a14af1cb5fe5ea5f6ff39f23d7952187e5f60bc2015f70d0098af6cf58a"
EXPECTED_R9_DESIGN_SHA = "77500a63eabd0df5673b923458893fbd44c0d3ca1ec22c403dff95b98d869bd0"
EXPECTED_R9_DESIGN_MANIFEST_SHA = "ad6fb53200789e051fc93d76d073c54c6f2d7d9bfaea4b3e288da0bd055765c0"

K32 = ctypes.WinDLL("kernel32", use_last_error=True)
HANDLE = ctypes.c_void_p
BOOL = ctypes.c_int
DWORD = ctypes.c_uint32
LPDWORD = ctypes.POINTER(DWORD)


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("nLength", DWORD), ("lpSecurityDescriptor", ctypes.c_void_p), ("bInheritHandle", BOOL)]


class JobAccounting(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_int64),
        ("TotalKernelTime", ctypes.c_int64),
        ("ThisPeriodTotalUserTime", ctypes.c_int64),
        ("ThisPeriodTotalKernelTime", ctypes.c_int64),
        ("TotalPageFaultCount", DWORD),
        ("TotalProcesses", DWORD),
        ("ActiveProcesses", DWORD),
        ("TotalTerminatedProcesses", DWORD),
    ]


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", DWORD), ("dwHighDateTime", DWORD)]


K32.CreateEventW.argtypes = [ctypes.c_void_p, BOOL, BOOL, ctypes.c_wchar_p]
K32.CreateEventW.restype = HANDLE
K32.SetHandleInformation.argtypes = [HANDLE, DWORD, DWORD]
K32.SetHandleInformation.restype = BOOL
K32.SetEvent.argtypes = [HANDLE]
K32.SetEvent.restype = BOOL
K32.CloseHandle.argtypes = [HANDLE]
K32.CloseHandle.restype = BOOL
K32.PeekNamedPipe.argtypes = [HANDLE, ctypes.c_void_p, DWORD, LPDWORD, LPDWORD, LPDWORD]
K32.PeekNamedPipe.restype = BOOL
K32.QueryInformationJobObject.argtypes = [HANDLE, ctypes.c_int, ctypes.c_void_p, DWORD, LPDWORD]
K32.QueryInformationJobObject.restype = BOOL
K32.TerminateJobObject.argtypes = [HANDLE, DWORD]
K32.TerminateJobObject.restype = BOOL
K32.WaitForSingleObject.argtypes = [HANDLE, DWORD]
K32.WaitForSingleObject.restype = DWORD
K32.OpenProcess.argtypes = [DWORD, BOOL, DWORD]
K32.OpenProcess.restype = HANDLE
K32.GetProcessTimes.argtypes = [HANDLE, ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME)]
K32.GetProcessTimes.restype = BOOL

HANDLE_FLAG_INHERIT = 1
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
JOB_OBJECT_QUERY = 0x0004
JOB_OBJECT_TERMINATE = 0x0008


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def job_active(value):
    info = JobAccounting()
    ok = K32.QueryInformationJobObject(HANDLE(value), 1, ctypes.byref(info), ctypes.sizeof(info), None)
    if not ok:
        return None, ctypes.get_last_error()
    return int(info.ActiveProcesses), 0


def parse_marker(line: str, prefix: str) -> dict:
    result = {"marker": prefix}
    for key, value in re.findall(r"([A-Za-z_]+)=([^\s]+)", line):
        if value.isdigit():
            result[key] = int(value)
        else:
            result[key] = value
    return result


def read_until(proc, marker: bytes, timeout_s: float) -> bytes:
    fd = proc.stdout.fileno()
    read_handle = HANDLE(msvcrt.get_osfhandle(fd))
    out = bytearray()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        available = DWORD()
        ok = K32.PeekNamedPipe(read_handle, None, 0, None, ctypes.byref(available), None)
        if ok and available.value:
            out.extend(os.read(fd, min(int(available.value), 65536)))
            if marker in out:
                return bytes(out)
            continue
        if proc.poll() is not None:
            break
        time.sleep(0.002)
    return bytes(out)


def marker_from(text: str, prefix: str):
    line = next((line for line in text.splitlines() if line.startswith(prefix + " ")), "")
    return parse_marker(line, prefix) if line else {}


def open_pid(pid: int):
    handle = K32.OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None, ctypes.get_last_error()
    create, exit_time, kernel, user = FILETIME(), FILETIME(), FILETIME(), FILETIME()
    if not K32.GetProcessTimes(handle, ctypes.byref(create), ctypes.byref(exit_time), ctypes.byref(kernel), ctypes.byref(user)):
        error = ctypes.get_last_error()
        K32.CloseHandle(handle)
        return None, error
    created = (int(create.dwHighDateTime) << 32) | int(create.dwLowDateTime)
    return {"handle": int(handle), "pid": pid, "creation_time_100ns": created}, 0


def build():
    vcvars = r"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
    tmp = ROOT / ".tmp"
    tmp.mkdir(exist_ok=True)
    lines = [
        "@echo off",
        f'set "TEMP={tmp}"',
        f'set "TMP={tmp}"',
        f'call "{vcvars}" >NUL',
        "cl /nologo /std:c++17 /EHsc /O2 /W4 /Fe:r9_custodian.exe r9_custodian.cpp",
        "exit /b %ERRORLEVEL%",
        "",
    ]
    BUILD_BAT.write_text("\r\n".join(lines), encoding="ascii", newline="")
    p = subprocess.run(["cmd.exe", "/d", "/c", str(BUILD_BAT)], cwd=ROOT, capture_output=True, timeout=90)
    output = p.stdout + p.stderr
    BUILD_LOG.write_bytes(output)
    return {"exit_code": p.returncode, "output": output.decode("utf-8", errors="replace"),
            "exe_exists": EXE.exists(), "exe_sha256": sha256(EXE) if EXE.exists() else None}


def create_go_event():
    sa = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), None, True)
    event = K32.CreateEventW(ctypes.byref(sa), True, False, None)
    if not event:
        raise OSError(ctypes.get_last_error(), "CreateEventW")
    if not K32.SetHandleInformation(event, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT):
        error = ctypes.get_last_error()
        K32.CloseHandle(event)
        raise OSError(error, "SetHandleInformation")
    return int(event)


def run_trial(mode: str):
    go = create_go_event()
    startup = subprocess.STARTUPINFO()
    startup.lpAttributeList = {"handle_list": [go]}
    launch_start = time.monotonic_ns()
    p = subprocess.Popen([str(EXE), "--outer-run", mode, str(os.getpid()), str(go), sys.executable],
                         cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         bufsize=0, close_fds=True, startupinfo=startup)
    popen_ns = time.monotonic_ns() - launch_start
    head_bytes = read_until(p, b"R9_READY", 15.0)
    head = head_bytes.decode("utf-8", errors="replace")
    outer = marker_from(head, "R9_OUTER_JOB_CONTROL_READY")
    ready = marker_from(head, "R9_READY")
    if not ready:
        remote = outer.get("external_job_handle")
        if remote:
            K32.TerminateJobObject(HANDLE(remote), 0xE9FF0001)
        tail = b""
        try:
            tail, _ = p.communicate(timeout=4.0)
        except subprocess.TimeoutExpired:
            p.kill()
            tail, _ = p.communicate(timeout=2.0)
        if remote:
            K32.CloseHandle(HANDLE(remote))
        K32.CloseHandle(HANDLE(go))
        return {"mode": mode, "popen_elapsed_ns_pre_request": popen_ns, "ready": False,
                "head_output": head, "tail_output": tail.decode("utf-8", errors="replace"), "outer_marker": outer}

    ready_wait_ns = time.monotonic_ns() - launch_start - popen_ns
    if not K32.SetEvent(HANDLE(go)):
        raise OSError(ctypes.get_last_error(), "SetEvent(go)")
    go_set_ns = time.monotonic_ns()

    if mode == "outer-job":
        more = read_until(p, b"R9_PENDING_IO", 5.0)
        all_head = head + more.decode("utf-8", errors="replace")
        barrier = marker_from(all_head, "R9_REQUEST_BARRIER")
        pending = marker_from(all_head, "R9_PENDING_IO")
        remote = outer.get("external_job_handle")
        identities = {}
        held = []
        for role, pid in [("launcher", outer.get("launcher_pid")), ("supervisor", ready.get("supervisor_pid")),
                          ("caller", ready.get("caller_pid")), ("broker", ready.get("broker_pid")),
                          ("worker", ready.get("worker_pid"))]:
            if pid:
                fact, error = open_pid(pid)
                if fact:
                    identities[role] = {k: v for k, v in fact.items() if k != "handle"}
                    held.append((role, fact["handle"]))
                else:
                    identities[role] = {"pid": pid, "open_error": error}
        before, before_error = job_active(remote) if remote else (None, 6)
        start = time.monotonic_ns()
        term_ok = bool(remote and K32.TerminateJobObject(HANDLE(remote), 0xE9FF0002))
        term_error = 0 if term_ok else ctypes.get_last_error()
        waits = {role: K32.WaitForSingleObject(HANDLE(h), 2500) for role, h in held}
        after, after_error = None, 0
        end = time.monotonic() + 2.5
        while remote and time.monotonic() < end:
            after, after_error = job_active(remote)
            if after == 0:
                break
            time.sleep(0.005)
        try:
            p.wait(timeout=4.0)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait(timeout=2.0)
        tail = b""
        try:
            tail = os.read(p.stdout.fileno(), 65536)
        except OSError:
            pass
        for _, handle in held:
            K32.CloseHandle(HANDLE(handle))
        if remote:
            K32.CloseHandle(HANDLE(remote))
        K32.CloseHandle(HANDLE(go))
        return {"mode": mode, "popen_elapsed_ns_pre_request": popen_ns, "ready_wait_ns_pre_request": ready_wait_ns,
                "go_set_elapsed_ns": time.monotonic_ns() - go_set_ns, "ready": ready, "outer_marker": outer,
                "request_barrier": barrier, "pending_marker": pending, "process_identities": identities,
                "outer_job_active_before": before, "outer_job_query_error_before": before_error,
                "terminate_returned": term_ok, "terminate_error": term_error, "process_wait_results": waits,
                "wait_object_0": WAIT_OBJECT_0, "outer_job_active_after": after, "outer_job_query_error_after": after_error,
                "terminate_and_empty_elapsed_ns": time.monotonic_ns() - start, "launcher_exit_code": p.returncode,
                "tail_output": tail.decode("utf-8", errors="replace")}

    try:
        tail, _ = p.communicate(timeout=10.0)
    except subprocess.TimeoutExpired:
        remote = outer.get("external_job_handle")
        outer_kill = None
        if remote:
            before, _ = job_active(remote)
            t0 = time.monotonic_ns()
            ok = bool(K32.TerminateJobObject(HANDLE(remote), 0xE9FF0003))
            after = None
            end = time.monotonic() + 2.5
            while time.monotonic() < end:
                after, _ = job_active(remote)
                if after == 0:
                    break
                time.sleep(0.005)
            outer_kill = {"active_before": before, "terminate_returned": ok, "active_after": after,
                          "terminate_elapsed_ns": time.monotonic_ns() - t0}
        p.kill()
        tail, _ = p.communicate(timeout=3.0)
        if remote:
            K32.CloseHandle(HANDLE(remote))
        K32.CloseHandle(HANDLE(go))
        return {"mode": mode, "ready": True, "runner_timeout": True, "outer_marker": outer,
                "ready_marker": ready, "outer_job_kill": outer_kill,
                "raw_output": head + tail.decode("utf-8", errors="replace")}

    full = head + tail.decode("utf-8", errors="replace")
    json_line = next((line for line in reversed(full.splitlines()) if line.startswith("{")), "")
    scenario = json.loads(json_line) if json_line else None
    remote = outer.get("external_job_handle")
    active_after, query_error = job_active(remote) if remote else (None, 6)
    if remote:
        K32.CloseHandle(HANDLE(remote))
    K32.CloseHandle(HANDLE(go))
    return {"mode": mode, "ready": True, "runner_timeout": False, "popen_elapsed_ns_pre_request": popen_ns,
            "ready_wait_ns_pre_request": ready_wait_ns, "outer_marker": outer, "ready_marker": ready,
            "outer_job_active_after_process_exit": active_after, "outer_job_query_error_after": query_error,
            "exit_code": p.returncode, "scenario": scenario, "raw_output": full}


def main():
    if os.name != "nt":
        raise SystemExit("R9 requires Windows")
    build_result = build()
    if build_result["exit_code"] != 0 or not EXE.exists():
        raise SystemExit("R9 native build failed")
    modes = ["p05", "caller-death", "popen-before", "popen-after", "outer-job"]
    rows = [run_trial(mode) for mode in modes]
    checks = []

    def check(name, ok, evidence):
        checks.append({"name": name, "pass": bool(ok), "evidence": evidence})

    r8_manifest = ROOT / "r8_baseline_manifest.json"
    r8_trials = ROOT / "r8_baseline_trials.json"
    design = ROOT / "R9_DESIGN_INPUT.md"
    design_manifest = ROOT / "r9_design_manifest.json"
    check("r8_baseline_manifest_sha_matches_frozen", sha256(r8_manifest) == EXPECTED_R8_MANIFEST_SHA, sha256(r8_manifest))
    check("r8_baseline_trials_sha_matches_frozen", sha256(r8_trials) == EXPECTED_R8_TRIALS_SHA, sha256(r8_trials))
    check("guardian_r9_design_sha_matches_frozen", sha256(design) == EXPECTED_R9_DESIGN_SHA, sha256(design))
    check("guardian_r9_design_manifest_sha_matches_frozen", sha256(design_manifest) == EXPECTED_R9_DESIGN_MANIFEST_SHA, sha256(design_manifest))
    by_mode = {r["mode"]: r for r in rows}

    p05 = by_mode["p05"].get("scenario") or {}
    check("P05_caller_returns_UNKNOWN_by_D_with_pending_broker_IO", p05.get("status") == "UNKNOWN" and
          p05.get("caller_api_return_by_D") and p05.get("writer_submitted") and
          p05.get("writer_pending_after_api_return") and p05.get("broker_alive_after_caller_death_or_return") and
          p05.get("writer_done") and p05.get("writer_error") == 995 and p05.get("broker_exact_exit_and_job_empty"), p05)

    death = by_mode["caller-death"].get("scenario") or {}
    check("caller_death_does_not_destroy_pending_IO_owner", death.get("caller_killed") and
          not death.get("caller_api_returned") and death.get("writer_pending_at_caller_terminal_event") and
          death.get("broker_alive_after_caller_death_or_return") and death.get("caller_dead_seen_by_broker") and
          death.get("writer_done") and death.get("writer_error") == 995 and
          death.get("caller_exact_exit_and_job_empty") and death.get("broker_exact_exit_and_job_empty"), death)

    before = by_mode["popen-before"].get("scenario") or {}
    check("Popen_block_before_child_is_fenced_inside_prestarted_worker_Job", before.get("caller_api_return_by_D") and
          before.get("helper_stage") == 1 and before.get("worker_job_terminated") and before.get("worker_job_empty"), before)
    after = by_mode["popen-after"].get("scenario") or {}
    check("Popen_child_created_before_outer_call_returns_is_fenced_by_Job", after.get("caller_api_return_by_D") and
          after.get("helper_stage") == 3 and after.get("worker_job_active_before_kill", 0) >= 2 and
          after.get("worker_job_terminated") and after.get("worker_job_empty"), after)

    outer = by_mode["outer-job"]
    waits = outer.get("process_wait_results", {})
    check("outer_Job_kills_all_prestarted_processes", outer.get("pending_marker", {}).get("pending") == 1 and
          outer.get("terminate_returned") and outer.get("outer_job_active_after") == 0 and
          bool(waits) and all(v == WAIT_OBJECT_0 for v in waits.values()), outer)

    trials = {
        "candidate": "R9 prestarted Windows inert supervisor/broker/sacrificial worker prototype",
        "status": "INERT_PROTOTYPE_ONLY_G1_CLOSED",
        "platform": {"system": platform.platform(), "windows_version": list(sys.getwindowsversion()), "python": sys.version},
        "build": build_result,
        "r8_baseline_manifest_sha256": sha256(r8_manifest),
        "r8_baseline_trials_sha256": sha256(r8_trials),
        "guardian_r9_design_sha256": sha256(design),
        "guardian_r9_design_manifest_sha256": sha256(design_manifest),
        "scenarios": rows,
        "deadline_observations": {
            mode: {
                "deadline_tick_ms": ((row.get("scenario") or {}).get("deadline_tick_ms")),
                "caller_api_return_tick_ms": ((row.get("scenario") or {}).get("caller_api_return_tick_ms")),
                "caller_return_lateness_ms": ((row.get("scenario") or {}).get("caller_return_lateness_ms")),
                "caller_api_return_by_D": ((row.get("scenario") or {}).get("caller_api_return_by_D")),
            }
            for mode, row in by_mode.items() if (row.get("scenario") or {}).get("deadline_tick_ms") is not None
        },
        "checks": checks,
        "failed_checks": [x for x in checks if not x["pass"]],
        "scope": [
            "Local inert Windows processes and local named-pipe IPC only; no SCM service was installed.",
            "Popen/CreateProcess at launcher startup remains prewarm/outside the request budget; no request-time service startup is attempted.",
            "The sacrificial Python helper is prestarted and Job-contained. popen-before blocks before child creation; popen-after creates a real inert child then blocks before the outer Popen call returns. These are deterministic wrappers around Popen, not injected hangs inside the Windows CreateProcess syscall.",
            "The 2 MiB pipe WriteFile is issued overlapped by a prestarted broker process, not by the caller. Caller API stack only publishes a fixed-size shared-memory request and polls one absolute D.",
            "Pending-I/O reaper is a separate process from the request caller and survives caller Job termination. It owns the pipe handle, OVERLAPPED, event, and buffer until final GetOverlappedResult. A 100 ms post-event completion-consumption hold is instrumented; this is not a kernel-level delayed-completion injection.",
            "P07 coverage is limited to an actual pending 2 MiB overlapped write, CancelIoEx, and a 100 ms user-mode hold after its completion event while the broker still owns the context; no kernel-delayed completion or broker-death injection was performed. P14 was not tested: no TerminateJobObject, QueryInformationJobObject, CancelIoEx, or CloseHandle stall was injected.",
            "The bounded shared-memory admission removes the synchronous Queue.put/pipe-write operation from the caller path in this prototype. It does not satisfy a strict caller hard deadline: the observed P05 and Popen wrapper trial returns occurred after D; see per-trial ticks and lateness fields.",
            "No synchronous CreateProcessW, WriteFile, QueryInformationJobObject, TerminateJobObject, CancelIoEx, SetEvent, or CloseHandle hang was injected. A synchronous Win32 call that blocks in the custodian/reaper remains a top-level limit.",
            "Runner subprocess.Popen used to start the local supervisor is synchronous and occurs before the request D; before it returns, the external Python runner has not yet received the duplicated outer Job handle. Its 10-second harness watchdog is not D.",
            "No CTP/native/provider/credentials/private config/network/SCM/default preflight or repository runtime route was used.",
        ],
        "decision": "R9 demonstrates a narrower prewarmed local topology only; G1 remains closed.",
    }
    TRIALS.write_text(json.dumps(trials, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    p05_final = p05
    findings = [
        "# R9 Windows prestarted inert custodian prototype findings",
        "",
        "Status: INERT PROTOTYPE ONLY / G1 CLOSED. This is a local process-topology experiment, not an SCM deployment or acceptance claim.",
        "",
        f"Platform: `{trials['platform']['system']}`; Python `{sys.version.split()[0]}`.",
        f"Reviewed design input: `R9_DESIGN_INPUT.md` SHA-256 `{sha256(design)}`; design receipt manifest SHA-256 `{sha256(design_manifest)}`.",
        f"R8 frozen baseline: manifest `{sha256(r8_manifest)}`, trials `{sha256(r8_trials)}`.",
        f"R9 source SHA-256: `{sha256(ROOT / 'r9_custodian.cpp')}`; trial log SHA-256: `{sha256(TRIALS)}`.",
        "",
        "## Caller deadline and pending I/O",
        "",
        f"The final P05 row reports D={p05_final.get('request_budget_ms')} ms, deadline tick `{p05_final.get('deadline_tick_ms')}`, caller return tick `{p05_final.get('caller_api_return_tick_ms')}`, lateness `{p05_final.get('caller_return_lateness_ms')} ms`, and caller return by D=`{p05_final.get('caller_api_return_by_D')}`. This is a failed hard-deadline sample. At that late return, I/O was still pending=`{p05_final.get('writer_pending_after_api_return')}`; the separate broker later canceled and consumed completion error `{p05_final.get('writer_error')}` (Windows ERROR_OPERATION_ABORTED=995), then exited with its Job empty. The caller path performs only fixed-size shared-memory publication and atomic polling; the prestarted broker owns the connected pipe, OVERLAPPED/event, and 2 MiB buffer through final completion.",
        "",
        "The first preserved trial log is `r9_trials_initial.json`; its SHA-256 is recorded in the manifest. The latest run’s structured `deadline_observations` lists absolute ticks and lateness for P05 and both Popen wrapper probes. Late UNKNOWN is classified as a failed caller return, never upgraded by later cleanup.",
        "",
        "The caller-death row terminates the caller Job while the write is pending. It checks that the broker remains alive and observes caller death, then cancels and consumes final completion. The broker is outside callerJob but remains inside the outer Job.",
        "",
        "## Sacrificial Popen boundary",
        "",
        "A Python helper process is started and assigned to its worker Job during prewarm, before READY. At request time, one injection blocks at the outer Popen wrapper before child creation; another creates an inert Python child and then blocks before the Popen wrapper returns. The supervisor holds the worker Job handle before either request and terminates it at D; the post-create case checks the Job had at least two active processes before termination and became empty afterward. These probes wrap Popen before/after its real CreateProcess work; they do not hang inside the OS CreateProcess syscall.",
        "",
        f"Popen-before stage `{before.get('helper_stage')}` returned at `{before.get('caller_api_return_tick_ms')}` vs D `{before.get('deadline_tick_ms')}` (lateness `{before.get('caller_return_lateness_ms')} ms`); Popen-after stage `{after.get('helper_stage')}` returned at `{after.get('caller_api_return_tick_ms')}` vs D `{after.get('deadline_tick_ms')}` (lateness `{after.get('caller_return_lateness_ms')} ms`). Both caller deadline checks fail. Their eventual worker Job termination/empty proof is cleanup evidence only.",
        "",
        "## Coverage by reviewed cases",
        "",
        "P02/P03: partial wrapper probes only (blocked immediately before Popen creates a child, and blocked after a real inert child exists but before Popen returns). No true CreateProcessW hang was injected. P07: pending overlapped write + cancellation + 100 ms user-mode post-event hold, but no delayed kernel completion. P14: untested. The outer-Job test kills the five-process tree and observes all process handles signaled plus ActiveProcesses=0; it does not prove survival of a dedicated service reaper or caller return when that reaper wedges.",
        "",
        "## Limits",
        "",
        "The local supervisor is launched by Python `subprocess.Popen` during prewarm. That call is synchronous before the runner receives the duplicated outer Job handle, so this prototype does not prove a deadline over startup. No SCM service was installed. Win32 synchronous API hangs and kernel-level delayed I/O completion were not injected; the measured completion hold delays final completion consumption only. The outer Job test proves tree termination after the external duplicate is available, not caller return by D if the only custodian wedges.",
        "",
        "R8 timing facts are distinct: the frozen R8 admission-sync trial and design receipt record D=1200 ms with caller decision at 1218 ms and no caller API return; an older replay finding recorded 1234 ms. R9 does not merge those samples, upgrade the R8 negative, or treat the R9 local topology checks as G1 acceptance.",
        "",
        "No CTP/provider, credentials, private config, network route, SCM, default preflight, or production runtime path was accessed.",
    ]
    FINDINGS.write_text("\n".join(findings) + "\n", encoding="utf-8")

    payload_names = [
        "R9_DESIGN_INPUT.md", "r9_design_manifest.json", "r8_baseline_manifest.json", "r8_baseline_trials.json", "r8_baseline_custodian.cpp",
        "r9_custodian.cpp", "r9_custodian.exe", "r9_custodian.obj", "r9_sacrificial_popen.py",
        "run_r9_trials.py", "r9_build.bat", "r9_build.log", "r9_trials_initial.json", "r9_trials.json", "R9_FINDINGS.md",
    ]
    manifest = {"candidate": trials["candidate"], "status": trials["status"],
                "payload_sha256": {n: sha256(ROOT / n) for n in payload_names},
                "failed_checks": trials["failed_checks"], "decision": trials["decision"],
                "baseline_r8_manifest_sha256": sha256(r8_manifest),
                "baseline_r8_trials_sha256": sha256(r8_trials),
                "guardian_r9_design_sha256": sha256(design),
                "guardian_r9_design_manifest_sha256": sha256(design_manifest)}
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_hash = sha256(MANIFEST)
    (ROOT / "r9_manifest.sha256").write_text(f"{manifest_hash}  r9_manifest.json\n", encoding="ascii")
    receipt = {"manifest": "r9_manifest.json", "manifest_sha256": manifest_hash,
               "trials_sha256": sha256(TRIALS), "source_sha256": sha256(ROOT / "r9_custodian.cpp"),
               "status": trials["status"], "no_provider_or_credentials": True,
               "no_repo_changes": True, "decision": trials["decision"]}
    RECEIPT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    receipt_hash = sha256(RECEIPT)
    (ROOT / "r9_receipt.sha256").write_text(f"{receipt_hash}  r9_receipt.json\n", encoding="ascii")
    print(json.dumps({"manifest_sha256": manifest_hash, "receipt_sha256": receipt_hash,
                      "source_sha256": sha256(ROOT / "r9_custodian.cpp"),
                      "trials_sha256": sha256(TRIALS), "checks": len(checks),
                      "failed_checks": len(trials["failed_checks"]), "decision": trials["decision"]}, indent=2))


if __name__ == "__main__":
    main()
