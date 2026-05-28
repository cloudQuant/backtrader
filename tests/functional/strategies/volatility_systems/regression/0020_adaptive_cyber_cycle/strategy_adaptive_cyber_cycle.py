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
import backtrader.feeds as btfeeds
import pandas as pd

MODE_ADAPTIVE_CYBER_CYCLE = 'adaptive_cyber_cycle'
MODE_ADAPTIVE_CG_OSCILLATOR = 'adaptive_cg_oscillator'
MODE_ADAPTIVE_RVI = 'adaptive_rvi'


class RingIndex:
    def __init__(self, size):
        self.size = size
        self.count = 1
        self.map = [0] * size

    def rotate(self):
        self.count -= 1
        if self.count < 0:
            self.count = self.size - 1
        for idx in range(self.size):
            numb = idx + self.count
            if numb > self.size - 1:
                numb -= self.size
            self.map[idx] = numb


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


class AdaptiveIndicatorFeed(btfeeds.PandasData):
    lines = ('main_line', 'trigger_line')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('main_line', 6), ('trigger_line', 7),
    )


def build_resampled_frame(df, indicator_minutes):
    rule = f'{int(indicator_minutes)}min'
    signal_df = df.resample(rule, label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'last',
    })
    signal_df = signal_df.dropna(subset=['open', 'high', 'low', 'close']).copy()
    signal_df['openinterest'] = signal_df['openinterest'].fillna(0)
    return signal_df


def compute_cycle_period(highs, lows, alpha):
    k0 = (1.0 - 0.5 * alpha) ** 2
    k1 = 2.0
    k2 = k1 * (1.0 - alpha)
    k3 = (1.0 - alpha) ** 2
    f0 = 0.0962
    f1 = 0.5769
    f2 = 0.5
    f3 = 0.08
    median = 5
    median2 = median // 2
    med2 = median % 2 == 0

    count1 = RingIndex(7)
    count2 = RingIndex(median)
    smooth = [0.0] * 7
    cycle = [0.0] * 7
    q1 = [0.0] * 7
    i1 = [0.0] * 7
    price = [0.0] * 7
    delta_phase = [0.0] * median

    inst_period = 1.0
    cperiod = 1.0
    result = []

    for bar in range(len(highs)):
        bar0 = count1.map[0]
        bar1 = count1.map[1]
        bar2 = count1.map[2]
        bar3 = count1.map[3]
        bar4 = count1.map[4]
        bar6 = count1.map[6]

        price[bar0] = (float(highs.iloc[bar]) + float(lows.iloc[bar])) / 2.0
        smooth[bar0] = (price[bar0] + 2.0 * price[bar1] + 2.0 * price[bar2] + price[bar3]) / 6.0

        if bar < 6:
            cycle[bar0] = (price[bar0] - 2.0 * price[bar1] + price[bar2]) / 4.0
        else:
            cycle[bar0] = k0 * (smooth[bar0] - k1 * smooth[bar1] + smooth[bar2]) + k2 * cycle[bar1] - k3 * cycle[bar2]

        q1[bar0] = (f0 * cycle[bar0] + f1 * cycle[bar2] - f1 * cycle[bar4] - f0 * cycle[bar6]) * (f2 + f3 * inst_period)
        i1[bar0] = cycle[bar3]

        if q1[bar0] and q1[bar1]:
            denom = 1.0 + i1[bar0] * i1[bar1] / (q1[bar0] * q1[bar1])
            delta_phase[count2.map[0]] = (i1[bar0] / q1[bar0] - i1[bar1] / q1[bar1]) / denom

        phase_idx = count2.map[0]
        delta_phase[phase_idx] = max(0.1, delta_phase[phase_idx])
        delta_phase[phase_idx] = min(1.1, delta_phase[phase_idx])

        median_values = sorted(delta_phase)
        if med2:
            median_delta = (median_values[median2] + median_values[median2 + 1]) / 2.0
        else:
            median_delta = median_values[median2]

        dc = 15.0 if not median_delta else 6.28318 / median_delta + 0.5
        inst_period = 0.67 * inst_period + 0.33 * dc
        cperiod = 0.85 * cperiod + 0.15 * inst_period
        result.append(cperiod)

        if bar < len(highs) - 1:
            count1.rotate()
            count2.rotate()

    return pd.Series(result, index=highs.index, dtype='float64')


def compute_adaptive_cyber_cycle(df, cycle_period):
    prices = [0.0] * 7
    smooth = [0.0] * 7
    cycle = [0.0] * 7
    main_line = []
    trigger_line = []

    for idx in range(len(df)):
        price_value = (float(df.iloc[idx]['high']) + float(df.iloc[idx]['low'])) / 2.0
        prices = [price_value] + prices[:-1]
        smooth_value = (prices[0] + 2.0 * prices[1] + 2.0 * prices[2] + prices[3]) / 6.0
        smooth = [smooth_value] + smooth[:-1]

        if idx >= 6:
            alpha1 = 2.0 / (float(cycle_period.iloc[idx]) + 1.0)
            k0 = (1.0 - 0.5 * alpha1) ** 2
            k2 = 2.0 * (1.0 - alpha1)
            k3 = (1.0 - alpha1) ** 2
            cycle_value = k0 * (smooth[0] - 2.0 * smooth[1] + smooth[2]) + k2 * cycle[0] - k3 * cycle[1]
        else:
            cycle_value = (prices[0] - 2.0 * prices[1] + prices[2]) / 4.0

        trigger_value = cycle[0]
        cycle = [cycle_value] + cycle[:-1]
        main_line.append(cycle_value)
        trigger_line.append(trigger_value)

    return pd.Series(main_line, index=df.index, dtype='float64'), pd.Series(trigger_line, index=df.index, dtype='float64')


def compute_adaptive_cg_oscillator(df, cycle_period):
    price_history = []
    prev_main = 0.0
    main_line = []
    trigger_line = []

    for idx in range(len(df)):
        price_history.insert(0, (float(df.iloc[idx]['high']) + float(df.iloc[idx]['low'])) / 2.0)
        intperiod = int(math.floor(float(cycle_period.iloc[idx]) / 2.0))
        if idx < intperiod:
            intperiod = idx

        numerator = 0.0
        denominator = 0.0
        for count in range(intperiod):
            price_value = price_history[count]
            numerator += (1.0 + count) * price_value
            denominator += price_value

        if denominator != 0.0:
            main_value = -numerator / denominator + (intperiod + 1.0) / 2.0
        else:
            main_value = math.nan

        main_line.append(main_value)
        trigger_line.append(prev_main)
        prev_main = main_value

    return pd.Series(main_line, index=df.index, dtype='float64'), pd.Series(trigger_line, index=df.index, dtype='float64')


def compute_adaptive_rvi(df, cycle_period):
    open_history = []
    close_history = []
    high_history = []
    low_history = []
    cp_history = []
    value1_history = []
    value2_history = []
    prev_main = 0.0
    main_line = []
    trigger_line = []

    for idx in range(len(df)):
        open_history.insert(0, float(df.iloc[idx]['open']))
        close_history.insert(0, float(df.iloc[idx]['close']))
        high_history.insert(0, float(df.iloc[idx]['high']))
        low_history.insert(0, float(df.iloc[idx]['low']))
        cp_history.insert(0, float(cycle_period.iloc[idx]))

        cp0 = cp_history[0] if len(cp_history) > 0 else 0.0
        cp1 = cp_history[1] if len(cp_history) > 1 else 0.0
        cp2 = cp_history[2] if len(cp_history) > 2 else 0.0
        cp3 = cp_history[3] if len(cp_history) > 3 else 0.0
        length = int(math.floor((4.0 * cp0 + 3.0 * cp1 + 2.0 * cp2 + cp3) / 20.0))
        if idx < length:
            length = idx

        def diff(values1, values2, offset):
            return values1[offset] - values2[offset]

        if len(close_history) >= 4 and len(open_history) >= 4:
            value1 = (
                diff(close_history, open_history, 0)
                + 2.0 * diff(close_history, open_history, 1)
                + 2.0 * diff(close_history, open_history, 2)
                + diff(close_history, open_history, 3)
            ) / 6.0
            value2 = (
                diff(high_history, low_history, 0)
                + 2.0 * diff(high_history, low_history, 1)
                + 2.0 * diff(high_history, low_history, 2)
                + diff(high_history, low_history, 3)
            ) / 6.0
        else:
            value1 = 0.0
            value2 = 0.0

        value1_history.insert(0, value1)
        value2_history.insert(0, value2)

        numerator = sum(value1_history[:length])
        denominator = sum(value2_history[:length])
        if denominator != 0.0:
            main_value = numerator / denominator
        else:
            main_value = math.nan

        main_line.append(main_value)
        trigger_line.append(prev_main)
        prev_main = main_value

    return pd.Series(main_line, index=df.index, dtype='float64'), pd.Series(trigger_line, index=df.index, dtype='float64')


def normalize_mode(mode):
    normalized = str(mode).strip().lower().replace(' ', '_')
    aliases = {
        'adaptivecybercycle': MODE_ADAPTIVE_CYBER_CYCLE,
        'adaptive_cyber_cycle': MODE_ADAPTIVE_CYBER_CYCLE,
        'adaptivecgoscillator': MODE_ADAPTIVE_CG_OSCILLATOR,
        'adaptive_cg_oscillator': MODE_ADAPTIVE_CG_OSCILLATOR,
        'adaptivervi': MODE_ADAPTIVE_RVI,
        'adaptive_rvi': MODE_ADAPTIVE_RVI,
    }
    if normalized not in aliases:
        raise ValueError(f'Unsupported mode: {mode}')
    return aliases[normalized]


def build_adaptive_signal_frame(df, indicator_minutes, mode, alpha):
    signal_df = build_resampled_frame(df, indicator_minutes)
    cycle_period = compute_cycle_period(signal_df['high'], signal_df['low'], alpha)
    normalized_mode = normalize_mode(mode)

    if normalized_mode == MODE_ADAPTIVE_CYBER_CYCLE:
        main_line, trigger_line = compute_adaptive_cyber_cycle(signal_df, cycle_period)
    elif normalized_mode == MODE_ADAPTIVE_CG_OSCILLATOR:
        main_line, trigger_line = compute_adaptive_cg_oscillator(signal_df, cycle_period)
    else:
        main_line, trigger_line = compute_adaptive_rvi(signal_df, cycle_period)

    signal_df = signal_df.copy()
    signal_df['main_line'] = main_line
    signal_df['trigger_line'] = trigger_line
    return signal_df


class AdaptiveCyberCycleStrategy(bt.Strategy):
    params = dict(
        mode=MODE_ADAPTIVE_CYBER_CYCLE,
        alpha=0.07,
        signal_bar=1,
        stop_loss_points=1000,
        take_profit_points=2000,
        mm=-0.1,
        point=0.01,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        indicator_minutes=240,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.signal_data = self.datas[1]
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
        dt = bt.num2date(self.base.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _line_value(self, line, ago):
        return float(line[-ago]) if ago else float(line[0])

    def _position_size(self, price):
        if self.p.mm < 0:
            return abs(self.p.mm)
        if price <= 0:
            return 0.0
        cash = self.broker.getcash()
        return round((cash * self.p.mm) / price, 4)

    def _check_exit_levels(self):
        if not self.position:
            return False
        close_price = float(self.base.close[0])
        point_value = float(self.p.point)
        stop_distance = self.p.stop_loss_points * point_value if self.p.stop_loss_points > 0 else None
        take_distance = self.p.take_profit_points * point_value if self.p.take_profit_points > 0 else None
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

    def _is_finite(self, value):
        return not math.isnan(value) and math.isfinite(value)

    def next(self):
        self.bar_num += 1
        if len(self.base) < 2:
            return

        if self._check_exit_levels():
            return

        signal_bar = max(int(self.p.signal_bar), 1)
        if len(self.signal_data) <= signal_bar:
            return

        current_signal_len = len(self.signal_data)
        if current_signal_len == self._last_signal_len:
            return
        self._last_signal_len = current_signal_len

        recent_ago = signal_bar - 1
        older_ago = signal_bar
        older_main = self._line_value(self.signal_data.main_line, older_ago)
        older_trigger = self._line_value(self.signal_data.trigger_line, older_ago)
        recent_main = self._line_value(self.signal_data.main_line, recent_ago)
        recent_trigger = self._line_value(self.signal_data.trigger_line, recent_ago)

        if not all(self._is_finite(value) for value in [older_main, older_trigger, recent_main, recent_trigger]):
            return

        close_price = float(self.base.close[0])
        size = self._position_size(close_price)
        if size <= 0:
            return

        buy_signal = older_main > older_trigger and recent_main <= recent_trigger
        sell_signal = older_main < older_trigger and recent_main >= recent_trigger

        if buy_signal:
            self.signal_count += 1
            self.log(f'buy signal main={older_main:.5f}->{recent_main:.5f} trigger={older_trigger:.5f}->{recent_trigger:.5f}')
            if self.position.size < 0 and self.p.sell_pos_close:
                self.close()
            if self.position.size <= 0 and self.p.buy_pos_open:
                self.buy(size=size)
            return

        if sell_signal:
            self.signal_count += 1
            self.log(f'sell signal main={older_main:.5f}->{recent_main:.5f} trigger={older_trigger:.5f}->{recent_trigger:.5f}')
            if self.position.size > 0 and self.p.buy_pos_close:
                self.close()
            if self.position.size >= 0 and self.p.sell_pos_open:
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
