"""Inlined regression test for trend_following/0161_1325_hammer_cci.

Self-contained single-file test (manually authored). Runs with runonce=True only.
"""
from __future__ import annotations
import backtrader as bt

import datetime
from pathlib import Path

from backtrader.utils.load_data import load_mt5_csv

_REPO = Path(__file__).resolve().parents[4]
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_M15.csv"


class Mt5PandasFeed(bt.feeds.PandasData):
    """Backtrader feed adapter for MT5-style OHLCV columns."""
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
    )


class HammerCciStrategy(bt.Strategy):
    """Hammer / Hanging Man + CCI confirmation."""
    params = dict(
        cci_period=25,
        cci_entry_long=-50,
        cci_entry_short=50,
        cci_exit_upper=80,
        cci_exit_lower=-80,
        ma_period=5,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        """Initialize CCI and moving-average helpers plus trade accounting counters."""
        self.cci = bt.indicators.CommodityChannelIndex(self.data, period=self.p.cci_period)
        self.close_avg = bt.indicators.SMA(self.data.close, period=self.p.ma_period)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

    def _is_hammer(self):
        o1, h1, l1, c1 = (float(self.data.open[-1]), float(self.data.high[-1]),
                          float(self.data.low[-1]), float(self.data.close[-1]))
        o2, c2 = float(self.data.open[-2]), float(self.data.close[-2])
        mid1 = (o1 + c1) / 2.0
        avg2 = float(self.close_avg[-2])
        rng = h1 - l1
        if rng < self.p.point:
            return False
        body_low = min(o1, c1)
        return (mid1 < avg2 and body_low > (h1 - rng / 3.0) and c1 < c2 and o1 < o2)

    def _is_hanging_man(self):
        o1, h1, l1, c1 = (float(self.data.open[-1]), float(self.data.high[-1]),
                          float(self.data.low[-1]), float(self.data.close[-1]))
        o2, c2 = float(self.data.open[-2]), float(self.data.close[-2])
        mid1 = (o1 + c1) / 2.0
        avg2 = float(self.close_avg[-2])
        rng = h1 - l1
        if rng < self.p.point:
            return False
        body_low = min(o1, c1)
        return (mid1 > avg2 and body_low > (h1 - rng / 3.0) and c1 > c2 and o1 > o2)

    def next(self):
        """Evaluate hammer/hanging-man setup and CCI levels to operate positions."""
        self.bar_num += 1
        warmup = max(self.p.cci_period, self.p.ma_period) + 5
        if len(self.data) < warmup:
            return

        cci0 = float(self.cci[0])
        cci1 = float(self.cci[-1])

        if self.position:
            if self.position.size > 0:
                if ((cci0 > self.p.cci_exit_lower and cci1 < self.p.cci_exit_lower) or
                        (cci0 < self.p.cci_exit_upper and cci1 > self.p.cci_exit_upper)):
                    self.close()
                    return
            elif self.position.size < 0:
                if ((cci0 < self.p.cci_exit_upper and cci1 > self.p.cci_exit_upper) or
                        (cci0 > self.p.cci_exit_lower and cci1 < self.p.cci_exit_lower)):
                    self.close()
                    return
        else:
            if self._is_hammer() and cci0 < self.p.cci_entry_long:
                self.buy(size=self.p.lot)
                return
            if self._is_hanging_man() and cci0 > self.p.cci_entry_short:
                self.sell(size=self.p.lot)
                return

    def notify_trade(self, trade):
        """Record first-open direction and closed trade outcome counters."""
        if trade.isopen and not self._position_was_open:
            if trade.size > 0:
                self.buy_count += 1
            elif trade.size < 0:
                self.sell_count += 1
            self._position_was_open = True
            return
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False


def test_160_0161_1325_hammer_cci() -> None:
    """Migrated regression test for trend_following/0161_1325_hammer_cci."""
    fromdate = datetime.datetime(2025, 12, 3, 1, 15)
    todate = datetime.datetime(2026, 3, 10, 9, 0)
    df = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate, bar_shift_minutes=15)

    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(
        commission=0.0, margin=0.01, mult=100.0,
        commtype=bt.CommInfoBase.COMM_FIXED, stocklike=False,
    )
    cerebro.adddata(Mt5PandasFeed(dataname=df, timeframe=bt.TimeFrame.Minutes, compression=15))
    cerebro.addstrategy(HammerCciStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    assert strat.bar_num == 6081
    assert strat.buy_count == 31
    assert strat.sell_count == 28
    assert strat.win_count == 40
    assert strat.loss_count == 19
    assert strat.trade_count == 59
    assert total_trades == 59
    assert abs(final_value - 1001116.7) < 0.01
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
