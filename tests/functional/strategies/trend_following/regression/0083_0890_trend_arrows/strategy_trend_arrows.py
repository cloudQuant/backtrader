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


class TrendArrowsIndicator(bt.Indicator):
    """Reconstructs trend_arrows indicator.

    Computes AverageHigh (avg of highest highs over iPeriod sub-windows)
    and AverageLow (avg of lowest lows over iPeriod sub-windows).
    TrendUp = LL when close > HH; TrendDown = HH when close < LL;
    else continues previous trend.
    SignUp when TrendUp appears fresh; SignDown when TrendDown appears fresh.
    Buffers: 0=TrendUp, 1=TrendDown, 2=SignUp(buy), 3=SignDown(sell).
    """
    lines = ('trend_up', 'trend_down', 'sign_up', 'sign_down')
    params = dict(iperiod=15, ifullperiods=1)

    def __init__(self):
        self._ip = int(self.p.iperiod)
        self._ifp = int(self.p.ifullperiods)
        self._window = self._ip + self._ifp
        self.addminperiod(self._window + 2)

    def next(self):
        ip = self._ip
        ifp = self._ifp
        window = self._window

        # Compute AverageHigh: average of highest highs over ip sub-windows
        segment_size = max(window // ip, 1)
        hh_sum = 0.0
        ll_sum = 0.0
        count = 0
        for seg in range(ip):
            start = seg * segment_size
            end = min(start + segment_size, window)
            if start >= len(self.data):
                break
            seg_high = -1e30
            seg_low = 1e30
            for k in range(start, min(end, len(self.data))):
                h = float(self.data.high[-k]) if k > 0 else float(self.data.high[0])
                l = float(self.data.low[-k]) if k > 0 else float(self.data.low[0])
                if h > seg_high:
                    seg_high = h
                if l < seg_low:
                    seg_low = l
            hh_sum += seg_high
            ll_sum += seg_low
            count += 1

        hh = hh_sum / count if count else float(self.data.high[0])
        ll = ll_sum / count if count else float(self.data.low[0])

        close_val = float(self.data.close[0])
        prev_tu = float(self.lines.trend_up[-1]) if len(self.lines.trend_up) > 1 else 0.0
        prev_td = float(self.lines.trend_down[-1]) if len(self.lines.trend_down) > 1 else 0.0
        if math.isnan(prev_tu):
            prev_tu = 0.0
        if math.isnan(prev_td):
            prev_td = 0.0

        tu = 0.0
        td = 0.0

        if close_val > hh:
            tu = ll
        elif close_val < ll:
            td = hh
        else:
            if prev_td != 0.0:
                td = hh
            if prev_tu != 0.0:
                tu = ll

        su = 0.0
        sd = 0.0
        if prev_tu == 0.0 and tu != 0.0:
            su = tu
        if prev_td == 0.0 and td != 0.0:
            sd = td

        self.lines.trend_up[0] = tu
        self.lines.trend_down[0] = td
        self.lines.sign_up[0] = su
        self.lines.sign_down[0] = sd


class ExpTrendArrowsStrategy(bt.Strategy):
    """EA reads buffer 2 (SignUp/buy) and buffer 3 (SignDown/sell).
    Also reads buffer 0/1 (TrendUp/TrendDown) for closing."""
    params = dict(
        iperiod=15,
        ifullperiods=1,
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
        self.indicator = TrendArrowsIndicator(
            self.signal_data,
            iperiod=self.p.iperiod,
            ifullperiods=self.p.ifullperiods,
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

    def _val(self, line, offset):
        v = float(line[-offset]) if offset else float(line[0])
        return 0.0 if math.isnan(v) else v

    def next(self):
        self.bar_num += 1
        if len(self.base) < 2:
            return
        if self._check_exit_levels():
            return
        sig_bar = max(int(self.p.signal_bar) - 1, 0)
        min_needed = self.p.iperiod + self.p.ifullperiods + sig_bar + 4
        if len(self.signal_data) < min_needed:
            return
        csl = len(self.signal_data)
        if csl == self._last_signal_len:
            return
        self._last_signal_len = csl

        su = self._val(self.indicator.sign_up, sig_bar)
        sd = self._val(self.indicator.sign_down, sig_bar)
        tu = self._val(self.indicator.trend_up, sig_bar)
        td = self._val(self.indicator.trend_down, sig_bar)

        cp = float(self.base.close[0])
        sz = float(self.p.fixed_lot)
        if sz <= 0:
            return

        BO = SO = BC = SC = False
        if su != 0.0:
            if self.p.buy_pos_open: BO = True
            if self.p.sell_pos_close: SC = True
        if sd != 0.0:
            if self.p.sell_pos_open: SO = True
            if self.p.buy_pos_close: BC = True

        # Also check TrendUp/TrendDown for closing existing positions
        if tu != 0.0 and self.p.sell_pos_open and self.p.sell_pos_close:
            SC = True
        if td != 0.0 and self.p.buy_pos_open and self.p.buy_pos_close:
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
