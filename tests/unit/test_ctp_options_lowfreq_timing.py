"""Pure local timing and risk projection contracts for the 014_1 example."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest


@pytest.fixture(scope="module")
def timing():
    return _load_timing_module()


@pytest.fixture(scope="module")
def strategy_runner():
    import importlib
    from pathlib import Path

    example = Path(__file__).resolve().parents[2] / "examples/014_1_ctp_options_lowfreq"
    assert example.is_dir()
    return importlib.import_module("examples.014_1_ctp_options_lowfreq.run")


def test_bar_envelope_and_strict_economic_score(timing):
    bars = {
        "F": {"close": 1000.0, "high": 1002.0, "low": 998.0},
        "C": {"close": 20.0, "high": 22.0, "low": 18.0},
        "P": {"close": 10.0, "high": 12.0, "low": 8.0},
    }
    envelopes = timing.freeze_bar_envelopes(
        bars,
        ticks={"F": 1.0, "C": 1.0, "P": 1.0},
        scope="synthetic-fq3",
    )
    assert envelopes["F"].half_envelope == 2.0
    assert (envelopes["F"].lower, envelopes["F"].upper) == (998.0, 1002.0)
    assert (envelopes["C"].lower, envelopes["C"].upper) == (18.0, 22.0)
    assert (envelopes["P"].lower, envelopes["P"].upper) == (8.0, 12.0)
    scores = timing.economic_scores(
        envelopes,
        multiplier=10.0,
        discount=1.0,
        strike=1000.0,
        total_costs={"conversion": 20.0, "reversal": 20.0},
    )
    assert scores["conversion"].gross_cny == 40.0
    assert scores["reversal"].gross_cny == -160.0
    assert scores["conversion"].net_cny == 20.0
    assert scores["conversion"].eligible is False
    assert (
        timing.economic_scores(
            envelopes,
            multiplier=10.0,
            discount=1.0,
            strike=1000.0,
            total_costs={"conversion": 25.0, "reversal": 25.0},
        )["conversion"].net_cny
        == 15.0
    )


def test_price_and_exchange_limit_intersection_is_fail_closed(timing):
    bars = {"F": {"close": 1000.0, "high": 1002.0, "low": 998.0}}
    with pytest.raises(timing.TimingContractError):
        timing.freeze_bar_envelopes(bars, ticks={"F": 1.0}, scope="")
    envelopes = timing.freeze_bar_envelopes(
        bars,
        ticks={"F": 1.0},
        exchange_limits={"F": {"lower": 999.0, "upper": 1001.0, "source": "fixture"}},
        scope="fixture-scope",
    )
    assert (envelopes["F"].lower, envelopes["F"].upper) == (999.0, 1001.0)
    assert timing.price_allowed(envelopes["F"], "buy", 1001.0)
    assert not timing.price_allowed(envelopes["F"], "buy", 1002.0)
    assert not timing.price_allowed(envelopes["F"], "sell", 998.0)


def test_six_side_offset_fee_schedule_is_complete_or_rejected(timing):
    bars = {
        "F": {"close": 1000.0, "high": 1002.0, "low": 998.0},
        "C": {"close": 20.0, "high": 22.0, "low": 18.0},
        "P": {"close": 10.0, "high": 12.0, "low": 8.0},
    }
    envelopes = timing.freeze_bar_envelopes(
        bars, ticks=dict.fromkeys(bars, 1.0), scope="fee-fixture"
    )
    fees = dict.fromkeys(
        (
            "open_buy",
            "open_sell",
            "close_buy",
            "close_sell",
            "close_today_buy",
            "close_today_sell",
        ),
        3.02,
    )
    scores = timing.economic_scores(
        envelopes,
        multiplier=10,
        discount=1,
        strike=1000,
        fee_schedule=fees,
    )
    assert scores["conversion"].total_cost_cny == pytest.approx(18.12)
    broken = dict(fees)
    broken.pop("close_today_sell")
    with pytest.raises(timing.TimingContractError):
        timing.economic_scores(
            envelopes,
            multiplier=10,
            discount=1,
            strike=1000,
            fee_schedule=broken,
        )


@pytest.mark.parametrize("bad", (True, float("nan"), float("inf"), 0.0))
def test_bar_envelope_rejects_nonpositive_or_nonfinite_tick(timing, bad):
    with pytest.raises(timing.TimingContractError):
        timing.freeze_bar_envelopes(
            {"F": {"close": 1000, "high": 1002, "low": 998}},
            ticks={"F": bad},
            scope="bad-tick",
        )


def test_deadline_boundaries_do_not_move_on_ack_or_retry(timing):
    window = timing.ExecutionWindow(decision_mono_ns=100_000_000_000)
    assert window.gate(101_000_000_000, "first_send").status == "ELIGIBLE_FOR_OTHER_GATES"
    assert window.gate(101_000_000_001, "first_send").status == "REJECT_NEW_ORDINARY_WRITE"
    assert window.gate(160_000_000_000, "remaining_legs").status == "ELIGIBLE_FOR_OTHER_GATES"
    assert (
        window.gate(160_000_000_001, "remaining_legs", possible_exposure=True).status
        == "RECOVERY_REQUIRED"
    )
    assert window.first_send_deadline_ns == 101_000_000_000
    assert window.completion_deadline_ns == 160_000_000_000
    window.observe_ack(199_000_000_000)
    assert window.first_send_deadline_ns == 101_000_000_000
    assert window.completion_deadline_ns == 160_000_000_000


def test_hold_projection_uses_fill_upper_for_min_and_exposure_lower_for_max(timing):
    holds = timing.HoldProjection(
        expected_legs=("F", "C", "P"), minimum_hold_seconds=1800, maximum_hold_seconds=7200
    )
    holds.record_possible_exposure("F", lower_ns=1_000_000_000_000)
    holds.record_confirmed_fill("F", 1_000_000_000_000, 1_010_000_000_000)
    holds.record_confirmed_fill("C", 1_025_000_000_000, 1_030_000_000_000)
    holds.record_confirmed_fill("P", 1_025_000_000_000, 1_030_000_000_000)
    assert holds.maximum_deadline_ns == 8_200_000_000_000
    assert holds.minimum_deadline_ns == 2_830_000_000_000
    assert holds.normal_exit_allowed(2_829_999_999_999) is False
    assert holds.normal_exit_allowed(2_830_000_000_000) is True
    assert holds.risk_exit_allowed(1_100_000_000_000) is False
    assert holds.risk_exit_allowed(8_200_000_000_000) is True


def test_clock_domain_regression_and_wall_jump_are_separate(timing):
    clock = timing.ScopedClock()
    clock.observe(
        timing.ClockObservation(
            monotonic_ns=100,
            wall_utc=datetime(2026, 9, 10, tzinfo=timezone.utc),
            domain="d1",
        )
    )
    clock.observe(
        timing.ClockObservation(
            monotonic_ns=200,
            wall_utc=datetime(2026, 9, 9, tzinfo=timezone.utc),
            domain="d1",
        )
    )
    assert clock.deadline_delta_ns(100, 200) == 100
    with pytest.raises(timing.ClockSafetyError):
        clock.observe(
            timing.ClockObservation(
                monotonic_ns=199,
                wall_utc=datetime(2026, 9, 10, tzinfo=timezone.utc),
                domain="d1",
            )
        )
    assert clock.rejection_reason == "CLOCK_REGRESSION"


def test_external_clock_requires_source_and_generation_and_binds_generation(timing):
    with pytest.raises(timing.ClockSafetyError):
        timing.ScopedClock().observe(
            {
                "monotonic_ns": 100,
                "wall_utc": datetime(2026, 9, 10, tzinfo=timezone.utc),
                "domain": "unsourced",
            }
        )
    clock = timing.ScopedClock()
    clock.observe(
        timing.ClockObservation(
            100,
            datetime(2026, 9, 10, tzinfo=timezone.utc),
            "d1",
            generation=1,
            trusted=True,
        )
    )
    with pytest.raises(timing.ClockSafetyError, match="GENERATION_CHANGED"):
        clock.observe(
            timing.ClockObservation(
                101,
                datetime(2026, 9, 10, tzinfo=timezone.utc),
                "d1",
                generation=2,
                trusted=True,
            )
        )


def test_risk_mapping_age_cannot_be_renewed_by_wall_rollback_or_untrusted_clock(timing):
    base = datetime(2026, 9, 10, tzinfo=timezone.utc)
    clock = timing.ScopedClock()
    before = clock.observe(
        timing.ClockObservation(911_000_000_000, base + timedelta(seconds=911), "d1")
    )
    assert (
        timing.project_risk_bar(
            bucket_end=base,
            now=before,
            session_open=True,
            price_limits_known=True,
        ).status
        == "BLOCKED_UNTIL_VALID_EVIDENCE"
    )
    after = clock.observe(
        timing.ClockObservation(912_000_000_000, base + timedelta(seconds=12), "d1")
    )
    assert (
        timing.project_risk_bar(
            bucket_end=base,
            now=after,
            session_open=True,
            price_limits_known=True,
        ).status
        == "BLOCKED_UNTIL_VALID_EVIDENCE"
    )
    untrusted = timing.project_risk_bar(
        bucket_end=base,
        now=timing.ClockObservation(
            1_000_000_000,
            base + timedelta(seconds=1),
            "d1",
            trusted=False,
        ),
        session_open=True,
        price_limits_known=True,
    )
    assert untrusted.status == "BLOCKED_UNTIL_VALID_EVIDENCE"


def test_ohlc_cannot_prove_ttl_fill_but_explicit_fact_can(timing):
    unknown = timing.classify_bar_only_fill(
        decision_mono_ns=100_000_000_000,
        next_bar_seconds=900,
        execution_window_seconds=60,
        touched=True,
        volume=10000,
    )
    assert unknown.status == "FILL_TIMING_UNKNOWN"
    assert unknown.confirmed_quantity == 0
    fact = timing.ExecutionFact(
        leg="P",
        quantity=1,
        status="completed",
        fill_lower_ns=100_500_000_000,
        fill_upper_ns=100_500_000_000,
        source="synthetic_timestamped_execution",
    )
    known = timing.classify_execution_facts((fact,), deadline_ns=160_000_000_000)
    assert known.status == "TIMESTAMPED_SYNTHETIC_ONLY"
    assert known.confirmed_quantity == 1


def test_scoped_execution_facts_require_identity_and_are_idempotent(timing):
    valid = timing.ExecutionFact(
        leg="P",
        quantity=1,
        status="completed",
        fill_lower_ns=110,
        fill_upper_ns=120,
        source="synthetic_timestamped_execution",
        clock_domain="d1",
        generation=1,
        fact_id="fill-1",
    )
    duplicate = timing.ExecutionFact(
        leg="P",
        quantity=1,
        status="completed",
        fill_lower_ns=110,
        fill_upper_ns=120,
        source="synthetic_timestamped_execution",
        clock_domain="d1",
        generation=1,
        fact_id="fill-1",
    )
    foreign = timing.ExecutionFact(
        leg="P",
        quantity=1,
        status="completed",
        fill_lower_ns=110,
        fill_upper_ns=120,
        source="synthetic_timestamped_execution",
        clock_domain="foreign-boot",
        generation=9,
        fact_id="fill-foreign",
    )
    result = timing.classify_execution_facts(
        [valid, duplicate, foreign],
        deadline_ns=160,
        expected_clock_domain="d1",
        expected_generation=1,
        decision_mono_ns=100,
    )
    assert result.confirmed_quantity == 1
    assert result.status == "TIMESTAMPED_SYNTHETIC_ONLY"


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    (
        ("order_id", "foreign-order", "FILL_ORDER_MISMATCH"),
        ("decision_id", "foreign-decision", "FILL_DECISION_MISMATCH"),
        ("basket_id", "foreign-basket", "FILL_BASKET_MISMATCH"),
        ("clock_domain", "foreign-clock", "FILL_CLOCK_DOMAIN_MISMATCH"),
        ("generation", 2, "FILL_CLOCK_GENERATION_MISMATCH"),
    ),
)
def test_execution_fact_admission_requires_one_order_and_complete_scope(
    timing, strategy_runner, field, value, reason
):
    """Every confirmation view must consume the same fully scoped admitted fact set."""

    strategy = SimpleNamespace(
        p=SimpleNamespace(clock_provider=None),
        _decision_scope=("20260910", 1, "day", "rules", "d1"),
        _active_decision_id="decision-1",
        _active_basket_id="basket-1",
        _planned_legs=[{"symbol": "P"}],
        _leg_index=0,
        _pending_order_ref=7,
        _submitted_order_ids_by_leg={"P": {"7"}},
        _execution_window=None,
        _execution_facts=[],
        _execution_fact_history=[],
        _execution_fact_keys=set(),
        _quarantined_execution_facts=[],
        _rejected_execution_possible=False,
        _hold_projection=timing.HoldProjection(
            expected_legs=("P",), minimum_hold_seconds=1800, maximum_hold_seconds=7200
        ),
        _confirmed_fill_by_leg={},
        _confirmed_fill_quantity=0.0,
        _fill_timing=timing.replay_fill_status(),
    )
    strategy_type = strategy_runner.CtpOptionsLowfreqStrategy
    strategy._strict_execution_scope = strategy_type._strict_execution_scope.__get__(strategy)
    strategy._confirmed_leg_quantity = strategy_type._confirmed_leg_quantity.__get__(strategy)
    valid = {
        "leg": "P",
        "quantity": 1,
        "status": "completed",
        "fill_lower_ns": 100,
        "fill_upper_ns": 100,
        "source": "synthetic_timestamped_execution",
        "clock_domain": "d1",
        "generation": 1,
        "decision_id": "decision-1",
        "basket_id": "basket-1",
        "order_id": "7",
        "fact_id": f"fact-{field}",
    }
    valid[field] = value

    result = strategy_runner.CtpOptionsLowfreqStrategy.record_execution_fact(strategy, valid)

    assert result["status"] == "FILL_TIMING_UNKNOWN"
    assert result["confirmed_quantity"] == 0
    assert strategy._execution_facts == []
    assert strategy._confirmed_fill_by_leg == {}
    assert strategy._hold_projection.projection()["confirmed_fill_upper_ns"] == {}
    assert strategy._rejected_execution_possible is True
    assert strategy._quarantined_execution_facts == [
        {"fact_id": f"fact-{field}", "leg": "P", "reason": reason}
    ]

    positive = SimpleNamespace(**strategy.__dict__)
    positive._execution_facts = []
    positive._execution_fact_history = []
    positive._execution_fact_keys = set()
    positive._quarantined_execution_facts = []
    positive._rejected_execution_possible = False
    positive._hold_projection = timing.HoldProjection(
        expected_legs=("P",), minimum_hold_seconds=1800, maximum_hold_seconds=7200
    )
    positive._confirmed_fill_by_leg = {}
    positive._confirmed_fill_quantity = 0.0
    positive._fill_timing = timing.replay_fill_status()
    positive._strict_execution_scope = strategy_type._strict_execution_scope.__get__(positive)
    positive._confirmed_leg_quantity = strategy_type._confirmed_leg_quantity.__get__(positive)
    positive_result = strategy_type.record_execution_fact(
        positive,
        {
            **valid,
            field: {
                "order_id": "7",
                "decision_id": "decision-1",
                "basket_id": "basket-1",
                "clock_domain": "d1",
                "generation": 1,
            }.get(field, valid[field]),
        },
    )
    assert positive_result["confirmed_quantity"] == 1
    assert positive._confirmed_fill_by_leg == {"P": 1}
    assert positive._hold_projection.projection()["confirmed_fill_upper_ns"] == {"P": 100}


def test_token_and_confirmation_projection_resets_invalid_scope_direction_and_gap(timing):
    token = timing.ExecutionToken("candidate", "20260910", "day", "bar")
    gate = timing.TokenProjection()
    assert gate.consume(token) is True
    assert gate.consume(token) is False
    confirm = timing.ConfirmationProjection(required=2)
    assert confirm.accept("conversion", "scope", "bar1", qualified=True) is False
    assert confirm.accept("conversion", "scope", "bar2", qualified=True) is True
    confirm.reset("invalid")
    assert confirm.accept("conversion", "scope", "bar3", qualified=True) is False
    assert confirm.accept("reversal", "scope", "bar4", qualified=True) is False
    assert confirm.accept("conversion", "new-scope", "bar5", qualified=True) is False


def test_risk_bar_age_and_session_gate_are_conservative(timing):
    now = timing.ClockObservation(
        monotonic_ns=1_000_000_000_000,
        wall_utc=datetime(2026, 9, 10, 9, 15, 11, tzinfo=timezone.utc),
        domain="d1",
    )
    fresh = timing.project_risk_bar(
        bucket_end=datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc),
        now=now,
        session_open=True,
        price_limits_known=True,
        mapping_error_ns=0,
    )
    assert fresh.age_upper_seconds == 911.0
    assert fresh.status == "BLOCKED_UNTIL_VALID_EVIDENCE"
    assert fresh.allowed_actions == ("query", "record_unresolved_exposure", "continue_monitoring")
    assert fresh.successful_flat_exit is False
    eligible = timing.project_risk_bar(
        bucket_end=datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc),
        now=timing.ClockObservation(
            monotonic_ns=1_000_000_000_000,
            wall_utc=datetime(2026, 9, 10, 9, 15, 10, tzinfo=timezone.utc),
            domain="d1",
        ),
        session_open=True,
        price_limits_known=True,
        mapping_error_ns=0,
    )
    assert eligible.status == "RECOVERY_PRICE_ELIGIBLE"


def test_risk_bar_evidence_requires_current_scope_source_and_reference(timing):
    now = timing.ClockObservation(
        monotonic_ns=10_000_000_000,
        wall_utc=datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc),
        domain="d1",
        generation=1,
        trusted=True,
    )
    scope = ("20260910", 1, "day", "rules", "d1")
    valid = timing.project_risk_bar(
        bucket_end=now.wall_utc,
        now=now,
        session_open=True,
        price_limits_known=True,
        scope=scope,
        session_evidence={"scope": scope, "generation": 1, "source": "session-query"},
        price_limits_evidence={
            "scope": scope,
            "generation": 1,
            "source": "instrument-query",
            "reference_identity": "instrument-query-1",
        },
    )
    assert valid.status == "RECOVERY_PRICE_ELIGIBLE"
    missing_source = timing.project_risk_bar(
        bucket_end=now.wall_utc,
        now=now,
        session_open=True,
        price_limits_known=True,
        scope=scope,
        session_evidence={"scope": scope, "generation": 1},
        price_limits_evidence={
            "scope": scope,
            "generation": 1,
            "source": "instrument-query",
        },
    )
    assert missing_source.status == "BLOCKED_UNTIL_VALID_EVIDENCE"


def test_session_and_loss_projection_keeps_missing_account_facts_unknown(timing):
    policy = timing.SessionRiskPolicy()
    session_end = datetime(2026, 9, 10, 15, 0, tzinfo=timezone.utc)
    open_projection = policy.evaluate(
        now_utc=datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc),
        session_end_utc=session_end,
        account_risk_known=False,
        fees_complete=False,
    )
    assert open_projection.ordinary_entry_allowed is False
    assert open_projection.account_risk_status == "UNKNOWN"
    exit_projection = policy.evaluate(
        now_utc=datetime(2026, 9, 10, 14, 50, tzinfo=timezone.utc),
        session_end_utc=session_end,
        basket_loss=150.0,
        daily_loss=300.0,
        account_risk_known=True,
        fees_complete=True,
    )
    assert exit_projection.ordinary_exit_due is True
    assert exit_projection.handover_due is False
    assert exit_projection.basket_loss_triggered is True
    assert exit_projection.daily_loss_triggered is True
    handover_projection = policy.evaluate(
        now_utc=datetime(2026, 9, 10, 14, 58, tzinfo=timezone.utc),
        session_end_utc=session_end,
        basket_loss=0,
        daily_loss=0,
        account_risk_known=True,
        fees_complete=True,
    )
    assert handover_projection.handover_due is True


def test_actual_cerebro_no_bar_dispatches_notify_idle_without_bar_time_fallback():
    import backtrader as bt
    import importlib

    runner = importlib.import_module("examples.014_1_ctp_options_lowfreq.run")

    class IdleFeed(bt.feed.DataBase):
        params = (("qcheck", 0.0),)

        def __init__(self):
            super().__init__()
            self.calls = 0

        def islive(self):
            return True

        def _load(self):
            self.calls += 1
            return None if self.calls == 1 else False

    config = runner.load_config()
    candidate = config["candidate"]
    symbols = (candidate["future"], candidate["call"], candidate["put"])
    now_calls = []

    def provider():
        now_calls.append(len(now_calls) + 1)
        return {
            "now_monotonic_ns": len(now_calls),
            "clock_domain_id": "actual-cerebro-idle",
            "now_epoch": 1790000000.0,
            "generation": 1,
            "trusted": True,
            "source": "synthetic-observed-clock",
        }

    params = dict(config["strategy_params"])
    params.update(
        candidate_id="fq3-idle-test",
        future_symbol=candidate["future"],
        call_symbol=candidate["call"],
        put_symbol=candidate["put"],
        strike=candidate["strike"],
        multiplier=candidate["multiplier"],
        discount=candidate["discount"],
        capital_limit=config["budget"]["capital_limit"],
        ordinary_limit=config["budget"]["ordinary_limit"],
        recovery_reserve=config["budget"]["recovery_reserve"],
        price_ticks=dict.fromkeys(symbols, config["strategy_params"]["price_tick"]),
        exchange_limits=dict.fromkeys(
            symbols,
            {"lower": 0.01, "upper": 1_000_000.0, "source": "synthetic-idle-fixture"},
        ),
        clock_provider=provider,
        **config["timing"],
    )
    cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
    for symbol in symbols:
        cerebro.adddata(IdleFeed(), name=symbol)
    cerebro.addstrategy(runner.CtpOptionsLowfreqStrategy, **params)
    strategies = cerebro.run(runonce=False)
    assert len(strategies) == 1
    assert now_calls == [1]
    assert strategies[0]._clock.last.monotonic_ns == 1
    assert strategies[0]._clock_rejection_latched is False


def test_actual_cerebro_confirmed_legs_use_frozen_holds_and_fresh_exit_window():
    """A legal synthetic fill trace drives the real strategy to ordinary exit."""

    import backtrader as bt
    import importlib

    runner = importlib.import_module("examples.014_1_ctp_options_lowfreq.run")

    config = runner.load_config()
    candidate = config["candidate"]
    symbols = (candidate["future"], candidate["call"], candidate["put"])
    clock = SimpleNamespace(strategy=None, last=None, calls=0)

    def provider():
        strategy = clock.strategy
        current = getattr(strategy, "_current_clock_now_ns", 0)
        state = getattr(strategy, "_state", "FLAT")
        if clock.last is None:
            value = current
        elif state == "OPEN" and current > clock.last:
            # The ordinary exit decision starts a separate window at the
            # current closed-bar clock point.
            value = current
        else:
            # Simulated callback delivery is kept inside the fixed 60-second
            # completion window; it is an explicit synthetic clock, not a
            # claim about a real CTP callback.
            value = clock.last + 100_000_000
        clock.last = value
        clock.calls += 1
        return {
            "now_monotonic_ns": value,
            "clock_domain_id": "iter23-replay-clock",
            "generation": 1,
            "trusted": True,
            "source": "synthetic-cerebro-fill-clock",
            "now_epoch": 1_790_000_000.0 + value / 1_000_000_000.0,
            "boot_id": "synthetic-cerebro-boot-1",
        }

    class ConfirmedFillStrategy(runner.CtpOptionsLowfreqStrategy):
        def __init__(self):
            clock.strategy = self
            self.submission_fact_counts = []
            self.injected_facts = []
            super().__init__()

        def _submit_next_leg(self):
            if self._state == "ENTERING" and self._leg_index < len(self._planned_legs):
                self.submission_fact_counts.append((self._leg_index, len(self._execution_facts)))
            return super()._submit_next_leg()

        def notify_order(self, order):
            if order.status == order.Completed and self._state == "ENTERING":
                leg_index = self._leg_index
                fill_ns = (
                    self._execution_window.decision_mono_ns + 500_000_000 + leg_index * 100_000_000
                )
                fact = {
                    "leg": order.data._name,
                    "quantity": 1,
                    "status": "completed",
                    "fill_lower_ns": fill_ns,
                    "fill_upper_ns": fill_ns,
                    "source": "synthetic_timestamped_execution",
                    "clock_domain": "iter23-replay-clock",
                    "generation": 1,
                    "decision_id": self._active_decision_id,
                    "basket_id": self._active_basket_id,
                    "order_id": str(order.ref),
                    "fact_id": f"cerebro-fill-{order.ref}",
                    "source_identity": "synthetic-cerebro-fill-v1",
                }
                self.injected_facts.append(fact)
                self.record_execution_fact(fact)
            return super().notify_order(order)

    params = dict(config["strategy_params"])
    params.update(
        candidate_id="fq3-confirmed-cerebro",
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
        clock_provider=provider,
    )
    params["price_ticks"] = dict.fromkeys(symbols, params["price_tick"])
    params["exchange_limits"] = {
        symbol: {
            "lower": 0.01,
            "upper": 10_000_000.0,
            "source": "synthetic-replay-price-limit-fixture",
        }
        for symbol in symbols
    }
    params["fee_schedule"] = dict.fromkeys(
        (
            "open_buy",
            "open_sell",
            "close_buy",
            "close_sell",
            "close_today_buy",
            "close_today_sell",
        ),
        float(params["round_trip_cost"]) / 6.0,
    )
    params["exit_reserve"] = 0.0
    params["financing_reserve"] = 0.0
    params["model_reserve"] = 0.0

    cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
    cerebro.broker.setcash(config["budget"]["capital_limit"])
    for symbol, rows in runner.replay_bars(candidate, "eligible").items():
        cerebro.adddata(runner._feed(rows), name=symbol)
    cerebro.addstrategy(ConfirmedFillStrategy, **params)
    strategy = cerebro.run(runonce=False)[0]
    report = strategy.report()

    assert strategy._state == "FLAT"
    assert report["flat_status"] == "LOCAL_BASKET_FLAT_UNVERIFIED"
    assert len(report["orders"]) == 6
    assert strategy.submission_fact_counts[:3] == [(0, 0), (1, 1), (2, 2)]
    assert len(strategy.injected_facts) == 3
    assert {fact["clock_domain"] for fact in strategy.injected_facts} == {"iter23-replay-clock"}
    assert {fact["generation"] for fact in strategy.injected_facts} == {1}
    assert {fact["decision_id"] for fact in strategy.injected_facts} == {
        strategy._active_decision_id
    }
    assert {fact["basket_id"] for fact in strategy.injected_facts} == {strategy._active_basket_id}
    assert all(fact["order_id"] and fact["fact_id"] for fact in strategy.injected_facts)

    timing = report["timing_projection"]
    entry_window = timing["execution_window"]
    exit_window = timing["exit_execution_window"]
    assert (
        entry_window["first_send_deadline_ns"] == entry_window["decision_mono_ns"] + 1_000_000_000
    )
    assert (
        entry_window["completion_deadline_ns"] == entry_window["decision_mono_ns"] + 60_000_000_000
    )
    assert exit_window["decision_mono_ns"] > entry_window["decision_mono_ns"]
    assert exit_window["first_send_deadline_ns"] == exit_window["decision_mono_ns"] + 1_000_000_000
    assert exit_window["completion_deadline_ns"] == exit_window["decision_mono_ns"] + 60_000_000_000

    hold = timing["hold"]
    assert set(hold["confirmed_fill_upper_ns"]) == set(symbols)
    assert (
        hold["minimum_deadline_ns"]
        == max(hold["confirmed_fill_upper_ns"].values()) + 1_800_000_000_000
    )
    assert (
        hold["maximum_deadline_ns"] == hold["first_possible_exposure_lower_ns"] + 7_200_000_000_000
    )
    exit_event = next(event for event in report["events"] if event["kind"] == "exit_decision")
    assert exit_event["reason"] == "residual_reverted"
    assert exit_event["held_minutes"] >= 30.0
    assert exit_window["decision_mono_ns"] < hold["maximum_deadline_ns"]
    assert timing["confirmed_fill_by_leg"] == dict.fromkeys(symbols, 1.0)
    assert timing["quarantined_execution_facts"] == []


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    (
        ("order_id", "foreign-order", "FILL_ORDER_MISMATCH"),
        ("decision_id", "foreign-decision", "FILL_DECISION_MISMATCH"),
        ("basket_id", "foreign-basket", "FILL_BASKET_MISMATCH"),
    ),
)
def test_actual_foreign_fact_cannot_authorize_next_protection_leg(field, value, reason):
    """Foreign identity facts keep risk evidence but grant no leg permission."""

    import backtrader as bt
    import importlib

    runner = importlib.import_module("examples.014_1_ctp_options_lowfreq.run")

    config = runner.load_config()
    candidate = config["candidate"]
    symbols = (candidate["future"], candidate["call"], candidate["put"])
    clock = SimpleNamespace(strategy=None, now=None)

    def provider():
        strategy = clock.strategy
        current = getattr(strategy, "_current_clock_now_ns", 0)
        if clock.now is None or (strategy._state == "OPEN" and current > clock.now):
            value = current
        else:
            value = clock.now + 100_000_000
        clock.now = value
        return {
            "now_monotonic_ns": value,
            "clock_domain_id": "iter23-replay-clock",
            "generation": 1,
            "trusted": True,
            "source": "synthetic-foreign-fact-clock",
            "now_epoch": 1_790_000_000.0 + value / 1_000_000_000.0,
            "boot_id": "synthetic-foreign-fact-boot-1",
        }

    class LoggingBroker(bt.brokers.BackBroker):
        def __init__(self):
            super().__init__()
            self.handoffs = []

        def buy(self, *args, **kwargs):
            self.handoffs.append("buy")
            return super().buy(*args, **kwargs)

        def sell(self, *args, **kwargs):
            self.handoffs.append("sell")
            return super().sell(*args, **kwargs)

    class ForeignFactStrategy(runner.CtpOptionsLowfreqStrategy):
        def __init__(self):
            clock.strategy = self
            self.injected_facts = []
            super().__init__()

        def notify_order(self, order):
            if order.status == order.Completed and self._state == "ENTERING":
                fill_ns = self._execution_window.decision_mono_ns + 500_000_000
                fact = {
                    "leg": order.data._name,
                    "quantity": 1,
                    "status": "completed",
                    "fill_lower_ns": fill_ns,
                    "fill_upper_ns": fill_ns,
                    "source": "synthetic_timestamped_execution",
                    "clock_domain": "iter23-replay-clock",
                    "generation": 1,
                    "decision_id": self._active_decision_id,
                    "basket_id": self._active_basket_id,
                    "order_id": str(order.ref),
                    "fact_id": f"foreign-fact-{order.ref}",
                    "source_identity": "synthetic-foreign-fact-test",
                }
                fact[field] = value
                self.injected_facts.append(fact)
                self.record_execution_fact(fact)
            return super().notify_order(order)

    params = dict(config["strategy_params"])
    params.update(
        candidate_id="fq3-foreign-fact-cerebro",
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
        clock_provider=provider,
    )
    params["price_ticks"] = dict.fromkeys(symbols, params["price_tick"])
    params["exchange_limits"] = {
        symbol: {
            "lower": 0.01,
            "upper": 10_000_000.0,
            "source": "synthetic-foreign-fact-limits",
        }
        for symbol in symbols
    }
    params["fee_schedule"] = dict.fromkeys(
        (
            "open_buy",
            "open_sell",
            "close_buy",
            "close_sell",
            "close_today_buy",
            "close_today_sell",
        ),
        float(params["round_trip_cost"]) / 6.0,
    )
    params["exit_reserve"] = 0.0
    params["financing_reserve"] = 0.0
    params["model_reserve"] = 0.0

    cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
    broker = LoggingBroker()
    cerebro.setbroker(broker)
    broker.setcash(config["budget"]["capital_limit"])
    for symbol, rows in runner.replay_bars(candidate, "eligible").items():
        cerebro.adddata(runner._feed(rows), name=symbol)
    cerebro.addstrategy(ForeignFactStrategy, **params)
    strategy = cerebro.run(runonce=False)[0]
    report = strategy.report()
    timing = report["timing_projection"]

    assert broker.handoffs == ["buy"]
    assert strategy._state == "HALTED"
    assert len(report["orders"]) == 1
    assert timing["confirmed_fill_quantity"] == 0
    assert timing["confirmed_fill_by_leg"] == {}
    assert timing["possible_exposure"] is True
    assert timing["fill_timing"]["status"] == "FILL_TIMING_UNKNOWN"
    assert timing["fill_timing"]["possible_exposure"] is True
    assert len(strategy._execution_fact_history) == 1
    assert strategy._execution_facts == []
    assert len(timing["quarantined_execution_facts"]) == 1
    assert timing["quarantined_execution_facts"][0]["reason"] == reason
    assert strategy.injected_facts[0][field] == value


def _load_timing_module():
    import importlib

    return importlib.import_module("examples.014_1_ctp_options_lowfreq.execution_timing")
