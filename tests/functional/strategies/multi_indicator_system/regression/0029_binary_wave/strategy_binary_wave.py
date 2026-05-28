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


class BinaryWaveIndicator(bt.Indicator):
    lines = ('wave', 'raw',)
    params = dict(
        weight_ma=1.0,
        weight_macd=1.0,
        weight_osma=1.0,
        weight_cci=1.0,
        weight_mom=1.0,
        weight_rsi=1.0,
        weight_adx=1.0,
        ma_period=13,
        ma_type='ema',
        fast_macd=12,
        slow_macd=26,
        signal_macd=9,
        cci_period=14,
        mom_period=14,
        rsi_period=14,
        adx_period=14,
        smooth_period=5,
    )

    def __init__(self):
        ma_type = str(self.p.ma_type).lower()
        ma_cls = bt.indicators.EMA if ma_type == 'ema' else bt.indicators.SMA
        self.ma = ma_cls(self.data.close, period=self.p.ma_period)
        self.macd = bt.indicators.MACD(
            self.data.close,
            period_me1=self.p.fast_macd,
            period_me2=self.p.slow_macd,
            period_signal=self.p.signal_macd,
        )
        self.cci = bt.indicators.CCI(self.data, period=self.p.cci_period)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.plus_di = bt.indicators.PlusDirectionalIndicator(self.data, period=self.p.adx_period)
        self.minus_di = bt.indicators.MinusDirectionalIndicator(self.data, period=self.p.adx_period)
        self.addminperiod(max(
            self.p.ma_period,
            self.p.slow_macd + self.p.signal_macd,
            self.p.cci_period,
            self.p.mom_period + 1,
            self.p.rsi_period,
            self.p.adx_period,
            self.p.smooth_period,
        ) + 5)

    def _momentum_ratio(self, idx=0):
        base_idx = idx - self.p.mom_period
        base = float(self.data.close[base_idx])
        if base == 0:
            return 100.0
        return float(self.data.close[idx]) / base * 100.0

    def _score(self):
        score = 0.0
        if self.p.weight_ma > 0:
            if float(self.data.close[0]) > float(self.ma[0]):
                score += self.p.weight_ma
            elif float(self.data.close[0]) < float(self.ma[0]):
                score -= self.p.weight_ma
        if self.p.weight_macd > 0:
            macd_now = float(self.macd.macd[0])
            macd_prev = float(self.macd.macd[-1])
            if macd_now > macd_prev:
                score += self.p.weight_macd
            elif macd_now < macd_prev:
                score -= self.p.weight_macd
        if self.p.weight_osma > 0:
            osma = float(self.macd.macd[0] - self.macd.signal[0])
            if osma > 0:
                score += self.p.weight_osma
            elif osma < 0:
                score -= self.p.weight_osma
        if self.p.weight_cci > 0:
            cci = float(self.cci[0])
            if cci > 0:
                score += self.p.weight_cci
            elif cci < 0:
                score -= self.p.weight_cci
        if self.p.weight_mom > 0:
            mom = self._momentum_ratio(0)
            if mom > 100.0:
                score += self.p.weight_mom
            elif mom < 100.0:
                score -= self.p.weight_mom
        if self.p.weight_rsi > 0:
            rsi = float(self.rsi[0])
            if rsi > 50.0:
                score += self.p.weight_rsi
            elif rsi < 50.0:
                score -= self.p.weight_rsi
        if self.p.weight_adx > 0:
            plus_di = float(self.plus_di[0])
            minus_di = float(self.minus_di[0])
            if plus_di > minus_di:
                score += self.p.weight_adx
            elif plus_di < minus_di:
                score -= self.p.weight_adx
        return score

    def next(self):
        raw = self._score()
        self.lines.raw[0] = raw
        if len(self) == 1:
            self.lines.wave[0] = raw
            return
        alpha = 2.0 / (self.p.smooth_period + 1.0)
        prev_wave = float(self.lines.wave[-1])
        if prev_wave != prev_wave:
            prev_wave = raw
        self.lines.wave[0] = prev_wave + alpha * (raw - prev_wave)

    def once(self, start, end):
        close_array = self.data.close.array
        ma_array = self.ma.array
        macd_array = self.macd.macd.array
        macd_signal_array = self.macd.signal.array
        cci_array = self.cci.array
        rsi_array = self.rsi.array
        plus_di_array = self.plus_di.array
        minus_di_array = self.minus_di.array
        wave_line = self.lines.wave.array
        raw_line = self.lines.raw.array
        for line in (wave_line, raw_line):
            while len(line) < end:
                line.append(float('nan'))

        alpha = 2.0 / (self.p.smooth_period + 1.0)
        prev_wave = None
        actual_end = min(
            end,
            len(close_array),
            len(ma_array),
            len(macd_array),
            len(macd_signal_array),
            len(cci_array),
            len(rsi_array),
            len(plus_di_array),
            len(minus_di_array),
        )
        for i in range(start, actual_end):
            score = 0.0
            close = float(close_array[i])
            if self.p.weight_ma > 0:
                ma = float(ma_array[i])
                if close > ma:
                    score += self.p.weight_ma
                elif close < ma:
                    score -= self.p.weight_ma
            if self.p.weight_macd > 0 and i > 0:
                macd_now = float(macd_array[i])
                macd_prev = float(macd_array[i - 1])
                if macd_now > macd_prev:
                    score += self.p.weight_macd
                elif macd_now < macd_prev:
                    score -= self.p.weight_macd
            if self.p.weight_osma > 0:
                osma = float(macd_array[i]) - float(macd_signal_array[i])
                if osma > 0:
                    score += self.p.weight_osma
                elif osma < 0:
                    score -= self.p.weight_osma
            if self.p.weight_cci > 0:
                cci = float(cci_array[i])
                if cci > 0:
                    score += self.p.weight_cci
                elif cci < 0:
                    score -= self.p.weight_cci
            if self.p.weight_mom > 0:
                base_idx = i - int(self.p.mom_period)
                base = float(close_array[base_idx]) if base_idx >= 0 else 0.0
                mom = close / base * 100.0 if base else 100.0
                if mom > 100.0:
                    score += self.p.weight_mom
                elif mom < 100.0:
                    score -= self.p.weight_mom
            if self.p.weight_rsi > 0:
                rsi = float(rsi_array[i])
                if rsi > 50.0:
                    score += self.p.weight_rsi
                elif rsi < 50.0:
                    score -= self.p.weight_rsi
            if self.p.weight_adx > 0:
                plus_di = float(plus_di_array[i])
                minus_di = float(minus_di_array[i])
                if plus_di > minus_di:
                    score += self.p.weight_adx
                elif plus_di < minus_di:
                    score -= self.p.weight_adx

            raw_line[i] = score
            wave = score if prev_wave is None else prev_wave + alpha * (score - prev_wave)
            wave_line[i] = wave
            prev_wave = wave


class BinaryWaveStrategy(bt.Strategy):
    params = dict(
        mode='breakdown',
        signal_bar=1,
        weight_ma=1.0,
        weight_macd=1.0,
        weight_osma=1.0,
        weight_cci=1.0,
        weight_mom=1.0,
        weight_rsi=1.0,
        weight_adx=1.0,
        ma_period=13,
        ma_type='ema',
        fast_macd=12,
        slow_macd=26,
        signal_macd=9,
        cci_period=14,
        mom_period=14,
        rsi_period=14,
        adx_period=14,
        smooth_period=5,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.wave = BinaryWaveIndicator(
            self.data,
            weight_ma=self.p.weight_ma,
            weight_macd=self.p.weight_macd,
            weight_osma=self.p.weight_osma,
            weight_cci=self.p.weight_cci,
            weight_mom=self.p.weight_mom,
            weight_rsi=self.p.weight_rsi,
            weight_adx=self.p.weight_adx,
            ma_period=self.p.ma_period,
            ma_type=self.p.ma_type,
            fast_macd=self.p.fast_macd,
            slow_macd=self.p.slow_macd,
            signal_macd=self.p.signal_macd,
            cci_period=self.p.cci_period,
            mom_period=self.p.mom_period,
            rsi_period=self.p.rsi_period,
            adx_period=self.p.adx_period,
            smooth_period=self.p.smooth_period,
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

    def _values(self):
        base = -int(self.p.signal_bar)
        return (
            float(self.wave.wave[base - 1]),
            float(self.wave.wave[base]),
            float(self.wave.wave[base + 1]),
        )

    def _signals(self):
        older, newer, latest = self._values()
        mode = str(self.p.mode).lower()
        if mode == 'twist':
            buy_signal = older >= newer and latest > newer
            sell_signal = older <= newer and latest < newer
        else:
            buy_signal = older <= 0 and newer > 0
            sell_signal = older >= 0 and newer < 0
        return buy_signal, sell_signal, newer, latest

    def next(self):
        self.bar_num += 1
        if len(self.data) < max(
            self.p.ma_period,
            self.p.slow_macd + self.p.signal_macd,
            self.p.cci_period,
            self.p.mom_period + 1,
            self.p.rsi_period,
            self.p.adx_period,
            self.p.smooth_period,
        ) + self.p.signal_bar + 5:
            return

        buy_signal, sell_signal, signal_value, latest = self._signals()

        if self.position:
            if self.position.size > 0 and sell_signal:
                self.log(f'close long & sell wave={signal_value:.2f} latest={latest:.2f}')
                self.close()
                self.sell(size=self.p.lot)
                return
            if self.position.size < 0 and buy_signal:
                self.log(f'close short & buy wave={signal_value:.2f} latest={latest:.2f}')
                self.close()
                self.buy(size=self.p.lot)
                return
        else:
            if buy_signal:
                self.log(f'buy wave={signal_value:.2f} latest={latest:.2f}')
                self.buy(size=self.p.lot)
                return
            if sell_signal:
                self.log(f'sell wave={signal_value:.2f} latest={latest:.2f}')
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
