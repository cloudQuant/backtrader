import backtrader as bt

from backtrader.channel import DataChannel
from backtrader.brokers.mixbroker import MixBroker
from backtrader.events import BarEvent, OrderBookSnapshot, TickEvent
from backtrader.feeds.mixed_channel import MixedChannel
from backtrader.order import Order


class MemoryChannel(DataChannel):
    def __init__(self, channel_type, symbol, events):
        super().__init__(symbol=symbol, validate=False, auto_fix=False)
        self.channel_type = channel_type
        self._events = list(events)

    def load(self):
        for event in self._events:
            yield event


class DemoStrategy(bt.Strategy):
    params = (("symbol", "BTC/USDT"),)

    def __init__(self):
        self.pending_order = None
        self._data_obj = type("Data", (), {"_name": self.p.symbol, "symbol": self.p.symbol})()

    def notify_order(self, order):
        if order.status == order.Completed:
            side = "BUY" if order.isbuy() else "SELL"
            print(f"{side} filled @ {order.executed.price:.2f} size={order.executed.size:.2f}")
        if not order.alive():
            self.pending_order = None

    def notify_tick(self, tick):
        if self.pending_order is not None:
            return

        last_bar = self.context.get_last_bar(self.p.symbol)
        ratio = self.context.get_ob_ratio(self.p.symbol, levels=1, window=1)
        sma = self.context.get_sma(self.p.symbol, period=20)
        position = self.context.get_position(self.p.symbol)
        pos_size = position.size if position is not None else 0.0

        if last_bar is None or sma is None or ratio is None:
            return

        if pos_size <= 0.0 and ratio > 1.0 and last_bar.close > sma:
            print("signal: buy")
            self.pending_order = self.buy(data=self._data_obj, size=1, exectype=Order.Market)
        elif pos_size > 0.0 and ratio < 1.0 and last_bar.close < sma:
            print("signal: sell")
            self.pending_order = self.sell(data=self._data_obj, size=1, exectype=Order.Market)


def build_demo_queue(symbol):
    tick_channel = MemoryChannel(
        "tick",
        symbol,
        [
            TickEvent(timestamp=21.0, symbol=symbol, price=20.0, volume=1.0),
            TickEvent(timestamp=22.0, symbol=symbol, price=20.0, volume=1.0),
            TickEvent(timestamp=24.0, symbol=symbol, price=1.0, volume=1.0),
            TickEvent(timestamp=25.0, symbol=symbol, price=1.0, volume=1.0),
        ],
    )
    orderbook_channel = MemoryChannel(
        "orderbook",
        symbol,
        [
            OrderBookSnapshot(
                timestamp=20.1,
                symbol=symbol,
                bids=[(20.0, 5.0)],
                asks=[(21.0, 1.0)],
            ),
            OrderBookSnapshot(
                timestamp=23.1,
                symbol=symbol,
                bids=[(1.0, 1.0)],
                asks=[(2.0, 5.0)],
            ),
        ],
    )
    bars = [
        BarEvent(
            timestamp=float(close_idx),
            symbol=symbol,
            open=float(close_idx),
            high=float(close_idx) + 0.5,
            low=max(float(close_idx) - 0.5, 0.1),
            close=float(close_idx),
            volume=10.0,
        )
        for close_idx in range(1, 21)
    ]
    bars.append(
        BarEvent(
            timestamp=23.0,
            symbol=symbol,
            open=1.0,
            high=1.5,
            low=0.5,
            close=1.0,
            volume=10.0,
        )
    )
    return MixedChannel(
        tick_channels=[tick_channel],
        orderbook_channels=[orderbook_channel],
        bars=[bars],
        adaptive=False,
        preload_window=10.0,
    )


def main():
    symbol = "BTC/USDT"
    cerebro = bt.Cerebro()
    broker = MixBroker(cash=1000.0)
    broker.setcommission(commission=0.0, name=symbol)
    cerebro.setbroker(broker)
    cerebro.addstrategy(DemoStrategy, symbol=symbol)

    print(f"initial cash: {broker.getcash():.2f}")
    results = cerebro.run(channel=build_demo_queue(symbol))
    strat = results[0]
    print(f"final cash: {broker.getcash():.2f}")
    print(f"order history: {broker.order_history}")
    print(f"context attached: {hasattr(strat, 'context')}")


if __name__ == "__main__":
    main()
