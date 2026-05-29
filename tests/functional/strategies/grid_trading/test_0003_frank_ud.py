"""Inlined regression test for grid_trading/0003_frank_ud.

Self-contained single-file test (manually authored). Runs with runonce=True only.
Hedge-grid martingale strategy on XAUUSD M15.
"""
from __future__ import annotations

import datetime
import io
from pathlib import Path

import backtrader as bt
import pandas as pd

_REPO = Path(__file__).resolve().parents[4]
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_M15.csv"


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.read().strip().split("\n")
    cleaned = "\n".join(line.strip().strip('"') for line in lines)
    df = pd.read_csv(io.StringIO(cleaned), sep="\t")
    df["datetime"] = pd.to_datetime(df["<DATE>"] + " " + df["<TIME>"], format="%Y.%m.%d %H:%M:%S")
    df = df.rename(columns={
        "<OPEN>": "open", "<HIGH>": "high", "<LOW>": "low", "<CLOSE>": "close",
        "<TICKVOL>": "tick_volume", "<VOL>": "real_volume",
    })
    df["openinterest"] = 0
    df["volume"] = df["tick_volume"]
    df = df[["datetime", "open", "high", "low", "close", "volume", "openinterest"]]
    df = df.set_index("datetime")
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
    )


class FrankUdStrategy(bt.Strategy):
    params = dict(
        takeprofit=12,
        stoploss=12,
        step=16,
        lot_auto=True,
        lot=0.5,
        min_lot=0.01,
        lot_step=0.01,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
        spread_points=0.0,
        multiplier=100.0,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_leg_count = 0
        self.sell_leg_count = 0
        self.closed_leg_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.cycle_count = 0
        self.addon_count = 0

        self.coefficient = 1.0
        self.legs = []
        self.virtual_realized_pnl = 0.0
        self.initial_virtual_cash = None
        self.virtual_equity = None

    def start(self):
        self.initial_virtual_cash = float(self.broker.getcash())
        self.virtual_equity = self.initial_virtual_cash

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _spread(self):
        return float(self.p.spread_points) * float(self.p.point)

    def _round_lot(self, value):
        step = max(float(self.p.lot_step), 1e-8)
        rounded = int(value / step) * step
        return round(max(rounded, float(self.p.min_lot)), 8)

    def _base_lot(self):
        if not bool(self.p.lot_auto):
            return self._round_lot(float(self.p.min_lot))
        return self._round_lot(float(self.p.lot))

    def _current_lot(self):
        return self._round_lot(self._base_lot() * self.coefficient)

    def _make_leg(self, side, entry_price, size, stop_price=None, take_profit_price=None):
        return {
            "side": side, "entry_price": float(entry_price), "size": float(size),
            "stop_price": stop_price, "take_profit_price": take_profit_price,
        }

    def _pnl_for_leg(self, side, entry_price, exit_price, size):
        direction = 1.0 if side == "buy" else -1.0
        return (float(exit_price) - float(entry_price)) * direction * float(size) * float(self.p.multiplier)

    def _update_virtual_equity(self):
        price = float(self.data.close[0])
        unrealized = 0.0
        for leg in self.legs:
            unrealized += self._pnl_for_leg(leg["side"], leg["entry_price"], price, leg["size"])
        self.virtual_equity = self.initial_virtual_cash + self.virtual_realized_pnl + unrealized

    def _can_trade(self):
        self._update_virtual_equity()
        return self.virtual_equity >= self.initial_virtual_cash * 0.5

    def _open_initial_pair(self):
        spread = self._spread()
        buy_entry = float(self.data.close[0]) + spread
        sell_entry = float(self.data.close[0])
        size = self._current_lot()
        unit = self._unit()
        self.legs = [
            self._make_leg("buy", buy_entry, size,
                stop_price=round(buy_entry - float(self.p.stoploss) * unit, int(self.p.price_digits)),
                take_profit_price=round(buy_entry + float(self.p.takeprofit) * unit, int(self.p.price_digits))),
            self._make_leg("sell", sell_entry, size,
                stop_price=round(sell_entry + float(self.p.stoploss) * unit, int(self.p.price_digits)),
                take_profit_price=round(sell_entry - float(self.p.takeprofit) * unit, int(self.p.price_digits))),
        ]
        self.cycle_count += 1
        self.buy_leg_count += 1
        self.sell_leg_count += 1

    def _side_legs(self, side):
        return [leg for leg in self.legs if leg["side"] == side]

    def _calc_net_price(self, side):
        legs = self._side_legs(side)
        if not legs:
            return None, None
        total_pv = sum(leg["entry_price"] * leg["size"] for leg in legs)
        total_vol = sum(leg["size"] for leg in legs)
        if total_vol == 0:
            return None, None
        net_price = total_pv / total_vol
        if side == "buy":
            nearest_price = min(leg["entry_price"] for leg in legs)
        else:
            nearest_price = max(leg["entry_price"] for leg in legs)
        return net_price, nearest_price

    def _sync_remaining_side(self):
        unit = self._unit()
        buys = self._side_legs("buy")
        sells = self._side_legs("sell")
        if buys and sells:
            return None, None
        if sells:
            net_price, nearest_price = self._calc_net_price("sell")
            tp = round(net_price - float(self.p.takeprofit) * unit, int(self.p.price_digits))
            for leg in sells:
                leg["stop_price"] = None
                leg["take_profit_price"] = tp
            return "sell", nearest_price
        if buys:
            net_price, nearest_price = self._calc_net_price("buy")
            tp = round(net_price + float(self.p.takeprofit) * unit, int(self.p.price_digits))
            for leg in buys:
                leg["stop_price"] = None
                leg["take_profit_price"] = tp
            return "buy", nearest_price
        return None, None

    def _close_hit_legs(self):
        if not self.legs:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        remaining = []
        for leg in self.legs:
            stop_hit = False
            take_hit = False
            if leg["stop_price"] is not None:
                stop_hit = low <= leg["stop_price"] if leg["side"] == "buy" else high >= leg["stop_price"]
            if leg["take_profit_price"] is not None:
                take_hit = high >= leg["take_profit_price"] if leg["side"] == "buy" else low <= leg["take_profit_price"]
            if stop_hit or take_hit:
                exit_price = leg["take_profit_price"] if take_hit and not stop_hit else leg["stop_price"]
                pnl = self._pnl_for_leg(leg["side"], leg["entry_price"], exit_price, leg["size"])
                self.virtual_realized_pnl += pnl
                self.closed_leg_count += 1
                if pnl >= 0:
                    self.win_count += 1
                else:
                    self.loss_count += 1
            else:
                remaining.append(leg)
        self.legs = remaining

    def _maybe_addon(self, side, nearest_price):
        if side is None or nearest_price is None or not self._can_trade():
            return
        unit = self._unit()
        close_price = float(self.data.close[0])
        if side == "sell" and close_price > nearest_price + float(self.p.step) * unit:
            self.coefficient *= 2.0
            size = self._current_lot()
            entry = close_price
            self.legs.append(self._make_leg("sell", entry, size,
                stop_price=round(entry + float(self.p.stoploss) * unit, int(self.p.price_digits))))
            self.sell_leg_count += 1
            self.addon_count += 1
        elif side == "buy" and close_price < nearest_price - float(self.p.step) * unit:
            self.coefficient *= 2.0
            size = self._current_lot()
            entry = close_price
            self.legs.append(self._make_leg("buy", entry, size,
                stop_price=round(entry - float(self.p.stoploss) * unit, int(self.p.price_digits))))
            self.buy_leg_count += 1
            self.addon_count += 1

    def next(self):
        self.bar_num += 1
        self._close_hit_legs()
        if not self.legs:
            if self._can_trade():
                self.coefficient = 1.0
                self._open_initial_pair()
            self._update_virtual_equity()
            return
        side, nearest_price = self._sync_remaining_side()
        self._maybe_addon(side, nearest_price)
        self._sync_remaining_side()
        self._update_virtual_equity()


def test_003_frank_ud() -> None:
    """Migrated regression test for grid_trading/0003_frank_ud."""
    fromdate = datetime.datetime(2025, 12, 3, 1, 15, 0)
    todate = datetime.datetime(2026, 3, 10, 9, 0, 0)
    raw = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate, bar_shift_minutes=15)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.adddata(Mt5PandasFeed(dataname=raw, timeframe=bt.TimeFrame.Minutes, compression=15), name="XAUUSD")
    cerebro.addstrategy(FrankUdStrategy)

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())

    print(f"CAPTURED: bar={strat.bar_num} buy_legs={strat.buy_leg_count} sell_legs={strat.sell_leg_count} "
          f"closed_legs={strat.closed_leg_count} win={strat.win_count} loss={strat.loss_count} "
          f"cycles={strat.cycle_count} addons={strat.addon_count} fv={final_value:.4f} "
          f"v_pnl={strat.virtual_realized_pnl:.4f}")

    assert strat.bar_num == 6129
    assert strat.buy_leg_count == 6107
    assert strat.sell_leg_count == 6107
    assert strat.closed_leg_count == 12212
    assert strat.win_count == 2254
    assert strat.loss_count == 9958
    assert strat.cycle_count == 6107
    assert strat.addon_count == 0
    assert abs(final_value - 1000000.0000) < 1.0
    assert abs(strat.virtual_realized_pnl - (-462240.0000)) < 1.0
