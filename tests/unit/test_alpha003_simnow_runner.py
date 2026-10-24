"""Runnable Alpha003 example contracts using explicit public source fixtures."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from copy import deepcopy
from collections import deque
import hashlib
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
        ("DCE.fixture",),
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
    assert loop._interrupt_refresh.is_set()


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
    ("selection_source", "unresolved_position"),
    (("bundle", False), ("bundle", True), ("ctp_query", False)),
    ids=("flat-two-epoch-positive", "nonflat-winddown-timeout", "same-store-query-live"),
)
def test_live_two_epoch_uses_real_three_route_cerebro_and_closes_before_next_bundle(
    tmp_path, monkeypatch, selection_source, unresolved_position
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
    from backtrader.feeds import futures_ctp_snapshot
    from tests.unit.stores import test_factor_execution_facts as facts_fixture
    from tests.test_utils.optional_sdk import optional_sdk

    query_result_type = optional_sdk("bt_api_ctp.query").QueryResult

    # Keep the controlled source/session timestamps historical relative to the
    # host query collector's completion time. This exercises strict causal
    # freshness without advancing a virtual clock days into the future.
    first_day = date(2026, 10, 22)
    second_day = date(2026, 10, 23)
    first_decision = datetime(2026, 10, 21, 9, 10, tzinfo=UTC)
    second_decision = datetime(2026, 10, 22, 9, 10, tzinfo=UTC)
    config = _base_config(tmp_path, "live")
    first_bundle = _write_json(
        tmp_path / "selection-first.json",
        _selection_bundle(
            current_day=first_day,
            decision_at=first_decision,
            select_first=False,
            session_end=(10, 59),
        ),
    )
    config["selection"]["bundle"] = str(first_bundle)
    config_path, config, first_plan, _tape, _quotes = _write_source_inputs(
        tmp_path,
        config,
        current_day=first_day,
        decision_at=first_decision,
        connection_generation=1,
        session_end=(10, 59),
    )
    second_bundle = _write_json(
        tmp_path / "selection-second.json",
        _selection_bundle(
            current_day=second_day,
            decision_at=second_decision,
            select_first=True,
            session_end=(10, 59),
        ),
    )
    if selection_source == "ctp_query":
        config["selection"].update(
            source="ctp_query",
            bundle=None,
            daily_bundles=[],
            max_epochs=2,
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
    else:
        config["selection"]["daily_bundles"] = [str(second_bundle)]
    config["live"].update(
        account_scope="alpha003-two-epoch-account",
        strategy_scope="alpha003-two-epoch-shadow",
        logical_run_id="alpha003-two-epoch-shadow-run",
        journal_path=str(tmp_path / "live-decisions.sqlite"),
        ready_timeout_seconds=1.0,
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
    config["cohort"].update(max_live_bar_age_seconds=30.0, max_future_skew_seconds=0.0)
    config["output"]["decision_tape_path"] = str(tmp_path / "live-decisions.jsonl")
    config["output"]["decision_tape_max_bytes"] = 50_000_000
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    now = (
        datetime(2026, 10, 22, 1, 0, tzinfo=UTC)
        if selection_source == "ctp_query"
        else first_plan["grid"].minutes[0].close_time - timedelta(minutes=1)
    )
    trace = []
    api_clients = []
    contexts = deque()

    class CausalFixtureClock:
        """Virtual UTC follows tape availability; monotonic drives deadlines."""

        def __init__(self, start):
            self._now = start
            self._mono = 1_000_000_000
            self._lock = threading.RLock()
            self._availability = ()
            self._availability_index = 0

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
                if self._availability_index < len(self._availability):
                    self._now = max(self._now, self._availability[self._availability_index])
                    self._availability_index += 1

        def set_epoch_events(self, events):
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
                # Startup facts are queried at the first planned bucket start.
                # The fixture has 119 closes so the last bar remains inside
                # the explicit two-hour query/state age.
                self._now = self._availability[0] - timedelta(seconds=62)

        def set_utc_now(self, value):
            with self._lock:
                self._now = value

        def wait_interruptibly(self, timeout_seconds, wait_for_event):
            # Check an actual Cerebro/Store wake first. During an epoch, move
            # UTC only to the next explicit provider availability time; no
            # host time is used to release a bar.
            if wait_for_event(0.0):
                return True
            with self._lock:
                while (
                    self._availability_index < len(self._availability)
                    and self._availability[self._availability_index] <= self._now
                ):
                    self._availability_index += 1
                if self._availability_index < len(self._availability):
                    self._now = max(self._now, self._availability[self._availability_index])
                    self._availability_index += 1
                    return False
            return wait_for_event(min(float(timeout_seconds), 0.01))

    clock = CausalFixtureClock(now)
    monkeypatch.setattr(RUNNER, "RunnerWallClock", lambda: clock)
    current_plan = {"value": first_plan}
    strategy_instances = []

    def make_context(plan, epoch_id, *, context=None):
        bar_rows = defaultdict(list)
        for ordinal, minute in enumerate(plan["grid"].minutes, 1):
            member_by_product = {member.product: member for member in minute.members}
            for target_index, target in enumerate(plan["targets"]):
                product = plan["product_by_target"][target]
                instrument = plan["routes"][product]
                member = member_by_product[product]
                close_time = minute.close_time
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
                        "available_at": close_time + timedelta(seconds=2),
                        "trading_day": member.trading_day.isoformat(),
                        "session_segment": member.session_id,
                        "timezone_id": "UTC",
                        "clock_domain_id": config["cohort"]["clock_domain_id"],
                        "connection_generation": f"epoch-{epoch_id}-generation-1",
                        "bar_sequence": ordinal,
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
        clock.set_epoch_events(bar_rows)
        return context

    def make_query_context(epoch_id, trading_day):
        day_text = trading_day.strftime("%Y%m%d")
        rows = facts_fixture._query_rows()
        catalog_rows = []
        quote_rows = []
        all_instrument_rows = []
        all_margin_rows = []
        for product in PRODUCTS:
            for contract_index, month in enumerate(("11", "12")):
                instrument = f"{product.product_id}{str(trading_day.year)[-2:]}{month}"
                catalog_rows.append(
                    {
                        "InstrumentID": instrument,
                        "ExchangeID": product.exchange_id,
                        "ProductID": product.product_id.lower(),
                        "ProductClass": "1",
                        "IsTrading": 1,
                        "ExpireDate": "20261116" if month == "11" else "20261214",
                    }
                )
                selected = contract_index == (1 if epoch_id == 1 else 0)
                quote_rows.append(
                    {
                        "InstrumentID": instrument,
                        "ExchangeID": product.exchange_id,
                        "TradingDay": day_text,
                        "OpenInterest": 2000 if selected else 1000,
                        "Volume": 1500 if selected else 1000,
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
        )

    class FakeCtpWrapper(facts_fixture._FakeRegisteredSimWrapper):
        def __init__(self, *args, **kwargs):
            allow_writes = kwargs.pop("registered_sim_allow_writes", False)
            history_limit = kwargs.pop("registered_sim_history_limit", 64)
            terminal_limit = kwargs.pop("registered_sim_terminal_order_limit", 512)
            context = contexts.popleft()
            if context.epoch_id > 1:
                clock.set_utc_now(datetime(2026, 10, 23, 1, 0, tzinfo=UTC))
            super().__init__(
                *args,
                registered_sim_allow_writes=allow_writes,
                registered_sim_history_limit=history_limit,
                registered_sim_terminal_order_limit=terminal_limit,
                query_rows=context.rows,
                query_time=clock.utc_now(),
                ticks={},
                **kwargs,
            )
            self.context = context
            self._selection_request_id = 0
            client = self.trader_client
            client._account_fingerprint = "alpha003-two-epoch-account"
            client._trading_day = context.trading_day
            client._front_id = 100 + context.epoch_id
            client._session_id = 10 + context.epoch_id
            client.is_ready = True
            client.is_trading_ready = False
            client.is_read_only_ready = True
            client.wait_ready = lambda timeout: True
            client._gate_state.update(
                connection_generation=client._connection_generation,
                trading_day=context.trading_day,
            )
            client.get_session_state = lambda: {
                "connected": self._connected,
                "read_only_ready": True,
                "trading_ready": False,
                "account_fingerprint": client._account_fingerprint,
                "connection_generation": client._connection_generation,
                "trading_day": client._trading_day,
            }
            self.closed = False
            api_clients.append(self)
            trace.append(("api_created", context.epoch_id))

        def connect(self):
            self._connected = True
            trace.append(("api_connected", self.context.epoch_id))

        def disconnect(self):
            self._connected = False
            self.closed = True
            trace.append(("api_closed", self.context.epoch_id))

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
            retrieved_at = clock.utc_now()
            return query_result_type(
                request_type=request_type,
                request_id=self._selection_request_id,
                connection_generation=self.trader_client._connection_generation,
                account_fingerprint=self.trader_client._account_fingerprint,
                started_at_utc=retrieved_at - timedelta(milliseconds=2),
                completed_at_utc=retrieved_at - timedelta(milliseconds=1),
                is_last_seen=True,
                error_code=None,
                error_message="",
                timed_out=False,
                complete=True,
                records=tuple(records),
                late_callback_count=0,
                unsupported=False,
                submit_code=0,
            )

        def query_instruments_result(
            self,
            instrument_id="",
            exchange_id="",
            timeout=5.0,
            *,
            product_id="",
            max_duration=None,
            **filters,
        ):
            if max_duration is not None:
                assert instrument_id == exchange_id == product_id == ""
                assert not filters
                trace.append(("selection_catalog_query", self.context.epoch_id))
                return self._selection_query_result("instruments", self.context.catalog_rows)
            return super().query_instruments_result(
                timeout=timeout,
                instrument_id=instrument_id,
                exchange_id=exchange_id,
                product_id=product_id,
                **filters,
            )

        def query_depth_market_data_result(
            self, instrument_id="", exchange_id="", timeout=5.0
        ):
            assert instrument_id == exchange_id == ""
            trace.append(("selection_depth_query", self.context.epoch_id))
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
            return row

    original_factory = registered_sim_module._make_api_factory
    monkeypatch.setattr(
        registered_sim_module,
        "_make_api_factory",
        lambda allow_writes, history_limit, terminal_limit, api_cls: original_factory(
            allow_writes, history_limit, terminal_limit, FakeCtpWrapper
        ),
    )
    monkeypatch.setattr(RUNNER, "_live_env_config", lambda _config: ({}, {}))
    if selection_source == "ctp_query":
        monkeypatch.setattr(futures_ctp_snapshot, "_now_utc", clock.utc_now)
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
        return plan

    monkeypatch.setattr(RUNNER, "load_market_plan", tracked_load)
    if selection_source == "ctp_query":
        original_query_plan = RUNNER.build_ctp_query_market_plan

        def tracked_query_plan(*args, **kwargs):
            plan = original_query_plan(*args, **kwargs)
            current_plan["value"] = plan
            trace.append(("query_plan_ready", plan["source_snapshot_id"]))
            return plan

        monkeypatch.setattr(RUNNER, "build_ctp_query_market_plan", tracked_query_plan)
    original_make_cohort = RUNNER._make_cohort

    def tracked_make_cohort(epoch_config, grid, *, begin_at=None):
        plan = current_plan["value"]
        assert grid is plan["grid"]
        epoch_id = epoch_config["cohort"]["epoch_id"]
        if selection_source == "ctp_query":
            context = api_clients[-1].context
            assert context.all_catalog_facts is True
            make_context(plan, epoch_id, context=context)
        else:
            contexts.append(make_context(plan, epoch_id))
        trace.append(("cohort_assembled", epoch_id))
        return original_make_cohort(epoch_config, grid, begin_at=begin_at)

    monkeypatch.setattr(RUNNER, "_make_cohort", tracked_make_cohort)
    original_run_live = RUNNER.run_live

    def tracked_run_live(epoch_config, *args, **kwargs):
        result = original_run_live(epoch_config, *args, **kwargs)
        trace.append(("run_live_returned", epoch_config["cohort"]["epoch_id"]))
        return result

    monkeypatch.setattr(RUNNER, "run_live", tracked_run_live)
    strategy_module = importlib.import_module("alpha003_strategy")
    original_notify_idle = strategy_module.Alpha003TargetStrategy.notify_idle

    def tracked_notify_idle(strategy):
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

    monkeypatch.setattr(strategy_module.Alpha003TargetStrategy, "notify_idle", tracked_notify_idle)

    failure = None
    result = None
    try:
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
        assert trace.index(("api_closed", 1)) < trace.index(("api_created", 2))
        assert trace.index(("api_closed", 1)) < trace.index(("selection_catalog_query", 2))
        assert trace.index(("api_closed", 1)) < trace.index(("selection_depth_query", 2))
        for epoch_index, epoch in enumerate(result["epochs"]):
            expected_day = first_day if epoch_index == 0 else second_day
            expected_instruments = (
                {"M2612", "Y2612", "A2612"}
                if epoch_index == 0
                else {"M2611", "Y2611", "A2611"}
            )
            assert epoch["epoch_id"] == epoch_index + 1
            assert epoch["retirement_proven"] is True
            assert epoch["selection_source"] == "ctp_query_snapshot_equal_weight_v1"
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
        < trace.index(("cohort_assembled", 2))
        < trace.index(("api_created", 2))
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


def _call_runner(capsys, *arguments):
    code = RUNNER.run(list(arguments))
    stdout = capsys.readouterr().out.strip().splitlines()[-1]
    return code, json.loads(stdout)


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
    code, result = _call_runner(
        capsys, "--mode", "research", "--config", str(offline_config_path)
    )
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
    assert str(second_path.resolve()) not in error.later_bundle_reads


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
    config["output"].update(
        decision_tape_path=str(tmp_path / f"{failure}-decisions.jsonl"),
        decision_tape_max_bytes=1_000_000,
    )
    if write_enabled:
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
                "md_front": "tcp://fixture.invalid:1",
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
        json.dumps({"config": {}, "api_kwargs": {}}),
    )

    closed = []
    lifecycle = []

    class FakeStore:
        registered_sim_route_id = "simnow-registered-v1"
        sdk_api = None

        def __init__(self, **kwargs):
            self.options = kwargs

        def getdata(self, **kwargs):
            return SimpleNamespace(name=kwargs["dataname"])

        def registered_sim_wait_ready(self, timeout):
            lifecycle.append("session_ready")
            return failure not in {"ready", "ready_store_stop"}

        def registered_sim_login_facts(self):
            lifecycle.append("login_facts")
            return {"read_only_ready": True, "trading_ready": True}

        def registered_sim_configure_arm_templates(self, templates):
            lifecycle.append("arm_templates")
            if failure == "arm":
                raise RuntimeError("fake arm configuration failure")

        def stop(self):
            closed.append("store")
            if failure == "ready_store_stop":
                raise RuntimeError("fake Store close failure")
            return {"shutdown_state": "PASS"}

    class FakeBroker:
        def __init__(self, *, store, **kwargs):
            self.store = store

        def get_shutdown_summary(self):
            return {"status": "NOT_STARTED", "store_shutdown_state": "UNPROVEN"}

    class FakeJournal:
        def __init__(self, path):
            self.path = path

        def close(self):
            closed.append("journal")

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
    monkeypatch.setattr(RUNNER, "_make_cohort", lambda *args, **kwargs: FakeCohort())
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
    assert by_resource["decision_tape"]["status"] == "CLOSED"
    assert by_resource["journal"]["status"] == "CLOSED"
    if failure == "ready_store_stop":
        assert by_resource["store"]["status"] == "FAILED"
    else:
        assert by_resource["store"]["shutdown_state"] == "PASS"
    assert by_resource["broker"]["status"] == "NOT_RUN"
    if failure in {"ready", "ready_store_stop", "arm"}:
        assert by_resource["query_refresh"]["status"] == "NOT_CREATED"
    else:
        assert by_resource["query_refresh"]["joined"] is True
        assert by_resource["query_refresh"]["status"] == "RETURNED"
        assert "query_refresh" in closed
    assert "store" in closed
    assert "journal" in closed
    if failure in {"ready", "ready_store_stop"}:
        assert lifecycle == ["session_ready"]
    elif failure == "arm":
        assert lifecycle == ["session_ready", "login_facts", "arm_templates"]
    else:
        assert lifecycle == [
            "session_ready",
            "login_facts",
            "arm_templates",
            "refresh_loop_created",
            "facts_refresh",
        ]


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

    clock = LocalFixtureClock(clock_times)
    cohort = RUNNER._make_cohort(config, plan["grid"])

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
    ):
        del timeout, overall_timeout, include_core, max_queries, cancel_event
        from backtrader.stores.factor_execution_facts import (
            FactorExecutionQuerySetFacts,
            FactorExecutionRefreshReceipt,
        )

        now = clock.utc_now()
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
