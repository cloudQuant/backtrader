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


def prepare_trend_equity_features(df, params):
    out = df[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    fast_ma = int(params.get('fast_ma', 50))
    slow_ma = int(params.get('slow_ma', 200))
    momentum_window = int(params.get('momentum_window', 63))
    vol_fast = int(params.get('volatility_window_fast', 21))
    vol_slow = int(params.get('volatility_window_slow', 63))
    decomposition_type = str(params.get('decomposition_type', 'put_overlay')).strip().lower()
    require_confirmation = bool(params.get('require_confirmation', True))

    out['returns'] = out['close'].pct_change()
    out['fast_ma'] = out['close'].rolling(fast_ma).mean()
    out['slow_ma'] = out['close'].rolling(slow_ma).mean()
    out['momentum'] = out['close'].pct_change(momentum_window)
    out['volatility_fast'] = out['returns'].rolling(vol_fast).std()
    out['volatility_slow'] = out['returns'].rolling(vol_slow).std()

    out['ma_signal'] = (out['fast_ma'] > out['slow_ma']).astype(float)
    out['momentum_confirm'] = (out['momentum'] > 0).astype(float)
    out['volatility_confirm'] = (out['volatility_fast'] < out['volatility_slow']).astype(float)
    out['confirmed_signal'] = (
        (out['ma_signal'] > 0.5)
        & (out['momentum_confirm'] > 0.5)
        & (out['volatility_confirm'] > 0.5)
    ).astype(float)
    signal_col = 'confirmed_signal' if require_confirmation else 'ma_signal'
    out['trend_signal'] = out[signal_col].astype(float)

    if decomposition_type == 'straddle':
        out['strategic_gold'] = 0.5
        out['strategic_cash'] = 0.5
        out['overlay'] = out['trend_signal'].map({1.0: 0.5, 0.0: -0.5})
    else:
        out['strategic_gold'] = 1.0
        out['strategic_cash'] = 0.0
        out['overlay'] = out['trend_signal'].map({1.0: 0.0, 0.0: -1.0})

    out['target_exposure'] = (out['strategic_gold'] + out['overlay']).clip(lower=0.0, upper=1.0)
    out['signal_change'] = out['trend_signal'].diff().fillna(1.0).abs().astype(float)
    out['turnover_flag'] = (out['target_exposure'].diff().abs().fillna(out['target_exposure'].abs()) > 0).astype(float)

    columns = [
        'open', 'high', 'low', 'close', 'volume', 'openinterest', 'returns',
        'fast_ma', 'slow_ma', 'momentum', 'volatility_fast', 'volatility_slow',
        'ma_signal', 'momentum_confirm', 'volatility_confirm', 'trend_signal',
        'strategic_gold', 'strategic_cash', 'overlay', 'target_exposure',
        'signal_change', 'turnover_flag',
    ]
    return out[columns].dropna().copy()


class TrendEquityDecompositionFeed(bt.feeds.PandasData):
    lines = (
        'returns', 'fast_ma', 'slow_ma', 'momentum', 'volatility_fast', 'volatility_slow',
        'ma_signal', 'momentum_confirm', 'volatility_confirm', 'trend_signal',
        'strategic_gold', 'strategic_cash', 'overlay', 'target_exposure',
        'signal_change', 'turnover_flag',
    )
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('returns', 6), ('fast_ma', 7), ('slow_ma', 8), ('momentum', 9), ('volatility_fast', 10), ('volatility_slow', 11),
        ('ma_signal', 12), ('momentum_confirm', 13), ('volatility_confirm', 14), ('trend_signal', 15),
        ('strategic_gold', 16), ('strategic_cash', 17), ('overlay', 18), ('target_exposure', 19),
        ('signal_change', 20), ('turnover_flag', 21),
    )


class TrendEquityDecompositionStrategy(bt.Strategy):
    params = dict(
        fast_ma=50,
        slow_ma=200,
        momentum_window=63,
        volatility_window_fast=21,
        volatility_window_slow=63,
        decomposition_type='put_overlay',
        require_confirmation=True,
        rebalance_interval_days=5,
    )

    def __init__(self):
        self.bar_num = 0
        self.pending_order = None
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.signal_change_count = 0
        self.turnover_events = 0
        self.long_days = 0
        self.flat_days = 0
        self.broker_value_series = []
        self.exposure_series = []
        self.overlay_series = []

    def _target_size(self, target_pct):
        broker_value = float(self.broker.getvalue())
        price = float(self.data.close[0])
        if broker_value <= 0 or price <= 0 or target_pct <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, 'mult', 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        size = broker_value * float(target_pct) / (price * multiplier)
        return max(0.01, round(size, 2))

    def next(self):
        self.bar_num += 1
        current_value = float(self.broker.getvalue())
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), current_value))

        target_exposure = float(self.data.target_exposure[0])
        overlay = float(self.data.overlay[0])
        self.exposure_series.append(target_exposure)
        self.overlay_series.append(overlay)

        if target_exposure > 0.5:
            self.long_days += 1
        else:
            self.flat_days += 1

        if float(self.data.signal_change[0]) > 0.5:
            self.signal_change_count += 1
        if float(self.data.turnover_flag[0]) > 0.5:
            self.turnover_events += 1

        if self.pending_order is not None:
            return
        if self.bar_num > 1 and (self.bar_num - 1) % max(1, int(self.p.rebalance_interval_days)) != 0 and float(self.data.signal_change[0]) <= 0.5:
            return

        current_size = float(self.getposition(self.data).size)
        target_size = self._target_size(target_exposure)
        if abs(current_size - target_size) < 0.01:
            return
        self.pending_order = self.order_target_size(data=self.data, target=target_size)

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
