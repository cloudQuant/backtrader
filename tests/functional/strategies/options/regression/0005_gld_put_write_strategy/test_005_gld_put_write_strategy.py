"""Inlined regression test for options/0005_gld_put_write_strategy.

Self-contained single-file test (manually authored). Runs with runonce=True only.
GLD short-put cash-secured put-write simulation with synthetic option pricing.
"""
from __future__ import annotations

import datetime
import io
import math
from pathlib import Path

import backtrader as bt
import pandas as pd

_REPO = Path(__file__).resolve().parents[6]
DATA_FILE = _REPO / "tests" / "datas" / "mt5_1d_data" / "GLD_1d.csv"


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, "r", encoding="utf-8", errors="ignore") as handle:
        lines = [line.strip().strip('"') for line in handle.readlines() if line.strip()]
    cleaned = "\n".join(lines)
    sep = "\t" if "\t" in lines[0] else ","
    df = pd.read_csv(io.StringIO(cleaned), sep=sep)
    dt_text = df["<DATE>"].astype(str) + " " + df["<TIME>"].astype(str)
    parsed = pd.to_datetime(dt_text, format="%Y.%m.%d %H:%M", errors="coerce")
    if parsed.isna().any():
        parsed = pd.to_datetime(dt_text, format="%Y.%m.%d %H:%M:%S", errors="coerce")
    if bar_shift_minutes:
        parsed = parsed + pd.to_timedelta(int(bar_shift_minutes), unit="m")
    df["datetime"] = parsed
    df = df.rename(columns={"<OPEN>": "open", "<HIGH>": "high", "<LOW>": "low", "<CLOSE>": "close",
                             "<TICKVOL>": "tick_volume", "<VOL>": "real_volume"})
    df["openinterest"] = 0
    df["volume"] = df["tick_volume"] if "tick_volume" in df.columns else 0
    df = df[["datetime", "open", "high", "low", "close", "volume", "openinterest"]]
    df = df.dropna(subset=["datetime"]).set_index("datetime").sort_index()
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def _compute_rsi(series, period):
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, pd.NA)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(50.0)


def prepare_put_write_features(price_df, params):
    out = price_df.copy()
    vol_window = int(params.get("vol_window", 21))
    ma_period = int(params.get("ma_period", 200))
    rsi_period = int(params.get("rsi_period", 14))
    rsi_threshold = float(params.get("rsi_threshold", 30))
    out["returns"] = out["close"].pct_change()
    out["realized_vol"] = out["returns"].rolling(vol_window).std() * math.sqrt(252.0)
    out["ma_filter"] = out["close"].rolling(ma_period).mean()
    out["rsi"] = _compute_rsi(out["close"], rsi_period)
    out["entry_filter"] = ((out["close"] >= out["ma_filter"]) & (out["rsi"] >= rsi_threshold)).astype(float)
    out = out[[
        "open", "high", "low", "close", "volume", "openinterest",
        "realized_vol", "ma_filter", "rsi", "entry_filter",
    ]].copy()
    return out.dropna()


class GLDPutWriteFeed(bt.feeds.PandasData):
    lines = ("realized_vol", "ma_filter", "rsi", "entry_filter")
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2), ("close", 3), ("volume", 4), ("openinterest", 5),
        ("realized_vol", 6), ("ma_filter", 7), ("rsi", 8), ("entry_filter", 9),
    )


class GLDPutWriteStrategy(bt.Strategy):
    params = dict(
        moneyness=0.95,
        dte_days=30,
        max_allocation=0.20,
        stop_loss_pct=0.50,
        premium_factor=0.30,
        contract_multiplier=100,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.roll_count = 0
        self.stop_count = 0
        self.expiry_count = 0
        self.active_option = None
        self.closed_trade_pnls = []
        self.signal_days = 0
        self.last_trade_bar = -1

    def _round_strike(self, price):
        strike = price * float(self.p.moneyness)
        return round(strike / 0.5) * 0.5

    def _estimate_option_mark(self, spot, strike, days_to_expiry, realized_vol):
        vol = max(float(realized_vol or 0.0), 0.05)
        time_value = vol * math.sqrt(max(days_to_expiry, 1) / 365.0) * float(spot) * float(self.p.premium_factor)
        intrinsic = max(0.0, float(strike) - float(spot))
        return intrinsic + time_value

    def _calc_contracts(self, broker_value, strike):
        capital_at_risk = broker_value * float(self.p.max_allocation)
        contract_value = max(float(strike) * float(self.p.contract_multiplier), 1e-9)
        return int(capital_at_risk // contract_value)

    def _open_new_option(self):
        spot = float(self.data.close[0])
        realized_vol = float(self.data.realized_vol[0])
        strike = self._round_strike(spot)
        contracts = self._calc_contracts(float(self.broker.getvalue()), strike)
        if contracts <= 0:
            return
        premium = self._estimate_option_mark(spot=spot, strike=strike,
                                              days_to_expiry=int(self.p.dte_days), realized_vol=realized_vol)
        open_commission = premium * contracts * float(self.p.contract_multiplier) * float(self.p.commission_pct)
        self.broker.add_cash(-open_commission)
        self.active_option = {
            "entry_bar": self.bar_num,
            "expiry_bar": self.bar_num + int(self.p.dte_days),
            "strike": strike,
            "contracts": contracts,
            "initial_premium": premium,
            "last_mark": premium,
            "fees_paid": open_commission,
        }
        self.sell_count += 1
        self.roll_count += 1

    def _close_option(self, current_mark, reason):
        if self.active_option is None:
            return
        close_commission = current_mark * self.active_option["contracts"] * float(self.p.contract_multiplier) * float(self.p.commission_pct)
        self.broker.add_cash(-close_commission)
        total_pnl = (
            (self.active_option["initial_premium"] - current_mark)
            * self.active_option["contracts"]
            * float(self.p.contract_multiplier)
            - self.active_option["fees_paid"]
            - close_commission
        )
        self.closed_trade_pnls.append(total_pnl)
        self.trade_count += 1
        if total_pnl >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.buy_count += 1
        if reason == "stop":
            self.stop_count += 1
        elif reason == "expiry":
            self.expiry_count += 1
        self.active_option = None
        self.last_trade_bar = self.bar_num

    def next(self):
        self.bar_num += 1
        if float(self.data.entry_filter[0]) > 0.5:
            self.signal_days += 1
        if self.active_option is not None:
            spot = float(self.data.close[0])
            realized_vol = float(self.data.realized_vol[0])
            days_to_expiry = max(0, int(self.active_option["expiry_bar"] - self.bar_num))
            current_mark = self._estimate_option_mark(
                spot=spot, strike=self.active_option["strike"],
                days_to_expiry=days_to_expiry, realized_vol=realized_vol,
            )
            daily_pnl = (self.active_option["last_mark"] - current_mark) * self.active_option["contracts"] * float(self.p.contract_multiplier)
            self.broker.add_cash(daily_pnl)
            self.active_option["last_mark"] = current_mark
            if current_mark >= self.active_option["initial_premium"] * (1.0 + float(self.p.stop_loss_pct)):
                self._close_option(current_mark=current_mark, reason="stop")
                return
            if self.bar_num >= self.active_option["expiry_bar"]:
                self._close_option(current_mark=current_mark, reason="expiry")
                return
            return
        if self.last_trade_bar == self.bar_num:
            return
        if float(self.data.entry_filter[0]) <= 0.5:
            return
        self._open_new_option()


def test_005_gld_put_write_strategy() -> None:
    """Migrated regression test for options/0005_gld_put_write_strategy."""
    fromdate = datetime.datetime(2010, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    raw = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate)
    params = dict(
        vol_window=21, ma_period=200, rsi_period=14, rsi_threshold=30,
    )
    frame = prepare_put_write_features(raw, params)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.adddata(GLDPutWriteFeed(dataname=frame, timeframe=bt.TimeFrame.Days), name="GLD")
    cerebro.addstrategy(GLDPutWriteStrategy)

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"trade={strat.trade_count} win={strat.win_count} loss={strat.loss_count} "
          f"roll={strat.roll_count} stop={strat.stop_count} expiry={strat.expiry_count} "
          f"signal_days={strat.signal_days} fv={final_value:.4f}")

    assert strat.bar_num == 3815
    assert strat.buy_count == 91
    assert strat.sell_count == 92
    assert strat.trade_count == 91
    assert strat.win_count == 81
    assert strat.loss_count == 10
    assert strat.roll_count == 92
    assert strat.stop_count == 9
    assert strat.expiry_count == 82
    assert strat.signal_days == 2350
    assert abs(final_value - 1156219.9740) < 1.0
