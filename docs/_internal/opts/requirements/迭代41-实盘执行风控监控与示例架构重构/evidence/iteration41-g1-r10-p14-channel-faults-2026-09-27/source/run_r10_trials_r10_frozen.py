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
EXE = ROOT / "r10_custodian.exe"
BUILD_BAT = ROOT / "r10_build.bat"
BUILD_LOG = ROOT / "r10_build.log"
TRIALS = ROOT / "r10_trials.json"
FINDINGS = ROOT / "R10_FINDINGS.md"
MANIFEST = ROOT / "r10_manifest.json"
RECEIPT = ROOT / "r10_receipt.json"
R9_BASELINE = ROOT / "r9_frozen_baseline"
EXPECTED_R8_MANIFEST_SHA = "f1ce63cf08ec620c7a4ca09fac55bc26a7553f88796cfb3e2a768f7bb008cdeb"
EXPECTED_R8_TRIALS_SHA = "4c412a14af1cb5fe5ea5f6ff39f23d7952187e5f60bc2015f70d0098af6cf58a"
EXPECTED_R9_MANIFEST_SHA = "98a8110a5c99e960d052c18d57c9aaedf3bd43fa61dc3271a8b7235a0280da81"
EXPECTED_R9_TRIALS_SHA = "c848ab2f51360399a399a16a441e66821eb3368ee36bdd44c17d2018dbd50dc7"

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
        "cl /nologo /std:c++17 /EHsc /O2 /W4 /Fe:r10_custodian.exe r10_custodian.cpp",
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
    head_bytes = read_until(p, b"R10_READY", 15.0)
    head = head_bytes.decode("utf-8", errors="replace")
    outer = marker_from(head, "R10_OUTER_JOB_CONTROL_READY")
    ready = marker_from(head, "R10_READY")
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
        more = read_until(p, b"R10_PENDING_IO", 5.0)
        all_head = head + more.decode("utf-8", errors="replace")
        barrier = marker_from(all_head, "R10_REQUEST_BARRIER")
        pending = marker_from(all_head, "R10_PENDING_IO")
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
        raise SystemExit("R10 requires Windows")
    build_result = build()
    if build_result["exit_code"] != 0 or not EXE.exists():
        raise SystemExit("R10 native build failed")
    modes = ["p05", "caller-death", "popen-before", "popen-after", "outer-job"]
    rows = [run_trial(mode) for mode in modes]
    checks = []

    def check(name, ok, evidence):
        checks.append({"name": name, "pass": bool(ok), "evidence": evidence})

    r9_manifest = R9_BASELINE / "r9_manifest.json"
    r9_trials = R9_BASELINE / "r9_trials.json"
    initial_trial = ROOT / "r10_trials_initial.json"
    first_failure_dir = ROOT / "first_run_failure"
    check("frozen_R9_manifest_matches", sha256(r9_manifest) == EXPECTED_R9_MANIFEST_SHA, sha256(r9_manifest))
    check("frozen_R9_trials_match", sha256(r9_trials) == EXPECTED_R9_TRIALS_SHA, sha256(r9_trials))
    by_mode = {r["mode"]: r for r in rows}
    p05 = by_mode["p05"].get("scenario") or {}
    check("P05_async_submit_returns_before_D_with_pending_IO_reaper_owned_UNKNOWN",
          p05.get("caller_submit_result") == 0 and p05.get("caller_submit_returned") and
          p05.get("caller_submit_return_before_D") and p05.get("ticket_state_final") == 3 and
          p05.get("caller_ticket_id") == p05.get("prewarmed_ticket_id") and p05.get("caller_ticket_id", 0) != 0 and
          p05.get("caller_submit_elapsed_us", 1e9) >= 0 and p05.get("caller_submit_elapsed_us", 1e9) <= 100000 and
          p05.get("ticket_unknown_tick_ms", 0) >= p05.get("deadline_tick_ms", 1) and
          p05.get("writer_pending_at_unknown") and p05.get("writer_done") and
          p05.get("writer_error") == 995 and p05.get("broker_exact_exit_and_job_empty"), p05)
    check("single_slot_rejects_pre_ready_busy_and_poisoned_submissions",
          p05.get("caller_pre_ready_submit_result") == 3 and p05.get("second_submit_busy_result") == 1 and
          p05.get("post_unknown_submit_result") == 2 and p05.get("slot_state_final") == 2, p05)
    check("late_success_cannot_upgrade_irrevocable_UNKNOWN",
          p05.get("late_success_attempted") and p05.get("late_success_cas_previous_state") == 3 and
          p05.get("late_success_blocked_by_unknown") and p05.get("ticket_state_final") == 3, p05)
    check("caller_death_keeps_pending_IO_owner_until_completion",
          (by_mode["caller-death"].get("scenario") or {}).get("caller_killed") and
          (by_mode["caller-death"].get("scenario") or {}).get("caller_pending_at_kill") and
          (by_mode["caller-death"].get("scenario") or {}).get("broker_alive_at_caller_terminal") and
          (by_mode["caller-death"].get("scenario") or {}).get("caller_dead_seen_by_broker") and
          (by_mode["caller-death"].get("scenario") or {}).get("writer_done") and
          (by_mode["caller-death"].get("scenario") or {}).get("writer_error") == 995 and
          (by_mode["caller-death"].get("scenario") or {}).get("broker_exact_exit_and_job_empty"),
          by_mode["caller-death"].get("scenario"))
    before = by_mode["popen-before"].get("scenario") or {}
    check("Popen_before_child_runs_in_prestarted_worker_and_ticket_is_async_UNKNOWN",
          before.get("caller_submit_result") == 0 and before.get("caller_submit_return_before_D") and
          before.get("helper_stage") == 1 and before.get("ticket_state_final") == 3 and
          before.get("worker_job_terminated") and before.get("worker_job_empty"), before)
    after = by_mode["popen-after"].get("scenario") or {}
    check("Popen_after_child_creation_is_job_fenced_and_ticket_is_async_UNKNOWN",
          after.get("caller_submit_result") == 0 and after.get("caller_submit_return_before_D") and
          after.get("helper_stage") == 3 and after.get("worker_job_active_before_kill", 0) >= 2 and
          after.get("ticket_state_final") == 3 and after.get("worker_job_terminated") and
          after.get("worker_job_empty"), after)
    outer = by_mode["outer-job"]
    waits = outer.get("process_wait_results", {})
    check("outer_Job_terminates_prestarted_process_tree",
          outer.get("pending_marker", {}).get("pending") == 1 and outer.get("terminate_returned") and
          outer.get("outer_job_active_after") == 0 and bool(waits) and
          all(v == WAIT_OBJECT_0 for v in waits.values()), outer)

    r9_baseline = json.loads(r9_trials.read_text(encoding="utf-8"))
    initial = json.loads(initial_trial.read_text(encoding="utf-8"))
    r9_rows = {x["mode"]: x.get("scenario") or {} for x in r9_baseline.get("scenarios", [])}
    trials = {
        "candidate": "R10 Windows inert one-shot asynchronous ticket API + prestarted broker/reaper",
        "status": "ASYNC_TICKET_PROTOTYPE_ONLY_G1_CLOSED",
        "platform": {"system": platform.platform(), "windows_version": list(sys.getwindowsversion()), "python": sys.version},
        "build": build_result,
        "frozen_r9_baseline": {
            "manifest_sha256": sha256(r9_manifest),
            "trials_sha256": sha256(r9_trials),
            "p05_deadline_ms": r9_rows.get("p05", {}).get("deadline_tick_ms"),
            "p05_caller_return_ms": r9_rows.get("p05", {}).get("caller_api_return_tick_ms"),
            "p05_lateness_ms": r9_rows.get("p05", {}).get("caller_return_lateness_ms"),
            "popen_before_lateness_ms": r9_rows.get("popen-before", {}).get("caller_return_lateness_ms"),
            "popen_after_lateness_ms": r9_rows.get("popen-after", {}).get("caller_return_lateness_ms"),
            "status": "R9 final P05 and both Popen caller returns were 3 ms late at D=1200ms"
        },
        "preserved_first_r10_failure": {
            "trials_sha256": sha256(initial_trial),
            "source_sha256": sha256(first_failure_dir / "r10_custodian.cpp"),
            "binary_sha256": sha256(first_failure_dir / "r10_custodian.exe"),
            "runner_sha256": sha256(first_failure_dir / "run_r10_trials.py"),
            "failed_checks": initial.get("failed_checks", []),
            "classification": "first full-run assertion mismatch: harness used submit_result key while JSON field was caller_submit_result; native trial data showed async submit success",
        },
        "scenarios": rows,
        "checks": checks,
        "failed_checks": [x for x in checks if not x["pass"]],
        "scope": [
            "Only inert local Windows processes and a local named pipe. No SCM service or production/runtime integration.",
            "Before READY, the one-shot request kind, D-capable shared state, caller Job, broker process, connected pipe, OVERLAPPED/event/buffer, worker Job, and worker process are prepared. Admission remains disabled until the harness opens the READY slot.",
            "The request submit API only reads admission and performs one atomic CAS on the preallocated one-slot mailbox. The API returns a ticket immediately; poll reads ticketState and does not change it. A second submit is BUSY; after reaper UNKNOWN the slot is POISONED and further submit is rejected.",
            "The broker/reaper process owns ticket transitions. It writes UNKNOWN at the first scheduled observation at/after absolute monotonic D, poisons the slot and requests I/O cancellation. The measured transition lateness is recorded; this prototype does not claim Windows wall-clock scheduling guarantees.",
            "The late-success case is an inert CAS injection by the broker after D. It verifies state-machine irreversibility, not a real provider or external completion source.",
            "P05 uses an actual pending 2 MiB overlapped local pipe write. Broker owns pipe/OVERLAPPED/event/buffer after caller return and after caller death; it cancels, waits for completion, holds 100ms after event, and calls GetOverlappedResult.",
            "Popen before/after probes block a prestarted Python helper around Popen. The post case creates an inert child before blocking and checks Job membership. These are not true CreateProcessW syscall hangs.",
            "No P14 blocking TerminateJobObject/QueryInformationJobObject/CancelIoEx/CloseHandle failure was injected. A higher custodian for a wedged broker/reaper remains unproven.",
            "The launcher and prewarm Win32 setup occur before request D; this is not a whole-command/startup deadline. No CTP/native/provider, credentials, private config, network, default preflight, or SCM was used.",
        ],
        "decision": "R10 demonstrates an asynchronous single-slot state-machine prototype only; G1 remains closed."
    }
    TRIALS.write_text(json.dumps(trials, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    p05 = by_mode["p05"].get("scenario") or {}
    death = by_mode["caller-death"].get("scenario") or {}
    before = by_mode["popen-before"].get("scenario") or {}
    after = by_mode["popen-after"].get("scenario") or {}
    outer = by_mode["outer-job"]
    findings = [
        "# R10 Windows inert asynchronous ticket prototype",
        "",
        "Status: AUTHOR PROTOTYPE ONLY / G1 CLOSED. This is not a Windows service, production route, or OS real-time guarantee.",
        "",
        f"R9 baseline manifest `{sha256(r9_manifest)}` and trials `{sha256(r9_trials)}` are frozen copies. R9 final recorded P05 and both Popen wrapper caller returns at D+3 ms; the R10 request API returns on mailbox publication and leaves outcome polling to the caller.",
        "",
        f"The first R10 full run is preserved in `r10_trials_initial.json` (SHA `{sha256(initial_trial)}`) with its exact source, binary, build log, and runner under `first_run_failure/`. Its sole failed check was a harness key mismatch (`submit_result` vs the emitted `caller_submit_result`); this was not treated as an implementation pass or discarded. The final rerun corrects the assertion and retains all observed rows.",
        "",
        "## Protocol",
        "",
        "The single-slot mailbox is preconfigured before READY. Admission starts disabled; a pre-READY submit returns NOT_READY. An accepted submit is one atomic slot CAS, with no request-time process creation, pipe setup, queue lock, or I/O. A second submit returns BUSY. `poll(ticket)` is an atomic read only. The separate prestarted broker/reaper transitions the ticket to UNKNOWN at its first scheduled observation at or after one absolute monotonic D and poisons the slot. This is an asynchronous API model; it does not promise an OS scheduling deadline.",
        "",
        f"In P05, D tick `{p05.get('deadline_tick_ms')}`, submit result `{p05.get('caller_submit_result')}`, observed submit API duration `{p05.get('caller_submit_elapsed_us')} µs`, ticket UNKNOWN tick `{p05.get('ticket_unknown_tick_ms')}` (reaper lateness `{p05.get('reaper_unknown_lateness_ms')} ms`). Pending overlapped I/O at UNKNOWN `{p05.get('writer_pending_at_unknown')}`; final completion error `{p05.get('writer_error')}`; caller poll observed `{p05.get('caller_poll_final_state')}`. The late success CAS saw state `{p05.get('late_success_cas_previous_state')}` and did not change final state `{p05.get('ticket_state_final')}`. Busy submit `{p05.get('second_submit_busy_result')}`, poisoned submit `{p05.get('post_unknown_submit_result')}`.",
        "",
        f"Caller-death trial: caller killed `{death.get('caller_killed')}` with pending I/O `{death.get('caller_pending_at_kill')}`; broker alive at caller terminal `{death.get('broker_alive_at_caller_terminal')}`, broker saw death `{death.get('caller_dead_seen_by_broker')}`, final ticket state `{death.get('ticket_state_final')}`, and writer completion error `{death.get('writer_error')}`.",
        "",
        f"Popen-before stage `{before.get('helper_stage')}` and Popen-after stage `{after.get('helper_stage')}` are wrapper-only stalls. The after case observed worker Job active count `{after.get('worker_job_active_before_kill')}` before Job termination; both were fenced to empty. Outer Job test active processes `{outer.get('outer_job_active_before')}` → `{outer.get('outer_job_active_after')}`; all observed process handles signaled.",
        "",
        "## Limits",
        "",
        "UNKNOWN transition timing is recorded but can be late if the broker/reaper is not scheduled. The late-success attempt is an inert CAS injection, not an external result. P02/P03 do not inject true CreateProcessW hangs; P14 is absent; no higher custodian proves caller behavior if the reaper wedges. Launcher and synchronous prewarm/setup are outside D. No SCM, CTP, provider, credentials, private config, network, or default route was used.",
        "",
        "Disposition: G1 CLOSED; R10 is local author evidence only.",
    ]
    FINDINGS.write_text("\n".join(findings) + "\n", encoding="utf-8")

    payload_names = [
        "r10_custodian.cpp", "r10_custodian.exe", "r10_custodian.obj", "r10_sacrificial_popen.py",
        "run_r10_trials.py", "r10_build.bat", "r10_build.log", "r10_trials.json", "R10_FINDINGS.md",
        "r10_trials_initial.json", "first_run_failure/r10_custodian.cpp", "first_run_failure/r10_custodian.exe",
        "first_run_failure/r10_custodian.obj", "first_run_failure/r10_sacrificial_popen.py",
        "first_run_failure/run_r10_trials.py", "first_run_failure/r10_build.bat", "first_run_failure/r10_build.log",
        "r9_frozen_baseline/r9_manifest.json", "r9_frozen_baseline/r9_receipt.json",
        "r9_frozen_baseline/r9_trials.json", "r9_frozen_baseline/r9_trials_initial.json",
        "r9_frozen_baseline/r9_custodian.cpp", "r9_frozen_baseline/r9_sacrificial_popen.py",
    ]
    manifest = {
        "candidate": trials["candidate"], "status": trials["status"],
        "payload_sha256": {n: sha256(ROOT / n) for n in payload_names},
        "checks": checks, "failed_checks": trials["failed_checks"], "decision": trials["decision"],
        "frozen_r9_manifest_sha256": sha256(r9_manifest), "frozen_r9_trials_sha256": sha256(r9_trials),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_hash = sha256(MANIFEST)
    (ROOT / "r10_manifest.sha256").write_text(f"{manifest_hash}  r10_manifest.json\n", encoding="ascii")
    receipt = {
        "manifest": "r10_manifest.json", "manifest_sha256": manifest_hash,
        "trials_sha256": sha256(TRIALS), "source_sha256": sha256(ROOT / "r10_custodian.cpp"),
        "status": trials["status"], "no_provider_or_credentials": True, "no_repo_changes": True,
        "decision": trials["decision"]
    }
    RECEIPT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    receipt_hash = sha256(RECEIPT)
    (ROOT / "r10_receipt.sha256").write_text(f"{receipt_hash}  r10_receipt.json\n", encoding="ascii")
    print(json.dumps({
        "manifest_sha256": manifest_hash, "receipt_sha256": receipt_hash,
        "source_sha256": sha256(ROOT / "r10_custodian.cpp"), "trials_sha256": sha256(TRIALS),
        "checks": len(checks), "failed_checks": len(trials["failed_checks"]), "decision": trials["decision"]
    }, indent=2))


if __name__ == "__main__":
    main()
