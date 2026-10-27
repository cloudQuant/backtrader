"""Synthetic fee-query stall coverage for the production Alpha003 refresh loop."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import threading
import time

from tests.unit import test_alpha003_simnow_runner as runner_fixtures
from tests.unit.stores import test_factor_execution_facts as facts_fixtures


RUNNER = runner_fixtures.RUNNER
UTC = timezone.utc


def test_commission_stall_serializes_next_core_refresh_and_bounds_stop_join():
    now = datetime.now(UTC)
    account = {
        "Available": "100000",
        "CurrMargin": "0",
        "BrokerID": "fake-broker",
        "AccountID": "configured-account",
        "InvestorID": "fake-investor",
    }
    rows = facts_fixtures._query_rows(account=account)
    rows["instrument_commission_rate_result"] = [facts_fixtures._commission_row()]
    api, store, broker, journal, _coordinator, target = facts_fixtures._system_under_test(
        now=now,
        rows=rows,
    )
    facts_fixtures._refresh_all(store, target)
    facts_fixtures._arm(store)
    assert facts_fixtures._consume_quote(store) is not None

    fee_entered = threading.Event()
    fee_release = threading.Event()
    fee_calls = []
    original_registered_query = store.registered_sim_query

    def block_first_fee_query(family, *args, **kwargs):
        if family == "instrument_commission_rate_result":
            fee_calls.append(kwargs.get("deadline_monotonic"))
            if len(fee_calls) == 1:
                fee_entered.set()
                if not fee_release.wait(5):
                    raise AssertionError("test did not release the fee-query leaf")
        return original_registered_query(family, *args, **kwargs)

    store.registered_sim_query = block_first_fee_query

    loop_options = {
        "coordinator": None,
        "account_scope": "acct-scope",
        "strategy_scope": "alpha003",
        "clock": SimpleNamespace(utc_now=lambda: datetime.now(UTC)),
        "quote_max_age": timedelta(seconds=2),
        "max_query_age": timedelta(seconds=30),
        "timeout": 1.0,
        "overall_timeout": 0.5,
        "interval": 0.01,
        "cerebro": SimpleNamespace(wake_live_bar_cohort=lambda: True),
        "shutdown_grace_seconds": 0.1,
        "commission_identity_by_target": {
            target.target_id: {
                "account_id": "configured-account",
                "invest_unit_id": "",
            }
        },
        "commission_required_for_open": True,
    }

    def make_loop(**overrides):
        return RUNNER.QueryRefreshLoop(
            store,
            broker,
            (target,),
            **{**loop_options, **overrides},
        )

    loop = make_loop()
    loop_started = False
    next_refresh_thread = None
    stop_thread = None
    next_refresh_done = threading.Event()
    stop_done = threading.Event()
    next_refresh_results = []
    next_refresh_errors = []
    stop_outcomes = []
    core_families = {
        "account_result",
        "orders_result",
        "trades_result",
        "instruments_result",
        "positions_result",
        "instrument_margin_rate_result",
    }

    def core_query_count():
        return sum(1 for family, _filters in api.query_calls if family in core_families)

    def run_next_refresh():
        try:
            next_refresh_results.append(loop.refresh_once())
        except BaseException as error:
            next_refresh_errors.append(error)
        finally:
            next_refresh_done.set()

    def stop_refresh_loop():
        started_at = time.monotonic()
        try:
            loop.stop_and_join()
        except BaseException as error:
            stop_outcomes.append((getattr(error, "code", None), time.monotonic() - started_at))
        else:
            stop_outcomes.append((None, time.monotonic() - started_at))
        finally:
            stop_done.set()

    try:
        calls_before_loop = core_query_count()
        loop.start()
        loop_started = True
        assert fee_entered.wait(2)
        assert type(fee_calls[0]) is float
        assert fee_calls[0] > time.monotonic()
        assert core_query_count() > calls_before_loop

        # The core receipt remains readable while the optional fee leaf is
        # blocked; the outer refresh lock still prevents another core pass.
        with loop.strategy_fact_projection_scope() as acquired:
            assert acquired is True
            assert loop.last_receipt is not None
            assert loop.last_facts is not None
        assert loop._refresh_serialization_lock.locked()

        core_calls_at_fee_barrier = core_query_count()
        next_started = threading.Event()

        def run_waiting_refresh():
            next_started.set()
            run_next_refresh()

        next_refresh_thread = threading.Thread(target=run_waiting_refresh)
        next_refresh_thread.start()
        assert next_started.wait(1)
        assert next_refresh_done.wait(0.05) is False
        assert core_query_count() == core_calls_at_fee_barrier

        # stop_and_join has a finite caller-side wait, but the fake synchronous
        # leaf ignores cancellation until explicitly released.
        loop.overall_timeout = 0.05
        stop_thread = threading.Thread(target=stop_refresh_loop)
        stop_thread.start()
        assert stop_done.wait(2)
        stop_thread.join(timeout=1)
        assert not stop_thread.is_alive()
        assert len(stop_outcomes) == 1
        assert stop_outcomes[0][0] == "LIVE_QUERY_REFRESH_DID_NOT_JOIN"
        assert 0.8 <= stop_outcomes[0][1] < 1.8
        assert loop.joined is False
        assert loop._thread.is_alive()
        assert next_refresh_done.is_set() is False
        assert core_query_count() == core_calls_at_fee_barrier

        fee_release.set()
        next_refresh_thread.join(timeout=3)
        loop._thread.join(timeout=3)
        assert not next_refresh_thread.is_alive()
        assert not loop._thread.is_alive()
        assert next_refresh_errors == []
        assert len(next_refresh_results) == 1

        # A fresh loop has fresh stop/cancel events and can query the same
        # synthetic Store after the blocked leaf has returned.
        recovered_loop = make_loop()
        recovered_receipt = recovered_loop.refresh_once()
        assert RUNNER.QueryRefreshLoop._receipt_complete(recovered_receipt)
        assert recovered_loop.last_receipt is recovered_receipt
        assert recovered_loop.last_facts is not None
        assert core_query_count() > core_calls_at_fee_barrier
    finally:
        fee_release.set()
        if stop_thread is not None:
            stop_thread.join(timeout=2)
        if next_refresh_thread is not None:
            next_refresh_thread.join(timeout=2)
        if loop_started and loop._thread.is_alive():
            try:
                loop.stop_and_join()
            except Exception:
                pass
            loop._thread.join(timeout=2)
        journal.close()
        assert stop_thread is None or not stop_thread.is_alive()
        assert next_refresh_thread is None or not next_refresh_thread.is_alive()
        assert not loop._thread.is_alive()
