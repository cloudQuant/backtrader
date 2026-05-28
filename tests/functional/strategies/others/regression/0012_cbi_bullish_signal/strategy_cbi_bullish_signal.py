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
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low', '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume', '<VOL>': 'real_volume',
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


def calculate_rsi(prices, period=14):
    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean().replace(0, pd.NA)
    rs = avg_gain / avg_loss
    return (100 - (100 / (1 + rs))).fillna(50.0)


def prepare_cbi_bullish_features(df, params):
    out = df.copy()
    rsi_period = int(params.get('rsi_period', 14))
    rsi_oversold = float(params.get('rsi_oversold', 25))
    low_period = int(params.get('low_period', 20))
    volume_window = int(params.get('volume_window', 20))
    volume_multiplier = float(params.get('volume_multiplier', 1.5))
    out['rsi'] = calculate_rsi(out['close'], rsi_period)
    out['rolling_low'] = out['close'].rolling(window=low_period).min()
    out['avg_volume'] = out['volume'].rolling(window=volume_window).mean()
    out['is_new_low'] = (out['close'] <= out['rolling_low']).astype(float)
    out['oversold'] = (out['rsi'] < rsi_oversold).astype(float)
    out['volume_spike'] = (out['volume'] > out['avg_volume'] * volume_multiplier).astype(float)
    out['entry_signal'] = ((out['is_new_low'] > 0.5) & (out['oversold'] > 0.5) & (out['volume_spike'] > 0.5)).astype(float)
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 'rsi', 'rolling_low', 'avg_volume', 'is_new_low', 'oversold', 'volume_spike', 'entry_signal']].copy()
    return out.dropna()


class Mt5CBIBullishFeed(bt.feeds.PandasData):
    lines = ('rsi', 'rolling_low', 'avg_volume', 'is_new_low', 'oversold', 'volume_spike', 'entry_signal',)
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('rsi', 6),
        ('rolling_low', 7),
        ('avg_volume', 8),
        ('is_new_low', 9),
        ('oversold', 10),
        ('volume_spike', 11),
        ('entry_signal', 12),
    )


class CBIBullishSignalStrategy(bt.Strategy):
    params = dict(
        rsi_period=14,
        rsi_oversold=25,
        low_period=20,
        volume_window=20,
        volume_multiplier=1.5,
        holding_days=15,
        stop_loss_pct=0.03,
        take_profit_pct=0.05,
        lot_size=0.2,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.signal_count = 0
        self.time_exit_count = 0
        self.stop_loss_exit_count = 0
        self.take_profit_exit_count = 0
        self.pending_order = None
        self.pending_exit_reason = None
        self.entry_bar = None
        self.entry_price = None
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

        entry_signal = float(self.data.entry_signal[0]) > 0.5

        if not self.position:
            if entry_signal:
                self.signal_count += 1
                self.buy_count += 1
                self.entry_bar = self.bar_num
                self.entry_price = float(self.data.close[0])
                self.pending_order = self.buy(size=self._get_position_size(target_notional_pct=float(self.p.lot_size)))
            return

        current_price = float(self.data.close[0])
        pnl_pct = (current_price - self.entry_price) / self.entry_price if self.entry_price else 0.0
        holding_days = self.bar_num - (self.entry_bar or self.bar_num)
        exit_reason = None

        if pnl_pct <= -float(self.p.stop_loss_pct):
            exit_reason = 'stop_loss'
        elif pnl_pct >= float(self.p.take_profit_pct):
            exit_reason = 'take_profit'
        elif holding_days >= int(self.p.holding_days):
            exit_reason = 'time_exit'

        if exit_reason is not None:
            self.sell_count += 1
            self.pending_exit_reason = exit_reason
            self.pending_order = self.close()

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if order.status == order.Completed and order.issell() and self.pending_exit_reason:
            if self.pending_exit_reason == 'time_exit':
                self.time_exit_count += 1
            elif self.pending_exit_reason == 'stop_loss':
                self.stop_loss_exit_count += 1
            elif self.pending_exit_reason == 'take_profit':
                self.take_profit_exit_count += 1
            self.pending_exit_reason = None
            self.entry_bar = None
            self.entry_price = None
        elif order.status == order.Completed and order.isbuy():
            self.entry_price = float(order.executed.price or self.data.close[0])
        if order.status in (order.Completed, order.Canceled, order.Margin, order.Rejected):
            self.pending_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
