import pytest

from backtrader.brokers.hft import ConstantLatencyModel, LatencyEngine, MatchingCore


class DummyData:
    def __init__(self, name):
        self._name = name
        self.name = name
        self.symbol = name


class DummyOrder:
    def __init__(self, name):
        self.data = DummyData(name)


def test_matching_core_indexes_orders_by_symbol():
    core = MatchingCore()
    order_a = DummyOrder("BTC/USDT")
    order_b = DummyOrder("ETH/USDT")

    core.submit_order(order_a, current_ts=0.0)
    core.submit_order(order_b, current_ts=0.0)

    assert core.pending_for_symbol("BTC/USDT") == [order_a]
    assert core.pending_for_symbol("ETH/USDT") == [order_b]
    assert set(core.pending_orders()) == {order_a, order_b}


def test_matching_core_activates_delayed_orders_via_latency_engine():
    engine = LatencyEngine(ConstantLatencyModel(order_entry_latency_ms=500))
    core = MatchingCore(latency_engine=engine)
    order = DummyOrder("BTC/USDT")

    result = core.submit_order(order, current_ts=1.0)

    assert result.action == "ACCEPTED"
    assert core.pending_orders() == []
    assert core.activate_orders(1.25) == []
    assert core.activate_orders(1.6) == [order]
    assert core.pending_for_symbol("BTC/USDT") == [order]


def test_matching_core_cancel_removes_pending_or_delayed_order():
    engine = LatencyEngine(ConstantLatencyModel(order_entry_latency_ms=500))
    delayed_core = MatchingCore(latency_engine=engine)
    delayed_order = DummyOrder("BTC/USDT")
    delayed_core.submit_order(delayed_order, current_ts=1.0)

    delayed_cancel = delayed_core.cancel_order(delayed_order)
    assert delayed_cancel.success is True
    assert delayed_core.activate_orders(2.0) == []

    core = MatchingCore()
    pending_order = DummyOrder("ETH/USDT")
    core.submit_order(pending_order, current_ts=0.0)

    cancel_result = core.cancel_order(pending_order)
    assert cancel_result.success is True
    assert core.pending_for_symbol("ETH/USDT") == []
