from __future__ import annotations

import bisect
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator, Optional

import numpy as np

from backtrader.brokers.hft.examples import build_quote_builder, get_hftbacktest_example_spec
from backtrader.brokers.hft.exchange import FillRole, OrderResult, QueueExchangeModel
from backtrader.brokers.hft.queue import ProbQueueModel
from backtrader.brokers.tickbroker import TickBroker
from backtrader.channels.orderbook import OrderBookChannel
from backtrader.channels.tick import TickChannel
from backtrader.order import Order


@dataclass(frozen=True)
class ComparisonFill:
    side: str
    price: float
    size: float
    timestamp_ns: Optional[int] = None
    local_timestamp_ns: Optional[int] = None
    exch_timestamp_ns: Optional[int] = None
    order_ref: Optional[int] = None


@dataclass(frozen=True)
class EngineResult:
    balance: float
    position: float
    num_trades: int
    fills: list[ComparisonFill]


@dataclass(frozen=True)
class StrategyComparisonResult:
    strategy: str
    decision_interval_ns: int
    backtrader: EngineResult
    hftbacktest: EngineResult
    matches: dict[str, bool]
    deltas: dict[str, float]


class _DataRef:
    def __init__(self, symbol: str):
        self._name = symbol
        self.name = symbol
        self.symbol = symbol


_BACKTRADER_COMPARISON_INITIAL_CASH = 1_000_000_000.0
_DEPTH_EVENT = 1
_TRADE_EVENT = 2
_BUY_EVENT = 1 << 29
_SELL_EVENT = 1 << 28
_EXCH_EVENT = 1 << 31


def _build_runtime_builder(spec, market_data_path):
    builder = build_quote_builder(spec)
    requirement = next(
        (item for item in spec.input_requirements if item.name == "precompute_data"), None
    )
    if requirement is None:
        return builder
    precompute_path = _resolve_required_input_path(market_data_path, requirement.patterns)
    if precompute_path is None:
        raise FileNotFoundError(
            f"Missing required precompute_data for strategy '{spec.name}'. Expected one of: {', '.join(requirement.patterns)}"
        )
    precompute = _load_precompute_data(precompute_path)
    if hasattr(builder, "precompute_data"):
        builder.precompute_data = precompute
    return builder


def _resolve_required_input_path(market_data_path, patterns):
    market_data_path = Path(market_data_path)
    for pattern in patterns:
        for base in (market_data_path.parent, *market_data_path.parents):
            candidate = base / pattern
            if candidate.exists():
                return candidate
    return None


def _load_precompute_data(precompute_path):
    with np.load(str(precompute_path)) as payload:
        if "data" in payload:
            return payload["data"]
        keys = list(payload.keys())
        if keys:
            return payload[keys[0]]
    raise ValueError(f"Unable to load precompute data from {precompute_path}")


def _builder_order_qty(builder) -> float:
    return float(getattr(builder, "current_order_qty", getattr(builder, "order_qty", 1.0)))


class _NoPartialQueueExchangeModel(QueueExchangeModel):
    def __init__(
        self, queue_model_power: float = 2.0, lot_size: float = 1.0, tick_size: float = None
    ):
        super().__init__(
            queue_model=ProbQueueModel(power=queue_model_power, lot_size=lot_size),
            tick_size=tick_size,
        )

    def on_new_order(self, order, ob_snapshot):
        if getattr(order, "_fill_role", None) == FillRole.MAKER:
            return OrderResult(action="PENDING")
        result = super().on_new_order(order, ob_snapshot)
        if result.action == "PENDING" and getattr(order, "_fill_role", None) == FillRole.MAKER:
            levels = (
                getattr(ob_snapshot, "bids", None)
                if order.isbuy()
                else getattr(ob_snapshot, "asks", None)
            )
            level_qty = self._level_qty(levels, float(order.price))
            order._queue_wait_for_first_visible_level = (
                order.isbuy()
                and level_qty <= 1e-12
                and float(getattr(order, "_queue_initial_ahead", 0.0)) <= 1e-12
            )
        return result

    def _same_price_tick(self, price_a: float, price_b: float) -> bool:
        if self._tick_size is not None and self._tick_size > 0:
            return round(price_a / self._tick_size) == round(price_b / self._tick_size)
        return price_a == price_b

    def _level_qty(self, levels, price: float) -> float:
        if not levels:
            return 0.0
        for level_price, level_qty in levels:
            if self._same_price_tick(float(level_price), float(price)):
                return float(level_qty)
        return 0.0

    def _trade_reaches_order(
        self, order_price: float, trade_price: float, is_buy_order: bool
    ) -> bool:
        if self._tick_size is not None and self._tick_size > 0:
            order_tick = round(order_price / self._tick_size)
            trade_tick = round(trade_price / self._tick_size)
            return trade_tick <= order_tick if is_buy_order else trade_tick >= order_tick
        return trade_price <= order_price if is_buy_order else trade_price >= order_price

    def on_trade(self, trade_event, pending_orders):
        fills: list = []
        trade_price = getattr(trade_event, "price", None)
        direction = str(getattr(trade_event, "direction", "")).lower()
        if trade_price is None or direction not in {"buy", "sell"}:
            return fills

        for order in pending_orders:
            if getattr(order, "_fill_role", None) != FillRole.MAKER:
                continue
            if direction == "buy":
                if order.isbuy():
                    continue
                if not self._trade_reaches_order(
                    float(order.price), float(trade_price), is_buy_order=False
                ):
                    continue
            else:
                if not order.isbuy():
                    continue
                if not self._trade_reaches_order(
                    float(order.price), float(trade_price), is_buy_order=True
                ):
                    continue

            remaining = getattr(getattr(order, "executed", None), "remsize", None)
            if remaining is None:
                remaining = getattr(order, "size", 0.0)
            remaining = abs(float(remaining))
            if remaining <= 0.0:
                continue

            if self._same_price_tick(float(order.price), float(trade_price)):
                if getattr(order, "_queue_wait_for_first_visible_level", False):
                    continue
                fillable = self._queue_model.update_on_trade(order, trade_event)
                if fillable <= 1e-12 and float(getattr(order, "_queue_ahead", 0.0)) >= 0.0:
                    continue
            fills.append((order, float(order.price), remaining, FillRole.MAKER))
        return fills

    def on_depth_update(self, ob_event, pending_orders):
        fills: list = []
        prev_bids = getattr(ob_event, "previous_bids", None) or []
        prev_asks = getattr(ob_event, "previous_asks", None) or []
        curr_bids = getattr(ob_event, "bids", None) or []
        curr_asks = getattr(ob_event, "asks", None) or []

        for order in pending_orders:
            if getattr(order, "_fill_role", None) != FillRole.MAKER:
                continue
            price = getattr(order, "price", None)
            if price is None:
                continue
            prev_qty = self._level_qty(prev_bids if order.isbuy() else prev_asks, float(price))
            new_qty = self._level_qty(curr_bids if order.isbuy() else curr_asks, float(price))
            if (
                getattr(order, "_queue_wait_for_first_visible_level", False)
                and prev_qty <= 1e-12
                and new_qty > 1e-12
            ):
                order._queue_ahead = float(new_qty)
                order._queue_initial_ahead = max(
                    float(getattr(order, "_queue_initial_ahead", 0.0)), float(new_qty)
                )
                order._queue_trade_qty = 0.0
                order._queue_fillable = 0.0
                order._queue_wait_for_first_visible_level = False
                continue
            if abs(prev_qty - new_qty) <= 1e-12:
                continue
            self._queue_model.update_on_depth(order, prev_qty, new_qty)
        return fills


def _fill_counter(fills: list[ComparisonFill]) -> Counter:
    return Counter(
        (item.side, round(float(item.price), 8), round(float(item.size), 8)) for item in fills
    )


def _ordered_fill_sequence(fills: list[ComparisonFill]) -> list[tuple[object, ...]]:
    return [(item.side, round(float(item.price), 8), round(float(item.size), 8)) for item in fills]


def _normalized_fill_sequence(fills: list[ComparisonFill]) -> list[tuple[object, ...]]:
    return sorted(
        (
            int(item.timestamp_ns or item.exch_timestamp_ns or item.local_timestamp_ns or 0),
            item.side,
            round(float(item.price), 8),
            round(float(item.size), 8),
            int(item.exch_timestamp_ns or 0),
        )
        for item in fills
    )


def compare_binance_bbo_strategy(
    strategy_name: str,
    orderbook_path,
    tick_path,
    market_data_path,
    tick_size: float,
    lot_size: float,
    symbol: str = "ETH/USDT",
    decision_interval_ns: Optional[int] = None,
    maker_commission: Optional[float] = None,
    taker_commission: Optional[float] = None,
    queue_model_power: Optional[float] = None,
    max_decisions: Optional[int] = None,
) -> StrategyComparisonResult:
    spec = get_hftbacktest_example_spec(strategy_name)
    interval_ns = int(decision_interval_ns or spec.strategy.interval_ns)
    maker_fee = float(
        maker_commission
        if maker_commission is not None
        else spec.asset_parameters.get("maker_commission", 0.0)
    )
    taker_fee = float(
        taker_commission
        if taker_commission is not None
        else spec.asset_parameters.get("taker_commission", 0.0)
    )
    queue_power = float(
        queue_model_power
        if queue_model_power is not None
        else spec.asset_parameters.get("queue_model_power", 2.0)
    )

    backtrader_builder = _build_runtime_builder(spec, market_data_path)
    hftbacktest_builder = _build_runtime_builder(spec, market_data_path)
    decision_anchor_ns = _market_data_exchange_anchor_ns(market_data_path)
    exchange_book = _market_data_exchange_book(market_data_path)

    backtrader_result = _run_backtrader_strategy(
        orderbook_path=orderbook_path,
        tick_path=tick_path,
        market_data_path=market_data_path,
        symbol=symbol,
        builder=backtrader_builder,
        tick_size=tick_size,
        lot_size=lot_size,
        decision_anchor_ns=decision_anchor_ns,
        exchange_book=exchange_book,
        interval_ns=interval_ns,
        maker_commission=maker_fee,
        taker_commission=taker_fee,
        queue_model_power=queue_power,
        max_decisions=max_decisions,
    )
    hftbacktest_result = _run_hftbacktest_strategy(
        market_data_path=market_data_path,
        builder=hftbacktest_builder,
        tick_size=tick_size,
        lot_size=lot_size,
        interval_ns=interval_ns,
        maker_commission=maker_fee,
        taker_commission=taker_fee,
        queue_model_power=queue_power,
        max_decisions=max_decisions,
    )
    bt_fills = _fill_counter(backtrader_result.fills)
    hft_fills = _fill_counter(hftbacktest_result.fills)
    bt_in_order = _ordered_fill_sequence(backtrader_result.fills)
    hft_in_order = _ordered_fill_sequence(hftbacktest_result.fills)
    bt_normalized = _normalized_fill_sequence(backtrader_result.fills)
    hft_normalized = _normalized_fill_sequence(hftbacktest_result.fills)

    return StrategyComparisonResult(
        strategy=strategy_name,
        decision_interval_ns=interval_ns,
        backtrader=backtrader_result,
        hftbacktest=hftbacktest_result,
        matches={
            "balance": abs(backtrader_result.balance - hftbacktest_result.balance) < 1e-5,
            "position": abs(backtrader_result.position - hftbacktest_result.position) < 1e-9,
            "num_trades": backtrader_result.num_trades == hftbacktest_result.num_trades,
            "fills": bt_fills == hft_fills,
            "fills_in_order": bt_in_order == hft_in_order,
            "fills_normalized_order": bt_normalized == hft_normalized,
        },
        deltas={
            "balance": backtrader_result.balance - hftbacktest_result.balance,
            "position": backtrader_result.position - hftbacktest_result.position,
            "num_trades": float(backtrader_result.num_trades - hftbacktest_result.num_trades),
        },
    )


def comparison_to_json(result: StrategyComparisonResult) -> str:
    payload = asdict(result)
    return json.dumps(payload, indent=2)


def engine_result_to_json(result: EngineResult) -> str:
    payload = asdict(result)
    return json.dumps(payload, indent=2)


def run_binance_bbo_backtrader_strategy(
    strategy_name: str,
    orderbook_path,
    tick_path,
    market_data_path,
    tick_size: float,
    lot_size: float,
    symbol: str = "ETH/USDT",
    decision_interval_ns: Optional[int] = None,
    maker_commission: Optional[float] = None,
    taker_commission: Optional[float] = None,
    queue_model_power: Optional[float] = None,
    max_decisions: Optional[int] = None,
) -> EngineResult:
    spec = get_hftbacktest_example_spec(strategy_name)
    interval_ns = int(decision_interval_ns or spec.strategy.interval_ns)
    maker_fee = float(
        maker_commission
        if maker_commission is not None
        else spec.asset_parameters.get("maker_commission", 0.0)
    )
    taker_fee = float(
        taker_commission
        if taker_commission is not None
        else spec.asset_parameters.get("taker_commission", 0.0)
    )
    queue_power = float(
        queue_model_power
        if queue_model_power is not None
        else spec.asset_parameters.get("queue_model_power", 2.0)
    )
    builder = _build_runtime_builder(spec, market_data_path)
    decision_anchor_ns = _market_data_exchange_anchor_ns(market_data_path)
    exchange_book = _market_data_exchange_book(market_data_path)
    return _run_backtrader_strategy(
        orderbook_path=orderbook_path,
        tick_path=tick_path,
        market_data_path=market_data_path,
        symbol=symbol,
        builder=builder,
        tick_size=tick_size,
        lot_size=lot_size,
        decision_anchor_ns=decision_anchor_ns,
        exchange_book=exchange_book,
        interval_ns=interval_ns,
        maker_commission=maker_fee,
        taker_commission=taker_fee,
        queue_model_power=queue_power,
        max_decisions=max_decisions,
    )


def run_binance_bbo_hftbacktest_strategy(
    strategy_name: str,
    orderbook_path,
    tick_path,
    market_data_path,
    tick_size: float,
    lot_size: float,
    symbol: str = "ETH/USDT",
    decision_interval_ns: Optional[int] = None,
    maker_commission: Optional[float] = None,
    taker_commission: Optional[float] = None,
    queue_model_power: Optional[float] = None,
    max_decisions: Optional[int] = None,
) -> EngineResult:
    _ = (orderbook_path, tick_path, symbol)
    spec = get_hftbacktest_example_spec(strategy_name)
    interval_ns = int(decision_interval_ns or spec.strategy.interval_ns)
    maker_fee = float(
        maker_commission
        if maker_commission is not None
        else spec.asset_parameters.get("maker_commission", 0.0)
    )
    taker_fee = float(
        taker_commission
        if taker_commission is not None
        else spec.asset_parameters.get("taker_commission", 0.0)
    )
    queue_power = float(
        queue_model_power
        if queue_model_power is not None
        else spec.asset_parameters.get("queue_model_power", 2.0)
    )
    builder = _build_runtime_builder(spec, market_data_path)
    return _run_hftbacktest_strategy(
        market_data_path=market_data_path,
        builder=builder,
        tick_size=tick_size,
        lot_size=lot_size,
        interval_ns=interval_ns,
        maker_commission=maker_fee,
        taker_commission=taker_fee,
        queue_model_power=queue_power,
        max_decisions=max_decisions,
    )


def _run_backtrader_strategy(
    orderbook_path,
    tick_path,
    market_data_path,
    symbol: str,
    builder,
    tick_size: float,
    lot_size: float,
    decision_anchor_ns: Optional[int],
    exchange_book,
    interval_ns: int,
    maker_commission: float,
    taker_commission: float,
    queue_model_power: float,
    max_decisions: Optional[int],
) -> EngineResult:
    data = _DataRef(symbol)
    broker = TickBroker(
        cash=_BACKTRADER_COMPARISON_INITIAL_CASH,
        checksubmit=False,
        allow_partial=False,
        exchange_model=_NoPartialQueueExchangeModel(
            queue_model_power=queue_model_power, lot_size=lot_size, tick_size=tick_size
        ),
    )
    broker.setcommission(
        commission=0.0,
        maker_commission=maker_commission,
        taker_commission=taker_commission,
        name=data.name,
    )
    local_orderbooks = iter(
        OrderBookChannel(symbol=symbol, dataname=str(orderbook_path), depth=1).load()
    )
    next_local_orderbook = next(local_orderbooks, None)
    exchange_events = _iter_exchange_market_events(market_data_path, symbol)
    depth_probe = _create_depth_probe(market_data_path, tick_size=tick_size, lot_size=lot_size)
    depth_probe_timestamp_ns = (
        int(getattr(depth_probe, "current_timestamp", 0) or 0) if depth_probe is not None else None
    )
    working_orders: dict = {}
    latest_snapshot = None
    latest_exchange_snapshot = None
    next_decision_ns = None
    decisions = 0
    decision_trades: list = []

    for channel_type, event in exchange_events:
        event_ns = _event_timestamp_ns(event)
        reached_limit = False
        if next_decision_ns is None:
            next_decision_ns = (
                int(decision_anchor_ns + interval_ns)
                if decision_anchor_ns is not None
                else int(event_ns + interval_ns)
            )
        while next_decision_ns is not None and event_ns > next_decision_ns:
            decision_ts = float(next_decision_ns / 1_000_000_000.0)
            latest_snapshot, next_local_orderbook = _advance_local_orderbook_snapshot(
                latest_snapshot,
                next_local_orderbook,
                local_orderbooks,
                decision_ts,
            )
            if latest_snapshot is None:
                next_decision_ns += interval_ns
                continue
            builder_context = {
                "timestamp_ns": int(next_decision_ns),
                "last_trades": tuple(decision_trades),
            }
            quotes = builder(broker.getposition(data).size, latest_snapshot, builder_context)
            decision_trades = []
            depth_probe_timestamp_ns, decision_depth = _advance_depth_probe(
                depth_probe, depth_probe_timestamp_ns, next_decision_ns
            )
            finalized_exchange_snapshot: Optional[object] = (
                latest_exchange_snapshot
                if int(getattr(latest_exchange_snapshot, "timestamp_ns", 0) or 0)
                == int(next_decision_ns)
                else None
            )
            if finalized_exchange_snapshot is not None:
                base_submission_snapshot = finalized_exchange_snapshot
            elif decision_depth is not None and _is_finite_book(
                float(decision_depth.best_bid), float(decision_depth.best_ask)
            ):
                base_submission_snapshot = SimpleNamespace(
                    bids=[(float(decision_depth.best_bid), float(decision_depth.best_bid_qty))],
                    asks=[(float(decision_depth.best_ask), float(decision_depth.best_ask_qty))],
                )
            else:
                base_submission_snapshot = (
                    latest_exchange_snapshot
                    or _lookup_exchange_snapshot(exchange_book, next_decision_ns)
                    or latest_snapshot
                )
            submission_snapshot = base_submission_snapshot
            if submission_snapshot is not None:
                submission_fallback_snapshot = (
                    None if finalized_exchange_snapshot is not None else latest_snapshot
                )
                submission_snapshot = _augment_submission_snapshot(
                    base_submission_snapshot,
                    decision_depth,
                    quotes,
                    tick_size=float(tick_size),
                    fallback_snapshot=submission_fallback_snapshot,
                )
            working_orders = _submit_or_replace_quotes(
                broker,
                data,
                working_orders,
                quotes,
                order_qty=_builder_order_qty(builder),
                tick_size=float(tick_size),
                snapshot=submission_snapshot,
                activation_timestamp_ns=int(next_decision_ns),
            )
            decisions += 1
            next_decision_ns += interval_ns
            if max_decisions is not None and decisions >= max_decisions:
                reached_limit = True
                break
        if channel_type == "orderbook":
            depth_probe_timestamp_ns, event_depth = _advance_depth_probe(
                depth_probe, depth_probe_timestamp_ns, event_ns
            )
            orderbook_event = _augment_orderbook_snapshot_for_orders(
                event,
                event_depth,
                list(broker._orders_by_symbol.get(data.name, [])),
                tick_size=float(tick_size),
            )
            latest_exchange_snapshot = orderbook_event
            broker.process_orderbook(orderbook_event)
        else:
            decision_trades.append(event)
            broker.process_tick(event)
        if reached_limit:
            break

    fills = [
        ComparisonFill(
            side=item["side"],
            price=float(item["price"]),
            size=float(item["size"]),
            timestamp_ns=int(item.get("timestamp_ns", 0)) or None,
            local_timestamp_ns=int(item.get("timestamp_ns", 0)) or None,
            exch_timestamp_ns=int(item.get("timestamp_ns", 0)) or None,
            order_ref=int(item.get("order_ref")) if item.get("order_ref") is not None else None,
        )
        for item in broker.order_history
        if item.get("status") in ("Partial", "Completed") and float(item.get("size", 0.0)) > 0.0
    ]
    state = broker.state_values(data)
    return EngineResult(
        balance=float(state["balance"] - _BACKTRADER_COMPARISON_INITIAL_CASH + state["fee"]),
        position=float(broker.getposition(data).size),
        num_trades=len(fills),
        fills=fills,
    )


def _run_hftbacktest_strategy(
    market_data_path,
    builder,
    tick_size: float,
    lot_size: float,
    interval_ns: int,
    maker_commission: float,
    taker_commission: float,
    queue_model_power: float,
    max_decisions: Optional[int],
) -> EngineResult:
    try:
        from hftbacktest import BacktestAsset, HashMapMarketDepthBacktest
        from hftbacktest.order import BUY, GTX, LIMIT, PARTIALLY_FILLED, SELL
    except Exception as exc:
        raise RuntimeError("hftbacktest is required to run this comparison") from exc

    asset = (
        BacktestAsset()
        .data([str(Path(market_data_path))])
        .linear_asset(1.0)
        .constant_order_latency(0, 0)
        .power_prob_queue_model(float(queue_model_power))
        .no_partial_fill_exchange()
        .trading_value_fee_model(float(maker_commission), float(taker_commission))
        .tick_size(float(tick_size))
        .lot_size(float(lot_size))
    )
    hbt = HashMapMarketDepthBacktest([asset])
    fills: list = []
    seen_exec_qty: dict = {}
    decisions = 0

    while hbt.elapse(interval_ns) == 0:
        depth = hbt.depth(0)
        if not _is_finite_book(depth.best_bid, depth.best_ask):
            continue

        _collect_hft_fills(hbt.orders(0), seen_exec_qty, fills)
        hbt.clear_inactive_orders(0)
        last_trades = list(hbt.last_trades(0))

        snapshot = SimpleNamespace(
            bids=[(float(depth.best_bid), float(depth.best_bid_qty))],
            asks=[(float(depth.best_ask), float(depth.best_ask_qty))],
        )
        quotes = builder(
            float(hbt.position(0)),
            snapshot,
            {
                "timestamp_ns": int(getattr(hbt, "current_timestamp", 0)),
                "last_trades": tuple(last_trades),
            },
        )
        if last_trades and hasattr(hbt, "clear_last_trades"):
            hbt.clear_last_trades(0)
        _replace_hft_orders(
            hbt=hbt,
            quotes=quotes,
            tick_size=float(tick_size),
            order_qty=_builder_order_qty(builder),
            buy_flag=BUY,
            sell_flag=SELL,
            gtx_flag=GTX,
            limit_flag=LIMIT,
            partial_filled_flag=PARTIALLY_FILLED,
        )
        decisions += 1
        if max_decisions is not None and decisions >= max_decisions:
            break

    _collect_hft_fills(hbt.orders(0), seen_exec_qty, fills)
    state = hbt.state_values(0)
    return EngineResult(
        balance=float(state.balance),
        position=float(state.position),
        num_trades=int(state.num_trades),
        fills=fills,
    )


def _iter_market_events(orderbook_path, tick_path, symbol: str) -> Iterator[tuple[str, object]]:
    orderbooks = iter(OrderBookChannel(symbol=symbol, dataname=str(orderbook_path), depth=1).load())
    ticks = iter(TickChannel(symbol=symbol, dataname=str(tick_path)).load())
    next_orderbook = next(orderbooks, None)
    next_tick = next(ticks, None)
    while next_orderbook is not None or next_tick is not None:
        if next_tick is None:
            yield "orderbook", next_orderbook
            next_orderbook = next(orderbooks, None)
            continue
        if next_orderbook is None:
            yield "tick", next_tick
            next_tick = next(ticks, None)
            continue
        if next_orderbook.timestamp <= next_tick.timestamp:
            yield "orderbook", next_orderbook
            next_orderbook = next(orderbooks, None)
        else:
            yield "tick", next_tick
            next_tick = next(ticks, None)


def _iter_exchange_market_events(market_data_path, symbol: str) -> Iterator[tuple[str, object]]:
    with np.load(str(Path(market_data_path))) as payload:
        data = payload["data"]
        bid_price = None
        ask_price = None
        bid_qty = 0.0
        ask_qty = 0.0
        previous_bid_price = None
        previous_ask_price = None
        previous_bid_qty = 0.0
        previous_ask_qty = 0.0
        event_seq = 0
        for row in data:
            ev = int(row["ev"])
            if not (ev & _EXCH_EVENT):
                continue
            timestamp = float(int(row["exch_ts"]) / 1_000_000_000.0)
            if ev & _TRADE_EVENT:
                event_seq += 1
                yield "tick", SimpleNamespace(
                    timestamp=timestamp,
                    timestamp_ns=int(row["exch_ts"]),
                    event_seq=event_seq,
                    symbol=symbol,
                    price=float(row["px"]),
                    volume=float(row["qty"]),
                    direction="buy" if (ev & _BUY_EVENT) else "sell",
                    bid_price=bid_price,
                    ask_price=ask_price,
                    bid_volume=bid_qty,
                    ask_volume=ask_qty,
                )
            if ev & _DEPTH_EVENT:
                previous_bid_price = bid_price
                previous_ask_price = ask_price
                previous_bid_qty = bid_qty
                previous_ask_qty = ask_qty
                if ev & _BUY_EVENT:
                    bid_price = float(row["px"])
                    bid_qty = float(row["qty"])
                elif ev & _SELL_EVENT:
                    ask_price = float(row["px"])
                    ask_qty = float(row["qty"])
                if bid_price is None or ask_price is None:
                    continue
                event_seq += 1
                yield "orderbook", SimpleNamespace(
                    timestamp=timestamp,
                    timestamp_ns=int(row["exch_ts"]),
                    event_seq=event_seq,
                    symbol=symbol,
                    previous_bids=(
                        [(previous_bid_price, previous_bid_qty)]
                        if previous_bid_price is not None
                        else []
                    ),
                    previous_asks=(
                        [(previous_ask_price, previous_ask_qty)]
                        if previous_ask_price is not None
                        else []
                    ),
                    bids=[(bid_price, bid_qty)],
                    asks=[(ask_price, ask_qty)],
                )


def _advance_local_orderbook_snapshot(
    latest_snapshot, next_orderbook, orderbooks, target_ts: float
):
    while next_orderbook is not None and float(next_orderbook.timestamp) <= float(target_ts):
        latest_snapshot = next_orderbook
        next_orderbook = next(orderbooks, None)
    return latest_snapshot, next_orderbook


def _create_depth_probe(market_data_path, tick_size: float, lot_size: float):
    try:
        from hftbacktest import BacktestAsset, HashMapMarketDepthBacktest
    except Exception:
        return None

    asset = (
        BacktestAsset()
        .data([str(Path(market_data_path))])
        .linear_asset(1.0)
        .constant_order_latency(0, 0)
        .power_prob_queue_model(2.0)
        .no_partial_fill_exchange()
        .trading_value_fee_model(0.0, 0.0)
        .tick_size(float(tick_size))
        .lot_size(float(lot_size))
    )
    return HashMapMarketDepthBacktest([asset])


def _augment_submission_snapshot(
    base_snapshot, depth, quotes, tick_size: float, fallback_snapshot=None
):
    if base_snapshot is None:
        return None
    if not getattr(base_snapshot, "bids", None) or not getattr(base_snapshot, "asks", None):
        return base_snapshot
    base_best_bid = float(base_snapshot.bids[0][0])
    base_best_ask = float(base_snapshot.asks[0][0])
    depth_usable = False
    if depth is not None:
        probe_best_bid = float(depth.best_bid)
        probe_best_ask = float(depth.best_ask)
        if _is_finite_book(probe_best_bid, probe_best_ask):
            depth_usable = (
                abs(base_best_bid - probe_best_bid) <= 1e-12
                and abs(base_best_ask - probe_best_ask) <= 1e-12
            )

    bid_levels = [(float(price), float(qty)) for price, qty in base_snapshot.bids]
    ask_levels = [(float(price), float(qty)) for price, qty in base_snapshot.asks]
    seen_bid_ticks = {_price_tick(price, tick_size) for price, _ in bid_levels}
    seen_ask_ticks = {_price_tick(price, tick_size) for price, _ in ask_levels}

    def _snapshot_level_qty(levels, target_tick: int) -> float:
        if not levels:
            return 0.0
        for level_price, level_qty in levels:
            if _price_tick(level_price, tick_size) == target_tick:
                return float(level_qty)
        return 0.0

    for side, price_tick, price in _normalize_quotes(quotes, tick_size=tick_size):
        if side == "buy":
            if price_tick in seen_bid_ticks:
                continue
            qty = float(depth.bid_qty_at_tick(price_tick)) if depth_usable else 0.0
            if qty <= 0.0 and fallback_snapshot is not None:
                qty = _snapshot_level_qty(getattr(fallback_snapshot, "bids", None), price_tick)
            if qty > 0.0:
                bid_levels.append((price, qty))
                seen_bid_ticks.add(price_tick)
            continue
        if price_tick in seen_ask_ticks:
            continue
        qty = float(depth.ask_qty_at_tick(price_tick)) if depth_usable else 0.0
        if qty <= 0.0 and fallback_snapshot is not None:
            qty = _snapshot_level_qty(getattr(fallback_snapshot, "asks", None), price_tick)
        if qty > 0.0:
            ask_levels.append((price, qty))
            seen_ask_ticks.add(price_tick)

    bid_levels.sort(key=lambda item: item[0], reverse=True)
    ask_levels.sort(key=lambda item: item[0])
    payload = dict(getattr(base_snapshot, "__dict__", {}))
    payload["bids"] = bid_levels
    payload["asks"] = ask_levels
    return SimpleNamespace(**payload)


def _advance_depth_probe(
    depth_probe, current_timestamp_ns: Optional[int], target_timestamp_ns: int
):
    if depth_probe is None:
        return current_timestamp_ns, None
    if current_timestamp_ns is None:
        current_timestamp_ns = int(getattr(depth_probe, "current_timestamp", 0) or 0)
    target_timestamp_ns = int(target_timestamp_ns)
    if target_timestamp_ns > current_timestamp_ns:
        status = depth_probe.elapse(target_timestamp_ns - current_timestamp_ns)
        current_timestamp_ns = target_timestamp_ns
        if status != 0:
            return current_timestamp_ns, None
    return current_timestamp_ns, depth_probe.depth(0)


def _augment_orderbook_snapshot_for_orders(base_snapshot, depth, pending_orders, tick_size: float):
    if base_snapshot is None:
        return None
    if depth is None:
        return base_snapshot
    if not getattr(base_snapshot, "bids", None) or not getattr(base_snapshot, "asks", None):
        return base_snapshot
    base_best_bid = float(base_snapshot.bids[0][0])
    base_best_ask = float(base_snapshot.asks[0][0])
    probe_best_bid = float(depth.best_bid)
    probe_best_ask = float(depth.best_ask)
    if not _is_finite_book(probe_best_bid, probe_best_ask):
        return base_snapshot
    if abs(base_best_bid - probe_best_bid) > 1e-12 or abs(base_best_ask - probe_best_ask) > 1e-12:
        return base_snapshot

    bid_levels = [(float(price), float(qty)) for price, qty in base_snapshot.bids]
    ask_levels = [(float(price), float(qty)) for price, qty in base_snapshot.asks]
    seen_bid_ticks = {_price_tick(price, tick_size) for price, _ in bid_levels}
    seen_ask_ticks = {_price_tick(price, tick_size) for price, _ in ask_levels}

    for order in pending_orders:
        if getattr(order, "_fill_role", None) != FillRole.MAKER:
            continue
        price = getattr(order, "price", None)
        if price is None:
            continue
        price = float(price)
        price_tick = _price_tick(price, tick_size)
        if order.isbuy():
            if price_tick in seen_bid_ticks:
                continue
            qty = float(depth.bid_qty_at_tick(price_tick))
            if qty > 0.0:
                bid_levels.append((price, qty))
                seen_bid_ticks.add(price_tick)
            continue
        if price_tick in seen_ask_ticks:
            continue
        qty = float(depth.ask_qty_at_tick(price_tick))
        if qty > 0.0:
            ask_levels.append((price, qty))
            seen_ask_ticks.add(price_tick)

    bid_levels.sort(key=lambda item: item[0], reverse=True)
    ask_levels.sort(key=lambda item: item[0])
    payload = dict(getattr(base_snapshot, "__dict__", {}))
    payload["bids"] = bid_levels
    payload["asks"] = ask_levels
    return SimpleNamespace(**payload)


def _submit_or_replace_quotes(
    broker,
    data,
    working_orders,
    quotes,
    order_qty: float,
    tick_size: float,
    snapshot,
    activation_timestamp_ns: int | None = None,
    activation_event_seq: int | None = None,
):
    working_orders = {
        key: order
        for key, order in working_orders.items()
        if order.alive() and order.status not in (Order.Canceled, Order.Rejected)
    }
    normalized = _normalize_quotes(quotes, tick_size=tick_size)
    target_keys = {(side, price_tick) for side, price_tick, _ in normalized}

    for key in list(working_orders):
        if key in target_keys:
            continue
        broker.cancel(working_orders[key])
        working_orders.pop(key, None)

    for side, price_tick, price in normalized:
        key = (side, price_tick)
        if key in working_orders:
            continue
        if side == "buy":
            order = broker.buy(
                owner=None, data=data, size=order_qty, price=price, exectype=Order.Limit
            )
        else:
            order = broker.sell(
                owner=None, data=data, size=order_qty, price=price, exectype=Order.Limit
            )
        order.time_in_force = "GTX"
        if activation_timestamp_ns is not None:
            order._active_after_timestamp_ns = int(activation_timestamp_ns)
        if activation_event_seq is not None:
            order._active_after_event_seq = int(activation_event_seq)
        if not _prime_backtrader_order(broker, order, snapshot):
            continue
        working_orders[key] = order
    return {
        key: order
        for key, order in working_orders.items()
        if order.alive() and order.status not in (Order.Canceled, Order.Rejected)
    }


def _prime_backtrader_order(broker, order, snapshot) -> bool:
    if snapshot is None or broker._exchange_model is None:
        return True
    if order.exectype not in (Order.Market, Order.Limit):
        return True
    exchange_result = broker._exchange_model.on_new_order(order, snapshot)
    if exchange_result.action == "REJECT":
        broker._remove_pending_order(order)
        order.addinfo(reject_reason=exchange_result.reject_reason)
        order.reject(broker)
        broker.notify(order)
        return False
    if exchange_result.action == "FILL":
        fill_price, fill_size = broker._aggregate_exchange_fills(exchange_result.fills)
        if fill_size > 0:
            broker._execute(order, fill_price, fill_size, snapshot, source="orderbook_depth")
        broker._remove_pending_order(order)
        return False
    return True


def _process_backtrader_depth_crosses(broker, data, ob_event) -> None:
    best_bid = ob_event.bids[0][0] if ob_event.bids else None
    best_ask = ob_event.asks[0][0] if ob_event.asks else None
    matched = []
    for order in list(broker._orders_by_symbol.get(data.name, [])):
        if getattr(order, "_fill_role", None) != FillRole.MAKER:
            continue
        if order.status in (
            Order.Canceled,
            Order.Rejected,
            Order.Completed,
            Order.Expired,
            Order.Margin,
        ):
            continue
        if order.isbuy():
            if best_ask is None or float(order.price) <= float(best_ask):
                continue
        else:
            if best_bid is None or float(order.price) >= float(best_bid):
                continue
        fill_size = broker._get_remaining_size(order)
        if fill_size <= 0:
            continue
        broker._execute(order, float(order.price), float(fill_size), ob_event, source="maker")
        matched.append(order)

    for order in matched:
        broker._remove_pending_order(order)


def _replace_hft_orders(
    hbt,
    quotes,
    tick_size: float,
    order_qty: float,
    buy_flag,
    sell_flag,
    gtx_flag,
    limit_flag,
    partial_filled_flag,
):
    target_keys = {
        (side, price_tick) for side, price_tick, _ in _normalize_quotes(quotes, tick_size=tick_size)
    }
    active_orders = {}
    values = hbt.orders(0).values()
    while True:
        order = values.next()
        if order is None:
            break
        side = "buy" if order.side == buy_flag else "sell"
        price_tick = int(round(float(order.price) / tick_size))
        active_orders[(side, price_tick)] = order
        if (side, price_tick) not in target_keys and order.cancellable:
            hbt.cancel(0, int(order.order_id), True)

    for side, price_tick, price in _normalize_quotes(quotes, tick_size=tick_size):
        if (side, price_tick) in active_orders:
            continue
        order_id = _order_id(side, price_tick)
        if side == "buy":
            hbt.submit_buy_order(0, order_id, price, order_qty, gtx_flag, limit_flag, True)
        else:
            hbt.submit_sell_order(0, order_id, price, order_qty, gtx_flag, limit_flag, True)


def _hft_order_key(order):
    return (
        int(order.order_id),
        int(getattr(order, "local_timestamp", 0)),
        int(getattr(order, "exch_timestamp", 0)),
        int(getattr(order, "side", 0)),
    )


def _collect_hft_fills(order_dict, seen_exec_qty, fills):
    values = order_dict.values()
    while True:
        order = values.next()
        if order is None:
            break
        key = _hft_order_key(order)
        exec_qty = float(order.exec_qty)
        previous = seen_exec_qty.get(key, 0.0)
        if exec_qty <= previous + 1e-12:
            continue
        fills.append(
            ComparisonFill(
                side="buy" if int(order.side) > 0 else "sell",
                price=float(order.exec_price),
                size=exec_qty - previous,
                timestamp_ns=int(getattr(order, "exch_timestamp", 0)) or None,
                local_timestamp_ns=int(getattr(order, "local_timestamp", 0)) or None,
                exch_timestamp_ns=int(getattr(order, "exch_timestamp", 0)) or None,
                order_ref=int(order.order_id),
            )
        )
        seen_exec_qty[key] = exec_qty


def _normalize_quotes(quotes, tick_size: float = 0.01):
    normalized = []
    seen = set()
    for side, value in quotes.items():
        prices = value if isinstance(value, (list, tuple)) else [value]
        for price in prices:
            price_tick = _price_tick(float(price), tick_size)
            key = (side, price_tick)
            if key in seen:
                continue
            seen.add(key)
            normalized_price = round(price_tick * tick_size, 12)
            normalized.append((side, price_tick, normalized_price))
    return normalized


def _price_tick(price: float, tick_size: float) -> int:
    return int(round(price / tick_size))


def _order_id(side: str, price_tick: int) -> int:
    return price_tick if side == "buy" else 1_000_000_000 + price_tick


def _is_finite_book(best_bid: float, best_ask: float) -> bool:
    return float(best_bid) == float(best_bid) and float(best_ask) == float(best_ask)


def _event_timestamp_ns(event) -> int:
    timestamp_ns = getattr(event, "timestamp_ns", None)
    if timestamp_ns is not None:
        return int(timestamp_ns)
    timestamp = getattr(event, "local_time", None) or getattr(event, "timestamp", 0.0)
    return int(round(float(timestamp) * 1_000_000_000.0))


def _market_data_exchange_anchor(market_data_path) -> Optional[float]:
    anchor_ns = _market_data_exchange_anchor_ns(market_data_path)
    if anchor_ns is None:
        return None
    return float(anchor_ns / 1_000_000_000.0)


def _market_data_exchange_anchor_ns(market_data_path) -> Optional[int]:
    try:
        with np.load(str(Path(market_data_path))) as payload:
            data = payload["data"]
            if len(data) == 0:
                return None
            return int(np.min(data["exch_ts"]))
    except Exception:
        return None


def _market_data_exchange_book(market_data_path):
    try:
        with np.load(str(Path(market_data_path))) as payload:
            data = payload["data"]
            if len(data) == 0:
                return None
            mask = (data["ev"] & np.uint64(_EXCH_EVENT) != 0) & (
                data["ev"] & np.uint64(_DEPTH_EVENT) != 0
            )
            rows = data[mask]
            if len(rows) == 0:
                return None
            order = np.argsort(rows["exch_ts"], kind="mergesort")
            rows = rows[order]
            exch_ts = []
            best_bids = []
            best_asks = []
            best_bid = None
            best_ask = None
            for row in rows:
                ev = int(row["ev"])
                if ev & _BUY_EVENT:
                    best_bid = float(row["px"])
                elif ev & _SELL_EVENT:
                    best_ask = float(row["px"])
                if best_bid is None or best_ask is None:
                    continue
                exch_ts.append(int(row["exch_ts"]))
                best_bids.append(best_bid)
                best_asks.append(best_ask)
            if not exch_ts:
                return None
            return (exch_ts, best_bids, best_asks)
    except Exception:
        return None


def _lookup_exchange_snapshot(exchange_book, timestamp_ns: int):
    if exchange_book is None:
        return None
    exch_ts, best_bids, best_asks = exchange_book
    index = bisect.bisect_right(exch_ts, int(timestamp_ns)) - 1
    if index < 0:
        return None
    return SimpleNamespace(
        bids=[(float(best_bids[index]), 0.0)],
        asks=[(float(best_asks[index]), 0.0)],
    )
