"""Read-only bridge from typed service facades to Backtrader Store/Broker/Feed.

This optional adapter imports only neutral bt_api_py service contracts. It does
not construct runtimes, discover providers, or expose execution methods. Tick feeds
remain unavailable until bt_api_py exposes a provider-neutral event and data
clock binding contract; this module does not interpret venue payloads.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from bt_api_py.service_contracts import (
    AccountObservation,
    AccountResourceKey,
    MarketBar,
    MarketInstrumentKey,
    MarketSourceDescriptor,
)
from bt_api_py.service_account_observation import (
    read_current_service_account_observation,
    require_service_account_open_order,
    require_service_account_position,
    require_service_account_quantity_unit,
    service_account_open_orders,
    service_account_positions,
    service_account_valuation,
    validate_service_account_client,
    validate_service_account_observation,
)
from bt_api_py.service_read_lifecycle import ServiceReadLifecycle
from bt_api_py.service_market_history import (
    MarketHistoryCollectionError,
    ServiceBarHistoryHandoff,
    ServiceBarStreamSession,
    collect_market_history,
    fixed_timeframe_seconds as _timeframe_seconds,
    validate_market_history_limits,
    require_service_bar_healthy,
)

from bt_api_py.service_market_bindings import (
    ServiceFeedBinding,
    ServiceOrderBookBinding,
    check_service_text as _check_text,
    parse_service_decimal as _decimal,
    validate_service_market_bindings,
)
from bt_api_py.service_market_history import (
    format_market_utc as _format_utc,
    parse_market_utc as _parse_utc,
)

from ..dataseries import TimeFrame
from ..events import OrderBookSnapshot


class ServiceReadProxyError(RuntimeError):
    """Finite local diagnostics for a rejected read-only projection."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code or not code.isascii():
            raise ValueError("code must be a finite ASCII identifier")
        self.code = code
        super().__init__(code)


class ServiceReadProxy:
    """Borrowed-facade adapter for observation-only bars and order books.

    Provider ticks stay disabled until the SDK exposes a neutral market-event
    and data-clock binding contract.
    """

    service_read_only = True
    read_only = True

    def __init__(
        self,
        account_client: Any,
        feeds: Mapping[
            str, ServiceFeedBinding | ServiceOrderBookBinding
        ],
        *,
        valuation_currency: str,
        position_mode: str,
        history_page_size: int = 1000,
        max_history_pages: int = 100,
        max_history_rows: int = 50000,
        default_history_limit: int = 500,
        clock: Any = None,
    ) -> None:
        expected_account, coverage = validate_service_account_client(account_client)
        copied = validate_service_market_bindings(
            feeds, account_client=account_client, coverage=coverage
        )
        _check_text(valuation_currency, "valuation_currency")
        if type(position_mode) is not str or position_mode not in {"net", "dual_side"}:
            raise ValueError("position_mode must be net or dual_side")
        validate_market_history_limits(
            history_page_size=history_page_size,
            max_history_pages=max_history_pages,
            max_history_rows=max_history_rows,
            default_history_limit=default_history_limit,
        )
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
        self._lifecycle = ServiceReadLifecycle(
            account_client,
            validate_observation=self._validate_observation,
            market_close_targets=self._market_close_targets,
            error_type=ServiceReadProxyError,
        )
        self._started_clients: set[str] = set()
        self._bar_stream_sessions: dict[str, ServiceBarStreamSession] = {}
        self._orderbook_projectors: dict[str, Any] = {}
        self._bootstrap_orderbooks: dict[str, OrderBookSnapshot] = {}
        self._bar_handoffs: dict[str, ServiceBarHistoryHandoff] = {}
        self._position_bindings: dict[tuple[AccountResourceKey, MarketInstrumentKey], str] = {}
        for dataname, binding in copied.items():
            map_key = (binding.resource, binding.market_client.key.instrument)
            if map_key in self._position_bindings:
                raise ValueError("each account instrument/resource needs one position feed mapping")
            self._position_bindings[map_key] = dataname

    @property
    def is_connected(self) -> bool:
        return self._lifecycle.is_connected

    def connect(self) -> None:
        """Read and validate one complete provider account snapshot."""
        self._lifecycle.connect()

    start = connect

    def _market_close_targets(self):
        for dataname, binding in self._feeds.items():
            yield binding.market_client, self._orderbook_projectors.get(
                dataname, binding.market_client
            )

    def disconnect(self) -> None:
        """Close injected facades while preserving shared runtime ownership."""
        self._lifecycle.close()

    close = disconnect

    def supports_position_mode(self, mode: str) -> bool:
        return type(mode) is str and mode == self._position_mode

    def supports_live_streaming(self, dataname: str) -> bool:
        """Tell BtApiFeed that this explicitly bound facade has a live poll."""
        return type(dataname) is str and dataname in self._feeds

    def supports_bar_history(
        self,
        dataname: str,
        *,
        timeframe: Any,
        compression: int = 1,
    ) -> bool:
        """Report whether a bound bar feed supports this fixed interval.

        This is an owner-thread, in-memory capability check. It is safe to call
        before ``connect`` and never starts a facade or reads provider state.
        """

        self._assert_owner()
        if self._lifecycle.closed_or_closing:
            return False
        if type(dataname) is not str or type(timeframe) is not int:
            return False
        binding = self._feeds.get(dataname)
        if type(binding) is not ServiceFeedBinding:
            return False
        try:
            requested_timeframe = _backtrader_timeframe(timeframe, compression)
            return _timeframe_seconds(requested_timeframe) == _timeframe_seconds(binding.timeframe)
        except (ServiceReadProxyError, TypeError, ValueError):
            return False

    def get_balance(self) -> dict[str, float]:
        observation = self._current_observation()
        available_cash, reported_equity = service_account_valuation(
            observation, currency=self._valuation_currency, error_type=ServiceReadProxyError
        )
        cash = _finite_float(available_cash, "available_cash")
        equity = _finite_float(reported_equity, "equity")
        return {"cash": cash, "value": equity}

    def get_positions(self) -> list[dict[str, Any]]:
        observation = self._current_observation()
        positions = service_account_positions(observation, error_type=ServiceReadProxyError)
        rows: list[dict[str, Any]] = []
        for position in positions:
            require_service_account_position(position, error_type=ServiceReadProxyError)
            dataname, binding = self._position_binding(position.resource, position.instrument)
            require_service_account_quantity_unit(
                position.qty_unit, binding.qty_unit,
                error_type=ServiceReadProxyError, code="POSITION_UNIT_MISMATCH",
            )
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
        orders = service_account_open_orders(observation, error_type=ServiceReadProxyError)
        rows: list[dict[str, Any]] = []
        for order in orders:
            require_service_account_open_order(order, error_type=ServiceReadProxyError)
            dataname, binding = self._position_binding(order.resource, order.instrument)
            require_service_account_quantity_unit(
                order.qty_unit, binding.qty_unit,
                error_type=ServiceReadProxyError, code="ORDER_UNIT_MISMATCH",
            )
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
        if type(binding) is ServiceOrderBookBinding:
            projector = self._orderbook_projector(dataname, binding)
            try:
                from bt_api_py.service_market_orderbook import validate_service_orderbook_bootstrap

                bootstrap = projector.start()
            except Exception as error:
                raise ServiceReadProxyError(
                    _sdk_error_code(error, "ORDERBOOK_PROJECTION_FAILED")
                ) from None
            latest = validate_service_orderbook_bootstrap(
                projector, bootstrap, error_type=ServiceReadProxyError
            )
            if latest is not None:
                self._bootstrap_orderbooks[dataname] = self._project_orderbook(binding, latest)
            self._started_clients.add(dataname)
            return

        session = self._bar_stream_sessions.get(dataname)
        if session is None:
            session = ServiceBarStreamSession(
                binding.market_client,
                timeframe=binding.timeframe,
                clock=self._clock,
                project_bar=_bar_to_dict,
                error_type=ServiceReadProxyError,
            )
            self._bar_stream_sessions[dataname] = session
        snapshot = session.start()
        handoff = self._bar_handoffs.setdefault(
            dataname,
            ServiceBarHistoryHandoff(
                bar_identity=_bar_identity, error_type=ServiceReadProxyError
            ),
        )
        handoff.stage_bootstrap(snapshot)
        self._started_clients.add(dataname)

    def _orderbook_projector(self, dataname: str, binding: ServiceOrderBookBinding) -> Any:
        projector = self._orderbook_projectors.get(dataname)
        if projector is not None:
            return projector
        try:
            from bt_api_py.service_market_orderbook import ServiceMarketOrderBookProjector

            projector = ServiceMarketOrderBookProjector(
                binding.market_client,
                max_depth=binding.max_depth,
                max_event_age_seconds=binding.max_event_age_seconds,
            )
        except Exception as error:
            raise ServiceReadProxyError(
                _sdk_error_code(error, "ORDERBOOK_SDK_OWNER_UNAVAILABLE")
            ) from None
        self._orderbook_projectors[dataname] = projector
        return projector

    @staticmethod
    def _project_orderbook(binding: ServiceOrderBookBinding, projection: Any) -> OrderBookSnapshot:
        try:
            from bt_api_py.service_market_orderbook import validate_service_orderbook_projection

            key, source = validate_service_orderbook_projection(
                projection, error_type=ServiceReadProxyError
            )
            multiplier = _decimal(binding.quantity_multiplier, "quantity_multiplier")
            bids = [
                (
                    _finite_float(price, "bid price"),
                    _finite_float(quantity * multiplier, "bid quantity"),
                )
                for price, quantity in projection.bids
            ]
            asks = [
                (
                    _finite_float(price, "ask price"),
                    _finite_float(quantity * multiplier, "ask quantity"),
                )
                for price, quantity in projection.asks
            ]
            observed_at = projection.observed_at_unix_ns / 1_000_000_000.0
            book = OrderBookSnapshot(
                timestamp=_finite_float(projection.timestamp_seconds, "timestamp"),
                symbol=key.instrument.native_symbol,
                exchange=key.instrument.venue,
                asset_type=key.instrument.product_type,
                local_time=observed_at,
                bids=bids,
                asks=asks,
                exchange_time=_finite_float(projection.timestamp_seconds, "exchange_time"),
                received_wall_time=observed_at,
                received_monotonic_ns=projection.observed_at_monotonic_ns,
                sequence=projection.provider_sequence,
                previous_sequence=projection.provider_previous_sequence,
                snapshot_or_delta=projection.snapshot_or_delta,
                continuity_status=projection.continuity_status,
                stale=projection.stale,
                stale_reason=projection.stale_reason,
                source=source.source,
                recovery_snapshot=projection.recovery_snapshot,
            )
            if not book.validate():
                raise ServiceReadProxyError("ORDERBOOK_PROJECTION_INVALID")
            return book
        except ServiceReadProxyError:
            raise
        except Exception as error:
            raise ServiceReadProxyError(
                _sdk_error_code(error, "ORDERBOOK_PROJECTION_INVALID")
            ) from None

    def orderbook_source_descriptor(self, dataname: str) -> MarketSourceDescriptor:
        """Return the authenticated source descriptor for a started L2 feed."""

        self._assert_connected()
        binding = self._binding(dataname)
        if type(binding) is not ServiceOrderBookBinding:
            raise ServiceReadProxyError("ORDERBOOK_FEED_UNBOUND")
        if dataname not in self._started_clients:
            raise ServiceReadProxyError("MARKET_NOT_SUBSCRIBED")
        projector = self._orderbook_projector(dataname, binding)
        try:
            descriptor = projector.source_descriptor
        except Exception as error:
            raise ServiceReadProxyError(
                _sdk_error_code(error, "ORDERBOOK_SOURCE_DESCRIPTOR_UNAVAILABLE")
            ) from None
        if type(descriptor) is not MarketSourceDescriptor:
            raise ServiceReadProxyError("ORDERBOOK_SOURCE_DESCRIPTOR_UNAVAILABLE")
        return descriptor

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
        if type(binding) is not ServiceFeedBinding:
            raise ServiceReadProxyError("MARKET_HISTORY_UNSUPPORTED")
        if dataname not in self._started_clients:
            raise ServiceReadProxyError("MARKET_NOT_SUBSCRIBED")
        requested_timeframe = _backtrader_timeframe(timeframe, compression)
        if _timeframe_seconds(requested_timeframe) != _timeframe_seconds(binding.timeframe):
            raise ServiceReadProxyError("TIMEFRAME_MISMATCH")
        try:
            typed_bars = collect_market_history(
                binding.market_client,
                history_start_utc=binding.history_start_utc,
                history_end_utc=binding.history_end_utc,
                since=since,
                now_utc=self._clock(),
                limit=limit,
                default_limit=self._default_history_limit,
                page_size=self._history_page_size,
                max_pages=self._max_history_pages,
                max_rows=self._max_history_rows,
            )
        except MarketHistoryCollectionError as error:
            raise ServiceReadProxyError(error.code) from None
        rows = [_bar_to_dict(bar) for bar in typed_bars]
        self._bar_handoffs[dataname].apply_history(rows)
        return rows

    def poll_bar(self, dataname: str) -> dict[str, Any] | None:
        """Return one ordered closed bar; never silently recover from a stream gap."""
        self._assert_connected()
        binding = self._binding(dataname)
        if type(binding) is not ServiceFeedBinding:
            if dataname not in self._started_clients:
                raise ServiceReadProxyError("MARKET_NOT_SUBSCRIBED")
            self._assert_market_stream_healthy(dataname, binding)
            # The orderbook binding has no bar result. Keep the normal Feed loop
            # alive without reading Kline history or synthesizing a bar.
            return None
        if dataname not in self._started_clients:
            raise ServiceReadProxyError("MARKET_NOT_SUBSCRIBED")
        handoff = self._bar_handoffs[dataname]
        has_pending, pending = handoff.take_pending()
        if has_pending:
            return pending
        bar = self._bar_stream_sessions[dataname].poll()
        if bar is None:
            return None
        return handoff.accept_live(bar)

    def poll_tick(self, dataname: str) -> dict[str, Any] | None:
        """Return no tick until the SDK exposes a neutral event/clock binding.

        The SDK does not yet expose the neutral MarketProviderEvent/data-clock
        contract needed to project provider ticks. Bar and orderbook bindings
        therefore have no tick projection.
        """
        self._assert_connected()
        self._binding(dataname)
        return None

    def poll_orderbook(self, dataname: str) -> OrderBookSnapshot | None:
        """Return one service-delivered complete-depth image for an L2 feed."""

        self._assert_connected()
        binding = self._binding(dataname)
        if type(binding) is not ServiceOrderBookBinding:
            # BtApiFeed probes this method for every live feed. Other explicit
            # bindings have no orderbook capability and remain idle here.
            return None
        if dataname not in self._started_clients:
            raise ServiceReadProxyError("MARKET_NOT_SUBSCRIBED")
        bootstrap = self._bootstrap_orderbooks.pop(dataname, None)
        if bootstrap is not None:
            return bootstrap
        projector = self._orderbook_projector(dataname, binding)
        try:
            projection = projector.poll(timeout_ms=0)
        except Exception as error:
            raise ServiceReadProxyError(
                _sdk_error_code(error, "ORDERBOOK_PROJECTION_FAILED")
            ) from None
        if projection is None:
            return None
        return self._project_orderbook(binding, projection)

    def _assert_market_stream_healthy(
        self,
        dataname: str,
        binding: ServiceFeedBinding | ServiceOrderBookBinding,
    ) -> None:
        if type(binding) is ServiceOrderBookBinding:
            projector = self._orderbook_projector(dataname, binding)
            from bt_api_py.service_market_orderbook import require_service_orderbook_healthy

            require_service_orderbook_healthy(
                projector, error_type=ServiceReadProxyError, code="MARKET_STREAM_UNHEALTHY"
            )
            return
        require_service_bar_healthy(
            binding.market_client, error_type=ServiceReadProxyError, code="MARKET_STREAM_UNHEALTHY"
        )

    def _position_binding(
        self, resource: AccountResourceKey, instrument: MarketInstrumentKey
    ) -> tuple[str, ServiceFeedBinding | ServiceOrderBookBinding]:
        dataname = self._position_bindings.get((resource, instrument))
        if dataname is None:
            raise ServiceReadProxyError("ACCOUNT_INSTRUMENT_UNMAPPED")
        return dataname, self._feeds[dataname]

    def _current_observation(self) -> AccountObservation:
        self._assert_connected()
        return read_current_service_account_observation(
            self._account_client, validate_observation=self._validate_observation
        )

    def _validate_observation(self, observation: Any) -> None:
        validate_service_account_observation(
            observation,
            expected_account=self._expected_account,
            required_coverage=self._required_coverage,
            valuation_currency=self._valuation_currency,
            validate_position=self._position_binding,
            error_type=ServiceReadProxyError,
        )

    def _binding(
        self, dataname: str
    ) -> ServiceFeedBinding | ServiceOrderBookBinding:
        if type(dataname) is not str or dataname not in self._feeds:
            raise ServiceReadProxyError("FEED_UNBOUND")
        return self._feeds[dataname]

    def _assert_connected(self) -> None:
        self._assert_owner()
        if not self.is_connected:
            raise ServiceReadProxyError("PROXY_NOT_CONNECTED")

    def _assert_owner(self) -> None:
        self._lifecycle.assert_owner()






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


def _sdk_error_code(error: Exception, fallback: str) -> str:
    code = getattr(error, "code", None)
    if type(code) is str and re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code):
        return code
    return fallback


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
    "ServiceReadProxy",
    "ServiceReadProxyError",
]
