from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

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


def prepare_trend_equity_primer_features(df, params):
    out = df[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    ma_fast = int(params.get('ma_fast', 50))
    ma_slow = int(params.get('ma_slow', 200))
    momentum_window = int(params.get('momentum_window', 63))
    breakout_window = int(params.get('breakout_window', 63))
    volatility_window = int(params.get('volatility_window', 21))
    position_method = str(params.get('position_method', 'long_flat')).strip().lower()
    target_volatility = float(params.get('target_volatility', 0.18))
    max_leverage = float(params.get('max_leverage', 1.5))
    use_momentum_confirmation = bool(params.get('use_momentum_confirmation', False))
    use_breakout_confirmation = bool(params.get('use_breakout_confirmation', False))
    apply_trend_filter_to_risk_parity = bool(params.get('apply_trend_filter_to_risk_parity', True))

    out['returns'] = out['close'].pct_change()
    out['fast_ma'] = out['close'].rolling(ma_fast).mean()
    out['slow_ma'] = out['close'].rolling(ma_slow).mean()
    out['momentum'] = out['close'].pct_change(momentum_window)
    out['breakout_level'] = out['close'].rolling(breakout_window).max().shift(1)
    out['realized_volatility'] = out['returns'].rolling(volatility_window).std() * math.sqrt(252.0)

    out['trend_signal'] = (out['fast_ma'] > out['slow_ma']).astype(float)
    out['momentum_confirm'] = (out['momentum'] > 0).astype(float)
    out['breakout_confirm'] = (out['close'] > out['breakout_level']).astype(float)

    confirmed = out['trend_signal'] > 0.5
    if use_momentum_confirmation:
        confirmed = confirmed & (out['momentum_confirm'] > 0.5)
    if use_breakout_confirmation:
        confirmed = confirmed & (out['breakout_confirm'] > 0.5)
    out['confirmed_signal'] = confirmed.astype(float)

    vol = out['realized_volatility'].replace(0, pd.NA)
    out['risk_parity_raw'] = (target_volatility / vol).astype(float)
    out['risk_parity_raw'] = out['risk_parity_raw'].clip(lower=0.0, upper=max_leverage)
    if apply_trend_filter_to_risk_parity:
        out['risk_parity_exposure'] = out['risk_parity_raw'] * out['confirmed_signal']
    else:
        out['risk_parity_exposure'] = out['risk_parity_raw']

    out['long_flat_exposure'] = out['confirmed_signal'].astype(float)
    if position_method == 'risk_parity':
        out['target_exposure'] = out['risk_parity_exposure']
    else:
        out['target_exposure'] = out['long_flat_exposure']

    out['cash_weight'] = (1.0 - out['target_exposure']).clip(lower=0.0)
    out['signal_change'] = out['confirmed_signal'].diff().fillna(1.0).abs().astype(float)
    out['turnover_flag'] = (out['target_exposure'].diff().abs().fillna(out['target_exposure'].abs()) > 1e-12).astype(float)

    columns = [
        'open', 'high', 'low', 'close', 'volume', 'openinterest', 'returns',
        'fast_ma', 'slow_ma', 'momentum', 'breakout_level', 'realized_volatility',
        'trend_signal', 'momentum_confirm', 'breakout_confirm', 'confirmed_signal',
        'long_flat_exposure', 'risk_parity_raw', 'risk_parity_exposure', 'target_exposure',
        'cash_weight', 'signal_change', 'turnover_flag',
    ]
    return out[columns].dropna().copy()


class TrendEquityPrimerFeed(bt.feeds.PandasData):
    lines = (
        'returns', 'fast_ma', 'slow_ma', 'momentum', 'breakout_level', 'realized_volatility',
        'trend_signal', 'momentum_confirm', 'breakout_confirm', 'confirmed_signal',
        'long_flat_exposure', 'risk_parity_raw', 'risk_parity_exposure', 'target_exposure',
        'cash_weight', 'signal_change', 'turnover_flag',
    )
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('returns', 6), ('fast_ma', 7), ('slow_ma', 8), ('momentum', 9), ('breakout_level', 10), ('realized_volatility', 11),
        ('trend_signal', 12), ('momentum_confirm', 13), ('breakout_confirm', 14), ('confirmed_signal', 15),
        ('long_flat_exposure', 16), ('risk_parity_raw', 17), ('risk_parity_exposure', 18), ('target_exposure', 19),
        ('cash_weight', 20), ('signal_change', 21), ('turnover_flag', 22),
    )


class TrendEquityPrimerStrategy(bt.Strategy):
    params = dict(
        ma_fast=50,
        ma_slow=200,
        momentum_window=63,
        breakout_window=63,
        volatility_window=21,
        position_method='risk_parity',
        target_volatility=0.18,
        max_leverage=1.5,
        use_momentum_confirmation=False,
        use_breakout_confirmation=False,
        apply_trend_filter_to_risk_parity=True,
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
        self.volatility_series = []

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
        realized_volatility = float(self.data.realized_volatility[0])
        self.exposure_series.append(target_exposure)
        self.volatility_series.append(realized_volatility)

        if target_exposure > 0.05:
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
