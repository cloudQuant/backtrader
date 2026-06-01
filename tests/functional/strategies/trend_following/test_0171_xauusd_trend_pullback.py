"""Inlined regression test for trend_following/0171_xauusd_trend_pullback.

Self-contained single-file test (manually authored). Runs with runonce=True
only and validates a three-timeframe trend pullback setup.

Data Used:
- XAUUSD M1 loaded from ``tests/datas/XAUUSD_M1.csv`` with 1-minute bars.
- XAUUSD M5 loaded from ``tests/datas/XAUUSD_M5.csv`` with 5-minute bars.
- XAUUSD M15 loaded from ``tests/datas/XAUUSD_M15.csv`` with 15-minute bars.
- Backtest window: 2026-03-08 00:00:00 to 2026-03-17 23:59:59.
- Warm-up bars for M5/M15 from 2026-03-05 00:00:00.

Strategy Principle:
The strategy filters trend direction on higher timeframe EMAs and ADX, then
waits for pullback confirmation on M5 and entry alignment on M1 before opening
positions with fixed-risk sizing and layered profit management.

Strategy Logic:
- Build parallel feeds for M1, M5, M15 and initialize indicators for trend,
  pullback, and entry scoring.
- Use trend regime detection, pullback scoring, and M1 RSI crossover logic to
  gate entry.
- On entry, set multi-target take-profit levels, optional breakeven/trailing,
  and exit risk with hard stop and daily/volume limits.
- Capture order/trade events to update trade counters and state used by assertions.
"""
from __future__ import annotations

import datetime
import math
from pathlib import Path

import backtrader as bt
from backtrader.utils.load_data import load_mt5_csv

_REPO = Path(__file__).resolve().parents[4]
DATA_DIR = _REPO / "tests" / "datas"


class Mt5PandasFeed(bt.feeds.PandasData):
    """Backtrader PandasData feed mapping MT5 CSV column order."""
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
    )


class XAUUSDTrendPullbackStrategy(bt.Strategy):
    """Three-timeframe trend-pullback strategy with risk and session controls."""
    params = dict(
        trend_ema_fast=50, trend_ema_slow=200, trend_ema_diff=4.5,
        adx_period=14, adx_threshold=22,
        pb_ema_short=20, pb_ema_long=30,
        pb_rsi_period=7,
        pb_rsi_long_lo=38.0, pb_rsi_long_hi=42.0,
        pb_rsi_short_lo=58.0, pb_rsi_short_hi=62.0,
        pb_atr_period=14, atr_min=1.2, atr_max=5.8,
        entry_rsi_period=7,
        entry_rsi_long_cross=45.0, entry_rsi_short_cross=55.0,
        sl_buffer=1.2, sl_min=3.0, sl_max=6.0,
        tp1_r=1.5, tp1_pct=0.50, tp2_r=3.0,
        be_trigger_r=1.0, be_offset=0.2,
        trailing_start_r=1.8, trailing_distance=2.2,
        risk_per_trade=0.005,
        max_trades_per_day=3, max_consecutive_loss=2,
        daily_loss_limit=0.02, daily_profit_lock=0.03,
        trade_start_hour=7, trade_end_hour=17,
        fixed_size=0.1,
        volume_min=0.01, volume_max=100.0, volume_step=0.01,
    )

    def __init__(self):
        """Initialize indicators, multi-timeframe state, and trading counters."""
        self.m1 = self.data0
        self.m5 = self.data1
        self.m15 = self.data2

        self.ema50 = bt.ind.EMA(self.m15.close, period=self.p.trend_ema_fast)
        self.ema200 = bt.ind.EMA(self.m15.close, period=self.p.trend_ema_slow)
        self.adx = bt.ind.ADX(self.m15, period=self.p.adx_period)
        self.plus_di = bt.ind.PlusDirectionalIndicator(self.m15, period=self.p.adx_period)
        self.minus_di = bt.ind.MinusDirectionalIndicator(self.m15, period=self.p.adx_period)

        self.pb_ema20 = bt.ind.EMA(self.m5.close, period=self.p.pb_ema_short)
        self.pb_ema30 = bt.ind.EMA(self.m5.close, period=self.p.pb_ema_long)
        self.pb_rsi = bt.ind.RSI(self.m5.close, period=self.p.pb_rsi_period)
        self.pb_atr = bt.ind.ATR(self.m5, period=self.p.pb_atr_period)

        self.m1_rsi = bt.ind.RSI(self.m1.close, period=self.p.entry_rsi_period)

        self.trend_dir = 0
        self.pullback_ready = 0
        self.entry_price = 0.0
        self.stop_loss = 0.0
        self.tp1_price = 0.0
        self.tp2_price = 0.0
        self.risk_amount = 0.0
        self.tp1_hit = False
        self.be_activated = False
        self.trailing_active = False
        self.trailing_stop = 0.0
        self.initial_size = 0.0
        self.has_pending_or_open = False

        self.current_date = None
        self.trades_today = 0
        self.consecutive_losses = 0
        self.daily_start_value = 0.0

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

        self.prev_m1_rsi = 0.0

        self.pending_entry_direction = 0
        self.pending_stop_loss = 0.0
        self.pending_risk_amount = 0.0

    def _new_day_check(self):
        cur = bt.num2date(self.m1.datetime[0]).date()
        if cur != self.current_date:
            self.current_date = cur
            self.trades_today = 0
            self.consecutive_losses = 0
            self.daily_start_value = self.broker.getvalue()

    def _in_trading_hours(self):
        dt = bt.num2date(self.m1.datetime[0])
        h = dt.hour
        return self.p.trade_start_hour <= h < self.p.trade_end_hour

    def _daily_limits_ok(self):
        if self.trades_today >= self.p.max_trades_per_day:
            return False
        if self.consecutive_losses >= self.p.max_consecutive_loss:
            return False
        if self.daily_start_value > 0:
            pnl_pct = (self.broker.getvalue() - self.daily_start_value) / self.daily_start_value
            if pnl_pct <= -self.p.daily_loss_limit:
                return False
            if pnl_pct >= self.p.daily_profit_lock:
                return False
        return True

    def _check_trend(self):
        try:
            ema50 = self.ema50[0]
            ema200 = self.ema200[0]
            adx_val = self.adx[0]
            plus_di = self.plus_di[0]
            minus_di = self.minus_di[0]
        except (IndexError, AttributeError):
            return 0
        if (ema50 > ema200 and (ema50 - ema200) >= self.p.trend_ema_diff
                and adx_val > self.p.adx_threshold and plus_di > minus_di):
            return 1
        if (ema50 < ema200 and (ema200 - ema50) >= self.p.trend_ema_diff
                and adx_val > self.p.adx_threshold and minus_di > plus_di):
            return -1
        return 0

    def _check_pullback_long(self):
        try:
            close = self.m5.close[0]
            low = self.m5.low[0]
            ema20 = self.pb_ema20[0]
            ema30 = self.pb_ema30[0]
            rsi = self.pb_rsi[0]
            atr = self.pb_atr[0]
        except (IndexError, AttributeError):
            return False
        if atr < self.p.atr_min or atr > self.p.atr_max:
            return False
        score = 0
        touch_dist = 0.5 * atr
        if abs(close - ema20) <= touch_dist or abs(close - ema30) <= touch_dist:
            score += 1
        if self.p.pb_rsi_long_lo <= rsi <= self.p.pb_rsi_long_hi:
            score += 1
        try:
            recent_lows = [self.m5.low[-i] for i in range(1, 4)]
            min_recent = min(recent_lows)
            if abs(low - min_recent) <= 0.5 * atr:
                score += 1
        except (IndexError,):
            pass
        return score >= 2

    def _check_pullback_short(self):
        try:
            close = self.m5.close[0]
            high = self.m5.high[0]
            ema20 = self.pb_ema20[0]
            ema30 = self.pb_ema30[0]
            rsi = self.pb_rsi[0]
            atr = self.pb_atr[0]
        except (IndexError, AttributeError):
            return False
        if atr < self.p.atr_min or atr > self.p.atr_max:
            return False
        score = 0
        touch_dist = 0.5 * atr
        if abs(close - ema20) <= touch_dist or abs(close - ema30) <= touch_dist:
            score += 1
        if self.p.pb_rsi_short_lo <= rsi <= self.p.pb_rsi_short_hi:
            score += 1
        try:
            recent_highs = [self.m5.high[-i] for i in range(1, 4)]
            max_recent = max(recent_highs)
            if abs(high - max_recent) <= 0.5 * atr:
                score += 1
        except (IndexError,):
            pass
        return score >= 2

    def _check_entry_long(self):
        try:
            close0 = self.m1.close[0]
            close1 = self.m1.close[-1]
            open0 = self.m1.open[0]
            open1 = self.m1.open[-1]
            low0 = self.m1.low[0]
            rsi_now = self.m1_rsi[0]
            rsi_prev = self.m1_rsi[-1]
        except (IndexError, AttributeError):
            return False
        score = 0
        if close1 > open1 and close0 > open0:
            score += 1
        if rsi_prev <= self.p.entry_rsi_long_cross < rsi_now:
            score += 1
        try:
            recent_highs = [self.m1.high[-i] for i in range(1, 6)]
            if close0 > max(recent_highs):
                score += 1
        except (IndexError,):
            pass
        body = abs(close0 - open0)
        lower_shadow = min(open0, close0) - low0
        if lower_shadow > 2 * body and body > 0:
            score += 1
        return score >= 2

    def _check_entry_short(self):
        try:
            close0 = self.m1.close[0]
            close1 = self.m1.close[-1]
            open0 = self.m1.open[0]
            open1 = self.m1.open[-1]
            high0 = self.m1.high[0]
            rsi_now = self.m1_rsi[0]
            rsi_prev = self.m1_rsi[-1]
        except (IndexError, AttributeError):
            return False
        score = 0
        if close1 < open1 and close0 < open0:
            score += 1
        if rsi_prev >= self.p.entry_rsi_short_cross > rsi_now:
            score += 1
        try:
            recent_lows = [self.m1.low[-i] for i in range(1, 6)]
            if close0 < min(recent_lows):
                score += 1
        except (IndexError,):
            pass
        body = abs(close0 - open0)
        upper_shadow = high0 - max(open0, close0)
        if upper_shadow > 2 * body and body > 0:
            score += 1
        return score >= 2

    def _calc_stop_loss_long(self):
        try:
            recent_lows = [self.m5.low[-i] for i in range(0, 4)]
            sl = min(recent_lows) - self.p.sl_buffer
        except (IndexError,):
            sl = self.m1.close[0] - self.p.sl_max
        return sl

    def _calc_stop_loss_short(self):
        try:
            recent_highs = [self.m5.high[-i] for i in range(0, 4)]
            sl = max(recent_highs) + self.p.sl_buffer
        except (IndexError,):
            sl = self.m1.close[0] + self.p.sl_max
        return sl

    def _normalize_position_size(self, size):
        min_size = max(self.p.volume_min, 0.0)
        max_size = max(min_size, self.p.volume_max)
        step = self.p.volume_step if self.p.volume_step > 0 else 0.01
        normalized = math.floor(size / step) * step
        normalized = max(min_size, min(normalized, max_size))
        return round(normalized, 2)

    def _calc_position_size(self, entry_price, stop_price, is_long):
        account_value = self.broker.getvalue()
        risk_dollars = account_value * self.p.risk_per_trade
        if entry_price <= 0 or stop_price <= 0:
            return self._normalize_position_size(self.p.fixed_size)
        comminfo = self.broker.getcommissioninfo(self.m1)
        direction = 1.0 if is_long else -1.0
        risk_per_lot = abs(comminfo.profitandloss(direction, entry_price, stop_price))
        if risk_per_lot <= 0:
            sl_distance = abs(entry_price - stop_price)
            if sl_distance <= 0:
                return self._normalize_position_size(self.p.fixed_size)
            mult = comminfo.p.mult if hasattr(comminfo, "p") else 100.0
            risk_per_lot = sl_distance * mult
        size = risk_dollars / risk_per_lot
        return self._normalize_position_size(size)

    def _open_long(self):
        price = self.m1.close[0]
        sl = self._calc_stop_loss_long()
        sl_dist = price - sl
        if sl_dist < self.p.sl_min:
            sl = price - self.p.sl_min
            sl_dist = self.p.sl_min
        elif sl_dist > self.p.sl_max:
            return
        size = self._calc_position_size(price, sl, True)
        self.buy(data=self.m1, size=size)
        self.buy_count += 1
        self.has_pending_or_open = True
        self.pending_entry_direction = 1
        self.pending_stop_loss = sl
        self.pending_risk_amount = sl_dist
        self.tp1_hit = False
        self.be_activated = False
        self.trailing_active = False
        self.trailing_stop = 0.0
        self.initial_size = 0.0

    def _open_short(self):
        price = self.m1.close[0]
        sl = self._calc_stop_loss_short()
        sl_dist = sl - price
        if sl_dist < self.p.sl_min:
            sl = price + self.p.sl_min
            sl_dist = self.p.sl_min
        elif sl_dist > self.p.sl_max:
            return
        size = self._calc_position_size(price, sl, False)
        self.sell(data=self.m1, size=size)
        self.sell_count += 1
        self.has_pending_or_open = True
        self.pending_entry_direction = -1
        self.pending_stop_loss = sl
        self.pending_risk_amount = sl_dist
        self.tp1_hit = False
        self.be_activated = False
        self.trailing_active = False
        self.trailing_stop = 0.0
        self.initial_size = 0.0

    def _manage_long_position(self):
        high = self.m1.high[0]
        low = self.m1.low[0]
        if low <= self.stop_loss:
            self.close(data=self.m1)
            return
        profit_dist = high - self.entry_price
        if not self.tp1_hit and high >= self.tp1_price:
            close_size = round(self.initial_size * self.p.tp1_pct, 2)
            if close_size >= 0.01:
                self.sell(data=self.m1, size=close_size)
            self.tp1_hit = True
        if high >= self.tp2_price:
            self.close(data=self.m1)
            return
        if not self.be_activated and profit_dist >= self.p.be_trigger_r * self.risk_amount:
            self.stop_loss = self.entry_price + self.p.be_offset
            self.be_activated = True
        if not self.trailing_active and profit_dist >= self.p.trailing_start_r * self.risk_amount:
            self.trailing_active = True
            self.trailing_stop = high - self.p.trailing_distance
        if self.trailing_active:
            new_trail = high - self.p.trailing_distance
            if new_trail > self.trailing_stop:
                self.trailing_stop = new_trail
            if low <= self.trailing_stop:
                self.close(data=self.m1)

    def _manage_short_position(self):
        low = self.m1.low[0]
        high = self.m1.high[0]
        if high >= self.stop_loss:
            self.close(data=self.m1)
            return
        profit_dist = self.entry_price - low
        if not self.tp1_hit and low <= self.tp1_price:
            close_size = round(self.initial_size * self.p.tp1_pct, 2)
            if close_size >= 0.01:
                self.buy(data=self.m1, size=close_size)
            self.tp1_hit = True
        if low <= self.tp2_price:
            self.close(data=self.m1)
            return
        if not self.be_activated and profit_dist >= self.p.be_trigger_r * self.risk_amount:
            self.stop_loss = self.entry_price - self.p.be_offset
            self.be_activated = True
        if not self.trailing_active and profit_dist >= self.p.trailing_start_r * self.risk_amount:
            self.trailing_active = True
            self.trailing_stop = low + self.p.trailing_distance
        if self.trailing_active:
            new_trail = low + self.p.trailing_distance
            if new_trail < self.trailing_stop:
                self.trailing_stop = new_trail
            if high >= self.trailing_stop:
                self.close(data=self.m1)

    def next(self):
        """Process one step of strategy state and execute entries/exits."""
        self.bar_num += 1
        self._new_day_check()
        pos = self.getposition(self.m1).size
        if pos > 0:
            self.has_pending_or_open = True
            self._manage_long_position()
            self.prev_m1_rsi = self.m1_rsi[0] if len(self.m1_rsi) > 0 else 0
            return
        elif pos < 0:
            self.has_pending_or_open = True
            self._manage_short_position()
            self.prev_m1_rsi = self.m1_rsi[0] if len(self.m1_rsi) > 0 else 0
            return
        else:
            if self.has_pending_or_open and self.pending_entry_direction == 0:
                self.has_pending_or_open = False
        if not self._in_trading_hours() or not self._daily_limits_ok():
            self.prev_m1_rsi = self.m1_rsi[0] if len(self.m1_rsi) > 0 else 0
            return
        trend = self._check_trend()
        if trend == 0:
            self.prev_m1_rsi = self.m1_rsi[0] if len(self.m1_rsi) > 0 else 0
            return
        if self.has_pending_or_open:
            self.prev_m1_rsi = self.m1_rsi[0] if len(self.m1_rsi) > 0 else 0
            return
        if trend == 1 and self._check_pullback_long():
            if self._check_entry_long():
                self._open_long()
        elif trend == -1 and self._check_pullback_short():
            if self._check_entry_short():
                self._open_short()
        self.prev_m1_rsi = self.m1_rsi[0] if len(self.m1_rsi) > 0 else 0

    def notify_order(self, order):
        """Update entry levels on fill and reset pending state on failure.

        Args:
            order: Backtrader order instance with the latest status.
        """
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if self.pending_entry_direction == 1 and order.isbuy():
                self.entry_price = order.executed.price
                self.stop_loss = self.pending_stop_loss
                self.risk_amount = self.entry_price - self.stop_loss
                if self.risk_amount <= 0:
                    self.risk_amount = self.pending_risk_amount
                self.tp1_price = self.entry_price + self.p.tp1_r * self.risk_amount
                self.tp2_price = self.entry_price + self.p.tp2_r * self.risk_amount
                self.initial_size = abs(order.executed.size)
                self.trades_today += 1
                self.pending_entry_direction = 0
            elif self.pending_entry_direction == -1 and not order.isbuy():
                self.entry_price = order.executed.price
                self.stop_loss = self.pending_stop_loss
                self.risk_amount = self.stop_loss - self.entry_price
                if self.risk_amount <= 0:
                    self.risk_amount = self.pending_risk_amount
                self.tp1_price = self.entry_price - self.p.tp1_r * self.risk_amount
                self.tp2_price = self.entry_price - self.p.tp2_r * self.risk_amount
                self.initial_size = abs(order.executed.size)
                self.trades_today += 1
                self.pending_entry_direction = 0
            return
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            if self.pending_entry_direction != 0:
                self.pending_entry_direction = 0
                self.pending_stop_loss = 0.0
                self.pending_risk_amount = 0.0
                self.has_pending_or_open = False

    def notify_trade(self, trade):
        """Track closed trade outcomes and daily loss streak state.

        Args:
            trade: Closed-trade event from Backtrader.
        """
        if trade.isclosed:
            self.trade_count += 1
            if trade.pnlcomm >= 0:
                self.win_count += 1
                self.consecutive_losses = 0
            else:
                self.loss_count += 1
                self.consecutive_losses += 1


def test_170_0171_xauusd_trend_pullback() -> None:
    """Migrated regression test for trend_following/0171_xauusd_trend_pullback."""
    fromdate = datetime.datetime(2026, 3, 8, 0, 0)
    todate = datetime.datetime(2026, 3, 17, 23, 59, 59)
    warmup_from = datetime.datetime(2026, 3, 5, 0, 0)

    df_m1 = load_mt5_csv(DATA_DIR / "XAUUSD_M1.csv",
                          fromdate=fromdate, todate=todate, bar_shift_minutes=1)
    df_m5 = load_mt5_csv(DATA_DIR / "XAUUSD_M5.csv",
                          fromdate=warmup_from, todate=todate, bar_shift_minutes=5)
    df_m15 = load_mt5_csv(DATA_DIR / "XAUUSD_M15.csv",
                           fromdate=warmup_from, todate=todate, bar_shift_minutes=15)

    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(
        commission=0.0, margin=0.01, mult=100.0,
        commtype=bt.CommInfoBase.COMM_FIXED, stocklike=False,
    )
    cerebro.adddata(Mt5PandasFeed(dataname=df_m1, timeframe=bt.TimeFrame.Minutes, compression=1))
    cerebro.adddata(Mt5PandasFeed(dataname=df_m5, timeframe=bt.TimeFrame.Minutes, compression=5))
    cerebro.adddata(Mt5PandasFeed(dataname=df_m15, timeframe=bt.TimeFrame.Minutes, compression=15))
    cerebro.addstrategy(XAUUSDTrendPullbackStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 9262
    assert strat.buy_count == 3
    assert strat.sell_count == 4
    assert strat.win_count == 4
    assert strat.loss_count == 3
    assert strat.trade_count == 7
    assert total_trades == 7
    assert abs(final_value - 1001058.61) < 1.0
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
