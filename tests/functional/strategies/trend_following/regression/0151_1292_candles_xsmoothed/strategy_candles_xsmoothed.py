from __future__ import absolute_import, division, print_function, unicode_literals

import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3] / 'backtrader'
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import backtrader as bt
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines)
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low',
        '<CLOSE>': 'close', '<TICKVOL>': 'volume', '<VOL>': 'openinterest',
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


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


def resolve_ma_class(name):
    mode = str(name).lower()
    if mode in {'sma', 'mode_sma'}:
        return bt.indicators.SMA
    if mode in {'ema', 'mode_ema'}:
        return bt.indicators.EMA
    if mode in {'smma', 'mode_smma'}:
        return bt.indicators.SmoothedMovingAverage
    return bt.indicators.WeightedMovingAverage


class CandlesXSmoothedIndicator(bt.Indicator):
    lines = ('smooth_open', 'smooth_high', 'smooth_low', 'smooth_close', 'color_state',)
    params = dict(
        ma_method='lwma',
        ma_length=30,
        ma_phase=100,
    )

    def __init__(self):
        ma_cls = resolve_ma_class(self.p.ma_method)
        self.lines.smooth_open = ma_cls(self.data.open, period=self.p.ma_length)
        self.lines.smooth_high = ma_cls(self.data.high, period=self.p.ma_length)
        self.lines.smooth_low = ma_cls(self.data.low, period=self.p.ma_length)
        self.lines.smooth_close = ma_cls(self.data.close, period=self.p.ma_length)
        self.addminperiod(self.p.ma_length + 2)

    def next(self):
        self.lines.color_state[0] = 0.0 if float(self.lines.smooth_open[0]) < float(self.lines.smooth_close[0]) else 1.0


class CandlesXSmoothedStrategy(bt.Strategy):
    params = dict(
        ma_method='lwma',
        ma_length=30,
        ma_phase=100,
        level=30,
        signal_bar=1,
        lot=0.1,
        point=0.01,
        price_digits=2,
        max_signal_lookback=500,
    )

    def __init__(self):
        self.signal = CandlesXSmoothedIndicator(
            self.data,
            ma_method=self.p.ma_method,
            ma_length=self.p.ma_length,
            ma_phase=self.p.ma_phase,
        )
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self._break_level = float(self.p.level) * float(self.p.point)

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _latest_breakout_state(self):
        signal_bar = max(1, int(self.p.signal_bar))
        max_lookback = min(len(self.data) - 1, int(self.p.max_signal_lookback))
        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False
        for shift in range(signal_bar, max_lookback + 1):
            close_value = float(self.data.close[-shift])
            smooth_high = float(self.signal.smooth_high[-shift])
            smooth_low = float(self.signal.smooth_low[-shift])
            if close_value < smooth_low - self._break_level:
                buy_close = True
                if shift == signal_bar:
                    sell_open = True
                break
            if close_value > smooth_high + self._break_level:
                sell_close = True
                if shift == signal_bar:
                    buy_open = True
                break
        return buy_open, sell_open, buy_close, sell_close

    def next(self):
        self.bar_num += 1
        if len(self.data) < int(self.p.ma_length) + int(self.p.signal_bar) + 5:
            return

        buy_open, sell_open, buy_close, sell_close = self._latest_breakout_state()
        current_close = float(self.data.close[0])
        current_high = float(self.signal.smooth_high[0])
        current_low = float(self.signal.smooth_low[0])

        if self.position:
            if self.position.size > 0:
                if buy_close and not sell_open:
                    self.log(f'close long close={current_close:.2f} slow={current_low:.2f}')
                    self.close()
                    return
                if sell_open:
                    self.log(f'close long & sell close={current_close:.2f} slow={current_low:.2f}')
                    self.close()
                    self.sell(size=self.p.lot)
                    return
            if self.position.size < 0:
                if sell_close and not buy_open:
                    self.log(f'close short close={current_close:.2f} shigh={current_high:.2f}')
                    self.close()
                    return
                if buy_open:
                    self.log(f'close short & buy close={current_close:.2f} shigh={current_high:.2f}')
                    self.close()
                    self.buy(size=self.p.lot)
                    return
        else:
            if buy_open:
                self.log(f'buy close={current_close:.2f} shigh={current_high:.2f}')
                self.buy(size=self.p.lot)
                return
            if sell_open:
                self.log(f'sell close={current_close:.2f} slow={current_low:.2f}')
                self.sell(size=self.p.lot)
                return

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            if trade.size > 0:
                self.buy_count += 1
            elif trade.size < 0:
                self.sell_count += 1
            self._position_was_open = True
            return
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
