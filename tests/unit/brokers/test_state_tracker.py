import pytest

from backtrader.brokers.hft import StateTracker


def test_state_tracker_tracks_fill_aggregates_and_snapshot():
    tracker = StateTracker()
    tracker.on_fill("BTC/USDT", 100.0, 2.0, 0.5)
    tracker.on_fill("BTC/USDT", 110.0, -1.0, 0.25)

    snapshot = tracker.snapshot("BTC/USDT", position=1.0, balance=1000.0, mid_price=111.0)

    assert snapshot["fee"] == pytest.approx(0.75)
    assert snapshot["num_trades"] == 2
    assert snapshot["trading_volume"] == pytest.approx(3.0)
    assert snapshot["trading_value"] == pytest.approx(310.0)
    assert snapshot["equity"] == pytest.approx(1111.0)


def test_state_tracker_snapshot_all_and_reset():
    tracker = StateTracker()
    tracker.on_fill("BTC/USDT", 100.0, 1.0, 0.1)
    tracker.on_fill("ETH/USDT", 200.0, 2.0, 0.2)

    values = tracker.snapshot_all(
        positions={"BTC/USDT": 1.0, "ETH/USDT": 2.0},
        balance_by_symbol={"BTC/USDT": 1000.0, "ETH/USDT": 500.0},
        mid_prices={"BTC/USDT": 101.0, "ETH/USDT": 210.0},
    )

    assert values["BTC/USDT"]["equity"] == pytest.approx(1101.0)
    assert values["ETH/USDT"]["equity"] == pytest.approx(920.0)

    tracker.reset()
    assert tracker.snapshot_all({}, {}, {}) == {}
