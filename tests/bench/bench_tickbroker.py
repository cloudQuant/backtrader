import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backtrader.brokers.hft import ConstantLatencyModel, QueueExchangeModel
from backtrader.brokers.tickbroker import TickBroker
from backtrader.events import OrderBookSnapshot, TickEvent
from backtrader.order import Order


class DummyData:
    def __init__(self, name="BTC/USDT"):
        self._name = name
        self.name = name
        self.symbol = name


def _run_case(label, num_ticks=100000, use_enhanced=False):
    data = DummyData()
    kwargs = {"cash": 100000.0}
    if use_enhanced:
        kwargs["latency_model"] = ConstantLatencyModel(order_entry_latency_ms=1)
        kwargs["exchange_model"] = QueueExchangeModel()
    broker = TickBroker(**kwargs)
    start = time.perf_counter()
    order_count = 0

    for i in range(num_ticks):
        if i % 100 == 0:
            order = broker.buy(owner=None, data=data, size=1, price=100.0, exectype=Order.Limit)
            if use_enhanced:
                order.time_in_force = "IOC"
            order_count += 1
            broker.process_orderbook(
                OrderBookSnapshot(
                    timestamp=float(i) + 0.1,
                    symbol=data._name,
                    bids=[(99.5, 2.0)],
                    asks=[(100.0, 2.0)],
                )
            )
        broker.process_tick(TickEvent(timestamp=float(i) + 1.0, symbol=data._name, price=100.0, volume=2.0))

    elapsed = time.perf_counter() - start
    rate = num_ticks / elapsed if elapsed else 0.0
    print(f"[{label}] ticks={num_ticks} orders={order_count} elapsed={elapsed:.4f}s rate={rate:.2f}/s")
    return {"label": label, "ticks": num_ticks, "orders": order_count, "elapsed": elapsed, "rate": rate}


if __name__ == "__main__":
    print("TickBroker benchmark")
    _run_case("baseline-100k", num_ticks=100000, use_enhanced=False)
    _run_case("enhanced-100k", num_ticks=100000, use_enhanced=True)
    _run_case("baseline-1m", num_ticks=1000000, use_enhanced=False)
    _run_case("enhanced-1m", num_ticks=1000000, use_enhanced=True)
