"""Test doubles for the unified bt_api_py integration surface."""

from __future__ import annotations

import collections
import datetime as dt
from copy import deepcopy
from typing import Any, Dict, Iterable, Optional

from backtrader.events import OrderBookSnapshot, TickEvent
from backtrader.stores.btapistore import BtApiStore

DEFAULT_SYMBOL = "BTC/USDT"


def make_bar(
    offset_minutes: int,
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
    volume: float = 1.0,
) -> Dict[str, Any]:
    """Create a deterministic OHLCV bar payload for tests."""
    base = dt.datetime(2024, 1, 1, 0, 0, 0)
    return {
        "datetime": base + dt.timedelta(minutes=offset_minutes),
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "volume": volume,
        "openinterest": 0.0,
    }


def make_tick(
    offset_seconds: int,
    price: float,
    volume: float = 1.0,
    symbol: str = DEFAULT_SYMBOL,
    direction: str = "buy",
) -> TickEvent:
    """Create a deterministic live tick event payload for tests."""
    base = dt.datetime(2024, 1, 1, 9, 0, 0, tzinfo=dt.timezone.utc)
    event = TickEvent(
        timestamp=(base + dt.timedelta(seconds=offset_seconds)).timestamp(),
        symbol=symbol,
        exchange="fake",
        asset_type="futures",
        local_time=(base + dt.timedelta(seconds=offset_seconds)).timestamp(),
        price=price,
        volume=volume,
        direction=direction,
        trade_id=f"tick-{offset_seconds}",
        bid_price=price - 0.5,
        ask_price=price + 0.5,
        bid_volume=volume,
        ask_volume=volume,
    )
    event.datetime = (base + dt.timedelta(seconds=offset_seconds)).replace(tzinfo=None)
    event.openinterest = 0.0
    return event


def make_orderbook(
    offset_seconds: int,
    bid_price: float,
    ask_price: float,
    bid_volume: float = 1.0,
    ask_volume: float = 1.0,
    symbol: str = DEFAULT_SYMBOL,
) -> OrderBookSnapshot:
    base = dt.datetime(2024, 1, 1, 9, 0, 0, tzinfo=dt.timezone.utc)
    event = OrderBookSnapshot(
        timestamp=(base + dt.timedelta(seconds=offset_seconds)).timestamp(),
        symbol=symbol,
        exchange="fake",
        asset_type="futures",
        local_time=(base + dt.timedelta(seconds=offset_seconds)).timestamp(),
        bids=[(bid_price, bid_volume)],
        asks=[(ask_price, ask_volume)],
    )
    event.datetime = (base + dt.timedelta(seconds=offset_seconds)).replace(tzinfo=None)
    return event


class FakeBtApiClient:
    """Minimal bt_api_py-compatible client for store/broker/feed tests."""

    def __init__(
        self,
        balance: Optional[Dict[str, float]] = None,
        positions: Optional[Iterable[Dict[str, Any]]] = None,
        history: Optional[Dict[str, Iterable[Dict[str, Any]]]] = None,
        live: Optional[Dict[str, Iterable[Dict[str, Any]]]] = None,
        live_ticks: Optional[Dict[str, Iterable[TickEvent]]] = None,
        live_orderbooks: Optional[Dict[str, Iterable[OrderBookSnapshot]]] = None,
        open_orders: Optional[Iterable[Dict[str, Any]]] = None,
        broker_updates: Optional[Iterable[Dict[str, Any]]] = None,
    ):
        self.balance = dict(balance or {"cash": 10000.0, "value": 10000.0})
        self.positions = list(positions or [])
        self.history = {key: list(value) for key, value in (history or {}).items()}
        self.live = {
            key: collections.deque(value) for key, value in (live or {}).items()
        }
        self.live_ticks = {
            key: collections.deque(deepcopy(list(value))) for key, value in (live_ticks or {}).items()
        }
        self.live_orderbooks = {
            key: collections.deque(deepcopy(list(value)))
            for key, value in (live_orderbooks or {}).items()
        }
        self.open_orders = deepcopy(list(open_orders or []))
        self.connected = False
        self.subscriptions = []
        self.submitted_orders = []
        self.cancelled_orders = []
        self.broker_updates = collections.deque(deepcopy(list(broker_updates or [])))

    def connect(self):
        """Simulate opening a connection."""
        self.connected = True

    def disconnect(self):
        """Simulate closing a connection."""
        self.connected = False

    def get_balance(self):
        """Return account balance payload."""
        return dict(self.balance)

    def get_positions(self):
        """Return current open positions."""
        return list(self.positions)

    def subscribe(self, dataname: str):
        """Record subscriptions for assertions."""
        self.subscriptions.append(dataname)

    def fetch_bars(self, dataname: str, **_kwargs):
        """Return historical bars for a symbol."""
        return deepcopy(self.history.get(dataname, []))

    def fetch_open_orders(self):
        """Return the provider's open orders payload."""
        return deepcopy(self.open_orders)

    def poll_bar(self, dataname: str):
        """Return the next live bar for a symbol."""
        queue = self.live.get(dataname)
        if not queue:
            return None
        return deepcopy(queue.popleft())

    def poll_tick(self, dataname: str):
        """Return the next live tick for a symbol."""
        queue = self.live_ticks.get(dataname)
        if not queue:
            return None
        return deepcopy(queue.popleft())

    def poll_orderbook(self, dataname: str):
        queue = self.live_orderbooks.get(dataname)
        if not queue:
            return None
        return deepcopy(queue.popleft())

    def has_pending_tick(self, dataname: str):
        """Return whether a symbol has queued live ticks."""
        queue = self.live_ticks.get(dataname)
        return bool(queue)

    def has_pending_orderbook(self, dataname: str):
        queue = self.live_orderbooks.get(dataname)
        return bool(queue)

    def supports_live_ticks(self, dataname: str):
        """Return whether a symbol is configured for live tick streaming."""
        return dataname in self.live_ticks

    def supports_live_orderbook(self, dataname: str):
        return dataname in self.live_orderbooks

    def submit_order(self, payload: Dict[str, Any]):
        """Record a submitted order and return an external id."""
        self.submitted_orders.append(dict(payload))
        return {"id": f"btapi-{len(self.submitted_orders)}"}

    def cancel_order(self, order_ref, dataname: Optional[str] = None):
        """Record an order cancellation."""
        self.cancelled_orders.append({"order_ref": order_ref, "dataname": dataname})
        return True

    def poll_broker_update(self):
        """Return the next queued broker-side update."""
        if not self.broker_updates:
            return None
        return deepcopy(self.broker_updates.popleft())

    def push_broker_update(self, update: Dict[str, Any]):
        """Append a broker-side update for later polling."""
        self.broker_updates.append(deepcopy(update))


def make_store(
    api: Optional[FakeBtApiClient] = None,
    provider: str = "okx",
    **kwargs,
) -> BtApiStore:
    """Build a BtApiStore backed by a fake client."""
    return BtApiStore(provider=provider, api=api or FakeBtApiClient(), **kwargs)
