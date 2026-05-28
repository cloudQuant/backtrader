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


def prepare_calendar_momentum_inputs(asset_map):
    aligned_index = None
    prepared = {}
    close_frames = []
    for symbol, df in asset_map.items():
        frame = df[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy().sort_index()
        prepared[symbol] = frame
        close_frames.append(frame[['close']].rename(columns={'close': symbol}))
        aligned_index = frame.index if aligned_index is None else aligned_index.intersection(frame.index)
    if aligned_index is None or len(aligned_index) == 0:
        raise ValueError('No overlapping data found for calendar momentum inputs')
    aligned_index = aligned_index.sort_values()
    prepared = {symbol: frame.loc[aligned_index].copy() for symbol, frame in prepared.items()}
    close_df = pd.concat([frame.loc[aligned_index] for frame in close_frames], axis=1).dropna(how='any')
    aligned_index = close_df.index
    prepared = {symbol: frame.loc[aligned_index].copy() for symbol, frame in prepared.items()}
    return prepared, close_df, aligned_index


def build_signal_frame(close_df, params):
    r1 = int(params.get('momentum_1m', 21))
    r3 = int(params.get('momentum_3m', 63))
    r6 = int(params.get('momentum_6m', 126))
    r12 = int(params.get('momentum_12m', 252))
    weights = params.get('momentum_weights', {}) or {}
    w1 = float(weights.get('r1m', 12.0))
    w3 = float(weights.get('r3m', 4.0))
    w6 = float(weights.get('r6m', 2.0))
    w12 = float(weights.get('r12m', 1.0))
    ma_period = int(params.get('ma_period', 200))
    turn_days = int(params.get('turn_of_month_entry_days', 4))
    start_days = int(params.get('month_start_hold_days', 3))
    mid_month_days = set(int(v) for v in params.get('mid_month_days', [15, 16, 17]))
    use_ma_filter = bool(params.get('use_ma_filter', True))

    momentum_components = {}
    momentum_scores = pd.DataFrame(index=close_df.index)
    for symbol in close_df.columns:
        prices = close_df[symbol]
        score = (
            w1 * prices.pct_change(r1) +
            w3 * prices.pct_change(r3) +
            w6 * prices.pct_change(r6) +
            w12 * prices.pct_change(r12)
        ) / 4.0
        momentum_scores[symbol] = score
        momentum_components[f'{symbol}_score'] = score

    ivy_series = close_df['ivv'] if 'ivv' in close_df.columns else close_df.iloc[:, 0]
    ivv_ma = ivy_series.rolling(ma_period).mean()
    reverse_rank = pd.Series(range(len(close_df)), index=close_df.index).groupby(close_df.index.to_period('M')).transform(
        lambda x: x.rank(ascending=False, method='first')
    )
    month_day = pd.Series(close_df.index.day, index=close_df.index)
    turn_of_month_signal = ((reverse_rank <= turn_days) | (month_day <= start_days)).astype(float)
    mid_month_signal = month_day.isin(mid_month_days).astype(float)
    calendar_signal = ((turn_of_month_signal > 0) | (mid_month_signal > 0)).astype(float)

    valid_rows = momentum_scores.notna().any(axis=1)
    momentum_scores = momentum_scores.loc[valid_rows].copy()
    ivy_series = ivy_series.loc[valid_rows].copy()
    ivv_ma = ivv_ma.loc[valid_rows].copy()
    reverse_rank = reverse_rank.loc[valid_rows].copy()
    month_day = month_day.loc[valid_rows].copy()
    turn_of_month_signal = turn_of_month_signal.loc[valid_rows].copy()
    mid_month_signal = mid_month_signal.loc[valid_rows].copy()
    calendar_signal = calendar_signal.loc[valid_rows].copy()
    momentum_components = {key: series.loc[valid_rows].copy() for key, series in momentum_components.items()}

    best_asset = momentum_scores.idxmax(axis=1)
    best_momentum = momentum_scores.max(axis=1)
    ma_filter_pass = ((ivy_series > ivv_ma) | (~use_ma_filter)).astype(float)
    allowed_signal = ((calendar_signal > 0) & ((ma_filter_pass > 0) | (best_momentum > 0))).astype(float)

    signal_df = pd.DataFrame(index=momentum_scores.index)
    signal_df['calendar_signal'] = calendar_signal
    signal_df['turn_of_month_signal'] = turn_of_month_signal
    signal_df['mid_month_signal'] = mid_month_signal
    signal_df['ivv_above_ma'] = ma_filter_pass
    signal_df['best_asset'] = best_asset
    signal_df['best_momentum'] = best_momentum
    signal_df['active_signal'] = allowed_signal
    for key, series in momentum_components.items():
        signal_df[key] = series
    return signal_df.dropna()


class CalendarMomentumStrategy(bt.Strategy):
    params = dict(
        signal_lookup=None,
        position_size=0.95,
        momentum_1m=21,
        momentum_3m=63,
        momentum_6m=126,
        momentum_12m=252,
        momentum_weights={'r1m': 12.0, 'r3m': 4.0, 'r6m': 2.0, 'r12m': 1.0},
        turn_of_month_entry_days=4,
        month_start_hold_days=3,
        mid_month_days=[15, 16, 17],
        ma_period=200,
        use_ma_filter=True,
        rebalance_interval_days=1,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.rebalance_count = 0
        self.pending_orders = []
        self.current_asset = None
        self.broker_value_series = []
        self.signal_lookup = self.p.signal_lookup or {}
        self.data_by_name = {data._name: data for data in self.datas}

    def _cancel_pending(self):
        for order in self.pending_orders:
            if order is not None:
                self.cancel(order)
        self.pending_orders = []

    def _close_all_except(self, keep_name=None):
        for data in self.datas:
            position = self.getposition(data)
            if position.size and data._name != keep_name:
                self.sell_count += 1
                self.pending_orders.append(self.close(data=data))

    def _target_asset(self, asset_name):
        target_pct = float(self.p.position_size)
        for data in self.datas:
            if data._name == asset_name:
                self.buy_count += 1
                self.pending_orders.append(self.order_target_percent(data=data, target=target_pct))
            else:
                if self.getposition(data).size:
                    self.sell_count += 1
                    self.pending_orders.append(self.order_target_percent(data=data, target=0.0))

    def next(self):
        self.bar_num += 1
        current_dt = bt.num2date(self.datas[0].datetime[0]).replace(tzinfo=None)
        self.broker_value_series.append((current_dt, float(self.broker.getvalue())))
        if self.pending_orders:
            return

        signal = self.signal_lookup.get(pd.Timestamp(current_dt))
        if signal is None:
            signal = self.signal_lookup.get(pd.Timestamp(current_dt.date()))
        if signal is None:
            return

        active_signal = float(signal.get('active_signal', 0.0)) > 0.5
        best_asset = str(signal.get('best_asset', ''))

        if not active_signal or best_asset not in self.data_by_name:
            if any(self.getposition(data).size for data in self.datas):
                self.rebalance_count += 1
                self._close_all_except(None)
                self.current_asset = None
            return

        if self.current_asset != best_asset or not self.getposition(self.data_by_name[best_asset]).size:
            self.rebalance_count += 1
            self._target_asset(best_asset)
            self.current_asset = best_asset

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_orders = [o for o in self.pending_orders if o.ref != order.ref]
        if order.status in (order.Canceled, order.Margin, order.Rejected):
            if not any(self.getposition(data).size for data in self.datas):
                self.current_asset = None
