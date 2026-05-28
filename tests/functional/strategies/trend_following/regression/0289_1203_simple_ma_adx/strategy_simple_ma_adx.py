from __future__ import absolute_import, division, print_function, unicode_literals

import io
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BACKTRADER_REPO = WORKSPACE_ROOT / 'backtrader'
if str(BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(BACKTRADER_REPO))

import backtrader as bt
import backtrader.feeds as btfeeds
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


class Mt5PandasFeed(btfeeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class SimpleMaAdxStrategy(bt.Strategy):
    params = dict(
        stop_loss_points=30,
        take_profit_points=100,
        adx_period=8,
        ma_period=8,
        adx_min=22.0,
        lot=0.1,
        point=0.01,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.ma = bt.ind.EMA(self.base.close, period=int(self.p.ma_period))
        self.adx = bt.ind.AverageDirectionalMovementIndex(self.base, period=int(self.p.adx_period))
        self.plus_di = bt.ind.PlusDirectionalIndicator(self.base, period=int(self.p.adx_period))
        self.minus_di = bt.ind.MinusDirectionalIndicator(self.base, period=int(self.p.adx_period))
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

    def log(self, text):
        dt = bt.num2date(self.base.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _check_exit_levels(self):
        if not self.position:
            return False
        close_price = float(self.base.close[0])
        stop_distance = float(self.p.stop_loss_points) * float(self.p.point) if self.p.stop_loss_points > 0 else None
        take_distance = float(self.p.take_profit_points) * float(self.p.point) if self.p.take_profit_points > 0 else None
        entry_price = float(self.position.price)

        if self.position.size > 0:
            if stop_distance is not None and close_price <= entry_price - stop_distance:
                self.log(f'close long by stop loss close={close_price:.2f} entry={entry_price:.2f}')
                self.close()
                return True
            if take_distance is not None and close_price >= entry_price + take_distance:
                self.log(f'close long by take profit close={close_price:.2f} entry={entry_price:.2f}')
                self.close()
                return True
        elif self.position.size < 0:
            if stop_distance is not None and close_price >= entry_price + stop_distance:
                self.log(f'close short by stop loss close={close_price:.2f} entry={entry_price:.2f}')
                self.close()
                return True
            if take_distance is not None and close_price <= entry_price - take_distance:
                self.log(f'close short by take profit close={close_price:.2f} entry={entry_price:.2f}')
                self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.base) < 4:
            return

        if self._check_exit_levels():
            return

        ma0 = float(self.ma[0])
        ma1 = float(self.ma[-1])
        ma2 = float(self.ma[-2])
        adx0 = float(self.adx[0])
        plus_di0 = float(self.plus_di[0])
        minus_di0 = float(self.minus_di[0])
        p_close = float(self.base.close[-1])
        size = abs(float(self.p.lot))
        if size <= 0:
            return

        buy_condition_1 = ma0 > ma1 and ma1 > ma2
        buy_condition_2 = p_close > ma1
        buy_condition_3 = adx0 > float(self.p.adx_min)
        buy_condition_4 = plus_di0 > minus_di0

        sell_condition_1 = ma0 < ma1 and ma1 < ma2
        sell_condition_2 = p_close < ma1
        sell_condition_3 = adx0 > float(self.p.adx_min)
        sell_condition_4 = plus_di0 < minus_di0

        close_price = float(self.base.close[0])
        if buy_condition_1 and buy_condition_2 and buy_condition_3 and buy_condition_4:
            self.signal_count += 1
            self.log(f'buy signal close={close_price:.2f} ma0={ma0:.5f} adx={adx0:.2f} +di={plus_di0:.2f} -di={minus_di0:.2f}')
            if self.position.size < 0:
                self.close()
            self.buy(size=size)
            return

        if sell_condition_1 and sell_condition_2 and sell_condition_3 and sell_condition_4:
            self.signal_count += 1
            self.log(f'sell signal close={close_price:.2f} ma0={ma0:.5f} adx={adx0:.2f} +di={plus_di0:.2f} -di={minus_di0:.2f}')
            if self.position.size > 0:
                self.close()
            self.sell(size=size)

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
