"""Local-process acceptance for delayed service execution refreshes.

The test uses a real authenticated execution service and SQLite journal. The
test host injects a delayed synthetic provider observation through the public
``SqliteExecutionStore.record_observation`` API with the current service writer
lease; this does not exercise a production provider callback adapter. A
manually driven refresh schedule exercises normal Cerebro order notifications.
Production automatic schedule assembly remains pending.
"""

from __future__ import annotations

import datetime as dt
import multiprocessing
from contextlib import suppress

import pytest

pytest.importorskip("bt_api_py")
pytest.importorskip("bt_api_execution")
zmq = pytest.importorskip("zmq")
pd = pytest.importorskip("pandas")

import backtrader as bt  # noqa: E402
from bt_api_base.service_protocol import WireIdentity, WireRole  # noqa: E402
from bt_api_py.service_config import parse_client_config  # noqa: E402
from bt_api_py.service_execution import ServiceExecutionClient  # noqa: E402
from bt_api_py.service_runtime import (  # noqa: E402
    ClientCurveKeys,
    ServiceClientRuntime,
    ZmqTransportFactory,
)

from backtrader.stores.service_execution_adapter import ServiceExecutionAdapter  # noqa: E402
from backtrader.stores.service_refresh_loop import ManagedOrderRefreshLoop  # noqa: E402
from tests.fixtures.fake_btapi import make_store  # noqa: E402
from tests.unit.brokers.test_btapibroker_managed_execution_projection import (  # noqa: E402
    _ResponseProvider,
)
from tests.unit.stores.test_service_execution_adapter_local_process import (  # noqa: E402
    _ACCOUNT,
    _ORDER_SCOPE_REF,
    _PRINCIPAL,
    _QUERY_SCOPE_REF,
    _SCOPE,
    _SERVICE_ID,
    _SERVICE_PRINCIPAL,
    _STRATEGY,
    _TRADING_DAY,
    _client_config,
    _close_host,
    _command,
    _endpoint,
    _host_process,
    _managed_broker_info,
    _receive,
    _service_config,
    _start_process,
)


_INTENT_ID = "intent.refresh-notification"
_CURVE_REFERENCE = "bt-execution-curve-v1"


@pytest.mark.parametrize(
    (
        "terminal_observation",
        "expected_terminal_status",
        "expected_terminal_size",
        "expected_terminal_price",
        "terminal_quantity",
        "terminal_price",
    ),
    (
        ("FILLED", bt.Order.Completed, 2.0, 101.5, "2", "101.5"),
        ("CANCELLED", bt.Order.Canceled, 1.0, 100.5, "1", "100.5"),
    ),
    ids=("filled-after-partial", "cancelled-after-partial"),
)
def test_cerebro_notifies_delayed_service_fill_or_cancel_once(
    tmp_path,
    terminal_observation,
    expected_terminal_status,
    expected_terminal_size,
    expected_terminal_price,
    terminal_quantity,
    terminal_price,
) -> None:
    """Delayed synthetic service observations reach Strategy.notify_order."""

    from bt_api_execution import ExecutionScope

    context = multiprocessing.get_context("spawn")
    endpoint = _endpoint()
    server_public, server_secret = zmq.curve_keypair()
    strategy_public, strategy_secret = zmq.curve_keypair()
    scope_key = ExecutionScope("PAPER", "simulation", _ACCOUNT, _STRATEGY, _TRADING_DAY).key
    keys = {
        "server_public": server_public,
        "server_secret": server_secret,
        "strategy_public": strategy_public,
    }
    host = None
    runtime = None
    store = None
    legacy_provider = _ResponseProvider([])
    clock = [0.0]

    try:
        host = _start_process(
            context,
            _host_process,
            (
                _service_config(endpoint),
                str(tmp_path / "refresh-registry.sqlite3"),
                keys,
                str(tmp_path / "refresh-execution.sqlite3"),
            ),
            "bt-refresh-notification-host",
        )
        ready = _receive(host["pipe"])
        assert ready[0] == "ready", ready
        assert ready[1] == endpoint

        runtime = ServiceClientRuntime(
            parse_client_config(_client_config(endpoint, _CURVE_REFERENCE)),
            identity=WireIdentity(WireRole.STRATEGY_CLIENT, _PRINCIPAL, _STRATEGY),
            scope_resolver=lambda _ref: _SCOPE,
            peer_resolver=lambda _service: WireIdentity(
                WireRole.SERVICE, _SERVICE_PRINCIPAL, _SERVICE_ID
            ),
            transport_factory=ZmqTransportFactory(
                {_CURVE_REFERENCE: ClientCurveKeys(server_public, strategy_public, strategy_secret)}
            ),
        )
        assert runtime.start().degraded_count == 0

        client = ServiceExecutionClient(
            runtime,
            "broker.orders",
            scope_ref=_ORDER_SCOPE_REF,
            query_mount="broker.order_query",
            query_scope_ref=_QUERY_SCOPE_REF,
        )
        adapter = ServiceExecutionAdapter(client)
        store = make_store(
            api=legacy_provider,
            managed_execution_adapter=adapter,
        )
        broker = store.getbroker(
            validation_enabled=False,
            cash_check_enabled=False,
            account_refresh_interval=3600.0,
            positions_refresh_interval=3600.0,
            open_orders_refresh_interval=3600.0,
        )
        frame = pd.DataFrame(
            {
                "open": [100.0] * 5,
                "high": [102.0] * 5,
                "low": [99.0] * 5,
                "close": [101.0] * 5,
                "volume": [1.0] * 5,
                "openinterest": [0.0] * 5,
            },
            index=[dt.datetime(2024, 1, day) for day in range(1, 6)],
        )
        data = bt.feeds.PandasData(dataname=frame)
        cerebro = bt.Cerebro(stdstats=False, runonce=False)
        cerebro.setbroker(broker)
        cerebro.adddata(data, name="BTC-USDT")

        class _RefreshStrategy(bt.Strategy):
            def __init__(self) -> None:
                self.order = None
                self.notifications = []
                self.phase = "submit"
                self.refresh_loop = ManagedOrderRefreshLoop(
                    self.broker,
                    interval_seconds=1.0,
                    monotonic_clock=lambda: clock[0],
                )

            def notify_order(self, order) -> None:
                if order.info.get("managed_intent_id") != _INTENT_ID:
                    return
                self.notifications.append(
                    (
                        order.status,
                        float(order.executed.size or 0.0),
                        float(order.executed.price or 0.0),
                    )
                )

            def next(self) -> None:
                if self.phase == "submit":
                    self.order = self.buy(
                        data=self.datas[0],
                        size=2,
                        price=101.0,
                        exectype=bt.Order.Limit,
                        **_managed_broker_info(_INTENT_ID),
                    )
                    self.phase = "await_acceptance"
                    return

                statuses = [status for status, _size, _price in self.notifications]
                if self.phase == "await_acceptance" and bt.Order.Accepted in statuses:
                    accepted = client.query(_INTENT_ID)
                    assert accepted is not None
                    assert accepted.state == "ACKED"
                    assert accepted.provider_order_id == "provider-order-1"
                    partial = _command(
                        host,
                        "record_observation",
                        _INTENT_ID,
                        "PARTIALLY_FILLED",
                        "1",
                        "100.5",
                    )
                    assert partial == (
                        "observation_recorded",
                        "ACKED",
                        _INTENT_ID,
                        scope_key,
                        "PARTIALLY_FILLED",
                        "provider-order-1",
                        "1",
                        "100.5",
                    )
                    clock[0] = 1.0
                    assert self.refresh_loop.run_once() == (self.order.ref,)
                    self.phase = "await_partial"
                    return

                if self.phase == "await_partial" and bt.Order.Partial in statuses:
                    assert self.notifications == [
                        (bt.Order.Accepted, 0.0, 0.0),
                        (bt.Order.Partial, 1.0, 100.5),
                    ]
                    assert statuses.count(bt.Order.Partial) == 1
                    # The same durable revision is queried again. It must not
                    # create a second partial notification before the terminal
                    # observation arrives.
                    clock[0] = 2.0
                    assert self.refresh_loop.run_once() == ()
                    assert self.refresh_loop.stats.applied == 1
                    assert self.refresh_loop.stats.failures == 0

                    terminal = _command(
                        host,
                        "record_observation",
                        _INTENT_ID,
                        terminal_observation,
                        terminal_quantity,
                        terminal_price,
                    )
                    assert terminal == (
                        "observation_recorded",
                        "PARTIALLY_FILLED",
                        _INTENT_ID,
                        scope_key,
                        terminal_observation,
                        "provider-order-1",
                        terminal_quantity,
                        terminal_price,
                    )
                    clock[0] = 3.0
                    assert self.refresh_loop.run_once() == (self.order.ref,)
                    self.phase = "await_terminal"
                    return

                if self.phase == "await_terminal" and expected_terminal_status in statuses:
                    terminal_count = sum(
                        status in (bt.Order.Completed, bt.Order.Canceled) for status in statuses
                    )
                    assert terminal_count == 1
                    clock[0] = 4.0
                    assert self.refresh_loop.run_once() == ()
                    self.phase = "done"
                    self.cerebro.runstop()

        cerebro.addstrategy(_RefreshStrategy)
        results = cerebro.run()
        strategy = results[0]

        assert strategy.phase == "done"
        assert [status for status, _size, _price in strategy.notifications] == [
            bt.Order.Accepted,
            bt.Order.Partial,
            expected_terminal_status,
        ]
        terminal_notifications = [
            (status, size, price)
            for status, size, price in strategy.notifications
            if status in (bt.Order.Completed, bt.Order.Canceled)
        ]
        assert terminal_notifications == [
            (expected_terminal_status, expected_terminal_size, expected_terminal_price)
        ]
        assert strategy.order.status == expected_terminal_status
        assert strategy.order.executed.size == pytest.approx(expected_terminal_size)
        assert strategy.order.executed.price == pytest.approx(expected_terminal_price)

        counts = _command(host, "counts")
        assert counts[1] == (_INTENT_ID,)
        assert counts[2] == ()
        assert counts[3] == (_INTENT_ID,)
        assert legacy_provider.submitted_orders == []
        durable = client.query(_INTENT_ID)
        assert durable.state == terminal_observation
        assert durable.provider_order_id == "provider-order-1"
        assert str(durable.filled_quantity) == terminal_quantity

        assert strategy.refresh_loop.stats.attempts == 4
        assert strategy.refresh_loop.stats.applied == 2
        assert strategy.refresh_loop.stats.failures == 0

        assert not store.is_connected
        assert store.get_command_health()["shutdown_state"] == "PASS"
        assert legacy_provider.connected is False
        runtime.close()
        assert runtime.state == "closed"
        runtime = None
        _close_host(host)
        host = None
    finally:
        if store is not None:
            with suppress(Exception):
                store.stop()
        if runtime is not None:
            with suppress(Exception):
                runtime.close()
        if host is not None:
            _close_host(host)
