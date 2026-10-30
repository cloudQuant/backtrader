"""Runnable Alpha003 example contracts using explicit public source fixtures."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from copy import deepcopy
from collections import deque
import hashlib
import importlib.metadata
import importlib.util
import itertools
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest
import yaml

from backtrader.feeds.futures_main_contract import (
    ExchangeTradingDay,
    FuturesContractRecord,
    MainContractPolicy,
    MainContractRankingSnapshot,
    ProductKey,
    ProductRankingCoverage,
    select_main_contracts,
)
from backtrader.feeds.futures_selection_io import selection_bundle_to_dict
from backtrader.feeds.futures_sessions import (
    ExchangeSessionCalendar,
    ProductTradingDaySessions,
    PublicSourceEvidence,
    SessionWindow,
)


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "unified" / "028_alpha003_simnow_minute"
RUNNER_PATH = EXAMPLE / "run.py"
UTC = timezone.utc
CHINA = timezone(timedelta(hours=8))
CURRENT_DAY = date(2026, 10, 21)
DECISION_AT = datetime(2026, 10, 21, 0, 45, tzinfo=UTC)
PRODUCTS = tuple(ProductKey("DCE", value) for value in ("M", "Y", "A"))


def _load_runner():
    example_path = str(EXAMPLE)
    if example_path not in sys.path:
        sys.path.insert(0, example_path)
    spec = importlib.util.spec_from_file_location("alpha003_simnow_runner_under_test", RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


RUNNER = _load_runner()


@pytest.mark.parametrize(
    ("failure_kind", "expected_detail"),
    [
        ("known", "CATALOG_QUERY_CALL_FAILED"),
        ("forged", "UNEXPECTED_COLLECTION_FAILURE"),
        ("subclass", "UNEXPECTED_COLLECTION_FAILURE"),
        ("unexpected", "UNEXPECTED_COLLECTION_FAILURE"),
    ],
)
def test_ctp_query_plan_projects_only_finite_snapshot_failure_codes(
    failure_kind, expected_detail
):
    from types import SimpleNamespace

    from backtrader.feeds.futures_ctp_snapshot import CtpFuturesSnapshotError

    class DerivedSnapshotError(CtpFuturesSnapshotError):
        pass

    calls = []

    class Store:
        def registered_sim_collect_futures_snapshot(self, **kwargs):
            calls.append(kwargs)
            if failure_kind == "known":
                raise CtpFuturesSnapshotError("CATALOG_QUERY_CALL_FAILED")
            if failure_kind == "forged":
                raise CtpFuturesSnapshotError("private-provider-payload")
            if failure_kind == "subclass":
                raise DerivedSnapshotError("CATALOG_QUERY_CALL_FAILED")
            raise RuntimeError("private-provider-payload")

    with pytest.raises(RUNNER.RunnerError) as caught:
        RUNNER.build_ctp_query_market_plan(Store(), {}, clock=SimpleNamespace())

    assert caught.value.code == "CTP_FUTURES_SNAPSHOT_COLLECTION_FAILED"
    assert caught.value.detail == expected_detail
    assert "private-provider-payload" not in str(caught.value)
    if failure_kind in {"known", "forged"}:
        assert caught.value.query_diagnostics == {
            "status": "UNAVAILABLE",
            "category": "NO_QUERY_OBSERVATION",
        }
    else:
        assert caught.value.query_diagnostics == {
            "status": "UNAVAILABLE",
            "category": "ERROR_TYPE_UNTRUSTED",
        }
    assert calls == [
        {"max_collection_seconds": 300.0, "max_snapshot_age_seconds": 300.0}
    ]


def test_ctp_query_plan_drops_malformed_snapshot_diagnostics_without_leaking_values():
    from backtrader.feeds.futures_ctp_snapshot import CtpFuturesSnapshotError

    error = CtpFuturesSnapshotError("CATALOG_QUERY_CALL_FAILED")
    object.__setattr__(error, "query_observations", ("private-provider-payload",))

    class Store:
        def registered_sim_collect_futures_snapshot(self, **_kwargs):
            raise error

    with pytest.raises(RUNNER.RunnerError) as caught:
        RUNNER.build_ctp_query_market_plan(Store(), {}, clock=object())

    assert caught.value.code == "CTP_FUTURES_SNAPSHOT_COLLECTION_FAILED"
    assert caught.value.detail == "CATALOG_QUERY_CALL_FAILED"
    assert caught.value.query_diagnostics == {
        "status": "UNAVAILABLE",
        "category": "INVALID_DIAGNOSTICS",
    }
    assert "private-provider-payload" not in str(caught.value)
    assert "private-provider-payload" not in json.dumps(caught.value.query_diagnostics)


@pytest.mark.parametrize(
    "forged_changes",
    (
        {"timed_out": True},
        {"record_count": 5, "record_count_capped": True},
        {"error_code_nonzero": True},
        {"first_completion_origin": "private-origin-payload"},
        {"completion_origin": 42},
    ),
)
def test_cli_query_diagnostic_serializer_rejects_forged_payloads(forged_changes):
    stage = {
        "stage": "catalog",
        "entered": True,
        "returned": True,
        "elapsed_seconds": 0.01,
        "prior_stage_complete": None,
        "result_type_matches": True,
        "request_type_matches": True,
        "generation_matches": True,
        "request_id_positive": True,
        "timed_out": False,
        "complete": True,
        "is_last_seen": True,
        "unsupported": False,
        "late_callbacks_reported": False,
        "late_callback_count_valid": True,
        "record_count": 1,
        "record_count_capped": False,
        "submit_category": "accepted",
        "error_code_present": False,
        "error_code_valid": True,
        "error_code_nonzero": False,
        "error_message_present": False,
        "error_message_valid": True,
        "error_category": "none",
        "first_completion_origin": "success",
        "completion_origin": "success",
    }
    valid = {"status": "AVAILABLE", "stages": [stage]}
    assert RUNNER._sanitize_ctp_query_diagnostics(valid) == valid

    contradictory = dict(stage, **forged_changes)
    forged = {"status": "AVAILABLE", "stages": [contradictory]}
    serialized = RUNNER._sanitize_ctp_query_diagnostics(forged)

    assert serialized == {
        "status": "UNAVAILABLE",
        "category": "INVALID_DIAGNOSTICS",
    }
    assert "timed_out" not in json.dumps(serialized)
    assert "private-origin-payload" not in json.dumps(serialized)


def test_replay_clock_deadline_samples_and_partial_waits_do_not_skip_slots():
    from types import SimpleNamespace

    times = tuple(DECISION_AT + timedelta(minutes=index) for index in range(3))
    cohort = SimpleNamespace(batch=None)
    cohort.current_batch = lambda: cohort.batch
    clock = RUNNER.ReplayTapeClock(times, cohort=cohort)
    previous = 0
    for _ in range(100):
        sample = clock.monotonic_ns()
        assert sample > previous
        previous = sample
        clock.wait(0.01)
        assert clock.utc_now() == times[0]

    cohort.batch = SimpleNamespace(status="COMPLETE", slot_index=0)
    # Delivery itself does not move Strategy's decision availability time.
    assert clock.utc_now() == times[0]
    clock.wait(0.01)
    assert clock.utc_now() == times[1]
    for _ in range(100):
        clock.monotonic_ns()
        clock.wait(0.01)
        assert clock.utc_now() == times[1]
    for status, slot in (("WAITING", 1), ("COMPLETE", True)):
        cohort.batch = SimpleNamespace(status=status, slot_index=slot)
        clock.wait(0.01)
        assert clock.utc_now() == times[1]
    cohort.batch = SimpleNamespace(status="COMPLETE", slot_index=1)
    clock.wait(0.01)
    assert clock.utc_now() == times[2]
    cohort.batch = SimpleNamespace(status="COMPLETE", slot_index=2)
    clock.wait(0.01)
    assert clock.utc_now() == times[2]

    # Prefetched bars can publish the next complete batch without a wait.
    # Its decision must still observe that slot's planned quote availability.
    prefetched = RUNNER.ReplayTapeClock(times, cohort=cohort)
    cohort.batch = None
    prefetched.monotonic_ns()
    assert prefetched.utc_now() == times[0]
    cohort.batch = SimpleNamespace(status="COMPLETE", slot_index=0)
    assert prefetched.utc_now() == times[0]
    cohort.batch = SimpleNamespace(status="WAITING", slot_index=1)
    assert prefetched.utc_now() == times[0]
    cohort.batch = SimpleNamespace(status="COMPLETE", slot_index=1)
    for _ in range(3):
        prefetched.monotonic_ns()
        assert prefetched.utc_now() == times[1]


def _load_official_simnow_selector():
    # The production selector is a pure-Python SDK source leaf. Load that exact
    # public file directly so these fake-native tests do not depend on an
    # installed CTP package (or import its package initializers/native leaves).
    explicit_source = os.environ.get("BT_CTP_TEST_SELECTOR_SOURCE")
    if explicit_source is not None:
        selector_path = Path(explicit_source)
        if not selector_path.is_file():
            raise FileNotFoundError(
                "BT_CTP_TEST_SELECTOR_SOURCE does not name a public selector source file"
            )
    else:
        try:
            distribution = importlib.metadata.distribution("bt-api-ctp")
        except importlib.metadata.PackageNotFoundError:
            pytest.skip("optional bt-api-ctp distribution is not installed")
        selector_path = Path(
            distribution.locate_file("bt_api_ctp/ctp_env_selector.py")
        )
        if not selector_path.is_file():
            raise FileNotFoundError(
                "installed bt-api-ctp distribution has no ctp_env_selector.py source file"
            )
    module_name = "_alpha003_simnow_test_ctp_env_selector"
    spec = importlib.util.spec_from_file_location(module_name, selector_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load public bt_api_ctp ctp_env_selector.py source")
    selector = importlib.util.module_from_spec(spec)
    previous_module = sys.modules.get(module_name)
    sys.modules[module_name] = selector
    try:
        spec.loader.exec_module(selector)
    finally:
        if previous_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous_module
    return selector


def _load_public_ctp_sdk_source(relative_path, module_name, source_environment):
    """Load one public pure-Python SDK contract leaf without package init."""
    explicit_source = os.environ.get(source_environment)
    if explicit_source is not None:
        source_path = Path(explicit_source)
        if not source_path.is_file():
            raise FileNotFoundError(
                "{} does not name a public SDK source file".format(source_environment)
            )
    else:
        try:
            distribution = importlib.metadata.distribution("bt-api-ctp")
        except importlib.metadata.PackageNotFoundError:
            pytest.skip("optional bt-api-ctp distribution is not installed")
        source_path = Path(distribution.locate_file(relative_path))
        if not source_path.is_file():
            raise FileNotFoundError(
                "installed bt-api-ctp distribution has no {} source file".format(
                    relative_path
                )
            )

    spec = importlib.util.spec_from_file_location(module_name, source_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load public {} SDK source".format(relative_path))
    module = importlib.util.module_from_spec(spec)
    previous_module = sys.modules.get(module_name)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous_module
    return module


def _official_simnow_store_config(selector=None):
    if selector is None:
        selector = _load_official_simnow_selector()
    profile = "set1_group1"
    td_front, md_front = selector.official_simnow_fronts(profile)
    return {
        "td_address": td_front,
        "md_address": md_front,
        "ctp_env_profile": profile,
    }, {}


def test_runner_wall_clock_wait_is_interrupted_by_public_cerebro_wake():
    from backtrader import Cerebro
    from backtrader._cerebro.runnext import _LiveBarCohortWake

    cerebro = Cerebro()
    wake = _LiveBarCohortWake()
    # This is the same active-cohort engine state guarded by the public wake
    # API; the test avoids starting a live Store or a provider thread.
    cerebro._live_bar_cohort = object()
    cerebro._live_bar_cohort_waker = wake
    cerebro._run_active = True
    generation = wake.snapshot()
    started = threading.Event()
    result = []
    clock = RUNNER.RunnerWallClock()

    def wait_for_wake():
        started.set()
        result.append(
            clock.wait_interruptibly(
                10.0,
                lambda timeout: wake.wait(generation, timeout),
            )
        )

    waiter = threading.Thread(target=wait_for_wake)
    before = time.monotonic()
    waiter.start()
    assert started.wait(1.0)
    assert cerebro.wake_live_bar_cohort() is True
    waiter.join(1.0)

    assert not waiter.is_alive()
    assert time.monotonic() - before < 1.0
    assert result == [True]
    assert cerebro._event_stop.is_set() is False


@pytest.mark.parametrize(
    ("ready", "expected_status", "expected_blocker"),
    (
        (True, "PASS", None),
        (False, "BLOCKED", "SHUTDOWN_ORDER_TERMINAL_PENDING"),
    ),
)
def test_refresh_loop_accepts_natural_eof_only_from_strategy_shutdown_proof(
    ready, expected_status, expected_blocker
):
    from types import SimpleNamespace

    loop = RUNNER.QueryRefreshLoop(
        None,
        None,
        (),
        coordinator=None,
        account_scope="fixture-account",
        strategy_scope="fixture-strategy",
        clock=None,
        quote_max_age=timedelta(seconds=1),
        max_query_age=timedelta(seconds=1),
        timeout=1,
        overall_timeout=1,
        interval=1,
        cerebro=SimpleNamespace(),
        shutdown_grace_seconds=1,
    )
    loop.bind_strategy(
        SimpleNamespace(
            shutdown_requested=True,
            shutdown_ready=ready,
            shutdown_blocker=expected_blocker,
        )
    )

    assert loop.stop_and_join() is True
    assert loop.shutdown_status == expected_status
    assert loop.shutdown_blocker == expected_blocker


def test_refresh_loop_finishes_inflight_query_before_successful_post_join_proof():
    from types import SimpleNamespace

    loop = RUNNER.QueryRefreshLoop(
        None,
        None,
        (SimpleNamespace(target_id="DCE.fixture"),),
        coordinator=None,
        account_scope="fixture-account",
        strategy_scope="fixture-strategy",
        clock=None,
        quote_max_age=timedelta(seconds=1),
        max_query_age=timedelta(seconds=1),
        timeout=0.1,
        overall_timeout=0.2,
        interval=1,
        cerebro=SimpleNamespace(wake_live_bar_cohort=lambda: True),
        shutdown_grace_seconds=1,
    )
    loop.bind_strategy(
        SimpleNamespace(
            shutdown_requested=True,
            shutdown_ready=True,
            shutdown_blocker=None,
            request_shutdown=lambda: None,
        )
    )
    refresh_entered = threading.Event()
    finish_refresh = threading.Event()
    refresh_observations = []

    def blocked_refresh_once():
        refresh_entered.set()
        if not finish_refresh.wait(2):
            raise AssertionError("test did not release the bounded refresh")
        refresh_observations.append(loop._interrupt_refresh.is_set())
        loop.last_receipt = "complete-current-refresh"

    loop.refresh_once = blocked_refresh_once
    loop.start()
    join_results = []
    join_thread = threading.Thread(target=lambda: join_results.append(loop.stop_and_join()))
    try:
        assert refresh_entered.wait(1)
        join_thread.start()
        assert loop._stop.wait(1)
        assert not loop._interrupt_refresh.is_set()
        assert join_thread.is_alive()
    finally:
        finish_refresh.set()
        if join_thread.ident is not None:
            join_thread.join(2)

    assert not join_thread.is_alive()
    assert join_results == [True]
    assert loop.joined is True
    assert refresh_observations == [False]
    assert loop.last_receipt == "complete-current-refresh"
    assert loop.shutdown_status == "PASS"


def test_refresh_loop_stop_wins_before_reserved_query_start():
    from types import SimpleNamespace

    loop = RUNNER.QueryRefreshLoop(
        None,
        None,
        (),
        coordinator=None,
        account_scope="fixture-account",
        strategy_scope="fixture-strategy",
        clock=None,
        quote_max_age=timedelta(seconds=1),
        max_query_age=timedelta(seconds=1),
        timeout=0.1,
        overall_timeout=0.2,
        interval=1,
        cerebro=SimpleNamespace(),
        shutdown_grace_seconds=1,
    )
    reservation_entered = threading.Event()
    release_reservation = threading.Event()
    reservation_results = []
    refresh_calls = []
    reserve = loop._reserve_refresh_start

    def pause_before_reservation():
        reservation_entered.set()
        if not release_reservation.wait(2):
            raise AssertionError("test did not release the refresh-start boundary")
        result = reserve()
        reservation_results.append(result)
        return result

    loop._reserve_refresh_start = pause_before_reservation
    loop.refresh_once = lambda: refresh_calls.append("started")
    loop.start()
    stop_results = []
    stop_thread = threading.Thread(target=lambda: stop_results.append(loop.stop_and_join()))
    try:
        assert reservation_entered.wait(1)
        stop_thread.start()
        assert loop._stop.wait(1)
        assert loop._interrupt_refresh.wait(1)
        release_reservation.set()
        stop_thread.join(2)
    finally:
        release_reservation.set()
        if stop_thread.ident is not None:
            stop_thread.join(2)

    assert not stop_thread.is_alive()
    assert stop_results == [True]
    assert loop.joined is True
    assert reservation_results == [False]
    assert refresh_calls == []


def test_refresh_loop_passes_same_query_set_receipt_to_terminal_coordinator():
    """Real runner, Store, Broker, and coordinator preserve the exact receipt pair."""
    from types import SimpleNamespace

    from backtrader.stores.factor_execution_facts import FactorExecutionRefreshReceipt
    from tests.unit.stores.test_factor_execution_facts import (
        _build_source_backed_read_only_reconciliation_case,
    )

    case = _build_source_backed_read_only_reconciliation_case()
    loop = RUNNER.QueryRefreshLoop(
        case.store,
        case.broker,
        (case.target,),
        coordinator=case.coordinator,
        account_scope=case.facts.account_scope,
        strategy_scope=case.facts.strategy_scope,
        clock=SimpleNamespace(utc_now=lambda: datetime.now(UTC)),
        quote_max_age=timedelta(seconds=2),
        max_query_age=timedelta(seconds=30),
        timeout=1.0,
        overall_timeout=8.0,
        interval=0.1,
        cerebro=SimpleNamespace(),
        shutdown_grace_seconds=1.0,
    )
    terminal_pairs = []
    terminal_results = []
    original = case.coordinator.reconcile_terminal_order_observations

    def capture_terminal(facts, *, refresh_receipt=None, limit=128, offset=0):
        terminal_pairs.append((facts, refresh_receipt))
        page = original(
            facts,
            refresh_receipt=refresh_receipt,
            limit=limit,
            offset=offset,
        )
        terminal_results.append(page)
        return page

    case.coordinator.reconcile_terminal_order_observations = capture_terminal
    try:
        receipt = loop.refresh_once()
        assert type(receipt) is FactorExecutionRefreshReceipt
        assert receipt is loop.last_receipt
        assert len(terminal_pairs) == 1
        facts, paired_receipt = terminal_pairs[0]
        assert paired_receipt is receipt
        assert facts.query_set_id == receipt.query_set.query_set_id
        assert tuple(item.request_id for item in facts.query_provenance) == tuple(
            item.request_id for item in receipt.query_provenance
        )
        assert terminal_results[0].items == ()
        assert loop.last_facts.query_set_id == receipt.query_set.query_set_id
    finally:
        case.journal.close()


def test_refresh_loop_rotates_margin_queries_only_over_execution_targets(monkeypatch):
    """Margin polling is scoped while core account queries retain the full pool."""
    from types import SimpleNamespace

    from backtrader.stores import factor_execution_facts as facts_module

    targets = tuple(SimpleNamespace(target_id=target_id) for target_id in ("M", "Y", "A"))
    requests = []
    core_families = (
        "account_result",
        "orders_result",
        "trades_result",
        "instruments_result",
        "positions_result",
    )

    def capture_refresh(
        _store,
        *,
        targets,
        timeout,
        overall_timeout,
        include_core,
        margin_target_ids,
        max_queries,
        cancel_event,
        utc_now,
        instrument_products=None,
    ):
        assert callable(utc_now)
        target_ids = tuple(target.target_id for target in targets)
        margin_target_ids = tuple(margin_target_ids)
        requests.append((target_ids, include_core, margin_target_ids))
        labels = core_families + tuple(
            "instrument_margin_rate_result:" + target_id for target_id in margin_target_ids
        )
        provenance = []
        for label in labels:
            family, separator, target_id = label.partition(":")
            provenance.append(
                SimpleNamespace(
                    family=family,
                    target_id=target_id if separator else None,
                    source_owned=True,
                    query_complete=True,
                    scope_complete=not separator,
                )
            )
        return SimpleNamespace(
            blockers=(),
            pending_families=(),
            cancelled=False,
            deadline_reached=False,
            requested_families=labels,
            attempted_families=labels,
            query_provenance=tuple(provenance),
            query_set=object(),
        )

    monkeypatch.setattr(facts_module, "refresh_factor_execution_queries", capture_refresh)
    monkeypatch.setattr(
        facts_module, "project_factor_execution_facts", lambda *_args, **_kwargs: None
    )

    def make_loop(execution_target_ids):
        return RUNNER.QueryRefreshLoop(
            object(),
            object(),
            targets,
            execution_target_ids=execution_target_ids,
            coordinator=None,
            account_scope="fixture-account",
            strategy_scope="fixture-strategy",
            clock=SimpleNamespace(utc_now=lambda: datetime.now(UTC)),
            quote_max_age=timedelta(seconds=1),
            max_query_age=timedelta(seconds=1),
            timeout=1,
            overall_timeout=2,
            interval=1,
            cerebro=SimpleNamespace(),
            shutdown_grace_seconds=1,
        )

    scoped_loop = make_loop(("A", "M"))
    for _ in range(4):
        scoped_loop.refresh_once()
    assert [request[2] for request in requests] == [("M",), ("A",), ("M",), ("A",)]

    full_pool_start = len(requests)
    full_pool_loop = make_loop(None)
    for _ in range(4):
        full_pool_loop.refresh_once()
    assert [request[2] for request in requests[full_pool_start:]] == [
        ("M",),
        ("Y",),
        ("A",),
        ("M",),
    ]

    assert all(request[0] == ("M", "Y", "A") and request[1] is True for request in requests)
    call_count = len(requests)
    with pytest.raises(RUNNER.RunnerError, match="LIVE_EXECUTION_TARGETS_INVALID"):
        make_loop(("M", "outside"))
    assert len(requests) == call_count


def test_reconcile_all_fails_closed_on_blocked_coordinator_result():
    """A blocked reconciliation page is never converted into success."""
    from types import SimpleNamespace

    receipt = object()

    def reconcile(_facts, *, refresh_receipt, limit, offset):
        assert refresh_receipt is receipt
        return SimpleNamespace(
            items=(SimpleNamespace(status="BLOCKED"),),
            observation_count=1,
            offset=offset,
            next_offset=None,
            truncated=False,
        )

    with pytest.raises(RUNNER.RunnerError, match="LIVE_RECONCILIATION_BLOCKED"):
        RUNNER.QueryRefreshLoop._reconcile_all(
            reconcile,
            object(),
            {"RESOLVED", "DUPLICATE", "EXTERNAL_TERMINAL_FLAT"},
            "terminal_orders",
            refresh_receipt=receipt,
        )


def _trading_days():
    day = date(2026, 10, 1)
    through = date(2026, 12, 18)
    result = []
    while day <= through:
        # The fixture explicitly labels 20 October as a source-confirmed holiday.
        if day.weekday() < 5 and day != date(2026, 10, 20):
            result.append(day)
        day += timedelta(days=1)
    return tuple(result)


def _session_calendar(current_day=CURRENT_DAY, *, session_end=(11, 0)):
    source_ids = ("dce-day-calendar", "dce-session-hours")
    published = datetime(2026, 10, 1, tzinfo=UTC)
    sources = tuple(
        PublicSourceEvidence(
            source_id=source_id,
            source_url=f"https://fixture.invalid/{source_id}",
            version="alpha003-runner-fixture-v1",
            available_at=published,
            retrieved_at=published + timedelta(minutes=1),
            sha256=hashlib.sha256(source_id.encode("ascii")).hexdigest(),
        )
        for source_id in source_ids
    )
    trading_days = _trading_days()
    day_window_start = datetime.combine(current_day, datetime.min.time(), tzinfo=CHINA).replace(
        hour=9
    )
    day_window_end = datetime.combine(current_day, datetime.min.time(), tzinfo=CHINA).replace(
        hour=session_end[0], minute=session_end[1]
    )
    return ExchangeSessionCalendar(
        exchange_id="DCE",
        calendar_source_id=source_ids[0],
        coverage_start=trading_days[0],
        coverage_through=trading_days[-1],
        trading_days=trading_days,
        product_universe=PRODUCTS,
        product_days=tuple(
            ProductTradingDaySessions(
                product=product,
                trading_day=current_day,
                source_id=source_ids[1],
                windows=(
                    SessionWindow(
                        session_id="day-am",
                        session_date=current_day,
                        start=day_window_start,
                        end=day_window_end,
                        source_id=source_ids[1],
                    ),
                ),
            )
            for product in PRODUCTS
        ),
        sources=sources,
        complete=True,
    )


def _selection_bundle(
    *,
    current_day=CURRENT_DAY,
    decision_at=DECISION_AT,
    select_first=False,
    session_end=(11, 0),
):
    prior_day = current_day - timedelta(days=1)
    if prior_day == date(2026, 10, 20):
        prior_day -= timedelta(days=1)
    candidates = []
    coverage = []
    for product in PRODUCTS:
        prefix = product.product_id
        first_open_interest = Decimal("400" if select_first else "100")
        second_open_interest = Decimal("300" if select_first else "300")
        records = (
            FuturesContractRecord(
                product,
                f"{prefix}2611",
                "future",
                True,
                date(2026, 11, 16),
                first_open_interest,
                Decimal("200"),
            ),
            FuturesContractRecord(
                product,
                f"{prefix}2612",
                "future",
                True,
                date(2026, 12, 15),
                second_open_interest,
                Decimal("250"),
            ),
        )
        candidates.extend(records)
        ids = tuple(item.instrument_id for item in records)
        coverage.append(
            ProductRankingCoverage(
                product=product,
                candidate_count=len(records),
                expected_instrument_ids=ids,
                ranking_instrument_ids=ids,
                candidate_set_complete=True,
                ranking_values_complete=True,
                finalized=True,
                latest_available=True,
                ranking_trading_day=prior_day,
                open_interest_unit="contracts",
                volume_unit="lots",
            )
        )
    available = datetime.combine(prior_day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=9)
    catalog_available = datetime(2026, 10, 1, tzinfo=UTC)
    snapshot = MainContractRankingSnapshot(
        source_id="official-prior-day-ranking-fixture",
        snapshot_id=f"ranking-{prior_day.isoformat()}-final",
        source_sha256=hashlib.sha256(b"ranking-fixture").hexdigest(),
        available_at=available,
        retrieved_at=available + timedelta(minutes=5),
        catalog_source_id="ctp-contract-catalog-fixture",
        catalog_snapshot_id="catalog-2026-10-01",
        catalog_sha256=hashlib.sha256(b"catalog-fixture").hexdigest(),
        catalog_available_at=catalog_available,
        catalog_retrieved_at=catalog_available + timedelta(minutes=5),
        coverage=tuple(coverage),
        candidates=tuple(candidates),
    )
    calendar = _session_calendar(current_day, session_end=session_end)
    calendars = (calendar,)
    policy = MainContractPolicy(
        policy_id="runner-fixture-prior-day-oi-v1",
        minimum_trading_days_to_expiry=5,
    )
    claim = select_main_contracts(
        snapshot,
        PRODUCTS,
        (ExchangeTradingDay("DCE", current_day),),
        tuple(item.to_main_contract_calendar() for item in calendars),
        decision_at=decision_at,
        policy=policy,
    )
    bundle = selection_bundle_to_dict(
        snapshot,
        PRODUCTS,
        (ExchangeTradingDay("DCE", current_day),),
        calendars,
        decision_at=decision_at,
        policy=policy,
        selection_claim=claim,
    )
    bundle["selection_claim"]["status"] = "BLOCKED"
    bundle["selection_claim"]["products"] = []
    return bundle


def _write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return path


def _base_config(tmp_path, mode):
    config = yaml.safe_load((EXAMPLE / "config.yaml").read_text(encoding="utf-8"))
    config["mode"] = mode
    config["entry"]["tier"] = "dry" if mode == "research" else mode
    bundle_path = _write_json(tmp_path / "selection.json", _selection_bundle())
    config["selection"]["source"] = "bundle"
    config["selection"]["query_mode"] = "legacy_two_query"
    config["selection"]["bundle"] = str(bundle_path)
    config["selection"]["authorized_products"] = None
    return config


def _write_source_inputs(
    tmp_path,
    config,
    *,
    delayed_quote=False,
    current_day=CURRENT_DAY,
    decision_at=DECISION_AT,
    connection_generation=1,
    session_end=(11, 0),
):
    config_path = tmp_path / "runner.yaml"
    config["cohort"]["max_window_bars"] = 256
    config["factor"]["preheat_bars"] = 20
    config["research"]["source_timezone"] = "Asia/Shanghai"
    config["research"]["price_basis"] = "raw-close-v1"
    config["output"]["evaluate_with_fincore"] = False
    config["output"]["directory"] = str(tmp_path / "output")
    config["output"]["decision_tape_path"] = str(tmp_path / "decision-tape.jsonl")
    config["output"]["decision_tape_max_bytes"] = 50_000_000

    # Keep the tape's explicit source day aligned with the public bundle.  The
    # default arguments retain the existing single-day research/replay tests.
    selection_path = Path(config["selection"]["bundle"])
    _write_json(
        selection_path,
        _selection_bundle(
            current_day=current_day,
            decision_at=decision_at,
            session_end=session_end,
        ),
    )
    provisional = yaml.safe_dump(config, sort_keys=False)
    config_path.write_text(provisional, encoding="utf-8")
    plan = RUNNER.load_market_plan(config, config_path)
    bars = []
    quotes = []
    permutations = tuple(itertools.permutations(range(len(PRODUCTS))))
    rng = random.Random(51003)
    open_orders = [
        list(permutations[rng.randrange(len(permutations))]) for _ in plan["grid"].minutes
    ]
    volume_orders = [
        list(permutations[rng.randrange(len(permutations))]) for _ in plan["grid"].minutes
    ]
    for ordinal, minute in enumerate(plan["grid"].minutes):
        member_by_product = {member.product: member for member in minute.members}
        for product_index, target in enumerate(plan["targets"]):
            product = plan["product_by_target"][target]
            instrument = plan["routes"][product]
            member = member_by_product[product]
            start = minute.close_time - timedelta(minutes=1)
            end = minute.close_time
            # Make each target's cross-sectional rank vary across time.  A
            # larger rank step than target offset keeps the supplied random
            # permutations real, rather than accidentally making every
            # target's rank constant and the rolling correlation undefined.
            open_price = 100.0 + open_orders[ordinal][product_index] * 0.5 + product_index * 0.01
            close_price = open_price + (0.2 if ordinal % 2 else -0.2)
            row = {
                "target": target,
                "instrument": instrument,
                "exchange": product.exchange_id,
                "bucket_start": start.isoformat().replace("+00:00", "Z"),
                "bucket_end": end.isoformat().replace("+00:00", "Z"),
                "available_at": (end + timedelta(seconds=2)).isoformat().replace("+00:00", "Z"),
                "trading_day": member.trading_day.isoformat(),
                "session_segment": member.session_id,
                "timezone_id": "UTC",
                "clock_domain_id": config["cohort"]["clock_domain_id"],
                "connection_generation": f"fixture-generation-{connection_generation}",
                "bar_sequence": ordinal + 1,
                "bar_id": f"{target}:{ordinal + 1}",
                "timestamp": end.timestamp(),
                "present": True,
                "complete": True,
                "quality": "GOOD",
                "quality_flags": [],
                "open": open_price,
                "high": max(open_price, close_price) + 0.5,
                "low": min(open_price, close_price) - 0.5,
                "close": close_price,
                "volume": float(100 + volume_orders[ordinal][product_index] * 100),
                "openinterest": 0.0,
            }
            bars.append(row)
            quote_event = end + timedelta(seconds=3)
            quote_available = end + timedelta(seconds=4)
            if delayed_quote and ordinal == 0 and product_index == 0:
                quote_available = plan["grid"].minutes[1].close_time + timedelta(seconds=10)
            quotes.append(
                {
                    "target": target,
                    "instrument": instrument,
                    "exchange": product.exchange_id,
                    "event_time": quote_event.isoformat().replace("+00:00", "Z"),
                    "available_at": quote_available.isoformat().replace("+00:00", "Z"),
                    "bid": f"{close_price:.1f}",
                    "ask": f"{close_price + 0.1:.1f}",
                    "source_ref": "fixture://quote-tape/v1",
                    "quote_id": f"quote:{target}:{ordinal + 1}",
                }
            )
    tape = {
        "schema": RUNNER.MINUTE_TAPE_SCHEMA,
        "snapshot_id": "runner-minute-fixture-v1",
        "source_ref": "fixture://minute-tape/v1",
        "source_timezone": "Asia/Shanghai",
        "price_basis": "raw-close-v1",
        "bars": bars,
    }
    tape_path = _write_json(tmp_path / "minute.json", tape)
    quotes_path = _write_json(
        tmp_path / "quotes.json",
        {
            "schema": RUNNER.QUOTE_TAPE_SCHEMA,
            "snapshot_id": "runner-quote-fixture-v1",
            "source_ref": "fixture://quote-tape/v1",
            "quotes": quotes,
        },
    )
    meta_available = plan["grid"].minutes[0].close_time
    instruments = []
    for target in plan["targets"]:
        product = plan["product_by_target"][target]
        instruments.append(
            {
                "target": target,
                "instrument": plan["routes"][product],
                "exchange": product.exchange_id,
                "snapshot_id": "runner-instrument-fixture-v1",
                "available_at": meta_available.isoformat().replace("+00:00", "Z"),
                "trading_permitted": True,
                "multiplier": "10",
                "long_margin_per_hand": "1000",
                "short_margin_per_hand": "1000",
                "tick_size": "0.1",
                "lower_limit": "80",
                "upper_limit": "130",
            }
        )
    metadata_path = _write_json(
        tmp_path / "instruments.json",
        {
            "schema": RUNNER.METADATA_SCHEMA,
            "snapshot_id": "runner-instrument-fixture-v1",
            "available_at": meta_available.isoformat().replace("+00:00", "Z"),
            "instruments": instruments,
        },
    )
    config["inputs"].update(
        minute_tape=str(tape_path),
        execution_quotes=str(quotes_path),
        instrument_metadata=str(metadata_path),
    )
    first = plan["grid"].minutes[0].close_time
    last = plan["grid"].minutes[-1].close_time
    config["research"]["start"] = first.isoformat().replace("+00:00", "Z")
    config["research"]["end"] = last.isoformat().replace("+00:00", "Z")
    config["replay"].update(starting_cash=1_000_000, commission=0)
    config["risk"].update(
        policy_id="runner-fixture-risk-v1",
        max_hold_eligible_bars=12,
        # The close policy starts before the final bar so a later causal bar
        # can actually fill the close; the final close itself cannot backfill.
        preclose_grace_seconds=300,
        run_end_policy="CLOSE_ALL",
        quote_max_age_seconds=60,
        # One synthetic metadata snapshot is explicit at the first planned
        # minute; its declared simulation freshness bound spans this finite
        # fixture without rewriting its source availability timestamp.
        max_state_age_seconds=7200,
        max_notional_per_position=100_000,
        max_total_notional=300_000,
        max_margin_per_position=10_000,
        max_total_margin=30_000,
        max_loss_per_position=10_000,
        max_total_loss=20_000,
        round_trip_fee_upper_bound_per_contract="1.00",
        stop_loss_ticks=1,
        max_order_intents_per_grid=2,
        max_order_intents_per_run=100,
    )
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return config_path, config, plan, tape, quotes


def _complete_live_epoch_result(epoch_id, routes):
    resources = [
        {"resource": "query_refresh", "status": "RETURNED", "started": True, "joined": True},
        {"resource": "broker", "status": "PASS", "store_shutdown_state": "PASS"},
        {"resource": "store", "status": "CLOSED_BY_BROKER", "shutdown_state": "PASS"},
        {"resource": "journal", "status": "CLOSED"},
        {"resource": "decision_tape", "status": "CLOSED"},
    ]
    return {
        "status": "LIVE_RUN_COMPLETE",
        "epoch_id": epoch_id,
        "routes": dict(routes),
        "shutdown_status": "PASS",
        "strategy_shutdown_ready": True,
        "strategy_shutdown_blocker": None,
        "strategy_shutdown_post_join_confirmed": True,
        "strategy_shutdown_post_join_blocker": None,
        "engine_winddown_status": "STOPPED",
        "engine_winddown_reason": "runstop_requested",
        "cleanup_complete": True,
        "resource_shutdown": resources,
        "decision_tape": {"record_count": 1, "sha256": "a" * 64},
        "decision_tape_readback": {"record_count": 1, "file_id": f"epoch-{epoch_id}"},
    }


def _daily_test_inputs(tmp_path):
    config = _base_config(tmp_path, "live")
    config_path, config, first_plan, _tape, _quotes = _write_source_inputs(tmp_path, config)
    next_path = _write_json(
        tmp_path / "selection-next.json",
        _selection_bundle(
            current_day=CURRENT_DAY + timedelta(days=1),
            decision_at=DECISION_AT + timedelta(days=1),
            select_first=True,
        ),
    )
    config["selection"]["daily_bundles"] = [str(next_path)]
    config["risk"]["run_end_policy"] = "CLOSE_ALL"
    return config_path, config, first_plan, next_path


@pytest.mark.parametrize(
    (
        "selection_source",
        "unresolved_position",
        "saved_history_restart",
        "source_final_highwater_missing",
        "lineage_chain_only",
        "legacy_v1_compat",
    ),
    (
        ("bundle", False, False, False, False, False),
        ("bundle", True, False, False, False, False),
        ("ctp_query", False, False, False, False, False),
        ("bundle", False, True, False, False, False),
        ("ctp_query", False, True, False, False, False),
        ("bundle", False, False, True, False, False),
        ("ctp_query", False, True, False, True, False),
        ("ctp_query", False, True, False, True, True),
    ),
    ids=(
        "flat-two-epoch-positive",
        "nonflat-winddown-timeout",
        "same-store-query-live",
        "saved-history-real-live-restart",
        "saved-query-history-three-epoch-restart",
        "final-highwater-missing-after-cleanup",
        "saved-query-history-8bar-lineage-e1-e5",
        "saved-query-history-v1-live-tail-and-mixed-tail-refusal",
    ),
)
def test_live_two_epoch_uses_real_three_route_cerebro_and_closes_before_next_bundle(
    tmp_path,
    monkeypatch,
    selection_source,
    unresolved_position,
    saved_history_restart,
    source_final_highwater_missing,
    lineage_chain_only,
    legacy_v1_compat,
):
    """Exercise daily assembly through the real Store/Broker/Cerebro stack.

    The CTP query and completed-bar provider leaves are synthetic. Selection,
    RegisteredSimStore, BtApiBroker, facts projection, cohort delivery,
    Alpha003 Strategy, journal, refresh loop, shutdown and tape are production
    objects.
    """
    from collections import defaultdict
    from types import SimpleNamespace

    import backtrader.stores.registered_sim as registered_sim_module
    import backtrader.stores.execution_decision_journal as journal_module
    import backtrader.stores.factor_execution as factor_execution_module
    from backtrader.feeds import futures_ctp_snapshot, futures_expected_calendar
    from backtrader.feeds.ctp_factor_source import CtpFactorSourceBinding
    from backtrader.stores.btapistore import _create_ctp_wrapper_class
    from tests.unit.stores import test_factor_execution_facts as facts_fixture

    if legacy_v1_compat:
        # Known legacy gap: the pinned v1 writer predates the durable source
        # predecessor/restart lineage that the journal now requires when a
        # saved-history epoch appends source anchors. Current (v2) writer
        # restarts are covered by the other saved-history cases. Restoring a
        # v1 row-level predecessor is a separate compatibility task; xfail
        # keeps the gap visible without masking a current-writer regression.
        pytest.xfail("legacy v1 tape has no source-predecessor lineage")
    query_saved_history = selection_source == "ctp_query" and saved_history_restart

    # Keep the controlled source/session timestamps historical relative to the
    # host query collector's completion time. This exercises strict causal
    # freshness without advancing a virtual clock days into the future.
    first_day = date(2026, 10, 22)
    second_day = date(2026, 10, 23)
    first_decision = datetime(2026, 10, 21, 9, 10, tzinfo=UTC)
    second_decision = datetime(2026, 10, 22, 9, 10, tzinfo=UTC)
    synthetic_calendar_review_at = datetime(2026, 10, 21, 9, 9, tzinfo=UTC)
    if selection_source == "ctp_query":
        # Keep this historical causal fixture independent of the production
        # source-review cutoff captured on 2026-10-26.
        monkeypatch.setattr(
            futures_expected_calendar,
            "RULE_REVIEW_RETRIEVED_AT_UTC",
            synthetic_calendar_review_at,
        )
    config = _base_config(tmp_path, "live")
    session_end = (11, 59) if saved_history_restart else (10, 59)
    first_bundle = _write_json(
        tmp_path / "selection-first.json",
        _selection_bundle(
            current_day=first_day,
            decision_at=first_decision,
            select_first=False,
            session_end=session_end,
        ),
    )
    config["selection"]["bundle"] = str(first_bundle)
    config_path, config, first_plan, _tape, _quotes = _write_source_inputs(
        tmp_path,
        config,
        current_day=first_day,
        decision_at=first_decision,
        connection_generation=1,
        session_end=session_end,
    )
    second_bundle = _write_json(
        tmp_path / "selection-second.json",
        _selection_bundle(
            current_day=second_day,
            decision_at=second_decision,
            select_first=True,
            session_end=session_end,
        ),
    )
    if selection_source == "ctp_query":
        config["selection"].update(
            source="ctp_query",
            bundle=None,
            daily_bundles=[],
            # Saved-history runs request a second query epoch so the
            # controlled application stop must prove it halts before that
            # epoch's Store or plan is created.
            max_epochs=2,
            # Keep the complete three-product mapping for selection and
            # evidence, while authorizing only a strict trading subset.
            authorized_products=["DCE.M", "DCE.A"],
        )
        config["risk"].update(
            policy_id="query-two-epoch-risk-v1",
            max_hold_eligible_bars=12,
            preclose_grace_seconds=300,
            run_end_policy="CLOSE_ALL",
            quote_max_age_seconds=60,
            max_state_age_seconds=7200,
            max_notional_per_position=100_000,
            max_total_notional=300_000,
            max_margin_per_position=10_000,
            max_total_margin=30_000,
            max_loss_per_position=10_000,
            max_total_loss=20_000,
            round_trip_fee_upper_bound_per_contract="1.00",
            stop_loss_ticks=1,
            max_order_intents_per_grid=2,
            max_order_intents_per_run=100,
        )
    elif saved_history_restart:
        config["selection"]["daily_bundles"] = []
    else:
        config["selection"]["daily_bundles"] = [str(second_bundle)]
    config["live"].update(
        account_scope="alpha003-two-epoch-account",
        strategy_scope="alpha003-two-epoch-shadow",
        logical_run_id="alpha003-two-epoch-shadow-run",
        journal_path=str(tmp_path / "live-decisions.sqlite"),
        # Three product-scoped instrument queries are paced by >=1 s each.
        ready_timeout_seconds=10.0,
        refresh_timeout_seconds=1.0,
        refresh_overall_timeout_seconds=10.0,
        # One complete query refresh runs at startup and when finite EOF
        # requests winddown. Keep the immutable query-set receipt stable
        # between those two control points during this short tape fixture.
        refresh_interval_seconds=60.0,
        quote_max_age_seconds=60.0,
        # Keep the synthetic query evidence on the same controlled clock as
        # the tape, with a finite bound that spans this one-session fixture.
        query_max_age_seconds=12 * 60 * 60,
        shutdown_grace_seconds=0.05 if unresolved_position else 5.0,
        allow_writes=False,
    )
    # The strategy rejects a query freshness bound looser than the frozen risk
    # policy's state age; keep the 12h fixture bound coherent with that policy
    # while both still span this one-session fixture.
    config["risk"]["max_state_age_seconds"] = 12 * 60 * 60
    config["cohort"].update(max_live_bar_age_seconds=30.0, max_future_skew_seconds=0.0)
    config["output"]["decision_tape_path"] = str(tmp_path / "live-decisions.jsonl")
    config["output"]["decision_tape_max_bytes"] = 50_000_000
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    now = (
        datetime(2026, 10, 22, 1, 0, tzinfo=UTC)
        if selection_source == "ctp_query"
        else first_plan["grid"].minutes[0].close_time - timedelta(minutes=1)
    )
    # The prior tape must retain one full LIVE_READY window after the initial
    # warmup; those rows are the journal-anchored values restored next epoch.
    restart_cut = 2 * config["factor"]["preheat_bars"]
    restart_step = 8 if lineage_chain_only else config["factor"]["preheat_bars"] + 8
    restart_cut_2 = restart_cut + restart_step
    restart_cut_3 = restart_cut_2 + restart_step
    restart_cutoffs = {
        1: restart_cut,
        2: restart_cut_2,
        3: restart_cut_3,
    }
    if lineage_chain_only:
        restart_cut_4 = restart_cut_3 + restart_step
        restart_cut_5 = restart_cut_4 + restart_step
        restart_cutoffs.update({4: restart_cut_4, 5: restart_cut_5})
        assert restart_cut_5 < len(first_plan["grid"].minutes)
    else:
        assert restart_cut_3 < len(first_plan["grid"].minutes)
    for cutoff in restart_cutoffs.values():
        assert len(
            {
                (member.trading_day, member.session_id)
                for minute in first_plan["grid"].minutes[
                    cutoff - config["factor"]["preheat_bars"] : cutoff
                ]
                for member in minute.members
            }
        ) == 1
    trace = []
    api_clients = []
    contexts = deque()
    live_run_results = []
    query_run_attempts = {"value": 0}
    query_context_serial = {"value": 0}
    pending_query_context_options = {}
    source_highwater_reads = []
    strategy_source_highwaters = []
    source_receipts_written = []
    source_receipt_events = []
    query_refresh_events = []
    source_receipt_counts = {
        "builder_calls": 0,
        "builder_returns": 0,
        "coordinator_write_calls": 0,
        "coordinator_write_returns": 0,
        "journal_grid_calls": 0,
        "journal_source_rows": 0,
    }
    decision_tape_closed = {"value": False}
    live_run_started_at = {"value": None}

    def _safe_source_code(value):
        if (
            type(value) is str
            and 0 < len(value) <= 96
            and all(
                character in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
                for character in value
            )
        ):
            return value
        return None

    def _public_source_traceback_lines(error):
        frames = []
        tb = error.__traceback__
        root = ROOT.resolve()
        while tb is not None and len(frames) < 16:
            code = tb.tb_frame.f_code
            try:
                source_path = Path(code.co_filename).resolve()
                source_name = source_path.relative_to(root).as_posix()
            except (OSError, RuntimeError, ValueError):
                tb = tb.tb_next
                continue
            frames.append(
                {
                    "source": source_name,
                    "function": code.co_name[:96],
                    "line": tb.tb_lineno,
                }
            )
            tb = tb.tb_next
        return frames[-8:]

    def _record_source_receipt_event(stage, *, result=None, error=None):
        if len(source_receipt_events) >= 16:
            del source_receipt_events[0]
        if error is None:
            source_receipt_events.append(
                {
                    "stage": stage,
                    "outcome": "RETURNED",
                    "result_type": type(result).__name__[:96],
                }
            )
            return
        source_receipt_events.append(
            {
                "stage": stage,
                "outcome": "ERROR",
                "exception_type": type(error).__name__[:96],
                "code": _safe_source_code(getattr(error, "code", None)),
                "traceback": _public_source_traceback_lines(error),
            }
        )

    original_record_grid_decision = journal_module.ExecutionDecisionJournal.record_grid_decision

    def tracked_record_grid_decision(journal, *args, **kwargs):
        source_receipt = kwargs.get("source_receipt")
        source_receipt_counts["journal_grid_calls"] += 1
        try:
            result = original_record_grid_decision(journal, *args, **kwargs)
        except Exception as error:
            _record_source_receipt_event("journal_record_grid_decision", error=error)
            raise
        if source_receipt is not None:
            source_receipt_counts["journal_source_rows"] += 1
            if len(source_receipts_written) < 16:
                source_receipts_written.append(type(source_receipt).__name__)
        return result

    monkeypatch.setattr(
        journal_module.ExecutionDecisionJournal,
        "record_grid_decision",
        tracked_record_grid_decision,
    )

    if source_final_highwater_missing:
        original_source_highwater = journal_module.ExecutionDecisionJournal.source_highwater
        original_tape_close = RUNNER.DecisionTapeWriter.close

        def missing_source_highwater(_journal, *args, **kwargs):
            if decision_tape_closed["value"]:
                source_highwater_reads.append((args, tuple(sorted(kwargs.items()))))
                return None
            result = original_source_highwater(_journal, *args, **kwargs)
            if source_receipts_written:
                strategy_source_highwaters.append(result)
            return result

        def track_decision_tape_close(tape):
            result = original_tape_close(tape)
            decision_tape_closed["value"] = True
            return result

        monkeypatch.setattr(
            journal_module.ExecutionDecisionJournal,
            "source_highwater",
            missing_source_highwater,
        )
        monkeypatch.setattr(RUNNER.DecisionTapeWriter, "close", track_decision_tape_close)

    class CausalFixtureClock:
        """Virtual UTC follows tape availability; monotonic drives deadlines."""

        def __init__(self, start):
            self._now = start
            self._mono = 1_000_000_000
            self._lock = threading.RLock()
            self._availability = ()
            self._availability_index = 0
            self._close_by_availability = {}
            self._required_completed_close = None
            self._completed_close = None

        def utc_now(self):
            with self._lock:
                return self._now

        def monotonic_ns(self):
            with self._lock:
                self._mono = time.monotonic_ns()
                return self._mono

        def wait(self, timeout_seconds):
            del timeout_seconds
            with self._lock:
                # The fixture's virtual market clock advances only through the
                # Cerebro/feed wait path, never through background query waits.
                if saved_history_restart:
                    return
                if self._availability_index < len(self._availability):
                    self._now = max(self._now, self._availability[self._availability_index])
                    self._availability_index += 1

        def set_epoch_events(
            self, events, *, start_at=None, required_completed_close=None
        ):
            with self._lock:
                self._availability = tuple(
                    sorted(
                        {
                            (
                                datetime.fromisoformat(row["available_at"].replace("Z", "+00:00"))
                                if isinstance(row["available_at"], str)
                                else row["available_at"]
                            )
                            for rows in events.values()
                            for row in rows
                        }
                    )
                )
                self._availability_index = 0
                self._close_by_availability = {
                    row["available_at"]: row["bucket_end"]
                    for rows in events.values()
                    for row in rows
                }
                self._completed_close = None
                if saved_history_restart and start_at is not None:
                    self._required_completed_close = (
                        required_completed_close
                        if required_completed_close is not None
                        else min(
                            row["bucket_start"]
                            for rows in events.values()
                            for row in rows
                        )
                    )
                else:
                    self._required_completed_close = None
                # Startup facts are queried at the first planned bucket start.
                # A restart resumes after the last saved history receipt instead
                # of rewinding the shared virtual clock.
                self._now = (
                    start_at
                    if start_at is not None
                    else self._availability[0] - timedelta(seconds=62)
                )

        def set_utc_now(self, value):
            with self._lock:
                self._now = value

        def record_completed_batch(self, batch):
            if not saved_history_restart or batch is None or batch.status != "COMPLETE":
                return
            with self._lock:
                self._completed_close = batch.close_time

        def wait_interruptibly(self, timeout_seconds, wait_for_event):
            # Check an actual Cerebro/Store wake first. During an epoch, move
            # UTC only to the next explicit provider availability time; no
            # host time is used to release a bar.
            if wait_for_event(0.0):
                return True
            with self._lock:
                if (
                    saved_history_restart
                    and self._required_completed_close is not None
                    and (
                        self._completed_close is None
                        or self._completed_close < self._required_completed_close
                    )
                ):
                    # A preparation-budget wait is not a new market minute.
                    # Keep the current source timestamp until Strategy has
                    # consumed its complete batch, including restored history.
                    return False
                while (
                    self._availability_index < len(self._availability)
                    and self._availability[self._availability_index] <= self._now
                ):
                    self._availability_index += 1
                if self._availability_index < len(self._availability):
                    next_availability = self._availability[self._availability_index]
                    self._now = max(self._now, next_availability)
                    if saved_history_restart:
                        self._required_completed_close = self._close_by_availability[
                            next_availability
                        ]
                    self._availability_index += 1
                    return False
            return wait_for_event(min(float(timeout_seconds), 0.01))

    clock = CausalFixtureClock(now)
    monkeypatch.setattr(RUNNER, "RunnerWallClock", lambda: clock)
    current_plan = {"value": first_plan}
    plans_by_epoch = {}
    calendar_overrides_by_epoch = {}
    provider_live_closes_by_epoch = {}
    query_plans_by_snapshot_id = {}
    strategy_instances = []

    def make_context(plan, epoch_id, *, context=None, calendar_override=None):
        bar_rows = defaultdict(list)
        live_slots_by_close = None
        restart_highwater_close = None
        if saved_history_restart and epoch_id > 1 and calendar_override is not None:
            gap = calendar_override.restart_gap
            prior_cutoff = restart_cutoffs[epoch_id - 1]
            prior_plan = plans_by_epoch[epoch_id - 1]
            expected_highwater_close = prior_plan["grid"].minutes[prior_cutoff - 1].close_time
            restart_highwater_close = expected_highwater_close
            if gap is None:
                assert lineage_chain_only
                live_close_set = {
                    minute.close_time
                    for ordinal, minute in enumerate(plan["grid"].minutes, 1)
                    if prior_cutoff < ordinal <= restart_cutoffs[epoch_id]
                }
                live_slots = tuple(
                    slot
                    for slot in calendar_override.slots
                    if slot.close_time in live_close_set
                )
                assert live_slots
                first_live_slot = live_slots[0]
                assert live_slots[0].bucket_start == expected_highwater_close
                omitted_plan_closes = ()
            else:
                assert gap.journal_highwater.close_time == expected_highwater_close
                assert gap.omitted_slot_count > 0
                assert gap.omitted_slot_count == (
                    gap.first_live_original_slot_index
                    - gap.history_highwater_original_slot_index
                    - 1
                )
                assert gap.first_live_cohort_slot_index == (
                    gap.history_highwater_original_slot_index + 1
                )
                highwater_slot = calendar_override.slots[
                    gap.history_highwater_original_slot_index
                ]
                first_live_slot = calendar_override.slots[gap.first_live_cohort_slot_index]
                assert highwater_slot.slot_id == gap.journal_highwater.slot_id
                assert highwater_slot.close_time == expected_highwater_close
                assert first_live_slot.slot_id == gap.first_live_slot_id
                assert first_live_slot.bucket_start == gap.first_live_bucket_start
                assert first_live_slot.close_time == gap.first_live_close_time
                assert first_live_slot.bucket_start >= gap.startup_time_utc
                omitted_plan_closes = tuple(
                    minute.close_time
                    for ordinal, minute in enumerate(plan["grid"].minutes, 1)
                    if ordinal > prior_cutoff and minute.close_time < first_live_slot.close_time
                )
                assert len(omitted_plan_closes) == gap.omitted_slot_count
                live_slots = tuple(
                    calendar_override.slots[gap.first_live_cohort_slot_index :]
                )
            assert live_slots and live_slots[0] is first_live_slot
            live_slots_by_close = {slot.close_time: slot for slot in live_slots}
            assert len(live_slots_by_close) == len(live_slots)
        for ordinal, minute in enumerate(plan["grid"].minutes, 1):
            if saved_history_restart:
                if epoch_id == 1 and ordinal > restart_cut:
                    continue
                if epoch_id > 1 and not restart_cutoffs[epoch_id - 1] < ordinal <= restart_cutoffs[
                    epoch_id
                ]:
                    continue
                if epoch_id not in restart_cutoffs:
                    raise AssertionError("unexpected saved-history epoch")
            close_time = minute.close_time
            if live_slots_by_close is not None:
                slot = live_slots_by_close.get(close_time)
                if slot is None:
                    # A restart may omit elapsed/partial calendar slots. The
                    # synthetic provider must not invent bars for those slots.
                    continue
                assert slot.bucket_start == close_time - timedelta(minutes=1)
            member_by_product = {member.product: member for member in minute.members}
            for target_index, target in enumerate(plan["targets"]):
                product = plan["product_by_target"][target]
                instrument = plan["routes"][product]
                member = member_by_product[product]
                start_time = close_time - timedelta(minutes=1)
                # Each target gets an independently moving open rank and
                # volume rank; equal cross-sections make Alpha003's rolling
                # correlation undefined and would test only the fail-closed
                # branch instead of a real finite factor output.
                base_price = (
                    100.0
                    + (ordinal % 7) * 0.13
                    + ((ordinal * (target_index + 1)) % 5) * 0.07
                    + target_index * 0.03
                )
                bar_rows[instrument].append(
                    {
                        "instrument": instrument,
                        "symbol": instrument,
                        "exchange": product.exchange_id,
                        "bucket_start": start_time,
                        "bucket_end": close_time,
                        "available_at": (
                            close_time
                            if lineage_chain_only
                            else close_time + timedelta(seconds=2)
                        ),
                        "trading_day": member.trading_day.strftime("%Y%m%d"),
                        "session_segment": member.session_id,
                        "timezone_id": "UTC",
                        "clock_domain_id": config["cohort"]["clock_domain_id"],
                        "connection_generation": f"epoch-{epoch_id}-generation-1",
                        # A new provider generation starts its own sequence at
                        # one. History and live therefore must be validated
                        # independently by source role.
                        "bar_sequence": len(bar_rows[instrument]) + 1,
                        "bar_id": f"epoch-{epoch_id}:{target}:{ordinal}",
                        "timestamp": close_time.timestamp(),
                        "present": True,
                        "complete": True,
                        "quality": "GOOD",
                        "quality_flags": (),
                        "open": base_price,
                        "high": base_price + 0.5,
                        "low": base_price - 0.5,
                        "close": base_price + (0.2 if (ordinal + target_index) % 2 else -0.2),
                        "volume": float(
                            100 + ((ordinal * (target_index + 2) + target_index * 3) % 11) * 10
                        ),
                        "openinterest": 0.0,
                    }
                )

        if live_slots_by_close is not None:
            window_start, window_end = restart_cutoffs[epoch_id - 1], restart_cutoffs[epoch_id]
            expected_live_closes = tuple(
                minute.close_time
                for ordinal, minute in enumerate(plan["grid"].minutes, 1)
                if window_start < ordinal <= window_end
                and minute.close_time in live_slots_by_close
            )
            assert expected_live_closes
            assert expected_live_closes[0] == live_slots[0].close_time
            assert expected_live_closes[-1] == plan["grid"].minutes[window_end - 1].close_time
            assert not set(omitted_plan_closes) & set(expected_live_closes)
            assert set(bar_rows) == {
                plan["routes"][plan["product_by_target"][target]]
                for target in plan["targets"]
            }
            assert all(
                tuple(row["bucket_end"] for row in rows) == expected_live_closes
                for rows in bar_rows.values()
            )
            provider_live_closes_by_epoch[epoch_id] = expected_live_closes
        rows = context.rows if context is not None else facts_fixture._query_rows()
        routes = [
            (
                target,
                plan["routes"][plan["product_by_target"][target]],
                plan["product_by_target"][target].exchange_id,
            )
            for target in plan["targets"]
        ]
        context_day = next(iter(plan["manifest"].trading_days)).current_trading_day.strftime(
            "%Y%m%d"
        )
        if context is None or not getattr(context, "all_catalog_facts", False):
            rows["instruments_result"] = [
                {
                    "InstrumentID": instrument,
                    "ExchangeID": exchange,
                    "IsTrading": 1,
                    "VolumeMultiple": 10,
                    "PriceTick": 0.1,
                    "LowerLimitPrice": 80,
                    "UpperLimitPrice": 130,
                }
                for _target, instrument, exchange in routes
            ]
        rows["instrument_margin_rate_result"] = [
            {
                "InstrumentID": instrument,
                "ExchangeID": exchange,
                "HedgeFlag": "1",
                "LongMarginRatioByMoney": "0.1",
                "LongMarginRatioByVolume": "0",
                "ShortMarginRatioByMoney": "0.1",
                "ShortMarginRatioByVolume": "0",
            }
            for _target, instrument, exchange in routes
        ]
        if unresolved_position:
            # This row is an actual CTP-shaped remote nonflat position. The
            # local Broker remains flat and the shared facts projector must
            # keep retirement blocked; no caller-supplied "unready" flag is
            # involved.
            _target, instrument, exchange = routes[0]
            rows["positions_result"] = [
                facts_fixture._dated_position_row(
                    1,
                    trading_day=context_day,
                    InstrumentID=instrument,
                    ExchangeID=exchange,
                )
            ]
        if context is None:
            context = SimpleNamespace(
                epoch_id=epoch_id,
                trading_day=context_day,
                rows=rows,
                bars={},
                catalog_rows=(),
                quote_rows=(),
                all_catalog_facts=False,
            )
        context.epoch_id = epoch_id
        context.trading_day = context_day
        context.rows = rows
        context.bars = {instrument: deque(events) for instrument, events in bar_rows.items()}
        clock.set_epoch_events(
            bar_rows,
            start_at=(clock.utc_now() if saved_history_restart and epoch_id > 1 else None),
            required_completed_close=restart_highwater_close,
        )
        return context

    def make_query_context(
        epoch_id,
        trading_day,
        *,
        snapshot_serial=None,
        selected_contract_index=None,
        stale_seconds=0,
        catalog_order_variant=False,
        catalog_semantic_change=False,
    ):
        if snapshot_serial is None:
            snapshot_serial = epoch_id
        if selected_contract_index is None:
            selected_contract_index = (
                1 if query_saved_history or epoch_id == 1 else 0
            )
        day_text = trading_day.strftime("%Y%m%d")
        rows = facts_fixture._query_rows()
        catalog_rows = []
        quote_rows = []
        all_instrument_rows = []
        all_margin_rows = []
        for product in PRODUCTS:
            for contract_index, month in enumerate(("11", "12")):
                instrument = f"{product.product_id}{str(trading_day.year)[-2:]}{month}"
                catalog_row = {
                    "InstrumentID": instrument,
                    "ExchangeID": product.exchange_id,
                    "ProductID": product.product_id.lower(),
                    "ProductClass": "1",
                    "IsTrading": 1,
                    "ExpireDate": "20261116" if month == "11" else "20261214",
                }
                if catalog_order_variant:
                    # InstrumentName is a real native catalog field but does
                    # not change contract identity, eligibility or routing.
                    catalog_row["InstrumentName"] = "Fixture label {}".format(snapshot_serial)
                if (
                    catalog_semantic_change
                    and product == PRODUCTS[0]
                    and contract_index == 0
                ):
                    catalog_row["ExpireDate"] = "20261117"
                catalog_rows.append(catalog_row)
                selected = contract_index == selected_contract_index
                quote_rows.append(
                    {
                        "InstrumentID": instrument,
                        "ExchangeID": product.exchange_id,
                        "TradingDay": day_text,
                        "OpenInterest": (
                            2000 + snapshot_serial * 10 if selected else 1000
                        ),
                        "Volume": 1500 + snapshot_serial * 10 if selected else 1000,
                    }
                )
                all_instrument_rows.append(
                    {
                        "InstrumentID": instrument,
                        "ExchangeID": product.exchange_id,
                        "ProductID": product.product_id.lower(),
                        "ProductClass": "1",
                        "IsTrading": 1,
                        "ExpireDate": "20261116" if month == "11" else "20261214",
                        "VolumeMultiple": 10,
                        "PriceTick": 0.1,
                        "LowerLimitPrice": 80,
                        "UpperLimitPrice": 130,
                    }
                )
                all_margin_rows.append(
                    {
                        "InstrumentID": instrument,
                        "ExchangeID": product.exchange_id,
                        "HedgeFlag": "1",
                        "LongMarginRatioByMoney": "0.1",
                        "LongMarginRatioByVolume": "0",
                        "ShortMarginRatioByMoney": "0.1",
                        "ShortMarginRatioByVolume": "0",
                    }
                )
        if catalog_order_variant:
            catalog_rows.reverse()
        rows["instruments_result"] = all_instrument_rows
        rows["instrument_margin_rate_result"] = all_margin_rows
        return SimpleNamespace(
            epoch_id=epoch_id,
            trading_day=day_text,
            rows=rows,
            bars={},
            catalog_rows=tuple(catalog_rows),
            quote_rows=tuple(quote_rows),
            all_catalog_facts=True,
            connection_generation=5000 + snapshot_serial,
            snapshot_serial=snapshot_serial,
            stale_seconds=stale_seconds,
        )

    def queue_query_context(
        epoch_id,
        *,
        selected_contract_index=None,
        stale_seconds=0,
        catalog_order_variant=False,
        catalog_semantic_change=False,
    ):
        query_context_serial["value"] += 1
        contexts.append(
            make_query_context(
                epoch_id,
                first_day,
                snapshot_serial=query_context_serial["value"],
                selected_contract_index=selected_contract_index,
                stale_seconds=stale_seconds,
                catalog_order_variant=catalog_order_variant,
                catalog_semantic_change=catalog_semantic_change,
            )
        )

    import types

    ctp_env_selector = _load_official_simnow_selector()
    if selection_source == "ctp_query":
        query_contract = _load_public_ctp_sdk_source(
            "bt_api_ctp/query.py",
            "_alpha003_simnow_test_query_contract",
            "BT_CTP_TEST_QUERY_SOURCE",
        )
        instrument_contract = _load_public_ctp_sdk_source(
            "bt_api_ctp/instrument.py",
            "_alpha003_simnow_test_instrument_contract",
            "BT_CTP_TEST_INSTRUMENT_SOURCE",
        )
        ctp_query_result_type = query_contract.QueryResult
        ctp_normalize_instrument = instrument_contract.normalize_ctp_instrument
    else:
        ctp_query_result_type = None
        ctp_normalize_instrument = None

    class CtpNativeStopReceipt:
        __module__ = "bt_api_ctp.ctp.client"

        def __init__(self, connection_generation, join_required=False):
            self.connection_generation = connection_generation
            self.native_released = True
            self.join_required = join_required
            self.join_completed = True
            self.thread_alive = False
            self.timed_out = False

        @property
        def complete(self):
            return (
                self.native_released is True
                and (self.join_required is False or self.join_completed is True)
                and self.thread_alive is False
                and self.timed_out is False
            )

    sdk_instances = {"md": [], "trader": []}

    class FakeMdClient:
        def __init__(self, **_kwargs):
            api = api_clients[-1]
            self._connection_generation = int(
                getattr(api.context, "connection_generation", api.context.epoch_id)
            )
            self.start_calls = []
            self.stop_calls = 0
            self.stop_receipts = []
            self.on_tick = None
            self.on_tick_with_generation = None
            self.on_disconnect = None
            self.on_disconnect_with_generation = None
            self.on_error = None
            sdk_instances["md"].append(self)

        @property
        def connection_generation(self):
            return self._connection_generation

        def start(self, *, block, join_observer):
            assert block is False
            assert join_observer is False
            self.start_calls.append({"block": block, "join_observer": join_observer})

        @staticmethod
        def wait_ready(timeout=20):
            del timeout
            return True

        @staticmethod
        def subscribe(_instruments):
            return None

        def stop(self):
            self.stop_calls += 1

        def stop_and_wait(self, timeout=2.0):
            assert 0.0 <= timeout <= 2.0
            receipt = CtpNativeStopReceipt(self.connection_generation)
            self.stop_receipts.append(receipt)
            return receipt

    class FakeTraderClient(facts_fixture._QueryClient):
        def __init__(self, **_kwargs):
            super().__init__()
            api = api_clients[-1]
            self._api = api
            context = api.context
            self._account_fingerprint = "alpha003-two-epoch-account"
            self._trading_day = context.trading_day
            self._connection_generation = int(
                getattr(context, "connection_generation", context.epoch_id)
            )
            self._front_id = 100 + context.epoch_id
            self._session_id = 10 + context.epoch_id
            self.is_ready = True
            self.is_trading_ready = False
            self.is_read_only_ready = True
            self._gate_state.update(
                connection_generation=self._connection_generation,
                trading_day=self._trading_day,
            )
            self.on_login = None
            self.on_order = None
            self.on_trade = None
            self.on_error = None
            self.start_calls = []
            self.stop_calls = 0
            self.stop_receipts = []
            self._query_leaf = api._query_leaf
            self._query_leaf.trader_client = self
            for name in (
                "query_account_result",
                "query_positions_result",
                "query_orders_result",
                "query_trades_result",
                "query_instruments_result",
                "query_instrument_margin_rate_result",
            ):
                setattr(self, name, getattr(self._query_leaf, name))
            sdk_instances["trader"].append(self)

        def start(self, *, block, join_observer):
            assert block is False
            assert join_observer is False
            self.start_calls.append({"block": block, "join_observer": join_observer})

        @staticmethod
        def wait_ready(timeout=20):
            del timeout
            return True

        def get_session_state(self):
            return {
                "connected": self._api._connected,
                "ready": self.is_ready,
                "read_only_ready": self.is_read_only_ready,
                "trading_ready": self.is_trading_ready,
                "account_fingerprint": self._account_fingerprint,
                "connection_generation": self._connection_generation,
                "trading_day": self._trading_day,
            }

        def stop(self):
            self.stop_calls += 1

        def stop_and_wait(self, timeout=2.0):
            assert 0.0 <= timeout <= 2.0
            receipt = CtpNativeStopReceipt(self._connection_generation)
            self.stop_receipts.append(receipt)
            return receipt

    package = types.ModuleType("bt_api_ctp")
    package.__path__ = []
    monkeypatch.setattr(package, "ctp_env_selector", ctp_env_selector, raising=False)
    ctp_package = types.ModuleType("bt_api_ctp.ctp")
    ctp_package.__path__ = []
    client_module = types.ModuleType("bt_api_ctp.ctp.client")
    client_module.MdClient = FakeMdClient
    client_module.TraderClient = FakeTraderClient
    client_module._MdSpi = type("_MdSpi", (), {})
    client_module._TraderSpi = type("_TraderSpi", (), {})
    client_module.CtpNativeStopReceipt = CtpNativeStopReceipt
    package.ctp = ctp_package
    ctp_package.client = client_module
    query_module = types.ModuleType("bt_api_ctp.query")
    query_module.__file__ = (
        query_contract.__file__ if selection_source == "ctp_query" else "<synthetic-query>"
    )
    query_module.QueryResult = ctp_query_result_type
    instrument_module = types.ModuleType("bt_api_ctp.instrument")
    instrument_module.__file__ = (
        instrument_contract.__file__
        if selection_source == "ctp_query"
        else "<synthetic-instrument>"
    )
    instrument_module.normalize_ctp_instrument = ctp_normalize_instrument
    package.query = query_module
    package.instrument = instrument_module
    md_api_module = types.ModuleType("bt_api_ctp.ctp.ctp_md_api")
    md_api_module.CThostFtdcMdSpi = type("CThostFtdcMdSpi", (), {})
    structs_module = types.ModuleType("bt_api_ctp.ctp.ctp_structs_order")
    structs_module.CThostFtdcInputOrderActionField = type(
        "CThostFtdcInputOrderActionField", (), {}
    )
    structs_module.CThostFtdcInputOrderField = type("CThostFtdcInputOrderField", (), {})
    trader_api_module = types.ModuleType("bt_api_ctp.ctp.ctp_trader_api")
    trader_api_module.CThostFtdcTraderSpi = type("CThostFtdcTraderSpi", (), {})
    for module_name, module in (
        ("bt_api_ctp", package),
        ("bt_api_ctp.ctp_env_selector", ctp_env_selector),
        ("bt_api_ctp.query", query_module),
        ("bt_api_ctp.instrument", instrument_module),
        ("bt_api_ctp.ctp", ctp_package),
        ("bt_api_ctp.ctp.client", client_module),
        ("bt_api_ctp.ctp.ctp_md_api", md_api_module),
        ("bt_api_ctp.ctp.ctp_structs_order", structs_module),
        ("bt_api_ctp.ctp.ctp_trader_api", trader_api_module),
    ):
        monkeypatch.setitem(sys.modules, module_name, module)

    production_ctp_wrapper = _create_ctp_wrapper_class()

    class FakeCtpWrapper(production_ctp_wrapper):
        def __init__(self, *args, **kwargs):
            context = contexts.popleft()
            if context.epoch_id > 1 and not saved_history_restart:
                clock.set_utc_now(datetime(2026, 10, 23, 1, 0, tzinfo=UTC))
            super().__init__(*args, **kwargs)
            self.context = context
            self._selection_request_id = 0
            self._query_leaf = facts_fixture._ProviderLeaves(
                query_rows=context.rows,
                query_time=clock.utc_now(),
            )
            self.closed = False
            self._first_bar_logged = False
            api_clients.append(self)
            trace.append(("api_created", context.epoch_id))
            if selection_source == "ctp_query":
                trace.append(
                    (
                        "api_created_snapshot",
                        context.snapshot_serial,
                        context.connection_generation,
                    )
                )

        def connect(self):
            super().connect()
            trace.append(("api_connected", self.context.epoch_id))
            if selection_source == "ctp_query":
                trace.append(
                    (
                        "api_connected_snapshot",
                        self.context.snapshot_serial,
                        self.context.connection_generation,
                    )
                )

        def disconnect(self):
            super().disconnect()
            self.closed = True
            trace.append(("api_closed", self.context.epoch_id))
            if selection_source == "ctp_query":
                trace.append(
                    (
                        "api_closed_snapshot",
                        self.context.snapshot_serial,
                        self.context.connection_generation,
                    )
                )

        def get_session_state(self):
            client = self.trader_client
            return {
                "connected": self._connected,
                "read_only_ready": client.is_read_only_ready,
                "connection_generation": client._connection_generation,
                "trading_day": client._trading_day,
            }

        def _selection_query_result(self, request_type, records):
            self._selection_request_id += 1
            self._query_leaf.query_time = clock.utc_now() - timedelta(
                seconds=self.context.stale_seconds
            )
            result = self._query_leaf._query(request_type, list(records))
            return ctp_query_result_type(
                request_type=result.request_type,
                request_id=result.request_id,
                connection_generation=result.connection_generation,
                account_fingerprint=result.account_fingerprint,
                started_at_utc=result.started_at_utc,
                completed_at_utc=result.completed_at_utc,
                is_last_seen=result.is_last_seen,
                error_code=result.error_code,
                error_message=result.error_message,
                timed_out=result.timed_out,
                complete=result.complete,
                records=result.records,
                late_callback_count=result.late_callback_count,
                unsupported=result.unsupported,
                submit_code=result.submit_code,
            )

        def query_instruments_result(
            self,
            instrument_id="",
            exchange_id="",
            timeout=5.0,
            *,
            product_id="",
            max_duration=None,
            deadline_monotonic=None,
            **filters,
        ):
            if max_duration is not None:
                assert instrument_id == exchange_id == product_id == ""
                assert not filters
                trace.append(("selection_catalog_query", self.context.epoch_id))
                if selection_source == "ctp_query":
                    trace.append(
                        ("selection_catalog_query_snapshot", self.context.snapshot_serial)
                    )
                return self._selection_query_result("instruments", self.context.catalog_rows)
            return super().query_instruments_result(
                timeout=timeout,
                instrument_id=instrument_id,
                exchange_id=exchange_id,
                product_id=product_id,
                deadline_monotonic=deadline_monotonic,
                **filters,
            )

        def query_depth_market_data_result(
            self,
            instrument_id="",
            exchange_id="",
            timeout=5.0,
            *,
            deadline_monotonic=None,
        ):
            assert instrument_id == exchange_id == ""
            trace.append(("selection_depth_query", self.context.epoch_id))
            if selection_source == "ctp_query":
                trace.append(
                    ("selection_depth_query_snapshot", self.context.snapshot_serial)
                )
            return self._selection_query_result("depth_market_data", self.context.quote_rows)

        def get_balance(self):
            return {"cash": 1_000_000.0, "value": 1_000_000.0}

        def get_positions(self):
            return []

        def fetch_open_orders(self):
            return []

        def get_open_orders(self):
            return []

        def subscribe(self, _symbols):
            return None

        def poll_bar(self, instrument):
            queue = self.context.bars.get(instrument)
            if not queue:
                return None
            event = queue[0]
            if event["available_at"] > clock.utc_now():
                return None
            row = queue.popleft()
            if saved_history_restart and not self._first_bar_logged:
                self._first_bar_logged = True
                trace.append(
                    (
                        "first_provider_bar",
                        self.context.epoch_id,
                        row["bar_sequence"],
                        row["bucket_end"],
                    )
                )
            return row

    original_factory = registered_sim_module._make_api_factory
    monkeypatch.setattr(
        registered_sim_module,
        "_make_api_factory",
        lambda allow_writes, history_limit, terminal_limit, api_cls: original_factory(
            allow_writes, history_limit, terminal_limit, FakeCtpWrapper
        ),
    )
    def fake_live_store_config(_config):
        store_config, api_kwargs = _official_simnow_store_config(ctp_env_selector)
        store_config.update(
            broker_id="alpha003-synthetic-broker",
            investor_id="alpha003-synthetic-investor",
            password="alpha003-synthetic-password",
        )
        return store_config, api_kwargs

    monkeypatch.setattr(RUNNER, "_live_env_config", fake_live_store_config)
    original_store_wait_ready = registered_sim_module.RegisteredSimStore.registered_sim_wait_ready
    original_store_login_facts = registered_sim_module.RegisteredSimStore.registered_sim_login_facts

    def tracked_store_wait_ready(store, *args, **kwargs):
        result = original_store_wait_ready(store, *args, **kwargs)
        if selection_source == "ctp_query":
            trace.append(("store_ready_snapshot", api_clients[-1].context.snapshot_serial))
        return result

    def tracked_store_login_facts(store, *args, **kwargs):
        result = original_store_login_facts(store, *args, **kwargs)
        if selection_source == "ctp_query":
            trace.append(("store_login_facts_snapshot", api_clients[-1].context.snapshot_serial))
        return result

    monkeypatch.setattr(
        registered_sim_module.RegisteredSimStore,
        "registered_sim_wait_ready",
        tracked_store_wait_ready,
    )
    monkeypatch.setattr(
        registered_sim_module.RegisteredSimStore,
        "registered_sim_login_facts",
        tracked_store_login_facts,
    )
    original_store_getdata = registered_sim_module.RegisteredSimStore.getdata
    factor_source_bindings = []

    def tracked_store_getdata(store, *args, **kwargs):
        binding = kwargs.get("ctp_factor_source_binding")
        if binding is not None:
            factor_source_bindings.append((store._api, binding))
        return original_store_getdata(store, *args, **kwargs)

    monkeypatch.setattr(
        registered_sim_module.RegisteredSimStore,
        "getdata",
        tracked_store_getdata,
    )
    original_refresh_initial = RUNNER.QueryRefreshLoop.refresh_initial

    original_refresh_once = RUNNER.QueryRefreshLoop.refresh_once

    def tracked_refresh_once(refresh_loop, *args, **kwargs):
        try:
            result = original_refresh_once(refresh_loop, *args, **kwargs)
        except Exception as error:
            if lineage_chain_only:
                query_refresh_events.append(
                    {
                        "epoch_id": config["cohort"]["epoch_id"],
                        "outcome": "ERROR",
                        "error_code": _safe_source_code(
                            getattr(error, "code", None)
                        ),
                        "last_error_code": _safe_source_code(
                            getattr(refresh_loop, "last_error_code", None)
                        ),
                        "reconciliation_blockers": tuple(
                            getattr(refresh_loop, "last_reconciliation_blockers", ())[:8]
                        ),
                    }
                )
            raise
        if lineage_chain_only:
            receipt = result
            query_set = getattr(receipt, "query_set", None)
            provenance = tuple(getattr(receipt, "query_provenance", ()))
            core_families = (
                "account_result",
                "orders_result",
                "trades_result",
                "instruments_result",
                "positions_result",
            )
            core_facts = tuple(
                fact
                for fact in provenance
                if getattr(fact, "family", None) in core_families
                and getattr(fact, "target_id", None) is None
            )
            request_ids = tuple(getattr(fact, "request_id", None) for fact in core_facts)
            generations = tuple(
                getattr(fact, "connection_generation", None) for fact in core_facts
            )
            accounts = tuple(
                getattr(fact, "account_fingerprint", None) for fact in core_facts
            )
            trading_days = tuple(getattr(fact, "trading_day", None) for fact in core_facts)
            started_values = tuple(getattr(fact, "started_at", None) for fact in core_facts)
            completed_values = tuple(getattr(fact, "completed_at", None) for fact in core_facts)
            completed_at = getattr(receipt, "completed_at", None)
            query_refresh_events.append(
                {
                    "epoch_id": config["cohort"]["epoch_id"],
                    "outcome": "RETURNED",
                    "last_error_code": _safe_source_code(
                        getattr(refresh_loop, "last_error_code", None)
                    ),
                    "requested": tuple(getattr(receipt, "requested_families", ())[:8]),
                    "attempted": tuple(getattr(receipt, "attempted_families", ())[:8]),
                    "pending": tuple(getattr(receipt, "pending_families", ())[:8]),
                    "receipt_blockers": tuple(getattr(receipt, "blockers", ())[:8]),
                    "query_set_available": query_set is not None,
                    "query_set_id_present": bool(
                        getattr(query_set, "query_set_id", None)
                    ),
                    "query_provenance": tuple(
                        {
                            "family": getattr(fact, "family", None),
                            "target_id": getattr(fact, "target_id", None),
                            "source_owned": getattr(fact, "source_owned", None),
                            "query_complete": getattr(fact, "query_complete", None),
                            "scope_complete": getattr(fact, "scope_complete", None),
                            "request_id_present": type(
                                getattr(fact, "request_id", None)
                            ) is int,
                            "generation_present": type(
                                getattr(fact, "connection_generation", None)
                            ) is int,
                            "started_present": getattr(fact, "started_at", None) is not None,
                            "completed_present": getattr(fact, "completed_at", None)
                            is not None,
                        }
                        for fact in getattr(receipt, "query_provenance", ())[:8]
                    ),
                    "query_set_checks": {
                        "core_order": tuple(
                            getattr(receipt, "attempted_families", ())[: len(core_families)]
                        )
                        == core_families,
                        "core_count": len(core_facts) == len(core_families),
                        "request_ids_positive_unique": (
                            len(request_ids) == len(core_families)
                            and all(type(value) is int and value > 0 for value in request_ids)
                            and len(set(request_ids)) == len(core_families)
                        ),
                        "generations_consistent": len(set(generations)) == 1,
                        "accounts_consistent": len(set(accounts)) == 1,
                        "trading_days_consistent": len(set(trading_days)) == 1,
                        "source_proofs_complete": all(
                            getattr(fact, "source_owned", None) is True
                            and getattr(fact, "query_complete", None) is True
                            and getattr(fact, "scope_complete", None) is True
                            for fact in core_facts
                        ),
                        "times_ordered_and_within_receipt": (
                            completed_at is not None
                            and len(started_values) == len(core_families)
                            and len(completed_values) == len(core_families)
                            and all(
                                started is not None
                                and completed is not None
                                and started <= completed <= completed_at
                                for started, completed in zip(
                                    started_values, completed_values
                                )
                            )
                        ),
                    },
                    "reconciliation_blockers": tuple(
                        getattr(refresh_loop, "last_reconciliation_blockers", ())[:8]
                    ),
                }
            )
            if len(query_refresh_events) > 16:
                del query_refresh_events[:-16]
        return result

    monkeypatch.setattr(RUNNER.QueryRefreshLoop, "refresh_once", tracked_refresh_once)

    def tracked_refresh_initial(refresh_loop, *args, **kwargs):
        if lineage_chain_only:
            # Cohort assembly positions the virtual source clock at the first
            # complete slot. Bind synthetic provider query completion to that
            # same startup instant so the production query-set causality check
            # sees a completed source read rather than a pre-assembly clock.
            api_clients[-1]._query_leaf.query_time = clock.utc_now()
        result = original_refresh_initial(refresh_loop, *args, **kwargs)
        if saved_history_restart:
            trace.append(("initial_refresh_complete", config["cohort"]["epoch_id"]))
        return result

    monkeypatch.setattr(RUNNER.QueryRefreshLoop, "refresh_initial", tracked_refresh_initial)
    if selection_source == "ctp_query":
        monkeypatch.setattr(futures_ctp_snapshot, "_now_utc", clock.utc_now)
        if not query_saved_history:
            contexts.append(make_query_context(1, first_day))
            contexts.append(make_query_context(2, second_day))

    original_load = RUNNER.load_market_plan

    def tracked_load(*args, bundle_path=None, **kwargs):
        if selection_source == "ctp_query":
            raise AssertionError("query selection must not open a saved bundle")
        if bundle_path is not None:
            assert api_clients and api_clients[0].closed is True, trace
            trace.append(("second_bundle_loaded", Path(bundle_path).name))
        plan = original_load(*args, bundle_path=bundle_path, **kwargs)
        current_plan["value"] = plan
        if bundle_path is not None:
            contexts.append(make_context(plan, len(live_run_results) + 1))
        return plan

    monkeypatch.setattr(RUNNER, "load_market_plan", tracked_load)
    if selection_source == "ctp_query":
        original_query_plan = RUNNER.build_ctp_query_market_plan

        def tracked_query_plan(*args, **kwargs):
            plan = original_query_plan(*args, **kwargs)
            for calendar in plan["session_calendars"].values():
                source = calendar.source_index[calendar.calendar_source_id]
                assert source.available_at == synthetic_calendar_review_at
                assert source.retrieved_at == synthetic_calendar_review_at
            current_plan["value"] = plan
            query_plans_by_snapshot_id[plan["source_snapshot_id"]] = plan
            trace.append(("query_plan_ready", plan["source_snapshot_id"]))
            trace.append(
                (
                    "query_plan_ready_epoch",
                    config["cohort"]["epoch_id"],
                    plan["source_snapshot_id"],
                )
            )
            trace.append(
                (
                    "query_plan_ready_snapshot",
                    plan["source_snapshot_id"],
                    api_clients[-1].context.snapshot_serial,
                )
            )
            return plan

        monkeypatch.setattr(RUNNER, "build_ctp_query_market_plan", tracked_query_plan)
    original_make_cohort = RUNNER._make_cohort

    def tracked_make_cohort(epoch_config, grid, *, begin_at=None, **kwargs):
        plan = current_plan["value"]
        assert grid is plan["grid"]
        epoch_id = epoch_config["cohort"]["epoch_id"]
        plans_by_epoch[epoch_id] = plan
        calendar_override = kwargs.get("calendar_override")
        calendar_overrides_by_epoch[epoch_id] = calendar_override
        if selection_source == "ctp_query":
            context = api_clients[-1].context
            assert context.all_catalog_facts is True
            make_context(
                plan,
                epoch_id,
                context=context,
                calendar_override=calendar_override,
            )
        else:
            make_context(
                plan,
                epoch_id,
                context=api_clients[-1].context,
                calendar_override=calendar_override,
            )
        trace.append(("cohort_assembled", epoch_id))
        return original_make_cohort(epoch_config, grid, begin_at=begin_at, **kwargs)

    monkeypatch.setattr(RUNNER, "_make_cohort", tracked_make_cohort)
    original_load_history = RUNNER._load_saved_live_history

    def tracked_load_history(epoch_config, *args, **kwargs):
        if epoch_config["inputs"].get("history_decision_tape") is not None:
            evidence = kwargs.get("selection_evidence")
            trace.append(
                (
                    "history_load",
                    epoch_config["cohort"]["epoch_id"],
                    evidence.get("source_snapshot_id") if isinstance(evidence, dict) else None,
                )
            )
        return original_load_history(epoch_config, *args, **kwargs)

    monkeypatch.setattr(RUNNER, "_load_saved_live_history", tracked_load_history)
    original_run_live = RUNNER.run_live

    def _source_receipt_failure_note(error):
        continuity = getattr(error, "source_continuity", None)
        continuity_projection = None
        if isinstance(continuity, dict):
            continuity_projection = {
                "status": continuity.get("status"),
                "available": continuity.get("available"),
                "record_count": continuity.get("record_count"),
                "failure_count": continuity.get("failure_count"),
                "first_error": _safe_source_code(continuity.get("first_error")),
                "final_highwater_matches_tape": continuity.get(
                    "final_highwater_matches_tape"
                ),
            }
        projection = {
            "exception_type": type(error).__name__[:96],
            "code": _safe_source_code(getattr(error, "code", None)),
            "source_continuity": continuity_projection,
            "source_receipt_counts": dict(source_receipt_counts),
            "events": source_receipt_events[-8:],
            "query_refresh_events": query_refresh_events[-8:],
        }
        return "bounded source-receipt diagnostic " + json.dumps(
            projection, sort_keys=True, separators=(",", ":")
        )

    def tracked_run_live(epoch_config, *args, **kwargs):
        if lineage_chain_only:
            live_run_started_at["value"] = time.monotonic()
        try:
            result = original_run_live(epoch_config, *args, **kwargs)
        except Exception as error:
            note = _source_receipt_failure_note(error)
            add_note = getattr(error, "add_note", None)
            if callable(add_note):
                add_note(note)
            raise
        live_run_results.append(result)
        trace.append(("run_live_returned", epoch_config["cohort"]["epoch_id"]))
        return result

    monkeypatch.setattr(RUNNER, "run_live", tracked_run_live)

    def run_saved_history_epoch():
        if not query_saved_history:
            if selection_source != "ctp_query":
                contexts.append(make_context(first_plan, config["cohort"]["epoch_id"]))
            return RUNNER.run_live(
                config,
                config_path,
                first_plan,
                "native",
                1,
                decision=SimpleNamespace(effective_tier="live"),
                allow_write_flag=False,
            )
        query_run_attempts["value"] += 1
        options = dict(pending_query_context_options)
        pending_query_context_options.clear()
        if query_run_attempts["value"] > 1 and not lineage_chain_only:
            # Rebuild each fresh query plan at a later decision time while
            # staying inside the next-bar boundary of the shared live grid.
            clock.set_utc_now(clock.utc_now() + timedelta(seconds=1))
        queue_query_context(config["cohort"]["epoch_id"], **options)
        previous_success_count = len(live_run_results)
        previous_api_count = len(api_clients)
        previous_trace_count = len(trace)
        sequence = RUNNER.run_live_epochs(
            config,
            config_path,
            None,
            "native",
            1,
            decision=SimpleNamespace(effective_tier="live"),
            allow_write_flag=False,
        )
        epoch_id = config["cohort"]["epoch_id"]
        assert sequence["status"] == "LIVE_EPOCH_SEQUENCE_STOPPED"
        assert sequence["stop_reason"] == "controlled_application_stop"
        assert sequence["epoch_count"] == 1
        assert sequence["query_epoch_attempts"] == [epoch_id]
        assert sequence["assembly_attempts"] == [epoch_id]
        assert sequence["next_epoch_loaded"] is False
        assert sequence["cleanup_complete"] is True
        stopped_epoch = sequence["epochs"][0]
        assert stopped_epoch["epoch_id"] == epoch_id
        assert stopped_epoch["status"] == "LIVE_RUN_COMPLETE"
        assert stopped_epoch["retirement_proven"] is False
        assert stopped_epoch["shutdown_path"] == "controlled_application_stop"
        assert stopped_epoch["shutdown_status"] == "PASS"
        assert stopped_epoch["strategy_shutdown_ready"] is True
        assert stopped_epoch["strategy_shutdown_post_join_confirmed"] is True
        assert stopped_epoch["engine_winddown_status"] == "NOT_REACHED"
        assert stopped_epoch["cleanup_complete"] is True
        assert stopped_epoch["decision_tape"]["closed"] is True
        assert len(api_clients) == previous_api_count + 1
        assert api_clients[-1].closed is True
        sequence_trace = trace[previous_trace_count:]
        assert [row for row in sequence_trace if row[0] == "api_created"] == [
            ("api_created", epoch_id)
        ]
        assert not any(
            row[0] in {"selection_catalog_query", "selection_depth_query"}
            and row[1] == epoch_id + 1
            for row in sequence_trace
        )
        assert len(live_run_results) == previous_success_count + 1
        return live_run_results[-1]

    strategy_module = importlib.import_module("alpha003_strategy")
    original_source_receipt = strategy_module.Alpha003TargetStrategy._source_receipt
    original_prenext = strategy_module.Alpha003TargetStrategy.prenext
    original_next = strategy_module.Alpha003TargetStrategy.next
    original_notify_idle = strategy_module.Alpha003TargetStrategy.notify_idle
    original_record_source_receipt = (
        factor_execution_module.FactorExecutionCoordinator.record_source_receipt
    )

    def tracked_source_receipt(strategy, *args, **kwargs):
        source_receipt_counts["builder_calls"] += 1
        try:
            result = original_source_receipt(strategy, *args, **kwargs)
        except Exception as error:
            _record_source_receipt_event("strategy_source_receipt", error=error)
            raise
        if legacy_v1_compat:
            # A v1-era receipt predates origin_partition. Keep production
            # strategy construction and journal serialization, but persist the
            # exact optional-field omission used by the legacy canonical form.
            from dataclasses import replace

            result = replace(
                result,
                members=tuple(
                    replace(member, origin_partition=None) for member in result.members
                ),
            )
        source_receipt_counts["builder_returns"] += 1
        _record_source_receipt_event("strategy_source_receipt", result=result)
        return result

    def tracked_record_source_receipt(coordinator, *args, **kwargs):
        source_receipt_counts["coordinator_write_calls"] += 1
        try:
            result = original_record_source_receipt(coordinator, *args, **kwargs)
        except Exception as error:
            _record_source_receipt_event("coordinator_record_source_receipt", error=error)
            raise
        source_receipt_counts["coordinator_write_returns"] += 1
        _record_source_receipt_event("coordinator_record_source_receipt", result=result)
        return result

    monkeypatch.setattr(
        strategy_module.Alpha003TargetStrategy,
        "_source_receipt",
        tracked_source_receipt,
    )
    monkeypatch.setattr(
        factor_execution_module.FactorExecutionCoordinator,
        "record_source_receipt",
        tracked_record_source_receipt,
    )

    def request_restart_after_final_batch(strategy):
        if not saved_history_restart or strategy.shutdown_requested:
            return
        epoch_id = strategy.p.cohort.epoch_id
        final_ordinal = {
            1: restart_cut,
            2: restart_cut_2,
            3: restart_cut_3,
        }
        if lineage_chain_only:
            final_ordinal.update({4: restart_cut_4, 5: restart_cut_5})
        final_ordinal = final_ordinal.get(epoch_id)
        if final_ordinal is None:
            return
        epoch_plan = current_plan["value"]
        final_close = epoch_plan["grid"].minutes[final_ordinal - 1].close_time
        batch = strategy.p.cohort.current_batch()
        context = api_clients[-1].context if api_clients else None
        receipts = tuple(batch.members.values()) if batch is not None else ()
        complete_final_batch = (
            batch is not None
            and batch.status == "COMPLETE"
            and batch.epoch_id == epoch_id
            and batch.close_time == final_close
            and set(batch.members) == set(epoch_plan["targets"])
            and all(
                receipt.epoch_id == epoch_id
                and receipt.close_time == final_close
                and receipt.source_role == "live"
                and receipt.complete is True
                and receipt.present is True
                and receipt.quality == "GOOD"
                and not receipt.missing_fields
                for receipt in receipts
            )
        )
        provider_exhausted = (
            context is not None
            and context.epoch_id == epoch_id
            and all(not queue for queue in context.bars.values())
        )
        tape_committed = (
            strategy._last_decision_tape_batch_id == getattr(batch, "batch_id", None)
            and strategy._last_decision_tape_reference is not None
            and strategy._last_decision_tape_error is None
        )
        if complete_final_batch and provider_exhausted and tape_committed:
            refresh_loop = strategy.p.control_refresh_loop
            assert refresh_loop.request_shutdown() is True
            trace.append(
                (
                    "fixture_restart_requested",
                    epoch_id,
                    batch.batch_id,
                    batch.close_time.isoformat(),
                )
            )

    def tracked_prenext(strategy):
        result = original_prenext(strategy)
        clock.record_completed_batch(strategy.p.cohort.current_batch())
        if lineage_chain_only:
            request_restart_after_final_batch(strategy)
        return result

    def tracked_next(strategy):
        result = original_next(strategy)
        clock.record_completed_batch(strategy.p.cohort.current_batch())
        request_restart_after_final_batch(strategy)
        return result

    def tracked_notify_idle(strategy):
        if lineage_chain_only and live_run_started_at["value"] is not None:
            if time.monotonic() - live_run_started_at["value"] > 30:
                batch = strategy.p.cohort.current_batch()
                context = api_clients[-1].context if api_clients else None
                diagnostic = {
                    "epoch_id": strategy.p.cohort.epoch_id,
                    "shutdown_requested": strategy.shutdown_requested,
                    "shutdown_blocker": strategy.shutdown_blocker,
                    "batch_status": getattr(batch, "status", None),
                    "batch_epoch_id": getattr(batch, "epoch_id", None),
                    "batch_close_time": (
                        batch.close_time.isoformat()
                        if batch is not None and batch.close_time is not None
                        else None
                    ),
                    "member_count": len(batch.members) if batch is not None else 0,
                    "provider_remaining": (
                        {key: len(queue) for key, queue in context.bars.items()}
                        if context is not None
                        else None
                    ),
                    "tape_batch_matches": (
                        strategy._last_decision_tape_batch_id
                        == getattr(batch, "batch_id", None)
                    ),
                    "tape_reference_present": (
                        strategy._last_decision_tape_reference is not None
                    ),
                    "tape_error": strategy._last_decision_tape_error,
                    "trace_tail": trace[-12:],
                }
                raise TimeoutError(
                    "bounded saved-history epoch wait "
                    + json.dumps(diagnostic, sort_keys=True, default=str)
                )
        original_notify_idle(strategy)
        if strategy.shutdown_requested:
            loop = strategy.p.control_refresh_loop
            facts = getattr(strategy, "last_execution_facts", None)
            summary = (
                strategy.p.cohort.epoch_id,
                strategy.shutdown_ready,
                strategy.shutdown_blocker,
                getattr(loop, "last_error_code", None),
                tuple(getattr(loop, "last_reconciliation_blockers", ())),
                getattr(facts, "read_only_reconciliation_ready", None),
                tuple(getattr(facts, "read_only_reconciliation_blockers", ())),
                tuple(getattr(facts, "blockers", ())),
            )
            if not trace or trace[-1] != ("shutdown_state", summary):
                trace.append(("shutdown_state", summary))
            if strategy not in strategy_instances:
                strategy_instances.append(strategy)

    monkeypatch.setattr(strategy_module.Alpha003TargetStrategy, "prenext", tracked_prenext)
    monkeypatch.setattr(strategy_module.Alpha003TargetStrategy, "next", tracked_next)
    monkeypatch.setattr(strategy_module.Alpha003TargetStrategy, "notify_idle", tracked_notify_idle)

    failure = None
    result = None
    continuity_error = None
    try:
        if source_final_highwater_missing:
            with pytest.raises(RUNNER.RunnerError) as continuity_error_context:
                run_saved_history_epoch()
            continuity_error = continuity_error_context.value
        elif saved_history_restart:
            config["risk"].update(
                policy_id="saved-history-budget-v1",
                max_hold_eligible_bars=12,
                preclose_grace_seconds=300,
                run_end_policy="CLOSE_ALL",
                quote_max_age_seconds=60,
                max_state_age_seconds=12 * 60 * 60,
                max_notional_per_position=100_000,
                max_total_notional=300_000,
                max_margin_per_position=10_000,
                max_total_margin=30_000,
                max_loss_per_position=10_000,
                max_total_loss=20_000,
                round_trip_fee_upper_bound_per_contract="1.00",
                stop_loss_ticks=1,
                max_order_intents_per_grid=2,
                max_order_intents_per_run=100,
            )
            config["cohort"]["epoch_id"] = 1
            first_result = run_saved_history_epoch()
            assert first_result["status"] == "LIVE_RUN_COMPLETE"
            assert first_result["cleanup_complete"] is True
            first_tape_path = Path(first_result["decision_tape"]["path"])
            first_tape_rows = tuple(
                RUNNER.iter_decision_tape(first_tape_path, max_bytes=50_000_000)
            )
            first_decisions = first_tape_rows[1:]
            assert all(
                row["header_record_id"] == first_tape_rows[0]["record_id"]
                for row in first_decisions
            )
            if selection_source == "bundle":
                legacy_rows = [dict(row) for row in first_tape_rows]
                for row in legacy_rows[1:]:
                    row.pop("header_record_id")
                legacy_rows = [
                    {
                        **{key: value for key, value in row.items() if key != "record_id"},
                        "record_id": hashlib.sha256(
                            RUNNER._canonical_json_bytes(
                                {key: value for key, value in row.items() if key != "record_id"}
                            ).rstrip(b"\n")
                        ).hexdigest(),
                    }
                    for row in legacy_rows
                ]
                legacy_tape_path = tmp_path / "saved-bundle-history-legacy-header-binding.jsonl"
                legacy_tape_path.write_bytes(
                    b"".join(RUNNER._canonical_json_bytes(row) for row in legacy_rows)
                )
                legacy_readback = tuple(
                    RUNNER.iter_decision_tape(legacy_tape_path, max_bytes=50_000_000)
                )
                assert len(legacy_readback) == len(first_tape_rows)
                assert legacy_readback[0]["selection_evidence"]["selection_source"] == (
                    "saved_bundle_legacy"
                )
                assert all("header_record_id" not in row for row in legacy_readback[1:])
            if query_saved_history:
                old_evidence = first_tape_rows[0]["selection_evidence"]
                old_manifest = old_evidence["manifest"]
                assert old_evidence["schema"] == (
                    "backtrader.alpha003_epoch_selection_evidence.v1"
                )
                assert old_evidence["manifest_sha256"] == hashlib.sha256(
                    RUNNER._canonical_json_bytes(old_manifest).rstrip(b"\n")
                ).hexdigest()
                evidence_binding = {
                    key: old_evidence[key]
                    for key in (
                        "schema",
                        "epoch_id",
                        "selection_source",
                        "selection_path",
                        "source_snapshot_id",
                        "manifest_sha256",
                        "routes",
                        "authorized_targets",
                        "selector_policy",
                        "grid_semantics_sha256",
                    )
                }
                grid_semantics = current_plan["value"]["grid"].to_dict()
                grid_semantics.pop("decision_at")
                grid_semantics.pop("calendar_hashes")
                assert old_evidence["grid_semantics_sha256"] == hashlib.sha256(
                    RUNNER._canonical_json_bytes(grid_semantics).rstrip(b"\n")
                ).hexdigest()
                assert old_evidence["binding_sha256"] == hashlib.sha256(
                    RUNNER._canonical_json_bytes(evidence_binding).rstrip(b"\n")
                ).hexdigest()
                assert set(old_evidence["routes"]) == {"DCE.M", "DCE.Y", "DCE.A"}
                assert old_evidence["source_snapshot_id"] == first_tape_rows[0][
                    "restart_identity"
                ]["source_snapshot_id"]
                assert first_tape_rows[0]["grid_sha256"] == first_tape_rows[0][
                    "restart_identity"
                ]["calendar"]["grid_sha256"]
                assert len(RUNNER._canonical_json_bytes(old_evidence)) <= 50_000_000
                assert all(
                    row["selection_evidence_sha256"] == old_evidence["binding_sha256"]
                    and row["record_id"]
                    == hashlib.sha256(
                        RUNNER._canonical_json_bytes(
                            {key: value for key, value in row.items() if key != "record_id"}
                        ).rstrip(b"\n")
                    ).hexdigest()
                    for row in first_decisions
                )
            assert len(first_decisions) == restart_cut
            assert first_tape_rows[0]["restart_identity"]["epoch_id"] == 1
            assert first_tape_rows[0]["targets"] == sorted(first_plan["targets"])
            assert first_decisions[0]["readiness"] == "WARMUP"
            assert all(
                member["quality_flags"] == []
                for row in first_decisions
                for member in row["members"].values()
            )
            first_slot_indexes = [row["slot_index"] for row in first_decisions]
            assert all(
                right == left + 1
                for left, right in zip(first_slot_indexes, first_slot_indexes[1:])
            )
            assert all(
                member["slot_index"] == row["slot_index"]
                and member["slot_id"] == "minute:" + RUNNER._aware_datetime(
                    row["close_time"], "tape slot close"
                ).isoformat()
                for row in first_decisions
                for member in row["members"].values()
            )
            assert all(row["epoch_id"] == 1 for row in first_decisions)

            config["cohort"]["epoch_id"] = 2
            config["inputs"]["history_decision_tape"] = str(first_tape_path)
            config["output"]["decision_tape_path"] = str(tmp_path / "live-decisions-resumed.jsonl")

            if legacy_v1_compat:
                legacy_schema = "backtrader.alpha003.decision_tape.v1"

                def assert_legacy_v1_rows(path):
                    rows = tuple(
                        RUNNER.iter_decision_tape(path, max_bytes=50_000_000)
                    )
                    assert rows[0]["schema"] == legacy_schema
                    assert "origin_partition_schema" not in rows[0]
                    assert all(
                        "origin_partition" not in member
                        for row in rows[1:]
                        for member in row["members"].values()
                    )
                    return rows

                first_tape_rows = assert_legacy_v1_rows(first_tape_path)
                first_decisions = first_tape_rows[1:]
                assert len(first_decisions[-config["factor"]["preheat_bars"] :]) == (
                    config["factor"]["preheat_bars"]
                )
                assert all(
                    member["source_role"] == "live"
                    for row in first_decisions[-config["factor"]["preheat_bars"] :]
                    for member in row["members"].values()
                )

                from backtrader.stores.execution_decision_journal import (
                    ExecutionDecisionJournal,
                )

                def read_legacy_source_receipts():
                    journal = ExecutionDecisionJournal(config["live"]["journal_path"])
                    try:
                        rows = tuple(
                            journal._connection.execute(
                                "SELECT account_scope,strategy_scope,logical_run_id,source_kind,"
                                "receipt_json,receipt_sha256 FROM execution_source_highwaters "
                                "ORDER BY account_scope,strategy_scope,logical_run_id,source_kind"
                            )
                        )
                        assert rows
                        snapshot = []
                        for row in rows:
                            scope = tuple(row[:4])
                            receipt_json = row[4]
                            receipt_sha256 = row[5]
                            assert hashlib.sha256(
                                receipt_json.encode("utf-8")
                            ).hexdigest() == receipt_sha256
                            receipt_values = json.loads(receipt_json)
                            assert all(
                                "origin_partition" not in member
                                for member in receipt_values["members"]
                            )
                            highwater = journal.source_highwater(*scope)
                            assert highwater is not None
                            assert highwater.receipt_sha256 == receipt_sha256
                            assert all(
                                member.origin_partition is None
                                for member in highwater.receipt.members
                            )
                            snapshot.append((scope, receipt_json, receipt_sha256))
                        return tuple(snapshot)
                    finally:
                        journal.close()

                before_reopen = read_legacy_source_receipts()
                after_reopen = read_legacy_source_receipts()
                assert after_reopen == before_reopen

                epoch2_result = run_saved_history_epoch()
                assert epoch2_result["status"] == "LIVE_RUN_COMPLETE"
                assert epoch2_result["epoch_id"] == 2
                assert epoch2_result["cleanup_complete"] is True
                assert epoch2_result["history_resume"]["restored_bar_count"] == (
                    config["factor"]["preheat_bars"]
                )
                assert api_clients[-1].closed is True
                epoch2_tape_path = Path(epoch2_result["decision_tape"]["path"])
                epoch2_tape_rows = assert_legacy_v1_rows(epoch2_tape_path)
                epoch2_decisions = epoch2_tape_rows[1:]
                warmup_bars = config["factor"]["preheat_bars"]
                assert len(epoch2_decisions) == warmup_bars + 8
                epoch2_history = epoch2_decisions[:warmup_bars]
                epoch2_live = epoch2_decisions[warmup_bars:]
                assert len(epoch2_live) == 8
                assert all(
                    member["source_role"] == "history"
                    for row in epoch2_history
                    for member in row["members"].values()
                )
                assert all(
                    member["source_role"] == "live"
                    for row in epoch2_live
                    for member in row["members"].values()
                )
                mixed_tail = epoch2_decisions[-warmup_bars:]
                assert len(mixed_tail) == warmup_bars
                assert all(
                    member["source_role"] == expected_role
                    for row, expected_role in zip(
                        mixed_tail,
                        ("history",) * (warmup_bars - 8) + ("live",) * 8,
                    )
                    for member in row["members"].values()
                )

                config["cohort"]["epoch_id"] = 3
                config["inputs"]["history_decision_tape"] = str(epoch2_tape_path)
                rejected_output = tmp_path / "live-decisions-v1-mixed-tail-rejected.jsonl"
                config["output"]["decision_tape_path"] = str(rejected_output)
                api_count_before_rejection = len(api_clients)
                with pytest.raises(RUNNER.RunnerError) as unproven_origin_error:
                    run_saved_history_epoch()
                assert (
                    unproven_origin_error.value.code
                    == "LIVE_HISTORY_ORIGIN_PARTITION_UNPROVEN"
                )
                assert len(api_clients) == api_count_before_rejection + 1
                assert api_clients[-1].closed is True
                assert not rejected_output.exists()
                assert len(
                    [row for row in trace if row[0] == "history_load" and row[1] == 3]
                ) == 1
                assert not any(
                    row == ("run_live_returned", 3) for row in trace
                )
                return

            if query_saved_history:
                configured_daily_bundles = config["selection"]["daily_bundles"]
                config["selection"]["daily_bundles"] = [str(second_bundle)]
                with pytest.raises(RUNNER.RunnerError) as daily_history_error:
                    RUNNER.run_live_epochs(
                        config,
                        config_path,
                        None,
                        "native",
                        1,
                        decision=SimpleNamespace(effective_tier="live"),
                        allow_write_flag=False,
                    )
                assert daily_history_error.value.code == "LIVE_HISTORY_SELECTION_UNSUPPORTED"
                config["selection"]["daily_bundles"] = configured_daily_bundles

                api_count_before_stale_plan = len(api_clients)
                with pytest.raises(RUNNER.RunnerError) as stale_plan_error:
                    RUNNER.run_live(
                        config,
                        config_path,
                        first_plan,
                        "native",
                        1,
                        decision=SimpleNamespace(effective_tier="live"),
                        allow_write_flag=False,
                    )
                assert stale_plan_error.value.code == "LIVE_HISTORY_FRESH_SELECTION_REQUIRED"
                assert len(api_clients) == api_count_before_stale_plan

                pending_query_context_options.update(stale_seconds=301)
                with pytest.raises(RUNNER.RunnerError) as stale_query_error:
                    run_saved_history_epoch()
                assert stale_query_error.value.code == "CTP_FUTURES_SNAPSHOT_COLLECTION_FAILED"
                assert stale_query_error.value.detail == "SNAPSHOT_TOO_OLD"
                query_diagnostics = stale_query_error.value.query_diagnostics
                assert query_diagnostics["status"] == "AVAILABLE"
                assert [row["stage"] for row in query_diagnostics["stages"]] == [
                    "catalog",
                    "depth",
                ]
                assert all(
                    row["result_type_matches"] is True
                    and row["request_type_matches"] is True
                    and row["generation_matches"] is True
                    and row["request_id_positive"] is True
                    and row["complete"] is True
                    and row["is_last_seen"] is True
                    and row["timed_out"] is False
                    for row in query_diagnostics["stages"]
                )
                assert all(
                    "request_id" not in row
                    and "connection_generation" not in row
                    and "records" not in row
                    and "error_message" not in row
                    for row in query_diagnostics["stages"]
                )
                assert api_clients[-1].closed is True
                assert not any(
                    row[0] == "history_load" and row[1] == 2 for row in trace
                )
                assert trace.count(("selection_catalog_query", 2)) == 1
                assert trace.count(("selection_depth_query", 2)) == 1

                config["cohort"]["epoch_id"] = 1
                with pytest.raises(RUNNER.RunnerError) as same_run_error:
                    run_saved_history_epoch()
                assert same_run_error.value.code == "LIVE_HISTORY_EPOCH_INVALID"
                assert api_clients[-1].closed is True
                config["cohort"]["epoch_id"] = 2

                def write_first_tape_tamper(name, mutate):
                    rows = [
                        json.loads(raw)
                        for raw in first_tape_path.read_bytes().splitlines()
                    ]
                    mutate(rows)
                    for row in rows:
                        row.pop("record_id", None)
                        row["record_id"] = hashlib.sha256(
                            RUNNER._canonical_json_bytes(row).rstrip(b"\n")
                        ).hexdigest()
                    path = tmp_path / name
                    path.write_bytes(
                        b"".join(RUNNER._canonical_json_bytes(row) for row in rows)
                    )
                    return path

                evidence_tamper_path = write_first_tape_tamper(
                    "history-selection-evidence-tampered.jsonl",
                    lambda rows: rows[0]["selection_evidence"]["manifest"].update(
                        status="BLOCKED"
                    ),
                )
                config["inputs"]["history_decision_tape"] = str(evidence_tamper_path)
                with pytest.raises(RUNNER.RunnerError) as evidence_tamper_error:
                    run_saved_history_epoch()
                assert evidence_tamper_error.value.code == (
                    "LIVE_HISTORY_SELECTION_EVIDENCE_INVALID"
                )
                assert api_clients[-1].closed is True

                row_binding_tamper_path = write_first_tape_tamper(
                    "history-selection-row-binding-tampered.jsonl",
                    lambda rows: rows[1].update(selection_evidence_sha256="0" * 64),
                )
                config["inputs"]["history_decision_tape"] = str(row_binding_tamper_path)
                with pytest.raises(RUNNER.RunnerError) as row_binding_error:
                    run_saved_history_epoch()
                assert row_binding_error.value.code == (
                    "DECISION_TAPE_SELECTION_EVIDENCE_MISMATCH"
                )
                assert api_clients[-1].closed is True

                original_stop_loss_ticks = config["risk"]["stop_loss_ticks"]
                changed_stop_loss_ticks = original_stop_loss_ticks + 1
                unchanged_run_intent_limit = config["risk"]["max_order_intents_per_run"]
                config["risk"]["stop_loss_ticks"] = changed_stop_loss_ticks

                def mutate_header_risk(rows, *, update_row_bindings):
                    header = rows[0]
                    header["restart_identity"]["risk"][
                        "stop_loss_ticks"
                    ] = changed_stop_loss_ticks
                    assert (
                        header["restart_identity"]["risk"]["max_order_intents_per_run"]
                        == unchanged_run_intent_limit
                    )
                    header.pop("record_id", None)
                    header["record_id"] = hashlib.sha256(
                        RUNNER._canonical_json_bytes(header).rstrip(b"\n")
                    ).hexdigest()
                    if update_row_bindings:
                        for row in rows[1:]:
                            row["header_record_id"] = header["record_id"]

                try:
                    header_risk_tamper_path = write_first_tape_tamper(
                        "history-header-risk-tampered.jsonl",
                        lambda rows: mutate_header_risk(rows, update_row_bindings=False),
                    )
                    header_risk_tamper_rows = [
                        json.loads(raw)
                        for raw in header_risk_tamper_path.read_bytes().splitlines()
                    ]
                    assert config["risk"]["stop_loss_ticks"] == (
                        header_risk_tamper_rows[0]["restart_identity"]["risk"][
                            "stop_loss_ticks"
                        ]
                    )
                    assert header_risk_tamper_rows[0]["record_id"] != first_tape_rows[0][
                        "record_id"
                    ]
                    assert all(
                        tampered["record_id"] == original["record_id"]
                        and tampered["header_record_id"] == first_tape_rows[0]["record_id"]
                        for tampered, original in zip(
                            header_risk_tamper_rows[1:], first_decisions
                        )
                    )
                    config["inputs"]["history_decision_tape"] = str(
                        header_risk_tamper_path
                    )
                    with pytest.raises(RUNNER.RunnerError) as header_binding_error:
                        run_saved_history_epoch()
                    assert header_binding_error.value.code == (
                        "DECISION_TAPE_HEADER_BINDING_MISMATCH"
                    )
                    assert api_clients[-1].closed is True
                    assert not Path(config["output"]["decision_tape_path"]).exists()

                    terminal_record_tamper_path = write_first_tape_tamper(
                        "history-header-risk-and-row-bindings-tampered.jsonl",
                        lambda rows: mutate_header_risk(rows, update_row_bindings=True),
                    )
                    terminal_record_tamper_rows = [
                        json.loads(raw)
                        for raw in terminal_record_tamper_path.read_bytes().splitlines()
                    ]
                    assert all(
                        row["header_record_id"] == terminal_record_tamper_rows[0]["record_id"]
                        for row in terminal_record_tamper_rows[1:]
                    )
                    assert all(
                        tampered["record_id"] != original["record_id"]
                        for tampered, original in zip(
                            terminal_record_tamper_rows[1:], first_decisions
                        )
                    )
                    config["inputs"]["history_decision_tape"] = str(
                        terminal_record_tamper_path
                    )
                    # Rebinding the header and row IDs still changes the
                    # terminal record referenced by the journal's source HWM.
                    # The loader checks that exact terminal binding before its
                    # later per-decision anchor lookup.
                    with pytest.raises(RUNNER.RunnerError) as source_highwater_error:
                        run_saved_history_epoch()
                    assert source_highwater_error.value.code == (
                        "LIVE_HISTORY_SOURCE_HIGHWATER_MISMATCH"
                    )
                    assert api_clients[-1].closed is True
                    assert not Path(config["output"]["decision_tape_path"]).exists()
                finally:
                    config["risk"]["stop_loss_ticks"] = original_stop_loss_ticks

                missing_header_binding_path = write_first_tape_tamper(
                    "history-header-binding-missing.jsonl",
                    lambda rows: [row.pop("header_record_id", None) for row in rows[1:]],
                )
                config["inputs"]["history_decision_tape"] = str(
                    missing_header_binding_path
                )
                with pytest.raises(RUNNER.RunnerError) as missing_header_binding_error:
                    run_saved_history_epoch()
                assert missing_header_binding_error.value.code == (
                    "DECISION_TAPE_HEADER_BINDING_REQUIRED"
                )
                assert api_clients[-1].closed is True

                config["inputs"]["history_decision_tape"] = str(first_tape_path)
                pending_query_context_options.update(selected_contract_index=0)
                with pytest.raises(RUNNER.RunnerError) as route_error:
                    run_saved_history_epoch()
                assert route_error.value.code == "LIVE_HISTORY_SELECTION_MISMATCH"
                assert api_clients[-1].closed is True

            truncated_path = tmp_path / "history-truncated.jsonl"
            truncated_path.write_bytes(first_tape_path.read_bytes()[:-1])
            config["inputs"]["history_decision_tape"] = str(truncated_path)
            with pytest.raises(RUNNER.RunnerError) as truncated_error:
                run_saved_history_epoch()
            assert truncated_error.value.code == "DECISION_TAPE_RECORD_INVALID"
            assert len(api_clients) == (query_run_attempts["value"] if query_saved_history else 1)

            malformed_path = tmp_path / "history-wrong-identity.jsonl"
            raw_lines = first_tape_path.read_bytes().splitlines(keepends=True)
            bad_header = json.loads(raw_lines[0])
            bad_header["restart_identity"]["scope_sha256"]["logical_run_id"] = "0" * 64
            bad_header.pop("record_id")
            bad_header["record_id"] = hashlib.sha256(
                RUNNER._canonical_json_bytes(bad_header).rstrip(b"\n")
            ).hexdigest()
            malformed_path.write_bytes(
                RUNNER._canonical_json_bytes(bad_header) + b"".join(raw_lines[1:])
            )
            config["inputs"]["history_decision_tape"] = str(malformed_path)
            with pytest.raises(RUNNER.RunnerError) as identity_error:
                run_saved_history_epoch()
            assert identity_error.value.code == "LIVE_HISTORY_IDENTITY_MISMATCH"
            assert len(api_clients) == (query_run_attempts["value"] if query_saved_history else 1)

            bad_batch_path = tmp_path / "history-wrong-batch.jsonl"
            bad_batch_rows = [json.loads(line) for line in raw_lines]
            bad_batch_rows[1]["batch_id"] = "nonempty-but-not-produced"
            bad_batch_rows[1].pop("record_id")
            bad_batch_rows[1]["record_id"] = hashlib.sha256(
                RUNNER._canonical_json_bytes(bad_batch_rows[1]).rstrip(b"\n")
            ).hexdigest()
            bad_batch_path.write_bytes(
                b"".join(RUNNER._canonical_json_bytes(row) for row in bad_batch_rows)
            )
            config["inputs"]["history_decision_tape"] = str(bad_batch_path)
            with pytest.raises(RUNNER.RunnerError) as batch_error:
                run_saved_history_epoch()
            assert batch_error.value.code == "LIVE_HISTORY_BATCH_ID_INVALID"
            assert len(api_clients) == (query_run_attempts["value"] if query_saved_history else 1)

            config["inputs"]["history_decision_tape"] = str(first_tape_path)
            from backtrader.stores.execution_decision_journal import ExecutionDecisionJournal

            history_cohort_id = "alpha003:{}:1".format(config["cohort"]["calendar_id"])
            journal_path = Path(config["live"]["journal_path"])
            journal = ExecutionDecisionJournal(journal_path)
            try:
                cursor = journal.grid_cursor(
                    config["live"]["account_scope"],
                    config["live"]["strategy_scope"],
                    history_cohort_id,
                )
                assert cursor is not None
                source_cursor_epoch = cursor.epoch_id
                journal._connection.execute(
                    "UPDATE execution_grid_cursors SET epoch_id = ? "
                    "WHERE account_scope = ? AND strategy_scope = ? AND cohort_id = ?",
                    (
                        "9",
                        config["live"]["account_scope"],
                        config["live"]["strategy_scope"],
                        history_cohort_id,
                    ),
                )
                journal._connection.commit()
            finally:
                journal.close()
            try:
                with pytest.raises(RUNNER.RunnerError) as cursor_epoch_error:
                    run_saved_history_epoch()
                assert cursor_epoch_error.value.code == "LIVE_HISTORY_JOURNAL_HIGHWATER_MISMATCH"
                assert len(api_clients) == (
                    query_run_attempts["value"] if query_saved_history else 1
                )
            finally:
                journal = ExecutionDecisionJournal(journal_path)
                try:
                    journal._connection.execute(
                        "UPDATE execution_grid_cursors SET epoch_id = ? "
                        "WHERE account_scope = ? AND strategy_scope = ? AND cohort_id = ?",
                        (
                            source_cursor_epoch,
                            config["live"]["account_scope"],
                            config["live"]["strategy_scope"],
                            history_cohort_id,
                        ),
                    )
                    journal._connection.commit()
                finally:
                    journal.close()

            from dataclasses import replace

            original_decision_for_key = ExecutionDecisionJournal.decision_for_key

            def run_with_anchor_lookup(
                lookup,
                expected_code="LIVE_HISTORY_JOURNAL_DECISION_ANCHOR_MISMATCH",
            ):
                with monkeypatch.context() as patcher:
                    patcher.setattr(ExecutionDecisionJournal, "decision_for_key", lookup)
                    with pytest.raises(RUNNER.RunnerError) as anchor_error:
                        run_saved_history_epoch()
                assert anchor_error.value.code == expected_code
                assert len(api_clients) == (
                    query_run_attempts["value"] if query_saved_history else 1
                )
                assert not Path(config["output"]["decision_tape_path"]).exists()

            run_with_anchor_lookup(lambda _journal, _key: None)

            def wrong_anchor_reference(journal, key):
                record = original_decision_for_key(journal, key)
                assert record is not None
                payload = dict(record.economic_payload)
                payload["decision_tape_record_id"] = "0" * 64
                return replace(record, economic_payload=payload)

            run_with_anchor_lookup(wrong_anchor_reference)

            if query_saved_history:
                pending_query_context_options.update(catalog_order_variant=True)
            result = run_saved_history_epoch()
            epoch2_result = result
            assert epoch2_result["status"] == "LIVE_RUN_COMPLETE"
            assert epoch2_result["epoch_id"] == 2
            assert epoch2_result["cleanup_complete"] is True
            epoch2_tape_path = Path(epoch2_result["decision_tape"]["path"])
            epoch2_tape_rows = tuple(
                RUNNER.iter_decision_tape(epoch2_tape_path, max_bytes=50_000_000)
            )
            epoch2_decisions = epoch2_tape_rows[1:]
            assert all(
                row["header_record_id"] == epoch2_tape_rows[0]["record_id"]
                for row in epoch2_decisions
            )

            if query_saved_history:
                old_query_snapshot = old_evidence["manifest"]["query_snapshot"]
                epoch2_evidence = epoch2_tape_rows[0]["selection_evidence"]
                epoch2_query_snapshot = epoch2_evidence["manifest"]["query_snapshot"]

                def normalized_catalog_records(evidence):
                    fields = (
                        "product",
                        "instrument_id",
                        "asset_type",
                        "is_trading",
                        "expiry_date",
                        "product_class",
                    )
                    return sorted(
                        RUNNER._canonical_json_bytes(
                            {field: row[field] for field in fields}
                        )
                        for row in evidence["manifest"]["query_snapshot"][
                            "catalog_records"
                        ]
                    )

                def actual_query_grid_hashes(evidence):
                    plan = query_plans_by_snapshot_id[evidence["source_snapshot_id"]]
                    grid_row = plan["grid"].to_dict()
                    raw_grid_sha256 = hashlib.sha256(
                        RUNNER._canonical_json_bytes(grid_row).rstrip(b"\n")
                    ).hexdigest()
                    stable_grid = {
                        key: value
                        for key, value in grid_row.items()
                        if key not in {"decision_at", "calendar_hashes"}
                    }
                    stable_grid_sha256 = hashlib.sha256(
                        RUNNER._canonical_json_bytes(stable_grid).rstrip(b"\n")
                    ).hexdigest()
                    return raw_grid_sha256, stable_grid_sha256

                assert old_evidence["routes"] == epoch2_evidence["routes"]
                assert (
                    old_query_snapshot["catalog_source"]["sha256"]
                    != epoch2_query_snapshot["catalog_source"]["sha256"]
                )
                assert (
                    old_query_snapshot["quote_source"]["sha256"]
                    != epoch2_query_snapshot["quote_source"]["sha256"]
                )
                assert normalized_catalog_records(old_evidence) == normalized_catalog_records(
                    epoch2_evidence
                )
                old_ranking = {
                    row["instrument_id"]: row["ranking_score"]
                    for row in old_evidence["manifest"]["candidates"]
                }
                epoch2_ranking = {
                    row["instrument_id"]: row["ranking_score"]
                    for row in epoch2_evidence["manifest"]["candidates"]
                }
                assert old_ranking != epoch2_ranking
                assert (
                    old_evidence["manifest"]["decision_at"]
                    != epoch2_evidence["manifest"]["decision_at"]
                )
                # The same synthetic CTP TradingDay uses one fixed source
                # review timestamp, so its calendar evidence is stable across
                # later selection decisions.
                assert (
                    old_evidence["manifest"]["calendars"][0]["sha256"]
                    == epoch2_evidence["manifest"]["calendars"][0]["sha256"]
                )
                old_grid_sha256, old_grid_semantics_sha256 = actual_query_grid_hashes(
                    old_evidence
                )
                epoch2_grid_sha256, epoch2_grid_semantics_sha256 = (
                    actual_query_grid_hashes(epoch2_evidence)
                )
                assert (
                    old_grid_sha256 != epoch2_grid_sha256
                )
                assert old_grid_semantics_sha256 == old_evidence["grid_semantics_sha256"]
                assert (
                    epoch2_grid_semantics_sha256
                    == epoch2_evidence["grid_semantics_sha256"]
                )
                assert epoch2_tape_rows[0]["grid_sha256"] == epoch2_tape_rows[0][
                    "restart_identity"
                ]["calendar"]["grid_sha256"]
                assert (
                    old_evidence["grid_semantics_sha256"]
                    == epoch2_evidence["grid_semantics_sha256"]
                )

            # Exercise structural tampering against the actual epoch-2 tape.
            # Recompute row IDs so each negative proves the semantic validator,
            # rather than only the JSONL integrity check, rejects the change.
            def write_tampered_history(name, mutate):
                rows = [json.loads(raw) for raw in epoch2_tape_path.read_bytes().splitlines()]
                mutate(rows)
                for row in rows:
                    row.pop("record_id", None)
                    row["record_id"] = hashlib.sha256(
                        RUNNER._canonical_json_bytes(row).rstrip(b"\n")
                    ).hexdigest()
                path = tmp_path / name
                path.write_bytes(
                    b"".join(RUNNER._canonical_json_bytes(row) for row in rows)
                )
                return path

            first_target = sorted(epoch2_decisions[0]["members"])[0]

            def make_unknown_role(rows):
                rows[1]["members"][first_target]["source_role"] = "warmup"

            def make_role_bounce(rows):
                for member in rows[-1]["members"].values():
                    member["source_role"] = "history"

            def make_history_generation_drift(rows):
                rows[2]["members"][first_target]["connection_generation"] = "tampered-history"

            warmup_bars = config["factor"]["preheat_bars"]
            first_live_record_index = warmup_bars + 1  # includes the tape header

            def make_live_generation_drift(rows):
                rows[first_live_record_index + 1]["members"][first_target][
                    "connection_generation"
                ] = "tampered-live"

            def make_history_sequence_rollback(rows):
                rows[2]["members"][first_target]["feed_sequence"] = rows[1]["members"][
                    first_target
                ]["feed_sequence"]

            def make_live_sequence_rollback(rows):
                rows[first_live_record_index + 1]["members"][first_target][
                    "feed_sequence"
                ] = rows[first_live_record_index]["members"][first_target]["feed_sequence"]

            def make_source_ref_drift(rows):
                rows[1]["members"][first_target]["source_ref"] = "ctp-live:wrong:route"

            def make_origin_partition_cohort_splice(rows):
                history_bars = config["factor"]["preheat_bars"]
                first_live_index = 1 + history_bars
                terminal_index = len(rows) - 1
                assert terminal_index > first_live_index
                for target in rows[1]["members"]:
                    origin_partition = dict(rows[1]["members"][target]["origin_partition"])
                    sequence = rows[first_live_index - 1]["members"][target]["feed_sequence"]
                    for row in rows[first_live_index:terminal_index]:
                        member = row["members"][target]
                        assert member["source_role"] == "live"
                        sequence += 1
                        member["connection_generation"] = origin_partition[
                            "connection_generation"
                        ]
                        member["feed_sequence"] = sequence
                        member["origin_partition"] = dict(origin_partition)

            def make_non_string_event_source(rows):
                rows[1]["members"][first_target]["event_source"] = 7

            def make_valid_price_change(rows):
                member = rows[-1]["members"][first_target]
                raw_values = member["raw_values"]
                raw_values["close"] += 0.01
                assert raw_values["low"] < raw_values["close"] < raw_values["high"]

            tampering_cases = (
                ("unknown-role", make_unknown_role, "LIVE_HISTORY_SOURCE_ROLE_INVALID"),
                (
                    "live-then-history",
                    make_role_bounce,
                    "LIVE_HISTORY_SOURCE_ROLE_ORDER_INVALID",
                ),
                (
                    "history-generation-drift",
                    make_history_generation_drift,
                    "LIVE_HISTORY_ORIGIN_PARTITION_INVALID",
                ),
                (
                    "live-generation-drift",
                    make_live_generation_drift,
                    "LIVE_HISTORY_ORIGIN_PARTITION_INVALID",
                ),
                (
                    "history-sequence-rollback",
                    make_history_sequence_rollback,
                    "LIVE_HISTORY_SEQUENCE_INVALID",
                ),
                (
                    "live-sequence-rollback",
                    make_live_sequence_rollback,
                    "LIVE_HISTORY_SEQUENCE_INVALID",
                ),
                ("source-ref-drift", make_source_ref_drift, "LIVE_HISTORY_MEMBER_INVALID"),
                (
                    "origin-partition-cohort-splice",
                    make_origin_partition_cohort_splice,
                    "LIVE_HISTORY_SOURCE_RECEIPT_MISMATCH",
                ),
                (
                    # Rehashing the valid-value edit changes the terminal
                    # record ID, so source-HWM binding fails before anchors.
                    "valid-price-change",
                    make_valid_price_change,
                    "LIVE_HISTORY_SOURCE_HIGHWATER_MISMATCH",
                ),
                (
                    "non-string-event-source",
                    make_non_string_event_source,
                    "LIVE_HISTORY_MEMBER_INVALID",
                ),
            )
            config["cohort"]["epoch_id"] = 3
            config["output"]["decision_tape_path"] = str(
                tmp_path / "live-decisions-epoch-3.jsonl"
            )
            if query_saved_history and not lineage_chain_only:
                # The query-history comparison must use the latest successful
                # tape as its baseline, not keep consulting epoch 1.
                config["inputs"]["history_decision_tape"] = str(epoch2_tape_path)
                pending_query_context_options.update(catalog_semantic_change=True)
                with pytest.raises(RUNNER.RunnerError) as catalog_error:
                    run_saved_history_epoch()
                assert catalog_error.value.code == "LIVE_HISTORY_SELECTION_MISMATCH"
                assert RUNNER._route_summary(current_plan["value"]) == epoch2_evidence[
                    "routes"
                ]
                assert api_clients[-1].closed is True
            if not lineage_chain_only:
                for name, mutate, expected_code in tampering_cases:
                    tampered_path = write_tampered_history(
                        "history-{}.jsonl".format(name), mutate
                    )
                    config["inputs"]["history_decision_tape"] = str(tampered_path)
                    tampering_error = None
                    try:
                        run_saved_history_epoch()
                    except RUNNER.RunnerError as caught_error:
                        tampering_error = caught_error
                    else:
                        pytest.fail("tampering case unexpectedly accepted: {}".format(name))
                    assert tampering_error is not None
                    assert tampering_error.code == expected_code, {
                        "tampering_case": name,
                        "expected_code": expected_code,
                        "actual_code": tampering_error.code,
                    }
                    assert len(api_clients) == (
                        query_run_attempts["value"] if query_saved_history else 2
                    )
                    assert not Path(config["output"]["decision_tape_path"]).exists()

            config["inputs"]["history_decision_tape"] = str(epoch2_tape_path)
            result = run_saved_history_epoch()
        else:
            if selection_source != "ctp_query":
                contexts.append(make_context(first_plan, config["cohort"]["epoch_id"]))
            result = RUNNER.run_live_epochs(
                config,
                config_path,
                None if selection_source == "ctp_query" else first_plan,
                "native",
                1,
                decision=SimpleNamespace(effective_tier="live"),
                allow_write_flag=False,
            )
    except TimeoutError as error:
        if unresolved_position:
            failure = error
        else:
            strategy = strategy_instances[-1] if strategy_instances else None
            facts = getattr(strategy, "last_execution_facts", None) if strategy else None
            loop = strategy.p.control_refresh_loop if strategy is not None else None
            loop_facts = getattr(loop, "last_facts", None)
            receipt = getattr(loop, "last_receipt", None)
            pytest.fail(
                repr(
                    {
                        "error": type(error).__name__,
                        "clock_now": clock.utc_now().isoformat(),
                        "availability_index": clock._availability_index,
                        "availability_count": len(clock._availability),
                        "remaining_bars": [
                            len(queue) for api in api_clients for queue in api.context.bars.values()
                        ],
                        "trace": trace[-10:],
                        "shutdown_blocker": (
                            strategy.shutdown_blocker if strategy is not None else None
                        ),
                        "facts_blockers": getattr(facts, "blockers", None),
                        "retirement_blockers": getattr(
                            facts, "read_only_reconciliation_blockers", None
                        ),
                        "route_sessions": [
                            (
                                row.target_id,
                                row.connection_generation,
                                row.trading_day,
                                row.current_session_account_fingerprint,
                                row.current_session_connection_generation,
                                row.current_session_trading_day,
                                row.current_session_trading_ready,
                            )
                            for row in getattr(facts, "routes", ())
                        ],
                        "positions": [
                            (
                                row.target_id,
                                row.instrument,
                                row.exchange,
                                row.quantity,
                                row.broker_quantity,
                                row.snapshot_id,
                                row.available_at,
                            )
                            for row in getattr(facts, "positions", ())
                        ],
                        "refresh_facts_blockers": getattr(loop_facts, "blockers", None),
                        "refresh_query_facts": [
                            (
                                row.family,
                                row.target_id,
                                row.request_id,
                                row.source_owned,
                                row.query_complete,
                                row.scope_complete,
                                row.started_at,
                                row.completed_at,
                                getattr(row, "reason_codes", None),
                            )
                            for row in getattr(loop_facts, "query_provenance", ())
                        ],
                        "query_set": getattr(receipt, "query_set", None),
                    }
                )
            )
    assert sdk_instances["md"] == [api.md_client for api in api_clients]
    assert sdk_instances["trader"] == [api.trader_client for api in api_clients]
    for api in api_clients:
        for client in (api.md_client, api.trader_client):
            assert client.start_calls == [{"block": False, "join_observer": False}]
            assert client.stop_calls == 1
            if api._ctp_factor_tick_source_enabled is True:
                assert len(client.stop_receipts) == 1
                receipt = client.stop_receipts[0]
                assert receipt.complete is True
                assert receipt.native_released is True
                assert receipt.join_required is False
                assert receipt.join_completed is True
                assert receipt.thread_alive is False
                assert receipt.timed_out is False
                expected_generation = (
                    api.md_client.connection_generation
                    if client is api.md_client
                    else api.trader_client._connection_generation
                )
                assert receipt.connection_generation == expected_generation
            else:
                # Query/history validation may close a successfully started
                # Store before the factor-source opt-in point. Those attempts
                # retain the legacy stop-only cleanup contract.
                assert client.stop_receipts == []
        assert api.live_tick_provenance is None
        health = api._get_live_ctp_stream_health()
        assert health["generation_callbacks_supported"] is True
        assert health["source_generation"] == api.md_client.connection_generation
        assert callable(api.md_client.on_tick_with_generation)
        assert callable(api.md_client.on_disconnect_with_generation)
    assert factor_source_bindings
    for api, binding in factor_source_bindings:
        assert isinstance(binding, CtpFactorSourceBinding)
        assert api._ctp_factor_tick_source_enabled is True
        assert api._ctp_factor_expected_md_generation == api.md_client.connection_generation
        assert binding.expected_md_generation == api.md_client.connection_generation
        assert binding.trader_trading_day == datetime.strptime(
            api.trader_client._trading_day, "%Y%m%d"
        ).date()

    if source_final_highwater_missing:
        assert continuity_error is not None
        assert continuity_error.code == "LIVE_SOURCE_CONTINUITY_UNAVAILABLE"
        assert failure is None
        assert result is None
        assert live_run_results == []
        assert len(api_clients) == 1 and api_clients[0].closed is True
        assert source_receipts_written, _source_receipt_failure_note(continuity_error)
        assert strategy_source_highwaters
        assert all(highwater is not None for highwater in strategy_source_highwaters)
        assert decision_tape_closed["value"] is True
        assert len(source_highwater_reads) == 1
        assert all(
            args
            == (
                "alpha003-two-epoch-account",
                "alpha003-two-epoch-shadow",
                "alpha003-two-epoch-shadow-run",
                RUNNER._live_source_lineage_kind(first_plan),
            )
            and kwargs == ()
            for args, kwargs in source_highwater_reads
        )
        source_continuity = continuity_error.source_continuity
        assert source_continuity["status"] == "UNAVAILABLE"
        assert source_continuity["available"] is False
        assert source_continuity["record_count"] > 0
        assert source_continuity["failure_count"] == 1
        assert source_continuity["first_error"] == "SOURCE_HIGHWATER_MISSING"
        assert source_continuity["final_highwater_matches_tape"] is False
        cleanup = continuity_error.cleanup_results
        assert RUNNER._cleanup_complete(cleanup) is True
        by_resource = {row["resource"]: row for row in cleanup}
        assert set(by_resource) == {
            "query_refresh",
            "decision_tape",
            "broker",
            "store",
            "journal",
        }
        assert by_resource["query_refresh"]["joined"] is True
        assert by_resource["decision_tape"]["status"] == "CLOSED"
        assert by_resource["decision_tape"]["record_count"] == source_continuity[
            "record_count"
        ]
        # This integration fixture is explicitly read-only, so the production
        # Broker reports observation-only rather than claiming flat/execution
        # reconciliation.  Cleanup still requires its actual Store stop to
        # pass; _cleanup_complete above also checks the refresh join, native
        # source receipt, journal, and tape.
        assert by_resource["broker"]["status"] == "OBSERVATION_ONLY"
        assert by_resource["broker"]["store_shutdown_state"] == "PASS"
        assert by_resource["store"]["status"] == "CLOSED_BY_BROKER"
        assert by_resource["store"]["shutdown_state"] == "PASS"
        assert by_resource["journal"]["status"] == "CLOSED"
        tape_rows = list(
            RUNNER.iter_decision_tape(
                Path(config["output"]["decision_tape_path"]),
                max_bytes=config["output"]["decision_tape_max_bytes"],
            )
        )
        decision_rows = [row for row in tape_rows if row["record_type"] == "DECISION"]
        assert len(decision_rows) == source_continuity["record_count"] > 0
        assert len(api_clients) == 1 and api_clients[0].closed is True
        return

    if unresolved_position:
        assert isinstance(failure, TimeoutError), repr(
            {
                "failure": type(failure).__name__ if failure else None,
                "result": result,
                "trace": trace,
            }
        )
        assert len(api_clients) == 1
        assert api_clients[0].closed is True
        assert not any(row[0] == "second_bundle_loaded" for row in trace)
        assert not any(row[0] == "cohort_assembled" and row[1] == 2 for row in trace)
        assert failure.assembly_attempts == (1,)
        assert failure.next_bundle_read_count == 0
        assert failure.next_epoch_load_permitted is False
        assert failure.old_route_handling == "OLD_ROUTE_UNRESOLVED_LOCAL_RESOURCES_CLOSED"
        assert failure.failed_epoch["engine_winddown_status"] == "TIMED_OUT"
        assert failure.failed_epoch["strategy_shutdown_ready"] is False
        assert failure.failed_epoch["cleanup_complete"] is True
        assert failure.failed_epoch["routes"] == RUNNER._route_summary(first_plan)
        assert any(
            state[1] is False
            and state[5] is False
            and state[2]
            and any(
                blocker.startswith("read_only_position_projection_mismatch:")
                for blocker in state[6]
            )
            for label, state in trace
            if label == "shutdown_state"
        )
        return

    assert failure is None

    if saved_history_restart:
        assert result["status"] == "LIVE_RUN_COMPLETE"
        assert result["epoch_id"] == 3
        assert result["cleanup_complete"] is True
        assert len(api_clients) == (
            query_run_attempts["value"] if query_saved_history else 3
        )
        assert all(client.closed for client in api_clients)
        for epoch_result in (first_result, epoch2_result, result):
            assert epoch_result["engine_winddown_status"] == "NOT_REACHED"
            assert epoch_result["engine_winddown_reason"] == "final_batch_not_reached"
            assert epoch_result["shutdown_path"] == "controlled_application_stop"
            assert epoch_result["strategy_shutdown_requested"] is True
            assert epoch_result["strategy_shutdown_ready"] is True
            assert epoch_result["strategy_shutdown_blocker"] is None
            assert epoch_result["strategy_shutdown_post_join_confirmed"] is True
            assert epoch_result["strategy_shutdown_post_join_blocker"] is None
            assert epoch_result["shutdown_status"] == "PASS"
            assert epoch_result["cleanup_complete"] is True
            query_refresh = next(
                row for row in epoch_result["resource_shutdown"]
                if row["resource"] == "query_refresh"
            )
            assert query_refresh["joined"] is True
        assert [row for row in trace if row[0] == "run_live_returned"] == [
            ("run_live_returned", 1),
            ("run_live_returned", 2),
            ("run_live_returned", 3),
        ]
        if query_saved_history:
            successful_evidence = (
                first_result["selection_evidence"],
                epoch2_tape_rows[0]["selection_evidence"],
                result["selection_evidence"],
            )
            assert len(
                {evidence["source_snapshot_id"] for evidence in successful_evidence}
            ) == 3
            assert len(
                {
                    evidence["manifest"]["query_snapshot"]["catalog_source"][
                        "connection_generation"
                    ]
                    for evidence in successful_evidence
                }
            ) == 3
            assert query_run_attempts["value"] == len(api_clients)
            snapshots = [
                (client.context.snapshot_serial, client.context.connection_generation)
                for client in api_clients
            ]
            assert len({serial for serial, _generation in snapshots}) == len(snapshots)
            assert len({generation for _serial, generation in snapshots}) == len(snapshots)
            for previous, current in zip(snapshots, snapshots[1:]):
                assert trace.index(("api_closed_snapshot", *previous)) < trace.index(
                    ("api_created_snapshot", *current)
                )
            for history_event in (row for row in trace if row[0] == "history_load"):
                _label, _epoch_id, snapshot_id = history_event
                assert snapshot_id is not None
                plan_ready_index = trace.index(("query_plan_ready", snapshot_id))
                catalog_index = trace.index(
                    (
                        "selection_catalog_query_snapshot",
                        next(
                            row[2]
                            for row in trace
                            if row[0] == "query_plan_ready_snapshot"
                            and row[1] == snapshot_id
                        ),
                    )
                )
                depth_index = trace.index(
                    (
                        "selection_depth_query_snapshot",
                        next(
                            row[2]
                            for row in trace
                            if row[0] == "query_plan_ready_snapshot"
                            and row[1] == snapshot_id
                        ),
                    )
                )
                history_index = trace.index(history_event)
                snapshot_serial = next(
                    row[2]
                    for row in trace
                    if row[0] == "query_plan_ready_snapshot" and row[1] == snapshot_id
                )
                ready_index = trace.index(("store_ready_snapshot", snapshot_serial))
                login_indexes = [
                    index
                    for index, row in enumerate(trace)
                    if row == ("store_login_facts_snapshot", snapshot_serial)
                ]
                assert len(login_indexes) >= 2
                assert (
                    ready_index
                    < login_indexes[0]
                    < catalog_index
                    < depth_index
                    < plan_ready_index
                    < login_indexes[1]
                    < history_index
                )
        expected_restart_requests = []
        for epoch_id, final_ordinal in (
            (1, restart_cut),
            (2, restart_cut_2),
            (3, restart_cut_3),
        ):
            final_close = plans_by_epoch[epoch_id]["grid"].minutes[
                final_ordinal - 1
            ].close_time
            calendar = calendar_overrides_by_epoch[epoch_id]
            if calendar is None:
                cohort_slot_index = final_ordinal - 1
            else:
                matching_slots = [
                    index
                    for index, slot in enumerate(calendar.slots)
                    if slot.close_time == final_close
                ]
                assert len(matching_slots) == 1
                cohort_slot_index = matching_slots[0]
            expected_restart_requests.append(
                (
                    "fixture_restart_requested",
                    epoch_id,
                    "{}:{}:{}:{}:{}".format(
                        "alpha003:{}:{}".format(
                            config["cohort"]["calendar_id"], epoch_id
                        ),
                        config["cohort"]["calendar_id"],
                        epoch_id,
                        config["cohort"]["calendar_version"],
                        cohort_slot_index,
                    ),
                    final_close.isoformat(),
                )
            )
        assert [row for row in trace if row[0] == "fixture_restart_requested"] == (
            expected_restart_requests
        )
        if query_saved_history and not lineage_chain_only:
            assert plans_by_epoch[3]["grid"].minutes[
                restart_cut_3 - 1
            ].close_time != first_plan["grid"].minutes[restart_cut_3 - 1].close_time
        assert trace.index(("initial_refresh_complete", 2)) < next(
            index for index, row in enumerate(trace)
            if row[0] == "first_provider_bar" and row[1] == 2
        )
        assert trace.index(("initial_refresh_complete", 3)) < next(
            index for index, row in enumerate(trace)
            if row[0] == "first_provider_bar" and row[1] == 3
        )
        old_decisions = first_decisions
        old_header = first_tape_rows[0]
        assert old_header["restart_identity"]["epoch_id"] == 1
        assert all(
            member["source_role"] == "live"
            for row in old_decisions
            for member in row["members"].values()
        )
        warmup_bars = config["factor"]["preheat_bars"]

        def eligible_live_grid_decisions(decisions):
            return tuple(
                row
                for row in decisions
                if row["readiness"] == "LIVE_READY"
                and row["members"]
                and all(
                    member["source_role"] == "live"
                    and member["complete"] is True
                    and member["present"] is True
                    and member["quality"] == "GOOD"
                    and not member["missing_fields"]
                    for member in row["members"].values()
                )
            )

        old_grid_decisions = eligible_live_grid_decisions(old_decisions)
        # A complete N-bar live window becomes eligible on its Nth bar, whose
        # zero-based offset is N - 1. Keep this GRID projection separate from
        # the source-tape tail restored as history below.
        first_ready_live_offset = warmup_bars - 1
        restored_ready_live_offset = 0 if lineage_chain_only else first_ready_live_offset
        assert old_grid_decisions == tuple(old_decisions[first_ready_live_offset:])
        assert not eligible_live_grid_decisions(old_decisions[:first_ready_live_offset])
        expected_history_tail = tuple(old_decisions[-warmup_bars:])
        assert len(expected_history_tail) == warmup_bars
        assert epoch2_result["status"] == "LIVE_RUN_COMPLETE"
        assert epoch2_result["epoch_id"] == 2
        assert epoch2_result["cleanup_complete"] is True
        assert epoch2_tape_rows[0]["restart_identity"]["epoch_id"] == 2
        expected_epoch2_live_closes = provider_live_closes_by_epoch[2]
        assert len(epoch2_decisions) == warmup_bars + len(expected_epoch2_live_closes)
        assert next(
            row for row in trace if row[0] == "first_provider_bar" and row[1] == 2
        ) == ("first_provider_bar", 2, 1, expected_epoch2_live_closes[0])
        assert all(row["epoch_id"] == 2 for row in epoch2_decisions)
        history_decisions = epoch2_decisions[:warmup_bars]
        live_decisions = epoch2_decisions[warmup_bars:]
        assert tuple(row["close_time"] for row in history_decisions) == tuple(
            row["close_time"] for row in expected_history_tail
        )
        assert tuple(row["close_time"] for row in live_decisions) == tuple(
            close.isoformat().replace("+00:00", "Z") for close in expected_epoch2_live_closes
        )
        assert not eligible_live_grid_decisions(history_decisions)
        assert not eligible_live_grid_decisions(live_decisions[:restored_ready_live_offset])
        assert all(
            member["source_role"] == "history"
            and member["connection_generation"] == "epoch-1-generation-1"
            and member["epoch_id"] == 2
            and member["source_ref"] == "ctp-live:{}:{}".format(
                target, first_plan["routes"][first_plan["product_by_target"][target]]
            )
            for row in history_decisions
            for target, member in row["members"].items()
        )
        assert all(
            member["source_role"] == "live"
            and member["connection_generation"] == "epoch-2-generation-1"
            for row in live_decisions
            for member in row["members"].values()
        )
        epoch2_grid_decisions = eligible_live_grid_decisions(epoch2_decisions)
        assert len(epoch2_grid_decisions) == (
            len(expected_epoch2_live_closes) - restored_ready_live_offset
        )
        assert epoch2_grid_decisions
        assert epoch2_grid_decisions == tuple(live_decisions[restored_ready_live_offset:])
        assert [
            next(iter(row["members"].values()))["feed_sequence"] for row in live_decisions
        ] == list(range(1, len(live_decisions) + 1))
        expected_history = first_plan["grid"].minutes[
            restart_cut - warmup_bars : restart_cut
        ]
        assert [row["close_time"] for row in history_decisions] == [
            minute.close_time.isoformat().replace("+00:00", "Z") for minute in expected_history
        ]
        assert live_decisions[0]["close_time"] == expected_epoch2_live_closes[
            0
        ].isoformat().replace("+00:00", "Z")
        assert epoch2_result["history_resume"]["source_epoch_id"] == 1
        assert epoch2_result["history_resume"]["restored_bar_count"] == warmup_bars
        assert epoch2_result["history_resume"]["last_close_time"] == history_decisions[-1][
            "close_time"
        ]
        assert epoch2_result["history_resume"]["prior_run_order_intents"] == 0
        assert (
            epoch2_result["history_resume"]["prior_grid_cursor_batch_id"]
            == old_grid_decisions[-1]["batch_id"]
        )
        assert epoch2_result["history_resume"]["run_order_intents_after"] == 0

        epoch3_rows = tuple(
            RUNNER.iter_decision_tape(
                Path(result["decision_tape"]["path"]), max_bytes=50_000_000
            )
        )
        assert epoch3_rows[0]["restart_identity"]["epoch_id"] == 3
        epoch3_decisions = epoch3_rows[1:]
        assert all(
            row["header_record_id"] == epoch3_rows[0]["record_id"]
            for row in epoch3_decisions
        )
        if query_saved_history:
            assert all(
                action.get("action") != "OPEN"
                for tape_rows in (first_tape_rows, epoch2_tape_rows, epoch3_rows)
                for decision_row in tape_rows[1:]
                for action in (decision_row.get("order_plan") or {}).get("actions", ())
            )
        expected_epoch3_live_closes = provider_live_closes_by_epoch[3]
        assert len(epoch3_decisions) == warmup_bars + len(expected_epoch3_live_closes)
        assert next(
            row for row in trace if row[0] == "first_provider_bar" and row[1] == 3
        ) == ("first_provider_bar", 3, 1, expected_epoch3_live_closes[0])
        assert all(row["epoch_id"] == 3 for row in epoch3_decisions)
        epoch3_history = epoch3_decisions[:warmup_bars]
        epoch3_live = epoch3_decisions[warmup_bars:]
        expected_epoch3_history_tail = tuple(epoch2_decisions[-warmup_bars:])
        assert len(expected_epoch3_history_tail) == warmup_bars
        assert tuple(row["close_time"] for row in epoch3_history) == tuple(
            row["close_time"] for row in expected_epoch3_history_tail
        )
        assert tuple(row["close_time"] for row in epoch3_live) == tuple(
            close.isoformat().replace("+00:00", "Z") for close in expected_epoch3_live_closes
        )
        assert not eligible_live_grid_decisions(epoch3_history)
        assert not eligible_live_grid_decisions(epoch3_live[:restored_ready_live_offset])
        assert all(
            member["source_role"] == "history"
            and member["epoch_id"] == 3
            and member["source_ref"] == "ctp-live:{}:{}".format(
                target, first_plan["routes"][first_plan["product_by_target"][target]]
            )
            for row in epoch3_history
            for target, member in row["members"].items()
        )
        for restored, original in zip(epoch3_history, expected_epoch3_history_tail):
            for target, member in restored["members"].items():
                original_member = original["members"][target]
                assert member["connection_generation"] == original_member[
                    "connection_generation"
                ]
                assert member["feed_sequence"] == original_member["feed_sequence"]
                assert member["bar_id"] == original_member["bar_id"]
                assert member["raw_values"] == original_member["raw_values"]
        assert all(
            member["source_role"] == "live"
            and member["connection_generation"] == "epoch-3-generation-1"
            for row in epoch3_live
            for member in row["members"].values()
        )
        assert all(
            member["feed_sequence"] == index
            for index, row in enumerate(epoch3_live, 1)
            for member in row["members"].values()
        )
        epoch3_grid_decisions = eligible_live_grid_decisions(epoch3_decisions)
        assert len(epoch3_grid_decisions) == (
            len(expected_epoch3_live_closes) - restored_ready_live_offset
        )
        assert epoch3_grid_decisions
        assert epoch3_grid_decisions == tuple(epoch3_live[restored_ready_live_offset:])
        expected_epoch3_history = plans_by_epoch[2]["grid"].minutes[
            restart_cut_2 - warmup_bars : restart_cut_2
        ]
        assert [row["close_time"] for row in epoch3_history] == [
            minute.close_time.isoformat().replace("+00:00", "Z")
            for minute in expected_epoch3_history
        ]
        assert epoch3_live[0]["close_time"] == expected_epoch3_live_closes[
            0
        ].isoformat().replace("+00:00", "Z")
        assert result["history_resume"]["source_epoch_id"] == 2
        assert result["history_resume"]["restored_bar_count"] == warmup_bars
        assert result["history_resume"]["last_close_time"] == epoch3_history[-1]["close_time"]
        assert result["history_resume"]["prior_grid_cursor_batch_id"] == (
            epoch2_grid_decisions[-1]["batch_id"]
        )
        assert result["history_resume"]["prior_run_order_intents"] == 0
        assert result["history_resume"]["run_order_intents_after"] == 0

        from backtrader.stores.execution_decision_journal import ExecutionDecisionJournal

        journal = ExecutionDecisionJournal(Path(config["live"]["journal_path"]))
        try:
            old_cursor = journal.grid_cursor(
                config["live"]["account_scope"],
                config["live"]["strategy_scope"],
                "alpha003:{}:1".format(config["cohort"]["calendar_id"]),
            )
            new_cursor = journal.grid_cursor(
                config["live"]["account_scope"],
                config["live"]["strategy_scope"],
                "alpha003:{}:2".format(config["cohort"]["calendar_id"]),
            )
            newest_cursor = journal.grid_cursor(
                config["live"]["account_scope"],
                config["live"]["strategy_scope"],
                "alpha003:{}:3".format(config["cohort"]["calendar_id"]),
            )
            assert old_cursor is not None and new_cursor is not None and newest_cursor is not None
            assert RUNNER._aware_datetime(old_cursor.close_time, "old cursor") == (
                RUNNER._aware_datetime(old_grid_decisions[-1]["close_time"], "old grid row")
            )
            assert old_cursor.ordinal == len(old_grid_decisions)
            assert RUNNER._aware_datetime(new_cursor.close_time, "new cursor") == (
                RUNNER._aware_datetime(epoch2_grid_decisions[-1]["close_time"], "new grid row")
            )
            assert new_cursor.ordinal == len(epoch2_grid_decisions)
            assert RUNNER._aware_datetime(newest_cursor.close_time, "newest cursor") == (
                RUNNER._aware_datetime(epoch3_grid_decisions[-1]["close_time"], "newest grid row")
            )
            assert newest_cursor.ordinal == len(epoch3_grid_decisions)
            assert journal.run_order_count(
                config["live"]["account_scope"],
                config["live"]["strategy_scope"],
                config["live"]["logical_run_id"],
            ) == 0
            budget = journal._connection.execute(
                "SELECT max_intents, intent_count FROM execution_run_order_budgets "
                "WHERE account_scope = ? AND strategy_scope = ? AND logical_run_id = ?",
                (
                    config["live"]["account_scope"],
                    config["live"]["strategy_scope"],
                    config["live"]["logical_run_id"],
                ),
            ).fetchone()
            assert budget is not None and tuple(budget) == (100, 0)
        finally:
            journal.close()

        previous_result = result
        previous_tape_rows = epoch3_rows
        for epoch_id in ((4, 5) if lineage_chain_only else ()):
            config["cohort"]["epoch_id"] = epoch_id
            config["inputs"]["history_decision_tape"] = previous_result[
                "decision_tape"
            ]["path"]
            config["output"]["decision_tape_path"] = str(
                tmp_path / "live-decisions-epoch-{}.jsonl".format(epoch_id)
            )
            next_result = run_saved_history_epoch()
            assert next_result["status"] == "LIVE_RUN_COMPLETE"
            assert next_result["epoch_id"] == epoch_id
            assert next_result["cleanup_complete"] is True
            assert api_clients[-1].closed is True
            next_rows = tuple(
                RUNNER.iter_decision_tape(
                    Path(next_result["decision_tape"]["path"]), max_bytes=50_000_000
                )
            )
            assert next_rows[0]["schema"] == RUNNER.DECISION_TAPE_SCHEMA
            assert (
                next_rows[0]["origin_partition_schema"]
                == RUNNER.SOURCE_ORIGIN_PARTITION_SCHEMA
            )
            next_decisions = next_rows[1:]
            previous_decisions = previous_tape_rows[1:]
            assert len(next_decisions) == config["factor"]["preheat_bars"] + 8
            assert all(row["epoch_id"] == epoch_id for row in next_decisions)
            history_decisions = next_decisions[: config["factor"]["preheat_bars"]]
            assert tuple(row["close_time"] for row in history_decisions) == tuple(
                row["close_time"]
                for row in previous_decisions[-config["factor"]["preheat_bars"] :]
            )
            for restored, original in zip(
                history_decisions,
                previous_decisions[-config["factor"]["preheat_bars"] :],
            ):
                for target, member in restored["members"].items():
                    original_member = original["members"][target]
                    assert member["source_role"] == "history"
                    assert member["connection_generation"] == original_member[
                        "connection_generation"
                    ]
                    assert member["feed_sequence"] == original_member["feed_sequence"]
                    assert member["bar_id"] == original_member["bar_id"]
                    assert member["raw_values"] == original_member["raw_values"]
                    assert member["origin_partition"] == original_member["origin_partition"]
            live_decisions = next_decisions[config["factor"]["preheat_bars"] :]
            assert len(live_decisions) == 8
            for row in live_decisions:
                for target, member in row["members"].items():
                    expected_source_ref = "ctp-live:{}:{}".format(
                        target,
                        current_plan["value"]["routes"][
                            current_plan["value"]["product_by_target"][target]
                        ],
                    )
                    assert member["source_role"] == "live"
                    assert member["connection_generation"] == f"epoch-{epoch_id}-generation-1"
                    assert member["source_ref"] == expected_source_ref
                    assert member["origin_partition"] == {
                        "schema": RUNNER.SOURCE_ORIGIN_PARTITION_SCHEMA,
                        "cohort_id": "alpha003:{}:{}".format(
                            config["cohort"]["calendar_id"], epoch_id
                        ),
                        "epoch_id": epoch_id,
                        "member_id": target,
                        "source_ref": expected_source_ref,
                        "source_role": "live",
                        "connection_generation": f"epoch-{epoch_id}-generation-1",
                    }
            assert next_result["history_resume"]["restored_bar_count"] == config[
                "factor"
            ]["preheat_bars"]
            assert next_result["history_resume"]["prior_run_order_intents"] == 0
            assert next_result["history_resume"]["run_order_intents_after"] == 0
            for row in history_decisions:
                assert not any(
                    action.get("action") in {"OPEN", "CLOSE", "CANCEL"}
                    for action in (row.get("order_plan") or {}).get("actions", ())
                )
            previous_result = next_result
            previous_tape_rows = next_rows
        return

    if selection_source == "ctp_query":
        assert result["status"] == "LIVE_EPOCH_SEQUENCE_COMPLETE"
        assert result["epoch_count"] == 2
        assert result["selection_source"] == "ctp_query_snapshot_equal_weight_v1"
        assert result["query_epoch_attempts"] == [1, 2]
        assert result["assembly_attempts"] == [1, 2]
        assert result["later_bundle_reads"] == []
        assert result["next_epoch_loaded"] is True
        assert len(api_clients) == 2
        assert all(client.closed for client in api_clients)
        # The public epoch result is itself the bounded readback surface. Do
        # the same strict JSON round trip as the CLI without serializing the
        # private plan object returned only to the epoch sequencer.
        result = json.loads(json.dumps(result, allow_nan=False))
        assert "_plan" not in result
        assert all("_plan" not in epoch for epoch in result["epochs"])
        assert trace.index(("api_closed", 1)) < trace.index(("api_created", 2))
        assert trace.index(("api_closed", 1)) < trace.index(("selection_catalog_query", 2))
        assert trace.index(("api_closed", 1)) < trace.index(("selection_depth_query", 2))
        for epoch_index, epoch in enumerate(result["epochs"]):
            expected_day = first_day if epoch_index == 0 else second_day
            expected_instruments = (
                {"M2612", "Y2612", "A2612"} if epoch_index == 0 else {"M2611", "Y2611", "A2611"}
            )
            assert epoch["epoch_id"] == epoch_index + 1
            assert epoch["retirement_proven"] is True
            assert epoch["selection_source"] == "ctp_query_snapshot_equal_weight_v1"
            assert epoch["simnow_profile"] == {
                "verified": True,
                "environment": "simnow",
                "profile": "set1_group1",
            }
            assert epoch["calendar_evidence_mode"] == "expected_rule_derived"
            calendar_rules_hash = epoch["calendar_rules_sha256"]
            assert isinstance(calendar_rules_hash, str) and len(calendar_rules_hash) == 64
            assert all(character in "0123456789abcdef" for character in calendar_rules_hash)
            assert epoch["trading_days"] == {"DCE": expected_day.isoformat()}
            assert epoch["engine_winddown_status"] == "STOPPED"
            assert epoch["strategy_shutdown_ready"] is True
            assert epoch["strategy_shutdown_post_join_confirmed"] is True
            assert epoch["cleanup_complete"] is True
            assert epoch["decision_tape"]["closed"] is True
            assert len(api_clients[epoch_index].context.catalog_rows) == 6
            assert len(api_clients[epoch_index].context.quote_rows) == 6
            assert api_clients[epoch_index].context.all_catalog_facts is True
            assert set(epoch["routes"]) == {"DCE.M", "DCE.Y", "DCE.A"}
            assert set(epoch["routes"].values()) == expected_instruments
            evidence = epoch["selection_evidence"]
            assert evidence["schema"] == "backtrader.alpha003_epoch_selection_evidence.v1"
            assert evidence["epoch_id"] == epoch["epoch_id"]
            assert evidence["selection_source"] == epoch["selection_source"]
            assert evidence["source_snapshot_id"] == epoch["source_snapshot_id"]
            assert evidence["routes"] == epoch["routes"]
            assert evidence["authorized_targets"] == ["DCE.M", "DCE.A"]
            manifest = evidence["manifest"]
            assert manifest["schema"] == "backtrader.futures_main_contract_manifest.v2"
            assert manifest["status"] == "READY"
            assert manifest["target_products"] == [
                {"exchange_id": "DCE", "product_id": product} for product in ("A", "M", "Y")
            ]
            assert (
                evidence["manifest_sha256"]
                == hashlib.sha256(RUNNER._canonical_json_bytes(manifest).rstrip(b"\n")).hexdigest()
            )
            binding = {
                key: evidence[key]
                for key in (
                    "schema",
                    "epoch_id",
                    "selection_source",
                    "selection_path",
                    "source_snapshot_id",
                    "manifest_sha256",
                    "routes",
                    "authorized_targets",
                    "selector_policy",
                    "grid_semantics_sha256",
                )
            }
            selection_plan = query_plans_by_snapshot_id[evidence["source_snapshot_id"]]
            grid_semantics = selection_plan["grid"].to_dict()
            grid_semantics.pop("decision_at")
            grid_semantics.pop("calendar_hashes")
            assert evidence["grid_semantics_sha256"] == hashlib.sha256(
                RUNNER._canonical_json_bytes(grid_semantics).rstrip(b"\n")
            ).hexdigest()
            assert (
                evidence["binding_sha256"]
                == hashlib.sha256(RUNNER._canonical_json_bytes(binding).rstrip(b"\n")).hexdigest()
            )
            assert len(RUNNER._canonical_json_bytes(evidence)) <= 50_000_000
            assert manifest["policy"]["ranking_mode"] == "ctp_query_snapshot_equal_weight_v1"
            assert manifest["policy"]["weights"] == {
                "open_interest": "0.5",
                "volume": "0.5",
            }
            assert manifest["policy"]["score_formula"] == "0.5 * open_interest + 0.5 * volume"
            assert manifest["query_snapshot"]["kind"] == (
                "CTP_CURRENT_DAY_QUERY_SNAPSHOT_NOT_FINALIZED_EOD"
            )
            query_snapshot = manifest["query_snapshot"]
            assert (
                manifest["source"]["snapshot_id"] == query_snapshot["quote_source"]["snapshot_id"]
            )
            assert (
                manifest["source"]["catalog"]["snapshot_id"]
                == query_snapshot["catalog_source"]["snapshot_id"]
            )
            assert epoch["source_snapshot_id"] == "{}|{}".format(
                query_snapshot["catalog_source"]["snapshot_id"],
                query_snapshot["quote_source"]["snapshot_id"],
            )
            assert query_snapshot["session"]["trading_day_after"] == expected_day.isoformat()
            for source_name in ("catalog_source", "quote_source"):
                source = query_snapshot[source_name]
                assert {
                    "source_id",
                    "snapshot_id",
                    "sha256",
                    "request_id",
                    "connection_generation",
                    "trading_day",
                    "started_at",
                    "completed_at",
                    "available_at",
                    "retrieved_at",
                    "complete",
                    "is_last_seen",
                    "record_count",
                } <= set(source)
                assert source["complete"] is True
                assert source["is_last_seen"] is True
                assert len(source["sha256"]) == 64
            assert len(manifest["calendars"]) == 1
            calendar = manifest["calendars"][0]
            assert calendar["evidence_mode"] == "expected_rule_derived"
            assert len(calendar["source_manifest_sha256"]) == 64
            catalog_rows = query_snapshot["catalog_records"]
            quote_rows = query_snapshot["quote_records"]
            assert len(catalog_rows) == len(quote_rows) == 6
            assert all(
                {"instrument_id", "product", "product_class", "is_trading", "expiry_date"}
                <= set(row)
                for row in catalog_rows
            )
            assert all(
                {"instrument_id", "exchange_id", "trading_day", "open_interest", "volume"}
                <= set(row)
                for row in quote_rows
            )
            assert len(manifest["candidates"]) == 6
            assert all(
                {
                    "instrument_id",
                    "open_interest",
                    "volume",
                    "ranking_score",
                    "quote_trading_day",
                    "action_day",
                    "update_time",
                    "update_millisec",
                }
                <= set(row)
                for row in manifest["candidates"]
            )
            quote_by_id = {row["instrument_id"]: row for row in quote_rows}
            for candidate in manifest["candidates"]:
                quote = quote_by_id[candidate["instrument_id"]]
                open_interest = Decimal(quote["open_interest"]["value"])
                volume = Decimal(quote["volume"]["value"])
                assert Decimal(candidate["ranking_score"]) == (open_interest + volume) / Decimal(
                    "2"
                )
            assert all(
                {"ranked_instrument_ids", "excluded_instrument_ids", "selected_instrument_id"}
                <= set(row)
                for row in manifest["products"]
            )
            for product_row in manifest["products"]:
                product = product_row["product"]
                target = f"{product['exchange_id']}.{product['product_id']}"
                assert evidence["routes"][target] == product_row["selected_instrument_id"]
            assert manifest["coverage"] == []
            assert len(manifest["query_coverage"]) == 3
            for coverage in manifest["query_coverage"]:
                product = coverage["product"]
                catalog_ids = {
                    row["instrument_id"] for row in catalog_rows if row["product"] == product
                }
                quote_ids = {
                    row["instrument_id"]
                    for row in quote_rows
                    if row["exchange_id"] == product["exchange_id"]
                    and row["instrument_id"].startswith(product["product_id"])
                }
                assert set(coverage["catalog_instrument_ids"]) == catalog_ids
                assert set(coverage["expected_quote_instrument_ids"]) == catalog_ids
                assert set(coverage["observed_quote_instrument_ids"]) == quote_ids == catalog_ids
            epoch_number = epoch["epoch_id"]
            assert trace.count(("selection_catalog_query", epoch_number)) == 1
            assert trace.count(("selection_depth_query", epoch_number)) == 1
            assert trace.count(("query_plan_ready", epoch["source_snapshot_id"])) == 1
            expected_decision_count = epoch["decision_tape_readback"]["record_count"]
            assert expected_decision_count > 100
            tape_rows = tuple(
                RUNNER.iter_decision_tape(
                    Path(epoch["decision_tape"]["path"]), max_bytes=50_000_000
                )
            )
            decisions = tape_rows[1:]
            assert len(decisions) == expected_decision_count
            assert all(set(row["members"]) == set(epoch["routes"]) for row in decisions)
            assert all(
                row["epoch_id"] == epoch_number
                and {target: member["instrument"] for target, member in row["members"].items()}
                == epoch["routes"]
                for row in decisions
            )
            assert all(
                member["source_role"] == "live"
                and member["complete"] is True
                and member["quality"] == "GOOD"
                for row in decisions
                for member in row["members"].values()
            )
            assert any(
                factor_value["value"]["finite"] is True
                for row in decisions
                for factor in row["factors"]["factors"].values()
                for factor_value in factor["values"].values()
            )
        assert result["epochs"][0]["routes"] != result["epochs"][1]["routes"]
        assert trace.index(("api_closed", 1)) < trace.index(("cohort_assembled", 2))
        return

    assert result["status"] == "LIVE_EPOCH_SEQUENCE_COMPLETE"
    assert result["epoch_count"] == 2
    assert result["assembly_attempts"] == [1, 2]
    assert result["later_bundle_reads"] == [str(second_bundle.resolve())]
    assert len(api_clients) == 2
    assert all(client.closed for client in api_clients)
    assert (
        trace.index(("run_live_returned", 1))
        < trace.index(("second_bundle_loaded", second_bundle.name))
        < trace.index(("api_created", 2))
        < trace.index(("cohort_assembled", 2))
    )
    assert trace.index(("api_closed", 1)) < trace.index(
        ("second_bundle_loaded", second_bundle.name)
    )

    old_routes = result["epochs"][0]["routes"]
    new_routes = result["epochs"][1]["routes"]
    assert set(old_routes) == set(new_routes) == {"DCE.M", "DCE.Y", "DCE.A"}
    assert all(old_routes[target] != new_routes[target] for target in old_routes)
    expected_decision_count = len(first_plan["grid"].minutes)
    assert expected_decision_count == 119
    for epoch in result["epochs"]:
        assert epoch["retirement_proven"] is True
        assert epoch["engine_winddown_status"] == "STOPPED"
        assert epoch["strategy_shutdown_ready"] is True
        assert epoch["strategy_shutdown_post_join_confirmed"] is True
        assert epoch["cleanup_complete"] is True
        assert epoch["decision_tape"]["closed"] is True
        assert epoch["decision_tape_readback"]["record_count"] == expected_decision_count
        path = Path(epoch["decision_tape"]["path"])
        rows = tuple(RUNNER.iter_decision_tape(path, max_bytes=50_000_000))
        decisions = rows[1:]
        assert len(decisions) == expected_decision_count
        assert all(row["epoch_id"] == epoch["epoch_id"] for row in decisions)
        assert all(set(row["members"]) == set(old_routes) for row in decisions)
        assert all(
            member["source_role"] == "live"
            and member["complete"] is True
            and member["quality"] == "GOOD"
            and {"open", "high", "low", "close", "volume", "openinterest"}.issubset(
                member["raw_values"]
            )
            for row in decisions
            for member in row["members"].values()
        )
        assert any(
            factor_value["value"]["finite"] is True
            for row in decisions
            for factor in row["factors"]["factors"].values()
            for factor_value in factor["values"].values()
        )


@pytest.mark.parametrize(
    ("evidence_owner", "field", "bad_value"),
    (
        ("strategy", "shutdown_requested", False),
        ("strategy", "shutdown_ready", False),
        ("strategy", "shutdown_blocker", "SHUTDOWN_OWNED_POSITION_OPEN:DCE.M"),
        ("strategy", "shutdown_post_join_confirmed", False),
        ("strategy", "shutdown_post_join_blocker", "SHUTDOWN_REFRESH_NOT_JOINED"),
        ("refresh", "shutdown_status", "BLOCKED"),
        ("refresh", "joined", False),
        ("engine", "live_bar_cohort_winddown_status", "TIMED_OUT"),
        ("engine", "live_bar_cohort_winddown_reason", "shutdown_deadline_expired"),
    ),
    ids=(
        "not-requested",
        "nonflat-or-unready",
        "strategy-blocker",
        "post-join-unconfirmed",
        "post-join-blocker",
        "refresh-blocked",
        "refresh-not-joined",
        "engine-status-drift",
        "engine-reason-drift",
    ),
)
def test_controlled_application_stop_requires_exact_post_join_proof(
    evidence_owner, field, bad_value
):
    from types import SimpleNamespace

    engine = SimpleNamespace(
        live_bar_cohort_winddown_status="NOT_REACHED",
        live_bar_cohort_winddown_reason="final_batch_not_reached",
    )
    strategy = SimpleNamespace(
        shutdown_requested=True,
        shutdown_ready=True,
        shutdown_blocker=None,
        shutdown_post_join_confirmed=True,
        shutdown_post_join_blocker=None,
    )
    refresh = SimpleNamespace(shutdown_status="PASS", joined=True)
    assert RUNNER._live_shutdown_path(engine, strategy, refresh) == (
        "controlled_application_stop"
    )

    owner = {"engine": engine, "strategy": strategy, "refresh": refresh}[evidence_owner]
    setattr(owner, field, bad_value)
    with pytest.raises(RUNNER.RunnerError) as error:
        RUNNER._live_shutdown_path(engine, strategy, refresh)
    assert error.value.code == "LIVE_CORE_WINDDOWN_NOT_CONFIRMED"
    assert error.value.detail == "{}:{}".format(
        engine.live_bar_cohort_winddown_status,
        engine.live_bar_cohort_winddown_reason,
    )


def _call_runner(capsys, *arguments):
    code = RUNNER.run(list(arguments))
    stdout = capsys.readouterr().out.strip().splitlines()[-1]
    return code, json.loads(stdout)


def test_live_capacity_evidence_stays_not_evaluated_after_clean_postflight():
    class _Capture:
        def report(self):
            return {
                "status": "RECORDED_NOT_EVALUATED",
                "acceptance_evaluated": False,
                "window_evaluation": "NOT_EVALUATED",
                "growth_evaluation": "NOT_EVALUATED",
                "issues": (),
            }

        def mark_callback_failure(self):
            raise AssertionError("callback failure was not observed")

    cleanup = [
        {"resource": "query_refresh", "joined": True},
        {"resource": "broker", "status": "PASS", "store_shutdown_state": "PASS"},
        {"resource": "store", "status": "RETURNED", "shutdown_state": "PASS"},
        {"resource": "journal", "status": "CLOSED"},
        {"resource": "decision_tape", "status": "CLOSED"},
    ]

    evidence = RUNNER._live_capacity_evidence(
        _Capture(),
        SimpleNamespace(_live_capacity_callback_failed=False),
        cleanup,
        run_id="synthetic-run",
        epoch_id=9,
        run_completed=True,
    )

    assert evidence["status"] == "RECORDED_NOT_EVALUATED"
    assert evidence["postflight"]["status"] == "OBSERVED"
    assert evidence["postflight"]["cleanup_complete"] is True
    assert evidence["acceptance_evaluated"] is False
    assert evidence["window_evaluation"] == "NOT_EVALUATED"
    assert evidence["growth_evaluation"] == "NOT_EVALUATED"


def test_live_capacity_callback_failure_keeps_postflight_report_incomplete():
    class _Capture:
        failed = False

        def mark_callback_failure(self):
            self.failed = True

        def report(self):
            return {
                "status": "INCOMPLETE" if self.failed else "RECORDED_NOT_EVALUATED",
                "acceptance_evaluated": False,
                "window_evaluation": "NOT_EVALUATED",
                "growth_evaluation": "NOT_EVALUATED",
                "issues": ("strategy_capacity_callback_failed",) if self.failed else (),
            }

    cleanup = [
        {"resource": "query_refresh", "joined": True},
        {"resource": "broker", "status": "PASS", "store_shutdown_state": "PASS"},
        {"resource": "store", "status": "RETURNED", "shutdown_state": "PASS"},
        {"resource": "journal", "status": "CLOSED"},
        {"resource": "decision_tape", "status": "CLOSED"},
    ]
    capture = _Capture()

    evidence = RUNNER._live_capacity_evidence(
        capture,
        SimpleNamespace(_live_capacity_callback_failed=True),
        cleanup,
        run_id="synthetic-run",
        epoch_id=9,
        run_completed=True,
    )

    assert evidence["status"] == "INCOMPLETE"
    assert evidence["postflight"]["status"] == "OBSERVED"
    assert "strategy_capacity_callback_failed" in evidence["issues"]


def test_saved_live_history_is_rejected_outside_live_mode(tmp_path, capsys):
    config = _base_config(tmp_path, "replay")
    config_path, config, _plan, minute_tape, _quotes = _write_source_inputs(tmp_path, config)
    config["inputs"]["history_decision_tape"] = str(minute_tape)
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    code, result = _call_runner(
        capsys, "--config", str(config_path), "--mode", "replay"
    )

    assert code == 2
    assert result["status"] == "BLOCKED"
    assert result["code"] == "LIVE_HISTORY_LIVE_MODE_REQUIRED"


def test_saved_live_history_rejects_daily_bundle_selection_before_provider(tmp_path):
    from types import SimpleNamespace

    config = {
        "inputs": {"history_decision_tape": str(tmp_path / "prior.jsonl")},
        "selection": {"source": "bundle", "daily_bundles": ["unused-next-day.json"]},
    }
    with pytest.raises(RUNNER.RunnerError) as error:
        RUNNER.run_live_epochs(
            config,
            tmp_path / "unused.yaml",
            None,
            "native",
            1,
            decision=SimpleNamespace(effective_tier="live"),
            allow_write_flag=False,
        )
    assert error.value.code == "LIVE_HISTORY_SELECTION_UNSUPPORTED"


def test_public_config_defaults_to_dry_and_cli_cannot_escalate(tmp_path, capsys):
    config_path = EXAMPLE / "config.yaml"
    code, result = _call_runner(capsys, "--config", str(config_path))
    assert code == 0
    assert result["status"] == "DRY_VALIDATION_COMPLETE"
    assert result["effective_tier"] == "dry"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert config["selection"]["source"] == "ctp_query"
    assert config["selection"]["bundle"] is None
    code, result = _call_runner(capsys, "--mode", "replay", "--config", str(config_path))
    assert code == 2
    assert result["code"] == "ENTRY_TIER_ESCALATION_DENIED"
    config["entry"]["tier"] = "replay"
    offline_config_path = tmp_path / "query-source-offline.yaml"
    offline_config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    code, result = _call_runner(capsys, "--mode", "research", "--config", str(offline_config_path))
    assert code == 2
    assert result["code"] == "OFFLINE_MODE_REQUIRES_SAVED_SELECTION_BUNDLE"
    code, result = _call_runner(
        capsys, "--mode", "dry", "--allow-write", "--config", str(config_path)
    )
    assert code == 2
    assert result["code"] == "ALLOW_WRITE_REQUIRES_LIVE_MODE"


def test_live_cli_json_never_serializes_private_selection_plan(tmp_path, monkeypatch, capsys):
    config = _base_config(tmp_path, "live")
    config_path = tmp_path / "cli-live.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    def live_with_internal_plan(_config, _config_path, plan, _factor_mode, _direction, **_kwargs):
        return {"status": "LIVE_RUN_COMPLETE", "_plan": plan}

    monkeypatch.setattr(RUNNER, "run_live", live_with_internal_plan)
    code, result = _call_runner(capsys, "--config", str(config_path))

    assert code == 0
    assert result["status"] == "LIVE_RUN_COMPLETE"
    assert "_plan" not in result
    assert "manifest" not in result


@pytest.mark.parametrize(
    ("error_kind", "expected_exit", "expected_status"),
    (
        ("runner", 2, "BLOCKED"),
        ("timeout", 1, "FAILED"),
    ),
    ids=("runner-error", "timeout-error"),
)
def test_live_cli_preserves_finite_epoch_failure_evidence_without_raw_context(
    tmp_path, monkeypatch, capsys, error_kind, expected_exit, expected_status
):
    config = _base_config(tmp_path, "live")
    config["live"]["account_scope"] = "private-config-marker"
    config_path = tmp_path / "cli-live-failure.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    plan = {
        "selection_path": Path(config["selection"]["bundle"]),
        "selection_source": "bundle",
        "source_snapshot_id": "synthetic-snapshot-v1",
        "targets": ("DCE.M",),
        "product_by_target": {"DCE.M": "DCE.M"},
        "routes": {"DCE.M": "M2611"},
    }
    expected_evidence = RUNNER._live_epoch_failure_evidence(config, plan, None, None, [])
    raw_exception_marker = "private raw exception text must stay hidden"

    def raise_live_failure(*_args, **_kwargs):
        if error_kind == "runner":
            error = RUNNER.RunnerError("LIVE_CORE_WINDDOWN_NOT_CONFIRMED", "TIMED_OUT")
        else:
            error = TimeoutError(raw_exception_marker)
        error.live_epoch_evidence = expected_evidence
        error.private_config_marker = "private-config-value"
        raise error

    monkeypatch.setattr(RUNNER, "load_market_plan", lambda *_args, **_kwargs: plan)
    monkeypatch.setattr(RUNNER, "run_live_epochs", raise_live_failure)

    code, result = _call_runner(capsys, "--config", str(config_path))

    assert code == expected_exit
    assert result["status"] == expected_status
    assert result["live_epoch_evidence"] == expected_evidence
    serialized = json.dumps(result, sort_keys=True)
    assert raw_exception_marker not in serialized
    assert "private-config-marker" not in serialized
    assert "private-config-value" not in serialized
    if error_kind == "runner":
        assert result["code"] == "LIVE_CORE_WINDDOWN_NOT_CONFIRMED"
    else:
        assert result["error_type"] == "TimeoutError"


def test_daily_rollover_loads_next_pit_bundle_only_after_retirement_proof(tmp_path, monkeypatch):
    from types import SimpleNamespace

    config_path, config, first_plan, second_path = _daily_test_inputs(tmp_path)
    events = []
    assembled = []

    real_load = RUNNER.load_market_plan

    def tracked_load(current_config, current_path, *, bundle_path=None):
        events.append(("load", Path(bundle_path).name))
        return real_load(current_config, current_path, bundle_path=bundle_path)

    def simulated_complete_epoch(
        epoch_config, _config_path, plan, _factor_mode, _direction, **_kwargs
    ):
        epoch_id = epoch_config["cohort"]["epoch_id"]
        events.append(("start", epoch_id))
        assembled.append((deepcopy(epoch_config), plan))
        # The live engine's returned contract is deliberately the full
        # retirement proof consumed by the production rollover gate. This
        # outer-loop test double does not stand in for the real run_live
        # composition exercised by the separate engine integration fixture.
        result = _complete_live_epoch_result(epoch_id, RUNNER._route_summary(plan))
        target = plan["targets"][0]
        instrument = RUNNER._route_summary(plan)[target]
        result["strategy_order_events"] = RUNNER._project_strategy_order_events(
            SimpleNamespace(
                order_events=deque(
                    [
                        {
                            "ref": 100 + epoch_id,
                            "status": "COMPLETED",
                            "instrument": instrument,
                            "executed_size": "1",
                            "executed_price": "100.0",
                        }
                    ],
                    maxlen=128,
                )
            ),
            plan,
            epoch_id,
        )
        events.append(("retired", epoch_id))
        return result

    monkeypatch.setattr(RUNNER, "load_market_plan", tracked_load)
    monkeypatch.setattr(RUNNER, "run_live", simulated_complete_epoch)
    decision = SimpleNamespace(effective_tier="live")

    result = RUNNER.run_live_epochs(
        config,
        config_path,
        first_plan,
        "native",
        1,
        decision=decision,
        allow_write_flag=False,
    )

    assert result["status"] == "LIVE_EPOCH_SEQUENCE_COMPLETE"
    assert result["epoch_count"] == 2
    assert result["assembly_attempts"] == [1, 2]
    assert result["later_bundle_reads"] == [str(second_path.resolve())]
    assert result["next_epoch_loaded"] is True
    assert events == [
        ("start", 1),
        ("retired", 1),
        ("load", second_path.name),
        ("start", 2),
        ("retired", 2),
    ]
    assert assembled[0][0]["cohort"]["epoch_id"] == 1
    assert assembled[1][0]["cohort"]["epoch_id"] == 2
    assert (
        assembled[0][0]["output"]["decision_tape_path"]
        != assembled[1][0]["output"]["decision_tape_path"]
    )
    assert set(assembled[0][1]["targets"]) == set(assembled[1][1]["targets"])
    old_routes = RUNNER._route_summary(assembled[0][1])
    new_routes = RUNNER._route_summary(assembled[1][1])
    assert all(old_routes[target] != new_routes[target] for target in old_routes)
    assert [row["strategy_order_events"]["events"][0]["epoch_id"] for row in result["epochs"]] == [
        1,
        2,
    ]
    assert all(row["strategy_shutdown_post_join_confirmed"] is True for row in result["epochs"])
    for row in result["epochs"]:
        event = row["strategy_order_events"]["events"][0]
        assert event["instrument"] == row["routes"][event["target"]]
        assert event["exchange"] == "DCE"


def test_daily_rollover_rejects_saved_bundle_policy_drift(tmp_path, monkeypatch):
    """A later PIT day cannot silently replace the frozen ranking policy."""
    from types import SimpleNamespace

    config_path, config, _first_plan, second_path = _daily_test_inputs(tmp_path)
    second_bundle = json.loads(second_path.read_text(encoding="utf-8"))
    second_bundle["policy"]["policy_id"] = "runner-fixture-different-policy-v1"
    _write_json(second_path, second_bundle)

    run_epochs = []

    def completed_epoch(epoch_config, _config_path, plan, _factor_mode, _direction, **_kwargs):
        epoch_id = epoch_config["cohort"]["epoch_id"]
        run_epochs.append(epoch_id)
        return _complete_live_epoch_result(epoch_id, RUNNER._route_summary(plan))

    monkeypatch.setattr(RUNNER, "run_live", completed_epoch)

    with pytest.raises(RUNNER.RunnerError) as caught:
        RUNNER.run_live_epochs(
            config,
            config_path,
            _first_plan,
            "native",
            1,
            decision=SimpleNamespace(effective_tier="live"),
            allow_write_flag=False,
        )

    assert caught.value.code == "DAILY_SELECTION_POLICY_CHANGED"
    assert run_epochs == [1]
    assert caught.value.assembly_attempts == (1,)
    assert caught.value.later_bundle_reads == (str(second_path.resolve()),)
    assert caught.value.next_epoch_load_permitted is False
    assert caught.value.epoch_results[0]["retirement_proven"] is True


def test_strategy_order_event_projection_keeps_exact_epoch_route_and_bounds(
    tmp_path,
):
    from types import SimpleNamespace

    config = _base_config(tmp_path, "live")
    config_path = tmp_path / "runner.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    plan = RUNNER.load_market_plan(config, config_path)
    target = plan["targets"][0]
    instrument = plan["routes"][plan["product_by_target"][target]]
    event = {
        "ref": 19,
        "status": "CANCELED",
        "instrument": instrument,
        "executed_size": "0",
        "executed_price": "0",
    }

    projection = RUNNER._project_strategy_order_events(
        SimpleNamespace(order_events=deque([event], maxlen=128)), plan, 4
    )
    assert projection["status"] == "AVAILABLE"
    assert projection["truncated"] is False
    assert projection["events"] == [
        {
            "epoch_id": 4,
            "target": target,
            "instrument": instrument,
            "exchange": "DCE",
            "ref": 19,
            "status": "CANCELED",
            "executed_size": "0",
            "executed_price": "0",
        }
    ]

    exact_route = RUNNER._project_strategy_order_events(
        SimpleNamespace(
            order_events=deque(
                [dict(event, instrument=(instrument, "DCE"), exchange="DCE")], maxlen=128
            )
        ),
        plan,
        4,
    )
    assert exact_route["status"] == "AVAILABLE"
    assert exact_route["events"][0]["instrument"] == instrument
    assert exact_route["events"][0]["exchange"] == "DCE"

    mismatched_exact_route = RUNNER._project_strategy_order_events(
        SimpleNamespace(
            order_events=deque(
                [dict(event, instrument=(instrument, "SHFE"), exchange="DCE")], maxlen=128
            )
        ),
        plan,
        4,
    )
    assert mismatched_exact_route["status"] == "BLOCKED"
    assert mismatched_exact_route["reason"] == "STRATEGY_ORDER_EVENT_ROUTE_UNBOUND"

    full = RUNNER._project_strategy_order_events(
        SimpleNamespace(order_events=deque([event] * 128, maxlen=128)), plan, 4
    )
    assert full["status"] == "AVAILABLE"
    assert full["retained_count"] == 128
    assert full["truncated"] is True

    unbound = RUNNER._project_strategy_order_events(
        SimpleNamespace(order_events=deque([dict(event, instrument="M9999")], maxlen=128)),
        plan,
        4,
    )
    assert unbound["status"] == "BLOCKED"
    assert unbound["reason"] == "STRATEGY_ORDER_EVENT_ROUTE_UNBOUND"


def test_daily_rollover_timeout_retains_old_route_evidence_and_never_loads_next(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    config_path, config, first_plan, second_path = _daily_test_inputs(tmp_path)
    load_attempts = []

    def forbidden_next_load(*_args, **kwargs):
        load_attempts.append(kwargs.get("bundle_path"))
        raise AssertionError("a later PIT bundle must not be loaded before old retirement")

    def unresolved_epoch(epoch_config, _config_path, plan, _factor_mode, _direction, **_kwargs):
        error = RUNNER.RunnerError("LIVE_CORE_WINDDOWN_NOT_CONFIRMED", "TIMED_OUT")
        error.live_epoch_evidence = {
            "epoch_id": epoch_config["cohort"]["epoch_id"],
            "selection_path": str(plan["selection_path"]),
            "routes": RUNNER._route_summary(plan),
            "engine_winddown_status": "TIMED_OUT",
            "engine_winddown_reason": "shutdown_deadline_expired",
            "strategy_shutdown_requested": True,
            "strategy_shutdown_ready": False,
            "strategy_shutdown_blocker": "SHUTDOWN_ORDER_TERMINAL_PENDING",
            "refresh_status": "BLOCKED",
            "refresh_blocker": "SHUTDOWN_ORDER_TERMINAL_PENDING",
            "refresh_error_code": None,
            "reconciliation_blockers": ["old_order_terminal_unproven"],
            "resource_shutdown": [],
            # Local clients can close normally after a remote UNKNOWN while
            # the old IDs/routes remain unresolved in the returned evidence.
            "cleanup_complete": True,
        }
        raise error

    monkeypatch.setattr(RUNNER, "load_market_plan", forbidden_next_load)
    monkeypatch.setattr(RUNNER, "run_live", unresolved_epoch)

    with pytest.raises(RUNNER.RunnerError) as caught:
        RUNNER.run_live_epochs(
            config,
            config_path,
            first_plan,
            "native",
            1,
            decision=SimpleNamespace(effective_tier="live"),
            allow_write_flag=False,
        )

    error = caught.value
    assert error.code == "LIVE_CORE_WINDDOWN_NOT_CONFIRMED"
    assert load_attempts == []
    assert error.epoch_results == ()
    assert error.assembly_attempts == (1,)
    assert error.later_bundle_reads == ()
    assert error.next_bundle_read_count == 0
    assert error.next_bundle_loaded is False
    assert error.next_epoch_load_permitted is False
    assert error.old_route_handling == "OLD_ROUTE_UNRESOLVED_LOCAL_RESOURCES_CLOSED"
    assert error.failed_epoch["engine_winddown_status"] == "TIMED_OUT"
    assert error.failed_epoch["strategy_shutdown_ready"] is False
    assert error.failed_epoch["strategy_shutdown_blocker"] == "SHUTDOWN_ORDER_TERMINAL_PENDING"
    assert error.failed_epoch["routes"] == RUNNER._route_summary(first_plan)
    assert error.failed_epoch["routes"]["DCE.M"] in {"M2611", "M2612"}
    assert str(second_path.resolve()) not in error.later_bundle_reads


def test_daily_rollover_requires_post_join_confirmation_after_engine_ready(tmp_path, monkeypatch):
    """A stale pre-join ready flag cannot authorize opening the next bundle."""
    from types import SimpleNamespace

    config_path, config, first_plan, second_path = _daily_test_inputs(tmp_path)
    load_attempts = []

    def forbidden_next_load(current_config, current_path, *, bundle_path=None):
        del current_config, current_path
        load_attempts.append(bundle_path)
        raise AssertionError("final post-join retirement must precede next bundle load")

    def session_changes_during_final_join(
        epoch_config, _config_path, plan, _factor_mode, _direction, **_kwargs
    ):
        # The Strategy was ready when the engine requested runstop. Its fresh
        # post-join projection observed a different current session and refused
        # retirement; this is the public run_live result consumed by the outer
        # daily selection gate.
        return {
            "status": "LIVE_RUN_COMPLETE",
            "epoch_id": epoch_config["cohort"]["epoch_id"],
            "routes": RUNNER._route_summary(plan),
            "shutdown_status": "PASS",
            # The engine-time shutdown check had already requested runstop.
            # Only the later, post-join projection sees this session change.
            "strategy_shutdown_ready": True,
            "strategy_shutdown_blocker": None,
            "strategy_shutdown_post_join_confirmed": False,
            "strategy_shutdown_post_join_blocker": "SHUTDOWN_RECONCILIATION_BLOCKED:session_identity_mismatch",
            "engine_winddown_status": "STOPPED",
            "engine_winddown_reason": "runstop_requested",
            "cleanup_complete": True,
            "live_capacity": {
                "status": "RECORDED_NOT_EVALUATED",
                "acceptance_evaluated": False,
                "window_evaluation": "NOT_EVALUATED",
                "growth_evaluation": "NOT_EVALUATED",
                "issues": (),
                "postflight": {"status": "OBSERVED", "retirement_proven": True},
            },
            "resource_shutdown": [
                {
                    "resource": "query_refresh",
                    "status": "RETURNED",
                    "started": True,
                    "joined": True,
                },
                {"resource": "broker", "status": "PASS", "store_shutdown_state": "PASS"},
                {"resource": "store", "status": "CLOSED_BY_BROKER", "shutdown_state": "PASS"},
                {"resource": "journal", "status": "CLOSED"},
                {"resource": "decision_tape", "status": "CLOSED"},
            ],
        }

    monkeypatch.setattr(RUNNER, "load_market_plan", forbidden_next_load)
    monkeypatch.setattr(RUNNER, "run_live", session_changes_during_final_join)

    with pytest.raises(RUNNER.RunnerError) as caught:
        RUNNER.run_live_epochs(
            config,
            config_path,
            first_plan,
            "native",
            1,
            decision=SimpleNamespace(effective_tier="live"),
            allow_write_flag=False,
        )

    error = caught.value
    assert error.code == "DAILY_EPOCH_RETIREMENT_UNPROVEN"
    assert load_attempts == []
    assert error.next_bundle_read_count == 0
    assert error.next_epoch_load_permitted is False
    assert error.failed_epoch["epoch_id"] == 1
    assert error.failed_epoch["engine_winddown_status"] == "STOPPED"
    assert error.failed_epoch["strategy_shutdown_ready"] is True
    assert error.failed_epoch["strategy_shutdown_post_join_confirmed"] is False
    assert (
        error.failed_epoch["strategy_shutdown_post_join_blocker"]
        == "SHUTDOWN_RECONCILIATION_BLOCKED:session_identity_mismatch"
    )
    assert error.failed_epoch["routes"] == RUNNER._route_summary(first_plan)
    capacity = error.failed_epoch["live_capacity"]
    assert capacity["status"] == "INCOMPLETE"
    assert capacity["postflight"]["status"] == "INCOMPLETE"
    assert capacity["postflight"]["retirement_proven"] is False
    assert "daily_epoch_retirement_unproven" in capacity["issues"]
    assert "daily_epoch_retirement_unproven" in capacity["postflight"]["issues"]
    assert str(second_path.resolve()) not in error.later_bundle_reads


def test_query_epoch_retirement_failure_preserves_incomplete_live_capacity(
    tmp_path, monkeypatch
):
    config = _base_config(tmp_path, "live")
    config_path, config, plan, _tape, _quotes = _write_source_inputs(tmp_path, config)
    config["selection"]["source"] = "ctp_query"
    config["selection"]["max_epochs"] = 1
    config["selection"]["daily_bundles"] = []
    capacity = {
        "status": "RECORDED_NOT_EVALUATED",
        "acceptance_evaluated": False,
        "window_evaluation": "NOT_EVALUATED",
        "growth_evaluation": "NOT_EVALUATED",
        "issues": (),
        "postflight": {"status": "OBSERVED", "retirement_proven": True},
    }
    forwarded = {}

    def unresolved_query_epoch(*_args, **kwargs):
        forwarded.update(kwargs)
        return {
            "_plan": plan,
            "status": "LIVE_RUN_COMPLETE",
            "engine_winddown_status": "STOPPED",
            "strategy_shutdown_ready": True,
            "strategy_shutdown_blocker": None,
            "strategy_shutdown_post_join_confirmed": False,
            "strategy_shutdown_post_join_blocker": "synthetic_retirement_unproven",
            "shutdown_status": "PASS",
            "resource_shutdown": [],
            "cleanup_complete": True,
            "live_capacity": capacity,
        }

    monkeypatch.setattr(RUNNER, "run_live", unresolved_query_epoch)
    with pytest.raises(RUNNER.RunnerError) as caught:
        RUNNER.run_live_epochs(
            config,
            config_path,
            None,
            "native",
            1,
            decision=SimpleNamespace(effective_tier="live"),
            allow_write_flag=False,
            _capture_live_capacity=True,
        )

    error = caught.value
    assert error.code == "DAILY_EPOCH_RETIREMENT_UNPROVEN"
    assert forwarded["_capture_live_capacity"] is True
    projected = error.failed_epoch["live_capacity"]
    assert projected["status"] == "INCOMPLETE"
    assert projected["postflight"]["status"] == "INCOMPLETE"
    assert projected["postflight"]["retirement_proven"] is False
    assert "daily_epoch_retirement_unproven" in projected["issues"]
    assert "daily_epoch_retirement_unproven" in projected["postflight"]["issues"]


def test_selection_is_recomputed_instead_of_trusting_serialized_claim(tmp_path):
    config = _base_config(tmp_path, "replay")
    config_path = tmp_path / "runner.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    plan = RUNNER.load_market_plan(config, config_path)
    assert plan["manifest"].status == "READY"
    assert plan["manifest"].selected_mapping() == tuple(
        (product, f"{product.product_id}2612")
        for product in sorted(PRODUCTS, key=lambda item: (item.exchange_id, item.product_id))
    )
    assert config["selection"]["bundle"] is not None


def test_research_uses_production_factor_strategy_and_full_planned_grid(tmp_path, capsys):
    config = _base_config(tmp_path, "research")
    config_path, config, plan, _tape, _quotes = _write_source_inputs(tmp_path, config)
    code, result = _call_runner(
        capsys, "--mode", "research", "--factor-mode", "native", "--config", str(config_path)
    )
    assert code == 0, result
    assert result["status"] == "RESEARCH_COMPLETE"
    assert result["factor_mode"] == "native"
    assert result["target_count"] == len(PRODUCTS)
    assert result["grid_count"] == len(plan["grid"].minutes)
    output_directory = Path(result["output_directory"])
    assert output_directory.is_dir()
    assert tuple(output_directory.glob("*.csv"))


def test_replay_executes_real_cerebro_orders_only_on_causal_later_bars(tmp_path, capsys):
    config = _base_config(tmp_path, "replay")
    config_path, _config, plan, _tape, _quotes = _write_source_inputs(tmp_path, config)
    code, result = _call_runner(
        capsys, "--mode", "replay", "--factor-mode", "native", "--config", str(config_path)
    )
    assert code == 0, result
    assert result["status"] == "REPLAY_COMPLETE"
    assert result["execution_mode"] == "LOCAL_BACKBROKER_CAUSAL_REPLAY"
    assert result["shutdown_status"] == "PASS"
    assert result["cohort_status"] == "COMPLETE"
    filled = [execution for order in result["orders"] for execution in order["executions"]]
    assert filled, json.dumps(result, indent=2)
    for execution in filled:
        assert execution["timing_verified"] is True
        assert execution["causal"] is True
        bar_start = datetime.fromisoformat(execution["bar_start"].replace("Z", "+00:00"))
        decision_available = datetime.fromisoformat(
            next(
                order["decision_available_at"]
                for order in result["orders"]
                if execution in order["executions"]
            ).replace("Z", "+00:00")
        )
        assert bar_start >= decision_available
    assert len(plan["grid"].minutes) > 30
    assert result["decision_tape_readback"]["record_count"] == len(plan["grid"].minutes)
    tape_rows = list(
        RUNNER.iter_decision_tape(
            Path(result["decision_tape"]["path"]),
            max_bytes=result["decision_tape"]["max_bytes"],
        )
    )
    assert tape_rows[0]["record_type"] == "HEADER"
    decisions = tape_rows[1:]
    assert len(decisions) == len(plan["grid"].minutes)
    assert all(row["header_record_id"] == tape_rows[0]["record_id"] for row in decisions)
    assert [row["close_time"] for row in decisions] == [
        minute.close_time.isoformat().replace("+00:00", "Z") for minute in plan["grid"].minutes
    ]
    for row in decisions:
        assert row["record_type"] == "DECISION"
        assert set(row["members"]) == set(plan["targets"])
        assert all(
            member["source_role"] == "history"
            and member["available_at"] >= member["close_time"]
            and set(RUNNER.OHLCV_FIELDS).issubset(member["raw_values"])
            for member in row["members"].values()
        )
        assert row["factors"]["factors"]
        assert row["order_plan"] is not None


def test_replay_rejects_late_quote_for_original_decision_and_tape_detects_tamper(tmp_path, capsys):
    config = _base_config(tmp_path, "replay")
    config_path, _config, plan, _tape, _quotes = _write_source_inputs(
        tmp_path, config, delayed_quote=True
    )
    code, result = _call_runner(
        capsys, "--mode", "replay", "--factor-mode", "native", "--config", str(config_path)
    )
    assert code == 0, result
    assert result["status"] == "REPLAY_COMPLETE"
    assert result["late_quote_count"] == 1
    rows = list(
        RUNNER.iter_decision_tape(
            Path(result["decision_tape"]["path"]),
            max_bytes=result["decision_tape"]["max_bytes"],
        )
    )
    first_plan = rows[1]["order_plan"]
    assert first_plan["status"] != "READY" or all(
        action["position_effect"] != "OPEN" for action in first_plan["actions"]
    )

    tape_path = Path(result["decision_tape"]["path"])
    raw = tape_path.read_bytes()
    tape_path.write_bytes(
        raw.replace(b"runner-minute-fixture-v1", b"tampered-minute-fixture-v1", 1)
    )
    with pytest.raises(RUNNER.RunnerError) as error:
        list(RUNNER.iter_decision_tape(tape_path, max_bytes=result["decision_tape"]["max_bytes"]))
    assert error.value.code == "DECISION_TAPE_RECORD_HASH_INVALID"


def test_decision_tape_requires_fresh_exclusive_bounded_destination(tmp_path):
    path = tmp_path / "tape.jsonl"
    writer = RUNNER.DecisionTapeWriter(
        path,
        50_000,
        mode="replay",
        factor_mode="native",
        direction=1,
        targets=("DCE.A",),
        calendar_id="fixture-calendar",
        grid_sha256="a" * 64,
        source_snapshot_id="fixture-source",
    )
    writer.close()
    with pytest.raises(RUNNER.RunnerError) as error:
        RUNNER.DecisionTapeWriter(
            path,
            50_000,
            mode="replay",
            factor_mode="native",
            direction=1,
            targets=("DCE.A",),
            calendar_id="fixture-calendar",
            grid_sha256="a" * 64,
            source_snapshot_id="fixture-source",
        )
    assert error.value.code == "DECISION_TAPE_CREATE_FAILED"

    undersized = tmp_path / "undersized.jsonl"
    with pytest.raises(RUNNER.RunnerError) as budget_error:
        RUNNER.DecisionTapeWriter(
            undersized,
            1,
            mode="replay",
            factor_mode="native",
            direction=1,
            targets=("DCE.A",),
            calendar_id="fixture-calendar",
            grid_sha256="a" * 64,
            source_snapshot_id="fixture-source",
        )
    assert budget_error.value.code == "DECISION_TAPE_BYTE_BUDGET_EXCEEDED"
    assert undersized.read_bytes() == b""


@pytest.mark.parametrize(
    ("failure", "expected_code", "write_enabled", "cleanup_complete"),
    (
        ("ready", "LIVE_CTP_SESSION_NOT_READY", False, True),
        ("ready_store_stop", "LIVE_CTP_SESSION_NOT_READY", False, False),
        ("grid_expired", "LIVE_GRID_HAS_NO_REMAINING_COMMON_MINUTES", False, True),
        ("grid_boundary", "LIVE_CTP_SESSION_NOT_READY", False, True),
        ("grid_remaining", "LIVE_CTP_SESSION_NOT_READY", False, True),
        ("grid_crossing", "COHORT_HAS_NO_PLANNED_SLOTS", False, True),
        ("refresh", "LIVE_INITIAL_QUERY_REFRESH_FAILED", True, True),
        ("arm", "RuntimeError", True, True),
    ),
)
def test_live_setup_failures_close_every_created_resource(
    tmp_path, monkeypatch, failure, expected_code, write_enabled, cleanup_complete
):
    from types import SimpleNamespace

    import backtrader as bt
    import backtrader.brokers.btapibroker as broker_module
    import backtrader.stores.execution_decision_journal as journal_module
    import backtrader.stores.factor_execution as coordinator_module
    import backtrader.stores.registered_sim as store_module

    config = _base_config(tmp_path, "live")
    config_path = tmp_path / "live.yaml"
    config["cohort"].update(max_live_bar_age_seconds=60, max_future_skew_seconds=0)
    config["live"].update(
        account_scope="fixture-account",
        strategy_scope="fixture-strategy",
        logical_run_id=f"fixture-{failure}",
        journal_path=str(tmp_path / f"{failure}.sqlite"),
        ready_timeout_seconds=1,
        refresh_timeout_seconds=1,
        refresh_overall_timeout_seconds=2,
        refresh_interval_seconds=0.1,
        quote_max_age_seconds=60,
        query_max_age_seconds=60,
        shutdown_grace_seconds=1,
        store_config_env="BT_ALPHA003_TEST_CONFIG_JSON",
    )
    config["live"]["allow_writes"] = write_enabled
    store_config, api_kwargs = _official_simnow_store_config()
    config["output"].update(
        decision_tape_path=str(tmp_path / f"{failure}-decisions.jsonl"),
        decision_tape_max_bytes=1_000_000,
    )
    if write_enabled:
        # Every write-enabled fixture needs the independent guard policy,
        # unless that particular case explicitly tests the missing-policy
        # preflight above.  This helper builds running/live setups rather
        # than configuration-validation failures.
        config["live"].update(
            loss_guard_net_loss_threshold=1000,
            loss_guard_max_observation_age_seconds=30,
        )
        config["risk"].update(
            policy_id="fake-live-risk-v1",
            max_hold_eligible_bars=12,
            preclose_grace_seconds=120,
            run_end_policy="CLOSE_ALL",
            quote_max_age_seconds=60,
            max_state_age_seconds=60,
            max_notional_per_position="100000",
            max_total_notional="300000",
            max_margin_per_position="10000",
            max_total_margin="30000",
            max_loss_per_position="10000",
            max_total_loss="20000",
            round_trip_fee_upper_bound_per_contract="1.00",
            stop_loss_ticks=1,
            max_order_intents_per_grid=2,
            max_order_intents_per_run=20,
        )
        config["live"]["arm_templates"] = [
            {
                "target": target,
                "md_front": store_config["md_address"],
                "strategy_identity_sha256": "a" * 64,
                "execution_cycle_id": f"cycle-{target}",
                "preflight_sha256": "b" * 64,
            }
            for target in (f"DCE.{product.product_id}" for product in PRODUCTS)
        ]
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    plan = RUNNER.load_market_plan(config, config_path)
    monkeypatch.setenv(
        "BT_ALPHA003_TEST_CONFIG_JSON",
        json.dumps({"config": store_config, "api_kwargs": api_kwargs}),
    )
    last_bucket_start = plan["grid"].minutes[-1].close_time - timedelta(minutes=1)
    later_bucket_start = last_bucket_start + timedelta(microseconds=1)
    if failure == "grid_expired":
        clock_now = later_bucket_start
    elif failure == "grid_boundary":
        clock_now = last_bucket_start
    elif failure == "grid_remaining":
        clock_now = last_bucket_start - timedelta(minutes=1)
    else:
        clock_now = DECISION_AT
    clock_calls = {"count": 0}

    class FixedClock:
        def utc_now(self):
            if failure == "grid_crossing":
                clock_calls["count"] += 1
                return last_bucket_start if clock_calls["count"] == 1 else later_bucket_start
            return clock_now

    monkeypatch.setattr(RUNNER, "RunnerWallClock", FixedClock)

    closed = []
    lifecycle = []
    constructed = []

    class FakeStore:
        registered_sim_route_id = "simnow-registered-v1"
        sdk_api = None

        def __init__(self, **kwargs):
            self.options = kwargs
            self.api_kwargs = kwargs.get("api_kwargs")
            assert isinstance(self.api_kwargs, dict)
            assert self.api_kwargs.get("ctp_join_observer") is False
            self.join_required = self.api_kwargs["ctp_join_observer"]
            self.factor_source_enabled = False
            self.expected_md_generation = None
            self.expected_trader_generation = None

        def getdata(self, **kwargs):
            return SimpleNamespace(name=kwargs["dataname"])

        def registered_sim_wait_ready(self, timeout):
            lifecycle.append("session_ready")
            return failure not in {
                "ready",
                "ready_store_stop",
                "grid_boundary",
                "grid_remaining",
            }

        def registered_sim_login_facts(self):
            lifecycle.append("login_facts")
            return {
                "read_only_ready": True,
                "trading_ready": True,
                "trading_day": "20261021",
                "connection_generation": 1,
            }

        def enable_ctp_factor_tick_source(self):
            lifecycle.append("factor_tick_source_enabled")
            self.factor_source_enabled = True
            self.expected_md_generation = 1
            self.expected_trader_generation = 1
            return 1

        @staticmethod
        def _synthetic_stop_receipt(generation, join_required):
            # This test-only receipt matches the public shutdown projection
            # shape; it does not exercise or establish native SDK cleanup.
            return {
                "connection_generation": generation,
                "join_required": join_required,
                "join_completed": join_required,
                "native_released": True,
                "thread_alive": False,
                "timed_out": False,
                "complete": True,
            }

        def _source_shutdown_receipt(self):
            lifecycle.append("source_shutdown_receipt_projected")
            return {
                "required": True,
                "status": "PASS",
                "expected_md_generation": self.expected_md_generation,
                "expected_trader_generation": self.expected_trader_generation,
                "join_required": self.join_required,
                "md_receipt": self._synthetic_stop_receipt(
                    self.expected_md_generation, self.join_required
                ),
                "trader_receipt": self._synthetic_stop_receipt(
                    self.expected_trader_generation, self.join_required
                ),
                "reason_codes": (),
            }

        def registered_sim_configure_arm_templates(self, templates):
            lifecycle.append("arm_templates")
            if failure == "arm":
                raise RuntimeError("fake arm configuration failure")

        def stop(self):
            closed.append("store")
            if failure == "ready_store_stop":
                raise RuntimeError("fake Store close failure")
            result = {"shutdown_state": "PASS"}
            if self.factor_source_enabled:
                result["ctp_factor_source_shutdown"] = self._source_shutdown_receipt()
            return result

    class FakeBroker:
        def __init__(self, *, store, **kwargs):
            constructed.append("broker")
            self.store = store

        def get_shutdown_summary(self):
            return {"status": "NOT_STARTED", "store_shutdown_state": "UNPROVEN"}

    class FakeJournal:
        def __init__(self, path, *, max_payload_bytes):
            assert max_payload_bytes == 131072
            constructed.append("journal")
            self.path = path
            self.max_payload_bytes = max_payload_bytes
            self._fee_pair_scope = None

        def close(self):
            closed.append("journal")

        def source_highwater(self, *args, **kwargs):
            del args, kwargs
            return None

        def register_fee_pair_required_scope(self, account_scope, strategy_scope):
            # Production run_live arms this fence before any provider work and
            # reads it back; return the real immutable projection type so the
            # runner's exact-type readback proof passes.
            from backtrader.stores.execution_decision_journal import (
                ExecutionFeePairScopeRegistration,
            )

            self._fee_pair_scope = ExecutionFeePairScopeRegistration(
                account_scope=account_scope,
                strategy_scope=strategy_scope,
                policy_id="REQUIRE_PAIR_FEE_V1",
                state="REQUIRE_PAIR_FAIL_CLOSED",
                registered_at_ns=1,
            )
            return self._fee_pair_scope

        def fee_pair_required_scope(self, account_scope, strategy_scope):
            if self._fee_pair_scope is None:
                return None
            assert self._fee_pair_scope.account_scope == account_scope
            assert self._fee_pair_scope.strategy_scope == strategy_scope
            return self._fee_pair_scope

    class FakeCoordinator:
        def __init__(self, broker, journal, **kwargs):
            self.broker = broker
            self.journal = journal
            broker.factor_execution_coordinator = self

    class FakeCerebro:
        def __init__(self, **kwargs):
            pass

        def setbroker(self, broker):
            self.broker = broker

        def adddata(self, data, name=None):
            return data

        def add_live_bar_cohort(self, cohort, *, clock, winddown_timeout_seconds=0):
            self.cohort = cohort
            self.clock = clock
            self.winddown_timeout_seconds = winddown_timeout_seconds

        def addstrategy(self, strategy, **kwargs):
            self.strategy = strategy

        def wake_live_bar_cohort(self):
            return True

        def runstop(self):
            return None

        def run(self, **kwargs):
            raise AssertionError("setup failure should occur before Cerebro.run")

    class FakeCohort:
        def __init__(self, calendar):
            assert calendar is not None
            self._calendar = calendar

        @property
        def calendar_fingerprint(self):
            return self._calendar.fingerprint

        def register_member(self, *args, **kwargs):
            return None

        def seal(self):
            return None

    class FakeRefreshLoop:
        def __init__(self, *args, **kwargs):
            lifecycle.append("refresh_loop_created")
            self.started = False
            self.joined = False
            self.last_receipt = None
            self.last_error_code = None
            self.shutdown_status = "NOT_REQUESTED"
            self.shutdown_blocker = None

        def refresh_once(self):
            lifecycle.append("facts_refresh")
            if failure == "refresh":
                raise RuntimeError("fake query refresh failure")
            self.last_error_code = None

        def _execution_error_code(self, error):
            return type(error).__name__

        def refresh_initial(self, *, wait_timeout):
            del wait_timeout
            return self.refresh_once()

        def start(self):
            self.started = True

        def stop_and_join(self):
            self.joined = True
            closed.append("query_refresh")
            return True

    monkeypatch.setattr(store_module, "RegisteredSimStore", FakeStore)
    monkeypatch.setattr(broker_module, "BtApiBroker", FakeBroker)
    monkeypatch.setattr(journal_module, "ExecutionDecisionJournal", FakeJournal)
    monkeypatch.setattr(coordinator_module, "FactorExecutionCoordinator", FakeCoordinator)
    monkeypatch.setattr(bt, "Cerebro", FakeCerebro)
    monkeypatch.setattr(RUNNER, "QueryRefreshLoop", FakeRefreshLoop)
    original_make_cohort = RUNNER._make_cohort

    def make_cohort(*args, **kwargs):
        if failure == "grid_crossing":
            return original_make_cohort(*args, **kwargs)
        return FakeCohort(kwargs["calendar_override"])

    monkeypatch.setattr(RUNNER, "_make_cohort", make_cohort)
    monkeypatch.setattr(RUNNER, "_make_strategy_kwargs", lambda *args, **kwargs: {})
    decision = SimpleNamespace(effective_tier="live")

    with pytest.raises(Exception) as error:
        RUNNER.run_live(
            config,
            config_path,
            plan,
            "native",
            1,
            decision=decision,
            allow_write_flag=write_enabled,
        )

    if expected_code == "RuntimeError":
        assert type(error.value).__name__ == expected_code
    else:
        assert getattr(error.value, "code", None) == expected_code
    cleanup = error.value.cleanup_results
    assert RUNNER._cleanup_complete(cleanup) is cleanup_complete
    by_resource = {row["resource"]: row for row in cleanup}
    source_enabled_failures = {"grid_crossing", "refresh", "arm"}
    # run_live now opens the journal (and, in write mode, arms the fee-pair
    # scope fence) before the remaining-grid preflight, so even an expired
    # read-only grid has a journal to close while no tape or broker exists.
    readiness_failures_after_journal = {
        "grid_remaining",
        "grid_boundary",
        "ready",
        "ready_store_stop",
        "grid_crossing",
        "grid_expired",
    }
    if failure in readiness_failures_after_journal:
        assert by_resource["decision_tape"]["status"] == "NOT_CREATED"
        assert by_resource["journal"]["status"] == "CLOSED"
        assert constructed == ["journal"]
        assert not Path(config["output"]["decision_tape_path"]).exists()
    else:
        assert by_resource["decision_tape"]["status"] == "CLOSED"
        assert by_resource["journal"]["status"] == "CLOSED"
        assert "journal" in constructed
    if failure == "ready_store_stop":
        assert by_resource["store"]["status"] == "FAILED"
        assert "ctp_factor_source_shutdown" not in by_resource["store"]
    else:
        assert by_resource["store"]["shutdown_state"] == "PASS"
    if failure in source_enabled_failures:
        assert RUNNER._ctp_factor_source_shutdown_complete(None) is True
        source_receipt = by_resource["store"]["ctp_factor_source_shutdown"]
        expected_native_receipt = {
            "connection_generation": 1,
            "join_required": False,
            "join_completed": False,
            "native_released": True,
            "thread_alive": False,
            "timed_out": False,
            "complete": True,
        }
        assert source_receipt == {
            "required": True,
            "status": "PASS",
            "expected_md_generation": 1,
            "expected_trader_generation": 1,
            "join_required": False,
            "md_receipt": expected_native_receipt,
            "trader_receipt": expected_native_receipt,
            "reason_codes": (),
        }
        assert lifecycle.index("factor_tick_source_enabled") < lifecycle.index(
            "source_shutdown_receipt_projected"
        )

        missing_source_projection = RUNNER._store_stop_evidence(
            {"shutdown_state": "PASS"}, ctp_factor_source_required=True
        )
        assert missing_source_projection == {
            "shutdown_state": "PASS",
            "ctp_factor_source_shutdown": {"required": True, "status": "UNPROVEN"},
        }
        missing_receipt = [
            (
                {**row, **missing_source_projection}
                if row["resource"] == "store"
                else dict(row)
            )
            for row in cleanup
        ]
        assert RUNNER._cleanup_complete(missing_receipt) is False
        incomplete_receipt = [
            {
                **row,
                **(
                    {"ctp_factor_source_shutdown": {"required": True, "status": "INCOMPLETE"}}
                    if row["resource"] == "store"
                    else {}
                ),
            }
            for row in cleanup
        ]
        assert RUNNER._cleanup_complete(incomplete_receipt) is False
    if failure == "grid_expired":
        assert "store" in closed
        assert lifecycle == []
    elif failure in readiness_failures_after_journal:
        assert by_resource["broker"]["status"] == "NOT_CREATED"
    else:
        assert by_resource["broker"]["status"] == "NOT_RUN"
    if failure in {
        "ready",
        "ready_store_stop",
        "grid_expired",
        "grid_boundary",
        "grid_remaining",
        "grid_crossing",
        "arm",
    }:
        assert by_resource["query_refresh"]["status"] == "NOT_CREATED"
    else:
        assert by_resource["query_refresh"]["joined"] is True
        assert by_resource["query_refresh"]["status"] == "RETURNED"
        assert "query_refresh" in closed
    assert "store" in closed
    assert "journal" in closed
    if failure in {"ready", "ready_store_stop", "grid_boundary", "grid_remaining"}:
        assert lifecycle == ["session_ready"]
    elif failure == "grid_expired":
        assert lifecycle == []
    elif failure == "grid_crossing":
        assert lifecycle == [
            "session_ready",
            "factor_tick_source_enabled",
            "login_facts",
            "source_shutdown_receipt_projected",
        ]
    if failure == "grid_crossing":
        assert clock_calls["count"] == 2
    elif failure == "arm":
        assert lifecycle == [
            "session_ready",
            "factor_tick_source_enabled",
            "login_facts",
            "login_facts",
            "arm_templates",
            "source_shutdown_receipt_projected",
        ]
    elif failure == "refresh":
        assert lifecycle == [
            "session_ready",
            "factor_tick_source_enabled",
            "login_facts",
            "login_facts",
            "arm_templates",
            "refresh_loop_created",
            "facts_refresh",
            "source_shutdown_receipt_projected",
        ]


def test_live_source_continuity_treats_empty_tape_as_not_applicable():
    class EmptyTape:
        @staticmethod
        def summary():
            return {"record_count": 0}

    class NoHighwaterRead:
        @staticmethod
        def source_highwater(*_args, **_kwargs):
            raise AssertionError("empty tape must not require a journal anchor")

    assert RUNNER._live_source_continuity_status(
        NoHighwaterRead(),
        {},
        EmptyTape(),
        None,
    ) == {
        "status": "NOT_APPLICABLE",
        "available": False,
        "record_count": 0,
        "failure_count": 0,
        "first_error": None,
        "final_highwater_matches_tape": None,
        "reason": "NO_ROWS",
    }


def test_replay_clock_ignores_quotes_past_the_next_slot_deadline(tmp_path):
    config = _base_config(tmp_path, "replay")
    config_path, config, plan, _raw_tape, _quotes = _write_source_inputs(
        tmp_path, config, delayed_quote=True
    )
    tape = RUNNER.load_minute_tape(Path(config["inputs"]["minute_tape"]), plan, config["cohort"])
    _, timely_quotes = RUNNER._quote_tape(
        Path(config["inputs"]["execution_quotes"]),
        plan,
        config["cohort"],
    )
    schedule, late_count = RUNNER._replay_clock_schedule(plan["grid"], tape, timely_quotes)
    assert late_count == 1
    first_close = plan["grid"].minutes[0].close_time
    first_available = max(
        event["available_at"]
        for target in plan["targets"]
        for event in tape["events"][target]
        if event["bucket_end"] == first_close
    )
    assert schedule[0] == first_available + timedelta(seconds=2)


def test_live_write_grant_requires_mode_config_and_live_entry_tier():
    from types import SimpleNamespace

    config = yaml.safe_load((EXAMPLE / "config.yaml").read_text(encoding="utf-8"))
    config["live"]["allow_writes"] = False
    with pytest.raises(RUNNER.RunnerError) as error:
        RUNNER._write_requested(config, True, SimpleNamespace(effective_tier="live"))
    assert error.value.code == "LIVE_WRITE_GRANT_MISSING_IN_CONFIG"
    config["live"]["allow_writes"] = True
    with pytest.raises(RUNNER.RunnerError) as error:
        RUNNER._write_requested(config, True, SimpleNamespace(effective_tier="replay"))
    assert error.value.code == "LIVE_WRITE_TIER_REQUIRED"
    assert RUNNER._write_requested(config, True, SimpleNamespace(effective_tier="live"))


def test_run_loss_policy_is_explicit_for_writes_and_inert_for_read_only():
    config = yaml.safe_load((EXAMPLE / "config.yaml").read_text(encoding="utf-8"))
    config["risk"]["max_total_loss"] = "20000"
    config["live"]["loss_guard_net_loss_threshold"] = 1000
    config["live"]["loss_guard_max_observation_age_seconds"] = 30

    assert RUNNER._run_loss_guard_policy(config, write_enabled=True) == (Decimal("1000"), 30)
    assert RUNNER._run_loss_guard_policy(config, write_enabled=False) == (None, None)

    config["live"]["loss_guard_net_loss_threshold"] = None
    config["live"]["loss_guard_max_observation_age_seconds"] = None
    assert RUNNER._run_loss_guard_policy(config, write_enabled=False) == (None, None)
    with pytest.raises(RUNNER.RunnerError) as missing:
        RUNNER._run_loss_guard_policy(config, write_enabled=True)
    assert missing.value.code == "LIVE_RUN_LOSS_POLICY_REQUIRED"

    config["live"]["loss_guard_net_loss_threshold"] = "not-a-threshold"
    config["live"]["loss_guard_max_observation_age_seconds"] = 30
    with pytest.raises(RUNNER.RunnerError) as invalid_threshold:
        RUNNER._run_loss_guard_policy(config, write_enabled=True)
    assert invalid_threshold.value.code == "LIVE_RUN_LOSS_POLICY_INVALID"

    config["live"]["loss_guard_net_loss_threshold"] = True
    config["live"]["loss_guard_max_observation_age_seconds"] = 30
    with pytest.raises(RUNNER.RunnerError) as boolean_threshold:
        RUNNER._run_loss_guard_policy(config, write_enabled=True)
    assert boolean_threshold.value.code == "LIVE_RUN_LOSS_POLICY_INVALID"

    config["live"]["loss_guard_net_loss_threshold"] = 1000
    config["live"]["loss_guard_max_observation_age_seconds"] = True
    with pytest.raises(RUNNER.RunnerError) as invalid_age:
        RUNNER._run_loss_guard_policy(config, write_enabled=True)
    assert invalid_age.value.code == "LIVE_RUN_LOSS_POLICY_INVALID"

    config["live"]["loss_guard_max_observation_age_seconds"] = 30
    config["live"]["loss_guard_net_loss_threshold"] = Decimal("7" * 256)
    assert RUNNER._run_loss_guard_policy(config, write_enabled=True) == (
        Decimal("7" * 256),
        30,
    )

    config["live"]["loss_guard_net_loss_threshold"] = Decimal("7" * 257)
    with pytest.raises(RUNNER.RunnerError) as precision_overflow:
        RUNNER._run_loss_guard_policy(config, write_enabled=True)
    assert precision_overflow.value.code == "LIVE_RUN_LOSS_POLICY_INVALID"

    for value in (Decimal("1E1001"), Decimal("1E-1001")):
        config["live"]["loss_guard_net_loss_threshold"] = value
        with pytest.raises(RUNNER.RunnerError) as exponent_overflow:
            RUNNER._run_loss_guard_policy(config, write_enabled=True)
        assert exponent_overflow.value.code == "LIVE_RUN_LOSS_POLICY_INVALID"

    for value in (Decimal("1E1000"), Decimal("1E-1000")):
        config["live"]["loss_guard_net_loss_threshold"] = value
        assert RUNNER._run_loss_guard_policy(config, write_enabled=True) == (value, 30)


def test_write_enabled_strategy_kwargs_forward_the_separate_loss_guard_policy():
    product = ProductKey("SHFE", "rb")
    config = {
        "live": {"strategy_scope": "alpha003-live"},
        "cohort": {
            "calendar_id": "calendar-v1",
            "max_pending_slots": 8,
            "max_window_bars": 512,
            "wait_timeout_seconds": 5.0,
        },
        "factor": {"preheat_bars": 30, "rebalance_every": 5},
    }
    plan = {
        "routes": {product: "rb2510"},
        "product_by_target": {"SHFE.rb": product},
        "authorized_targets": ("SHFE.rb",),
        "session_calendars": {},
    }
    policy = object()

    kwargs = RUNNER._make_strategy_kwargs(
        config,
        plan,
        "native",
        1,
        policy,
        replay=False,
        cohort=object(),
        account_scope="account-scope",
        logical_run_id="logical-run",
        execution_enabled=True,
        loss_guard_net_loss_threshold=Decimal("1000"),
        loss_guard_max_observation_age_seconds=30,
    )

    assert kwargs["execution_enabled"] is True
    assert kwargs["risk_policy"] is policy
    assert kwargs["live_capacity_callback"] is None
    assert kwargs["loss_guard_net_loss_threshold"] == Decimal("1000")
    assert kwargs["loss_guard_max_observation_age_seconds"] == 30


def test_copied_folder_dry_entry_needs_no_sibling_example_import(tmp_path):
    copied = tmp_path / "copied-alpha003-example"
    copied.mkdir()
    for name in ("run.py", "config.yaml", "entry_tier.py"):
        shutil.copyfile(EXAMPLE / name, copied / name)
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    command = [sys.executable, str(copied / "run.py"), "--config", str(copied / "config.yaml")]
    process = subprocess.run(
        command,
        cwd=copied,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout.strip().splitlines()[-1])
    assert result["status"] == "DRY_VALIDATION_COMPLETE"


def _typed_local_shutdown_facts(now, targets, *, strategy_scope, nonflat=False):
    """Build explicit local-simulation facts for real Strategy/Cerebro wiring."""
    from backtrader.stores.factor_execution_facts import (
        FactorExecutionAccountFacts,
        FactorExecutionFacts,
        FactorExecutionInstrumentFacts,
        FactorExecutionPositionFacts,
        FactorExecutionQueryFact,
        FactorExecutionQuoteFacts,
        FactorExecutionRouteFacts,
        _query_set_identifier,
    )

    families = (
        ("account_result", "account"),
        ("orders_result", "orders"),
        ("trades_result", "trades"),
        ("instruments_result", "instruments"),
        ("positions_result", "positions"),
    )
    fingerprint = "local-simulation-account-v1"
    query_provenance = tuple(
        FactorExecutionQueryFact(
            family=family,
            request_type=request_type,
            request_id=index,
            connection_generation=1,
            account_fingerprint=fingerprint,
            trading_day=CURRENT_DAY.isoformat(),
            started_at=now - timedelta(microseconds=1),
            completed_at=now,
            source_owned=True,
            query_complete=True,
            scope_complete=True,
            row_count=0,
        )
        for index, (family, request_type) in enumerate(families, 1)
    )
    snapshot_id = "local-shutdown-query-set-v1"
    query_set_id = _query_set_identifier(
        fingerprint,
        1,
        CURRENT_DAY.isoformat(),
        now - timedelta(microseconds=1),
        now,
        tuple((family, index) for index, (family, _request_type) in enumerate(families, 1)),
    )
    account = FactorExecutionAccountFacts(
        account_scope="local-shutdown-fixture",
        snapshot_id=snapshot_id,
        available_at=now,
        route_permitted=True,
        available_margin=Decimal("1000000"),
        used_margin=Decimal(0),
        current_notional=Decimal(0),
        current_worst_case_loss=Decimal(0),
        account_fingerprint=fingerprint,
        connection_generation=1,
        trading_day=CURRENT_DAY.isoformat(),
    )
    positions = []
    quotes = []
    instruments = []
    routes = []
    for index, item in enumerate(targets, 1):
        quantity = Decimal(1) if nonflat and index == 1 else Decimal(0)
        positions.append(
            FactorExecutionPositionFacts(
                target_id=item.target_id,
                instrument=item.instrument,
                exchange=item.exchange,
                quantity=quantity,
                snapshot_id=snapshot_id,
                available_at=now,
                owner_strategy_scope=None,
                owner_intent_id=None,
                average_price=None,
                stop_price=None,
                held_eligible_bars=None,
                long_quantity=quantity,
                short_quantity=Decimal(0),
                broker_quantity=quantity,
            )
        )
        instruments.append(
            FactorExecutionInstrumentFacts(
                target_id=item.target_id,
                instrument=item.instrument,
                exchange=item.exchange,
                snapshot_id=snapshot_id,
                available_at=now,
                trading_permitted=True,
                multiplier=Decimal(10),
                long_margin_per_hand=Decimal(1000),
                short_margin_per_hand=Decimal(1000),
                tick_size=Decimal("0.1"),
                lower_limit=Decimal(80),
                upper_limit=Decimal(130),
            )
        )
        quotes.append(
            FactorExecutionQuoteFacts(
                instrument=item.instrument,
                exchange=item.exchange,
                source="local-simulation",
                source_ref="fixture://local-quote-tape/v1",
                metadata_snapshot_id=snapshot_id,
                generation=1,
                sequence=index,
                trading_day=CURRENT_DAY.isoformat(),
                event_time=now,
                available_at=now,
                bid=Decimal("100.0"),
                ask=Decimal("100.1"),
                bid_size=Decimal(1),
                ask_size=Decimal(1),
                tick_size=Decimal("0.1"),
                lower_limit=Decimal(80),
                upper_limit=Decimal(130),
                quality="GOOD",
            )
        )
        routes.append(
            FactorExecutionRouteFacts(
                target_id=item.target_id,
                instrument=item.instrument,
                exchange=item.exchange,
                route_name="ctp/direct/registered-sim",
                eligible=True,
                allow_writes=False,
                frozen=False,
                capability_observed=True,
                capability_managed=False,
                capability_armed=False,
                capability_matches_route=False,
                instrument_query_complete=True,
                instrument_eligible=True,
                unknown_order_count=0,
                dispatching_order_count=0,
                connection_generation=1,
                trading_day=CURRENT_DAY.isoformat(),
                reason_codes=(),
                sdk_frozen=False,
                current_session_account_fingerprint=fingerprint,
                current_session_connection_generation=1,
                current_session_trading_day=CURRENT_DAY.isoformat(),
            )
        )
    return FactorExecutionFacts(
        account_scope="local-shutdown-fixture",
        strategy_scope=strategy_scope,
        snapshot_id=snapshot_id,
        available_at=now,
        account=account,
        positions=tuple(positions),
        working_orders=(),
        terminal_orders=(),
        trade_observations=(),
        quotes=tuple(quotes),
        instruments=tuple(instruments),
        route_eligibilities=tuple(routes),
        query_provenance=query_provenance,
        blockers=(),
        diagnostics=("LOCAL_SIMULATION_FIXTURE",),
        query_set_id=query_set_id,
    )


@pytest.mark.parametrize("nonflat", (False, True))
def test_real_cerebro_live_strategy_winddown_is_ready_or_times_out(tmp_path, monkeypatch, nonflat):
    """Exercise the actual live Strategy/feed/cohort/Broker lifecycle offline."""
    import backtrader as bt
    import backtrader.stores.factor_execution_facts as facts_module
    from backtrader.feeds.btapifeed import BtApiFeed
    from backtrader.stores.factor_execution_facts import FactorExecutionTarget
    from alpha003_strategy import Alpha003TargetStrategy

    config = _base_config(tmp_path, "live")
    config_path, config, plan, raw_tape, _raw_quotes = _write_source_inputs(tmp_path, config)
    config["cohort"].update(max_live_bar_age_seconds=7200, max_future_skew_seconds=0)
    config["live"].update(
        strategy_scope="local-shutdown-strategy",
        account_scope="local-shutdown-fixture",
        logical_run_id="local-shutdown-run",
        refresh_timeout_seconds=1,
        refresh_overall_timeout_seconds=2,
        refresh_interval_seconds=0.1,
        quote_max_age_seconds=60,
        query_max_age_seconds=7200,
    )
    config["output"]["decision_tape_path"] = str(tmp_path / "local-live-tape.jsonl")
    config["output"]["decision_tape_max_bytes"] = 50_000_000
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    tape = RUNNER.load_minute_tape(Path(config["inputs"]["minute_tape"]), plan, config["cohort"])
    _, quotes = RUNNER._quote_tape(
        Path(config["inputs"]["execution_quotes"]), plan, config["cohort"]
    )
    clock_times, _late_count = RUNNER._replay_clock_schedule(plan["grid"], tape, quotes)

    class LocalFixtureClock(RUNNER.ReplayTapeClock):
        def utc_now(self):
            try:
                return super().utc_now()
            except RuntimeError:
                # Runner-owned refresh may run before Cerebro's first sample.
                return clock_times[0]

    cohort = RUNNER._make_cohort(config, plan["grid"])
    clock = LocalFixtureClock(clock_times, cohort=cohort)

    class LocalProjectionStore:
        _cerebro_managed_lifecycle = True

        def start(self):
            return None

        def get_notifications(self):
            return []

        def stop(self):
            return None

    store = LocalProjectionStore()
    broker = bt.brokers.BackBroker(cash=1_000_000)
    broker.store = store
    broker.next_without_bar = True
    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    cerebro.setbroker(broker)
    targets = []
    for target in plan["targets"]:
        product = plan["product_by_target"][target]
        instrument = plan["routes"][product]
        events = tuple(tape["events"][target])
        feed = BtApiFeed(
            dataname=instrument,
            historical_bars=(),
            live_bars=events,
            backfill_start=False,
            cohort_source_mode=True,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            clock=clock,
        )
        cerebro.adddata(feed, name=target)
        cohort.register_member(
            target,
            feed,
            instrument=instrument,
            source_ref=tape["source_ref"],
            line_fields=RUNNER.OHLCV_FIELDS,
            raw_fields=RUNNER.OHLCV_FIELDS,
            clock_domain_id=tape["clock_domain_id"],
            timezone_id=tape["timezone_id"],
            session_semantics=config["cohort"]["session_semantics"],
            numeric_fields=RUNNER.OHLCV_FIELDS,
        )
        product = plan["product_by_target"][target]
        targets.append(
            FactorExecutionTarget(
                target_id=target,
                instrument=instrument,
                exchange=product.exchange_id,
                data=feed,
            )
        )
    cohort.seal()
    cerebro.add_live_bar_cohort(
        cohort,
        clock=clock,
        winddown_timeout_seconds=0.02 if nonflat else 1.0,
    )

    def local_refresh(
        _store,
        *,
        targets,
        timeout,
        overall_timeout,
        include_core,
        margin_target_ids,
        max_queries,
        cancel_event,
        utc_now,
        instrument_products=None,
    ):
        del timeout, overall_timeout, include_core, max_queries, cancel_event
        from backtrader.stores.factor_execution_facts import (
            FactorExecutionQuerySetFacts,
            FactorExecutionRefreshReceipt,
        )

        now = utc_now()
        base = (
            ("account_result", "account"),
            ("orders_result", "orders"),
            ("trades_result", "trades"),
            ("instruments_result", "instruments"),
            ("positions_result", "positions"),
        )
        labels = tuple(family for family, _kind in base) + tuple(
            "instrument_margin_rate_result:" + target_id for target_id in (margin_target_ids or ())
        )
        rows = [
            facts_module.FactorExecutionQueryFact(
                family=family,
                request_type=request_type,
                request_id=index,
                connection_generation=1,
                account_fingerprint="local-simulation-account-v1",
                trading_day=CURRENT_DAY.isoformat(),
                started_at=now - timedelta(microseconds=1),
                completed_at=now,
                source_owned=True,
                query_complete=True,
                scope_complete=True,
                row_count=0,
            )
            for index, (family, request_type) in enumerate(base, 1)
        ]
        next_id = len(rows) + 1
        for target_id in margin_target_ids or ():
            rows.append(
                facts_module.FactorExecutionQueryFact(
                    family="instrument_margin_rate_result",
                    request_type="margin_rate",
                    request_id=next_id,
                    connection_generation=1,
                    account_fingerprint="local-simulation-account-v1",
                    trading_day=CURRENT_DAY.isoformat(),
                    started_at=now - timedelta(microseconds=1),
                    completed_at=now,
                    source_owned=True,
                    query_complete=True,
                    scope_complete=False,
                    row_count=1,
                    target_id=target_id,
                )
            )
            next_id += 1
        query_set = FactorExecutionQuerySetFacts(
            query_set_id="local-simulation-query-set-%d" % next_id,
            account_fingerprint="local-simulation-account-v1",
            connection_generation=1,
            trading_day=CURRENT_DAY.isoformat(),
            started_at_utc=now - timedelta(microseconds=1),
            completed_at_utc=now,
            query_ids=tuple((family, index) for index, (family, _kind) in enumerate(base, 1)),
        )
        return FactorExecutionRefreshReceipt(
            started_at=now - timedelta(microseconds=1),
            completed_at=now,
            requested_families=labels,
            attempted_families=labels,
            query_provenance=tuple(rows),
            blockers=(),
            deadline_reached=False,
            pending_families=(),
            cancelled=False,
            query_set=query_set,
        )

    monkeypatch.setattr(facts_module, "refresh_factor_execution_queries", local_refresh)
    monkeypatch.setattr(
        facts_module,
        "project_factor_execution_facts",
        lambda _store, _broker, *, targets, account_scope, strategy_scope, now, **_kwargs: (
            _typed_local_shutdown_facts(
                now, targets, strategy_scope=strategy_scope, nonflat=nonflat
            )
        ),
    )
    refresh_loop = RUNNER.QueryRefreshLoop(
        store,
        broker,
        tuple(targets),
        coordinator=None,
        account_scope="local-shutdown-fixture",
        strategy_scope="local-shutdown-strategy",
        clock=clock,
        quote_max_age=timedelta(seconds=60),
        max_query_age=timedelta(seconds=7200),
        timeout=1,
        overall_timeout=2,
        interval=0.05,
        cerebro=cerebro,
        shutdown_grace_seconds=0.02 if nonflat else 1.0,
    )
    policy = RUNNER._risk_policy(config)
    decision_tape = RUNNER._new_decision_tape(
        config,
        config_path,
        plan,
        mode="live",
        factor_mode="native",
        direction=1,
        source_snapshot_id="local-simulation-fixture",
    )
    strategy_kwargs = RUNNER._make_strategy_kwargs(
        config,
        plan,
        "native",
        1,
        policy,
        replay=False,
        cohort=cohort,
        account_scope="local-shutdown-fixture",
        logical_run_id="local-shutdown-run",
        replay_quotes=(),
        replay_instruments={},
        max_live_bar_age_seconds=7200,
        max_future_skew_seconds=0,
        execution_enabled=False,
        decision_tape=decision_tape,
        control_refresh_loop=refresh_loop,
    )
    cerebro.addstrategy(Alpha003TargetStrategy, **strategy_kwargs)

    refresh_loop.refresh_once()
    refresh_loop.start()
    strategy = None
    try:
        if nonflat:
            with pytest.raises(TimeoutError, match="shutdown winddown timed out"):
                cerebro.run(runonce=False, preload=False)
            strategy = refresh_loop._strategy
            assert cerebro.live_bar_cohort_winddown_status == "TIMED_OUT"
            assert strategy is not None
            assert strategy.shutdown_requested is True
            assert strategy.shutdown_ready is False
            assert strategy.shutdown_blocker == (
                "SHUTDOWN_RECONCILIATION_BLOCKED:read_only_position_owner_unresolved:DCE.A"
            )
            assert refresh_loop.shutdown_status == "BLOCKED"
        else:
            result = cerebro.run(runonce=False, preload=False)[0]
            strategy = result
            assert cerebro.live_bar_cohort_winddown_status == "STOPPED"
            assert cerebro.live_bar_cohort_winddown_reason == "runstop_requested"
            assert strategy.shutdown_requested is True
            assert strategy.shutdown_ready is True
            assert strategy.shutdown_blocker is None
            assert refresh_loop.shutdown_status == "PASS"
            assert len(broker.orders) == 0
        assert refresh_loop.joined is True
    finally:
        decision_tape.close()
