from __future__ import absolute_import, division, print_function, unicode_literals

import io
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BACKTRADER_REPO = WORKSPACE_ROOT / 'backtrader'
if str(BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(BACKTRADER_REPO))

import backtrader as bt
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines if line.strip())
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={'<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low', '<CLOSE>': 'close', '<TICKVOL>': 'volume', '<VOL>': 'openinterest'})
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.set_index('datetime').sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5))


class DayTradingStrategy(bt.Strategy):
    params = dict(fixed_lot=0.1, trailing_stop_points=25, take_profit_points=50, stop_loss_points=0, point=0.01)

    def __init__(self):
        self.macd = bt.indicators.MACD(self.data.open, period_me1=12, period_me2=26, period_signal=9)
        self.stoch = bt.indicators.Stochastic(self.data, period=5, period_dfast=3, period_dslow=3)
        self.sar = bt.indicators.ParabolicSAR(self.data, af=0.02, afmax=0.2)
        self.mom = bt.indicators.Momentum(self.data.open, period=14)
        self.signal_count = 0
        self.trade_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

    def _manage_trailing_stop(self):
        if not self.position or self.p.trailing_stop_points <= 0:
            return False
        dist = float(self.p.trailing_stop_points) * float(self.p.point)
        cp = float(self.data.close[0])
        ep = float(self.position.price)
        if self.position.size > 0 and cp - ep > dist:
            if cp <= ep + dist:
                self.close()
                return True
        if self.position.size < 0 and ep - cp > dist:
            if cp >= ep - dist:
                self.close()
                return True
        return False

    def _manage_tp_sl(self):
        if not self.position:
            return False
        cp = float(self.data.close[0])
        ep = float(self.position.price)
        tp = float(self.p.take_profit_points) * float(self.p.point)
        sl = float(self.p.stop_loss_points) * float(self.p.point)
        if self.position.size > 0:
            if tp > 0 and cp >= ep + tp:
                self.close(); return True
            if sl > 0 and cp <= ep - sl:
                self.close(); return True
        if self.position.size < 0:
            if tp > 0 and cp <= ep - tp:
                self.close(); return True
            if sl > 0 and cp >= ep + sl:
                self.close(); return True
        return False

    def next(self):
        if len(self.data) < 200:
            return
        if self._manage_tp_sl():
            return
        if self._manage_trailing_stop():
            return
        ask = float(self.data.close[0])
        bid = float(self.data.close[0])
        is_buying = float(self.sar[0]) <= ask and float(self.sar[-1]) > float(self.sar[0]) and float(self.mom[0]) < 100.0 and float(self.macd.macd[0]) < float(self.macd.signal[0]) and float(self.stoch.percK[0]) < 35.0
        is_selling = float(self.sar[0]) >= bid and float(self.sar[-1]) < float(self.sar[0]) and float(self.mom[0]) > 100.0 and float(self.macd.macd[0]) > float(self.macd.signal[0]) and float(self.stoch.percK[0]) > 60.0
        is_closing = False
        if self.position.size > 0 and (is_selling or is_closing):
            self.close()
            return
        if self.position.size < 0 and (is_buying or is_closing):
            self.close()
            return
        if not self.position:
            if is_buying and not is_selling and not is_closing:
                self.signal_count += 1
                self.buy(size=float(self.p.fixed_lot))
            elif is_selling and not is_buying and not is_closing:
                self.signal_count += 1
                self.sell(size=float(self.p.fixed_lot))

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            self._position_was_open = True
            if trade.size > 0:
                self.buy_count += 1
            elif trade.size < 0:
                self.sell_count += 1
            return
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False
