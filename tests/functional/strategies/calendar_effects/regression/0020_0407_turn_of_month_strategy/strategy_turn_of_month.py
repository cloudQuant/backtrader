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


def prepare_turn_of_month_features(price_df, params):
    last_days = int(params.get('last_days', 3))
    first_days = int(params.get('first_days', 3))
    out = price_df.copy()
    current_period = pd.Series(out.index, index=out.index).dt.to_period('M')
    fwd_rank = pd.Series(range(len(out)), index=out.index).groupby(current_period).transform(lambda x: x.rank(method='first'))
    rev_rank = pd.Series(range(len(out)), index=out.index).groupby(current_period).transform(lambda x: x.rank(ascending=False, method='first'))
    out['is_month_end_window'] = (rev_rank <= last_days).astype(float)
    out['is_month_start_window'] = (fwd_rank <= first_days).astype(float)
    in_window = (out['is_month_end_window'] > 0.5) | (out['is_month_start_window'] > 0.5)
    prev_in_window = in_window.shift(1).fillna(False)
    out['in_turn_window'] = in_window.astype(float)
    out['entry_signal'] = (in_window & (~prev_in_window)).astype(float)
    out['exit_signal'] = ((~in_window) & prev_in_window).astype(float)
    return out


class TurnOfMonthFeed(bt.feeds.PandasData):
    lines = ('is_month_end_window', 'is_month_start_window', 'in_turn_window', 'entry_signal', 'exit_signal')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('is_month_end_window', 6), ('is_month_start_window', 7), ('in_turn_window', 8), ('entry_signal', 9), ('exit_signal', 10),
    )


class TurnOfMonthStrategy(bt.Strategy):
    params = dict(
        stop_loss_pct=0.02,
        last_days=3,
        first_days=3,
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
        self.entry_price = None
        self.stop_price = None
        self.broker_value_series = []
        self.window_days = 0

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if float(self.data.in_turn_window[0]) > 0.5:
            self.window_days += 1
        if self.pending_order is not None:
            return
        close = float(self.data.close[0])
        low = float(self.data.low[0])
        if self.position:
            if self.stop_price is not None and low <= self.stop_price:
                self.sell_count += 1
                self.pending_order = self.close()
                return
            if float(self.data.exit_signal[0]) > 0.5:
                self.sell_count += 1
                self.pending_order = self.close()
                return
            return
        if float(self.data.entry_signal[0]) > 0.5:
            self.buy_count += 1
            self.pending_order = self.order_target_percent(target=1.0)
            self.entry_price = close
            self.stop_price = close * (1.0 - float(self.p.stop_loss_pct))

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
        if not self.position:
            self.entry_price = None
            self.stop_price = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
