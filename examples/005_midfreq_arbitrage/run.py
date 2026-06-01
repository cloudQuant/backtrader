import backtrader as bt

from backtrader.channel import DataChannel
from backtrader.brokers.mixbroker import MixBroker
from backtrader.events import BarEvent, OrderBookSnapshot, TickEvent
from backtrader.feeds.mixed_channel import build_mixed_channel
from backtrader.order import Order


class MemoryChannel(DataChannel):
    def __init__(self, channel_type, symbol, events):
        super().__init__(symbol=symbol, validate=False, auto_fix=False)
        self.channel_type = channel_type
        self._events = list(events)

    def load(self):
        for event in self._events:
            yield event


class PairArbitrageStrategy(bt.Strategy):
    params = (("symbol_a", "BTC/USDT"), ("symbol_b", "ETH/USDT"))

    def __init__(self):
        self.completed_refs = set()
        self.pending_refs = set()
        self.data_a = type("Data", (), {"_name": self.p.symbol_a, "symbol": self.p.symbol_a})()
        self.data_b = type("Data", (), {"_name": self.p.symbol_b, "symbol": self.p.symbol_b})()

    def notify_order(self, order):
        if order.status == order.Completed and order.ref not in self.completed_refs:
            self.completed_refs.add(order.ref)
            side = "BUY" if order.isbuy() else "SELL"
            symbol = getattr(order.data, "symbol", getattr(order.data, "_name", ""))
            print(f"{side} {symbol} @ {order.executed.price:.2f} size={order.executed.size:.2f}")
        if not order.alive():
            self.pending_refs.discard(order.ref)

    def notify_tick(self, tick):
        snapshot_all = self.context.snapshot_all()
        if self.pending_refs:
            return

        snap_a = snapshot_all["symbols"].get(self.p.symbol_a)
        snap_b = snapshot_all["symbols"].get(self.p.symbol_b)
        if snap_a is None or snap_b is None:
            return
        if snap_a["last_tick"] is None or snap_b["last_tick"] is None:
            return
        if snap_a["last_bar"] is None or snap_b["last_bar"] is None:
            return
        if snap_a["ob_ratio"] is None or snap_b["ob_ratio"] is None:
            return

        pos_a = snap_a["position"].size if snap_a["position"] is not None else 0.0
        pos_b = snap_b["position"].size if snap_b["position"] is not None else 0.0
        spread = snap_a["last_tick"].price - snap_b["last_tick"].price

        if pos_a <= 0.0 and pos_b >= 0.0 and spread >= 8.0 and snap_a["ob_ratio"] > 1.0 and snap_b["ob_ratio"] < 1.0:
            print(f"open spread={spread:.2f}")
            order_a = self.buy(data=self.data_a, size=1, exectype=Order.Market)
            order_b = self.sell(data=self.data_b, size=1, exectype=Order.Market)
            self.pending_refs.update([order_a.ref, order_b.ref])
        elif pos_a > 0.0 and pos_b < 0.0 and spread <= 2.0:
            print(f"close spread={spread:.2f}")
            order_a = self.sell(data=self.data_a, size=1, exectype=Order.Market)
            order_b = self.buy(data=self.data_b, size=1, exectype=Order.Market)
            self.pending_refs.update([order_a.ref, order_b.ref])


def build_demo_channel():
    symbol_a = "BTC/USDT"
    symbol_b = "ETH/USDT"

    tick_a = MemoryChannel(
        "tick",
        symbol_a,
        [
            TickEvent(timestamp=21.0, symbol=symbol_a, price=20.0, volume=1.0),
            TickEvent(timestamp=24.0, symbol=symbol_a, price=12.0, volume=1.0),
            TickEvent(timestamp=25.0, symbol=symbol_a, price=12.0, volume=1.0),
        ],
    )
    tick_b = MemoryChannel(
        "tick",
        symbol_b,
        [
            TickEvent(timestamp=20.5, symbol=symbol_b, price=10.0, volume=1.0),
            TickEvent(timestamp=23.5, symbol=symbol_b, price=10.0, volume=1.0),
            TickEvent(timestamp=26.0, symbol=symbol_b, price=10.0, volume=1.0),
        ],
    )
    orderbook_a = MemoryChannel(
        "orderbook",
        symbol_a,
        [
            OrderBookSnapshot(timestamp=20.1, symbol=symbol_a, bids=[(20.0, 5.0)], asks=[(21.0, 1.0)]),
            OrderBookSnapshot(timestamp=23.1, symbol=symbol_a, bids=[(12.0, 2.0)], asks=[(13.0, 2.0)]),
        ],
    )
    orderbook_b = MemoryChannel(
        "orderbook",
        symbol_b,
        [
            OrderBookSnapshot(timestamp=20.2, symbol=symbol_b, bids=[(10.0, 1.0)], asks=[(11.0, 5.0)]),
            OrderBookSnapshot(timestamp=23.2, symbol=symbol_b, bids=[(10.0, 2.0)], asks=[(11.0, 2.0)]),
        ],
    )
    bars_a = [
        BarEvent(timestamp=float(index), symbol=symbol_a, open=float(index), high=float(index) + 0.5, low=max(float(index) - 0.5, 0.1), close=float(index), volume=5.0)
        for index in range(1, 21)
    ]
    bars_a.append(BarEvent(timestamp=23.0, symbol=symbol_a, open=12.0, high=12.5, low=11.5, close=12.0, volume=5.0))
    bars_b = [
        BarEvent(timestamp=float(index) + 0.05, symbol=symbol_b, open=float(index), high=float(index) + 0.5, low=max(float(index) - 0.5, 0.1), close=float(index), volume=5.0)
        for index in range(1, 21)
    ]
    bars_b.append(BarEvent(timestamp=23.05, symbol=symbol_b, open=10.0, high=10.5, low=9.5, close=10.0, volume=5.0))

    return build_mixed_channel(
        tick_channels=[tick_a, tick_b],
        orderbook_channels=[orderbook_a, orderbook_b],
        bars=[bars_a, bars_b],
        adaptive=False,
        preload_window=10.0,
    )


def main():
    cerebro = bt.Cerebro()
    broker = MixBroker(cash=1000.0)
    broker.setcommission(commission=0.0, name="BTC/USDT")
    broker.setcommission(commission=0.0, name="ETH/USDT")
    cerebro.setbroker(broker)
    cerebro.addstrategy(PairArbitrageStrategy)

    print(f"initial cash: {broker.getcash():.2f}")
    results = cerebro.run(channel=build_demo_channel())
    strat = results[0]
    print(f"final cash: {broker.getcash():.2f}")
    print(f"completed refs: {sorted(strat.completed_refs)}")
    print(f"order history: {broker.order_history}")
    print(f"snapshot all: {broker.get_symbol_snapshots()}")


if __name__ == "__main__":
    main()
