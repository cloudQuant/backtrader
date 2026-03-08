"""Test doubles for the unified bt_api_py integration surface."""

from __future__ import annotations

import collections
import datetime as dt
from copy import deepcopy
from typing import Any, Dict, Iterable, Optional

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


class FakeBtApiClient:
    """Minimal bt_api_py-compatible client for store/broker/feed tests."""

    def __init__(
        self,
        balance: Optional[Dict[str, float]] = None,
        positions: Optional[Iterable[Dict[str, Any]]] = None,
        history: Optional[Dict[str, Iterable[Dict[str, Any]]]] = None,
        live: Optional[Dict[str, Iterable[Dict[str, Any]]]] = None,
    ):
        self.balance = dict(balance or {"cash": 10000.0, "value": 10000.0})
        self.positions = list(positions or [])
        self.history = {key: list(value) for key, value in (history or {}).items()}
        self.live = {
            key: collections.deque(value) for key, value in (live or {}).items()
        }
        self.connected = False
        self.subscriptions = []
        self.submitted_orders = []
        self.cancelled_orders = []

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

    def poll_bar(self, dataname: str):
        """Return the next live bar for a symbol."""
        queue = self.live.get(dataname)
        if not queue:
            return None
        return deepcopy(queue.popleft())

    def submit_order(self, payload: Dict[str, Any]):
        """Record a submitted order and return an external id."""
        self.submitted_orders.append(dict(payload))
        return {"id": f"btapi-{len(self.submitted_orders)}"}

    def cancel_order(self, order_ref, dataname: Optional[str] = None):
        """Record an order cancellation."""
        self.cancelled_orders.append({"order_ref": order_ref, "dataname": dataname})
        return True


def make_store(
    api: Optional[FakeBtApiClient] = None,
    provider: str = "okx",
    **kwargs,
) -> BtApiStore:
    """Build a BtApiStore backed by a fake client."""
    return BtApiStore(provider=provider, api=api or FakeBtApiClient(), **kwargs)
