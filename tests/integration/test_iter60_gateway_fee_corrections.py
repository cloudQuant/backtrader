"""Iteration 60 R3: fill fees and late fee corrections in Gateway mode, as in direct.

The Gateway account owner's producer publishes trade observations with the
provider fee of each fill (Base execution event v2). A later report of an
applied fill with a higher fee is a new Gateway event; ``BtApiBroker``
projects it through the direct repeated-fill path, so the Strategy's
``notify_fee_correction`` fires with the same delta and currency as for the
direct-mode Store rows, and the strategy ledger books the same fee totals. A
lower fee is refused by the Gateway producer before anything is published.
INTEGRATION_SIM: local SQLite, in-process co-located Gateway read service, no
provider or network.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("bt_api_py.service_execution_event_consumer")
pytest.importorskip("bt_api_gateway.execution_event_publisher")

_HERE = Path(__file__).resolve().parent

#: SELL 2 @1500 of strategy A: two fills with fees, then a late correction of
#: the first fill's fee (0.5 -> 0.8 CNY) after the order is terminal.
_FEES = {"t-1": "0.5", "t-2": "0.5"}
_CORRECTED = ("t-1", "o-1", "1", "1500", "0.8")


def _support():
    import sys

    if str(_HERE) not in sys.path:
        sys.path.insert(0, str(_HERE))
    import iter60_gateway_execution_support as support

    return support


def _fee_trade(t, trade_id, order_id, quantity, price, fee):
    from bt_api_base.execution_row_observation_protocol import AccountExecutionTradeObservation

    base = t.trade_obs(trade_id, order_id, quantity, price)
    return AccountExecutionTradeObservation(base.account_key, base.trade, fee, "CNY")


def _record_corrections(strategy, sink):
    def notify_fee_correction(order, trade, delta, currency):
        sink.append((order.ref is not None, round(float(delta), 10), currency))

    strategy.notify_fee_correction = notify_fee_correction


def _direct(directory):
    t = _support()
    s = t.stack(directory, "direct")
    corrections = []
    _record_corrections(s.a, corrections)
    order = t.place(s)
    t.cycle(s)
    rows = t.direct_rows(order)
    for row in rows:
        if row["kind"] == "trade":
            row.update(fee=_FEES[row["trade_id"]], fee_currency="CNY", fee_unit="currency")
    trade_id, order_id, quantity, price, fee = _CORRECTED
    late = dict(next(r for r in rows if r.get("trade_id") == trade_id))
    late.update(fee=fee)
    for row in [*rows, late]:
        s.store.rows.append(row)
        s.broker.next()
        t.cycle(s)
    return s, corrections


def _gateway(directory):
    t = _support()
    s = t.stack(directory, "gateway")
    corrections = []
    _record_corrections(s.a, corrections)
    t.place(s)
    t.cycle(s)
    items = []
    for step in t.SCRIPT:
        if step[0] == "order":
            items.append(t.order_obs(*step[1:]))
        else:
            items.append(_fee_trade(t, *step[1:], _FEES[step[1]]))
    items.append(_fee_trade(t, *_CORRECTED))
    for item in items:
        t.publish(directory / "gateway.sqlite3", [item])
        s.broker.next()
        t.cycle(s)
    return s, corrections


def _fees(s):
    return dict(s.ledger.snapshot("strategy-a").fees_since_baseline)


@pytest.mark.integration
def test_gateway_fee_correction_matches_direct(tmp_path):
    t = _support()
    direct, direct_corrections = _direct(tmp_path / "direct")
    gateway, gateway_corrections = _gateway(tmp_path / "gateway")
    try:
        assert direct_corrections == [(True, 0.3, "CNY")]
        assert gateway_corrections == direct_corrections
        shapes = t.shapes(gateway.received)
        assert shapes == t.shapes(direct.received)
        assert ("order", "Completed") in shapes
        assert t.position(gateway) == t.position(direct) == Decimal("0")
        assert _fees(gateway) == _fees(direct)
        assert Decimal(str(_fees(gateway)["CNY"])) == Decimal("1.3")
        state = gateway.broker.gateway_execution_events_state(gateway.a)
        assert state["state"] == "ACTIVE" and state["applied"] == 6
    finally:
        for s in (direct, gateway):
            s.broker.close_gateway_execution_events()
            s.broker.close_strategy_notification_recovery()
            s.ledger.close()


@pytest.mark.integration
def test_a_lower_fill_fee_is_refused_by_the_gateway_producer(tmp_path):
    from bt_api_gateway.execution_event_publisher import GatewayExecutionEventError

    t = _support()
    path = tmp_path / "gateway.sqlite3"
    t.publish(path, [t.order_obs("o-1", "sa-1", "open", "0", "2")])
    t.publish(path, [_fee_trade(t, "t-1", "o-1", "1", "1500", "0.5")])
    with pytest.raises(GatewayExecutionEventError) as refused:
        t.publish(path, [_fee_trade(t, "t-1", "o-1", "1", "1500", "0.4")])
    assert refused.value.code == "EXECUTION_FEE_REGRESSED"
