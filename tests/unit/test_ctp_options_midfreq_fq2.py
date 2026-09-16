"""Focused FQ2 feature and token regressions for the Iteration 24 replay."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import importlib
import sys
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "014_2_ctp_options_midfreq"
from backtrader.feeds import (  # noqa: E402
    BarBarrierPolicy,
    BarLeg,
    CtpQuoteEvidence,
    MultiLegBarBarrier,
)

strategy_module = importlib.import_module(
    "examples.014_2_ctp_options_midfreq.ctp_options_midfreq_strategy"
)
features_module = importlib.import_module("examples.014_2_ctp_options_midfreq.features")
fixture_module = importlib.import_module("examples.014_2_ctp_options_midfreq.fq2_fixture")
validate_config = strategy_module.validate_config
FeaturePolicy = features_module.FeaturePolicy
FeatureReason = features_module.FeatureReason
_normalize_quote = features_module._normalize_quote
compute_minute_features = features_module.compute_minute_features
ReplayQuoteProducer = fixture_module.ReplayQuoteProducer


@pytest.fixture(scope="module")
def config() -> dict:
    return validate_config(yaml.safe_load((EXAMPLE / "config.yaml").read_text(encoding="utf-8")))


def _producer(config: dict, scenario: str = "edge") -> ReplayQuoteProducer:
    candidate = config["candidate"]
    return ReplayQuoteProducer(
        candidate_id=candidate["candidate_id"],
        exchange=candidate["exchange"],
        rules_hash=candidate["rules_hash"],
        contracts=candidate["contracts"],
        scenario=scenario,
        strike=candidate["strike"],
        multiplier=candidate["multiplier"],
        discount_factor=candidate["discount_factor"],
    )


def _policy(config: dict) -> FeaturePolicy:
    candidate = config["candidate"]
    contracts = candidate["contracts"]
    feature = config["features"]
    signal = config["signal"]
    return FeaturePolicy(
        symbols=(contracts["future"], contracts["call"], contracts["put"]),
        multiplier=candidate["multiplier"],
        strike=candidate["strike"],
        discount_factor=candidate["discount_factor"],
        price_tick_by_symbol={
            contracts[field]: candidate["price_ticks"][field] for field in ("future", "call", "put")
        },
        history_bars=signal["history_bars"],
        short_window_seconds=feature["short_window_seconds"],
        long_window_seconds=feature["long_window_seconds"],
        max_segment_seconds=feature["max_segment_seconds"],
        max_cross_leg_skew_ms=feature["max_cross_leg_skew_ms"],
        minimum_new_snapshots=feature["minimum_new_snapshots"],
        persistence_ratio=feature["persistence_ratio"],
        max_adverse_pressure=feature["max_adverse_pressure"],
        residual_floor_cny=signal["residual_floor_cny"],
        z_entry=signal["z_entry"],
        minimum_net_edge_cny=signal["minimum_net_edge_cny"],
        cost_bound_cny=signal["cost_bound_cny"],
    )


def _bar_data(producer: ReplayQuoteProducer, minute_index: int, symbol: str) -> SimpleNamespace:
    residual = producer.residual_for_minute(minute_index)
    future = producer.strike
    put = Decimal("9.5")
    call = put + producer.discount_factor * (future - producer.strike)
    call += residual / producer.multiplier
    close = {
        producer.contracts["future"]: future,
        producer.contracts["call"]: call,
        producer.contracts["put"]: put,
    }[symbol]
    values = [float(close)]
    return SimpleNamespace(
        open=values,
        high=values,
        low=values,
        close=values,
        volume=[1.0],
        openinterest=[0.0],
    )


def _decision_input(config: dict, producer: ReplayQuoteProducer, minute_index: int = 60):
    candidate = config["candidate"]
    contracts = candidate["contracts"]
    barrier = MultiLegBarBarrier(
        expected_legs=tuple(
            BarLeg(contracts[field], candidate["exchange"]) for field in ("future", "call", "put")
        ),
        candidate_id=candidate["candidate_id"],
        expected_rules_hash=candidate["rules_hash"],
        policy=BarBarrierPolicy(timeframe_seconds=60.0, timeout_seconds=2.0),
        clock_mode="replay",
        expected_clock_domain="iter24-replay-clock",
    )
    result = None
    for leg_index, field in enumerate(("future", "call", "put")):
        symbol = contracts[field]
        result = barrier.ingest(
            producer.bar_for(
                minute_index, symbol, _bar_data(producer, minute_index, symbol), leg_index
            )
        )
    assert result is not None and result.ready
    return result.decision_input


def _history() -> tuple[Decimal, ...]:
    return tuple(Decimal(value) for value in ("-10", "0", "10") * 20)


def _with_events(decision_input, events_by_symbol):
    return replace(
        decision_input,
        accepted_quotes=events_by_symbol,
        quote_rejections=dict.fromkeys(events_by_symbol, ()),
    )


def _events(decision_input) -> dict[str, tuple[dict, ...]]:
    return {
        symbol: tuple(dict(event) for event in values)
        for symbol, values in decision_input.accepted_quotes.items()
    }


def _shift(
    event: dict, producer: ReplayQuoteProducer, *, event_delta=timedelta(0), receive_delta=None
) -> dict:
    result = dict(event)
    result["event_time"] = result["event_time"] + event_delta
    result["received_at"] = result["received_at"] + (
        event_delta if receive_delta is None else receive_delta
    )
    result["received_monotonic_ns"] = producer.clock_mapping.map_wall_to_mono_ns(
        result["received_at"]
    )
    result["received_monotonic"] = result["received_monotonic_ns"] / 1_000_000_000
    return result


def _short_schedule(decision_input, producer: ReplayQuoteProducer, *, gap: bool) -> dict:
    end = decision_input.bucket_end
    result = {}
    for symbol, values in _events(decision_input).items():
        outside = [event for event in values if event["event_time"] < end - timedelta(seconds=5)]
        inside = [
            event for event in values if end - timedelta(seconds=5) <= event["event_time"] < end
        ]
        keep = [
            event
            for event in inside
            if event["event_time"]
            in {
                end - timedelta(seconds=5),
                end - timedelta(seconds=3),
                end - timedelta(seconds=1),
            }
        ]
        if gap:
            keep = [
                (
                    _shift(event, producer, event_delta=timedelta(milliseconds=1))
                    if event["event_time"] == end - timedelta(seconds=3)
                    else event
                )
                for event in keep
            ]
        result[symbol] = tuple(outside + keep)
    return result


def test_public_edge_replay_matches_independent_feature_oracle_shape() -> None:
    import json
    import subprocess

    result = subprocess.run(
        [sys.executable, str(EXAMPLE / "run.py"), "--scenario", "edge"],
        cwd=EXAMPLE,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    decision = report["ordinary_decisions"][0]
    feature = report["feature_history"][-1]
    assert decision["outcome"] == "REPLAY_WRITE_DISABLED"
    assert decision["direction"] == "conversion"
    assert decision["residual_cny"] == 80.0
    assert decision["score_conversion_cny"] == 40.0
    assert decision["score_reversal_cny"] == -120.0
    assert decision["persistence_conversion"] == 1.0
    assert decision["short_window_covered_ms"] == 5000
    assert decision["long_window_covered_ms"] == 60000
    assert decision["synchronized_states_5s"] >= 3
    assert len(decision["bar_ids"]) == 3
    assert tuple(decision["bar_ids"]) == tuple(feature["bar_ids"])
    assert decision["quote_cutoffs"] == feature["quote_cutoffs"]
    assert decision["source_sequences"] == {
        symbol: list(sequence)
        for symbol, sequence in report["barrier"]["last_input"]["source_sequences"].items()
    }
    assert decision["bucket_end"] == feature["bucket_end"]
    assert decision["common_available_at"] == report["barrier"]["last_input"]["common_available_at"]
    assert decision["barrier_ready_mono"] <= decision["barrier_deadline_mono"]
    assert feature["i5_by_symbol"] == {
        "F_LOCAL_1000": 0.0,
        "C_LOCAL_1000": -0.5,
        "P_LOCAL_1000": 0.5,
    }
    assert feature["microprice_by_symbol"] == {
        "F_LOCAL_1000": 1000.0,
        "C_LOCAL_1000": 17.25,
        "P_LOCAL_1000": 9.75,
    }
    assert feature["micro_shift_ticks_by_symbol"] == {
        "F_LOCAL_1000": 0.0,
        "C_LOCAL_1000": -0.25,
        "P_LOCAL_1000": 0.25,
    }
    assert feature["adverse_pressure_conversion"] == pytest.approx(1 / 3)
    assert feature["median_cny"] == 0.0
    assert feature["mad_cny"] == 10.0
    assert feature["scale_cny"] == 30.0
    assert feature["z_score"] == pytest.approx(80 / 30)
    assert report["token_ledger"]["issued_count"] == 1
    assert report["token_ledger"]["consumed_count"] == 1
    assert report["orders_submitted"] == 0
    assert report["external_network_requests"] == 0
    assert report["external_trade_writes"] == 0


def test_in_process_cerebro_consumes_both_replay_scenarios() -> None:
    runner = importlib.import_module("examples.014_2_ctp_options_midfreq.run")

    raw = runner.load_config()
    edge = runner.run_replay(raw, scenario="edge", inject_cutoff_tick=True)
    no_edge = runner.run_replay(raw, scenario="no_edge", inject_at_cutoff_tick=True)
    assert edge["ordinary_decisions"][0]["outcome"] == "REPLAY_WRITE_DISABLED"
    assert edge["accepted_cutoff_tick_features"]
    assert no_edge["ordinary_decisions"][0]["outcome"] == "NO_EDGE"
    assert no_edge["accepted_cutoff_tick_features"] == []
    assert no_edge["rejected_tick_count"] == 1


def test_short_window_is_time_integrated_and_gap_cannot_be_filled(config: dict) -> None:
    producer = _producer(config)
    decision_input = _decision_input(config, producer)
    policy = _policy(config)
    exact = compute_minute_features(
        _with_events(decision_input, _short_schedule(decision_input, producer, gap=False)),
        policy=policy,
        history=_history(),
    )
    gap = compute_minute_features(
        _with_events(decision_input, _short_schedule(decision_input, producer, gap=True)),
        policy=policy,
        history=_history(),
    )
    assert exact.short_window_covered_ms == 5000
    assert exact.short_window_complete is True
    assert exact.synchronized_states_5s == 3
    assert gap.short_window_covered_ms == 4999
    assert gap.short_window_complete is False
    assert FeatureReason.FEATURE_SEGMENT_TOO_LONG in gap.reasons
    assert gap.signal_ready is False


def test_persistence_and_score_use_strict_boundaries(config: dict) -> None:
    producer = _producer(config)
    decision_input = _decision_input(config, producer)
    policy = _policy(config)
    values = _events(decision_input)
    call = producer.contracts["call"]
    end = decision_input.bucket_end
    for index, event in enumerate(values[call]):
        if event["event_time"] == end - timedelta(seconds=4):
            event["bid"] = 14.0
    exact = compute_minute_features(
        _with_events(decision_input, values), policy=policy, history=_history()
    )
    assert exact.persistence_conversion == Decimal("0.8")
    assert exact.signal_ready is True

    below_values = _events(decision_input)
    for event in below_values[call]:
        if event["event_time"] == end - timedelta(seconds=4):
            event["bid"] = 14.0
            shifted = _shift(event, producer, event_delta=timedelta(milliseconds=-1))
            event.clear()
            event.update(shifted)
    below = compute_minute_features(
        _with_events(decision_input, below_values), policy=policy, history=_history()
    )
    assert below.persistence_conversion < Decimal("0.8")
    assert below.signal_ready is False

    score_values = _events(decision_input)
    for event in score_values[call]:
        if event["event_time"] == end - timedelta(seconds=1):
            event["bid"] = 15.0
            event["ask"] = 20.0
    score_edge = compute_minute_features(
        _with_events(decision_input, score_values), policy=policy, history=_history()
    )
    assert score_edge.score_conversion_cny == Decimal("20")
    assert score_edge.signal_ready is False
    assert score_edge.reason == FeatureReason.NO_SIGNAL_NET_EDGE


def test_cross_leg_receive_skew_accepts_500_and_rejects_501(config: dict) -> None:
    producer = _producer(config)
    decision_input = _decision_input(config, producer)
    policy = _policy(config)

    def causal_values(delay_ms: int) -> dict[str, tuple[dict, ...]]:
        """Build the corrected 500ms cadence used by the replay contract.

        The half-second source cadence supplies an as-of state before every
        receive boundary.  The call leg is delayed by the requested amount;
        receive-time selection therefore cannot silently backfill a missing
        interval while the source and receive skews remain within the stated
        500ms contract for the exact boundary.
        """

        templates = _events(decision_input)
        end = decision_input.bucket_end
        symbols = tuple(producer.contracts.values())
        values: dict[str, tuple[dict, ...]] = {}
        for leg_index, symbol in enumerate(symbols):
            template = templates[symbol][-1]
            events = []
            for sample in range(123):
                event_time = end - timedelta(milliseconds=61_000 - sample * 500)
                received_at = event_time + timedelta(
                    milliseconds=delay_ms if symbol == producer.contracts["call"] else 0
                )
                if event_time >= end or received_at >= end:
                    continue
                event = dict(template)
                event["event_time"] = event_time
                event["received_at"] = received_at
                event["received_monotonic_ns"] = producer.clock_mapping.map_wall_to_mono_ns(
                    received_at
                )
                event["received_monotonic"] = event["received_monotonic_ns"] / 1_000_000_000
                event["ingest_seq"] = 720_000 + sample * 3 + leg_index + 1
                events.append(event)
            values[symbol] = tuple(events)
        return values

    exact = compute_minute_features(
        _with_events(decision_input, causal_values(500)), policy=policy, history=_history()
    )
    assert exact.source_skew_ms == Decimal("500.0")
    assert exact.receive_skew_ms <= Decimal("500")
    assert exact.signal_ready is True

    late_values = causal_values(501)
    late = compute_minute_features(
        _with_events(decision_input, late_values), policy=policy, history=_history()
    )
    assert late.source_skew_ms > Decimal("500")
    assert late.signal_ready is False
    assert FeatureReason.FEATURE_CROSS_LEG_SKEW in late.reasons

    source_values = _events(decision_input)
    call = producer.contracts["call"]
    source_values[call] = source_values[call] + tuple(
        dict(
            _shift(
                event,
                producer,
                event_delta=timedelta(milliseconds=500),
                receive_delta=timedelta(milliseconds=500),
            ),
            ingest_seq=event["ingest_seq"] - 1,
        )
        for event in source_values[call]
    )
    source_exact = compute_minute_features(
        _with_events(decision_input, source_values), policy=policy, history=_history()
    )
    assert source_exact.source_skew_ms == Decimal("500.0")
    assert source_exact.signal_ready is True

    source_late_values = _events(decision_input)
    source_late_values[call] = source_late_values[call] + tuple(
        dict(
            _shift(
                event,
                producer,
                event_delta=timedelta(milliseconds=501),
                receive_delta=timedelta(milliseconds=501),
            ),
            ingest_seq=event["ingest_seq"] - 1,
        )
        for event in source_late_values[call]
    )
    source_late = compute_minute_features(
        _with_events(decision_input, source_late_values), policy=policy, history=_history()
    )
    assert source_late.source_skew_ms == Decimal("501.0")
    assert source_late.signal_ready is False


def test_warmup_59_is_rejected_and_60_is_eligible(config: dict) -> None:
    producer = _producer(config)
    decision_input = _decision_input(config, producer)
    policy = _policy(config)
    warm = compute_minute_features(decision_input, policy=policy, history=_history()[:-1])
    ready = compute_minute_features(decision_input, policy=policy, history=_history())
    assert warm.history_before_current == 59
    assert warm.signal_ready is False
    assert warm.reason == FeatureReason.BLOCKED_WARMUP
    assert ready.history_before_current == 60
    assert ready.signal_ready is True


def test_duplicate_future_late_and_missing_quote_fields_fail_closed(config: dict) -> None:
    producer = _producer(config)
    decision_input = _decision_input(config, producer)
    policy = _policy(config)
    values = _events(decision_input)
    future = dict(values[producer.contracts["future"]][-1])
    values[producer.contracts["future"]] = values[producer.contracts["future"]] + (future,)
    duplicate = compute_minute_features(
        _with_events(decision_input, values), policy=policy, history=_history()
    )
    assert duplicate.reason == FeatureReason.FEATURE_QUOTE_DUPLICATE
    assert duplicate.signal_ready is False

    values = _events(decision_input)
    future_symbol = producer.contracts["future"]
    values[future_symbol] = values[future_symbol][:-1] + (
        _shift(values[future_symbol][-1], producer, event_delta=timedelta(seconds=1)),
    )
    future_result = compute_minute_features(
        _with_events(decision_input, values), policy=policy, history=_history()
    )
    assert future_result.reason == FeatureReason.FEATURE_QUOTE_FUTURE

    values = _events(decision_input)
    late_event = _shift(values[future_symbol][-1], producer, receive_delta=timedelta(seconds=61))
    values[future_symbol] = values[future_symbol][:-1] + (late_event,)
    late_result = compute_minute_features(
        _with_events(decision_input, values), policy=policy, history=_history()
    )
    assert late_result.reason == FeatureReason.FEATURE_QUOTE_LATE

    values = _events(decision_input)
    missing = dict(values[future_symbol][-1])
    del missing["bid_qty"]
    values[future_symbol] = values[future_symbol][:-1] + (missing,)
    schema_result = compute_minute_features(
        _with_events(decision_input, values), policy=policy, history=_history()
    )
    assert schema_result.reason == FeatureReason.FEATURE_QUOTE_SCHEMA


def test_typed_ctp_quote_adapter_preserves_book_and_identity_fields(config: dict) -> None:
    producer = _producer(config)
    decision_input = _decision_input(config, producer)
    future = producer.contracts["future"]
    raw = decision_input.accepted_quotes[future][-1]
    typed = CtpQuoteEvidence(
        symbol=raw["symbol"],
        exchange=raw["exchange"],
        asset_type="ctp-future",
        bid=raw["bid"],
        ask=raw["ask"],
        bid_size=raw["bid_qty"],
        ask_size=raw["ask_qty"],
        last=raw["last"],
        lower_limit=0.01,
        upper_limit=100000.0,
        source_epoch=raw["event_time"].timestamp(),
        receive_epoch=raw["received_at"].timestamp(),
        receive_monotonic_ns=raw["received_monotonic_ns"],
        ingest_seq=raw["ingest_seq"],
        connection_generation=raw["generation"],
        subscription_epoch=1,
        trading_day=raw["trading_day"],
        action_day=raw["action_day"],
        clock_domain_id=raw["clock_domain"],
        rules_hash=raw["rules_hash"],
        source=raw["source"],
        event_time_source=raw["event_time_source"],
        source_clock_error_ms=0.0,
        receive_clock_error_ms=0.0,
    )
    snapshot = _normalize_quote(
        typed,
        symbol=future,
        session_segment=decision_input.session_segment,
        candidate_id=decision_input.candidate_id,
    )
    assert snapshot.bid == Decimal("999")
    assert snapshot.ask == Decimal("1001")
    assert snapshot.bid_qty == Decimal("1")
    assert snapshot.ask_qty == Decimal("1")
    assert snapshot.generation == decision_input.generation


def test_capacity_and_exchange_identity_are_fail_closed(config: dict) -> None:
    producer = _producer(config)
    decision_input = _decision_input(config, producer)
    policy = _policy(config)
    future = producer.contracts["future"]
    values = _events(decision_input)
    values[future] = values[future] + (values[future][-1],) * 197
    capacity = compute_minute_features(
        _with_events(decision_input, values), policy=policy, history=_history()
    )
    assert capacity.reason == FeatureReason.FEATURE_QUOTE_CAPACITY

    values = _events(decision_input)
    values[future][-1]["exchange"] = "OTHER_EXCHANGE"
    identity = compute_minute_features(
        _with_events(decision_input, values), policy=policy, history=_history()
    )
    assert identity.reason == FeatureReason.FEATURE_QUOTE_IDENTITY
