"""Isolated MarketHub-only observer for the 007 CTP Gateway strategies.

This module intentionally does not import a BtApi Store, Gateway Broker, Risk,
Execution, persistence/recovery helper, YAML reader, or any previous-run path.
The caller must supply an already-held ``GatewayClientConnection`` in memory.
The only remote application API used below is the CTP Gateway MarketHub read
runtime. Market subscriptions are read-control calls; order/cancel calls are
rejected locally before they can reach a remote client.

This is an observation runner, not an authorization to trade. It never reads
old run directories or stop markers, and every invocation gets a fresh run ID.
The current SDK CTP composition uses one fixed strategy reference, so runs using
that identity are serial only. Direct callers must provide cross-process
serialization; ``market_only_cli`` supplies the per-user global lease.
"""
from __future__ import annotations

import importlib.util
import math
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

import backtrader as bt
from backtrader.brokers.bbroker import BackBroker
from backtrader.channel import Event, EventPriority
from backtrader.feeds.livefeed import LiveFeedBase
from backtrader.utils import date2num


class MarketOnlyError(RuntimeError):
    """Finite, value-free failure of the market-only boundary."""

    def __init__(self, code: str):
        if (
            type(code) is not str
            or not code.isascii()
            or not code.replace("_", "").isalnum()
        ):
            code = "MARKET_ONLY_FAILED"
        self.code = code
        super().__init__(code)


class MarketOnlyPositionUnknown(MarketOnlyError):
    """A market-only process has no authority to infer account position."""


class MarketOnlyOrderRejected(MarketOnlyError):
    """Every strategy-originated order/cancel request is refused locally."""


@dataclass(frozen=True)
class StrategySpec:
    directory: str
    module: str
    class_name: str
    instruments: tuple[tuple[str, str], ...]
    resample_seconds: int = 0


# Stable, public example mapping. No YAML or historical runner configuration
# is loaded to select a strategy or instrument.
STRATEGIES: dict[str, StrategySpec] = {
    "bbroker_5s_single_symbol_gateway": StrategySpec(
        "bbroker_5s_single_symbol_gateway", "single_symbol_ma_strategy.py", "SingleSymbolMaStrategy", (("rb2701", "SHFE"),), 5
    ),
    "bbroker_5s_pair_arbitrage_gateway": StrategySpec(
        "bbroker_5s_pair_arbitrage_gateway", "pair_spread_strategy.py", "PairSpreadStrategy", (("rb2701", "SHFE"), ("hc2701", "SHFE")), 5
    ),
    "mixbroker_5s_single_symbol_gateway": StrategySpec(
        "mixbroker_5s_single_symbol_gateway", "single_symbol_ma_strategy.py", "SingleSymbolMaStrategy", (("rb2701", "SHFE"),), 5
    ),
    "mixbroker_5s_pair_arbitrage_gateway": StrategySpec(
        "mixbroker_5s_pair_arbitrage_gateway", "pair_spread_strategy.py", "PairSpreadStrategy", (("rb2701", "SHFE"), ("hc2701", "SHFE")), 5
    ),
    "tickbroker_5s_single_symbol_gateway": StrategySpec(
        "tickbroker_5s_single_symbol_gateway", "single_symbol_ma_strategy.py", "SingleSymbolMaStrategy", (("rb2701", "SHFE"),), 5
    ),
    "tickbroker_5s_pair_arbitrage_gateway": StrategySpec(
        "tickbroker_5s_pair_arbitrage_gateway", "pair_spread_strategy.py", "PairSpreadStrategy", (("rb2701", "SHFE"), ("hc2701", "SHFE")), 5
    ),
    "mixbroker_single_symbol_gateway": StrategySpec(
        "mixbroker_single_symbol_gateway", "single_symbol_mix_strategy.py", "SingleSymbolMixStrategy", (("rb2701", "SHFE"),)
    ),
    "mixbroker_pair_arbitrage_gateway": StrategySpec(
        "mixbroker_pair_arbitrage_gateway", "pair_mix_arbitrage_strategy.py", "PairMixArbitrageStrategy", (("rb2701", "SHFE"), ("hc2701", "SHFE"))
    ),
    "tickbroker_single_symbol_gateway": StrategySpec(
        "tickbroker_single_symbol_gateway", "single_symbol_tick_strategy.py", "SingleSymbolTickStrategy", (("rb2701", "SHFE"),)
    ),
    "tickbroker_pair_arbitrage_gateway": StrategySpec(
        "tickbroker_pair_arbitrage_gateway", "pair_tick_arbitrage_strategy.py", "PairTickArbitrageStrategy", (("rb2701", "SHFE"), ("hc2701", "SHFE"))
    ),
    "sa_dual_ma_gateway": StrategySpec(
        "sa_dual_ma_gateway", "sa_dual_ma_strategy.py", "DualMAStrategy", (("SA701", "CZCE"),), 60
    ),
}


@dataclass(frozen=True)
class MarketOnlyRunIdentity:
    run_id: str
    run_root: Path


def create_market_only_run_identity(
    run_root: str | Path, *, bucket: str = "market-only"
) -> MarketOnlyRunIdentity:
    """Create a new run directory without opening or enumerating old state."""
    base = Path(run_root)
    if not base.is_absolute() or bucket not in {"market-only", "strategies-market-only"}:
        raise MarketOnlyError("RUN_ROOT_MUST_BE_ABSOLUTE")
    run_id = uuid.uuid4().hex
    current = base / bucket / run_id
    current.mkdir(parents=True, exist_ok=False)
    return MarketOnlyRunIdentity(run_id, current)


@dataclass(frozen=True)
class MarketOnlyTick:
    symbol: str
    price: float
    event_time: datetime
    volume: float = 0.0
    open_interest: float = 0.0
    source_event: Any = None
    execution_eligible: bool = False


class ServiceMarketTickReader:
    """Bind the SDK-authenticated MarketHub stream to observation-only ticks."""

    def __init__(self, client: Any, symbol: str, venue: str):
        self._client = client
        self._symbol = symbol
        self._venue = venue
        self._source = None
        self._sequence = 0
        self._epoch = None
        self._started = False
        self._closed = False
        self._snapshot = None

    def start(self) -> None:
        from bt_api_base.market_protocol import MarketSourceDescriptor, MarketSubscriptionKey
        from bt_api_base.service_protocol import WireEnvelope
        from bt_api_py.ctp_account_process import CTP_MARKET_TICK_CHANNEL
        from bt_api_py.service_market import MarketBootstrap

        bootstrap = self._client.start()
        source = bootstrap.source_descriptor
        key = self._client.key
        if (
            type(bootstrap) is not MarketBootstrap
            or type(source) is not MarketSourceDescriptor
            or type(key) is not MarketSubscriptionKey
            or key.instrument.native_symbol != self._symbol
            or key.instrument.venue != self._venue
            or key.channel != CTP_MARKET_TICK_CHANNEL
            or source.key != key
            or bootstrap.resync_required
            or bootstrap.snapshot_complete
            or bootstrap.full_baseline_available
            or bootstrap.stream_id != source.stream_id
            or bootstrap.snapshot_epoch != source.epoch
            or bootstrap.cursor_epoch != source.epoch
            or bootstrap.cursor_sequence != bootstrap.snapshot_sequence
        ):
            raise MarketOnlyError("MARKET_BOOTSTRAP_INVALID")
        self._source = source
        self._epoch = source.epoch
        self._sequence = bootstrap.snapshot_sequence
        self._started = True
        if bootstrap.snapshot is not None:
            if type(bootstrap.snapshot) is not WireEnvelope:
                raise MarketOnlyError("MARKET_SNAPSHOT_INVALID")
            self._snapshot = self._project(bootstrap.snapshot, self._sequence)

    def poll(self, timeout_ms: int = 20) -> MarketOnlyTick | None:
        if not self._started or self._closed:
            raise MarketOnlyError("MARKET_READER_NOT_STARTED")
        if self._snapshot is not None:
            tick, self._snapshot = self._snapshot, None
            return tick
        frame = self._client.poll(timeout_ms=timeout_ms)
        if frame is None:
            if not self._client.healthy or self._client.recovery_required:
                raise MarketOnlyError("MARKET_STREAM_UNHEALTHY")
            return None
        return self._project(frame, self._sequence + 1)

    def _project(self, frame: Any, expected_sequence: int) -> MarketOnlyTick:
        from bt_api_base.market_protocol import (
            MARKET_EVENT_OPERATION,
            MARKET_EVENT_SCHEMA,
            MARKET_EVENT_SCHEMA_VERSION,
            MarketSubscriptionKey,
        )
        from bt_api_base.market_tick_protocol import (
            MarketClockQuality,
            MarketEventCursor,
            MarketFreshnessStatus,
            MarketTickPayload,
            bind_market_tick_event,
        )
        from bt_api_base.service_protocol import WireEnvelope

        try:
            header = frame.header
            if (
                type(frame) is not WireEnvelope
                or header.stream_id != self._source.stream_id
                or header.stream_epoch != self._epoch
                or header.sequence != expected_sequence
                or header.operation != MARKET_EVENT_OPERATION
                or header.schema_id != MARKET_EVENT_SCHEMA
                or header.schema_version != MARKET_EVENT_SCHEMA_VERSION
                or set(frame.payload) != {"key", "data"}
                or MarketSubscriptionKey.from_dict(frame.payload["key"]) != self._client.key
            ):
                raise ValueError
            payload = MarketTickPayload.from_dict(frame.payload["data"])
            price = float(payload.last_price) if payload.last_price is not None else math.nan
            if (
                payload.instrument != self._client.key.instrument
                or payload.source_clock_quality is not MarketClockQuality.UNKNOWN
                or payload.receive_clock_quality is not MarketClockQuality.UNKNOWN
                or payload.freshness_status is not MarketFreshnessStatus.UNAVAILABLE
                or payload.execution_eligible
                or not math.isfinite(price)
                or price <= 0
                or not payload.provider_event_time_utc
            ):
                raise ValueError
            cursor = MarketEventCursor(header.stream_id, header.stream_epoch, header.sequence)
            bound = bind_market_tick_event(payload, self._source, cursor)
            event_time = datetime.fromisoformat(
                payload.provider_event_time_utc.replace("Z", "+00:00")
            )
            if event_time.tzinfo is None or event_time.utcoffset() != timezone.utc.utcoffset(event_time):
                raise ValueError
            tick = MarketOnlyTick(
                symbol=self._symbol,
                price=price,
                event_time=event_time,
                volume=float(payload.delta_volume or 0.0),
                open_interest=float(payload.open_interest or 0.0),
                source_event=bound,
            )
        except Exception:
            raise MarketOnlyError("MARKET_FRAME_REJECTED") from None
        self._sequence = expected_sequence
        return tick

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._client.close()


class CtpGatewayMarketOnlySession:
    """Own only the SDK's market runtime and per-instrument MarketHub clients."""

    def __init__(self, connection: Any):
        from bt_api_py.ctp_gateway_composition import GatewayClientConnection

        if type(connection) is not GatewayClientConnection:
            raise TypeError("an exact in-memory GatewayClientConnection is required")
        self._connection = connection
        self._runtime = None
        self._clients: list[ServiceMarketTickReader] = []
        self._closed = False

    def start(self) -> None:
        from bt_api_py.ctp_gateway_composition import create_gateway_market_runtime

        self._runtime, _market_factory = create_gateway_market_runtime(
            self._connection, start=False
        )
        self._runtime.start()

    def new_reader(self, symbol: str, venue: str) -> ServiceMarketTickReader:
        from bt_api_py.ctp_gateway_composition import gateway_market_check_client

        if self._runtime is None or self._closed:
            raise MarketOnlyError("MARKET_SESSION_NOT_STARTED")
        client = gateway_market_check_client(self._runtime, self._connection, symbol, venue)
        reader = ServiceMarketTickReader(client, symbol, venue)
        self._clients.append(reader)
        return reader

    def close(self) -> None:
        if self._closed:
            return
        for reader in reversed(self._clients):
            reader.close()
        if self._runtime is not None:
            self._runtime.close()
        self._closed = True


_UNCERTAIN_SESSIONS: list[CtpGatewayMarketOnlySession] = []
_RUN_LOCK = threading.Lock()


class MarketOnlyBroker(BackBroker):
    """Local Cerebro guard; it has no provider/Gateway connection or account state."""

    def __init__(self, *args, **kwargs):
        self.market_only_order_attempts = 0
        self.market_only_order_rejections = 0
        self.market_only_cancel_attempts = 0
        self.market_only_cancel_rejections = 0
        self.market_only_account_read_attempts = 0
        super().__init__(*args, **kwargs)

    def _reject_order(self):
        self.market_only_order_attempts += 1
        self.market_only_order_rejections += 1
        raise MarketOnlyOrderRejected("MARKET_ONLY_ORDER_REJECTED")

    def _reject_cancel(self):
        self.market_only_cancel_attempts += 1
        self.market_only_cancel_rejections += 1
        raise MarketOnlyOrderRejected("MARKET_ONLY_CANCEL_REJECTED")

    def get_strategy_position(self, strategy, data, side=None):
        self.market_only_account_read_attempts += 1
        raise MarketOnlyPositionUnknown("POSITION_UNKNOWN")

    def getposition(self, data, side=None):
        self.market_only_account_read_attempts += 1
        raise MarketOnlyPositionUnknown("POSITION_UNKNOWN")

    def get_closable(self, data, side):
        self.market_only_account_read_attempts += 1
        raise MarketOnlyPositionUnknown("POSITION_UNKNOWN")

    def getcash(self):
        self.market_only_account_read_attempts += 1
        raise MarketOnlyPositionUnknown("ACCOUNT_CASH_UNKNOWN")

    def getvalue(self, datas=None):
        self.market_only_account_read_attempts += 1
        raise MarketOnlyPositionUnknown("ACCOUNT_VALUE_UNKNOWN")

    def buy(self, *args, **kwargs):
        self._reject_order()

    def sell(self, *args, **kwargs):
        self._reject_order()

    def submit(self, *args, **kwargs):
        self._reject_order()

    def cancel(self, *args, **kwargs):
        self._reject_cancel()


class MarketHubFeed(LiveFeedBase):
    """A history-free line feed over one exact MarketHub subscription."""

    params = (("reader", None), ("symbol", None), ("deadline", None), ("receipt_sink", None))

    def __init__(self):
        super().__init__()
        self._observed_ticks = 0

    def start(self):
        super().start()
        self.p.reader.start()
        self.put_notification(self.LIVE)

    def stop(self):
        super().stop()

    def islive(self):
        return True

    def _load(self):
        if self.p.deadline is not None and time.monotonic() >= self.p.deadline:
            return False
        tick = self.p.reader.poll()
        if tick is None:
            if getattr(self.p.reader, "finished", False):
                return False
            return None
        self.lines.datetime[0] = date2num(tick.event_time)
        self.lines.open[0] = self.lines.high[0] = self.lines.low[0] = self.lines.close[0] = tick.price
        self.lines.volume[0] = tick.volume
        self.lines.openinterest[0] = tick.open_interest
        self._observed_ticks += 1
        if self.p.receipt_sink is not None:
            self.p.receipt_sink.record_tick(tick)
        event = Event(
            timestamp=tick.event_time.timestamp(),
            priority=EventPriority.TICK,
            channel_type="tick",
            channel_name=tick.symbol,
            data=tick,
        )
        # No feed reference means dispatch cannot route this observation to a
        # broker processor even if a future Cerebro broker adds one.
        event._source_feed = None
        self._env.dispatch_channel_event(event)
        return True


class MarketOnlyStrategyGuard:
    """Mixin that keeps strategy callbacks observational and rejects writes."""

    def __init__(self, *args, **kwargs):
        self.market_only_started = False
        self.market_only_tick_count = 0
        self.market_only_order_attempts = 0
        self.market_only_order_rejections = 0
        self.market_only_cancel_attempts = 0
        self.market_only_cancel_rejections = 0
        super().__init__(*args, **kwargs)

    def start(self):
        self.market_only_started = True
        super().start()

    def notify_tick(self, tick):
        # Let the strategy update its quote-derived observation state. The
        # ten trading strategies are explicitly disabled and unknown position
        # reads remain unreadable; this mixin and the local broker reject any
        # attempted write before it could leave the process.
        if tick.symbol in {data._name for data in self.datas}:
            self.market_only_tick_count += 1
        super().notify_tick(tick)

    def _refresh_position(self, symbol):
        """Keep position UNKNOWN; never ask a broker or cache a flat default."""
        symbol = str(symbol)
        unreadable_reader = getattr(super(), "_unreadable_positions", None)
        if callable(unreadable_reader):
            unreadable = unreadable_reader()
        else:
            unreadable = self.__dict__.setdefault("_market_only_unreadable", set())
        unreadable.add(symbol)
        cache = getattr(self, "position_cache", None)
        if isinstance(cache, dict):
            cache[symbol] = math.nan
        return math.nan

    def _position_size(self, symbol):
        return self._refresh_position(symbol)

    def getwriterinfo(self):
        # Cerebro's optional end-of-run writer normally asks the broker for
        # account value. This run has no account read and emits no account
        # projection, so provide an intentionally empty writer row.
        return {}

    def buy(self, *args, **kwargs):
        self.market_only_order_attempts += 1
        self.market_only_order_rejections += 1
        raise MarketOnlyOrderRejected("MARKET_ONLY_ORDER_REJECTED")

    def sell(self, *args, **kwargs):
        self.market_only_order_attempts += 1
        self.market_only_order_rejections += 1
        raise MarketOnlyOrderRejected("MARKET_ONLY_ORDER_REJECTED")

    def cancel(self, *args, **kwargs):
        self.market_only_cancel_attempts += 1
        self.market_only_cancel_rejections += 1
        raise MarketOnlyOrderRejected("MARKET_ONLY_CANCEL_REJECTED")


_STRATEGY_MODULES: dict[str, ModuleType] = {}
_GUARDED_STRATEGIES: dict[str, type] = {}


def _load_strategy_class(name: str) -> type:
    try:
        spec = STRATEGIES[name]
    except KeyError:
        raise MarketOnlyError("UNKNOWN_STRATEGY") from None
    module = _STRATEGY_MODULES.get(name)
    if module is None:
        path = Path(__file__).resolve().parent / spec.directory / spec.module
        module_spec = importlib.util.spec_from_file_location(
            f"_market_only_007_{name}", path
        )
        if module_spec is None or module_spec.loader is None:
            raise MarketOnlyError("STRATEGY_SOURCE_UNAVAILABLE")
        module = importlib.util.module_from_spec(module_spec)
        import sys

        sys.modules[module_spec.name] = module
        module_spec.loader.exec_module(module)
        _STRATEGY_MODULES[name] = module
    return getattr(module, spec.class_name)


def _guarded_strategy(name: str) -> type:
    guarded = _GUARDED_STRATEGIES.get(name)
    if guarded is not None:
        return guarded
    base = _load_strategy_class(name)
    guarded = type(
        f"MarketOnly_{base.__name__}",
        (MarketOnlyStrategyGuard, base),
        {"__module__": __name__},
    )
    _GUARDED_STRATEGIES[name] = guarded
    return guarded


def _strategy_kwargs(strategy_class: type) -> dict[str, Any]:
    try:
        names = {name for name, _value in strategy_class.params._getitems()}
    except AttributeError:
        names = {name for name, _value in strategy_class.params}
    kwargs: dict[str, Any] = {}
    if "enable_trading" in names:
        kwargs["enable_trading"] = False
    for name in ("force_entry_after_bars", "force_exit_after_bars", "force_entry_tick", "force_exit_tick"):
        if name in names:
            kwargs[name] = 0
    if "bar_source" in names:
        kwargs["bar_source"] = "datafeed"
    return kwargs


def _create_cerebro(
    strategy_name: str,
    reader_factory: Callable[[str, str], Any],
    *,
    deadline: float | None = None,
    receipt_sink: Any = None,
) -> bt.Cerebro:
    spec = STRATEGIES[strategy_name]
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.setbroker(MarketOnlyBroker())
    strategy_class = _guarded_strategy(strategy_name)
    kwargs = _strategy_kwargs(strategy_class)
    if "enable_trading" in kwargs and kwargs["enable_trading"] is not False:
        raise MarketOnlyError("TRADING_FLAG_NOT_DISABLED")
    cerebro.addstrategy(strategy_class, **kwargs)
    for symbol, venue in spec.instruments:
        data = MarketHubFeed(
            reader=reader_factory(symbol, venue),
            symbol=symbol,
            deadline=deadline,
            receipt_sink=receipt_sink,
        )
        if spec.resample_seconds:
            timeframe = bt.TimeFrame.Minutes if spec.resample_seconds == 60 else bt.TimeFrame.Seconds
            compression = 1 if spec.resample_seconds == 60 else spec.resample_seconds
            data.resample(timeframe=timeframe, compression=compression)
        cerebro.adddata(data, name=symbol)
    return cerebro


def _write_receipt_scope(receipt_sink: Any, cerebro: bt.Cerebro | None, results: list[Any] | None) -> None:
    if receipt_sink is None:
        return
    broker = None if cerebro is None else cerebro.getbroker()
    strategies = list(results or ())
    if not strategies and cerebro is not None:
        strategies = list(getattr(cerebro, "runningstrats", ()) or ())
    metrics = {
        "market_operation_allowlist": [
            "market.subscribe",
            "market.unsubscribe",
            "market.snapshot",
            "market.head",
            "market.read_after",
        ],
        "market_operation_counts_instrumented": False,
        "strategy_order_attempts": sum(getattr(s, "market_only_order_attempts", 0) for s in strategies),
        "strategy_order_rejections": sum(getattr(s, "market_only_order_rejections", 0) for s in strategies),
        "strategy_cancel_attempts": sum(getattr(s, "market_only_cancel_attempts", 0) for s in strategies),
        "strategy_cancel_rejections": sum(getattr(s, "market_only_cancel_rejections", 0) for s in strategies),
        "broker_order_attempts": getattr(broker, "market_only_order_attempts", 0),
        "broker_order_rejections": getattr(broker, "market_only_order_rejections", 0),
        "broker_cancel_attempts": getattr(broker, "market_only_cancel_attempts", 0),
        "broker_cancel_rejections": getattr(broker, "market_only_cancel_rejections", 0),
        "account_read_attempts": getattr(broker, "market_only_account_read_attempts", 0),
        "global_zero_write_claim": False,
    }
    receipt_sink.record_zero_write_scope(metrics)


def run_market_only(
    strategy_name: str,
    *,
    connection: Any,
    run_root: str | Path,
    run_seconds: float | None = None,
    generation_id: str | None = None,
    run_identity: MarketOnlyRunIdentity | None = None,
    receipt_sink: Any = None,
    identity_guard: Any = None,
) -> tuple[MarketOnlyRunIdentity, list[Any]]:
    """Run one observer using only a trusted in-memory Gateway market connection.

    The caller owns credential/config acquisition. This function accepts no
    config path, old state root, recovery flag, or strategy parameter override.
    A single strategy name is required; this API does not start a strategy group.
    """
    if type(strategy_name) is not str:
        raise MarketOnlyError("SINGLE_STRATEGY_RUN_REQUIRED")
    if strategy_name not in STRATEGIES:
        raise MarketOnlyError("UNKNOWN_STRATEGY")
    if run_seconds is not None:
        if type(run_seconds) not in (int, float) or not math.isfinite(float(run_seconds)) or run_seconds <= 0:
            raise MarketOnlyError("INVALID_RUN_DEADLINE")
    if not _RUN_LOCK.acquire(blocking=False):
        raise MarketOnlyError("MARKET_ONLY_RUN_ALREADY_ACTIVE")
    try:
        if _UNCERTAIN_SESSIONS:
            # A close failure leaves the fixed Gateway strategy identity's
            # registration/MarketHub ownership uncertain. Do not start another
            # runtime in this process and do not try to clean the old one here.
            raise MarketOnlyError("MARKET_ONLY_UNCERTAIN_SESSION_RETAINED")
        identity = run_identity or create_market_only_run_identity(
            run_root,
            bucket="strategies-market-only" if receipt_sink is not None else "market-only",
        )
        if type(identity) is not MarketOnlyRunIdentity or identity.run_root.parent.parent != Path(run_root):
            raise MarketOnlyError("RUN_IDENTITY_INVALID")
        session = CtpGatewayMarketOnlySession(connection)
        deadline = None if run_seconds is None else time.monotonic() + float(run_seconds)
        cerebro = None
        results = None
        try:
            if receipt_sink is not None:
                receipt_sink.record_start(
                    generation_id=generation_id,
                    run_id=identity.run_id,
                    strategy=strategy_name,
                    instruments=list(STRATEGIES[strategy_name].instruments),
                )
            if identity_guard is not None:
                identity_guard.mark_active(generation_id=generation_id, run_id=identity.run_id)
            session.start()
            cerebro = _create_cerebro(
                strategy_name, session.new_reader, deadline=deadline, receipt_sink=receipt_sink
            )
            results = cerebro.run(runonce=False, preload=False, exactbars=1)
            return identity, results
        finally:
            try:
                session.close()
            except Exception:
                try:
                    _write_receipt_scope(receipt_sink, cerebro, results)
                except Exception:
                    pass
                try:
                    if receipt_sink is not None:
                        receipt_sink.record_cleanup(status="uncertain")
                except Exception:
                    pass
                if identity_guard is not None:
                    try:
                        identity_guard.mark_uncertain()
                    except Exception:
                        # Preserve the original close failure. The active
                        # marker still blocks a later invocation if rewriting
                        # it to UNCERTAIN also fails.
                        pass
                # Keep references and the process/global identity lease alive.
                if session not in _UNCERTAIN_SESSIONS:
                    _UNCERTAIN_SESSIONS.append(session)
                if identity_guard is not None:
                    if identity_guard not in _UNCERTAIN_SESSIONS:
                        _UNCERTAIN_SESSIONS.append(identity_guard)
                raise MarketOnlyError("MARKET_SESSION_CLOSE_UNCERTAIN") from None
            try:
                if identity_guard is not None and identity_guard.retained:
                    raise MarketOnlyError("MARKET_IDENTITY_CLEANUP_UNCERTAIN")
                _write_receipt_scope(receipt_sink, cerebro, results)
                if receipt_sink is not None:
                    receipt_sink.record_cleanup(status="clean")
                if identity_guard is not None:
                    identity_guard.clear_active_marker()
                    identity_guard.release_clean()
            except Exception:
                if identity_guard is not None:
                    try:
                        identity_guard.mark_uncertain()
                    except Exception:
                        pass
                try:
                    _write_receipt_scope(receipt_sink, cerebro, results)
                except Exception:
                    pass
                try:
                    if receipt_sink is not None:
                        receipt_sink.record_cleanup(status="uncertain")
                except Exception:
                    pass
                if session not in _UNCERTAIN_SESSIONS:
                    _UNCERTAIN_SESSIONS.append(session)
                if identity_guard is not None:
                    if identity_guard not in _UNCERTAIN_SESSIONS:
                        _UNCERTAIN_SESSIONS.append(identity_guard)
                raise MarketOnlyError("MARKET_ONLY_FINALIZATION_UNCERTAIN") from None
    finally:
        _RUN_LOCK.release()
