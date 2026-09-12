"""Focused replay contracts for the self-contained Iteration 25 example."""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import backtrader as bt
import pytest

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "examples" / "015_ctp_options_highfreq"
PACKAGE = "iter25_ctp_options_highfreq_example"


def _load_example_package() -> None:
    if PACKAGE in sys.modules:
        return
    spec = importlib.util.spec_from_file_location(
        PACKAGE,
        EXAMPLE / "__init__.py",
        submodule_search_locations=[str(EXAMPLE)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE] = module
    spec.loader.exec_module(module)


_load_example_package()
runner = importlib.import_module(f"{PACKAGE}.run")
strategy_module = importlib.import_module(f"{PACKAGE}.ctp_options_highfreq_strategy")
timing_module = importlib.import_module(f"{PACKAGE}.execution_timing")


def _config() -> dict:
    raw, _ = runner.load_config(EXAMPLE / "config.yaml")
    return runner.effective_config(raw, mode="replay", purpose="formula")


def test_valid_tick_only_cohorts_are_deterministic_and_never_submit_orders():
    first = runner.run_replay(_config(), scenario="valid_cohort")
    second = runner.run_replay(_config(), scenario="valid_cohort")

    assert first["business_summary_hash"] == second["business_summary_hash"]
    assert first["confirmed_cohorts"] == 2
    assert first["ordinary_intent_count"] == 1
    assert first["ordinary_intents"][0]["execution_status"] == "NOT_SUBMITTED_REPLAY"
    assert first["callback_counts"]["tick"] == 6
    assert first["external_network_requests"] == 0
    assert first["external_write_requests"] == 0
    assert first["simulated_broker_orders"] == 0
    assert first["actual_fills"] == 0
    assert first["pnl_fields_emitted"] is False
    assert first["hft_status"] == "NOT_ADMITTED"
    for quote in first["last_cohort"]["quotes"].values():
        assert quote["exchange"] == "CZCE"
        assert quote["source"] == "local_synthetic_fixture"
        assert quote["event_time_source"] == "fixture_utc"
    assert first["runtime_chain"] == {
        "cerebro": "backtrader.cerebro.Cerebro",
        "broker": "backtrader.brokers.tickbroker.TickBroker",
        "event": "backtrader.channel.Event",
        "tick_event": "backtrader.events.TickEvent",
        "strategy": f"{PACKAGE}.ctp_options_highfreq_strategy.CtpOptionsHighfreqStrategy",
    }


@pytest.mark.parametrize("scenario", ["insufficient_cohort", "stale_source"])
def test_incomplete_or_stale_cohorts_reject_without_an_ordinary_intent(scenario):
    report = runner.run_replay(_config(), scenario=scenario)

    assert report["ordinary_intent_count"] == 0
    assert report["normal_order_submissions"] == 0
    assert report["external_write_requests"] == 0
    if scenario == "insufficient_cohort":
        assert report["confirmed_cohorts"] == 1
    else:
        assert report["reject_counts"] == {"STALE_COHORT_SOURCE_TIME": 1}
        assert report["confirmed_cohorts"] == 0


def test_repeated_raw_payloads_cannot_count_as_the_second_three_leg_update():
    report = runner.run_replay(_config(), scenario="duplicate_payload")

    assert report["confirmed_cohorts"] == 0
    assert report["ordinary_intent_count"] == 0
    assert report["last_rejection"] == "DUPLICATE_COHORT_PAYLOAD"
    assert report["reject_counts"] == {"DUPLICATE_COHORT_PAYLOAD": 1}


def test_duplicate_ingest_sequence_clears_confirmation(monkeypatch):
    original_cohort_events = runner._cohort_events

    def cohort_events(*args, **kwargs):
        events = original_cohort_events(*args, **kwargs)
        for event in events:
            tick = event.data
            if event.channel_type == "tick" and tick.symbol == "FG701" and tick.ingest_seq > 3:
                tick.ingest_seq = 1
        return events

    monkeypatch.setattr(runner, "_cohort_events", cohort_events)
    report = runner.run_replay(_config(), scenario="valid_cohort")

    assert report["ordinary_intent_count"] == 0
    assert report["confirmed_cohorts"] == 0
    assert report["reject_counts"] == {"DUPLICATE_OR_OUT_OF_ORDER": 1}


def test_quality_failure_after_one_economic_confirmation_clears_the_streak(monkeypatch):
    original_cohort_events = runner._cohort_events

    def cohort_events(*args, **kwargs):
        events = original_cohort_events(*args, **kwargs)
        for event in events:
            if event.channel_type == "tick" and event.data.ingest_seq > 3:
                event.data.continuity_status = "gap"
        return events

    monkeypatch.setattr(runner, "_cohort_events", cohort_events)
    report = runner.run_replay(_config(), scenario="valid_cohort")

    assert report["ordinary_intent_count"] == 0
    assert report["confirmed_cohorts"] == 0
    assert report["reject_counts"] == {"QUOTE_CONTINUITY_NOT_CONTINUOUS": 3}


def test_no_edge_cohort_cannot_supply_confirmation_to_a_later_edge_cohort(monkeypatch):
    original_cohort_events = runner._cohort_events

    def cohort_events(*args, **kwargs):
        events = original_cohort_events(*args, **kwargs)
        for event in events:
            tick = event.data
            if event.channel_type == "tick" and tick.symbol == "FG701C970" and tick.ingest_seq <= 3:
                tick.bid_price = 10.0
                tick.ask_price = 11.0
                tick.price = 10.0
        return events

    monkeypatch.setattr(runner, "_cohort_events", cohort_events)
    report = runner.run_replay(_config(), scenario="valid_cohort")

    assert report["ordinary_intent_count"] == 0
    assert report["confirmed_cohorts"] == 1
    assert report["last_screen"]["conversion"]["eligible"] is True
    assert report["reject_counts"] == {"NO_SIGNAL_NET_EDGE": 1}


def test_direction_switch_clears_prior_confirmation(monkeypatch):
    original_cohort_events = runner._cohort_events

    def cohort_events(*args, **kwargs):
        events = original_cohort_events(*args, **kwargs)
        for event in events:
            tick = event.data
            if event.channel_type != "tick" or tick.ingest_seq <= 3:
                continue
            if tick.symbol == "FG701C970":
                tick.bid_price = 4.0
                tick.ask_price = 5.0
                tick.price = 4.0
            elif tick.symbol == "FG701P970":
                tick.bid_price = 30.0
                tick.ask_price = 31.0
                tick.price = 30.0
        return events

    monkeypatch.setattr(runner, "_cohort_events", cohort_events)
    report = runner.run_replay(_config(), scenario="valid_cohort")

    assert report["ordinary_intent_count"] == 0
    assert report["confirmed_cohorts"] == 1
    assert report["last_screen"]["reversal"]["eligible"] is True
    assert report["reject_counts"] == {"SIGNAL_DIRECTION_CHANGED": 1}


def _strategy_and_events(scenario="valid_cohort"):
    config = _config()
    fixture, _, _ = runner.load_fixture(config)
    bundle = runner.validate_bundle(fixture, config)
    cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
    cerebro.setbroker(runner.TickBroker(cash=100000.0))
    cerebro.addstrategy(
        strategy_module.CtpOptionsHighfreqStrategy, **runner._strategy_params(config, bundle)
    )
    strategy = cerebro.run(channel=[])[0]
    return strategy, runner._cohort_events(fixture, bundle, scenario)


def _trusted_now_from_tick(tick, *, monotonic_delta_ns=0, epoch_delta=0.0, domain=None):
    return runner.bt.feeds.CtpCohortNow(
        now_monotonic_ns=tick.recv_monotonic_ns + monotonic_delta_ns,
        now_epoch=runner._iso(float(tick.recv_time_utc and tick.received_wall_time) + epoch_delta),
        clock_domain_id=domain or tick.clock_domain_id,
        receive_clock_error_ms=0.0,
        receive_clock_quality="verified",
        freshness_verified=True,
    )


def test_idle_without_trusted_now_clears_confirmation_and_never_uses_last_tick_time():
    strategy, events = _strategy_and_events()
    for event in events[:3]:
        strategy.notify_tick(event.data)

    assert strategy._confirmed_cohorts == 1
    strategy.notify_idle()

    assert strategy._confirmed_cohorts == 0
    assert strategy._ordinary_intents == []
    assert strategy._last_rejection == "TRUSTED_NOW_REQUIRED"


def test_idle_recheck_expires_cached_cohort_without_creating_or_faking_risk_actions():
    strategy, events = _strategy_and_events()
    for event in events[:3]:
        strategy.notify_tick(event.data)

    stale_now = _trusted_now_from_tick(
        events[2].data, monotonic_delta_ns=1_000_000_000, epoch_delta=1.0
    )
    strategy.notify_idle(now=stale_now)

    assert strategy._confirmed_cohorts == 0
    assert strategy._ordinary_intents == []
    assert strategy._last_rejection == "STALE_COHORT_RECEIVE_TIME"
    assert strategy.replay_report()["offline_deadline_projection"]["risk_actions"] == []
    assert strategy.replay_report()["normal_order_submissions"] == 0


@pytest.mark.parametrize("bad_now", (object(), {"now_monotonic_ns": 1}))
def test_idle_bad_clock_evidence_latches_rejection_without_using_a_local_clock(bad_now):
    strategy, events = _strategy_and_events()
    for event in events[:3]:
        strategy.notify_tick(event.data)

    strategy.notify_idle(now=bad_now)
    for event in events[3:]:
        strategy.notify_tick(event.data)

    assert strategy._confirmed_cohorts == 0
    assert strategy._ordinary_intents == []
    assert strategy._clock_rejection_latched is True
    assert strategy._last_rejection == "TRUSTED_NOW_INVALID"


def test_idle_recheck_of_a_fresh_cached_edge_is_observational_only():
    strategy, events = _strategy_and_events()
    for event in events[:3]:
        strategy.notify_tick(event.data)

    strategy.notify_idle(now=_trusted_now_from_tick(events[2].data, monotonic_delta_ns=1_000_000))

    assert strategy._confirmed_cohorts == 1
    assert strategy._ordinary_intents == []
    assert strategy.replay_report()["offline_deadline_projection"]["risk_actions"] == []


def test_offline_deadline_projection_exposes_design_timeouts_without_claiming_risk_actions():
    report = runner.run_replay(_config(), scenario="valid_cohort")

    projection = report["ordinary_intents"][0]["deadline_projection"]
    assert projection["status"] == "OFFLINE_SIGNAL_ONLY"
    assert projection["risk_projection_available"] is False
    assert projection["leg_timeout_ms"] == 1_000
    assert projection["unhedged_timeout_ms"] == 3_000
    assert projection["holding_timeout_ms"] == 60_000
    assert projection["risk_actions"] == []
    assert report["risk_reduction_requests"] == 0
    assert report["normal_order_submissions"] == 0


@pytest.mark.parametrize(
    ("monotonic_delta_ns", "domain", "reason"),
    (
        (-1, None, "IDLE_CLOCK_REGRESSION"),
        (0, "foreign-clock-domain", "IDLE_CLOCK_DOMAIN_MISMATCH"),
    ),
)
def test_idle_clock_regression_or_domain_change_latches_ordinary_intent_rejection(
    monotonic_delta_ns, domain, reason
):
    strategy, events = _strategy_and_events()
    for event in events[:3]:
        strategy.notify_tick(event.data)

    idle_now = _trusted_now_from_tick(
        events[2].data,
        monotonic_delta_ns=monotonic_delta_ns,
        domain=domain,
    )
    strategy.notify_idle(now=idle_now)
    for event in events[3:]:
        strategy.notify_tick(event.data)

    assert strategy._confirmed_cohorts == 0
    assert strategy._ordinary_intents == []
    assert strategy._clock_rejection_latched is True
    assert strategy._last_rejection == reason
    assert strategy.replay_report()["normal_order_submissions"] == 0


def test_mixed_trading_day_cannot_form_a_three_leg_cohort():
    report = runner.run_replay(_config(), scenario="mixed_trading_day")

    assert report["confirmed_cohorts"] == 0
    assert report["ordinary_intent_count"] == 0
    assert report["reject_counts"] == {"COHORT_TRADING_DAY_MISMATCH": 1}


@pytest.mark.parametrize(
    ("scenario", "reason"),
    (
        ("quality_gap", "QUOTE_CONTINUITY_NOT_CONTINUOUS"),
        ("quality_flag", "QUOTE_QUALITY_FLAGS_PRESENT"),
        ("incomplete_volume", "VOLUME_INCOMPLETE"),
        ("volume_quality_gap", "VOLUME_QUALITY_NOT_CONTINUOUS"),
        ("out_of_limit", "QUOTE_OUTSIDE_DAILY_LIMIT"),
        ("execution_ineligible", "EXECUTION_INELIGIBLE_QUOTE"),
    ),
)
def test_bad_ctp_v2_quote_quality_cannot_form_an_ordinary_intent(scenario, reason):
    report = runner.run_replay(_config(), scenario=scenario)

    assert report["confirmed_cohorts"] == 0
    assert report["ordinary_intent_count"] == 0
    assert report["normal_order_submissions"] == 0
    assert report["reject_counts"] == {reason: 6}


def _run_with_tick_mutation(monkeypatch, mutate_tick):
    """Exercise the full replay while corrupting each generated CTP quote."""

    original_cohort_events = runner._cohort_events

    def cohort_events(*args, **kwargs):
        events = original_cohort_events(*args, **kwargs)
        for event in events:
            if event.channel_type == "tick":
                mutate_tick(event.data)
        return events

    monkeypatch.setattr(runner, "_cohort_events", cohort_events)
    return runner.run_replay(_config(), scenario="valid_cohort")


def test_equal_daily_price_limits_fail_closed_during_a_complete_replay(monkeypatch):
    report = _run_with_tick_mutation(
        monkeypatch,
        lambda tick: setattr(tick, "lower_limit", float(tick.upper_limit)),
    )

    assert report["confirmed_cohorts"] == 0
    assert report["ordinary_intent_count"] == 0
    assert report["normal_order_submissions"] == 0
    assert report["reject_counts"] == {"DAILY_PRICE_LIMIT_INVALID": 6}


@pytest.mark.parametrize("bound", ("lower_limit", "upper_limit"))
def test_each_daily_price_limit_must_follow_the_leg_tick_grid(monkeypatch, bound):
    report = _run_with_tick_mutation(
        monkeypatch,
        lambda tick: setattr(tick, bound, float(getattr(tick, bound)) + 0.5),
    )

    assert report["confirmed_cohorts"] == 0
    assert report["ordinary_intent_count"] == 0
    assert report["normal_order_submissions"] == 0
    assert report["reject_counts"] == {"QUOTE_OFF_TICK_GRID": 6}


@pytest.mark.parametrize(
    ("source", "event_time_source", "reason"),
    (
        ("   ", "fixture_utc", "QUOTE_SOURCE_MISSING"),
        ("local_synthetic_fixture", None, "EVENT_TIME_SOURCE_MISSING"),
        # The public validator checks the event-time provenance before the
        # source field, so a payload missing both has one deterministic cause.
        ("", "", "EVENT_TIME_SOURCE_MISSING"),
    ),
)
def test_missing_quote_provenance_cannot_form_an_ordinary_intent(
    monkeypatch, source, event_time_source, reason
):
    def clear_provenance(tick):
        tick.source = source
        tick.event_time_source = event_time_source

    report = _run_with_tick_mutation(monkeypatch, clear_provenance)

    assert report["confirmed_cohorts"] == 0
    assert report["ordinary_intent_count"] == 0
    assert report["normal_order_submissions"] == 0
    assert report["reject_counts"] == {reason: 6}


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    (
        ("source_clock_quality", "unknown", "SOURCE_CLOCK_UNVERIFIED"),
        ("receive_clock_quality", "unknown", "RECEIVE_CLOCK_UNVERIFIED"),
        ("freshness_verified", False, "FRESHNESS_UNVERIFIED"),
        ("clock_domain_id", " ", "CLOCK_DOMAIN_UNKNOWN"),
    ),
)
def test_public_quote_clock_and_freshness_gates_fail_closed(monkeypatch, field, value, reason):
    report = _run_with_tick_mutation(monkeypatch, lambda tick: setattr(tick, field, value))

    assert report["confirmed_cohorts"] == 0
    assert report["ordinary_intent_count"] == 0
    assert report["normal_order_submissions"] == 0
    assert report["reject_counts"] == {reason: 6}


@pytest.mark.parametrize(
    ("field", "value", "reason", "count"),
    (
        ("exchange", "DCE", "EXCHANGE_MISMATCH", 6),
        ("asset_type", "option", "ASSET_TYPE_MISMATCH", 2),
        ("stale", True, "QUOTE_STREAM_UNREADY", 6),
        ("stale_reason", "recovery_pending_validation", "QUOTE_STREAM_UNREADY", 6),
    ),
)
def test_frozen_exchange_role_and_stream_health_cannot_be_overridden(
    monkeypatch, field, value, reason, count
):
    report = _run_with_tick_mutation(monkeypatch, lambda tick: setattr(tick, field, value))

    assert report["confirmed_cohorts"] == 0
    assert report["ordinary_intent_count"] == 0
    assert report["normal_order_submissions"] == 0
    assert report["reject_counts"] == {reason: count}


@pytest.mark.parametrize("action_day", (None, "", "20260230", "2026-01-05"))
def test_missing_or_invalid_action_day_cannot_form_an_ordinary_intent(monkeypatch, action_day):
    report = _run_with_tick_mutation(
        monkeypatch,
        lambda tick: setattr(tick, "action_day", action_day),
    )

    assert report["confirmed_cohorts"] == 0
    assert report["ordinary_intent_count"] == 0
    assert report["normal_order_submissions"] == 0
    assert report["reject_counts"] == {"ACTION_DAY_INVALID": 6}


def test_valid_night_session_action_day_can_differ_from_trading_day(monkeypatch):
    report = _run_with_tick_mutation(
        monkeypatch,
        lambda tick: setattr(tick, "action_day", "20260909"),
    )

    assert report["confirmed_cohorts"] == 2
    assert report["ordinary_intent_count"] == 1
    assert {quote["action_day"] for quote in report["last_cohort"]["quotes"].values()} == {
        "20260909"
    }


def test_reconnect_with_sequence_restart_cannot_complete_a_cross_scope_confirmation(monkeypatch):
    original_cohort_events = runner._cohort_events

    def cohort_events(*args, **kwargs):
        events = original_cohort_events(*args, **kwargs)
        for event in events:
            if event.channel_type == "tick" and event.data.ingest_seq > 3:
                event.data.connection_generation = 2
                event.data.ingest_seq -= 3
        return events

    monkeypatch.setattr(runner, "_cohort_events", cohort_events)
    report = runner.run_replay(_config(), scenario="valid_cohort")

    assert report["confirmed_cohorts"] == 1
    assert report["ordinary_intent_count"] == 0
    assert report["normal_order_submissions"] == 0


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    (
        ("ask_price", 1.0e100, "QUOTE_NUMERIC_TYPE_INVALID"),
        ("bid_volume", sys.float_info.max, "QUOTE_NUMERIC_TYPE_INVALID"),
        ("lower_limit", 1.0e100, "QUOTE_NUMERIC_TYPE_INVALID"),
        ("source_clock_error_ms", sys.float_info.max, "SOURCE_CLOCK_ERROR_INVALID"),
    ),
)
def test_ctp_extreme_numeric_sentinels_cannot_form_an_ordinary_intent(
    monkeypatch, field, value, reason
):
    report = _run_with_tick_mutation(
        monkeypatch,
        lambda tick: setattr(tick, field, value),
    )

    assert report["confirmed_cohorts"] == 0
    assert report["ordinary_intent_count"] == 0
    assert report["normal_order_submissions"] == 0
    assert report["reject_counts"] == {reason: 6}


@pytest.mark.parametrize(
    ("field", "reason"),
    (("event_time_utc", "SOURCE_TIME_INVALID"), ("recv_time_utc", "RECEIVE_TIME_INVALID")),
)
def test_ctp_extreme_epoch_strings_cannot_form_an_ordinary_intent(monkeypatch, field, reason):
    report = _run_with_tick_mutation(
        monkeypatch,
        lambda tick: setattr(tick, field, "1e100"),
    )

    assert report["confirmed_cohorts"] == 0
    assert report["ordinary_intent_count"] == 0
    assert report["normal_order_submissions"] == 0
    assert report["reject_counts"] == {reason: 6}


@pytest.mark.parametrize(
    ("field", "reason"),
    (("event_time_utc", "SOURCE_TIME_INVALID"), ("recv_time_utc", "RECEIVE_TIME_INVALID")),
)
def test_boolean_epoch_values_cannot_form_an_ordinary_intent(monkeypatch, field, reason):
    report = _run_with_tick_mutation(
        monkeypatch,
        lambda tick: setattr(tick, field, True),
    )

    assert report["confirmed_cohorts"] == 0
    assert report["ordinary_intent_count"] == 0
    assert report["normal_order_submissions"] == 0
    assert report["reject_counts"] == {reason: 6}


def test_fractional_ingest_sequence_cannot_form_an_ordinary_intent(monkeypatch):
    report = _run_with_tick_mutation(
        monkeypatch,
        lambda tick: setattr(tick, "ingest_seq", tick.ingest_seq + 0.5),
    )

    assert report["confirmed_cohorts"] == 0
    assert report["ordinary_intent_count"] == 0
    assert report["normal_order_submissions"] == 0
    assert report["reject_counts"] == {"QUOTE_IDENTITY_TYPE_INVALID": 6}


@pytest.mark.parametrize(
    "field",
    ("ingest_seq", "connection_generation", "subscription_epoch", "recv_monotonic_ns"),
)
def test_uint64_identity_overflow_cannot_form_an_ordinary_intent(monkeypatch, field):
    report = _run_with_tick_mutation(
        monkeypatch,
        lambda tick: setattr(tick, field, 1 << 64),
    )

    assert report["confirmed_cohorts"] == 0
    assert report["ordinary_intent_count"] == 0
    assert report["normal_order_submissions"] == 0
    assert report["reject_counts"] == {"QUOTE_IDENTITY_TYPE_INVALID": 6}


@pytest.mark.parametrize("field", ("ask_price", "bid_volume"))
def test_boolean_ctp_price_or_volume_cannot_form_an_ordinary_intent(monkeypatch, field):
    report = _run_with_tick_mutation(
        monkeypatch,
        lambda tick: setattr(tick, field, True),
    )

    assert report["confirmed_cohorts"] == 0
    assert report["ordinary_intent_count"] == 0
    assert report["normal_order_submissions"] == 0
    assert report["reject_counts"] == {"QUOTE_NUMERIC_TYPE_INVALID": 6}


def test_bar_and_idle_callbacks_cannot_create_an_ordinary_intent():
    report = runner.run_replay(
        _config(), scenario="bar_only", invoke_idle_probe=True, invoke_next_probe=True
    )

    assert report["callback_counts"] == {"tick": 0, "bar": 1, "idle": 1, "next": 1}
    assert report["ordinary_intent_count"] == 0
    assert report["normal_order_submissions"] == 0
    assert report["actual_fills"] == 0


def test_direct_runner_is_self_contained_and_writes_only_requested_report(tmp_path):
    output = tmp_path / "replay-output"
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [
            sys.executable,
            str(EXAMPLE / "run.py"),
            "--mode",
            "replay",
            "--purpose",
            "formula",
            "--scenario",
            "valid_cohort",
            "--output-dir",
            str(output),
        ],
        cwd=EXAMPLE,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 0, (
        "Direct execution requires the installed backtrader package to expose "
        "backtrader.feeds.CtpQuoteCohortValidator and CtpCohortNow.\n" + completed.stderr
    )
    report = json.loads(completed.stdout)
    assert report["ordinary_intent_count"] == 1
    assert report["external_network_requests"] == 0
    assert (output / "report.json").is_file()
    assert (output / "run_manifest.json").is_file()


def test_direct_runner_uses_the_safe_local_replay_default_without_arguments():
    """A copied strategy directory is runnable without selecting an unsafe mode."""

    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [sys.executable, str(EXAMPLE / "run.py")],
        cwd=EXAMPLE,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["status"] == "LOCAL_REPLAY_PASS"
    assert report["ordinary_intent_count"] == 1
    assert report["external_network_requests"] == 0
    assert report["external_write_requests"] == 0


def test_python_sources_do_not_import_or_read_another_example_directory():
    source_files = [
        EXAMPLE / "__init__.py",
        EXAMPLE / "run.py",
        EXAMPLE / "ctp_options_highfreq_strategy.py",
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in source_files)

    assert "examples." not in source
    assert "ctp_options_common" not in source
    assert "strategy_candidate_approval" not in source
    assert "sys.path" not in source
    assert "importlib" not in (EXAMPLE / "run.py").read_text(encoding="utf-8")
    assert "CtpQuoteCohortValidator" in (EXAMPLE / "ctp_options_highfreq_strategy.py").read_text(
        encoding="utf-8"
    )
    assert "CtpCohortNow" in (EXAMPLE / "ctp_options_highfreq_strategy.py").read_text(
        encoding="utf-8"
    )
    assert "class QuoteEvidence" not in source
    assert "normalize_ctp_quote" not in source
    assert "def _validate_cohort" not in source
    assert strategy_module.CtpOptionsHighfreqStrategy.__module__.startswith(PACKAGE)


def test_non_replay_modes_fail_closed_before_any_runtime_chain_is_created():
    raw, _ = runner.load_config(EXAMPLE / "config.yaml")
    shadow = runner.effective_config(raw, mode="shadow", purpose="formula")

    with pytest.raises(runner.RunnerConfigurationError, match="REPLAY_MODE_REQUIRED"):
        runner.run_replay(shadow)


def test_replay_cash_cannot_be_lower_than_the_frozen_capital_contract():
    raw, _ = runner.load_config(EXAMPLE / "config.yaml")
    raw = deepcopy(raw)
    raw["replay"]["starting_cash"] = 9_999

    with pytest.raises(runner.RunnerConfigurationError, match="cover the capital cap"):
        runner.effective_config(raw, mode="replay", purpose="formula")


def _timing_fact(**overrides):
    values = {
        "fact_id": "fact-1",
        "fact_type": "durable_intent",
        "intent_id": "intent-1",
        "provider_id": "provider-1",
        "source_id": "source-1",
        "scope_id": "scope-1",
        "clock_domain_id": "clock-1",
        "order_id": "order-1",
        "leg_id": "FG701",
        "origin_lower_ns": 1_000_000_000,
    }
    values.update(overrides)
    return timing_module.TimingFact(**values)


def test_hf_t1_real_cerebro_no_market_noarg_idle_is_fail_closed_and_read_only():
    strategy, _events = _strategy_and_events()
    strategy.notify_idle()
    report = strategy.replay_report()
    projection = report["timing_projection"]

    assert report["callback_counts"]["idle"] == 1
    assert report["ordinary_intent_count"] == 0
    assert projection["clock_trusted"] is False
    assert projection["native_write_eligible"] is False
    assert projection["proposals"][0]["action"] == "BLOCK"
    assert projection["proposals"][0]["reason"] == "TRUSTED_NOW_REQUIRED"
    assert projection["proposals"][0]["native_write_eligible"] is False


def test_hf_t1_single_admissible_fact_set_drives_positive_projection_and_no_write():
    facts = (
        _timing_fact(fact_id="intent", fact_type="durable_intent"),
        _timing_fact(fact_id="send", fact_type="send", origin_lower_ns=1_100_000_000),
        _timing_fact(fact_id="confirm", fact_type="confirmed"),
        _timing_fact(fact_id="leg", fact_type="per_leg", leg_id="FG701"),
        _timing_fact(fact_id="aggregate", fact_type="aggregate"),
        _timing_fact(fact_id="hold", fact_type="hold"),
    )
    projection = timing_module.project_timing(
        facts,
        now_upper_ns=1_100_000_000 + 999_999_999,
        expected_provider_id="provider-1",
        expected_source_id="source-1",
        expected_scope_id="scope-1",
        expected_clock_domain_id="clock-1",
        intent_id="intent-1",
        leg_ids=("FG701",),
        last_idle_lower_ns=2_099_999_999,
    )

    assert projection.admissible_fact_ids == (
        "aggregate",
        "confirm",
        "hold",
        "intent",
        "leg",
        "send",
    )
    assert projection.confirmed is True
    assert projection.per_leg_expired == ()
    assert projection.aggregate_expired is False
    assert projection.hold_expired is False
    assert projection.protection_required is False
    assert projection.native_write_eligible is False
    assert all(proposal.native_write_eligible is False for proposal in projection.proposals)


@pytest.mark.parametrize(
    ("phase", "ttl_ns", "expired_field", "reason"),
    (
        ("per_leg", 1_000_000_000, "per_leg_expired", "PER_LEG_TTL_EXCEEDED"),
        ("aggregate", 3_000_000_000, "aggregate_expired", "UNHEDGED_TTL_EXCEEDED"),
        ("hold", 60_000_000_000, "hold_expired", "HOLDING_TTL_EXCEEDED"),
    ),
)
@pytest.mark.parametrize("delta_ns, expected_expired", ((-1, False), (0, True), (1, True)))
def test_hf_t1_ttl_boundaries_and_late_ack_cannot_extend_origin(
    phase, ttl_ns, expired_field, reason, delta_ns, expected_expired
):
    facts = (
        _timing_fact(fact_id="intent", fact_type="durable_intent"),
        _timing_fact(fact_id="send", fact_type="send", origin_lower_ns=1_100_000_000),
        _timing_fact(fact_id="phase", fact_type=phase),
        _timing_fact(
            fact_id="late-ack",
            fact_type="ack",
            origin_lower_ns=1_100_000_000 + ttl_ns + 999,
        ),
    )
    projection = timing_module.project_timing(
        facts,
        now_upper_ns=1_100_000_000 + ttl_ns + delta_ns,
        expected_provider_id="provider-1",
        expected_source_id="source-1",
        expected_scope_id="scope-1",
        expected_clock_domain_id="clock-1",
        intent_id="intent-1",
        leg_ids=("FG701",),
        last_idle_lower_ns=None,
    )

    assert bool(getattr(projection, expired_field)) is expected_expired
    assert (reason in projection.expired_reasons) is expected_expired
    assert "late-ack" in projection.admissible_fact_ids
    assert projection.protection_required is bool(projection.expired_reasons)
    assert projection.native_write_eligible is False
    assert all(proposal.native_write_eligible is False for proposal in projection.proposals)
    assert projection.origin_lower_ns == 1_100_000_000


def test_hf_t1_missing_or_foreign_identity_is_uncertain_evidence_only():
    facts = (
        _timing_fact(fact_id="valid", fact_type="confirmed"),
        _timing_fact(fact_id="foreign", provider_id="other-provider"),
        _timing_fact(fact_id="missing-source", source_id=""),
        _timing_fact(fact_id="missing-order", order_id=""),
    )
    projection = timing_module.project_timing(
        facts,
        now_upper_ns=1_100_000_000,
        expected_provider_id="provider-1",
        expected_source_id="source-1",
        expected_scope_id="scope-1",
        expected_clock_domain_id="clock-1",
        intent_id="intent-1",
        leg_ids=("FG701",),
        last_idle_lower_ns=None,
    )

    assert projection.admissible_fact_ids == ("valid",)
    assert projection.uncertain_fact_ids == (
        "foreign",
        "missing-order",
        "missing-source",
    )
    assert projection.confirmed is True
    assert projection.native_write_eligible is False


def test_hf_t1_idle_interval_boundary_requires_protection_without_reusing_cached_opportunity():
    projection = timing_module.project_timing(
        (_timing_fact(fact_type="confirmed"),),
        now_upper_ns=1_050_000_000,
        expected_provider_id="provider-1",
        expected_source_id="source-1",
        expected_scope_id="scope-1",
        expected_clock_domain_id="clock-1",
        intent_id="intent-1",
        leg_ids=("FG701",),
        last_idle_lower_ns=1_000_000_000,
    )

    assert projection.idle_overdue is True
    assert projection.protection_required is True
    assert projection.proposals[0].action == "PROTECT"
    assert projection.proposals[0].reason == "IDLE_INTERVAL_EXCEEDED"


@pytest.mark.parametrize(
    ("section", "field", "value", "limit"),
    (
        ("feed", "max_quote_age_ms", 250.001, 250),
        ("feed", "max_cross_leg_skew_ms", 100.001, 100),
        ("feed", "max_source_age_upper_ms", 250.001, 250),
        ("feed", "max_source_skew_upper_ms", 100.001, 100),
        ("feed", "max_source_clock_error_ms", 5.001, 5),
    ),
)
def test_freshness_and_clock_bounds_cannot_be_widened_past_frozen_limits(
    section, field, value, limit
):
    raw, _ = runner.load_config(EXAMPLE / "config.yaml")
    raw = deepcopy(raw)
    raw[section][field] = value

    with pytest.raises(runner.RunnerConfigurationError, match="frozen upper bound"):
        runner.effective_config(raw, mode="replay", purpose="formula")
