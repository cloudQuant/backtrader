from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

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
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
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


class Ma2CciStrategy(bt.Strategy):
    params = dict(
        fast_ma_period=4,
        slow_ma_period=8,
        cci_period=4,
        atr_period=4,
        lots=0.1,
        max_risk=0.02,
        decrease_factor=3.0,
        point=0.01,
    )

    def __init__(self):
        self.fast_ma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.fast_ma_period)
        self.slow_ma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.slow_ma_period)
        self.cci = bt.indicators.CommodityChannelIndex(self.data, period=self.p.cci_period)
        self.atr = bt.indicators.AverageTrueRange(self.data, period=self.p.atr_period)

        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

        self.order = None
        self.pending_entry_side = None
        self.pending_stop_distance = None
        self.stop_price = None
        self._position_was_open = False
        self._closed_trade_pnls = []

        self.addminperiod(max(self.p.fast_ma_period, self.p.slow_ma_period, self.p.cci_period, self.p.atr_period) + 3)

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _normalize_lot(self, lot):
        return max(round(float(lot), 2), 0.01)

    def _loss_streak(self):
        losses = 0
        for pnl in reversed(self._closed_trade_pnls):
            if pnl > 0:
                break
            if pnl < 0:
                losses += 1
        return losses

    def _current_lot(self):
        if float(self.p.lots) == 0:
            lot = float(self.broker.getcash()) * float(self.p.max_risk) / 1000.0
        else:
            lot = float(self.p.lots)

        if float(self.p.decrease_factor) > 0:
            losses = self._loss_streak()
            if losses > 1:
                lot = lot - lot * losses / float(self.p.decrease_factor)

        return self._normalize_lot(lot)

    def _queue_entry(self, side):
        self.pending_entry_side = side
        atr_prev = float(self.atr[-1]) if math.isfinite(float(self.atr[-1])) else 0.0
        self.pending_stop_distance = atr_prev if atr_prev > 0 else None

    def _clear_exit_levels(self):
        self.stop_price = None
        self.pending_stop_distance = None

    def _check_stop(self):
        if not self.position or self.stop_price is None or self.order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0 and low <= self.stop_price:
            self.log(f'close long by atr stop={self.stop_price:.5f}')
            self.order = self.close()
            return True
        if self.position.size < 0 and high >= self.stop_price:
            self.log(f'close short by atr stop={self.stop_price:.5f}')
            self.order = self.close()
            return True
        return False

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return

        if not self.position and self.pending_entry_side is not None:
            lot = self._current_lot()
            if self.pending_entry_side == 'long':
                self.log(f'pending buy lot={lot:.2f}')
                self.order = self.buy(size=lot)
            else:
                self.log(f'pending sell lot={lot:.2f}')
                self.order = self.sell(size=lot)
            self.pending_entry_side = None
            return

        if self._check_stop():
            return

        fma1 = float(self.fast_ma[-1])
        fma2 = float(self.fast_ma[-2])
        sma1 = float(self.slow_ma[-1])
        sma2 = float(self.slow_ma[-2])
        cci1 = float(self.cci[-1])
        cci2 = float(self.cci[-2])

        close_buy = fma1 < sma1 and fma2 >= sma2
        close_sell = fma1 > sma1 and fma2 <= sma2
        open_buy = (fma1 > sma1 and fma2 <= sma2) and (cci1 > 0 and cci2 <= 0)
        open_sell = (fma1 < sma1 and fma2 >= sma2) and (cci1 < 0 and cci2 >= 0)
        if open_buy or open_sell:
            self.signal_count += 1

        if self.position.size > 0 and close_buy:
            self.log(f'close buy by ma cross fma1={fma1:.5f} sma1={sma1:.5f}')
            self.order = self.close()
            return

        if self.position.size < 0 and close_sell:
            self.log(f'close sell by ma cross fma1={fma1:.5f} sma1={sma1:.5f}')
            self.order = self.close()
            return

        if self.position:
            return

        if open_buy:
            self.log(f'buy signal fma1={fma1:.5f} sma1={sma1:.5f} cci1={cci1:.5f}')
            self._queue_entry('long')
            lot = self._current_lot()
            self.order = self.buy(size=lot)
            self.pending_entry_side = None
            return

        if open_sell:
            self.log(f'sell signal fma1={fma1:.5f} sma1={sma1:.5f} cci1={cci1:.5f}')
            self._queue_entry('short')
            lot = self._current_lot()
            self.order = self.sell(size=lot)
            self.pending_entry_side = None
            return

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if self.position:
                stop_distance = self.pending_stop_distance or 0.0
                if stop_distance > 0:
                    if self.position.size > 0:
                        self.stop_price = float(order.executed.price) - stop_distance
                    else:
                        self.stop_price = float(order.executed.price) + stop_distance
            else:
                self._clear_exit_levels()
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'order failed status={order.getstatusname()}')
            if not self.position:
                self.pending_entry_side = None
        self.order = None

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
        self._closed_trade_pnls.append(float(trade.pnlcomm))
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False
        self._clear_exit_levels()
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
