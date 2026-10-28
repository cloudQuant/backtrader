"""Source-backed ordinary Alpha003 live order path over RegisteredSim.

Only provider SDK leaves and the bounded source bar/tick tape are synthetic.
The 028 Runner, Alpha003 Strategy, cohort, Broker, Store, query refresh,
execution coordinator, and journal are the production implementations.
"""

from __future__ import annotations

from collections import defaultdict, deque
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import math
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
import threading
import time

import pytest

from tests.unit import test_alpha003_simnow_runner as runner_fixtures
from tests.unit.stores import test_factor_execution_facts as facts_fixtures


RUNNER = runner_fixtures.RUNNER
UTC = timezone.utc


def _bounded_capacity_fact_projection(facts, *, group):
    """Keep only finite status, issue, and count facts from one capacity sample."""
    if not hasattr(facts, "get"):
        return {"status": "UNAVAILABLE"}
    fields_by_group = {
        "lines": (
            "schema",
            "status",
            "observation_complete",
            "graph_node_count",
            "graph_reference_count",
            "graph_node_limit",
            "graph_reference_limit",
            "line_buffer_count",
            "bounded_line_buffer_count",
            "unbounded_line_buffer_count",
            "line_capacity_unavailable_count",
            "unobservable_line_reference_count",
            "unobservable_line_collection_count",
            "line_capacity_sum",
            "max_line_capacity",
            "retained_line_value_count",
            "bounded_retained_line_value_count",
            "unbounded_retained_line_value_count",
            "retained_line_value_count_status",
            "max_retained_values_per_line",
            "value_line_count",
            "reason_line_count",
            "issues",
        ),
        "diagnostics": (
            "schema",
            "status",
            "factor_count",
            "call_count",
            "once_range_count",
            "call_sample_count",
            "once_range_sample_count",
            "sample_limits",
            "issues",
        ),
    }
    fields = fields_by_group.get(group)
    if fields is None:
        raise ValueError("unsupported capacity diagnostic group")
    result = {}
    for name in fields:
        if name not in facts:
            continue
        value = facts.get(name)
        if name == "issues":
            value = tuple(value or ())[:16]
        elif name == "sample_limits":
            value = tuple(value or ())[:8]
        result[name] = value
    return result


def _synthetic_live_config(tmp_path, mode="live"):
    """Build the runner's complete public config shape without reading example files."""
    return {
        "schema": RUNNER.SCHEMA,
        "mode": mode,
        "entry": {"tier": "dry" if mode == "research" else mode},
        "factor": {
            "mode": "native",
            "direction": 1,
            "preheat_bars": 20,
            "rebalance_every": 1,
        },
        "selection": {
            "source": "bundle",
            "query_mode": "legacy_two_query",
            "bundle": str(tmp_path / "selection.json"),
            "authorized_products": None,
            "daily_bundles": [],
            "max_epochs": 1,
        },
        "inputs": {
            "minute_tape": None,
            "execution_quotes": None,
            "instrument_metadata": None,
            "history_decision_tape": None,
        },
        "research": {
            "start": None,
            "end": None,
            "source_timezone": "Asia/Shanghai",
            "price_basis": "raw-close-v1",
        },
        "cohort": {
            "calendar_id": "synthetic-alpha003-calendar",
            "calendar_version": "fixture-v1",
            "epoch_id": 1,
            "clock_domain_id": "synthetic-ctp-clock-v1",
            # The synthetic source rows carry UTC bucket timestamps and declare
            # timezone_id="UTC"; keep the exact cohort/feed member contract aligned.
            "timezone_id": "UTC",
            "session_semantics": "ctp-trading-day-v1",
            "max_pending_slots": 1,
            "max_window_bars": 256,
            "wait_timeout_seconds": 1.0,
            "max_live_bar_age_seconds": 30.0,
            "max_future_skew_seconds": 0.0,
        },
        "replay": {"starting_cash": 1_000_000, "commission": 0},
        "risk": {
            "policy_id": None,
            **{name: None for name in RUNNER.RISK_FIELDS},
        },
        "live": {
            "store_config_env": "synthetic-test-only",
            "allow_writes": True,
            "account_scope": "synthetic-alpha003-account",
            "strategy_scope": "synthetic-alpha003-strategy",
            "logical_run_id": "synthetic-alpha003-run",
            "journal_path": str(tmp_path / "execution-journal.sqlite"),
            "arm_templates": [],
            "ready_timeout_seconds": 1.0,
            "refresh_timeout_seconds": 1.0,
            "refresh_overall_timeout_seconds": 5.0,
            "refresh_interval_seconds": 0.01,
            "quote_max_age_seconds": 60.0,
            "query_max_age_seconds": 7200.0,
            "loss_guard_net_loss_threshold": "1000.00",
            "loss_guard_max_observation_age_seconds": 7200,
            "shutdown_grace_seconds": 5.0,
            "golden_targets": None,
            # Preserve this order-chain fixture's existing no-fee-identity case.
            "commission_identity_by_target": None,
        },
        "output": {
            "directory": str(tmp_path / "output"),
            "evaluate_with_fincore": False,
            "decision_tape_path": str(tmp_path / "decision-tape.jsonl"),
            "decision_tape_max_bytes": 50_000_000,
        },
    }


def _run_alpha003_live_strategy_order_chain_fixture(
    tmp_path,
    monkeypatch,
    *,
    _fee_pair_source_only=False,
    _fee_pair_missing_pair_then_block=False,
    _fee_pair_stale_snapshot_after_append=False,
    _capacity_only=False,
    _factor_mode="native",
    _capture_capacity=False,
    _causal_quote_barrier=False,
    _defer_capacity_status_assertion=False,
    _diagnostic_path=None,
):
    """Ordinary Alpha003 decisions traverse real Store/Broker/query lifecycles."""
    import backtrader.stores.execution_decision_journal as journal_module
    import backtrader.stores.registered_sim as registered_sim_module
    import backtrader.brokers.btapibroker as broker_module
    import backtrader.feeds.btapifeed as btapifeed_module
    import backtrader.feeds.ctp_factor_source as ctp_factor_source_module
    import backtrader.stores.factor_execution as factor_execution_module
    import backtrader.stores.factor_position_book as factor_position_book_module

    if type(_defer_capacity_status_assertion) is not bool:
        raise TypeError("_defer_capacity_status_assertion must be bool")
    if type(_causal_quote_barrier) is not bool:
        raise TypeError("_causal_quote_barrier must be bool")
    if type(_fee_pair_source_only) is not bool:
        raise TypeError("_fee_pair_source_only must be bool")
    if type(_fee_pair_missing_pair_then_block) is not bool:
        raise TypeError("_fee_pair_missing_pair_then_block must be bool")
    if type(_fee_pair_stale_snapshot_after_append) is not bool:
        raise TypeError("_fee_pair_stale_snapshot_after_append must be bool")
    if (
        (_fee_pair_missing_pair_then_block or _fee_pair_stale_snapshot_after_append)
        and not _fee_pair_source_only
    ):
        raise ValueError("fee-pair failure modes require fee-pair source-only mode")

    decision_tape_failure_probe = []
    source_receipt_field_probe = []
    fee_pair_source_attempts = []
    fee_pair_writer_attempts = []
    fee_pair_reservation_attempts = []
    fee_pair_stale_snapshot_events = []
    fee_pair_stale_grid_inputs = []
    fee_pair_stale_grid_results = []
    fee_pair_live_ordinary_fallbacks = []
    fee_pair_risk_path_batches = []
    fee_pair_stale_batch_ids = set()

    def _safe_receipt_equal(left, right):
        try:
            return bool(left == right)
        except BaseException:
            return False

    def _receipt_member_differences(left, right):
        from collections.abc import Mapping as MappingABC
        from dataclasses import fields as dataclass_fields, is_dataclass

        if isinstance(left, MappingABC) and isinstance(right, MappingABC):
            keys = list(left)
            keys.extend(key for key in right if key not in left)
            differences = []
            for index, key in enumerate(keys[:128]):
                left_present = key in left
                right_present = key in right
                row = {
                    "member_index": index,
                    "left_present": left_present,
                    "right_present": right_present,
                }
                if left_present and right_present:
                    row["unequal_fields"] = _receipt_member_differences(left[key], right[key])
                differences.append(row)
            return differences
        if isinstance(left, (tuple, list)) and isinstance(right, (tuple, list)):
            differences = []
            for index in range(min(max(len(left), len(right)), 128)):
                left_present = index < len(left)
                right_present = index < len(right)
                row = {
                    "member_index": index,
                    "left_present": left_present,
                    "right_present": right_present,
                }
                if left_present and right_present:
                    row["unequal_fields"] = _receipt_member_differences(
                        left[index], right[index]
                    )
                differences.append(row)
            return differences
        if is_dataclass(left) and is_dataclass(right):
            unequal = []
            for item in dataclass_fields(type(left)):
                if not _safe_receipt_equal(getattr(left, item.name), getattr(right, item.name)):
                    unequal.append(item.name[:64])
            return unequal
        if isinstance(left, MappingABC) or isinstance(right, MappingABC):
            return ["member_shape"]
        return [] if _safe_receipt_equal(left, right) else ["member_value"]

    receipt_type = journal_module.ExecutionSourceReceipt
    original_receipt_eq = receipt_type.__eq__

    def observe_source_receipt_eq(receipt, other):
        equal = original_receipt_eq(receipt, other)
        caller = sys._getframe(1)
        if (
            equal is False
            and type(receipt) is receipt_type
            and type(other) is receipt_type
            and caller.f_code.co_name == "_verified_source_tape_readback_locked"
            and not source_receipt_field_probe
        ):
            from dataclasses import fields as dataclass_fields

            field_rows = []
            member_differences = None
            for item in dataclass_fields(receipt_type):
                left = getattr(receipt, item.name)
                right = getattr(other, item.name)
                is_equal = _safe_receipt_equal(left, right)
                field_rows.append({"field": item.name[:64], "equal": is_equal})
                if item.name == "members" and not is_equal:
                    member_differences = _receipt_member_differences(left, right)
            source_receipt_field_probe.append(
                {
                    "fields": field_rows,
                    "members_differences": member_differences,
                }
            )
        return equal

    monkeypatch.setattr(receipt_type, "__eq__", observe_source_receipt_eq)

    def _safe_writer_error_projection(error):
        if error is None:
            return None
        raw_code = getattr(error, "code", None)
        code = None
        if (
            type(raw_code) is str
            and 1 <= len(raw_code) <= 96
            and raw_code.isascii()
            and raw_code[0].isalpha()
            and all(
                character.isupper() or character.isdigit() or character == "_"
                for character in raw_code
            )
        ):
            code = raw_code
        frames = []
        traceback = getattr(error, "__traceback__", None)
        while traceback is not None and len(frames) < 5:
            frame = traceback.tb_frame
            frames.append(
                {
                    "file": Path(frame.f_code.co_filename).name[:64],
                    "function": frame.f_code.co_name[:64],
                    "line": int(traceback.tb_lineno),
                }
            )
            traceback = traceback.tb_next
        return {
            "type": type(error).__name__[:64],
            "code": code,
            "frames": frames,
        }

    def _record_decision_tape_failure(row):
        if len(decision_tape_failure_probe) < 12:
            decision_tape_failure_probe.append(row)

    writer_class = RUNNER.DecisionTapeWriter
    original_writer_setattr = writer_class.__setattr__

    if _fee_pair_missing_pair_then_block:
        original_fee_pair_writer = writer_class.record_fee_pair_source_only_from_live
        original_fee_pair_reserve = (
            journal_module.ExecutionDecisionJournal.reserve_fee_pair_workflow_candidate
        )

        def observe_fee_pair_reservation(journal, candidate, *args, **kwargs):
            fee_pair_reservation_attempts.append(
                getattr(candidate, "batch_id", None)
            )
            return original_fee_pair_reserve(journal, candidate, *args, **kwargs)

        monkeypatch.setattr(
            journal_module.ExecutionDecisionJournal,
            "reserve_fee_pair_workflow_candidate",
            observe_fee_pair_reservation,
        )

        def observe_fee_pair_writer_attempt(writer, batch, *args, **kwargs):
            fee_pair_writer_attempts.append(
                {
                    "batch_id": getattr(batch, "batch_id", None),
                    "slot_index": getattr(batch, "slot_index", None),
                }
            )
            return original_fee_pair_writer(writer, batch, *args, **kwargs)

        monkeypatch.setattr(
            writer_class,
            "record_fee_pair_source_only_from_live",
            observe_fee_pair_writer_attempt,
        )

    def observe_writer_setattr(writer, name, value):
        was_failed = getattr(writer, "_failed", False) if name == "_failed" else None
        original_writer_setattr(writer, name, value)
        if name == "_failed" and value is True and was_failed is not True:
            caller = sys._getframe(1)
            _record_decision_tape_failure(
                {
                    "phase": "failed_flag_first_set",
                    "caller_file": Path(caller.f_code.co_filename).name[:64],
                    "caller_function": caller.f_code.co_name[:64],
                    "caller_line": int(caller.f_lineno),
                    "active_error": _safe_writer_error_projection(sys.exc_info()[1]),
                }
            )

    monkeypatch.setattr(writer_class, "__setattr__", observe_writer_setattr)
    original_writer_close = writer_class.close

    def observe_writer_close(writer, *args, **kwargs):
        before_failed = getattr(writer, "_failed", None)
        before_closed = getattr(writer, "_closed", None)
        try:
            return original_writer_close(writer, *args, **kwargs)
        except BaseException as error:
            _record_decision_tape_failure(
                {
                    "phase": "close_exception",
                    "before_failed": before_failed,
                    "before_closed": before_closed,
                    "error": _safe_writer_error_projection(error),
                }
            )
            raise

    monkeypatch.setattr(writer_class, "close", observe_writer_close)

    start_day = runner_fixtures.CURRENT_DAY
    decision_at = runner_fixtures.DECISION_AT
    config = _synthetic_live_config(tmp_path, "live")
    config_path, config, full_plan, tape, _quotes = runner_fixtures._write_source_inputs(
        tmp_path,
        config,
        current_day=start_day,
        decision_at=decision_at,
    )

    # Fifty bars keep the order-chain regression small. The capacity pairing
    # below uses the complete 120-minute DCE fixture session; the formal
    # all-pool acceptance grid remains 195 minutes.
    minute_count = len(full_plan["grid"].minutes) if _capacity_only else 50
    plan = dict(full_plan)
    plan["grid"] = replace(full_plan["grid"], minutes=full_plan["grid"].minutes[:minute_count])
    planned_closes = {minute.close_time for minute in plan["grid"].minutes}
    target_by_instrument = {
        plan["routes"][plan["product_by_target"][target]]: target for target in plan["targets"]
    }
    bars_by_instrument = defaultdict(deque)

    def refill_bars():
        for source in tape["bars"]:
            end = datetime.fromisoformat(source["bucket_end"].replace("Z", "+00:00"))
            if end not in planned_closes:
                continue
            event = dict(source)
            for name in ("bucket_start", "bucket_end", "available_at"):
                event[name] = datetime.fromisoformat(event[name].replace("Z", "+00:00"))
            bars_by_instrument[event["instrument"]].append(event)

    refill_bars()

    causal_quote_rows_by_close = {}
    causal_quote_receipt_events = {}
    causal_quote_receipt_by_bar_id = {}
    causal_quote_receipt_trace = []
    causal_quote_barrier_trace = []
    store_callback_time_context = threading.local()
    store_tick_fields_by_bar_id = {}
    store_tick_fields_lock = threading.Lock()
    post_dispatch_clock_advances_by_close = {}
    post_dispatch_clock_advanced_closes = set()
    causal_quote_refresh_by_close = {}
    causal_quote_receipt_lock = threading.Lock()
    for instrument, source_rows in bars_by_instrument.items():
        target = target_by_instrument[instrument]
        for row in source_rows:
            causal_quote_rows_by_close.setdefault(row["bucket_end"], {})[target] = row
            causal_quote_receipt_events[row["bar_id"]] = threading.Event()

    causal_quote_row_by_bar_id = {
        row["bar_id"]: row
        for source_rows in bars_by_instrument.values()
        for row in source_rows
    }
    source_calendar_trace = {}
    final_close = plan["grid"].minutes[-1].close_time
    post_dispatch_probe_close = plan["grid"].minutes[
        min(40, len(plan["grid"].minutes) - 1)
    ].close_time

    def synthetic_ctp_tick_time(bucket_end):
        if _capacity_only:
            if bucket_end == final_close:
                # Keep the final quote inside DCE day-am and map it to the
                # planned 11:00 close. The completed final BarEvent comes from
                # the source tape row, not from a post-session CTP tick.
                return bucket_end - timedelta(milliseconds=1)
            # The full source row becomes available 2 seconds after close;
            # keep each synthetic CTP event no later than that row boundary.
            return bucket_end + timedelta(seconds=1, milliseconds=990)
        return bucket_end + timedelta(seconds=2, milliseconds=10)

    if _capacity_only:
        source_calendar = ctp_factor_source_module.CtpFactorSourceCalendar.from_grid(
            plan["grid"],
            config["cohort"]["clock_domain_id"],
            plan["session_calendars"],
        )
        minutes_by_close = {minute.close_time: minute for minute in plan["grid"].minutes}
        source_calendar_trace = {}
        for target in plan["targets"]:
            product = plan["product_by_target"][target]
            rows = sorted(
                (row for row in tape["bars"] if row["target"] == target),
                key=lambda row: row["bucket_end"],
            )
            assert len(rows) == len(plan["grid"].minutes) == minute_count
            mapped_tick_count = 0
            outside_session_tick_count = 0
            day_counts = {}
            session_counts = {}
            for row, minute in zip(rows, plan["grid"].minutes):
                member = next(item for item in minute.members if item.product == product)
                bucket_start = datetime.fromisoformat(row["bucket_start"].replace("Z", "+00:00"))
                bucket_end = datetime.fromisoformat(row["bucket_end"].replace("Z", "+00:00"))
                available_at = datetime.fromisoformat(row["available_at"].replace("Z", "+00:00"))
                event_time = synthetic_ctp_tick_time(bucket_end)
                callback_delivery_at = (
                    event_time
                    if _causal_quote_barrier
                    else available_at + timedelta(milliseconds=200)
                )
                assert row["instrument"] == plan["routes"][product]
                assert row["exchange"] == product.exchange_id
                assert row["trading_day"] == member.trading_day.isoformat()
                assert row["trading_day"].replace("-", "") == member.trading_day.strftime("%Y%m%d")
                assert row["session_segment"] == member.session_id
                assert bucket_start == minute.close_time - timedelta(minutes=1)
                assert bucket_end == minute.close_time
                assert minutes_by_close[bucket_end] is minute
                assert available_at >= bucket_end
                assert available_at >= event_time
                assert callback_delivery_at >= event_time
                day_counts[row["trading_day"]] = day_counts.get(row["trading_day"], 0) + 1
                session_counts[row["session_segment"]] = (
                    session_counts.get(row["session_segment"], 0) + 1
                )

                # Verify the event-time/session projection for every target and
                # every source row before executing the chain. In the capacity
                # profile, delivery still follows source-row availability.
                trading_day = datetime.fromisoformat(row["trading_day"]).date()
                action_day = event_time.astimezone(timezone(timedelta(hours=8))).date()
                selected_session = source_calendar.session_for(product, event_time, trading_day)
                allowed_action_days = source_calendar.action_days_by_product_day.get(
                    (product, trading_day), frozenset()
                )
                assert action_day in allowed_action_days
                if selected_session is None:
                    outside_session_tick_count += 1
                    continue
                mapped_tick_count += 1
                projected_close = event_time.replace(second=0, microsecond=0) + timedelta(minutes=1)
                projected_member = source_calendar.members_by_close.get(projected_close, {}).get(
                    product
                )
                assert projected_member is not None
                assert selected_session == (
                    projected_member.session_date,
                    projected_member.session_id,
                )
                assert action_day in {projected_member.action_day, projected_member.session_date}
            assert mapped_tick_count == len(rows)
            assert outside_session_tick_count == 0
            source_calendar_trace[target] = {
                "product": f"{product.exchange_id}.{product.product_id}",
                "instrument": plan["routes"][product],
                "source_bar_count": len(rows),
                "source_bar_member_matches": len(rows),
                "ctp_tick_session_mapped_count": mapped_tick_count,
                "ctp_tick_outside_session_count": outside_session_tick_count,
                "trading_day_counts": day_counts,
                "session_segment_counts": session_counts,
                "first_source_trading_day": rows[0]["trading_day"],
                "last_source_trading_day": rows[-1]["trading_day"],
                "first_source_session_segment": rows[0]["session_segment"],
                "last_source_session_segment": rows[-1]["session_segment"],
                "first_close_time": plan["grid"].minutes[0].close_time,
                "last_close_time": plan["grid"].minutes[-1].close_time,
            }

    def make_query_rows():
        rows = facts_fixtures._query_rows()
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
            for instrument, exchange in route_rows
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
            for instrument, exchange in route_rows
        ]
        return rows

    route_rows = [
        (
            plan["routes"][plan["product_by_target"][target]],
            plan["product_by_target"][target].exchange_id,
        )
        for target in plan["targets"]
    ]
    query_rows = make_query_rows()

    event_times = tuple(
        sorted(
            {
                event["available_at"] + timedelta(milliseconds=200)
                for rows in bars_by_instrument.values()
                for event in rows
            }
        )
    )

    class SourceClock:
        """UTC follows explicit bar availability; monotonic remains real."""

        def __init__(self, times):
            self._times = tuple(times)
            self._index = 0
            self._scheduled = []
            # Keep the first close inside the Runner's cohort window; its
            # bucket begins about one minute before event availability.
            self._now = self._times[0] - timedelta(seconds=65)
            self._lock = threading.RLock()
            self.snapshot_clock_trace = {
                "call_count": 0,
                "observer_errors": 0,
                "sample_limit": 256,
                "samples": [],
            }

        def utc_now(self):
            with self._lock:
                now = self._now
                virtual_bar_index = self._index
                next_synthetic_bar = (
                    self._times[self._index] if self._index < len(self._times) else None
                )
                next_provider_event = self._scheduled[0][0] if self._scheduled else None
            if _capture_capacity:
                try:
                    caller = sys._getframe(1)
                    if (
                        caller.f_globals.get("__name__") == "backtrader.research.live"
                        and caller.f_code.co_name == "snapshot"
                    ):
                        live_factors = caller.f_locals.get("self")
                        batch = caller.f_locals.get("batch")
                        close_time = getattr(batch, "close_time", None)
                        available_at = getattr(batch, "available_at", None)
                        plan = getattr(live_factors, "_plan", None)
                        max_age = getattr(plan, "max_live_bar_age_seconds", None)
                        max_future_skew = getattr(plan, "max_future_skew_seconds", None)
                        age_seconds = (
                            (now - close_time).total_seconds()
                            if isinstance(close_time, datetime)
                            else None
                        )
                        future_skew_seconds = (
                            max(
                                (close_time - now).total_seconds(),
                                (available_at - now).total_seconds(),
                            )
                            if isinstance(close_time, datetime)
                            and isinstance(available_at, datetime)
                            else None
                        )
                        engine_state = {"runnext_frame_found": False}
                        engine_frame = caller.f_back
                        for _depth in range(16):
                            if engine_frame is None:
                                break
                            if (
                                engine_frame.f_globals.get("__name__")
                                == "backtrader._cerebro.runnext"
                                and engine_frame.f_code.co_name == "_runnext"
                            ):
                                engine_locals = engine_frame.f_locals
                                prepared = engine_locals.get("prepared_result")
                                prepared_status = getattr(prepared, "status", None)
                                prepared_status = getattr(prepared_status, "value", prepared_status)
                                engine_state = {
                                    "runnext_frame_found": True,
                                    "cohort_wait": engine_locals.get("cohort_wait")
                                    if type(engine_locals.get("cohort_wait")) is bool
                                    else None,
                                    "cohort_prepare_budget_exhausted": engine_locals.get(
                                        "cohort_prepare_budget_exhausted"
                                    )
                                    if type(engine_locals.get("cohort_prepare_budget_exhausted"))
                                    is bool
                                    else None,
                                    "cohort_source_collection_active": engine_locals.get(
                                        "cohort_source_collection_active"
                                    )
                                    if type(engine_locals.get("cohort_source_collection_active"))
                                    is bool
                                    else None,
                                    "cohort_status": prepared_status
                                    if type(prepared_status) is str
                                    else None,
                                }
                                break
                            engine_frame = engine_frame.f_back
                        trace = self.snapshot_clock_trace
                        with self._lock:
                            trace["call_count"] += 1
                            if len(trace["samples"]) < trace["sample_limit"]:
                                trace["samples"].append(
                                    {
                                        "slot_index": getattr(batch, "slot_index", None),
                                        "batch_id": getattr(batch, "batch_id", None),
                                        "close_time": (
                                            close_time.isoformat()
                                            if isinstance(close_time, datetime)
                                            else None
                                        ),
                                        "available_at": (
                                            available_at.isoformat()
                                            if isinstance(available_at, datetime)
                                            else None
                                        ),
                                        "scheduler_now": now.isoformat(),
                                        "observer_monotonic_ns": time.monotonic_ns(),
                                        "virtual_bar_index": virtual_bar_index,
                                        "runnext_engine_state": engine_state,
                                        "next_synthetic_bar": (
                                            next_synthetic_bar.isoformat()
                                            if isinstance(next_synthetic_bar, datetime)
                                            else None
                                        ),
                                        "next_provider_event": (
                                            next_provider_event.isoformat()
                                            if isinstance(next_provider_event, datetime)
                                            else None
                                        ),
                                        "age_seconds": age_seconds,
                                        "max_live_bar_age_seconds": max_age,
                                        "future_skew_seconds": future_skew_seconds,
                                        "max_future_skew_seconds": max_future_skew,
                                        "stale": (
                                            type(age_seconds) in (int, float)
                                            and type(max_age) in (int, float)
                                            and age_seconds > max_age
                                        ),
                                        "future_skew_exceeded": (
                                            type(future_skew_seconds) in (int, float)
                                            and type(max_future_skew) in (int, float)
                                            and future_skew_seconds > max_future_skew
                                        ),
                                    }
                                )
                except Exception:
                    with self._lock:
                        self.snapshot_clock_trace["observer_errors"] += 1
            return now

        def monotonic_ns(self):
            return time.monotonic_ns()

        def time(self):
            return self.utc_now().timestamp()

        def schedule_at(self, when, callback):
            if not isinstance(when, datetime) or when.tzinfo is None or not callable(callback):
                raise TypeError("scheduled source events need an aware time and callback")
            with self._lock:
                self._scheduled.append((when, callback))
                self._scheduled.sort(key=lambda item: item[0])
                ready = self._take_due_locked()
            self._dispatch(ready)

        def _take_due_locked(self):
            ready = []
            while self._scheduled and self._scheduled[0][0] <= self._now:
                _when, callback = self._scheduled.pop(0)
                ready.append(callback)
            return ready

        @staticmethod
        def _dispatch(callbacks):
            for callback in callbacks:
                callback()

        def advance(self, delta):
            with self._lock:
                self._now += delta
                now = self._now
                ready = self._take_due_locked()
            self._dispatch(ready)
            return now

        def reset(self, times):
            with self._lock:
                self._times = tuple(times)
                self._index = 0
                self._scheduled.clear()
                self._now = self._times[0] - timedelta(seconds=65)
                self.snapshot_clock_trace = {
                    "call_count": 0,
                    "observer_errors": 0,
                    "sample_limit": 256,
                    "samples": [],
                }

        def time_ns(self):
            return int(self.utc_now().timestamp() * 1_000_000_000)

        def wait(self, timeout_seconds):
            del timeout_seconds

        def wait_interruptibly(self, timeout_seconds, wait_for_event):
            if wait_for_event(0.0):
                return True
            timeout_seconds = float(timeout_seconds)
            if timeout_seconds <= 0.0:
                return False
            with self._lock:
                while self._index < len(self._times) and self._times[self._index] <= self._now:
                    self._index += 1
                next_bar = self._times[self._index] if self._index < len(self._times) else None
                next_provider = self._scheduled[0][0] if self._scheduled else None
                candidates = [item for item in (next_bar, next_provider) if item is not None]
                next_event = min(candidates) if candidates else None
                now = self._now
                timeout_deadline = now + timedelta(seconds=timeout_seconds)
                # Model an interruptible wait faithfully: a synthetic clock
                # advances only through the requested timeout or to the next
                # scheduled source event, whichever comes first. If the
                # timeout expires before that event, Cerebro gets a chance to
                # retry its cohort decision without receiving future data.
                self._now = max(
                    now, min(timeout_deadline, next_event) if next_event else timeout_deadline
                )
                while self._index < len(self._times) and self._times[self._index] <= self._now:
                    self._index += 1
                ready = self._take_due_locked()
            # Synthetic time already advanced by the bounded wait. Returning
            # False tells the engine to re-evaluate its decision; an event
            # waker observed before the wait is the only interrupt result.
            self._dispatch(ready)
            return False

    clock = SourceClock(event_times)

    def source_clock_wait_boundary_probe():
        event_at = datetime(2025, 1, 2, tzinfo=timezone.utc)
        probe = SourceClock((event_at,))
        fired_at = []
        probe.schedule_at(event_at, lambda: fired_at.append(probe.utc_now()))
        started_at = probe.utc_now()
        short_return = probe.wait_interruptibly(0.5, lambda _timeout: False)
        after_short = probe.utc_now()
        short_advance = (after_short - started_at).total_seconds()
        fired_after_short = len(fired_at)
        long_return = probe.wait_interruptibly(120.0, lambda _timeout: False)
        finished_at = probe.utc_now()
        return {
            "short_wait_returned": short_return,
            "short_wait_advance_seconds": short_advance,
            "event_not_delivered_before_deadline": fired_after_short == 0,
            "long_wait_returned": long_return,
            "event_delivered_at_scheduled_time": (
                len(fired_at) == 1 and fired_at[0] == event_at and finished_at == event_at
            ),
        }

    wait_boundary_probe = source_clock_wait_boundary_probe()
    assert wait_boundary_probe == {
        "short_wait_returned": False,
        "short_wait_advance_seconds": 0.5,
        "event_not_delivered_before_deadline": True,
        "long_wait_returned": False,
        "event_delivered_at_scheduled_time": True,
    }
    refresh_condition = threading.Condition()
    # Keep the ordinary Strategy projection and the real refresh/publication
    # transaction on one deterministic fake-provider turn.  SourceClock's
    # lock protects only its timestamp and cannot protect the query-set
    # receipt while QueryRefreshLoop temporarily invalidates it.
    fact_turn_lock = threading.RLock()
    refresh_state = {"started": 0, "completed": 0, "errors": []}
    refresh_receipts = []
    refresh_attempt_events = []
    api_instances = []
    fill_timeline = []

    def note_fill_event(kind, **facts):
        if len(fill_timeline) >= 512 or not api_instances or api_instances[-1]._phase != 1:
            return
        fill_timeline.append(
            {
                "sequence": len(fill_timeline),
                "kind": kind,
                "source_time": clock.utc_now().isoformat(),
                "monotonic_ns": time.monotonic_ns(),
                **facts,
            }
        )

    store_write_calls = []
    broker_rejections = []
    reconciliation_observations = []
    dated_page_failure_recorded = {"value": False}
    broker_position_observations = []
    book_position_observations = []
    broker_update_observations = []
    terminal_position_trace = {
        "next_sequence": 0,
        "records": [],
        "record_indexes": {},
        "call_order": [],
        "dropped_unique_inputs": 0,
        "dropped_call_order": 0,
        "observer_errors": 0,
        "first_mismatch": None,
        "last_mismatch": None,
        "first_mismatch_after_broker_update": None,
        "last_broker_update": None,
    }
    active_terminal_observations = []
    terminal_position_event_lock = threading.Lock()

    original_terminal_reconcile = (
        factor_execution_module.FactorExecutionCoordinator.reconcile_terminal_order_observations
    )
    original_one_terminal_reconcile = (
        factor_execution_module.FactorExecutionCoordinator._reconcile_one_terminal_order
    )
    original_terminal_position_consistent = factor_execution_module._terminal_position_consistent

    def begin_terminal_position_event():
        with terminal_position_event_lock:
            terminal_position_trace["next_sequence"] += 1
            return (
                terminal_position_trace["next_sequence"],
                terminal_position_trace["last_broker_update"],
            )

    def record_broker_update_event(event):
        with terminal_position_event_lock:
            terminal_position_trace["next_sequence"] += 1
            event["sequence"] = terminal_position_trace["next_sequence"]
            terminal_position_trace["last_broker_update"] = event
            return event["sequence"]

    def diagnostic_value(value):
        return {
            "type": "{}.{}".format(type(value).__module__, type(value).__qualname__),
            "value": repr(value),
        }

    def terminal_position_inputs(position, facts, observation):
        if position is None:
            return None
        broker_quantity = getattr(position, "broker_quantity", None)
        long_quantity = getattr(position, "long_quantity", None)
        short_quantity = getattr(position, "short_quantity", None)
        broker_is_decimal = isinstance(broker_quantity, Decimal)
        long_is_decimal = isinstance(long_quantity, Decimal)
        short_is_decimal = isinstance(short_quantity, Decimal)
        broker_is_finite = broker_is_decimal and broker_quantity.is_finite()
        long_is_finite = long_is_decimal and long_quantity.is_finite()
        short_is_finite = short_is_decimal and short_quantity.is_finite()
        long_nonnegative = long_is_finite and long_quantity >= 0
        short_nonnegative = short_is_finite and short_quantity >= 0
        sides_consistent = bool(
            long_is_finite and short_is_finite and not (long_quantity > 0 and short_quantity > 0)
        )
        net_quantity_matches = bool(
            broker_is_finite
            and long_is_finite
            and short_is_finite
            and broker_quantity == long_quantity - short_quantity
        )
        try:
            same_time = bool(
                factor_execution_module._same_time(
                    getattr(position, "available_at", None),
                    getattr(facts, "available_at", None),
                )
            )
        except Exception:
            same_time = None
        checks = {
            "snapshot_matches": getattr(position, "snapshot_id", None)
            == getattr(facts, "snapshot_id", None),
            "available_at_matches": same_time,
            "broker_is_finite_decimal": broker_is_finite,
            "long_is_finite_decimal": long_is_finite,
            "long_is_nonnegative": long_nonnegative,
            "short_is_finite_decimal": short_is_finite,
            "short_is_nonnegative": short_nonnegative,
            "sides_are_consistent": sides_consistent,
            "net_quantity_matches_sides": net_quantity_matches,
        }
        comparison_result = (
            all(value is True for value in checks.values()) if None not in checks.values() else None
        )
        return {
            "target": {
                "target_id": getattr(position, "target_id", None),
                "instrument": getattr(position, "instrument", None),
                "exchange": getattr(position, "exchange", None),
                "observation_id": getattr(observation, "observation_id", None),
                "observation_instrument": getattr(observation, "instrument", None),
                "observation_exchange": getattr(observation, "exchange", None),
            },
            "snapshot": {
                "position": diagnostic_value(getattr(position, "snapshot_id", None)),
                "facts": diagnostic_value(getattr(facts, "snapshot_id", None)),
            },
            "available_at": {
                "position": diagnostic_value(getattr(position, "available_at", None)),
                "facts": diagnostic_value(getattr(facts, "available_at", None)),
            },
            "quantities": {
                "broker": diagnostic_value(broker_quantity),
                "long": diagnostic_value(long_quantity),
                "short": diagnostic_value(short_quantity),
            },
            "checks": checks,
            "comparison_result": comparison_result,
        }

    def record_terminal_position_check(
        *,
        sequence,
        source,
        position,
        facts,
        observation,
        result,
        blocker_code=None,
        broker_update_before_check=None,
    ):
        try:
            inputs = terminal_position_inputs(position, facts, observation)
            input_key = json.dumps(
                inputs,
                default=str,
                sort_keys=True,
                separators=(",", ":"),
            )
            if isinstance(result, bool):
                result_projection = result
            else:
                result_projection = {
                    "type": "{}.{}".format(type(result).__module__, type(result).__qualname__),
                    "status": getattr(result, "status", None),
                    "blocker_code": getattr(result, "blocker_code", None),
                }
            is_mismatch = (
                result is False or blocker_code == "TERMINAL_POSITION_RECONCILIATION_MISMATCH"
            )
            with terminal_position_event_lock:
                row_index = terminal_position_trace["record_indexes"].get(input_key)
                if row_index is None and len(terminal_position_trace["records"]) < 16:
                    row_index = len(terminal_position_trace["records"])
                    terminal_position_trace["record_indexes"][input_key] = row_index
                    terminal_position_trace["records"].append(
                        {"input": inputs, "first_sequence": sequence, "sources": [], "calls": []}
                    )
                elif row_index is None:
                    terminal_position_trace["dropped_unique_inputs"] += 1

                call = {
                    "sequence": sequence,
                    "source": source,
                    "input_index": row_index,
                    "result": result_projection,
                    "blocker_code": blocker_code,
                    "broker_update_before_check": (
                        None
                        if broker_update_before_check is None
                        else broker_update_before_check["sequence"]
                    ),
                }
                if len(terminal_position_trace["call_order"]) < 256:
                    terminal_position_trace["call_order"].append(call)
                else:
                    terminal_position_trace["dropped_call_order"] += 1
                if row_index is not None:
                    row = terminal_position_trace["records"][row_index]
                    if source not in row["sources"]:
                        row["sources"].append(source)
                    if len(row["calls"]) < 32:
                        row["calls"].append(call)
                if is_mismatch:
                    mismatch = {
                        "sequence": sequence,
                        "source": source,
                        "input_index": row_index,
                        "input": inputs,
                        "result": result_projection,
                        "blocker_code": blocker_code,
                        "broker_update_before_check": broker_update_before_check,
                    }
                    current = terminal_position_trace["first_mismatch"]
                    if current is None or sequence < current["sequence"]:
                        terminal_position_trace["first_mismatch"] = mismatch
                    current_last = terminal_position_trace["last_mismatch"]
                    if current_last is None or sequence > current_last["sequence"]:
                        terminal_position_trace["last_mismatch"] = mismatch
                    current_after_update = terminal_position_trace[
                        "first_mismatch_after_broker_update"
                    ]
                    if (
                        broker_update_before_check is not None
                        and sequence > broker_update_before_check["sequence"]
                        and (
                            current_after_update is None
                            or sequence < current_after_update["sequence"]
                        )
                    ):
                        terminal_position_trace["first_mismatch_after_broker_update"] = mismatch
        except Exception:
            # Diagnostics must never change a production predicate or callback path.
            with terminal_position_event_lock:
                terminal_position_trace["observer_errors"] += 1

    def traced_terminal_position_consistent(position, facts):
        sequence, broker_update_before_check = begin_terminal_position_event()
        observation = active_terminal_observations[-1] if active_terminal_observations else None
        result = original_terminal_position_consistent(position, facts)
        record_terminal_position_check(
            sequence=sequence,
            source="_terminal_position_consistent",
            position=position,
            facts=facts,
            observation=observation,
            result=result,
            broker_update_before_check=broker_update_before_check,
        )
        return result

    monkeypatch.setattr(
        factor_execution_module,
        "_terminal_position_consistent",
        traced_terminal_position_consistent,
    )

    def traced_one_terminal_reconcile(coordinator, facts, observation, **kwargs):
        sequence, broker_update_before_check = begin_terminal_position_event()
        active_terminal_observations.append(observation)
        try:
            result = original_one_terminal_reconcile(coordinator, facts, observation, **kwargs)
        finally:
            active_terminal_observations.pop()
        blocker_code = getattr(result, "blocker_code", None)
        if blocker_code == "TERMINAL_POSITION_RECONCILIATION_MISMATCH":
            matches = tuple(
                position
                for position in getattr(facts, "positions", ())
                if getattr(position, "instrument", None) == getattr(observation, "instrument", None)
                and getattr(position, "exchange", None) == getattr(observation, "exchange", None)
            )
            record_terminal_position_check(
                sequence=sequence,
                source="_reconcile_one_terminal_order_inline",
                position=matches[0] if len(matches) == 1 else None,
                facts=facts,
                observation=observation,
                result=result,
                blocker_code=blocker_code,
                broker_update_before_check=broker_update_before_check,
            )
        return result

    monkeypatch.setattr(
        factor_execution_module.FactorExecutionCoordinator,
        "_reconcile_one_terminal_order",
        traced_one_terminal_reconcile,
    )

    original_dated_trade_reconcile = (
        factor_position_book_module.FactorPositionBook.reconcile_dated_trade_observations
    )

    def traced_dated_trade_reconcile(position_book, *args, **kwargs):
        page = original_dated_trade_reconcile(position_book, *args, **kwargs)
        api = api_instances[-1] if api_instances else None
        items = tuple(getattr(page, "items", ()))
        item_states = tuple(
            (getattr(item, "status", None), getattr(item, "blocker_code", None))
            for item in items[:16]
        )
        has_blocker = any(
            status not in {"APPLIED", "DUPLICATE", "EXTERNAL_FLAT"} or blocker_code is not None
            for status, blocker_code in item_states
        )
        if (
            api is not None
            and api._phase == 1
            and has_blocker
            and not dated_page_failure_recorded["value"]
        ):
            dated_page_failure_recorded["value"] = True
            note_fill_event(
                "dated_trade_reconciliation_failure_page",
                offset=getattr(page, "offset", None),
                observation_count=getattr(page, "observation_count", None),
                item_states=item_states,
            )
        return page

    monkeypatch.setattr(
        factor_position_book_module.FactorPositionBook,
        "reconcile_dated_trade_observations",
        traced_dated_trade_reconcile,
    )

    def traced_terminal_reconcile(coordinator, facts, **kwargs):
        page = original_terminal_reconcile(coordinator, facts, **kwargs)
        observation = {
            "query_set_id": getattr(facts, "query_set_id", None),
            "available_at": getattr(facts, "available_at", None),
            "observation_count": getattr(page, "observation_count", None),
            "truncated": getattr(page, "truncated", None),
            "items": tuple(
                (
                    getattr(item, "observation_id", None),
                    getattr(item, "status", None),
                    getattr(item, "blocker_code", None),
                    getattr(item, "intent_id", None),
                )
                for item in getattr(page, "items", ())
            ),
        }
        reconciliation_observations.append(observation)
        if any(
            item[1] not in {"RESOLVED", "DUPLICATE", "EXTERNAL_TERMINAL_FLAT"}
            for item in observation["items"]
        ):
            note_fill_event("terminal_reconciliation_blocked", **observation)
        return page

    monkeypatch.setattr(
        factor_execution_module.FactorExecutionCoordinator,
        "reconcile_terminal_order_observations",
        traced_terminal_reconcile,
    )

    original_reject_order = broker_module.BtApiBroker._reject_order

    def traced_reject_order(broker, order, error_code, error_msg):
        broker_rejections.append(
            {
                "ref": getattr(order, "ref", None),
                "data_name": getattr(getattr(order, "data", None), "_name", None),
                "size": getattr(order, "size", None),
                "error_code": error_code,
                "error_msg": error_msg,
            }
        )
        return original_reject_order(broker, order, error_code, error_msg)

    monkeypatch.setattr(broker_module.BtApiBroker, "_reject_order", traced_reject_order)

    original_position_snapshot = broker_module.BtApiBroker.execution_position_snapshot

    def traced_position_snapshot(broker, data):
        snapshot = original_position_snapshot(broker, data)
        broker_position_observations.append(
            (
                getattr(data, "_name", None),
                None if snapshot is None else getattr(snapshot, "quantity", None),
                None if snapshot is None else getattr(snapshot, "long_quantity", None),
                None if snapshot is None else getattr(snapshot, "short_quantity", None),
            )
        )
        return snapshot

    monkeypatch.setattr(
        broker_module.BtApiBroker, "execution_position_snapshot", traced_position_snapshot
    )

    for method_name in ("_apply_order_update", "_apply_trade_update"):
        original_method = getattr(broker_module.BtApiBroker, method_name)

        def trace_broker_update(broker, update, *args, _method=original_method, **kwargs):
            position_before = tuple(
                (key, getattr(position, "size", None)) for key, position in broker.positions.items()
            )
            result = _method(broker, update, *args, **kwargs)
            position_after = tuple(
                (key, getattr(position, "size", None)) for key, position in broker.positions.items()
            )
            last_broker_update = {
                "method": _method.__name__,
                "update_kind": update.get("kind"),
                "status": update.get("status"),
                "order_ref": update.get("order_ref"),
                "trade_id": update.get("trade_id"),
                "position_before": position_before[-8:],
                "position_after": position_after[-8:],
            }
            update_sequence = record_broker_update_event(last_broker_update)
            broker_update_observations.append(
                (
                    _method.__name__,
                    update.get("kind"),
                    update.get("status"),
                    update.get("order_ref"),
                    update.get("trade_id"),
                    result,
                    position_after,
                )
            )
            note_fill_event(
                "broker_update_applied",
                method=_method.__name__,
                observer_sequence=update_sequence,
                update_kind=update.get("kind"),
                status=update.get("status"),
                order_ref=update.get("order_ref"),
                trade_id=update.get("trade_id"),
                result=result,
                position_before=position_before,
                position_after=position_after,
            )
            return result

        monkeypatch.setattr(broker_module.BtApiBroker, method_name, trace_broker_update)

    import backtrader.stores.factor_position_book as position_book_module

    original_book_snapshot = position_book_module.FactorPositionBook.snapshot

    def traced_book_snapshot(book, **kwargs):
        snapshot = original_book_snapshot(book, **kwargs)
        book_position_observations.append(
            (
                kwargs.get("instrument"),
                getattr(snapshot, "status", None),
                getattr(snapshot, "blocker_code", None),
                getattr(snapshot, "signed_quantity", None),
                getattr(snapshot, "attributed_signed_quantity", None),
                getattr(snapshot, "owner_intent_id", None),
            )
        )
        return snapshot

    monkeypatch.setattr(position_book_module.FactorPositionBook, "snapshot", traced_book_snapshot)

    original_store_submit = registered_sim_module.RegisteredSimStore.submit_order

    def traced_store_submit(store, order):
        identity = {
            "ref": getattr(order, "ref", None),
            "data_name": getattr(getattr(order, "data", None), "_name", None),
            "size": getattr(order, "size", None),
            "price": getattr(order, "price", None),
            "info": dict(getattr(order, "info", {})),
        }
        try:
            result = original_store_submit(store, order)
        except Exception as exc:
            store_write_calls.append(
                {
                    "operation": "submit",
                    "identity": identity,
                    "error_type": type(exc).__name__,
                    "error_code": getattr(exc, "code", None),
                    "error": str(exc),
                }
            )
            raise
        store_write_calls.append(
            {"operation": "submit", "identity": identity, "result": repr(result)}
        )
        return result

    monkeypatch.setattr(
        registered_sim_module.RegisteredSimStore, "submit_order", traced_store_submit
    )

    ctp_client_module = None
    for module_name in ("bt_api_ctp.ctp.client", "bt_api_py.ctp.client"):
        try:
            ctp_client_module = __import__(module_name, fromlist=["MdClient", "TraderClient"])
            break
        except ImportError:
            continue
    if ctp_client_module is None:
        pytest.skip("CTP SDK client module is unavailable")

    class SyntheticCtpNativeStopReceipt:
        """Typed fake shutdown receipt for the provider clients above."""

        def __init__(self, connection_generation):
            self.connection_generation = connection_generation
            self.join_required = False
            self.join_completed = True
            self.native_released = True
            self.thread_alive = False
            self.timed_out = False

        @property
        def complete(self):
            return (
                self.native_released is True
                and self.join_completed is True
                and self.thread_alive is False
                and self.timed_out is False
            )

    monkeypatch.setattr(
        ctp_client_module, "CtpNativeStopReceipt", SyntheticCtpNativeStopReceipt, raising=False
    )

    import backtrader.stores.btapistore as btapistore_module

    # Bind Store wall time to the explicit synthetic provider clock. Observe
    # completed production TickEvents below, after provenance stamping.
    # Monotonic time remains real for query TTLs and bounded waits.
    monkeypatch.setattr(
        btapistore_module,
        "time",
        SimpleNamespace(
            time=clock.time,
            monotonic=time.monotonic,
            monotonic_ns=time.monotonic_ns,
            sleep=time.sleep,
        ),
    )

    class Alpha003MdClient:
        """Synthetic MD SDK leaf; production wrapper owns callback binding/normalization."""

        def __init__(self, **_kwargs):
            self._state_lock = threading.RLock()
            self._connection_generation = 1
            self.on_tick = None
            self.on_tick_with_generation = None
            self.on_disconnect = None
            self.on_disconnect_with_generation = None
            self.on_error = None
            self._subscribed = set()
            self._scheduled_bar_ids = set()
            self.stopped = False
            self._api = api_instances[-1]

        @property
        def connection_generation(self):
            with self._state_lock:
                return self._connection_generation

        def start(self, block=False, join_observer=True):
            assert block is False
            assert join_observer is False

        def wait_ready(self, timeout=20):
            del timeout
            return True

        @staticmethod
        def _raw_tick(instrument, exchange, trading_day, event_time):
            local = event_time.astimezone(timezone(timedelta(hours=8)))
            return SimpleNamespace(
                InstrumentID=instrument,
                ExchangeID=exchange,
                LastPrice=100.0,
                Volume=0,
                BidPrice1=99.9,
                AskPrice1=100.1,
                BidVolume1=5,
                AskVolume1=6,
                OpenInterest=0.0,
                Turnover=0.0,
                TradingDay=trading_day.replace("-", ""),
                ActionDay=local.strftime("%Y%m%d"),
                UpdateTime=local.strftime("%H:%M:%S"),
                UpdateMillisec=local.microsecond // 1000,
            )

        def _dispatch_tick(self, payload):
            # Match the SDK's generation-aware callback contract: capture the
            # callback and source generation together, then invoke outside the
            # client lock. The production wrapper owns normalization/queueing.
            with self._state_lock:
                callback = self.on_tick_with_generation
                generation = self._connection_generation
            if not callable(callback):
                raise AssertionError("production wrapper did not bind generation tick callback")
            callback(payload, generation)
            bar_id = getattr(store_callback_time_context, "bar_id", None)
            row = causal_quote_row_by_bar_id.get(bar_id)
            if (
                _causal_quote_barrier
                and row is not None
                and row["bucket_end"] == post_dispatch_probe_close
            ):
                close_time = row["bucket_end"]
                expected_rows = causal_quote_rows_by_close.get(close_time, {})
                expected_bar_ids = tuple(
                    expected_rows[target]["bar_id"]
                    for target in plan["targets"]
                    if target in expected_rows
                )
                with store_tick_fields_lock:
                    all_callbacks_returned = (
                        len(expected_bar_ids) == len(plan["targets"])
                        and all(
                            expected_id in store_tick_fields_by_bar_id
                            for expected_id in expected_bar_ids
                        )
                    )
                    do_advance = (
                        all_callbacks_returned
                        and close_time not in post_dispatch_clock_advanced_closes
                    )
                    if do_advance:
                        post_dispatch_clock_advanced_closes.add(close_time)
                        callback_event = store_tick_fields_by_bar_id[bar_id]
                        callback_fields = {
                            "received_wall_time": getattr(
                                callback_event, "received_wall_time", None
                            ),
                            "ctp_callback_received_wall_time": getattr(
                                callback_event, "ctp_callback_received_wall_time", None
                            ),
                        }
                if do_advance:
                    before_advance = clock.utc_now()
                    clock.advance(timedelta(milliseconds=12))
                    after_advance = clock.utc_now()
                    tick_received_at = datetime.fromtimestamp(
                        callback_fields["received_wall_time"], UTC
                    )
                    advance = {
                        "bar_id": bar_id,
                        "close_time": close_time.isoformat(),
                        "callback_returned_before_advance": True,
                        "advance_milliseconds": 12,
                        "clock_before": before_advance.isoformat(),
                        "clock_after": after_advance.isoformat(),
                        "tick_received_wall_time": tick_received_at.isoformat(),
                        "clock_advanced_after_tick_by_milliseconds": (
                            after_advance - tick_received_at
                        ).total_seconds()
                        * 1000,
                    }
                    if after_advance - before_advance != timedelta(milliseconds=12):
                        raise AssertionError("synthetic post-callback clock advance was not 12ms")
                    with store_tick_fields_lock:
                        post_dispatch_clock_advances_by_close[close_time] = advance
            return generation

        def subscribe(self, instruments):
            with self._state_lock:
                self._subscribed.update(str(item) for item in instruments)
            for instrument in tuple(str(item) for item in instruments):
                rows = self._api._source_bars.get(instrument)
                if rows is None:
                    continue
                for row in tuple(rows):
                    bar_id = row["bar_id"]
                    if bar_id in self._scheduled_bar_ids:
                        continue
                    self._scheduled_bar_ids.add(bar_id)
                    delivery_at = (
                        synthetic_ctp_tick_time(row["bucket_end"])
                        if _causal_quote_barrier
                        else row["available_at"] + timedelta(milliseconds=200)
                    )

                    def deliver(instrument=instrument, row=row, bar_id=bar_id):
                        event_time = synthetic_ctp_tick_time(row["bucket_end"])
                        payload = self._raw_tick(
                            instrument,
                            row["exchange"],
                            row["trading_day"],
                            event_time,
                        )
                        if _capacity_only and row["bucket_end"] == final_close:
                            # This zero-volume quote cannot synthesize the last
                            # bar; that complete BarEvent is the source tape row.
                            assert payload.Volume == 0
                        store_callback_time_context.bar_id = bar_id
                        try:
                            callback_generation = self._dispatch_tick(payload)
                        finally:
                            del store_callback_time_context.bar_id
                        self._api.tick_observations.append(
                            (
                                instrument,
                                bar_id,
                                callback_generation,
                                row["connection_generation"],
                            )
                        )
                        with store_tick_fields_lock:
                            tick_event = store_tick_fields_by_bar_id.get(bar_id)
                        tick_fields = (
                            {
                                "event_id": getattr(tick_event, "event_id", None),
                                "ctp_callback_received_wall_time": getattr(
                                    tick_event, "ctp_callback_received_wall_time", None
                                ),
                                "received_wall_time": getattr(
                                    tick_event, "received_wall_time", None
                                ),
                            }
                            if tick_event is not None
                            else {}
                        )
                        callback_wall_time = tick_fields.get(
                            "ctp_callback_received_wall_time"
                        )
                        received_wall_time = tick_fields.get("received_wall_time")
                        if (
                            not tick_fields
                            or type(callback_wall_time) not in (float, int)
                            or type(received_wall_time) not in (float, int)
                        ):
                            raise AssertionError(
                                "Store did not expose actual stamped TickEvent wall-time fields"
                            )
                        callback_received_at = datetime.fromtimestamp(
                            callback_wall_time, UTC
                        )
                        received_at = datetime.fromtimestamp(received_wall_time, UTC)
                        with causal_quote_receipt_lock:
                            receipt = {
                                "bar_id": bar_id,
                                "instrument": instrument,
                                "target_id": target_by_instrument[instrument],
                                "connection_generation": callback_generation,
                                "source_generation": row.get(
                                    "source_generation", row.get("connection_generation")
                                ),
                                "source_session_generation": row.get(
                                    "source_session_generation", row.get("session_generation")
                                ),
                                "source_stream_generation": row.get(
                                    "stream_generation", getattr(payload, "stream_generation", None)
                                ),
                                "source_sequence": row.get(
                                    "sequence", getattr(payload, "sequence", None)
                                ),
                                "source_clock_domain_id": row.get("clock_domain_id"),
                                "source_role": row.get("source_role"),
                                "trading_day": row.get("trading_day"),
                                "session_segment": row.get("session_segment"),
                                "tick_trading_day": getattr(payload, "TradingDay", None),
                                "tick_action_day": getattr(payload, "ActionDay", None),
                                "tick_update_time": getattr(payload, "UpdateTime", None),
                                "tick_update_millisec": getattr(payload, "UpdateMillisec", None),
                                "event_time": event_time.isoformat(),
                                "scheduled_delivery_at": delivery_at.isoformat(),
                                "tick_event_id": tick_fields.get("event_id"),
                                "ctp_callback_received_wall_time": (
                                    callback_received_at.isoformat()
                                ),
                                "received_wall_time": received_at.isoformat(),
                                "received_at": received_at.isoformat(),
                            }
                            causal_quote_receipt_by_bar_id[bar_id] = receipt
                            if len(causal_quote_receipt_trace) < 512:
                                causal_quote_receipt_trace.append(receipt)
                        receipt_event = causal_quote_receipt_events.get(bar_id)
                        if receipt_event is not None:
                            receipt_event.set()
                        if (
                            self._api._phase == 1
                            and not any(self._api._source_bars.values())
                            and self._api._pending_close_instrument == instrument
                            and self._api._pending_close_callback is not None
                        ):
                            order_ref = self._api._pending_close_callback
                            self._api._pending_close_callback = None
                            self._api._pending_close_instrument = None
                            self._api.trader_client.emit_fill(order_ref)

                    clock.schedule_at(delivery_at, deliver)

        def schedule_winddown_quote(self, instrument, query_set_id, query_completed_at):
            api = self._api
            if instrument in api._winddown_scheduled_instruments:
                return
            route = next(
                ((item, exchange) for item, exchange in route_rows if item == instrument), None
            )
            if route is None:
                raise AssertionError("winddown quote route was not configured")
            _instrument, exchange = route
            event_time = query_completed_at + timedelta(milliseconds=5)
            delivery_at = query_completed_at + timedelta(milliseconds=25)
            api._winddown_scheduled_instruments.add(instrument)
            api._winddown_query_set_for[instrument] = query_set_id
            api._winddown_metadata[instrument] = {
                "query_set_id": query_set_id,
                "query_completed_at": query_completed_at.isoformat(),
                "event_time": event_time.isoformat(),
                "delivery_at": delivery_at.isoformat(),
            }

            def deliver():
                payload = self._raw_tick(
                    instrument,
                    exchange,
                    start_day.strftime("%Y%m%d"),
                    event_time,
                )
                generation = self._dispatch_tick(payload)
                api.tick_observations.append(
                    (instrument, "winddown:" + query_set_id, generation, "provider-scheduled")
                )
                if (
                    api._phase == 1
                    and api._pending_close_instrument == instrument
                    and api._pending_close_callback is not None
                ):
                    order_ref = api._pending_close_callback
                    api._pending_close_callback = None
                    api._pending_close_instrument = None
                    api.trader_client.emit_fill(order_ref)

            clock.schedule_at(delivery_at, deliver)

        def stop(self):
            self.stopped = True

        def stop_and_wait(self, timeout=2.0):
            assert 0.0 <= timeout <= 2.0
            return SyntheticCtpNativeStopReceipt(self.connection_generation)

        def capture_tick_callback(self, payload):
            """Capture generation with callback under SDK lock, invoke outside it."""
            with self._state_lock:
                callback = self.on_tick_with_generation
                generation = self._connection_generation
            if not callable(callback):
                raise AssertionError("production wrapper did not bind generation tick callback")
            return lambda: callback(payload, generation)

        def dispatch_disconnect(self, reason, generation=None):
            with self._state_lock:
                callback = self.on_disconnect_with_generation
                captured_generation = (
                    self._connection_generation if generation is None else generation
                )
            if callable(callback):
                callback(reason, captured_generation)

    class Alpha003TraderClient(facts_fixtures._ProviderLeaves):
        """Synthetic typed-query/trader SDK leaf under the real CTP wrapper."""

        def __init__(self, **_kwargs):
            super().__init__(query_rows=query_rows, query_time=clock.utc_now(), ticks={})
            self._api = api_instances[-1]
            self.trader_client._account_fingerprint = "alpha003-factor-chain-account"
            self.trader_client._trading_day = start_day.strftime("%Y%m%d")
            self.trader_client._connection_generation = 1
            # RegisteredSimStore reads the public fake client's generation/day
            # directly when binding the live factor source; the nested query
            # leaf separately supplies typed query provenance.
            self._account_fingerprint = "alpha003-factor-chain-account"
            self._trading_day = start_day.strftime("%Y%m%d")
            self._connection_generation = 1
            self._front_id = 4
            self._session_id = 7
            self._req_id = 0
            self._next_order_ref_value = 100
            self.is_ready = True
            self.is_read_only_ready = True
            self.is_trading_ready = True
            self.stopped = False
            self.native_calls = self._api.native_calls
            self._provider_orders = {}
            self._fake_active_capability = None

        def start(self, block=False, join_observer=True):
            assert block is False
            assert join_observer is False

        def wait_ready(self, timeout=20):
            del timeout
            return True

        def stop(self):
            self.stopped = True

        def stop_and_wait(self, timeout=2.0):
            assert 0.0 <= timeout <= 2.0
            return SyntheticCtpNativeStopReceipt(self._connection_generation)

        def next_order_ref(self):
            self._next_order_ref_value += 1
            return str(self._next_order_ref_value)

        def get_query_session_scope(self):
            return self.trader_client.get_query_session_scope()

        def get_execution_gate_state(self):
            return dict(self.trader_client.get_execution_gate_state())

        def get_session_state(self):
            state = self.trader_client.get_session_state()
            state.update(
                front_id=self._front_id,
                session_id=self._session_id,
                read_only_ready=self.is_read_only_ready,
                trading_ready=self.is_trading_ready,
            )
            return state

        def arm_execution_for_registered_sim(self, **kwargs):
            capability, state = self.trader_client.arm_execution_for_registered_sim(**kwargs)
            self._fake_active_capability = capability
            return capability, state

        def disarm_execution_gate(self, capability, reason):
            if capability is not self._fake_active_capability:
                raise AssertionError("fake SDK disarm must name the active capability")
            self._fake_active_capability = None
            state = dict(self.trader_client._gate_state)
            state.update(
                managed=False,
                armed=False,
                instrument=None,
                authorized_instruments=[],
                revocation_reason=reason,
            )
            self.trader_client._gate_state = state
            return {"revoked": True}

        def _query_family(self, family, request_type, **filters):
            self.query_rows = dict(query_rows)
            started_at = clock.utc_now()
            self.query_time = started_at + timedelta(milliseconds=2)
            result = super()._query_family(family, request_type, **filters)
            clock.advance(timedelta(milliseconds=2))
            note_fill_event(
                "query_completed",
                family=family,
                request_id=getattr(result, "request_id", None),
                query_started_at=started_at.isoformat(),
                query_completed_at=str(getattr(result, "completed_at_utc", None)),
                row_count=(
                    None if getattr(result, "records", None) is None else len(result.records)
                ),
                query_complete=getattr(result, "complete", None),
            )
            return result

        def query_account(self, timeout=5):
            del timeout
            return dict(query_rows["account_result"][0])

        def query_positions(self, timeout=5):
            del timeout
            return [dict(row) for row in query_rows["positions_result"]]

        def query_instrument(self, instrument, exchange_id="", timeout=5):
            del timeout
            return next(
                (
                    dict(row)
                    for row in query_rows["instruments_result"]
                    if row.get("InstrumentID") == instrument
                    and (not exchange_id or row.get("ExchangeID") == exchange_id)
                ),
                None,
            )

        def query_instrument_margin_rate(self, instrument, exchange_id="", timeout=5):
            del timeout
            return next(
                (
                    dict(row)
                    for row in query_rows["instrument_margin_rate_result"]
                    if row.get("InstrumentID") == instrument
                    and (not exchange_id or row.get("ExchangeID") == exchange_id)
                ),
                None,
            )

        def query_instrument_commission_rate(self, instrument, exchange_id="", timeout=5):
            del timeout
            return {
                "InstrumentID": instrument,
                "ExchangeID": exchange_id,
                "OpenRatioByMoney": "0",
                "OpenRatioByVolume": "0",
                "CloseRatioByMoney": "0",
                "CloseRatioByVolume": "0",
                "CloseTodayRatioByMoney": "0",
                "CloseTodayRatioByVolume": "0",
            }

        def submit_order_insert(self, field, request_id, *, execution_capability):
            if execution_capability is not self._fake_active_capability:
                raise AssertionError("native insert did not receive the exact SDK grant")
            order_ref = str(field.OrderRef)
            offset_flag = str(field.CombOffsetFlag)
            identity = {
                "order_ref": order_ref,
                "order_sys_id": "sys-" + order_ref,
                "instrument_id": str(field.InstrumentID),
                "exchange_id": str(field.ExchangeID),
                "side": "buy" if str(field.Direction) == "0" else "sell",
                "offset_flag": offset_flag,
                "offset": {
                    "0": "open",
                    "1": "close",
                    "3": "close_today",
                    "4": "close_yesterday",
                }.get(offset_flag),
                "size": int(field.VolumeTotalOriginal),
                "price": float(field.LimitPrice),
                "front_id": self._front_id,
                "session_id": self._session_id,
            }
            if identity["offset"] is None:
                raise AssertionError("unexpected CTP offset in source-backed order")
            self._provider_orders[order_ref] = identity
            self.native_calls.append(
                (
                    "insert",
                    identity["instrument_id"],
                    identity["exchange_id"],
                    order_ref,
                    request_id,
                )
            )
            self._publish_order(identity, status="3", filled=0, remaining=identity["size"])
            order_callback = self.on_order
            if not callable(order_callback):
                raise AssertionError("production wrapper did not bind the CTP order callback")
            order_callback(self._ctp_order_event(identity, "3", 0, identity["size"]))
            if (
                self._api._phase == 1
                and identity["offset"] == "open"
                and self._api._pending_fill_callback is None
                and not self._api._applied_fill_query
            ):
                self._api._pending_fill_callback = order_ref
                self._api._pending_fill_instrument = identity["instrument_id"]
            elif self._api._phase == 1 and identity["offset"].startswith("close"):
                self._api._pending_close_callback = order_ref
                self._api._pending_close_instrument = identity["instrument_id"]
            self._api._mark_refresh_required()
            return 0

        def submit_order_action(self, field, request_id, *, execution_capability):
            if execution_capability is not self._fake_active_capability:
                raise AssertionError("native cancel did not receive the exact SDK grant")
            order_ref = str(field.OrderRef)
            identity = self._provider_orders[order_ref]
            self.native_calls.append(
                (
                    "cancel",
                    identity["instrument_id"],
                    identity["exchange_id"],
                    order_ref,
                    request_id,
                )
            )
            self._publish_order(identity, status="5", filled=0, remaining=identity["size"])
            self.on_order(self._ctp_order_event(identity, "5", 0, identity["size"]))
            self._api._mark_refresh_required()
            return 0

        def _ctp_order_event(self, identity, status, filled, remaining):
            local = clock.utc_now().astimezone(timezone(timedelta(hours=8)))
            return SimpleNamespace(
                OrderRef=identity["order_ref"],
                OrderSysID=identity["order_sys_id"],
                InstrumentID=identity["instrument_id"],
                ExchangeID=identity["exchange_id"],
                FrontID=identity["front_id"],
                SessionID=identity["session_id"],
                OrderStatus=status,
                OrderSubmitStatus="3",
                Direction="0" if identity["side"] == "buy" else "1",
                CombOffsetFlag=identity["offset_flag"],
                VolumeTotalOriginal=identity["size"],
                VolumeTraded=filled,
                VolumeTotal=remaining,
                LimitPrice=identity["price"],
                TradingDay=start_day.strftime("%Y%m%d"),
                InsertTime=local.strftime("%H:%M:%S"),
                UpdateTime=local.strftime("%H:%M:%S"),
            )

        def _publish_order(self, identity, *, status, filled, remaining):
            row = {
                "OrderRef": identity["order_ref"],
                "OrderSysID": identity["order_sys_id"],
                "InstrumentID": identity["instrument_id"],
                "ExchangeID": identity["exchange_id"],
                "TradingDay": start_day.strftime("%Y%m%d"),
                "FrontID": identity["front_id"],
                "SessionID": identity["session_id"],
                "OrderStatus": status,
                "OrderSubmitStatus": "3",
                "Direction": "0" if identity["side"] == "buy" else "1",
                "CombOffsetFlag": identity["offset_flag"],
                "VolumeTotalOriginal": identity["size"],
                "VolumeTraded": filled,
                "VolumeTotal": remaining,
                "LimitPrice": identity["price"],
            }
            rows = query_rows["orders_result"]
            rows[:] = [item for item in rows if str(item.get("OrderRef")) != identity["order_ref"]]
            rows.append(row)

        def emit_fill(self, order_ref):
            identity = self._provider_orders[str(order_ref)]
            quantity = identity["size"]
            self._publish_order(identity, status="0", filled=quantity, remaining=0)
            self.on_order(self._ctp_order_event(identity, "0", quantity, 0))
            local = clock.utc_now().astimezone(timezone(timedelta(hours=8)))
            trade_id = "alpha003-{}-{}".format(identity["offset"], identity["order_ref"])
            offset_flag = identity["offset_flag"]
            trade = SimpleNamespace(
                TradeID=trade_id,
                OrderRef=identity["order_ref"],
                OrderSysID=identity["order_sys_id"],
                InstrumentID=identity["instrument_id"],
                ExchangeID=identity["exchange_id"],
                Direction="0" if identity["side"] == "buy" else "1",
                OffsetFlag=offset_flag,
                HedgeFlag="1",
                Volume=quantity,
                Price=100.0,
                TradeDate=local.strftime("%Y%m%d"),
                TradeTime=local.strftime("%H:%M:%S"),
                TradingDay=start_day.strftime("%Y%m%d"),
            )
            self.on_trade(trade)
            query_rows["trades_result"].append(
                {
                    "TradeID": trade_id,
                    "OrderRef": identity["order_ref"],
                    "OrderSysID": identity["order_sys_id"],
                    "InstrumentID": identity["instrument_id"],
                    "ExchangeID": identity["exchange_id"],
                    "Direction": trade.Direction,
                    "OffsetFlag": offset_flag,
                    "HedgeFlag": "1",
                    "Volume": str(quantity),
                    "Price": "100",
                    "TradeDate": trade.TradeDate,
                    "TradeTime": trade.TradeTime,
                    "TradingDay": start_day.strftime("%Y%m%d"),
                }
            )
            if identity["offset"] == "open":
                position = facts_fixtures._dated_position_row(
                    quantity,
                    side="LONG" if identity["side"] == "buy" else "SHORT",
                    trading_day=start_day.strftime("%Y%m%d"),
                    PositionCost=str(Decimal(quantity) * Decimal("1000")),
                )
                position.update(
                    InstrumentID=identity["instrument_id"], ExchangeID=identity["exchange_id"]
                )
                query_rows["positions_result"][:] = [
                    row
                    for row in query_rows["positions_result"]
                    if row.get("InstrumentID") != identity["instrument_id"]
                ]
                query_rows["positions_result"].append(position)
            else:
                query_rows["positions_result"][:] = [
                    row
                    for row in query_rows["positions_result"]
                    if row.get("InstrumentID") != identity["instrument_id"]
                ]
            note_fill_event(
                "provider_callback_fill",
                order_ref=identity["order_ref"],
                trade_id=trade_id,
                offset=identity["offset"],
                query_position_rows=tuple(
                    (row.get("InstrumentID"), row.get("Position"))
                    for row in query_rows["positions_result"]
                ),
            )
            self._api._mark_refresh_required()
            if identity["offset"] == "open":
                self._api._pending_fill_callback = None
                self._api._pending_fill_instrument = None
                self._api._applied_fill_query = True

    monkeypatch.setattr(ctp_client_module, "MdClient", Alpha003MdClient)
    monkeypatch.setattr(ctp_client_module, "TraderClient", Alpha003TraderClient)

    # Retain the actual TickEvent object created by Store. Its fields are read
    # only after the full callback returns, so later Store provenance stamping
    # is included rather than reconstructed from a wrapper clock sample.
    tick_event_class = btapistore_module.TickEvent
    original_tick_event_init = tick_event_class.__init__

    def observe_tick_event_init(event, *args, **kwargs):
        result = original_tick_event_init(event, *args, **kwargs)
        bar_id = getattr(store_callback_time_context, "bar_id", None)
        if type(bar_id) is str and bar_id:
            with store_tick_fields_lock:
                if bar_id in store_tick_fields_by_bar_id:
                    raise AssertionError("duplicate production TickEvent for source bar")
                store_tick_fields_by_bar_id[bar_id] = event
        return result

    monkeypatch.setattr(tick_event_class, "__init__", observe_tick_event_init)
    CtpClientWrapper = btapistore_module._create_ctp_wrapper_class()

    class Alpha003BarTapeMixin(CtpClientWrapper):
        """Only the completed-bar tape is fake; all live CTP paths stay real."""

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._source_bars = bars_by_instrument
            self._phase = len(api_instances)
            self._sent_tick_for = set()
            self._winddown_metadata = {}
            self._winddown_query_set_for = {}
            self._winddown_scheduled_instruments = set()
            self._pending_fill_callback = None
            self._pending_fill_instrument = None
            self._pending_close_callback = None
            self._pending_close_instrument = None
            self._applied_fill_query = False
            self.native_calls = []
            self.tick_observations = []
            self.winddown_tick_observations = []
            self.winddown_poll_attempts = 0
            self.winddown_poll_blockers = []
            self._required_refresh_start = None
            api_instances.append(self)

        @property
        def closed(self):
            return bool(
                self.md_client is not None
                and self.trader_client is not None
                and self.md_client.stopped
                and self.trader_client.stopped
            )

        def _mark_refresh_required(self):
            with refresh_condition:
                self._required_refresh_start = refresh_state["started"] + 1

        def _wait_for_refresh(self):
            with refresh_condition:
                required = self._required_refresh_start
                if required is None:
                    return
                if not refresh_condition.wait_for(
                    lambda: refresh_state["completed"] >= required,
                    timeout=4.0,
                ):
                    raise AssertionError(
                        "complete provider query refresh did not follow order write"
                    )
                self._required_refresh_start = None

        def poll_bar(self, instrument):
            self._wait_for_refresh()
            if (
                self._phase == 1
                and instrument == self._pending_fill_instrument
                and self._pending_fill_callback is not None
                and not self._applied_fill_query
            ):
                order_ref = self._pending_fill_callback
                note_fill_event(
                    "provider_fill_scheduled_from_bar_tape",
                    order_ref=order_ref,
                    instrument=instrument,
                    query_position_before=tuple(
                        (row.get("InstrumentID"), row.get("Position"))
                        for row in query_rows["positions_result"]
                    ),
                )
                self.trader_client.emit_fill(order_ref)
            rows = self._source_bars.get(instrument)
            if not rows or rows[0]["available_at"] > clock.utc_now():
                return None
            row = dict(rows.popleft())
            self._sent_tick_for.discard(row["bar_id"])
            # The source fixture stores ISO dates, while the live CTP cohort
            # calendar and native bar contract use compact YYYYMMDD trading
            # days. Convert at this synthetic live-provider boundary so both
            # ordinary order-chain and capacity runs exercise the same shape.
            row["trading_day"] = row["trading_day"].replace("-", "")
            return row

    def client_generation(api):
        return api.md_client.connection_generation

    original_factory = registered_sim_module._make_api_factory
    monkeypatch.setattr(
        registered_sim_module,
        "_make_api_factory",
        lambda allow_writes, history_limit, terminal_limit, api_cls: original_factory(
            allow_writes, history_limit, terminal_limit, Alpha003BarTapeMixin
        ),
    )
    synthetic_profile = "synthetic-simnow-profile-v1"
    synthetic_td_front = "fixture://simnow/trader"
    synthetic_md_front = "fixture://simnow/market-data"

    def synthetic_fronts(profile):
        if profile != synthetic_profile:
            raise KeyError(profile)
        return synthetic_td_front, synthetic_md_front

    def synthetic_profile_for_td_front(td_front):
        return synthetic_profile if td_front == synthetic_td_front else None

    def verify_synthetic_profile(td_front, md_front, profile):
        return (td_front, md_front, profile) == (
            synthetic_td_front,
            synthetic_md_front,
            synthetic_profile,
        )

    monkeypatch.setattr(
        RUNNER,
        "_sdk_profile_contract",
        lambda: (
            synthetic_fronts,
            synthetic_profile_for_td_front,
            verify_synthetic_profile,
        ),
    )
    synthetic_store_config = {
        "td_address": synthetic_td_front,
        "md_address": synthetic_md_front,
        "ctp_env_profile": synthetic_profile,
        "environment": "simnow",
        "broker_id": "9999",
        "investor_id": "fixture",
        "password": "unused synthetic placeholder",
    }
    synthetic_api_kwargs = {}
    monkeypatch.setattr(
        RUNNER,
        "_live_env_config",
        lambda _config: (dict(synthetic_store_config), dict(synthetic_api_kwargs)),
    )
    monkeypatch.setattr(RUNNER, "RunnerWallClock", lambda: clock)

    captured_strategies = []
    trade_notify_observations = []
    strategy_decision_trace = []
    idle_decision_trace = []
    store_tick_trace = []
    chain_trace = []
    risk_scope_trace = []
    risk_dispatch_trace = []
    bar_source_trace = {
        "count": 0,
        "samples": [],
        "sample_limit": 24,
        "first_by_target": {},
        "by_target_count": {target: 0 for target in plan["targets"]},
        "mapping_match_count": {target: 0 for target in plan["targets"]},
        "mapping_mismatch_count": {target: 0 for target in plan["targets"]},
        "first_error": None,
        "observer_errors": 0,
    }
    bar_source_trace_lock = threading.Lock()
    diagnostic_path = (
        Path(_diagnostic_path)
        if _diagnostic_path is not None
        else tmp_path / "alpha003-capacity-diagnostic.json"
        if _capacity_only
        else Path(__file__).resolve().parents[2]
        / ".codex-tmp"
        / "alpha003_registered_sim_order_chain_{}.json".format(time.time_ns())
    )

    original_capture_cohort_source = btapifeed_module.BtApiFeed._cohort_capture_source

    def traced_capture_cohort_source(feed, event, source_role, received_monotonic_ns, max_slot):
        sample = None
        try:

            def value(*names, default=None):
                return btapifeed_module._tick_value(event, *names, default=default)

            cohort = getattr(feed, "_live_bar_cohort", None)
            member = cohort.member_for_feed(feed) if cohort is not None else None
            slot_index = feed._cohort_event_slot_index(event)
            slots = getattr(getattr(cohort, "_calendar", None), "slots", ())
            slot = (
                slots[slot_index]
                if isinstance(slot_index, int) and 0 <= slot_index < len(slots)
                else None
            )
            member_sessions = getattr(slot, "member_sessions", {}) if slot is not None else {}
            expected_member_session = (
                member_sessions.get(member.member_id)
                if member is not None and hasattr(member_sessions, "get")
                else None
            )
            sample = {
                "feed_member_id": getattr(member, "member_id", None),
                "feed_instrument": getattr(feed, "_dataname", None),
                "feed_name": getattr(feed, "_name", None),
                "source_role": source_role,
                "source_ref": value("source_ref"),
                "source_route": value(
                    "route", "instrument", "instrument_id", "InstrumentID", "source", "symbol"
                ),
                "source_exchange": value("exchange", "exchange_id", "ExchangeID"),
                "source_generation": value("connection_generation"),
                "source_target": value("target", "ctp_factor_target_id"),
                "source_binding_target": value("ctp_factor_target_id"),
                "source_product": value("ctp_factor_product"),
                "source_calendar_hash": value("ctp_source_calendar_hash"),
                "source_clock_domain_id": value("clock_domain_id"),
                "actual_trading_day": value("trading_day"),
                "actual_session_segment": value("session_segment"),
                "actual_bucket_start": value("bucket_start"),
                "actual_close_time": value("bucket_end"),
                "actual_timestamp": value("timestamp"),
                "actual_available_at": value("available_at"),
                "planned_slot_index": slot_index,
                "planned_slot_id": getattr(slot, "slot_id", None),
                "planned_bucket_start": getattr(slot, "bucket_start", None),
                "planned_close_time": getattr(slot, "close_time", None),
                "planned_trading_day": getattr(
                    expected_member_session, "trading_day", getattr(slot, "trading_day", None)
                ),
                "planned_session_segment": getattr(
                    expected_member_session,
                    "session_segment",
                    getattr(slot, "session_segment", None),
                ),
            }
            sample["time_session_route_matches_planned_slot"] = bool(
                slot is not None
                and member is not None
                and sample["actual_bucket_start"] == sample["planned_bucket_start"]
                and sample["actual_close_time"] == slot.close_time
                and sample["actual_trading_day"] == sample["planned_trading_day"]
                and sample["actual_session_segment"] == sample["planned_session_segment"]
                and sample["feed_instrument"] == member.instrument
                and sample["source_generation"] not in (None, "", 0)
                and isinstance(sample["actual_available_at"], datetime)
                and sample["actual_available_at"] >= slot.close_time
                and (
                    sample["actual_timestamp"] is None
                    or (
                        type(sample["actual_timestamp"]) in (int, float)
                        and abs(sample["actual_timestamp"] - slot.close_time.timestamp()) <= 1.0e-6
                    )
                )
            )
            target = sample["source_target"]
            if target not in bar_source_trace["by_target_count"]:
                target = target_by_instrument.get(sample["feed_instrument"])
            with bar_source_trace_lock:
                bar_source_trace["count"] += 1
                if target in bar_source_trace["by_target_count"]:
                    bar_source_trace["by_target_count"][target] += 1
                    mapping_key = (
                        "mapping_match_count"
                        if sample["time_session_route_matches_planned_slot"]
                        else "mapping_mismatch_count"
                    )
                    bar_source_trace[mapping_key][target] += 1
                    bar_source_trace["first_by_target"].setdefault(target, sample)
                if len(bar_source_trace["samples"]) < bar_source_trace["sample_limit"]:
                    bar_source_trace["samples"].append(sample)
        except Exception:
            with bar_source_trace_lock:
                bar_source_trace["observer_errors"] += 1
        try:
            return original_capture_cohort_source(
                feed, event, source_role, received_monotonic_ns, max_slot
            )
        except Exception as exc:
            if sample is not None:
                with bar_source_trace_lock:
                    if bar_source_trace["first_error"] is None:
                        bar_source_trace["first_error"] = {
                            "type": type(exc).__name__,
                            "message": str(exc)[:256],
                            "sample": sample,
                        }
            raise

    monkeypatch.setattr(
        btapifeed_module.BtApiFeed,
        "_cohort_capture_source",
        traced_capture_cohort_source,
    )

    def persist_diagnostic(stage, *, result_value=None, error=None, archive_evidence=None):
        def capacity_summary(report):
            if not hasattr(report, "get"):
                return None
            expected = tuple(
                ordinal
                for ordinal in (report.get("expected_ordinals") or ())
                if type(ordinal) is int
            )
            samples = []
            for sample in tuple(report.get("samples") or ())[:16]:
                if not hasattr(sample, "get"):
                    continue
                ordinal = sample.get("ordinal")
                samples.append(
                    {
                        "ordinal": ordinal if type(ordinal) is int else None,
                        "status": sample.get("status"),
                        "issues": tuple(sample.get("issues") or ())[:16],
                        "lines": _bounded_capacity_fact_projection(
                            sample.get("lines"), group="lines"
                        ),
                        "diagnostics": _bounded_capacity_fact_projection(
                            sample.get("diagnostics"), group="diagnostics"
                        ),
                    }
                )
            observed = tuple(
                sample["ordinal"] for sample in samples if type(sample.get("ordinal")) is int
            )
            return {
                "run_id": report.get("run_id"),
                "status": report.get("status"),
                "issues": tuple(report.get("issues") or ())[:32],
                "first_ready_engine_phase": report.get("first_ready_engine_phase"),
                "calendar_slot_count": report.get("calendar_slot_count"),
                "sample_count": report.get("sample_count"),
                "expected_ordinals": expected,
                "observed_ordinals": observed,
                "missing_ordinals": tuple(value for value in expected if value not in observed),
                "samples": tuple(samples),
            }

        def result_summary(value):
            if not isinstance(value, dict):
                return None
            if "phase1" in value or "phase2" in value:
                return {
                    phase: result_summary(value.get(phase))
                    for phase in ("phase1", "phase2")
                    if phase in value
                }
            summary = {
                key: value.get(key)
                for key in (
                    "write_mode",
                    "shutdown_status",
                    "cleanup_complete",
                    "resource_shutdown",
                    "strategy_shutdown_blocker",
                    "strategy_shutdown_post_join_blocker",
                    "decision_tape",
                    "decision_tape_readback",
                )
                if key in value
            }
            if "live_capacity" in value:
                summary["live_capacity"] = capacity_summary(value.get("live_capacity"))
            events = value.get("strategy_order_events")
            if isinstance(events, dict):
                summary["strategy_order_events"] = {
                    "events": tuple(tuple(events.get("events") or ())[-32:])
                }
            return summary

        strategy = captured_strategies[-1] if captured_strategies else None
        refresh_loop = (
            getattr(getattr(strategy, "p", None), "control_refresh_loop", None)
            if strategy is not None
            else None
        )
        fact = getattr(strategy, "last_execution_facts", None)
        plan_now = getattr(strategy, "last_order_plan", None)
        payload = {
            "schema": "alpha003_registered_sim_order_chain_diagnostic_v1",
            "stage": stage,
            "captured_at_utc": clock.utc_now().isoformat(),
            "argv": tuple(sys.argv),
            "error": (None if error is None else (type(error).__name__, str(error)[:512])),
            "refresh": {
                "started": refresh_state["started"],
                "completed": refresh_state["completed"],
                "errors": tuple(refresh_state["errors"][-16:]),
                "receipts": tuple(refresh_receipts[-32:]),
                "published_query_set_id": getattr(
                    getattr(getattr(refresh_loop, "last_receipt", None), "query_set", None),
                    "query_set_id",
                    None,
                ),
                "published_facts_query_set_id": getattr(
                    getattr(refresh_loop, "last_facts", None), "query_set_id", None
                ),
                "last_error_code": getattr(refresh_loop, "last_error_code", None),
            },
            "strategy": (
                None
                if strategy is None
                else {
                    "last_batch_id": strategy._last_batch_id,
                    "last_execution_block_reason": strategy.last_execution_block_reason,
                    "facts": (
                        None
                        if fact is None
                        else {
                            "snapshot_id": getattr(fact, "snapshot_id", None),
                            "query_set_id": getattr(fact, "query_set_id", None),
                            "available_at": getattr(fact, "available_at", None),
                            "blockers": getattr(fact, "blockers", None),
                            "risk_reduction_blockers": getattr(
                                fact, "risk_reduction_blockers", None
                            ),
                            "order_cancel_blockers": getattr(fact, "order_cancel_blockers", None),
                            "quotes": tuple(
                                (
                                    getattr(quote, "instrument", None),
                                    getattr(quote, "source", None),
                                    getattr(quote, "sequence", None),
                                    getattr(quote, "event_time", None),
                                    getattr(quote, "available_at", None),
                                    getattr(quote, "quality", None),
                                )
                                for quote in getattr(fact, "quotes", ())
                            ),
                        }
                    ),
                    "plan": (
                        None
                        if plan_now is None
                        else {
                            "status": getattr(plan_now, "status", None),
                            "reason": getattr(plan_now, "reason", None),
                            "actions": tuple(
                                (
                                    getattr(action, "action", None),
                                    getattr(action, "instrument", None),
                                    getattr(action, "position_effect", None),
                                    getattr(action, "quantity", None),
                                    getattr(action, "offset", None),
                                    getattr(action, "reason", None),
                                )
                                for action in getattr(plan_now, "actions", ())
                            ),
                        }
                    ),
                    "order_events": tuple(
                        dict(event) if hasattr(event, "items") else str(event)[:512]
                        for event in tuple(getattr(strategy, "order_events", ()) or ())[-16:]
                    ),
                    "trade_events": tuple(
                        dict(event)
                        for event in tuple(getattr(strategy, "trade_events", ()) or ())[-16:]
                    ),
                }
            ),
            "trade_notify_observations": tuple(trade_notify_observations[-32:]),
            "apis": tuple(
                {
                    "phase": current_api._phase,
                    "closed": current_api.closed,
                    "native_calls": tuple(current_api.native_calls[-64:]),
                }
                for current_api in api_instances[-2:]
            ),
            "provider_rows": {
                family: tuple(query_rows.get(family, ())[-32:])
                for family in (
                    "account_result",
                    "positions_result",
                    "orders_result",
                    "trades_result",
                    "instruments_result",
                    "instrument_margin_rate_result",
                )
            },
            "archive_evidence": archive_evidence,
            "refresh_counts": (refresh_state["started"], refresh_state["completed"]),
            "strategy_callbacks": tuple(strategy_decision_trace[-256:]),
            "provider_timeline": tuple(fill_timeline[-512:]),
            "store_ticks": tuple(store_tick_trace[-128:]),
            "chain_trace": tuple(chain_trace[-128:]),
            "source_calendar_trace": source_calendar_trace,
            "source_clock_freshness_trace": (
                {
                    "call_count": clock.snapshot_clock_trace["call_count"],
                    "observer_errors": clock.snapshot_clock_trace["observer_errors"],
                    "sample_limit": clock.snapshot_clock_trace["sample_limit"],
                    "samples": tuple(clock.snapshot_clock_trace["samples"]),
                }
                if _capture_capacity
                else None
            ),
            "bar_source_trace": {
                **bar_source_trace,
                "samples": tuple(bar_source_trace["samples"]),
            },
            "risk_scopes": tuple(risk_scope_trace[-64:]),
            "risk_dispatch": tuple(risk_dispatch_trace[-32:]),
            "reconciliation": tuple(reconciliation_observations[-32:]),
            "terminal_position_checks": tuple(
                {
                    "input": record["input"],
                    "first_sequence": record["first_sequence"],
                    "sources": tuple(record["sources"]),
                    "calls": tuple(record["calls"]),
                }
                for record in sorted(
                    terminal_position_trace["records"], key=lambda item: item["first_sequence"]
                )
            ),
            "terminal_position_call_order": tuple(
                sorted(terminal_position_trace["call_order"], key=lambda item: item["sequence"])
            ),
            "terminal_position_trace_bounds": {
                "unique_inputs_limit": 16,
                "unique_inputs_dropped": terminal_position_trace["dropped_unique_inputs"],
                "call_order_limit": 256,
                "call_order_dropped": terminal_position_trace["dropped_call_order"],
                "observer_errors": terminal_position_trace["observer_errors"],
            },
            "terminal_position_first_mismatch": terminal_position_trace["first_mismatch"],
            "terminal_position_last_mismatch": terminal_position_trace["last_mismatch"],
            "terminal_position_first_mismatch_after_broker_update": terminal_position_trace[
                "first_mismatch_after_broker_update"
            ],
            "terminal_position_last_broker_update": terminal_position_trace["last_broker_update"],
            "broker_position_observations": tuple(broker_position_observations[-16:]),
            "store_write_calls": tuple(store_write_calls[-64:]),
            "broker_rejections": tuple(broker_rejections[-64:]),
            "result": result_summary(result_value),
        }
        diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
        diagnostic_path.write_text(
            json.dumps(payload, default=str, sort_keys=True, indent=2), encoding="utf-8"
        )
        return str(diagnostic_path)

    original_scope_enter = factor_execution_module.FactorExecutionDecisionScope.__enter__

    def traced_scope_enter(scope):
        try:
            result = original_scope_enter(scope)
        except Exception as error:
            if getattr(scope, "risk_only", False):
                risk_scope_trace.append(
                    {
                        "kind": "risk_scope_enter_failed",
                        "decision_kind": getattr(scope.key, "decision_kind", None),
                        "close_time": getattr(scope.key, "close_time", None),
                        "intents": tuple(scope.intent_keys),
                        "error": (type(error).__name__, str(error)),
                    }
                )
            raise
        if getattr(scope, "risk_only", False):
            risk_scope_trace.append(
                {
                    "kind": "risk_scope_entered",
                    "decision_kind": getattr(scope.key, "decision_kind", None),
                    "close_time": getattr(scope.key, "close_time", None),
                    "decision_id": scope.decision_id,
                    "intent_keys": tuple(scope.intent_keys),
                    "dispatch_allowed": scope.dispatch_allowed,
                    "is_new_grid": scope.is_new_grid,
                    "run_order_intents_used": scope.run_order_intents_used,
                }
            )
        if len(risk_scope_trace) > 64:
            del risk_scope_trace[:-64]
        return result

    monkeypatch.setattr(
        factor_execution_module.FactorExecutionDecisionScope,
        "__enter__",
        traced_scope_enter,
    )
    original_bind_strategy = RUNNER.QueryRefreshLoop.bind_strategy

    def capture_bound_strategy(loop, strategy):
        original_bind_strategy(loop, strategy)
        captured_strategies.append(strategy)

        original_next = strategy.next
        original_notify_idle = strategy.notify_idle
        original_run_live = strategy._run_live
        original_notify_trade = strategy.notify_trade
        strategy_index = len(captured_strategies) - 1

        def observe_notify_trade(trade):
            result = original_notify_trade(trade)
            event = dict(strategy.trade_events[-1])
            assert event["ref"] == trade.ref
            trade_notify_observations.append(
                {
                    "strategy_index": strategy_index,
                    "event": event,
                    "trade_ref": trade.ref,
                    "instrument_id": getattr(trade.data, "_dataname", None),
                    "data_name": getattr(trade.data, "_name", None),
                    "long": trade.long,
                    "size": str(trade.size),
                    "price": str(trade.price),
                    "pnl": str(trade.pnl),
                    "pnlcomm": str(trade.pnlcomm),
                    "commission": str(trade.commission),
                    "isclosed": bool(trade.isclosed),
                }
            )
            return result

        strategy.notify_trade = observe_notify_trade

        def parse_refresh_time(record, key):
            try:
                value = datetime.fromisoformat(record[key])
            except (KeyError, TypeError, ValueError):
                return None
            return value if isinstance(value, datetime) else None

        def project_refresh_attempt(record, latest_quote_received_at):
            started_at = parse_refresh_time(record, "started_at")
            completed_at = parse_refresh_time(record, "completed_at")
            provenance = tuple(record.get("provenance") or ())
            query_set_id = record.get("query_set_id")
            return {
                "attempt": record.get("attempt"),
                "attempt_status": record.get("attempt_status"),
                "return_category": record.get("return_category"),
                "exception_type": record.get("exception_type"),
                "last_error_code": record.get("last_error_code"),
                "started_at": record.get("started_at"),
                "completed_at": record.get("completed_at"),
                "started_after_quote_receipt": bool(
                    started_at is not None and started_at > latest_quote_received_at
                ),
                "completed_at_or_after_quote_receipt": bool(
                    completed_at is not None and completed_at >= latest_quote_received_at
                ),
                "error_code": record.get("error_code"),
                "blockers": tuple(record.get("blockers") or ())[:8],
                "pending_families": tuple(record.get("pending_families") or ())[:8],
                "cancelled": record.get("cancelled"),
                "deadline_reached": record.get("deadline_reached"),
                "requested_families": tuple(record.get("requested_families") or ())[:8],
                "attempted_families": tuple(record.get("attempted_families") or ())[:8],
                "query_set_id_present": type(query_set_id) is str and bool(query_set_id),
                "query_set_id": query_set_id if type(query_set_id) is str else None,
                "last_facts_present": record.get("last_facts_present"),
                "last_facts_query_set_id_present": bool(
                    record.get("last_facts_query_set_id")
                ),
                "last_facts_query_set_id": record.get("last_facts_query_set_id"),
                "last_facts_available_at": record.get("last_facts_available_at"),
                "last_facts_blockers": tuple(record.get("last_facts_blockers") or ())[:8],
                "provenance_count": len(provenance),
                "query_complete_count": sum(
                    len(row) > 2 and row[2] is True for row in provenance
                ),
                "source_owned_count": sum(
                    len(row) > 3 and row[3] is True for row in provenance
                ),
                "scope_complete_count": sum(
                    len(row) > 4 and row[4] is True for row in provenance
                ),
            }

        def post_quote_refresh_attempts(latest_quote_received_at):
            projected = []
            with refresh_condition:
                attempt_events = tuple(refresh_attempt_events)
            for record in attempt_events:
                started_at = parse_refresh_time(record, "started_at")
                completed_at = parse_refresh_time(record, "completed_at")
                if (
                    started_at is not None
                    and (
                        started_at > latest_quote_received_at
                        or (
                            completed_at is not None
                            and completed_at >= latest_quote_received_at
                        )
                    )
                ):
                    projected.append(project_refresh_attempt(record, latest_quote_received_at))
            if len(projected) <= 8:
                return tuple(projected), len(projected), False
            return tuple(projected[:4] + projected[-4:]), len(projected), True

        def refresh_loop_projection(refresh_loop):
            receipt = getattr(refresh_loop, "last_receipt", None)
            query_set = getattr(receipt, "query_set", None)
            receipt_query_set_id = getattr(query_set, "query_set_id", None)
            facts = getattr(refresh_loop, "last_facts", None)
            facts_query_set_id = getattr(facts, "query_set_id", None)
            receipt_blockers = tuple(getattr(receipt, "blockers", ()) or ())[:8]
            receipt_pending = tuple(getattr(receipt, "pending_families", ()) or ())[:8]
            facts_blockers = tuple(getattr(facts, "blockers", ()) or ())[:8]
            return {
                "receipt_present": receipt is not None,
                "receipt_query_set_id_present": (
                    type(receipt_query_set_id) is str and bool(receipt_query_set_id)
                ),
                "receipt_query_set_id": (
                    receipt_query_set_id if type(receipt_query_set_id) is str else None
                ),
                "receipt_blockers": receipt_blockers,
                "receipt_pending_families": receipt_pending,
                "receipt_cancelled": getattr(receipt, "cancelled", None),
                "receipt_deadline_reached": getattr(receipt, "deadline_reached", None),
                "last_error_code": getattr(refresh_loop, "last_error_code", None),
                "last_reconciliation_blocker_count": len(
                    tuple(getattr(refresh_loop, "last_reconciliation_blockers", ()) or ())
                ),
                "last_facts_present": facts is not None,
                "last_facts_query_set_id_present": (
                    type(facts_query_set_id) is str and bool(facts_query_set_id)
                ),
                "last_facts_query_set_id": (
                    facts_query_set_id if type(facts_query_set_id) is str else None
                ),
                "last_facts_available_at": getattr(facts, "available_at", None),
                "last_facts_snapshot_id_present": bool(getattr(facts, "snapshot_id", None)),
                "last_facts_blockers": facts_blockers,
            }

        def refresh_attempt_is_successful_after_quote(record, latest_quote_received_at):
            started_at = parse_refresh_time(record, "started_at")
            completed_at = parse_refresh_time(record, "completed_at")
            query_set_id = record.get("query_set_id")
            return bool(
                started_at is not None
                and started_at > latest_quote_received_at
                and completed_at is not None
                and completed_at >= latest_quote_received_at
                and record.get("error_code") is None
                and not record.get("blockers")
                and not record.get("pending_families")
                and record.get("cancelled") is False
                and record.get("deadline_reached") is False
                and type(query_set_id) is str
                and bool(query_set_id)
                and record.get("last_facts_present") is True
                and record.get("last_facts_query_set_id") == query_set_id
            )

        def successful_refresh_for_query_set(query_set_id, latest_quote_received_at):
            if type(query_set_id) is not str or not query_set_id:
                return None
            return next(
                (
                    attempt
                    for attempt in reversed(refresh_receipts)
                    if attempt.get("query_set_id") == query_set_id
                    and refresh_attempt_is_successful_after_quote(
                        attempt, latest_quote_received_at
                    )
                ),
                None,
            )

        def wait_for_post_receipt_query_refresh(callback_name):
            """Wait outside the Strategy/query lock for one real refresh after quote receipt."""
            if not _causal_quote_barrier or callback_name not in {"next", "notify_idle"}:
                return None
            try:
                close_time = strategy.data0.datetime.datetime(0)
                if close_time.tzinfo is None:
                    close_time = close_time.replace(tzinfo=UTC)
                else:
                    close_time = close_time.astimezone(UTC)
            except (AttributeError, IndexError, TypeError, ValueError):
                return {"status": "UNOBSERVABLE", "reason": "CURRENT_BAR_CLOSE_UNAVAILABLE"}
            rows_by_target = causal_quote_rows_by_close.get(close_time)
            if not rows_by_target or len(rows_by_target) != len(plan["targets"]):
                return {
                    "status": "UNOBSERVABLE",
                    "reason": "CURRENT_BAR_QUOTE_SET_INCOMPLETE",
                    "close_time": close_time.isoformat(),
                    "expected_targets": len(plan["targets"]),
                    "observed_targets": len(rows_by_target or {}),
                }
            expected_rows = tuple(rows_by_target[target] for target in plan["targets"])
            receipt_rows = []
            for row in expected_rows:
                event = causal_quote_receipt_events[row["bar_id"]]
                if not event.is_set():
                    event.wait(timeout=0.25)
                receipt = causal_quote_receipt_by_bar_id.get(row["bar_id"])
                if not event.is_set() or not isinstance(receipt, dict):
                    return {
                        "status": "UNOBSERVABLE",
                        "reason": "CURRENT_BAR_QUOTE_RECEIPT_MISSING",
                        "close_time": close_time.isoformat(),
                    }
                receipt_rows.append(receipt)
            try:
                latest_receipt_at = max(
                    datetime.fromisoformat(item["received_at"]) for item in receipt_rows
                )
            except (KeyError, TypeError, ValueError):
                return {
                    "status": "UNOBSERVABLE",
                    "reason": "CURRENT_BAR_QUOTE_RECEIPT_TIME_MISSING",
                    "close_time": close_time.isoformat(),
                }

            def successful_refresh_started_after_receipt():
                for attempt in reversed(refresh_receipts):
                    if refresh_attempt_is_successful_after_quote(attempt, latest_receipt_at):
                        return attempt
                return None

            refresh_loop = getattr(strategy.p, "control_refresh_loop", None)
            wait_started_at = clock.utc_now()
            wait_started_monotonic = time.monotonic()
            with refresh_condition:
                refresh_started_before = refresh_state["started"]
                refresh_completed_before = refresh_state["completed"]
                selected_refresh = successful_refresh_started_after_receipt()
                if selected_refresh is None:
                    # Wait for the exact causal predicate, not an arbitrary
                    # refresh completion (which could have started before the
                    # quote receipt). Condition.wait_for releases this lock.
                    completed = refresh_condition.wait_for(
                        lambda: successful_refresh_started_after_receipt() is not None,
                        timeout=4.0,
                    )
                    selected_refresh = successful_refresh_started_after_receipt()
                else:
                    completed = True
                refresh_started_after = refresh_state["started"]
                refresh_completed_after = refresh_state["completed"]
            wait_completed_at = clock.utc_now()
            wait_duration_seconds = time.monotonic() - wait_started_monotonic
            attempt_samples, attempt_sample_count, attempt_samples_truncated = (
                post_quote_refresh_attempts(latest_receipt_at)
            )
            selected_attempt_projection = (
                project_refresh_attempt(selected_refresh, latest_receipt_at)
                if selected_refresh is not None
                else None
            )
            observed_return_categories = (
                ("NO_REFRESH_ATTEMPT_OBSERVED",)
                if not attempt_samples
                else tuple(
                    sorted(
                        {
                            "REFRESH_RAISED"
                            if item.get("attempt_status") == "RAISED"
                            else "ATTEMPT_IN_PROGRESS_AT_OBSERVATION"
                            if item.get("attempt_status") == "IN_PROGRESS"
                            else "ERROR_CODE_PRESENT"
                            if item.get("error_code") is not None
                            else "STARTED_BEFORE_OR_AT_QUOTE"
                            if item.get("started_after_quote_receipt") is not True
                            else "BLOCKERS_PRESENT"
                            if item.get("blockers")
                            else "PENDING_FAMILIES"
                            if item.get("pending_families")
                            else "CANCELLED"
                            if item.get("cancelled") is True
                            else "DEADLINE_REACHED"
                            if item.get("deadline_reached") is True
                            else "QUERY_SET_ID_MISSING"
                            if not item.get("query_set_id_present")
                            else "FACTS_NOT_PUBLISHED"
                            if item.get("last_facts_present") is not True
                            or item.get("last_facts_query_set_id")
                            != item.get("query_set_id")
                            else "COMPLETE_QUERY_SET"
                            for item in attempt_samples
                        }
                    )
                )
            )
            result = {
                "status": "PASS" if completed and selected_refresh is not None else "INCOMPLETE",
                "reason": None if selected_refresh is not None else "POST_RECEIPT_REFRESH_UNAVAILABLE",
                "close_time": close_time.isoformat(),
                "latest_quote_received_at": latest_receipt_at.isoformat(),
                "wait_started_at": wait_started_at.isoformat(),
                "wait_completed_at": wait_completed_at.isoformat(),
                "wait_duration_seconds": round(wait_duration_seconds, 6),
                "wait_timeout_seconds": 4.0,
                "wait_timed_out": bool(not completed),
                "refresh_started_before": refresh_started_before,
                "refresh_completed_before": refresh_completed_before,
                "refresh_started_after": refresh_started_after,
                "refresh_completed_after": refresh_completed_after,
                "observed_post_quote_attempt_count": attempt_sample_count,
                "post_quote_attempt_samples_truncated": attempt_samples_truncated,
                "post_quote_attempt_samples": attempt_samples,
                "observed_return_categories": observed_return_categories,
                "loop_state_after_wait": refresh_loop_projection(refresh_loop),
                "refresh_attempt": (
                    selected_refresh.get("attempt") if selected_refresh is not None else None
                ),
                "refresh_started_at": (
                    selected_refresh.get("started_at") if selected_refresh is not None else None
                ),
                "refresh_completed_at": (
                    selected_refresh.get("completed_at") if selected_refresh is not None else None
                ),
                "refresh_query_set_id_present": bool(
                    selected_refresh.get("query_set_id") if selected_refresh is not None else False
                ),
                "refresh_query_set_id": (
                    selected_refresh.get("query_set_id") if selected_refresh is not None else None
                ),
                "selected_refresh_attempt": selected_attempt_projection,
            }
            causal_quote_refresh_by_close[close_time] = result
            return result

        def trace_strategy_turn(callback_name, callback, *args, **kwargs):
            # The synthetic event barrier is outside fact_turn_lock so the real
            # QueryRefreshLoop thread can publish a post-receipt snapshot. The
            # Strategy callback then uses its ordinary production projection.
            post_receipt_refresh = wait_for_post_receipt_query_refresh(callback_name)
            with fact_turn_lock:
                # This timestamp is the strategy turn's first source-clock
                # observation, after it owns the same lock as query refresh.
                callback_requested_at = clock.utc_now()
                refresh_loop = strategy.p.control_refresh_loop
                receipt_before = getattr(refresh_loop, "last_receipt", None)
                before_query_set = getattr(
                    getattr(receipt_before, "query_set", None), "query_set_id", None
                )
                before_refresh = (refresh_state["started"], refresh_state["completed"])
                if (
                    isinstance(post_receipt_refresh, dict)
                    and post_receipt_refresh.get("latest_quote_received_at")
                ):
                    try:
                        latest_quote_received_at = datetime.fromisoformat(
                            post_receipt_refresh["latest_quote_received_at"]
                        )
                    except (TypeError, ValueError):
                        latest_quote_received_at = None
                    callback_loop_state = refresh_loop_projection(refresh_loop)
                    callback_query_set_id = callback_loop_state.get(
                        "receipt_query_set_id"
                    )
                    callback_attempt = (
                        None
                        if latest_quote_received_at is None
                        else successful_refresh_for_query_set(
                            callback_query_set_id, latest_quote_received_at
                        )
                    )
                    attempt_samples, attempt_sample_count, attempt_samples_truncated = (
                        post_quote_refresh_attempts(latest_quote_received_at)
                        if latest_quote_received_at is not None
                        else ((), 0, False)
                    )
                    post_receipt_refresh.update(
                        {
                            "callback_entry_at": callback_requested_at.isoformat(),
                            "callback_entry_loop_state": callback_loop_state,
                            "callback_entry_query_set_id": callback_query_set_id,
                            "callback_entry_query_set_id_matches_post_quote_refresh": (
                                callback_attempt is not None
                            ),
                            "callback_entry_refresh_attempt": (
                                callback_attempt.get("attempt")
                                if callback_attempt is not None
                                else None
                            ),
                            "post_quote_attempt_samples": attempt_samples,
                            "observed_post_quote_attempt_count": attempt_sample_count,
                            "post_quote_attempt_samples_truncated": attempt_samples_truncated,
                        }
                    )
                    if callback_attempt is not None:
                        post_receipt_refresh.update(
                            {
                                "refresh_attempt": callback_attempt.get("attempt"),
                                "refresh_started_at": callback_attempt.get("started_at"),
                                "refresh_completed_at": callback_attempt.get("completed_at"),
                                "refresh_query_set_id_present": True,
                                "refresh_query_set_id": callback_query_set_id,
                            }
                        )
                    if post_receipt_refresh.get("wait_timed_out") is True:
                        post_receipt_refresh["status"] = "INCOMPLETE"
                        post_receipt_refresh["reason"] = "POST_RECEIPT_REFRESH_WAIT_TIMED_OUT"
                    elif callback_attempt is None:
                        post_receipt_refresh["status"] = "INCOMPLETE"
                        post_receipt_refresh["reason"] = (
                            "CALLBACK_ENTRY_QUERY_SET_NOT_PROVEN_POST_QUOTE"
                        )
                    else:
                        post_receipt_refresh["status"] = "PASS"
                        post_receipt_refresh["reason"] = None
                try:
                    result = callback(*args, **kwargs)
                except Exception as exc:
                    if len(strategy_decision_trace) < 256:
                        strategy_decision_trace.append(
                            {
                                "kind": "strategy_callback_error",
                                "callback": callback_name,
                                "requested_at": callback_requested_at.isoformat(),
                                "query_set_before": before_query_set,
                                "refresh_started_completed_before": before_refresh,
                            "post_receipt_refresh": post_receipt_refresh,
                                "error": (type(exc).__name__, str(exc)[:512]),
                            }
                        )
                    raise
                api = api_instances[-1] if api_instances else None
                if api is not None and api._phase == 1 and len(strategy_decision_trace) < 256:
                    facts = strategy.last_execution_facts
                    plan_now = strategy.last_order_plan
                    receipt_after = getattr(refresh_loop, "last_receipt", None)
                    strategy_decision_trace.append(
                        {
                            "kind": "strategy_callback",
                            "callback": callback_name,
                            "requested_at": callback_requested_at.isoformat(),
                            "entered_at": clock.utc_now().isoformat(),
                            "refresh_started_completed_before": before_refresh,
                            "refresh_started_completed_after": (
                                refresh_state["started"],
                                refresh_state["completed"],
                            ),
                            "post_receipt_refresh": post_receipt_refresh,
                            "query_set_before": before_query_set,
                            "query_set_after": getattr(
                                getattr(receipt_after, "query_set", None),
                                "query_set_id",
                                None,
                            ),
                            "last_error_code": getattr(refresh_loop, "last_error_code", None),
                            "batch_id": strategy._last_batch_id,
                            "execution_block_reason": strategy.last_execution_block_reason,
                            "facts": (
                                None
                                if facts is None
                                else {
                                    "snapshot_id": getattr(facts, "snapshot_id", None),
                                    "query_set_id": getattr(facts, "query_set_id", None),
                                    "available_at": getattr(facts, "available_at", None),
                                    "blockers": getattr(facts, "blockers", None),
                                    "risk_reduction_blockers": getattr(
                                        facts, "risk_reduction_blockers", None
                                    ),
                                    "order_cancel_blockers": getattr(
                                        facts, "order_cancel_blockers", None
                                    ),
                                    "quotes": tuple(
                                        (
                                            getattr(quote, "instrument", None),
                                            getattr(quote, "source", None),
                                            getattr(quote, "sequence", None),
                                            getattr(quote, "event_time", None),
                                            getattr(quote, "available_at", None),
                                            getattr(quote, "quality", None),
                                        )
                                        for quote in getattr(facts, "quotes", ())
                                    ),
                                }
                            ),
                            "plan": (
                                None
                                if plan_now is None
                                else {
                                    "status": getattr(plan_now, "status", None),
                                    "reason": getattr(plan_now, "reason", None),
                                    "actions": tuple(
                                        (
                                            getattr(action, "action", None),
                                            getattr(action, "instrument", None),
                                            getattr(action, "position_effect", None),
                                            getattr(action, "quantity", None),
                                            getattr(action, "offset", None),
                                            getattr(action, "reason", None),
                                        )
                                        for action in getattr(plan_now, "actions", ())
                                    ),
                                }
                            ),
                        }
                    )
                return result

        def traced_next(*args, **kwargs):
            return trace_strategy_turn("next", original_next, *args, **kwargs)

        def traced_notify_idle(*args, **kwargs):
            return trace_strategy_turn("notify_idle", original_notify_idle, *args, **kwargs)

        strategy.next = traced_next
        strategy.notify_idle = traced_notify_idle

        def traced_run_live(batch, snapshot, now, ordinal, session_close, run_end, **kwargs):
            barrier_record = None
            if _causal_quote_barrier and batch is not None:
                close_time = getattr(batch, "close_time", None)
                rows_by_target = causal_quote_rows_by_close.get(close_time, {})
                expected_rows = tuple(
                    rows_by_target[target]
                    for target in plan["targets"]
                    if target in rows_by_target
                )
                expected_delivery = max(
                    (
                        synthetic_ctp_tick_time(row["bucket_end"])
                        for row in expected_rows
                    ),
                    default=None,
                )
                before_barrier = clock.utc_now()
                if expected_delivery is not None and before_barrier < expected_delivery:
                    clock.advance(expected_delivery - before_barrier)
                receipt_results = tuple(
                    (
                        row["target"],
                        row["bar_id"],
                        causal_quote_receipt_events[row["bar_id"]].wait(timeout=0.25),
                    )
                    for row in expected_rows
                )
                barrier_at = clock.utc_now()
                now = max(now, barrier_at)
                barrier_record = {
                    "batch_id": getattr(batch, "batch_id", None),
                    "slot_index": getattr(batch, "slot_index", None),
                    "close_time": close_time.isoformat()
                    if hasattr(close_time, "isoformat")
                    else None,
                    "expected_target_count": len(plan["targets"]),
                    "expected_receipt_count": len(expected_rows),
                    "receipt_events": tuple(
                        {
                            "target_id": target,
                            "bar_id": bar_id,
                            "released": released,
                            "receipt": causal_quote_receipt_by_bar_id.get(bar_id),
                        }
                        for target, bar_id, released in receipt_results
                    ),
                    "barrier_released_at": barrier_at.isoformat(),
                    "risk_snapshot_evaluated_at": now.isoformat(),
                    "post_dispatch_clock_advance": post_dispatch_clock_advances_by_close.get(
                        close_time
                    ),
                    "receipt_precedes_risk_snapshot": bool(
                        len(expected_rows) == len(plan["targets"])
                        and all(released for _target, _bar_id, released in receipt_results)
                        and all(
                            causal_quote_receipt_by_bar_id.get(row["bar_id"], {}).get(
                                "received_at"
                            )
                            is not None
                            and datetime.fromisoformat(
                                causal_quote_receipt_by_bar_id[row["bar_id"]]["received_at"]
                            )
                            <= now
                            for row in expected_rows
                        )
                    ),
                }
                with causal_quote_receipt_lock:
                    if len(causal_quote_barrier_trace) < 128:
                        causal_quote_barrier_trace.append(barrier_record)
                if not barrier_record["receipt_precedes_risk_snapshot"]:
                    raise AssertionError("causal quote receipt barrier did not release")
            result = original_run_live(
                batch, snapshot, now, ordinal, session_close, run_end, **kwargs
            )
            if (
                _fee_pair_stale_snapshot_after_append
                and getattr(batch, "batch_id", None) in fee_pair_stale_batch_ids
            ):
                current_plan = strategy.last_order_plan
                current_actions = tuple(getattr(current_plan, "actions", ()) or ())
                grid_input = next(
                    (
                        item
                        for item in fee_pair_stale_grid_inputs
                        if item["batch_id"] == getattr(batch, "batch_id", None)
                    ),
                    None,
                )
                input_actions = () if grid_input is None else grid_input["actions"]
                input_reductions = tuple(
                    action
                    for action in input_actions
                    if getattr(action, "action", None) == "CANCEL"
                    or (
                        getattr(action, "action", None) == "SUBMIT"
                        and getattr(action, "position_effect", None) == "CLOSE"
                    )
                )
                fee_pair_stale_grid_results.append(
                    {
                        "batch_id": getattr(batch, "batch_id", None),
                        "block_reason": strategy.last_execution_block_reason,
                        "input_open_action_count": sum(
                            getattr(action, "action", None) == "SUBMIT"
                            and getattr(action, "position_effect", None) == "OPEN"
                            for action in input_actions
                        ),
                        "input_reduction_action_count": len(input_reductions),
                        "has_open_action": any(
                            getattr(action, "action", None) == "SUBMIT"
                            and getattr(action, "position_effect", None) == "OPEN"
                            for action in current_actions
                        ),
                        "input_reductions_retained": all(
                            any(retained is action for retained in current_actions)
                            for action in input_reductions
                        ),
                        "actions": tuple(
                            (
                                getattr(action, "action", None),
                                getattr(action, "position_effect", None),
                            )
                            for action in current_actions
                        ),
                    }
                )
            if barrier_record is not None:
                facts = strategy.last_execution_facts
                facts_quotes = tuple(getattr(facts, "quotes", ()) or ())
                quotes_by_instrument = {
                    getattr(quote, "instrument", None): quote for quote in facts_quotes
                }
                facts_available_at = getattr(facts, "available_at", None)
                facts_snapshot_id = getattr(facts, "snapshot_id", None)
                store = getattr(getattr(strategy, "broker", None), "store", None)
                get_latest_tick = getattr(store, "get_latest_tick_snapshot", None)
                fact_matches = []
                for receipt_row in causal_quote_rows_by_close.get(
                    getattr(batch, "close_time", None), {}
                ).values():
                    expected_receipt = causal_quote_receipt_by_bar_id.get(
                        receipt_row["bar_id"], {}
                    )
                    quote = quotes_by_instrument.get(receipt_row["instrument"])
                    quote_event_time = getattr(quote, "event_time", None)
                    quote_available_at = getattr(quote, "available_at", None)
                    raw_tick = (
                        get_latest_tick(receipt_row["instrument"])
                        if callable(get_latest_tick)
                        else None
                    )
                    try:
                        received_at = datetime.fromisoformat(expected_receipt["received_at"])
                        callback_received_at = datetime.fromisoformat(
                            expected_receipt["ctp_callback_received_wall_time"]
                        )
                        event_time = datetime.fromisoformat(expected_receipt["event_time"])
                    except (KeyError, TypeError, ValueError):
                        received_at = callback_received_at = event_time = None
                    observed_tick_event = store_tick_fields_by_bar_id.get(
                        receipt_row["bar_id"]
                    )
                    observed_tick_fields = (
                        {
                            "event_id": getattr(observed_tick_event, "event_id", None),
                            "ctp_callback_received_wall_time": getattr(
                                observed_tick_event,
                                "ctp_callback_received_wall_time",
                                None,
                            ),
                            "received_wall_time": getattr(
                                observed_tick_event, "received_wall_time", None
                            ),
                        }
                        if observed_tick_event is not None
                        else {}
                    )
                    raw_callback_wall_time = getattr(
                        raw_tick, "ctp_callback_received_wall_time", None
                    )
                    raw_received_wall_time = getattr(raw_tick, "received_wall_time", None)
                    raw_callback_received_at = (
                        datetime.fromtimestamp(raw_callback_wall_time, UTC)
                        if type(raw_callback_wall_time) in (float, int)
                        else None
                    )
                    raw_received_at = (
                        datetime.fromtimestamp(raw_received_wall_time, UTC)
                        if type(raw_received_wall_time) in (float, int)
                        else None
                    )
                    actual_tick_fields_match = bool(
                        raw_tick is not None
                        and getattr(raw_tick, "event_id", None)
                        == observed_tick_fields.get("event_id")
                        and raw_callback_wall_time
                        == observed_tick_fields.get("ctp_callback_received_wall_time")
                        and raw_received_wall_time
                        == observed_tick_fields.get("received_wall_time")
                    )
                    receipt_uses_actual_tick_received_time = bool(
                        raw_received_at is not None and received_at == raw_received_at
                    )
                    callback_receipt_preserves_callback_time = bool(
                        raw_callback_received_at is not None
                        and callback_received_at == raw_callback_received_at
                    )
                    quote_uses_actual_tick_received_time = bool(
                        raw_received_at is not None
                        and isinstance(quote_available_at, datetime)
                        and abs((quote_available_at - raw_received_at).total_seconds())
                        <= 0.000001
                    )
                    target_suffix = ":" + receipt_row["target"]
                    blocker_codes = tuple(
                        sorted(
                            blocker[: -len(target_suffix)]
                            for blocker in (getattr(facts, "blockers", ()) or ())
                            if isinstance(blocker, str) and blocker.endswith(target_suffix)
                        )
                    )
                    fact_event_after_snapshot = bool(
                        isinstance(facts_available_at, datetime)
                        and isinstance(quote_event_time, datetime)
                        and quote_event_time >= facts_available_at
                    )
                    fact_receive_after_snapshot = bool(
                        isinstance(facts_available_at, datetime)
                        and isinstance(quote_available_at, datetime)
                        and quote_available_at >= facts_available_at
                    )
                    fact_matches.append(
                        {
                            "target_id": receipt_row["target"],
                            "instrument": receipt_row["instrument"],
                            "receipt_event_time": expected_receipt.get("event_time"),
                            "receipt_callback_received_wall_time": expected_receipt.get(
                                "ctp_callback_received_wall_time"
                            ),
                            "receipt_available_at": expected_receipt.get("received_at"),
                            "actual_tick_callback_received_wall_time": raw_callback_received_at.isoformat()
                            if raw_callback_received_at is not None
                            else None,
                            "actual_tick_received_wall_time": raw_received_at.isoformat()
                            if raw_received_at is not None
                            else None,
                            "actual_tick_fields_match_observed_event": actual_tick_fields_match,
                            "receipt_uses_actual_tick_received_time": receipt_uses_actual_tick_received_time,
                            "callback_receipt_preserves_callback_time": callback_receipt_preserves_callback_time,
                            "quote_uses_actual_tick_received_time": quote_uses_actual_tick_received_time,
                            "risk_quote_event_time": quote_event_time.isoformat()
                            if hasattr(quote_event_time, "isoformat")
                            else None,
                            "risk_quote_available_at": quote_available_at.isoformat()
                            if hasattr(quote_available_at, "isoformat")
                            else None,
                            "risk_facts_available_at": facts_available_at.isoformat()
                            if hasattr(facts_available_at, "isoformat")
                            else None,
                            "risk_facts_snapshot_id_present": bool(facts_snapshot_id),
                            "quote_metadata_snapshot_matches_facts": bool(
                                quote is not None
                                and getattr(quote, "metadata_snapshot_id", None)
                                == facts_snapshot_id
                            ),
                            "quote_event_at_or_after_risk_facts": fact_event_after_snapshot,
                            "quote_receive_at_or_after_risk_facts": fact_receive_after_snapshot,
                            "quote_quality": getattr(quote, "quality", None),
                            "quote_generation": getattr(quote, "generation", None),
                            "quote_sequence": getattr(quote, "sequence", None),
                            "quote_blocker_codes": blocker_codes[:16],
                            "consumed_tick_envelope": {
                                "snapshot_or_delta": getattr(raw_tick, "snapshot_or_delta", None),
                                "coalesced_count": getattr(raw_tick, "coalesced_count", None),
                                "continuity_status": getattr(raw_tick, "continuity_status", None),
                                "stale": getattr(raw_tick, "stale", None),
                                "connection_generation": getattr(
                                    raw_tick, "connection_generation", None
                                ),
                                "stream_generation": getattr(
                                    raw_tick, "stream_generation", None
                                ),
                                "sequence": getattr(raw_tick, "sequence", None),
                                "previous_sequence": getattr(raw_tick, "previous_sequence", None),
                                "source_present": bool(getattr(raw_tick, "source", None)),
                                "event_id_present": bool(getattr(raw_tick, "event_id", None)),
                                "volume_semantics": getattr(raw_tick, "volume_semantics", None),
                                "volume_complete": getattr(raw_tick, "volume_complete", None),
                                "delta_volume_present": getattr(
                                    raw_tick, "delta_volume", None
                                )
                                is not None,
                                "delta_volume_is_zero": getattr(
                                    raw_tick, "delta_volume", None
                                )
                                == 0,
                            },
                            "matches_receipt": bool(
                                quote is not None
                                and event_time is not None
                                and received_at is not None
                                and quote_event_time == event_time
                                and isinstance(quote_available_at, datetime)
                                and abs((quote_available_at - received_at).total_seconds())
                                <= 0.000001
                                and actual_tick_fields_match
                                and receipt_uses_actual_tick_received_time
                                and callback_receipt_preserves_callback_time
                                and quote_uses_actual_tick_received_time
                            ),
                        }
                    )
                barrier_record["risk_snapshot_quote_facts"] = tuple(fact_matches)
                barrier_record["all_risk_quotes_match_receipts"] = bool(
                    len(fact_matches) == len(plan["targets"])
                    and all(item["matches_receipt"] for item in fact_matches)
                )
                post_receipt_refresh = causal_quote_refresh_by_close.get(
                    getattr(batch, "close_time", None)
                )
                barrier_record["post_receipt_refresh"] = post_receipt_refresh
                barrier_record["all_quote_receipts_precede_risk_facts_snapshot"] = bool(
                    post_receipt_refresh is not None
                    and post_receipt_refresh.get("status") == "PASS"
                    and isinstance(facts_available_at, datetime)
                    and all(
                        isinstance(
                            datetime.fromisoformat(item["received_at"]), datetime
                        )
                        and datetime.fromisoformat(item["received_at"]) < facts_available_at
                        for item in (
                            causal_quote_receipt_by_bar_id.get(row["bar_id"], {})
                            for row in causal_quote_rows_by_close.get(
                                getattr(batch, "close_time", None), {}
                            ).values()
                        )
                    )
                )
                barrier_record["risk_facts_query_set_matches_post_receipt_refresh"] = bool(
                    post_receipt_refresh is not None
                    and post_receipt_refresh.get("status") == "PASS"
                    and facts is not None
                    and getattr(facts, "query_set_id", None)
                    == post_receipt_refresh.get("refresh_query_set_id")
                )
                barrier_record["order_plan_reason"] = getattr(
                    getattr(strategy, "last_order_plan", None), "reason", None
                )
                barrier_record["execution_block_reason"] = getattr(
                    strategy, "last_execution_block_reason", None
                )
                with causal_quote_receipt_lock:
                    if causal_quote_barrier_trace:
                        causal_quote_barrier_trace[-1] = barrier_record
            api = api_instances[-1] if api_instances else None
            if api is not None and api._phase == 1 and strategy.shutdown_requested:
                facts = strategy.last_execution_facts
                plan_now = strategy.last_order_plan
                observation = {
                    "sequence": len(chain_trace),
                    "kind": "strategy_run_live",
                    "now": now.isoformat() if hasattr(now, "isoformat") else now,
                    "batch_id": getattr(batch, "batch_id", None),
                    "run_end": run_end,
                    "snapshot_id": getattr(facts, "snapshot_id", None),
                    "query_set_id": getattr(facts, "query_set_id", None),
                    "facts_available_at": getattr(facts, "available_at", None),
                    "risk_reduction_ready": getattr(facts, "risk_reduction_ready", None),
                    "risk_reduction_blockers": getattr(facts, "risk_reduction_blockers", None),
                    "positions": tuple(
                        (
                            getattr(position, "instrument", None),
                            getattr(position, "quantity", None),
                            getattr(position, "position_book_status", None),
                            getattr(position, "position_book_blocker_code", None),
                            getattr(position, "owner_strategy_scope", None),
                            getattr(position, "owner_intent_id", None),
                            getattr(position, "stop_price", None),
                        )
                        for position in getattr(facts, "positions", ())
                    ),
                    "quotes": tuple(
                        (
                            getattr(quote, "instrument", None),
                            getattr(quote, "event_time", None),
                            getattr(quote, "available_at", None),
                            getattr(quote, "quality", None),
                        )
                        for quote in getattr(facts, "quotes", ())
                    ),
                    "plan": (
                        getattr(plan_now, "status", None),
                        getattr(plan_now, "reason", None),
                        tuple(
                            (
                                getattr(action, "action", None),
                                getattr(action, "instrument", None),
                                getattr(action, "position_effect", None),
                                getattr(action, "quantity", None),
                                getattr(action, "offset", None),
                                getattr(action, "reason", None),
                            )
                            for action in getattr(plan_now, "actions", ())
                        ),
                    ),
                    "shutdown": (
                        strategy.shutdown_ready,
                        strategy.shutdown_blocker,
                    ),
                    "latest_winddown_ticks": tuple(api.winddown_tick_observations[-3:]),
                }
                idle_decision_trace.append(observation)
                chain_trace.append(observation)
                if len(idle_decision_trace) > 128:
                    del idle_decision_trace[:-128]
                if len(chain_trace) > 128:
                    del chain_trace[:-128]
            return result

        strategy._run_live = traced_run_live

        if _fee_pair_missing_pair_then_block or _fee_pair_stale_snapshot_after_append:
            original_fee_pair_record = strategy._record_fee_pair_source_only_tape
            missing_pair_forced = False
            stale_snapshot_forced = False

            def observe_fee_pair_source_attempt(batch, snapshot, target_decision, facts):
                nonlocal missing_pair_forced, stale_snapshot_forced
                readiness_value = getattr(snapshot, "readiness", None)
                readiness = getattr(readiness_value, "name", readiness_value)
                readiness = str(readiness) if readiness is not None else "UNAVAILABLE"
                forced_missing_pair = bool(
                    _fee_pair_missing_pair_then_block
                    and readiness == "LIVE_READY"
                    and not missing_pair_forced
                )
                if forced_missing_pair:
                    # Exercise the real writer's production missing-pair check:
                    # its source projection is absent for this LIVE_READY slot.
                    target_decision = None
                    missing_pair_forced = True
                recorded = original_fee_pair_record(
                    batch, snapshot, target_decision, facts
                )
                fee_pair_source_attempts.append(
                    {
                        "batch_id": getattr(batch, "batch_id", None),
                        "slot_index": getattr(batch, "slot_index", None),
                        "readiness": str(readiness),
                        "forced_missing_pair": forced_missing_pair,
                        "durable": recorded[0],
                        "reason": recorded[2],
                    }
                )
                if (
                    _fee_pair_stale_snapshot_after_append
                    and recorded[0]
                    and not stale_snapshot_forced
                ):
                    original_snapshot = strategy.live_factors.snapshot
                    pending = [True]
                    batch_id = getattr(batch, "batch_id", None)
                    fee_pair_stale_batch_ids.add(batch_id)
                    stale_snapshot_forced = True

                    def return_stale_snapshot_once():
                        if pending[0]:
                            pending[0] = False
                            fee_pair_stale_snapshot_events.append(batch_id)
                            return None
                        return original_snapshot()

                    monkeypatch.setattr(
                        strategy.live_factors, "snapshot", return_stale_snapshot_once
                    )
                return recorded

            strategy._record_fee_pair_source_only_tape = observe_fee_pair_source_attempt

        if _fee_pair_stale_snapshot_after_append:
            original_record_source_only = strategy._record_source_only
            original_live_risk_decision = strategy._live_risk_decision
            original_live_grid_decision = strategy._live_grid_decision

            def observe_record_source_only(batch, snapshot, tape_reference):
                readiness_value = getattr(snapshot, "readiness", None)
                readiness = getattr(readiness_value, "name", readiness_value)
                if str(readiness) == "LIVE_READY":
                    fee_pair_live_ordinary_fallbacks.append(
                        getattr(batch, "batch_id", None)
                    )
                return original_record_source_only(batch, snapshot, tape_reference)

            def observe_live_risk_decision(batch, *args, **kwargs):
                if getattr(batch, "batch_id", None) in fee_pair_stale_batch_ids:
                    fee_pair_risk_path_batches.append(getattr(batch, "batch_id", None))
                return original_live_risk_decision(batch, *args, **kwargs)

            def observe_live_grid_decision(*args, **kwargs):
                result = original_live_grid_decision(*args, **kwargs)
                batch = args[0] if args else kwargs.get("batch")
                plan = args[3] if len(args) > 3 else kwargs.get("plan")
                batch_id = getattr(batch, "batch_id", None)
                if batch_id in fee_pair_stale_batch_ids:
                    fee_pair_stale_grid_inputs.append(
                        {
                            "batch_id": batch_id,
                            "actions": tuple(getattr(plan, "actions", ()) or ()),
                        }
                    )
                return result

            strategy._record_source_only = observe_record_source_only
            strategy._live_risk_decision = observe_live_risk_decision
            strategy._live_grid_decision = observe_live_grid_decision

        original_dispatch_live_actions = strategy._dispatch_live_actions

        def traced_dispatch_live_actions(actions, batch):
            result = original_dispatch_live_actions(actions, batch)
            api = api_instances[-1] if api_instances else None
            if api is not None and api._phase == 1:
                risk_dispatch_trace.append(
                    {
                        "kind": "dispatch_live_actions_returned",
                        "actions": tuple(
                            (
                                getattr(action, "action", None),
                                getattr(action, "instrument", None),
                                getattr(action, "side", None),
                                getattr(action, "position_effect", None),
                                getattr(action, "quantity", None),
                                getattr(action, "offset", None),
                            )
                            for action in actions
                        ),
                        "orders": tuple(
                            (
                                ref,
                                getattr(order, "status", None),
                                getattr(getattr(order, "data", None), "_name", None),
                                getattr(order, "size", None),
                                getattr(getattr(order, "info", None), "factor_intent_id", None),
                            )
                            for ref, order in getattr(strategy, "_orders_by_broker_ref", {}).items()
                        )[-8:],
                        "store_writes": len(store_write_calls),
                        "native_calls": len(api.native_calls),
                    }
                )
                if len(risk_dispatch_trace) > 32:
                    del risk_dispatch_trace[:-32]
            return result

        strategy._dispatch_live_actions = traced_dispatch_live_actions

        store = getattr(getattr(strategy, "broker", None), "store", None)
        original_poll_tick = getattr(store, "poll_tick", None)
        if callable(original_poll_tick):

            def traced_store_poll_tick(dataname):
                tick = original_poll_tick(dataname)
                api = api_instances[-1] if api_instances else None
                if tick is not None and api is not None and api._phase == 1:
                    observation = {
                        "sequence": len(chain_trace),
                        "kind": "store_poll_tick_returned",
                        "instrument": dataname,
                        "event_id": getattr(tick, "event_id", None),
                        "event_time": getattr(tick, "event_time", None),
                        "received_wall_time": getattr(tick, "received_wall_time", None),
                        "source": getattr(tick, "source", None),
                        "query_set_id": api._winddown_query_set_for.get(dataname),
                        "source_clock": clock.utc_now().isoformat(),
                    }
                    store_tick_trace.append(observation)
                    chain_trace.append(observation)
                    query_set_id = api._winddown_query_set_for.get(dataname)
                    if query_set_id is not None:
                        api.winddown_tick_observations.append(
                            {
                                "instrument": dataname,
                                "query_set_id": query_set_id,
                                "event_id": getattr(tick, "event_id", None),
                                "event_time": getattr(tick, "event_time", None),
                                "received_wall_time": getattr(tick, "received_wall_time", None),
                                "source": getattr(tick, "source", None),
                            }
                        )
                        api._winddown_query_set_for.pop(dataname, None)
                        api._winddown_scheduled_instruments.discard(dataname)
                    if len(store_tick_trace) > 128:
                        del store_tick_trace[:-128]
                    if len(chain_trace) > 128:
                        del chain_trace[:-128]
                return tick

            store.poll_tick = traced_store_poll_tick

    monkeypatch.setattr(RUNNER.QueryRefreshLoop, "bind_strategy", capture_bound_strategy)

    original_refresh = RUNNER.QueryRefreshLoop.refresh_once

    def counted_refresh(loop):
        # The test fake provider advances its event clock during each typed
        # query. Keep the entire refresh transaction, including publication
        # and its bounded trace record, indivisible from Strategy clock reads.
        with fact_turn_lock:
            with refresh_condition:
                refresh_state["started"] += 1
                started = refresh_state["started"]
                refresh_condition.notify_all()
            refresh_started_at = clock.utc_now()
            attempt_event = {
                "attempt": started,
                "attempt_status": "IN_PROGRESS",
                "return_category": None,
                "started_at": refresh_started_at.isoformat(),
                "completed_at": None,
                "error_code": None,
                "query_set_id": None,
                "blockers": (),
                "pending_families": (),
                "cancelled": None,
                "deadline_reached": None,
                "last_facts_present": False,
                "last_facts_query_set_id": None,
                "provenance": (),
            }
            with refresh_condition:
                refresh_attempt_events.append(attempt_event)
            try:
                receipt = original_refresh(loop)
                loop_facts = getattr(loop, "last_facts", None)
                loop_facts_available_at = getattr(loop_facts, "available_at", None)
                loop_facts_blockers = tuple(
                    getattr(loop_facts, "blockers", ()) or ()
                )[:8]
                refresh_receipts.append(
                    {
                        "attempt": started,
                        "started_at": refresh_started_at.isoformat(),
                        "completed_at": clock.utc_now().isoformat(),
                        "error_code": getattr(loop, "last_error_code", None),
                        "query_set_id": getattr(
                            getattr(receipt, "query_set", None), "query_set_id", None
                        ),
                        "requested_families": getattr(receipt, "requested_families", None),
                        "attempted_families": getattr(receipt, "attempted_families", None),
                        "pending_families": getattr(receipt, "pending_families", None),
                        "cancelled": getattr(receipt, "cancelled", None),
                        "deadline_reached": getattr(receipt, "deadline_reached", None),
                        "blockers": getattr(receipt, "blockers", None),
                        "last_facts_present": loop_facts is not None,
                        "last_facts_query_set_id": getattr(
                            loop_facts, "query_set_id", None
                        ),
                        "last_facts_available_at": (
                            loop_facts_available_at.isoformat()
                            if hasattr(loop_facts_available_at, "isoformat")
                            else None
                        ),
                        "last_facts_snapshot_id_present": bool(
                            getattr(loop_facts, "snapshot_id", None)
                        ),
                        "last_facts_blockers": loop_facts_blockers,
                        "last_reconciliation_blockers": tuple(
                            getattr(loop, "last_reconciliation_blockers", ()) or ()
                        )[:8],
                        "provenance": tuple(
                            (
                                getattr(item, "family", None),
                                getattr(item, "target_id", None),
                                getattr(item, "query_complete", None),
                                getattr(item, "source_owned", None),
                                getattr(item, "scope_complete", None),
                                getattr(item, "request_id", None),
                                getattr(item, "completed_at", None),
                            )
                            for item in getattr(receipt, "query_provenance", ())
                        ),
                    }
                )
                with refresh_condition:
                    attempt_event.update(refresh_receipts[-1])
                    attempt_event["attempt_status"] = "RETURNED"
                    attempt_event["return_category"] = (
                        "BLOCKERS_PRESENT"
                        if getattr(receipt, "blockers", ())
                        else "PENDING_FAMILIES"
                        if getattr(receipt, "pending_families", ())
                        else "CANCELLED"
                        if getattr(receipt, "cancelled", None) is True
                        else "DEADLINE_REACHED"
                        if getattr(receipt, "deadline_reached", None) is True
                        else "QUERY_SET_MISSING"
                        if not getattr(
                            getattr(receipt, "query_set", None), "query_set_id", None
                        )
                        else "FACTS_NOT_PUBLISHED"
                        if loop_facts is None
                        or getattr(loop_facts, "query_set_id", None)
                        != getattr(getattr(receipt, "query_set", None), "query_set_id", None)
                        else "COMPLETE_QUERY_SET"
                    )
                query_set = getattr(receipt, "query_set", None)
                api = api_instances[-1] if api_instances else None
                if (
                    api is not None
                    and api._phase == 1
                    and query_set is not None
                    and not getattr(receipt, "blockers", ())
                    and not getattr(receipt, "pending_families", ())
                    and getattr(receipt, "cancelled", False) is False
                    and getattr(receipt, "deadline_reached", False) is False
                    and all(not rows for rows in bars_by_instrument.values())
                    and api.md_client is not None
                ):
                    query_completed_at = query_set.completed_at_utc
                    for instrument, _exchange in route_rows:
                        api.md_client.schedule_winddown_quote(
                            instrument,
                            query_set.query_set_id,
                            query_completed_at,
                        )
                return receipt
            except Exception as exc:
                reconciliation_blockers = tuple(
                    getattr(loop, "last_reconciliation_blockers", ())[:16]
                )
                with refresh_condition:
                    refresh_state["errors"].append(
                        (
                            clock.utc_now().isoformat(),
                            type(exc).__name__,
                            getattr(exc, "code", None),
                            str(exc)[:512],
                            reconciliation_blockers,
                        )
                    )
                with refresh_condition:
                    attempt_event.update(
                        {
                            "attempt_status": "RAISED",
                            "return_category": "REFRESH_RAISED",
                            "completed_at": clock.utc_now().isoformat(),
                            "error_code": getattr(exc, "code", None),
                            "exception_type": type(exc).__name__,
                            "last_error_code": getattr(loop, "last_error_code", None),
                            "last_reconciliation_blockers": reconciliation_blockers,
                            "last_facts_present": getattr(loop, "last_facts", None) is not None,
                            "last_facts_query_set_id": getattr(
                                getattr(loop, "last_facts", None), "query_set_id", None
                            ),
                        }
                    )
                note_fill_event(
                    "refresh_failed",
                    exception_type=type(exc).__name__,
                    code=getattr(exc, "code", None),
                    message=str(exc)[:512],
                    runner_reconciliation_blockers=reconciliation_blockers,
                )
                raise
            finally:
                with refresh_condition:
                    if attempt_event.get("attempt_status") == "IN_PROGRESS":
                        attempt_event.update(
                            {
                                "attempt_status": "FINALLY_WITHOUT_RETURN_FACTS",
                                "return_category": "UNCLASSIFIED_TERMINAL",
                                "completed_at": clock.utc_now().isoformat(),
                            }
                        )
                    refresh_state["completed"] = max(refresh_state["completed"], started)
                    refresh_condition.notify_all()

    monkeypatch.setattr(RUNNER.QueryRefreshLoop, "refresh_once", counted_refresh)
    # Journal timestamps are a test clock leaf, aligned with the typed query
    # source and the same virtual event clock. Production code remains intact.
    monkeypatch.setattr(
        journal_module,
        "time",
        SimpleNamespace(
            time_ns=clock.time_ns,
            monotonic=time.monotonic,
            monotonic_ns=time.monotonic_ns,
        ),
    )

    config["live"].update(
        account_scope="alpha003-factor-chain-account",
        strategy_scope="alpha003-factor-chain",
        logical_run_id="alpha003-factor-chain-run",
        journal_path=str(tmp_path / "factor-chain.sqlite"),
        ready_timeout_seconds=1.0,
        refresh_timeout_seconds=1.0,
        refresh_overall_timeout_seconds=5.0,
        refresh_interval_seconds=0.01,
        quote_max_age_seconds=60.0,
        query_max_age_seconds=7200.0,
        shutdown_grace_seconds=5.0,
        allow_writes=not _capacity_only,
        arm_templates=[
            {
                "target": target,
                "md_front": synthetic_store_config["md_address"],
                "strategy_identity_sha256": "a" * 64,
                "execution_cycle_id": "alpha003-factor-chain-" + target,
                "preflight_sha256": "b" * 64,
            }
            for target in plan["authorized_targets"]
        ],
    )
    config["risk"]["run_end_policy"] = "CLOSE_ALL"
    config["cohort"].update(
        max_pending_slots=1,
        max_live_bar_age_seconds=30.0,
        max_future_skew_seconds=0.0,
    )
    config["output"]["decision_tape_path"] = str(tmp_path / "factor-chain-tape.jsonl")
    config["output"]["decision_tape_max_bytes"] = 50_000_000
    config_path.write_text(
        runner_fixtures.yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )

    try:
        result = RUNNER.run_live(
            config,
            config_path,
            plan,
            _factor_mode,
            1,
            decision=SimpleNamespace(effective_tier="live"),
            allow_write_flag=not _capacity_only,
            _capture_live_capacity=_capture_capacity,
            _include_plan=_capacity_only,
        )
    except Exception as exc:
        persist_diagnostic("known_cancel_run_exception", error=exc)
        print(
            "DECISION_TAPE_FAILURE_PROBE="
            + json.dumps(decision_tape_failure_probe, sort_keys=True, separators=(",", ":"))
        )
        print(
            "DECISION_TAPE_SOURCE_RECEIPT_FIELD_PROBE="
            + json.dumps(
                source_receipt_field_probe,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        observations = tuple(item for api in api_instances for item in api.tick_observations[-9:])
        cleanup = getattr(exc, "cleanup_results", None)
        failure = getattr(exc, "live_epoch_evidence", None)
        resources = getattr(exc, "retained_live_resources", {})
        resource_names = tuple(resources) if hasattr(resources, "__iter__") else ()
        refresh_loop = resources.get("refresh_loop") if hasattr(resources, "get") else None
        broker = resources.get("broker") if hasattr(resources, "get") else None
        store = resources.get("store") if hasattr(resources, "get") else None
        try:
            broker_shutdown = broker.get_shutdown_summary() if broker is not None else None
        except Exception as summary_error:
            broker_shutdown = type(summary_error).__name__
        try:
            store_health = store.get_command_health() if store is not None else None
        except Exception as health_error:
            store_health = type(health_error).__name__
        strategy = (
            getattr(refresh_loop, "_strategy", None)
            if refresh_loop is not None
            else (captured_strategies[-1] if captured_strategies else None)
        )
        strategy_events = tuple(dict(event) for event in getattr(strategy, "order_events", ()))[
            -12:
        ]
        fact = getattr(strategy, "last_execution_facts", None)
        fact_summary = (
            None
            if fact is None
            else {
                "blockers": getattr(fact, "blockers", None),
                "risk_reduction_blockers": getattr(fact, "risk_reduction_blockers", None),
                "order_cancel_blockers": getattr(fact, "order_cancel_blockers", None),
                "query_set_id": getattr(fact, "query_set_id", None),
            }
        )
        native_calls = tuple(call for api in api_instances for call in api.native_calls)
        raise AssertionError(
            f"actual Cerebro chain failed: {exc}; ticks={observations!r}; "
            f"native_calls={native_calls!r}; resources={resource_names!r}; "
            f"store_write_calls={tuple(store_write_calls)!r}; "
            f"broker_rejections={tuple(broker_rejections)!r}; "
            f"refresh_errors={tuple(refresh_state['errors'])!r}; "
            f"refresh_receipts={tuple(refresh_receipts[-8:])!r}; "
            f"refresh_counts={(refresh_state['started'], refresh_state['completed'])!r}; "
            f"terminal_reconciliation={tuple(reconciliation_observations[-8:])!r}; "
            f"provider_terminal_rows={tuple(query_rows['orders_result'])!r}; "
            f"broker_shutdown={broker_shutdown!r}; store_health={store_health!r}; "
            f"strategy_block_reason={getattr(strategy, 'last_execution_block_reason', None)!r}; "
            f"strategy_events={strategy_events!r}; facts={fact_summary!r}; "
            f"cleanup={cleanup!r}; live_failure={failure!r}"
        ) from exc

    persist_diagnostic("known_cancel_run_returned", result_value={"phase1": result})
    if _capacity_only:
        tape = result["decision_tape"]
        readback = result["decision_tape_readback"]
        capacity = result.get("live_capacity")
        assert len(api_instances) == 1
        assert api_instances[0].closed is True
        assert api_instances[0].native_calls == []
        assert store_write_calls == []
        assert refresh_state["errors"] == []
        assert refresh_state["started"] == refresh_state["completed"]
        assert result["write_mode"] is False
        assert result["cleanup_complete"] is True
        assert result["strategy_shutdown_ready"] is True
        assert result["strategy_shutdown_post_join_confirmed"] is True
        assert tape["closed"] is True and tape["failed"] is False
        assert readback["record_count"] == tape["record_count"] == minute_count
        shutdown = {row["resource"]: row for row in result["resource_shutdown"]}
        assert shutdown["query_refresh"]["joined"] is True
        assert shutdown["decision_tape"]["status"] == "CLOSED"
        assert shutdown["store"]["shutdown_state"] == "PASS"
        factor_source_shutdown = shutdown["store"]["ctp_factor_source_shutdown"]
        assert factor_source_shutdown["status"] == "PASS"
        assert factor_source_shutdown["md_receipt"]["complete"] is True
        assert factor_source_shutdown["trader_receipt"]["complete"] is True
        assert capacity is not None

        def bounded_capacity_facts(facts):
            if not hasattr(facts, "get"):
                return {"status": "UNAVAILABLE"}
            return {
                key: facts.get(key)
                for key in (
                    "status",
                    "reason_code",
                    "line_buffer_count",
                    "bounded_line_buffer_count",
                    "unbounded_line_buffer_count",
                    "line_capacity_unavailable_count",
                    "line_capacity_sum",
                    "max_line_capacity",
                    "retained_line_value_count",
                    "retained_line_value_count_status",
                    "observation_complete",
                    "object_count",
                    "factor_call_count",
                )
                if key in facts
            }

        if not _defer_capacity_status_assertion:
            assert capacity["status"] == "RECORDED_NOT_EVALUATED", {
                "run_id": capacity.get("run_id"),
                "issues": capacity.get("issues"),
                "process_identity": capacity.get("process_identity"),
                "first_ready_engine_phase": capacity.get("first_ready_engine_phase"),
                "sample_count": capacity.get("sample_count"),
                "expected_ordinals": capacity.get("expected_ordinals"),
                "samples": tuple(
                    {
                        "ordinal": sample.get("ordinal"),
                        "status": sample.get("status"),
                        "issues": sample.get("issues"),
                        "cohort_identity": bounded_capacity_facts(sample.get("cohort_identity")),
                        "lines": bounded_capacity_facts(sample.get("lines")),
                        "cohort": bounded_capacity_facts(sample.get("cohort")),
                        "diagnostics": bounded_capacity_facts(sample.get("diagnostics")),
                        "orders": bounded_capacity_facts(sample.get("orders")),
                        "strategy_events": bounded_capacity_facts(sample.get("strategy_events")),
                    }
                    for sample in capacity.get("samples", ())
                ),
            }
        assert capacity["acceptance_evaluated"] is False
        assert capacity["run_id"] == "alpha003-factor-chain-run"
        assert capacity["postflight"] == {
            "status": "OBSERVED",
            "run_id": "alpha003-factor-chain-run",
            "epoch_id": result["epoch_id"],
            "cleanup_complete": True,
            "run_completed": True,
        }
        tape_path = Path(tape["path"])
        tape_rows = tuple(
            json.loads(line) for line in tape_path.read_text(encoding="utf-8").splitlines()
        )
        assert tape_rows[0]["record_type"] == "HEADER"
        assert len(tape_rows) - 1 == minute_count
        assert all(row["record_type"] == "DECISION" for row in tape_rows[1:])
        assert bar_source_trace["observer_errors"] == 0
        assert set(bar_source_trace["first_by_target"]) == set(plan["targets"])
        assert all(bar_source_trace["by_target_count"][target] > 0 for target in plan["targets"])
        for target in plan["targets"]:
            sample = bar_source_trace["first_by_target"][target]
            product = plan["product_by_target"][target]
            assert sample["source_role"] in {"history", "live"}
            assert sample["feed_member_id"] == target
            assert sample["feed_instrument"] == plan["routes"][product]
            assert sample["source_route"] == plan["routes"][product]
            assert sample["source_generation"] is not None
            assert sample["actual_bucket_start"] == sample["planned_bucket_start"]
            assert sample["actual_close_time"] == sample["planned_close_time"]
            assert sample["actual_trading_day"] == sample["planned_trading_day"]
            assert sample["actual_session_segment"] == sample["planned_session_segment"]
            assert sample["time_session_route_matches_planned_slot"] is True
            assert bar_source_trace["mapping_mismatch_count"][target] == 0
            assert bar_source_trace["mapping_match_count"][target] > 0
        return {
            "summary": result,
            "plan": result["_plan"],
            "tape_rows": tape_rows,
            "preheat_bars": config["factor"]["preheat_bars"],
            "source_clock_wait_boundary_probe": wait_boundary_probe,
            "causal_quote_barrier_trace": tuple(causal_quote_barrier_trace[-128:]),
            "post_dispatch_clock_advance": post_dispatch_clock_advances_by_close.get(
                post_dispatch_probe_close
            ),
        }

    if _fee_pair_source_only:
        tape = result["decision_tape"]
        assert result["write_mode"] is True
        assert result["cleanup_complete"] is True
        assert tape["closed"] is True and tape["failed"] is False
        assert refresh_state["errors"] == []
        assert refresh_state["started"] == refresh_state["completed"]
        assert len(api_instances) == 1 and api_instances[0].closed is True
        assert not [call for call in api_instances[0].native_calls if call[0] == "insert"]
        assert store_write_calls == []

        tape_rows = tuple(
            RUNNER.iter_decision_tape(Path(tape["path"]), max_bytes=tape["max_bytes"])
        )
        decision_rows = tuple(row for row in tape_rows if row["record_type"] == "DECISION")

        if _fee_pair_missing_pair_then_block:
            live_rows = tuple(
                row for row in decision_rows if row["readiness"] == "LIVE_READY"
            )
            pre_live_rows = tuple(
                row for row in decision_rows if row["readiness"] in {"WARMUP", "CATCHING_UP"}
            )
            assert not live_rows
            assert pre_live_rows, "the synthetic gap case must first exercise the pre-live path"
            assert len(fee_pair_source_attempts) >= 2, fee_pair_source_attempts
            first_attempt = fee_pair_source_attempts[0]
            later_attempts = tuple(fee_pair_source_attempts[1:])
            assert first_attempt["forced_missing_pair"] is True
            assert first_attempt["durable"] is False
            assert first_attempt["reason"] == "FEE_PAIR_LIVE_SOURCE_CANDIDATE_UNAVAILABLE"
            assert all(
                item["reason"] == "FEE_PAIR_SOURCE_SEQUENCE_BLOCKED"
                and item["durable"] is False
                and item["batch_id"] != first_attempt["batch_id"]
                and item["slot_index"] > first_attempt["slot_index"]
                for item in later_attempts
            ), later_attempts
            assert fee_pair_writer_attempts == [
                {
                    "batch_id": first_attempt["batch_id"],
                    "slot_index": first_attempt["slot_index"],
                }
            ]
            assert all(
                row["order_plan"]["status"] == "NO_ACTION"
                and not row["order_plan"]["actions"]
                for row in pre_live_rows
            )
            assert not [call for call in api_instances[0].native_calls if call[0] == "insert"]
            assert store_write_calls == []

            strategy = captured_strategies[-1]
            journal = journal_module.ExecutionDecisionJournal(tmp_path / "factor-chain.sqlite")
            try:
                assert journal.fee_pair_required_scope(
                    strategy._account_scope, strategy._strategy_scope
                ) is not None
                highwater = journal.source_highwater(
                    strategy._account_scope,
                    strategy._strategy_scope,
                    strategy._logical_run_id,
                    strategy._source_kind,
                )
                if pre_live_rows:
                    last_pre_live = pre_live_rows[-1]
                    assert highwater is not None
                    assert highwater.receipt.tape_file_id == last_pre_live["file_id"]
                    assert highwater.receipt.tape_record_id == last_pre_live["record_id"]
                    assert highwater.receipt.tape_record_index == last_pre_live["record_index"]
                    assert highwater.receipt.batch_id == last_pre_live["batch_id"]
                else:
                    assert highwater is None
            finally:
                journal.close()
            return {
                "evidence_level": "SOURCE_FAKE_REGISTERED_SIM_MISSING_PAIR_SEQUENCE_BLOCK_ONLY",
                "decision_rows": len(decision_rows),
                "pre_live_no_intent_rows": len(pre_live_rows),
                "live_source_only_rows": 0,
                "first_terminal_reason": first_attempt["reason"],
                "subsequent_terminal_reason": "FEE_PAIR_SOURCE_SEQUENCE_BLOCKED",
                "first_missing_batch_id": first_attempt["batch_id"],
                "writer_attempt_count": len(fee_pair_writer_attempts),
                "reservation_attempt_count": len(fee_pair_reservation_attempts),
                "complete_live_grid_coverage": False,
                "grid_acceptance": "SOURCE_ONLY_ONLY_NO_COMPLETE_GRID_ACCEPTANCE",
                "open_fill_close_cancel_chain": "NOT_COVERED_BY_THIS_REGISTERED_SCOPE_FIXTURE",
                "tape_closed": tape["closed"],
                "pre_live_highwater_matches_last_tape_row": bool(pre_live_rows),
            }

        live_rows = tuple(row for row in decision_rows if row["readiness"] == "LIVE_READY")
        assert live_rows
        assert all(
            row.get("fee_pair_workflow")
            and row["order_plan"]
            == {
                "status": "SOURCE_ONLY",
                "reason": "FEE_PAIR_NOT_AUTHORIZED",
                "decision_batch_id": row["batch_id"],
                "decision_available_at": row["available_at"],
                "actions": [],
            }
            for row in live_rows
        )
        journal = journal_module.ExecutionDecisionJournal(tmp_path / "factor-chain.sqlite")
        try:
            scope = journal.fee_pair_required_scope(
                "alpha003-factor-chain-account", "alpha003-factor-chain"
            )
            assert scope is not None
            workflow_rows = []
            source_kind = None
            for row in live_rows:
                extension = row["fee_pair_workflow"]
                workflow = journal.fee_pair_workflow_candidate(extension["candidate_id"])
                assert workflow is not None and workflow.state == "SOURCE_ONLY"
                assert workflow.candidate_sha256 == extension["candidate_sha256"]
                assert workflow.source_only_decision_id is not None
                decision = journal.decision(workflow.source_only_decision_id)
                assert decision is not None
                assert decision.intent_keys == () and decision.is_noop
                assert decision.economic_payload.get("_execution_source_anchor_only") is True
                assert decision.economic_payload.get("_execution_fee_pair_workflow") == dict(
                    extension
                )
                source_kind = decision.key.decision_kind
                workflow_rows.append(workflow)
            assert source_kind is not None
            highwater = journal.source_highwater(
                "alpha003-factor-chain-account",
                "alpha003-factor-chain",
                "alpha003-factor-chain-run",
                source_kind,
            )
            last_live = live_rows[-1]
            assert highwater is not None and highwater.anchor_kind == "SOURCE_ONLY"
            assert highwater.receipt.tape_file_id == last_live["file_id"]
            assert highwater.receipt.tape_record_id == last_live["record_id"]
            assert highwater.receipt.tape_record_index == last_live["record_index"]
            assert highwater.receipt.batch_id == last_live["batch_id"]
            assert len(workflow_rows) == len(live_rows)
        finally:
            journal.close()
        if _fee_pair_stale_snapshot_after_append:
            assert len(fee_pair_stale_snapshot_events) == 1
            stale_batch_id = fee_pair_stale_snapshot_events[0]
            assert stale_batch_id in {row["batch_id"] for row in live_rows}
            stale_results = tuple(
                row for row in fee_pair_stale_grid_results if row["batch_id"] == stale_batch_id
            )
            assert len(stale_results) == 1, stale_results
            assert (
                stale_results[0]["block_reason"]
                == "FACTOR_SNAPSHOT_CHANGED_BEFORE_DECISION"
            )
            assert stale_results[0]["has_open_action"] is False
            assert stale_batch_id in fee_pair_risk_path_batches
            assert fee_pair_live_ordinary_fallbacks == []
            return {
                "evidence_level": "SOURCE_FAKE_REGISTERED_SIM_SOURCE_ONLY_STALE_GRID_BLOCK_ONLY",
                "decision_rows": len(decision_rows),
                "live_source_only_rows": len(live_rows),
                "stale_batch_id": stale_batch_id,
                "stale_grid_reason": stale_results[0]["block_reason"],
                "input_open_action_count": stale_results[0]["input_open_action_count"],
                "input_reduction_action_count": stale_results[0][
                    "input_reduction_action_count"
                ],
                "open_filter_action_coverage": (
                    "EXERCISED"
                    if stale_results[0]["input_open_action_count"]
                    else "NOT_EXERCISED_NO_PLANNED_OPEN_ACTION"
                ),
                "owned_position_reduction_coverage": (
                    "EXERCISED"
                    if stale_results[0]["input_reduction_action_count"]
                    else "NOT_EXERCISED_NO_POSITION_ACTION"
                ),
                "open_action_after_stale_grid": stale_results[0]["has_open_action"],
                "ordinary_live_source_fallback_count": len(
                    fee_pair_live_ordinary_fallbacks
                ),
                "risk_path_reached_stale_batch": stale_batch_id
                in fee_pair_risk_path_batches,
                "owned_position_reduction_observed": False,
                "complete_live_grid_coverage": False,
                "grid_acceptance": "SOURCE_ONLY_ONLY_NO_COMPLETE_GRID_ACCEPTANCE",
                "open_fill_close_cancel_chain": "NOT_COVERED_BY_THIS_REGISTERED_SCOPE_FIXTURE",
                "tape_closed": tape["closed"],
                "tape_failed": tape["failed"],
                "highwater_matches_last_live_row": True,
            }
        return {
            "evidence_level": "SOURCE_FAKE_REGISTERED_SIM_FEE_PAIR_SOURCE_ONLY",
            "decision_rows": len(decision_rows),
            "live_source_only_rows": len(live_rows),
            "native_insert_count": 0,
            "store_submit_count": 0,
            "tape_closed": tape["closed"],
            "highwater_matches_last_live_row": True,
            "complete_live_grid_coverage": False,
            "observed_live_rows_all_source_only": True,
            "grid_acceptance": "SOURCE_ONLY_ONLY_NO_COMPLETE_GRID_ACCEPTANCE",
            "open_fill_close_cancel_chain": "NOT_COVERED_BY_THIS_REGISTERED_SCOPE_FIXTURE",
        }

    # The legacy OPEN/fill/CLOSE/CANCEL assertions below remain available to
    # historical callers, but current registered-scope tests return through the
    # SOURCE_ONLY branches above. This fixture has no pre-owned position, so it
    # does not currently cover owned-position CANCEL/CLOSE dispatch.
    assert len(api_instances) == 1
    cancel_api = api_instances[0]
    assert cancel_api.closed is True
    inserts = [call for call in cancel_api.native_calls if call[0] == "insert"]
    cancels = [call for call in cancel_api.native_calls if call[0] == "cancel"]
    assert inserts, (
        result,
        tuple(store_write_calls),
        tuple(broker_rejections),
        tuple(refresh_receipts[-8:]),
        tuple(
            (
                getattr(strategy, "last_execution_block_reason", None),
                getattr(getattr(strategy, "last_order_plan", None), "status", None),
                getattr(getattr(strategy, "last_order_plan", None), "reason", None),
                getattr(strategy, "last_execution_facts", None),
            )
            for strategy in captured_strategies[-1:]
        ),
        str(diagnostic_path),
    )
    assert cancels, result
    assert all(call[2] == "DCE" for call in inserts + cancels)
    assert result["write_mode"] is True
    assert result["shutdown_status"] == "PASS"
    events = result["strategy_order_events"]["events"]
    assert any(event["status"] == "ACCEPTED" for event in events), events
    assert any(event["status"] == "CANCELED" for event in events), events
    assert result["cleanup_complete"] is True

    # Start a second source-backed run on fresh journal/query state.  Its
    # factor OPEN receives one full CTP fill through the ordinary callback
    # queue, and the strategy then sends its configured run-end CLOSE_ALL.
    query_rows.clear()
    query_rows.update(make_query_rows())
    bars_by_instrument.clear()
    refill_bars()
    clock.reset(event_times)
    # The first run also exercises a fast refresh cadence while bars arrive.
    # During the second run, allow one bounded quote-only maintenance turn to
    # consume every target's real post-query tick before the next full query
    # set supersedes that snapshot. Query age and quote freshness gates remain
    # unchanged; only the fake run's refresh schedule is realistic for this
    # three-feed provider cadence.
    config["live"]["refresh_interval_seconds"] = 0.25
    config["live"].update(
        logical_run_id="alpha003-factor-chain-fill-close-run",
        journal_path=str(tmp_path / "factor-chain-fill-close.sqlite"),
    )
    config["output"]["decision_tape_path"] = str(tmp_path / "factor-chain-fill-close-tape.jsonl")
    config_path.write_text(
        runner_fixtures.yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    try:
        fill_close_result = RUNNER.run_live(
            config,
            config_path,
            plan,
            "native",
            1,
            decision=SimpleNamespace(effective_tier="live"),
            allow_write_flag=True,
        )
    except Exception as exc:
        persist_diagnostic("fill_close_run_exception", result_value={"phase1": result}, error=exc)
        resources = getattr(exc, "retained_live_resources", {})
        refresh_loop = resources.get("refresh_loop") if hasattr(resources, "get") else None
        live_failure = getattr(exc, "live_epoch_evidence", None)
        live_failure_summary = (
            None
            if not isinstance(live_failure, dict)
            else {
                key: live_failure.get(key)
                for key in (
                    "engine_winddown_status",
                    "engine_winddown_reason",
                    "strategy_shutdown_requested",
                    "strategy_shutdown_ready",
                    "strategy_shutdown_blocker",
                    "strategy_shutdown_post_join_confirmed",
                    "strategy_shutdown_post_join_blocker",
                    "refresh_status",
                    "refresh_blocker",
                    "refresh_error_code",
                    "reconciliation_blockers",
                    "strategy_order_events",
                )
            }
        )
        strategy = (
            getattr(refresh_loop, "_strategy", None)
            if refresh_loop is not None
            else (captured_strategies[-1] if captured_strategies else None)
        )
        broker = resources.get("broker") if hasattr(resources, "get") else None
        broker_positions = []
        if broker is not None and strategy is not None:
            for data in tuple(getattr(strategy, "datas", ())):
                try:
                    position = broker.execution_position_snapshot(data)
                    broker_positions.append(
                        (getattr(data, "_name", None), position, broker.getposition(data).size)
                    )
                except Exception as snapshot_error:
                    broker_positions.append(
                        (getattr(data, "_name", None), type(snapshot_error).__name__)
                    )
        fact = getattr(strategy, "last_execution_facts", None)
        native_calls = tuple(call for api in api_instances for call in api.native_calls)
        first_bad_reconciliation = next(
            (
                observation
                for observation in reconciliation_observations
                if any(
                    item[1] not in {"RESOLVED", "DUPLICATE", "EXTERNAL_TERMINAL_FLAT"}
                    for item in observation["items"]
                )
            ),
            None,
        )
        callback_index = next(
            (
                index
                for index, event in enumerate(fill_timeline)
                if event["kind"] == "provider_callback_fill"
            ),
            0,
        )
        fill_timing_window = tuple(fill_timeline[callback_index : callback_index + 28])
        terminal_tail = tuple(
            (
                observation["query_set_id"],
                observation["available_at"],
                tuple((item[1], item[2]) for item in observation["items"]),
            )
            for observation in reconciliation_observations[-8:]
        )
        refresh_tail = tuple(
            (
                receipt["attempt"],
                receipt["error_code"],
                receipt["query_set_id"],
                receipt["blockers"],
            )
            for receipt in refresh_receipts[-8:]
        )
        strategy_state = (
            None
            if strategy is None
            else (
                getattr(strategy, "shutdown_requested", None),
                getattr(strategy, "shutdown_ready", None),
                getattr(strategy, "shutdown_blocker", None),
                getattr(strategy, "last_execution_block_reason", None),
            )
        )
        plan = getattr(strategy, "last_order_plan", None)
        plan_summary = (
            None
            if plan is None
            else {
                "status": getattr(plan, "status", None),
                "reason": getattr(plan, "reason", None),
                "actions": tuple(
                    (
                        getattr(action, "action", None),
                        getattr(action, "target_id", None),
                        getattr(action, "instrument", None),
                        getattr(action, "side", None),
                        getattr(action, "position_effect", None),
                        getattr(action, "quantity", None),
                        getattr(action, "offset", None),
                        getattr(action, "reason", None),
                    )
                    for action in getattr(plan, "actions", ())
                ),
                "decision_available_at": getattr(plan, "decision_available_at", None),
                "decision_batch_id": getattr(plan, "decision_batch_id", None),
            }
        )
        fact_summary = (
            None
            if fact is None
            else {
                "blockers": getattr(fact, "blockers", None),
                "risk_reduction_blockers": getattr(fact, "risk_reduction_blockers", None),
                "order_cancel_blockers": getattr(fact, "order_cancel_blockers", None),
                "risk_reduction_ready": getattr(fact, "risk_reduction_ready", None),
                "open_risk_ready": getattr(fact, "open_risk_ready", None),
                "snapshot_id": getattr(fact, "snapshot_id", None),
                "query_set_id": getattr(fact, "query_set_id", None),
                "available_at": getattr(fact, "available_at", None),
                "account": getattr(fact, "account", None),
                "positions": tuple(
                    (
                        getattr(position, "target_id", None),
                        getattr(position, "instrument", None),
                        getattr(position, "quantity", None),
                        getattr(position, "owner_strategy_scope", None),
                        getattr(position, "owner_intent_id", None),
                        getattr(position, "average_price", None),
                        getattr(position, "stop_price", None),
                        getattr(position, "held_eligible_bars", None),
                        getattr(position, "position_book_status", None),
                        getattr(position, "position_book_blocker_code", None),
                    )
                    for position in getattr(fact, "positions", ())
                ),
                "quotes": tuple(
                    (
                        getattr(quote, "instrument", None),
                        getattr(quote, "bid", None),
                        getattr(quote, "ask", None),
                        getattr(quote, "event_time", None),
                        getattr(quote, "available_at", None),
                        getattr(quote, "quality", None),
                    )
                    for quote in getattr(fact, "quotes", ())
                ),
                "working_orders": tuple(
                    (
                        getattr(order, "instrument", None),
                        getattr(order, "state", None),
                        getattr(order, "position_effect", None),
                        getattr(order, "owner_intent_id", None),
                        getattr(order, "remaining_quantity", None),
                    )
                    for order in getattr(fact, "working_orders", ())
                ),
            }
        )
        query_completion_trace = tuple(
            (
                receipt["attempt"],
                receipt["query_set_id"],
                max((item[-1] for item in receipt["provenance"]), default=None),
            )
            for receipt in refresh_receipts[-8:]
        )
        tick_trace_summary = tuple(
            (
                item["sequence"],
                item["instrument"],
                item["query_set_id"],
                item["event_time"],
                item["received_wall_time"],
                item["source_clock"],
            )
            for item in store_tick_trace[-12:]
        )
        store_write_summary = tuple(
            (
                call.get("operation"),
                ((call.get("identity") or {}).get("info") or {}).get("instrument_id"),
                ((call.get("identity") or {}).get("info") or {}).get("exchange_id"),
                (call.get("identity") or {}).get("size"),
                ((call.get("identity") or {}).get("info") or {}).get("factor_position_effect"),
                ((call.get("identity") or {}).get("info") or {}).get("factor_intent_id"),
                ((call.get("identity") or {}).get("info") or {}).get("offset"),
                call.get("result"),
            )
            for call in store_write_calls[-12:]
        )
        idle_trace_summary = tuple(
            (
                item["sequence"],
                item["now"],
                item["query_set_id"],
                item["facts_available_at"],
                item["risk_reduction_ready"],
                item["risk_reduction_blockers"],
                item["positions"],
                item["quotes"],
                item["plan"],
                item["shutdown"],
            )
            for item in idle_decision_trace[-12:]
        )
        raise AssertionError(
            f"factor-driven OPEN/fill/CLOSE run failed: {exc}; "
            f"native_calls={native_calls!r}; "
            f"store_writes={store_write_summary!r}; "
            f"risk_scopes={tuple(risk_scope_trace[-8:])!r}; "
            f"risk_dispatch={tuple(risk_dispatch_trace[-8:])!r}; "
            f"broker_rejections={tuple(broker_rejections[-8:])!r}; "
            f"refresh_errors={tuple(refresh_state['errors'][:4])!r}; "
            f"refresh_tail={refresh_tail!r}; "
            f"fill_timing_window={fill_timing_window!r}; "
            f"query_completion_trace={query_completion_trace!r}; "
            f"terminal_tail={terminal_tail!r}; "
            f"first_bad_terminal_reconciliation={first_bad_reconciliation!r}; "
            f"broker_updates={tuple(broker_update_observations[-8:])!r}; "
            f"runner_reconciliation_blockers={tuple(getattr(refresh_loop, 'last_reconciliation_blockers', ())[-16:])!r}; "
            f"strategy_state={strategy_state!r}; "
            f"strategy_plan={plan_summary!r}; strategy_fact={fact_summary!r}; "
            f"live_failure={live_failure_summary!r}; "
            f"quote_only_tail={tuple(api_instances[-1].winddown_tick_observations[-9:])!r}; "
            f"store_tick_trace={tick_trace_summary!r}; "
            f"idle_decision_trace={idle_trace_summary!r}; "
            f"last_execution_block_reason={getattr(strategy, 'last_execution_block_reason', None)!r}; "
            f"remaining_source_bars={tuple((key, len(value)) for key, value in api_instances[-1]._source_bars.items())!r}; "
            f"winddown_poll_attempts={api_instances[-1].winddown_poll_attempts}; "
            f"winddown_poll_blockers={tuple(api_instances[-1].winddown_poll_blockers[-8:])!r}"
        ) from exc

    persist_diagnostic(
        "fill_close_run_returned",
        result_value={"phase1": result, "phase2": fill_close_result},
    )
    assert len(api_instances) == 2
    fill_close_api = api_instances[1]
    assert fill_close_api.closed is True
    submissions = [call for call in store_write_calls if call["operation"] == "submit"]
    assert any(
        call["identity"]["info"].get("factor_position_effect") == "OPEN" for call in submissions
    ), submissions
    assert any(
        call["identity"]["info"].get("factor_position_effect") == "CLOSE" for call in submissions
    ), (
        "ordinary Alpha003 produced no factor CLOSE; "
        f"submissions={tuple((call['identity']['data_name'], call['identity']['size'], call['identity']['info'].get('factor_position_effect'), call['identity']['info'].get('factor_intent_id'), call['identity']['info'].get('factor_reason'), call['identity']['info'].get('offset')) for call in submissions)!r}; "
        f"native_calls={tuple(fill_close_api.native_calls)!r}; "
        f"strategy_events={fill_close_result['strategy_order_events']!r}; "
        f"reconciliation={tuple(reconciliation_observations[-12:])!r}; "
        f"broker_updates={tuple(broker_update_observations[-12:])!r}; "
        f"fill_timeline={tuple(fill_timeline)!r}; "
        f"provider_positions={tuple(query_rows['positions_result'])!r}; "
        f"provider_trades={tuple(query_rows['trades_result'])!r}; "
        f"shutdown={(fill_close_result['shutdown_status'], fill_close_result['strategy_shutdown_blocker'], fill_close_result['strategy_shutdown_post_join_blocker'])!r}"
    )
    filled_open_instruments = {
        str(row.get("InstrumentID"))
        for row in query_rows["trades_result"]
        if str(row.get("OffsetFlag")) == "0"
    }
    assert filled_open_instruments, query_rows["trades_result"]
    assert any(
        call[0] == "insert" and call[1] in filled_open_instruments
        for call in fill_close_api.native_calls
    ), (fill_close_api.native_calls, filled_open_instruments)
    assert any(call[0] == "cancel" for call in fill_close_api.native_calls)
    assert fill_close_result["write_mode"] is True
    assert fill_close_result["shutdown_status"] == "PASS"
    fill_close_events = fill_close_result["strategy_order_events"]["events"]
    assert any(event["status"] == "COMPLETED" for event in fill_close_events), fill_close_events
    assert any(event["status"] == "CANCELED" for event in fill_close_events), fill_close_events
    assert fill_close_result["cleanup_complete"] is True

    shutdown = {item["resource"]: item for item in fill_close_result["resource_shutdown"]}
    assert shutdown["query_refresh"]["joined"] is True, shutdown
    assert shutdown["query_refresh"]["status"] == "RETURNED", shutdown
    assert shutdown["broker"]["status"] == "PASS", shutdown
    assert shutdown["broker"]["store_shutdown_state"] == "PASS", shutdown
    assert shutdown["store"]["status"] == "CLOSED_BY_BROKER", shutdown
    assert shutdown["store"]["shutdown_state"] == "PASS", shutdown
    assert shutdown["journal"]["status"] == "CLOSED", shutdown
    assert shutdown["decision_tape"]["status"] == "CLOSED", shutdown
    assert fill_close_result["decision_tape"]["closed"] is True
    assert fill_close_result["decision_tape"]["failed"] is False
    assert fill_close_result["decision_tape_readback"]["record_count"] == (
        fill_close_result["decision_tape"]["record_count"]
    )

    # Observe the original Strategy notify_trade events and the actual
    # Backtrader Trade object passed by Broker.  The strategy event intentionally
    # publishes aggregate PnL (gross/net), while the real Trade object carries
    # the aggregate commission used to derive the net value.
    fill_close_strategy_index = len(captured_strategies) - 1
    strategy_trade_events = tuple(dict(event) for event in captured_strategies[-1].trade_events)
    trade_observations = tuple(
        observation
        for observation in trade_notify_observations
        if observation["strategy_index"] == fill_close_strategy_index
    )
    assert tuple(event["status"] for event in strategy_trade_events) == ("OPEN", "CLOSED"), (
        strategy_trade_events,
        trade_observations,
    )
    assert len(trade_observations) == len(strategy_trade_events) == 2
    assert tuple(observation["event"] for observation in trade_observations) == (
        strategy_trade_events
    )
    assert tuple(observation["isclosed"] for observation in trade_observations) == (
        False,
        True,
    )
    for event, observation in zip(strategy_trade_events, trade_observations):
        assert event["ref"] == observation["trade_ref"]
        for field in ("size", "price", "pnl", "pnlcomm"):
            assert Decimal(event[field]) == Decimal(observation[field]), (
                event,
                observation,
                field,
            )

    close_submissions = [
        call
        for call in submissions
        if call["identity"]["info"].get("factor_position_effect") == "CLOSE"
    ]
    assert len(close_submissions) == 1, close_submissions
    close_identity = close_submissions[0]["identity"]
    close_intent_id = close_identity["info"].get("factor_intent_id")
    assert isinstance(close_intent_id, str) and close_intent_id
    close_trades = [
        row
        for row in query_rows["trades_result"]
        if str(row.get("InstrumentID")) == str(close_identity["info"].get("instrument_id"))
        and str(row.get("OffsetFlag")) == "1"
    ]
    assert len(close_trades) == 1, close_trades
    close_trade = close_trades[0]
    open_trades = [
        row
        for row in query_rows["trades_result"]
        if str(row.get("InstrumentID")) == str(close_identity["info"].get("instrument_id"))
        and str(row.get("OffsetFlag")) == "0"
    ]
    assert len(open_trades) == 1, open_trades
    open_trade = open_trades[0]

    open_event, closed_event = strategy_trade_events
    open_observation, closed_observation = trade_observations
    assert open_observation["instrument_id"] == closed_observation["instrument_id"]
    assert open_observation["instrument_id"] == str(open_trade["InstrumentID"])
    assert closed_observation["instrument_id"] == str(close_trade["InstrumentID"])
    assert open_event["ref"] == closed_event["ref"]
    assert open_event["status"] == "OPEN" and closed_event["status"] == "CLOSED"

    open_quantity = Decimal(str(open_trade["Volume"]))
    open_direction = str(open_trade["Direction"])
    assert open_direction in {"0", "1"}, open_trade
    signed_open_quantity = open_quantity if open_direction == "0" else -open_quantity
    assert Decimal(open_event["size"]) == signed_open_quantity, (open_event, open_trade)
    assert open_observation["long"] is (signed_open_quantity > 0), (
        open_observation,
        open_trade,
    )
    assert Decimal(closed_event["size"]) == 0, (closed_event, close_trade)
    assert closed_observation["long"] is open_observation["long"]

    open_price = Decimal(str(open_trade["Price"]))
    close_price = Decimal(str(close_trade["Price"]))
    close_direction = str(close_trade["Direction"])
    assert close_direction in {"0", "1"}, close_trade
    assert close_direction != open_direction, (open_trade, close_trade)
    assert Decimal(str(close_trade["Volume"])) == open_quantity, (open_trade, close_trade)
    assert Decimal(open_event["price"]) == open_price, (open_event, open_trade)
    # A closed Backtrader Trade retains its average entry price.  Its realized
    # closing execution price and quantity are reported by the completed order
    # projection and the source-backed CTP trade row below.
    assert Decimal(closed_event["price"]) == open_price, (closed_event, open_trade)
    assert close_price == open_price
    instrument_row = next(
        row
        for row in query_rows["instruments_result"]
        if str(row.get("InstrumentID")) == str(open_trade["InstrumentID"])
        and str(row.get("ExchangeID")) == str(open_trade["ExchangeID"])
    )
    expected_gross_pnl = (
        (close_price - open_price)
        * signed_open_quantity
        * Decimal(str(instrument_row["VolumeMultiple"]))
    )
    assert Decimal(open_event["pnl"]) == 0
    assert Decimal(closed_event["pnl"]) == expected_gross_pnl
    for event, observation in zip(strategy_trade_events, trade_observations):
        event_commission = Decimal(event["pnl"]) - Decimal(event["pnlcomm"])
        trade_commission = Decimal(observation["commission"])
        assert abs(event_commission - trade_commission) <= Decimal("0.00000001"), (
            event,
            observation,
        )
    assert Decimal(closed_observation["commission"]) >= Decimal(open_observation["commission"]) >= 0

    # Reopen the exact run journal only after Runner reports it CLOSED.  The
    # archive verifier and the read-only SQL below bind the provider callback,
    # native OrderRef, complete-query terminal observation, flat position
    # snapshot, and durable intent resolution for this actual Strategy CLOSE.
    from backtrader.stores.execution_decision_journal import ExecutionDecisionJournal
    from backtrader.stores.execution_journal_archive import (
        verify_execution_journal_archive,
    )

    journal_path = tmp_path / "factor-chain-fill-close.sqlite"
    archive_path = tmp_path / "factor-chain-fill-close-archive.sqlite3"
    archive_writer = ExecutionDecisionJournal(journal_path)
    try:
        archive_receipt = archive_writer.archive_snapshot(archive_path)
    finally:
        archive_writer.close()
    assert (
        verify_execution_journal_archive(
            archive_path,
            expected_schema_version=ExecutionDecisionJournal._SCHEMA_VERSION,
            expected_sha256=archive_receipt.sha256,
        )
        == archive_receipt
    )
    with closing(sqlite3.connect(archive_path.as_uri() + "?mode=ro", uri=True)) as archived:
        archived.execute("PRAGMA query_only = ON")
        callback_bindings = archived.execute(
            """SELECT i.intent_id,n.order_ref,n.instrument,n.exchange,n.trading_day,
                      c.receipt_id,c.callback_id,c.acknowledged,c.evidence_payload_json
               FROM execution_decision_callbacks AS c
               JOIN execution_decision_intents AS i ON i.intent_id=c.intent_id
               JOIN execution_native_intent_identities AS n ON n.intent_id=i.intent_id
               WHERE c.acknowledged=1
               ORDER BY c.created_at_ns"""
        ).fetchall()
        terminal_chain = archived.execute(
            """SELECT n.order_ref,n.instrument,n.exchange,n.trading_day,
                      c.callback_id,c.acknowledged,c.evidence_payload_json,
                      r.query_id,r.state,r.terminal_state,r.terminal_event_id,
                      r.position_snapshot_id,r.position_flat,
                      z.terminal_state,z.terminal_event_id,z.reconciliation_id,
                      z.position_snapshot_id,z.position_flat
               FROM execution_decision_intents AS i
               JOIN execution_native_intent_identities AS n ON n.intent_id=i.intent_id
               JOIN execution_decision_callbacks AS c
                 ON c.intent_id=i.intent_id AND c.callback_id LIKE 'ctp-trade:%'
               JOIN execution_intent_reconciliations AS r ON r.intent_id=i.intent_id
               JOIN execution_intent_resolutions AS z ON z.intent_id=i.intent_id
               WHERE i.intent_id=?
               ORDER BY r.created_at_ns DESC,c.created_at_ns DESC,c.callback_id ASC LIMIT 1""",
            (close_intent_id,),
        ).fetchone()
    assert terminal_chain is not None, close_intent_id
    (
        native_order_ref,
        native_instrument,
        native_exchange,
        native_trading_day,
        callback_id,
        callback_acknowledged,
        callback_payload_json,
        query_id,
        reconciliation_state,
        terminal_state,
        terminal_event_id,
        position_snapshot_id,
        position_flat,
        resolution_state,
        resolution_event_id,
        resolution_id,
        resolution_snapshot_id,
        resolution_flat,
    ) = terminal_chain
    callback_payload = json.loads(callback_payload_json)
    assert native_order_ref == str(close_trade["OrderRef"]), terminal_chain
    assert native_instrument == str(close_trade["InstrumentID"]), terminal_chain
    assert native_exchange == str(close_trade["ExchangeID"]), terminal_chain
    assert native_trading_day == str(close_trade["TradingDay"]), terminal_chain
    assert callback_id and callback_acknowledged == 1, terminal_chain
    assert callback_payload.get("evidence_kind") == "native_trade_callback", terminal_chain
    assert callback_payload["provider_trade_id"] == str(close_trade["TradeID"]), (
        callback_payload,
        close_trade,
    )
    assert query_id == terminal_event_id
    assert reconciliation_state == "KNOWN"
    assert terminal_state == resolution_state == "FILLED"
    assert resolution_event_id == terminal_event_id
    assert resolution_id
    assert position_snapshot_id == resolution_snapshot_id
    assert position_flat == resolution_flat == 1
    assert any(
        call[0] == "insert"
        and call[1] == native_instrument
        and call[2] == native_exchange
        and call[3] == native_order_ref
        for call in fill_close_api.native_calls
    ), (fill_close_api.native_calls, terminal_chain)

    callbacks_by_trade_id = defaultdict(list)
    for row in callback_bindings:
        payload = json.loads(row[8])
        trade_id = payload.get("provider_trade_id")
        if trade_id in {str(open_trade["TradeID"]), str(close_trade["TradeID"])}:
            callbacks_by_trade_id[trade_id].append((row, payload))
    assert set(callbacks_by_trade_id) == {
        str(open_trade["TradeID"]),
        str(close_trade["TradeID"]),
    }, callbacks_by_trade_id
    open_native_rows = [
        row
        for row, payload in callbacks_by_trade_id[str(open_trade["TradeID"])]
        if payload.get("evidence_kind") == "native_trade_callback"
    ]
    assert len(open_native_rows) == 1, open_native_rows
    open_intent_id = open_native_rows[0][0]

    completed_order_events = [
        event
        for event in fill_close_result["strategy_order_events"]["events"]
        if event["status"] == "COMPLETED"
    ]
    for trade_row, effect, trade_observation in (
        (open_trade, "OPEN", open_observation),
        (close_trade, "CLOSE", closed_observation),
    ):
        native_ref = str(trade_row["OrderRef"])
        trade_id = str(trade_row["TradeID"])
        callback_pair = callbacks_by_trade_id[trade_id]
        assert len(callback_pair) == 2, (trade_id, callback_pair)
        callback_by_kind = {}
        for callback_row, callback_payload in callback_pair:
            evidence_kind = callback_payload.get("evidence_kind")
            assert evidence_kind in {
                "native_trade_callback",
                "complete_trades_query_observation",
            }, (trade_id, callback_row, callback_payload)
            assert evidence_kind not in callback_by_kind, (trade_id, callback_pair)
            callback_by_kind[evidence_kind] = (callback_row, callback_payload)
            assert callback_row[7] == 1, (trade_id, callback_row)
        assert set(callback_by_kind) == {
            "native_trade_callback",
            "complete_trades_query_observation",
        }, (trade_id, callback_by_kind)
        native_callback_row, native_callback_payload = callback_by_kind["native_trade_callback"]
        query_callback_row, query_callback_payload = callback_by_kind[
            "complete_trades_query_observation"
        ]
        assert native_callback_row[:5] == query_callback_row[:5], (
            native_callback_row,
            query_callback_row,
        )
        native_receipt_id, native_callback_id = native_callback_row[5:7]
        query_receipt_id, query_callback_id = query_callback_row[5:7]
        assert native_receipt_id != query_receipt_id, callback_pair
        assert native_callback_id.startswith("ctp-trade:"), native_callback_row
        assert query_callback_id.startswith("query-trade:"), query_callback_row
        native_digest = native_callback_id[len("ctp-trade:") :]
        query_digest = query_callback_id[len("query-trade:") :]
        assert len(native_digest) == len(query_digest) == 64, callback_pair
        assert native_digest == query_digest and all(
            char in "0123456789abcdef" for char in native_digest
        ), callback_pair
        intent_id, observed_native_ref, instrument, exchange, trading_day = native_callback_row[:5]
        assert observed_native_ref == native_ref, (native_callback_row, trade_row)
        assert instrument == str(trade_row["InstrumentID"]), (native_callback_row, trade_row)
        assert exchange == str(trade_row["ExchangeID"]), (native_callback_row, trade_row)
        assert trading_day == str(trade_row["TradingDay"]), (native_callback_row, trade_row)
        expected_execution_id = "ctp:{}:{}".format(trade_row["TradeDate"], trade_id)
        local_fill_time = datetime.strptime(
            "{} {}".format(trade_row["TradeDate"], trade_row["TradeTime"]),
            "%Y%m%d %H:%M:%S",
        ).replace(tzinfo=timezone(timedelta(hours=8)))
        utc_fill_time = local_fill_time.astimezone(UTC)
        utc_epoch = datetime(1970, 1, 1, tzinfo=UTC)
        elapsed = utc_fill_time - utc_epoch
        expected_filled_at_ns = (
            elapsed.days * 86400 + elapsed.seconds
        ) * 1_000_000_000 + elapsed.microseconds * 1_000
        expected_common_payload = {
            "event_type": "execution_fill",
            "exchange": exchange,
            "execution_id": expected_execution_id,
            "fee": None,
            "filled_at_ns": expected_filled_at_ns,
            "instrument_id": instrument,
            "order_ref": native_ref,
            "order_sys_id": str(trade_row["OrderSysID"]),
            "price": str(Decimal(str(trade_row["Price"]))),
            "provider_trade_id": trade_id,
            "quantity": str(Decimal(str(trade_row["Volume"]))),
            "time_source": "CTP_TradeDate_TradeTime_UTC_PLUS_08",
        }
        for field, expected in expected_common_payload.items():
            assert native_callback_payload.get(field) == expected, (
                trade_id,
                field,
                native_callback_payload,
            )
            assert query_callback_payload.get(field) == expected, (
                trade_id,
                field,
                query_callback_payload,
            )
        assert query_callback_payload.get("evidence_kind") == ("complete_trades_query_observation")
        assert query_callback_payload.get("query_observation_id")
        assert query_callback_payload.get("snapshot_id")
        assert query_callback_payload.get("request_id", 0) > 0
        assert query_callback_payload.get("connection_generation", 0) > 0
        assert query_callback_payload.get("account_fingerprint") == (
            "alpha003-factor-chain-account"
        )
        assert query_callback_payload.get("account_scope") == ("alpha003-factor-chain-account")
        assert query_callback_payload.get("strategy_scope") == "alpha003-factor-chain"
        assert query_callback_payload.get("trading_day") == trading_day
        assert native_callback_row[0] == query_callback_row[0] == intent_id
        if effect == "OPEN":
            assert str(trade_row["OffsetFlag"]) == "0", trade_row
            assert str(trade_row["Direction"]) in {"0", "1"}, trade_row
        else:
            assert str(trade_row["OffsetFlag"]) == "1", trade_row
        matching_submissions = [
            call
            for call in submissions
            if call["identity"]["info"].get("factor_intent_id") == intent_id
            and call["identity"]["info"].get("factor_position_effect") == effect
        ]
        assert len(matching_submissions) == 1, (trade_row, native_callback_row, submissions)
        submission = matching_submissions[0]["identity"]
        assert Decimal(str(abs(submission["size"]))) == Decimal(str(trade_row["Volume"]))
        assert trade_observation["instrument_id"] == instrument
        order_events = [
            event for event in completed_order_events if event["ref"] == submission["ref"]
        ]
        assert len(order_events) == 1, (submission, completed_order_events)
        assert Decimal(order_events[0]["executed_size"]) == Decimal(str(submission["size"]))
        assert Decimal(order_events[0]["executed_price"]) == Decimal(str(trade_row["Price"]))
        assert any(
            call[0] == "insert"
            and call[1] == str(trade_row["InstrumentID"])
            and call[2] == str(trade_row["ExchangeID"])
            and call[3] == native_ref
            for call in fill_close_api.native_calls
        ), (trade_row, fill_close_api.native_calls)
        with closing(sqlite3.connect(archive_path.as_uri() + "?mode=ro", uri=True)) as archived:
            archived.execute("PRAGMA query_only = ON")
            position_fills = archived.execute(
                """SELECT account_scope,instrument,exchange,execution_id,receipt_id,
                          intent_id,strategy_scope,position_effect,order_side,
                          owner_intent_id,quantity,price,fee,filled_at_ns
                   FROM factor_position_fills WHERE intent_id=?""",
                (intent_id,),
            ).fetchall()
        assert len(position_fills) == 1, (trade_id, position_fills)
        (
            account_scope,
            fill_instrument,
            fill_exchange,
            fill_execution_id,
            fill_receipt_id,
            fill_intent_id,
            strategy_scope,
            position_effect,
            order_side,
            owner_intent_id,
            fill_quantity,
            fill_price,
            fill_fee,
            fill_filled_at_ns,
        ) = position_fills[0]
        expected_side = "BUY" if str(trade_row["Direction"]) == "0" else "SELL"
        expected_owner_intent = None if effect == "OPEN" else open_intent_id
        assert account_scope == "alpha003-factor-chain-account", position_fills
        assert fill_instrument == instrument and fill_exchange == exchange, position_fills
        assert fill_execution_id == expected_execution_id, position_fills
        assert fill_receipt_id in {native_receipt_id, query_receipt_id}, position_fills
        assert fill_intent_id == intent_id, position_fills
        assert strategy_scope == "alpha003-factor-chain", position_fills
        assert position_effect == effect and order_side == expected_side, position_fills
        assert owner_intent_id == expected_owner_intent, position_fills
        assert Decimal(fill_quantity) == Decimal(str(trade_row["Volume"])), position_fills
        assert Decimal(fill_price) == Decimal(str(trade_row["Price"])), position_fills
        assert fill_fee is None, position_fills
        assert fill_filled_at_ns == expected_filled_at_ns, position_fills
    with closing(sqlite3.connect(archive_path.as_uri() + "?mode=ro", uri=True)) as archived:
        archived.execute("PRAGMA query_only = ON")
        all_position_fills = archived.execute(
            "SELECT execution_id,intent_id FROM factor_position_fills ORDER BY execution_id"
        ).fetchall()
    assert len(all_position_fills) == 2, all_position_fills
    assert {row[0] for row in all_position_fills} == {
        "ctp:{}:{}".format(open_trade["TradeDate"], open_trade["TradeID"]),
        "ctp:{}:{}".format(close_trade["TradeDate"], close_trade["TradeID"]),
    }, all_position_fills
    persist_diagnostic(
        "complete",
        result_value={"phase1": result, "phase2": fill_close_result},
        archive_evidence={
            "path": str(archive_path),
            "sha256": archive_receipt.sha256,
            "size_bytes": archive_receipt.size_bytes,
            "table_row_counts": dict(archive_receipt.table_row_counts),
            "verified": True,
            "terminal_chain": terminal_chain,
            "provider_trade_id": close_trade.get("TradeID"),
            "strategy_trade_events": strategy_trade_events,
            "trade_notify_observations": trade_observations,
        },
    )


def _live_tape_semantic_projection(rows):
    member_fields = (
        "slot_index",
        "instrument",
        "source_ref",
        "source_role",
        "connection_generation",
        "feed_sequence",
        "bucket_start",
        "close_time",
        "available_at",
        "trading_day",
        "session_segment",
        "timezone_id",
        "clock_domain_id",
        "bar_id",
        "complete",
        "quality",
        "present",
        "missing_fields",
        "quality_flags",
        "event_source",
        "raw_values",
    )
    factor_value_fields = (
        "value",
        "status",
        "reason",
        "present",
        "complete",
        "quality",
        "source_role",
        "member_id",
        "source_ref",
        "sequence",
        "generation",
    )
    projected = []
    for row in rows[1:]:
        factors = row["factors"]["factors"]
        target_decision = row["target_decision"]
        if target_decision is None:
            decision = None
        else:
            decision = {
                key: target_decision.get(key)
                for key in (
                    "status",
                    "reason",
                    "factor_name",
                    "direction",
                    "rebalance_every",
                    "authorized_targets",
                    "eligible_targets",
                )
            }
            decision["targets"] = tuple(
                {
                    key: item.get(key)
                    for key in (
                        "target_id",
                        "product_key",
                        "target_position",
                        "raw_score",
                        "oriented_score",
                    )
                }
                for item in target_decision.get("targets", ())
            )
        projected.append(
            {
                "slot_index": row["slot_index"],
                "calendar_id": row["calendar_id"],
                "calendar_version": row["calendar_version"],
                "slot_id": row.get("slot_id"),
                "close_time": row["close_time"],
                "available_at": row["available_at"],
                "readiness": row["readiness"],
                "readiness_reasons": tuple(row["readiness_reasons"]),
                "members": {
                    target: {key: member.get(key) for key in member_fields}
                    for target, member in sorted(row["members"].items())
                },
                "factors": {
                    name: {
                        target: {key: value.get(key) for key in factor_value_fields}
                        for target, value in sorted(factor["values"].items())
                    }
                    for name, factor in sorted(factors.items())
                },
                "target_decision": decision,
                "order_plan": {
                    "status": row["order_plan"]["status"],
                    "reason": row["order_plan"]["reason"],
                    "actions": tuple(row["order_plan"]["actions"]),
                },
            }
        )
    # Some non-ready rows use IEEE NaN for an unavailable factor value. JSON
    # normalization keeps equal NaN projections comparable without erasing
    # any finite values or reason/membership differences.
    return len(projected), json.dumps(
        projected, allow_nan=True, sort_keys=True, separators=(",", ":")
    )


@pytest.mark.integration
def test_registered_sim_fee_pair_scope_fails_closed_before_open_dispatch(
    tmp_path, monkeypatch
):
    """Registered fee-pair scope writes SOURCE_ONLY and dispatches no OPEN."""

    outcome = _run_alpha003_live_strategy_order_chain_fixture(
        tmp_path,
        monkeypatch,
        _fee_pair_source_only=True,
        _diagnostic_path=tmp_path / "registered-fee-pair-fail-closed.json",
    )
    assert outcome["evidence_level"] == "SOURCE_FAKE_REGISTERED_SIM_FEE_PAIR_SOURCE_ONLY"
    assert outcome["live_source_only_rows"] > 0
    assert outcome["highwater_matches_last_live_row"] is True
    assert outcome["native_insert_count"] == 0
    assert outcome["store_submit_count"] == 0
    assert outcome["complete_live_grid_coverage"] is False
    assert (
        outcome["open_fill_close_cancel_chain"]
        == "NOT_COVERED_BY_THIS_REGISTERED_SCOPE_FIXTURE"
    )


@pytest.mark.skip(
    reason=(
        "Legacy OPEN/fill/CLOSE/CANCEL chain is pending a synthetic owned-position and "
        "working-order fixture compatible with the registered fee-pair OPEN fence."
    )
)
@pytest.mark.integration
def test_alpha003_live_strategy_submits_and_cancels_through_registered_sim(
    tmp_path, monkeypatch
):
    """Original order-chain acceptance remains pending; see the internal fixture helper."""
    _run_alpha003_live_strategy_order_chain_fixture(
        tmp_path,
        monkeypatch,
        _fee_pair_source_only=False,
    )


@pytest.mark.integration
def test_registered_sim_production_tape_and_live_capacity_exactbars_pair(tmp_path):
    """Compare the production live Strategy/tape and exactbars capacity.

    The source fixture selects from a saved bundle, so the formal saved-tape
    validator must reject its source contract.  A separate ordinary
    Cerebro/Research recomputation checks the synthetic tape values without
    claiming query-validator or formal acceptance evidence.
    """
    import backtrader as bt

    from scripts import validate_iteration51_saved_factor_tape as saved_tape_validator

    project_expected_plan = saved_tape_validator.project_expected_plan

    def bounded_capacity_report(report):
        if not hasattr(report, "get"):
            return None
        expected_ordinals = tuple(report.get("expected_ordinals") or ())
        samples = tuple(report.get("samples") or ())[:16]
        observed_ordinals = tuple(
            sample.get("ordinal")
            for sample in samples
            if hasattr(sample, "get") and type(sample.get("ordinal")) is int
        )
        return {
            "status": report.get("status"),
            "issues": tuple(report.get("issues") or ())[:32],
            "first_ready_engine_phase": report.get("first_ready_engine_phase"),
            "calendar_slot_count": report.get("calendar_slot_count"),
            "sample_count": report.get("sample_count"),
            "expected_ordinals": expected_ordinals,
            "observed_ordinals": observed_ordinals,
            "missing_ordinals": tuple(
                ordinal for ordinal in expected_ordinals if ordinal not in observed_ordinals
            ),
            "samples": tuple(
                {
                    "ordinal": sample.get("ordinal"),
                    "status": sample.get("status"),
                    "issues": tuple(sample.get("issues") or ())[:16],
                    "lines": _bounded_capacity_fact_projection(sample.get("lines"), group="lines"),
                    "diagnostics": _bounded_capacity_fact_projection(
                        sample.get("diagnostics"), group="diagnostics"
                    ),
                }
                for sample in samples
                if hasattr(sample, "get")
            ),
        }

    def saved_diagnostic(case_root):
        diagnostic_path = case_root / "alpha003-capacity-diagnostic.json"
        if not diagnostic_path.is_file():
            return None
        try:
            return json.loads(diagnostic_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None

    def saved_capacity_report(case_root):
        diagnostic = saved_diagnostic(case_root)
        result = diagnostic.get("result") if isinstance(diagnostic, dict) else None
        if isinstance(result, dict) and "phase1" in result:
            result = result.get("phase1")
        return result.get("live_capacity") if isinstance(result, dict) else None

    cases = {}
    case_results = []
    semantic_pairing = {"status": "NOT_EVALUATED"}
    original_cerebro = bt.Cerebro
    aggregate_path = tmp_path / "exactbars-capacity-ab-diagnostic.json"

    def write_aggregate_diagnostic():
        payload = {
            "schema": "alpha003_exactbars_capacity_ab_diagnostic_v1",
            "case_count": len(case_results),
            "cases": tuple(case_results),
            "semantic_pairing": semantic_pairing,
        }
        aggregate_path.write_text(
            json.dumps(payload, default=str, sort_keys=True, indent=2), encoding="utf-8"
        )

    def synthetic_offline_recompute(tape_rows, preheat_bars, factor_mode, source_factor_mode):
        """Recompute one synthetic tape through ordinary Cerebro/Research.

        This intentionally bypasses only the saved-tape *query-source*
        projection.  The formal validator remains unchanged and is not
        reported as passing for this saved-bundle fixture.
        """

        def decode_synthetic_factor_point(point, member):
            """Validate one synthetic point while preserving source generation types.

            The ordinary offline comparator does not invoke the formal tape
            validator: this fixture is deliberately a saved-bundle source and
            that validator rejects it before row validation.  Its factor
            generation field is bound to the source member, whose public
            contract permits a non-empty string or a positive integer.
            """
            expected_point_fields = {
                "value",
                "status",
                "reason",
                "present",
                "complete",
                "quality",
                "source_role",
                "member_id",
                "source_ref",
                "sequence",
                "generation",
            }
            if not hasattr(point, "keys") or set(point) != expected_point_fields:
                raise ValueError("synthetic factor point fields are invalid")
            value_row = point.get("value")
            if (
                not hasattr(value_row, "keys")
                or set(value_row) != {"finite", "value", "float64_hex"}
                or type(value_row.get("finite")) is not bool
                or type(value_row.get("float64_hex")) is not str
                or not value_row["float64_hex"]
            ):
                raise ValueError("synthetic factor value fields are invalid")
            if value_row["finite"]:
                raw_number = value_row.get("value")
                if raw_number is None or isinstance(raw_number, bool):
                    raise ValueError("synthetic finite factor value is invalid")
                number = float(raw_number)
                if not math.isfinite(number) or number.hex() != value_row["float64_hex"]:
                    raise ValueError("synthetic finite factor value encoding is invalid")
            else:
                if value_row.get("value") is not None or value_row["float64_hex"] != "nan":
                    raise ValueError("synthetic unavailable factor value is invalid")
                number = None

            status = point.get("status")
            reason = point.get("reason")
            if (
                type(status) is not str
                or status not in {"OUTPUT_AVAILABLE", "OUTPUT_UNAVAILABLE"}
                or (
                    reason is not None
                    and (type(reason) is not str or not reason or reason != reason.strip())
                )
                or (number is not None) != (status == "OUTPUT_AVAILABLE")
                or (number is not None) != (reason is None)
            ):
                raise ValueError("synthetic factor status/reason is invalid")
            if type(point.get("present")) is not bool or type(point.get("complete")) is not bool:
                raise ValueError("synthetic factor membership flags are invalid")
            for field in ("quality", "source_role", "member_id"):
                value = point.get(field)
                if type(value) is not str or not value or value != value.strip():
                    raise ValueError("synthetic factor receipt text is invalid")
            source_ref = point.get("source_ref")
            if source_ref is not None and (
                type(source_ref) is not str or not source_ref or source_ref != source_ref.strip()
            ):
                raise ValueError("synthetic factor source reference is invalid")
            sequence = point.get("sequence")
            if type(sequence) is not int or sequence < 1:
                raise ValueError("synthetic factor sequence is invalid")
            generation = point.get("generation")
            member_generation = member.get("connection_generation")
            if (
                type(generation) not in (str, int)
                or type(generation) is not type(member_generation)
                or generation != member_generation
                or (
                    type(generation) is str
                    and (
                        not generation or generation != generation.strip() or len(generation) > 256
                    )
                )
                or (type(generation) is int and generation < 1)
            ):
                raise ValueError("synthetic factor generation is not source-bound")
            return number, status, reason

        header = tape_rows[0]
        targets = tuple(header["targets"])
        decisions = tuple(tape_rows[1:])
        source_identity = header["source_snapshot_id"]
        calendar_id = header["calendar_id"]
        selection_evidence = header["selection_evidence"]
        authorized_targets = tuple(selection_evidence["authorized_targets"])
        expected = {
            "targets": targets,
            "minutes": tuple({"close_time": row["close_time"]} for row in decisions),
            "source_snapshot_id": source_identity,
            "calendar_id": calendar_id,
        }
        field_names = tuple(saved_tape_validator._OHLCV_FIELDS)
        raw_by_target = {
            target: {
                field: [float(row["members"][target]["raw_values"][field]) for row in decisions]
                for field in field_names
            }
            for target in targets
        }
        offline = saved_tape_validator._run_factor_strategy(
            expected,
            raw_by_target,
            factor_mode=factor_mode,
            direction=1,
        )
        failed_checks = []
        value_comparisons = 0
        reason_comparisons = 0
        membership_comparisons = 0
        live_ready_rows = 0
        finite_witnesses = set()
        finite_targets = set()
        two_candidate_witness_rows = 0
        source_sha256 = None
        plan_id = None
        for row_index, row in enumerate(decisions):
            if (
                row.get("record_index") != row_index + 1
                or row.get("slot_index") != row_index
                or row.get("calendar_id") != calendar_id
                or row.get("close_time") != expected["minutes"][row_index]["close_time"]
            ):
                failed_checks.append("tape_record_grid_binding")
            factor_block = row.get("factors")
            factor_rows = factor_block.get("factors") if hasattr(factor_block, "get") else None
            factor = factor_rows.get("alpha003") if hasattr(factor_rows, "get") else None
            if not hasattr(factor, "get"):
                failed_checks.append("tape_alpha003_factor_missing")
                continue
            current_source_sha = factor.get("source_sha256")
            current_plan_id = factor_block.get("plan_id")
            if source_sha256 is None:
                source_sha256 = current_source_sha
                plan_id = current_plan_id
            elif current_source_sha != source_sha256 or current_plan_id != plan_id:
                failed_checks.append("tape_factor_plan_or_source_changed")
            if (
                factor.get("mode") != header.get("factor_mode")
                or factor.get("mode") != source_factor_mode
                or factor.get("direction") != 1
                or factor.get("panel_line") != "factor"
                or not hasattr(factor.get("values"), "keys")
                or set(factor["values"]) != set(targets)
            ):
                failed_checks.append("tape_factor_metadata_or_membership")
            values = factor.get("values") if hasattr(factor.get("values"), "get") else {}
            members = row.get("members") if hasattr(row.get("members"), "get") else {}
            if set(members) != set(targets):
                failed_checks.append("tape_member_set")
            finite_candidates = {}
            for target in targets:
                saved = values.get(target)
                member = members.get(target)
                if not hasattr(saved, "get") or not hasattr(member, "get"):
                    failed_checks.append("tape_factor_or_member_missing")
                    continue
                try:
                    saved_number, saved_status, saved_reason = decode_synthetic_factor_point(
                        saved, member
                    )
                except Exception:
                    failed_checks.append("tape_factor_value_invalid")
                    continue
                actual = offline["values"][target][row_index]
                actual_reason = offline["reasons"][target][row_index]
                saved_value = saved["value"]
                if math.isfinite(actual):
                    value_matches = (
                        saved_number is not None
                        and saved_value.get("float64_hex") == actual.hex()
                        and float(saved_value.get("value")).hex() == actual.hex()
                    )
                else:
                    value_matches = saved_number is None and saved_value.get("float64_hex") == "nan"
                if not value_matches:
                    failed_checks.append("alpha003_value_hex_mismatch")
                if saved_reason != actual_reason:
                    failed_checks.append("alpha003_reason_mismatch")
                if (
                    saved.get("present") is not True
                    or saved.get("complete") is not True
                    or saved.get("quality") != member.get("quality")
                    or saved.get("source_role") != member.get("source_role")
                    or saved.get("member_id") != target
                    or saved.get("source_ref") != member.get("source_ref")
                    or saved.get("sequence") != member.get("feed_sequence")
                    or saved.get("generation") != member.get("connection_generation")
                    or (saved_number is not None) != (saved_status == "OUTPUT_AVAILABLE")
                ):
                    failed_checks.append("alpha003_member_receipt_mismatch")
                value_comparisons += 1
                reason_comparisons += 1
                membership_comparisons += 1
                if row_index >= preheat_bars - 1 and saved_number is not None:
                    finite_witnesses.add(saved_number.hex())
                    finite_targets.add(target)
                    if target in authorized_targets:
                        finite_candidates[target] = saved_number
            if (
                len(finite_candidates) >= 2
                and len({value.hex() for value in finite_candidates.values()}) >= 2
            ):
                two_candidate_witness_rows += 1

            expected_readiness = "LIVE_READY" if row_index >= preheat_bars - 1 else "WARMUP"
            if row.get("readiness") != expected_readiness:
                failed_checks.append("tape_readiness_cutoff")
            elif expected_readiness == "LIVE_READY":
                live_ready_rows += 1
                if row.get("readiness_reasons") != []:
                    failed_checks.append("live_ready_reasons_not_empty")
            try:
                saved_tape_validator._check_decision_membership(
                    row.get("target_decision"),
                    expected={"authorized_targets": list(authorized_targets)},
                    row=row,
                    factor_points=values,
                    source_sha256=current_source_sha,
                    source_factor_mode=header["factor_mode"],
                    direction=1,
                )
            except Exception:
                failed_checks.append("tape_decision_factor_membership")

        if offline.get("source_sha256") != source_sha256:
            failed_checks.append("offline_factor_source_mismatch")
        if header.get("factor_mode") != source_factor_mode:
            failed_checks.append("live_factor_mode_mismatch")
        if len(decisions) != 120:
            failed_checks.append("full_120_grid_missing")
        if live_ready_rows < 100:
            failed_checks.append("live_ready_threshold")
        if len(finite_witnesses) < 2:
            failed_checks.append("distinct_finite_witness_threshold")
        if len(finite_targets) < 2:
            failed_checks.append("distinct_target_witness_threshold")
        if two_candidate_witness_rows < 1:
            failed_checks.append("two_candidate_witness_threshold")
        expected_comparisons = len(decisions) * len(targets)
        if not (
            value_comparisons
            == reason_comparisons
            == membership_comparisons
            == expected_comparisons
        ):
            failed_checks.append("factor_comparison_count_mismatch")
        return {
            "status": "PASS" if not failed_checks else "FAIL",
            "evidence_level": "SYNTHETIC_ORDINARY_CEREBRO_RECOMPUTE_ONLY",
            "offline_factor_mode": factor_mode,
            "source_factor_mode": source_factor_mode,
            "selection_source": selection_evidence.get("selection_source"),
            "query_validator": "NOT_RUN_SAVED_BUNDLE_SOURCE_CONTRACT",
            "grid_count": len(decisions),
            "target_count": len(targets),
            "value_comparisons": value_comparisons,
            "reason_comparisons": reason_comparisons,
            "membership_comparisons": membership_comparisons,
            "live_ready_rows": live_ready_rows,
            "distinct_finite_witnesses": len(finite_witnesses),
            "distinct_finite_targets": len(finite_targets),
            "two_candidate_witness_rows": two_candidate_witness_rows,
            "factor_source_matches_tape": offline.get("source_sha256") == source_sha256,
            "failed_checks": tuple(sorted(set(failed_checks))),
        }

    for factor_mode in ("native", "build"):
        for exactbars in (0, 1):
            key = (factor_mode, exactbars)
            case_root = tmp_path / f"{factor_mode}-exactbars-{exactbars}"
            patch = pytest.MonkeyPatch()
            created_engines = []
            case_result = {
                "factor_mode": factor_mode,
                "exactbars": exactbars,
                "status": "FAIL",
                "diagnostic_path": str(case_root / "alpha003-capacity-diagnostic.json"),
            }
            try:
                case_root.mkdir()
                if exactbars == 0:
                    class ConfiguredCerebro(original_cerebro):
                        def __init__(self, *args, **kwargs):
                            assert kwargs.get("runonce") is False
                            assert kwargs.get("preload") is False
                            kwargs["exactbars"] = 0
                            super().__init__(*args, **kwargs)
                            created_engines.append(self)

                    patch.setattr(bt, "Cerebro", ConfiguredCerebro)
                else:
                    # This case exercises the actual run.py live entry, whose
                    # constructor must enable exactbars=1.  Do not patch or
                    # wrap Cerebro here: the line-capacity evidence below
                    # checks the real QBuffer effect of that production call.
                    assert bt.Cerebro is original_cerebro
                    case_result["production_cerebro_unpatched"] = True
                outcome = _run_alpha003_live_strategy_order_chain_fixture(
                    case_root,
                    patch,
                    _capacity_only=True,
                    _factor_mode=factor_mode,
                    _capture_capacity=True,
                    _causal_quote_barrier=True,
                    _defer_capacity_status_assertion=True,
                )

                if exactbars == 0:
                    assert len(created_engines) == 1
                    engine = created_engines[0]
                    assert engine.p.exactbars == 0
                    assert engine.p.runonce is False
                    assert engine.p.preload is False
                else:
                    assert not created_engines
                    assert bt.Cerebro is original_cerebro
                    case_result["production_cerebro_unpatched"] = True
                patch.undo()
                assert bt.Cerebro is original_cerebro

                summary = outcome["summary"]
                assert summary["factor_mode"] == factor_mode
                post_dispatch_probe = outcome["post_dispatch_clock_advance"]
                assert post_dispatch_probe is not None, (
                    factor_mode,
                    exactbars,
                    outcome["causal_quote_barrier_trace"][-4:],
                )
                assert post_dispatch_probe["callback_returned_before_advance"] is True
                assert post_dispatch_probe["advance_milliseconds"] == 12
                assert abs(
                    post_dispatch_probe["clock_advanced_after_tick_by_milliseconds"]
                    - 12
                ) <= 0.001
                case_result["source_clock_wait_boundary_probe"] = outcome[
                    "source_clock_wait_boundary_probe"
                ]
                case_result["causal_quote_barrier_trace"] = outcome[
                    "causal_quote_barrier_trace"
                ]
                expected_grid_count = len(outcome["plan"]["grid"].minutes)
                assert len(outcome["tape_rows"]) - 1 == expected_grid_count
                signature = _live_tape_semantic_projection(outcome["tape_rows"])
                cases[key] = signature
                case_result["decision_record_count"] = expected_grid_count
                case_result["semantic_projection_rows"] = signature[0]
                try:
                    project_expected_plan(
                        outcome["plan"],
                        clock_domain_id=summary["source_clock_domain_id"],
                        calendar_id=outcome["tape_rows"][0]["calendar_id"],
                    )
                except Exception as error:
                    query_source_preflight = {
                        "status": "REJECTED_SOURCE_CONTRACT",
                        "error_type": type(error).__name__,
                        "error_code": getattr(error, "code", None),
                        "selection_source": outcome["plan"].get("selection_source"),
                        "tape_selection_source": outcome["tape_rows"][0]
                        .get("selection_evidence", {})
                        .get("selection_source"),
                    }
                else:
                    query_source_preflight = {
                        "status": "UNEXPECTEDLY_ACCEPTED_SOURCE_CONTRACT",
                        "selection_source": outcome["plan"].get("selection_source"),
                    }
                case_result["formal_query_validator_preflight"] = query_source_preflight
                offline_recomputations = {}
                for offline_mode in ("native", "build"):
                    try:
                        recomputation = synthetic_offline_recompute(
                            outcome["tape_rows"],
                            outcome["preheat_bars"],
                            offline_mode,
                            factor_mode,
                        )
                    except Exception as error:
                        offline_recomputations[offline_mode] = {
                            "status": "EXCEPTION",
                            "error_type": type(error).__name__,
                            "error_code": getattr(error, "code", None),
                        }
                    else:
                        offline_recomputations[offline_mode] = recomputation
                case_result["offline_recomputations"] = offline_recomputations
                report = summary["live_capacity"]
                case_result["capacity"] = bounded_capacity_report(report)
                samples = report["samples"]
                failed_checks = []

                def require(check, condition):
                    if not condition:
                        failed_checks.append(check)

                require(
                    "capacity_report_complete", report.get("status") == "RECORDED_NOT_EVALUATED"
                )
                require(
                    "capacity_not_acceptance_evaluated", report.get("acceptance_evaluated") is False
                )
                require(
                    "source_clock_wait_boundary_contract",
                    case_result["source_clock_wait_boundary_probe"]
                    == {
                        "short_wait_returned": False,
                        "short_wait_advance_seconds": 0.5,
                        "event_not_delivered_before_deadline": True,
                        "long_wait_returned": False,
                        "event_delivered_at_scheduled_time": True,
                    },
                )
                require(
                    "capacity_sample_count_matches_grid",
                    report.get("sample_count") == len(report.get("expected_ordinals") or ()) == 16,
                )
                require(
                    "capacity_expected_ordinals_present",
                    tuple(report.get("expected_ordinals") or ())
                    == tuple(sample.get("ordinal") for sample in samples),
                )
                require(
                    "all_capacity_samples_observed",
                    all(sample.get("status") == "OBSERVED" for sample in samples),
                )
                line_rows = [sample.get("lines", {}) for sample in samples]
                require(
                    "all_line_facts_observed",
                    all(facts.get("status") == "OBSERVED" for facts in line_rows),
                )
                require(
                    "line_capacity_available",
                    all(facts.get("line_capacity_unavailable_count") == 0 for facts in line_rows),
                )
                require(
                    "line_buffers_observed",
                    all(facts.get("line_buffer_count", 0) > 0 for facts in line_rows),
                )
                if exactbars == 0:
                    require(
                        "unbounded_lines_present_for_exactbars_zero",
                        all(facts.get("unbounded_line_buffer_count", 0) > 0 for facts in line_rows),
                    )
                    require(
                        "unbounded_retained_values_grow_for_exactbars_zero",
                        len(line_rows) >= 2
                        and line_rows[-1].get("unbounded_retained_line_value_count", 0)
                        > line_rows[0].get("unbounded_retained_line_value_count", 0),
                    )
                else:
                    require(
                        "no_unbounded_lines_for_exactbars_one",
                        all(facts.get("unbounded_line_buffer_count") == 0 for facts in line_rows),
                    )
                    require(
                        "all_lines_bounded_for_exactbars_one",
                        all(
                            facts.get("bounded_line_buffer_count") == facts.get("line_buffer_count")
                            for facts in line_rows
                        ),
                    )
                    require(
                        "qbuffer_capacity_stable_for_exactbars_one",
                        len(
                            {
                                (
                                    facts.get("line_buffer_count"),
                                    facts.get("line_capacity_sum"),
                                    facts.get("max_line_capacity"),
                                )
                                for facts in line_rows
                            }
                        )
                        == 1,
                    )
                    require(
                        "production_live_entry_cerebro_unpatched",
                        case_result.get("production_cerebro_unpatched") is True
                        and bt.Cerebro is original_cerebro
                        and not created_engines,
                    )
                require(
                    "formal_query_validator_source_contract_rejected",
                    query_source_preflight.get("status") == "REJECTED_SOURCE_CONTRACT"
                    and query_source_preflight.get("error_code") == "PLAN_SELECTION_SOURCE_INVALID"
                    and query_source_preflight.get("selection_source") == "saved_bundle_legacy"
                    and query_source_preflight.get("tape_selection_source")
                    == "saved_bundle_legacy",
                )
                for offline_mode in ("native", "build"):
                    recomputation = offline_recomputations.get(offline_mode, {})
                    require(
                        f"synthetic_{offline_mode}_recomputation_completed",
                        recomputation.get("status") == "PASS",
                    )
                    require(
                        f"synthetic_{offline_mode}_source_mode_matches",
                        recomputation.get("source_factor_mode") == factor_mode,
                    )
                    require(
                        f"synthetic_{offline_mode}_mode_matches",
                        recomputation.get("offline_factor_mode") == offline_mode,
                    )
                    require(
                        f"synthetic_{offline_mode}_grid_matches",
                        recomputation.get("grid_count") == 120
                        and recomputation.get("target_count") == len(outcome["plan"]["targets"]),
                    )
                    expected_comparisons = expected_grid_count * len(outcome["plan"]["targets"])
                    require(
                        f"synthetic_{offline_mode}_value_comparisons_match",
                        recomputation.get("value_comparisons") == expected_comparisons,
                    )
                    require(
                        f"synthetic_{offline_mode}_reason_and_membership_match",
                        recomputation.get("reason_comparisons")
                        == recomputation.get("membership_comparisons")
                        == expected_comparisons,
                    )
                    require(
                        f"synthetic_{offline_mode}_live_ready_threshold",
                        recomputation.get("live_ready_rows", 0) >= 100,
                    )
                barrier_rows = case_result["causal_quote_barrier_trace"]
                barrier_slots = tuple(row.get("slot_index") for row in barrier_rows)
                live_ready_slots = tuple(
                    row["slot_index"]
                    for row in outcome["tape_rows"][1:]
                    if row.get("readiness") == "LIVE_READY"
                )
                contiguous_run_live_slots = (
                    tuple(range(barrier_slots[0], expected_grid_count))
                    if barrier_slots
                    else ()
                )
                require(
                    "causal_quote_barrier_covers_all_run_live_batches_and_live_ready_slots",
                    barrier_slots == contiguous_run_live_slots
                    and bool(live_ready_slots)
                    and set(live_ready_slots).issubset(barrier_slots),
                )
                require(
                    "all_quote_receipts_precede_risk_snapshot",
                    all(row.get("receipt_precedes_risk_snapshot") is True for row in barrier_rows),
                )
                require(
                    "risk_snapshot_quotes_match_actual_store_tick_fields",
                    all(
                        row.get("all_risk_quotes_match_receipts") is True
                        and all(
                            item.get("actual_tick_fields_match_observed_event") is True
                            and item.get("receipt_uses_actual_tick_received_time") is True
                            and item.get("callback_receipt_preserves_callback_time") is True
                            and item.get("quote_uses_actual_tick_received_time") is True
                            for item in row.get("risk_snapshot_quote_facts", ())
                        )
                        for row in barrier_rows
                    ),
                )
                probe_barrier_rows = tuple(
                    row
                    for row in barrier_rows
                    if row.get("close_time")
                    == outcome["post_dispatch_clock_advance"].get("close_time")
                )
                require(
                    "real_tick_receipt_and_quote_survive_12ms_post_callback_advance",
                    len(probe_barrier_rows) == 1
                    and probe_barrier_rows[0].get("post_dispatch_clock_advance")
                    == outcome["post_dispatch_clock_advance"]
                    and all(
                        item.get("matches_receipt") is True
                        for item in probe_barrier_rows[0].get(
                            "risk_snapshot_quote_facts", ()
                        )
                    ),
                )
                require(
                    "post_receipt_real_query_refresh_completed",
                    bool(barrier_rows)
                    and all(
                        isinstance(row.get("post_receipt_refresh"), dict)
                        and row["post_receipt_refresh"].get("status") == "PASS"
                        for row in barrier_rows
                    ),
                )
                require(
                    "post_receipt_refresh_has_real_query_set_id",
                    bool(barrier_rows)
                    and all(
                        row["post_receipt_refresh"].get("refresh_query_set_id_present") is True
                        for row in barrier_rows
                        if isinstance(row.get("post_receipt_refresh"), dict)
                    )
                    and all(isinstance(row.get("post_receipt_refresh"), dict) for row in barrier_rows),
                )
                require(
                    "all_quote_receipts_precede_risk_facts_snapshot",
                    bool(barrier_rows)
                    and all(
                        row.get("all_quote_receipts_precede_risk_facts_snapshot") is True
                        for row in barrier_rows
                    ),
                )
                require(
                    "risk_facts_use_same_post_receipt_query_set",
                    bool(barrier_rows)
                    and all(
                        row.get("risk_facts_query_set_matches_post_receipt_refresh") is True
                        for row in barrier_rows
                    ),
                )
                case_result["failed_checks"] = tuple(failed_checks)
                case_result["offline_recomputation_modes"] = (
                    ("native", "build")
                    if all(
                        offline_recomputations.get(mode, {}).get("status") == "PASS"
                        for mode in ("native", "build")
                    )
                    else ()
                )
                assert not failed_checks, {"failed_checks": tuple(failed_checks)}
                case_result["status"] = "PASS"
            except Exception as error:
                case_result["status"] = "FAIL"
                case_result["error_type"] = type(error).__name__
                case_result["error"] = str(error)[:512]
                report = saved_capacity_report(case_root)
                if report is not None:
                    case_result["capacity"] = bounded_capacity_report(report)
            finally:
                diagnostic = saved_diagnostic(case_root)
                if isinstance(diagnostic, dict):
                    clock_trace = diagnostic.get("source_clock_freshness_trace")
                    if isinstance(clock_trace, dict):
                        case_result["source_clock_freshness_trace"] = clock_trace
                try:
                    patch.undo()
                except Exception as error:
                    case_result["status"] = "FAIL"
                    case_result["cleanup_error_type"] = type(error).__name__
                    case_result["cleanup_error"] = str(error)[:256]
                case_results.append(case_result)
                write_aggregate_diagnostic()

    if len(cases) == 4:
        baseline = cases[("native", 0)]
        all_match = all(signature == baseline for signature in cases.values())
        baseline_rows = json.loads(baseline[1])
        comparison_diagnostics = {}
        for (factor_mode, exactbars), signature in sorted(cases.items()):
            candidate_rows = json.loads(signature[1])
            differing_slots = 0
            order_plan_reason_slots = 0
            target_decision_reason_slots = 0
            factor_reason_points = 0
            readiness_reason_slots = 0
            for expected_row, candidate_row in zip(baseline_rows, candidate_rows):
                if expected_row != candidate_row:
                    differing_slots += 1
                if (
                    expected_row["order_plan"].get("reason")
                    != candidate_row["order_plan"].get("reason")
                ):
                    order_plan_reason_slots += 1
                expected_decision = expected_row.get("target_decision")
                candidate_decision = candidate_row.get("target_decision")
                if (expected_decision or {}).get("reason") != (
                    candidate_decision or {}
                ).get("reason"):
                    target_decision_reason_slots += 1
                if expected_row.get("readiness_reasons") != candidate_row.get(
                    "readiness_reasons"
                ):
                    readiness_reason_slots += 1
                expected_factors = expected_row.get("factors", {})
                candidate_factors = candidate_row.get("factors", {})
                for factor_name in set(expected_factors) | set(candidate_factors):
                    expected_values = expected_factors.get(factor_name, {})
                    candidate_values = candidate_factors.get(factor_name, {})
                    for target in set(expected_values) | set(candidate_values):
                        if expected_values.get(target, {}).get("reason") != (
                            candidate_values.get(target, {}).get("reason")
                        ):
                            factor_reason_points += 1
            comparison_diagnostics[f"{factor_mode}/exactbars={exactbars}"] = {
                "full_projection_matches_baseline": signature == baseline,
                "differing_slots": differing_slots,
                "order_plan_reason_slots": order_plan_reason_slots,
                "target_decision_reason_slots": target_decision_reason_slots,
                "factor_reason_points": factor_reason_points,
                "readiness_reason_slots": readiness_reason_slots,
            }
        semantic_pairing = {
            "status": "PASS" if baseline[0] == 120 and all_match else "FAIL",
            "grid_count": baseline[0],
            "all_combinations_match": all_match,
            "comparison_diagnostics": comparison_diagnostics,
        }
    else:
        semantic_pairing = {
            "status": "INCOMPLETE",
            "completed_combination_count": len(cases),
        }
    write_aggregate_diagnostic()
    assert (
        len(case_results) == 4
        and all(result["status"] == "PASS" for result in case_results)
        and semantic_pairing["status"] == "PASS"
    ), {
        "cases": tuple(case_results),
        "semantic_pairing": semantic_pairing,
        "aggregate_diagnostic_path": str(aggregate_path),
    }
    baseline = cases[("native", 0)]
    assert baseline[0] == 120
    assert all(signature == baseline for signature in cases.values())
