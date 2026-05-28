from __future__ import absolute_import, division, print_function, unicode_literals

import io

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


class TrendCaptureStrategy(bt.Strategy):
    params = dict(
        lots=0.1,
        maximum_risk=0.05,
        stop_loss=1800,
        take_profit=500,
        sar_step=0.02,
        sar_max=0.2,
        adx_period=14,
        adx_level=20,
        shift=1,
        break_even=50,
        point=0.01,
    )

    def __init__(self):
        self.sar = bt.indicators.ParabolicSAR(self.data, af=self.p.sar_step, afmax=self.p.sar_max)
        self.adx = bt.indicators.AverageDirectionalMovementIndex(self.data, period=self.p.adx_period)

        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

        self.order = None
        self.stop_price = None
        self.take_price = None
        self._position_was_open = False
        self._current_trade_direction = None
        self._closed_trade_meta = []

        self.addminperiod(max(self.p.adx_period, 5) + int(self.p.shift) + 2)

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _normalize_lot(self, lot):
        return max(round(float(lot), 2), 0.01)

    def _current_lot(self):
        if float(self.p.lots) == 0:
            lot = float(self.broker.getcash()) * float(self.p.maximum_risk) / 1000.0
        else:
            lot = float(self.p.lots)
        return self._normalize_lot(lot)

    def _allowed_direction(self):
        if not self._closed_trade_meta:
            return 0
        last = self._closed_trade_meta[-1]
        if last['pnl'] > 0:
            return 1 if last['direction'] == 'buy' else -1
        return -1 if last['direction'] == 'buy' else 1

    def _apply_breakeven(self):
        if not self.position or int(self.p.break_even) <= 0:
            return
        op = float(self.position.price)
        if self.position.size > 0:
            if self.stop_price is None or self.stop_price < op:
                trigger = float(self.data.close[0]) - float(self.p.point) * int(self.p.break_even)
                if trigger >= op:
                    self.stop_price = op
        else:
            if self.stop_price is None or self.stop_price > op:
                trigger = float(self.data.close[0]) + float(self.p.point) * int(self.p.break_even)
                if trigger <= op:
                    self.stop_price = op

    def _check_exit_levels(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.log(f'close long by stop={self.stop_price:.5f}')
                self.order = self.close()
                return True
            if self.take_price is not None and high >= self.take_price:
                self.log(f'close long by take={self.take_price:.5f}')
                self.order = self.close()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.log(f'close short by stop={self.stop_price:.5f}')
                self.order = self.close()
                return True
            if self.take_price is not None and low <= self.take_price:
                self.log(f'close short by take={self.take_price:.5f}')
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return

        self._apply_breakeven()
        if self._check_exit_levels():
            return

        idx = -int(self.p.shift)
        sar_value = float(self.sar[idx])
        adx_value = float(self.adx[idx])
        close_value = float(self.data.close[idx])

        open_buy = close_value > sar_value and adx_value < float(self.p.adx_level)
        open_sell = close_value < sar_value and adx_value < float(self.p.adx_level)
        if (open_buy and not open_sell) or (open_sell and not open_buy):
            self.signal_count += 1
        allowed_dir = self._allowed_direction()

        if self.position:
            return

        lot = self._current_lot()
        if open_buy and not open_sell and allowed_dir != -1:
            ask = float(self.data.close[0])
            self.stop_price = ask - float(self.p.point) * float(self.p.stop_loss)
            self.take_price = ask + float(self.p.point) * float(self.p.take_profit)
            self.log(f'buy signal sar={sar_value:.5f} close={close_value:.5f} adx={adx_value:.5f} lot={lot:.2f}')
            self.order = self.buy(size=lot)
            return

        if open_sell and not open_buy and allowed_dir != 1:
            bid = float(self.data.close[0])
            self.stop_price = bid + float(self.p.point) * float(self.p.stop_loss)
            self.take_price = bid - float(self.p.point) * float(self.p.take_profit)
            self.log(f'sell signal sar={sar_value:.5f} close={close_value:.5f} adx={adx_value:.5f} lot={lot:.2f}')
            self.order = self.sell(size=lot)
            return

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'order failed status={order.getstatusname()}')
            if not self.position:
                self.stop_price = None
                self.take_price = None
        self.order = None

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            if trade.size > 0:
                self.buy_count += 1
                self._current_trade_direction = 'buy'
            elif trade.size < 0:
                self.sell_count += 1
                self._current_trade_direction = 'sell'
            self._position_was_open = True
            return
        if not trade.isclosed:
            return
        self.trade_count += 1
        direction = self._current_trade_direction or ('buy' if trade.pnlcomm >= 0 else 'sell')
        self._closed_trade_meta.append({'direction': direction, 'pnl': float(trade.pnlcomm)})
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False
        self._current_trade_direction = None
        self.stop_price = None
        self.take_price = None
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
