from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math
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
    df = df.rename(columns={
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low',
        '<CLOSE>': 'close', '<TICKVOL>': 'volume', '<VOL>': 'openinterest',
    })
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
    params = (('datetime', None), ('open', 0), ('high', 1), ('low', 2),
              ('close', 3), ('volume', 4), ('openinterest', 5))


class PriceChannelStopIndicator(bt.Indicator):
    """Reconstructs PriceChannel_Stop from its MQ5 source.

    6 output buffers mapped to lines:
      0=DownTrendSignal, 1=DownTrendBuffer, 2=DownTrendLine
      3=UpTrendSignal,   4=UpTrendBuffer,   5=UpTrendLine
    """
    lines = ('down_signal', 'down_buffer', 'down_line',
             'up_signal', 'up_buffer', 'up_line')
    params = dict(channel_period=5, risk=0.10)

    def __init__(self):
        self._cp = int(self.p.channel_period)
        self._risk = float(self.p.risk)
        self._trend = 0
        self._prev_bsmax = 0.0
        self._prev_bsmin = 0.0
        self.addminperiod(self._cp + 2)

    def next(self):
        cp = self._cp
        risk = self._risk

        # Highest high and lowest low over [bar, bar+ChannelPeriod)
        hi = max(float(self.data.high[-i]) for i in range(cp))
        lo = min(float(self.data.low[-i]) for i in range(cp))

        d_price = (hi - lo) * risk
        bsmax = hi - d_price
        bsmin = lo + d_price

        cur_close = float(self.data.close[0])

        if cur_close > self._prev_bsmax:
            self._trend = 1
        if cur_close < self._prev_bsmin:
            self._trend = -1

        # Ratchet
        if self._trend > 0 and bsmin < self._prev_bsmin:
            bsmin = self._prev_bsmin
        if self._trend < 0 and bsmax > self._prev_bsmax:
            bsmax = self._prev_bsmax

        # Reset all
        self.lines.down_signal[0] = 0.0
        self.lines.down_buffer[0] = 0.0
        self.lines.down_line[0] = 0.0
        self.lines.up_signal[0] = 0.0
        self.lines.up_buffer[0] = 0.0
        self.lines.up_line[0] = 0.0

        prev_down_buffer = float(self.lines.down_buffer[-1]) if len(self) > 1 and not math.isnan(float(self.lines.down_buffer[-1])) else 0.0
        prev_up_buffer = float(self.lines.up_buffer[-1]) if len(self) > 1 and not math.isnan(float(self.lines.up_buffer[-1])) else 0.0

        if self._trend > 0:
            price = bsmin
            if prev_down_buffer > 0:
                self.lines.up_signal[0] = price
                self.lines.up_line[0] = price
            else:
                self.lines.up_buffer[0] = price
                self.lines.up_line[0] = price

        if self._trend < 0:
            price = bsmax
            if prev_up_buffer > 0:
                self.lines.down_signal[0] = price
                self.lines.down_line[0] = price
            else:
                self.lines.down_buffer[0] = price
                self.lines.down_line[0] = price

        self._prev_bsmax = bsmax
        self._prev_bsmin = bsmin


class ExpPriceChannelStopStrategy(bt.Strategy):
    params = dict(
        channel_period=5,
        risk=0.10,
        signal_bar=1,
        stop_loss_points=1000,
        take_profit_points=2000,
        fixed_lot=0.1,
        point=0.0001,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        indicator_minutes=60,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.signal_data = self.datas[1]
        self.indicator = PriceChannelStopIndicator(
            self.signal_data,
            channel_period=self.p.channel_period,
            risk=self.p.risk,
        )
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self._last_signal_len = 0

    def log(self, text):
        print(f'{bt.num2date(self.base.datetime[0]).isoformat()}, {text}')

    def _check_exit_levels(self):
        if not self.position:
            return False
        cp = float(self.base.close[0])
        pv = float(self.p.point)
        sd = self.p.stop_loss_points * pv if self.p.stop_loss_points > 0 else None
        td = self.p.take_profit_points * pv if self.p.take_profit_points > 0 else None
        ep = float(self.position.price)
        if self.position.size > 0:
            if sd and cp <= ep - sd:
                self.log(f'close long SL {cp:.5f}'); self.close(); return True
            if td and cp >= ep + td:
                self.log(f'close long TP {cp:.5f}'); self.close(); return True
        elif self.position.size < 0:
            if sd and cp >= ep + sd:
                self.log(f'close short SL {cp:.5f}'); self.close(); return True
            if td and cp <= ep - td:
                self.log(f'close short TP {cp:.5f}'); self.close(); return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.base) < 2:
            return
        if self._check_exit_levels():
            return
        sig_bar = max(int(self.p.signal_bar) - 1, 0)
        min_needed = int(self.p.channel_period) + sig_bar + 4
        if len(self.signal_data) < min_needed:
            return
        csl = len(self.signal_data)
        if csl == self._last_signal_len:
            return
        self._last_signal_len = csl

        def gv(line, ago):
            v = float(line[-ago]) if ago > 0 else float(line[0])
            return 0.0 if math.isnan(v) else v

        # Buffer 3 = up_signal (buy signal), Buffer 0 = down_signal (sell signal)
        up_sig = gv(self.indicator.up_signal, sig_bar)
        dn_sig = gv(self.indicator.down_signal, sig_bar)
        # Buffer 4 = up_buffer (buy stop), Buffer 1 = down_buffer (sell stop)
        up_buf = gv(self.indicator.up_buffer, sig_bar)
        dn_buf = gv(self.indicator.down_buffer, sig_bar)

        cp = float(self.base.close[0])
        sz = float(self.p.fixed_lot)
        if sz <= 0:
            return

        BO = SO = BC = SC = False

        if up_sig != 0.0:
            if self.p.buy_pos_open: BO = True
            if self.p.sell_pos_close: SC = True
        if dn_sig != 0.0:
            if self.p.sell_pos_open: SO = True
            if self.p.buy_pos_close: BC = True

        # Continuous trend close via stop buffers
        if self.p.sell_pos_open and self.p.sell_pos_close and up_buf != 0.0:
            SC = True
        if self.p.buy_pos_open and self.p.buy_pos_close and dn_buf != 0.0:
            BC = True

        if SC and self.position.size < 0:
            self.log(f'close short signal {cp:.5f}'); self.close()
        if BC and self.position.size > 0:
            self.log(f'close long signal {cp:.5f}'); self.close()
        if BO:
            self.signal_count += 1
            self.log(f'buy signal {cp:.5f}')
            if self.position.size <= 0: self.buy(size=sz)
        if SO:
            self.signal_count += 1
            self.log(f'sell signal {cp:.5f}')
            if self.position.size >= 0: self.sell(size=sz)

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            if trade.size > 0: self.buy_count += 1
            elif trade.size < 0: self.sell_count += 1
            self._position_was_open = True; return
        if not trade.isclosed: return
        self.trade_count += 1
        if trade.pnlcomm >= 0: self.win_count += 1
        else: self.loss_count += 1
        self._position_was_open = False
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
