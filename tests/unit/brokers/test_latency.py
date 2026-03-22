import pytest

from backtrader.brokers.hft import ConstantLatencyModel, IntpLatencyModel, LatencyEngine
from backtrader.events import TickEvent


def test_constant_latency_model_returns_fixed_values():
    model = ConstantLatencyModel(
        feed_latency_ms=100,
        order_entry_latency_ms=200,
        order_response_latency_ms=300,
    )

    assert model.feed_latency(1.0, "BTC/USDT") == pytest.approx(0.1)
    assert model.order_entry_latency(1.0, "BTC/USDT") == pytest.approx(0.2)
    assert model.order_response_latency(1.0, "BTC/USDT") == pytest.approx(0.3)


def test_latency_engine_applies_feed_latency_and_activates_delayed_orders():
    engine = LatencyEngine(ConstantLatencyModel(feed_latency_ms=50, order_entry_latency_ms=200))
    event = TickEvent(timestamp=1.0, symbol="BTC/USDT", price=100.0, volume=1.0)

    engine.delay_order(object(), 1.0, "BTC/USDT")
    delayed = engine.get_visible_orders(1.1)
    ready = engine.get_visible_orders(1.21)
    event = engine.apply_feed_latency(event)

    assert delayed == []
    assert len(ready) == 1
    assert event.local_time == pytest.approx(1.05)


def test_intp_latency_model_interpolates_between_points():
    model = IntpLatencyModel(
        [
            (1.0, 0.1, 0.2, 0.3),
            (3.0, 0.3, 0.6, 0.9),
        ]
    )

    assert model.feed_latency(2.0, "BTC/USDT") == pytest.approx(0.2)
    assert model.order_entry_latency(2.0, "BTC/USDT") == pytest.approx(0.4)
    assert model.order_response_latency(2.0, "BTC/USDT") == pytest.approx(0.6)
