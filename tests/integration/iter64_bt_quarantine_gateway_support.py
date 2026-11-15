"""Private synthetic Gateway process for the iteration 64.09 test.

Only operation names are recorded at this process's listener.  Provider,
keys, account, and journal are synthetic and never belong to an existing host.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import sys
import threading
import time


SDK_ROOT = Path(__file__).resolve().parents[3] / "bt_api_py"


def _report(messages, write_metadata, write_event, lifecycle, state, pid):
    try:
        while True:
            message = messages.get()
            if message[0] == "ready":
                write_metadata(message[2])
                write_event("ready")
            elif message[0] == "error":
                lifecycle["fixture_error"] = True
                write_event("error")
            elif message[0] == "cleanup_uncertain":
                lifecycle["fixture_error"] = True
                return
            elif message[0] == "probe":
                write_event("reporter_probe")
            elif message[0] == "closed":
                if len(message) != 2 or message[1] != pid:
                    state["failed"] = True
                else:
                    state["closed_seen"] = True
                return
    except BaseException:
        state["failed"] = True


def _run_child(main_func, config_path, report_failure, retain):
    try:
        main_func(config_path)
    except BaseException:
        try:
            report_failure()
        finally:
            retain()


def _retain_forever():
    while True:
        try:
            threading.Event().wait()
        except BaseException:
            continue


def _write_protected_key(writer, path, key, *, secret):
    # Use the SDK's exclusive, short-write-aware secret path for public keys
    # as well, so every synthetic key file has the same restrictive mode.
    result = writer(path, key, secret=True)
    if path.stat().st_mode & 0o777 != 0o600:
        raise RuntimeError("synthetic_key_permissions")
    return result


def main(config_path: str) -> None:
    os.umask(0o077)
    sys.path.insert(0, str(SDK_ROOT))
    from bt_api_py.gateway_direct_owner import GatewayDirectOwner
    from bt_api_py.service_host import ServiceHost
    import tests.integration.test_iter64_risk_service_process as fixture
    from tests.integration.test_iter64_risk_service_process import (
        CONTROL, RISK, STRATEGY, _gateway, _risk_files,
    )

    data = json.loads(Path(config_path).read_text(encoding="utf-8"))
    keys = {name: tuple(part.encode("ascii") for part in pair)
            for name, pair in data["keys"].items()}
    publics = {keys["strategy"][0]: STRATEGY.principal_ref,
               keys["risk_delegate"][0]: RISK.principal_ref,
               keys["risk_control"][0]: CONTROL.principal_ref}
    sdk_write_key = fixture._write_key
    fixture._write_key = lambda path, key, *, secret: _write_protected_key(
        sdk_write_key, path, key, secret=secret
    )
    risk_path = _risk_files(Path(data["risk_root"]), keys, data["gateway_endpoint"],
                            data["risk_endpoint"])
    policy_path = Path(data["risk_root"]) / "risk_policy.yaml"
    policy = policy_path.read_text(encoding="utf-8")
    assert policy.count("self_trade: {enabled: false") == 1
    policy_path.write_text(policy.replace("self_trade: {enabled: false",
                                          "self_trade: {enabled: true"), encoding="utf-8")
    config = json.loads(risk_path.read_text(encoding="utf-8"))
    config["principals"][1]["operations"].append("risk.policy.read")
    risk_path.write_text(json.dumps(config), encoding="utf-8")

    events = Path(data["events"])
    operations = Path(data["operations"])
    metadata = Path(data["metadata"])
    messages, controls = queue.Queue(), queue.Queue()
    recording = threading.Event()
    max_operations = 2048
    operation_count = 0
    recording_failed = threading.Event()
    control_failed = threading.Event()
    lifecycle = {"host": False, "owner": False, "fixture_error": False}
    reporter_state = {"failed": False, "closed_seen": False}
    original_dispatch = ServiceHost._dispatch_request
    original_host_close = ServiceHost.close
    original_owner_close = GatewayDirectOwner.close

    def host_close(host):
        result = original_host_close(host)
        lifecycle["host"] = host.state == "closed" and not host._last_cleanup_failures
        if not lifecycle["host"]:
            raise RuntimeError("synthetic_host_close_uncertain")
        return result

    def owner_close(owner, timeout_seconds):
        result = original_owner_close(owner, timeout_seconds)
        deadline = time.monotonic() + 5
        status = owner.status()
        while status.thread_alive and time.monotonic() < deadline:
            time.sleep(0.01)
            status = owner.status()
        lifecycle["owner"] = (result is True and owner.closed is True
                              and status.thread_alive is False and status.running is False
                              and status.failure_category is None)
        if not lifecycle["owner"]:
            raise RuntimeError("synthetic_owner_close_uncertain")
        return result

    ServiceHost.close = host_close
    GatewayDirectOwner.close = owner_close

    def recording_dispatch(host, principal, request):
        nonlocal operation_count
        if recording.is_set():
            try:
                operation = request.header.operation
                if type(operation) is not str or len(operation) > 128 or not operation.isprintable():
                    recording_failed.set()
                else:
                    operation_count += 1
                    with operations.open("a", encoding="utf-8") as out:
                        if operation_count <= max_operations:
                            out.write(json.dumps({"operation": operation}) + "\n")
                        elif operation_count == max_operations + 1:
                            out.write(json.dumps({"overflow": True}) + "\n")
            except Exception:
                recording_failed.set()
        return original_dispatch(host, principal, request)

    ServiceHost._dispatch_request = recording_dispatch

    def write_metadata(journal_id):
        descriptor = os.open(metadata, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as out:
            json.dump({"journal_id": journal_id, "risk_config": str(risk_path)}, out)

    def write_event(kind):
        if kind == "reporter_probe" and (recording_failed.is_set() or control_failed.is_set()):
            kind = "error"
        with events.open("a", encoding="utf-8") as out:
            out.write(json.dumps({"event": kind, "pid": os.getpid()}) + "\n")

    def receive_control() -> None:
        try:
            for line in sys.stdin:
                if line.strip() == "observe":
                    recording.set()
                    with events.open("a", encoding="utf-8") as out:
                        out.write(json.dumps({"event": "observing", "pid": os.getpid()}) + "\n")
                elif line.strip() == "probe":
                    messages.put(("probe",))
                elif line.strip() == "stop":
                    controls.put("stop")
                    return
        except BaseException:
            control_failed.set()

    reporter = threading.Thread(target=_report, args=(messages, write_metadata, write_event,
                                                       lifecycle, reporter_state, os.getpid()), daemon=True)
    reporter.start()
    threading.Thread(target=receive_control, daemon=True).start()
    try:
        try:
            _gateway(data["gateway_root"], data["gateway_endpoint"], keys["gateway_server"],
                     publics, messages, controls)
        except BaseException:
            lifecycle["fixture_error"] = True
        reporter.join(timeout=5)
        verified = (not reporter.is_alive() and lifecycle["host"] and lifecycle["owner"]
                    and reporter_state["closed_seen"] and not reporter_state["failed"]
                    and not lifecycle["fixture_error"] and not recording_failed.is_set()
                    and not control_failed.is_set())
        with events.open("a", encoding="utf-8") as out:
            for step in ("host", "owner"):
                out.write(json.dumps({"event": "cleanup_step", "step": step,
                                      "code": "ok" if lifecycle[step] else "uncertain",
                                      "pid": os.getpid()}) + "\n")
            out.write(json.dumps({"event": "closed" if verified else "cleanup_uncertain",
                                  "pid": os.getpid()}) + "\n")
        if not verified:
            threading.Event().wait()
    finally:
        ServiceHost._dispatch_request = original_dispatch
        ServiceHost.close = original_host_close
        GatewayDirectOwner.close = original_owner_close


if __name__ == "__main__" and len(sys.argv) == 2:
    _run_child(main, sys.argv[1],
               lambda: print("synthetic_child_failure", file=sys.stderr, flush=True),
               _retain_forever)
