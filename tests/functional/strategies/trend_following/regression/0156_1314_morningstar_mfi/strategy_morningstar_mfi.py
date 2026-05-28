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


class MoneyFlowIndex(bt.Indicator):
    lines = ('mfi',)
    params = (('period', 14),)

    def __init__(self):
        self.addminperiod(self.p.period + 1)

    def next(self):
        positive_flow = 0.0
        negative_flow = 0.0
        for i in range(self.p.period):
            curr_tp = (float(self.data.high[-i]) + float(self.data.low[-i]) + float(self.data.close[-i])) / 3.0
            prev_tp = (float(self.data.high[-i - 1]) + float(self.data.low[-i - 1]) + float(self.data.close[-i - 1])) / 3.0
            raw_flow = curr_tp * float(self.data.volume[-i])
            if curr_tp > prev_tp:
                positive_flow += raw_flow
            elif curr_tp < prev_tp:
                negative_flow += raw_flow
        if negative_flow == 0.0:
            self.lines.mfi[0] = 100.0
            return
        money_ratio = positive_flow / negative_flow
        self.lines.mfi[0] = 100.0 - (100.0 / (1.0 + money_ratio))


class MorningStarMfiStrategy(bt.Strategy):
    """
    Morning Star / Evening Star + MFI confirmation.
    Buy: Morning Star (or Doji) AND MFI < mfi_entry_long
    Sell: Evening Star (or Doji) AND MFI > mfi_entry_short
    Exit: MFI crosses overbought/oversold levels
    """
    params = dict(
        mfi_period=12,
        mfi_entry_long=40,
        mfi_entry_short=60,
        mfi_exit_upper=70,
        mfi_exit_lower=30,
        ma_period=5,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.mfi = MoneyFlowIndex(self.data, period=self.p.mfi_period)
        self.sma_body = bt.indicators.SMA(abs(self.data.close - self.data.open), period=self.p.ma_period)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _avg_body(self):
        return float(self.sma_body[0])

    def _mid_oc(self, ago):
        return (float(self.data.open[ago]) + float(self.data.close[ago])) / 2.0

    def _is_morning_star(self):
        o3, c3 = float(self.data.open[-3]), float(self.data.close[-3])
        o2, c2 = float(self.data.open[-2]), float(self.data.close[-2])
        c1 = float(self.data.close[-1])
        avg = self._avg_body()
        if avg < self.p.point:
            return False
        return ((o3 - c3) > avg and
                abs(c2 - o2) < avg * 0.5 and
                c2 < c3 and o2 < o3 and
                c1 > self._mid_oc(-3))

    def _is_morning_doji(self):
        o3, c3 = float(self.data.open[-3]), float(self.data.close[-3])
        o2, c2 = float(self.data.open[-2]), float(self.data.close[-2])
        o1, c1 = float(self.data.open[-1]), float(self.data.close[-1])
        avg = self._avg_body()
        if avg < self.p.point:
            return False
        return ((o3 - c3) > avg and
                abs(c2 - o2) < avg * 0.1 and
                c2 < c3 and o2 < o3 and
                o1 > c2 and c1 > c2)

    def _is_evening_star(self):
        o3, c3 = float(self.data.open[-3]), float(self.data.close[-3])
        o2, c2 = float(self.data.open[-2]), float(self.data.close[-2])
        c1 = float(self.data.close[-1])
        avg = self._avg_body()
        if avg < self.p.point:
            return False
        return ((c3 - o3) > avg and
                abs(c2 - o2) < avg * 0.5 and
                c2 > c3 and o2 > o3 and
                c1 < self._mid_oc(-3))

    def _is_evening_doji(self):
        o3, c3 = float(self.data.open[-3]), float(self.data.close[-3])
        o2, c2 = float(self.data.open[-2]), float(self.data.close[-2])
        o1, c1 = float(self.data.open[-1]), float(self.data.close[-1])
        avg = self._avg_body()
        if avg < self.p.point:
            return False
        return ((c3 - o3) > avg and
                abs(c2 - o2) < avg * 0.1 and
                c2 > c3 and o2 > o3 and
                o1 < c2 and c1 < c2)

    def next(self):
        self.bar_num += 1
        warmup = max(self.p.mfi_period, self.p.ma_period) + 5
        if len(self.data) < warmup:
            return

        mfi0 = float(self.mfi[0])
        mfi1 = float(self.mfi[-1])

        if self.position:
            if self.position.size > 0:
                if ((mfi0 > self.p.mfi_exit_upper and mfi1 < self.p.mfi_exit_upper) or
                    (mfi0 < self.p.mfi_exit_lower and mfi1 > self.p.mfi_exit_lower)):
                    self.log(f'close long mfi={mfi0:.1f}')
                    self.close()
                    return
            elif self.position.size < 0:
                if ((mfi0 > self.p.mfi_exit_lower and mfi1 < self.p.mfi_exit_lower) or
                    (mfi0 > self.p.mfi_exit_upper and mfi1 < self.p.mfi_exit_upper)):
                    self.log(f'close short mfi={mfi0:.1f}')
                    self.close()
                    return
        else:
            if (self._is_morning_star() or self._is_morning_doji()) and mfi1 < self.p.mfi_entry_long:
                self.log(f'buy morningstar+mfi mfi={mfi1:.1f}')
                self.buy(size=self.p.lot)
                return
            if (self._is_evening_star() or self._is_evening_doji()) and mfi1 > self.p.mfi_entry_short:
                self.log(f'sell eveningstar+mfi mfi={mfi1:.1f}')
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
