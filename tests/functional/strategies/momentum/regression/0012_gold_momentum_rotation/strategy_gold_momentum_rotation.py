from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import pandas as pd


ASSET_ORDER = ['GLD', 'IAU', 'IVV', 'IEF', 'DBC']


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
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low',
        '<CLOSE>': 'close', '<TICKVOL>': 'tick_volume', '<VOL>': 'real_volume',
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


def prepare_rotation_inputs(asset_frames, params):
    common_index = None
    for frame in asset_frames.values():
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    common_index = common_index.sort_values()
    aligned = {name: frame.loc[common_index].copy() for name, frame in asset_frames.items()}
    close_df = pd.DataFrame({name: frame['close'] for name, frame in aligned.items()}, index=common_index)
    lookback_days = int(params.get('lookback_months', 3)) * 21
    score_df = close_df / close_df.shift(lookback_days) - 1.0
    signal_df = aligned['GLD'][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    rebalance_flag = pd.Series(0.0, index=common_index)
    weight_df = pd.DataFrame(0.0, index=common_index, columns=close_df.columns)
    top_n = max(1, int(params.get('top_n', 1)))
    month_groups = pd.Series(common_index, index=common_index).groupby(common_index.to_period('M')).agg('last')
    rebalance_dates = pd.DatetimeIndex(month_groups.values)
    current_weights = pd.Series(0.0, index=close_df.columns)
    for dt in common_index:
        if dt in rebalance_dates and dt in score_df.index:
            day_scores = score_df.loc[dt].dropna().sort_values(ascending=False)
            current_weights = pd.Series(0.0, index=close_df.columns)
            if not day_scores.empty:
                selected = day_scores.head(top_n).index.tolist()
                for symbol in selected:
                    current_weights[symbol] = 1.0 / top_n
            rebalance_flag.loc[dt] = 1.0
        weight_df.loc[dt] = current_weights
    for symbol in close_df.columns:
        signal_df[f'{symbol.lower()}_weight'] = weight_df[symbol]
        signal_df[f'{symbol.lower()}_score'] = score_df[symbol]
    signal_df['rebalance_flag'] = rebalance_flag
    signal_df = signal_df.dropna().copy()
    aligned = {name: frame.loc[signal_df.index].copy() for name, frame in aligned.items()}
    return aligned, signal_df


class RotationSignalFeed(bt.feeds.PandasData):
    lines = (
        'gld_weight', 'iau_weight', 'ivv_weight', 'ief_weight', 'dbc_weight',
        'gld_score', 'iau_score', 'ivv_score', 'ief_score', 'dbc_score',
        'rebalance_flag',
    )
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('gld_weight', 6), ('iau_weight', 7), ('ivv_weight', 8), ('ief_weight', 9), ('dbc_weight', 10),
        ('gld_score', 11), ('iau_score', 12), ('ivv_score', 13), ('ief_score', 14), ('dbc_score', 15),
        ('rebalance_flag', 16),
    )


class GoldMomentumRotationStrategy(bt.Strategy):
    params = dict(
        trailing_stop_pct=0.20,
        lot_size=1.0,
        lookback_months=3,
        rebalance_freq='M',
        top_n=1,
    )

    def __init__(self):
        self.signal = self.datas[0]
        self.asset_map = {name: self.getdatabyname(name) for name in ASSET_ORDER}
        self.order_refs = set()
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.rebalance_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.current_asset = None
        self.trailing_high = None
        self.broker_value_series = []

    def _submit(self, order):
        if order is not None:
            self.order_refs.add(order.ref)

    def _target_size(self, data, target_weight):
        broker_value = float(self.broker.getvalue())
        price = float(data.close[0])
        if broker_value <= 0 or price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(data)
        multiplier = float(getattr(comminfo.p, 'mult', 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        return round(broker_value * float(self.p.lot_size) * float(target_weight) / (price * multiplier), 2)

    def _selected_asset(self):
        best_name = None
        best_weight = 0.0
        for symbol in ASSET_ORDER:
            weight = float(getattr(self.signal, f'{symbol.lower()}_weight')[0])
            if weight > best_weight:
                best_weight = weight
                best_name = symbol
        return best_name, best_weight

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.signal.datetime[0]), float(self.broker.getvalue())))
        if self.current_asset is not None and self.getposition(self.asset_map[self.current_asset]).size > 0:
            current_price = float(self.asset_map[self.current_asset].close[0])
            self.trailing_high = current_price if self.trailing_high is None else max(self.trailing_high, current_price)
            if current_price <= self.trailing_high * (1.0 - float(self.p.trailing_stop_pct)) and not self.order_refs:
                order = self.close(data=self.asset_map[self.current_asset])
                self._submit(order)
                self.current_asset = None
                self.trailing_high = None
                self.sell_count += 1
                return
        if self.order_refs:
            return
        if float(self.signal.rebalance_flag[0]) <= 0.5:
            return
        self.rebalance_count += 1
        selected_asset, selected_weight = self._selected_asset()
        for symbol in ASSET_ORDER:
            data = self.asset_map[symbol]
            target_weight = selected_weight if symbol == selected_asset else 0.0
            order = self.order_target_size(data=data, target=self._target_size(data, target_weight))
            self._submit(order)
            if order is not None:
                if target_weight > 0:
                    self.buy_count += 1
                else:
                    self.sell_count += 1
        self.current_asset = selected_asset
        self.trailing_high = float(self.asset_map[selected_asset].close[0]) if selected_asset else None

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.order_refs.discard(order.ref)

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
