from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None):
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as handle:
        lines = [line.strip().strip('"') for line in handle.readlines() if line.strip()]
    cleaned = '\n'.join(lines)
    sep = '\t' if '\t' in lines[0] else ','
    df = pd.read_csv(io.StringIO(cleaned), sep=sep)
    dt_text = df['<DATE>'].astype(str) + ' ' + df['<TIME>'].astype(str)
    parsed = pd.to_datetime(dt_text, format='%Y.%m.%d %H:%M', errors='coerce')
    if parsed.isna().any():
        parsed = pd.to_datetime(dt_text, format='%Y.%m.%d %H:%M:%S', errors='coerce')
    df['datetime'] = parsed
    df = df.rename(columns={
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low',
        '<CLOSE>': 'close', '<TICKVOL>': 'tick_volume', '<VOL>': 'real_volume',
    })
    df['openinterest'] = 0
    df['volume'] = df['tick_volume'] if 'tick_volume' in df.columns else 0
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.set_index('datetime').sort_index()
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def prepare_nr7_filtered_features(df, params):
    out = df.copy()
    lookback = int(params.get('lookback', 7))
    atr_period = int(params.get('atr_period', 14))
    atr_ma_period = int(params.get('atr_ma_period', 50))
    ma_period = int(params.get('ma_period', 50))
    use_trend_filter = bool(params.get('use_trend_filter', True))
    volatility_threshold = float(params.get('volatility_threshold', 2.5))
    out['daily_range'] = out['high'] - out['low']
    out['min_range_prev'] = out['daily_range'].shift(1).rolling(window=lookback - 1).min()
    out['nr7'] = (out['daily_range'] < out['min_range_prev']).astype(float)
    tr1 = out['high'] - out['low']
    tr2 = (out['high'] - out['close'].shift(1)).abs()
    tr3 = (out['low'] - out['close'].shift(1)).abs()
    out['tr'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    out['atr'] = out['tr'].rolling(window=atr_period).mean()
    out['atr_ma'] = out['atr'].rolling(window=atr_ma_period).mean()
    out['normal_volatility'] = (out['atr'] < out['atr_ma'] * volatility_threshold).astype(float)
    out['filtered_nr7'] = ((out['nr7'] > 0.5) & (out['normal_volatility'] > 0.5)).astype(float)
    out['trend_ma'] = out['close'].rolling(window=ma_period).mean()
    out['uptrend'] = (out['close'] > out['trend_ma']).astype(float)
    out['downtrend'] = (out['close'] < out['trend_ma']).astype(float)
    prev_filtered_nr7 = out['filtered_nr7'].shift(1) > 0.5
    prev_high = out['high'].shift(1)
    prev_low = out['low'].shift(1)
    if use_trend_filter:
        out['breakout_up'] = (prev_filtered_nr7 & (out['close'] > prev_high) & (out['uptrend'] > 0.5)).astype(float)
        out['breakout_down'] = (prev_filtered_nr7 & (out['close'] < prev_low) & (out['downtrend'] > 0.5)).astype(float)
    else:
        out['breakout_up'] = (prev_filtered_nr7 & (out['close'] > prev_high)).astype(float)
        out['breakout_down'] = (prev_filtered_nr7 & (out['close'] < prev_low)).astype(float)
    out['reverse_long_exit'] = (out['breakout_down'] > 0.5).astype(float)
    out['reverse_short_exit'] = (out['breakout_up'] > 0.5).astype(float)
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 'nr7', 'filtered_nr7', 'atr', 'atr_ma', 'trend_ma', 'breakout_up', 'breakout_down', 'reverse_long_exit', 'reverse_short_exit']].copy()
    return out.dropna()


class Mt5NR7FilteredFeed(bt.feeds.PandasData):
    lines = ('nr7', 'filtered_nr7', 'atr', 'atr_ma', 'trend_ma', 'breakout_up', 'breakout_down', 'reverse_long_exit', 'reverse_short_exit')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('nr7', 6), ('filtered_nr7', 7), ('atr', 8), ('atr_ma', 9), ('trend_ma', 10), ('breakout_up', 11), ('breakout_down', 12), ('reverse_long_exit', 13), ('reverse_short_exit', 14),
    )


class NR7BreakoutFilterExitStrategy(bt.Strategy):
    params = dict(
        stop_loss_atr=2.5,
        take_profit_atr=4.0,
        time_exit=5,
        lot_size=1.0,
        lookback=7,
        atr_period=14,
        atr_ma_period=50,
        use_trend_filter=True,
        ma_period=50,
        volatility_threshold=2.5,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_order = None
        self.entry_price = None
        self.entry_bar = None
        self.stop_loss = None
        self.take_profit = None
        self.position_type = 0
        self.broker_value_series = []

    def _get_position_size(self, target_notional_pct=1.0, price=None):
        if target_notional_pct <= 0:
            return 0.0
        broker_value = float(self.broker.getvalue())
        execution_price = float(self.data.close[0] if price is None else price)
        if broker_value <= 0 or execution_price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, 'mult', 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        size = broker_value * float(target_notional_pct) / (execution_price * multiplier)
        return max(0.01, round(size, 2))

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return
        if self.position:
            bars_held = self.bar_num - self.entry_bar
            if self.position_type == 1 and float(self.data.reverse_long_exit[0]) > 0.5:
                self.pending_order = self.close()
                self.position_type = 0
                return
            if self.position_type == -1 and float(self.data.reverse_short_exit[0]) > 0.5:
                self.pending_order = self.close()
                self.position_type = 0
                return
            if self.position_type == 1 and self.data.low[0] < self.stop_loss:
                self.pending_order = self.close()
                self.position_type = 0
                return
            if self.position_type == -1 and self.data.high[0] > self.stop_loss:
                self.pending_order = self.close()
                self.position_type = 0
                return
            if self.position_type == 1 and self.data.high[0] > self.take_profit:
                self.pending_order = self.close()
                self.position_type = 0
                return
            if self.position_type == -1 and self.data.low[0] < self.take_profit:
                self.pending_order = self.close()
                self.position_type = 0
                return
            if bars_held >= self.p.time_exit:
                self.pending_order = self.close()
                self.position_type = 0
            return
        atr = float(self.data.atr[0])
        if atr <= 0:
            return
        if float(self.data.breakout_up[0]) > 0.5:
            self.buy_count += 1
            self.entry_price = float(self.data.close[0])
            self.entry_bar = self.bar_num
            self.stop_loss = self.entry_price - self.p.stop_loss_atr * atr
            self.take_profit = self.entry_price + self.p.take_profit_atr * atr
            self.position_type = 1
            self.pending_order = self.buy(size=self._get_position_size(target_notional_pct=float(self.p.lot_size)))
        elif float(self.data.breakout_down[0]) > 0.5:
            self.sell_count += 1
            self.entry_price = float(self.data.close[0])
            self.entry_bar = self.bar_num
            self.stop_loss = self.entry_price + self.p.stop_loss_atr * atr
            self.take_profit = self.entry_price - self.p.take_profit_atr * atr
            self.position_type = -1
            self.pending_order = self.sell(size=self._get_position_size(target_notional_pct=float(self.p.lot_size)))

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
