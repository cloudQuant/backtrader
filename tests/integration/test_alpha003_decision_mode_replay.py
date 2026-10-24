"""Actual Alpha003 snapshots through the 028 decision and replay contracts.

This extends the fixed-economics journal test with real Alpha003 values and
receipts from the established source-backed Cerebro fixture.  The remaining
account, position, quote, and instrument facts are fixed typed test inputs;
provider, account, and native execution APIs are never called.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import backtrader as bt
import pandas as pd
import pytest

from backtrader.brokers.factor_replay import CausalReplayBroker, ReplayBarTiming
from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionJournal,
    ExecutionDecisionJournalError,
    ExecutionDecisionKey,
)
from backtrader.stores.factor_execution import FactorExecutionCoordinator
from backtrader.stores.registered_sim import RegisteredSimStore
from tests.integration import test_factor_decision_replay_economics as economics
from tests.integration import test_live_alpha003_parity as parity


_STRATEGY = economics._STRATEGY
_UTC = parity._UTC
_TARGETS = tuple("asset-%d" % index for index in range(6))
_PRODUCT_KEYS = {
    "asset-0": ("SHFE", "rb"),
    "asset-1": ("DCE", "i"),
    "asset-2": ("SHFE", "cu"),
    "asset-3": ("DCE", "jm"),
    "asset-4": ("SHFE", "al"),
    "asset-5": ("DCE", "m"),
}
_PLANNING_ROUTES = {
    "asset-0": ("rb2610", "SHFE"),
    "asset-1": ("i2610", "DCE"),
    "asset-2": ("cu2610", "SHFE"),
    "asset-3": ("jm2610", "DCE"),
    "asset-4": ("al2610", "SHFE"),
    "asset-5": ("m2610", "DCE"),
}
_ACCOUNT_SCOPE = economics.ACCOUNT_SCOPE
_STRATEGY_SCOPE = economics.STRATEGY_SCOPE
_RUN_ID = economics.RUN_ID


def _policy_input(batch, snapshot, *, execution_mode):
    return _STRATEGY.policy_input_from_shared_snapshot(
        batch,
        snapshot,
        required_targets=_TARGETS,
        authorized_targets=_TARGETS,
        product_keys=_PRODUCT_KEYS,
        execution_mode=execution_mode,
        eligible_grid_index=batch.slot_index + 1,
        rebalance_every=5,
    )


def _planning(target_decision, *, close, replay=False):
    planning = economics._planning_input(target_decision, close=close)
    positions = tuple(
        replace(
            planning.positions[0],
            target_id=target,
            instrument=instrument,
            exchange=exchange,
        )
        for target, (instrument, exchange) in _PLANNING_ROUTES.items()
    )
    instruments = tuple(
        replace(
            planning.instruments[0],
            target_id=target,
            instrument=instrument,
            exchange=exchange,
        )
        for target, (instrument, exchange) in _PLANNING_ROUTES.items()
    )
    quotes = tuple(
        replace(
            planning.quotes[0],
            instrument=instrument,
            exchange=exchange,
            source_ref="fixture-quote-" + target,
        )
        for target, (instrument, exchange) in _PLANNING_ROUTES.items()
    )
    if not replay:
        return replace(planning, positions=positions, instruments=instruments, quotes=quotes)
    return replace(
        planning,
        positions=positions,
        instruments=instruments,
        quotes=tuple(replace(quote, evidence_source="REPLAY_TAPE") for quote in quotes),
        evidence_source="CAUSAL_REPLAY",
    )


def _assert_same_targets(left, right):
    assert left.status == right.status == "TARGETS_READY", (
        left.status,
        left.reason,
        right.status,
        right.reason,
    )
    assert tuple(
        (item.target_id, item.target_position, item.raw_score, item.oriented_score)
        for item in left.targets
    ) == tuple(
        (item.target_id, item.target_position, item.raw_score, item.oriented_score)
        for item in right.targets
    )


def _decision_facade(broker, coordinator, batch, snapshot, target_decision):
    cohort = SimpleNamespace(cohort_id=batch.cohort_id, current_batch=lambda: batch)
    owner = object.__new__(_STRATEGY.Alpha003TargetStrategy)
    owner.broker = broker
    owner._coordinator = coordinator
    owner._account_scope = _ACCOUNT_SCOPE
    owner._strategy_scope = _STRATEGY_SCOPE
    owner._logical_run_id = coordinator.logical_run_id
    owner._last_signal_target = target_decision
    owner.last_execution_block_reason = None
    owner.p = SimpleNamespace(cohort=cohort, execution_enabled=False)
    owner.live_factors = SimpleNamespace(snapshot=lambda: snapshot)
    owner._dispatch_live_actions = lambda *_args: pytest.fail(
        "shadow grid decision must not dispatch an order"
    )
    return owner


def _new_journal_context():
    store = RegisteredSimStore(allow_writes=False, api_cls=economics._NeverCalledProvider)
    broker = bt.brokers.BtApiBroker(
        store=store,
        cash=10_000,
        validation_enabled=False,
        cash_check_enabled=False,
    )
    journal = ExecutionDecisionJournal(":memory:")
    coordinator = FactorExecutionCoordinator(
        broker,
        journal,
        account_scope=_ACCOUNT_SCOPE,
        strategy_scope=_STRATEGY_SCOPE,
        logical_run_id=_RUN_ID,
        max_order_intents_per_grid=2,
        max_order_intents_per_run=20,
    )
    return broker, journal, coordinator


def _make_order_economics(plan, batch, risk_policy):
    owner = SimpleNamespace(_risk_policy=risk_policy)
    owner._risk_policy_payload = lambda: _STRATEGY.Alpha003TargetStrategy._risk_policy_payload(
        owner
    )
    return _STRATEGY.Alpha003TargetStrategy._order_intents(owner, plan, batch)


def _run_causal_fill(action, target_decision, quote, close):
    # The first candidate bar starts at the decision bar's close, four seconds
    # before the risk projection is available.  The following bar starts only
    # after that exact decision cutoff.
    ends = tuple(close + timedelta(minutes=index) for index in range(4))
    timings = tuple(
        ReplayBarTiming(
            start=end - timedelta(minutes=1),
            end=end,
            available_at=end,
        )
        for end in ends
    )
    frame = pd.DataFrame(
        {
            "open": (100.0, 100.0, 100.0, 100.0),
            "high": (101.0, 101.0, 101.0, 101.0),
            "low": (99.0, 99.0, 99.0, 99.0),
            "close": (100.0, 100.0, 100.0, 100.0),
            "volume": (10.0, 10.0, 10.0, 10.0),
        },
        index=pd.DatetimeIndex(ends),
    )
    data = bt.feeds.PandasData(dataname=frame)
    broker = CausalReplayBroker(cash=10_000)
    broker.bind_data_timing(data, timings)
    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    cerebro.setbroker(broker)
    cerebro.adddata(data, name=action.target_id)

    class ReplayActionStrategy(bt.Strategy):
        params = (
            ("action", None),
            ("decision", None),
            ("batch", None),
            ("quote", None),
            ("execution_enabled", True),
        )

        def __init__(self):
            self._data_by_target = {action.target_id: self.datas[0]}
            self._logical_run_id = _RUN_ID
            self._strategy_scope = _STRATEGY_SCOPE
            self._last_signal_target = self.p.decision
            self._replay_quotes = (self.p.quote,)
            self._orders_by_broker_ref = {}
            self._replay_order_count = 0
            self.positions_seen = []
            self.order = None

        def _latest_replay_quote(self, instrument, exchange, *, available_by):
            return _STRATEGY.Alpha003TargetStrategy._latest_replay_quote(
                self,
                instrument,
                exchange,
                available_by=available_by,
            )

        def next(self):
            self.positions_seen.append(self.position.size)
            if len(self) == 1:
                _STRATEGY.Alpha003TargetStrategy._dispatch_replay_actions(
                    self,
                    _STRATEGY.Alpha003OrderPlan(
                        "READY",
                        None,
                        (self.p.action,),
                        self.p.batch.batch_id,
                        self.p.action.decision_available_at,
                        "replay-account",
                    ),
                    self.p.batch,
                )
                self.order = next(iter(self._orders_by_broker_ref.values()))

    cerebro.addstrategy(
        ReplayActionStrategy,
        action=action,
        decision=target_decision,
        batch=SimpleNamespace(batch_id=action.reason + "-batch"),
        quote=quote,
    )
    strategy = cerebro.run()[0]
    assert action.decision_available_at is not None
    assert action.decision_available_at > close
    assert strategy.positions_seen[:2] == [0, 0]
    assert strategy.order.status == bt.Order.Completed
    assert abs(strategy.order.executed.size) == action.quantity
    assert strategy.order.info.decision_available_at == action.decision_available_at
    assert strategy.positions_seen[2] == (
        action.quantity if action.side == "BUY" else -action.quantity
    )
    assert not broker._replay_order_cutoffs


@pytest.mark.integration
def test_real_alpha003_live_and_replay_snapshots_drive_028_economics_once(monkeypatch):
    """Real Alpha003 outputs preserve mode, direction, availability, and journal identity."""
    base = parity._minute_frames(320)
    frames = base
    from tests.test_utils.alpha101_native_harness import oracle_expected

    oracle, declared_history = oracle_expected(3, frames)
    assert declared_history == 9
    assert all(math.isfinite(value) for value in oracle[-1])
    assert len(set(oracle[-1])) > 1
    original_plan_builder = parity._live_alpha003_plan

    def negative_direction_plan(targets, **kwargs):
        plan = original_plan_builder(targets, **kwargs)
        spec = _STRATEGY.make_alpha003_factor_spec(mode=kwargs["mode"], direction=-1)
        return type(plan)(
            targets=plan.targets,
            factors={"alpha003": spec},
            calendar_id=plan.calendar_id,
            frequency=plan.frequency,
            plan_id=plan.plan_id,
            groups=plan.groups,
            warmup_min_bars=plan.warmup_min_bars,
            max_pending_slots=plan.max_pending_slots,
            max_window_bars=plan.max_window_bars,
            wait_timeout_ns=plan.wait_timeout_ns,
            max_live_bar_age_seconds=plan.max_live_bar_age_seconds,
            max_future_skew_seconds=plan.max_future_skew_seconds,
            allow_history_prewarm=plan.allow_history_prewarm,
        )

    monkeypatch.setattr(parity, "_live_alpha003_plan", negative_direction_plan)
    runs = {}
    for mode in ("native", "build"):
        live_strategy, live_cohort, _live_feeds = parity._run_live(frames, mode=mode)
        replay_strategy, replay_cohort, _replay_feeds = parity._run_live(
            frames,
            mode=mode,
            history_bars=len(frames[_TARGETS[0]]),
        )
        live_batch = live_cohort.current_batch()
        live_snapshot = live_strategy.snapshots[-1]
        replay_batch = replay_cohort.current_batch()
        replay_snapshot = replay_strategy.snapshots[-1]
        assert live_batch is not None and live_batch.status == "COMPLETE"
        assert replay_batch is not None and replay_batch.status == "COMPLETE"
        assert live_snapshot.readiness.value == "LIVE_READY"
        assert replay_snapshot.batch_complete is True
        assert live_snapshot.close_time == replay_snapshot.close_time
        assert live_snapshot.available_at == replay_snapshot.available_at
        assert live_batch.close_time == replay_batch.close_time
        assert live_batch.available_at == replay_batch.available_at

        live_block = live_snapshot.factors["alpha003"]
        replay_block = replay_snapshot.factors["alpha003"]
        assert live_block.direction == replay_block.direction == -1
        assert tuple(live_block.values) == tuple(replay_block.values) == _TARGETS
        for target in _TARGETS:
            live_value = live_block.values[target]
            replay_value = replay_block.values[target]
            assert live_value.status.value == replay_value.status.value == "OUTPUT_AVAILABLE"
            assert live_value.value == replay_value.value
            assert live_value.reason == replay_value.reason is None
            expected = oracle[-1][_TARGETS.index(target)]
            assert math.isclose(live_value.value, expected, rel_tol=1e-10, abs_tol=1e-12)

        live_input = _policy_input(live_batch, live_snapshot, execution_mode="LIVE")
        replay_input = _policy_input(replay_batch, replay_snapshot, execution_mode="REPLAY")
        live_decision = _STRATEGY.select_alpha003_targets(live_input)
        replay_decision = _STRATEGY.select_alpha003_targets(replay_input)
        _assert_same_targets(live_decision, replay_decision)
        assert live_input.eligible_grid_index == replay_input.eligible_grid_index == 320
        assert all(item.oriented_score == item.raw_score * -1.0 for item in live_decision.targets)
        normal_direction = _STRATEGY.select_alpha003_targets(
            replace(live_input, factor=replace(live_input.factor, direction=1))
        )
        assert normal_direction.status == "TARGETS_READY"
        assert {item.target_id: item.target_position for item in normal_direction.targets} == {
            item.target_id: -item.target_position for item in live_decision.targets
        }
        assert {item.target_id: item.target_position for item in live_decision.targets} == {
            item.target_id: item.target_position for item in replay_decision.targets
        }

        close = live_snapshot.close_time
        live_planning = _planning(live_decision, close=close)
        replay_planning = _planning(replay_decision, close=close, replay=True)
        live_order_plan = _STRATEGY.plan_alpha003_orders(live_planning)
        replay_order_plan = _STRATEGY.plan_alpha003_orders(replay_planning)
        assert live_order_plan.status == replay_order_plan.status == "READY"
        assert live_order_plan.actions == replay_order_plan.actions
        for action in replay_order_plan.actions:
            target = next(
                item for item in replay_decision.targets if item.target_id == action.target_id
            )
            assert action.side == ("BUY" if target.target_position == 1 else "SELL")
            assert action.decision_available_at == close + timedelta(seconds=4)

        live_keys, live_economics = _make_order_economics(
            live_order_plan, live_batch, live_planning.risk_policy
        )
        build_or_native_batch = live_batch
        runs[(mode, "live")] = (
            live_batch,
            live_snapshot,
            live_decision,
            live_planning,
            live_order_plan,
            live_keys,
            live_economics,
        )
        runs[(mode, "replay")] = (
            replay_batch,
            replay_snapshot,
            replay_decision,
            replay_planning,
            replay_order_plan,
            *_make_order_economics(replay_order_plan, replay_batch, replay_planning.risk_policy),
        )
        assert build_or_native_batch.batch_id == live_snapshot.batch_id

    native = runs[("native", "live")]
    build = runs[("build", "live")]
    _assert_same_targets(native[2], build[2])
    assert native[0].batch_id == build[0].batch_id
    assert native[0].close_time == build[0].close_time
    assert native[0].available_at == build[0].available_at
    assert native[1].factors["alpha003"].values == build[1].factors["alpha003"].values
    assert native[4].actions == build[4].actions
    assert native[5] == build[5]
    assert native[6] == build[6]
    for mode in ("native", "build"):
        live_row = runs[(mode, "live")]
        replay_row = runs[(mode, "replay")]
        assert live_row[5] == replay_row[5]
        assert tuple(
            {key: value for key, value in item.items() if key != "batch_id"} for item in live_row[6]
        ) == tuple(
            {key: value for key, value in item.items() if key != "batch_id"}
            for item in replay_row[6]
        )

    batch, snapshot, decision, planning, live_order_plan, keys, order_economics = native
    broker, journal, coordinator = _new_journal_context()
    owner = _decision_facade(broker, coordinator, batch, snapshot, decision)
    _STRATEGY.Alpha003TargetStrategy._live_grid_decision(
        owner, batch, snapshot, None, live_order_plan, planning=planning
    )
    cursor = coordinator.grid_cursor(batch.cohort_id)
    assert cursor is not None and cursor.ordinal == 1
    saved = journal.decision(cursor.decision_id)
    assert saved is not None and saved.is_noop is True
    assert saved.intent_keys == ()
    assert (
        saved.economic_payload["factor_source_sha256"] == snapshot.factors["alpha003"].source_sha256
    )
    assert len(saved.economic_payload["proposed_actions"]) == 2
    assert coordinator.run_order_count() == 0

    # Same actual batch/snapshot/economics is idempotent; an order-price change
    # under that same decision key is rejected by the durable journal.
    _STRATEGY.Alpha003TargetStrategy._live_grid_decision(
        owner, batch, snapshot, None, live_order_plan, planning=planning
    )
    assert coordinator.grid_cursor(batch.cohort_id) == cursor
    changed_action = replace(
        live_order_plan.actions[0],
        limit_price=live_order_plan.actions[0].limit_price + Decimal("0.1"),
    )
    changed_plan = replace(
        live_order_plan,
        actions=(changed_action,) + live_order_plan.actions[1:],
    )
    with pytest.raises(ExecutionDecisionJournalError, match="DECISION_CONFLICT"):
        _STRATEGY.Alpha003TargetStrategy._live_grid_decision(
            owner, batch, snapshot, None, changed_plan, planning=planning
        )

    stale_key = ExecutionDecisionKey(
        account_scope=_ACCOUNT_SCOPE,
        strategy_scope=_STRATEGY_SCOPE,
        logical_run_id="alpha003-run-restarted",
        cohort_id="alpha003-new-config-mode-epoch-generation",
        close_time=batch.close_time.isoformat().replace("+00:00", "Z"),
        decision_kind="ALPHA003_GRID",
    )
    stale_payload = {
        key: value
        for key, value in saved.economic_payload.items()
        if key != "_journal_run_order_reservation"
    }
    stale_payload.update(
        factor_mode="build",
        config_sha256="c" * 64,
        generation="connection-generation-2",
    )
    with pytest.raises(ExecutionDecisionJournalError, match="GRID_CURSOR_STALE_OR_CONFLICT"):
        journal.record_grid_decision(
            stale_key,
            stale_payload,
            epoch_id="2",
            batch_id="alpha003-new-batch",
            eligible=True,
            complete=True,
            live_ready=True,
            inputs_complete=True,
            max_order_intents_per_run=20,
            expected_run_order_intents_used=0,
            remaining_exit_intent_reserve=0,
        )
    assert journal.grid_cursor(_ACCOUNT_SCOPE, _STRATEGY_SCOPE, stale_key.cohort_id) is None

    # The real Alpha003-selected instrument's owner stays blocked after an
    # ambiguous dispatch, even when a later grid is planned from real values.
    seed_key = ExecutionDecisionKey(
        account_scope=_ACCOUNT_SCOPE,
        strategy_scope=_STRATEGY_SCOPE,
        logical_run_id="alpha003-prior-run",
        cohort_id="alpha003-prior-grid",
        close_time=(batch.close_time - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        decision_kind="ALPHA003_GRID",
    )
    seed_decision = journal.record_decision(
        seed_key,
        {"signal": "actual-alpha003-target", "intent_economics": (dict(order_economics[0]),)},
        intent_keys=(keys[0],),
    )
    unknown = journal.prepare_intent(
        seed_decision.decision_id,
        keys[0],
        dict(order_economics[0]),
        original_identity={"backtrader_order_ref": 101},
    )
    assert journal.claim_dispatch(unknown.intent_id) is not None
    journal.record_dispatch_result(
        unknown.intent_id,
        state="UNKNOWN",
        outcome_code="connection_lost_after_dispatch",
    )
    later_key = ExecutionDecisionKey(
        account_scope=_ACCOUNT_SCOPE,
        strategy_scope=_STRATEGY_SCOPE,
        logical_run_id="alpha003-run-later",
        cohort_id="alpha003-later-grid",
        close_time=(batch.close_time + timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
        decision_kind="ALPHA003_GRID",
    )
    later_decision = journal.record_grid_decision(
        later_key,
        {"signal": "actual-alpha003-target", "intent_economics": order_economics},
        intent_keys=keys,
        epoch_id="2",
        batch_id="alpha003-later-batch",
        eligible=True,
        complete=True,
        live_ready=True,
        inputs_complete=True,
        max_order_intents_per_run=20,
        expected_run_order_intents_used=0,
        remaining_exit_intent_reserve=0,
    )
    with pytest.raises(ExecutionDecisionJournalError, match="INSTRUMENT_OWNER_ACTIVE"):
        journal.prepare_intent(
            later_decision.decision.decision_id,
            keys[0],
            dict(order_economics[0]),
            original_identity={"backtrader_order_ref": 202},
        )
    owner_row = journal.active_instrument_owner(_ACCOUNT_SCOPE, keys[0].instrument)
    assert owner_row is not None and owner_row.intent_id == unknown.intent_id
    assert owner_row.state == "UNKNOWN"

    # An observed-but-unavailable quote is a typed source blocker. The same
    # actual factor decision and all other non-factor facts cannot open a hand.
    blocked_plan = _STRATEGY.plan_alpha003_orders(replace(planning, quotes=()))
    assert blocked_plan.status == "BLOCKED"
    assert blocked_plan.reason == "CURRENT_QUOTE_UNAVAILABLE"
    assert not any(
        action.action == "SUBMIT" and action.position_effect == "OPEN"
        for action in blocked_plan.actions
    )
    blocked_broker, blocked_journal, blocked_coordinator = _new_journal_context()
    blocked_owner = _decision_facade(blocked_broker, blocked_coordinator, batch, snapshot, decision)
    blocked_planning = replace(planning, quotes=())
    _STRATEGY.Alpha003TargetStrategy._live_grid_decision(
        blocked_owner,
        batch,
        snapshot,
        None,
        blocked_plan,
        planning=blocked_planning,
        proposed_plan=live_order_plan,
    )
    blocked_cursor = blocked_coordinator.grid_cursor(batch.cohort_id)
    assert blocked_cursor is not None
    blocked_saved = blocked_journal.decision(blocked_cursor.decision_id)
    assert blocked_saved is not None and blocked_saved.is_noop is True
    assert blocked_saved.intent_keys == ()
    assert blocked_saved.economic_payload["plan_status"] == "BLOCKED"
    assert blocked_saved.economic_payload["plan_reason"] == "CURRENT_QUOTE_UNAVAILABLE"
    assert all(
        action["action"] == "SUBMIT" and action["position_effect"] == "OPEN"
        for action in blocked_saved.economic_payload["proposed_actions"]
    )
    assert blocked_coordinator.run_order_count() == 0
    blocked_journal.close()

    replay_batch, _replay_snapshot, replay_decision, replay_planning, replay_plan, *_ = runs[
        ("native", "replay")
    ]
    replay_action = next(
        action
        for action in replay_plan.actions
        if action.action == "SUBMIT"
        and action.position_effect == "OPEN"
        and action.side in {"BUY", "SELL"}
    )
    replay_quote = _STRATEGY.Alpha003ReplayQuoteFact(
        instrument=replay_action.instrument,
        exchange=replay_action.exchange,
        event_time=replay_batch.close_time + timedelta(seconds=2),
        available_at=replay_batch.close_time + timedelta(seconds=3),
        bid=Decimal("100.0"),
        ask=Decimal("100.1"),
        source_ref="actual-alpha003-replay-quote-source",
        quote_id="actual-alpha003-replay-quote-1",
    )
    _run_causal_fill(replay_action, replay_decision, replay_quote, replay_batch.close_time)
    journal.close()
