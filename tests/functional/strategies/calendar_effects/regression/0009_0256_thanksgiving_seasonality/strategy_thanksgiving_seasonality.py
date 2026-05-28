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


def get_thanksgiving_date(year):
    nov_first = pd.Timestamp(year=year, month=11, day=1)
    offset = (3 - nov_first.weekday()) % 7
    return nov_first + pd.Timedelta(days=offset + 21)


def find_last_trading_day(index, target_date, weekday, max_days=7):
    candidates = index[(index <= target_date) & (index.weekday == weekday)]
    if len(candidates) == 0:
        return None
    candidate = candidates[-1]
    if (target_date - candidate) > pd.Timedelta(days=max_days):
        return None
    return candidate


def find_first_trading_day(index, target_date, weekday, max_days=7):
    candidates = index[(index > target_date) & (index.weekday == weekday)]
    if len(candidates) == 0:
        return None
    candidate = candidates[0]
    if (candidate - target_date) > pd.Timedelta(days=max_days):
        return None
    return candidate


def prepare_thanksgiving_features(price_df, params):
    out = price_df.copy()
    use_tuesday_filter = bool(params.get('use_tuesday_filter', True))
    tuesday_close_fraction = float(params.get('tuesday_close_fraction', 0.5))
    out['setup_code'] = 0.0
    out['tuesday_filter_pass'] = 0.0
    out['long_setup'] = 0.0
    out['short_setup'] = 0.0
    out['thanksgiving_year'] = 0.0
    index = pd.DatetimeIndex(out.index)
    for year in sorted(index.year.unique()):
        thanksgiving = get_thanksgiving_date(int(year))
        pre_tuesday = find_last_trading_day(index, thanksgiving - pd.Timedelta(days=1), weekday=1, max_days=7)
        post_friday = find_first_trading_day(index, thanksgiving, weekday=4, max_days=4)
        if pre_tuesday is None and post_friday is None:
            continue
        filter_pass = True
        if pre_tuesday is not None:
            bar = out.loc[pre_tuesday]
            day_range = float(bar['high'] - bar['low'])
            threshold_price = float(bar['low']) + max(day_range, 0.0) * tuesday_close_fraction
            filter_pass = float(bar['close']) <= threshold_price if day_range > 0 else True
            if not use_tuesday_filter:
                filter_pass = True
            out.loc[pre_tuesday, 'tuesday_filter_pass'] = 1.0 if filter_pass else 0.0
            out.loc[pre_tuesday, 'thanksgiving_year'] = float(year)
            if filter_pass:
                out.loc[pre_tuesday, 'long_setup'] = 1.0
                out.loc[pre_tuesday, 'setup_code'] = 1.0
        if post_friday is not None:
            out.loc[post_friday, 'short_setup'] = 1.0
            out.loc[post_friday, 'setup_code'] = 2.0
            out.loc[post_friday, 'thanksgiving_year'] = float(year)
    out = out[[
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'setup_code', 'tuesday_filter_pass', 'long_setup', 'short_setup', 'thanksgiving_year',
    ]].copy()
    return out.dropna()


class Mt5ThanksgivingSeasonalityFeed(bt.feeds.PandasData):
    lines = ('setup_code', 'tuesday_filter_pass', 'long_setup', 'short_setup', 'thanksgiving_year')
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('setup_code', 6),
        ('tuesday_filter_pass', 7),
        ('long_setup', 8),
        ('short_setup', 9),
        ('thanksgiving_year', 10),
    )


class ThanksgivingSeasonalityStrategy(bt.Strategy):
    params = dict(
        long_hold_bars=2,
        short_hold_bars=1,
        long_target_pct=0.20,
        short_target_pct=0.10,
        stop_loss_pct=0.025,
        take_profit_pct=0.03,
        use_tuesday_filter=True,
        tuesday_close_fraction=0.5,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.long_setup_count = 0
        self.short_setup_count = 0
        self.long_entry_count = 0
        self.short_entry_count = 0
        self.time_exit_count = 0
        self.stop_exit_count = 0
        self.take_exit_count = 0
        self.pending_order = None
        self.pending_open_side = None
        self.pending_exit_reason = None
        self.entry_bar = None
        self.entry_price = None
        self.active_side = 0
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
        if float(self.data.long_setup[0]) > 0.5:
            self.long_setup_count += 1
        if float(self.data.short_setup[0]) > 0.5:
            self.short_setup_count += 1
        if self.pending_order is not None:
            return
        close_price = float(self.data.close[0])
        if self.position:
            holding_bars = self.bar_num - (self.entry_bar or self.bar_num)
            exit_reason = None
            if self.active_side > 0:
                if self.entry_price is not None and close_price <= self.entry_price * (1.0 - float(self.p.stop_loss_pct)):
                    exit_reason = 'stop_loss'
                elif self.entry_price is not None and close_price >= self.entry_price * (1.0 + float(self.p.take_profit_pct)):
                    exit_reason = 'take_profit'
                elif holding_bars >= int(self.p.long_hold_bars):
                    exit_reason = 'time_exit'
            elif self.active_side < 0:
                if self.entry_price is not None and close_price >= self.entry_price * (1.0 + float(self.p.stop_loss_pct)):
                    exit_reason = 'stop_loss'
                elif self.entry_price is not None and close_price <= self.entry_price * (1.0 - float(self.p.take_profit_pct)):
                    exit_reason = 'take_profit'
                elif holding_bars >= int(self.p.short_hold_bars):
                    exit_reason = 'time_exit'
            if exit_reason is not None:
                if self.active_side > 0:
                    self.sell_count += 1
                else:
                    self.buy_count += 1
                self.pending_exit_reason = exit_reason
                self.pending_order = self.close()
                return
            return
        if float(self.data.long_setup[0]) > 0.5:
            size = self._get_position_size(target_notional_pct=float(self.p.long_target_pct))
            if size > 0:
                self.buy_count += 1
                self.long_entry_count += 1
                self.pending_open_side = 1
                self.pending_order = self.buy(size=size)
                return
        if float(self.data.short_setup[0]) > 0.5:
            size = self._get_position_size(target_notional_pct=float(self.p.short_target_pct))
            if size > 0:
                self.sell_count += 1
                self.short_entry_count += 1
                self.pending_open_side = -1
                self.pending_order = self.sell(size=size)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if order.status == order.Completed:
            if self.pending_open_side is not None:
                self.active_side = int(self.pending_open_side)
                self.entry_price = float(order.executed.price or self.data.close[0])
                self.entry_bar = self.bar_num
                self.pending_open_side = None
            elif self.pending_exit_reason is not None:
                if self.pending_exit_reason == 'time_exit':
                    self.time_exit_count += 1
                elif self.pending_exit_reason == 'stop_loss':
                    self.stop_exit_count += 1
                elif self.pending_exit_reason == 'take_profit':
                    self.take_exit_count += 1
                self.pending_exit_reason = None
                self.active_side = 0
                self.entry_price = None
                self.entry_bar = None
        if order.status in (order.Completed, order.Canceled, order.Margin, order.Rejected):
            if order.status != order.Completed:
                self.pending_open_side = None
                self.pending_exit_reason = None
            self.pending_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
