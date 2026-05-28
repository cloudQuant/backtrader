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
    df = df.dropna(subset=['datetime']).set_index('datetime').sort_index()
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def prepare_intraday_seasonality_features(price_df, params):
    out = price_df.copy()
    buy_hour = int(params.get('buy_hour_utc', 21))
    sell_hour = int(params.get('sell_hour_utc', 23))
    fixed_target_percent = float(params.get('fixed_target_percent', 1.0))
    out['hour'] = out.index.hour.astype(float)
    out['buy_signal'] = (out.index.hour == buy_hour).astype(float)
    out['sell_signal'] = (out.index.hour == sell_hour).astype(float)
    out['target_percent'] = 0.0
    in_window = ((out.index.hour >= buy_hour) & (out.index.hour < sell_hour)).astype(float)
    out.loc[in_window > 0, 'target_percent'] = fixed_target_percent
    return out[[
        'open', 'high', 'low', 'close', 'volume', 'openinterest', 'hour', 'buy_signal', 'sell_signal', 'target_percent'
    ]].dropna().copy()


class BitcoinSeasonalityFeed(bt.feeds.PandasData):
    lines = ('hour', 'buy_signal', 'sell_signal', 'target_percent')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('hour', 6), ('buy_signal', 7), ('sell_signal', 8), ('target_percent', 9),
    )


class BitcoinSeasonalityStrategy(bt.Strategy):
    params = dict(
        fixed_target_percent=1.0,
        buy_hour_utc=21,
        sell_hour_utc=23,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_order = None
        self.broker_value_series = []
        self.seasonality_hours = 0

    def _current_exposure(self):
        broker_value = float(self.broker.getvalue())
        price = float(self.data.close[0])
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, 'mult', 1.0) or 1.0)
        if broker_value <= 0 or price <= 0 or multiplier <= 0:
            return 0.0
        return float(self.position.size) * price * multiplier / broker_value

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if float(self.data.target_percent[0]) > 0:
            self.seasonality_hours += 1
        if self.pending_order is not None:
            return
        target_percent = float(self.data.target_percent[0])
        current_exposure = self._current_exposure()
        if abs(target_percent - current_exposure) < 0.03:
            return
        if target_percent > current_exposure:
            self.buy_count += 1
        elif target_percent < current_exposure:
            self.sell_count += 1
        self.pending_order = self.order_target_percent(target=target_percent)

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
