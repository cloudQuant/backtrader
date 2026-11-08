"""E043 synthetic loopback probe; no venue connection and no product edits.

The R21 fixture runs the real CTP Python session, Gateway profile/Host and
CURVE, with synthetic native TD/MD. Only the child-local fixture grant is
extended to register the existing batch operation. A single batch item is used.
"""
from __future__ import annotations

import json
import multiprocessing
import os
import queue
import signal
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, "/Users/yunjinqi/Documents/new_projects/bt_api_py")
import zmq
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from bt_api_base.service_protocol import WireScope
from bt_api_gateway.direct_command_journal import GatewayDirectCommandJournal
from bt_api_py._contracts.models import OrderRequest
from bt_api_py.gateway_direct_client import GatewayClientRoute
from bt_api_py.gateway_strategy_client import GatewayStrategyClientSession
from bt_api_py.order_correlation_issuer import DurableOrderCorrelationIssuer
from bt_api_py.service_config import parse_client_config
from bt_api_py.service_runtime import ClientCurveKeys
from tests.integration import test_iter63_ctp_gateway_joint_service as f
from tests.integration.test_iter63_gateway_direct_service import CLIENT_A, DOMAIN, OPS, SERVICE, _client_config
from tests.integration.test_service_account_instrument_metadata import _free_endpoint
from tests.unit.test_iter63_gateway_direct_client import MemoryHost
from tests.unit.test_iter63_gateway_direct_service import _order


def gateway_with_batch(root, rpc, market, server_keys, client_keys, journal_id, issuer_id, events, controls, block):
    # Only this child process changes the fixture's test authority. No source file is changed.
    f.MARKET_OPS = f.MARKET_OPS | frozenset({"market.bootstrap_many"})
    def trace(frame, event, arg):
        if event == "exception" and frame.f_code.co_filename.endswith("ctp_gateway_trading.py") and not isinstance(arg[1], GeneratorExit):
            print("SYNTHETIC_PROFILE_EXCEPTION", frame.f_lineno, repr(arg[1]), flush=True)
        return trace
    threading.settrace(trace)
    sys.settrace(trace)
    f._gateway(root, rpc, market, server_keys, client_keys, journal_id, issuer_id, events, controls, block)


def deadline(_signum, _frame):
    raise TimeoutError("PROBE_TOTAL_DEADLINE")


def main():
    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(25)
    started = time.monotonic()
    root = Path(tempfile.mkdtemp(prefix="run-", dir="/tmp/iter63-e043-probe")).resolve()
    (root / "guard").mkdir()
    (root / "flow").mkdir(mode=0o700)
    journal = GatewayDirectCommandJournal.create(root / "orders.sqlite", f.SCOPE, generation="provisioned")
    issuer = DurableOrderCorrelationIssuer(root / "identity.sqlite")
    issuer_id = issuer.issuer_id
    issuer.close()
    rpc, market = _free_endpoint(), _free_endpoint()
    server_keys = zmq.curve_keypair()
    client_keys = tuple(zmq.curve_keypair() for _ in range(3))
    ctx = multiprocessing.get_context("spawn")
    entered, release = ctx.Event(), ctx.Event()
    events, controls = ctx.Queue(), ctx.Queue()
    child = ctx.Process(target=gateway_with_batch, args=(str(root), rpc, market, server_keys, client_keys,
        journal.journal_id, issuer_id, events, controls, (entered, release)))
    child.start()
    a = c = None
    t = None
    result = {"probe": "E043_bootstrap_many_single_key", "evidence": "incomplete"}
    try:
        ready = events.get(timeout=8)
        if ready != ("ready", child.pid):
            raise RuntimeError("fixture_start_failed: " + repr(ready))
        f.MARKET_OPS = f.MARKET_OPS | frozenset({"market.bootstrap_many"})
        a = f._session(CLIENT_A, client_keys[0], server_keys[0], rpc, market, journal.journal_id, "IF2612", root)
        a.start(timeout_seconds=5)
        market_binding = next(x for x in a.status().bindings if x.mount == "store.market")
        assert "market.bootstrap_many" in market_binding.operations
        original_registration = market_binding.registration_id

        raw = _client_config(rpc, f.CLIENT_C).to_public_dict()
        raw["clients"]["gateway"]["settings"]["bindings"][0]["account_ref"] = f.SCOPE
        scope = WireScope(DOMAIN, account_ref=f.SCOPE, strategy_ref=f.CLIENT_C.actor_ref, run_id="e043-run-c")
        c = GatewayStrategyClientSession(parse_client_config(raw),
            binding=GatewayCommandBinding(journal.journal_id, f.SCOPE, f.CLIENT_C.actor_ref, f.CLIENT_C.principal_ref),
            route=GatewayClientRoute("broker.direct_write", SERVICE.actor_ref, "gateway-a", "scope-a", scope, f.CLIENT_C),
            peer=SERVICE, security_profiles={"security-a": ClientCurveKeys(server_keys[0], *client_keys[2])},
            host=MemoryHost(), requested_operations=OPS)
        c.start(timeout_seconds=5)
        request = OrderRequest.from_dict(_order(key="e043-status", symbol="IF2612", account=f.SCOPE))
        reserve = f._until(lambda: (x if (x := c.command_client.reserve(request, timeout_seconds=1)).outcome == "OBSERVED" else None), timeout=5)
        assert reserve.record.state == "RESERVED"
        initial = c.command_client.status("e043-status", timeout_seconds=1)
        assert initial.outcome == "OBSERVED" and initial.record.state == "RESERVED"
        c_registration = c.status().bindings[0].registration_id

        responses = queue.Queue()
        def batch():
            try:
                value = a.runtime.call("store.market", "market.bootstrap_many", {
                    "subscriptions": [{"key": f._key("IF2612").to_dict(), "require_source_descriptor": True}]
                }, timeout_seconds=8)
                responses.put(("reply", value.get("status", "OK")))
            except BaseException as error:
                responses.put(("error", type(error).__name__, getattr(error, "code", "")))
        t = threading.Thread(target=batch, name="single-original-batch", daemon=True)
        t.start()
        if not entered.wait(5):
            raise RuntimeError("native_md_start_not_entered")
        assert not release.is_set() and t.is_alive()
        before = time.monotonic()
        status = c.command_client.status("e043-status", timeout_seconds=0.5)
        elapsed = time.monotonic() - before
        after_registration = c.status().bindings[0].registration_id
        original_a_registration = next(x for x in a.status().bindings if x.mount == "store.market").registration_id
        result.update(native_start_entered=True, batch_thread_inflight=t.is_alive(),
            batch_item_count=1, principal_c_same_registration=(c_registration == after_registration),
            batch_same_registration=(original_registration == original_a_registration),
            status_outcome=status.outcome, status_code=status.code, status_elapsed_seconds=round(elapsed, 3),
            total_before_release_seconds=round(time.monotonic() - started, 3))
        result["evidence"] = "reproduced" if (status.outcome == "UNKNOWN" and elapsed < 1.5 and t.is_alive()) else "not_reproduced"
        release.set()
        t.join(5)
        result["original_batch_settled"] = not t.is_alive()
        result["original_batch_result"] = responses.get_nowait() if not responses.empty() else None
        result["batch_registration_after_release_same"] = (next(x for x in a.status().bindings if x.mount == "store.market").registration_id == original_registration)
        resumed = f._until(lambda: (x if (x := c.command_client.status("e043-status", timeout_seconds=1)).outcome == "OBSERVED" else None), timeout=5)
        result["status_after_release"] = resumed.outcome
        result["status_after_release_state"] = resumed.record.state
        result["status_registration_after_release_same"] = (c.status().bindings[0].registration_id == c_registration)
        controls.put("stats")
        stats = events.get(timeout=3)
        result["native_td_stream_md_counts"] = stats[1:5]
    finally:
        release.set()
        if t is not None:
            t.join(4)
        result["batch_thread_stopped"] = (t is None or not t.is_alive())
        cleanup = []
        for label, session in (("a", a), ("c", c)):
            if session is not None:
                try:
                    closed = session.close(timeout_seconds=3)
                    cleanup.append((label, closed.state, closed.thread_alive, closed.owner_cleanup_uncertainties))
                except BaseException as error:
                    cleanup.append((label, type(error).__name__))
        controls.put("stop")
        child.join(6)
        if child.is_alive():
            child.terminate()  # This process was created by this probe only.
            child.join(2)
            result["forced_child_stop"] = True
        else:
            result["forced_child_stop"] = False
        tail = []
        while True:
            try:
                tail.append(events.get_nowait())
            except queue.Empty:
                break
        result.update(child_exitcode=child.exitcode, child_events=tail, cleanup=cleanup,
            total_seconds=round(time.monotonic()-started, 3))
        signal.alarm(0)
        print(json.dumps(result, ensure_ascii=True, sort_keys=True), flush=True)
    if (result["evidence"] != "reproduced" or result.get("forced_child_stop")
        or result.get("child_exitcode") != 0 or not result.get("batch_thread_stopped")
        or result.get("status_after_release_state") != "RESERVED"
        or result.get("native_td_stream_md_counts") != (1, 1, 1, 1)):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
