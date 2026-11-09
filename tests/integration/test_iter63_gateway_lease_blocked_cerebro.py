"""Iteration 63.11: a strategy blocked in ``next()`` keeps its Gateway registration.

The client runtime renews its Registry lease on its own thread, so a Cerebro
strategy that blocks for several lease periods can still call the Gateway
afterwards. With renewals suppressed the same scenario loses the lease, which
shows the check is real. The Gateway runs in its own process with a short
Registry lease (synthetic; no venue).
"""

import multiprocessing
import socket
import time
import traceback
from pathlib import Path

import backtrader as bt
import pytest
import zmq
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from bt_api_base.gateway_execution_stream_protocol import gateway_execution_consumer_ref
from bt_api_py.service_runtime import ClientCurveKeys

from backtrader.live_state import StrategyStateDir
from backtrader.live_state.gateway_pending import GatewayPendingHost
from tests.integration.test_iter63_gateway_stream_consumer_process import (
    ACCOUNT,
    CLIENT,
    DOMAIN,
    _configured_raw,
    _gateway,
    _join,
    _message,
)

LEASE_SECONDS = 2.0
BLOCK_SECONDS = 3.5 * LEASE_SECONDS
# Long enough that a respawned client (about 1 s to start) lands inside it.
KILL_LEASE_SECONDS = 6.0


def _short_lease_gateway(lease_seconds, *args):
    import bt_api_py.service_host as service_host

    base = service_host.ServiceRegistry

    class ShortLeaseRegistry(base):
        def __init__(self, *a, **k):
            k["lease_seconds"] = lease_seconds
            super().__init__(*a, **k)

    service_host.ServiceRegistry = ShortLeaseRegistry
    _gateway(*args)


def _blocked_cerebro_client(root, endpoint, server_public, keys, journal_id, messages, renewals):
    store = None
    try:
        import pandas as pd
        from bt_api_py.service_runtime import ServiceClientRuntime

        from backtrader.stores.btapistore import BtApiStore

        if not renewals:
            # Negative control: renewals would only be due long after the test.
            ServiceClientRuntime._RENEWAL_FRACTION = 1000.0
        path = Path(root) / "blocked-strategy"
        path.mkdir()
        state = StrategyStateDir.initialize(path)
        binding = GatewayCommandBinding(journal_id, ACCOUNT, CLIENT.actor_ref, CLIENT.principal_ref)
        GatewayPendingHost.upgrade_for_gateway(path, state.strategy_uuid, binding)
        GatewayPendingHost.upgrade_for_cancellation(path, state.strategy_uuid, binding)
        consumer = gateway_execution_consumer_ref(
            principal_ref=CLIENT.principal_ref, actor_ref=CLIENT.actor_ref,
            execution_domain_ref=DOMAIN, account_scope=ACCOUNT, strategy_scope=CLIENT.actor_ref)
        GatewayPendingHost.upgrade_for_execution(path, state.strategy_uuid, binding,
                                                 consumer_ref=consumer)
        host = GatewayPendingHost.upgrade_for_order_state(path, state.strategy_uuid, binding)
        store = BtApiStore(
            config={"gateway_strategy": _configured_raw(endpoint, journal_id),
                    "contracts": {"rb": {"quantity_unit": "lots", "time_in_force": "GFD"}}},
            gateway_host=host,
            gateway_security_profiles={"security": ClientCurveKeys(server_public, *keys)},
        )

        class BlockingStrategy(bt.Strategy):
            def __init__(self):
                self.result = None

            def next(self):
                if self.result is not None:
                    return
                assert self.broker._gateway_stream_binding.strategy is self

                def probe():
                    snapshot = store.gateway_api.status()
                    ids = tuple(sorted(b.registration_id for b in snapshot.bindings if b.active))
                    return snapshot.healthy, ids

                before = probe()
                started = time.monotonic()
                time.sleep(BLOCK_SECONDS)  # strategy thread blocked for several leases
                blocked = time.monotonic() - started
                # Healthy means the lease deadline is still in the future; it only
                # moves after the Gateway accepted a renewal of these registrations.
                self.result = (before, blocked, probe())

            def stop(self):
                messages.put(("blocked-result", *self.result))

        frame = pd.DataFrame({"open": [10.0] * 3, "high": [11.0] * 3, "low": [9.0] * 3,
                              "close": [10.0] * 3, "volume": [1.0] * 3},
                             index=pd.date_range("2030-01-01 09:00", periods=3, freq="min"))
        cerebro = bt.Cerebro(stdstats=False, runonce=False)
        cerebro.setbroker(bt.brokers.BtApiBroker(store=store))
        cerebro.adddata(bt.feeds.PandasData(dataname=frame), name="rb")
        cerebro.addstrategy(BlockingStrategy)
        cerebro.run()
    except BaseException:
        messages.put(("error", traceback.format_exc()))
    finally:
        if store is not None and store.gateway_api is not None:
            try:
                store.stop(timeout=5)
            except BaseException:
                if renewals:
                    messages.put(("error", traceback.format_exc()))


@pytest.mark.parametrize("renewals", [True, False], ids=["renewing", "renewals-suppressed"])
def test_blocked_cerebro_strategy_keeps_its_gateway_lease(tmp_path, renewals):
    ctx = multiprocessing.get_context("spawn")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        endpoint = "tcp://127.0.0.1:" + str(sock.getsockname()[1])
    server_keys, client_keys = zmq.curve_keypair(), zmq.curve_keypair()
    gm, gc, cm, cc = ctx.Queue(), ctx.Queue(), ctx.Queue(), ctx.Queue()
    server = ctx.Process(target=_short_lease_gateway,
                         args=(LEASE_SECONDS, str(tmp_path), endpoint, server_keys, client_keys,
                               gm, gc))
    client = None
    server.start()
    try:
        ready = _message(gm, "ready")
        client = ctx.Process(target=_blocked_cerebro_client,
                             args=(str(tmp_path), endpoint, server_keys[0], client_keys, ready[2],
                                   cm, renewals))
        client.start()
        result = cm.get(timeout=60)
        assert result[0] == "blocked-result", result
        before, blocked, after = result[1:]
        assert before[0] is True and before[1] and blocked >= BLOCK_SECONDS
        if renewals:
            # Same registrations, still within a lease the Gateway renewed.
            assert after == before, result
        else:
            assert after[0] is False, result
        client.join(30)
        if client.is_alive():
            client.terminate()
            client.join(5)
        if renewals:
            assert client.exitcode == 0
    finally:
        if client is not None and client.is_alive():
            client.terminate()
            client.join(5)
        gc.put("stop")
        _join(server)
        for q in (gm, gc, cm, cc):
            q.close()


def _registering_client(root, name, endpoint, server_public, keys, journal_id, messages, hold):
    store = None
    try:
        from backtrader.stores.btapistore import BtApiStore
        from tests.unit.brokers.test_iter63_gateway_notification_delivery import framework

        path = Path(root) / name
        path.mkdir()
        state = StrategyStateDir.initialize(path)
        binding = GatewayCommandBinding(journal_id, ACCOUNT, CLIENT.actor_ref, CLIENT.principal_ref)
        GatewayPendingHost.upgrade_for_gateway(path, state.strategy_uuid, binding)
        GatewayPendingHost.upgrade_for_cancellation(path, state.strategy_uuid, binding)
        consumer = gateway_execution_consumer_ref(
            principal_ref=CLIENT.principal_ref, actor_ref=CLIENT.actor_ref,
            execution_domain_ref=DOMAIN, account_scope=ACCOUNT, strategy_scope=CLIENT.actor_ref)
        GatewayPendingHost.upgrade_for_execution(path, state.strategy_uuid, binding,
                                                 consumer_ref=consumer)
        host = GatewayPendingHost.upgrade_for_order_state(path, state.strategy_uuid, binding)
        store = BtApiStore(
            config={"gateway_strategy": _configured_raw(endpoint, journal_id),
                    "contracts": {"rb": {"quantity_unit": "lots", "time_in_force": "GFD"}}},
            gateway_host=host,
            gateway_security_profiles={"security": ClientCurveKeys(server_public, *keys)},
        )
        _, broker, _ = framework()
        broker.store = store
        try:
            broker.start()
        except Exception as exc:
            messages.put(("start", name, "refused", getattr(exc, "code", type(exc).__name__)))
            return
        messages.put(("start", name, "registered", store.gateway_api.status().healthy))
        if hold:
            time.sleep(600)  # killed by the test while registered
    except BaseException:
        messages.put(("error", traceback.format_exc()))
    finally:
        if store is not None and store.gateway_api is not None:
            try:
                store.stop(timeout=5)
            except BaseException:
                pass


def test_killed_client_registration_expires_then_the_strategy_can_return(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        endpoint = "tcp://127.0.0.1:" + str(sock.getsockname()[1])
    server_keys, client_keys = zmq.curve_keypair(), zmq.curve_keypair()
    gm, gc, cm = ctx.Queue(), ctx.Queue(), ctx.Queue()
    server = ctx.Process(target=_short_lease_gateway,
                         args=(KILL_LEASE_SECONDS, str(tmp_path), endpoint, server_keys,
                               client_keys, gm, gc))
    clients = []

    def start(name, hold):
        proc = ctx.Process(target=_registering_client,
                           args=(str(tmp_path), name, endpoint, server_keys[0], client_keys,
                                 journal_id, cm, hold))
        proc.start()
        clients.append(proc)
        return proc, cm.get(timeout=60)

    server.start()
    try:
        journal_id = _message(gm, "ready")[2]
        first, registered = start("first", hold=True)
        assert registered == ("start", "first", "registered", True), registered
        first.kill()  # no unregister: only the lease can end this registration
        first.join(10)
        killed_at = time.monotonic()

        _, early = start("early", hold=False)
        # Still within the dead client's lease: the identity is not free yet.
        assert time.monotonic() - killed_at < KILL_LEASE_SECONDS
        assert early[:3] == ("start", "early", "refused"), early

        time.sleep(max(0.0, KILL_LEASE_SECONDS + 1.0 - (time.monotonic() - killed_at)))
        _, later = start("later", hold=False)
        assert later == ("start", "later", "registered", True), later
    finally:
        for proc in clients:
            if proc.is_alive():
                proc.kill()
            proc.join(10)
        gc.put("stop")
        _join(server)
        for q in (gm, gc, cm):
            q.close()
