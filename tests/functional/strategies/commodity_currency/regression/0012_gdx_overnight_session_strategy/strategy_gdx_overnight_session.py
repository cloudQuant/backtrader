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
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume',
        '<VOL>': 'real_volume',
    })
    df['openinterest'] = 0
    df['volume'] = df['tick_volume'] if 'tick_volume' in df.columns else 0
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.dropna(subset=['datetime']).set_index('datetime').sort_index()
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def prepare_overnight_features(df):
    out = df.copy()
    out['next_open_price'] = out['open'].shift(-1)
    out['overnight_return'] = out['next_open_price'] / out['close'] - 1.0
    out['intraday_return'] = out['close'] / out['open'] - 1.0
    out['trend_ma'] = out['close'].rolling(50).mean()
    out['trade_signal'] = (out['close'] > out['trend_ma']).astype(float)
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 'next_open_price', 'overnight_return', 'intraday_return', 'trend_ma', 'trade_signal']].copy()
    return out.dropna(subset=['next_open_price', 'trend_ma'])


class GDXOvernightFeed(bt.feeds.PandasData):
    lines = ('next_open_price', 'overnight_return', 'intraday_return', 'trend_ma', 'trade_signal')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('next_open_price', 6), ('overnight_return', 7), ('intraday_return', 8), ('trend_ma', 9), ('trade_signal', 10),
    )


class GDXOvernightSessionStrategy(bt.Strategy):
    params = dict(
        use_trend_filter=False,
        trend_ma_period=50,
        target_pct=1.0,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.pending_order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.broker_value_series = []
        self.entry_session_date = None

    def _get_position_size(self, target_notional_pct=1.0, price=None):
        if target_notional_pct <= 0:
            return 0.0
        broker_value = float(self.broker.getvalue())
        execution_price = float(self.data.open[0] if price is None else price)
        if broker_value <= 0 or execution_price <= 0:
            return 0.0
        size = broker_value * float(target_notional_pct) * 0.995 / execution_price
        return max(0.01, round(size, 4))

    def _can_enter(self):
        if not bool(self.p.use_trend_filter):
            return True
        return float(self.data.trade_signal[0]) > 0.5

    def next_open(self):
        if self.pending_order is not None:
            return
        current_session_date = bt.num2date(self.data.datetime[0]).date()
        if self.position and self.entry_session_date is not None and current_session_date > self.entry_session_date:
            self.sell_count += 1
            self.pending_order = self.close()

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return
        if self.position:
            return
        if not self._can_enter():
            return
        if not pd.notna(self.data.next_open_price[0]) or float(self.data.next_open_price[0]) <= 0:
            return
        size = self._get_position_size(target_notional_pct=float(self.p.target_pct), price=float(self.data.close[0]))
        if size <= 0:
            return
        self.buy_count += 1
        self.entry_session_date = bt.num2date(self.data.datetime[0]).date()
        self.pending_order = self.buy(size=size)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if order.status in (order.Canceled, order.Margin, order.Rejected):
            if not self.position:
                self.entry_session_date = None
        if order.status == order.Completed and not self.position:
            self.entry_session_date = None
        self.pending_order = None
