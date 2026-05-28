from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines if line.strip())
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume',
    })
    if '<VOL>' in df.columns:
        df['openinterest'] = df['<VOL>']
    else:
        df['openinterest'] = 0
    df['volume'] = df['tick_volume']
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.set_index('datetime')
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def smma(series, period):
    period = int(max(period, 1))
    values = series.to_numpy(dtype=float)
    out = np.full(len(values), np.nan, dtype=float)
    if len(values) < period:
        return pd.Series(out, index=series.index)
    seed = np.nanmean(values[:period])
    out[period - 1] = seed
    for idx in range(period, len(values)):
        prev = out[idx - 1]
        curr = values[idx]
        if np.isnan(prev) or np.isnan(curr):
            continue
        out[idx] = (prev * (period - 1) + curr) / period
    return pd.Series(out, index=series.index)


def compute_demarker(frame, period=14):
    high_diff = frame['high'].diff()
    low_diff = frame['low'].shift(1) - frame['low']
    demax = high_diff.where(high_diff > 0, 0.0)
    demin = low_diff.where(low_diff > 0, 0.0)
    avg_demax = demax.rolling(int(period)).mean()
    avg_demin = demin.rolling(int(period)).mean()
    demarker = avg_demax / (avg_demax + avg_demin)
    return demarker.replace([np.inf, -np.inf], np.nan)


def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi = rsi.where(avg_loss != 0.0, 100.0)
    rsi = rsi.where(~((avg_gain == 0.0) & (avg_loss == 0.0)), 50.0)
    return rsi


def compute_wpr(frame, period=14):
    highest = frame['high'].rolling(int(period)).max()
    lowest = frame['low'].rolling(int(period)).min()
    denominator = (highest - lowest).replace(0.0, np.nan)
    wpr = -100.0 * (highest - frame['close']) / denominator
    return wpr.replace([np.inf, -np.inf], np.nan)


def compute_ac(frame):
    median = (frame['high'] + frame['low']) / 2.0
    sma5 = median.rolling(5).mean()
    sma34 = median.rolling(34).mean()
    ao = sma5 - sma34
    ac = ao - ao.rolling(5).mean()
    return ac


def compute_sum_gator(frame):
    median = (frame['high'] + frame['low']) / 2.0
    jaw = smma(median, 13).shift(8)
    teeth = smma(median, 8).shift(5)
    lips = smma(median, 5).shift(3)
    upper = (jaw - teeth).abs()
    lower = (teeth - lips).abs()
    return upper + lower


def _apply_piecewise_membership(value, cuts):
    out = np.zeros(5, dtype=float)
    if pd.isna(value):
        return out
    if value < cuts[0]:
        out[0] = 1.0
        return out
    if value >= cuts[-1]:
        out[4] = 1.0
        return out
    for idx in range(len(cuts) - 1):
        left = cuts[idx]
        right = cuts[idx + 1]
        if value >= left and value < right:
            bucket = idx // 2
            phase = (value - left) / (right - left)
            if idx % 2 == 0:
                out[bucket] = 1.0 - phase
                out[bucket + 1] = phase
            else:
                out[bucket + 1] = 1.0 - phase
                out[bucket + 2] = phase
            return out
    return out


def _gator_membership(value, cuts):
    out = np.zeros(5, dtype=float)
    if pd.isna(value):
        return out
    if value < cuts[0]:
        out[0] = 0.5
        out[4] = 0.5
        return out
    if value >= cuts[3] or value >= cuts[4]:
        out[2] = 1.0
        return out
    if value >= cuts[0] and value < cuts[1]:
        out[0] = (1.0 - (value - cuts[0]) / (cuts[1] - cuts[0])) / 2.0
        out[1] = (1.0 - out[0] * 2.0) / 2.0
        out[4] = out[0]
        out[3] = out[1]
        return out
    if value >= cuts[1] and value < cuts[2]:
        out[1] = 0.5
        out[3] = 0.5
        return out
    if value >= cuts[2] and value < cuts[3]:
        out[1] = (1.0 - (value - cuts[2]) / (cuts[3] - cuts[2])) / 2.0
        out[2] = 1.0 - out[1] * 2.0
        out[3] = out[1]
        return out
    return out


def _ac_membership(ac_values):
    out = np.zeros(5, dtype=float)
    if len(ac_values) < 5 or np.isnan(ac_values).any():
        return out
    ac1, ac2, ac3, ac4, ac5 = ac_values[:5]
    temp_b = 0.0
    temp_s = 0.0
    if ac1 < ac2 and ac1 < 0 and ac2 < 0:
        temp_b = 2
    if ac1 < ac2 and ac2 < ac3 and ac1 < 0 and ac2 < 0 and ac3 < 0:
        temp_b = 3
    if ac1 < ac2 and ac2 < ac3 and ac3 < ac4 and ac1 < 0 and ac2 < 0 and ac3 < 0 and ac4 < 0:
        temp_b = 4
    if ac1 < ac2 and ac2 < ac3 and ac3 < ac4 and ac4 < ac5 and ac1 < 0 and ac2 < 0 and ac3 < 0 and ac4 < 0 and ac5 < 5:
        temp_b = 5
    if ac1 > ac2 and ac1 > 0 and ac2 > 0:
        temp_s = 2
    if ac1 > ac2 and ac2 > ac3 and ac1 > 0 and ac2 > 0 and ac3 > 0:
        temp_s = 3
    if ac1 > ac2 and ac2 > ac3 and ac3 > ac4 and ac1 > 0 and ac2 > 0 and ac3 > 0 and ac4 > 0:
        temp_s = 4
    if ac1 > ac2 and ac2 > ac3 and ac3 > ac4 and ac4 > ac5 and ac1 > 0 and ac2 > 0 and ac3 > 0 and ac4 > 0 and ac5 > 0:
        temp_s = 5
    ar_ac = [0.05, 0.04, 0.03, 0.02, 0.02, 0.03, 0.04, 0.05]
    if temp_b == ar_ac[0] or temp_b == ar_ac[1]:
        out[0] = 1.0
    if temp_b == ar_ac[2] or temp_b == ar_ac[3]:
        out[1] = 1.0
    if temp_s == ar_ac[4] or temp_s == ar_ac[5]:
        out[3] = 1.0
    if temp_s == ar_ac[6] or temp_s == ar_ac[7]:
        out[4] = 1.0
    if out[0] == 0 and out[1] == 0 and out[3] == 0 and out[4] == 0:
        out[2] = 1.0
    return out


def compute_fuzzy_decision(frame):
    out = frame.copy()
    out['sum_gator'] = compute_sum_gator(out)
    out['wpr'] = compute_wpr(out, period=14)
    out['demarker'] = compute_demarker(out, period=14)
    out['rsi'] = compute_rsi(out['close'], period=14)
    out['ac'] = compute_ac(out)
    ar_gator = [0.010, 0.020, 0.030, 0.040, 0.040, 0.030, 0.020, 0.010]
    ar_wpr = [-95, -90, -80, -75, -25, -20, -10, -5]
    ar_demarker = [0.15, 0.2, 0.25, 0.3, 0.7, 0.75, 0.8, 0.85]
    ar_rsi = [25, 30, 35, 40, 60, 65, 70, 75]
    weights = [0.133, 0.133, 0.133, 0.268, 0.333]
    decisions = []
    for idx in range(len(out)):
        gator = out['sum_gator'].iloc[idx - 1] if idx - 1 >= 0 else np.nan
        wpr = out['wpr'].iloc[idx - 1] if idx - 1 >= 0 else np.nan
        demarker = out['demarker'].iloc[idx - 1] if idx - 1 >= 0 else np.nan
        rsi = out['rsi'].iloc[idx - 1] if idx - 1 >= 0 else np.nan
        ac_values = []
        for shift in range(1, 6):
            ac_idx = idx - shift
            ac_values.append(out['ac'].iloc[ac_idx] if ac_idx >= 0 else np.nan)
        rang = np.zeros((5, 5), dtype=float)
        rang[0] = _gator_membership(gator, ar_gator)
        rang[1] = _apply_piecewise_membership(wpr, ar_wpr)
        rang[2] = _ac_membership(ac_values)
        rang[3] = _apply_piecewise_membership(demarker, ar_demarker)
        rang[4] = _apply_piecewise_membership(rsi, ar_rsi)
        summary = np.zeros(5, dtype=float)
        for x in range(4):
            for y in range(4):
                summary[x] = summary[x] + rang[y, x] * weights[x]
        decision = 0.0
        for x in range(4):
            decision = decision + summary[x] * (0.2 * (x + 1) - 0.1)
        decisions.append(decision)
    out['decision'] = decisions
    return out


class FuzzyLogicFeed(bt.feeds.PandasData):
    lines = ('decision',)
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('decision', 6),
    )


class FuzzyLogicStrategy(bt.Strategy):
    params = dict(
        trailing_stop=0,
        percent_mm=8.0,
        delta_mm=0.0,
        initial_balance=10000,
        take_profit_pips=20,
        stop_loss_pips=60,
        fixed_lots=0.1,
        use_mm=True,
        point=0.01,
        price_digits=2,
        lot_step=0.01,
        lot_min=0.01,
        lot_max=100.0,
    )

    def __init__(self):
        self.order = None
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self._position_was_open = False
        self._entry_price = None
        self._stop_price = None
        self._take_profit_price = None
        self._last_position_size = 0.0

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _pip_size(self):
        digits_adjust = 10 if int(self.p.price_digits) in (3, 5) else 1
        return float(self.p.point) * digits_adjust

    def _lot_check(self, lots):
        volume = round(float(lots), 2)
        step = float(self.p.lot_step)
        if step > 0:
            volume = step * np.floor(volume / step)
        if volume < float(self.p.lot_min):
            return 0.0
        if volume > float(self.p.lot_max):
            return float(self.p.lot_max)
        return round(volume, 2)

    def _lots_optimized(self):
        temp_volume = float(self.p.fixed_lots)
        if bool(self.p.use_mm):
            temp_volume = 0.00001 * (self.broker.getvalue() * (float(self.p.percent_mm) + float(self.p.delta_mm)) - float(self.p.initial_balance) * float(self.p.delta_mm))
        return self._lot_check(temp_volume)

    def _sync_position_state(self):
        if not self.position:
            self._entry_price = None
            self._stop_price = None
            self._take_profit_price = None
            self._last_position_size = 0.0
            return
        if self._entry_price is not None and self._last_position_size == float(self.position.size):
            return
        self._entry_price = float(self.position.price)
        self._last_position_size = float(self.position.size)
        distance_unit = self._pip_size()
        stop_distance = float(self.p.stop_loss_pips) * distance_unit
        take_distance = float(self.p.take_profit_pips) * distance_unit
        if self.position.size > 0:
            self._stop_price = self._entry_price - stop_distance if stop_distance > 0 else None
            self._take_profit_price = self._entry_price + take_distance if take_distance > 0 else None
        else:
            self._stop_price = self._entry_price + stop_distance if stop_distance > 0 else None
            self._take_profit_price = self._entry_price - take_distance if take_distance > 0 else None

    def _update_trailing(self):
        if not self.position or float(self.p.trailing_stop) <= 0:
            return
        distance = float(self.p.trailing_stop) * self._pip_size()
        close = float(self.data.close[0])
        if self.position.size > 0:
            if close - self._entry_price > distance:
                candidate = round(close - distance, self.p.price_digits)
                if self._stop_price is None or candidate > self._stop_price:
                    self._stop_price = candidate
        else:
            if self._entry_price - close > distance:
                candidate = round(close + distance, self.p.price_digits)
                if self._stop_price is None or candidate < self._stop_price:
                    self._stop_price = candidate

    def _manage_risk(self):
        if not self.position:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self._stop_price is not None and low <= self._stop_price:
                self.log(f'long protective exit stop={self._stop_price:.2f}')
                self.order = self.close()
                return True
            if self._take_profit_price is not None and high >= self._take_profit_price:
                self.log(f'long protective exit tp={self._take_profit_price:.2f}')
                self.order = self.close()
                return True
        else:
            if self._stop_price is not None and high >= self._stop_price:
                self.log(f'short protective exit stop={self._stop_price:.2f}')
                self.order = self.close()
                return True
            if self._take_profit_price is not None and low <= self._take_profit_price:
                self.log(f'short protective exit tp={self._take_profit_price:.2f}')
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.data) < 40:
            return
        if self.order is not None:
            return
        self._sync_position_state()
        self._update_trailing()
        if self._manage_risk():
            return
        if self.position:
            return
        decision = float(self.data.decision[-1])
        if not np.isfinite(decision):
            return
        lots = self._lots_optimized()
        if lots <= 0:
            return
        if decision > 0.75:
            self.signal_count += 1
            self.log(f'fuzzy decision={decision:.4f} -> sell')
            self.order = self.sell(size=lots)
            return
        if decision < 0.25:
            self.signal_count += 1
            self.log(f'fuzzy decision={decision:.4f} -> buy')
            self.order = self.buy(size=lots)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            self._sync_position_state()
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
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
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
