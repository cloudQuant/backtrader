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


def prepare_bollinger_features(df, params):
    out = df.copy()
    period = int(params.get('period', 20))
    num_std = float(params.get('num_std', 2.0))
    ma_period = int(params.get('ma_period', 100))
    use_trend_filter = bool(params.get('use_trend_filter', True))
    close = out['close']
    out['middle'] = close.rolling(window=period).mean()
    out['std'] = close.rolling(window=period).std()
    out['upper'] = out['middle'] + num_std * out['std']
    out['lower'] = out['middle'] - num_std * out['std']
    out['bandwidth'] = (out['upper'] - out['lower']) / out['middle']
    band_span = (out['upper'] - out['lower']).replace(0, pd.NA)
    out['percent_b'] = (close - out['lower']) / band_span
    out['trend_ma'] = close.rolling(window=ma_period).mean()
    out['uptrend'] = (close > out['trend_ma']).astype(float)
    out['downtrend'] = (close < out['trend_ma']).astype(float)
    oversold = float(params.get('oversold_threshold', 0.05))
    overbought = float(params.get('overbought_threshold', 0.95))
    if use_trend_filter:
        out['long_entry'] = ((out['percent_b'] <= oversold) & (out['uptrend'] > 0.5)).astype(float)
        out['short_entry'] = ((out['percent_b'] >= overbought) & (out['downtrend'] > 0.5)).astype(float)
    else:
        out['long_entry'] = (out['percent_b'] <= oversold).astype(float)
        out['short_entry'] = (out['percent_b'] >= overbought).astype(float)
    out['long_exit'] = (close >= out['middle']).astype(float)
    out['short_exit'] = (close <= out['middle']).astype(float)
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 'upper', 'middle', 'lower', 'bandwidth', 'percent_b', 'trend_ma', 'long_entry', 'short_entry', 'long_exit', 'short_exit']].copy()
    return out.dropna()


class Mt5BollingerFeed(bt.feeds.PandasData):
    lines = ('upper', 'middle', 'lower', 'bandwidth', 'percent_b', 'trend_ma', 'long_entry', 'short_entry', 'long_exit', 'short_exit')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('upper', 6), ('middle', 7), ('lower', 8), ('bandwidth', 9), ('percent_b', 10), ('trend_ma', 11), ('long_entry', 12), ('short_entry', 13), ('long_exit', 14), ('short_exit', 15),
    )


class BollingerBandsSetupStrategy(bt.Strategy):
    params = dict(
        lot_size=1.0,
        period=20,
        num_std=2.0,
        oversold_threshold=0.05,
        overbought_threshold=0.95,
        use_trend_filter=True,
        ma_period=100,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_order = None
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
            if self.position_type == 1 and float(self.data.long_exit[0]) > 0.5:
                self.pending_order = self.close()
                self.position_type = 0
                return
            if self.position_type == -1 and float(self.data.short_exit[0]) > 0.5:
                self.pending_order = self.close()
                self.position_type = 0
                return
            return
        if float(self.data.long_entry[0]) > 0.5:
            self.buy_count += 1
            self.position_type = 1
            self.pending_order = self.buy(size=self._get_position_size(target_notional_pct=float(self.p.lot_size)))
        elif float(self.data.short_entry[0]) > 0.5:
            self.sell_count += 1
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
