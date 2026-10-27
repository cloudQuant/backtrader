"""The production fee refresh wakes only the Alpha003 engine idle path."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import MappingProxyType, SimpleNamespace
import threading

import backtrader as bt
from backtrader.research.live_cohort import LiveBarCohort

from tests.integration.test_live_factor_cohort_composition import _bar_event, _calendar
from tests.integration.test_live_factor_cohort_pending_wait import (
    _DelayedEventClient,
    _InterruptibleClock,
)
from tests.unit import test_alpha003_simnow_runner as runner_fixtures
from tests.unit import test_alpha003_simnow_strategy as strategy_fixtures
from tests.unit.stores import test_factor_execution_facts as facts_fixtures
from tests.fixtures.fake_btapi import make_store


RUNNER = runner_fixtures.RUNNER
ALPHA003 = strategy_fixtures._STRATEGY.Alpha003TargetStrategy
UTC = timezone.utc


def test_fee_pair_priority_and_snapshot_updates_wake_real_cohort_idle_once():
    now = datetime.now(UTC)
    account = {
        "Available": "100000",
        "CurrMargin": "0",
        "BrokerID": "fake-broker",
        "AccountID": "configured-account",
        "InvestorID": "fake-investor",
    }
    target_specs = (
        ("A", "rb2510", "SHFE"),
        ("B", "i2510", "DCE"),
        ("C", "cu2510", "SHFE"),
    )
    (
        api,
        store,
        facts_broker,
        journal,
        _coordinator,
        facts_targets,
        templates,
    ) = facts_fixtures._multi_target_system_under_test(
        now=now,
        target_specs=target_specs,
        account=account,
    )
    api.query_rows["instrument_commission_rate_result"] = [
        facts_fixtures._commission_row(instrument="rb2510", exchange="SHFE"),
        facts_fixtures._commission_row(instrument="i2510", exchange="DCE"),
        facts_fixtures._commission_row(instrument="cu2510", exchange="SHFE"),
    ]
    api._use_observed_query_clock = True

    first_target = facts_targets[0]
    store.registered_sim_arm(
        instrument=first_target.instrument,
        exchange=first_target.exchange,
        **templates[(first_target.instrument, first_target.exchange)],
    )
    for target in facts_targets:
        assert store.poll_tick(target.instrument) is not None

    calendar, sessions = _calendar(("A", "B", "C"), slots=2)
    first_slot, pending_slot = calendar.slots
    cohort = LiveBarCohort(
        "alpha003-fee-idle-wake",
        calendar,
        max_pending_slots=2,
        max_window_bars=4,
        wait_timeout_ns=5_000_000_000,
    )
    clock = _InterruptibleClock(pending_slot.close_time)
    direct_bars = tuple(
        MappingProxyType(
            dict(
                _bar_event(
                    slot,
                    "A",
                    index + 1,
                    10.0 + index,
                    trading_day=sessions["member-A"].trading_day,
                    session_segment=sessions["member-A"].session_segment,
                )
            )
        )
        for index, slot in enumerate((first_slot, pending_slot))
    )
    client = _DelayedEventClient(
        live={
            target_id: (
                dict(
                    _bar_event(
                        first_slot,
                        target_id,
                        1,
                        20.0 + index,
                        trading_day=sessions["member-" + target_id].trading_day,
                        session_segment=sessions["member-" + target_id].session_segment,
                    )
                ),
            )
            for index, target_id in enumerate(("B", "C"))
        }
    )
    feed_store = make_store(api=client, provider="okx", preserve_raw_bars=True)
    feeds = {
        "A": bt.feeds.BtApiFeed(
            dataname="A",
            live_bars=direct_bars,
            cohort_source_mode=True,
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            bar_watermark_ms=0,
            clock=clock,
        ),
        "B": bt.feeds.BtApiFeed(
            dataname="B",
            cohort_source_mode=True,
            store=feed_store,
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            bar_watermark_ms=0,
            clock=clock,
        ),
        "C": bt.feeds.BtApiFeed(
            dataname="C",
            cohort_source_mode=True,
            store=feed_store,
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            bar_watermark_ms=0,
            clock=clock,
        ),
    }
    cerebro = bt.Cerebro(stdstats=False, exactbars=3, preload=False, runonce=False)
    broker = bt.brokers.BackBroker()
    broker.next_without_bar = True
    cerebro.setbroker(broker)
    for target_id, feed in feeds.items():
        cerebro.adddata(feed, name=target_id)
        cohort.register_member(
            "member-" + target_id,
            feed,
            instrument=target_id,
            source_ref="fee-idle-wake-fixture",
            line_fields=("open", "high", "low", "close", "volume", "openinterest"),
            raw_fields=("open", "high", "low", "close", "volume", "openinterest"),
            numeric_fields=("open", "high", "low", "close", "volume", "openinterest"),
        )
    cohort.seal()
    cerebro.add_live_bar_cohort(cohort, clock=clock)

    loop = RUNNER.QueryRefreshLoop(
        store,
        facts_broker,
        facts_targets,
        execution_target_ids=("A", "B", "C"),
        commission_identity_by_target={
            target_id: {"account_id": "configured-account", "invest_unit_id": ""}
            for target_id in ("A", "B", "C")
        },
        commission_required_for_open=True,
        coordinator=None,
        account_scope="acct-scope",
        strategy_scope="alpha003",
        clock=SimpleNamespace(utc_now=lambda: datetime.now(UTC)),
        quote_max_age=timedelta(seconds=30),
        max_query_age=timedelta(seconds=30),
        timeout=1.0,
        overall_timeout=0.5,
        interval=0.5,
        cerebro=cerebro,
        shutdown_grace_seconds=0.1,
    )

    fee_b_entered = threading.Event()
    fee_b_release = threading.Event()
    fee_c_entered = threading.Event()
    fee_c_release = threading.Event()
    fee_calls = []
    original_registered_query = store.registered_sim_query

    def hold_fee_leaf(family, *args, **kwargs):
        if family == "instrument_commission_rate_result":
            instrument_id = kwargs.get("instrument_id")
            fee_calls.append(instrument_id)
            if instrument_id == "i2510":
                fee_b_entered.set()
                if not fee_b_release.wait(5):
                    raise AssertionError("test did not release fee B leaf")
            elif instrument_id == "cu2510":
                fee_c_entered.set()
                if not fee_c_release.wait(5):
                    raise AssertionError("test did not release fee C leaf")
        return original_registered_query(family, *args, **kwargs)

    store.registered_sim_query = hold_fee_leaf

    class CommissionIdleStrategy(bt.Strategy):
        params = (
            ("control_refresh_loop", None),
            ("facts_broker", None),
            ("facts_targets", None),
            ("candidate", None),
            ("replay_mode", False),
            ("execution_enabled", False),
        )

        def __init__(self):
            self._shutdown_requested = threading.Event()
            self._risk_policy = None
            self._target_ids = ("A", "B", "C")
            self._authorized_targets = frozenset(self._target_ids)
            self._account_scope = "acct-scope"
            self._strategy_scope = "alpha003"
            self._routes = {
                target.target_id: (target.instrument, target.exchange)
                for target in self.p.facts_targets
            }
            self._data_by_target = {
                target.target_id: target.data for target in self.p.facts_targets
            }
            self._quote_max_age_seconds = Decimal("30")
            self._max_query_age_seconds = Decimal("30")
            self.last_execution_facts = None
            self._last_execution_facts_broker = None
            self._last_execution_facts_store = None
            self.last_execution_block_reason = None
            self._last_commission_idle_notice = None
            self.live_fact_refresh_count = 0
            self.idle_updates = []
            self._last_recorded_idle_revision = 0
            self.p.control_refresh_loop.bind_strategy(self)

        @property
        def shutdown_requested(self):
            return False

        @property
        def shutdown_ready(self):
            return False

        @property
        def shutdown_blocker(self):
            return None

        def _clock_now(self):
            return datetime.now(UTC)

        def _live_facts(self, observed_at):
            self.live_fact_refresh_count += 1
            self.broker = self.p.facts_broker
            return ALPHA003._live_facts(self, observed_at)

        def next(self):
            self.p.control_refresh_loop.publish_commission_target_decision(self.p.candidate)
            # The exact same candidate is idempotent; it must not duplicate the
            # priority wake or reset round-robin selection.
            self.p.control_refresh_loop.publish_commission_target_decision(self.p.candidate)
            self.p.control_refresh_loop.start()

        def notify_idle(self):
            ALPHA003.notify_idle(self)
            notice = self._last_commission_idle_notice
            if notice is not None and notice["revision"] > self._last_recorded_idle_revision:
                self._last_recorded_idle_revision = notice["revision"]
                fees = tuple(
                    sorted(
                        (item.target_id, item.commission_fee_status)
                        for item in getattr(self.last_execution_facts, "instruments", ())
                    )
                )
                self.idle_updates.append((notice, fees, self.live_fact_refresh_count))
                if fees == (
                    ("A", "QUERY_UNAVAILABLE"),
                    ("B", "AVAILABLE"),
                    ("C", "AVAILABLE"),
                ):
                    self.cerebro.runstop()

    candidate = strategy_fixtures._STRATEGY.select_alpha003_targets(
        strategy_fixtures._policy(
            (
                strategy_fixtures._point("A", 1.0),
                strategy_fixtures._point("B", 3.0),
                strategy_fixtures._point("C", -1.0),
            ),
            required=("A", "B", "C"),
            authorized=("A", "B", "C"),
            grid=5,
        )
    )
    assert tuple(target.target_id for target in candidate.targets) == ("B", "C")
    candidate = strategy_fixtures.replace(
        candidate,
        batch_id="fee-idle-candidate-grid-1",
        available_at=datetime.now(UTC),
    )
    original_wake = cerebro.wake_live_bar_cohort
    wake_results = []

    def observe_wake():
        result = original_wake()
        wake_results.append(result)
        return result

    cerebro.wake_live_bar_cohort = observe_wake
    priority_idle = threading.Event()
    b_fee_idle = threading.Event()
    release_errors = []
    engine_errors = []
    engine_done = threading.Event()
    engine_result = []
    strategy_ref = []

    initial_receipt = loop.refresh_initial(wait_timeout=1.0)
    assert initial_receipt is not None
    assert loop.last_facts is not None
    assert loop.last_error_code is None

    def observe_strategy_idle(self):
        original_notify_idle(self)
        notice = self._last_commission_idle_notice
        if notice is not None:
            if notice["priority_changed"] and not notice["fee_snapshot_changed"]:
                priority_idle.set()
            if notice["fee_snapshot_changed"]:
                fees = {
                    item.target_id: item.commission_fee_status
                    for item in getattr(self.last_execution_facts, "instruments", ())
                }
                if fees.get("B") == "AVAILABLE" and fees.get("C") != "AVAILABLE":
                    b_fee_idle.set()

    original_notify_idle = CommissionIdleStrategy.notify_idle
    CommissionIdleStrategy.notify_idle = observe_strategy_idle
    cerebro.addstrategy(
        CommissionIdleStrategy,
        control_refresh_loop=loop,
        facts_broker=facts_broker,
        facts_targets=facts_targets,
        candidate=candidate,
    )

    def engine_run():
        try:
            engine_result.extend(cerebro.run(runonce=False, preload=False))
            if engine_result:
                strategy_ref.append(engine_result[0])
        except BaseException as error:
            engine_errors.append(error)
        finally:
            engine_done.set()

    def release_pair_in_order():
        try:
            if not fee_b_entered.wait(3):
                raise AssertionError("selected fee B was not prioritized first")
            assert loop._refresh_serialization_lock.locked()
            assert loop.last_facts is not None
            assert priority_idle.wait(3)
            assert strategy_ref == []
            assert loop.consume_commission_idle_notice() is None
            fee_b_release.set()
            if not fee_c_entered.wait(3):
                raise AssertionError("selected fee C was not prioritized after fee B")
            if not b_fee_idle.wait(3):
                raise AssertionError("fee B snapshot did not wake strategy idle")
            fee_c_release.set()
        except BaseException as error:
            release_errors.append(error)
            fee_b_release.set()
            fee_c_release.set()
            cerebro.runstop()

    release_thread = threading.Thread(target=release_pair_in_order, daemon=True)
    try:
        release_thread.start()
        # The real Cerebro cohort is driven by synthetic feed leaves; the
        # refresh side uses the real QueryRefreshLoop and fake native query leaf.
        engine_run()
        assert engine_done.is_set()
        assert engine_errors == []
        assert release_errors == []
        release_thread.join(timeout=1)
        assert release_thread.is_alive() is False
        assert loop.stop_and_join() is True
        strategy = engine_result[0]
        assert strategy_ref == [strategy]
        assert strategy.live_fact_refresh_count == 2
        assert [item[0]["priority_changed"] for item in strategy.idle_updates] == [
            True,
            False,
            False,
        ]
        assert [item[0]["fee_snapshot_changed"] for item in strategy.idle_updates] == [
            False,
            True,
            True,
        ]
        assert [item[2] for item in strategy.idle_updates] == [0, 1, 2]
        fee_snapshots = [dict(item[1]) for item in strategy.idle_updates]
        assert fee_snapshots[0] == {}
        assert fee_snapshots[1] == {
            "A": "QUERY_UNAVAILABLE",
            "B": "AVAILABLE",
            "C": "QUERY_UNAVAILABLE",
        }
        assert fee_snapshots[2] == {
            "A": "QUERY_UNAVAILABLE",
            "B": "AVAILABLE",
            "C": "AVAILABLE",
        }
        assert fee_calls == ["i2510", "cu2510"]
        assert wake_results == [True, True, True]
        assert loop._commission_priority_refresh_pending is False
        assert loop._commission_idle_revision == 3
        assert loop._commission_idle_wake_error is None
        assert loop.consume_commission_idle_notice() is None
        assert loop.joined is True
        assert len(broker.orders) == 0
        assert getattr(strategy.p, "decision_tape", None) is None

        def reject_wake():
            wake_results.append(False)
            return False

        cerebro.wake_live_bar_cohort = reject_wake
        loop.publish_commission_target_decision(
            SimpleNamespace(
                status="TARGETS_READY",
                execution_mode="LIVE",
                batch_id="fee-idle-candidate-grid-2",
                targets=(SimpleNamespace(target_id="A"), SimpleNamespace(target_id="B")),
                authorized_targets=("A", "B", "C"),
                available_at=datetime.now(UTC),
            )
        )
        assert wake_results == [True, True, True, False]
        assert loop._commission_priority_refresh_pending is True
        assert loop._commission_idle_wake_error == "LIVE_COHORT_WAKE_DECLINED"
        pending_notice = loop.consume_commission_idle_notice()
        assert pending_notice is not None
        assert pending_notice["priority_changed"] is True
        assert pending_notice["fee_snapshot_changed"] is False
        assert pending_notice["batch_id"] == "fee-idle-candidate-grid-2"
    finally:
        fee_b_release.set()
        fee_c_release.set()
        if release_thread.is_alive():
            release_thread.join(timeout=10)
        if not engine_done.is_set():
            cerebro.runstop()
        if loop._thread.ident is not None and not loop.joined:
            try:
                loop.stop_and_join()
            except Exception:
                pass
        if engine_done.is_set():
            assert not loop._thread.is_alive()
        journal.close()
        assert not release_thread.is_alive()
