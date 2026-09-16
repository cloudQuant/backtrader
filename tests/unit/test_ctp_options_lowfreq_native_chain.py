"""Offline native-free C/P/F closed-bar chain for the Iteration 23 example.

This test is intentionally not a SimNow or live-CTP claim.  It exercises the
real Store, Feed, Broker, Cerebro and strategy classes with a finite local
CTP-v2-shaped source, and verifies that the strategy consumes the immutable
closed-bar object supplied by the Feed rather than rebuilding evidence from
Backtrader line values.
"""

from __future__ import annotations

import datetime as dt
import importlib
from dataclasses import replace
from types import SimpleNamespace

import backtrader as bt
import pytest

from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.events import TickEvent
from backtrader.feeds import BarEvidence, ClockMapping
from backtrader.stores.btapistore import BtApiStore
from tests.fixtures.fake_btapi import FakeBtApiClient

BASE = dt.datetime(2026, 9, 10, 1, 0, tzinfo=dt.timezone.utc)
CLOCK_DOMAIN = "iter23-local-native-free-clock"
RULES_HASH = "iter23-local-native-free-rules-v1"
EXCHANGE = "CZCE"
FUTURE = "CZCE.SA701"
CALL = "CZCE.SA701C1080"
PUT = "CZCE.SA701P1080"


class FiniteCtpFixtureClient(FakeBtApiClient):
    """A finite, zero-network CTP-v2-shaped source with loud write tracking."""

    def __init__(
        self,
        *args,
        final_watermark=None,
        interleave_symbols=(),
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._final_watermark = final_watermark or (
            BASE + dt.timedelta(minutes=15, milliseconds=500)
        )
        self._interleave_symbols = tuple(interleave_symbols)
        self._next_interleave_symbol = 0

    def is_source_exhausted(self, symbol):
        return not self.live_ticks.get(symbol)

    def get_source_event_time_watermark(self, _symbol):
        return self._final_watermark

    def poll_tick(self, dataname):
        if self._interleave_symbols:
            expected = self._interleave_symbols[self._next_interleave_symbol]
            if dataname != expected:
                return None
        tick = super().poll_tick(dataname)
        if tick is not None and self._interleave_symbols:
            self._next_interleave_symbol = (self._next_interleave_symbol + 1) % len(
                self._interleave_symbols
            )
        return tick

    def submit_order(self, _payload):
        raise AssertionError("market-data-only native-chain fixture must never submit an order")

    def cancel_order(self, _order_ref, dataname=None):
        raise AssertionError(
            f"market-data-only native-chain fixture must never cancel an order for {dataname}"
        )


class FixedClock:
    def monotonic_ns(self):
        return 1_000_000_000


def _tick(symbol, price, ingest_seq):
    event = TickEvent(
        timestamp=BASE.timestamp(),
        symbol=symbol,
        exchange=EXCHANGE,
        asset_type="option" if symbol != FUTURE else "futures",
        local_time=BASE.timestamp(),
        price=price,
        volume=1.0,
        direction="buy",
        bid_price=price - 1.0,
        ask_price=price + 1.0,
        bid_volume=2.0,
        ask_volume=2.0,
    )
    event.datetime = BASE.replace(tzinfo=None)
    event.schema_version = "ctp.quote.v2"
    event.volume_semantics = "delta"
    event.cum_volume = 100.0 + ingest_seq
    event.cumulative_volume = 100.0 + ingest_seq
    event.delta_volume = 1.0
    event.volume_complete = True
    event.volume_quality = "CONTINUOUS"
    event.trading_day = "20260910"
    event.action_day = "20260910"
    event.event_time_utc = BASE
    event.recv_time_utc = BASE + dt.timedelta(microseconds=ingest_seq)
    event.recv_monotonic_ns = 1_000_000_000 + ingest_seq
    event.received_monotonic_ns = event.recv_monotonic_ns
    event.clock_domain_id = CLOCK_DOMAIN
    event.connection_generation = 7
    event.subscription_epoch = 3
    event.ingest_seq = ingest_seq
    event.rules_hash = RULES_HASH
    event.session_segment = "local-native-free"
    event.source = "iter23.local-native-free.fixture"
    event.source_clock_quality = "verified"
    event.receive_clock_quality = "verified"
    event.source_clock_error_ms = 0.0
    event.receive_clock_error_ms = 0.0
    event.freshness_verified = True
    event.execution_eligible = True
    event.quality_flags = ()
    event.event_time_source = "action_day_update_time"
    event.stale = False
    event.stale_reason = ""
    event.continuity_status = "continuous"
    event.snapshot_or_delta = "snapshot"
    return event


def _tick_at(symbol, price, ingest_seq, timestamp):
    """Build the same strict fixture tick at a later closed-bar boundary."""

    event = _tick(symbol, price, ingest_seq)
    event.timestamp = timestamp.timestamp()
    event.local_time = event.timestamp
    event.exchange_time = event.timestamp
    event.received_wall_time = event.timestamp
    event.datetime = timestamp.replace(tzinfo=None)
    event.event_time_utc = timestamp
    event.recv_time_utc = timestamp + dt.timedelta(microseconds=ingest_seq)
    return event


def _eligible_candidate_ticks():
    """Turn the synthetic local 014_1 eligible fixture into sealed Feed input."""

    runner = importlib.import_module("examples.014_1_ctp_options_lowfreq.run")
    config = runner.load_config()
    candidate = config["candidate"]
    assert (candidate["future"], candidate["call"], candidate["put"]) == (FUTURE, CALL, PUT)
    bars_by_symbol = runner.replay_bars(candidate, "eligible")
    live_ticks = {}
    for symbol_index, (symbol, bars) in enumerate(bars_by_symbol.items(), start=1):
        live_ticks[symbol] = [
            _tick_at(
                symbol,
                float(bar["close"]),
                (bar_index * 10) + symbol_index,
                bar["datetime"].replace(tzinfo=dt.timezone.utc) + dt.timedelta(milliseconds=500),
            )
            for bar_index, bar in enumerate(bars, start=1)
        ]
    final_bar_start = bars_by_symbol[FUTURE][-1]["datetime"].replace(tzinfo=dt.timezone.utc)
    return (
        config,
        candidate,
        live_ticks,
        final_bar_start + dt.timedelta(minutes=15, milliseconds=500),
    )


def _candidate_strategy_kwargs(config, candidate, sealed_bar_clock):
    """Bind this native-consumer probe to every candidate configuration input."""

    params = dict(config["strategy_params"])
    symbols = (candidate["future"], candidate["call"], candidate["put"])
    params.update(
        candidate_id=f"{config['strategy_id']}-replay-v1",
        future_symbol=candidate["future"],
        call_symbol=candidate["call"],
        put_symbol=candidate["put"],
        strike=candidate["strike"],
        multiplier=candidate["multiplier"],
        discount=candidate["discount"],
        capital_limit=config["budget"]["capital_limit"],
        ordinary_limit=config["budget"]["ordinary_limit"],
        recovery_reserve=config["budget"]["recovery_reserve"],
        first_send_seconds=config["timing"]["first_send_seconds"],
        completion_seconds=config["timing"]["completion_seconds"],
        minimum_hold_seconds=config["timing"]["minimum_hold_seconds"],
        maximum_hold_seconds=config["timing"]["maximum_hold_seconds"],
        risk_bar_max_age_seconds=config["timing"]["risk_bar_max_age_seconds"],
        session_stop_entry_seconds=config["timing"]["session_stop_entry_seconds"],
        session_exit_seconds=config["timing"]["session_exit_seconds"],
        session_handover_seconds=config["timing"]["session_handover_seconds"],
        price_ticks=dict.fromkeys(symbols, params["price_tick"]),
        exchange_limits={
            symbol: {
                "lower": 0.01,
                "upper": 10_000_000.0,
                "source": "synthetic-replay-price-limit-fixture",
            }
            for symbol in symbols
        },
        fee_schedule=dict.fromkeys(
            (
                "open_buy",
                "open_sell",
                "close_buy",
                "close_sell",
                "close_today_buy",
                "close_today_sell",
            ),
            float(params["round_trip_cost"]) / 6.0,
        ),
        exit_reserve=0.0,
        financing_reserve=0.0,
        model_reserve=0.0,
        clock_provider=sealed_bar_clock,
        require_feed_bar_evidence=True,
        bar_evidence_clock_domain=CLOCK_DOMAIN,
    )
    return params


def _closed_bar_evidence(bar):
    """Freeze Feed-owned closed-bar metadata into the public evidence type."""

    assert bar.rules_hash == RULES_HASH
    assert bar.session_segment == "local-native-free"
    assert bar.quote_cutoff_seq == bar.last_ingest_seq
    mapping = ClockMapping(
        mapping_id="iter23-local-native-free-closed-bar-mapping",
        # One synthetic mapping spans this entire finite replay.  Re-anchoring
        # each bar would itself be a clock-scope change and must be rejected
        # by the real multi-leg barrier.
        wall_utc_at_anchor=BASE,
        mono_ns_at_anchor=1_000_000_000,
        clock_domain_id=bar.clock_domain_id,
        connection_generation=bar.connection_generation,
        source="iter23.local-native-free.closed-bar-fixture",
        error_bound_ns=0,
        valid_until_mono_ns=1_000_000_000 + 10**15,
        rules_hash=bar.rules_hash,
        synthetic=True,
    )
    return BarEvidence(
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
        clock_domain=bar.clock_domain_id,
        clock_mode="replay",
        candidate_id="iter23-local-native-free-v1",
        timeframe_seconds=900.0,
        trade_count=1,
        complete=bar.complete,
        clock_mapping=mapping,
    )


def _run_chain(
    strategy_cls,
    *,
    evidence_provider,
    before_run=None,
    live_ticks=None,
    final_watermark=None,
    interleave_symbols=(),
    strategy_kwargs=None,
):
    """Run one finite Store/Feed/Broker/Cerebro chain without any transport write."""

    client = FiniteCtpFixtureClient(
        live_ticks=(
            {
                FUTURE: [_tick(FUTURE, 1000.0, 1)],
                CALL: [_tick(CALL, 30.0, 2)],
                PUT: [_tick(PUT, 30.0, 3)],
            }
            if live_ticks is None
            else live_ticks
        ),
        final_watermark=final_watermark,
        interleave_symbols=interleave_symbols,
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
    clock = FixedClock()
    for symbol in (FUTURE, CALL, PUT):
        feed = store.getdata(
            dataname=symbol,
            timeframe=bt.TimeFrame.Minutes,
            compression=15,
            backfill_start=False,
            dispatch_ticks=False,
            dispatch_bars=True,
            qcheck=0,
            price_tick=1.0,
            clock=clock,
            closed_bar_evidence_provider=evidence_provider,
        )
        feeds.append(feed)
        cerebro.adddata(feed, name=symbol)
    strategy_args = {
        "candidate_id": "iter23-local-native-free-v1",
        "future_symbol": FUTURE,
        "call_symbol": CALL,
        "put_symbol": PUT,
        "exchange": EXCHANGE,
        "rules_hash": RULES_HASH,
        "require_feed_bar_evidence": True,
        "bar_evidence_clock_domain": CLOCK_DOMAIN,
    }
    strategy_args.update(strategy_kwargs or {})
    cerebro.addstrategy(strategy_cls, **strategy_args)
    if before_run is not None:
        before_run(cerebro)

    [strategy] = cerebro.run(preload=False, runonce=False)
    return client, broker, feeds, strategy


def test_closed_feed_bars_reach_lowfreq_strategy_without_raw_line_reconstruction(monkeypatch):
    """Run the complete zero-write local chain through ``Cerebro.run``."""

    strategy_module = importlib.import_module(
        "examples.014_1_ctp_options_lowfreq.ctp_options_lowfreq_strategy"
    )
    strategy_cls = strategy_module.CtpOptionsLowfreqStrategy

    def raw_line_reconstruction_is_forbidden(*_args, **_kwargs):
        raise AssertionError("native closed-bar path rebuilt evidence from raw lines")

    monkeypatch.setattr(strategy_cls, "_bar_evidence", raw_line_reconstruction_is_forbidden)
    client, broker, feeds, strategy = _run_chain(
        strategy_cls, evidence_provider=_closed_bar_evidence
    )

    decision = strategy._last_decision_input
    assert decision is not None, {
        "rejections": strategy._rejections,
        "params": {
            "require_feed_bar_evidence": strategy.p.require_feed_bar_evidence,
            "bar_evidence_clock_domain": strategy.p.bar_evidence_clock_domain,
        },
        "feed_sequences": [feed._bar_sequence for feed in feeds],
        "remaining_ticks": {symbol: len(queue) for symbol, queue in client.live_ticks.items()},
    }
    assert set(decision.bars) == {FUTURE, CALL, PUT}
    assert all(isinstance(bar, BarEvidence) for bar in decision.bars.values())
    assert all(bar.rules_hash == RULES_HASH for bar in decision.bars.values())
    assert all(bar.session_segment == "local-native-free" for bar in decision.bars.values())
    accepted_cohort = next(item for item in strategy._bar_cohort_evidence if item["ready"])
    assert tuple(accepted_cohort["source_bar_ids"]) == decision.bar_ids
    assert client.submitted_orders == []
    assert client.cancelled_orders == []
    assert broker.get_param("market_data_only") is True


def test_required_feed_evidence_fails_closed_without_raw_line_fallback(monkeypatch):
    """An absent provider cannot fall back to mutable Backtrader line buffers."""

    strategy_module = importlib.import_module(
        "examples.014_1_ctp_options_lowfreq.ctp_options_lowfreq_strategy"
    )
    strategy_cls = strategy_module.CtpOptionsLowfreqStrategy

    def raw_line_reconstruction_is_forbidden(*_args, **_kwargs):
        raise AssertionError("missing Feed evidence fell back to raw lines")

    monkeypatch.setattr(strategy_cls, "_bar_evidence", raw_line_reconstruction_is_forbidden)
    client, broker, _, strategy = _run_chain(strategy_cls, evidence_provider=None)

    assert strategy._last_decision_input is None
    assert "FEED_CLOSED_BAR_EVIDENCE_REQUIRED" in strategy._rejections
    assert "BARARRIER_NOT_READY" in strategy._rejections
    assert client.submitted_orders == []
    assert client.cancelled_orders == []
    assert broker.get_param("market_data_only") is True


def test_direct_closed_evidence_callback_lacks_feed_provenance(monkeypatch):
    """A look-alike callback cannot replace the Feed/Cerebro hand-off."""

    strategy_module = importlib.import_module(
        "examples.014_1_ctp_options_lowfreq.ctp_options_lowfreq_strategy"
    )
    strategy_cls = strategy_module.CtpOptionsLowfreqStrategy
    client, broker, _, strategy = _run_chain(strategy_cls, evidence_provider=_closed_bar_evidence)
    decision = strategy._last_decision_input
    assert decision is not None

    def raw_line_reconstruction_is_forbidden(*_args, **_kwargs):
        raise AssertionError("direct callback fell back to raw lines")

    monkeypatch.setattr(strategy_cls, "_bar_evidence", raw_line_reconstruction_is_forbidden)
    prior_results = len(strategy._barrier_results)
    strategy.notify_bar(SimpleNamespace(closed_bar_evidence=decision.bars[FUTURE]))

    assert len(strategy._barrier_results) == prior_results
    assert "FEED_CLOSED_BAR_PROVENANCE_REQUIRED" in strategy._rejections
    assert client.submitted_orders == []
    assert client.cancelled_orders == []
    assert broker.get_param("market_data_only") is True


def test_genuine_feed_event_rejects_replaced_sealed_evidence(monkeypatch):
    """A pre-dispatch hook cannot retain the Feed marker and swap evidence."""

    strategy_module = importlib.import_module(
        "examples.014_1_ctp_options_lowfreq.ctp_options_lowfreq_strategy"
    )
    strategy_cls = strategy_module.CtpOptionsLowfreqStrategy

    def raw_line_reconstruction_is_forbidden(*_args, **_kwargs):
        raise AssertionError("tampered Feed callback fell back to raw lines")

    monkeypatch.setattr(strategy_cls, "_bar_evidence", raw_line_reconstruction_is_forbidden)

    def replace_one_genuine_event(cerebro):
        original_dispatch = cerebro.dispatch_channel_event

        def dispatch(event):
            if event.channel_type == "bar" and event.data.symbol == FUTURE:
                original_evidence = event.data.closed_bar_evidence
                event.data.closed_bar_evidence = replace(original_evidence, close=999.0)
            return original_dispatch(event)

        monkeypatch.setattr(cerebro, "dispatch_channel_event", dispatch)

    client, broker, _, strategy = _run_chain(
        strategy_cls,
        evidence_provider=_closed_bar_evidence,
        before_run=replace_one_genuine_event,
    )

    assert strategy._last_decision_input is None
    assert "FEED_CLOSED_BAR_PROVENANCE_REQUIRED" in strategy._rejections
    assert client.submitted_orders == []
    assert client.cancelled_orders == []
    assert broker.get_param("market_data_only") is True


def test_feed_decision_backlog_is_bounded_and_halts_on_overflow():
    """Feed callbacks cannot accumulate an unbounded unseen-decision queue."""

    strategy_module = importlib.import_module(
        "examples.014_1_ctp_options_lowfreq.ctp_options_lowfreq_strategy"
    )
    client, broker, _, strategy = _run_chain(
        strategy_module.CtpOptionsLowfreqStrategy,
        evidence_provider=_closed_bar_evidence,
    )

    assert strategy._queue_feed_decision(object()) is True
    assert strategy._queue_feed_decision(object()) is False
    assert strategy._state == "HALTED"
    assert not strategy._pending_feed_decision_inputs
    assert "FEED_BAR_DECISION_QUEUE_OVERFLOW" in strategy._rejections
    assert client.submitted_orders == []
    assert client.cancelled_orders == []
    assert broker.get_param("market_data_only") is True


def test_generation_reset_discards_queued_old_feed_decision_before_next():
    """A retired barrier scope cannot leave an old READY input actionable in ``next``."""

    strategy_module = importlib.import_module(
        "examples.014_1_ctp_options_lowfreq.ctp_options_lowfreq_strategy"
    )
    client, broker, _, strategy = _run_chain(
        strategy_module.CtpOptionsLowfreqStrategy,
        evidence_provider=_closed_bar_evidence,
    )
    decision = strategy._last_decision_input
    assert decision is not None
    assert strategy._queue_feed_decision(decision) is True

    generation_eight_mapping = replace(
        decision.clock_mapping,
        mapping_id=f"{decision.clock_mapping.mapping_id}:generation-8",
        connection_generation=8,
    )
    generation_eight_bar = replace(
        decision.bars[FUTURE],
        generation=8,
        clock_mapping=generation_eight_mapping,
        bar_id=f"{decision.bars[FUTURE].bar_id}:generation-8",
    )
    result = strategy._barrier.ingest(generation_eight_bar)

    assert result.reason == "GENERATION_MISMATCH"
    assert result.ready is False
    assert result.reset_warmup is True
    assert strategy._consume_barrier_result(result, generation_eight_bar.bucket_end) is None
    assert not strategy._pending_feed_decision_inputs
    assert strategy._last_decision_input is None
    assert strategy._barrier.last_input is None

    strategy.next()

    assert strategy._rejections[-1] == "BARARRIER_NOT_READY"
    assert client.submitted_orders == []
    assert client.cancelled_orders == []
    assert broker.get_param("market_data_only") is True


def test_feed_callback_burst_halts_before_an_unconsumed_second_cohort_can_act():
    """A stalled consumer cannot use a second real cohort after queue saturation."""

    strategy_module = importlib.import_module(
        "examples.014_1_ctp_options_lowfreq.ctp_options_lowfreq_strategy"
    )

    class NoConsumeStrategy(strategy_module.CtpOptionsLowfreqStrategy):
        def __init__(self):
            super().__init__()
            self.callback_queue_states = []

        def next(self):
            # Deliberately leave the native decision queue untouched.  Feed
            # scheduling still invokes this callback after each real cohort.
            self.callback_queue_states.append(
                (self._event_count, len(self._pending_feed_decision_inputs), self._state)
            )

    second_tick = BASE + dt.timedelta(minutes=15, milliseconds=500)
    client, broker, feeds, strategy = _run_chain(
        NoConsumeStrategy,
        evidence_provider=_closed_bar_evidence,
        live_ticks={
            FUTURE: [_tick(FUTURE, 1000.0, 1), _tick_at(FUTURE, 1001.0, 11, second_tick)],
            CALL: [_tick(CALL, 30.0, 2), _tick_at(CALL, 31.0, 12, second_tick)],
            PUT: [_tick(PUT, 30.0, 3), _tick_at(PUT, 29.0, 13, second_tick)],
        },
        final_watermark=BASE + dt.timedelta(minutes=30, milliseconds=500),
    )

    assert [feed._bar_sequence for feed in feeds] == [2, 2, 2]
    assert sum(item["ready"] for item in strategy._barrier_results) == 2
    assert strategy.callback_queue_states == [(3, 1, "FLAT"), (6, 0, "HALTED")]
    assert strategy._state == "HALTED"
    assert not strategy._pending_feed_decision_inputs
    assert strategy._last_decision_input is None
    assert "FEED_BAR_DECISION_QUEUE_OVERFLOW" in strategy._rejections
    assert client.submitted_orders == []
    assert client.cancelled_orders == []
    assert broker.get_param("market_data_only") is True


def test_feed_decision_overflow_preserves_recovery_posture_for_possible_exposure():
    """A backlog failure cannot hide timing risk after a possible fill."""

    strategy_module = importlib.import_module(
        "examples.014_1_ctp_options_lowfreq.ctp_options_lowfreq_strategy"
    )
    client, broker, _, strategy = _run_chain(
        strategy_module.CtpOptionsLowfreqStrategy,
        evidence_provider=_closed_bar_evidence,
    )

    strategy._state = "OPEN"
    strategy._possible_exposure = True
    strategy._hold_projection.record_possible_exposure(FUTURE, lower_ns=0)
    assert strategy._queue_feed_decision(object()) is True
    assert strategy._queue_feed_decision(object()) is False

    assert strategy._state == "HALTED"
    assert strategy._basket_status == "RECOVERY_REQUIRED"
    strategy.notify_idle(
        {
            "now_monotonic_ns": 7_201_000_000_000,
            "now_epoch": BASE.timestamp() + 7_201.0,
            "clock_domain_id": CLOCK_DOMAIN,
            "generation": 7,
            "trusted": True,
            "source": "iter23-local-native-free-risk-clock",
        }
    )
    assert any(event["kind"] == "risk_deadline_reached" for event in strategy._cycle_events)
    assert client.submitted_orders == []
    assert client.cancelled_orders == []
    assert broker.get_param("market_data_only") is True


def test_native_path_buy_is_rejected_before_the_fixture_client_write_boundary():
    """A strategy-originated order attempt remains local in market-data-only mode."""

    strategy_module = importlib.import_module(
        "examples.014_1_ctp_options_lowfreq.ctp_options_lowfreq_strategy"
    )

    class WriteProbeStrategy(strategy_module.CtpOptionsLowfreqStrategy):
        def __init__(self):
            super().__init__()
            self.write_probe_attempts = 0
            self.write_probe_order = None

        def next(self):
            super().next()
            if self._last_decision_input is None or self.write_probe_attempts:
                return
            self.write_probe_attempts += 1
            self.write_probe_order = self.buy(
                data=self._data_by_symbol[FUTURE],
                size=1,
                exectype=bt.Order.Limit,
                price=float(self._last_decision_input.bars[FUTURE].close),
            )

    client, broker, _, strategy = _run_chain(
        WriteProbeStrategy,
        evidence_provider=_closed_bar_evidence,
    )

    assert strategy.write_probe_attempts == 1
    assert strategy.write_probe_order is not None
    assert strategy.write_probe_order.status == strategy.write_probe_order.Rejected
    assert strategy.write_probe_order.info.error_code == "market_data_only"
    assert client.submitted_orders == []
    assert client.cancelled_orders == []
    assert broker.get_param("market_data_only") is True
    assert broker.get_market_data_only_audit() == {
        "submit_rejected": 1,
        "cancel_rejected": 0,
        "batch_cancel_rejected": 0,
        "total_rejected": 1,
    }


def test_sealed_candidate_conversion_reaches_read_only_broker_without_transport_write():
    """LOCAL_SUBSET: a synthetic local eligible C/P/F signal reaches only the broker gate."""

    strategy_module = importlib.import_module(
        "examples.014_1_ctp_options_lowfreq.ctp_options_lowfreq_strategy"
    )

    class SealedBarClock:
        """A local monotonic projection of the exact sealed-bar clock scope."""

        def __init__(self):
            self.strategy = None

        def __call__(self):
            current = getattr(self.strategy, "_current_clock_now_ns", None)
            current = 0 if current is None else current
            return {
                "now_monotonic_ns": current,
                "clock_domain_id": CLOCK_DOMAIN,
                "generation": 7,
                "trusted": True,
                "source": "iter23-local-native-free-sealed-bar-clock",
                "boot_id": "iter23-local-native-free-fixture-boot",
            }

    sealed_bar_clock = SealedBarClock()

    class CandidateEntryProbeStrategy(strategy_module.CtpOptionsLowfreqStrategy):
        def __init__(self):
            sealed_bar_clock.strategy = self
            self.entry_attempts = []
            self.submission_attempts = []
            super().__init__()

        def _start_entry(self, direction, limits, score, timestamp):
            self.entry_attempts.append(
                {
                    "direction": direction,
                    "legs": self._entry_legs_for(direction, limits),
                    "timestamp": timestamp,
                }
            )
            return super()._start_entry(direction, limits, score, timestamp)

        def _submit_next_leg(self):
            if self._state == "ENTERING" and self._leg_index < len(self._planned_legs):
                self.submission_attempts.append(dict(self._planned_legs[self._leg_index]))
            return super()._submit_next_leg()

    config, candidate, live_ticks, final_watermark = _eligible_candidate_ticks()

    def candidate_evidence(bar):
        return replace(
            _closed_bar_evidence(bar),
            candidate_id=f"{config['strategy_id']}-replay-v1",
        )

    client, broker, _, strategy = _run_chain(
        CandidateEntryProbeStrategy,
        evidence_provider=candidate_evidence,
        live_ticks=live_ticks,
        final_watermark=final_watermark,
        interleave_symbols=(FUTURE, CALL, PUT),
        strategy_kwargs=_candidate_strategy_kwargs(config, candidate, sealed_bar_clock),
    )

    assert strategy.p.strike == candidate["strike"]
    assert strategy.p.multiplier == candidate["multiplier"]
    assert strategy.p.discount == candidate["discount"]
    assert strategy.p.window == config["strategy_params"]["window"]
    assert strategy.p.capital_limit == config["budget"]["capital_limit"]
    assert strategy.p.first_send_seconds == config["timing"]["first_send_seconds"]
    assert [attempt["direction"] for attempt in strategy.entry_attempts] == ["conversion"], {
        "rejections": strategy._rejections,
        "events": strategy._cycle_events,
        "barrier_results": strategy._barrier_results,
    }
    assert strategy.entry_attempts[0]["legs"] == [
        {"symbol": PUT, "side": "buy", "price": 42.0, "size": 1},
        {"symbol": FUTURE, "side": "buy", "price": 1002.0, "size": 1},
        {"symbol": CALL, "side": "sell", "price": 138.0, "size": 1},
    ]
    assert strategy.submission_attempts == [strategy.entry_attempts[0]["legs"][0]]
    assert strategy._state == "HALTED"
    assert "ORDER_TERMINAL_WITHOUT_FULL_FILL" in strategy._rejections
    assert [
        (order["symbol"], order["side"], order["status"]) for order in strategy._order_projection
    ] == [(PUT, "buy", "rejected")]
    assert client.submitted_orders == []
    assert client.cancelled_orders == []
    assert broker.get_param("market_data_only") is True


def test_late_sealed_candidate_cohort_cannot_create_an_entry_or_transport_write():
    """A late C/P/F leg remains below the candidate-entry boundary."""

    strategy_module = importlib.import_module(
        "examples.014_1_ctp_options_lowfreq.ctp_options_lowfreq_strategy"
    )

    class CandidateEntryProbeStrategy(strategy_module.CtpOptionsLowfreqStrategy):
        def __init__(self):
            sealed_bar_clock.strategy = self
            self.entry_attempts = []
            self.submission_attempts = []
            super().__init__()

        def _start_entry(self, direction, limits, score, timestamp):
            self.entry_attempts.append(
                {
                    "direction": direction,
                    "legs": self._entry_legs_for(direction, limits),
                    "timestamp": timestamp,
                }
            )
            return super()._start_entry(direction, limits, score, timestamp)

        def _submit_next_leg(self):
            if self._state == "ENTERING" and self._leg_index < len(self._planned_legs):
                self.submission_attempts.append(dict(self._planned_legs[self._leg_index]))
            return super()._submit_next_leg()

    class SealedBarClock:
        def __init__(self):
            self.strategy = None

        def __call__(self):
            current = getattr(self.strategy, "_current_clock_now_ns", None)
            return {
                "now_monotonic_ns": 0 if current is None else current,
                "clock_domain_id": CLOCK_DOMAIN,
                "generation": 7,
                "trusted": True,
                "source": "iter23-local-native-free-partial-cohort-clock",
                "boot_id": "iter23-local-native-free-fixture-boot",
            }

    sealed_bar_clock = SealedBarClock()
    config, candidate, live_ticks, final_watermark = _eligible_candidate_ticks()
    candidate_leg_time = dt.datetime(2026, 9, 10, 19, 15, 0, 500_000, tzinfo=dt.timezone.utc)
    candidate_bucket_end = candidate_leg_time.replace(microsecond=0)
    late_index = next(
        index
        for index, tick in enumerate(live_ticks[PUT])
        if tick.event_time_utc == candidate_leg_time
    )
    late_tick = live_ticks[PUT][late_index]
    # Deliver the candidate's PUT leg a full bucket late.  It remains a real
    # Feed event, but cannot form the matching F/C/P sealed cohort.
    live_ticks[PUT][late_index] = _tick_at(
        PUT,
        float(late_tick.price),
        late_tick.ingest_seq,
        candidate_leg_time + dt.timedelta(minutes=15),
    )

    def candidate_evidence(bar):
        return replace(
            _closed_bar_evidence(bar),
            candidate_id=f"{config['strategy_id']}-replay-v1",
            trade_count=bar.trade_count,
        )

    client, broker, _, strategy = _run_chain(
        CandidateEntryProbeStrategy,
        evidence_provider=candidate_evidence,
        live_ticks=live_ticks,
        final_watermark=final_watermark,
        interleave_symbols=(FUTURE, CALL, PUT),
        strategy_kwargs=_candidate_strategy_kwargs(config, candidate, sealed_bar_clock),
    )

    assert strategy.entry_attempts == []
    assert strategy.submission_attempts == []
    late_cohorts = [
        item
        for item in strategy._bar_cohort_evidence
        if item["bucket_end"] == candidate_bucket_end.isoformat()
    ]
    assert any(
        item["reason"] == "SKIP_BARRIER_TIMEOUT"
        and item["ready"] is False
        and item["barrier_evidence"] is None
        for item in late_cohorts
    )
    assert client.submitted_orders == []
    assert client.cancelled_orders == []
    assert broker.get_param("market_data_only") is True


def test_closed_bar_provider_cannot_mutate_feed_owned_event_before_validation():
    """The provider sees a detached snapshot, not the event later dispatched."""

    strategy_module = importlib.import_module(
        "examples.014_1_ctp_options_lowfreq.ctp_options_lowfreq_strategy"
    )

    def forged_identity(bar):
        bar.symbol = "FORGED.SYMBOL"
        return _closed_bar_evidence(bar)

    with pytest.raises(ValueError, match="identity does not match BarEvent"):
        _run_chain(
            strategy_module.CtpOptionsLowfreqStrategy,
            evidence_provider=forged_identity,
        )


@pytest.mark.parametrize("dispatch_bars", (False, True))
def test_closed_bar_identity_binding_is_not_retained_without_a_dispatch_target(dispatch_bars):
    """A skipped bar callback cannot leak one identity entry per closed bar."""

    client = FiniteCtpFixtureClient(live_ticks={FUTURE: [_tick(FUTURE, 1000.0, 1)]})
    store = BtApiStore(provider="btapi", api=client, market_data_only=True)
    feed = store.getdata(
        dataname=FUTURE,
        timeframe=bt.TimeFrame.Minutes,
        compression=15,
        backfill_start=False,
        dispatch_ticks=False,
        dispatch_bars=dispatch_bars,
        qcheck=0,
        price_tick=1.0,
        clock=FixedClock(),
        closed_bar_evidence_provider=_closed_bar_evidence,
    )
    # Deliberately leave the feed outside Cerebro: with dispatch enabled it
    # still has no delivery target, which exercises the early-return branch.
    feed._start()
    try:
        feed._check()
        assert feed._sealed_closed_bar_evidence_by_event_id == {}
    finally:
        feed.stop()
