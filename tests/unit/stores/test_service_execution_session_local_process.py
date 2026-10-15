"""Local-process lifecycle acceptance for an owned service execution session.

The tests use a real spawned service, CURVE transport, SDK runtime, Store,
Broker, and Cerebro run. Provider changes are synthetic durable observations
injected by the test host through its public SQLite store API. The successful
case does not exercise a production provider callback adapter. It lets the
session's Broker hook maintain registrations and refresh orders; the Strategy
itself never calls a refresh method.
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
from bt_api_execution import ExecutionScope  # noqa: E402
from bt_api_py.service_config import parse_client_config  # noqa: E402
from bt_api_py.service_runtime import (  # noqa: E402
    ClientCurveKeys,
    ServiceClientRuntime,
    ZmqTransportFactory,
)

from backtrader.stores.service_execution_session import ServiceExecutionSession  # noqa: E402
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
    _command,
    _endpoint,
    _host_process,
    _managed_broker_info,
    _receive,
    _service_config,
    _start_process,
)


_INTENT_ID = "intent.execution-session-refresh"
_CURVE_REFERENCE = "bt-execution-curve-v1"
_EXECUTION_SCOPE_KEY = ExecutionScope("PAPER", "simulation", _ACCOUNT, _STRATEGY, _TRADING_DAY).key


class _StrategyStartFailure(RuntimeError):
    """One exact exception used to verify exception-preserving cleanup."""


def _runtime(endpoint: str, keys: dict[str, bytes], clock: list[float]):
    raw_config = _client_config(endpoint, _CURVE_REFERENCE)
    raw_config["clients"]["execution"]["settings"]["options"]["heartbeat_interval_seconds"] = 1
    return ServiceClientRuntime(
        parse_client_config(raw_config),
        identity=WireIdentity(WireRole.STRATEGY_CLIENT, _PRINCIPAL, _STRATEGY),
        scope_resolver=lambda _ref: _SCOPE,
        peer_resolver=lambda _service: WireIdentity(
            WireRole.SERVICE, _SERVICE_PRINCIPAL, _SERVICE_ID
        ),
        transport_factory=ZmqTransportFactory(
            {
                _CURVE_REFERENCE: ClientCurveKeys(
                    keys["server_public"], keys["strategy_public"], keys["strategy_secret"]
                )
            }
        ),
        monotonic_clock=lambda: clock[0],
    )


def _cerebro_with_feed(broker):
    frame = pd.DataFrame(
        {
            "open": [100.0] * 6,
            "high": [102.0] * 6,
            "low": [99.0] * 6,
            "close": [101.0] * 6,
            "volume": [1.0] * 6,
            "openinterest": [0.0] * 6,
        },
        index=[dt.datetime(2024, 1, day) for day in range(1, 7)],
    )
    cerebro = bt.Cerebro(stdstats=False, runonce=False)
    cerebro.setbroker(broker)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame), name="BTC-USDT")
    return cerebro


def _start_host(tmp_path):
    context = multiprocessing.get_context("spawn")
    endpoint = _endpoint()
    server_public, server_secret = zmq.curve_keypair()
    strategy_public, strategy_secret = zmq.curve_keypair()
    keys = {
        "server_public": server_public,
        "server_secret": server_secret,
        "strategy_public": strategy_public,
        "strategy_secret": strategy_secret,
    }
    host = _start_process(
        context,
        _host_process,
        (
            _service_config(endpoint),
            str(tmp_path / "session-registry.sqlite3"),
            keys,
            str(tmp_path / "session-execution.sqlite3"),
        ),
        "bt-execution-session-host",
    )
    ready = _receive(host["pipe"])
    assert ready[0] == "ready", ready
    assert ready[1] == endpoint
    return endpoint, keys, host


def _close_host_normally(host) -> None:
    """Close the fixture host and assert its normal zero exit without a kill fallback."""

    pipe = host["pipe"]
    process = host["process"]
    if pipe.closed:
        return
    pipe.send(("close",))
    closed = _receive(pipe, timeout=20.0)
    assert closed == ("closed", "closed"), closed
    process.join(20)
    assert not process.is_alive(), "spawned execution service did not exit normally"
    assert process.exitcode == 0
    pipe.close()
    process.close()


@pytest.fixture
def local_execution_host(tmp_path):
    """Keep the spawned service under normal-close cleanup for all test paths."""

    endpoint, keys, host = _start_host(tmp_path)
    try:
        yield endpoint, keys, host
    finally:
        _close_host_normally(host)


def _cleanup_after_failed_run(store, runtime) -> None:
    """Best-effort leak cleanup when setup or the session run fails early."""

    if store is not None and store.is_connected:
        with suppress(Exception):
            store.stop()
    if runtime is not None and runtime.state != "closed":
        with suppress(Exception):
            runtime.close()


def _observe_lease_renewals(runtime):
    """Spy on session-driven maintenance and retain only lease deadline facts."""

    observations = []
    maintain = runtime.maintain

    def _maintain_and_observe():
        before = {
            binding.registration_id: binding.lease_deadline
            for binding in runtime.bindings
            if binding.active
        }
        summary = maintain()
        after = {
            binding.registration_id: binding.lease_deadline
            for binding in runtime.bindings
            if binding.active
        }
        observations.append((before, after))
        return summary

    runtime.maintain = _maintain_and_observe
    return observations


def test_session_drives_cerebro_refresh_and_renews_due_runtime_leases(
    local_execution_host,
) -> None:
    """One owned run renews due bindings and emits the delayed cumulative fill."""

    clock = [0.0]
    endpoint, keys, host = local_execution_host
    runtime = _runtime(endpoint, keys, clock)
    renewals = _observe_lease_renewals(runtime)
    legacy_provider = _ResponseProvider([])
    store = make_store(api=legacy_provider)
    broker = store.getbroker(
        validation_enabled=False,
        cash_check_enabled=False,
        account_refresh_interval=3600.0,
        positions_refresh_interval=3600.0,
        open_orders_refresh_interval=3600.0,
    )
    cerebro = _cerebro_with_feed(broker)
    observations = []

    class _RefreshStrategy(bt.Strategy):
        def __init__(self) -> None:
            self.order = None
            self.phase = "submit"
            self.notifications = []
            self.partial_refresh_attempts = 0

        def notify_order(self, order) -> None:
            if order.info.get("managed_intent_id") == _INTENT_ID:
                self.notifications.append(
                    (
                        order.status,
                        float(order.executed.size or 0.0),
                        float(order.executed.price or 0.0),
                    )
                )

        def next(self) -> None:
            statuses = [status for status, _size, _price in self.notifications]
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

            if self.phase == "await_acceptance" and bt.Order.Accepted in statuses:
                accepted = _command(
                    host, "record_observation", _INTENT_ID, "PARTIALLY_FILLED", "1", "100.5"
                )
                observations.append(accepted)
                assert accepted == (
                    "observation_recorded",
                    "ACKED",
                    _INTENT_ID,
                    _EXECUTION_SCOPE_KEY,
                    "PARTIALLY_FILLED",
                    "provider-order-1",
                    "1",
                    "100.5",
                )
                clock[0] = 1.0
                self.phase = "await_partial"
                return

            if self.phase == "await_partial" and bt.Order.Partial in statuses:
                assert self.notifications == [
                    (bt.Order.Accepted, 0.0, 0.0),
                    (bt.Order.Partial, 1.0, 100.5),
                ]
                assert statuses.count(bt.Order.Partial) == 1
                partial_stats = session.refresh_stats
                assert partial_stats is not None
                assert partial_stats.applied == 1
                assert partial_stats.failures == 0
                self.partial_refresh_attempts = partial_stats.attempts
                clock[0] = 2.0
                self.phase = "await_unchanged_refresh"
                return

            if self.phase == "await_unchanged_refresh":
                assert self.notifications == [
                    (bt.Order.Accepted, 0.0, 0.0),
                    (bt.Order.Partial, 1.0, 100.5),
                ]
                unchanged_stats = session.refresh_stats
                assert unchanged_stats is not None
                assert unchanged_stats.attempts == self.partial_refresh_attempts + 1
                assert unchanged_stats.applied == 1
                assert unchanged_stats.failures == 0
                filled = _command(host, "record_observation", _INTENT_ID, "FILLED", "2", "101.5")
                observations.append(filled)
                assert filled == (
                    "observation_recorded",
                    "PARTIALLY_FILLED",
                    _INTENT_ID,
                    _EXECUTION_SCOPE_KEY,
                    "FILLED",
                    "provider-order-1",
                    "2",
                    "101.5",
                )
                clock[0] = 3.0
                self.phase = "await_completion"
                return

            if self.phase == "await_completion" and bt.Order.Completed in statuses:
                self.phase = "done"
                self.cerebro.runstop()

    cerebro.addstrategy(_RefreshStrategy)
    session = ServiceExecutionSession(
        runtime,
        mount="broker.orders",
        scope_ref=_ORDER_SCOPE_REF,
        query_mount="broker.order_query",
        query_scope_ref=_QUERY_SCOPE_REF,
        refresh_interval_seconds=1.0,
        max_refresh_interval_seconds=2.0,
        backoff_factor=2.0,
        limit=8,
        monotonic_clock=lambda: clock[0],
    )

    try:
        results = session.run(cerebro)
        strategy = results[0]

        assert strategy.phase == "done"
        assert strategy.notifications == [
            (bt.Order.Accepted, 0.0, 0.0),
            (bt.Order.Partial, 1.0, 100.5),
            (bt.Order.Completed, 2.0, 101.5),
        ]
        assert strategy.order.status == bt.Order.Completed
        assert strategy.order.executed.size == pytest.approx(2.0)
        assert strategy.order.executed.price == pytest.approx(101.5)
        assert len(observations) == 2
        assert all(item[3] for item in observations)

        counts = _command(host, "counts")
        assert counts[1] == (_INTENT_ID,)
        assert counts[2] == ()
        assert counts[3] == (_INTENT_ID,)
        assert legacy_provider.submitted_orders == []
        assert legacy_provider.cancelled_orders == []
        assert not store.is_connected
        assert store.get_command_health()["shutdown_state"] == "PASS"
        assert legacy_provider.connected is False
        assert runtime.state == "closed"
        assert runtime.cleanup_failures == 0
        assert runtime.unregister_uncertainties == 0
        cleanup = session.cleanup_report
        assert cleanup.state == "closed"
        assert cleanup.errors == ()
        assert cleanup.broker_stop_attempted is True
        assert cleanup.store_connected is False
        assert cleanup.runtime_state == "closed"
        assert cleanup.runtime_close_attempted is True
        assert cleanup.cleanup_failures == 0
        assert cleanup.unregister_uncertainties == 0

        advanced = any(
            any(
                after.get(registration_id, 0.0) > deadline
                for registration_id, deadline in before.items()
            )
            for before, after in renewals
        )
        assert advanced, "session maintenance did not renew any due registration lease"
    finally:
        _cleanup_after_failed_run(store, runtime)


def test_session_closes_runtime_store_and_host_when_strategy_start_raises(
    local_execution_host,
) -> None:
    """The run's original startup exception survives normal lifecycle cleanup."""

    clock = [0.0]
    endpoint, keys, host = local_execution_host
    runtime = _runtime(endpoint, keys, clock)
    legacy_provider = _ResponseProvider([])
    store = make_store(api=legacy_provider)
    broker = store.getbroker(
        validation_enabled=False,
        cash_check_enabled=False,
        account_refresh_interval=3600.0,
        positions_refresh_interval=3600.0,
        open_orders_refresh_interval=3600.0,
    )
    cerebro = _cerebro_with_feed(broker)
    failure = _StrategyStartFailure("strategy-start-sentinel")
    startup_state = []

    class _FailingStrategy(bt.Strategy):
        def start(self) -> None:
            startup_state.append((store.is_connected, runtime.state))
            raise failure

    cerebro.addstrategy(_FailingStrategy)
    session = ServiceExecutionSession(
        runtime,
        mount="broker.orders",
        scope_ref=_ORDER_SCOPE_REF,
        query_mount="broker.order_query",
        query_scope_ref=_QUERY_SCOPE_REF,
        refresh_interval_seconds=1.0,
        max_refresh_interval_seconds=2.0,
        backoff_factor=2.0,
        limit=8,
        monotonic_clock=lambda: clock[0],
    )

    try:
        with pytest.raises(_StrategyStartFailure) as raised:
            session.run(cerebro)
        assert raised.value is failure
        assert startup_state == [(True, "registered")]
        assert not store.is_connected
        assert store.get_command_health()["shutdown_state"] == "PASS"
        assert legacy_provider.connected is False
        assert legacy_provider.submitted_orders == []
        assert legacy_provider.cancelled_orders == []
        assert runtime.state == "closed"
        assert runtime.cleanup_failures == 0
        assert runtime.unregister_uncertainties == 0
        cleanup = session.cleanup_report
        assert cleanup.state == "closed"
        assert cleanup.errors == ()
        assert cleanup.broker_stop_attempted is True
        assert cleanup.store_connected is False
        assert cleanup.runtime_state == "closed"
        assert cleanup.runtime_close_attempted is True
        assert cleanup.cleanup_failures == 0
        assert cleanup.unregister_uncertainties == 0
        counts = _command(host, "counts")
        assert counts[1:] == ((), (), ())
    finally:
        _cleanup_after_failed_run(store, runtime)


def test_public_configured_example_runs_cerebro_in_a_subprocess() -> None:
    """The published config/CLI entry owns a real client and local host lifecycle."""

    import json
    import subprocess
    import sys
    from pathlib import Path

    repository = Path(__file__).resolve().parents[3]
    config = repository / "examples" / "service_execution_session" / "config.example.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "examples.service_execution_session.run",
            "--config",
            str(config),
        ],
        cwd=repository,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )

    assert completed.returncode == 0, (completed.stdout, completed.stderr)
    assert completed.stderr == ""
    prefix = "SERVICE_EXECUTION_SESSION_DEMO "
    records = [
        line[len(prefix) :]
        for line in completed.stdout.splitlines()
        if line.startswith(prefix)
    ]
    assert len(records) == 1, completed.stdout
    result = json.loads(records[0])
    assert result == {
        "account_cash_snapshot_observed": False,
        "bars_seen": 3,
        "evidence": "LOCAL_SYNTHETIC_PUBLIC_CEREBRO_ENTRY_ONLY",
        "last_close": 103.0,
        "legacy_position_and_order_inputs": "synthetic-empty",
        "provider_cancel_calls": 0,
        "provider_submit_calls": 0,
        "configured_route_count": 2,
        "remaining_runtime_binding_count": 0,
        "runtime_cleanup_failures": 0,
        "runtime_state": "closed",
        "runtime_unregister_uncertainties": 0,
        "service_host_exit_code": 0,
        "service_host_state": "closed",
        "status": "LOCAL_SYNTHETIC_COMPLETED",
        "store_connected_after_run": False,
        "synthetic_provider": "synthetic-no-write",
    }
