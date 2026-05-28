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
    if mode in {'mode_sma', 'sma'}:
        return bt.indicators.SimpleMovingAverage
    if mode in {'mode_ema', 'ema', 'mode_jjma', 'jjma', 'mode_jurx', 'jurx', 'mode_parma', 'parma', 'mode_t3', 't3', 'mode_vidya', 'vidya', 'mode_ama', 'ama'}:
        return bt.indicators.ExponentialMovingAverage
    if mode in {'mode_smma', 'smma'}:
        return bt.indicators.SmoothedMovingAverage
    return bt.indicators.WeightedMovingAverage


class QQECloudIndicator(bt.Indicator):
    lines = ('up', 'down')
    params = dict(rsi_period=14, sf=5, darfactor=4.236, xma_method='sma', xphase=15)

    def __init__(self):
        self._rsi = bt.indicators.RelativeStrengthIndex(self.data.close, period=max(2, int(self.p.rsi_period)))
        ma_cls = resolve_ma_class(self.p.xma_method)
        self._xrsi = ma_cls(self._rsi, period=max(1, int(self.p.sf)))
        wilders_period = max(2, int(self.p.rsi_period) * 2 - 1)
        self._mom = abs(self._xrsi - self._xrsi(-1))
        self._xmom = ma_cls(self._mom, period=wilders_period)
        self._xxmom = ma_cls(self._xmom, period=wilders_period)
        self.addminperiod(int(self.p.rsi_period) + int(self.p.sf) + wilders_period * 2 + 5)

    def next(self):
        xrsi = float(self._xrsi[0])
        prev_xrsi = float(self._xrsi[-1])
        dar = float(self._xxmom[0]) * float(self.p.darfactor)
        prev_tr = float(self.lines.down[-1]) if len(self) > 0 else 50.0
        if prev_tr != prev_tr:
            prev_tr = 50.0
        tr = prev_tr
        dv = tr
        if xrsi < tr:
            tr = xrsi + dar
            if prev_xrsi < dv and tr > dv:
                tr = dv
        elif xrsi > tr:
            tr = xrsi - dar
            if prev_xrsi > dv and tr < dv:
                tr = dv
        self.lines.up[0] = xrsi
        self.lines.down[0] = tr

    def once(self, start, end):
        xrsi_array = self._xrsi.array
        xxmom_array = self._xxmom.array
        up_line = self.lines.up.array
        down_line = self.lines.down.array
        for line in (up_line, down_line):
            while len(line) < end:
                line.append(float('nan'))

        prev_tr = 50.0
        actual_end = min(end, len(xrsi_array), len(xxmom_array))
        for i in range(start, actual_end):
            xrsi = float(xrsi_array[i])
            prev_xrsi = float(xrsi_array[i - 1]) if i > 0 else xrsi
            dar = float(xxmom_array[i]) * float(self.p.darfactor)
            tr = prev_tr
            dv = tr
            if xrsi < tr:
                tr = xrsi + dar
                if prev_xrsi < dv and tr > dv:
                    tr = dv
            elif xrsi > tr:
                tr = xrsi - dar
                if prev_xrsi > dv and tr < dv:
                    tr = dv
            up_line[i] = xrsi
            down_line[i] = tr
            prev_tr = tr


class QQECloudStrategy(bt.Strategy):
    params = dict(
        start_hour=8,
        start_minute=0,
        stop_hour=23,
        stop_minute=59,
        rsi_period=14,
        sf=5,
        darfactor=4.236,
        xma_method='sma',
        xphase=15,
        signal_bar=1,
        lot=0.1,
    )

    def __init__(self):
        self.indicator = QQECloudIndicator(
            self.data,
            rsi_period=self.p.rsi_period,
            sf=self.p.sf,
            darfactor=self.p.darfactor,
            xma_method=self.p.xma_method,
            xphase=self.p.xphase,
        )
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

    def _indicator_signals(self):
        shift = max(1, int(self.p.signal_bar))
        up = float(self.indicator.up[-shift])
        dn = float(self.indicator.down[-shift])
        buy_open1 = up > dn
        sell_open1 = up < dn
        buy_close = sell_open1
        sell_close = buy_open1
        return buy_open1, sell_open1, buy_close, sell_close

    def next(self):
        self.bar_num += 1
        warmup = int(self.p.rsi_period) + int(self.p.sf) + int(self.p.rsi_period) * 4 + int(self.p.signal_bar) + 5
        if len(self.data) < warmup:
            return
        buy_open1, sell_open1, buy_close, sell_close = self._indicator_signals()
        dt = bt.num2date(self.data.datetime[0])
        buy_open = buy_open1 and dt.hour == int(self.p.start_hour) and dt.minute == int(self.p.start_minute)
        sell_open = sell_open1 and dt.hour == int(self.p.start_hour) and dt.minute == int(self.p.start_minute)
        if (dt.hour == int(self.p.stop_hour) and dt.minute >= int(self.p.stop_minute)) or dt.hour > int(self.p.stop_hour) or dt.hour < int(self.p.start_hour):
            buy_close = True
            sell_close = True
        up = float(self.indicator.up[0])
        dn = float(self.indicator.down[0])
        if self.position:
            if self.position.size > 0:
                if buy_close and not sell_open:
                    self.log(f'close long up={up:.2f} dn={dn:.2f}')
                    self.close()
                    return
                if sell_open:
                    self.log(f'close long & sell up={up:.2f} dn={dn:.2f}')
                    self.close()
                    self.sell(size=self.p.lot)
                    return
            if self.position.size < 0:
                if sell_close and not buy_open:
                    self.log(f'close short up={up:.2f} dn={dn:.2f}')
                    self.close()
                    return
                if buy_open:
                    self.log(f'close short & buy up={up:.2f} dn={dn:.2f}')
                    self.close()
                    self.buy(size=self.p.lot)
                    return
        else:
            if buy_open1 and buy_open:
                self.log(f'buy up={up:.2f} dn={dn:.2f}')
                self.buy(size=self.p.lot)
                return
            if sell_open1 and sell_open:
                self.log(f'sell up={up:.2f} dn={dn:.2f}')
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
