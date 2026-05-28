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


def prepare_time_series_momentum_features(df, params):
    out = df.copy()
    lookback_months = int(params.get('lookback_months', 12))
    long_short = bool(params.get('long_short', True))
    lookback_days = lookback_months * 21
    close = out['close']
    out['tsm_return'] = close / close.shift(lookback_days) - 1.0
    out['month_key'] = out.index.to_period('M').astype(str)
    out['rebalance_signal'] = (out['month_key'] != out['month_key'].shift(1)).astype(float)
    out['target_signal'] = 0.0
    rebalance_mask = out['rebalance_signal'] > 0.5
    out.loc[rebalance_mask & (out['tsm_return'] > 0), 'target_signal'] = 1.0
    if long_short:
        out.loc[rebalance_mask & (out['tsm_return'] < 0), 'target_signal'] = -1.0
    else:
        out.loc[rebalance_mask & (out['tsm_return'] <= 0), 'target_signal'] = 0.0
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 'tsm_return', 'rebalance_signal', 'target_signal']].copy()
    return out.dropna()


class Mt5TimeSeriesMomentumFeed(bt.feeds.PandasData):
    lines = ('tsm_return', 'rebalance_signal', 'target_signal')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('tsm_return', 6), ('rebalance_signal', 7), ('target_signal', 8),
    )


class GoldTimeSeriesMomentumStrategy(bt.Strategy):
    params = dict(
        lot_size=1.0,
        lookback_months=12,
        rebalance_freq='M',
        long_short=True,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_order = None
        self.last_target_signal = None
        self.broker_value_series = []

    def _get_position_size(self, target_signal=1.0, price=None):
        if abs(target_signal) <= 0:
            return 0.0
        broker_value = float(self.broker.getvalue())
        execution_price = float(self.data.close[0] if price is None else price)
        if broker_value <= 0 or execution_price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, 'mult', 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        size = broker_value * float(self.p.lot_size) * abs(float(target_signal)) / (execution_price * multiplier)
        size = max(0.01, round(size, 2))
        return size if float(target_signal) > 0 else -size

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return
        if float(self.data.rebalance_signal[0]) <= 0.5:
            return
        target_signal = float(self.data.target_signal[0])
        if self.last_target_signal is not None and abs(target_signal - self.last_target_signal) < 1e-9:
            return
        current_size = float(self.position.size)
        target_size = self._get_position_size(target_signal=target_signal) if abs(target_signal) > 0 else 0.0
        self.pending_order = self.order_target_size(target=target_size)
        if self.pending_order is not None:
            if target_size > current_size:
                self.buy_count += 1
            elif target_size < current_size:
                self.sell_count += 1
        self.last_target_signal = target_signal

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
