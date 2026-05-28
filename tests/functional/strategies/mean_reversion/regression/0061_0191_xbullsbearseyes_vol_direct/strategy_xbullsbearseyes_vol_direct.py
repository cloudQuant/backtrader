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


def resample_to_h2(df):
    agg = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'tick_volume': 'sum',
        'openinterest': 'sum',
    }
    h2 = df.resample('2h', label='right', closed='right').agg(agg)
    return h2.dropna(subset=['open', 'high', 'low', 'close'])


def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def recursive_bulls_bears_direct(frame, period=13, gamma=0.6, ma_length=12, volume_type='tick'):
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
        ind = (result * 100.0 - 50.0) * float(volume.iloc[idx])
        raw_values.append(ind)

    ind_series = pd.Series(raw_values, index=frame.index)
    direct = ind_series.rolling(ma_length).mean()
    return direct


def build_signal_frame(
    filepath,
    fromdate=None,
    todate=None,
    bar_shift_minutes=15,
    period=13,
    gamma=0.6,
    ma_length=12,
    signal_bar=1,
    volume_type='tick',
):
    base = load_mt5_csv(filepath, fromdate=fromdate, todate=todate, bar_shift_minutes=bar_shift_minutes)
    frame = resample_to_h2(base)
    frame['direct'] = recursive_bulls_bears_direct(frame, period=period, gamma=gamma, ma_length=ma_length, volume_type=volume_type)
    direction_color = pd.Series(index=frame.index, dtype='float64')
    for idx in range(len(frame)):
        if idx == 0 or pd.isna(frame['direct'].iat[idx]) or pd.isna(frame['direct'].iat[idx - 1]):
            direction_color.iat[idx] = pd.NA
            continue
        if frame['direct'].iat[idx] > frame['direct'].iat[idx - 1]:
            direction_color.iat[idx] = 0.0
        elif frame['direct'].iat[idx] < frame['direct'].iat[idx - 1]:
            direction_color.iat[idx] = 1.0
        else:
            direction_color.iat[idx] = direction_color.iat[idx - 1]
    frame['color'] = direction_color
    current_color = frame['color'].shift(signal_bar)
    previous_color = frame['color'].shift(signal_bar + 1)
    frame['buy_signal'] = (previous_color == 0.0) & (current_color == 1.0)
    frame['sell_signal'] = (previous_color == 1.0) & (current_color == 0.0)
    frame['close_buy_signal'] = frame['sell_signal']
    frame['close_sell_signal'] = frame['buy_signal']
    return frame.dropna(subset=['direct', 'color'])


class XBullsBearsEyesVolDirectFeed(bt.feeds.PandasData):
    lines = ('direct', 'color', 'buy_signal', 'sell_signal', 'close_buy_signal', 'close_sell_signal',)
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('tick_volume', 5),
        ('openinterest', 6),
        ('direct', 7),
        ('color', 8),
        ('buy_signal', 9),
        ('sell_signal', 10),
        ('close_buy_signal', 11),
        ('close_sell_signal', 12),
    )


class XBullsBearsEyesVolDirectStrategy(bt.Strategy):
    params = dict(
        lot=0.1,
        stop_loss_points=1000,
        take_profit_points=2000,
        point=0.01,
        period=13,
        gamma=0.6,
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

        entry_price = float(self.data.open[0])
        if bool(self.data.buy_signal[0]):
            self.pending_side = 'long'
            self.pending_stop = entry_price - self.p.stop_loss_points * self.p.point if self.p.stop_loss_points else None
            self.pending_take_profit = entry_price + self.p.take_profit_points * self.p.point if self.p.take_profit_points else None
            self.log(
                'buy '
                f'size={self.p.lot:.2f} '
                f'open={entry_price:.2f} '
                f'direct={float(self.data.direct[0]):.2f} '
                f'color={float(self.data.color[0]):.0f}'
            )
            self.order = self.buy(size=self.p.lot)
            return

        if bool(self.data.sell_signal[0]):
            self.pending_side = 'short'
            self.pending_stop = entry_price + self.p.stop_loss_points * self.p.point if self.p.stop_loss_points else None
            self.pending_take_profit = entry_price - self.p.take_profit_points * self.p.point if self.p.take_profit_points else None
            self.log(
                'sell '
                f'size={self.p.lot:.2f} '
                f'open={entry_price:.2f} '
                f'direct={float(self.data.direct[0]):.2f} '
                f'color={float(self.data.color[0]):.0f}'
            )
            self.order = self.sell(size=self.p.lot)

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
