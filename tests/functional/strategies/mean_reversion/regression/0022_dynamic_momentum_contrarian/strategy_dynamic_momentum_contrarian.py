from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
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
    df = df.set_index('datetime').sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def prepare_dynamic_features(df, params):
    out = df.copy()
    lookback = int(params.get('momentum_lookback_days', 252))
    crash_window = int(params.get('crash_window_days', 21))
    crash_threshold = float(params.get('crash_threshold', -0.15))
    contrarian_duration = int(params.get('contrarian_duration_days', 63))
    target_percent = float(params.get('target_percent', 0.95))
    returns = out['close'].pct_change().fillna(0.0)
    momentum = out['close'] / out['close'].shift(lookback) - 1.0
    crash_signal = returns.rolling(crash_window).sum() < crash_threshold
    signal = pd.Series(0.0, index=out.index)
    contrarian_days_left = 0
    regime = []
    for idx in range(len(out)):
        if idx < lookback:
            regime.append(0.0)
            continue
        if contrarian_days_left <= 0 and bool(crash_signal.iloc[idx]):
            contrarian_days_left = contrarian_duration
        if contrarian_days_left > 0:
            signal.iloc[idx] = 1.0
            regime.append(1.0)
            contrarian_days_left -= 1
        else:
            if float(momentum.iloc[idx]) > 0.0:
                signal.iloc[idx] = 1.0
                regime.append(2.0)
            else:
                signal.iloc[idx] = 0.0
                regime.append(0.0)
    out['return_1d'] = returns.to_numpy()
    out['momentum'] = momentum.to_numpy()
    out['crash_signal'] = crash_signal.astype(float).to_numpy()
    out['regime'] = np.array(regime, dtype=float)
    out['signal'] = signal.to_numpy()
    out['target_pct'] = out['signal'] * target_percent
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 'return_1d', 'momentum', 'crash_signal', 'regime', 'signal', 'target_pct']].copy()
    return out


class Mt5DynamicFeed(bt.feeds.PandasData):
    lines = ('return_1d', 'momentum', 'crash_signal', 'regime', 'signal', 'target_pct',)
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('return_1d', 6),
        ('momentum', 7),
        ('crash_signal', 8),
        ('regime', 9),
        ('signal', 10),
        ('target_pct', 11),
    )


class DynamicMomentumContrarianStrategy(bt.Strategy):
    params = dict(
        momentum_lookback_days=252,
        crash_window_days=21,
        crash_threshold=-0.15,
        contrarian_duration_days=63,
        target_percent=0.95,
    )

    def __init__(self):
        self.bar_num = 0
        self.rebalance_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.momentum_mode_days = 0
        self.contrarian_mode_days = 0
        self.flat_days = 0
        self.switch_count = 0
        self.pending_order = None
        self.last_target_pct = None
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


    def _current_position_pct(self):
        broker_value = float(self.broker.getvalue())
        if broker_value <= 0:
            return 0.0
        price = float(self.data.close[0])
        if price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, 'mult', 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        return float(self.position.size) * price * multiplier / broker_value


    def _order_target_notional_pct(self, target_pct):
        target_size = self._get_position_size(target_notional_pct=target_pct)
        return self.order_target_size(target=target_size)

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        regime = int(round(float(self.data.regime[0])))
        if regime == 1:
            self.contrarian_mode_days += 1
        elif regime == 2:
            self.momentum_mode_days += 1
        else:
            self.flat_days += 1
        target_pct = float(self.data.target_pct[0])
        if self.pending_order is not None:
            return
        if self.last_target_pct is not None and abs(target_pct - self.last_target_pct) > 1e-9:
            self.switch_count += 1
        self.last_target_pct = target_pct
        current_pct = self._current_position_pct()
        if abs(current_pct - target_pct) < 0.02:
            return
        self.rebalance_count += 1
        self.pending_order = self._order_target_notional_pct(target_pct)
        if target_pct > current_pct:
            self.buy_count += 1
        elif target_pct < current_pct:
            self.sell_count += 1

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        # 无论订单状态如何，都清除挂单引用
        self.pending_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
