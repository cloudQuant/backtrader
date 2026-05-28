from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines if line.strip())
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume',
    })
    if '<VOL>' in df.columns:
        df['openinterest'] = df['<VOL>']
    else:
        df['openinterest'] = 0
    df['volume'] = df['tick_volume']
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.set_index('datetime')
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df.sort_index()


def resample_ohlc(df, rule):
    agg = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'last',
    }
    out = df.resample(rule, label='right', closed='right').agg(agg).dropna()
    out['openinterest'] = out['openinterest'].fillna(0)
    return out


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


class ExpPricePositionStrategy(bt.Strategy):
    params = dict(
        symbol='XAUUSD',
        risk_percentage=3.0,
        tp_vs_sl_ratio=3.0,
        money_management_type='dynamic',
        trade_lot_size=0.1,
        close_by_opposite_signal=True,
        use_trailing_stop=True,
        trailing_fixed_pips_sl=10,
        magic=1234,
        point=0.01,
        price_digits=2,
        contract_size=100000.0,
        leverage=100.0,
        lot_min=0.01,
        lot_max=100.0,
        lot_step=0.01,
        tick_size=0.01,
        tick_value=1.0,
        spread_points=0.0,
        hist_bars=360,
        fast_period=2,
        slow_period=30,
        price_position_smma=26,
        price_position_sma=20,
    )

    def __init__(self):
        self.h1 = self.datas[0]
        self.d1 = self.datas[1]
        median = (self.h1.high + self.h1.low) / 2.0
        typical = (self.h1.high + self.h1.low + self.h1.close) / 3.0
        self.media1 = bt.indicators.SmoothedMovingAverage(median, period=self.p.price_position_smma)
        self.media2 = bt.indicators.SimpleMovingAverage(median, period=self.p.price_position_sma)
        self.mma_fast = bt.indicators.SimpleMovingAverage(typical, period=self.p.fast_period)
        self.mma_slow = bt.indicators.SmoothedMovingAverage(median, period=self.p.slow_period)
        self.order = None
        self.pending_reverse = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.bar_num = 0
        self.last_close_dt = None
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None
        self.last_position_size = 0.0

    def log(self, text):
        dt = bt.num2date(self.h1.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _ago(self, line, ago):
        return float(line[0] if ago == 0 else line[-ago])

    def _pip(self):
        pip = self.p.point * 10 if int(self.p.price_digits) in (3, 5) else self.p.point
        if self.p.symbol and self.p.symbol[0] in ('X', '#'):
            pip = self.p.point * 10
        return float(pip)

    def _round_price(self, value):
        return round(float(value), int(self.p.price_digits))

    def _round_lot(self, value):
        step = float(self.p.lot_step)
        value = max(float(self.p.lot_min), min(float(self.p.lot_max), float(value)))
        steps = round(value / step)
        digits = 0
        text = f'{step:.8f}'.rstrip('0')
        if '.' in text:
            digits = len(text.split('.')[-1])
        return round(steps * step, digits)

    def _current_profit(self):
        if not self.position or self.entry_price is None:
            return 0.0
        close = float(self.h1.close[0])
        return (close - self.entry_price) * float(self.position.size) * float(self.p.contract_size)

    def _trade_size(self, side):
        if str(self.p.money_management_type).lower() == 'fixed':
            return self._round_lot(self.p.trade_lot_size)
        final_account = min(float(self.broker.getcash()), float(self.broker.getvalue()))
        open_total = max(5, (1 if self.position else 0) + 1)
        lots = (final_account * (float(self.p.risk_percentage) / 100.0)) / (float(self.p.contract_size) / float(self.p.leverage))
        lots = lots / open_total
        return self._round_lot(lots)

    def _calculate_price_risk(self, lots):
        moneyrisk = min(float(self.broker.getcash()), float(self.broker.getvalue())) * float(self.p.risk_percentage) / 100.0
        tick_value_size = float(self.p.tick_value) * float(self.p.point) / float(self.p.tick_size)
        sltp = moneyrisk / max(lots * tick_value_size, 1e-9) + float(self.p.spread_points)
        value = self._round_price(sltp * float(self.p.point))
        return max(value, self._round_price(38 * self._pip()))

    def _sync_position_levels(self):
        if not self.position:
            self.entry_price = None
            self.stop_price = None
            self.take_profit_price = None
            self.last_position_size = 0.0
            return
        if self.entry_price is not None and self.last_position_size == float(self.position.size):
            return
        self.entry_price = float(self.position.price)
        self.last_position_size = float(self.position.size)
        lots = abs(float(self.position.size))
        sltp = self._calculate_price_risk(max(lots, float(self.p.lot_min)))
        if self.position.size > 0:
            self.stop_price = self._round_price(self.entry_price - sltp)
            self.take_profit_price = self._round_price(self.entry_price + sltp * float(self.p.tp_vs_sl_ratio))
        else:
            self.stop_price = self._round_price(self.entry_price + sltp)
            self.take_profit_price = self._round_price(self.entry_price - sltp * float(self.p.tp_vs_sl_ratio))

    def _step_up_down(self):
        pr = 9
        available = min(int(self.p.hist_bars), len(self.h1) - 1)
        if available < pr + 1:
            return 0
        ml_hi = 0
        ml_lo = 0
        ma_hi = self._ago(self.mma_fast, 1)
        ma_lo = self._ago(self.mma_fast, 1)
        divma520 = 0.0
        divma521 = 0.0
        for i in range(pr, -1, -1):
            value = self._ago(self.mma_fast, i)
            if value > ma_hi:
                ma_hi = value
                ml_hi = i
            if value < ma_lo:
                ma_lo = value
                ml_lo = i
            divma520 = self._ago(self.mma_fast, i) - self._ago(self.mma_slow, i)
            divma521 = self._ago(self.mma_fast, i + 1) - self._ago(self.mma_slow, i + 1)
        ups = False
        dns = False
        pre = available
        for j in range(pre - 1, -1, -1):
            fast_j = self._ago(self.mma_fast, j)
            if (ml_hi > ml_lo) and (fast_j > ma_lo):
                ups = True
                dns = False
            if (ml_hi > ml_lo) and (divma520 < divma521):
                dns = True
                ups = False
            if (ml_hi < ml_lo) and (fast_j < ma_hi):
                dns = True
                ups = False
            if (ml_hi < ml_lo) and (divma520 > divma521):
                ups = True
                dns = False
        if ups:
            return 1
        if dns:
            return -1
        return 0

    def _price_position(self):
        available = min(int(self.p.hist_bars), len(self.h1) - 1)
        if available < 5:
            return 0
        direction = None
        for ago in range(0, available):
            signal = (self._ago(self.media1, ago) + self._ago(self.media2, ago)) / 2.0
            open_ = self._ago(self.h1.open, ago)
            close_ = self._ago(self.h1.close, ago)
            high_ = self._ago(self.h1.high, ago)
            low_ = self._ago(self.h1.low, ago)
            if open_ <= signal and close_ > signal:
                direction = low_
                break
            if open_ >= signal and close_ < signal:
                direction = high_
                break
        if direction is None:
            return 0
        close0 = float(self.h1.close[0])
        if close0 > direction:
            return 1
        if close0 < direction:
            return -1
        return 0

    def _trade_fx(self):
        if len(self.h1) < 3 or len(self.d1) < 2:
            return 0
        ma_open0 = self._ago(self.mma_fast, 0)
        ma_open1 = self._ago(self.mma_fast, 1)
        dclos1 = self._ago(self.d1.close, 1)
        hclos1 = self._ago(self.h1.close, 1)
        hclos0 = self._ago(self.h1.close, 0)
        pwr1 = round(((hclos1 - dclos1) / dclos1) * 100.0, 2) if dclos1 else 0.0
        pwr0 = round(((hclos0 - dclos1) / dclos1) * 100.0, 2) if dclos1 else 0.0
        h1_open = self._ago(self.h1.open, 0)
        h1_close = self._ago(self.h1.close, 0)
        h1_high = self._ago(self.h1.high, 0)
        h1_low = self._ago(self.h1.low, 0)
        stepud = self._step_up_down()
        prcpos = self._price_position()
        if prcpos == 1 and stepud == 1 and h1_close > h1_open and h1_low < ma_open0 and ma_open0 > ma_open1 and pwr0 > pwr1:
            return 1
        if prcpos == -1 and stepud == -1 and h1_close < h1_open and h1_high > ma_open0 and ma_open0 < ma_open1 and pwr0 < pwr1:
            return -1
        return 0

    def _enter(self, direction):
        lots = self._trade_size(direction)
        if lots <= 0:
            return
        self.signal_count += 1
        if direction > 0:
            self.log(f'buy signal lots={lots:.2f}')
            self.order = self.buy(size=lots)
        else:
            self.log(f'sell signal lots={lots:.2f}')
            self.order = self.sell(size=lots)

    def _manage_trailing(self):
        if not self.position or not self.p.use_trailing_stop:
            return False
        vts = self._round_price(float(self.p.trailing_fixed_pips_sl) * self._pip())
        vtp = self._round_price(vts * float(self.p.tp_vs_sl_ratio))
        close = float(self.h1.close[0])
        if self.position.size > 0:
            if (close - self.entry_price) > vts and (self.take_profit_price - close) > vts:
                new_sl = self._round_price(close - vts)
                new_tp = max(self.take_profit_price, self._round_price(close + vtp))
                if self.stop_price is None or new_sl > self.stop_price:
                    self.stop_price = new_sl
                    self.take_profit_price = new_tp
            return False
        if (self.entry_price - close) > vts and (close - self.take_profit_price) > vts:
            new_sl = self._round_price(close + vts)
            new_tp = min(self.take_profit_price, self._round_price(close - vtp))
            if self.stop_price is None or new_sl < self.stop_price:
                self.stop_price = new_sl
                self.take_profit_price = new_tp
        return False

    def _manage_position(self):
        if not self.position:
            return False
        high = float(self.h1.high[0])
        low = float(self.h1.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.log(f'close long stop={self.stop_price:.2f}')
                self.order = self.close()
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.log(f'close long tp={self.take_profit_price:.2f}')
                self.order = self.close()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.log(f'close short stop={self.stop_price:.2f}')
                self.order = self.close()
                return True
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.log(f'close short tp={self.take_profit_price:.2f}')
                self.order = self.close()
                return True
        if self.p.use_trailing_stop:
            self._manage_trailing()
        else:
            stepud = self._step_up_down()
            cur_profit = self._current_profit()
            if self.position.size > 0 and stepud == -1 and cur_profit > 0:
                self.log('close long on profitable opposite StepUpDown')
                self.order = self.close()
                return True
            if self.position.size < 0 and stepud == 1 and cur_profit > 0:
                self.log('close short on profitable opposite StepUpDown')
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.h1) < max(int(self.p.hist_bars // 4), 40) or len(self.d1) < 2:
            return
        if self.order is not None:
            return
        self._sync_position_levels()
        if self._manage_position():
            return
        signal = self._trade_fx()
        current_dt = bt.num2date(self.h1.datetime[0])
        if self.position:
            if signal > 0 and self.position.size < 0 and self.p.close_by_opposite_signal:
                self.pending_reverse = 1
                self.log('close short by opposite signal')
                self.order = self.close()
                return
            if signal < 0 and self.position.size > 0 and self.p.close_by_opposite_signal:
                self.pending_reverse = -1
                self.log('close long by opposite signal')
                self.order = self.close()
                return
            return
        if self.pending_reverse:
            direction = self.pending_reverse
            self.pending_reverse = 0
            self._enter(direction)
            return
        if self.last_close_dt is not None and self.last_close_dt == current_dt:
            return
        if signal > 0:
            self._enter(1)
        elif signal < 0:
            self._enter(-1)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if self.position:
                self._sync_position_levels()
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
            else:
                self.last_close_dt = bt.num2date(self.h1.datetime[0])
                self.entry_price = None
                self.stop_price = None
                self.take_profit_price = None
                self.last_position_size = 0.0
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
