"""Feed-sealed native-consumer coverage for the Iteration 24 C/P/F example.

This is a finite local fixture, not a SimNow or live-CTP result.  It runs the
real Store, three BtApiFeed instances, a market-data-only BtApiBroker,
``Cerebro.run`` and the strategy.  The strategy must consume Feed-sealed
``BarEvidence`` and must not reconstruct a cohort from mutable Backtrader
lines or a replay producer.
"""

from __future__ import annotations

import copy
import datetime as dt
import importlib
from types import MappingProxyType, SimpleNamespace
from typing import Any, Dict, Iterable, Mapping, Sequence

import backtrader as bt
import pytest

from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.events import TickEvent
from backtrader.feeds import BarEvidence, ClockMapping
from backtrader.stores.btapistore import BtApiStore
from tests.fixtures.fake_btapi import FakeBtApiClient

runner = importlib.import_module("examples.014_2_ctp_options_midfreq.run")
strategy_module = importlib.import_module(
    "examples.014_2_ctp_options_midfreq.ctp_options_midfreq_strategy"
)

CONFIG = runner.validate_config(runner.load_config())
CANDIDATE = CONFIG["candidate"]
FUTURE = CANDIDATE["contracts"]["future"]
CALL = CANDIDATE["contracts"]["call"]
PUT = CANDIDATE["contracts"]["put"]
SYMBOLS = (FUTURE, CALL, PUT)
BASE = dt.datetime(2026, 1, 5, 9, 0, tzinfo=dt.timezone.utc)
EXCHANGE = CANDIDATE["exchange"]
RULES_HASH = CANDIDATE["rules_hash"]
CLOCK_DOMAIN = "iter24-replay-clock"
SESSION_SEGMENT = "replay-minute"


def _clock_mapping(generation: int) -> ClockMapping:
    """Return the explicit synthetic mapping for one source generation."""

    return ClockMapping(
        mapping_id=f"iter24-local-feed-sealed-mapping-g{generation}",
        wall_utc_at_anchor=BASE,
        mono_ns_at_anchor=1_000_000_000,
        clock_domain_id=CLOCK_DOMAIN,
        connection_generation=generation,
        source="iter24.local-feed-sealed.registry",
        error_bound_ns=0,
        valid_until_mono_ns=1_000_000_000 + 10**15,
        rules_hash=RULES_HASH,
        synthetic=True,
    )


def _source_tick_snapshot(tick: TickEvent) -> Mapping[str, Any]:
    """Freeze the source fields that become one FQ2 quote evidence record."""

    return MappingProxyType(
        {
            "event_id": tick.event_id,
            "symbol": tick.symbol,
            "exchange": tick.exchange,
            "event_time": tick.event_time_utc,
            "received_at": tick.recv_time_utc,
            "received_monotonic_ns": tick.received_monotonic_ns,
            "ingest_seq": tick.ingest_seq,
            "generation": tick.connection_generation,
            "trading_day": tick.trading_day,
            "session_segment": tick.session_segment,
            "rules_hash": tick.rules_hash,
            "clock_domain": tick.clock_domain_id,
            "clock_mode": "replay",
            "candidate_id": CANDIDATE["candidate_id"],
            "quality": "GOOD",
            "volume_complete": tick.volume_complete,
            "bid": tick.bid_price,
            "ask": tick.ask_price,
            "bid_qty": tick.bid_volume,
            "ask_qty": tick.ask_volume,
            "last": tick.price,
            "source": tick.source,
            "event_time_source": tick.event_time_source,
            "source_clock_error_ms": tick.source_clock_error_ms,
            "receive_clock_error_ms": tick.receive_clock_error_ms,
        }
    )


class FiniteCtpFixtureClient(FakeBtApiClient):
    """Finite CTP-v2-shaped source whose write boundary fails loudly."""

    def __init__(
        self,
        *args: Any,
        final_watermark: dt.datetime,
        interleave_symbols: Iterable[str] = (),
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._final_watermark = final_watermark
        self._interleave_symbols = tuple(interleave_symbols)
        self._next_interleave_symbol = 0
        self.delivered_source_ticks: Dict[str, list[Mapping[str, Any]]] = {
            symbol: [] for symbol in SYMBOLS
        }

    def is_source_exhausted(self, symbol: str) -> bool:
        return not self.live_ticks.get(symbol)

    def get_source_event_time_watermark(self, _symbol: str) -> dt.datetime:
        return self._final_watermark

    def poll_tick(self, dataname: str) -> Any:
        if self._interleave_symbols:
            expected = self._interleave_symbols[self._next_interleave_symbol]
            if dataname != expected:
                return None
        tick = super().poll_tick(dataname)
        if tick is not None:
            self.delivered_source_ticks[dataname].append(_source_tick_snapshot(tick))
        if tick is not None and self._interleave_symbols:
            self._next_interleave_symbol = (self._next_interleave_symbol + 1) % len(
                self._interleave_symbols
            )
        return tick

    def submit_order(self, _payload: Mapping[str, Any]) -> None:
        raise AssertionError("market-data-only Feed fixture must never submit an order")

    def cancel_order(self, _order_ref: Any, dataname: str | None = None) -> None:
        raise AssertionError(
            "market-data-only Feed fixture must never cancel an order " f"for {dataname}"
        )


class FixedClock:
    def monotonic_ns(self) -> int:
        return 1_000_000_000


def _tick_at(
    symbol: str,
    *,
    bid: float,
    ask: float,
    bid_qty: float,
    ask_qty: float,
    ingest_seq: int,
    timestamp: dt.datetime,
    generation: int,
    session_segment: str,
) -> TickEvent:
    """Build one strict CTP-v2 source event with its exact frozen quote values."""

    last = (bid + ask) / 2.0
    received_at = timestamp + dt.timedelta(microseconds=1)
    mapping = _clock_mapping(generation)
    event_id = f"iter24.local-feed-sealed:{symbol}:{generation}:{ingest_seq}"
    event = TickEvent(
        timestamp=timestamp.timestamp(),
        symbol=symbol,
        exchange=EXCHANGE,
        asset_type="ctp-option" if symbol != FUTURE else "ctp-future",
        local_time=timestamp.timestamp(),
        exchange_time=timestamp.timestamp(),
        received_wall_time=received_at.timestamp(),
        received_monotonic_ns=mapping.map_wall_to_mono_ns(received_at),
        sequence=ingest_seq,
        snapshot_or_delta="snapshot",
        continuity_status="continuous",
        source="iter24.local-feed-sealed.fixture",
        event_id=event_id,
        price=last,
        volume=1.0,
        direction="buy",
        trade_id=event_id,
        bid_price=bid,
        ask_price=ask,
        bid_volume=bid_qty,
        ask_volume=ask_qty,
    )
    event.datetime = timestamp.replace(tzinfo=None)
    event.schema_version = "ctp.quote.v2"
    event.volume_semantics = "delta"
    event.cum_volume = 100.0 + ingest_seq
    event.cumulative_volume = 100.0 + ingest_seq
    event.delta_volume = 1.0
    event.volume_complete = True
    event.volume_quality = "CONTINUOUS"
    event.trading_day = timestamp.strftime("%Y%m%d")
    event.action_day = event.trading_day
    event.event_time_utc = timestamp
    event.recv_time_utc = received_at
    event.recv_monotonic_ns = mapping.map_wall_to_mono_ns(received_at)
    event.received_monotonic_ns = event.recv_monotonic_ns
    event.clock_domain_id = CLOCK_DOMAIN
    event.connection_generation = generation
    event.subscription_epoch = 1
    event.ingest_seq = ingest_seq
    event.rules_hash = RULES_HASH
    event.session_segment = session_segment
    event.source_clock_quality = "verified"
    event.receive_clock_quality = "verified"
    event.source_clock_error_ms = 0.0
    event.receive_clock_error_ms = 0.0
    event.freshness_verified = True
    event.execution_eligible = True
    event.quality_flags = ()
    event.event_time_source = "exchange-event-fixture"
    event.stale = False
    event.stale_reason = ""
    event.continuity_status = "continuous"
    event.snapshot_or_delta = "snapshot"
    return event


class ImmutableQuoteRegistry:
    """Immutable FQ2 source records frozen solely from the Feed input ticks."""

    def __init__(self, source_ticks: Mapping[str, Sequence[TickEvent]]) -> None:
        by_bucket: Dict[tuple[str, dt.datetime], list[Mapping[str, Any]]] = {}
        self._source_by_symbol: Dict[str, tuple[Mapping[str, Any], ...]] = {}
        self._emitted_evidence: list[BarEvidence] = []
        for symbol in SYMBOLS:
            entries = []
            for tick in source_ticks.get(symbol, ()):
                assert tick.symbol == symbol
                snapshot = _source_tick_snapshot(tick)
                assert snapshot["last"] == (snapshot["bid"] + snapshot["ask"]) / 2.0
                assert snapshot["event_time"] <= snapshot["received_at"]
                bucket_end = snapshot["event_time"].replace(second=0, microsecond=0) + dt.timedelta(
                    minutes=1
                )
                by_bucket.setdefault((symbol, bucket_end), []).append(snapshot)
                entries.append(snapshot)
            self._source_by_symbol[symbol] = tuple(entries)

        frozen_buckets: Dict[tuple[str, dt.datetime], tuple[Mapping[str, Any], ...]] = {}
        for key, entries in by_bucket.items():
            ordered = tuple(sorted(entries, key=lambda item: int(item["ingest_seq"])))
            assert len({item["event_id"] for item in ordered}) == len(ordered)
            assert all(
                earlier["ingest_seq"] < later["ingest_seq"]
                for earlier, later in zip(ordered, ordered[1:])
            )
            frozen_buckets[key] = ordered
        self._by_bucket = MappingProxyType(frozen_buckets)

    def source_quote_count(self, symbol: str) -> int:
        """Return the immutable count for one exact Feed source subscription."""

        return len(self._source_by_symbol[symbol])

    @property
    def emitted_evidence(self) -> tuple[BarEvidence, ...]:
        """Expose only immutable, provider-emitted evidence for test assertions."""

        return tuple(self._emitted_evidence)

    def quotes_for_bar(self, bar: Any) -> tuple[Mapping[str, Any], ...]:
        """Return exactly the source quotes in this Feed-sealed bar range."""

        source_bucket = self._by_bucket.get((bar.symbol, bar.bucket_end))
        assert source_bucket
        generation = getattr(bar, "connection_generation", None)
        if generation is None:
            generation = bar.generation
        clock_domain = getattr(bar, "clock_domain_id", None)
        if clock_domain is None:
            clock_domain = bar.clock_domain
        quotes = tuple(
            quote
            for quote in source_bucket
            if bar.first_ingest_seq <= int(quote["ingest_seq"]) <= bar.last_ingest_seq
        )
        assert quotes
        sequences = tuple(int(quote["ingest_seq"]) for quote in quotes)
        assert sequences[0] == bar.first_ingest_seq
        assert sequences[-1] == bar.last_ingest_seq == bar.quote_cutoff_seq
        assert all(quote["event_time"] <= bar.max_event_time for quote in quotes)
        assert all(quote["received_at"] <= bar.available_at for quote in quotes)
        assert all(quote["exchange"] == bar.exchange for quote in quotes)
        assert all(quote["generation"] == generation for quote in quotes)
        assert all(quote["trading_day"] == bar.trading_day for quote in quotes)
        assert all(quote["session_segment"] == bar.session_segment for quote in quotes)
        assert all(quote["rules_hash"] == bar.rules_hash for quote in quotes)
        assert all(quote["clock_domain"] == clock_domain for quote in quotes)
        return quotes

    def assert_evidence_matches_source(self, evidence: BarEvidence) -> None:
        """Prove every sealed evidence quote is an exact immutable Feed source record."""

        expected = self.quotes_for_bar(evidence)
        assert tuple(evidence.quote_events) == expected
        for source, quote in zip(expected, evidence.quote_events):
            for field in (
                "event_id",
                "symbol",
                "event_time",
                "received_at",
                "ingest_seq",
                "bid",
                "ask",
                "bid_qty",
                "ask_qty",
                "last",
            ):
                assert quote[field] == source[field]

    def record_emitted_evidence(self, evidence: BarEvidence) -> None:
        """Retain an emitted proof after validating its source provenance."""

        self.assert_evidence_matches_source(evidence)
        self._emitted_evidence.append(evidence)

    def assert_delivery_matches_source(
        self, delivered: Mapping[str, Sequence[Mapping[str, Any]]]
    ) -> None:
        """Prove the Fake client handed Feed the exact registry source values."""

        for symbol in SYMBOLS:
            expected = self._source_by_symbol[symbol]
            actual = tuple(delivered[symbol])
            assert len(actual) == len(expected)
            for source, observed in zip(expected, actual):
                for field in (
                    "event_id",
                    "symbol",
                    "event_time",
                    "received_at",
                    "ingest_seq",
                    "bid",
                    "ask",
                    "bid_qty",
                    "ask_qty",
                    "last",
                ):
                    assert observed[field] == source[field]

    def assert_decision_matches_source(self, decision: Any) -> None:
        """Prove the strategy received the exact immutable Feed input quotes."""

        for symbol, bar in decision.bars.items():
            expected = self.quotes_for_bar(bar)
            actual = tuple(decision.accepted_quotes[symbol])
            assert len(actual) == len(expected)
            for source, observed in zip(expected, actual):
                for field in (
                    "event_id",
                    "symbol",
                    "event_time",
                    "received_at",
                    "ingest_seq",
                    "bid",
                    "ask",
                    "bid_qty",
                    "ask_qty",
                    "last",
                ):
                    assert observed[field] == source[field]


class ClosedEvidenceFactory:
    """Feed callback that turns only registry-frozen TickEvent records into evidence."""

    def __init__(self, registry: ImmutableQuoteRegistry) -> None:
        self._registry = registry

    def __call__(self, bar: Any) -> BarEvidence:
        assert bar.symbol in SYMBOLS
        assert bar.exchange == EXCHANGE
        assert bar.rules_hash == RULES_HASH
        assert bar.quote_cutoff_seq == bar.last_ingest_seq
        quotes = self._registry.quotes_for_bar(bar)
        mapping = _clock_mapping(bar.connection_generation)
        evidence = BarEvidence(
            symbol=bar.symbol,
            exchange=bar.exchange,
            bucket_start=bar.bucket_start,
            bucket_end=bar.bucket_end,
            available_at=bar.available_at,
            seal_received_mono=mapping.map_wall_to_mono_ns(bar.available_at) / 1_000_000_000.0,
            seal_received_at=bar.available_at,
            trading_day=bar.trading_day,
            generation=bar.connection_generation,
            session_segment=bar.session_segment,
            rules_hash=bar.rules_hash,
            quality=bar.quality,
            volume_complete=bar.volume_complete,
            first_ingest_seq=bar.first_ingest_seq,
            last_ingest_seq=bar.last_ingest_seq,
            quote_cutoff_seq=bar.quote_cutoff_seq,
            bar_id=bar.bar_id,
            bar_sequence=bar.bar_sequence,
            closure_reason=bar.closure_reason,
            watermark=bar.watermark,
            max_event_time=bar.max_event_time,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            openinterest=bar.openinterest,
            quote_events=quotes,
            clock_domain=bar.clock_domain_id,
            clock_mode="replay",
            candidate_id=CANDIDATE["candidate_id"],
            timeframe_seconds=60.0,
            trade_count=bar.trade_count,
            complete=bar.complete,
            clock_mapping=mapping,
        )
        self._registry.record_emitted_evidence(evidence)
        return evidence


def _native_ticks(
    minutes: int,
    *,
    generations: Sequence[int] | None = None,
    session_segments: Sequence[str] | None = None,
) -> Dict[str, list[TickEvent]]:
    """Emit strict FQ2 source ticks; the registry will freeze these exact fields."""

    if generations is None:
        generations = (7,) * minutes
    if session_segments is None:
        session_segments = (SESSION_SEGMENT,) * minutes
    if len(generations) != minutes or len(session_segments) != minutes:
        raise ValueError("each synthetic minute needs generation and session evidence")
    result: Dict[str, list[TickEvent]] = {symbol: [] for symbol in SYMBOLS}
    for minute_index in range(minutes):
        for sample in range(60):
            timestamp = BASE + dt.timedelta(minutes=minute_index, seconds=sample)
            for symbol_index, symbol in enumerate(SYMBOLS, start=1):
                if symbol == FUTURE:
                    bid, ask, bid_qty, ask_qty = 999.0, 1001.0, 2.0, 2.0
                elif symbol == CALL:
                    bid, ask, bid_qty, ask_qty = 9.0, 11.0, 1.0, 3.0
                else:
                    bid, ask, bid_qty, ask_qty = 9.0, 11.0, 3.0, 1.0
                ingest_seq = (minute_index + 1) * 100_000 + 10_000 + sample * 3 + symbol_index
                result[symbol].append(
                    _tick_at(
                        symbol,
                        bid=bid,
                        ask=ask,
                        bid_qty=bid_qty,
                        ask_qty=ask_qty,
                        ingest_seq=ingest_seq,
                        timestamp=timestamp,
                        generation=generations[minute_index],
                        session_segment=session_segments[minute_index],
                    )
                )
    return result


def _run_chain(
    strategy_cls: type,
    *,
    attach_feed_evidence: bool,
    live_ticks: Dict[str, list[TickEvent]] | None = None,
    final_watermark: dt.datetime | None = None,
    strategy_kwargs: Mapping[str, Any] | None = None,
    dispatch_bars: bool = True,
    dispatch_ticks: bool = False,
) -> tuple[FiniteCtpFixtureClient, BtApiBroker, list[Any], Any, ImmutableQuoteRegistry]:
    """Run one Store/three-Feed/Broker/Cerebro chain with no transport writes."""

    live_ticks = _native_ticks(1) if live_ticks is None else live_ticks
    registry = ImmutableQuoteRegistry(live_ticks)
    evidence_provider = ClosedEvidenceFactory(registry) if attach_feed_evidence else None
    if final_watermark is None:
        final_watermark = BASE + dt.timedelta(minutes=1, milliseconds=500)
    client = FiniteCtpFixtureClient(
        live_ticks=live_ticks,
        final_watermark=final_watermark,
        interleave_symbols=SYMBOLS,
    )
    store = BtApiStore(provider="btapi", api=client, market_data_only=True)
    broker = BtApiBroker(
        store=store,
        provider="btapi",
        market_data_only=True,
        sdk_preflight=False,
        flatten_on_stop=False,
        force_refresh_queries=False,
    )
    cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
    cerebro.setbroker(broker)
    feeds = []
    for symbol in SYMBOLS:
        feed = store.getdata(
            dataname=symbol,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            backfill_start=False,
            dispatch_ticks=dispatch_ticks,
            dispatch_bars=dispatch_bars,
            qcheck=0,
            price_tick=1.0,
            clock=FixedClock(),
            closed_bar_evidence_provider=evidence_provider,
        )
        feeds.append(feed)
        cerebro.adddata(feed, name=symbol)
    params = {
        "config": copy.deepcopy(CONFIG),
        "require_feed_bar_evidence": True,
    }
    params.update(strategy_kwargs or {})
    cerebro.addstrategy(strategy_cls, **params)
    [strategy] = cerebro.run(preload=False, runonce=False)
    return client, broker, feeds, strategy, registry


def _assert_zero_write(client: FiniteCtpFixtureClient, broker: BtApiBroker) -> None:
    """Assert the fixture client submitted nothing and the broker is read-only."""
    assert client.submitted_orders == []
    assert client.cancelled_orders == []
    assert broker.get_param("market_data_only") is True


def test_feed_sealed_bars_reach_midfreq_strategy_without_raw_reconstruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real chain delivers an immutable Feed-sealed F/C/P decision input."""

    strategy_cls = strategy_module.CTPOptionsMidFrequencyStrategy
    assert dict(strategy_cls.params._getitems())["require_feed_bar_evidence"] is False

    def raw_reconstruction_forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Feed-sealed path rebuilt evidence from raw producer or lines")

    monkeypatch.setattr(strategy_cls, "_bar_evidence", raw_reconstruction_forbidden)
    monkeypatch.setattr(strategy_cls, "_current_synchronous_minute", raw_reconstruction_forbidden)
    client, broker, feeds, strategy, registry = _run_chain(
        strategy_cls,
        attach_feed_evidence=True,
        live_ticks=_native_ticks(2),
        final_watermark=BASE + dt.timedelta(minutes=2, milliseconds=500),
    )

    decision = strategy._last_decision_input
    assert decision is not None, {
        "rejections": list(strategy._rejections),
        "barrier_results": list(strategy._barrier_results),
        "feed_sequences": [feed._bar_sequence for feed in feeds],
    }
    assert set(decision.bars) == set(SYMBOLS)
    assert all(isinstance(bar, BarEvidence) for bar in decision.bars.values())
    assert all(bar.rules_hash == RULES_HASH for bar in decision.bars.values())
    assert all(bar.session_segment == SESSION_SEGMENT for bar in decision.bars.values())
    assert client.subscriptions == list(SYMBOLS)
    assert all(registry.source_quote_count(symbol) >= 100 for symbol in SYMBOLS)
    assert all(len(client.delivered_source_ticks[symbol]) >= 100 for symbol in SYMBOLS)
    assert len(registry.emitted_evidence) >= len(SYMBOLS) * 2
    assert all(
        sum(evidence.symbol == symbol for evidence in registry.emitted_evidence) >= 2
        for symbol in SYMBOLS
    )
    registry.assert_delivery_matches_source(client.delivered_source_ticks)
    for evidence in registry.emitted_evidence:
        registry.assert_evidence_matches_source(evidence)
    registry.assert_decision_matches_source(decision)
    assert strategy.build_report()["input_boundary"] == "feed_sealed_closed_bar_evidence"
    assert strategy.build_report()["feed_evidence"]["fault"] is None
    _assert_zero_write(client, broker)


@pytest.mark.parametrize(
    ("dispatch_bars", "dispatch_ticks"),
    ((False, False), (True, True)),
    ids=("bar-dispatch-disabled", "raw-tick-dispatch-enabled"),
)
def test_feed_mode_requires_bar_only_btapifeed_dispatch_contract(
    dispatch_bars: bool, dispatch_ticks: bool
) -> None:
    """Opt-in evidence mode rejects a Feed that could expose raw tick callbacks."""

    with pytest.raises(strategy_module.ConfigurationError) as excinfo:
        _run_chain(
            strategy_module.CTPOptionsMidFrequencyStrategy,
            attach_feed_evidence=True,
            dispatch_bars=dispatch_bars,
            dispatch_ticks=dispatch_ticks,
        )

    assert excinfo.value.code == "FEED_EVIDENCE_DISPATCH"


def test_feed_mode_rejects_missing_evidence_without_raw_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An absent Feed provider cannot fall back to a replay producer or lines."""

    strategy_cls = strategy_module.CTPOptionsMidFrequencyStrategy

    def raw_reconstruction_forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("missing Feed evidence fell back to raw producer or lines")

    monkeypatch.setattr(strategy_cls, "_bar_evidence", raw_reconstruction_forbidden)
    monkeypatch.setattr(strategy_cls, "_current_synchronous_minute", raw_reconstruction_forbidden)
    client, broker, _, strategy, _ = _run_chain(strategy_cls, attach_feed_evidence=False)

    assert strategy._last_decision_input is None
    assert "FEED_CLOSED_BAR_EVIDENCE_REQUIRED" in strategy._rejections
    _assert_zero_write(client, broker)


def test_direct_closed_evidence_callback_lacks_feed_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A look-alike callback cannot replace BtApiFeed's synchronous hand-off."""

    strategy_cls = strategy_module.CTPOptionsMidFrequencyStrategy
    client, broker, _, strategy, _ = _run_chain(strategy_cls, attach_feed_evidence=True)
    decision = strategy._last_decision_input
    assert decision is not None

    def raw_reconstruction_forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("direct callback fell back to raw producer or lines")

    monkeypatch.setattr(strategy_cls, "_bar_evidence", raw_reconstruction_forbidden)
    prior_results = len(strategy._barrier_results)
    strategy.notify_bar(SimpleNamespace(closed_bar_evidence=decision.bars[FUTURE]))

    assert len(strategy._barrier_results) == prior_results
    assert "FEED_CLOSED_BAR_PROVENANCE_REQUIRED" in strategy._rejections
    _assert_zero_write(client, broker)


def test_late_feed_leg_cannot_form_a_decision_or_transport_write() -> None:
    """A real Feed bar arriving in the next bucket remains below the barrier."""

    live_ticks = _native_ticks(1)
    delayed = _native_ticks(2)[PUT][60:]
    live_ticks[PUT] = delayed
    client, broker, _, strategy, _ = _run_chain(
        strategy_module.CTPOptionsMidFrequencyStrategy,
        attach_feed_evidence=True,
        live_ticks=live_ticks,
        final_watermark=BASE + dt.timedelta(minutes=2, milliseconds=500),
    )

    assert strategy._last_decision_input is None
    assert any(item["reason"] == "SKIP_BARRIER_TIMEOUT" for item in strategy._barrier_results)
    _assert_zero_write(client, broker)


def test_feed_decision_queue_overflow_latches_without_transport_write() -> None:
    """A stalled strategy cannot retain an unbounded Feed-ahead-of-next backlog."""

    class NoConsumeStrategy(strategy_module.CTPOptionsMidFrequencyStrategy):
        def __init__(self) -> None:
            super().__init__()
            self.next_queue_states = []

        def next(self) -> None:
            self.next_queue_states.append(
                (
                    self._event_count,
                    len(self._pending_feed_decision_inputs),
                    self._feed_evidence_fault,
                )
            )

    client, broker, _, strategy, _ = _run_chain(
        NoConsumeStrategy,
        attach_feed_evidence=True,
        live_ticks=_native_ticks(2),
        final_watermark=BASE + dt.timedelta(minutes=2, milliseconds=500),
    )

    assert sum(item["ready"] for item in strategy._barrier_results) == 2
    assert strategy._feed_evidence_fault == "FEED_BAR_DECISION_QUEUE_OVERFLOW"
    assert not strategy._pending_feed_decision_inputs
    assert strategy._last_decision_input is None
    assert "FEED_BAR_DECISION_QUEUE_OVERFLOW" in strategy._rejections
    _assert_zero_write(client, broker)


def test_feed_scope_reset_revokes_queued_prior_generation_before_later_next() -> None:
    """A genuine Feed generation/session reset cannot let a held old input reach ``next``."""

    class HoldFirstFeedDecision(strategy_module.CTPOptionsMidFrequencyStrategy):
        def __init__(self) -> None:
            super().__init__()
            self.held_generation: int | None = None
            self.consumed_generations: list[int] = []
            self.feed_ingest_records: list[dict[str, Any]] = []

        def _ingest_bar_evidence(self, bar: BarEvidence) -> Any:
            accepted = super()._ingest_bar_evidence(bar)
            result = self._barrier_results[-1]
            self.feed_ingest_records.append(
                {
                    "generation": bar.generation,
                    "session_segment": bar.session_segment,
                    "reason": result["reason"],
                    "reset_warmup": result["reset_warmup"],
                    "scope_reset": result["scope_reset"],
                    "pending_generations": tuple(
                        decision.bars[FUTURE].generation
                        for decision in self._pending_feed_decision_inputs
                    ),
                    "last_generation": (
                        None
                        if self._last_decision_input is None
                        else self._last_decision_input.bars[FUTURE].generation
                    ),
                }
            )
            return accepted

        def next(self) -> None:
            queued_generations = tuple(
                decision.bars[FUTURE].generation for decision in self._pending_feed_decision_inputs
            )
            if queued_generations and self.held_generation is None:
                # This is the deliberate Feed-before-next window: retain the
                # first (generation 7) item until a subsequent Feed callback
                # proves that a scope reset revokes it.
                self.held_generation = queued_generations[0]
                return
            if queued_generations:
                self.consumed_generations.append(queued_generations[0])
            super().next()

    generations = (7, 7, 8, 8, 8)
    session_segments = (
        SESSION_SEGMENT,
        SESSION_SEGMENT,
        "replay-minute-gen8",
        "replay-minute-gen8",
        "replay-minute-gen8",
    )
    client, broker, _, strategy, _ = _run_chain(
        HoldFirstFeedDecision,
        attach_feed_evidence=True,
        live_ticks=_native_ticks(
            len(generations), generations=generations, session_segments=session_segments
        ),
        final_watermark=BASE + dt.timedelta(minutes=len(generations), milliseconds=500),
    )

    assert strategy.held_generation == 7
    reset_records = [record for record in strategy.feed_ingest_records if record["scope_reset"]]
    assert reset_records
    assert any(
        record["generation"] == 8
        and record["session_segment"] == "replay-minute-gen8"
        and record["reset_warmup"]
        and record["pending_generations"] == ()
        and record["last_generation"] is None
        for record in reset_records
    )
    assert strategy.consumed_generations
    assert 7 not in strategy.consumed_generations
    assert set(strategy.consumed_generations) == {8}
    _assert_zero_write(client, broker)
