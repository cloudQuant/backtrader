"""Root-only installed-consumer CTP no-Join loopback gate; never run before review/pinning."""
from __future__ import annotations

import base64
import csv
import dataclasses
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import socket
import sys
import threading
import time

CONSUMER_ROOT = Path(r"D:/temp/i51-ctp-nojoin-consumer-20261027-r1/consumer")
CLIENT_SHA256 = "14a8f80d0ee0f14d8e57affefdaf850a255d31ff6fa478962060d7b37e8b3264"
RECORD_PINS = (
    ("bt_api_base-0.15.8.dist-info/RECORD", 15821, "6284d7236b283cbcc5599d2ad14e5ab81d83d93ee641392ef612acbe1df54dda"),
    ("bt_api_ctp-2.0.4+iteration41.i9.dist-info/RECORD", 14197, "928671c3cb7f211f2157b183e9d033e7afdddfbea153d6f4eba995e87956e8a1"),
)
CLIENT_BYTES = 505552
BASE_WHEEL_SHA256 = "b579a73531281d74f6e1630d447717b9f87e38bf507d82178d9ad46745017f39"
WHEEL_SHA256 = "32811ab303cd875274fc9d69ee3ca3f29d83c33d9d5217f4eadd037cb07123d7"
SOURCE_COMMIT = "574cd2dd495a3c675d7cd23fcbf23a797a08c04d"
FLOW_ROOT = Path(r"D:/temp/i51-ctp-nojoin-client-20261027-r1")
FRONT = "tcp://127.0.0.1:1"
TIMEOUT = 20.0
OBSERVE = 0.75

# Strong Python references remain inspectable in the interactive -i host.
GATE_REFS = []
RESULT = {
    "schema": "i51_ctp_nojoin_installed_client_gate_v1",
    "status": "NOT_RUN",
    "acceptance_level": "LOCAL_LOOPBACK_NATIVE_LIFECYCLE_ONLY",
    "provider_or_account_acceptance": "NOT_CLAIMED",
    "phases": {},
    "clients": [],
}


class GateFailure(RuntimeError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def verify_install():
    root = CONSUMER_ROOT.resolve()
    if Path(sys.prefix).resolve() != root:
        raise GateFailure("consumer_interpreter_root_mismatch")
    site = root / "Lib" / "site-packages"
    source = site / "bt_api_ctp" / "ctp" / "client.py"
    if not source.is_file() or source.stat().st_size != CLIENT_BYTES or sha256(source) != CLIENT_SHA256:
        raise GateFailure("installed_client_source_hash_mismatch")
    records = []
    for relative, expected_size, expected_hash in RECORD_PINS:
        rel = PurePosixPath(relative)
        if rel.is_absolute() or ".." in rel.parts:
            raise GateFailure("record_relative_path_invalid")
        path = site.joinpath(*rel.parts)
        if not path.is_file() or path.stat().st_size != expected_size or sha256(path) != expected_hash:
            raise GateFailure("installed_record_hash_mismatch")
        records.append(path)
    matched = False
    with records[1].open("r", encoding="utf-8", newline="") as stream:
        for row in csv.reader(stream):
            if len(row) == 3 and row[0] == "bt_api_ctp/ctp/client.py":
                encoded = base64.urlsafe_b64encode(hashlib.sha256(source.read_bytes()).digest())
                matched = (
                    row[1] == "sha256=" + encoded.decode("ascii").rstrip("=")
                    and row[2] == str(CLIENT_BYTES)
                )
                break
    if matched:
        return root, source.resolve()
    raise GateFailure("record_client_row_mismatch")


def refused_loopback():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(5.0)
        code = sock.connect_ex(("127.0.0.1", 1))
    finally:
        sock.close()
    if code not in {errno.ECONNREFUSED, getattr(errno, "WSAECONNREFUSED", 10061)}:
        raise GateFailure("fixed_loopback_front_not_confirmed_refused")
    return code


def bounded(label, function):
    box, done = {}, threading.Event()
    started_at = time.monotonic()

    def invoke():
        try:
            box["value"] = function()
        except BaseException as exc:
            box["exception"] = exc
            GATE_REFS.append(exc)
        finally:
            done.set()

    thread = threading.Thread(target=invoke, name="i51-ctp-" + label, daemon=True)
    GATE_REFS.extend((box, done, thread))
    try:
        thread.start()
    except BaseException as exc:
        box["exception"] = exc
        GATE_REFS.append(exc)
        return {"done": False, "alive": False, "elapsed_seconds": time.monotonic() - started_at, "box": box}
    completed = done.wait(TIMEOUT)
    if completed:
        deadline = time.monotonic() + 0.5
        while thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.005)
    return {
        "done": completed,
        "alive": thread.is_alive(),
        "elapsed_seconds": time.monotonic() - started_at,
        "box": box,
    }


def snapshot(client, module, lock_name):
    lock = getattr(client, lock_name)
    if not lock.acquire(timeout=1.0):
        return {"lock_acquired": False}, None
    try:
        api = getattr(client, "_api", None)
        if api is None:
            api = getattr(client, "_startup_native_api", None)
        if api is None:
            api = getattr(client, "_last_stopped_native_api", None)
        spi = getattr(client, "_spi", None)
        join_thread = getattr(client, "_thread", None)
        policies = getattr(client, "_join_observer_policy_by_api_id", {})
        policy = policies.get(id(api)) if api is not None else None
        out = {
            "lock_acquired": True,
            "api_present": api is not None,
            "spi_present": spi is not None,
            "join_policy_false_for_exact_api": bool(policy is not None and policy[0] is api and policy[1] is False),
            "join_observer_thread_present": join_thread is not None,
            "join_observer_thread_count": int(join_thread is not None),
            "join_observer_thread_alive": bool(join_thread and join_thread.is_alive()),
            "join_active": bool(getattr(client, "_join_active", False)),
            "deferred_owner_cleanup_pending": None,
            "active_api_detached": api is None or getattr(client, "_api", None) is not api,
            "connection_generation": int(getattr(client, "_connection_generation", 0)),
            "connected": bool(getattr(client, "_connected", False)),
            "api_ref": api,
            "spi_ref": spi,
        }
        if api is not None:
            GATE_REFS.append(api)
        if spi is not None:
            GATE_REFS.append(spi)
        if join_thread is not None:
            GATE_REFS.append(join_thread)
    finally:
        lock.release()
    out["api_release_confirmed"] = bool(
        api is not None and module._ctp_native_api_release_confirmed(api)
    )
    out["deferred_owner_cleanup_pending"] = bool(
        api is not None and module._ctp_native_deferred_owner_cleanup_pending(client, api, lock)
    )
    return out, api


def receipt_fields(receipt):
    out = {"type": type(receipt).__name__, "complete": False}
    if dataclasses.is_dataclass(receipt):
        for field in dataclasses.fields(receipt):
            if field.name.startswith("_"):
                continue
            value = getattr(receipt, field.name)
            if type(value) in (str, int, float, bool, type(None)):
                out[field.name] = value
        out["complete"] = bool(getattr(receipt, "complete", False))
    return out


def exercise(label, client, module, trader=False):
    GATE_REFS.append(client)
    lock_name = "_query_state_lock" if trader else "_state_lock"
    start = bounded(label + "-start", lambda: client.start(block=False, join_observer=False))
    first, api_before = snapshot(client, module, lock_name)
    time.sleep(OBSERVE)
    observed, api_observed = snapshot(client, module, lock_name)
    api_expected = api_before if api_before is not None else api_observed
    start_error = start["box"].get("exception")
    if not start["done"] or start["alive"]:
        return {
            "client": label,
            "start_completed": start["done"],
            "start_worker_alive": start["alive"],
            "start_elapsed_seconds": start["elapsed_seconds"],
            "start_exception_type": type(start_error).__name__ if start_error is not None else None,
            "callback_observation_seconds": OBSERVE,
            "before_stop": {k: v for k, v in observed.items() if not k.endswith("_ref")},
            "typed_stop_method_called_once": False,
            "stop_skipped_while_start_worker_uncertain": True,
            "passed": False,
        }
    generation = int(observed.get("connection_generation", 0))
    startup_phase = attempt_id = None
    if trader:
        try:
            attempt = client.native_startup_attempt
            GATE_REFS.append(attempt)
            startup_phase, attempt_id = attempt.phase, attempt.api_attempt_id
        except BaseException as exc:
            GATE_REFS.append(exc)
            startup_phase = "observation_error"
    method = "stop_startup_and_wait" if trader and generation == 0 else "stop_and_wait"
    stop = bounded(label + "-typed-stop", lambda: getattr(client, method)(TIMEOUT))
    receipt = stop["box"].get("value")
    if receipt is not None:
        GATE_REFS.append(receipt)
    stop_error = stop["box"].get("exception")
    if not stop["done"] or stop["alive"]:
        view = receipt_fields(receipt)
        expected_type = module.CtpNativeStartupStopReceipt if method == "stop_startup_and_wait" else module.CtpNativeStopReceipt
        return {
            "client": label,
            "start_completed": start["done"],
            "start_worker_alive": start["alive"],
            "start_elapsed_seconds": start["elapsed_seconds"],
            "start_exception_type": type(start_error).__name__ if start_error is not None else None,
            "callback_observation_seconds": OBSERVE,
            "before_stop": {k: v for k, v in observed.items() if not k.endswith("_ref")},
            "typed_stop_method_called_once": method,
            "stop_completed": stop["done"],
            "stop_worker_alive": stop["alive"],
            "typed_stop_elapsed_seconds": stop["elapsed_seconds"],
            "stop_exception_type": type(stop_error).__name__ if stop_error is not None else None,
            "receipt": view,
            "receipt_type_exact": type(receipt) is expected_type,
            "after_stop_observation_skipped_while_stop_worker_uncertain": True,
            "passed": False,
        }
    after, api_after = snapshot(client, module, lock_name)
    if api_expected is not None:
        after["api_release_confirmed"] = bool(module._ctp_native_api_release_confirmed(api_expected))
        after["deferred_owner_cleanup_pending"] = bool(
            module._ctp_native_deferred_owner_cleanup_pending(client, api_expected, getattr(client, lock_name))
        )
    view = receipt_fields(receipt)
    expected_type = module.CtpNativeStartupStopReceipt if method == "stop_startup_and_wait" else module.CtpNativeStopReceipt
    exact_type = type(receipt) is expected_type
    passed = bool(
        start["done"] and not start["alive"] and start_error is None
        and stop["done"] and not stop["alive"] and stop_error is None
        and exact_type and view.get("complete") is True
        and view.get("native_released") is True and view.get("join_required") is False
        and view.get("join_completed") is True and view.get("thread_alive") is False
        and view.get("timed_out") is False and api_expected is not None and api_after is api_expected
        and (first.get("join_policy_false_for_exact_api") is True
             or observed.get("join_policy_false_for_exact_api") is True)
        and observed.get("connection_generation") == 0
        and after.get("api_release_confirmed") is True
        and after.get("deferred_owner_cleanup_pending") is False
        and after.get("join_observer_thread_present") is False
        and after.get("join_active") is False and after.get("active_api_detached") is True
    )
    if method == "stop_startup_and_wait":
        passed = passed and view.get("outcome") == "api_created_released"
    return {
        "client": label, "start_completed": start["done"], "start_worker_alive": start["alive"],
        "start_elapsed_seconds": start["elapsed_seconds"],
        "start_exception_type": type(start_error).__name__ if start_error is not None else None,
        "callback_observation_seconds": OBSERVE, "before_stop": {k:v for k,v in observed.items() if not k.endswith("_ref")},
        "startup_phase": startup_phase, "startup_attempt_id_present": type(attempt_id) is str,
        "typed_stop_method_called_once": method, "stop_completed": stop["done"],
        "stop_worker_alive": stop["alive"], "typed_stop_elapsed_seconds": stop["elapsed_seconds"],
        "stop_exception_type": type(stop_error).__name__ if stop_error is not None else None,
        "receipt": view, "receipt_type_exact": exact_type,
        "after_stop": {k:v for k,v in after.items() if not k.endswith("_ref")}, "passed": passed,
    }


def run_gate():
    RESULT["status"] = "HOLD"
    RESULT["invocation"] = "consumer-python -I -i <this-script>"
    RESULT["artifact"] = {"consumer_root": str(CONSUMER_ROOT), "wheel_sha256": WHEEL_SHA256,
                          "base_wheel_sha256": BASE_WHEEL_SHA256, "source_commit": SOURCE_COMMIT,
                          "client_sha256": CLIENT_SHA256,
                          "client_bytes": CLIENT_BYTES,
                          "record_pins": [{"relative": r, "size_bytes": n, "sha256": h}
                                          for r, n, h in RECORD_PINS]}
    phases = RESULT["phases"]
    flow_created = False
    try:
        if FLOW_ROOT.exists():
            raise GateFailure("fresh_flow_root_already_exists")
        FLOW_ROOT.mkdir(parents=False, exist_ok=False)
        flow_created = True
        os.environ.update({"TEMP": str(FLOW_ROOT), "TMP": str(FLOW_ROOT), "TMPDIR": str(FLOW_ROOT)})
        import tempfile
        tempfile.tempdir = str(FLOW_ROOT)
        phases["fresh_flow_root_bound_before_sdk_import"] = True
        if sys.flags.isolated != 1 or sys.flags.interactive != 1:
            raise GateFailure("requires_isolated_interactive_host_before_sdk_work")
        phases["isolated_interactive_host"] = True
        _, expected_client = verify_install()
        phases["installed_record_and_source"] = "verified"
        phases["loopback_refusal_code"] = refused_loopback()
        phases["front"] = FRONT

        import bt_api_ctp.ctp.client as module
        origin = Path(module.__file__).resolve()
        if origin != expected_client or sha256(origin) != CLIENT_SHA256:
            raise GateFailure("imported_client_origin_or_hash_mismatch")
        phases["imported_client_origin"] = str(origin)
        md = module.MdClient(FRONT, "SYNTHETIC-BROKER", "SYNTHETIC-MD-USER", "SYNTHETIC-MD-PASSWORD")
        md_result = exercise("md", md, module)
        RESULT["clients"].append(md_result)
        if not md_result["passed"]:
            RESULT["status"] = "HOLD_MD_CLEANUP_OR_OBSERVATION_UNCERTAIN"
            return
        trader = module.TraderClient(FRONT, "SYNTHETIC-BROKER", "SYNTHETIC-TD-USER", "SYNTHETIC-TD-PASSWORD",
                                     app_id="SYNTHETIC-APP", auth_code="SYNTHETIC-AUTH-CODE",
                                     auto_settlement_confirm=False)
        td_result = exercise("trader", trader, module, trader=True)
        RESULT["clients"].append(td_result)
        RESULT["status"] = "PASS_LOCAL_LOOPBACK_NOJOIN_LIFECYCLE_ONLY" if td_result["passed"] else "HOLD_TRADER_CLEANUP_OR_OBSERVATION_UNCERTAIN"
    except BaseException as exc:
        GATE_REFS.append(exc)
        RESULT["status"] = "HOLD_GATE_EXCEPTION"
        RESULT["exception_type"] = type(exc).__name__
        RESULT["phase_code"] = getattr(exc, "code", "unclassified")
    finally:
        if flow_created:
            try:
                result_path = FLOW_ROOT / "result.json"
                RESULT["result_path"] = str(result_path)
                with result_path.open("x", encoding="utf-8", newline="\n") as stream:
                    json.dump(RESULT, stream, sort_keys=True, separators=(",", ":"))
                    stream.write("\n")
            except BaseException as exc:
                GATE_REFS.append(exc)
                RESULT["status"] = "HOLD_RESULT_WRITE_FAILED"
                RESULT["result_write_exception_type"] = type(exc).__name__


run_gate()
print(json.dumps(RESULT, sort_keys=True, separators=(",", ":")))
