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


def _holding_month_set(entry_month, holding_months):
    return {((entry_month - 1 + offset) % 12) + 1 for offset in range(int(holding_months))}


def _average_trade_return(monthly_close, entry_month, holding_months):
    returns = []
    for idx in range(len(monthly_close) - int(holding_months)):
        if int(monthly_close.index[idx].month) != int(entry_month):
            continue
        entry_price = float(monthly_close.iloc[idx])
        exit_price = float(monthly_close.iloc[idx + int(holding_months)])
        if entry_price > 0:
            returns.append(exit_price / entry_price - 1.0)
    if not returns:
        return None, 0
    return sum(returns) / len(returns), len(returns)


def prepare_seasonal_sell_features(price_df, params):
    out = price_df.copy()
    min_history_years = int(params.get('min_history_years', 5))
    min_trade_count = max(3, min_history_years - 1)
    test_entry_months = [int(v) for v in params.get('test_entry_months', list(range(1, 13)))]
    test_holding_months = [int(v) for v in params.get('test_holding_months', [3, 6, 9])]
    target_percent_value = float(params.get('target_percent', 1.0))

    monthly_close = out['close'].resample('ME').last().dropna()
    chosen_entry = {}
    chosen_holding = {}
    seasonal_score = {}
    historical_trades = {}
    hold_flag = {}

    for idx in range(len(monthly_close)):
        current_month_end = monthly_close.index[idx]
        history = monthly_close.iloc[:idx]
        best_combo = None
        best_return = None
        best_trade_count = 0
        if len(history) >= min_history_years * 12:
            for entry_month in test_entry_months:
                for holding_months in test_holding_months:
                    avg_return, trade_count = _average_trade_return(history, entry_month, holding_months)
                    if avg_return is None or trade_count < min_trade_count:
                        continue
                    if best_return is None or avg_return > best_return:
                        best_return = avg_return
                        best_trade_count = trade_count
                        best_combo = (entry_month, holding_months)
        if best_combo is None:
            chosen_entry[current_month_end] = None
            chosen_holding[current_month_end] = None
            seasonal_score[current_month_end] = None
            historical_trades[current_month_end] = 0.0
            hold_flag[current_month_end] = 0.0
            continue
        entry_month, holding_months = best_combo
        chosen_entry[current_month_end] = float(entry_month)
        chosen_holding[current_month_end] = float(holding_months)
        seasonal_score[current_month_end] = float(best_return)
        historical_trades[current_month_end] = float(best_trade_count)
        hold_flag[current_month_end] = 1.0 if int(current_month_end.month) in _holding_month_set(entry_month, holding_months) else 0.0

    monthly_feature = pd.DataFrame({
        'best_entry_month': pd.Series(chosen_entry, dtype='float64'),
        'best_holding_months': pd.Series(chosen_holding, dtype='float64'),
        'seasonal_score': pd.Series(seasonal_score, dtype='float64'),
        'historical_trade_count': pd.Series(historical_trades, dtype='float64'),
        'holding_flag': pd.Series(hold_flag, dtype='float64'),
    }).sort_index()
    monthly_feature['target_percent'] = monthly_feature['holding_flag'].fillna(0.0) * target_percent_value

    out['month_end'] = out.index.to_period('M').to_timestamp('M')
    out = out.join(monthly_feature, on='month_end')
    out['best_entry_month'] = out['best_entry_month'].ffill()
    out['best_holding_months'] = out['best_holding_months'].ffill()
    out['seasonal_score'] = out['seasonal_score'].ffill()
    out['historical_trade_count'] = out['historical_trade_count'].ffill().fillna(0.0)
    out['holding_flag'] = out['holding_flag'].fillna(0.0)
    out['target_percent'] = out['target_percent'].fillna(0.0)
    out['month'] = pd.Series(out.index.month, index=out.index, dtype='float64')
    prev_target = out['target_percent'].shift(1).fillna(out['target_percent'])
    out['buy_signal'] = ((prev_target <= 0) & (out['target_percent'] > 0)).astype(float)
    out['sell_signal'] = ((prev_target > 0) & (out['target_percent'] <= 0)).astype(float)
    return out[[
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'month', 'best_entry_month', 'best_holding_months', 'seasonal_score',
        'historical_trade_count', 'holding_flag', 'target_percent', 'buy_signal', 'sell_signal',
    ]].copy()


class SeasonalSellFeed(bt.feeds.PandasData):
    lines = ('month', 'best_entry_month', 'best_holding_months', 'seasonal_score', 'historical_trade_count', 'holding_flag', 'target_percent', 'buy_signal', 'sell_signal')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('month', 6), ('best_entry_month', 7), ('best_holding_months', 8), ('seasonal_score', 9), ('historical_trade_count', 10), ('holding_flag', 11), ('target_percent', 12), ('buy_signal', 13), ('sell_signal', 14),
    )


class SeasonalSellAugustStrategy(bt.Strategy):
    params = dict(
        rebalance_tolerance=0.05,
        min_history_years=5,
        test_entry_months=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        test_holding_months=[3, 6, 9],
        target_percent=1.0,
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
        self.holding_days = 0
        self.flat_days = 0

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
        target_percent = float(self.data.target_percent[0])
        if target_percent > 0:
            self.holding_days += 1
        else:
            self.flat_days += 1
        if self.pending_order is not None:
            return
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
