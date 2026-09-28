import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

import run_r10_trials_r10_frozen as r10

ROOT = Path(__file__).resolve().parent
EXE = ROOT / "r10_custodian.exe"
TRIALS = ROOT / "r10_r1_trials.json"


def read_line_until(proc, marker: bytes, timeout_s: float) -> bytes:
    import msvcrt

    fd = proc.stdout.fileno()
    read_handle = r10.HANDLE(msvcrt.get_osfhandle(fd))
    out = bytearray()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        available = r10.DWORD()
        ok = r10.K32.PeekNamedPipe(read_handle, None, 0, None, r10.ctypes.byref(available), None)
        if ok and available.value:
            out.extend(os.read(fd, min(int(available.value), 65536)))
            if marker in out:
                return bytes(out)
            continue
        if proc.poll() is not None:
            break
        time.sleep(0.002)
    return bytes(out)


def stop_outer(proc, outer, code):
    remote = outer.get("external_job_handle")
    before, before_error = r10.job_active(remote) if remote else (None, 6)
    start = time.monotonic_ns()
    ok = bool(remote and r10.K32.TerminateJobObject(r10.HANDLE(remote), code))
    error = 0 if ok else (r10.ctypes.get_last_error() if remote else 6)
    after = None
    end = time.monotonic() + 3.0
    while remote and time.monotonic() < end:
        after, _ = r10.job_active(remote)
        if after == 0:
            break
        time.sleep(0.005)
    try:
        proc.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2.0)
    if remote:
        r10.K32.CloseHandle(r10.HANDLE(remote))
    return {"active_before": before, "query_error_before": before_error,
            "terminate_returned": ok, "terminate_error": error, "active_after": after,
            "elapsed_ns": time.monotonic_ns() - start}


def run_trial(mode: str, stuck_expected: bool = False):
    go = r10.create_go_event()
    startup = subprocess.STARTUPINFO()
    startup.lpAttributeList = {"handle_list": [go]}
    launch_start = time.monotonic_ns()
    proc = subprocess.Popen([str(EXE), "--outer-run", mode, str(os.getpid()), str(go), sys.executable],
                            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0,
                            close_fds=True, startupinfo=startup)
    head = read_line_until(proc, b"R10_READY", 15.0).decode("utf-8", errors="replace")
    outer = r10.marker_from(head, "R10_OUTER_JOB_CONTROL_READY")
    ready = r10.marker_from(head, "R10_READY")
    if not ready:
        cleanup = stop_outer(proc, outer, 0xE9FF1001) if outer.get("external_job_handle") else None
        r10.K32.CloseHandle(r10.HANDLE(go))
        return {"mode": mode, "ready": False, "head": head, "cleanup": cleanup}
    ready_ns = time.monotonic_ns() - launch_start
    if not r10.K32.SetEvent(r10.HANDLE(go)):
        raise OSError(r10.ctypes.get_last_error(), "SetEvent(go)")
    decision_output = read_line_until(proc, b"}\n", 9.0).decode("utf-8", errors="replace")
    full = head + decision_output
    json_line = next((line for line in reversed(full.splitlines()) if line.startswith("{\"mode\":")), "")
    scenario = json.loads(json_line) if json_line else None
    if scenario is None:
        cleanup = stop_outer(proc, outer, 0xE9FF1002)
        r10.K32.CloseHandle(r10.HANDLE(go))
        return {"mode": mode, "ready": True, "decision_line_received": False,
                "raw_output": full, "outer_kill": cleanup}
    active_at_report, error_at_report = r10.job_active(outer.get("external_job_handle"))
    if stuck_expected:
        cleanup = stop_outer(proc, outer, 0xE9FF1003)
        exit_code = proc.returncode
    else:
        try:
            proc.wait(timeout=5.0)
            exit_code = proc.returncode
            cleanup = None
        except subprocess.TimeoutExpired:
            cleanup = stop_outer(proc, outer, 0xE9FF1004)
            exit_code = proc.returncode
    if outer.get("external_job_handle"):
        r10.K32.CloseHandle(r10.HANDLE(outer["external_job_handle"]))
    r10.K32.CloseHandle(r10.HANDLE(go))
    qpf = scenario.get("qpc_frequency", 0)
    terminal = scenario.get("caller_terminal_qpc", 0)
    deadline = scenario.get("request_deadline_qpc", 0)
    return {"mode": mode, "ready": ready, "ready_elapsed_ns_before_request": ready_ns,
            "scenario": scenario, "launcher_exit_code": exit_code,
            "outer_job_active_at_decision_report": active_at_report,
            "outer_job_query_error_at_report": error_at_report,
            "caller_terminal_lateness_us": ((terminal - deadline) * 1e6 / qpf)
            if terminal and deadline and qpf else None,
            "post_decision_outer_kill": cleanup, "raw_output": full}


def run_admission_probe():
    p = subprocess.run([str(EXE), "--admission-probe"], cwd=ROOT, capture_output=True,
                       text=True, timeout=5.0)
    rows = [json.loads(line) for line in p.stdout.splitlines() if line.startswith("{")]
    return {"exit_code": p.returncode, "stdout": p.stdout, "stderr": p.stderr, "cases": rows}


def main():
    if os.name != "nt":
        raise SystemExit("R10-r1 requires Windows")
    build = r10.build()
    if build["exit_code"] != 0:
        raise SystemExit("R10-r1 native build failed; see r10_build.log")
    admission = run_admission_probe()
    modes = []
    for mode, stuck, trial_id in [
        ("p05", False, "p05-final"),
        ("caller-death", False, "caller-death-final"),
        ("late-admission", False, "late-admission-1"),
        ("cancel-stall", True, "cancel-stall-final"),
        ("cancel-stall-caller-death", True, "cancel-stall-caller-death-final"),
        ("join-stall", True, "join-stall-final"),
        ("late-admission", False, "late-admission-repeat-1"),
    ]:
        row = run_trial(mode, stuck_expected=stuck)
        row["trial_id"] = trial_id
        modes.append(row)
    checks = []

    def check(name, ok, evidence):
        checks.append({"name": name, "pass": bool(ok), "evidence": evidence})

    cases = {x["name"]: x for x in admission["cases"]}
    check("QPC_D_minus_epsilon_accepts", cases.get("D_minus_epsilon", {}).get("result") == 0 and
          cases.get("D_minus_epsilon", {}).get("slot_state") == 2, cases.get("D_minus_epsilon"))
    check("QPC_D_exact_rejects_before_slot_CAS", cases.get("D_exact", {}).get("result") == 4 and
          cases.get("D_exact", {}).get("slot_state") == 0 and cases.get("D_exact", {}).get("clock_samples_consumed") == 1,
          cases.get("D_exact"))
    check("QPC_D_plus_epsilon_rejects_before_slot_CAS", cases.get("D_plus_epsilon", {}).get("result") == 4 and
          cases.get("D_plus_epsilon", {}).get("slot_state") == 0, cases.get("D_plus_epsilon"))
    check("claim_to_D_race_poisoned", cases.get("race_claim_to_D", {}).get("result") == 4 and
          cases.get("race_claim_to_D", {}).get("slot_state") == 3, cases.get("race_claim_to_D"))
    check("publish_to_D_or_later_race_irrevocably_unknown", all(
          cases.get(n, {}).get("result") == 4 and cases.get(n, {}).get("slot_state") == 3 and
          cases.get(n, {}).get("ticket_state") == 3 for n in ("race_publish_to_D", "race_publish_after_D")),
          [cases.get("race_publish_to_D"), cases.get("race_publish_after_D")])
    check("concurrent_one_slot_has_one_winner", cases.get("concurrent_one_slot", {}).get("threads_created") == 8 and
          cases.get("concurrent_one_slot", {}).get("accepted") == 1 and
          cases.get("concurrent_one_slot", {}).get("busy") == 7 and
          cases.get("concurrent_one_slot", {}).get("other") == 0, cases.get("concurrent_one_slot"))
    check("poisoned_slot_rejects_reuse_before_D", cases.get("poisoned_slot_no_reuse", {}).get("result") == 2 and
          cases.get("poisoned_slot_no_reuse", {}).get("slot_state") == 3 and
          cases.get("poisoned_slot_no_reuse", {}).get("ticket_state") == 3 and
          cases.get("poisoned_slot_no_reuse", {}).get("ticket_id") == 0,
          cases.get("poisoned_slot_no_reuse"))
    by_mode = {x["mode"]: x for x in modes}
    p05 = by_mode["p05"].get("scenario") or {}
    check("accepted_submit_samples_before_same_QPC_D", p05.get("caller_submit_result") == 0 and
          p05.get("caller_submit_start_qpc", 0) < p05.get("request_deadline_qpc", 1) and
          p05.get("caller_submit_return_qpc", 0) < p05.get("request_deadline_qpc", 1),
          {k: p05.get(k) for k in ("caller_submit_result", "caller_submit_start_qpc", "caller_submit_return_qpc", "request_deadline_qpc")})
    check("baseline_P05_unknown_and_I/O_cleanup_exact", p05.get("caller_submit_result") == 0 and
          p05.get("ticket_state_final") == 3 and p05.get("caller_poll_final_state") == 3 and
          p05.get("writer_pending_at_unknown") and p05.get("writer_done") and
          p05.get("broker_exact_exit_and_job_empty") and not p05.get("broker_controls_retained_by_supervisor"), p05)
    check("late_success_and_post_deadline_submit_cannot_reuse_poisoned_ticket",
          p05.get("slot_state_final") == 3 and p05.get("post_unknown_submit_result") == 4 and
          p05.get("late_success_attempted") and p05.get("late_success_blocked_by_unknown") and
          p05.get("late_success_cas_previous_state") == 3 and p05.get("ticket_state_final") == 3, p05)
    death = by_mode["caller-death"].get("scenario") or {}
    check("normal_caller_death_keeps_pending_IO_owner_until_completion", death.get("caller_killed") and
          death.get("caller_pending_at_kill") and death.get("caller_dead_seen_by_broker") and
          death.get("writer_done") and death.get("broker_exact_exit_and_job_empty"), death)
    late_rows = [x for x in modes if x["mode"] == "late-admission"]
    late_facts = [x.get("scenario") or {} for x in late_rows]
    check("live_late_admission_rejected_without_ticket_or_worker_on_repeat", len(late_facts) == 2 and all(
          s.get("caller_submit_result") == 4 and
          s.get("caller_submit_start_qpc", 0) >= s.get("request_deadline_qpc", 1) and
          s.get("caller_ticket_id") == 0 and s.get("slot_state_final") == 0 and
          s.get("ticket_state_final") == 0 and not s.get("writer_submitted") and
          s.get("broker_exact_exit_and_job_empty") for s in late_facts),
          [{"trial_id": x.get("trial_id"), **(x.get("scenario") or {})} for x in late_rows])
    cancel = by_mode["cancel-stall"].get("scenario") or {}
    check("injected_cancel_failure_returns_caller_UNKNOWN_and_retains_pending_IO_controls", cancel.get("ticket_state_final") == 3 and
          cancel.get("caller_poll_final_state") == 3 and cancel.get("caller_exit") == 0 and
          cancel.get("writer_pending_final") and cancel.get("writer_cancel_failure_injected") and
          cancel.get("broker_alive_at_caller_terminal") and cancel.get("broker_shutdown_incomplete") and
          cancel.get("broker_controls_retained_by_supervisor") and cancel.get("overlapped_context_retained") and
          cancel.get("broker_job_active_after", 0) > 0, cancel)
    cancel_death = by_mode["cancel-stall-caller-death"].get("scenario") or {}
    check("caller_death_with_pending_unresolved_IO_is_UNKNOWN_and_controls_retained", cancel_death.get("caller_killed") and
          cancel_death.get("caller_pending_at_kill") and cancel_death.get("caller_dead_seen_by_broker") and
          cancel_death.get("ticket_state_final") == 3 and cancel_death.get("writer_pending_final") and
          cancel_death.get("broker_shutdown_incomplete") and cancel_death.get("broker_controls_retained_by_supervisor"), cancel_death)
    join = by_mode["join-stall"].get("scenario") or {}
    check("bounded_broker_join_timeout_does_not_block_caller_or_release_controls", join.get("ticket_state_final") == 3 and
          join.get("caller_poll_final_state") == 3 and join.get("caller_exit") == 0 and
          join.get("writer_done") and not join.get("writer_pending_final") and join.get("writer_join_injected") and
          join.get("broker_join_timed_out") and join.get("broker_shutdown_incomplete") and
          join.get("broker_controls_retained_by_supervisor") and join.get("broker_job_active_after", 0) > 0, join)

    trials = {
        "candidate": "R10-r1 QPC admission boundary + retained-I/O/bounded-join negative prototype",
        "status": "AUTHOR_INERT_WINDOWS_PROTOTYPE_G1_CLOSED",
        "platform": {"system": platform.platform(), "windows_version": list(sys.getwindowsversion()), "python": sys.version},
        "build": build, "admission_probe": admission, "scenarios": modes, "checks": checks,
        "failed_checks": [x for x in checks if not x["pass"]],
        "r10_frozen_source_sha256": r10.sha256(ROOT / "R10_BASELINE" / "r10_custodian.cpp"),
        "r10_frozen_trials_sha256": r10.sha256(ROOT / "R10_BASELINE" / "r10_trials.json"),
        "scope": [
            "Only inert local Windows processes, shared memory, Jobs, and a local named pipe were used.",
            "The same absolute QueryPerformanceCounter deadline D is checked before slot CAS and after each admission publication phase; the broker checks the same D before request transitions and worker start.",
            "At D and D+epsilon SubmitTicket rejects before touching the slot. If a claim/publication race crosses D, the slot is poisoned and any ticket is irrevocably UNKNOWN.",
            "The QPC checks do not prove a hard caller-return time guarantee under OS preemption or a blocking syscall. Whole-command hard D remains unproven.",
            "P05 exercises pending 2 MiB local named-pipe overlapped I/O. Cancellation failure is simulated by skipping CancelIoEx; this is not a real CancelIoEx kernel/API failure.",
            "The unresolved-I/O writer keeps the issuing thread, OVERLAPPED, event, buffer, and pipe handles alive. The broker uses bounded writer waits and retains controls if the writer is still live/pending; the supervisor emits the caller decision and retains its own controls unless exact broker exit plus Job-empty plus no pending I/O are observed.",
            "The caller-death cancellation-stall case proves the separate caller can die while the broker remains owner; external test Job termination is fixture teardown after the recorded UNKNOWN decision, not successful cleanup evidence.",
            "P02/P03 true CreateProcessW kernel hangs, P14 native termination/query/close failure, higher-custodian failure, SCM/service lifecycle, and whole-command startup/setup deadline are not tested or proved.",
            "No CTP/native provider, credentials, private config, network, SDK, or default preflight was connected. G1 and ordinary preflight remain closed."
        ],
        "decision": "R10-r1 closes two local prototype gaps only; it is not whole-command G1 acceptance."
    }
    TRIALS.write_text(json.dumps(trials, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"trials": str(TRIALS), "checks": len(checks),
                      "failed_checks": len(trials["failed_checks"]), "decision": trials["decision"]}, indent=2))
    if trials["failed_checks"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
