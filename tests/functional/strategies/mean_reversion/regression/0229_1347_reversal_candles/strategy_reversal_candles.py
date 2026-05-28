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


class ReversalCandlesStrategy(bt.Strategy):
    """
    MQL5 Wizard - Reversal Candlestick Patterns signal.

    Uses composite candles (combining up to 'candle_range' bars) to detect
    reversal patterns similar to hammer/hanging man.

    Open long: Bullish composite candle formed (large lower shadow, small upper shadow)
    Close long: Bearish composite candle formed
    Open short: Bearish composite candle formed (large upper shadow, small lower shadow)
    Close short: Bullish composite candle formed
    """
    params = dict(
        candle_range=3,
        minimum=50,
        shadow_big=0.5,
        shadow_small=0.2,
        stop_loss=2.0,
        take_profit=1.0,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self.entry_order = None
        self.stop_order = None
        self.tp_order = None

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _composite_candle(self, start_idx):
        """
        Build a composite candle starting from bar index 'start_idx' (1-based from current).
        Returns (direction, size) where direction > 0 for bullish, < 0 for bearish, 0 for none.
        The absolute value is the number of bars used.
        """
        if len(self.data) < start_idx + self.p.candle_range:
            return 0, 0, 0, 0

        for num_bars in range(1, self.p.candle_range + 1):
            idx_start = -(start_idx + num_bars - 1)
            idx_end = -start_idx

            high_val = max(float(self.data.high[i]) for i in range(idx_start, idx_end + 1))
            low_val = min(float(self.data.low[i]) for i in range(idx_start, idx_end + 1))
            open_val = float(self.data.open[idx_start])
            close_val = float(self.data.close[idx_end])

            size = high_val - low_val
            if size < self.p.minimum * self.p.point:
                continue

            body = close_val - open_val
            if abs(body) < 1e-10:
                continue

            if body > 0:  # bullish
                upper_shadow = high_val - close_val
                lower_shadow = open_val - low_val
            else:  # bearish
                upper_shadow = high_val - open_val
                lower_shadow = close_val - low_val

            upper_ratio = upper_shadow / size if size > 0 else 0
            lower_ratio = lower_shadow / size if size > 0 else 0

            # Bullish reversal: large lower shadow, small upper shadow
            if lower_ratio >= self.p.shadow_big and upper_ratio <= self.p.shadow_small:
                return num_bars, size, high_val, low_val

            # Bearish reversal: large upper shadow, small lower shadow
            if upper_ratio >= self.p.shadow_big and lower_ratio <= self.p.shadow_small:
                return -num_bars, size, high_val, low_val

        return 0, 0, 0, 0

    def _cancel_pending(self):
        if self.stop_order:
            self.cancel(self.stop_order)
            self.stop_order = None
        if self.tp_order:
            self.cancel(self.tp_order)
            self.tp_order = None
        if self.entry_order:
            self.cancel(self.entry_order)
            self.entry_order = None

    def next(self):
        self.bar_num += 1
        if len(self.data) < self.p.candle_range + 3:
            return

        if self.entry_order:
            return

        candle_dir, candle_size, _, _ = self._composite_candle(1)

        if candle_dir == 0:
            return

        if self.position:
            if self.position.size > 0 and candle_dir < 0:
                self._cancel_pending()
                self.log(f'close long price={self.data.close[0]:.2f}')
                self.close()
                return
            if self.position.size < 0 and candle_dir > 0:
                self._cancel_pending()
                self.log(f'close short price={self.data.close[0]:.2f}')
                self.close()
                return
        else:
            if candle_dir > 0:
                price = float(self.data.close[0])
                sl = round(price - self.p.stop_loss * candle_size, self.p.price_digits) if self.p.stop_loss > 0 else None
                tp = round(price + self.p.take_profit * candle_size, self.p.price_digits) if self.p.take_profit > 0 else None
                self.log(f'buy signal price={price:.2f} sl={sl} tp={tp}')
                self.entry_order = self.buy(size=self.p.lot)
                if sl:
                    self.stop_order = self.sell(size=self.p.lot, exectype=bt.Order.Stop, price=sl)
                if tp:
                    self.tp_order = self.sell(size=self.p.lot, exectype=bt.Order.Limit, price=tp)
                return
            if candle_dir < 0:
                price = float(self.data.close[0])
                sl = round(price + self.p.stop_loss * candle_size, self.p.price_digits) if self.p.stop_loss > 0 else None
                tp = round(price - self.p.take_profit * candle_size, self.p.price_digits) if self.p.take_profit > 0 else None
                self.log(f'sell signal price={price:.2f} sl={sl} tp={tp}')
                self.entry_order = self.sell(size=self.p.lot)
                if sl:
                    self.stop_order = self.buy(size=self.p.lot, exectype=bt.Order.Stop, price=sl)
                if tp:
                    self.tp_order = self.buy(size=self.p.lot, exectype=bt.Order.Limit, price=tp)
                return

    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order == self.entry_order:
                self.entry_order = None
            elif order == self.stop_order:
                self.stop_order = None
                if self.tp_order:
                    self.cancel(self.tp_order)
                    self.tp_order = None
            elif order == self.tp_order:
                self.tp_order = None
                if self.stop_order:
                    self.cancel(self.stop_order)
                    self.stop_order = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.entry_order:
                self.entry_order = None
            elif order == self.stop_order:
                self.stop_order = None
            elif order == self.tp_order:
                self.tp_order = None

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
