"""Credential-free, loopback-only CTP native release observation.

Run only in the reviewed consumer with python -I -i. The script does not read
configuration, create a Store/client, authenticate, issue requests, or exit.
Uncertain API/SPI/thread references remain in GATE_STATE for Root inspection.
"""
from __future__ import annotations

import errno
import hashlib
import importlib
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

CONSUMER = Path(r"D:\temp\i51cal-consumer-20261027-r1\consumer").resolve()
CLIENT_PATH = CONSUMER / "Lib" / "site-packages" / "bt_api_ctp" / "ctp" / "client.py"
CLIENT_SHA256 = "1c7aa46dbc97f01c838820661ecf3cf1249fefd297c89a1fd24af4151540529d"
ROOT = Path(r"D:\temp\i51-ctp-nojoin-gate-20261027-r2")
MD_FLOW, TD_FLOW = ROOT / "md-flow", ROOT / "td-flow"
RESULT = ROOT / "result.json"
FRONT = "tcp://127.0.0.1:1"
RELEASE_TIMEOUT, PRE_OBSERVE, POST_OBSERVE = 10.0, 0.75, 1.25
CALLBACKS = (
    "OnFrontConnected", "OnFrontDisconnected", "OnHeartBeatWarning",
    "OnRspUserLogin", "OnRtnDepthMarketData", "OnRspSubMarketData",
    "OnRspAuthenticate", "OnRspSettlementInfoConfirm", "OnRspQryTradingAccount",
    "OnRspQryInvestorPosition", "OnRspQryOrder", "OnRspQryTrade",
    "OnRspQryInstrument", "OnRspQryDepthMarketData", "OnRspQryOptionInstrTradeCost",
    "OnRspQryOptionInstrCommRate", "OnRspQryInstrumentMarginRate",
    "OnRspQryInstrumentCommissionRate", "OnRtnOrder", "OnRspOrderAction",
    "OnErrRtnOrderAction", "OnRtnTrade", "OnRspOrderInsert", "OnErrRtnOrderInsert",
    "OnRspError",
)
GATE_STATE = {"status": "NOT_STARTED", "cases": [], "exceptions": []}


def _callback_facts(case):
    m = case["metrics"]
    with m["lock"]:
        events, active = list(m["events"]), m["inflight"]
    intervals = {}
    for stamp, kind, name, token in sorted(events):
        if kind == "enter":
            intervals[token] = [name, stamp, None]
        elif kind == "exit" and token in intervals:
            intervals[token][2] = stamp
    release_ns = case.get("release_return_ns")
    after = active_at_return = 0
    if release_ns is not None:
        for _, entered, exited in intervals.values():
            after += entered >= release_ns
            active_at_return += entered <= release_ns and (exited is None or exited >= release_ns)
    return active, after, active_at_return


def _public_case(c):
    active, after, at_return = _callback_facts(c)
    return {
        "name": c["name"], "phase": c["phase"], "failure_code": c.get("failure_code"),
        "api_calls": list(c["api_calls"]), "register_spi_detach_calls": c["detach_calls"],
        "release_calls": c["release_calls"], "release_call_finished": c["release_call_finished"],
        "release_returned_normally": c["release_returned_normally"],
        "release_api_same_as_created_api": c.get("release_api_same"),
        "release_worker_alive": bool(c["release_thread"] and c["release_thread"].is_alive()),
        "release_elapsed_ms": (round((c["release_return_ns"] - c["release_started_ns"]) / 1_000_000, 3)
                               if c.get("release_return_ns") is not None else None),
        "join_calls": c["join_calls"], "callback_entries": c["metrics"]["entries"],
        "callback_exits": c["metrics"]["exits"], "callbacks_inflight": active,
        "callbacks_inflight_at_release_return": at_return,
        "callbacks_after_release_return": after, "callback_counts": dict(c["metrics"]["by_name"]),
        "elapsed_ms": round((time.perf_counter() - c["started"]) * 1000, 3),
        "python_threads_before": c.get("python_threads_before"),
        "python_threads_after_init": c.get("python_threads_after_init"),
        "python_threads_after_release": threading.active_count(),
        "thread_fact_scope": "Python-managed only; not proof of native API quiescence",
        "native_process_thread_count": None,
    }


def _persist(phase):
    GATE_STATE["phase"] = phase
    if ROOT.is_dir():
        data = {
            "schema": 1, "gate": "I51_CTP_NOJOIN_NATIVE_PRIMITIVE",
            "status": GATE_STATE["status"], "phase": phase, "front": FRONT,
            "scope": "credential-free loopback native lifecycle only",
            "join_calls": 0, "login_auth_subscription_query_calls": 0,
            "client_source_sha256": GATE_STATE.get("client_source_sha256"),
            "cases": [_public_case(c) for c in GATE_STATE["cases"]],
        }
        RESULT.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _front_is_unserved():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(5.0)
        return s.connect_ex(("127.0.0.1", 1)) == errno.ECONNREFUSED
    finally:
        s.close()


def _make_spi(base, name, case):
    def method(callback_name):
        def callback(self, *args, **kwargs):
            m, stamp = case["metrics"], time.perf_counter_ns()
            with m["lock"]:
                token = m["next_token"]
                m["next_token"] += 1
                m["events"].append((stamp, "enter", callback_name, token))
                m["entries"] += 1
                m["inflight"] += 1
                m["by_name"][callback_name] = m["by_name"].get(callback_name, 0) + 1
            try:
                return None
            finally:
                with m["lock"]:
                    m["events"].append((time.perf_counter_ns(), "exit", callback_name, token))
                    m["exits"] += 1
                    m["inflight"] -= 1
        callback.__name__ = callback_name
        return callback

    ns = {"__module__": __name__, "__init__": lambda self: base.__init__(self)}
    ns.update({n: method(n) for n in CALLBACKS})
    return type(name, (base,), ns)()


def _new_case(name):
    return {
        "name": name, "phase": "created", "started": time.perf_counter(),
        "api": None, "spi": None, "release_thread": None, "api_calls": [],
        "detach_calls": 0, "release_calls": 0, "release_call_finished": False,
        "release_returned_normally": False, "release_api_same": None,
        "release_started_ns": None, "release_return_ns": None,
        "join_calls": 0, "errors": [],
        "metrics": {"lock": threading.Lock(), "events": [], "next_token": 0,
                    "entries": 0, "exits": 0, "inflight": 0, "by_name": {}},
    }


def _run_case(client, name, factory, spi_base, flow):
    c = _new_case(name)
    GATE_STATE["cases"].append(c)
    GATE_STATE["active_case"] = c
    try:
        if any(flow.iterdir()):
            c.update(phase="flow_precondition", failure_code="FLOW_DIRECTORY_NOT_EMPTY")
            return False
        c["python_threads_before"] = threading.active_count()
        c["phase"] = "api_factory"
        c["api"] = factory(str(flow) + os.sep)
        if c["api"] is None:
            c.update(phase="api_factory_failed", failure_code="API_FACTORY_RETURNED_NONE")
            return False
        c["spi"] = _make_spi(spi_base, "Gate" + name.title() + "Spi", c)
        c["phase"] = "register_spi"
        c["api_calls"].append("RegisterSpi(spi)")
        c["api"].RegisterSpi(c["spi"])
        c["phase"] = "register_front"
        c["api_calls"].append("RegisterFront(loopback_closed)")
        c["api"].RegisterFront(FRONT)
        c["phase"] = "init"
        c["api_calls"].append("Init")
        c["api"].Init()
        c["python_threads_after_init"] = threading.active_count()
        c["phase"] = "pre_release_observation"
        time.sleep(PRE_OBSERVE)
        c["phase"] = "detach_spi"
        c["detach_calls"] = 1
        c["api_calls"].append("RegisterSpi(None)")
        c["api"].RegisterSpi(None)
        c["phase"] = "before_release"
        _persist("before_release_" + name)
    except BaseException as error:
        c["errors"].append(error)
        GATE_STATE["exceptions"].append(error)
        c.update(phase="retained_uncertain", failure_code="SETUP_OR_DETACH_FAILED")
        return False

    try:
        release = c["api"].Release
        c["release_api_same"] = getattr(release, "__self__", c["api"]) is c["api"]
        if not callable(release) or not c["release_api_same"]:
            c.update(phase="release_binding_invalid", failure_code="RELEASE_BINDING_INVALID")
            return False
    except BaseException as error:
        c["errors"].append(error)
        GATE_STATE["exceptions"].append(error)
        c.update(phase="release_binding_failed", failure_code="RELEASE_BINDING_FAILED")
        return False
    finished = threading.Event()

    def release_once():
        with c["metrics"]["lock"]:
            c["release_calls"] += 1
        try:
            release()
            c["release_returned_normally"] = True
        except BaseException as error:
            c["errors"].append(error)
            GATE_STATE["exceptions"].append(error)
        finally:
            stamp = time.perf_counter_ns()
            with c["metrics"]["lock"]:
                c["release_return_ns"] = stamp
                c["metrics"]["events"].append((stamp, "release", "", -1))
                c["release_call_finished"] = True
            finished.set()

    c["phase"] = "release_started"
    c["release_started_ns"] = time.perf_counter_ns()
    worker = threading.Thread(target=release_once, name="i51-ctp-" + name + "-release", daemon=True)
    c["release_thread"] = worker
    try:
        worker.start()
    except BaseException as error:
        c["errors"].append(error)
        GATE_STATE["exceptions"].append(error)
        c.update(phase="release_worker_start_failed", failure_code="RELEASE_WORKER_START_FAILED")
        return False
    if not finished.wait(RELEASE_TIMEOUT):
        c.update(phase="release_timeout", failure_code="RELEASE_DID_NOT_RETURN_WITHIN_BOUND")
        return False
    c["phase"] = "post_release_observation"
    time.sleep(POST_OBSERVE)
    active, after, at_return = _callback_facts(c)
    c["post_release_observe_seconds"] = POST_OBSERVE
    if (not c["release_returned_normally"] or c["release_thread"].is_alive()
            or active or after or at_return):
        c.update(phase="release_or_callback_incomplete", failure_code="RELEASE_CALLBACK_OBSERVATION_INCOMPLETE")
        return False
    c["phase"] = "observed_release_no_join"
    return True


def main():
    try:
        if ROOT.exists() or not ROOT.parent.is_dir():
            raise RuntimeError("OUTPUT_ROOT_NOT_FRESH_OR_TEMP_UNAVAILABLE")
        ROOT.mkdir()
        MD_FLOW.mkdir()
        TD_FLOW.mkdir()
        GATE_STATE.update(status="RUNNING", root=str(ROOT), result_path=str(RESULT))
        _persist("fresh_empty_flow_directories")
        if Path(sys.prefix).resolve() != CONSUMER:
            raise RuntimeError("INSTALLED_CONSUMER_INTERPRETER_REQUIRED")
        client = importlib.import_module("bt_api_ctp.ctp.client")
        GATE_STATE["client_module"] = client
        source = Path(client.__file__).resolve()
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if source != CLIENT_PATH.resolve() or digest != CLIENT_SHA256:
            raise RuntimeError("INSTALLED_CLIENT_SOURCE_PIN_MISMATCH")
        GATE_STATE["client_source_sha256"] = digest
        _persist("installed_client_pinned")
        if not _front_is_unserved():
            raise RuntimeError("FIXED_LOOPBACK_FRONT_NOT_CONFIRMED_CLOSED")
        _persist("loopback_front_confirmed_closed")
        cases = (
            ("md", client.CThostFtdcMdApi.CreateFtdcMdApi, client.CThostFtdcMdSpi, MD_FLOW),
            ("td", client.CThostFtdcTraderApi.CreateFtdcTraderApi, client.CThostFtdcTraderSpi, TD_FLOW),
        )
        for name, factory, spi, flow in cases:
            if not _run_case(client, name, factory, spi, flow):
                GATE_STATE["status"] = "BLOCKED_RETAINED_OR_INCOMPLETE"
                _persist("case_incomplete_" + name)
                return
            _persist("case_observed_" + name)
        GATE_STATE["status"] = "COMPLETE_OBSERVED_WINDOW_ONLY"
        _persist("complete_observed_window_only")
    except BaseException as error:
        GATE_STATE["exceptions"].append(error)
        GATE_STATE["status"] = "BLOCKED_PREFLIGHT_OR_GATE_EXCEPTION"
        try:
            _persist("blocked")
        except BaseException as persist_error:
            GATE_STATE["exceptions"].append(persist_error)


if __name__ == "__main__":
    main()
