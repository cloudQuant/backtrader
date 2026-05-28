from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import pandas as pd

ASSET_CODE_TO_NAME = {
    0: 'CASH',
    1: 'XAUUSD',
    2: 'IVV',
    3: 'IEF',
    4: 'GLD',
}
ASSET_NAME_TO_CODE = {value: key for key, value in ASSET_CODE_TO_NAME.items()}


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
    if bar_shift_minutes:
        parsed = parsed + pd.to_timedelta(int(bar_shift_minutes), unit='m')
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


def resample_to_monthly(df):
    monthly = pd.DataFrame({
        'open': df['open'].resample('ME').first(),
        'high': df['high'].resample('ME').max(),
        'low': df['low'].resample('ME').min(),
        'close': df['close'].resample('ME').last(),
        'volume': df['volume'].resample('ME').sum(),
        'openinterest': df['openinterest'].resample('ME').last().fillna(0),
    })
    return monthly.dropna(subset=['open', 'high', 'low', 'close'])


def prepare_dual_momentum_data(asset_daily_frames, params):
    monthly_frames = {name: resample_to_monthly(frame) for name, frame in asset_daily_frames.items()}
    common_index = None
    for frame in monthly_frames.values():
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    common_index = common_index.sort_values()
    monthly_frames = {name: frame.loc[common_index].copy() for name, frame in monthly_frames.items()}

    formation_period = int(params.get('formation_period_months', 12))
    close_table = pd.DataFrame({name: frame['close'] for name, frame in monthly_frames.items()}, index=common_index)
    momentum = close_table / close_table.shift(formation_period) - 1.0
    valid_mask = momentum.notna().any(axis=1)
    best_asset = pd.Series(index=momentum.index, dtype='object')
    best_return = pd.Series(index=momentum.index, dtype='float64')
    best_asset.loc[valid_mask] = momentum.loc[valid_mask].idxmax(axis=1)
    best_return.loc[valid_mask] = momentum.loc[valid_mask].max(axis=1)
    selected_asset = best_asset.where(best_return > 0, 'CASH')
    selected_code = selected_asset.map(lambda x: ASSET_NAME_TO_CODE.get(x, 0)).astype(float)

    signal_df = monthly_frames['XAUUSD'][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    signal_df['xauusd_return_12m'] = momentum['XAUUSD']
    signal_df['ivv_return_12m'] = momentum['IVV']
    signal_df['ief_return_12m'] = momentum['IEF']
    signal_df['gld_return_12m'] = momentum['GLD']
    signal_df['best_return_12m'] = best_return
    signal_df['selected_asset_code'] = selected_code
    signal_df['risk_on'] = (selected_code > 0).astype(float)

    monthly_summary = pd.DataFrame({
        'XAUUSD': close_table['XAUUSD'],
        'IVV': close_table['IVV'],
        'IEF': close_table['IEF'],
        'GLD': close_table['GLD'],
        'xauusd_return_12m': momentum['XAUUSD'],
        'ivv_return_12m': momentum['IVV'],
        'ief_return_12m': momentum['IEF'],
        'gld_return_12m': momentum['GLD'],
        'selected_asset': selected_asset,
        'selected_asset_code': selected_code,
        'best_return_12m': best_return,
    }).loc[valid_mask].copy()

    return signal_df.dropna(), monthly_frames, monthly_summary


class DualMomentumSignalFeed(bt.feeds.PandasData):
    lines = (
        'xauusd_return_12m', 'ivv_return_12m', 'ief_return_12m', 'gld_return_12m',
        'best_return_12m', 'selected_asset_code', 'risk_on',
    )
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('xauusd_return_12m', 6), ('ivv_return_12m', 7), ('ief_return_12m', 8), ('gld_return_12m', 9),
        ('best_return_12m', 10), ('selected_asset_code', 11), ('risk_on', 12),
    )


class GoldDualMomentumStrategy(bt.Strategy):
    params = dict(
        formation_period_months=12,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.signal = self.datas[0]
        self.asset_feeds = {
            1: self.getdatabyname('XAUUSD'),
            2: self.getdatabyname('IVV'),
            3: self.getdatabyname('IEF'),
            4: self.getdatabyname('GLD'),
        }
        self.bar_num = 0
        self.rebalance_count = 0
        self.switch_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.cash_month_count = 0
        self.gold_month_count = 0
        self.stock_month_count = 0
        self.bond_month_count = 0
        self.gld_month_count = 0
        self.pending_order_refs = set()
        self.last_selected_code = None
        self.broker_value_series = []

    def _selected_code(self):
        value = float(self.signal.selected_asset_code[0])
        return int(round(value)) if value == value else 0

    def _record_allocation_month(self, code):
        if code == 0:
            self.cash_month_count += 1
        elif code == 1:
            self.gold_month_count += 1
        elif code == 2:
            self.stock_month_count += 1
        elif code == 3:
            self.bond_month_count += 1
        elif code == 4:
            self.gld_month_count += 1

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.signal.datetime[0]), float(self.broker.getvalue())))
        selected_code = self._selected_code()
        self._record_allocation_month(selected_code)

        if self.pending_order_refs:
            return

        if self.last_selected_code is not None and selected_code == self.last_selected_code:
            return

        if self.last_selected_code is not None and selected_code != self.last_selected_code:
            self.switch_count += 1
        self.last_selected_code = selected_code
        self.rebalance_count += 1

        for asset_code, data in self.asset_feeds.items():
            target_pct = 1.0 if asset_code == selected_code else 0.0
            order = self.order_target_percent(data=data, target=target_pct)
            if order is not None:
                self.pending_order_refs.add(order.ref)
                if target_pct > 0:
                    self.buy_count += 1
                else:
                    if self.getposition(data).size != 0:
                        self.sell_count += 1

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order_refs.discard(order.ref)

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
