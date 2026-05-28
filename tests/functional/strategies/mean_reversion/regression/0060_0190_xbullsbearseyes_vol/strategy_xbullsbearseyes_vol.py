from __future__ import absolute_import, division, print_function, unicode_literals

import io
import sys
from pathlib import Path

import pandas as pd

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
LOCAL_BACKTRADER_REPO = WORKSPACE_ROOT / 'backtrader'
if str(LOCAL_BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(LOCAL_BACKTRADER_REPO))

import backtrader as bt


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=15):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines)
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume',
        '<VOL>': 'openinterest',
    })
    df['volume'] = df['tick_volume']
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'tick_volume', 'openinterest']]
    df = df.set_index('datetime')
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def resample_to_h8(df):
    agg = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'tick_volume': 'sum',
        'openinterest': 'sum',
    }
    h8 = df.resample('8h', label='right', closed='right').agg(agg)
    return h8.dropna(subset=['open', 'high', 'low', 'close'])


def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def recursive_histogram(frame, period=13, gamma=0.6, ma_length=12, volume_type='tick'):
    price_ema = ema(frame['close'], period)
    bears = frame['low'] - price_ema
    bulls = frame['high'] - price_ema
    volume = frame['tick_volume'] if str(volume_type).lower() == 'tick' else frame['volume']

    l0 = l1 = l2 = l3 = 0.0
    raw_values = []
    for idx in range(len(frame)):
        total_power = float(bears.iloc[idx] + bulls.iloc[idx])
        l0_prev, l1_prev, l2_prev, l3_prev = l0, l1, l2, l3
        l0 = (1.0 - gamma) * total_power + gamma * l0_prev
        l1 = -gamma * l0 + l0_prev + gamma * l1_prev
        l2 = -gamma * l1 + l1_prev + gamma * l2_prev
        l3 = -gamma * l2 + l2_prev + gamma * l3_prev
        cu = 0.0
        cd = 0.0
        if l0 >= l1:
            cu = l0 - l1
        else:
            cd = l1 - l0
        if l1 >= l2:
            cu += l1 - l2
        else:
            cd += l2 - l1
        if l2 >= l3:
            cu += l2 - l3
        else:
            cd += l3 - l2
        result = cu / (cu + cd) if (cu + cd) != 0 else 0.0
        raw_values.append((result * 100.0 - 50.0) * float(volume.iloc[idx]))

    histogram = pd.Series(raw_values, index=frame.index).rolling(ma_length).mean()
    smoothed_volume = volume.rolling(ma_length).mean()
    return histogram, smoothed_volume


def assign_zone_color(histogram, smoothed_volume, high_level_2, high_level_1, low_level_1, low_level_2):
    colors = pd.Series(index=histogram.index, dtype='float64')
    max_level = high_level_2 * smoothed_volume
    up_level = high_level_1 * smoothed_volume
    down_level = low_level_1 * smoothed_volume
    min_level = low_level_2 * smoothed_volume

    for idx in range(len(histogram)):
        value = histogram.iat[idx]
        if pd.isna(value) or pd.isna(smoothed_volume.iat[idx]):
            colors.iat[idx] = pd.NA
            continue
        color = 2.0
        if value > max_level.iat[idx]:
            color = 0.0
        elif value > up_level.iat[idx]:
            color = 1.0
        elif value < min_level.iat[idx]:
            color = 4.0
        elif value < down_level.iat[idx]:
            color = 3.0
        colors.iat[idx] = color
    return colors


def build_signal_frame(
    filepath,
    fromdate=None,
    todate=None,
    bar_shift_minutes=15,
    period=13,
    gamma=0.6,
    high_level_2=25,
    high_level_1=10,
    low_level_1=-10,
    low_level_2=-25,
    ma_length=12,
    signal_bar=1,
    volume_type='tick',
):
    base = load_mt5_csv(filepath, fromdate=fromdate, todate=todate, bar_shift_minutes=bar_shift_minutes)
    frame = resample_to_h8(base)
    histogram, smoothed_volume = recursive_histogram(frame, period=period, gamma=gamma, ma_length=ma_length, volume_type=volume_type)
    frame['histogram'] = histogram
    frame['smoothed_volume'] = smoothed_volume
    frame['zone_color'] = assign_zone_color(histogram, smoothed_volume, high_level_2, high_level_1, low_level_1, low_level_2)

    current_color = frame['zone_color'].shift(signal_bar)
    previous_color = frame['zone_color'].shift(signal_bar + 1)

    frame['buy_signal_normal'] = (previous_color == 1.0) & (current_color > 1.0)
    frame['buy_signal_strong'] = (previous_color == 0.0) & (current_color > 0.0)
    frame['sell_signal_normal'] = (previous_color == 3.0) & (current_color < 3.0)
    frame['sell_signal_strong'] = (previous_color == 4.0) & (current_color < 4.0)
    frame['close_buy_signal'] = frame['sell_signal_normal'] | frame['sell_signal_strong']
    frame['close_sell_signal'] = frame['buy_signal_normal'] | frame['buy_signal_strong']
    return frame.dropna(subset=['histogram', 'smoothed_volume', 'zone_color'])


class XBullsBearsEyesVolFeed(bt.feeds.PandasData):
    lines = (
        'histogram', 'smoothed_volume', 'zone_color',
        'buy_signal_normal', 'buy_signal_strong', 'sell_signal_normal', 'sell_signal_strong',
        'close_buy_signal', 'close_sell_signal',
    )
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('tick_volume', 5),
        ('openinterest', 6),
        ('histogram', 7),
        ('smoothed_volume', 8),
        ('zone_color', 9),
        ('buy_signal_normal', 10),
        ('buy_signal_strong', 11),
        ('sell_signal_normal', 12),
        ('sell_signal_strong', 13),
        ('close_buy_signal', 14),
        ('close_sell_signal', 15),
    )


class XBullsBearsEyesVolStrategy(bt.Strategy):
    params = dict(
        mm1=0.1,
        mm2=0.2,
        lot_or_risk='lot',
        stop_loss_points=1000,
        take_profit_points=2000,
        point=0.01,
        margin_per_lot=250.0,
        lot_step=0.01,
        lot_min=0.01,
        lot_max=100.0,
        period=13,
        gamma=0.6,
        high_level_2=25,
        high_level_1=10,
        low_level_1=-10,
        low_level_2=-25,
        ma_length=12,
        signal_bar=1,
        volume_type='tick',
    )

    def __init__(self):
        self.order = None
        self.current_stop = None
        self.current_take_profit = None
        self.pending_stop = None
        self.pending_take_profit = None
        self.pending_side = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def next(self):
        self.bar_num += 1

    def _normalize_lot(self, lot):
        step = self.p.lot_step
        lot = step * round(lot / step)
        lot = max(self.p.lot_min, min(self.p.lot_max, lot))
        return round(lot, 2)

    def trade_size(self, share):
        if str(self.p.lot_or_risk).lower() == 'lot':
            return self._normalize_lot(share)
        margin = self.p.margin_per_lot
        if margin <= 0:
            return 0.0
        cash = self.broker.getcash()
        lot = cash * (share / 100.0) / margin
        if lot <= 0:
            return 0.0
        return self._normalize_lot(lot)

    def _close_if_exit_hit(self):
        if not self.position:
            return False
        low = float(self.data.low[-1])
        high = float(self.data.high[-1])
        if self.position.size > 0:
            if self.current_stop is not None and low <= self.current_stop:
                self.log(f'close long stop={self.current_stop:.2f}')
                self.order = self.close()
                return True
            if self.current_take_profit is not None and high >= self.current_take_profit:
                self.log(f'close long take_profit={self.current_take_profit:.2f}')
                self.order = self.close()
                return True
            if bool(self.data.close_buy_signal[0]):
                self.log('close long signal_reverse')
                self.order = self.close()
                return True
        else:
            if self.current_stop is not None and high >= self.current_stop:
                self.log(f'close short stop={self.current_stop:.2f}')
                self.order = self.close()
                return True
            if self.current_take_profit is not None and low <= self.current_take_profit:
                self.log(f'close short take_profit={self.current_take_profit:.2f}')
                self.order = self.close()
                return True
            if bool(self.data.close_sell_signal[0]):
                self.log('close short signal_reverse')
                self.order = self.close()
                return True
        return False

    def next_open(self):
        if self.order:
            return
        if len(self.data) < 2:
            return

        if self.position:
            self._close_if_exit_hit()
            return

        buy_size = 0.0
        sell_size = 0.0
        if bool(self.data.buy_signal_normal[0]):
            buy_size += self.trade_size(self.p.mm1)
        if bool(self.data.buy_signal_strong[0]):
            buy_size += self.trade_size(self.p.mm2)
        if bool(self.data.sell_signal_normal[0]):
            sell_size += self.trade_size(self.p.mm1)
        if bool(self.data.sell_signal_strong[0]):
            sell_size += self.trade_size(self.p.mm2)

        entry_price = float(self.data.open[0])
        if buy_size > 0:
            self.pending_side = 'long'
            self.pending_stop = entry_price - self.p.stop_loss_points * self.p.point if self.p.stop_loss_points else None
            self.pending_take_profit = entry_price + self.p.take_profit_points * self.p.point if self.p.take_profit_points else None
            self.log(
                'buy '
                f'size={buy_size:.2f} '
                f'open={entry_price:.2f} '
                f'hist={float(self.data.histogram[0]):.2f} '
                f'color={float(self.data.zone_color[0]):.0f}'
            )
            self.order = self.buy(size=buy_size)
            return

        if sell_size > 0:
            self.pending_side = 'short'
            self.pending_stop = entry_price + self.p.stop_loss_points * self.p.point if self.p.stop_loss_points else None
            self.pending_take_profit = entry_price - self.p.take_profit_points * self.p.point if self.p.take_profit_points else None
            self.log(
                'sell '
                f'size={sell_size:.2f} '
                f'open={entry_price:.2f} '
                f'hist={float(self.data.histogram[0]):.2f} '
                f'color={float(self.data.zone_color[0]):.0f}'
            )
            self.order = self.sell(size=sell_size)

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if self.pending_side == 'long' and self.position.size > 0:
                self.buy_count += 1
                self.current_stop = self.pending_stop
                self.current_take_profit = self.pending_take_profit
            elif self.pending_side == 'short' and self.position.size < 0:
                self.sell_count += 1
                self.current_stop = self.pending_stop
                self.current_take_profit = self.pending_take_profit
            elif self.position.size == 0:
                self.current_stop = None
                self.current_take_profit = None
        self.order = None
        self.pending_stop = None
        self.pending_take_profit = None
        self.pending_side = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm > 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
