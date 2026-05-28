from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math
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


class MUVNorDiffCloudIndicator(bt.Indicator):
    lines = ('buy', 'sell', 'sma_res', 'ema_res')
    params = dict(ma_period=14, momentum=1, kperiod=14)

    def __init__(self):
        price = self.data.close
        self._sma = bt.indicators.SimpleMovingAverage(price, period=max(1, int(self.p.ma_period)))
        self._ema = bt.indicators.ExponentialMovingAverage(price, period=max(1, int(self.p.ma_period)))
        self.addminperiod(int(self.p.ma_period) + int(self.p.momentum) + int(self.p.kperiod) + 5)

    def next(self):
        momentum = max(1, int(self.p.momentum))
        kperiod = max(2, int(self.p.kperiod))
        sma_vals = []
        ema_vals = []
        for i in range(kperiod):
            sma_vals.append(float(self._sma[-i]) - float(self._sma[-i - momentum]))
            ema_vals.append(float(self._ema[-i]) - float(self._ema[-i - momentum]))
        sma_cur = sma_vals[0]
        ema_cur = ema_vals[0]
        sma_max = max(sma_vals)
        sma_min = min(sma_vals)
        ema_max = max(ema_vals)
        ema_min = min(ema_vals)
        sma_range = sma_max - sma_min
        ema_range = ema_max - ema_min
        sma_res = 100.0 - 200.0 * (sma_max - sma_cur) / sma_range if sma_range > 0 else 100.0
        ema_res = 100.0 - 200.0 * (ema_max - ema_cur) / ema_range if ema_range > 0 else 100.0
        self.lines.sma_res[0] = sma_res
        self.lines.ema_res[0] = ema_res
        self.lines.buy[0] = 100.0 if sma_res == 100.0 or ema_res == 100.0 else 0.0
        self.lines.sell[0] = -100.0 if sma_res == -100.0 or ema_res == -100.0 else 0.0

    def once(self, start, end):
        momentum = max(1, int(self.p.momentum))
        kperiod = max(2, int(self.p.kperiod))
        sma = self._sma.array
        ema = self._ema.array
        buy = self.lines.buy.array
        sell = self.lines.sell.array
        sma_res_line = self.lines.sma_res.array
        ema_res_line = self.lines.ema_res.array

        for i in range(start, end):
            sma_vals = []
            ema_vals = []
            for j in range(kperiod):
                idx = i - j
                prev = idx - momentum
                if prev < 0:
                    continue
                sma_delta = float(sma[idx]) - float(sma[prev])
                ema_delta = float(ema[idx]) - float(ema[prev])
                if math.isfinite(sma_delta):
                    sma_vals.append(sma_delta)
                if math.isfinite(ema_delta):
                    ema_vals.append(ema_delta)
            if not sma_vals or not ema_vals:
                sma_res = ema_res = 0.0
            else:
                sma_cur = sma_vals[0]
                ema_cur = ema_vals[0]
                sma_max = max(sma_vals)
                sma_min = min(sma_vals)
                ema_max = max(ema_vals)
                ema_min = min(ema_vals)
                sma_range = sma_max - sma_min
                ema_range = ema_max - ema_min
                sma_res = 100.0 - 200.0 * (sma_max - sma_cur) / sma_range if sma_range > 0 else 100.0
                ema_res = 100.0 - 200.0 * (ema_max - ema_cur) / ema_range if ema_range > 0 else 100.0
            sma_res_line[i] = sma_res
            ema_res_line[i] = ema_res
            buy[i] = 100.0 if sma_res == 100.0 or ema_res == 100.0 else 0.0
            sell[i] = -100.0 if sma_res == -100.0 or ema_res == -100.0 else 0.0


class MUVNorDiffCloudStrategy(bt.Strategy):
    params = dict(
        ma_period=14,
        momentum=1,
        kperiod=14,
        signal_bar=1,
        lot=0.1,
    )

    def __init__(self):
        self.indicator = MUVNorDiffCloudIndicator(
            self.data,
            ma_period=self.p.ma_period,
            momentum=self.p.momentum,
            kperiod=self.p.kperiod,
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

    def _has_recent_signal(self, line, shift, limit=120):
        start = max(shift + 1, 1)
        max_lookback = min(len(self.data) - 1, start + limit)
        for bar in range(start, max_lookback):
            if float(line[-bar]) != 0.0:
                return True
        return False

    def _signals(self):
        shift = max(1, int(self.p.signal_bar))
        up_value = float(self.indicator.buy[-shift])
        dn_value = float(self.indicator.sell[-shift])
        buy_open = up_value != 0.0
        sell_open = dn_value != 0.0
        buy_close = sell_open
        sell_close = buy_open
        if not buy_close and not sell_close:
            if self.position.size < 0 and self._has_recent_signal(self.indicator.buy, shift):
                sell_close = True
            if self.position.size > 0 and self._has_recent_signal(self.indicator.sell, shift):
                buy_close = True
        return buy_open, sell_open, buy_close, sell_close

    def next(self):
        self.bar_num += 1
        warmup = int(self.p.ma_period) + int(self.p.momentum) + int(self.p.kperiod) + int(self.p.signal_bar) + 5
        if len(self.data) < warmup:
            return
        buy_open, sell_open, buy_close, sell_close = self._signals()
        sma_res = float(self.indicator.sma_res[0])
        ema_res = float(self.indicator.ema_res[0])
        if self.position:
            if self.position.size > 0:
                if buy_close and not sell_open:
                    self.log(f'close long sma={sma_res:.2f} ema={ema_res:.2f}')
                    self.close()
                    return
                if sell_open:
                    self.log(f'close long & sell sma={sma_res:.2f} ema={ema_res:.2f}')
                    self.close()
                    self.sell(size=self.p.lot)
                    return
            if self.position.size < 0:
                if sell_close and not buy_open:
                    self.log(f'close short sma={sma_res:.2f} ema={ema_res:.2f}')
                    self.close()
                    return
                if buy_open:
                    self.log(f'close short & buy sma={sma_res:.2f} ema={ema_res:.2f}')
                    self.close()
                    self.buy(size=self.p.lot)
                    return
        else:
            if buy_open:
                self.log(f'buy sma={sma_res:.2f} ema={ema_res:.2f}')
                self.buy(size=self.p.lot)
                return
            if sell_open:
                self.log(f'sell sma={sma_res:.2f} ema={ema_res:.2f}')
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
