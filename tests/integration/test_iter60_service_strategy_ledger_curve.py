"""Iteration 60 R2-E: a BT strategy in service mode against a host-owned strategy ledger.

A spawned SDK ``ServiceHost`` (real CURVE/ZMQ, strict MessagePack envelopes)
runs the execution ``account_owner`` with typed ``command_bindings`` and the
``strategy_ledger`` option. In this process, Backtrader:

* sizes with ``Strategy.order_target_value`` from the service strategy book
  (``ServiceStrategyAccountBookView`` over the registered runtime route);
* submits the resulting order through ``ServiceExecutionAdapter`` with the
  SDK typed execution client (``assemble_service_execution``);
* values the book with ``value_strategy_book`` once the host reports the fill
  and the account position subscription shows it (``BALANCED``), and refuses
  ``IN_FLIGHT``/``RESIDUAL``/``UNVERIFIED`` books.

The host's synthetic provider accepts orders; fills, fees and the position
subscription are driven through the control pipe. INTEGRATION_SIM: local
subprocess, temp SQLite, CURVE on 127.0.0.1; no real account, provider or
network. Not covered here: ``ServiceExecutionSession``/Cerebro run loop and
the ``BtApiBroker`` refresh path (orders are submitted through the adapter
directly).
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("zmq")
pytest.importorskip("msgpack")
pytest.importorskip("bt_api_execution")
pytest.importorskip("bt_api_py.service_strategy_ledger_host")

import backtrader as bt  # noqa: E402
from backtrader.service.service_execution_adapter import ServiceExecutionAdapter  # noqa: E402
from backtrader.service.service_strategy_account_book import (  # noqa: E402
    ServiceStrategyAccountBookError,
    ServiceStrategyAccountBookView,
    value_strategy_book,
)
from bt_api_py.service_execution_assembly import assemble_service_execution  # noqa: E402
from tests.unit import test_iter60_live_mark_eligibility as marks  # noqa: E402
from tests.unit import test_iter60_service_strategy_valuation as valuation  # noqa: E402

_HERE = Path(__file__).resolve().parent


def _support():
    if str(_HERE) not in sys.path:
        sys.path.insert(0, str(_HERE))
    import iter60_service_ledger_host_support as support

    return support


def _order(intent_id: str, size: float, price: float, effect: str):
    t = _support()
    return SimpleNamespace(
        info={
            "managed_intent_id": intent_id,
            "managed_signal_id": "signal-" + intent_id,
            "managed_instrument": t.INSTRUMENT,
            "managed_position_effect": effect,
            "managed_metadata_version": "bt-r2e-metadata-v1",
        },
        exectype=bt.Order.Limit,
        created=SimpleNamespace(size=size, price=price),
        size=size,
        isbuy=lambda: size > 0,
    )


@pytest.fixture
def session(tmp_path):
    t = _support()
    host = t.Host(tmp_path)
    assert host.ready[0] == "ready", host.ready
    assembly = None
    try:
        assembly = assemble_service_execution(
            t.client_config(host.endpoint), runtime_factory=t.runtime_factory(host.keys)
        )
        assembly.claim_owned_runtimes()
        assembly.start()
        view = ServiceStrategyAccountBookView(
            assembly.runtime,
            mount="broker.order_query",
            scope_ref=t.QUERY_SCOPE_REF,
            strategy_ref=t.STRATEGY,
            account_ref=t.ACCOUNT,
        )
        adapter = ServiceExecutionAdapter(assembly.execution_client)
        yield SimpleNamespace(host=host, view=view, adapter=adapter, t=t)
    finally:
        if assembly is not None and assembly.state not in {"unclaimed", "released"}:
            assembly.close()
        if not getattr(host, "closed", False):
            host.close()


def _strategy(view):
    t = _support()
    feed, _clock = marks._feed(name=t.INSTRUMENT, close=50000.0)
    strategy, orders = valuation._strategy(view, [feed])
    return strategy, orders, feed


@pytest.mark.integration
def test_service_strategy_ledger_end_to_end_over_curve(session):
    s, t = session, session.t
    strategy, orders, feed = _strategy(s.view)

    # Empty book: BALANCED against an empty, complete subscription snapshot.
    snapshot = s.view.snapshot()
    assert snapshot.reconciliation_state == "BALANCED"
    assert snapshot.position_cut_id == snapshot.financial_cut_id
    strategy.order_target_value(data=feed, target=100000.0)
    assert orders == [("buy", 2.0)]

    # The BT order goes out as one typed command; the ledger admits it.
    projection = s.adapter.submit_order(_order("bt-buy-1", 2.0, 50000.0, "OPEN"), None)
    assert projection["status"] != "rejected", projection
    # Over budget (5 x 50000 > 200000): refused by the host ledger before the
    # journal saw it. The reply states "not journaled, not dispatched"
    # (iteration 60 R3), so the order is a definitive BT rejection, never UNKNOWN.
    refused = s.adapter.submit_order(_order("bt-buy-big", 5.0, 50000.0, "OPEN"), None)
    assert refused["error_code"] == "BUDGET_EXCEEDED", refused
    assert refused["status"] == "rejected", refused
    assert refused.get("execution_unknown") is not True
    assert refused.get("service_execution_state") != "UNKNOWN"

    # The provider fills; the subscription has not shown it yet: IN_FLIGHT.
    assert s.host.command("fill", "bt-buy-1", "FILLED", "2", "50000", "2") == "FILLED"
    with pytest.raises(ValueError, match="STRATEGY_BOOK_RECONCILIATION_IN_FLIGHT"):
        strategy.order_target_value(data=feed, target=50000.0)

    # The subscription shows the fill: BALANCED, valued from one ledger cut.
    s.host.command("positions", {t.INSTRUMENT: "2"})
    snapshot = s.view.snapshot()
    assert snapshot.reconciliation_state == "BALANCED"
    assert snapshot.position_cut_id == snapshot.financial_cut_id
    book = value_strategy_book(
        snapshot,
        marks={t.INSTRUMENT: Decimal("50000")},
        multipliers={t.INSTRUMENT: Decimal("1")},
    )
    assert book.cash == Decimal("99998")  # 200000 - 2 x 50000 - fee 2
    assert book.equity == Decimal("199998")
    assert book.positions == {t.INSTRUMENT: Decimal("2")}
    orders.clear()
    strategy.order_target_value(data=feed, target=50000.0)
    assert orders == [("sell", 1.0)]

    # A close beyond the strategy's own position is refused by the ledger.
    flip = s.adapter.submit_order(_order("bt-sell-3", -3.0, 50000.0, "CLOSE"), None)
    assert flip["error_code"] == "POSITION_FLIP_REFUSED", flip
    assert flip["status"] == "rejected", flip
    close = s.adapter.submit_order(_order("bt-sell-1", -1.0, 50000.0, "CLOSE"), None)
    assert close["status"] != "rejected", close
    # While the close is pending, a difference on its instrument is IN_FLIGHT.
    s.host.command("positions", {t.INSTRUMENT: "1"})
    with pytest.raises(ValueError, match="STRATEGY_BOOK_RECONCILIATION_IN_FLIGHT"):
        strategy.order_target_value(data=feed, target=50000.0)
    assert s.host.command("fill", "bt-sell-1", "FILLED", "1", "50000", "1") == "FILLED"
    s.host.command("positions", {t.INSTRUMENT: "1"})
    book = value_strategy_book(
        s.view.snapshot(),
        marks={t.INSTRUMENT: Decimal("50000")},
        multipliers={t.INSTRUMENT: Decimal("1")},
    )
    assert book.cash == Decimal("149997")  # + 1 x 50000 - fee 1
    assert book.positions == {t.INSTRUMENT: Decimal("1")}

    # Activity the ledger cannot explain: RESIDUAL, nothing is valued.
    s.host.command("positions", {t.INSTRUMENT: "7"})
    with pytest.raises(ServiceStrategyAccountBookError, match="RESIDUAL"):
        s.view.snapshot()
    with pytest.raises(ValueError, match="RESIDUAL"):
        strategy.order_target_value(data=feed, target=50000.0)

    # The subscription loses continuity: UNVERIFIED.
    s.host.command("interrupt")
    with pytest.raises(ServiceStrategyAccountBookError, match="UNVERIFIED"):
        s.view.snapshot()
    assert orders == [("sell", 1.0)]
    # Only admitted orders reached the provider.
    assert s.host.close() == ["bt-buy-1", "bt-sell-1"]
    s.host.closed = True


@pytest.mark.integration
def test_a_dispatch_time_timeout_stays_unknown_and_is_never_rejected(session):
    """The provider call outlives the client's request timeout: UNKNOWN, not Rejected."""

    s, t = session, session.t
    slow = s.adapter.submit_order(_order(t.SLOW_PREFIX + "1", 1.0, 50000.0, "OPEN"), None)
    assert slow["status"] == "pending", slow
    assert slow["execution_unknown"] is True
    assert slow["service_execution_state"] == "UNKNOWN"
    assert slow["error_code"] != "BUDGET_EXCEEDED"
    # The host did dispatch it: a definitive rejection would have been wrong.
    assert s.host.close() == [t.SLOW_PREFIX + "1"]
    s.host.closed = True


@pytest.mark.integration
def test_host_refuses_a_ledger_without_subscription_evidence(tmp_path):
    t = _support()
    host = t.Host(tmp_path, mode="no_positions")
    try:
        assert host.ready == ("error", "STRATEGY_LEDGER_POSITIONS_REQUIRED")
    finally:
        host.kill()
