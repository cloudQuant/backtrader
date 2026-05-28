from __future__ import absolute_import, division, print_function, unicode_literals

import calendar
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


def get_third_friday(year, month):
    cal = calendar.Calendar()
    fridays = [day for day, weekday in cal.itermonthdays2(year, month) if day != 0 and weekday == 4]
    return pd.Timestamp(year=year, month=month, day=fridays[2])


def get_previous_trading_day(index, target_date):
    candidates = index[index < target_date]
    return candidates[-1] if len(candidates) else None


def get_next_trading_day(index, target_date):
    candidates = index[index > target_date]
    return candidates[0] if len(candidates) else None


def prepare_december_opex_features(price_df, params):
    out = price_df.copy()
    require_negative_november = bool(params.get('require_negative_november', False))
    use_extended_window = bool(params.get('use_extended_window', True))
    oversold_target_multiplier = float(params.get('oversold_target_multiplier', 1.5))
    out['entry_signal'] = 0.0
    out['extended_window'] = 0.0
    out['oversold_boost'] = 0.0
    out['target_pct'] = 0.0
    out['opex_year'] = 0.0
    index = pd.DatetimeIndex(out.index)
    base_target_pct = float(params.get('base_target_pct', 0.20))
    for year in sorted(index.year.unique()):
        third_friday = get_third_friday(int(year), 12)
        week_monday = third_friday - pd.Timedelta(days=4)
        entry_day = index[(index >= week_monday) & (index <= third_friday)]
        if len(entry_day) == 0:
            continue
        entry_day = entry_day[0]
        november_data = out[(out.index.year == int(year)) & (out.index.month == 11)]
        november_return = 0.0
        if len(november_data) >= 2:
            november_return = float(november_data['close'].iloc[-1] / november_data['close'].iloc[0] - 1.0)
        oversold_condition = november_return < 0.0
        if require_negative_november and not oversold_condition:
            continue
        target_pct = base_target_pct * (oversold_target_multiplier if oversold_condition else 1.0)
        out.loc[entry_day, 'entry_signal'] = 1.0
        out.loc[entry_day, 'oversold_boost'] = 1.0 if oversold_condition else 0.0
        out.loc[entry_day, 'target_pct'] = target_pct
        out.loc[entry_day, 'opex_year'] = float(year)
        if use_extended_window:
            out.loc[entry_day, 'extended_window'] = 1.0
    out = out[[
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'entry_signal', 'extended_window', 'oversold_boost', 'target_pct', 'opex_year',
    ]].copy()
    return out.dropna()


class Mt5DecemberOpExFeed(bt.feeds.PandasData):
    lines = ('entry_signal', 'extended_window', 'oversold_boost', 'target_pct', 'opex_year')
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('entry_signal', 6),
        ('extended_window', 7),
        ('oversold_boost', 8),
        ('target_pct', 9),
        ('opex_year', 10),
    )


class DecemberOpExSeasonalityStrategy(bt.Strategy):
    params = dict(
        use_extended_window=True,
        base_hold_bars=5,
        extended_hold_bars=10,
        stop_loss_pct=0.035,
        take_profit_pct=0.06,
        base_target_pct=0.2,
        oversold_target_multiplier=1.5,
        require_negative_november=False,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.entry_setup_count = 0
        self.oversold_boost_count = 0
        self.extended_trade_count = 0
        self.time_exit_count = 0
        self.stop_exit_count = 0
        self.take_exit_count = 0
        self.pending_order = None
        self.entry_bar = None
        self.entry_price = None
        self.active_hold_bars = 0
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
        close_price = float(self.data.close[0])
        if self.position:
            holding_bars = self.bar_num - (self.entry_bar or self.bar_num)
            exit_reason = None
            if self.entry_price is not None and close_price <= self.entry_price * (1.0 - float(self.p.stop_loss_pct)):
                exit_reason = 'stop_loss'
            elif self.entry_price is not None and close_price >= self.entry_price * (1.0 + float(self.p.take_profit_pct)):
                exit_reason = 'take_profit'
            elif holding_bars >= int(self.active_hold_bars):
                exit_reason = 'time_exit'
            if exit_reason is not None:
                self.sell_count += 1
                self.pending_exit_reason = exit_reason
                self.pending_order = self.close()
                return
            return
        if float(self.data.entry_signal[0]) > 0.5:
            target_pct = float(self.data.target_pct[0])
            size = self._get_position_size(target_notional_pct=target_pct)
            if size > 0:
                self.entry_setup_count += 1
                if float(self.data.oversold_boost[0]) > 0.5:
                    self.oversold_boost_count += 1
                if bool(self.p.use_extended_window) and float(self.data.extended_window[0]) > 0.5:
                    self.active_hold_bars = int(self.p.base_hold_bars + self.p.extended_hold_bars)
                    self.extended_trade_count += 1
                else:
                    self.active_hold_bars = int(self.p.base_hold_bars)
                self.buy_count += 1
                self.pending_order = self.buy(size=size)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.entry_price = float(order.executed.price or self.data.close[0])
                self.entry_bar = self.bar_num
            elif order.issell():
                reason = getattr(self, 'pending_exit_reason', None)
                if reason == 'time_exit':
                    self.time_exit_count += 1
                elif reason == 'stop_loss':
                    self.stop_exit_count += 1
                elif reason == 'take_profit':
                    self.take_exit_count += 1
                self.pending_exit_reason = None
                self.entry_price = None
                self.entry_bar = None
                self.active_hold_bars = 0
        if order.status in (order.Completed, order.Canceled, order.Margin, order.Rejected):
            self.pending_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
