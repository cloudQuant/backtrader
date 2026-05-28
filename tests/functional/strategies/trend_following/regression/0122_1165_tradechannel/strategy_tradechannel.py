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


class TradeChannelStrategy(bt.Strategy):
    params = dict(
        lots=0.1,
        max_risk=0.02,
        decrease_factor=3.0,
        atr_period=4,
        channel_period=20,
        trailing=300,
        point=0.01,
    )

    def __init__(self):
        self.atr = bt.indicators.AverageTrueRange(self.data, period=self.p.atr_period)

        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

        self.order = None
        self.stop_price = None
        self._position_was_open = False
        self._closed_trade_pnls = []

        self.addminperiod(max(self.p.atr_period, self.p.channel_period) + 3)

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

    def _channel_values(self):
        r = int(self.p.channel_period)
        highs_curr = [float(self.data.high[-i]) for i in range(1, r + 1)]
        highs_prev = [float(self.data.high[-i]) for i in range(2, r + 2)]
        lows_curr = [float(self.data.low[-i]) for i in range(1, r + 1)]
        lows_prev = [float(self.data.low[-i]) for i in range(2, r + 2)]

        resist = max(highs_curr)
        resist_prev = max(highs_prev)
        support = min(lows_curr)
        support_prev = min(lows_prev)
        close_prev = float(self.data.close[-1])
        high_prev = float(self.data.high[-1])
        low_prev = float(self.data.low[-1])
        pivot = (resist + support + close_prev) / 3.0
        return resist, resist_prev, support, support_prev, pivot, close_prev, high_prev, low_prev

    def _is_open_buy(self, resist, resist_prev, pivot, close_prev, high_prev):
        if high_prev >= resist and resist == resist_prev:
            return True
        if close_prev < resist and resist == resist_prev and close_prev > pivot:
            return True
        return False

    def _is_open_sell(self, support, support_prev, pivot, close_prev, low_prev):
        if low_prev <= support and support == support_prev:
            return True
        if close_prev > support and support == support_prev and close_prev < pivot:
            return True
        return False

    def _is_close_buy(self, resist, resist_prev, high_prev):
        return high_prev >= resist and resist == resist_prev

    def _is_close_sell(self, support, support_prev, low_prev):
        return low_prev <= support and support == support_prev

    def _check_stop(self):
        if not self.position or self.stop_price is None or self.order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0 and low <= self.stop_price:
            self.log(f'close long by stop={self.stop_price:.5f}')
            self.order = self.close()
            return True
        if self.position.size < 0 and high >= self.stop_price:
            self.log(f'close short by stop={self.stop_price:.5f}')
            self.order = self.close()
            return True
        return False

    def _apply_trailing(self):
        if not self.position or int(self.p.trailing) <= 0:
            return
        if self.position.size > 0:
            new_stop = float(self.data.close[0]) - float(self.p.point) * int(self.p.trailing)
            if new_stop >= float(self.position.price):
                if self.stop_price is None or new_stop > self.stop_price:
                    self.stop_price = new_stop
        else:
            new_stop = float(self.data.close[0]) + float(self.p.point) * int(self.p.trailing)
            if new_stop <= float(self.position.price):
                if self.stop_price is None or new_stop < self.stop_price:
                    self.stop_price = new_stop

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return

        self._apply_trailing()
        if self._check_stop():
            return

        resist, resist_prev, support, support_prev, pivot, close_prev, high_prev, low_prev = self._channel_values()
        atr_prev = float(self.atr[-1])

        if self.position.size > 0 and self._is_close_buy(resist, resist_prev, high_prev):
            self.log(f'close buy by channel resist={resist:.5f} high_prev={high_prev:.5f}')
            self.order = self.close()
            return

        if self.position.size < 0 and self._is_close_sell(support, support_prev, low_prev):
            self.log(f'close sell by channel support={support:.5f} low_prev={low_prev:.5f}')
            self.order = self.close()
            return

        if self.position:
            return

        open_buy = self._is_open_buy(resist, resist_prev, pivot, close_prev, high_prev)
        open_sell = self._is_open_sell(support, support_prev, pivot, close_prev, low_prev)
        if (open_buy and not open_sell) or (open_sell and not open_buy):
            self.signal_count += 1
        lot = self._current_lot()

        if open_buy and not open_sell:
            self.stop_price = support - atr_prev
            self.log(f'buy signal resist={resist:.5f} support={support:.5f} pivot={pivot:.5f} lot={lot:.2f}')
            self.order = self.buy(size=lot)
            return

        if open_sell and not open_buy:
            self.stop_price = resist + atr_prev
            self.log(f'sell signal resist={resist:.5f} support={support:.5f} pivot={pivot:.5f} lot={lot:.2f}')
            self.order = self.sell(size=lot)
            return

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'order failed status={order.getstatusname()}')
            if not self.position:
                self.stop_price = None
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
        self.stop_price = None
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
