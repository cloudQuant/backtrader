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
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
    })
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.set_index('datetime')
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def compute_rsi(series, period):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(50.0)


def get_probability(a1, a2, a3, x0, x1, x2, x3, x4, x5, x6, x7):
    pn1 = 1.0 - a1
    pn2 = 1.0 - a2
    pn3 = 1.0 - a3
    probability = (
        pn1 * (pn2 * (pn3 * x0 + a3 * x1) + a2 * (pn3 * x2 + a3 * x3))
        + a1 * (pn2 * (pn3 * x4 + a3 * x5) + a2 * (pn3 * x6 + a3 * x7))
    )
    return probability / 100.0


def build_signal_frame(
    filepath,
    fromdate=None,
    todate=None,
    bar_shift_minutes=15,
    lots=1.0,
    sltp_pips=100,
    x0=6,
    x1=96,
    x2=90,
    x3=35,
    x4=64,
    x5=83,
    x6=66,
    x7=50,
    rsi_period=9,
    rsi_price='open',
):
    frame = load_mt5_csv(filepath, fromdate=fromdate, todate=todate, bar_shift_minutes=bar_shift_minutes)
    price_series = frame['open'] if str(rsi_price).lower() == 'open' else frame['close']
    frame['rsi'] = compute_rsi(price_series, rsi_period)
    frame['a1'] = frame['rsi'] / 100.0
    frame['a2'] = frame['rsi'].shift(rsi_period) / 100.0
    frame['a3'] = frame['rsi'].shift(rsi_period * 2) / 100.0
    frame['probability_short'] = get_probability(frame['a1'], frame['a2'], frame['a3'], x0, x1, x2, x3, x4, x5, x6, x7)
    frame['signal'] = frame['probability_short'] * 2.0 - 1.0
    frame['buy_signal'] = frame['signal'] < 0.0
    frame['sell_signal'] = frame['signal'] >= 0.0
    return frame.dropna(subset=['a1', 'a2', 'a3', 'probability_short', 'signal'])


class RNNFeed(bt.feeds.PandasData):
    lines = ('rsi', 'a1', 'a2', 'a3', 'probability_short', 'signal', 'buy_signal', 'sell_signal')
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('rsi', 6),
        ('a1', 7),
        ('a2', 8),
        ('a3', 9),
        ('probability_short', 10),
        ('signal', 11),
        ('buy_signal', 12),
        ('sell_signal', 13),
    )


class RNNStrategy(bt.Strategy):
    params = dict(
        lots=1.0,
        sltp_pips=100,
        point=0.01,
        x0=6,
        x1=96,
        x2=90,
        x3=35,
        x4=64,
        x5=83,
        x6=66,
        x7=50,
        rsi_period=9,
        rsi_price='open',
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
        else:
            if self.current_stop is not None and high >= self.current_stop:
                self.log(f'close short stop={self.current_stop:.2f}')
                self.order = self.close()
                return True
            if self.current_take_profit is not None and low <= self.current_take_profit:
                self.log(f'close short take_profit={self.current_take_profit:.2f}')
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
        distance = self.p.sltp_pips * self.p.point if self.p.sltp_pips else 0.0

        if bool(self.data.buy_signal[0]):
            self.pending_side = 'long'
            self.pending_stop = entry_price - distance if distance else None
            self.pending_take_profit = entry_price + distance if distance else None
            self.log(
                'buy '
                f'open={entry_price:.2f} '
                f'prob_short={float(self.data.probability_short[0]):.4f} '
                f'signal={float(self.data.signal[0]):.4f}'
            )
            self.order = self.buy(size=self.p.lots)
            return

        self.pending_side = 'short'
        self.pending_stop = entry_price + distance if distance else None
        self.pending_take_profit = entry_price - distance if distance else None
        self.log(
            'sell '
            f'open={entry_price:.2f} '
            f'prob_short={float(self.data.probability_short[0]):.4f} '
            f'signal={float(self.data.signal[0]):.4f}'
        )
        self.order = self.sell(size=self.p.lots)

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
