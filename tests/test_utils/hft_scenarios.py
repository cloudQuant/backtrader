from dataclasses import asdict, dataclass

from backtrader.brokers.hft import OBIAlphaQuoteBuilder, PlainGridQuoteBuilder, QueueExchangeModel, QueueMarketMakingQuoteBuilder
from backtrader.brokers.tickbroker import TickBroker
from backtrader.events import OrderBookSnapshot, TickEvent
from backtrader.order import Order


class DummyData:
    def __init__(self, name="BTC/USDT"):
        self._name = name
        self.name = name
        self.symbol = name


@dataclass
class TradeFill:
    side: str
    price: float
    size: float


@dataclass
class ScenarioResult:
    cash: float
    position: float
    fills: list[TradeFill]


@dataclass
class ScenarioSpec:
    name: str
    source: str
    orderbooks: list
    ticks: list
    builder_factory: object


class ReferenceMakerRunner:
    def __init__(self, cash=1000.0, order_qty=1.0):
        self.cash = cash
        self.position = 0.0
        self.order_qty = order_qty
        self.pending = {}
        self.queue_ahead = {}
        self.fills = []

    @staticmethod
    def _normalize_quotes(new_quotes):
        normalized = {}
        for side, value in new_quotes.items():
            if isinstance(value, (list, tuple)):
                prices = tuple(float(price) for price in value)
            else:
                prices = (float(value),)
            normalized[side] = prices
        return normalized

    def cancel_missing(self, new_quotes):
        normalized = self._normalize_quotes(new_quotes)
        expected = {(side, price) for side, prices in normalized.items() for price in prices}
        stale = [key for key in self.pending if key not in expected]
        for key in stale:
            self.pending.pop(key, None)
            self.queue_ahead.pop(key, None)

    def submit_quotes(self, snapshot, new_quotes):
        normalized = self._normalize_quotes(new_quotes)
        best_bid_qty = snapshot.bids[0][1] if snapshot.bids else 0.0
        best_ask_qty = snapshot.asks[0][1] if snapshot.asks else 0.0
        for side, prices in normalized.items():
            for price in prices:
                key = (side, price)
                if key in self.pending:
                    continue
                self.pending[key] = price
                self.queue_ahead[key] = best_bid_qty if side == "buy" else best_ask_qty

    def on_trade(self, tick):
        for side, target_price in list(self.pending):
            if tick.price != target_price:
                continue

            remaining_trade = tick.volume
            key = (side, target_price)
            ahead = self.queue_ahead.get(key, 0.0)
            consumed = min(ahead, remaining_trade)
            ahead -= consumed
            remaining_trade -= consumed
            self.queue_ahead[key] = ahead
            if remaining_trade < self.order_qty:
                continue

            if side == "buy":
                self.cash -= target_price * self.order_qty
                self.position += self.order_qty
            else:
                self.cash += target_price * self.order_qty
                self.position -= self.order_qty
            self.fills.append(TradeFill(side=side, price=target_price, size=self.order_qty))
            self.pending.pop(key, None)
            self.queue_ahead.pop(key, None)


def _cleanup_orders(working_orders):
    return {
        key: order
        for key, order in working_orders.items()
        if order.alive() and order.status not in (Order.Canceled, Order.Rejected)
    }


def _normalize_quotes(quotes):
    normalized = {}
    for side, value in quotes.items():
        if isinstance(value, (list, tuple)):
            prices = tuple(float(price) for price in value)
        else:
            prices = (float(value),)
        normalized[side] = prices
    return normalized


def _submit_or_replace_quotes(broker, data, working_orders, quotes):
    working_orders = _cleanup_orders(working_orders)
    normalized = _normalize_quotes(quotes)
    target_keys = {(side, price) for side, prices in normalized.items() for price in prices}

    for key in list(working_orders):
        if key in target_keys:
            continue
        broker.cancel(working_orders[key])
        working_orders.pop(key, None)

    for side, prices in normalized.items():
        for target_price in prices:
            key = (side, target_price)
            if key in working_orders:
                continue
            if side == "buy":
                order = broker.buy(owner=None, data=data, size=1.0, price=target_price, exectype=Order.Limit)
            else:
                order = broker.sell(owner=None, data=data, size=1.0, price=target_price, exectype=Order.Limit)
            order.time_in_force = "GTX"
            working_orders[key] = order
    return _cleanup_orders(working_orders)


def _fill_history(broker):
    return [
        TradeFill(side=item["side"], price=item["price"], size=item["size"])
        for item in broker.order_history
        if item.get("status") == "Completed"
    ]


def run_backtrader_scenario(spec, cash=1000.0):
    data = DummyData()
    broker = TickBroker(cash=cash, exchange_model=QueueExchangeModel())
    broker.setcommission(commission=0.0, name=data.name)
    working_orders = {}
    quote_builder = spec.builder_factory()

    for snapshot, trade in zip(spec.orderbooks, spec.ticks):
        quotes = quote_builder(broker.getposition(data).size, snapshot)
        working_orders = _submit_or_replace_quotes(broker, data, working_orders, quotes)
        broker.process_orderbook(snapshot)
        working_orders = _cleanup_orders(working_orders)
        broker.process_tick(trade)
        working_orders = _cleanup_orders(working_orders)

    return ScenarioResult(
        cash=broker.getcash(),
        position=broker.getposition(data).size,
        fills=_fill_history(broker),
    ), broker, data


def run_reference_scenario(spec, cash=1000.0):
    runner = ReferenceMakerRunner(cash=cash, order_qty=1.0)
    quote_builder = spec.builder_factory()
    for snapshot, trade in zip(spec.orderbooks, spec.ticks):
        quotes = quote_builder(runner.position, snapshot)
        runner.cancel_missing(quotes)
        runner.submit_quotes(snapshot, quotes)
        runner.on_trade(trade)
    return ScenarioResult(cash=runner.cash, position=runner.position, fills=runner.fills)


def compare_scenario(spec, cash=1000.0):
    reference = run_reference_scenario(spec, cash=cash)
    backtrader, broker, data = run_backtrader_scenario(spec, cash=cash)
    return {
        "name": spec.name,
        "source": spec.source,
        "reference": scenario_to_dict(reference),
        "backtrader": scenario_to_dict(backtrader),
        "matches": {
            "cash": abs(reference.cash - backtrader.cash) < 1e-9,
            "position": abs(reference.position - backtrader.position) < 1e-9,
            "fills": reference.fills == backtrader.fills,
            "trade_count": broker.state_values(data)["num_trades"] == len(reference.fills),
        },
        "trade_count": len(reference.fills),
        "state_values": broker.state_values(data),
    }


def scenario_to_dict(result):
    return {
        "cash": result.cash,
        "position": result.position,
        "fills": [asdict(fill) for fill in result.fills],
    }


def get_hft_scenario_specs():
    return [
        ScenarioSpec(
            name="plain_grid",
            source="High-Frequency Grid Trading.ipynb",
            orderbooks=[
                OrderBookSnapshot(timestamp=1.0, symbol="BTC/USDT", bids=[(100.0, 1.0)], asks=[(101.0, 1.0)]),
                OrderBookSnapshot(timestamp=2.0, symbol="BTC/USDT", bids=[(100.0, 1.0)], asks=[(101.0, 1.0)]),
            ],
            ticks=[
                TickEvent(timestamp=1.5, symbol="BTC/USDT", price=100.0, volume=2.0),
                TickEvent(timestamp=2.5, symbol="BTC/USDT", price=101.0, volume=2.0),
            ],
            builder_factory=lambda: PlainGridQuoteBuilder(
                tick_size=1.0,
                grid_num=1,
                max_position=1.0,
                grid_interval=1.0,
                half_spread=0.5,
                order_qty=1.0,
            ),
        ),
        ScenarioSpec(
            name="queue_market_making",
            source="Queue-Based Market Making in Large Tick Size Assets.ipynb",
            orderbooks=[
                OrderBookSnapshot(timestamp=1.0, symbol="BTC/USDT", bids=[(100.0, 5.0)], asks=[(101.0, 1.0)]),
                OrderBookSnapshot(timestamp=2.0, symbol="BTC/USDT", bids=[(100.0, 1.0)], asks=[(101.0, 5.0)]),
            ],
            ticks=[
                TickEvent(timestamp=1.5, symbol="BTC/USDT", price=100.0, volume=6.0),
                TickEvent(timestamp=2.5, symbol="BTC/USDT", price=101.0, volume=6.0),
            ],
            builder_factory=lambda: QueueMarketMakingQuoteBuilder(
                tick_size=1.0,
                order_qty=1.0,
                grid_num=1,
                max_position=1.0,
                half_spread=0.49,
                grid_interval=1.0,
                skew_adj=1.0,
            ),
        ),
        ScenarioSpec(
            name="obi_alpha_market_making",
            source="Market Making with Alpha - Order Book Imbalance.ipynb",
            orderbooks=[
                OrderBookSnapshot(timestamp=1.0, symbol="BTC/USDT", bids=[(100.0, 8.0), (99.0, 4.0)], asks=[(101.0, 2.0), (102.0, 1.0)]),
                OrderBookSnapshot(timestamp=2.0, symbol="BTC/USDT", bids=[(100.0, 2.0), (99.0, 1.0)], asks=[(101.0, 8.0), (102.0, 4.0)]),
                OrderBookSnapshot(timestamp=3.0, symbol="BTC/USDT", bids=[(100.0, 7.0), (99.0, 3.0)], asks=[(101.0, 2.0), (102.0, 1.0)]),
                OrderBookSnapshot(timestamp=4.0, symbol="BTC/USDT", bids=[(100.0, 1.0), (99.0, 1.0)], asks=[(101.0, 7.0), (102.0, 3.0)]),
            ],
            ticks=[
                TickEvent(timestamp=1.5, symbol="BTC/USDT", price=100.0, volume=9.0),
                TickEvent(timestamp=2.5, symbol="BTC/USDT", price=101.0, volume=9.0),
                TickEvent(timestamp=3.5, symbol="BTC/USDT", price=100.0, volume=8.0),
                TickEvent(timestamp=4.5, symbol="BTC/USDT", price=101.0, volume=8.0),
            ],
            builder_factory=lambda: OBIAlphaQuoteBuilder(
                tick_size=1.0,
                depth_levels=2,
                half_spread=1.0,
                skew=0.5,
                c1=1.0,
                order_qty=1.0,
                max_position=1.0,
                window=3,
                grid_num=1,
                grid_interval=1.0,
            ),
        ),
    ]


def build_hft_comparison_report(cash=1000.0):
    return [compare_scenario(spec, cash=cash) for spec in get_hft_scenario_specs()]
