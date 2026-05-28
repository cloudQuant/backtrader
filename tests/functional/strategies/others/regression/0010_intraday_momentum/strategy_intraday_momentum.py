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
    parsed = pd.to_datetime(dt_text, format='%Y.%m.%d %H:%M:%S', errors='coerce')
    if parsed.isna().any():
        parsed = pd.to_datetime(dt_text, format='%Y.%m.%d %H:%M', errors='coerce')
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


def prepare_intraday_momentum_features(df, params):
    signal_bar_index = int(params.get('signal_bar_index', 11))
    signal_threshold = float(params.get('signal_threshold', 0.0015))
    gross_exposure = float(params.get('gross_exposure', 0.95))

    frame = df.copy()
    frame['session_date'] = frame.index.date
    frame['bar_slot'] = frame.groupby('session_date').cumcount()
    frame['session_open'] = frame.groupby('session_date')['open'].transform('first')
    frame['morning_return'] = frame['close'] / frame['session_open'] - 1.0
    frame['is_eod'] = frame['session_date'] != frame['session_date'].shift(-1)

    target_pct = []
    signal_change = []
    session_signal = 0.0
    prev_session = None
    prev_target = 0.0

    for row in frame.itertuples():
        session_date = row.session_date
        if session_date != prev_session:
            session_signal = 0.0
            prev_session = session_date
        if row.bar_slot == signal_bar_index:
            if row.morning_return >= signal_threshold:
                session_signal = gross_exposure
            elif row.morning_return <= -signal_threshold:
                session_signal = -gross_exposure
            else:
                session_signal = 0.0
        if bool(row.is_eod):
            target = 0.0
        else:
            target = session_signal
        target_pct.append(target)
        signal_change.append(1.0 if target != prev_target else 0.0)
        prev_target = target

    frame['target_pct'] = target_pct
    frame['signal_change'] = signal_change
    feature_cols = ['open', 'high', 'low', 'close', 'volume', 'openinterest', 'morning_return', 'target_pct', 'signal_change', 'is_eod']
    return frame[feature_cols].dropna()


class IntradayMomentumFeed(bt.feeds.PandasData):
    lines = ('morning_return', 'target_pct', 'signal_change', 'is_eod')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('morning_return', 6), ('target_pct', 7), ('signal_change', 8), ('is_eod', 9),
    )


class GoldIntradayMomentumStrategy(bt.Strategy):
    params = dict(
        stop_loss_pct=0.004,
        take_profit_pct=0.008,
        signal_bar_index=11,
        signal_threshold=0.0015,
        gross_exposure=0.95,
        commission_pct=0.0002,
    )

    def __init__(self):
        self.pending_order = None
        self.bar_num = 0
        self.signal_change_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.entry_price = None
        self.broker_value_series = []

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return
        if self.position:
            pnl_pct = 0.0
            if self.entry_price:
                direction = 1.0 if self.position.size > 0 else -1.0
                pnl_pct = direction * (float(self.data.close[0]) / self.entry_price - 1.0)
            if pnl_pct <= -float(self.p.stop_loss_pct) or pnl_pct >= float(self.p.take_profit_pct):
                self.pending_order = self.close()
                return
        if float(self.data.signal_change[0]) <= 0.5:
            return
        self.signal_change_count += 1
        self.pending_order = self.order_target_percent(target=float(self.data.target_pct[0]))

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if order.status == order.Completed:
            if float(order.executed.size) > 0:
                self.buy_count += 1
            elif float(order.executed.size) < 0:
                self.sell_count += 1
            if order.size != 0 and self.position:
                self.entry_price = float(order.executed.price)
            elif not self.position:
                self.entry_price = None
        self.pending_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
