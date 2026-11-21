"""Exercise deferred reverse and protection using the real strategy and broker."""

import importlib.util
import math
import sys
from pathlib import Path

import pandas as pd
import pytest

import backtrader as bt


def strategy_class():
    path = (
        Path(__file__).resolve().parents[3]
        / "tests/functional/strategies/mean_reversion/test_0081_0260_exp_trendmanager_tm_plus.py"
    )
    spec = importlib.util.spec_from_file_location("trend_pending_real_strategy", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.ExpTrendManagerTmPlusStrategy


def run_case(mode, kind, stride=1):
    n = 40 * stride
    dates = pd.date_range("2024-01-01", periods=n, freq="min")
    prices = [100.0] * n
    signal = [100.0 + i for i in range(n)]
    if kind not in ("pending_valid", "fresh_close", "canceled_close"):
        signal[12 * stride] = math.nan
    if kind == "pending_notify":
        for i in range(13 * stride, n):
            signal[i] = 200.0 - i
    highs, lows = [101.0] * n, [99.0] * n
    if kind == "stop":
        lows[12] = 79.0
    if kind == "limit":
        highs[12] = 161.0
    execution = pd.DataFrame(
        {
            "open": prices,
            "high": highs,
            "low": lows,
            "close": prices,
            "volume": [1.0] * n,
        },
        index=dates,
    )
    source = pd.DataFrame(
        {
            "open": prices,
            "high": prices,
            "low": prices,
            "close": signal,
            "volume": [1.0] * n,
        },
        index=dates,
    ).iloc[::stride]

    class Trace(strategy_class()):
        def __init__(self):
            super().__init__()
            self.events = []
            self.injected = set()

        def log(self, text):
            pass

        def _submit_entry(self, side, reason):
            self.events.append(
                (
                    "entry",
                    len(self.signal_data),
                    side,
                    reason,
                    float(self.indicator.color_state[0]),
                )
            )
            return super()._submit_entry(side, reason)

        def _submit_close(self, reason, reverse=None):
            self.events.append(
                (
                    "close",
                    len(self.signal_data),
                    reason,
                    float(self.indicator.color_state[0]),
                )
            )
            return super()._submit_close(reason, reverse)

        def notify_order(self, order):
            if order.status == order.Completed:
                role = (
                    "stop"
                    if order == self.stop_order
                    else "limit"
                    if order == self.limit_order
                    else "close"
                    if order == self.close_order
                    else "entry"
                )
                self.events.append(
                    (
                        "filled",
                        len(self.signal_data),
                        role,
                        float(order.executed.size),
                        float(self.indicator.color_state[0]),
                    )
                )
            super().notify_order(order)
            if order.status == order.Canceled:
                self.events.append(
                    (
                        "canceled_state",
                        self.pending_reverse,
                        self._pending_reverse_deferred,
                    )
                )

        def next(self):
            bar = len(self.signal_data)
            if (
                kind in ("pending_next", "pending_valid")
                and bar == 13
                and bar not in self.injected
            ):
                self.injected.add(bar)
                self.pending_reverse = "short" if kind == "pending_valid" else "long"
            if (
                kind
                in (
                    "pending_notify",
                    "time",
                    "stop",
                    "limit",
                    "fresh_close",
                    "canceled_close",
                )
                and bar == 10
                and bar not in self.injected
            ):
                self.injected.add(bar)
                self._submit_entry("long", "fixture preexisting position")
            if (
                kind in ("pending_notify", "fresh_close", "canceled_close")
                and bar == 12
                and len(self.exec_data) % stride == 0
                and bar not in self.injected
            ):
                self.injected.add(bar)
                if kind == "fresh_close":
                    self._pending_reverse_deferred = True
                self._submit_close("fixture reversal", reverse="short")
                if kind == "canceled_close":
                    self._pending_reverse_deferred = True
                    self.cancel(self.close_order)
            super().next()

    c = bt.Cerebro(stdstats=False, runonce=mode)
    c.adddata(bt.feeds.PandasData(dataname=execution))
    c.adddata(bt.feeds.PandasData(dataname=source))
    c.addstrategy(
        Trace, length1=2, length2=3, time_trade=kind == "time", hold_minutes=1
    )
    return c.run(preload=True)[0]


@pytest.mark.parametrize("mode", [False, True])
@pytest.mark.parametrize("kind", ["pending_next", "pending_notify"])
@pytest.mark.parametrize("stride", [1, 2])
def test_deferred_reverse_waits_until_both_colors_recover(mode, kind, stride):
    s = run_case(mode, kind, stride=stride)
    reverse = [e for e in s.events if e[0] == "entry" and e[3] == "reverse after close"]
    assert len(reverse) == 1, s.events
    assert reverse[0][1] == 17, s.events
    assert not math.isnan(reverse[0][4])
    if kind == "pending_notify":
        assert any(
            e[:3] == ("filled", 13, "close") and math.isnan(e[4]) for e in s.events
        ), s.events
    assert s.pending_reverse is None


@pytest.mark.parametrize("mode", [False, True])
@pytest.mark.parametrize(
    "kind,role", [("time", "close"), ("stop", "stop"), ("limit", "limit")]
)
def test_missing_color_preserves_existing_protective_exit(mode, kind, role):
    s = run_case(mode, kind)
    assert any(e[:3] == ("filled", 11, "entry") for e in s.events), s.events
    exit_fills = [e for e in s.events if e[0] == "filled" and e[2] == role]
    assert len(exit_fills) == 1, s.events
    assert exit_fills[0][1] == (14 if kind == "time" else 13), s.events
    if kind == "time":
        assert any(
            e[:3] == ("close", 13, "time trade expiry") and math.isnan(e[3])
            for e in s.events
        ), s.events
    else:
        assert math.isnan(exit_fills[0][4]), s.events
    assert not s.position


@pytest.mark.parametrize("mode", [False, True])
@pytest.mark.parametrize("initial_side", ["long", "short"])
@pytest.mark.parametrize("matching", [False, True])
def test_real_delayed_reversal_requires_matching_recovered_color(
    mode, initial_side, matching
):
    n = 35
    dates = pd.date_range("2024-01-01", periods=n, freq="min")
    base = [100.0] * n
    recovery = (
        [80.0 - i for i in range(n - 11)]
        if matching
        else [160.0 + i for i in range(n - 11)]
    )
    signal = [100.0 + i for i in range(9)] + [90.0, math.nan] + recovery
    if initial_side == "short":
        signal = [200.0 - x for x in signal]
    execution = pd.DataFrame(
        {
            "open": base,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": base,
            "volume": [1.0] * n,
        },
        index=dates,
    )
    source = pd.DataFrame(
        {"open": base, "high": base, "low": base, "close": signal, "volume": [1.0] * n},
        index=dates,
    )

    class Trace(strategy_class()):
        def __init__(self):
            super().__init__()
            self.events = []
            self.forced = False

        def log(self, text):
            pass

        def _submit_entry(self, side, reason):
            self.events.append(
                (
                    "entry",
                    len(self.signal_data),
                    side,
                    reason,
                    float(self.indicator.color_state[0]),
                )
            )
            return super()._submit_entry(side, reason)

        def _submit_close(self, reason, reverse=None):
            self.events.append(
                (
                    "close",
                    len(self.signal_data),
                    reverse,
                    float(self.indicator.color_state[0]),
                )
            )
            return super()._submit_close(reason, reverse)

        def notify_order(self, order):
            if order.status == order.Completed:
                self.events.append(
                    (
                        "filled",
                        len(self.signal_data),
                        float(order.executed.size),
                        float(self.indicator.color_state[0]),
                    )
                )
            super().notify_order(order)

        def next(self):
            if len(self.signal_data) == 8 and not self.forced:
                self.forced = True
                self._submit_entry(initial_side, "fixture initial position")
            super().next()

    c = bt.Cerebro(stdstats=False, runonce=mode)
    c.adddata(bt.feeds.PandasData(dataname=execution))
    c.adddata(bt.feeds.PandasData(dataname=source))
    c.addstrategy(Trace, length1=2, length2=3, time_trade=False)
    s = c.run(preload=True)[0]
    reverse_side = "short" if initial_side == "long" else "long"
    assert any(e[:3] == ("close", 10, reverse_side) for e in s.events), s.events
    assert any(
        e[0] == "filled" and e[1] == 11 and math.isnan(e[3]) for e in s.events
    ), s.events
    reverse = [e for e in s.events if e[0] == "entry" and e[3] == "reverse after close"]
    if matching:
        assert len(reverse) == 1 and reverse[0][1:3] == (15, reverse_side), s.events
        assert s.position.size == pytest.approx(0.1 if reverse_side == "long" else -0.1)
    else:
        assert not reverse, s.events
        assert not s.position
    assert s.pending_reverse is None


@pytest.mark.parametrize("mode", [False, True])
def test_undeferred_pending_retains_existing_finite_behavior(mode):
    s = run_case(mode, "pending_valid")
    reverse = [e for e in s.events if e[0] == "entry" and e[3] == "reverse after close"]
    assert len(reverse) == 1 and reverse[0][1:3] == (13, "short"), s.events


@pytest.mark.parametrize("mode", [False, True])
def test_new_close_resets_old_deferral_flag(mode):
    s = run_case(mode, "fresh_close")
    reverse = [e for e in s.events if e[0] == "entry" and e[3] == "reverse after close"]
    assert len(reverse) == 1 and reverse[0][1:3] == (13, "short"), s.events


@pytest.mark.parametrize("mode", [False, True])
def test_canceled_close_clears_pending_and_deferral_flag(mode):
    s = run_case(mode, "canceled_close")
    assert ("canceled_state", None, False) in s.events, s.events
    assert not [
        e for e in s.events if e[0] == "entry" and e[3] == "reverse after close"
    ]
    assert s.pending_reverse is None and not s._pending_reverse_deferred


@pytest.mark.parametrize("mode", [False, True])
@pytest.mark.parametrize("stride", [1, 2])
@pytest.mark.parametrize("already_consumed", [False, True])
@pytest.mark.parametrize("direction", ["long", "short"])
def test_cancel_stale_pending_processes_new_flip_once_per_signal_clock(
    mode, stride, already_consumed, direction
):
    n = 35
    dates = pd.date_range("2024-01-01", periods=n * stride, freq="min")
    base = [100.0] * (n * stride)
    source_base = [100.0] * n
    prices = (
        [100.0 + i for i in range(9)]
        + [90.0, math.nan, 80.0, 79.0, 78.0]
        + [200.0 + i for i in range(n - 14)]
    )
    if direction == "short":
        prices = [200.0 - x for x in prices]
    execution = pd.DataFrame(
        {
            "open": base,
            "high": [101.0] * (n * stride),
            "low": [99.0] * (n * stride),
            "close": base,
            "volume": [1.0] * (n * stride),
        },
        index=dates,
    )
    source = pd.DataFrame(
        {
            "open": source_base,
            "high": source_base,
            "low": source_base,
            "close": prices,
            "volume": [1.0] * n,
        },
        index=dates[::stride],
    )

    class Trace(strategy_class()):
        def __init__(self):
            super().__init__()
            self.entries = []
            self.injected = False

        def log(self, text):
            pass

        def _submit_entry(self, side, reason):
            self.entries.append(
                (len(self.signal_data), len(self.exec_data), side, reason)
            )
            return super()._submit_entry(side, reason)

        def next(self):
            bar = len(self.signal_data)
            self.p.buy_pos_open = bar >= 12
            self.p.sell_pos_open = bar >= 12
            if bar == 12 and not self.injected:
                self.injected = True
                self.pending_reverse = "short" if direction == "long" else "long"
            if bar == 15 and already_consumed:
                self.last_signal_dt = bt.num2date(self.signal_data.datetime[0])
            super().next()

    c = bt.Cerebro(stdstats=False, runonce=mode)
    c.adddata(bt.feeds.PandasData(dataname=execution))
    c.adddata(bt.feeds.PandasData(dataname=source))
    c.addstrategy(Trace, length1=2, length2=3, time_trade=False)
    s = c.run(preload=True)[0]
    assert s.pending_reverse is None
    if already_consumed:
        assert s.entries == [], s.entries
        assert not s.position
    else:
        assert len(s.entries) == 1, s.entries
        expected_reason = (
            "trendmanager color flip up"
            if direction == "long"
            else "trendmanager color flip down"
        )
        assert s.entries[0][0] == 15 and s.entries[0][2:] == (
            direction,
            expected_reason,
        ), s.entries
        assert s.position.size == pytest.approx(0.1 if direction == "long" else -0.1)


def run_margin_case(mode, stride, direction, zero_size=False):
    n = 35
    dates = pd.date_range("2024-01-01", periods=n * stride, freq="min")
    base = [100.0] * (n * stride)
    source_base = [100.0] * n
    values = (
        [100.0 + i for i in range(9)]
        + [90.0, math.nan, 120.0, 121.0, 122.0, 80.0]
        + [79.0 - i for i in range(n - 15)]
    )
    if direction == "long":
        values = [200.0 - x for x in values]
    execution = pd.DataFrame(
        {
            "open": base,
            "high": [101.0] * (n * stride),
            "low": [99.0] * (n * stride),
            "close": base,
            "volume": [1.0] * (n * stride),
        },
        index=dates,
    )
    source = pd.DataFrame(
        {
            "open": source_base,
            "high": source_base,
            "low": source_base,
            "close": values,
            "volume": [1.0] * n,
        },
        index=dates[::stride],
    )

    class Trace(strategy_class()):
        def __init__(self):
            super().__init__()
            self.entries = []
            self.margins = []
            self.clocks = []
            self.injected = False

        def log(self, text):
            pass

        def _submit_entry(self, side, reason):
            self.entries.append(
                (len(self.signal_data), len(self.exec_data), side, reason)
            )
            return super()._submit_entry(side, reason)

        def notify_order(self, order):
            if order.status == order.Margin and order == self.entry_order:
                self.margins.append((len(self.signal_data), len(self.exec_data)))
            super().notify_order(order)

        def next(self):
            nbar = len(self.signal_data)
            self.p.buy_pos_open = nbar >= 12
            self.p.sell_pos_open = nbar >= 12
            if nbar == 12 and not self.injected:
                self.injected = True
                self.pending_reverse = direction
            super().next()
            if nbar == 15:
                current = bt.num2date(self.signal_data.datetime[0])
                self.clocks.append(self.last_signal_dt == current)

    c = bt.Cerebro(stdstats=False, runonce=mode)
    c.broker.setcash(0.01)
    c.broker.setcommission(
        commission=0.0,
        margin=1000,
        mult=100,
        commtype=bt.CommInfoBase.COMM_FIXED,
        stocklike=False,
    )
    c.adddata(bt.feeds.PandasData(dataname=execution))
    c.adddata(bt.feeds.PandasData(dataname=source))
    kwargs = {"length1": 2, "length2": 3, "time_trade": False}
    if zero_size:
        kwargs.update(mm=0.0, lot_min=0.0)
    c.addstrategy(Trace, **kwargs)
    return c.run(preload=True)[0]


@pytest.mark.parametrize("mode", [False, True])
@pytest.mark.parametrize("stride", [1, 2])
@pytest.mark.parametrize("direction", ["long", "short"])
def test_deferred_margin_rejection_does_not_resubmit_same_signal_bar(
    mode, stride, direction
):
    s = run_margin_case(mode, stride, direction)
    assert len(s.entries) == 1, s.entries
    assert s.entries[0][0] == 15 and s.entries[0][2:] == (
        direction,
        "reverse after close",
    ), s.entries
    assert len(s.margins) == 1 and s.margins[0][0] == (16 if stride == 1 else 15), (
        s.margins
    )
    assert s.clocks and s.clocks[0]
    assert not s.position and s.pending_reverse is None


@pytest.mark.parametrize("mode", [False, True])
def test_no_order_created_does_not_consume_recovery_signal_clock(mode):
    s = run_margin_case(mode, 2, "short", zero_size=True)
    assert s.clocks[:2] == [False, True], s.clocks
    assert not s.margins and not s.position


@pytest.mark.parametrize("mode", [False, True])
@pytest.mark.parametrize("stride", [1, 2])
def test_natural_delayed_reverse_margin_is_not_resent(mode, stride):
    n = 35
    dates = pd.date_range("2024-01-01", periods=n * stride, freq="min")
    base = [100.0] * (n * stride)
    sigbase = [100.0] * n
    values = (
        [100.0 + i for i in range(9)]
        + [90.0, math.nan, 120.0, 121.0, 122.0, 80.0]
        + [79.0 - i for i in range(n - 15)]
    )
    execution = pd.DataFrame(
        {
            "open": base,
            "high": [101.0] * (n * stride),
            "low": [99.0] * (n * stride),
            "close": base,
            "volume": [1.0] * (n * stride),
        },
        index=dates,
    )
    source = pd.DataFrame(
        {
            "open": sigbase,
            "high": sigbase,
            "low": sigbase,
            "close": values,
            "volume": [1.0] * n,
        },
        index=dates[::stride],
    )

    class Trace(strategy_class()):
        def __init__(self):
            super().__init__()
            self.entries = []
            self.closes = []
            self.fills = []
            self.margins = []
            self.opened = False
            self.cash_reduced = False

        def log(self, text):
            pass

        def _submit_entry(self, side, reason):
            self.entries.append((len(self.signal_data), side, reason))
            return super()._submit_entry(side, reason)

        def _submit_close(self, reason, reverse=None):
            self.closes.append((len(self.signal_data), reason, reverse))
            return super()._submit_close(reason, reverse)

        def notify_order(self, order):
            if order.status == order.Completed:
                self.fills.append(
                    (
                        len(self.signal_data),
                        float(order.executed.size),
                        float(self.indicator.color_state[0]),
                    )
                )
            if order.status == order.Margin and order == self.entry_order:
                self.margins.append((len(self.signal_data), len(self.exec_data)))
            super().notify_order(order)

        def next(self):
            bar = len(self.signal_data)
            if bar == 8 and not self.opened:
                self.opened = True
                self._submit_entry("long", "fixture existing position")
            if bar == 14 and not self.cash_reduced:
                self.cash_reduced = True
                self.broker.setcash(0.01)
            super().next()

    def filler(order, price, ago):
        if (
            order.issell()
            and order.exectype == bt.Order.Market
            and len(order.data) < 10 * stride + 1
        ):
            return 0.0
        return abs(order.executed.remsize)

    c = bt.Cerebro(stdstats=False, runonce=mode)
    c.broker.setcash(1000.0)
    c.broker.setcommission(
        commission=0.0,
        margin=1000,
        mult=100,
        commtype=bt.CommInfoBase.COMM_FIXED,
        stocklike=False,
    )
    c.broker.set_filler(filler)
    c.adddata(bt.feeds.PandasData(dataname=execution))
    c.adddata(bt.feeds.PandasData(dataname=source))
    c.addstrategy(Trace, length1=2, length2=3, time_trade=False)
    s = c.run(preload=True)[0]
    assert (10, "trendmanager sell flip", "short") in s.closes, s.closes
    assert any(
        bar == 11 and size < 0 and math.isnan(color) for bar, size, color in s.fills
    ), s.fills
    assert [e for e in s.entries if e[2] == "reverse after close"] == [
        (15, "short", "reverse after close")
    ], s.entries
    assert len(s.entries) == 2 and len(s.margins) == 1, (s.entries, s.margins)
    assert not s.position and s.pending_reverse is None
