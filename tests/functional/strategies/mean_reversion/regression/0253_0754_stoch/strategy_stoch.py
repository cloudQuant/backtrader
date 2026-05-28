from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
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
        '<TICKVOL>': 'tick_volume',
        '<VOL>': 'real_volume',
    })
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
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class StochStrategy(bt.Strategy):
    params = dict(
        take_profit=57,
        lots=0.1,
        stop_loss=7,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
    )

    def __init__(self):
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0

        self.pending_buy = None
        self.pending_sell = None
        self.position_side = None
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None
        self.last_day = None

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _clear_pending(self):
        self.pending_buy = None
        self.pending_sell = None

    def _delete_all_positions_and_orders(self):
        if self.position:
            self.close()
            self.completed_order_count += 1
            self.position_side = None
            self.entry_price = None
            self.stop_price = None
            self.take_profit_price = None
        self._clear_pending()

    def _place_daily_limits(self):
        prev_high = float(self.data.high[-1])
        prev_low = float(self.data.low[-1])
        prev_close = float(self.data.close[-1])
        unit = self._unit()
        h4 = (((prev_high - prev_low) * 1.1) / 2.0) + prev_close
        l4 = prev_close - (((prev_high - prev_low) * 1.1) / 2.0)
        self.pending_sell = {
            'entry': round(h4, int(self.p.price_digits)),
            'stop': round(h4 + float(self.p.stop_loss) * unit, int(self.p.price_digits)),
            'take': round(h4 - float(self.p.take_profit) * unit, int(self.p.price_digits)),
            'tag': 'H4',
        }
        self.pending_buy = {
            'entry': round(l4, int(self.p.price_digits)),
            'stop': round(l4 - float(self.p.stop_loss) * unit, int(self.p.price_digits)),
            'take': round(l4 + float(self.p.take_profit) * unit, int(self.p.price_digits)),
            'tag': 'L4',
        }
        self.signal_count += 2
        self.log(f'place limits buy={self.pending_buy["entry"]:.2f} sell={self.pending_sell["entry"]:.2f}')

    def _trigger_pending(self):
        if self.position:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.pending_sell and high >= self.pending_sell['entry']:
            self.sell(size=self.p.lots)
            self.position_side = 'sell'
            self.entry_price = self.pending_sell['entry']
            self.stop_price = self.pending_sell['stop']
            self.take_profit_price = self.pending_sell['take']
            self.completed_order_count += 1
            self.sell_count += 1
            self.pending_sell = None
            self.pending_buy = None
            return
        if self.pending_buy and low <= self.pending_buy['entry']:
            self.buy(size=self.p.lots)
            self.position_side = 'buy'
            self.entry_price = self.pending_buy['entry']
            self.stop_price = self.pending_buy['stop']
            self.take_profit_price = self.pending_buy['take']
            self.completed_order_count += 1
            self.buy_count += 1
            self.pending_buy = None
            self.pending_sell = None

    def _manage_position(self):
        if not self.position_side:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position_side == 'buy':
            if low <= self.stop_price or high >= self.take_profit_price:
                self.close()
                self.completed_order_count += 1
                self.position_side = None
                self.entry_price = None
                self.stop_price = None
                self.take_profit_price = None
        else:
            if high >= self.stop_price or low <= self.take_profit_price:
                self.close()
                self.completed_order_count += 1
                self.position_side = None
                self.entry_price = None
                self.stop_price = None
                self.take_profit_price = None

    def next(self):
        self.bar_num += 1
        dt = bt.num2date(self.data.datetime[0])
        if len(self) < 2:
            return
        if dt.hour == 23 and dt.minute == 59:
            self._delete_all_positions_and_orders()
            return
        if self.position_side:
            self._manage_position()
        self._trigger_pending()
        day_key = dt.date()
        if self.last_day != day_key:
            self.last_day = day_key
            if not self.position_side and not self.pending_buy and not self.pending_sell:
                self._place_daily_limits()

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
