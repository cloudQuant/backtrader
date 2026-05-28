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


def prepare_first_day_month_features(price_df, params):
    out = price_df.copy()
    skip_months = set(int(v) for v in params.get('skip_months', [8]))
    periods = pd.Series(out.index.to_period('M'), index=out.index)
    prev_periods = periods.shift(1)
    out['is_first_trading_day'] = (periods != prev_periods).astype(float)
    out['is_skip_month'] = pd.Series([1.0 if idx.month in skip_months else 0.0 for idx in out.index], index=out.index)
    trade_day = (out['is_first_trading_day'] > 0.5) & (out['is_skip_month'] < 0.5)
    out['entry_signal'] = trade_day.shift(1).fillna(False).astype(float)
    out['exit_signal'] = trade_day.astype(float)
    return out


class FirstDayMonthFeed(bt.feeds.PandasData):
    lines = ('is_first_trading_day', 'is_skip_month', 'entry_signal', 'exit_signal')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('is_first_trading_day', 6), ('is_skip_month', 7), ('entry_signal', 8), ('exit_signal', 9),
    )


class FirstDayMonthStrategy(bt.Strategy):
    params = dict(
        position_size=0.10,
        holding_bars=1,
        skip_months=[8],
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
        self.signal_days = 0
        self.skipped_month_days = 0

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
        if float(self.data.is_first_trading_day[0]) > 0.5:
            if float(self.data.is_skip_month[0]) > 0.5:
                self.skipped_month_days += 1
            else:
                self.signal_days += 1
        if self.pending_order is not None:
            return
        if self.position:
            if float(self.data.exit_signal[0]) > 0.5:
                self.sell_count += 1
                self.pending_order = self.close()
            return
        if float(self.data.entry_signal[0]) > 0.5:
            self.buy_count += 1
            self.pending_order = self.buy(size=self._get_position_size(target_notional_pct=float(self.p.position_size)))

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
