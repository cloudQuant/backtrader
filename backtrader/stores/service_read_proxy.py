"""Read-only bridge from typed service facades to Backtrader Store/Broker/Feed.

This optional adapter imports only neutral bt_api_base contracts. It does not
construct runtimes, discover providers, or expose execution methods.
"""

from __future__ import annotations

import math
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any

from bt_api_base.account_protocol import (
    AccountKey,
    AccountOpenOrder,
    AccountObservation,
    AccountPosition,
    AccountResourceKey,
)
from bt_api_base.market_history_protocol import MarketBar, MarketHistoryPage, MarketHistoryRequest
from bt_api_base.market_protocol import (
    MARKET_EVENT_OPERATION,
    MARKET_EVENT_SCHEMA,
    MARKET_EVENT_SCHEMA_VERSION,
    MarketInstrumentKey,
    MarketSubscriptionKey,
)
from bt_api_base.service_protocol import (
    WireEnvelope,
    WireMessageKind,
    WireScope,
    validate_event,
)

from ..dataseries import TimeFrame


class ServiceReadProxyError(RuntimeError):
    """Finite local diagnostics for a rejected read-only projection."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code or not code.isascii():
            raise ValueError("code must be a finite ASCII identifier")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ServiceFeedBinding:
    """Explicit binding from a Backtrader dataname to one market service feed."""

    market_client: Any
    resource: AccountResourceKey
    qty_unit: str
    timeframe: str
    quantity_multiplier: str = "1"
    history_start_utc: str | None = None
    history_end_utc: str | None = None

    def __post_init__(self) -> None:
        if type(self.resource) is not AccountResourceKey:
            raise TypeError("resource must be an AccountResourceKey")
        _check_text(self.qty_unit, "qty_unit")
        _timeframe_seconds(self.timeframe)
        if self.timeframe.endswith("w"):
            raise ValueError(
                "weekly feeds are unsupported without an explicit calendar-week anchor"
            )
        multiplier = _decimal(self.quantity_multiplier, "quantity_multiplier")
        if multiplier <= 0:
            raise ValueError("quantity_multiplier must be positive")
        key = getattr(self.market_client, "key", None)
        if type(key) is not MarketSubscriptionKey:
            raise TypeError("market_client.key must be a MarketSubscriptionKey")
        if type(getattr(self.market_client, "stream_scope", None)) is not WireScope:
            raise TypeError("market_client.stream_scope must be a WireScope")
        for method in ("start", "history", "poll", "close"):
            if not callable(getattr(self.market_client, method, None)):
                raise TypeError(f"market_client must provide {method}()")
        if key.channel != "bar" or key.timeframe != self.timeframe:
            raise ValueError("market client must bind the configured fixed bar timeframe")
        if key.depth is not None:
            raise ValueError("bar feed key must not declare depth")
        if key.instrument.product_type != self.resource.product_type:
            raise ValueError("feed resource product_type must match its instrument")
        if (self.history_start_utc is None) != (self.history_end_utc is None):
            raise ValueError("history_start_utc and history_end_utc must be supplied together")
        if self.history_start_utc is not None:
            start = _parse_utc(self.history_start_utc, "history_start_utc")
            end = _parse_utc(self.history_end_utc, "history_end_utc")
            if start >= end:
                raise ValueError("history start must precede history end")


@dataclass(frozen=True)
class ServiceCtpTickBinding:
    """Explicit binding for an unmodified provider ``ctp.quote.v2`` tick stream."""

    market_client: Any
    resource: AccountResourceKey
    qty_unit: str
    clock_domain_id: str
    quantity_multiplier: str = "1"

    def __post_init__(self) -> None:
        if type(self.resource) is not AccountResourceKey:
            raise TypeError("resource must be an AccountResourceKey")
        _check_text(self.qty_unit, "qty_unit")
        _check_text(self.clock_domain_id, "clock_domain_id")
        if _decimal(self.quantity_multiplier, "quantity_multiplier") <= 0:
            raise ValueError("quantity_multiplier must be positive")
        key = getattr(self.market_client, "key", None)
        if type(key) is not MarketSubscriptionKey:
            raise TypeError("market_client.key must be a MarketSubscriptionKey")
        if type(getattr(self.market_client, "stream_scope", None)) is not WireScope:
            raise TypeError("market_client.stream_scope must be a WireScope")
        for method in ("start", "poll", "close"):
            if not callable(getattr(self.market_client, method, None)):
                raise TypeError(f"market_client must provide {method}()")
        if key.channel != "ctp.quote.v2" or key.timeframe is not None or key.depth is not None:
            raise ValueError("CTP quote binding requires the fixed ctp.quote.v2 event channel")
        if key.instrument.product_type != self.resource.product_type:
            raise ValueError("feed resource product_type must match its instrument")


class ServiceReadProxy:
    """Borrowed-facade adapter implementing the observation-only Store API."""

    service_read_only = True
    read_only = True

    def __init__(
        self,
        account_client: Any,
        feeds: Mapping[str, ServiceFeedBinding | ServiceCtpTickBinding],
        *,
        valuation_currency: str,
        position_mode: str,
        history_page_size: int = 1000,
        max_history_pages: int = 100,
        max_history_rows: int = 50000,
        default_history_limit: int = 500,
        clock: Any = None,
    ) -> None:
        if not callable(getattr(account_client, "refresh", None)) or not callable(
            getattr(account_client, "snapshot", None)
        ):
            raise TypeError("account_client must provide refresh() and snapshot()")
        if not callable(getattr(account_client, "close", None)):
            raise TypeError("account_client must provide close()")
        if getattr(account_client, "require_open_orders", None) is not True:
            raise ValueError("account_client must require complete open orders")
        expected_account = getattr(account_client, "expected_account", None)
        if type(expected_account) is not AccountKey:
            raise TypeError("account_client.expected_account must be an AccountKey")
        coverage = getattr(account_client, "required_coverage", None)
        if type(coverage) is not tuple or not coverage:
            raise TypeError("account_client.required_coverage must be a non-empty tuple")
        if any(type(item) is not AccountResourceKey for item in coverage):
            raise TypeError("account coverage entries must be AccountResourceKey values")
        if len(set(coverage)) != len(coverage):
            raise ValueError("account coverage must not contain duplicates")
        if not isinstance(feeds, Mapping) or not feeds:
            raise TypeError("feeds must be a non-empty mapping")
        copied: dict[str, ServiceFeedBinding | ServiceCtpTickBinding] = {}
        market_clients: set[int] = set()
        for dataname, binding in feeds.items():
            _check_text(dataname, "dataname")
            if type(binding) not in {ServiceFeedBinding, ServiceCtpTickBinding}:
                raise TypeError(
                    "feed mappings must contain ServiceFeedBinding or ServiceCtpTickBinding values"
                )
            if id(binding.market_client) in market_clients:
                raise ValueError("each feed requires its own market client")
            market_clients.add(id(binding.market_client))
            if binding.resource not in coverage:
                raise ValueError("feed resource is outside the account client's coverage")
            copied[dataname] = binding
        if id(account_client) in market_clients:
            raise ValueError("account and market service clients must be distinct facades")
        _check_text(valuation_currency, "valuation_currency")
        if type(position_mode) is not str or position_mode not in {"net", "dual_side"}:
            raise ValueError("position_mode must be net or dual_side")
        if type(history_page_size) is not int or not 1 <= history_page_size <= 1000:
            raise ValueError("history_page_size must be between 1 and 1000")
        if type(max_history_pages) is not int or not 1 <= max_history_pages <= 10000:
            raise ValueError("max_history_pages must be positive and bounded")
        if type(max_history_rows) is not int or not 1 <= max_history_rows <= 1000000:
            raise ValueError("max_history_rows must be positive and bounded")
        if (
            type(default_history_limit) is not int
            or not 1 <= default_history_limit <= max_history_rows
        ):
            raise ValueError("default_history_limit must fit max_history_rows")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")

        self._account_client = account_client
        self._expected_account = expected_account
        self._required_coverage = frozenset(coverage)
        self._feeds = MappingProxyType(copied)
        self._valuation_currency = valuation_currency
        self._position_mode = position_mode
        self._history_page_size = history_page_size
        self._max_history_pages = max_history_pages
        self._max_history_rows = max_history_rows
        self._default_history_limit = default_history_limit
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._owner_thread_id = threading.get_ident()
        self._connected = False
        self._closed = False
        self._closing = False
        self._closed_facade_ids: set[int] = set()
        self._started_clients: set[str] = set()
        self._stream_epochs: dict[str, str] = {}
        self._last_sequences: dict[str, int] = {}
        self._bootstrap_bars: dict[str, dict[str, Any]] = {}
        self._bootstrap_ticks: dict[str, dict[str, Any]] = {}
        self._ctp_tick_scopes: dict[str, tuple[int, int]] = {}
        self._ctp_tick_sequences: dict[str, int] = {}
        self._pending_bars: dict[str, dict[str, Any]] = {}
        self._history_by_open: dict[str, dict[str, tuple[Any, ...]]] = {}
        self._last_emitted_open: dict[str, str] = {}
        self._last_emitted_identity: dict[str, tuple[Any, ...]] = {}
        self._position_bindings: dict[tuple[AccountResourceKey, MarketInstrumentKey], str] = {}
        for dataname, binding in copied.items():
            map_key = (binding.resource, binding.market_client.key.instrument)
            if map_key in self._position_bindings:
                raise ValueError("each account instrument/resource needs one position feed mapping")
            self._position_bindings[map_key] = dataname

    @property
    def is_connected(self) -> bool:
        return self._connected and not self._closed and not self._closing

    def connect(self) -> None:
        """Read and validate one complete provider account snapshot."""
        self._assert_owner()
        if self._closed:
            raise ServiceReadProxyError("PROXY_CLOSED")
        if self._closing:
            raise ServiceReadProxyError("PROXY_CLOSING")
        if self._connected:
            return
        view = self._account_client.refresh()
        self._validate_observation(getattr(view, "observation", None))
        self._connected = True

    start = connect

    def disconnect(self) -> None:
        """Close only injected facades; their shared runtime remains caller-owned."""
        self._assert_owner()
        if self._closed:
            return
        self._closing = True
        errors: list[BaseException] = []
        for binding in self._feeds.values():
            facade_id = id(binding.market_client)
            if facade_id in self._closed_facade_ids:
                continue
            try:
                binding.market_client.close()
            except BaseException as exc:
                errors.append(exc)
            else:
                self._closed_facade_ids.add(facade_id)
        account_id = id(self._account_client)
        if account_id not in self._closed_facade_ids:
            try:
                self._account_client.close()
            except BaseException as exc:
                errors.append(exc)
            else:
                self._closed_facade_ids.add(account_id)
        if errors:
            self._connected = True
            raise errors[0]
        self._connected = False
        self._closed = True
        self._closing = False

    close = disconnect

    def supports_position_mode(self, mode: str) -> bool:
        return type(mode) is str and mode == self._position_mode

    def supports_live_streaming(self, dataname: str) -> bool:
        """Tell BtApiFeed that this explicitly bound facade has a live poll."""
        return type(dataname) is str and dataname in self._feeds

    def get_balance(self) -> dict[str, float]:
        observation = self._current_observation()
        valuation = observation.valuation
        if (
            valuation is None
            or valuation.currency != self._valuation_currency
            or valuation.available_cash is None
            or valuation.equity is None
        ):
            raise ServiceReadProxyError("VALUATION_UNAVAILABLE")
        cash = _finite_float(valuation.available_cash, "available_cash")
        equity = _finite_float(valuation.equity, "equity")
        return {"cash": cash, "value": equity}

    def get_positions(self) -> list[dict[str, Any]]:
        observation = self._current_observation()
        if not observation.positions_complete:
            raise ServiceReadProxyError("POSITIONS_INCOMPLETE")
        rows: list[dict[str, Any]] = []
        for position in observation.positions:
            if type(position) is not AccountPosition:
                raise ServiceReadProxyError("POSITION_INVALID")
            dataname, binding = self._position_binding(position.resource, position.instrument)
            if position.qty_unit != binding.qty_unit:
                raise ServiceReadProxyError("POSITION_UNIT_MISMATCH")
            raw_quantity = _decimal(position.quantity, "position quantity")
            if self._position_mode == "dual_side" and raw_quantity < 0:
                raise ServiceReadProxyError("POSITION_QUANTITY_INVALID")
            size = _finite_float(
                raw_quantity * _decimal(binding.quantity_multiplier, "quantity_multiplier"),
                "position quantity",
            )
            if self._position_mode == "net":
                if position.side != "net":
                    raise ServiceReadProxyError("POSITION_MODE_MISMATCH")
                direction = "short" if size < 0 else "long"
            else:
                if position.side not in {"long", "short"}:
                    raise ServiceReadProxyError("POSITION_MODE_MISMATCH")
                direction = position.side
                size = abs(size)
            if size and position.average_price is None:
                raise ServiceReadProxyError("POSITION_PRICE_UNKNOWN")
            price = (
                0.0
                if position.average_price is None
                else _finite_float(position.average_price, "average_price")
            )
            rows.append(
                {
                    "data_name": dataname,
                    "symbol": position.instrument.native_symbol,
                    "volume": abs(size),
                    "size": size,
                    "direction": direction,
                    "price": price,
                    "qty_unit": position.qty_unit,
                    "price_currency": position.price_currency,
                    "resource": position.resource.to_dict(),
                    "position_side": position.side,
                }
            )
        return rows

    def fetch_open_orders(self) -> list[dict[str, Any]]:
        observation = self._current_observation()
        if observation.open_orders is None or not observation.open_orders_complete:
            raise ServiceReadProxyError("OPEN_ORDERS_INCOMPLETE")
        rows: list[dict[str, Any]] = []
        for order in observation.open_orders:
            if type(order) is not AccountOpenOrder:
                raise ServiceReadProxyError("OPEN_ORDER_INVALID")
            dataname, binding = self._position_binding(order.resource, order.instrument)
            if order.qty_unit != binding.qty_unit:
                raise ServiceReadProxyError("ORDER_UNIT_MISMATCH")
            if (self._position_mode == "net" and order.position_side != "net") or (
                self._position_mode == "dual_side" and order.position_side == "net"
            ):
                raise ServiceReadProxyError("ORDER_POSITION_MODE_MISMATCH")
            multiplier = _decimal(binding.quantity_multiplier, "quantity_multiplier")
            amount = _finite_float(
                _decimal(order.quantity, "order quantity") * multiplier,
                "quantity",
            )
            filled = _finite_float(
                _decimal(order.filled_quantity, "filled quantity") * multiplier,
                "filled_quantity",
            )
            rows.append(
                {
                    "data_name": dataname,
                    "symbol": order.instrument.native_symbol,
                    "order_id": order.order_id,
                    "external_order_id": order.order_id,
                    "client_order_id": order.client_order_id,
                    "side": order.side,
                    "position_side": order.position_side,
                    "order_type": order.order_type,
                    "status": order.status,
                    "quantity": amount,
                    "filled_quantity": filled,
                    "qty_unit": order.qty_unit,
                    "created_at_utc": order.created_at_utc,
                    "observed_at_utc": order.observed_at_utc,
                    "limit_price": _optional_float(order.limit_price, "limit_price"),
                    "stop_price": _optional_float(order.stop_price, "stop_price"),
                    "price_currency": order.price_currency,
                    "reduce_only": order.reduce_only,
                    "resource": order.resource.to_dict(),
                }
            )
        return rows

    def subscribe(self, dataname: str) -> None:
        self._assert_connected()
        binding = self._binding(dataname)
        if dataname in self._started_clients:
            return
        client = binding.market_client
        bootstrap = client.start()
        if (
            getattr(client, "healthy", None) is not True
            or getattr(client, "recovery_required", None) is not False
        ):
            raise ServiceReadProxyError("MARKET_START_UNHEALTHY")
        key = client.key
        if type(key) is not MarketSubscriptionKey:
            raise ServiceReadProxyError("MARKET_KEY_INVALID")
        is_tick_binding = type(binding) is ServiceCtpTickBinding
        if (is_tick_binding and key.channel != "ctp.quote.v2") or (
            not is_tick_binding and key.channel != "bar"
        ):
            raise ServiceReadProxyError("MARKET_KEY_INVALID")
        epoch = getattr(bootstrap, "snapshot_epoch", None)
        sequence = getattr(bootstrap, "snapshot_sequence", None)
        if (
            type(epoch) is not str
            or not epoch
            or type(sequence) is not int
            or sequence < 0
            or getattr(bootstrap, "stream_id", None) != key.stream_id
            or getattr(bootstrap, "resync_required", None) is not False
            or getattr(bootstrap, "snapshot_kind", None) != "latest_event"
            or getattr(bootstrap, "snapshot_complete", None) is not False
            or getattr(bootstrap, "full_baseline_available", None) is not False
        ):
            raise ServiceReadProxyError("MARKET_BOOTSTRAP_INVALID")
        self._stream_epochs[dataname] = epoch
        self._last_sequences[dataname] = sequence
        snapshot = getattr(bootstrap, "snapshot", None)
        if snapshot is not None:
            if sequence == 0:
                raise ServiceReadProxyError("MARKET_BOOTSTRAP_INVALID")
            if is_tick_binding:
                self._bootstrap_ticks[dataname] = self._event_tick(
                    dataname, snapshot, expected_sequence=sequence
                )
            else:
                self._bootstrap_bars[dataname] = self._event_bar(
                    dataname, snapshot, expected_sequence=sequence
                )
        elif sequence != 0:
            raise ServiceReadProxyError("MARKET_BOOTSTRAP_INVALID")
        self._started_clients.add(dataname)

    def fetch_bars(
        self,
        dataname: str,
        *,
        timeframe: Any = None,
        compression: int = 1,
        since: Any = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Read bounded, paginated history after the market stream is started."""
        self._assert_connected()
        binding = self._binding(dataname)
        if type(binding) is ServiceCtpTickBinding:
            raise ServiceReadProxyError("CTP_TICK_HISTORY_UNSUPPORTED")
        if dataname not in self._started_clients:
            raise ServiceReadProxyError("MARKET_NOT_SUBSCRIBED")
        requested_timeframe = _backtrader_timeframe(timeframe, compression)
        if _timeframe_seconds(requested_timeframe) != _timeframe_seconds(binding.timeframe):
            raise ServiceReadProxyError("TIMEFRAME_MISMATCH")
        if limit is None:
            total_limit = self._default_history_limit
        elif type(limit) is int and 1 <= limit <= self._max_history_rows:
            total_limit = limit
        else:
            raise ServiceReadProxyError("HISTORY_LIMIT_INVALID")
        duration = _timeframe_seconds(binding.timeframe)
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ServiceReadProxyError("CLOCK_INVALID")
        now = now.astimezone(timezone.utc)
        if binding.history_end_utc is None:
            end = _floor_time(now, duration)
            start = end - timedelta(seconds=duration * total_limit)
            if since is not None:
                start = max(start, _floor_time(_parse_since(since), duration))
        else:
            start = _parse_utc(binding.history_start_utc, "history_start_utc")
            end = _parse_utc(binding.history_end_utc, "history_end_utc")
            if since is not None:
                start = max(start, _floor_time(_parse_since(since), duration))
        if start >= end or end > now:
            raise ServiceReadProxyError("HISTORY_WINDOW_INVALID")
        if _epoch_seconds(start) % duration or _epoch_seconds(end) % duration:
            raise ServiceReadProxyError("HISTORY_WINDOW_UNALIGNED")

        rows: list[dict[str, Any]] = []
        cursor = start
        pages = 0
        previous_open: datetime | None = None
        previous_close: datetime | None = None
        page: MarketHistoryPage | None = None
        while cursor < end:
            if pages >= self._max_history_pages:
                raise ServiceReadProxyError("HISTORY_PAGE_LIMIT")
            remaining = total_limit - len(rows)
            if remaining <= 0:
                raise ServiceReadProxyError("HISTORY_ROW_LIMIT")
            page_limit = min(self._history_page_size, remaining)
            request = MarketHistoryRequest(
                key=binding.market_client.key,
                start_time_utc=_format_utc(cursor),
                end_time_utc=_format_utc(end),
                limit=page_limit,
            )
            page = binding.market_client.history(request)
            pages += 1
            if type(page) is not MarketHistoryPage or page.request != request:
                raise ServiceReadProxyError("HISTORY_PAGE_INVALID")
            if len(page.bars) > page_limit or len(rows) + len(page.bars) > total_limit:
                raise ServiceReadProxyError("HISTORY_ROW_LIMIT")
            for bar in page.bars:
                if type(bar) is not MarketBar:
                    raise ServiceReadProxyError("HISTORY_BAR_INVALID")
                opened = _parse_utc(bar.open_time_utc, "open_time_utc")
                closed = _parse_utc(bar.close_time_utc, "close_time_utc")
                _validate_bar_interval(binding, opened, closed, now=now)
                if previous_open is not None and opened <= previous_open:
                    raise ServiceReadProxyError("HISTORY_ORDER_INVALID")
                if previous_close is not None and opened < previous_close:
                    raise ServiceReadProxyError("HISTORY_OVERLAP")
                previous_open, previous_close = opened, closed
                rows.append(_bar_to_dict(bar))
            if page.complete:
                break
            next_start = _parse_utc(page.next_start_time_utc, "next_start_time_utc")
            if next_start <= cursor or next_start >= end or next_start != previous_close:
                raise ServiceReadProxyError("HISTORY_CURSOR_INVALID")
            cursor = next_start
        if page is None or not page.complete:
            raise ServiceReadProxyError("HISTORY_PAGE_LIMIT")

        by_open: dict[str, tuple[Any, ...]] = {}
        for row in rows:
            open_key = row["timestamp"]
            identity = _bar_identity(row)
            if open_key in by_open:
                if by_open[open_key] != identity:
                    raise ServiceReadProxyError("HISTORY_BAR_CONFLICT")
                raise ServiceReadProxyError("HISTORY_DUPLICATE_BAR")
            by_open[open_key] = identity
        self._history_by_open[dataname] = by_open

        latest = self._bootstrap_bars.pop(dataname, None)
        if latest is not None:
            opened = latest["timestamp"]
            found = by_open.get(opened)
            if found is not None:
                if found != _bar_identity(latest):
                    raise ServiceReadProxyError("HISTORY_LIVE_CONFLICT")
            elif rows and _parse_utc(opened, "open_time_utc") <= _parse_utc(
                rows[-1]["timestamp"], "open_time_utc"
            ):
                raise ServiceReadProxyError("HISTORY_LIVE_ORDER_INVALID")
            else:
                self._pending_bars[dataname] = latest
        if rows:
            self._last_emitted_open[dataname] = rows[-1]["timestamp"]
            self._last_emitted_identity[dataname] = _bar_identity(rows[-1])
        return rows

    def poll_bar(self, dataname: str) -> dict[str, Any] | None:
        """Return one ordered closed bar; never silently recover from a stream gap."""
        self._assert_connected()
        binding = self._binding(dataname)
        if type(binding) is ServiceCtpTickBinding:
            if dataname not in self._started_clients:
                raise ServiceReadProxyError("MARKET_NOT_SUBSCRIBED")
            self._assert_market_stream_healthy(binding)
            # BtApiFeed polls for a bar after draining the tick route. A tick-only
            # binding has no bar result, so an idle None keeps the normal Feed loop
            # running without reading Kline history or synthesizing a bar.
            return None
        if dataname not in self._started_clients:
            raise ServiceReadProxyError("MARKET_NOT_SUBSCRIBED")
        pending = self._pending_bars.get(dataname)
        if pending is not None:
            del self._pending_bars[dataname]
            return self._remember_emitted(dataname, pending)
        self._assert_market_stream_healthy(binding)
        event = binding.market_client.poll(timeout_ms=0)
        self._assert_market_stream_healthy(binding)
        if event is None:
            return None
        sequence = self._last_sequences[dataname] + 1
        bar = self._event_bar(dataname, event, expected_sequence=sequence)
        self._last_sequences[dataname] = event.header.sequence
        open_time = bar["timestamp"]
        identity = _bar_identity(bar)
        last_open = self._last_emitted_open.get(dataname)
        if last_open is not None and _parse_utc(open_time, "open_time_utc") < _parse_utc(
            last_open, "last_emitted_open"
        ):
            raise ServiceReadProxyError("LIVE_BAR_OUT_OF_ORDER")
        previous = self._history_by_open.get(dataname, {}).get(open_time)
        if previous is not None:
            if previous != identity:
                raise ServiceReadProxyError("HISTORY_LIVE_CONFLICT")
            return None
        return self._remember_emitted(dataname, bar)

    def poll_tick(self, dataname: str) -> dict[str, Any] | None:
        """Return one original CTP V2 tick after validating transport and source identity."""
        self._assert_connected()
        binding = self._binding(dataname)
        if type(binding) is ServiceFeedBinding:
            # BtApiFeed may probe for ticks while consuming a bar service feed.
            # This binding has no tick capability, so preserve the normal idle
            # result and keep its bar polling path independent.
            return None
        if type(binding) is not ServiceCtpTickBinding:
            raise ServiceReadProxyError("TICK_FEED_UNBOUND")
        if dataname not in self._started_clients:
            raise ServiceReadProxyError("MARKET_NOT_SUBSCRIBED")
        bootstrap = self._bootstrap_ticks.pop(dataname, None)
        if bootstrap is not None:
            return dict(bootstrap)
        self._assert_market_stream_healthy(binding)
        event = binding.market_client.poll(timeout_ms=0)
        self._assert_market_stream_healthy(binding)
        if event is None:
            return None
        sequence = self._last_sequences[dataname] + 1
        tick = self._event_tick(dataname, event, expected_sequence=sequence)
        self._last_sequences[dataname] = event.header.sequence
        return tick

    @staticmethod
    def _assert_market_stream_healthy(
        binding: ServiceFeedBinding | ServiceCtpTickBinding,
    ) -> None:
        client = binding.market_client
        if (
            getattr(client, "healthy", None) is not True
            or getattr(client, "recovery_required", None) is not False
        ):
            raise ServiceReadProxyError("MARKET_STREAM_UNHEALTHY")

    def _event_bar(
        self,
        dataname: str,
        event: Any,
        *,
        expected_sequence: int,
    ) -> dict[str, Any]:
        binding = self._binding(dataname)
        key = binding.market_client.key
        if type(event) is not WireEnvelope:
            raise ServiceReadProxyError("MARKET_EVENT_INVALID")
        header = event.header
        epoch = self._stream_epochs.get(dataname)
        scope = binding.market_client.stream_scope
        try:
            validate_event(
                event,
                expected_scope=scope,
                expected_stream_id=key.stream_id,
                expected_stream_epoch=epoch,
                expected_sequence=expected_sequence,
            )
        except Exception:
            raise ServiceReadProxyError("MARKET_EVENT_INVALID") from None
        if (
            header.kind is not WireMessageKind.EVENT
            or header.operation != MARKET_EVENT_OPERATION
            or header.schema_id != MARKET_EVENT_SCHEMA
            or header.schema_version != MARKET_EVENT_SCHEMA_VERSION
            or set(event.payload) != {"key", "data"}
        ):
            raise ServiceReadProxyError("MARKET_EVENT_INVALID")
        try:
            event_key = MarketSubscriptionKey.from_dict(event.payload["key"])
            if event_key != key:
                raise ValueError
            bar = MarketBar.from_dict(event.payload["data"])
            sent_at = _parse_utc(header.sent_at_utc, "sent_at_utc")
            now = self._clock()
            if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
                raise ValueError
            _validate_bar_interval(
                binding,
                _parse_utc(bar.open_time_utc, "open_time_utc"),
                _parse_utc(bar.close_time_utc, "close_time_utc"),
                now=now.astimezone(timezone.utc),
                sent_at=sent_at,
            )
            return _bar_to_dict(bar)
        except ServiceReadProxyError:
            raise
        except Exception:
            raise ServiceReadProxyError("MARKET_EVENT_INVALID") from None

    def _event_tick(
        self,
        dataname: str,
        event: Any,
        *,
        expected_sequence: int,
    ) -> dict[str, Any]:
        """Validate CTP source scope separately from the authenticated wire cursor."""
        binding = self._binding(dataname)
        if type(binding) is not ServiceCtpTickBinding:
            raise ServiceReadProxyError("TICK_FEED_UNBOUND")
        key = binding.market_client.key
        if type(event) is not WireEnvelope:
            raise ServiceReadProxyError("MARKET_EVENT_INVALID")
        try:
            validate_event(
                event,
                expected_scope=binding.market_client.stream_scope,
                expected_stream_id=key.stream_id,
                expected_stream_epoch=self._stream_epochs.get(dataname),
                expected_sequence=expected_sequence,
            )
            header = event.header
            if (
                header.kind is not WireMessageKind.EVENT
                or header.operation != MARKET_EVENT_OPERATION
                or header.schema_id != MARKET_EVENT_SCHEMA
                or header.schema_version != MARKET_EVENT_SCHEMA_VERSION
                or set(event.payload) != {"key", "data"}
            ):
                raise ValueError
            event_key = MarketSubscriptionKey.from_dict(event.payload["key"])
            if event_key != key:
                raise ValueError
            raw = event.payload["data"]
            if not isinstance(raw, Mapping):
                raise ValueError
            tick = dict(raw)
            if (
                tick.get("schema_version") != "ctp.quote.v2"
                or tick.get("symbol") != key.instrument.native_symbol
                or tick.get("instrument_id") != key.instrument.instrument_id
                or tick.get("exchange_id") != key.instrument.venue
                or tick.get("clock_domain_id") != binding.clock_domain_id
            ):
                raise ValueError
            generation = tick.get("connection_generation")
            subscription_epoch = tick.get("subscription_epoch")
            ingest_sequence = tick.get("ingest_seq")
            if (
                type(generation) is not int
                or generation <= 0
                or type(subscription_epoch) is not int
                or subscription_epoch <= 0
                or type(ingest_sequence) is not int
                or ingest_sequence <= 0
            ):
                raise ValueError
            event_time = _parse_utc(tick.get("event_time_utc"), "event_time_utc")
            receive_time = _parse_utc(tick.get("recv_time_utc"), "recv_time_utc")
            recv_monotonic_ns = tick.get("recv_monotonic_ns")
            if (
                receive_time < event_time - timedelta(seconds=0.5)
                or type(recv_monotonic_ns) is not int
                or recv_monotonic_ns <= 0
            ):
                raise ValueError
            scope = (generation, subscription_epoch)
            previous_scope = self._ctp_tick_scopes.get(dataname)
            previous_sequence = self._ctp_tick_sequences.get(dataname)
            if previous_scope is not None and scope != previous_scope:
                raise ServiceReadProxyError("CTP_SOURCE_SCOPE_CHANGED")
            if previous_sequence is not None and ingest_sequence <= previous_sequence:
                raise ServiceReadProxyError("CTP_INGEST_SEQUENCE_INVALID")
            self._ctp_tick_scopes[dataname] = scope
            self._ctp_tick_sequences[dataname] = ingest_sequence
            return tick
        except ServiceReadProxyError:
            raise
        except Exception:
            raise ServiceReadProxyError("CTP_TICK_EVENT_INVALID") from None

    def _remember_emitted(self, dataname: str, bar: dict[str, Any]) -> dict[str, Any] | None:
        open_time = bar["timestamp"]
        previous_open = self._last_emitted_open.get(dataname)
        identity = _bar_identity(bar)
        if previous_open is not None:
            if _parse_utc(open_time, "open_time_utc") < _parse_utc(previous_open, "open_time_utc"):
                raise ServiceReadProxyError("LIVE_BAR_OUT_OF_ORDER")
            if open_time == previous_open:
                if self._last_emitted_identity.get(dataname) != identity:
                    raise ServiceReadProxyError("HISTORY_LIVE_CONFLICT")
                return None
        self._last_emitted_open[dataname] = open_time
        self._last_emitted_identity[dataname] = identity
        return dict(bar)

    def _position_binding(
        self, resource: AccountResourceKey, instrument: MarketInstrumentKey
    ) -> tuple[str, ServiceFeedBinding | ServiceCtpTickBinding]:
        dataname = self._position_bindings.get((resource, instrument))
        if dataname is None:
            raise ServiceReadProxyError("ACCOUNT_INSTRUMENT_UNMAPPED")
        return dataname, self._feeds[dataname]

    def _current_observation(self) -> AccountObservation:
        self._assert_connected()
        try:
            view = self._account_client.snapshot()
        except Exception:
            view = self._account_client.refresh()
        observation = getattr(view, "observation", None)
        self._validate_observation(observation)
        return observation

    def _validate_observation(self, observation: Any) -> None:
        if type(observation) is not AccountObservation:
            raise ServiceReadProxyError("ACCOUNT_OBSERVATION_INVALID")
        if observation.account_key != self._expected_account:
            raise ServiceReadProxyError("ACCOUNT_IDENTITY_MISMATCH")
        if set(observation.coverage) != self._required_coverage:
            raise ServiceReadProxyError("ACCOUNT_COVERAGE_MISMATCH")
        if observation.balances_complete is not True:
            raise ServiceReadProxyError("BALANCES_INCOMPLETE")
        if observation.positions_complete is not True:
            raise ServiceReadProxyError("POSITIONS_INCOMPLETE")
        for item in observation.positions:
            self._position_binding(item.resource, item.instrument)
        if observation.valuation is not None and (
            observation.valuation.currency != self._valuation_currency
        ):
            raise ServiceReadProxyError("VALUATION_CURRENCY_MISMATCH")

    def _binding(self, dataname: str) -> ServiceFeedBinding | ServiceCtpTickBinding:
        if type(dataname) is not str or dataname not in self._feeds:
            raise ServiceReadProxyError("FEED_UNBOUND")
        return self._feeds[dataname]

    def _assert_connected(self) -> None:
        self._assert_owner()
        if not self.is_connected:
            raise ServiceReadProxyError("PROXY_NOT_CONNECTED")

    def _assert_owner(self) -> None:
        if threading.get_ident() != self._owner_thread_id:
            raise ServiceReadProxyError("WRONG_OWNER_THREAD")


def _check_text(value: Any, field: str) -> str:
    if type(value) is not str or not value or value != value.strip() or not value.isprintable():
        raise ValueError(f"{field} must be non-empty printable text")
    value.encode("utf-8", errors="strict")
    return value


def _decimal(value: Any, field: str) -> Decimal:
    if type(value) is not str or len(value) > 128:
        raise TypeError(f"{field} must be a bounded decimal string")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field} is invalid") from None
    if not parsed.is_finite():
        raise ValueError(f"{field} must be finite")
    return parsed


def _finite_float(value: Any, field: str) -> float:
    if isinstance(value, Decimal):
        decimal_value = value
    else:
        decimal_value = _decimal(value, field)
    result = float(decimal_value)
    if not math.isfinite(result):
        raise ServiceReadProxyError("NUMBER_OUT_OF_RANGE")
    if decimal_value != 0 and result == 0.0:
        raise ServiceReadProxyError("NUMBER_UNDERFLOW")
    return result


def _optional_float(value: str | None, field: str) -> float | None:
    return None if value is None else _finite_float(value, field)


def _timeframe_seconds(value: str) -> int:
    match = re.fullmatch(r"([1-9][0-9]{0,11})([smhdw])", value) if type(value) is str else None
    if match is None:
        raise ValueError("timeframe must be a positive fixed interval")
    count = int(match.group(1))
    unit = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[match.group(2)]
    return count * unit


def _backtrader_timeframe(timeframe: Any, compression: int) -> str:
    if type(compression) is not int or compression <= 0:
        raise ServiceReadProxyError("TIMEFRAME_UNSUPPORTED")
    unit = {
        TimeFrame.Seconds: "s",
        TimeFrame.Minutes: "m",
        TimeFrame.Days: "d",
    }.get(timeframe)
    if unit is None:
        raise ServiceReadProxyError("TIMEFRAME_UNSUPPORTED")
    return f"{compression}{unit}"


def _parse_utc(value: Any, field: str) -> datetime:
    if (
        type(value) is not str
        or re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z",
            value,
        )
        is None
    ):
        raise ValueError(f"{field} must be a UTC timestamp ending in Z")
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise ValueError(f"{field} is invalid") from None
    return result.astimezone(timezone.utc)


def _parse_since(value: Any) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ServiceReadProxyError("HISTORY_SINCE_UNSUPPORTED")
    return value.astimezone(timezone.utc)


def _format_utc(value: datetime) -> str:
    result = value.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="microseconds")
    if "." in result:
        whole, fraction = result.split(".", 1)
        fraction = fraction.rstrip("0")
        result = whole if not fraction else f"{whole}.{fraction}"
    return result + "Z"


def _epoch_seconds(value: datetime) -> int:
    return math.floor(value.timestamp())


def _floor_time(value: datetime, duration: int) -> datetime:
    seconds = _epoch_seconds(value)
    return datetime.fromtimestamp(seconds - seconds % duration, tz=timezone.utc)


def _bar_to_dict(bar: MarketBar) -> dict[str, Any]:
    return {
        "timestamp": _format_utc(_parse_utc(bar.open_time_utc, "open_time_utc")),
        "close_time_utc": _format_utc(_parse_utc(bar.close_time_utc, "close_time_utc")),
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "openinterest": bar.open_interest,
    }


def _validate_bar_interval(
    binding: ServiceFeedBinding,
    opened: datetime,
    closed: datetime,
    *,
    now: datetime,
    sent_at: datetime | None = None,
) -> None:
    duration = _timeframe_seconds(binding.timeframe)
    if (closed - opened).total_seconds() != duration:
        raise ServiceReadProxyError("MARKET_BAR_TIMEFRAME_MISMATCH")
    if (
        opened.microsecond
        or closed.microsecond
        or _epoch_seconds(opened) % duration
        or _epoch_seconds(closed) % duration
    ):
        raise ServiceReadProxyError("MARKET_BAR_ALIGNMENT_INVALID")
    if closed > now:
        raise ServiceReadProxyError("MARKET_BAR_FUTURE")
    if sent_at is not None and closed > sent_at:
        raise ServiceReadProxyError("MARKET_BAR_NOT_CLOSED_AT_SENT")


def _bar_identity(bar: Mapping[str, Any]) -> tuple[Any, ...]:
    numeric_fields = ("open", "high", "low", "close", "volume")
    numeric = tuple(_decimal(bar[field], field) for field in numeric_fields)
    interest = bar.get("openinterest")
    normalized_interest = None if interest is None else _decimal(interest, "open_interest")
    return (
        _format_utc(_parse_utc(bar["timestamp"], "timestamp")),
        _format_utc(_parse_utc(bar["close_time_utc"], "close_time_utc")),
        *numeric,
        normalized_interest,
    )


__all__ = [
    "ServiceCtpTickBinding",
    "ServiceFeedBinding",
    "ServiceReadProxy",
    "ServiceReadProxyError",
]
