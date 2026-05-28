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


def prepare_seasonal_features(price_df, params):
    out = price_df.copy()
    min_history_years = int(params.get('min_history_years', 5))
    strong_weight = float(params.get('strong_weight', 1.0))
    neutral_weight = float(params.get('neutral_weight', 0.5))
    weak_weight = float(params.get('weak_weight', 0.0))

    monthly_close = out['close'].resample('ME').last()
    monthly_return = monthly_close.pct_change()
    month_number = monthly_return.index.month

    target_weight_map = {}
    state_map = {}
    avg_return_map = {}
    obs_count_map = {}

    history = {month: [] for month in range(1, 13)}
    for idx, ret in monthly_return.items():
        month = int(idx.month)
        samples = history[month]
        obs_count = len(samples)
        if obs_count >= min_history_years:
            month_avgs = {m: (sum(vals) / len(vals)) for m, vals in history.items() if len(vals) >= min_history_years}
            current_avg = sum(samples) / len(samples)
            if len(month_avgs) >= 3:
                median_avg = sorted(month_avgs.values())[len(month_avgs) // 2]
                strong_months = {m for m, avg in month_avgs.items() if avg > median_avg}
                weak_months = {m for m, avg in month_avgs.items() if avg < median_avg}
                if month in strong_months:
                    target_weight_map[idx] = strong_weight
                    state_map[idx] = 2.0
                elif month in weak_months:
                    target_weight_map[idx] = weak_weight
                    state_map[idx] = 0.0
                else:
                    target_weight_map[idx] = neutral_weight
                    state_map[idx] = 1.0
                avg_return_map[idx] = current_avg
                obs_count_map[idx] = float(obs_count)
            else:
                target_weight_map[idx] = neutral_weight
                state_map[idx] = 1.0
                avg_return_map[idx] = current_avg
                obs_count_map[idx] = float(obs_count)
        else:
            target_weight_map[idx] = neutral_weight
            state_map[idx] = 1.0
            avg_return_map[idx] = None
            obs_count_map[idx] = float(obs_count)
        if pd.notna(ret):
            samples.append(float(ret))

    monthly_feature = pd.DataFrame({
        'target_percent': pd.Series(target_weight_map),
        'seasonal_state': pd.Series(state_map),
        'historical_avg_return': pd.Series(avg_return_map, dtype='float64'),
        'historical_observations': pd.Series(obs_count_map, dtype='float64'),
    }).sort_index()

    out['month_end'] = out.index.to_period('M').to_timestamp('M')
    out = out.join(monthly_feature, on='month_end')
    out['target_percent'] = out['target_percent'].ffill().fillna(neutral_weight)
    out['seasonal_state'] = out['seasonal_state'].ffill().fillna(1.0)
    out['historical_avg_return'] = out['historical_avg_return'].ffill()
    out['historical_observations'] = out['historical_observations'].ffill().fillna(0.0)
    out['month'] = pd.Series(out.index.month, index=out.index, dtype='float64')
    out['is_strong_month'] = (out['seasonal_state'] >= 2.0).astype(float)
    out['is_weak_month'] = (out['seasonal_state'] <= 0.0).astype(float)
    out['is_neutral_month'] = (out['seasonal_state'] == 1.0).astype(float)
    prev_target = out['target_percent'].shift(1).fillna(out['target_percent'])
    out['rebalance_signal'] = (prev_target != out['target_percent']).astype(float)
    return out[[
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'month', 'seasonal_state', 'historical_avg_return', 'historical_observations',
        'is_strong_month', 'is_weak_month', 'is_neutral_month', 'target_percent', 'rebalance_signal',
    ]].copy()


class SeasonalTradingFeed(bt.feeds.PandasData):
    lines = ('month', 'seasonal_state', 'historical_avg_return', 'historical_observations', 'is_strong_month', 'is_weak_month', 'is_neutral_month', 'target_percent', 'rebalance_signal')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('month', 6), ('seasonal_state', 7), ('historical_avg_return', 8), ('historical_observations', 9), ('is_strong_month', 10), ('is_weak_month', 11), ('is_neutral_month', 12), ('target_percent', 13), ('rebalance_signal', 14),
    )


class SeasonalTradingStrategy(bt.Strategy):
    params = dict(
        rebalance_tolerance=0.05,
        min_history_years=5,
        strong_weight=1.0,
        neutral_weight=0.5,
        weak_weight=0.0,
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
        self.broker_value_series = []
        self.strong_days = 0
        self.weak_days = 0
        self.neutral_days = 0

    def _current_exposure(self):
        broker_value = float(self.broker.getvalue())
        price = float(self.data.close[0])
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, 'mult', 1.0) or 1.0)
        if broker_value <= 0 or price <= 0 or multiplier <= 0:
            return 0.0
        return float(self.position.size) * price * multiplier / broker_value

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if float(self.data.is_strong_month[0]) > 0.5:
            self.strong_days += 1
        elif float(self.data.is_weak_month[0]) > 0.5:
            self.weak_days += 1
        else:
            self.neutral_days += 1
        if self.pending_order is not None:
            return
        target_percent = float(self.data.target_percent[0])
        current_exposure = self._current_exposure()
        if abs(target_percent - current_exposure) <= float(self.p.rebalance_tolerance):
            return
        if target_percent > current_exposure:
            self.buy_count += 1
        elif target_percent < current_exposure:
            self.sell_count += 1
        self.pending_order = self.order_target_percent(target=target_percent)

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
