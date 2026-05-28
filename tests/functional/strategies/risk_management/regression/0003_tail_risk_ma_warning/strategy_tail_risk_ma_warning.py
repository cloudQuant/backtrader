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


def prepare_tail_risk_features(df, params):
    out = df.copy()
    month_end_index = out.index.to_period('M').to_timestamp('M')
    monthly_close = out['close'].groupby(month_end_index).last()
    ma_period = int(params.get('ma_period_months', 10))
    monthly_ma = monthly_close.rolling(ma_period).mean()
    monthly_risk_state = (monthly_close < monthly_ma).astype(float)
    active_risk_state = monthly_risk_state.shift(1).reindex(month_end_index).fillna(0.0)
    out['monthly_close'] = monthly_close.reindex(month_end_index).to_numpy()
    out['monthly_ma'] = monthly_ma.reindex(month_end_index).to_numpy()
    out['risk_state'] = active_risk_state.to_numpy()
    normal_position = float(params.get('normal_position_pct', 1.0))
    risk_position = float(params.get('risk_position_pct', 0.5))
    out['target_pct'] = np.where(out['risk_state'] >= 0.5, risk_position, normal_position)
    monthly_returns = monthly_close.pct_change()
    large_loss_threshold = -abs(float(params.get('loss_threshold_pct', 5.0))) / 100.0
    monthly_large_loss = (monthly_returns <= large_loss_threshold).astype(float)
    monthly_large_loss_active = monthly_large_loss.reindex(month_end_index).fillna(0.0)
    out['large_loss_flag'] = monthly_large_loss_active.to_numpy()
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 'monthly_close', 'monthly_ma', 'risk_state', 'target_pct', 'large_loss_flag']].copy()
    monthly_table = pd.DataFrame({
        'monthly_close': monthly_close,
        'monthly_ma': monthly_ma,
        'risk_state': monthly_risk_state,
        'monthly_return': monthly_returns,
        'large_loss_flag': monthly_large_loss,
    }).dropna(subset=['monthly_close'])
    return out, monthly_table


class Mt5TailRiskFeed(bt.feeds.PandasData):
    lines = ('monthly_close', 'monthly_ma', 'risk_state', 'target_pct', 'large_loss_flag',)
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('monthly_close', 6),
        ('monthly_ma', 7),
        ('risk_state', 8),
        ('target_pct', 9),
        ('large_loss_flag', 10),
    )


class TailRiskMAWarningStrategy(bt.Strategy):
    params = dict(
        ma_period_months=10,
        loss_threshold_pct=5.0,
        normal_position_pct=1.0,
        risk_position_pct=0.5,
    )

    def __init__(self):
        self.bar_num = 0
        self.rebalance_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.risk_month_count = 0
        self.normal_month_count = 0
        self.state_switch_count = 0
        self.pending_order = None
        self.current_month = None
        self.last_target_pct = None
        self.broker_value_series = []

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _month_key(self):
        dt = bt.num2date(self.data.datetime[0])
        return dt.year, dt.month


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
        month_key = self._month_key()
        if month_key == self.current_month:
            return
        self.current_month = month_key
        target_pct = float(self.data.target_pct[0])
        risk_state = int(round(float(self.data.risk_state[0])))
        if risk_state == 1:
            self.risk_month_count += 1
        else:
            self.normal_month_count += 1
        if self.last_target_pct is not None and abs(target_pct - self.last_target_pct) > 1e-9:
            self.state_switch_count += 1
        self.last_target_pct = target_pct
        if self.pending_order is not None:
            return
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
