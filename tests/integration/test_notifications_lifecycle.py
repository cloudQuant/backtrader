"""Iteration 32 integration: notifications inside a real backtest.

Two things are verified end to end:

1. ``Strategy.send_message`` works from inside ``next``/``nextstart``/``stop``
   with the strategy context and the *backtest* timestamp, and a flush collects
   everything.
2. Enabling notifications changes nothing about the backtest itself - the final
   value and trade statistics are identical with and without them (NFR32-03 /
   AC32-20).
"""

import json

import pytest

import backtrader as bt

from tests.unit.notifications.conftest import FakeTransport, json_response

CSV = "tests/datas/2006-day-001.txt"


def _build_strategy(notify):
    """Return a deterministic strategy class that optionally notifies."""

    class NotifyingStrategy(bt.Strategy):
        """Alternates buy/close every five bars and reports progress."""

        params = (("notify", notify),)

        def __init__(self):
            self.messages = []

        def nextstart(self):
            if self.p.notify:
                self.send_message("minperiod reached", level="info", wait=True)
            self.next()

        def next(self):
            if len(self) % 5:
                return
            if not self.position:
                self.buy(size=10)
            else:
                self.close()

        def stop(self):
            if self.p.notify:
                self.send_message("backtest finished", level="warning", wait=True)

    return NotifyingStrategy


def _run_backtest(notify):
    """Run the fixture backtest and return its metrics."""
    cerebro = bt.Cerebro()
    # The fixture prices are in the thousands, so the default 10k cash cannot
    # fill a 10-share order and the strategy would never trade.
    cerebro.broker.setcash(1_000_000.0)
    cerebro.adddata(
        bt.feeds.GenericCSVData(
            dataname=CSV,
            dtformat="%Y-%m-%d",
            datetime=0,
            open=1,
            high=2,
            low=3,
            close=4,
            volume=5,
            openinterest=-1,
        )
    )
    cerebro.addstrategy(_build_strategy(notify))
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="dd")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
    strategy = cerebro.run()[0]
    analysis = strategy.analyzers.trades.get_analysis()
    return {
        "final_value": round(strategy.broker.getvalue(), 6),
        "closed_trades": int(analysis.get("total", {}).get("closed", 0)),
        "max_drawdown": round(strategy.analyzers.dd.get_analysis()["max"]["drawdown"], 6),
        "sharpe": round(strategy.analyzers.sharpe.get_analysis().get("sharperatio") or 0.0, 6),
        "bars": len(strategy),
    }


@pytest.fixture(autouse=True)
def _cleanup():
    """Reset the notification singleton around each test."""
    bt.reset_notifications()
    yield
    bt.reset_notifications()


def test_notifications_do_not_change_backtest_metrics():
    """Metrics are byte-identical with and without notifications."""
    baseline = _run_backtest(notify=False)
    assert baseline["closed_trades"] > 0, "the fixture must actually trade"

    transport = FakeTransport(default=json_response({"errcode": 0}))
    bt.configure_notifications([{"channel": "ntfy", "topic": "integration"}], transport=transport)
    instrumented = _run_backtest(notify=True)
    assert bt.flush_notifications(timeout=10.0) is True
    assert instrumented == baseline

    assert transport.requests, "instrumented run must actually deliver notifications"
    assert bt.notification_stats()["ntfy"]["sent"] == 2
    assert bt.notification_stats()["ntfy"]["failed"] == 0


def test_lifecycle_messages_carry_strategy_context_and_backtest_time():
    """Messages carry the strategy name, level prefix and backtest timestamp."""
    transport = FakeTransport(default=json_response({"errcode": 0}))
    bt.configure_notifications([{"channel": "ntfy", "topic": "integration"}], transport=transport)
    _run_backtest(notify=True)
    assert bt.flush_notifications(timeout=10.0) is True

    messages = [
        json.loads(request.body.decode("utf-8"))["message"] for request in transport.requests
    ]
    assert len(messages) == 2
    assert any("[INFO] NotifyingStrategy" in message for message in messages)
    assert any("[WARNING] NotifyingStrategy" in message for message in messages)
    assert all("2006-" in message for message in messages), "backtest time, not wall clock"
    assert all("minperiod reached" in m or "backtest finished" in m for m in messages)


def test_failing_channel_leaves_the_backtest_untouched():
    """A channel that always fails must not perturb the run."""

    def handler(request):
        raise ConnectionError("no route to host")

    baseline = _run_backtest(notify=False)
    transport = FakeTransport(handler=handler)
    bt.configure_notifications([{"channel": "ntfy", "topic": "integration"}], transport=transport)
    instrumented = _run_backtest(notify=True)
    assert instrumented == baseline
    assert bt.notification_stats()["ntfy"]["failed"] == 2


def test_not_configured_strategy_runs_are_still_clean():
    """Without configuration the instrumented strategy behaves like the baseline."""
    assert _run_backtest(notify=True) == _run_backtest(notify=False)
