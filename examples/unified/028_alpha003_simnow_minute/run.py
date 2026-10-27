"""Standalone entry point for the shared native Alpha003 example.

The runner only adapts explicit inputs to Backtrader's normal Cerebro,
FactorStrategy, shared bar-cohort, Broker and Store APIs.  It contains no
Alpha003 formula and never turns an observed-bar intersection into a calendar.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from collections import defaultdict, deque
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import signal
import sys
import threading
import time
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional, Tuple
import uuid

import yaml

from entry_tier import conflict as tier_conflict
from entry_tier import decide as decide_tier
from entry_tier import invalid as tier_invalid


SCHEMA = "backtrader.alpha003.simnow_runner.v1"
MINUTE_TAPE_SCHEMA = "backtrader.alpha003.minute_tape.v1"
QUOTE_TAPE_SCHEMA = "backtrader.alpha003.execution_quote_tape.v1"
METADATA_SCHEMA = "backtrader.alpha003.replay_instrument_metadata.v1"
LEGACY_DECISION_TAPE_SCHEMA = "backtrader.alpha003.decision_tape.v1"
DECISION_TAPE_SCHEMA = "backtrader.alpha003.decision_tape.v2"
SOURCE_ORIGIN_PARTITION_SCHEMA = "backtrader.execution_source_origin_partition.v1"
# The opt-in SOURCE_ONLY fee-pair helper applies tighter read limits than the
# general decision-tape reader.  The tape cap is aligned with the Journal's
# default decision-byte budget; a single line may be larger only when a future
# explicitly reviewed contract raises this fixed bound.
_FEE_PAIR_SOURCE_ONLY_MAX_TAPE_BYTES = 512 * 1024 * 1024
_FEE_PAIR_SOURCE_ONLY_MAX_RECORD_BYTES = 8 * 1024 * 1024
# The 87-target GRID receipt and its production execution evidence exceed the
# journal's general 64 KiB default. Keep this run-local cap bounded and leave
# the journal-wide default unchanged.
_LIVE_DECISION_JOURNAL_MAX_PAYLOAD_BYTES = 131_072
_LIVE_COMMISSION_QUERY_BUDGET_SECONDS = 3.0
_LIVE_COMMISSION_CACHE_REFRESH_SECONDS = 30.0
UTC = timezone.utc
OHLCV_FIELDS = ("open", "high", "low", "close", "volume", "openinterest")
RISK_FIELDS = (
    "max_hold_eligible_bars",
    "preclose_grace_seconds",
    "run_end_policy",
    "quote_max_age_seconds",
    "max_state_age_seconds",
    "max_notional_per_position",
    "max_total_notional",
    "max_margin_per_position",
    "max_total_margin",
    "max_loss_per_position",
    "max_total_loss",
    "round_trip_fee_upper_bound_per_contract",
    "stop_loss_ticks",
    "max_order_intents_per_grid",
    "max_order_intents_per_run",
)


class RunnerError(ValueError):
    """A public example input cannot establish its required run contract."""

    def __init__(self, code: str, detail: Optional[str] = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(code if detail is None else f"{code}: {detail}")


_CTP_FUTURES_SNAPSHOT_ERROR_CODES = frozenset(
    {
        "CATALOG_EXCHANGE_ID_MISSING",
        "CATALOG_EXPIRY_INVALID",
        "CATALOG_FIELD_CONFLICT",
        "CATALOG_IDENTITY_INVALID",
        "CATALOG_INSTRUMENT_ID_MISSING",
        "CATALOG_NORMALIZATION_FAILED",
        "CATALOG_PRODUCT_CLASS_INVALID",
        "CATALOG_PRODUCT_CLASS_MISSING",
        "CATALOG_PRODUCT_ID_MISSING",
        "CATALOG_QUERY_CALL_FAILED",
        "CATALOG_ROW_INVALID",
        "COLLECTION_LIMIT_INVALID",
        "COLLECTION_SPAN_EXCEEDED",
        "COLLECTION_TIMEOUT",
        "COLLECTOR_CLOCK_INVALID",
        "CTP_SDK_UNAVAILABLE",
        "PUBLIC_QUERY_METHOD_MISSING",
        "QUERY_BOOLEAN_STATE_INVALID",
        "QUERY_COMPLETION_TIME_INVALID",
        "QUERY_COMPLETION_TIME_MISSING",
        "QUERY_ERROR",
        "QUERY_ERROR_MESSAGE",
        "QUERY_ERROR_STATE_INVALID",
        "QUERY_GENERATION_INVALID",
        "QUERY_GENERATION_MISMATCH",
        "QUERY_INCOMPLETE",
        "QUERY_LATE_CALLBACKS",
        "QUERY_RECORDS_NOT_IMMUTABLE",
        "QUERY_REQUEST_ID_COLLISION",
        "QUERY_REQUEST_ID_INVALID",
        "QUERY_REQUEST_TYPE_INVALID",
        "QUERY_REQUEST_TYPE_MISMATCH",
        "QUERY_REQUEST_FILTERS_MISMATCH",
        "QUERY_RECORD_LIMIT_INVALID",
        "QUERY_RECORD_LIMIT_UNAVAILABLE",
        "QUERY_RECORD_LIMIT_MISMATCH",
        "QUERY_RECORD_LIMIT_STATE_INVALID",
        "QUERY_RECORD_LIMIT_EXCEEDED",
        "QUERY_RESULT_TYPE_INVALID",
        "QUERY_ROW_KEY_UNSUPPORTED",
        "QUERY_ROW_VALUE_UNSUPPORTED",
        "QUERY_START_TIME_INVALID",
        "QUERY_SUBMISSION_FAILED",
        "QUERY_TERMINAL_PACKET_MISSING",
        "QUERY_TIME_IN_FUTURE",
        "QUERY_TIME_REVERSED",
        "QUERY_TIMED_OUT",
        "QUERY_UNSUPPORTED",
        "PRODUCT_QUERY_EMPTY",
        "PRODUCT_QUERY_RECORD_CAP_EXCEEDED",
        "PRODUCT_FIELD_CONFLICT",
        "PRODUCT_CANONICAL_COLLISION",
        "PRODUCT_DUPLICATE",
        "PRODUCT_CLASS_MISMATCH",
        "PRODUCT_CLASS_MISSING",
        "PRODUCT_CLASS_INVALID",
        "PRODUCT_EXCHANGE_ID_MISSING",
        "PRODUCT_EXCHANGE_ID_INVALID",
        "PRODUCT_ID_MISSING",
        "PRODUCT_ID_INVALID",
        "PRODUCTS_QUERY_CALL_FAILED",
        "INSTRUMENT_RECORD_CAP_EXHAUSTED",
        "INSTRUMENT_RECORD_CAP_EXCEEDED",
        "INSTRUMENT_QUERY_ROW_SCOPE_MISMATCH",
        "DEPTH_QUERY_CALL_FAILED",
        "QUOTE_ACTION_DAY_INVALID",
        "QUOTE_EXCHANGE_ID_MISSING",
        "QUOTE_IDENTITY_INVALID",
        "QUOTE_INSTRUMENT_ID_MISSING",
        "QUOTE_OPEN_INTEREST_MISSING",
        "QUOTE_QUERY_CALL_FAILED",
        "QUOTE_ROW_INVALID",
        "QUOTE_TRADING_DAY_INVALID",
        "QUOTE_TRADING_DAY_MISSING",
        "QUOTE_UPDATE_MILLISEC_INVALID",
        "QUOTE_UPDATE_TIME_INVALID",
        "QUOTE_VOLUME_MISSING",
        "ROW_FIELD_CONFLICT",
        "SESSION_CHANGED_DURING_COLLECTION",
        "SESSION_GENERATION_UNAVAILABLE",
        "SESSION_NOT_READ_ONLY_READY",
        "SESSION_STATE_METHOD_MISSING",
        "SESSION_STATE_UNAVAILABLE",
        "SESSION_TRADING_DAY_UNAVAILABLE",
        "SNAPSHOT_AGE_LIMIT_INVALID",
        "SNAPSHOT_TOO_OLD",
        "SOURCE_PREFIX_INVALID",
    }
)


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RunnerError("INPUT_OBJECT_REQUIRED", label)
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    missing = expected.difference(value)
    extra = set(value).difference(expected)
    if missing or extra:
        raise RunnerError(
            "INPUT_FIELDS_INVALID",
            f"{label}: missing={sorted(missing)} extra={sorted(extra)}",
        )


def _text(value: Any, label: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise RunnerError("INPUT_TEXT_INVALID", label)
    return value


def _aware_datetime(value: Any, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif type(value) is str:
        raw = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            raise RunnerError("INPUT_TIMESTAMP_INVALID", label) from None
    else:
        raise RunnerError("INPUT_TIMESTAMP_INVALID", label)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RunnerError("INPUT_TIMESTAMP_NAIVE", label)
    return parsed.astimezone(UTC)


def _iso_date(value: Any, label: str) -> date:
    if type(value) is not str:
        raise RunnerError("INPUT_DATE_INVALID", label)
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise RunnerError("INPUT_DATE_INVALID", label) from None
    if parsed.isoformat() != value:
        raise RunnerError("INPUT_DATE_INVALID", label)
    return parsed


def _tape_trading_day(value: Any, label: str) -> str:
    """Serialize a canonical cohort day as ISO, accepting the CTP wire form."""
    if type(value) is str and len(value) == 8 and value.isascii() and value.isdecimal():
        try:
            return datetime.strptime(value, "%Y%m%d").date().isoformat()
        except ValueError:
            raise RunnerError("INPUT_DATE_INVALID", label) from None
    return _iso_date(value, label).isoformat()


def _number(value: Any, label: str, *, positive: bool = False, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or value is None:
        raise RunnerError("INPUT_NUMBER_INVALID", label)
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise RunnerError("INPUT_NUMBER_INVALID", label) from None
    if not math.isfinite(number):
        raise RunnerError("INPUT_NUMBER_INVALID", label)
    if positive and number <= 0:
        raise RunnerError("INPUT_NUMBER_INVALID", label)
    if nonnegative and number < 0:
        raise RunnerError("INPUT_NUMBER_INVALID", label)
    return number


def _decimal(value: Any, label: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise RunnerError("INPUT_DECIMAL_INVALID", label)
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise RunnerError("INPUT_DECIMAL_INVALID", label) from None
    if not number.is_finite() or (positive and number <= 0):
        raise RunnerError("INPUT_DECIMAL_INVALID", label)
    return number


def _read_json(path: Path, label: str) -> Mapping[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle, parse_float=Decimal)
    except OSError:
        raise RunnerError("INPUT_FILE_UNAVAILABLE", label) from None
    except (json.JSONDecodeError, UnicodeError):
        raise RunnerError("INPUT_JSON_INVALID", label) from None
    return _mapping(value, label)


def _resolve_path(config_path: Path, value: Any, label: str) -> Path:
    if type(value) is not str or not value or value != value.strip():
        raise RunnerError("INPUT_PATH_REQUIRED", label)
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = config_path.parent / path
    return path.resolve(strict=False)


_CONFIG_KEYS = {
    "schema",
    "mode",
    "entry",
    "factor",
    "selection",
    "inputs",
    "research",
    "cohort",
    "replay",
    "risk",
    "live",
    "output",
}
_SECTION_KEYS = {
    "entry": {"tier"},
    "factor": {"mode", "direction", "preheat_bars", "rebalance_every"},
    "selection": {
        "source",
        "query_mode",
        "bundle",
        "authorized_products",
        "daily_bundles",
        "max_epochs",
    },
    "inputs": {"minute_tape", "execution_quotes", "instrument_metadata", "history_decision_tape"},
    "research": {"start", "end", "source_timezone", "price_basis"},
    "cohort": {
        "calendar_id",
        "calendar_version",
        "epoch_id",
        "clock_domain_id",
        "timezone_id",
        "session_semantics",
        "max_pending_slots",
        "max_window_bars",
        "wait_timeout_seconds",
        "max_live_bar_age_seconds",
        "max_future_skew_seconds",
    },
    "replay": {"starting_cash", "commission"},
    "risk": {"policy_id", *RISK_FIELDS},
    "live": {
        "store_config_env",
        "allow_writes",
        "account_scope",
        "strategy_scope",
        "logical_run_id",
        "journal_path",
        "arm_templates",
        "ready_timeout_seconds",
        "refresh_timeout_seconds",
        "refresh_overall_timeout_seconds",
        "refresh_interval_seconds",
        "quote_max_age_seconds",
        "query_max_age_seconds",
        "loss_guard_net_loss_threshold",
        "loss_guard_max_observation_age_seconds",
        "shutdown_grace_seconds",
        "golden_targets",
        "commission_identity_by_target",
    },
    "output": {
        "directory",
        "evaluate_with_fincore",
        "decision_tape_path",
        "decision_tape_max_bytes",
    },
}


def load_config(config_path: Path) -> dict[str, Any]:
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            config = yaml.safe_load(handle)
    except OSError:
        raise RunnerError("CONFIG_FILE_UNAVAILABLE", str(config_path)) from None
    except yaml.YAMLError:
        raise RunnerError("CONFIG_YAML_INVALID", str(config_path)) from None
    config = dict(_mapping(config, "config"))
    unknown = set(config).difference(_CONFIG_KEYS)
    missing = _CONFIG_KEYS.difference(config)
    if unknown or missing:
        raise RunnerError(
            "CONFIG_FIELDS_INVALID", f"missing={sorted(missing)} extra={sorted(unknown)}"
        )
    if config.get("schema") != SCHEMA:
        raise RunnerError("CONFIG_SCHEMA_UNSUPPORTED", str(config.get("schema")))
    if config.get("mode") not in {"dry", "research", "replay", "live"}:
        raise RunnerError("CONFIG_MODE_INVALID")
    for section, expected in _SECTION_KEYS.items():
        row = dict(_mapping(config.get(section), section))
        # Keep the original one-bundle public configuration valid.  Daily
        # rollover is an additive opt-in and omitted source/epoch keys retain
        # the original offline-bundle behavior for copied configurations.
        if section == "selection":
            row.setdefault("source", "bundle")
            row.setdefault("query_mode", "legacy_two_query")
            row.setdefault("daily_bundles", [])
            row.setdefault("max_epochs", 1)
        elif section == "inputs":
            # Existing copied configurations remain valid; saved-history
            # continuation is an explicit live-only opt-in.
            row.setdefault("history_decision_tape", None)
        elif section == "live":
            # Golden live validation is an explicit feed subset; omitted keys
            # preserve the existing complete-pool runner behavior.
            row.setdefault("golden_targets", None)
            # Existing copied configs remain valid for dry/read-only runs. A
            # write-enabled live run validates these explicitly before setup.
            row.setdefault("loss_guard_net_loss_threshold", None)
            row.setdefault("loss_guard_max_observation_age_seconds", None)
            # Optional fee-query identity never becomes a startup requirement;
            # an invalid or absent row simply leaves OPEN fee evidence blocked.
            row.setdefault("commission_identity_by_target", None)
        extra = set(row).difference(expected)
        missing_section = expected.difference(row)
        if extra or missing_section:
            raise RunnerError(
                "CONFIG_SECTION_FIELDS_INVALID",
                f"{section}: missing={sorted(missing_section)} extra={sorted(extra)}",
            )
        config[section] = row
    daily_bundles = config["selection"]["daily_bundles"]
    if type(daily_bundles) is not list:
        raise RunnerError("DAILY_SELECTION_BUNDLES_INVALID")
    for index, value in enumerate(daily_bundles):
        _text(value, f"selection.daily_bundles[{index}]")
    selection = config["selection"]
    if selection["source"] not in {"bundle", "ctp_query"}:
        raise RunnerError("SELECTION_SOURCE_INVALID")
    if type(selection["query_mode"]) is not str or selection["query_mode"] not in {
        "legacy_two_query",
        "staged_product_set",
    }:
        raise RunnerError("SELECTION_QUERY_MODE_INVALID")
    if selection["source"] != "ctp_query" and selection["query_mode"] != "legacy_two_query":
        raise RunnerError("SELECTION_QUERY_MODE_REQUIRES_CTP_QUERY")
    max_epochs = selection["max_epochs"]
    if type(max_epochs) is not int or not 1 <= max_epochs <= 100:
        raise RunnerError("SELECTION_MAX_EPOCHS_INVALID")
    if selection["source"] == "ctp_query" and daily_bundles:
        raise RunnerError("QUERY_SELECTION_DAILY_BUNDLES_UNSUPPORTED")
    return config


def _validate_golden_targets_option(
    config: Mapping[str, Any], *, mode: str, decision: Any, allow_write_flag: bool
) -> Optional[tuple[str, ...]]:
    """Validate the opt-in read-only CTP golden feed subset before resources."""

    live = config.get("live")
    if not isinstance(live, Mapping):
        raise RunnerError("LIVE_SECTION_INVALID")
    raw_targets = live.get("golden_targets")
    if raw_targets is None:
        return None
    selection = config.get("selection")
    if (
        mode != "live"
        or not isinstance(selection, Mapping)
        or selection.get("source") != "ctp_query"
        or selection.get("daily_bundles")
    ):
        raise RunnerError("GOLDEN_TARGETS_LIVE_CTP_QUERY_REQUIRED")
    if (
        live.get("allow_writes") is not False
        or allow_write_flag is not False
        or getattr(decision, "effective_tier", None) != "live"
    ):
        raise RunnerError("GOLDEN_TARGETS_READ_ONLY_REQUIRED")
    arm_templates = live.get("arm_templates")
    if type(arm_templates) is not list or arm_templates:
        raise RunnerError("GOLDEN_TARGETS_WRITE_CONFIGURATION_UNSUPPORTED")
    if type(raw_targets) is not list:
        raise RunnerError("GOLDEN_TARGETS_INVALID")
    if not 3 <= len(raw_targets) <= 5:
        raise RunnerError("GOLDEN_TARGETS_COUNT_INVALID")
    targets = []
    for target in raw_targets:
        if (
            type(target) is not str
            or not target
            or target != target.strip()
            or target != target.upper()
            or target.count(".") != 1
            or any(not part for part in target.split("."))
        ):
            raise RunnerError("GOLDEN_TARGETS_INVALID")
        targets.append(target)
    if len(targets) != len(set(targets)):
        raise RunnerError("GOLDEN_TARGETS_DUPLICATE")
    authorized = selection.get("authorized_products")
    if authorized is not None and (
        type(authorized) is not list
        or not authorized
        or any(type(target) is not str or not target for target in authorized)
        or not set(authorized).intersection(targets)
    ):
        raise RunnerError("GOLDEN_AUTHORIZED_TARGETS_EMPTY")
    return tuple(sorted(targets))


def _daily_bundle_paths(config: Mapping[str, Any], config_path: Path) -> tuple[Path, ...]:
    """Resolve the ordered future bundles without opening their contents."""

    rows = config["selection"].get("daily_bundles", [])
    if type(rows) is not list:
        raise RunnerError("DAILY_SELECTION_BUNDLES_INVALID")
    primary = _resolve_path(config_path, config["selection"]["bundle"], "selection.bundle")
    paths = tuple(
        _resolve_path(config_path, value, f"selection.daily_bundles[{index}]")
        for index, value in enumerate(rows)
    )
    if primary in paths or len(paths) != len(set(paths)):
        raise RunnerError("DAILY_SELECTION_BUNDLE_DUPLICATE")
    return paths


def _requested_mode(config: Mapping[str, Any], cli_mode: Optional[str]) -> str:
    return str(cli_mode or config["mode"])


def resolve_mode(config: Mapping[str, Any], cli_mode: Optional[str]):
    mode = _requested_mode(config, cli_mode)
    requested_tier = "dry" if mode in ("dry", "research") else mode
    decision = decide_tier(config, requested_tier if cli_mode is not None else None)
    if tier_invalid(decision):
        raise RunnerError("ENTRY_TIER_INVALID")
    if tier_conflict(decision):
        raise RunnerError("ENTRY_TIER_ESCALATION_DENIED")
    mode_tier = "dry" if mode in ("dry", "research") else mode
    rank = {"dry": 0, "replay": 1, "live": 2}
    if rank[mode_tier] > rank[decision.effective_tier]:
        raise RunnerError("ENTRY_TIER_ESCALATION_DENIED")
    return mode, decision


def _target_id(product: Any) -> str:
    return f"{product.exchange_id}.{product.product_id}"


def _session_documents(bundle: Mapping[str, Any]):
    from backtrader.feeds.futures_sessions import load_exchange_session_calendar

    docs = bundle.get("calendars")
    if type(docs) is not list or not docs:
        raise RunnerError("SESSION_CALENDAR_REQUIRED")
    calendars = {}
    for document in docs:
        _mapping(document, "session calendar")
        if document.get("schema") != "backtrader.exchange_session_calendar.v1":
            raise RunnerError("SESSION_CALENDAR_SCHEMA_REQUIRED")
        calendar = load_exchange_session_calendar(document)
        if calendar.exchange_id in calendars:
            raise RunnerError("SESSION_CALENDAR_DUPLICATE_EXCHANGE")
        calendars[calendar.exchange_id] = calendar
    return calendars


def load_market_plan(
    config: Mapping[str, Any], config_path: Path, *, bundle_path: Optional[Path] = None
):
    """Recompute contract selection and all-member UTC minute slots."""
    from backtrader.feeds.futures_selection_io import load_selection_bundle
    from backtrader.feeds.futures_sessions import build_common_minute_grid

    selection_path = (
        _resolve_path(config_path, config["selection"]["bundle"], "selection.bundle")
        if bundle_path is None
        else Path(bundle_path).expanduser().resolve(strict=False)
    )
    bundle = _read_json(selection_path, "selection.bundle")
    manifest = load_selection_bundle(bundle)
    if manifest.status != "READY":
        raise RunnerError("POINT_IN_TIME_SELECTION_BLOCKED", ",".join(manifest.blockers))
    route_pairs = manifest.selected_mapping()
    routes = dict(route_pairs)
    products = tuple(manifest.target_products)
    if set(routes) != set(products):
        raise RunnerError("POINT_IN_TIME_ROUTE_SET_MISMATCH")
    day_by_exchange = {row.exchange_id: row.current_trading_day for row in manifest.trading_days}
    if set(day_by_exchange) != {product.exchange_id for product in products}:
        raise RunnerError("POINT_IN_TIME_TRADING_DAY_SET_MISMATCH")
    session_calendars = _session_documents(bundle)
    if set(session_calendars) != {product.exchange_id for product in products}:
        raise RunnerError("SESSION_CALENDAR_SET_MISMATCH")
    product_days = {product: (day_by_exchange[product.exchange_id],) for product in products}
    grid = build_common_minute_grid(
        products,
        tuple(session_calendars.values()),
        product_days,
        decision_at=manifest.decision_at,
    )
    if grid.status != "READY" or not grid.minutes:
        raise RunnerError("PLANNED_MINUTE_GRID_BLOCKED", grid.status)
    authorized_values = config["selection"]["authorized_products"]
    if authorized_values is None:
        authorized = tuple(_target_id(product) for product in products)
    else:
        if type(authorized_values) is not list or not authorized_values:
            raise RunnerError("AUTHORIZED_PRODUCTS_INVALID")
        authorized = tuple(_text(item, "authorized product") for item in authorized_values)
        target_names = {_target_id(product) for product in products}
        if len(set(authorized)) != len(authorized) or not set(authorized).issubset(target_names):
            raise RunnerError("AUTHORIZED_PRODUCTS_OUTSIDE_POOL")
    return {
        "bundle": bundle,
        "manifest": manifest,
        "products": products,
        "routes": routes,
        "targets": tuple(_target_id(product) for product in products),
        "product_by_target": {_target_id(product): product for product in products},
        "target_by_product": {product: _target_id(product) for product in products},
        "authorized_targets": authorized,
        "session_calendars": session_calendars,
        "grid": grid,
        "selection_path": selection_path,
        "selection_source": "saved_bundle_legacy",
        "source_snapshot_id": manifest.source_snapshot_id,
    }


def build_ctp_query_market_plan(store, config, *, clock):
    """Select and calendarize the complete CTP futures universe on this Store.

    The snapshot bridge is deliberately called only after the caller has made
    this exact Store ready. It reads the existing client; it does not construct
    or connect another provider session. No catalog row is removed before the
    shared selector has checked classification and complete depth coverage.
    """

    from backtrader.feeds.futures_expected_calendar import (
        RULE_REVIEW_RETRIEVED_AT_UTC,
        build_expected_daytime_calendars,
    )
    from backtrader.feeds.futures_main_contract import (
        CTP_QUERY_SNAPSHOT_EQUAL_WEIGHT_POLICY,
        ExchangeTradingDay,
        ProductKey,
        select_main_contracts,
    )
    from backtrader.feeds.futures_sessions import build_common_minute_grid

    collector = getattr(store, "registered_sim_collect_futures_snapshot", None)
    if not callable(collector):
        raise RunnerError("CTP_FUTURES_SNAPSHOT_BRIDGE_UNAVAILABLE")
    selection = config.get("selection")
    query_mode = "legacy_two_query"
    if isinstance(selection, Mapping):
        query_mode = selection.get("query_mode", query_mode)
    if type(query_mode) is not str or query_mode not in {
        "legacy_two_query",
        "staged_product_set",
    }:
        raise RunnerError("SELECTION_QUERY_MODE_INVALID")
    if query_mode == "staged_product_set":
        collector_kwargs = {
            "max_collection_seconds": 300.0,
            "max_snapshot_age_seconds": 300.0,
            "query_mode": query_mode,
        }
    else:
        collector_kwargs = {
            "max_collection_seconds": 300.0,
            "max_snapshot_age_seconds": 300.0,
        }
    try:
        snapshot = collector(**collector_kwargs)
    except Exception as error:
        # Do not expose SDK exception text, provider payloads, or account data.
        from backtrader.feeds.futures_ctp_snapshot import CtpFuturesSnapshotError

        detail = "UNEXPECTED_COLLECTION_FAILURE"
        if type(error) is CtpFuturesSnapshotError:
            code = getattr(error, "code", None)
            if type(code) is str:
                numbered_instrument_failure = False
                prefix = "INSTRUMENTS_"
                suffix = "_QUERY_CALL_FAILED"
                if code.startswith(prefix) and code.endswith(suffix):
                    request_ordinal = code[len(prefix) : -len(suffix)]
                    numbered_instrument_failure = (
                        len(request_ordinal) == 3
                        and request_ordinal.isascii()
                        and request_ordinal.isdigit()
                        and 1 <= int(request_ordinal) <= 256
                    )
                if code in _CTP_FUTURES_SNAPSHOT_ERROR_CODES or numbered_instrument_failure:
                    detail = code
        runner_error = RunnerError("CTP_FUTURES_SNAPSHOT_COLLECTION_FAILED", detail)
        runner_error.query_diagnostics = _project_ctp_snapshot_query_diagnostics(error)
        raise runner_error from None

    from backtrader.feeds.futures_main_contract import MainContractQuerySnapshot

    if not isinstance(snapshot, MainContractQuerySnapshot):
        raise RunnerError("CTP_FUTURES_SNAPSHOT_TYPE_INVALID")
    if query_mode == "staged_product_set":
        query_set = snapshot.query_set
        if query_set is None:
            raise RunnerError("CTP_FUTURES_QUERY_SET_UNAVAILABLE")
        products = tuple(item.product for item in query_set.products)
    else:
        if snapshot.query_set is not None:
            raise RunnerError("CTP_FUTURES_QUERY_MODE_MISMATCH")
        products = tuple(
            sorted(
                {row.product for row in snapshot.catalog_records if row.product_class == "1"},
                key=lambda product: (product.exchange_id, product.product_id),
            )
        )
    if not products or any(not isinstance(product, ProductKey) for product in products):
        raise RunnerError("CTP_FUTURES_PRODUCT_POOL_UNAVAILABLE")
    trading_day = snapshot.session_trading_day_after
    if type(trading_day) is not date:
        raise RunnerError("CTP_FUTURES_TRADING_DAY_UNAVAILABLE")
    exchanges = tuple(sorted({product.exchange_id for product in products}))
    current_days = dict.fromkeys(exchanges, trading_day)
    day_rows = tuple(ExchangeTradingDay(exchange, trading_day) for exchange in exchanges)
    decision_at = _aware_datetime(clock.utc_now(), "CTP selection decision time")

    try:
        calendar_build = build_expected_daytime_calendars(
            products,
            current_days,
            as_of=decision_at,
            retrieved_at=RULE_REVIEW_RETRIEVED_AT_UTC,
        )
        manifest = select_main_contracts(
            snapshot,
            products,
            day_rows,
            calendar_build.trading_calendars,
            decision_at=decision_at,
            policy=CTP_QUERY_SNAPSHOT_EQUAL_WEIGHT_POLICY,
        )
        if manifest.status != "READY":
            raise RunnerError("POINT_IN_TIME_SELECTION_BLOCKED", ",".join(manifest.blockers))
        routes = dict(manifest.selected_mapping())
        selected_last_days = {}
        selected = dict(routes)
        for assessment in manifest.candidates:
            product = assessment.product
            if (
                product in selected
                and selected[product] == assessment.instrument_id
                and product.exchange_id == "CFFEX"
                and product.product_id in {"TF", "T", "TS", "TL"}
                and assessment.expiry_date is not None
            ):
                selected_last_days[product] = (assessment.expiry_date,)
        if selected_last_days:
            calendar_build = build_expected_daytime_calendars(
                products,
                current_days,
                as_of=decision_at,
                retrieved_at=RULE_REVIEW_RETRIEVED_AT_UTC,
                selected_contract_last_trading_days=selected_last_days,
            )
            manifest = select_main_contracts(
                snapshot,
                products,
                day_rows,
                calendar_build.trading_calendars,
                decision_at=decision_at,
                policy=CTP_QUERY_SNAPSHOT_EQUAL_WEIGHT_POLICY,
            )
            if manifest.status != "READY":
                raise RunnerError("POINT_IN_TIME_SELECTION_BLOCKED", ",".join(manifest.blockers))
            routes = dict(manifest.selected_mapping())
        product_days = dict.fromkeys(products, (trading_day,))
        grid = build_common_minute_grid(
            products,
            calendar_build.session_calendars,
            product_days,
            decision_at=decision_at,
        )
    except RunnerError:
        raise
    except Exception as error:
        code = getattr(error, "code", None)
        safe_code = code if type(code) is str and code.isascii() else type(error).__name__
        raise RunnerError("CTP_QUERY_PLAN_BUILD_FAILED", safe_code) from None
    if grid.status != "READY" or not grid.minutes:
        raise RunnerError("PLANNED_MINUTE_GRID_BLOCKED", grid.status)
    if set(routes) != set(products):
        raise RunnerError("POINT_IN_TIME_ROUTE_SET_MISMATCH")

    authorized_values = config["selection"]["authorized_products"]
    if authorized_values is None:
        authorized = tuple(_target_id(product) for product in products)
    else:
        if type(authorized_values) is not list or not authorized_values:
            raise RunnerError("AUTHORIZED_PRODUCTS_INVALID")
        authorized = tuple(_text(item, "authorized product") for item in authorized_values)
        target_names = {_target_id(product) for product in products}
        if len(set(authorized)) != len(authorized) or not set(authorized).issubset(target_names):
            raise RunnerError("AUTHORIZED_PRODUCTS_OUTSIDE_POOL")

    if query_mode == "staged_product_set":
        source_snapshot_id = snapshot.query_set.snapshot_id
        if type(source_snapshot_id) is not str or not source_snapshot_id:
            raise RunnerError("CTP_FUTURES_SNAPSHOT_ID_UNAVAILABLE")
        selection_path = f"ctp-query://{source_snapshot_id}"
    else:
        catalog_id = snapshot.catalog_source.snapshot_id
        quote_id = snapshot.quote_source.snapshot_id
        if type(catalog_id) is not str or type(quote_id) is not str:
            raise RunnerError("CTP_FUTURES_SNAPSHOT_ID_UNAVAILABLE")
        source_snapshot_id = f"{catalog_id}|{quote_id}"
        selection_path = f"ctp-query://{catalog_id}|{quote_id}"
    return {
        "bundle": None,
        "manifest": manifest,
        "products": products,
        "routes": routes,
        "targets": tuple(_target_id(product) for product in products),
        "product_by_target": {_target_id(product): product for product in products},
        "target_by_product": {product: _target_id(product) for product in products},
        "authorized_targets": authorized,
        "session_calendars": calendar_build.session_calendar_by_exchange,
        "grid": grid,
        "selection_path": selection_path,
        "selection_source": "ctp_query_snapshot_equal_weight_v1",
        "source_snapshot_id": source_snapshot_id,
        "calendar_evidence_mode": calendar_build.evidence_mode,
        "calendar_rules_sha256": calendar_build.rules_manifest_sha256,
    }


_CTP_QUERY_DIAGNOSTIC_CATEGORIES = frozenset(
    {
        "unavailable",
        "none",
        "timeout",
        "unsupported",
        "incomplete",
        "late_callbacks",
        "record_limit",
        "scope_mismatch",
        "submission_error",
        "query_error",
        "invalid",
    }
)
_CTP_QUERY_COMPLETION_ORIGINS = frozenset(
    {
        "unknown",
        "query_response",
        "response_error",
        "front_disconnected",
        "client_stop",
        "local_cancel",
        "submit_exception",
        "submit_rejected",
        "timeout",
        "deadline",
        "success",
        "record_limit",
        "local_preflight",
    }
)
_CTP_QUERY_SUBMIT_CATEGORIES = frozenset(
    {"unavailable", "not_observed", "accepted", "rejected", "invalid"}
)
_CTP_QUERY_DIAGNOSTIC_MAX_RECORDS = 20_000
_CTP_QUERY_UNAVAILABLE_CATEGORIES = frozenset(
    {
        "DIAGNOSTIC_CONTRACT_UNAVAILABLE",
        "ERROR_TYPE_UNTRUSTED",
        "NO_QUERY_OBSERVATION",
        "INVALID_DIAGNOSTICS",
    }
)
_CTP_QUERY_STAGE_FIELD_NAMES = (
    "stage",
    "entered",
    "returned",
    "elapsed_seconds",
    "prior_stage_complete",
    "result_type_matches",
    "request_type_matches",
    "generation_matches",
    "request_id_positive",
    "timed_out",
    "complete",
    "is_last_seen",
    "unsupported",
    "late_callbacks_reported",
    "late_callback_count_valid",
    "record_count",
    "record_count_capped",
    "submit_category",
    "error_code_present",
    "error_code_valid",
    "error_code_nonzero",
    "error_message_present",
    "error_message_valid",
    "error_category",
    "first_completion_origin",
    "completion_origin",
)
_CTP_QUERY_STAGED_STAGE_FIELD_NAMES = _CTP_QUERY_STAGE_FIELD_NAMES + (
    "requested_record_limit",
    "record_limit_observed",
    "record_limit_matches",
    "record_limit_exceeded",
    "request_filters_match",
)
_CTP_QUERY_STAGE_FIELDS = frozenset(_CTP_QUERY_STAGE_FIELD_NAMES)
_CTP_QUERY_STAGED_STAGE_FIELDS = frozenset(_CTP_QUERY_STAGED_STAGE_FIELD_NAMES)


def _sanitize_ctp_query_diagnostics(value):
    """Copy only the exact finite diagnostics schema into public output."""

    unavailable = {"status": "UNAVAILABLE", "category": "INVALID_DIAGNOSTICS"}
    if type(value) is not dict:
        return unavailable
    if value.get("status") == "UNAVAILABLE":
        if (
            set(value) == {"status", "category"}
            and type(value.get("category")) is str
            and value["category"] in _CTP_QUERY_UNAVAILABLE_CATEGORIES
        ):
            return dict(value)
        return unavailable
    if set(value) != {"status", "stages"} or value.get("status") != "AVAILABLE":
        return unavailable
    stages = value.get("stages")
    if type(stages) is not list or not 1 <= len(stages) <= 258:
        return unavailable
    if type(stages[0]) is not dict or type(stages[0].get("stage")) is not str:
        return unavailable
    staged_query_set = stages[0]["stage"] == "products"
    if not staged_query_set and len(stages) > 2:
        return unavailable
    product_count = stages[0].get("record_count") if staged_query_set else None
    if product_count is not None and (
        type(product_count) is not int
        or not 0 <= product_count <= _CTP_QUERY_DIAGNOSTIC_MAX_RECORDS
    ):
        return unavailable
    if (
        staged_query_set
        and product_count is not None
        and product_count > 256
        and len(stages) > 1
    ):
        return unavailable
    if staged_query_set and product_count is None and len(stages) > 1:
        return unavailable
    if staged_query_set and product_count == 0 and len(stages) > 1:
        return unavailable

    sanitized = []
    for index, stage in enumerate(stages):
        stage_fields = (
            _CTP_QUERY_STAGED_STAGE_FIELDS if staged_query_set else _CTP_QUERY_STAGE_FIELDS
        )
        if type(stage) is not dict or set(stage) != stage_fields:
            return unavailable
        if staged_query_set:
            if index == 0:
                expected_name = "products"
            elif index <= product_count:
                expected_name = "instruments_{:03d}".format(index)
            elif index == product_count + 1:
                expected_name = "depth"
            else:
                return unavailable
        else:
            expected_name = "catalog" if index == 0 else "depth"
        if staged_query_set:
            requested_limit = stage.get("requested_record_limit")
            if expected_name == "products":
                valid_limit = type(requested_limit) is int and requested_limit == 256
            elif expected_name == "depth":
                valid_limit = type(requested_limit) is int and requested_limit == 20_000
            else:
                valid_limit = (
                    type(requested_limit) is int and 1 <= requested_limit <= 20_000
                )
            if not valid_limit:
                return unavailable
        if (
            type(stage["stage"]) is not str
            or stage["stage"] != expected_name
            or stage["entered"] is not True
            or type(stage["returned"]) is not bool
            or type(stage["submit_category"]) is not str
            or stage["submit_category"] not in _CTP_QUERY_SUBMIT_CATEGORIES
            or type(stage["error_category"]) is not str
            or stage["error_category"] not in _CTP_QUERY_DIAGNOSTIC_CATEGORIES
            or type(stage["first_completion_origin"]) is not str
            or stage["first_completion_origin"] not in _CTP_QUERY_COMPLETION_ORIGINS
            or type(stage["completion_origin"]) is not str
            or stage["completion_origin"] not in _CTP_QUERY_COMPLETION_ORIGINS
        ):
            return unavailable
        if not staged_query_set and (
            stage["error_category"] in {"record_limit", "scope_mismatch"}
            or stage["first_completion_origin"] == "record_limit"
            or stage["completion_origin"] == "record_limit"
        ):
            return unavailable
        prior = stage["prior_stage_complete"]
        if index == 0:
            if prior is not None:
                return unavailable
        elif prior is not True:
            return unavailable
        elapsed = stage["elapsed_seconds"]
        if elapsed is not None and (
            type(elapsed) is not float or not math.isfinite(elapsed) or elapsed < 0
        ):
            return unavailable

        optional_booleans = (
            "result_type_matches",
            "request_type_matches",
            "generation_matches",
            "request_id_positive",
            "timed_out",
            "complete",
            "is_last_seen",
            "unsupported",
            "late_callbacks_reported",
            "late_callback_count_valid",
            "record_count_capped",
            "error_code_present",
            "error_code_valid",
            "error_code_nonzero",
            "error_message_present",
            "error_message_valid",
        )
        if staged_query_set:
            optional_booleans += (
                "record_limit_matches",
                "record_limit_exceeded",
                "request_filters_match",
            )
        if any(
            stage[name] is not None and type(stage[name]) is not bool
            for name in optional_booleans
        ):
            return unavailable
        if stage["returned"] is True:
            if type(stage["result_type_matches"]) is not bool:
                return unavailable
        elif stage["result_type_matches"] is not None:
            return unavailable
        if stage["result_type_matches"] is not True and (
            stage["first_completion_origin"] != "unknown"
            or stage["completion_origin"] != "unknown"
        ):
            return unavailable

        record_count = stage["record_count"]
        if record_count is not None and (
            type(record_count) is not int
            or not 0 <= record_count <= _CTP_QUERY_DIAGNOSTIC_MAX_RECORDS
        ):
            return unavailable
        if (record_count is None) != (stage["record_count_capped"] is None):
            return unavailable
        if stage["record_count_capped"] is True and record_count != (
            _CTP_QUERY_DIAGNOSTIC_MAX_RECORDS
        ):
            return unavailable

        requested_limit = stage.get("requested_record_limit")
        observed_limit = stage.get("record_limit_observed")
        if staged_query_set and requested_limit is None:
            return unavailable
        if requested_limit is None:
            if any(
                stage.get(name) is not None
                for name in (
                    "record_limit_observed",
                    "record_limit_matches",
                    "record_limit_exceeded",
                    "request_filters_match",
                )
            ):
                return unavailable
        elif type(requested_limit) is not int or not 1 <= requested_limit <= 100_000:
            return unavailable
        if observed_limit is not None and (
            type(observed_limit) is not int or not 1 <= observed_limit <= 100_000
        ):
            return unavailable

        if stage["result_type_matches"] is True:
            required_boolean_facts = (
                "request_type_matches",
                "generation_matches",
                "request_id_positive",
                "timed_out",
                "complete",
                "is_last_seen",
                "unsupported",
                "late_callbacks_reported",
                "late_callback_count_valid",
                "error_code_present",
                "error_code_valid",
                "error_code_nonzero",
                "error_message_present",
                "error_message_valid",
            )
            if (
                any(stage[name] is None for name in required_boolean_facts)
                or record_count is None
                or stage["submit_category"] in {"unavailable", "invalid"}
                or stage["error_category"] == "unavailable"
            ):
                return unavailable
            if requested_limit is not None:
                if (
                    type(observed_limit) is not int
                    or type(stage.get("record_limit_matches")) is not bool
                    or type(stage.get("record_limit_exceeded")) is not bool
                    or type(stage.get("request_filters_match")) is not bool
                    or stage.get("record_limit_matches")
                    is not (observed_limit == requested_limit)
                ):
                    return unavailable
                if stage["record_count_capped"] is True and stage.get(
                    "record_limit_exceeded"
                ) is not True:
                    return unavailable
                if record_count > requested_limit and stage.get(
                    "record_limit_exceeded"
                ) is not True:
                    return unavailable
            elif any(
                stage.get(name) is not None
                for name in (
                    "record_limit_observed",
                    "record_limit_matches",
                    "record_limit_exceeded",
                    "request_filters_match",
                )
            ):
                return unavailable
            if stage["error_code_valid"] is True:
                if type(stage["error_code_nonzero"]) is not bool:
                    return unavailable
            elif stage["error_code_nonzero"] is not None:
                return unavailable
            if (
                stage["error_code_present"] is False
                and stage["error_code_valid"] is False
            ) or (
                stage["error_code_nonzero"] is True
                and stage["error_code_present"] is not True
            ):
                return unavailable
            if stage["error_message_valid"] is True:
                if type(stage["error_message_present"]) is not bool:
                    return unavailable
            elif stage["error_message_present"] is not None:
                return unavailable

            invalid_facts = (
                stage["request_id_positive"] is False
                or stage["late_callback_count_valid"] is False
                or stage["error_code_valid"] is False
                or stage["error_message_valid"] is False
            )
            if invalid_facts:
                expected_error_category = "invalid"
            elif stage["timed_out"] is True:
                expected_error_category = "timeout"
            elif stage.get("record_limit_exceeded") is True or stage["completion_origin"] == (
                "record_limit"
            ):
                expected_error_category = "record_limit"
            elif stage.get("record_limit_matches") is False or stage.get(
                "request_filters_match"
            ) is False:
                expected_error_category = "scope_mismatch"
            elif stage["unsupported"] is True:
                expected_error_category = "unsupported"
            elif stage["error_code_nonzero"] is True:
                expected_error_category = "query_error"
            elif stage["submit_category"] == "rejected":
                expected_error_category = "submission_error"
            elif stage["error_message_present"] is True:
                expected_error_category = "query_error"
            elif stage["complete"] is False or stage["is_last_seen"] is False:
                expected_error_category = "incomplete"
            elif stage["late_callbacks_reported"] is True:
                expected_error_category = "late_callbacks"
            else:
                expected_error_category = "none"
            if stage["error_category"] != expected_error_category:
                return unavailable
        else:
            if (
                any(stage[name] is not None for name in optional_booleans)
                or record_count is not None
                or stage["submit_category"] != "unavailable"
                or stage["error_category"] != "unavailable"
            ):
                return unavailable

        sanitized.append(dict(stage))

    if len(sanitized) > 1:
        for prior_stage in sanitized[:-1]:
            if not (
                prior_stage["returned"] is True
                and prior_stage["result_type_matches"] is True
                and prior_stage["request_type_matches"] is True
                and prior_stage["generation_matches"] is True
                and prior_stage["request_id_positive"] is True
                and prior_stage["timed_out"] is False
                and prior_stage["unsupported"] is False
                and prior_stage["complete"] is True
                and prior_stage["is_last_seen"] is True
                and prior_stage["late_callbacks_reported"] is False
                and prior_stage["late_callback_count_valid"] is True
                and prior_stage["record_count"] is not None
                and prior_stage["submit_category"] in {"accepted", "not_observed"}
                and prior_stage["error_category"] == "none"
                and prior_stage["error_code_valid"] is True
                and prior_stage["error_message_valid"] is True
                and prior_stage["error_message_present"] is False
            ):
                return unavailable
    return {"status": "AVAILABLE", "stages": sanitized}


def _project_ctp_snapshot_query_diagnostics(error):
    """Whitelist exact collector DTOs, then apply the shared strict sanitizer."""

    def unavailable(category):
        return {"status": "UNAVAILABLE", "category": category}

    try:
        from backtrader.feeds.futures_ctp_snapshot import (
            CtpFuturesSnapshotError,
            CtpFuturesSnapshotQueryObservation,
        )
    except ImportError:
        return unavailable("DIAGNOSTIC_CONTRACT_UNAVAILABLE")
    if type(error) is not CtpFuturesSnapshotError:
        return unavailable("ERROR_TYPE_UNTRUSTED")
    observations = getattr(error, "query_observations", None)
    if type(observations) is not tuple or not observations:
        return unavailable("NO_QUERY_OBSERVATION")
    staged_query_set = (
        type(observations[0]) is CtpFuturesSnapshotQueryObservation
        and getattr(observations[0], "stage", None) == "products"
    )
    max_observations = 258 if staged_query_set else 2
    if len(observations) > max_observations or any(
        type(item) is not CtpFuturesSnapshotQueryObservation for item in observations
    ):
        return unavailable("INVALID_DIAGNOSTICS")
    field_names = (
        _CTP_QUERY_STAGED_STAGE_FIELD_NAMES
        if staged_query_set
        else _CTP_QUERY_STAGE_FIELD_NAMES
    )
    try:
        stages = [
            {name: getattr(observation, name) for name in field_names}
            for observation in observations
        ]
    except Exception:
        return unavailable("INVALID_DIAGNOSTICS")
    return _sanitize_ctp_query_diagnostics({"status": "AVAILABLE", "stages": stages})


def _apply_golden_target_subset(plan, requested_targets):
    """Project a read-only subset only after the complete CTP plan is READY."""

    if requested_targets is None:
        return plan
    manifest = plan.get("manifest") if isinstance(plan, Mapping) else None
    if (
        plan.get("selection_source") != "ctp_query_snapshot_equal_weight_v1"
        or getattr(manifest, "status", None) != "READY"
    ):
        raise RunnerError("GOLDEN_TARGETS_FULL_SELECTION_NOT_READY")
    try:
        full_products = tuple(plan["products"])
        full_routes = dict(plan["routes"])
        full_targets = tuple(plan["targets"])
        product_by_target = dict(plan["product_by_target"])
        target_by_product = dict(plan["target_by_product"])
        full_authorized_targets = tuple(plan["authorized_targets"])
        full_grid = plan["grid"]
        route_rows = dict(manifest.selected_mapping())
    except Exception as error:
        raise RunnerError("GOLDEN_TARGETS_FULL_SELECTION_INVALID", type(error).__name__) from None
    expected_targets = tuple(_target_id(product) for product in full_products)
    if (
        not full_products
        or len(set(full_products)) != len(full_products)
        or full_targets != expected_targets
        or set(product_by_target) != set(full_targets)
        or any(
            product_by_target[target] != product
            for target, product in zip(full_targets, full_products)
        )
        or target_by_product
        != {product: target for product, target in zip(full_products, full_targets)}
        or set(full_routes) != set(full_products)
        or full_routes != route_rows
        or set(getattr(manifest, "target_products", ())) != set(full_products)
        or getattr(full_grid, "status", None) != "READY"
        or not getattr(full_grid, "minutes", ())
        or set(getattr(full_grid, "target_products", ())) != set(full_products)
        or len(full_authorized_targets) != len(set(full_authorized_targets))
        or not set(full_authorized_targets).issubset(set(full_targets))
    ):
        raise RunnerError("GOLDEN_TARGETS_FULL_SELECTION_INVALID")
    requested = set(requested_targets)
    unknown = requested.difference(full_targets)
    if unknown:
        raise RunnerError("GOLDEN_TARGETS_OUTSIDE_SELECTED_POOL")
    active_targets = tuple(target for target in full_targets if target in requested)
    active_products = tuple(product_by_target[target] for target in active_targets)
    if not active_products:
        raise RunnerError("GOLDEN_TARGETS_EMPTY")
    try:
        from backtrader.feeds.futures_sessions import build_common_minute_grid

        product_days = dict(full_grid.product_trading_days)
        if set(product_days) != set(full_products):
            raise ValueError("full grid TradingDay map differs from full selection")
        calendars = plan["session_calendars"]
        if not isinstance(calendars, Mapping):
            raise ValueError("session calendars are unavailable")
        active_grid = build_common_minute_grid(
            active_products,
            tuple(calendars.values()),
            {product: product_days[product] for product in active_products},
            decision_at=full_grid.decision_at,
        )
    except Exception as error:
        raise RunnerError("GOLDEN_TARGETS_GRID_BUILD_FAILED", type(error).__name__) from None
    if active_grid.status != "READY" or not active_grid.minutes:
        raise RunnerError("GOLDEN_TARGETS_GRID_UNAVAILABLE", active_grid.status)

    active_routes = {product: full_routes[product] for product in active_products}
    active_product_by_target = {
        target: product_by_target[target] for target in active_targets
    }
    active_target_set = set(active_targets)
    active_authorized_targets = tuple(
        target for target in full_authorized_targets if target in active_target_set
    )
    projected = dict(plan)
    projected.update(
        {
            "full_products": full_products,
            "full_routes": full_routes,
            "full_selected_targets": full_targets,
            "full_product_by_target": product_by_target,
            "full_target_by_product": target_by_product,
            "full_authorized_targets": full_authorized_targets,
            "full_grid": full_grid,
            "active_shadow_targets": active_targets,
            "golden_targets": active_targets,
            "products": active_products,
            "routes": active_routes,
            "targets": active_targets,
            "product_by_target": active_product_by_target,
            "target_by_product": {
                product: target for target, product in active_product_by_target.items()
            },
            "authorized_targets": active_authorized_targets,
            "grid": active_grid,
        }
    )
    return projected


def _minute_slot_index(grid: Any):
    from backtrader.feeds.futures_sessions import PlannedCommonMinute

    index = {}
    for minute in grid.minutes:
        if not isinstance(minute, PlannedCommonMinute):
            raise RunnerError("PLANNED_GRID_RECORD_INVALID")
        if minute.close_time in index:
            raise RunnerError("PLANNED_GRID_DUPLICATE_CLOSE")
        index[minute.close_time] = minute
    return index


def load_minute_tape(path: Path, plan: Mapping[str, Any], cohort_config: Mapping[str, Any]):
    """Validate immutable saved minute events against the complete planned grid."""
    document = _read_json(path, "minute_tape")
    required = {"schema", "snapshot_id", "source_ref", "source_timezone", "price_basis", "bars"}
    if set(document).difference(required) or required.difference(document):
        raise RunnerError("MINUTE_TAPE_FIELDS_INVALID")
    if document["schema"] != MINUTE_TAPE_SCHEMA:
        raise RunnerError("MINUTE_TAPE_SCHEMA_UNSUPPORTED")
    snapshot_id = _text(document["snapshot_id"], "minute tape snapshot_id")
    source_ref = _text(document["source_ref"], "minute tape source_ref")
    source_timezone = _text(document["source_timezone"], "minute tape source_timezone")
    price_basis = _text(document["price_basis"], "minute tape price_basis")
    if price_basis.lower() in {"default", "unknown", "unspecified"}:
        raise RunnerError("MINUTE_TAPE_PRICE_BASIS_UNSPECIFIED")
    configured_tz = plan.get("source_timezone")
    if configured_tz and configured_tz != source_timezone:
        raise RunnerError("MINUTE_TAPE_TIMEZONE_MISMATCH")
    configured_basis = plan.get("price_basis")
    if configured_basis and configured_basis != price_basis:
        raise RunnerError("MINUTE_TAPE_PRICE_BASIS_MISMATCH")
    clock_domain_id = _text(cohort_config["clock_domain_id"], "clock_domain_id")
    timezone_id = _text(cohort_config["timezone_id"], "timezone_id")
    raw_bars = document["bars"]
    if type(raw_bars) is not list or not raw_bars:
        raise RunnerError("MINUTE_TAPE_BARS_REQUIRED")
    planned = _minute_slot_index(plan["grid"])
    expected_targets = set(plan["targets"])
    route_by_target = {
        _target_id(product): (instrument, product.exchange_id)
        for product, instrument in plan["routes"].items()
    }
    sequences = {}
    seen_bar_ids = set()
    events = defaultdict(dict)
    for ordinal, raw in enumerate(raw_bars):
        row = _mapping(raw, f"bars[{ordinal}]")
        expected_keys = {
            "target",
            "instrument",
            "exchange",
            "bucket_start",
            "bucket_end",
            "available_at",
            "trading_day",
            "session_segment",
            "timezone_id",
            "clock_domain_id",
            "connection_generation",
            "bar_sequence",
            "bar_id",
            "timestamp",
            "present",
            "complete",
            "quality",
            "quality_flags",
            *OHLCV_FIELDS,
        }
        if set(row) != expected_keys:
            raise RunnerError("MINUTE_BAR_FIELDS_INVALID", str(ordinal))
        target = _text(row["target"], f"bars[{ordinal}].target")
        if target not in expected_targets:
            raise RunnerError("MINUTE_BAR_TARGET_OUTSIDE_POOL", target)
        instrument, exchange = route_by_target[target]
        if row["instrument"] != instrument or row["exchange"] != exchange:
            raise RunnerError("MINUTE_BAR_ROUTE_MISMATCH", target)
        start = _aware_datetime(row["bucket_start"], "bucket_start")
        end = _aware_datetime(row["bucket_end"], "bucket_end")
        available = _aware_datetime(row["available_at"], "available_at")
        if end <= start or end - start != timedelta(minutes=1) or available < end:
            raise RunnerError("MINUTE_BAR_AVAILABILITY_INVALID", target)
        slot = planned.get(end)
        if slot is None or start != end - timedelta(minutes=1):
            raise RunnerError("MINUTE_BAR_OUTSIDE_PLANNED_GRID", target)
        member_by_product = {member.product: member for member in slot.members}
        member = member_by_product.get(plan["product_by_target"][target])
        if member is None:
            raise RunnerError("MINUTE_BAR_PLANNED_MEMBER_MISSING", target)
        trading_day = _iso_date(row["trading_day"], "trading_day").isoformat()
        if (
            trading_day != member.trading_day.isoformat()
            or row["session_segment"] != member.session_id
        ):
            raise RunnerError("MINUTE_BAR_SESSION_MISMATCH", target)
        if row["timezone_id"] != timezone_id or row["clock_domain_id"] != clock_domain_id:
            raise RunnerError("MINUTE_BAR_CLOCK_PROFILE_MISMATCH", target)
        generation = row["connection_generation"]
        if type(generation) not in (str, int) or generation in ("", 0):
            raise RunnerError("MINUTE_BAR_GENERATION_INVALID", target)
        sequence = row["bar_sequence"]
        if type(sequence) is not int or sequence <= 0:
            raise RunnerError("MINUTE_BAR_SEQUENCE_INVALID", target)
        key = (target, generation)
        if sequence <= sequences.get(key, 0):
            raise RunnerError("MINUTE_BAR_SEQUENCE_NOT_INCREASING", target)
        sequences[key] = sequence
        bar_id = _text(row["bar_id"], "bar_id")
        if (target, bar_id) in seen_bar_ids:
            raise RunnerError("MINUTE_BAR_ID_DUPLICATE", target)
        seen_bar_ids.add((target, bar_id))
        if type(row["present"]) is not bool or row["present"] is not True:
            raise RunnerError("MINUTE_BAR_NOT_PRESENT", target)
        if type(row["complete"]) is not bool or row["complete"] is not True:
            raise RunnerError("MINUTE_BAR_INCOMPLETE", target)
        if row["quality"] != "GOOD" or row["quality_flags"] != []:
            raise RunnerError("MINUTE_BAR_QUALITY_BLOCKED", target)
        values = {
            name: _number(
                row[name], f"{name}[{ordinal}]", nonnegative=name in {"volume", "openinterest"}
            )
            for name in OHLCV_FIELDS
        }
        if values["open"] <= 0 or values["high"] <= 0 or values["low"] <= 0 or values["close"] <= 0:
            raise RunnerError("MINUTE_BAR_PRICE_INVALID", target)
        if (
            values["low"] > min(values["open"], values["close"])
            or values["high"] < max(values["open"], values["close"])
            or values["low"] > values["high"]
        ):
            raise RunnerError("MINUTE_BAR_OHLC_INVALID", target)
        timestamp = _number(row["timestamp"], "bar timestamp", positive=True)
        if abs(timestamp - end.timestamp()) > 1e-6:
            raise RunnerError("MINUTE_BAR_TIMESTAMP_MISMATCH", target)
        event = dict(row)
        event.update(
            {
                "instrument": instrument,
                "symbol": instrument,
                "datetime": end.isoformat(),
                "timestamp": timestamp,
                "bucket_start": start,
                "bucket_end": end,
                "available_at": available,
                "trading_day": trading_day,
                "source": "saved-minute-tape",
                "source_snapshot_id": snapshot_id,
                "source_ref": source_ref,
                # The cohort freezes source envelopes; retain the validated
                # empty marker as a tuple rather than the mutable JSON list.
                "quality_flags": (),
            }
        )
        events[target][end] = MappingProxyType(event)
    for target, by_close in events.items():
        if tuple(sorted(by_close)) != tuple(by_close):
            # JSON order is source order; do not silently sort a malformed tape.
            raise RunnerError("MINUTE_TAPE_SOURCE_ORDER_INVALID", target)
    return {
        "snapshot_id": snapshot_id,
        "source_ref": source_ref,
        "source_timezone": source_timezone,
        "price_basis": price_basis,
        "clock_domain_id": clock_domain_id,
        "timezone_id": timezone_id,
        "events": {target: tuple(rows.values()) for target, rows in events.items()},
    }


def _require_grid_endpoints(config: Mapping[str, Any], grid: Any):
    start = config["research"]["start"]
    end = config["research"]["end"]
    if start is None or end is None:
        raise RunnerError("RESEARCH_ENDPOINTS_REQUIRED")
    start_utc = _aware_datetime(start, "research.start")
    end_utc = _aware_datetime(end, "research.end")
    closes = {minute.close_time for minute in grid.minutes}
    if start_utc not in closes or end_utc not in closes or start_utc > end_utc:
        raise RunnerError("RESEARCH_ENDPOINTS_OUTSIDE_PLANNED_GRID")
    return start_utc, end_utc


def _factor_parameters(config: Mapping[str, Any], cli_factor_mode: Optional[str]):
    factor = config["factor"]
    mode = cli_factor_mode or factor["mode"] or "native"
    if mode not in ("native", "build"):
        raise RunnerError("FACTOR_MODE_INVALID")
    direction = factor["direction"]
    if type(direction) is not int or direction not in (-1, 1):
        raise RunnerError("FACTOR_DIRECTION_INVALID")
    preheat = factor["preheat_bars"]
    cadence = factor["rebalance_every"]
    if type(preheat) is not int or preheat < 1 or type(cadence) is not int or cadence < 1:
        raise RunnerError("FACTOR_WINDOW_INVALID")
    return mode, direction, preheat, cadence


def _make_research_spec(
    config: Mapping[str, Any], plan: Mapping[str, Any], tape: Mapping[str, Any]
):
    import pandas as pd
    from backtrader.research.specs import ResearchSpec

    start, end = _require_grid_endpoints(config, plan["grid"])
    times = [minute.close_time for minute in plan["grid"].minutes]
    frame = pd.DataFrame(
        {"open_time": [close - timedelta(minutes=1) for close in times]},
        index=pd.DatetimeIndex(times, name="close_time"),
    )
    return ResearchSpec(
        grid=frame,
        start=start,
        end=end,
        targets=plan["targets"],
        source_timezone=tape["source_timezone"],
        snapshot_id=tape["snapshot_id"],
        price_basis=tape["price_basis"],
        calendar_id=config["cohort"]["calendar_id"],
        frequency="1min",
    )


def run_research(
    config: Mapping[str, Any], config_path: Path, plan: Mapping[str, Any], mode: str, direction: int
):
    import backtrader as bt
    import pandas as pd
    from backtrader.research import FactorStrategy, align_to_grid
    from alpha003_strategy import make_alpha003_factor_spec

    input_path = _resolve_path(config_path, config["inputs"]["minute_tape"], "inputs.minute_tape")
    tape = load_minute_tape(input_path, plan, config["cohort"])
    research = _make_research_spec(config, plan, tape)
    cerebro = bt.Cerebro(stdstats=False)
    for target in plan["targets"]:
        rows = tape["events"].get(target, ())
        source = pd.DataFrame(
            [
                {
                    field: _number(
                        event[field], field, nonnegative=field in {"volume", "openinterest"}
                    )
                    for field in OHLCV_FIELDS
                }
                for event in rows
            ],
            index=pd.DatetimeIndex([event["bucket_end"] for event in rows], name="close_time"),
        )
        aligned = align_to_grid(source, research, target, data_version=tape["snapshot_id"])
        cerebro.adddata(aligned.feed, name=target)
    spec = make_alpha003_factor_spec(mode=mode, direction=direction)
    cerebro.addstrategy(FactorStrategy, research=research, factors={spec.name: spec})
    strategies = cerebro.run()
    strategy = strategies[0]
    panel = strategy.get_panel()
    output_dir = _resolve_path(config_path, config["output"]["directory"], "output.directory")
    output_path = panel.to_csv(output_dir)
    summary: dict[str, Any] = {
        "status": "RESEARCH_COMPLETE",
        "mode": "research",
        "factor_mode": mode,
        "direction": direction,
        "snapshot_id": tape["snapshot_id"],
        "grid_sha256": research.grid_sha256,
        "target_count": len(plan["targets"]),
        "grid_count": len(research.grid),
        "output_directory": str(output_path),
    }
    if config["output"]["evaluate_with_fincore"] is True:
        evaluation = strategy.evaluate()
        summary["evaluation_status"] = getattr(evaluation, "status", None)
    elif config["output"]["evaluate_with_fincore"] is not False:
        raise RunnerError("FINCORE_FLAG_INVALID")
    return summary


def _member_session_api():
    import backtrader.research.live_cohort as cohort_module

    slot_parameters = inspect.signature(cohort_module.LiveCalendarSlot).parameters
    session_cls = getattr(cohort_module, "LiveCalendarMemberSession", None)
    return cohort_module, slot_parameters, session_cls


def _calendar_slots(
    grid: Any,
    *,
    begin_at: Optional[datetime] = None,
    ctp_trading_days: bool = False,
):
    if type(ctp_trading_days) is not bool:
        raise RunnerError("COHORT_CTP_TRADING_DAY_OPTION_INVALID")

    def calendar_day(value):
        if type(value) is not date:
            raise RunnerError("COHORT_TRADING_DAY_INVALID")
        return value.strftime("%Y%m%d") if ctp_trading_days else value.isoformat()

    cohort_module, slot_parameters, member_session_cls = _member_session_api()
    slots = []
    for minute in _remaining_live_grid_minutes(grid, begin_at):
        start = minute.close_time - timedelta(minutes=1)
        members = {
            f"{item.product.exchange_id}.{item.product.product_id}": item for item in minute.members
        }
        session_pairs = {(calendar_day(item.trading_day), item.session_id) for item in minute.members}
        member_sessions = None
        if len(session_pairs) > 1:
            if "member_sessions" not in slot_parameters or member_session_cls is None:
                raise RunnerError("COHORT_MEMBER_SESSION_API_REQUIRED")
            member_sessions = {
                target: member_session_cls(
                    trading_day=calendar_day(member.trading_day),
                    session_segment=member.session_id,
                )
                for target, member in members.items()
            }
        elif "member_sessions" in slot_parameters and member_session_cls is not None:
            member_sessions = {
                target: member_session_cls(
                    trading_day=calendar_day(member.trading_day),
                    session_segment=member.session_id,
                )
                for target, member in members.items()
            }
        trading_day, session_segment = next(iter(session_pairs))
        kwargs = {
            "slot_id": f"minute:{minute.close_time.isoformat()}",
            "bucket_start": start,
            "close_time": minute.close_time,
            "trading_day": trading_day,
            "session_segment": session_segment,
        }
        if member_sessions is not None:
            kwargs["member_sessions"] = MappingProxyType(member_sessions)
        slots.append(cohort_module.LiveCalendarSlot(**kwargs))
    if not slots:
        raise RunnerError("COHORT_HAS_NO_PLANNED_SLOTS")
    return tuple(slots)


def _remaining_live_grid_minutes(grid: Any, begin_at: Optional[datetime]):
    """Return planned minutes whose bucket start is not before live startup."""

    from backtrader.feeds.futures_sessions import PlannedCommonMinute

    remaining = []
    for minute in grid.minutes:
        if not isinstance(minute, PlannedCommonMinute):
            raise RunnerError("PLANNED_GRID_RECORD_INVALID")
        start = minute.close_time - timedelta(minutes=1)
        if begin_at is not None and start < begin_at:
            continue
        remaining.append(minute)
    return tuple(remaining)


def _make_live_calendar(
    config: Mapping[str, Any],
    grid: Any,
    *,
    begin_at: Optional[datetime] = None,
    ctp_trading_days: bool = False,
):
    from backtrader.research.live_cohort import LiveCohortCalendar

    cohort_cfg = config["cohort"]
    if type(cohort_cfg["epoch_id"]) is not int or cohort_cfg["epoch_id"] < 1:
        raise RunnerError("COHORT_EPOCH_INVALID")
    return LiveCohortCalendar(
        calendar_id=_text(cohort_cfg["calendar_id"], "calendar_id"),
        version=_text(cohort_cfg["calendar_version"], "calendar_version"),
        epoch_id=cohort_cfg["epoch_id"],
        frequency="1min",
        frequency_seconds=60,
        timezone_id=_text(cohort_cfg["timezone_id"], "timezone_id"),
        clock_domain_id=_text(cohort_cfg["clock_domain_id"], "clock_domain_id"),
        session_semantics=_text(cohort_cfg["session_semantics"], "session_semantics"),
        slots=_calendar_slots(grid, begin_at=begin_at, ctp_trading_days=ctp_trading_days),
    )


def _make_cohort(
    config: Mapping[str, Any],
    grid: Any,
    *,
    begin_at: Optional[datetime] = None,
    ctp_trading_days: bool = False,
    calendar_override: Any = None,
):
    from backtrader.research.live_cohort import LiveBarCohort, LiveCohortCalendar

    cohort_cfg = config["cohort"]
    wait_seconds = _number(
        cohort_cfg["wait_timeout_seconds"], "wait_timeout_seconds", positive=True
    )
    if calendar_override is None:
        calendar = _make_live_calendar(
            config, grid, begin_at=begin_at, ctp_trading_days=ctp_trading_days
        )
    elif type(calendar_override) is not LiveCohortCalendar:
        raise RunnerError("COHORT_CALENDAR_OVERRIDE_INVALID")
    else:
        calendar = calendar_override
        if (
            calendar.calendar_id != cohort_cfg["calendar_id"]
            or calendar.version != cohort_cfg["calendar_version"]
            or calendar.epoch_id != cohort_cfg["epoch_id"]
        ):
            raise RunnerError("COHORT_CALENDAR_OVERRIDE_IDENTITY_INVALID")
    kwargs: dict[str, Any] = {
        "max_pending_slots": cohort_cfg["max_pending_slots"],
        "max_window_bars": cohort_cfg["max_window_bars"],
        "wait_timeout_ns": int(wait_seconds * 1_000_000_000),
    }
    return LiveBarCohort(
        cohort_id=f"alpha003:{cohort_cfg['calendar_id']}:{cohort_cfg['epoch_id']}",
        calendar=calendar,
        **kwargs,
    )


def _risk_policy(config: Mapping[str, Any]):
    from alpha003_strategy import Alpha003RiskPolicy

    raw = config["risk"]
    optional_fields = {"round_trip_fee_upper_bound_per_contract"}
    if raw["policy_id"] is None or any(
        raw[key] is None for key in RISK_FIELDS if key not in optional_fields
    ):
        return None
    values = {"risk_policy_id": _text(raw["policy_id"], "risk.policy_id")}
    for name in RISK_FIELDS:
        value = raw[name]
        if name in {"run_end_policy"}:
            values[name] = _text(value, f"risk.{name}")
        elif name in {
            "quote_max_age_seconds",
            "max_state_age_seconds",
            "max_notional_per_position",
            "max_total_notional",
            "max_margin_per_position",
            "max_total_margin",
            "max_loss_per_position",
            "max_total_loss",
        }:
            values[name] = _decimal(value, f"risk.{name}", positive=True)
        elif name == "round_trip_fee_upper_bound_per_contract":
            values[name] = None if value is None else _decimal(value, f"risk.{name}")
            if values[name] is not None and values[name] < 0:
                raise RunnerError("RISK_POLICY_INVALID", name)
        else:
            if type(value) is not int:
                raise RunnerError("RISK_POLICY_INVALID", name)
            values[name] = value
    try:
        return Alpha003RiskPolicy(**values)
    except (TypeError, ValueError):
        raise RunnerError("RISK_POLICY_INVALID") from None


def _commission_identity_by_target(
    config: Mapping[str, Any], authorized_target_ids: Tuple[str, ...]
) -> dict[str, dict[str, str]]:
    """Return only exact non-credential account/unit mappings for live targets.

    Invalid optional entries are omitted and therefore block OPEN through the
    fee projection.  They must not make refresh startup or safe reductions
    fail.  In particular, an empty investment-unit value is an explicit
    operator mapping consumed only by the fee sidecar.
    """

    raw = config.get("live", {}).get("commission_identity_by_target")
    if not isinstance(raw, Mapping):
        return {}
    allowed = set(authorized_target_ids)
    result = {}
    for target_id, identity in raw.items():
        if type(target_id) is not str or target_id not in allowed or not isinstance(identity, Mapping):
            continue
        if set(identity) != {"account_id", "invest_unit_id"}:
            continue
        account_id = identity.get("account_id")
        invest_unit_id = identity.get("invest_unit_id")
        if (
            type(account_id) is not str
            or not account_id
            or account_id != account_id.strip()
            or type(invest_unit_id) is not str
            or invest_unit_id != invest_unit_id.strip()
        ):
            continue
        result[target_id] = {
            "account_id": account_id,
            "invest_unit_id": invest_unit_id,
        }
    return result


def _run_loss_guard_policy(config: Mapping[str, Any], *, write_enabled: bool):
    """Require the separate run-level CNY loss policy only for live writes."""
    if type(write_enabled) is not bool:
        raise RunnerError("LIVE_RUN_LOSS_POLICY_INVALID")
    if not write_enabled:
        return None, None
    live = config["live"]
    raw_threshold = live.get("loss_guard_net_loss_threshold")
    raw_age = live.get("loss_guard_max_observation_age_seconds")
    if raw_threshold is None or raw_age is None:
        raise RunnerError("LIVE_RUN_LOSS_POLICY_REQUIRED")
    try:
        threshold = _decimal(
            raw_threshold,
            "live.loss_guard_net_loss_threshold",
            positive=True,
        )
    except RunnerError:
        raise RunnerError("LIVE_RUN_LOSS_POLICY_INVALID") from None
    parts = threshold.as_tuple()
    if (
        len(parts.digits) > 256
        or abs(parts.exponent) > 1000
        or abs(threshold.adjusted()) > 1000
    ):
        raise RunnerError("LIVE_RUN_LOSS_POLICY_INVALID")
    if type(raw_age) is not int or not 1 <= raw_age <= 86_400:
        raise RunnerError("LIVE_RUN_LOSS_POLICY_INVALID")
    return threshold, raw_age


def _require_replay_budgets(config: Mapping[str, Any]):
    policy = _risk_policy(config)
    if policy is None:
        raise RunnerError("REPLAY_RISK_BUDGETS_REQUIRED")
    replay = config["replay"]
    cash = _number(replay["starting_cash"], "replay.starting_cash", positive=True)
    commission = _number(replay["commission"], "replay.commission", nonnegative=True)
    return policy, cash, commission


def _quote_tape(path: Path, plan: Mapping[str, Any], cohort_config: Mapping[str, Any]):
    from alpha003_strategy import Alpha003ReplayQuoteFact

    document = _read_json(path, "execution_quotes")
    if set(document) != {"schema", "snapshot_id", "source_ref", "quotes"}:
        raise RunnerError("QUOTE_TAPE_FIELDS_INVALID")
    if document["schema"] != QUOTE_TAPE_SCHEMA:
        raise RunnerError("QUOTE_TAPE_SCHEMA_UNSUPPORTED")
    snapshot_id = _text(document["snapshot_id"], "quote snapshot_id")
    root_source = _text(document["source_ref"], "quote source_ref")
    rows = document["quotes"]
    if type(rows) is not list or not rows:
        raise RunnerError("QUOTE_TAPE_ROWS_REQUIRED")
    route_by_target = {
        _target_id(product): (instrument, product.exchange_id)
        for product, instrument in plan["routes"].items()
    }
    quote_facts = []
    seen = set()
    for ordinal, raw in enumerate(rows):
        row = _mapping(raw, f"quotes[{ordinal}]")
        expected = {
            "target",
            "instrument",
            "exchange",
            "event_time",
            "available_at",
            "bid",
            "ask",
            "source_ref",
            "quote_id",
        }
        if set(row) != expected:
            raise RunnerError("QUOTE_FIELDS_INVALID", str(ordinal))
        target = _text(row["target"], "quote target")
        if (
            target not in route_by_target
            or (row["instrument"], row["exchange"]) != route_by_target[target]
        ):
            raise RunnerError("QUOTE_ROUTE_MISMATCH", target)
        event_time = _aware_datetime(row["event_time"], "quote event_time")
        available_at = _aware_datetime(row["available_at"], "quote available_at")
        if available_at < event_time:
            raise RunnerError("QUOTE_AVAILABILITY_INVALID", target)
        bid = _decimal(row["bid"], "quote bid", positive=True)
        ask = _decimal(row["ask"], "quote ask", positive=True)
        if bid > ask:
            raise RunnerError("QUOTE_CROSSED", target)
        quote_id = _text(row["quote_id"], "quote_id")
        if quote_id in seen:
            raise RunnerError("QUOTE_ID_DUPLICATE", quote_id)
        seen.add(quote_id)
        quote_facts.append(
            Alpha003ReplayQuoteFact(
                instrument=row["instrument"],
                exchange=row["exchange"],
                event_time=event_time,
                available_at=available_at,
                bid=bid,
                ask=ask,
                source_ref=_text(row["source_ref"] or root_source, "quote source_ref"),
                quote_id=quote_id,
            )
        )
    return snapshot_id, tuple(quote_facts)


def _replay_instruments(path: Path, plan: Mapping[str, Any]):
    document = _read_json(path, "instrument_metadata")
    if set(document) != {"schema", "snapshot_id", "available_at", "instruments"}:
        raise RunnerError("REPLAY_METADATA_FIELDS_INVALID")
    if document["schema"] != METADATA_SCHEMA:
        raise RunnerError("REPLAY_METADATA_SCHEMA_UNSUPPORTED")
    snapshot = _text(document["snapshot_id"], "metadata snapshot_id")
    available_at = _aware_datetime(document["available_at"], "metadata available_at")
    rows = document["instruments"]
    if type(rows) is not list:
        raise RunnerError("REPLAY_METADATA_ROWS_INVALID")
    fields = {
        "target",
        "instrument",
        "exchange",
        "snapshot_id",
        "available_at",
        "trading_permitted",
        "multiplier",
        "long_margin_per_hand",
        "short_margin_per_hand",
        "tick_size",
        "lower_limit",
        "upper_limit",
    }
    route_by_target = {
        _target_id(product): (instrument, product.exchange_id)
        for product, instrument in plan["routes"].items()
    }
    metadata = {}
    for ordinal, raw in enumerate(rows):
        row = _mapping(raw, f"instruments[{ordinal}]")
        if set(row) != fields:
            raise RunnerError("REPLAY_INSTRUMENT_FIELDS_INVALID", str(ordinal))
        target = _text(row["target"], "metadata target")
        if (
            target not in route_by_target
            or (row["instrument"], row["exchange"]) != route_by_target[target]
        ):
            raise RunnerError("REPLAY_METADATA_ROUTE_MISMATCH", target)
        if type(row["trading_permitted"]) is not bool:
            raise RunnerError("REPLAY_PERMISSION_INVALID", target)
        local_available = _aware_datetime(row["available_at"], "instrument available_at")
        if local_available != available_at:
            raise RunnerError("REPLAY_METADATA_AVAILABILITY_MISMATCH", target)
        metadata[target] = {
            "instrument": row["instrument"],
            "exchange": row["exchange"],
            "snapshot_id": _text(row["snapshot_id"], "instrument snapshot_id") or snapshot,
            "available_at": local_available,
            "trading_permitted": row["trading_permitted"],
            "multiplier": _decimal(row["multiplier"], "multiplier", positive=True),
            "long_margin_per_hand": _decimal(
                row["long_margin_per_hand"], "long margin", positive=True
            ),
            "short_margin_per_hand": _decimal(
                row["short_margin_per_hand"], "short margin", positive=True
            ),
            "tick_size": _decimal(row["tick_size"], "tick_size", positive=True),
            "lower_limit": _decimal(row["lower_limit"], "lower_limit", positive=True),
            "upper_limit": _decimal(row["upper_limit"], "upper_limit", positive=True),
        }
        if metadata[target]["lower_limit"] >= metadata[target]["upper_limit"]:
            raise RunnerError("REPLAY_PRICE_LIMITS_INVALID", target)
    if set(metadata) != set(plan["targets"]):
        raise RunnerError("REPLAY_METADATA_TARGET_SET_MISMATCH")
    return snapshot, metadata


class ReplayTapeClock:
    """Replay time stays on a slot until its cohort batch completes.

    Cerebro and its feeds may sample ``monotonic_ns`` several times within a
    round, so those samples advance only the monotonic clock. When bound to a
    cohort, ``utc_now`` follows a published completed batch and ``wait`` moves
    to the next slot. An unbound clock remains at its first UTC slot.
    """

    def __init__(self, times, *, cohort=None):
        ordered = tuple(times)
        if not ordered or any(not isinstance(item, datetime) for item in ordered):
            raise ValueError("ReplayTapeClock requires explicit availability times")
        utc_times = tuple(_aware_datetime(item, "replay clock time") for item in ordered)
        if tuple(sorted(utc_times)) != utc_times:
            raise ValueError("ReplayTapeClock times must be monotone")
        if cohort is not None and not callable(getattr(cohort, "current_batch", None)):
            raise ValueError("ReplayTapeClock cohort must expose current_batch")
        self._times = utc_times
        self._cohort = cohort
        self._index = 0
        self._started = False
        self._mono = 1_000_000_000
        self._lock = threading.Lock()

    def utc_now(self):
        with self._lock:
            if not self._started:
                raise RuntimeError("ReplayTapeClock has not entered a Cerebro round")
        batch = self._cohort.current_batch() if self._cohort is not None else None
        slot_index = getattr(batch, "slot_index", None)
        batch_complete = getattr(batch, "status", None) == "COMPLETE"
        with self._lock:
            if (
                batch_complete
                and type(slot_index) is int
                and 0 <= slot_index < len(self._times)
                and slot_index > self._index
            ):
                self._index = slot_index
            return self._times[self._index]

    def monotonic_ns(self):
        with self._lock:
            self._mono += 1_000_000
            self._started = True
            return self._mono

    def wait(self, timeout_seconds):
        del timeout_seconds
        batch = self._cohort.current_batch() if self._cohort is not None else None
        slot_index = getattr(batch, "slot_index", None)
        batch_complete = getattr(batch, "status", None) == "COMPLETE"
        with self._lock:
            self._mono += 1_000_000
            if (
                batch_complete
                and type(slot_index) is int
                and 0 <= slot_index < len(self._times)
                and slot_index >= self._index
            ):
                self._index = min(slot_index + 1, len(self._times) - 1)


def _replay_clock_schedule(grid, tape, quotes):
    """Build a bounded decision-time schedule from source availability.

    Quote rows are assigned to the planned minute interval in which their
    source event occurred. A quote must be available by the next planned close
    to be consumed at this decision; a late row is left out, so a stale signal
    cannot wait hours for it and then become actionable.
    """
    minutes = tuple(grid.minutes)
    schedule = []
    late_quote_count = 0
    for index, minute in enumerate(minutes):
        next_close = (
            minutes[index + 1].close_time
            if index + 1 < len(minutes)
            else minute.close_time + timedelta(minutes=1)
        )
        available_at = max(
            event["available_at"]
            for target in tape["events"]
            for event in tape["events"][target]
            if event["bucket_end"] == minute.close_time
        )
        for quote in quotes:
            if not (minute.close_time <= quote.event_time < next_close):
                continue
            if quote.available_at <= next_close:
                available_at = max(available_at, quote.available_at)
            else:
                late_quote_count += 1
        if schedule:
            available_at = max(schedule[-1], available_at)
        schedule.append(available_at)
    return tuple(schedule), late_quote_count


class RunnerWallClock:
    """Scheduler clock; it does not rewrite exchange timestamps or source bars."""

    def utc_now(self):
        return datetime.now(UTC)

    def monotonic_ns(self):
        return time.monotonic_ns()

    def wait(self, timeout_seconds):
        time.sleep(timeout_seconds)

    def wait_interruptibly(self, timeout_seconds, wait_for_event):
        """Wait on the engine's generation-bound condition without moving UTC."""
        return wait_for_event(timeout_seconds)


def _assert_strategy_params(strategy_cls, required):
    names = set(strategy_cls.params._getkeys())
    missing = set(required).difference(names)
    if missing:
        raise RunnerError("ALPHA003_STRATEGY_API_PENDING", ",".join(sorted(missing)))


def _make_strategy_kwargs(config, plan, factor_mode, direction, risk_policy, *, replay, **extra):
    from alpha003_strategy import Alpha003TargetStrategy

    required = {
        "cohort",
        "calendar_id",
        "strategy_scope",
        "product_keys",
        "authorized_targets",
        "replay_mode",
        "execution_enabled",
        "risk_policy",
        "replay_quotes",
        "replay_instruments",
        "session_calendars",
        "routes",
        "account_scope",
        "logical_run_id",
        "source_kind",
        "max_live_bar_age_seconds",
        "max_future_skew_seconds",
        "live_ready_callback",
        "live_next_callback",
        "live_capacity_callback",
        "loss_guard_net_loss_threshold",
        "loss_guard_max_observation_age_seconds",
    }
    _assert_strategy_params(Alpha003TargetStrategy, required)
    route_by_target = {
        _target_id(product): (instrument, product.exchange_id)
        for product, instrument in plan["routes"].items()
    }
    strategy_scope = config["live"]["strategy_scope"] or "alpha003-example"
    return {
        "cohort": extra.pop("cohort"),
        "calendar_id": config["cohort"]["calendar_id"],
        "strategy_scope": strategy_scope,
        "product_keys": {
            target: (product.exchange_id, product.product_id)
            for target, product in plan["product_by_target"].items()
        },
        "authorized_targets": tuple(plan["authorized_targets"]),
        "factor_mode": factor_mode,
        "direction": direction,
        "preheat_bars": config["factor"]["preheat_bars"],
        "max_pending_slots": config["cohort"]["max_pending_slots"],
        "max_window_bars": config["cohort"]["max_window_bars"],
        "wait_timeout_ns": int(float(config["cohort"]["wait_timeout_seconds"]) * 1_000_000_000),
        "rebalance_every": config["factor"]["rebalance_every"],
        "replay_mode": replay,
        "execution_enabled": replay,
        "risk_policy": risk_policy,
        "loss_guard_net_loss_threshold": extra.pop("loss_guard_net_loss_threshold", None),
        "loss_guard_max_observation_age_seconds": extra.pop(
            "loss_guard_max_observation_age_seconds", None
        ),
        "routes": route_by_target,
        "session_calendars": plan["session_calendars"],
        "account_scope": extra.pop("account_scope", None),
        "logical_run_id": extra.pop("logical_run_id", None),
        "replay_quotes": extra.pop("replay_quotes", ()),
        "replay_instruments": extra.pop("replay_instruments", {}),
        "live_ready_callback": extra.pop("live_ready_callback", None),
        "live_next_callback": extra.pop("live_next_callback", None),
        "live_capacity_callback": extra.pop("live_capacity_callback", None),
        **extra,
    }


def _check_tape_complete(plan, tape):
    expected_closes = tuple(minute.close_time for minute in plan["grid"].minutes)
    for target in plan["targets"]:
        actual = tuple(event["bucket_end"] for event in tape["events"].get(target, ()))
        if actual != expected_closes:
            missing = len(set(expected_closes).difference(actual))
            extra = len(set(actual).difference(expected_closes))
            raise RunnerError(
                "REPLAY_TAPE_NOT_FULL_GRID", f"{target}: missing={missing} extra={extra}"
            )


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError, UnicodeError):
        raise RunnerError("DECISION_TAPE_VALUE_INVALID") from None


def _tape_scalar(value: Any, label: str) -> Any:
    """Return a bounded JSON scalar while preserving finite numeric values."""
    if value is None or type(value) in (str, int, bool):
        return value
    if isinstance(value, datetime):
        return _json_time(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise RunnerError("DECISION_TAPE_VALUE_INVALID", label)
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RunnerError("DECISION_TAPE_VALUE_INVALID", label)
        return value
    if hasattr(value, "value") and type(getattr(value, "value")) in (str, int, bool):
        return value.value
    raise RunnerError("DECISION_TAPE_VALUE_INVALID", label)


def _tape_factor_value(value: Any) -> Mapping[str, Any]:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return {"finite": False, "value": None, "float64_hex": None}
    if not math.isfinite(number):
        return {"finite": False, "value": None, "float64_hex": number.hex()}
    return {"finite": True, "value": number, "float64_hex": number.hex()}


def _decision_tape_record(
    batch: Any,
    snapshot: Any,
    target_decision: Any,
    order_plan: Any,
    *,
    file_id: str,
    index: int,
    targets: tuple[str, ...],
    calendar_fingerprint: Optional[str] = None,
) -> dict[str, Any]:
    members = getattr(batch, "members", None)
    if not isinstance(members, Mapping) or tuple(sorted(members)) != tuple(sorted(targets)):
        raise RunnerError("DECISION_TAPE_MEMBER_SET_INVALID")
    if (
        getattr(batch, "status", None) != "COMPLETE"
        or getattr(snapshot, "batch_complete", None) is not True
        or getattr(snapshot, "batch_id", None) != getattr(batch, "batch_id", None)
        or getattr(snapshot, "close_time", None) != getattr(batch, "close_time", None)
    ):
        raise RunnerError("DECISION_TAPE_BATCH_SNAPSHOT_MISMATCH")

    member_rows = {}
    for target in sorted(targets):
        receipt = members[target]
        envelope = getattr(receipt, "envelope", None)
        if envelope is None or getattr(envelope, "member_id", None) != target:
            raise RunnerError("DECISION_TAPE_RECEIPT_INVALID", target)
        raw_values = getattr(envelope, "raw_values", None)
        if not isinstance(raw_values, Mapping) or not set(OHLCV_FIELDS).issubset(raw_values):
            raise RunnerError("DECISION_TAPE_RAW_FIELDS_INVALID", target)
        member_rows[target] = {
            "cohort_id": _tape_scalar(getattr(envelope, "cohort_id", None), "cohort_id"),
            "calendar_id": _tape_scalar(getattr(envelope, "calendar_id", None), "calendar_id"),
            "epoch_id": _tape_scalar(getattr(envelope, "epoch_id", None), "epoch_id"),
            "slot_index": _tape_scalar(getattr(envelope, "slot_index", None), "slot_index"),
            "slot_id": _tape_scalar(getattr(envelope, "slot_id", None), "slot_id"),
            "instrument": _tape_scalar(getattr(envelope, "instrument", None), "instrument"),
            "source_ref": _tape_scalar(getattr(envelope, "source_ref", None), "source_ref"),
            "origin_partition": _tape_origin_partition(
                getattr(envelope, "origin_partition", None), target
            ),
            "source_role": _tape_scalar(getattr(envelope, "source_role", None), "source_role"),
            "connection_generation": _tape_scalar(
                getattr(envelope, "connection_generation", None), "connection_generation"
            ),
            "feed_sequence": _tape_scalar(
                getattr(envelope, "feed_sequence", None), "feed_sequence"
            ),
            "bucket_start": _tape_scalar(getattr(envelope, "bucket_start", None), "bucket_start"),
            "close_time": _tape_scalar(getattr(envelope, "close_time", None), "close_time"),
            "available_at": _tape_scalar(getattr(envelope, "available_at", None), "available_at"),
            "trading_day": _tape_trading_day(
                getattr(envelope, "trading_day", None), "trading_day"
            ),
            "session_segment": _tape_scalar(
                getattr(envelope, "session_segment", None), "session_segment"
            ),
            "timezone_id": _tape_scalar(getattr(envelope, "timezone_id", None), "timezone_id"),
            "clock_domain_id": _tape_scalar(
                getattr(envelope, "clock_domain_id", None), "clock_domain_id"
            ),
            "bar_id": _tape_scalar(getattr(envelope, "bar_id", None), "bar_id"),
            "complete": _tape_scalar(getattr(envelope, "complete", None), "complete"),
            "quality": _tape_scalar(getattr(envelope, "quality", None), "quality"),
            "present": _tape_scalar(getattr(envelope, "present", None), "present"),
            "quality_flags": list(getattr(envelope, "quality_flags", ())),
            "event_source": _tape_scalar(getattr(envelope, "event_source", None), "event_source"),
            "received_monotonic_ns": _tape_scalar(
                getattr(envelope, "received_monotonic_ns", None), "received_monotonic_ns"
            ),
            "raw_values": {
                field: _tape_scalar(raw_values[field], f"{target}.{field}")
                for field in sorted(raw_values)
            },
        }
        if calendar_fingerprint is not None:
            member_rows[target]["missing_fields"] = list(
                getattr(envelope, "missing_fields", ())
            )
            member_rows[target]["rules_hash"] = _tape_scalar(
                getattr(envelope, "rules_hash", None), "rules_hash"
            )

    factors = getattr(snapshot, "factors", None)
    if not isinstance(factors, Mapping) or not factors:
        raise RunnerError("DECISION_TAPE_FACTOR_SNAPSHOT_INVALID")
    factor_rows = {}
    for name, factor in sorted(factors.items()):
        values = getattr(factor, "values", None)
        if not isinstance(values, Mapping) or tuple(sorted(values)) != tuple(sorted(targets)):
            raise RunnerError("DECISION_TAPE_FACTOR_TARGET_SET_INVALID", str(name))
        factor_rows[str(name)] = {
            "mode": _tape_scalar(getattr(factor, "mode", None), "factor mode"),
            "panel_line": _tape_scalar(getattr(factor, "panel_line", None), "factor panel"),
            "direction": _tape_scalar(getattr(factor, "direction", None), "factor direction"),
            "source_sha256": _tape_scalar(
                getattr(factor, "source_sha256", None), "factor source hash"
            ),
            "values": {
                target: {
                    "value": _tape_factor_value(getattr(values[target], "value", None)),
                    "status": _tape_scalar(
                        getattr(values[target], "status", None), "factor status"
                    ),
                    "reason": _tape_scalar(
                        getattr(values[target], "reason", None), "factor reason"
                    ),
                    "present": _tape_scalar(
                        getattr(values[target], "present", None), "factor present"
                    ),
                    "complete": _tape_scalar(
                        getattr(values[target], "complete", None), "factor complete"
                    ),
                    "quality": _tape_scalar(
                        getattr(values[target], "quality", None), "factor quality"
                    ),
                    "source_role": _tape_scalar(
                        getattr(values[target], "source_role", None), "factor source role"
                    ),
                    "member_id": _tape_scalar(
                        getattr(values[target], "member_id", None), "factor member"
                    ),
                    "source_ref": _tape_scalar(
                        getattr(values[target], "source_ref", None), "factor source ref"
                    ),
                    "sequence": _tape_scalar(
                        getattr(values[target], "sequence", None), "factor sequence"
                    ),
                    "generation": _tape_scalar(
                        getattr(values[target], "generation", None), "factor generation"
                    ),
                }
                for target in sorted(targets)
            },
        }

    decision_row = None
    if target_decision is not None:
        target_rows = []
        for item in getattr(target_decision, "targets", ()):
            product = getattr(item, "product_key", None)
            target_rows.append(
                {
                    "target_id": _tape_scalar(getattr(item, "target_id", None), "decision target"),
                    "product_key": {
                        "exchange_id": _tape_scalar(
                            getattr(product, "exchange_id", None), "product exchange"
                        ),
                        "product_id": _tape_scalar(
                            getattr(product, "product_id", None), "product id"
                        ),
                    },
                    "target_position": _tape_scalar(
                        getattr(item, "target_position", None), "target position"
                    ),
                    "raw_score": _tape_factor_value(getattr(item, "raw_score", None)),
                    "oriented_score": _tape_factor_value(getattr(item, "oriented_score", None)),
                }
            )
        decision_row = {
            name: _tape_scalar(getattr(target_decision, name), f"decision {name}")
            for name in (
                "status",
                "reason",
                "factor_name",
                "mode",
                "execution_mode",
                "direction",
                "source_sha256",
                "cohort_id",
                "batch_id",
                "close_time",
                "available_at",
                "eligible_grid_index",
                "rebalance_every",
            )
        }
        decision_row.update(
            authorized_targets=list(getattr(target_decision, "authorized_targets", ())),
            eligible_targets=list(getattr(target_decision, "eligible_targets", ())),
            targets=target_rows,
        )

    plan_row = None
    if order_plan is not None:
        actions = []
        for action in getattr(order_plan, "actions", ()):
            actions.append(
                {
                    name: _tape_scalar(getattr(action, name), f"order action {name}")
                    for name in (
                        "action",
                        "target_id",
                        "instrument",
                        "side",
                        "position_effect",
                        "quantity",
                        "limit_price",
                        "offset",
                        "reason",
                        "planned_stop_price",
                        "exchange",
                        "decision_available_at",
                        "entry_grid_ordinal",
                    )
                }
            )
        plan_row = {
            "status": _tape_scalar(getattr(order_plan, "status", None), "plan status"),
            "reason": _tape_scalar(getattr(order_plan, "reason", None), "plan reason"),
            "decision_batch_id": _tape_scalar(
                getattr(order_plan, "decision_batch_id", None), "plan batch"
            ),
            "decision_available_at": _tape_scalar(
                getattr(order_plan, "decision_available_at", None), "plan availability"
            ),
            "actions": actions,
        }

    row = {
        "schema": DECISION_TAPE_SCHEMA,
        "record_type": "DECISION",
        "file_id": file_id,
        "record_index": index,
        "batch_id": _tape_scalar(getattr(batch, "batch_id", None), "batch_id"),
        "cohort_id": _tape_scalar(getattr(batch, "cohort_id", None), "cohort_id"),
        "calendar_id": _tape_scalar(getattr(batch, "calendar_id", None), "calendar_id"),
        "calendar_version": _tape_scalar(
            getattr(batch, "calendar_version", None), "calendar_version"
        ),
        "epoch_id": _tape_scalar(getattr(batch, "epoch_id", None), "epoch_id"),
        "slot_index": _tape_scalar(getattr(batch, "slot_index", None), "slot_index"),
        "close_time": _tape_scalar(getattr(batch, "close_time", None), "close_time"),
        "available_at": _tape_scalar(getattr(batch, "available_at", None), "available_at"),
        "readiness": _tape_scalar(getattr(snapshot, "readiness", None), "snapshot readiness"),
        "readiness_reasons": list(getattr(snapshot, "readiness_reasons", ())),
        "members": member_rows,
        "factors": {
            "plan_id": _tape_scalar(getattr(snapshot, "plan_id", None), "factor plan"),
            "factors": factor_rows,
        },
        "target_decision": decision_row,
        "order_plan": plan_row,
    }
    if calendar_fingerprint is not None:
        row["calendar_fingerprint"] = calendar_fingerprint
        row["slot_id"] = member_rows[sorted(member_rows)[0]]["slot_id"]
    return row


class DecisionTapeWriter:
    """Exclusive, byte-bounded JSONL tape for replayable cohort decisions."""

    def __init__(
        self,
        path: Path,
        max_bytes: int,
        *,
        mode: str,
        factor_mode: str,
        direction: int,
        targets: tuple[str, ...],
        calendar_id: str,
        grid_sha256: Optional[str],
        source_snapshot_id: Optional[str],
        restart_identity: Optional[Mapping[str, Any]] = None,
        selection_evidence: Optional[Mapping[str, Any]] = None,
        calendar_fingerprint: Optional[str] = None,
    ) -> None:
        if type(max_bytes) is not int or max_bytes < 1:
            raise RunnerError("DECISION_TAPE_BYTE_BUDGET_INVALID")
        if mode not in {"replay", "live"}:
            raise RunnerError("DECISION_TAPE_MODE_INVALID")
        self.mode = mode
        self.factor_mode = factor_mode
        self.direction = direction
        self.path = path.resolve(strict=False)
        self.max_bytes = max_bytes
        self.targets = tuple(sorted(targets))
        self.calendar_id = calendar_id
        self.grid_sha256 = grid_sha256
        self.source_snapshot_id = source_snapshot_id
        if not self.targets or len(self.targets) != len(set(self.targets)):
            raise RunnerError("DECISION_TAPE_TARGETS_INVALID")
        self.file_id = str(uuid.uuid4())
        self._bytes = 0
        self._record_count = 0
        self._hash = hashlib.sha256()
        self._closed = False
        self._failed = False
        self._lock = threading.RLock()
        self._last_record_reference = None
        self._header_record_id = None
        self._fee_pair_source_scope = None
        if calendar_fingerprint is not None and (
            type(calendar_fingerprint) is not str
            or len(calendar_fingerprint) != 64
            or any(ch not in "0123456789abcdef" for ch in calendar_fingerprint)
        ):
            raise RunnerError("DECISION_TAPE_CALENDAR_FINGERPRINT_INVALID")
        self.calendar_fingerprint = calendar_fingerprint
        self._selection_evidence = (
            _validate_selection_evidence(selection_evidence)
            if selection_evidence is not None
            else None
        )
        self._selection_evidence_sha256 = (
            self._selection_evidence["binding_sha256"]
            if self._selection_evidence is not None
            else None
        )
        self._restart_identity = (
            None
            if restart_identity is None
            else json.loads(_canonical_json_bytes(restart_identity))
        )
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self.path.open("xb")
        except OSError:
            raise RunnerError("DECISION_TAPE_CREATE_FAILED") from None
        header = {
            "schema": DECISION_TAPE_SCHEMA,
            "origin_partition_schema": SOURCE_ORIGIN_PARTITION_SCHEMA,
            "record_type": "HEADER",
            "file_id": self.file_id,
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "mode": mode,
            "factor_mode": factor_mode,
            "direction": direction,
            "targets": list(self.targets),
            "calendar_id": calendar_id,
            "grid_sha256": grid_sha256,
            "source_snapshot_id": source_snapshot_id,
        }
        if calendar_fingerprint is not None:
            header["calendar_fingerprint"] = calendar_fingerprint
        if restart_identity is not None:
            _canonical_json_bytes(restart_identity)
            header["restart_identity"] = dict(restart_identity)
        if self._selection_evidence is not None:
            header["selection_evidence"] = dict(self._selection_evidence)
        canonical = _canonical_json_bytes(header)
        self._header_record_id = hashlib.sha256(canonical.rstrip(b"\n")).hexdigest()
        header["record_id"] = self._header_record_id
        try:
            self._append(_canonical_json_bytes(header), count_record=False)
        except BaseException:
            try:
                self._handle.close()
            finally:
                self._closed = True
            raise

    @property
    def last_record_reference(self):
        with self._lock:
            return self._last_record_reference

    def _append(self, raw: bytes, *, count_record: bool) -> None:
        with self._lock:
            if self._closed or self._failed:
                raise RunnerError("DECISION_TAPE_UNAVAILABLE")
            offset = self._bytes
            if offset + len(raw) > self.max_bytes:
                self._failed = True
                raise RunnerError("DECISION_TAPE_BYTE_BUDGET_EXCEEDED")
            try:
                written = self._handle.write(raw)
                if written != len(raw):
                    raise OSError("short decision tape write")
                self._handle.flush()
                os.fsync(self._handle.fileno())
            except BaseException:
                try:
                    os.ftruncate(self._handle.fileno(), offset)
                    self._handle.seek(offset)
                    self._handle.flush()
                    os.fsync(self._handle.fileno())
                except BaseException:
                    pass
                self._failed = True
                raise RunnerError("DECISION_TAPE_WRITE_FAILED") from None
            self._bytes += len(raw)
            self._hash.update(raw)
            if count_record:
                self._record_count += 1

    def record_decision(self, batch, snapshot, target_decision, order_plan):
        with self._lock:
            if self._closed or self._failed:
                raise RunnerError("DECISION_TAPE_UNAVAILABLE")
            index = self._record_count + 1
            row = _decision_tape_record(
                batch,
                snapshot,
                target_decision,
                order_plan,
                file_id=self.file_id,
                index=index,
                targets=self.targets,
                calendar_fingerprint=self.calendar_fingerprint,
            )
            if self._selection_evidence_sha256 is not None:
                row["selection_evidence_sha256"] = self._selection_evidence_sha256
            row["header_record_id"] = self._header_record_id
            digest = hashlib.sha256(_canonical_json_bytes(row).rstrip(b"\n")).hexdigest()
            row["record_id"] = digest
            raw = _canonical_json_bytes(row)
            self._append(raw, count_record=True)
            self._last_record_reference = MappingProxyType(
                {
                    "file_id": self.file_id,
                    "record_id": digest,
                    "record_index": index,
                    "batch_id": row["batch_id"],
                }
            )
            return True

    def record_fee_pair_source_only(
        self,
        candidate,
        batch,
        snapshot,
        target_decision,
        journal,
        *,
        owner_token: str,
        ttl_seconds: float = 10.0,
    ):
        """Append and verify one v17 candidate as a no-intent SOURCE_ONLY row.

        This is an opt-in, same-process source-only helper. It does not query
        fees, authorize OPEN, recover a writer after restart, or establish
        cross-process exclusion. The ordinary ``record_decision`` row format
        remains unchanged. Candidate signal/factor/quote hashes are opaque
        commitments: this helper binds their v17 candidate digest into the
        row, but does not claim to recompute their underlying content.
        """
        from backtrader.stores import execution_decision_journal as journal_api

        if type(candidate) is not journal_api.ExecutionFeePairCandidate:
            raise RunnerError("FEE_PAIR_CANDIDATE_TYPE_INVALID")
        if type(journal) is not journal_api.ExecutionDecisionJournal:
            raise RunnerError("FEE_PAIR_JOURNAL_TYPE_INVALID")

        with self._lock:
            if self._closed or self._failed:
                raise RunnerError("DECISION_TAPE_UNAVAILABLE")
            if self.calendar_fingerprint is None:
                raise RunnerError("FEE_PAIR_TAPE_CALENDAR_FINGERPRINT_REQUIRED")
            if self._selection_evidence is None:
                raise RunnerError("FEE_PAIR_TAPE_SELECTION_EVIDENCE_REQUIRED")
            self._verify_fee_pair_writer_prefix(journal)
            self._verify_fee_pair_candidate_writer_binding(candidate)

            expected_index = self._record_count + 1
            source_scope = (
                candidate.key.account_scope,
                candidate.key.strategy_scope,
                candidate.key.logical_run_id,
                candidate.source_kind,
                candidate.cohort_id,
                candidate.epoch_id,
                candidate.calendar_id,
                candidate.calendar_version,
                candidate.calendar_fingerprint,
            )
            if (
                self._fee_pair_source_scope is not None
                and self._fee_pair_source_scope != source_scope
            ):
                raise RunnerError("FEE_PAIR_TAPE_SOURCE_SCOPE_MISMATCH")
            highwater = journal.source_highwater(
                candidate.key.account_scope,
                candidate.key.strategy_scope,
                candidate.key.logical_run_id,
                candidate.source_kind,
            )
            if highwater is not None and (
                candidate.epoch_id < highwater.receipt.epoch_id
                or (
                    candidate.epoch_id == highwater.receipt.epoch_id
                    and candidate.slot_index <= highwater.receipt.slot_index
                )
            ):
                raise RunnerError("FEE_PAIR_TAPE_SLOT_ALREADY_CONSUMED")
            if (
                candidate.expected_tape_file_id != self.file_id
                or candidate.expected_tape_record_index != expected_index
            ):
                raise RunnerError("FEE_PAIR_TAPE_POSITION_MISMATCH")

            row = _decision_tape_record(
                batch,
                snapshot,
                target_decision,
                None,
                file_id=self.file_id,
                index=expected_index,
                targets=self.targets,
                calendar_fingerprint=self.calendar_fingerprint,
            )
            _validate_fee_pair_candidate_projection(candidate, row, journal_api)
            row["order_plan"] = {
                "status": "SOURCE_ONLY",
                "reason": "FEE_PAIR_NOT_AUTHORIZED",
                "decision_batch_id": row["batch_id"],
                "decision_available_at": row["available_at"],
                "actions": [],
            }
            if self._selection_evidence_sha256 is not None:
                row["selection_evidence_sha256"] = self._selection_evidence_sha256
            row["header_record_id"] = self._header_record_id

            # Both hashes have fixed-width SHA-256 encodings.  Check the exact
            # line and file limits before the durable claim so a local capacity
            # rejection cannot strand an APPEND_CLAIMED workflow.
            size_probe = dict(row)
            size_probe["fee_pair_workflow"] = {
                "candidate_id": "0" * 64,
                "candidate_sha256": "0" * 64,
            }
            size_probe["record_id"] = "0" * 64
            size_probe_raw = _canonical_json_bytes(size_probe)
            if len(size_probe_raw) > _FEE_PAIR_SOURCE_ONLY_MAX_RECORD_BYTES:
                raise RunnerError("FEE_PAIR_TAPE_RECORD_BYTE_LIMIT_EXCEEDED")
            if self._bytes + len(size_probe_raw) > _FEE_PAIR_SOURCE_ONLY_MAX_TAPE_BYTES:
                raise RunnerError("FEE_PAIR_TAPE_BYTE_LIMIT_EXCEEDED")
            if self._bytes + len(size_probe_raw) > self.max_bytes:
                raise RunnerError("DECISION_TAPE_BYTE_BUDGET_EXCEEDED")

            try:
                # The Journal is the durable duplicate/cursor authority.  This
                # scalar binds this same-process writer to one source scope;
                # failures after this point leave the writer latched unusable.
                self._fee_pair_source_scope = source_scope
                reserved = journal.reserve_fee_pair_workflow_candidate(
                    candidate,
                    owner_token=owner_token,
                    ttl_seconds=ttl_seconds,
                )
                candidate_id = reserved.candidate_id
                candidate_sha256 = reserved.candidate_sha256
                if (
                    reserved.state != "RESERVED"
                    or type(candidate_id) is not str
                    or not _is_lower_sha256(candidate_id)
                    or not _is_lower_sha256(candidate_sha256)
                ):
                    raise RunnerError("FEE_PAIR_CANDIDATE_RESERVATION_INVALID")

                claimed = journal.record_fee_pair_workflow_append_claim(
                    candidate_id, owner_token=owner_token
                )
                if claimed.state != "APPEND_CLAIMED":
                    raise RunnerError("FEE_PAIR_APPEND_CLAIM_INVALID")

                row["fee_pair_workflow"] = {
                    "candidate_id": candidate_id,
                    "candidate_sha256": candidate_sha256,
                }
                digest = hashlib.sha256(_canonical_json_bytes(row).rstrip(b"\n")).hexdigest()
                row["record_id"] = digest
                raw = _canonical_json_bytes(row)
                if len(raw) != len(size_probe_raw):
                    raise RunnerError("FEE_PAIR_TAPE_RECORD_SIZE_PROJECTION_MISMATCH")
                self._append(raw, count_record=True)
                self._last_record_reference = MappingProxyType(
                    {
                        "file_id": self.file_id,
                        "record_id": digest,
                        "record_index": expected_index,
                        "batch_id": row["batch_id"],
                    }
                )

                verified_row = self._verify_fee_pair_candidate_tape_rows(
                    journal,
                    candidate,
                    candidate_id=candidate_id,
                    candidate_sha256=candidate_sha256,
                    expected_index=expected_index,
                )
                receipt = _fee_pair_source_receipt_from_tape_row(
                    verified_row, candidate, journal_api
                )
                attached = journal.attach_verified_fee_pair_source_receipt(
                    candidate_id, receipt, owner_token=owner_token
                )
                if attached.state != "RECEIPT_VERIFIED":
                    raise RunnerError("FEE_PAIR_SOURCE_RECEIPT_NOT_ATTACHED")
                decision = journal.finalize_fee_pair_source_only_from_attached_receipt(
                    candidate_id, owner_token=owner_token
                )
                if (
                    decision.key != candidate.key
                    or decision.intent_keys
                    or decision.economic_payload.get("_execution_source_anchor_only") is not True
                    or decision.economic_payload.get("_execution_fee_pair_workflow")
                    != {
                        "candidate_id": candidate_id,
                        "candidate_sha256": candidate_sha256,
                    }
                ):
                    raise RunnerError("FEE_PAIR_SOURCE_ONLY_DECISION_INVALID")
                workflow = journal.fee_pair_workflow_candidate(candidate_id)
                highwater = journal.source_highwater(
                    candidate.key.account_scope,
                    candidate.key.strategy_scope,
                    candidate.key.logical_run_id,
                    candidate.source_kind,
                )
                if (
                    workflow is None
                    or workflow.state != "SOURCE_ONLY"
                    or workflow.source_only_decision_id != decision.decision_id
                    or highwater is None
                    or highwater.anchor_kind != "SOURCE_ONLY"
                    or highwater.receipt != receipt
                ):
                    raise RunnerError("FEE_PAIR_SOURCE_ONLY_HIGHWATER_INVALID")
                return MappingProxyType(
                    {
                        "candidate_id": candidate_id,
                        "candidate_sha256": candidate_sha256,
                        "tape_reference": dict(self._last_record_reference),
                        "source_receipt": receipt,
                        "decision": decision,
                    }
                )
            except BaseException:
                # A post-reservation failure leaves the Journal claim unresolved
                # and the tape unusable for further writes in this process.
                self._failed = True
                raise

    def _verify_fee_pair_candidate_writer_binding(self, candidate) -> None:
        identity = self._restart_identity
        evidence = self._selection_evidence
        scope_hashes = identity.get("scope_sha256") if isinstance(identity, Mapping) else None
        calendar = identity.get("calendar") if isinstance(identity, Mapping) else None
        identity_targets = identity.get("targets") if isinstance(identity, Mapping) else None
        routes = identity.get("routes") if isinstance(identity, Mapping) else None
        key = candidate.key
        expected_scope_hashes = {
            "account_scope": hashlib.sha256(key.account_scope.encode("utf-8")).hexdigest(),
            "strategy_scope": hashlib.sha256(key.strategy_scope.encode("utf-8")).hexdigest(),
            "logical_run_id": hashlib.sha256(key.logical_run_id.encode("utf-8")).hexdigest(),
        }
        if (
            not isinstance(identity, Mapping)
            or not isinstance(evidence, Mapping)
            or not isinstance(scope_hashes, Mapping)
            or not isinstance(calendar, Mapping)
            or type(identity_targets) is not list
            or not isinstance(routes, Mapping)
            or identity.get("schema") != "backtrader.alpha003.live_restart_identity.v1"
            or identity.get("mode") != self.mode
            or identity.get("factor_mode") != self.factor_mode
            or identity.get("direction") != self.direction
            or identity.get("epoch_id") != candidate.epoch_id
            or identity.get("scope_sha256") != expected_scope_hashes
            or tuple(identity_targets) != self.targets
            or set(routes) != set(self.targets)
            or identity.get("selection_source") != evidence.get("selection_source")
            or identity.get("source_snapshot_id") != self.source_snapshot_id
            or not _selection_evidence_matches_identity(evidence, identity)
            or calendar.get("calendar_id") != self.calendar_id
            or calendar.get("grid_sha256") != self.grid_sha256
            or candidate.calendar_id != self.calendar_id
            or candidate.calendar_fingerprint != self.calendar_fingerprint
            or len(candidate.target_ids) != 2
            or len(set(candidate.target_ids)) != 2
            or not set(candidate.target_ids).issubset(set(self.targets))
            or type(candidate.source_kind) is not str
            or not candidate.source_kind
        ):
            raise RunnerError("FEE_PAIR_TAPE_PLAN_BINDING_MISMATCH")

    def _verify_fee_pair_writer_prefix(self, journal) -> None:
        try:
            handle_size = os.fstat(self._handle.fileno()).st_size
            path_size = self.path.stat().st_size
        except OSError:
            raise RunnerError("FEE_PAIR_TAPE_WRITER_STATE_UNAVAILABLE") from None
        if (
            handle_size != self._bytes
            or path_size != self._bytes
            or self._bytes > _FEE_PAIR_SOURCE_ONLY_MAX_TAPE_BYTES
        ):
            raise RunnerError("FEE_PAIR_TAPE_WRITER_SIZE_MISMATCH")
        summary = self._stream_fee_pair_tape(journal)
        header = summary["header"]
        last = summary["last"]
        if (
            header is None
            or header.get("file_id") != self.file_id
            or header.get("record_id") != self._header_record_id
            or header.get("mode") != "live"
            or header.get("factor_mode") != self.factor_mode
            or header.get("direction") != self.direction
            or tuple(header.get("targets", ())) != self.targets
            or header.get("calendar_id") != self.calendar_id
            or header.get("grid_sha256") != self.grid_sha256
            or header.get("source_snapshot_id") != self.source_snapshot_id
            or header.get("calendar_fingerprint") != self.calendar_fingerprint
            or header.get("restart_identity") != self._restart_identity
            or header.get("selection_evidence") != self._selection_evidence
        ):
            raise RunnerError("FEE_PAIR_TAPE_WRITER_HEADER_MISMATCH")
        if (
            summary["row_count"] < 1
            or summary["row_count"] - 1 != self._record_count
            or summary["raw_sha256"] != self._hash.hexdigest()
        ):
            raise RunnerError("FEE_PAIR_TAPE_WRITER_CONTENT_MISMATCH")
        actual_last = None
        if last is not None:
            actual_last = {
                "file_id": last["file_id"],
                "record_id": last["record_id"],
                "record_index": last["record_index"],
                "batch_id": last["batch_id"],
            }
        if actual_last != self.last_record_reference:
            raise RunnerError("FEE_PAIR_TAPE_WRITER_TAIL_MISMATCH")

    def _stream_fee_pair_tape(
        self,
        journal,
        *,
        candidate=None,
        candidate_id=None,
        candidate_sha256=None,
        expected_index=None,
    ):
        raw_hasher = hashlib.sha256()
        header = None
        last = None
        matched = None
        row_count = 0
        max_bytes = min(self.max_bytes, _FEE_PAIR_SOURCE_ONLY_MAX_TAPE_BYTES)
        for row in iter_decision_tape(
            self.path,
            max_bytes=max_bytes,
            max_record_bytes=_FEE_PAIR_SOURCE_ONLY_MAX_RECORD_BYTES,
            _raw_hasher=raw_hasher,
        ):
            if row_count == 0:
                header = row
            else:
                if "fee_pair_workflow" in row:
                    extension_row = self._validate_fee_pair_tape_extension(
                        row,
                        journal,
                        candidate=candidate,
                        candidate_id=candidate_id,
                        candidate_sha256=candidate_sha256,
                        expected_index=expected_index,
                    )
                    if extension_row is not None:
                        if matched is not None:
                            raise RunnerError("FEE_PAIR_TAPE_CANDIDATE_ROW_MISMATCH")
                        matched = extension_row
                last = row
            row_count += 1
        return {
            "header": header,
            "last": last,
            "matched": matched,
            "row_count": row_count,
            "raw_sha256": raw_hasher.hexdigest(),
        }

    def _validate_fee_pair_tape_extension(
        self,
        row,
        journal,
        *,
        candidate=None,
        candidate_id=None,
        candidate_sha256=None,
        expected_index=None,
    ):
        from backtrader.stores import execution_decision_journal as journal_api

        extension = row["fee_pair_workflow"]
        if (
            not isinstance(extension, Mapping)
            or set(extension) != {"candidate_id", "candidate_sha256"}
            or not _is_lower_sha256(extension.get("candidate_id"))
            or not _is_lower_sha256(extension.get("candidate_sha256"))
        ):
            raise RunnerError("FEE_PAIR_TAPE_EXTENSION_INVALID")
        current_id = extension["candidate_id"]
        current_sha256 = extension["candidate_sha256"]
        workflow = journal.fee_pair_workflow_candidate(current_id)
        if (
            workflow is None
            or workflow.candidate_id != current_id
            or workflow.candidate_sha256 != current_sha256
        ):
            raise RunnerError("FEE_PAIR_TAPE_EXTENSION_BINDING_MISMATCH")
        if candidate_id is not None and current_id == candidate_id:
            if (
                candidate is None
                or current_sha256 != candidate_sha256
                or row.get("record_index") != expected_index
                or workflow.state != "APPEND_CLAIMED"
                or workflow.source_only_decision_id is not None
            ):
                raise RunnerError("FEE_PAIR_TAPE_EXTENSION_BINDING_MISMATCH")
            _validate_fee_pair_candidate_projection(candidate, row, journal_api)
            return row
        if workflow.state != "SOURCE_ONLY" or type(workflow.source_only_decision_id) is not str:
            raise RunnerError("FEE_PAIR_TAPE_EXTENSION_STATE_INVALID")
        decision = journal.decision(workflow.source_only_decision_id)
        source_scope = self._fee_pair_source_scope
        if (
            decision is None
            or decision.decision_id != workflow.source_only_decision_id
            or source_scope is None
            or decision.key.account_scope != source_scope[0]
            or decision.key.strategy_scope != source_scope[1]
            or decision.key.logical_run_id != source_scope[2]
            or decision.key.decision_kind != source_scope[3]
            or decision.key.cohort_id != row.get("cohort_id")
            or decision.key.close_time != row.get("close_time")
            or decision.intent_keys
            or decision.economic_payload.get("_execution_source_anchor_only") is not True
            or decision.economic_payload.get("_execution_fee_pair_workflow") != dict(extension)
        ):
            raise RunnerError("FEE_PAIR_TAPE_EXTENSION_BINDING_MISMATCH")
        receipt_values = decision.economic_payload.get("_execution_source_receipt")
        if not isinstance(receipt_values, Mapping):
            raise RunnerError("FEE_PAIR_TAPE_EXTENSION_BINDING_MISMATCH")
        row_receipt_fields = (
            ("cohort_id", "cohort_id"),
            ("calendar_id", "calendar_id"),
            ("calendar_version", "calendar_version"),
            ("calendar_fingerprint", "calendar_fingerprint"),
            ("epoch_id", "epoch_id"),
            ("slot_index", "slot_index"),
            ("slot_id", "slot_id"),
            ("close_time", "close_time"),
            ("batch_id", "batch_id"),
            ("readiness", "readiness"),
            ("file_id", "tape_file_id"),
            ("record_id", "tape_record_id"),
            ("record_index", "tape_record_index"),
        )
        if (
            receipt_values.get("source_kind") != source_scope[3]
            or any(
                receipt_values.get(receipt_name) != row.get(row_name)
                for row_name, receipt_name in row_receipt_fields
            )
            or not self._fee_pair_receipt_members_match(row, receipt_values, journal_api)
        ):
            raise RunnerError("FEE_PAIR_TAPE_EXTENSION_BINDING_MISMATCH")
        return None

    @staticmethod
    def _fee_pair_receipt_members_match(row, receipt_values, journal_api):
        receipt_members = receipt_values.get("members")
        if type(receipt_members) not in (list, tuple):
            return False
        try:
            journal_members = []
            for value in receipt_members:
                if not isinstance(value, Mapping):
                    return False
                member_values = dict(value)
                member_values["missing_fields"] = tuple(member_values["missing_fields"])
                member_values["quality_flags"] = tuple(member_values["quality_flags"])
                journal_members.append(journal_api.ExecutionSourceMemberReceipt(**member_values))
            tape_members = _fee_pair_source_members_from_tape_row(row, journal_api)
        except (
            KeyError,
            TypeError,
            ValueError,
            journal_api.ExecutionDecisionJournalError,
            RunnerError,
        ):
            return False
        return tuple(journal_members) == tape_members

    def _verify_fee_pair_candidate_tape_rows(
        self,
        journal,
        candidate,
        *,
        candidate_id,
        candidate_sha256,
        expected_index,
    ):
        from backtrader.stores import execution_decision_journal as journal_api

        summary = self._stream_fee_pair_tape(
            journal,
            candidate=candidate,
            candidate_id=candidate_id,
            candidate_sha256=candidate_sha256,
            expected_index=expected_index,
        )
        rows_seen = summary["row_count"]
        verified_row = summary["matched"]
        if (
            summary["header"] is None
            or summary["header"].get("file_id") != self.file_id
            or rows_seen - 1 != self._record_count
            or self._record_count != expected_index
            or summary["raw_sha256"] != self._hash.hexdigest()
        ):
            raise RunnerError("FEE_PAIR_TAPE_READBACK_INDEX_MISMATCH")
        reference = self._last_record_reference
        if (
            verified_row is None
            or verified_row is not summary["last"]
            or reference is None
            or verified_row.get("file_id") != reference.get("file_id")
            or verified_row.get("record_id") != reference.get("record_id")
            or verified_row.get("record_index") != reference.get("record_index")
            or verified_row.get("batch_id") != reference.get("batch_id")
            or verified_row.get("order_plan")
            != {
                "status": "SOURCE_ONLY",
                "reason": "FEE_PAIR_NOT_AUTHORIZED",
                "decision_batch_id": verified_row.get("batch_id"),
                "decision_available_at": verified_row.get("available_at"),
                "actions": [],
            }
        ):
            raise RunnerError("FEE_PAIR_TAPE_CANDIDATE_ROW_MISMATCH")
        _validate_fee_pair_candidate_projection(
            candidate,
            verified_row,
            journal_api,
        )
        return verified_row

    def close(self):
        with self._lock:
            if self._closed:
                return self.summary()
            try:
                self._handle.flush()
                os.fsync(self._handle.fileno())
            except OSError:
                self._failed = True
                raise RunnerError("DECISION_TAPE_CLOSE_FAILED") from None
            finally:
                try:
                    self._handle.close()
                except OSError:
                    self._failed = True
            self._closed = True
            if self._failed:
                raise RunnerError("DECISION_TAPE_CLOSE_FAILED")
            return self.summary()

    def summary(self):
        return {
            "file_id": self.file_id,
            "path": str(self.path),
            "bytes": self._bytes,
            "max_bytes": self.max_bytes,
            "record_count": self._record_count,
            "sha256": self._hash.hexdigest(),
            "closed": self._closed,
            "failed": self._failed,
            "last_record_reference": (
                dict(self._last_record_reference)
                if self._last_record_reference is not None
                else None
            ),
        }


def _is_lower_sha256(value: Any) -> bool:
    return bool(
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _fee_pair_source_members_from_tape_row(row, journal_api):
    member_rows = row.get("members")
    if not isinstance(member_rows, Mapping) or not member_rows:
        raise RunnerError("FEE_PAIR_TAPE_SOURCE_MEMBERS_INVALID")
    result = []
    try:
        for member_id in sorted(member_rows):
            member = member_rows[member_id]
            if not isinstance(member, Mapping):
                raise RunnerError("FEE_PAIR_TAPE_SOURCE_MEMBER_INVALID")
            result.append(
                journal_api.ExecutionSourceMemberReceipt(
                    member_id=member_id,
                    source_ref=member["source_ref"],
                    source_role=member["source_role"],
                    connection_generation=member["connection_generation"],
                    feed_sequence=member["feed_sequence"],
                    bar_id=member["bar_id"],
                    bucket_start=member["bucket_start"],
                    close_time=member["close_time"],
                    available_at=member["available_at"],
                    trading_day=member["trading_day"],
                    session_segment=member["session_segment"],
                    timezone_id=member["timezone_id"],
                    clock_domain_id=member["clock_domain_id"],
                    complete=member["complete"],
                    quality=member["quality"],
                    present=member["present"],
                    missing_fields=tuple(member.get("missing_fields", ())),
                    quality_flags=tuple(member.get("quality_flags", ())),
                    event_source=member.get("event_source", ""),
                    received_monotonic_ns=member.get("received_monotonic_ns"),
                    rules_hash=member.get("rules_hash"),
                    origin_partition=member.get("origin_partition"),
                )
            )
    except RunnerError:
        raise
    except (
        KeyError,
        TypeError,
        ValueError,
        journal_api.ExecutionDecisionJournalError,
    ) as error:
        code = getattr(error, "code", None)
        raise RunnerError(
            "FEE_PAIR_TAPE_SOURCE_MEMBER_INVALID",
            code if type(code) is str else None,
        ) from None
    return tuple(result)


def _validate_fee_pair_candidate_projection(
    candidate, row, journal_api, *, allow_missing_candidate=False
):
    if candidate is None and allow_missing_candidate:
        candidate = None
    elif candidate is None:
        raise RunnerError("FEE_PAIR_CANDIDATE_REQUIRED")
    if (
        row.get("schema") != DECISION_TAPE_SCHEMA
        or row.get("record_type") != "DECISION"
        or not _is_lower_sha256(row.get("calendar_fingerprint"))
        or type(row.get("slot_id")) is not str
        or not row["slot_id"]
    ):
        raise RunnerError("FEE_PAIR_TAPE_SOURCE_PROJECTION_INVALID")

    members = _fee_pair_source_members_from_tape_row(row, journal_api)
    member_rows = row["members"]
    member_ids = tuple(member.member_id for member in members)
    slot_ids = {member_rows[member_id].get("slot_id") for member_id in member_ids}
    for member_id in member_ids:
        member_row = member_rows[member_id]
        if (
            member_row.get("cohort_id") != row.get("cohort_id")
            or member_row.get("calendar_id") != row.get("calendar_id")
            or member_row.get("epoch_id") != row.get("epoch_id")
            or member_row.get("slot_index") != row.get("slot_index")
            or member_row.get("close_time") != row.get("close_time")
        ):
            raise RunnerError("FEE_PAIR_TAPE_SOURCE_PROJECTION_INVALID")
    if slot_ids != {row.get("slot_id")}:
        raise RunnerError("FEE_PAIR_TAPE_SOURCE_PROJECTION_INVALID")

    target_decision = row.get("target_decision")
    if not isinstance(target_decision, Mapping):
        raise RunnerError("FEE_PAIR_TAPE_TARGET_PROJECTION_INVALID")
    target_rows = target_decision.get("targets")
    if not isinstance(target_rows, list):
        raise RunnerError("FEE_PAIR_TAPE_TARGET_PROJECTION_INVALID")
    target_positions = {}
    for item in target_rows:
        if not isinstance(item, Mapping):
            raise RunnerError("FEE_PAIR_TAPE_TARGET_PROJECTION_INVALID")
        target_id = item.get("target_id")
        position = item.get("target_position")
        if type(target_id) is not str or target_id in target_positions:
            raise RunnerError("FEE_PAIR_TAPE_TARGET_PROJECTION_INVALID")
        if type(position) is not int or position not in (-1, 1):
            raise RunnerError("FEE_PAIR_TAPE_TARGET_PROJECTION_INVALID")
        target_positions[target_id] = position

    if candidate is None:
        if len(target_positions) != 2 or not set(target_positions).issubset(set(member_ids)):
            raise RunnerError("FEE_PAIR_TAPE_TARGET_PROJECTION_INVALID")
        return members

    if (
        candidate.expected_tape_file_id != row.get("file_id")
        or candidate.expected_tape_record_index != row.get("record_index")
        or candidate.batch_id != row.get("batch_id")
        or candidate.cohort_id != row.get("cohort_id")
        or candidate.calendar_id != row.get("calendar_id")
        or candidate.calendar_version != row.get("calendar_version")
        or candidate.calendar_fingerprint != row.get("calendar_fingerprint")
        or candidate.epoch_id != row.get("epoch_id")
        or candidate.slot_index != row.get("slot_index")
        or candidate.slot_id != row.get("slot_id")
        or candidate.readiness != row.get("readiness")
        or candidate.key.close_time != row.get("close_time")
        or candidate.source_members != members
        or len(candidate.target_ids) != 2
        or len(set(candidate.target_ids)) != 2
        or not set(candidate.target_ids).issubset(set(member_ids))
        or set(target_positions) != set(candidate.target_ids)
        or tuple(target_positions.get(target) for target in candidate.target_ids)
        != candidate.directions
    ):
        raise RunnerError("FEE_PAIR_TAPE_CANDIDATE_PROJECTION_MISMATCH")
    return members


def _fee_pair_source_receipt_from_tape_row(row, candidate, journal_api):
    members = _validate_fee_pair_candidate_projection(candidate, row, journal_api)
    try:
        # The row carries the physical source projection and strict-reader IDs.
        # The v17 predecessor/restart objects are not columns in the v2 tape
        # schema; copy those candidate-bound values and let Journal's public
        # attach API verify the complete typed receipt against its reserved row.
        receipt = journal_api.ExecutionSourceReceipt(
            source_kind=candidate.source_kind,
            cohort_id=row["cohort_id"],
            calendar_id=row["calendar_id"],
            calendar_version=row["calendar_version"],
            calendar_fingerprint=row["calendar_fingerprint"],
            epoch_id=row["epoch_id"],
            slot_index=row["slot_index"],
            slot_id=row["slot_id"],
            close_time=row["close_time"],
            batch_id=row["batch_id"],
            readiness=row["readiness"],
            tape_file_id=row["file_id"],
            tape_record_id=row["record_id"],
            tape_record_index=row["record_index"],
            members=members,
            predecessor=candidate.source_predecessor,
            restart_marker=candidate.source_restart_marker,
        )
    except (
        KeyError,
        TypeError,
        ValueError,
        journal_api.ExecutionDecisionJournalError,
    ) as error:
        code = getattr(error, "code", None)
        raise RunnerError(
            "FEE_PAIR_TAPE_SOURCE_RECEIPT_INVALID",
            code if type(code) is str else None,
        ) from None
    if (
        receipt.source_kind != candidate.source_kind
        or receipt.cohort_id != row.get("cohort_id")
        or receipt.calendar_id != row.get("calendar_id")
        or receipt.calendar_version != row.get("calendar_version")
        or receipt.calendar_fingerprint != row.get("calendar_fingerprint")
        or receipt.epoch_id != row.get("epoch_id")
        or receipt.slot_index != row.get("slot_index")
        or receipt.slot_id != row.get("slot_id")
        or receipt.close_time != row.get("close_time")
        or receipt.batch_id != row.get("batch_id")
        or receipt.readiness != row.get("readiness")
        or receipt.tape_file_id != row.get("file_id")
        or receipt.tape_record_id != row.get("record_id")
        or receipt.tape_record_index != row.get("record_index")
        or receipt.members != members
        or receipt.predecessor != candidate.source_predecessor
        or receipt.restart_marker != candidate.source_restart_marker
    ):
        raise RunnerError("FEE_PAIR_TAPE_SOURCE_RECEIPT_MISMATCH")
    return receipt


def iter_decision_tape(
    path: Path,
    *,
    max_bytes: int,
    max_record_bytes: Optional[int] = None,
    _raw_hasher=None,
):
    """Read and verify one JSONL record at a time under the declared byte cap."""
    if type(max_bytes) is not int or max_bytes < 1:
        raise RunnerError("DECISION_TAPE_BYTE_BUDGET_INVALID")
    if max_record_bytes is not None and (type(max_record_bytes) is not int or max_record_bytes < 1):
        raise RunnerError("DECISION_TAPE_RECORD_BYTE_LIMIT_INVALID")
    if _raw_hasher is not None and not callable(getattr(_raw_hasher, "update", None)):
        raise RunnerError("DECISION_TAPE_HASHER_INVALID")
    try:
        if path.stat().st_size > max_bytes:
            raise RunnerError("DECISION_TAPE_BYTE_BUDGET_EXCEEDED")
        handle = path.open("rb")
    except OSError:
        raise RunnerError("DECISION_TAPE_READ_FAILED") from None
    with handle:
        total = 0
        index = 0
        header_seen = False
        tape_schema = None
        file_id = None
        targets = None
        header_record_id = None
        selection_evidence_sha256 = None
        require_header_binding = False
        while True:
            read_size = max_bytes - total + 1
            if max_record_bytes is not None:
                read_size = min(read_size, max_record_bytes + 1)
            raw = handle.readline(read_size)
            if not raw:
                break
            if _raw_hasher is not None:
                _raw_hasher.update(raw)
            if max_record_bytes is not None and len(raw) > max_record_bytes:
                raise RunnerError("DECISION_TAPE_RECORD_BYTE_LIMIT_EXCEEDED")
            total += len(raw)
            if total > max_bytes:
                if max_record_bytes is None:
                    raise RunnerError("DECISION_TAPE_RECORD_INVALID")
                raise RunnerError("DECISION_TAPE_BYTE_BUDGET_EXCEEDED")
            if not raw.endswith(b"\n"):
                raise RunnerError("DECISION_TAPE_RECORD_INVALID")
            try:
                row = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                raise RunnerError("DECISION_TAPE_RECORD_INVALID") from None
            if not isinstance(row, dict):
                raise RunnerError("DECISION_TAPE_RECORD_INVALID")
            record_id = row.pop("record_id", None)
            expected = hashlib.sha256(_canonical_json_bytes(row).rstrip(b"\n")).hexdigest()
            row["record_id"] = record_id
            if type(record_id) is not str or record_id != expected:
                raise RunnerError("DECISION_TAPE_RECORD_HASH_INVALID")
            if not header_seen:
                tape_schema = row.get("schema")
                if (
                    row.get("record_type") != "HEADER"
                    or tape_schema not in (LEGACY_DECISION_TAPE_SCHEMA, DECISION_TAPE_SCHEMA)
                    or (
                        tape_schema == DECISION_TAPE_SCHEMA
                        and row.get("origin_partition_schema") != SOURCE_ORIGIN_PARTITION_SCHEMA
                    )
                    or (
                        tape_schema == LEGACY_DECISION_TAPE_SCHEMA
                        and "origin_partition_schema" in row
                    )
                ):
                    raise RunnerError("DECISION_TAPE_HEADER_INVALID")
                file_id = row.get("file_id")
                targets = row.get("targets")
                header_record_id = record_id
                if type(file_id) is not str or type(targets) is not list or not targets:
                    raise RunnerError("DECISION_TAPE_HEADER_INVALID")
                if len(targets) != len(set(targets)) or tuple(targets) != tuple(sorted(targets)):
                    raise RunnerError("DECISION_TAPE_HEADER_INVALID")
                if "selection_evidence" in row:
                    selection_evidence = _validate_selection_evidence(row["selection_evidence"])
                    if row.get("source_snapshot_id") != selection_evidence["source_snapshot_id"]:
                        raise RunnerError("DECISION_TAPE_HEADER_INVALID")
                    selection_evidence_sha256 = selection_evidence["binding_sha256"]
                    require_header_binding = (
                        selection_evidence["selection_source"]
                        == "ctp_query_snapshot_equal_weight_v1"
                    )
                header_seen = True
            else:
                index += 1
                if (
                    row.get("record_type") != "DECISION"
                    or row.get("schema") != tape_schema
                    or row.get("file_id") != file_id
                    or row.get("record_index") != index
                    or set(row.get("members", {})) != set(targets)
                ):
                    raise RunnerError("DECISION_TAPE_RECORD_INVALID")
                if "header_record_id" in row:
                    if row["header_record_id"] != header_record_id:
                        raise RunnerError("DECISION_TAPE_HEADER_BINDING_MISMATCH")
                elif require_header_binding:
                    raise RunnerError("DECISION_TAPE_HEADER_BINDING_REQUIRED")
                if selection_evidence_sha256 is None:
                    if "selection_evidence_sha256" in row:
                        raise RunnerError("DECISION_TAPE_SELECTION_EVIDENCE_MISMATCH")
                elif row.get("selection_evidence_sha256") != selection_evidence_sha256:
                    raise RunnerError("DECISION_TAPE_SELECTION_EVIDENCE_MISMATCH")
            yield MappingProxyType(row)
    if not header_seen:
        raise RunnerError("DECISION_TAPE_HEADER_MISSING")


def _new_decision_tape(
    config,
    config_path,
    plan,
    *,
    mode,
    factor_mode,
    direction,
    source_snapshot_id,
    restart_identity=None,
    selection_evidence=None,
    calendar_fingerprint=None,
):
    raw_path = config["output"]["decision_tape_path"]
    raw_budget = config["output"]["decision_tape_max_bytes"]
    if raw_path is None or raw_budget is None:
        raise RunnerError("DECISION_TAPE_PROFILE_REQUIRED")
    if type(raw_budget) is not int or raw_budget < 1:
        raise RunnerError("DECISION_TAPE_BYTE_BUDGET_INVALID")
    path = _resolve_path(config_path, raw_path, "output.decision_tape_path")
    return DecisionTapeWriter(
        path,
        raw_budget,
        mode=mode,
        factor_mode=factor_mode,
        direction=direction,
        targets=tuple(plan["targets"]),
        calendar_id=config["cohort"]["calendar_id"],
        grid_sha256=getattr(plan["grid"], "evidence_sha256", None),
        source_snapshot_id=source_snapshot_id,
        restart_identity=restart_identity,
        selection_evidence=selection_evidence,
        calendar_fingerprint=calendar_fingerprint,
    )


def _live_restart_identity(config, config_path, plan, *, factor_mode, direction, simnow_profile):
    """Bind a saved live tape to the exact public run/journal continuation scope."""
    cohort = config["cohort"]
    live = config["live"]
    risk = config["risk"]
    epoch_id = cohort["epoch_id"]
    if type(epoch_id) is not int or epoch_id < 1:
        raise RunnerError("LIVE_HISTORY_EPOCH_INVALID")
    scope_hashes = {
        name: hashlib.sha256(_text(live[name], "live." + name).encode("utf-8")).hexdigest()
        for name in ("account_scope", "strategy_scope", "logical_run_id")
    }
    journal_path = _resolve_path(config_path, live["journal_path"], "live.journal_path")
    identity = {
        "schema": "backtrader.alpha003.live_restart_identity.v1",
        "epoch_id": epoch_id,
        "mode": "live",
        "factor_mode": factor_mode,
        "direction": direction,
        "scope_sha256": scope_hashes,
        "journal_path_sha256": hashlib.sha256(str(journal_path).encode("utf-8")).hexdigest(),
        "selection_source": plan.get("selection_source"),
        "source_snapshot_id": plan.get("source_snapshot_id"),
        "targets": sorted(plan["targets"]),
        "authorized_targets": sorted(plan["authorized_targets"]),
        "routes": {
            target: plan["routes"][plan["product_by_target"][target]]
            for target in sorted(plan["targets"])
        },
        "calendar": {
            "calendar_id": _text(cohort["calendar_id"], "cohort.calendar_id"),
            "calendar_version": _text(cohort["calendar_version"], "cohort.calendar_version"),
            "calendar_rules_sha256": plan.get("calendar_rules_sha256"),
            "grid_sha256": getattr(plan["grid"], "evidence_sha256", None),
            "clock_domain_id": _text(cohort["clock_domain_id"], "cohort.clock_domain_id"),
            "timezone_id": _text(cohort["timezone_id"], "cohort.timezone_id"),
            "session_semantics": _text(cohort["session_semantics"], "cohort.session_semantics"),
            "frequency": "1min",
        },
        "simnow_profile": {
            "verified": simnow_profile.get("verified"),
            "environment": simnow_profile.get("environment"),
            "profile": simnow_profile.get("profile"),
        },
        "risk": {name: risk[name] for name in ("policy_id", *RISK_FIELDS)},
    }
    if plan.get("golden_targets") is not None:
        identity.update(
            {
                "full_selected_targets": sorted(plan["full_selected_targets"]),
                "active_shadow_targets": sorted(plan["active_shadow_targets"]),
                "full_authorized_targets": sorted(plan["full_authorized_targets"]),
                "full_routes": _full_route_summary(plan),
                "full_grid_semantics_sha256": _grid_semantics_sha256(plan["full_grid"]),
                "active_grid_semantics_sha256": _grid_semantics_sha256(plan["grid"]),
            }
        )
    _canonical_json_bytes(identity)
    return identity


def _selection_evidence_matches_identity(evidence, identity):
    if "active_shadow_targets" in evidence:
        return bool(
            evidence["epoch_id"] == identity.get("epoch_id")
            and evidence["selection_source"] == identity.get("selection_source")
            and evidence["source_snapshot_id"] == identity.get("source_snapshot_id")
            and evidence["routes"] == identity.get("full_routes")
            and evidence["authorized_targets"] == identity.get("full_authorized_targets")
            and evidence["full_selected_targets"] == identity.get("full_selected_targets")
            and evidence["active_shadow_targets"] == identity.get("active_shadow_targets")
            and evidence["active_routes"] == identity.get("routes")
            and evidence["active_authorized_targets"] == identity.get("authorized_targets")
            and evidence["grid_semantics_sha256"] == identity.get("full_grid_semantics_sha256")
            and evidence["active_grid_semantics_sha256"]
            == identity.get("active_grid_semantics_sha256")
        )
    return bool(
        evidence["epoch_id"] == identity.get("epoch_id")
        and evidence["selection_source"] == identity.get("selection_source")
        and evidence["source_snapshot_id"] == identity.get("source_snapshot_id")
        and evidence["routes"] == identity.get("routes")
        and sorted(evidence["routes"]) == identity.get("targets")
        and sorted(evidence["authorized_targets"]) == identity.get("authorized_targets")
    )


def _load_saved_live_history(
    config,
    config_path,
    plan,
    *,
    restart_identity,
    selection_evidence=None,
    now,
    journal=None,
    scopes=None,
    source_kind="ALPHA003_GRID",
):
    """Stream-verify a prior decision tape and retain only one bounded warmup window."""
    raw_path = config["inputs"].get("history_decision_tape")
    if raw_path is None:
        return None
    selection_source = config["selection"]["source"]
    query_selection = selection_source == "ctp_query"
    if selection_source not in {"bundle", "ctp_query"} or config["selection"]["daily_bundles"]:
        raise RunnerError("LIVE_HISTORY_SELECTION_UNSUPPORTED")
    if query_selection:
        if selection_evidence is None:
            raise RunnerError("LIVE_HISTORY_SELECTION_EVIDENCE_INVALID")
        selection_evidence = _validate_selection_evidence(selection_evidence)
        if (
            selection_evidence["selection_source"] != "ctp_query_snapshot_equal_weight_v1"
            or not _selection_evidence_matches_identity(selection_evidence, restart_identity)
        ):
            raise RunnerError("LIVE_HISTORY_SELECTION_EVIDENCE_INVALID")
    elif selection_evidence is not None:
        selection_evidence = _validate_selection_evidence(selection_evidence)
        if not _selection_evidence_matches_identity(selection_evidence, restart_identity):
            raise RunnerError("LIVE_HISTORY_SELECTION_EVIDENCE_INVALID")
    source_path = _resolve_path(config_path, raw_path, "inputs.history_decision_tape")
    output_path = _resolve_path(
        config_path, config["output"]["decision_tape_path"], "output.decision_tape_path"
    )
    journal_path = _resolve_path(config_path, config["live"]["journal_path"], "live.journal_path")
    if source_path in {output_path, journal_path}:
        raise RunnerError("LIVE_HISTORY_PATH_CONFLICT")
    preheat_bars = config["factor"]["preheat_bars"]
    if type(preheat_bars) is not int or preheat_bars < 1:
        raise RunnerError("LIVE_HISTORY_WARMUP_INVALID")
    now = _aware_datetime(now, "live history cutover time")
    future_slots = _remaining_live_grid_minutes(plan["grid"], now)
    if not future_slots:
        raise RunnerError("LIVE_HISTORY_GRID_WINDOW_UNAVAILABLE")
    if journal is None or not isinstance(scopes, Mapping):
        raise RunnerError("LIVE_HISTORY_SOURCE_JOURNAL_REQUIRED")
    source_highwater = journal.source_highwater(
        scopes["account_scope"],
        scopes["strategy_scope"],
        scopes["logical_run_id"],
        source_kind,
    )
    if source_highwater is None:
        raise RunnerError("LIVE_HISTORY_SOURCE_HIGHWATER_MISSING")
    slot_by_close = {minute.close_time: minute for minute in plan["grid"].minutes}
    target_set = tuple(sorted(plan["targets"]))
    tail = deque(maxlen=preheat_bars)
    previous_close = None
    previous_slot_index = None
    previous_batch_id = None
    previous_sequences = {}
    generations = {}
    previous_origin_partitions = {}
    previous_origin_sequences = {}
    previous_source_roles = {}
    source_cohort_id = None
    source_epoch_id = None
    historical_grid_cursor = None
    source_calendar_fingerprint = None
    header = None
    tape_schema = None
    record_count = 0
    latest_grid_anchor = None
    iterator = iter_decision_tape(
        source_path, max_bytes=config["output"]["decision_tape_max_bytes"]
    )
    for row in iterator:
        if header is None:
            header = row
            tape_schema = row["schema"]
            source_calendar_fingerprint = row.get("calendar_fingerprint")
            if (
                type(source_calendar_fingerprint) is not str
                or len(source_calendar_fingerprint) != 64
                or any(ch not in "0123456789abcdef" for ch in source_calendar_fingerprint)
            ):
                raise RunnerError("LIVE_HISTORY_HEADER_CALENDAR_FINGERPRINT_INVALID")
            identity = row.get("restart_identity")
            if not isinstance(identity, Mapping):
                raise RunnerError("LIVE_HISTORY_IDENTITY_REQUIRED")
            try:
                _exact_keys(identity, set(restart_identity), "live history identity")
            except RunnerError:
                raise RunnerError("LIVE_HISTORY_IDENTITY_INVALID") from None
            old_epoch = identity.get("epoch_id")
            current_epoch = restart_identity["epoch_id"]
            if type(old_epoch) is not int or old_epoch < 1 or old_epoch >= current_epoch:
                raise RunnerError("LIVE_HISTORY_EPOCH_INVALID")
            if (
                row.get("mode") != "live"
                or row.get("factor_mode") != restart_identity["factor_mode"]
            ):
                raise RunnerError("LIVE_HISTORY_MODE_MISMATCH")
            old_selection_evidence = row.get("selection_evidence")
            if query_selection and old_selection_evidence is None:
                raise RunnerError("LIVE_HISTORY_SELECTION_EVIDENCE_INVALID")
            if old_selection_evidence is not None:
                old_selection_evidence = _validate_selection_evidence(old_selection_evidence)
                if not _selection_evidence_matches_identity(old_selection_evidence, identity):
                    raise RunnerError("LIVE_HISTORY_SELECTION_EVIDENCE_INVALID")
                if query_selection:
                    if (
                        old_selection_evidence["selection_source"]
                        != "ctp_query_snapshot_equal_weight_v1"
                    ):
                        raise RunnerError("LIVE_HISTORY_SELECTION_EVIDENCE_INVALID")
                    if _query_history_selection_projection(
                        old_selection_evidence
                    ) != _query_history_selection_projection(selection_evidence):
                        raise RunnerError("LIVE_HISTORY_SELECTION_MISMATCH")
            header_targets = row.get("targets")
            if (
                type(header_targets) is not list
                or tuple(header_targets) != target_set
                or row.get("calendar_id") != config["cohort"]["calendar_id"]
                or row.get("direction") != identity.get("direction")
                or row.get("source_snapshot_id") != identity.get("source_snapshot_id")
                or row.get("grid_sha256") != identity.get("calendar", {}).get("grid_sha256")
            ):
                raise RunnerError("LIVE_HISTORY_HEADER_MISMATCH")
            same_query_source = (
                query_selection
                and identity.get("selection_source") == "ctp_query_snapshot_equal_weight_v1"
                and restart_identity.get("selection_source")
                == "ctp_query_snapshot_equal_weight_v1"
            )
            for name, expected in restart_identity.items():
                if name == "epoch_id" or (name == "source_snapshot_id" and same_query_source):
                    continue
                if name == "calendar" and same_query_source:
                    old_calendar = dict(identity[name])
                    current_calendar = dict(expected)
                    old_calendar.pop("grid_sha256", None)
                    current_calendar.pop("grid_sha256", None)
                    if _canonical_json_bytes(old_calendar) != _canonical_json_bytes(
                        current_calendar
                    ):
                        raise RunnerError("LIVE_HISTORY_IDENTITY_MISMATCH")
                    continue
                if _canonical_json_bytes(identity[name]) != _canonical_json_bytes(expected):
                    raise RunnerError("LIVE_HISTORY_IDENTITY_MISMATCH")
            source_epoch_id = old_epoch
            source_cohort_id = "alpha003:{}:{}".format(config["cohort"]["calendar_id"], old_epoch)
            historical_grid_cursor = journal.grid_cursor(
                scopes["account_scope"],
                scopes["strategy_scope"],
                source_cohort_id,
            )
            continue

        record_count += 1
        close_time = _aware_datetime(row.get("close_time"), "saved decision close_time")
        if previous_close is not None and close_time <= previous_close:
            raise RunnerError("LIVE_HISTORY_ORDER_INVALID")
        previous_close = close_time
        if close_time > now or close_time not in slot_by_close:
            raise RunnerError("LIVE_HISTORY_OUTSIDE_CURRENT_GRID")
        minute = slot_by_close[close_time]
        slot_index = row.get("slot_index")
        batch_id = row.get("batch_id")
        decision_available_at = _aware_datetime(
            row.get("available_at"), "saved decision available_at"
        )
        if type(slot_index) is not int or slot_index < 0:
            raise RunnerError("LIVE_HISTORY_SLOT_IDENTITY_INVALID")
        if previous_slot_index is not None and slot_index != previous_slot_index + 1:
            raise RunnerError("LIVE_HISTORY_SLOT_SEQUENCE_INVALID")
        expected_batch_id = "{}:{}:{}:{}:{}".format(
            source_cohort_id,
            config["cohort"]["calendar_id"],
            source_epoch_id,
            config["cohort"]["calendar_version"],
            slot_index,
        )
        if type(batch_id) is not str or batch_id != expected_batch_id:
            raise RunnerError("LIVE_HISTORY_BATCH_ID_INVALID")
        if batch_id == previous_batch_id:
            raise RunnerError("LIVE_HISTORY_BATCH_ID_INVALID")
        if decision_available_at < close_time or decision_available_at > now:
            raise RunnerError("LIVE_HISTORY_AVAILABILITY_INVALID")
        previous_slot_index = slot_index
        previous_batch_id = batch_id
        readiness = row.get("readiness")
        if (
            row.get("epoch_id") != source_epoch_id
            or type(row.get("epoch_id")) is not int
            or row.get("cohort_id") != source_cohort_id
            or row.get("calendar_id") != config["cohort"]["calendar_id"]
            or row.get("calendar_version") != config["cohort"]["calendar_version"]
            or type(row.get("calendar_fingerprint")) is not str
            or len(row.get("calendar_fingerprint")) != 64
            or row.get("calendar_fingerprint") != source_calendar_fingerprint
            or row.get("slot_id") != f"minute:{close_time.isoformat()}"
            or type(readiness) is not str
            or readiness not in {
                "INITIALIZING", "WARMUP", "CATCHING_UP", "LIVE_READY", "DEGRADED"
            }
        ):
            raise RunnerError("LIVE_HISTORY_RECORD_IDENTITY_INVALID")
        members = row.get("members")
        if not isinstance(members, Mapping) or set(members) != set(target_set):
            raise RunnerError("LIVE_HISTORY_MEMBER_SET_INVALID")
        event_rows = {}
        event_source_roles = {}
        for target in target_set:
            member = members[target]
            expected_member_keys = {
                "cohort_id", "calendar_id", "epoch_id", "slot_index", "slot_id", "instrument",
                "source_ref", "source_role", "connection_generation", "feed_sequence",
                "bucket_start", "close_time", "available_at", "trading_day", "session_segment",
                "timezone_id", "clock_domain_id", "bar_id", "complete", "quality", "present",
                "quality_flags", "missing_fields", "rules_hash", "event_source",
                "received_monotonic_ns", "raw_values",
            }
            if tape_schema == DECISION_TAPE_SCHEMA:
                expected_member_keys.add("origin_partition")
            try:
                _exact_keys(member, expected_member_keys, "saved history member")
            except RunnerError:
                raise RunnerError("LIVE_HISTORY_MEMBER_INVALID") from None
            instrument = plan["routes"][plan["product_by_target"][target]]
            source_ref = "ctp-live:{}:{}".format(target, instrument)
            product = plan["product_by_target"][target]
            planned_member = next(item for item in minute.members if item.product == product)
            bucket_start = _aware_datetime(member["bucket_start"], "saved history bucket_start")
            member_close = _aware_datetime(member["close_time"], "saved history member close_time")
            available_at = _aware_datetime(member["available_at"], "saved history available_at")
            day = _iso_date(member["trading_day"], "saved history trading_day")
            source_role = member["source_role"]
            generation = member["connection_generation"]
            sequence = member["feed_sequence"]
            bar_id = member["bar_id"]
            if tape_schema == DECISION_TAPE_SCHEMA:
                origin_partition = _tape_origin_partition(member["origin_partition"], target)
            elif source_role == "live":
                # A legacy live row's original partition is uniquely recoverable
                # from its exact, journal-anchored current source identity.
                origin_partition = {
                    "schema": SOURCE_ORIGIN_PARTITION_SCHEMA,
                    "cohort_id": source_cohort_id,
                    "epoch_id": source_epoch_id,
                    "member_id": target,
                    "source_ref": source_ref,
                    "source_role": "live",
                    "connection_generation": generation,
                }
            else:
                # Legacy history rows have already discarded their origin role
                # and generation partition. Only fail if one enters the bounded
                # restored tail; older rows remain validation context.
                origin_partition = None
            if source_role not in ("history", "live"):
                raise RunnerError("LIVE_HISTORY_SOURCE_ROLE_INVALID", target)
            if (
                member["cohort_id"] != source_cohort_id
                or member["calendar_id"] != config["cohort"]["calendar_id"]
                or member["epoch_id"] != source_epoch_id
                or type(member["slot_index"]) is not int
                or member["slot_index"] != slot_index
                or member["slot_id"] != f"minute:{close_time.isoformat()}"
                or member["instrument"] != instrument
                or member["source_ref"] != source_ref
                or isinstance(generation, bool)
                or not isinstance(generation, (str, int))
                or generation in ("", 0)
                or type(sequence) is not int
                or sequence < 1
                or type(bar_id) is not str
                or not bar_id
                or member_close != close_time
                or bucket_start != minute.close_time - timedelta(minutes=1)
                or close_time != minute.close_time
                or available_at < close_time
                or available_at > decision_available_at
                or day != planned_member.trading_day
                or member["session_segment"] != planned_member.session_id
                or member["timezone_id"] != config["cohort"]["timezone_id"]
                or member["clock_domain_id"] != config["cohort"]["clock_domain_id"]
                or member["complete"] is not True
                or member["present"] is not True
                or member["quality"] != "GOOD"
                or type(member["quality_flags"]) is not list
                or member["quality_flags"] not in ([], ["LEGACY_SCHEMA"])
                or type(member["missing_fields"]) is not list
                or member["missing_fields"] != []
                or (
                    member["rules_hash"] is not None
                    and (
                        type(member["rules_hash"]) is not str
                        or len(member["rules_hash"]) != 64
                        or any(ch not in "0123456789abcdef" for ch in member["rules_hash"])
                    )
                )
                or type(member["event_source"]) is not str
                or type(member["raw_values"]) is not dict
                or set(member["raw_values"]) != set(OHLCV_FIELDS)
            ):
                raise RunnerError("LIVE_HISTORY_MEMBER_INVALID", target)
            previous_role = previous_source_roles.get(target)
            if previous_role == "live" and source_role != "live":
                raise RunnerError("LIVE_HISTORY_SOURCE_ROLE_ORDER_INVALID", target)
            if origin_partition is not None:
                origin_role = origin_partition["source_role"]
                origin_epoch = origin_partition["epoch_id"]
                if (
                    origin_partition["cohort_id"] == ""
                    or origin_partition["source_ref"] != source_ref
                    or origin_partition["connection_generation"] != generation
                    or origin_epoch > source_epoch_id
                    or (
                        origin_epoch == source_epoch_id
                        and (
                            origin_partition["cohort_id"] != source_cohort_id
                            or origin_role != source_role
                        )
                    )
                    or (origin_epoch < source_epoch_id and origin_partition["cohort_id"] == source_cohort_id)
                    or (source_role == "live" and origin_role != "live")
                ):
                    raise RunnerError("LIVE_HISTORY_ORIGIN_PARTITION_INVALID", target)
            previous_partition = previous_origin_partitions.get(target)
            if origin_partition is not None:
                if previous_partition is not None:
                    if not _origin_partition_follows(previous_partition, origin_partition):
                        raise RunnerError("LIVE_HISTORY_ORIGIN_PARTITION_ORDER_INVALID", target)
                    if (
                        dict(previous_partition) == dict(origin_partition)
                        and sequence <= previous_origin_sequences[target]
                    ):
                        raise RunnerError("LIVE_HISTORY_SEQUENCE_INVALID", target)
                previous_origin_partitions[target] = origin_partition
                previous_origin_sequences[target] = sequence
            else:
                role_key = (target, source_role)
                if role_key in generations and generations[role_key] != generation:
                    raise RunnerError("LIVE_HISTORY_GENERATION_CHANGED", target)
                prior_sequence = previous_sequences.get(role_key)
                if prior_sequence is not None and sequence <= prior_sequence:
                    raise RunnerError("LIVE_HISTORY_SEQUENCE_INVALID", target)
                generations[role_key] = generation
                previous_sequences[role_key] = sequence
            previous_source_roles[target] = source_role
            values = {
                name: _number(member["raw_values"][name], "saved history " + target + "." + name)
                for name in OHLCV_FIELDS
            }
            if (
                min(values["open"], values["high"], values["low"], values["close"]) <= 0
                or values["high"] < max(values["open"], values["close"], values["low"])
                or values["low"] > min(values["open"], values["close"], values["high"])
                or values["volume"] < 0
                or values["openinterest"] < 0
            ):
                raise RunnerError("LIVE_HISTORY_OHLCV_INVALID", target)
            tape_anchor_identity = (
                row["file_id"],
                row["record_id"],
                row["record_index"],
                batch_id,
                source_cohort_id,
                source_epoch_id,
                row["calendar_id"],
                row["calendar_version"],
                row["calendar_fingerprint"],
                slot_index,
                row["slot_id"],
                close_time,
            )
            event_rows[target] = MappingProxyType(
                {
                    "instrument": instrument,
                    "symbol": instrument,
                    "exchange": product.exchange_id,
                    "source_ref": source_ref,
                    "timestamp": close_time.timestamp(),
                    "datetime": close_time,
                    "bucket_start": bucket_start,
                    "bucket_end": close_time,
                    "available_at": available_at,
                    "trading_day": day.strftime("%Y%m%d"),
                    "session_segment": member["session_segment"],
                    "timezone_id": member["timezone_id"],
                    "clock_domain_id": member["clock_domain_id"],
                    "connection_generation": generation,
                    "bar_sequence": sequence,
                    "bar_id": bar_id,
                    "rules_hash": member["rules_hash"],
                    "received_monotonic_ns": member["received_monotonic_ns"],
                    "origin_partition": (
                        None
                        if origin_partition is None
                        else MappingProxyType(dict(origin_partition))
                    ),
                    "present": True,
                    "complete": True,
                    "quality": "GOOD",
                    "quality_flags": tuple(member["quality_flags"]),
                    "missing_fields": tuple(member["missing_fields"]),
                    "source": member["event_source"],
                    "_saved_history_tape_anchor": tape_anchor_identity,
                    "_saved_history_record_source_role": source_role,
                    **values,
                }
            )
            event_source_roles[target] = source_role
        decision_reference = MappingProxyType(
            {
                "file_id": row["file_id"],
                "record_id": row["record_id"],
                "record_index": row["record_index"],
                "calendar_fingerprint": row["calendar_fingerprint"],
                "calendar_id": row["calendar_id"],
                "calendar_version": row["calendar_version"],
                "slot_index": row["slot_index"],
                "slot_id": row["slot_id"],
                "readiness": readiness,
                "members": members,
                "batch_id": batch_id,
                "close_time": close_time,
                "cohort_id": source_cohort_id,
                "epoch_id": source_epoch_id,
            }
        )
        if (
            historical_grid_cursor is not None
            and historical_grid_cursor.epoch_id == str(source_epoch_id)
            and historical_grid_cursor.batch_id == batch_id
            and _aware_datetime(historical_grid_cursor.close_time, "history grid cursor")
            == close_time
        ):
            latest_grid_anchor = decision_reference
        tail.append(
            (
                close_time,
                readiness,
                slot_index,
                batch_id,
                event_rows,
                event_source_roles,
                decision_reference,
            )
        )

    if header is None or not record_count:
        raise RunnerError("LIVE_HISTORY_RECORDS_MISSING")
    if len(tail) != preheat_bars:
        raise RunnerError("LIVE_HISTORY_WARMUP_NOT_CONTIGUOUS")
    if any(
        event["origin_partition"] is None
        for item in tail
        for event in item[4].values()
    ):
        raise RunnerError("LIVE_HISTORY_ORIGIN_PARTITION_UNPROVEN")
    if any(item[1] not in {"WARMUP", "CATCHING_UP", "LIVE_READY"} for item in tail):
        raise RunnerError("LIVE_HISTORY_TAIL_NOT_RESTORABLE")
    for target in target_set:
        events = tuple(item[4][target] for item in tail)
        if any(
            events[index]["bucket_end"] - events[index - 1]["bucket_end"] != timedelta(minutes=1)
            for index in range(1, len(events))
        ):
            raise RunnerError("LIVE_HISTORY_WARMUP_NOT_CONTIGUOUS", target)
        if len({(event["trading_day"], event["session_segment"]) for event in events}) != 1:
            raise RunnerError("LIVE_HISTORY_SESSION_CHANGED", target)
    last_reference = tail[-1][6]
    source_receipt = source_highwater.receipt
    if (
        source_highwater.account_scope != scopes["account_scope"]
        or source_highwater.strategy_scope != scopes["strategy_scope"]
        or source_highwater.logical_run_id != scopes["logical_run_id"]
        or source_receipt.cohort_id != source_cohort_id
        or source_receipt.calendar_id != config["cohort"]["calendar_id"]
        or source_receipt.calendar_version != config["cohort"]["calendar_version"]
        or source_receipt.epoch_id != source_epoch_id
        or source_receipt.tape_file_id != header["file_id"]
        or source_receipt.tape_record_id != last_reference["record_id"]
        or source_receipt.tape_record_index != record_count
        or source_receipt.batch_id != last_reference["batch_id"]
        or source_receipt.close_time != _json_time(last_reference["close_time"])
        or source_receipt.calendar_fingerprint != last_reference["calendar_fingerprint"]
    ):
        raise RunnerError("LIVE_HISTORY_SOURCE_HIGHWATER_MISMATCH")
    from backtrader.research.live_cohort import (
        LiveCohortJournalHighWater,
        LiveCohortJournalMemberHighWater,
    )

    calendar_highwater = LiveCohortJournalHighWater(
        cohort_id=source_receipt.cohort_id,
        calendar_id=source_receipt.calendar_id,
        calendar_version=source_receipt.calendar_version,
        calendar_fingerprint=source_receipt.calendar_fingerprint,
        epoch_id=source_receipt.epoch_id,
        slot_index=source_receipt.slot_index,
        slot_id=source_receipt.slot_id,
        close_time=_aware_datetime(source_receipt.close_time, "source high-water close_time"),
        batch_id=source_receipt.batch_id,
        members={
            member.member_id: LiveCohortJournalMemberHighWater(
                member_id=member.member_id,
                source_ref=member.source_ref,
                source_role=member.source_role,
                connection_generation=member.connection_generation,
                feed_sequence=member.feed_sequence,
                bar_id=member.bar_id,
                close_time=_aware_datetime(member.close_time, "source member close_time"),
                trading_day=member.trading_day,
                session_segment=member.session_segment,
            )
            for member in source_receipt.members
        },
    )
    decision_anchors = list(item[6] for item in tail)
    if latest_grid_anchor is not None and all(
        item["record_index"] != latest_grid_anchor["record_index"] for item in decision_anchors
    ):
        decision_anchors.append(latest_grid_anchor)
    return {
        "source_path": source_path,
        "source_file_id": header["file_id"],
        "source_epoch_id": source_epoch_id,
        "source_cohort_id": source_cohort_id,
        "record_count": record_count,
        "bar_count": preheat_bars,
        "first_bucket_start": tail[0][4][target_set[0]]["bucket_start"],
        "last_close_time": tail[-1][0],
        "last_batch_id": tail[-1][3],
        "decision_anchors": tuple(decision_anchors),
        "source_highwater": source_highwater,
        "calendar_highwater": calendar_highwater,
        "latest_grid_anchor": latest_grid_anchor,
        "bars_by_target": {
            target: tuple(item[4][target] for item in tail) for target in target_set
        },
    }


def _verify_saved_history_decision_anchors(journal, scopes, saved_history):
    """Bind every restored source row to its atomic GRID or SOURCE_ONLY record."""
    from backtrader.stores.execution_decision_journal import (
        ExecutionDecisionKey,
        ExecutionDecisionJournalError,
        ExecutionDecisionRecord,
        _source_receipt_from_values,
        _source_receipt_sha256,
    )
    from backtrader.research.live_cohort import (
        _SAVED_HISTORY_ANCHOR_EVENT_KEY,
        _make_verified_saved_history_journal_anchor,
    )

    verified_records = {}
    for anchor in saved_history["decision_anchors"]:
        close_time = anchor["close_time"].isoformat().replace("+00:00", "Z")
        key = ExecutionDecisionKey(
            account_scope=scopes["account_scope"],
            strategy_scope=scopes["strategy_scope"],
            logical_run_id=scopes["logical_run_id"],
            cohort_id=anchor["cohort_id"],
            close_time=close_time,
            decision_kind=saved_history["source_highwater"].source_kind,
        )
        record = journal.decision_for_key(key)
        if (
            not isinstance(record, ExecutionDecisionRecord)
            or record.key != key
            or not isinstance(record.economic_payload, Mapping)
        ):
            raise RunnerError("LIVE_HISTORY_JOURNAL_DECISION_ANCHOR_MISMATCH")
        payload = record.economic_payload
        receipt = payload.get("_execution_source_receipt")
        source_only = payload.get("_execution_source_anchor_only") is True
        grid_candidate = (
            anchor["readiness"] == "LIVE_READY"
            and all(member["source_role"] == "live" for member in anchor["members"].values())
            and all(
                member["complete"] is True
                and member["present"] is True
                and member["quality"] == "GOOD"
                and member["missing_fields"] == []
                and set(member["quality_flags"]).issubset({"LEGACY_SCHEMA"})
                for member in anchor["members"].values()
            )
        )
        if (
            not isinstance(receipt, Mapping)
            or (not source_only and payload.get("_execution_source_anchor_only") is not None)
            or (not source_only and not grid_candidate)
            or (source_only and record.intent_keys)
        ):
            raise RunnerError("LIVE_HISTORY_JOURNAL_DECISION_ANCHOR_MISMATCH")
        expected_source = {
            "source_kind": saved_history["source_highwater"].source_kind,
            "cohort_id": anchor["cohort_id"],
            "calendar_id": anchor["calendar_id"],
            "calendar_version": anchor["calendar_version"],
            "calendar_fingerprint": anchor["calendar_fingerprint"],
            "epoch_id": anchor["epoch_id"],
            "slot_index": anchor["slot_index"],
            "slot_id": anchor["slot_id"],
            "close_time": _json_time(anchor["close_time"]),
            "batch_id": anchor["batch_id"],
            "readiness": anchor["readiness"],
            "tape_file_id": anchor["file_id"],
            "tape_record_id": anchor["record_id"],
            "tape_record_index": anchor["record_index"],
        }
        if any(receipt.get(name) != expected for name, expected in expected_source.items()):
            raise RunnerError("LIVE_HISTORY_SOURCE_RECEIPT_MISMATCH")
        member_values = receipt.get("members")
        if type(member_values) not in (tuple, list) or len(member_values) != len(anchor["members"]):
            raise RunnerError("LIVE_HISTORY_SOURCE_RECEIPT_MISMATCH")
        expected_members = []
        for member_id, member in sorted(anchor["members"].items()):
            expected_member = {
                    "member_id": member_id,
                    "source_ref": member["source_ref"],
                    "source_role": member["source_role"],
                    "connection_generation": member["connection_generation"],
                    "feed_sequence": member["feed_sequence"],
                    "bar_id": member["bar_id"],
                    "bucket_start": member["bucket_start"],
                    "close_time": member["close_time"],
                    "available_at": member["available_at"],
                    "trading_day": member["trading_day"].replace("-", ""),
                    "session_segment": member["session_segment"],
                    "timezone_id": member["timezone_id"],
                    "clock_domain_id": member["clock_domain_id"],
                    "complete": member["complete"],
                    "quality": member["quality"],
                    "present": member["present"],
                    "missing_fields": tuple(member["missing_fields"]),
                    "quality_flags": tuple(member["quality_flags"]),
                    "event_source": member["event_source"],
                    "received_monotonic_ns": member["received_monotonic_ns"],
                    "rules_hash": member["rules_hash"],
                }
            if "origin_partition" in member:
                expected_member["origin_partition"] = dict(member["origin_partition"])
            expected_members.append(expected_member)
        if list(member_values) != expected_members:
            raise RunnerError("LIVE_HISTORY_SOURCE_RECEIPT_MISMATCH")
        if not source_only:
            expected_references = (
                ("decision_tape_file_id", "file_id"),
                ("decision_tape_record_id", "record_id"),
                ("decision_tape_record_index", "record_index"),
                ("decision_tape_batch_id", "batch_id"),
            )
            if (
                payload.get("batch_id") != anchor["batch_id"]
                or payload.get("epoch_id") != anchor["epoch_id"]
                or payload.get("decision_tape_status") != "DURABLE"
                or any(
                    payload.get(payload_key) != anchor[reference_key]
                    for payload_key, reference_key in expected_references
                )
            ):
                raise RunnerError("LIVE_HISTORY_JOURNAL_DECISION_ANCHOR_MISMATCH")
        try:
            typed_receipt = _source_receipt_from_values(receipt)
            receipt_sha256 = _source_receipt_sha256(typed_receipt)
        except (ExecutionDecisionJournalError, TypeError, ValueError, KeyError):
            raise RunnerError("LIVE_HISTORY_SOURCE_RECEIPT_MISMATCH") from None
        anchor_identity = (
            anchor["file_id"],
            anchor["record_id"],
            anchor["record_index"],
            anchor["batch_id"],
            anchor["cohort_id"],
            anchor["epoch_id"],
            anchor["calendar_id"],
            anchor["calendar_version"],
            anchor["calendar_fingerprint"],
            anchor["slot_index"],
            anchor["slot_id"],
            _aware_datetime(anchor["close_time"], "saved history anchor close_time"),
        )
        verified_records[anchor_identity] = {
            "decision_id": record.decision_id,
            "receipt_sha256": receipt_sha256,
            "receipt_members": {
                member["member_id"]: dict(member) for member in member_values
            },
            "anchor": anchor,
        }

    # Do not publish any row capability until every tail decision and member
    # receipt has passed the exact journal-to-tape checks above.
    verified_anchors = {}
    for target, events in saved_history["bars_by_target"].items():
        for event in events:
            anchor_identity = event.get(_SAVED_HISTORY_ANCHOR_EVENT_KEY)
            verified_record = verified_records.get(anchor_identity)
            if verified_record is None:
                raise RunnerError("LIVE_HISTORY_JOURNAL_DECISION_ANCHOR_MISMATCH")
            member_receipt = verified_record["receipt_members"].get(target)
            if member_receipt is None:
                raise RunnerError("LIVE_HISTORY_SOURCE_RECEIPT_MISMATCH")
            origin_partition = event.get("origin_partition")
            if not isinstance(origin_partition, Mapping):
                raise RunnerError("LIVE_HISTORY_ORIGIN_PARTITION_UNPROVEN", target)
            receipt_partition = member_receipt.get("origin_partition")
            if receipt_partition is None:
                # Old source receipts omitted this optional field. A live row's
                # origin is uniquely recoverable from its source cohort/epoch,
                # exact member/source and generation already checked above.
                if (
                    member_receipt.get("source_role") != "live"
                    or origin_partition.get("cohort_id")
                    != verified_record["anchor"]["cohort_id"]
                    or origin_partition.get("epoch_id")
                    != verified_record["anchor"]["epoch_id"]
                    or origin_partition.get("source_role") != "live"
                    or origin_partition.get("member_id") != member_receipt["member_id"]
                    or origin_partition.get("source_ref") != member_receipt["source_ref"]
                    or origin_partition.get("connection_generation")
                    != member_receipt["connection_generation"]
                ):
                    raise RunnerError("LIVE_HISTORY_ORIGIN_PARTITION_UNPROVEN", target)
            elif dict(receipt_partition) != dict(origin_partition):
                raise RunnerError("LIVE_HISTORY_SOURCE_RECEIPT_MISMATCH", target)
            anchor = verified_record["anchor"]
            facts = {
                "decision_id": verified_record["decision_id"],
                "receipt_sha256": verified_record["receipt_sha256"],
                "tape_file_id": anchor["file_id"],
                "tape_record_id": anchor["record_id"],
                "tape_record_index": anchor["record_index"],
                "batch_id": anchor["batch_id"],
                "source_cohort_id": anchor["cohort_id"],
                "source_epoch_id": anchor["epoch_id"],
                "calendar_id": anchor["calendar_id"],
                "calendar_version": anchor["calendar_version"],
                "calendar_fingerprint": anchor["calendar_fingerprint"],
                "slot_index": anchor["slot_index"],
                "slot_id": anchor["slot_id"],
                "close_time": anchor["close_time"],
                "member_receipt": member_receipt,
                "origin_partition": origin_partition,
            }
            verified_anchors[(anchor_identity, target)] = (
                _make_verified_saved_history_journal_anchor(**facts)
            )
    saved_history["verified_journal_anchors"] = MappingProxyType(verified_anchors)


def _decision_tape_readback(
    path: Path,
    max_bytes: int,
    *,
    expected_close_times: Optional[tuple[datetime, ...]] = None,
) -> Mapping[str, Any]:
    header = None
    count = 0
    last_reference = None
    for row in iter_decision_tape(path, max_bytes=max_bytes):
        if header is None:
            header = row
            continue
        if expected_close_times is not None:
            expected_index = count
            if expected_index >= len(expected_close_times) or row.get("close_time") != _json_time(
                expected_close_times[expected_index]
            ):
                raise RunnerError("DECISION_TAPE_GRID_COVERAGE_MISMATCH")
        count += 1
        last_reference = {
            "file_id": row["file_id"],
            "record_id": row["record_id"],
            "record_index": row["record_index"],
            "batch_id": row["batch_id"],
        }
    if header is None:
        raise RunnerError("DECISION_TAPE_HEADER_MISSING")
    if expected_close_times is not None and count != len(expected_close_times):
        raise RunnerError("DECISION_TAPE_GRID_COVERAGE_MISMATCH")
    return {
        "file_id": header["file_id"],
        "record_count": count,
        "last_record_reference": last_reference,
        "actual_bytes": path.stat().st_size,
    }


def _live_source_continuity_status(
    journal, scopes, decision_tape, strategy, source_kind="ALPHA003_GRID"
):
    """Project whether this run's fsynced tape is durably anchored through its tail."""

    tape = decision_tape.summary()
    record_count = tape.get("record_count")
    if type(record_count) is not int or record_count < 0:
        return {
            "status": "UNAVAILABLE",
            "available": False,
            "record_count": 0,
            "failure_count": 1,
            "first_error": "SOURCE_TAPE_COUNT_INVALID",
            "final_highwater_matches_tape": False,
        }
    if record_count == 0:
        return {
            "status": "NOT_APPLICABLE",
            "available": False,
            "record_count": 0,
            "failure_count": 0,
            "first_error": None,
            "final_highwater_matches_tape": None,
            "reason": "NO_ROWS",
        }

    strategy_failures = getattr(strategy, "source_continuity_failure_count", 0)
    first_error = getattr(strategy, "source_continuity_first_error", None)
    if type(strategy_failures) is not int or strategy_failures < 0:
        strategy_failures = 1
        first_error = "SOURCE_CONTINUITY_STATE_INVALID"
    if first_error is not None and first_error not in {
        "DURABLE_DECISION_COORDINATOR_UNAVAILABLE",
        "SOURCE_RECEIPT_BUILD_FAILED",
        "SOURCE_RECEIPT_WRITE_FAILED",
        "SOURCE_HIGHWATER_CONFIRMATION_FAILED",
    }:
        first_error = "SOURCE_CONTINUITY_STATE_INVALID"
        strategy_failures = max(strategy_failures, 1)

    highwater_read_error = False
    if journal is None:
        highwater = None
    else:
        try:
            highwater = journal.source_highwater(
                scopes["account_scope"],
                scopes["strategy_scope"],
                scopes["logical_run_id"],
                source_kind,
            )
        except Exception:
            highwater = None
            highwater_read_error = True
    last = tape.get("last_record_reference")
    receipt = None if highwater is None else highwater.receipt
    final_match = bool(
        highwater is not None
        and receipt is not None
        and highwater.anchor_kind in {"GRID", "SOURCE_ONLY"}
        and isinstance(last, Mapping)
        and tape.get("file_id") == decision_tape.file_id == receipt.tape_file_id
        and type(last.get("record_index")) is int
        and last.get("record_index") == record_count == receipt.tape_record_index
        and last.get("record_id") == receipt.tape_record_id
        and last.get("batch_id") == receipt.batch_id
        and receipt.calendar_fingerprint == decision_tape.calendar_fingerprint
    )
    if not final_match:
        strategy_failures += 1
        if first_error is None:
            if highwater_read_error:
                first_error = "SOURCE_HIGHWATER_FINAL_READ_FAILED"
            else:
                first_error = (
                    "SOURCE_HIGHWATER_MISSING"
                    if highwater is None
                    else "SOURCE_HIGHWATER_FINAL_MISMATCH"
                )
    available = strategy_failures == 0 and final_match
    return {
        "status": "AVAILABLE" if available else "UNAVAILABLE",
        "available": available,
        "record_count": record_count,
        "failure_count": strategy_failures,
        "first_error": first_error,
        "final_highwater_matches_tape": final_match,
    }


def _run_cerebro_with_decision_tape(
    cerebro,
    strategy_cls,
    strategy_kwargs,
    writer,
    *,
    expected_close_times=None,
):
    strategy = None
    primary_error = None
    primary_traceback = None
    close_error = None
    close_traceback = None
    try:
        strategy_kwargs["decision_tape"] = writer
        cerebro.addstrategy(strategy_cls, **strategy_kwargs)
        strategy = cerebro.run(runonce=False, preload=False)[0]
    except BaseException as error:
        primary_error = error
        primary_traceback = error.__traceback__
    try:
        writer.close()
    except BaseException as error:
        close_error = error
        close_traceback = error.__traceback__
    if primary_error is not None:
        raise primary_error.with_traceback(primary_traceback)
    if close_error is not None:
        raise close_error.with_traceback(close_traceback)
    readback = _decision_tape_readback(
        writer.path,
        writer.max_bytes,
        expected_close_times=expected_close_times,
    )
    if (
        readback["file_id"] != writer.file_id
        or readback["record_count"] != writer.summary()["record_count"]
    ):
        raise RunnerError("DECISION_TAPE_READBACK_MISMATCH")
    return strategy, writer.summary(), readback


def run_replay(config, config_path, plan, factor_mode, direction):
    import backtrader as bt
    from backtrader.brokers.factor_replay import CausalReplayBroker, ReplayBarTiming
    from backtrader.feeds.btapifeed import BtApiFeed
    from alpha003_strategy import Alpha003TargetStrategy

    risk_policy, starting_cash, commission = _require_replay_budgets(config)
    tape_path = _resolve_path(config_path, config["inputs"]["minute_tape"], "inputs.minute_tape")
    tape = load_minute_tape(tape_path, plan, config["cohort"])
    _check_tape_complete(plan, tape)
    quote_path = _resolve_path(
        config_path, config["inputs"]["execution_quotes"], "inputs.execution_quotes"
    )
    _quote_snapshot, replay_quotes = _quote_tape(quote_path, plan, config["cohort"])
    metadata_path = _resolve_path(
        config_path, config["inputs"]["instrument_metadata"], "inputs.instrument_metadata"
    )
    _metadata_snapshot, replay_instruments = _replay_instruments(metadata_path, plan)
    cohort = _make_cohort(config, plan["grid"])
    broker = CausalReplayBroker(cash=starting_cash)
    broker.setcommission(commission=commission)
    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    cerebro.setbroker(broker)
    data_by_target = {}
    for target in plan["targets"]:
        product = plan["product_by_target"][target]
        instrument = plan["routes"][product]
        events = tape["events"][target]
        feed = BtApiFeed(
            dataname=instrument,
            historical_bars=events,
            live_bars=(),
            backfill_start=False,
            cohort_source_mode=True,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
        )
        cerebro.adddata(feed, name=target)
        cohort.register_member(
            target,
            feed,
            instrument=instrument,
            source_ref=tape["source_ref"],
            line_fields=OHLCV_FIELDS,
            raw_fields=OHLCV_FIELDS,
            clock_domain_id=tape["clock_domain_id"],
            timezone_id=tape["timezone_id"],
            session_semantics=config["cohort"]["session_semantics"],
            numeric_fields=OHLCV_FIELDS,
        )
        timings = tuple(
            ReplayBarTiming(event["bucket_start"], event["bucket_end"], event["available_at"])
            for event in events
        )
        broker.bind_data_timing(feed, timings)
        data_by_target[target] = feed
    cohort.seal()
    availability_by_slot, late_quote_count = _replay_clock_schedule(
        plan["grid"], tape, replay_quotes
    )
    clock = ReplayTapeClock(availability_by_slot, cohort=cohort)
    cerebro.add_live_bar_cohort(cohort, clock=clock, winddown_timeout_seconds=0.0)
    run_id = f"replay-{tape['snapshot_id']}"
    decision_tape = _new_decision_tape(
        config,
        config_path,
        plan,
        mode="replay",
        factor_mode=factor_mode,
        direction=direction,
        source_snapshot_id=tape["snapshot_id"],
    )
    strategy_kwargs = _make_strategy_kwargs(
        config,
        plan,
        factor_mode,
        direction,
        risk_policy,
        replay=True,
        cohort=cohort,
        account_scope=f"local-replay:{run_id}",
        logical_run_id=run_id,
        replay_quotes=replay_quotes,
        replay_instruments=replay_instruments,
    )
    strategy, decision_tape_summary, decision_tape_readback = _run_cerebro_with_decision_tape(
        cerebro,
        Alpha003TargetStrategy,
        strategy_kwargs,
        decision_tape,
        expected_close_times=tuple(minute.close_time for minute in plan["grid"].minutes),
    )
    decision = getattr(strategy, "last_target_decision", None)
    factor_snapshot = strategy.live_factors.snapshot()
    factor_outputs = next(iter(factor_snapshot.factors.values())).values
    shutdown_ready = getattr(strategy, "shutdown_ready", False) is True
    shutdown_blocker = getattr(strategy, "shutdown_blocker", None)
    output = {
        "status": "REPLAY_COMPLETE" if shutdown_ready else "REPLAY_INCOMPLETE",
        "mode": "replay",
        "factor_mode": factor_mode,
        "snapshot_id": tape["snapshot_id"],
        "grid_sha256": plan["grid"].evidence_sha256
        if hasattr(plan["grid"], "evidence_sha256")
        else None,
        "target_count": len(plan["targets"]),
        "cohort_status": getattr(cohort.current_batch(), "status", None),
        "signal_block_reason": getattr(strategy, "last_signal_block_reason", None),
        "signal_status": getattr(decision, "status", None),
        "order_plan_status": getattr(getattr(strategy, "last_order_plan", None), "status", None),
        "order_plan_reason": getattr(getattr(strategy, "last_order_plan", None), "reason", None),
        "execution_block_reason": getattr(strategy, "last_execution_block_reason", None),
        "decision_close_time": _json_time(getattr(decision, "close_time", None)),
        "factor_readiness": getattr(
            factor_snapshot.readiness, "value", str(factor_snapshot.readiness)
        ),
        "factor_readiness_reasons": list(factor_snapshot.readiness_reasons),
        "factor_batch_complete": factor_snapshot.batch_complete,
        "factor_outputs": {
            target: {
                "status": getattr(row.status, "value", str(row.status)),
                "reason": row.reason,
                "source_role": row.source_role,
                "present": row.present,
                "complete": row.complete,
                "quality": row.quality,
                "finite": math.isfinite(row.value),
            }
            for target, row in factor_outputs.items()
        },
        "cash": broker.getcash(),
        "value": broker.getvalue(),
        "positions": {
            target: broker.getposition(feed).size for target, feed in data_by_target.items()
        },
        "orders": _replay_order_summary(broker, data_by_target, tape),
        "execution_mode": "LOCAL_BACKBROKER_CAUSAL_REPLAY",
        "shutdown_status": "PASS" if shutdown_ready else "BLOCKED",
        "shutdown_blocker": shutdown_blocker,
        "late_quote_count": late_quote_count,
        "decision_tape": decision_tape_summary,
        "decision_tape_readback": decision_tape_readback,
    }
    return output


def _json_time(value):
    return (
        value.astimezone(UTC).isoformat().replace("+00:00", "Z")
        if isinstance(value, datetime)
        else None
    )


def _replay_order_summary(broker, data_by_target, tape):
    """Expose ordinary BackBroker orders with their exact matched tape bars."""
    from backtrader.utils.dateintern import num2date

    target_by_feed = {id(feed): target for target, feed in data_by_target.items()}
    event_index = {target: tuple(tape["events"].get(target, ())) for target in data_by_target}
    summaries = []
    for order in getattr(broker, "orders", ()):
        target = target_by_feed.get(id(order.data))
        if target is None:
            continue
        cutoff = order.info.get("decision_available_at")
        executions = []
        for bit in getattr(order.executed, "exbits", ()):
            end = _aware_datetime(num2date(bit.dt, tz=UTC, naive=False), "replay execution label")
            matched = next(
                (
                    event
                    for event in event_index[target]
                    if abs((event["bucket_end"] - end).total_seconds()) <= 0.001
                ),
                None,
            )
            start = matched["bucket_start"] if matched is not None else None
            available = matched["available_at"] if matched is not None else None
            executions.append(
                {
                    "size": str(bit.size),
                    "price": str(bit.price),
                    "bar_start": _json_time(start),
                    "bar_end": _json_time(matched["bucket_end"]) if matched is not None else None,
                    "bar_available_at": _json_time(available),
                    "timing_verified": matched is not None,
                    "causal": (
                        matched is not None
                        and isinstance(cutoff, datetime)
                        and start >= _aware_datetime(cutoff, "decision_available_at")
                    ),
                }
            )
        summaries.append(
            {
                "ref": order.ref,
                "target": target,
                "instrument": order.info.get("instrument_id"),
                "exchange": order.info.get("exchange_id"),
                "side": "BUY" if order.isbuy() else "SELL",
                "position_effect": order.info.get("factor_position_effect"),
                "status": order.getstatusname().upper(),
                "decision_available_at": _json_time(cutoff),
                "quote_id": order.info.get("replay_quote_id"),
                "executed_size": str(order.executed.size),
                "executed_price": str(order.executed.price),
                "executions": executions,
            }
        )
    return summaries


class QueryRefreshLoop:
    """One serialized bounded Store-query caller for live fact freshness."""

    def __init__(
        self,
        store,
        broker,
        targets,
        *,
        execution_target_ids=None,
        commission_identity_by_target=None,
        commission_required_for_open=None,
        coordinator,
        account_scope,
        strategy_scope,
        clock,
        quote_max_age,
        max_query_age,
        timeout,
        overall_timeout,
        interval,
        cerebro,
        shutdown_grace_seconds,
    ):
        self.store = store
        self.broker = broker
        self.targets = tuple(targets)
        full_target_ids = tuple(getattr(target, "target_id", None) for target in self.targets)
        if any(
            type(target_id) is not str or not target_id or target_id != target_id.strip()
            for target_id in full_target_ids
        ) or len(set(full_target_ids)) != len(full_target_ids):
            raise RunnerError("LIVE_REFRESH_TARGETS_INVALID")
        if execution_target_ids is None:
            self.execution_target_ids = full_target_ids
        elif (
            type(execution_target_ids) is not tuple
            or not execution_target_ids
            or any(
                type(target_id) is not str or not target_id or target_id != target_id.strip()
                for target_id in execution_target_ids
            )
            or len(set(execution_target_ids)) != len(execution_target_ids)
            or not set(execution_target_ids).issubset(set(full_target_ids))
        ):
            raise RunnerError("LIVE_EXECUTION_TARGETS_INVALID")
        else:
            requested_execution_targets = set(execution_target_ids)
            self.execution_target_ids = tuple(
                target_id
                for target_id in full_target_ids
                if target_id in requested_execution_targets
            )
        execution_target_set = set(self.execution_target_ids)
        self._margin_targets = tuple(
            target for target in self.targets if target.target_id in execution_target_set
        )
        self.commission_identity_by_target = {
            target_id: dict(identity)
            for target_id, identity in (
                commission_identity_by_target.items()
                if isinstance(commission_identity_by_target, Mapping)
                else ()
            )
            if target_id in execution_target_set and isinstance(identity, Mapping)
        }
        if commission_required_for_open is None:
            self.commission_required_for_open = commission_identity_by_target is not None
        elif type(commission_required_for_open) is bool:
            self.commission_required_for_open = commission_required_for_open
        else:
            raise RunnerError("LIVE_COMMISSION_REQUIREMENT_INVALID")
        self._commission_targets = tuple(
            target
            for target in self.targets
            if target.target_id in self.commission_identity_by_target
            and type(self.commission_identity_by_target[target.target_id].get("account_id")) is str
            and bool(self.commission_identity_by_target[target.target_id].get("account_id"))
            and self.commission_identity_by_target[target.target_id].get("account_id")
            == self.commission_identity_by_target[target.target_id].get("account_id").strip()
            and self.commission_identity_by_target[target.target_id].get("invest_unit_id") == ""
        )
        self.coordinator = coordinator
        self.account_scope = account_scope
        self.strategy_scope = strategy_scope
        self.clock = clock
        self.quote_max_age = quote_max_age
        self.max_query_age = max_query_age
        self.timeout = timeout
        self.overall_timeout = overall_timeout
        self.interval = interval
        self.cerebro = cerebro
        self.shutdown_grace_seconds = shutdown_grace_seconds
        self._stop = threading.Event()
        self._refresh_wakeup = threading.Event()
        self._shutdown_event = threading.Event()
        self._interrupt_refresh = threading.Event()
        self._refresh_start_lock = threading.Lock()
        self._strategy_lock = threading.RLock()
        self._commission_target_lock = threading.Lock()
        self._commission_target_decision = None
        # Store query snapshots and Strategy projections share one
        # non-reentrant consistency boundary.  Strategy only probes it
        # nonblocking so an engine turn never waits for provider I/O.
        self._fact_snapshot_lock = threading.Lock()
        # Refreshers remain serialized while the projection lock is released
        # around the optional native fee query.  Strategy never takes this
        # lock, so a stalled sidecar cannot hide the last complete core view.
        self._refresh_serialization_lock = threading.Lock()
        self._fact_projection_waiting = threading.Event()
        self._projection_wake_error = None
        self._strategy = None
        self._shutdown_forwarded = False
        self._shutdown_deadline = None
        self.shutdown_status = "NOT_REQUESTED"
        self.shutdown_blocker = None
        self.shutdown_requested_at = None
        self.shutdown_completed_at = None
        self._thread = threading.Thread(
            target=self._run, name="alpha003-query-refresh", daemon=False
        )
        self.last_receipt = None
        self.last_facts = None
        self.last_error_code = None
        self.last_reconciliation_blockers = ()
        self._reconciliation_blockers_work = []
        self.joined = False
        self.started = False
        self._margin_index = 0
        self._commission_index = 0
        self._commission_priority_index = 0
        self._startup_recovery_scope_timeout = None
        self._startup_refresh_deadline = None
        # A scoped pass that does not complete must be retried under the same
        # durable dispatch fence.  This is only a bounded in-process hint;
        # durable DISPATCHING rows remain the source of truth after restart.
        self._dispatching_recovery_retry_pending = False

    def bind_strategy(self, strategy):
        with self._strategy_lock:
            if self._strategy is not None and self._strategy is not strategy:
                raise RunnerError("LIVE_STRATEGY_BINDING_CONFLICT")
            self._strategy = strategy

    def publish_commission_target_decision(self, decision):
        """Publish only the latest immutable live pair for fee-query priority."""

        snapshot = None
        try:
            targets = tuple(getattr(item, "target_id", None) for item in decision.targets)
            authorized = tuple(decision.authorized_targets)
            available_at = _aware_datetime(
                decision.available_at, "commission target decision time"
            )
            if (
                decision.status == "TARGETS_READY"
                and decision.execution_mode == "LIVE"
                and type(decision.batch_id) is str
                and bool(decision.batch_id)
                and len(targets) == 2
                and all(type(value) is str and value for value in targets)
                and len(set(targets)) == 2
                and len(authorized) == len(set(authorized))
                and all(type(value) is str and value for value in authorized)
            ):
                snapshot = (
                    self.execution_target_ids,
                    authorized,
                    targets,
                    available_at,
                    time.monotonic(),
                    decision.batch_id,
                )
        except (AttributeError, TypeError, ValueError, OverflowError):
            snapshot = None
        with self._commission_target_lock:
            previous = self._commission_target_decision
            if (
                snapshot is None
                or previous is None
                or snapshot[:3] != previous[:3]
            ):
                self._commission_priority_index = 0
            self._commission_target_decision = snapshot

    def _commission_priority_target_ids(self):
        """Read a fresh, same-grant selected pair without sharing mutable state."""

        with self._commission_target_lock:
            snapshot = self._commission_target_decision
        if snapshot is None:
            return ()
        captured_execution_ids, authorized, target_ids, available_at, published_at, _batch_id = (
            snapshot
        )
        execution_ids = self.execution_target_ids
        if (
            captured_execution_ids != execution_ids
            or frozenset(authorized) != frozenset(execution_ids)
            or not set(target_ids).issubset(set(execution_ids))
        ):
            return ()
        try:
            now = _aware_datetime(self.clock.utc_now(), "commission priority time")
            age = now - available_at
            monotonic_age = time.monotonic() - published_at
            max_age = float(self.quote_max_age.total_seconds())
        except (AttributeError, TypeError, ValueError, OverflowError):
            return ()
        if (
            age.total_seconds() < 0
            or age.total_seconds() > max_age
            or monotonic_age < 0
            or monotonic_age > max_age
        ):
            return ()
        return target_ids

    def _commission_query_is_fresh(self, target_id):
        facts = self.last_facts
        account = getattr(facts, "account", None) if facts is not None else None
        if account is None:
            return False
        matches = tuple(
            fact
            for fact in getattr(facts, "query_provenance", ())
            if getattr(fact, "family", None) == "instrument_commission_rate_result"
            and getattr(fact, "target_id", None) == target_id
        )
        if len(matches) != 1:
            return False
        fact = matches[0]
        completed_at = getattr(fact, "completed_at", None)
        if (
            getattr(fact, "source_owned", None) is not True
            or getattr(fact, "query_complete", None) is not True
            or type(getattr(fact, "request_id", None)) is not int
            or getattr(fact, "request_id", 0) <= 0
            or getattr(fact, "connection_generation", None)
            != getattr(account, "connection_generation", None)
            or getattr(fact, "trading_day", None) != getattr(account, "trading_day", None)
            or getattr(fact, "account_fingerprint", None)
            != getattr(account, "account_fingerprint", None)
            or completed_at is None
        ):
            return False
        try:
            now = _aware_datetime(self.clock.utc_now(), "commission freshness time")
            completed_at = _aware_datetime(completed_at, "commission completion time")
            max_age = min(
                float(self.max_query_age.total_seconds()),
                _LIVE_COMMISSION_CACHE_REFRESH_SECONDS,
            )
            age = (now - completed_at).total_seconds()
        except (AttributeError, TypeError, ValueError, OverflowError):
            return False
        return 0 <= age <= max_age

    def _select_commission_target(self):
        """Prioritize stale selected/held fees, then preserve full-pool RR."""

        if not self._commission_targets:
            return None
        by_id = {target.target_id: target for target in self._commission_targets}
        priority_ids = list(self._commission_priority_target_ids())
        facts = self.last_facts
        held_ids = tuple(
            position.target_id
            for position in getattr(facts, "positions", ())
            if getattr(position, "target_id", None) in by_id
            and getattr(position, "quantity", None) not in (None, 0)
        )
        priority_ids.extend(value for value in held_ids if value not in priority_ids)
        if priority_ids:
            start = self._commission_priority_index % len(priority_ids)
            rotated = priority_ids[start:] + priority_ids[:start]
            for target_id in rotated:
                if target_id in by_id and not self._commission_query_is_fresh(target_id):
                    self._commission_priority_index = (
                        priority_ids.index(target_id) + 1
                    ) % len(priority_ids)
                    target = by_id[target_id]
                    self._commission_index = (
                        self._commission_targets.index(target) + 1
                    ) % len(self._commission_targets)
                    return target
        count = len(self._commission_targets)
        start = self._commission_index % count
        for offset in range(count):
            index = (start + offset) % count
            target = self._commission_targets[index]
            if not self._commission_query_is_fresh(target.target_id):
                self._commission_index = (index + 1) % count
                return target
        return None

    @contextmanager
    def strategy_fact_projection_scope(self):
        """Try to pin one complete Store/query-set view without blocking."""

        if not self._fact_snapshot_lock.acquire(blocking=False):
            self._fact_projection_waiting.set()
            yield False
            return
        # A successful reader is itself the retry after a previously busy
        # projection, so it can consume the pending wake request.
        self._fact_projection_waiting.clear()
        try:
            yield True
        finally:
            self._fact_snapshot_lock.release()

    def _wake_waiting_strategy_projection(self):
        if not self._fact_projection_waiting.is_set():
            return
        if not (self._thread.is_alive() or self._shutdown_event.is_set()):
            return
        # Clear before calling the wake API. A new failed projection racing
        # this wake sets the event again and will be signaled by the next pass.
        self._fact_projection_waiting.clear()
        wake = getattr(self.cerebro, "wake_live_bar_cohort", None)
        if not callable(wake):
            self._projection_wake_error = "LIVE_COHORT_WAKE_API_UNAVAILABLE"
            self._fact_projection_waiting.set()
            return
        try:
            wake()
        except Exception as error:
            self._projection_wake_error = "LIVE_COHORT_WAKE_FAILED:" + type(error).__name__
            self._fact_projection_waiting.set()
            return
        self._projection_wake_error = None

    def request_shutdown(self):
        """Publish a winddown request for the serialized refresh loop."""
        if not self._shutdown_event.is_set():
            self.shutdown_requested_at = time.monotonic()
            self.shutdown_status = "REQUESTED"
        self._shutdown_event.set()
        self._refresh_wakeup.set()
        return True

    def _observe_strategy_shutdown_request(self):
        """Promote the Strategy's finite-epoch request to the control loop."""
        with self._strategy_lock:
            strategy = self._strategy
        if strategy is None:
            return False
        try:
            requested = strategy.shutdown_requested is True
        except Exception as error:
            self.last_error_code = "STRATEGY_SHUTDOWN_STATE_UNAVAILABLE:" + type(error).__name__
            return False
        if requested and not self._shutdown_event.is_set():
            self.request_shutdown()
            return True
        return False

    def _wake_engine(self):
        wake = getattr(self.cerebro, "wake_live_bar_cohort", None)
        if not callable(wake):
            self.shutdown_status = "BLOCKED"
            self.shutdown_blocker = "LIVE_COHORT_WAKE_API_UNAVAILABLE"
            return False
        try:
            wake()
        except Exception as error:
            self.shutdown_status = "BLOCKED"
            self.shutdown_blocker = "LIVE_COHORT_WAKE_FAILED:" + type(error).__name__
            return False
        return True

    def _advance_shutdown(self, *, wake_engine=False):
        """Forward a request and observe state without stopping the engine.

        Strategy.notify_idle owns risk-reduction decisions and calls the public
        Cerebro runstop API only after it has fresh authoritative shutdown
        proof. This loop keeps the serialized Store refresher alive until the
        Strategy/core finishes or the core's bounded winddown expires.
        """
        if not self._shutdown_event.is_set():
            return False
        with self._strategy_lock:
            strategy = self._strategy
        if strategy is None:
            return False
        newly_forwarded = False
        if not self._shutdown_forwarded:
            try:
                strategy.request_shutdown()
            except Exception as error:
                self.shutdown_status = "BLOCKED"
                self.shutdown_blocker = "STRATEGY_SHUTDOWN_REQUEST_FAILED:" + type(error).__name__
                return False
            self._shutdown_forwarded = True
            newly_forwarded = True
            requested_at = self.shutdown_requested_at
            if requested_at is None:
                requested_at = time.monotonic()
            self._shutdown_deadline = requested_at + self.shutdown_grace_seconds
        if (newly_forwarded or wake_engine) and not self._wake_engine():
            return True
        try:
            ready = strategy.shutdown_ready
            blocker = strategy.shutdown_blocker
        except Exception as error:
            ready = False
            blocker = "STRATEGY_SHUTDOWN_STATE_UNAVAILABLE:" + type(error).__name__
        if ready is True:
            self.shutdown_status = "PASS"
            self.shutdown_blocker = None
            self.shutdown_completed_at = time.monotonic()
            return False
        self.shutdown_blocker = (
            blocker if type(blocker) is str and blocker else "OWNED_STATE_NOT_TERMINAL"
        )
        if time.monotonic() >= self._shutdown_deadline:
            self.shutdown_status = "BLOCKED"
            self.shutdown_completed_at = time.monotonic()
            # The core winddown owns the engine deadline and raises on timeout.
            # Keep refreshing evidence; never turn unresolved state into a
            # normal runstop from this control path.
        return False

    @staticmethod
    def _reconcile_all(
        method,
        facts,
        allowed_statuses,
        label,
        *,
        refresh_receipt=None,
        diagnostic_sink=None,
    ):
        offset = 0
        total = 0
        while True:
            page_kwargs = {"limit": 128, "offset": offset}
            if refresh_receipt is not None:
                # Terminal UNKNOWN recovery must validate the very query batch
                # from which ``facts`` was projected.  The caller passes this
                # receipt from its current refresh_snapshot invocation; never
                # reuse the loop's previously published receipt here.
                page_kwargs["refresh_receipt"] = refresh_receipt
            page = method(facts, **page_kwargs)
            if page.offset != offset or page.observation_count > 512:
                raise RunnerError("LIVE_RECONCILIATION_PAGE_INVALID", label)
            blocked_items = tuple(
                item for item in page.items if getattr(item, "status", None) not in allowed_statuses
            )
            if blocked_items:
                QueryRefreshLoop._record_reconciliation_blockers(
                    diagnostic_sink, label, offset, blocked_items
                )
                raise RunnerError("LIVE_RECONCILIATION_BLOCKED", label)
            total += len(page.items)
            if total > 512:
                raise RunnerError("LIVE_RECONCILIATION_LIMIT_EXCEEDED", label)
            if not page.truncated:
                if page.next_offset is not None or total != page.observation_count:
                    raise RunnerError("LIVE_RECONCILIATION_PAGE_INVALID", label)
                return
            if (
                type(page.next_offset) is not int
                or page.next_offset <= offset
                or page.next_offset != offset + len(page.items)
            ):
                raise RunnerError("LIVE_RECONCILIATION_PAGE_INVALID", label)
            offset = page.next_offset

    @staticmethod
    def _append_reconciliation_blocker(diagnostic_sink, label, offset, status, blocker_code):
        """Append one bounded, identifier-only reconciliation diagnostic."""

        if type(diagnostic_sink) is not list or len(diagnostic_sink) >= 16:
            return
        if (
            type(status) is not str
            or not status
            or len(status) > 64
            or any(not (char.isalnum() or char in "_:-.") for char in status)
        ):
            status = "UNOBSERVED"
        if (
            type(blocker_code) is not str
            or not blocker_code
            or len(blocker_code) > 128
            or any(not (char.isalnum() or char in "_:-.") for char in blocker_code)
        ):
            blocker_code = None
        diagnostic_sink.append((label, offset, status, blocker_code))

    @staticmethod
    def _record_reconciliation_blockers(diagnostic_sink, label, offset, items):
        if type(diagnostic_sink) is not list:
            return
        for item in items:
            if len(diagnostic_sink) >= 16:
                break
            QueryRefreshLoop._append_reconciliation_blocker(
                diagnostic_sink,
                label,
                offset,
                getattr(item, "status", None),
                getattr(item, "blocker_code", None),
            )

    @staticmethod
    def _receipt_complete(receipt):
        if (
            receipt.blockers
            or receipt.pending_families
            or receipt.cancelled
            or receipt.deadline_reached
            or tuple(receipt.attempted_families) != tuple(receipt.requested_families)
        ):
            return False
        provenance = {(fact.family, fact.target_id): fact for fact in receipt.query_provenance}
        if len(provenance) != len(receipt.requested_families):
            return False
        for label in receipt.requested_families:
            if ":" in label:
                family, target_id = label.split(":", 1)
            else:
                family, target_id = label, None
            fact = provenance.get((family, target_id))
            if fact is None or not fact.source_owned or not fact.query_complete:
                return False
            if target_id is None and fact.scope_complete is not True:
                return False
        return True

    @staticmethod
    def _execution_error_code(error):
        code = getattr(error, "code", None)
        if type(code) is str and code and code == code.strip():
            return code
        return type(error).__name__

    def _dispatching_recovery_candidate(self):
        """Return whether this refresh must hold the durable recovery gate.

        The journal projection is intentionally bounded.  A truncated page is
        ambiguous, so it takes the gate conservatively.  The coordinator then
        validates each exact source observation against the durable journal;
        this hint never resolves or selects an intent itself.
        """

        if self.coordinator is None:
            return False
        try:
            cancel_absence_page = self.coordinator.dispatching_cancel_store_absence_candidates(
                limit=128
            )
        except Exception as error:
            raise RunnerError(
                "LIVE_CANCEL_DISPATCHING_STORE_ABSENCE_PENDING",
                self._execution_error_code(error),
            ) from None
        cancel_candidates = getattr(cancel_absence_page, "items", None)
        cancel_truncated = getattr(cancel_absence_page, "truncated", None)
        if type(cancel_candidates) is not tuple or type(cancel_truncated) is not bool:
            raise RunnerError("LIVE_CANCEL_DISPATCHING_STORE_ABSENCE_PENDING")
        if cancel_candidates or cancel_truncated:
            return True
        try:
            page = self.coordinator.execution_intent_snapshot(limit=128)
        except Exception as error:
            raise RunnerError(
                "LIVE_RECOVERY_INTENT_SNAPSHOT_UNAVAILABLE",
                self._execution_error_code(error),
            ) from None
        items = getattr(page, "items", None)
        truncated = getattr(page, "truncated", None)
        if type(items) is not tuple or type(truncated) is not bool:
            raise RunnerError("LIVE_RECOVERY_INTENT_SNAPSHOT_INVALID")
        if any(type(getattr(item, "state", None)) is not str for item in items):
            raise RunnerError("LIVE_RECOVERY_INTENT_SNAPSHOT_INVALID")
        return bool(
            self._dispatching_recovery_retry_pending
            or truncated
            or any(item.state == "DISPATCHING" for item in items)
        )

    def _require_dispatching_cancel_absence_ack(self):
        """Keep facts unpublished until every durable cancel marker is acked."""

        if self.coordinator is None:
            return
        try:
            page = self.coordinator.dispatching_cancel_store_absence_candidates(limit=128)
        except Exception as error:
            self.last_receipt = None
            self.last_facts = None
            self.last_error_code = "LIVE_CANCEL_DISPATCHING_STORE_ABSENCE_PENDING"
            self._dispatching_recovery_retry_pending = True
            raise RunnerError(
                self.last_error_code,
                self._execution_error_code(error),
            ) from None
        items = getattr(page, "items", None)
        truncated = getattr(page, "truncated", None)
        if type(items) is not tuple or type(truncated) is not bool or items or truncated:
            self.last_receipt = None
            self.last_facts = None
            self.last_error_code = "LIVE_CANCEL_DISPATCHING_STORE_ABSENCE_PENDING"
            self._dispatching_recovery_retry_pending = True
            raise RunnerError(self.last_error_code)

    def refresh_initial(self, *, wait_timeout):
        """Perform the first refresh, retrying only bounded gate contention.

        A competing live process may still own the dispatch gate.  Retry that
        admission briefly without querying or holding the gate during the
        wait; other incomplete refreshes retain the existing startup behavior.
        """

        deadline = time.monotonic() + wait_timeout
        self._startup_refresh_deadline = deadline
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    if self.last_error_code is None:
                        self.last_error_code = "LIVE_INITIAL_QUERY_READY_TIMEOUT"
                    return None
                self._startup_recovery_scope_timeout = remaining
                try:
                    receipt = self.refresh_once()
                except Exception as error:
                    self.last_error_code = self._execution_error_code(error)
                    if self.last_error_code != "DISPATCH_SERIALIZATION_BUSY":
                        raise
                    receipt = None
                finally:
                    self._startup_recovery_scope_timeout = None
                if self.last_error_code != "DISPATCH_SERIALIZATION_BUSY":
                    return receipt
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return receipt
                time.sleep(min(0.05, remaining))
        finally:
            self._startup_refresh_deadline = None

    def refresh_once(self):
        # Clear, refresh, reconcile and republish as one unit with respect to
        # Strategy fact projection. Readers fail fast while this lock is held.
        # The outer lock serializes refreshers but is not used by Strategy.
        # Optional sidecar I/O can release only the inner projection lock while
        # preventing a second core refresh from overlapping.
        with self._refresh_serialization_lock:
            try:
                with self._fact_snapshot_lock:
                    self._reconciliation_blockers_work = []
                    self.last_reconciliation_blockers = ()
                    try:
                        return self._refresh_once_locked()
                    except Exception:
                        self.last_reconciliation_blockers = tuple(
                            self._reconciliation_blockers_work[:16]
                        )
                        raise
            finally:
                self._wake_waiting_strategy_projection()

    def _refresh_optional_commission_without_projection_lock(self):
        """Query one optional fee target without hiding complete core facts."""

        if not self._fact_snapshot_lock.locked():
            raise RunnerError("LIVE_FACT_PROJECTION_LOCK_REQUIRED")
        self._fact_snapshot_lock.release()
        try:
            self._refresh_commission_sidecar()
        finally:
            # Projection is in-memory and Strategy probes nonblocking. Reacquire
            # before the refresh thread mutates any published state.
            self._fact_snapshot_lock.acquire()

    def _refresh_once_locked(self):
        # Clear the previously published proof before inspecting durable
        # intents.  No reader may use an older query set if recovery admission
        # is busy, unsupported, or the bounded journal projection is invalid.
        self.last_receipt = None
        self.last_facts = None
        self.last_error_code = None
        needs_recovery_scope = self._dispatching_recovery_candidate()
        if not needs_recovery_scope:
            return self._refresh_once_body()

        journal = getattr(self.coordinator, "journal", None)
        serialization_path = getattr(journal, "dispatch_serialization_path", None)
        if serialization_path is None:
            self.last_error_code = "DISPATCHING_RECOVERY_REQUIRES_CROSS_PROCESS_GATE"
            self._dispatching_recovery_retry_pending = True
            raise RunnerError(self.last_error_code)

        self._dispatching_recovery_retry_pending = True
        timeout = min(5.0, self.overall_timeout)
        startup_timeout = self._startup_recovery_scope_timeout
        if startup_timeout is not None:
            timeout = min(timeout, startup_timeout)
        if timeout <= 0:
            self.last_error_code = "DISPATCH_SERIALIZATION_BUSY"
            raise RunnerError(self.last_error_code)
        try:
            with self.coordinator.terminal_recovery_scope(timeout_seconds=timeout):
                try:
                    receipt = self._refresh_once_body()
                except Exception:
                    self._require_dispatching_cancel_absence_ack()
                    raise
                # This runs under both the cross-process terminal lease and
                # the fact-snapshot lock, including the body's early returns.
                # Strategy projection cannot observe a successful refresh until
                # the durable local-absence acknowledgement is present.
                self._require_dispatching_cancel_absence_ack()
        except Exception as error:
            self.last_error_code = self._execution_error_code(error)
            raise
        if self.last_error_code is None:
            self._dispatching_recovery_retry_pending = False
        return receipt

    def _refresh_once_body(self):
        from backtrader.stores.factor_execution_facts import (
            project_factor_execution_facts,
            refresh_factor_execution_queries,
        )

        if not self.targets:
            raise RunnerError("LIVE_REFRESH_TARGETS_REQUIRED")
        margin_target = self._margin_targets[self._margin_index % len(self._margin_targets)]
        self._margin_index = (self._margin_index + 1) % len(self._margin_targets)

        def refresh_snapshot():
            refresh_timeout = self.timeout
            refresh_overall_timeout = self.overall_timeout
            startup_deadline = self._startup_refresh_deadline
            if startup_deadline is not None:
                remaining = startup_deadline - time.monotonic()
                if remaining <= 0:
                    self.last_error_code = "LIVE_INITIAL_QUERY_READY_TIMEOUT"
                    return None, None, None
                refresh_overall_timeout = min(refresh_overall_timeout, remaining)
                refresh_timeout = min(refresh_timeout, refresh_overall_timeout)
            receipt = refresh_factor_execution_queries(
                self.store,
                targets=self.targets,
                timeout=refresh_timeout,
                overall_timeout=refresh_overall_timeout,
                include_core=True,
                margin_target_ids=(margin_target.target_id,),
                max_queries=6,
                cancel_event=self._interrupt_refresh,
                utc_now=self.clock.utc_now,
            )
            if not self._receipt_complete(receipt):
                self.last_error_code = "LIVE_QUERY_REFRESH_INCOMPLETE"
                return receipt, None, None
            query_set = getattr(receipt, "query_set", None)
            if query_set is None:
                self.last_error_code = "LIVE_QUERY_SET_UNAVAILABLE"
                return receipt, None, None
            now = _aware_datetime(self.clock.utc_now(), "live refresh decision time")
            facts = project_factor_execution_facts(
                self.store,
                self.broker,
                targets=self.targets,
                account_scope=self.account_scope,
                strategy_scope=self.strategy_scope,
                now=now,
                quote_max_age=self.quote_max_age,
                max_query_age=self.max_query_age,
                query_set=query_set,
                execution_target_ids=self.execution_target_ids,
                commission_identity_by_target=self.commission_identity_by_target,
                commission_required_for_open=self.commission_required_for_open,
            )
            return receipt, query_set, facts

        receipt, query_set, facts = refresh_snapshot()
        if facts is None:
            self.last_receipt = receipt
            return receipt

        if self.coordinator is not None:
            self._reconcile_dated_trades(
                facts,
                refresh_receipt=receipt,
                diagnostic_sink=self._reconciliation_blockers_work,
            )
            self._reconcile_all(
                self.coordinator.trade_reconciliation_snapshot,
                facts,
                {"APPLIED", "DUPLICATE", "EXTERNAL_FLAT"},
                "trade_proof",
                diagnostic_sink=self._reconciliation_blockers_work,
            )
            # Trade receipts and dated position-book rows are committed after
            # the first position query. A fresh complete account query-set is
            # required before terminal-order reconciliation can release the
            # old order/position ownership.
            receipt, query_set, facts = refresh_snapshot()
            if facts is None:
                self.last_receipt = receipt
                return receipt
            self._reconcile_all(
                self.coordinator.reconcile_terminal_order_observations,
                facts,
                {"RESOLVED", "DUPLICATE", "EXTERNAL_TERMINAL_FLAT"},
                "terminal_orders",
                refresh_receipt=receipt,
                diagnostic_sink=self._reconciliation_blockers_work,
            )
            # Strategy and the proof reads both consume the exact second query
            # set, which postdates the durable trade/dated-book writes.
            now = _aware_datetime(self.clock.utc_now(), "live refresh decision time")
            facts = project_factor_execution_facts(
                self.store,
                self.broker,
                targets=self.targets,
                account_scope=self.account_scope,
                strategy_scope=self.strategy_scope,
                now=now,
                quote_max_age=self.quote_max_age,
                max_query_age=self.max_query_age,
                query_set=query_set,
                execution_target_ids=self.execution_target_ids,
                commission_identity_by_target=self.commission_identity_by_target,
                commission_required_for_open=self.commission_required_for_open,
            )
            self._reconcile_all(
                self.coordinator.trade_reconciliation_snapshot,
                facts,
                {"APPLIED", "DUPLICATE", "EXTERNAL_FLAT"},
                "trade_proof",
                diagnostic_sink=self._reconciliation_blockers_work,
            )
            self._reconcile_all(
                self.coordinator.terminal_order_reconciliation_snapshot,
                facts,
                {"RESOLVED", "DUPLICATE", "EXTERNAL_TERMINAL_FLAT"},
                "terminal_order_proof",
                diagnostic_sink=self._reconciliation_blockers_work,
            )
            # Dated rows are part of the strategy's source-backed risk facts.
            # A fill that cannot be bound to the position book remains a hard
            # refresh blocker; it is never inferred from net Broker quantity.
            # EXTERNAL_FLAT is allowed through the shared proof snapshot, but
            # the dated writer above must preserve that external classification
            # and must never turn it into an owned lot.
            self.last_reconciliation_blockers = ()

        self.last_receipt = receipt
        self.last_facts = facts
        self.last_error_code = None
        # Initial readiness is based on the five sealed core queries only.
        # Once the live refresh thread is running, issue the optional fee query
        # outside the projection lock; a native delay must leave safe strategy
        # actions able to read this complete core receipt.
        if self._startup_refresh_deadline is None and self._commission_targets:
            self._refresh_optional_commission_without_projection_lock()
            try:
                facts = project_factor_execution_facts(
                    self.store,
                    self.broker,
                    targets=self.targets,
                    account_scope=self.account_scope,
                    strategy_scope=self.strategy_scope,
                    now=_aware_datetime(self.clock.utc_now(), "live refresh decision time"),
                    quote_max_age=self.quote_max_age,
                    max_query_age=self.max_query_age,
                    query_set=query_set,
                    execution_target_ids=self.execution_target_ids,
                    commission_identity_by_target=self.commission_identity_by_target,
                    commission_required_for_open=self.commission_required_for_open,
                )
            except Exception:
                # A malformed/expired optional row cannot revoke the core seal.
                return receipt
            self.last_facts = facts
        return receipt

    def _refresh_commission_sidecar(self):
        """Attempt one bounded optional fee query without touching core status."""

        if not self._commission_targets:
            return
        target = self._select_commission_target()
        if target is None:
            return
        identity = self.commission_identity_by_target.get(target.target_id)
        route_getter = getattr(
            self.store, "registered_sim_write_route_invest_unit_id", None
        )
        try:
            source_route_unit_id = (
                route_getter(target.instrument, target.exchange)
                if callable(route_getter)
                else None
            )
        except Exception:
            source_route_unit_id = None
        if (
            not isinstance(identity, Mapping)
            or type(source_route_unit_id) is not str
            or identity.get("invest_unit_id") != source_route_unit_id
        ):
            # The sidecar is optional and the native query may hold SDK state.
            # A configuration value alone cannot authorize it: first bind the
            # exact target to the source-owned CTP write route.
            return
        # This result remains outside the five-family receipt.  A sidecar
        # failure cannot change the core deadline or status.  SDK versions
        # without a source-bound issue deadline are rejected before dispatch.
        try:
            deadline = time.monotonic() + _LIVE_COMMISSION_QUERY_BUDGET_SECONDS
            self.store.registered_sim_query(
                "instrument_commission_rate_result",
                timeout=_LIVE_COMMISSION_QUERY_BUDGET_SECONDS,
                attempts=1,
                deadline_monotonic=deadline,
                instrument_id=target.instrument,
                exchange_id=target.exchange,
            )
        except Exception:
            return

    def _reconcile_dated_trades(self, facts, *, refresh_receipt, diagnostic_sink=None):
        """Apply complete trade pages to the durable execution and dated books."""

        offset = 0
        total = 0
        while True:
            trade_page = self.coordinator.reconcile_trade_observations(
                facts, limit=128, offset=offset, refresh_receipt=refresh_receipt
            )
            if trade_page.offset != offset or trade_page.observation_count > 512:
                self._append_reconciliation_blocker(
                    diagnostic_sink, "trade_page", offset, "PAGE_INVALID", "TRADE_PAGE_SHAPE"
                )
                raise RunnerError("LIVE_TRADE_RECONCILIATION_BLOCKED")
            blocked_trade_items = tuple(
                item
                for item in trade_page.items
                if getattr(item, "status", None) not in {"APPLIED", "DUPLICATE", "EXTERNAL_FLAT"}
            )
            if blocked_trade_items:
                self._record_reconciliation_blockers(
                    diagnostic_sink, "trade_page", offset, blocked_trade_items
                )
                raise RunnerError("LIVE_TRADE_RECONCILIATION_BLOCKED")
            dated_page = self.coordinator.position_book.reconcile_dated_trade_observations(
                facts,
                reconciliation_page=trade_page,
                limit=128,
                offset=offset,
            )
            if (
                dated_page.offset != offset
                or dated_page.observation_count != trade_page.observation_count
                or tuple(item.observation_id for item in dated_page.items)
                != tuple(item.observation_id for item in trade_page.items)
            ):
                self._append_reconciliation_blocker(
                    diagnostic_sink, "dated_page", offset, "PAGE_INVALID", "DATED_PAGE_SHAPE"
                )
                raise RunnerError("LIVE_DATED_TRADE_RECONCILIATION_PAGE_INVALID")
            for trade_item, dated_item in zip(trade_page.items, dated_page.items):
                if trade_item.status in {"APPLIED", "DUPLICATE"}:
                    if dated_item.status not in {"APPLIED", "DUPLICATE"}:
                        self._record_reconciliation_blockers(
                            diagnostic_sink, "dated_page", offset, (dated_item,)
                        )
                        raise RunnerError("LIVE_DATED_TRADE_RECONCILIATION_BLOCKED")
                elif dated_item.status != "EXTERNAL_FLAT":
                    self._record_reconciliation_blockers(
                        diagnostic_sink, "dated_page", offset, (dated_item,)
                    )
                    raise RunnerError("LIVE_DATED_TRADE_RECONCILIATION_BLOCKED")
            total += len(trade_page.items)
            if total > 512:
                self._append_reconciliation_blocker(
                    diagnostic_sink,
                    "trade_page",
                    offset,
                    "LIMIT_EXCEEDED",
                    "TRADE_OBSERVATION_LIMIT",
                )
                raise RunnerError("LIVE_RECONCILIATION_LIMIT_EXCEEDED", "dated_trades")
            if not trade_page.truncated:
                if (
                    trade_page.next_offset is not None
                    or dated_page.truncated
                    or dated_page.next_offset is not None
                    or total != trade_page.observation_count
                ):
                    self._append_reconciliation_blocker(
                        diagnostic_sink,
                        "dated_page",
                        offset,
                        "PAGE_INVALID",
                        "DATED_PAGE_SHAPE",
                    )
                    raise RunnerError("LIVE_DATED_TRADE_RECONCILIATION_PAGE_INVALID")
                return
            if (
                type(trade_page.next_offset) is not int
                or trade_page.next_offset <= offset
                or trade_page.next_offset != offset + len(trade_page.items)
                or not dated_page.truncated
                or dated_page.next_offset != trade_page.next_offset
            ):
                self._append_reconciliation_blocker(
                    diagnostic_sink,
                    "dated_page",
                    offset,
                    "PAGE_INVALID",
                    "DATED_PAGE_SHAPE",
                )
                raise RunnerError("LIVE_DATED_TRADE_RECONCILIATION_PAGE_INVALID")
            offset = trade_page.next_offset

    def start(self):
        self._thread.start()
        self.started = True

    def _reserve_refresh_start(self):
        """Clear cancellation only when this refresh wins the stop boundary."""

        with self._refresh_start_lock:
            if self._stop.is_set():
                return False
            self._interrupt_refresh.clear()
            return True

    def _run(self):
        next_refresh_at = 0.0
        while not self._stop.is_set():
            observed_request = self._observe_strategy_shutdown_request()
            if observed_request:
                next_refresh_at = min(next_refresh_at, time.monotonic())
            if self._shutdown_event.is_set():
                self._advance_shutdown()
            now = time.monotonic()
            if now >= next_refresh_at:
                # Reserve the refresh start atomically with stop_and_join().
                # If stop won the lock, do not erase its cancellation or begin
                # another query cycle after shutdown was requested.
                if not self._reserve_refresh_start():
                    break
                try:
                    self.refresh_once()
                except Exception as error:
                    self.last_error_code = self._execution_error_code(error)
                next_refresh_at = time.monotonic() + self.interval
                if self._shutdown_event.is_set():
                    # The first forwarded request wakes the engine. Subsequent
                    # refreshes keep its evidence current without turning the
                    # control loop into a second engine waker.
                    self._advance_shutdown()
            # Shutdown flags are independent of Store query cadence: finite
            # EOF must be noticed promptly even when refresh_interval is long.
            wait_for = min(0.05, max(0.0, next_refresh_at - time.monotonic()))
            self._refresh_wakeup.wait(wait_for)
            self._refresh_wakeup.clear()

    def stop_and_join(self):
        with self._strategy_lock:
            strategy = self._strategy
        preserve_current_refresh = False
        if strategy is not None:
            try:
                requested = strategy.shutdown_requested is True
                ready = strategy.shutdown_ready is True
                blocker = strategy.shutdown_blocker
            except Exception as error:
                requested = False
                ready = False
                blocker = "STRATEGY_SHUTDOWN_STATE_UNAVAILABLE:" + type(error).__name__
            if requested and ready:
                self.shutdown_status = "PASS"
                self.shutdown_blocker = None
                self.shutdown_completed_at = time.monotonic()
            elif requested:
                self.shutdown_status = "BLOCKED"
                self.shutdown_blocker = (
                    blocker
                    if type(blocker) is str and blocker
                    else "TERMINAL_WINDDOWN_NOT_CONFIRMED"
                )
                self.shutdown_completed_at = time.monotonic()
            preserve_current_refresh = requested and ready
        with self._refresh_start_lock:
            self._stop.set()
            if not preserve_current_refresh:
                # A successful engine-thread winddown still needs a fresh
                # post-join query-set projection. Cancelling an already-running
                # refresh here would replace the last complete receipt with a
                # partial one and make Strategy.stop() fail its final proof.
                # The current pass is bounded by overall_timeout (twice when
                # the coordinator performs its post-trade second query-set pass).
                self._interrupt_refresh.set()
        self._refresh_wakeup.set()
        if self._thread.ident is not None:
            join_timeout = self.overall_timeout * (2 if preserve_current_refresh else 1) + 1.0
            self._thread.join(timeout=join_timeout)
            if self._thread.is_alive():
                self.joined = False
                raise RunnerError("LIVE_QUERY_REFRESH_DID_NOT_JOIN")
        self.joined = True
        return True


def _cleanup_live_resource(cleanup, name, operation, *, project=None):
    """Attempt one cleanup action and retain a finite outcome without masking errors."""

    try:
        result = operation()
    except BaseException as error:
        row = {"resource": name, "status": "FAILED", "error_type": type(error).__name__}
    else:
        row = {"resource": name, "status": "RETURNED"}
        if project is not None:
            try:
                row.update(project(result))
            except BaseException as error:
                row.update(status="UNPROVEN", projection_error_type=type(error).__name__)
    cleanup.append(row)
    return row


def _store_stop_evidence(result, *, ctp_factor_source_required=False):
    state = result.get("shutdown_state") if isinstance(result, Mapping) else None
    if type(state) is not str or state not in {"PASS", "FAIL", "INCOMPLETE", "NOT_STARTED"}:
        state = "UNPROVEN"
    evidence = {"shutdown_state": state}
    if isinstance(result, Mapping) and "ctp_factor_source_shutdown" in result:
        evidence["ctp_factor_source_shutdown"] = _ctp_factor_source_shutdown_evidence(
            result.get("ctp_factor_source_shutdown")
        )
    elif ctp_factor_source_required:
        evidence["ctp_factor_source_shutdown"] = {
            "required": True,
            "status": "UNPROVEN",
        }
    if ctp_factor_source_required and evidence.get("ctp_factor_source_shutdown", {}).get(
        "required"
    ) is not True:
        evidence["ctp_factor_source_shutdown"] = {
            "required": True,
            "status": "UNPROVEN",
        }
    return evidence


def _ctp_factor_source_shutdown_evidence(value):
    """Allowlist the opted-in CTP lifecycle receipts used by cleanup gates."""
    if not isinstance(value, Mapping):
        return {"required": None, "status": "UNPROVEN"}
    required = value.get("required")
    if required is False and value.get("status") == "NOT_REQUIRED":
        return {"required": False, "status": "NOT_REQUIRED"}
    if required is not True:
        return {"required": required if type(required) is bool else None, "status": "UNPROVEN"}

    expected_md = value.get("expected_md_generation")
    expected_trader = value.get("expected_trader_generation")
    join_required = value.get("join_required")
    reasons = value.get("reason_codes")
    if isinstance(reasons, (tuple, list)) and all(type(reason) is str for reason in reasons):
        reason_codes = tuple(reasons)
    else:
        reason_codes = ("reason_codes_unproven",)
    projected = {
        "required": True,
        "status": "INCOMPLETE",
        "expected_md_generation": expected_md if type(expected_md) is int else None,
        "expected_trader_generation": expected_trader if type(expected_trader) is int else None,
        "join_required": join_required if type(join_required) is bool else None,
        "md_receipt": None,
        "trader_receipt": None,
        "reason_codes": reason_codes,
    }

    def project_receipt(receipt, generation):
        if not isinstance(receipt, Mapping):
            return None
        fields = (
            "connection_generation",
            "join_required",
            "join_completed",
            "native_released",
            "thread_alive",
            "timed_out",
            "complete",
        )
        row = {name: receipt.get(name) for name in fields}
        if (
            type(row["connection_generation"]) is not int
            or type(generation) is not int
            or row["connection_generation"] != generation
            or type(row["join_required"]) is not bool
            or type(row["join_completed"]) is not bool
            or type(row["native_released"]) is not bool
            or type(row["thread_alive"]) is not bool
            or type(row["timed_out"]) is not bool
            or type(row["complete"]) is not bool
        ):
            return None
        return row

    md_receipt = project_receipt(value.get("md_receipt"), expected_md)
    trader_receipt = project_receipt(value.get("trader_receipt"), expected_trader)
    projected["md_receipt"] = md_receipt
    projected["trader_receipt"] = trader_receipt
    md_complete = (
        md_receipt is not None
        and md_receipt["join_required"] is join_required
        and md_receipt["native_released"] is True
        and md_receipt["thread_alive"] is False
        and md_receipt["timed_out"] is False
        and md_receipt["complete"] is True
        and (join_required is False or md_receipt["join_completed"] is True)
    )
    trader_complete = (
        trader_receipt is not None
        and trader_receipt["join_required"] is join_required
        and trader_receipt["native_released"] is True
        and trader_receipt["thread_alive"] is False
        and trader_receipt["timed_out"] is False
        and trader_receipt["complete"] is True
        and (join_required is False or trader_receipt["join_completed"] is True)
    )
    if (
        type(expected_md) is int
        and expected_md > 0
        and type(expected_trader) is int
        and expected_trader > 0
        and type(join_required) is bool
        and md_complete
        and trader_complete
        and value.get("status") == "PASS"
        and projected["reason_codes"] == ()
    ):
        projected["status"] = "PASS"
    elif not projected["reason_codes"]:
        projected["reason_codes"] = ("native_shutdown_receipt_incomplete",)
    return projected


def _ctp_factor_source_shutdown_complete(value):
    """Require exact generation-bound native receipts only after source opt-in."""
    if value is None:
        return True
    if isinstance(value, Mapping) and value.get("required") is False:
        return value.get("status") == "NOT_REQUIRED"
    projected = _ctp_factor_source_shutdown_evidence(value)
    return projected.get("required") is True and projected.get("status") == "PASS"


def _broker_shutdown_evidence(broker):
    try:
        summary = broker.get_shutdown_summary()
    except Exception as error:
        return {"status": "UNPROVEN", "summary_error_type": type(error).__name__}
    if not isinstance(summary, Mapping):
        return {"status": "UNPROVEN"}
    allowed = {
        "PASS",
        "FAIL",
        "INCOMPLETE",
        "BLOCKED",
        "NOT_STARTED",
        "OBSERVATION_ONLY",
        "OBSERVATION_ONLY_NONFLAT",
    }
    status = summary.get("status")
    store_state = summary.get("store_shutdown_state")
    return {
        "status": status if type(status) is str and status in allowed else "UNPROVEN",
        "store_shutdown_state": (
            store_state
            if type(store_state) is str
            and store_state in {"PASS", "FAIL", "INCOMPLETE", "UNPROVEN"}
            else "UNPROVEN"
        ),
    }


def _attach_cleanup_results(error, cleanup):
    try:
        error.cleanup_results = tuple(dict(item) for item in cleanup)
    except Exception:
        pass


def _attach_unclosed_live_resources(error, resources, cleanup):
    """Keep uncertain local handles reachable for embedded callers."""

    if _cleanup_complete(cleanup):
        return
    try:
        error.retained_live_resources = MappingProxyType(
            {name: value for name, value in resources.items() if value is not None}
        )
    except Exception:
        pass


def _live_epoch_failure_evidence(config, plan, cerebro, refresh_loop, cleanup):
    """Project only public lifecycle state needed to diagnose a failed epoch.

    In particular, keep the old exact routes visible when a shutdown is
    blocked.  This is not a claim that a remote order is flat or resolved;
    it lets the caller retain the route identity while deciding whether a
    later selection may be opened.
    """

    strategy = getattr(refresh_loop, "_strategy", None) if refresh_loop is not None else None
    try:
        shutdown_requested = getattr(strategy, "shutdown_requested", False) is True
        shutdown_ready = getattr(strategy, "shutdown_ready", False) is True
        shutdown_blocker = getattr(strategy, "shutdown_blocker", None)
        shutdown_post_join_confirmed = (
            getattr(strategy, "shutdown_post_join_confirmed", False) is True
        )
        shutdown_post_join_blocker = getattr(strategy, "shutdown_post_join_blocker", None)
    except Exception as error:
        shutdown_requested = False
        shutdown_ready = False
        shutdown_blocker = "STRATEGY_STATE_UNAVAILABLE:" + type(error).__name__
        shutdown_post_join_confirmed = False
        shutdown_post_join_blocker = "STRATEGY_FINAL_STATE_UNAVAILABLE:" + type(error).__name__
    try:
        order_event_projection = _project_strategy_order_events(
            strategy, plan, config["cohort"]["epoch_id"]
        )
    except Exception as error:
        # Failure diagnostics must preserve the original lifecycle error.
        order_event_projection = {
            "status": "BLOCKED",
            "reason": "STRATEGY_ORDER_EVENT_PROJECTION_FAILED:" + type(error).__name__,
            "events": [],
        }
    try:
        winddown_status = getattr(cerebro, "live_bar_cohort_winddown_status", None)
        winddown_reason = getattr(cerebro, "live_bar_cohort_winddown_reason", None)
    except Exception:
        winddown_status = None
        winddown_reason = None
    return {
        "epoch_id": config["cohort"]["epoch_id"],
        "selection_path": str(plan["selection_path"]) if plan is not None else None,
        "selection_source": plan.get("selection_source") if plan is not None else None,
        "source_snapshot_id": plan.get("source_snapshot_id") if plan is not None else None,
        "routes": _route_summary(plan) if plan is not None else {},
        "engine_winddown_status": winddown_status,
        "engine_winddown_reason": winddown_reason,
        "strategy_shutdown_requested": shutdown_requested,
        "strategy_shutdown_ready": shutdown_ready,
        "strategy_shutdown_blocker": (shutdown_blocker if type(shutdown_blocker) is str else None),
        "strategy_shutdown_post_join_confirmed": shutdown_post_join_confirmed,
        "strategy_shutdown_post_join_blocker": (
            shutdown_post_join_blocker if type(shutdown_post_join_blocker) is str else None
        ),
        "strategy_order_events": order_event_projection,
        "refresh_status": (
            refresh_loop.shutdown_status if refresh_loop is not None else "NOT_CREATED"
        ),
        "refresh_blocker": (refresh_loop.shutdown_blocker if refresh_loop is not None else None),
        "refresh_error_code": (
            refresh_loop.last_error_code if refresh_loop is not None else "NOT_CREATED"
        ),
        "reconciliation_blockers": (
            list(refresh_loop.last_reconciliation_blockers) if refresh_loop is not None else []
        ),
        "resource_shutdown": [dict(item) for item in cleanup],
        "cleanup_complete": _cleanup_complete(cleanup),
    }


def _project_strategy_order_events(strategy, plan, epoch_id):
    """Bind the Strategy's bounded callback window to this exact epoch route set.

    The Strategy keeps at most 128 callback observations.  A full window is
    conservatively marked truncated because the public surface does not expose
    a dropped-event counter; retirement proof still comes from the Strategy's
    current facts, journal and position projection.
    """

    if plan is None:
        return {
            "status": "UNAVAILABLE",
            "reason": "SELECTION_PLAN_UNAVAILABLE",
            "capacity": 128,
            "retained_count": 0,
            "truncated": None,
            "events": [],
        }
    events = getattr(strategy, "order_events", None) if strategy is not None else None
    if events is None:
        return {
            "status": "UNAVAILABLE",
            "reason": "STRATEGY_ORDER_EVENT_SURFACE_UNAVAILABLE",
            "capacity": 128,
            "retained_count": 0,
            "truncated": None,
            "events": [],
        }
    if not isinstance(events, (deque, list, tuple)) or len(events) > 128:
        return {
            "status": "BLOCKED",
            "reason": "STRATEGY_ORDER_EVENT_SURFACE_INVALID",
            "capacity": 128,
            "retained_count": None,
            "truncated": None,
            "events": [],
        }

    target_by_instrument = defaultdict(list)
    for target in plan["targets"]:
        product = plan["product_by_target"][target]
        target_by_instrument[plan["routes"][product]].append((target, product.exchange_id))

    projected = []
    for event in tuple(events):
        if not isinstance(event, Mapping):
            return {
                "status": "BLOCKED",
                "reason": "STRATEGY_ORDER_EVENT_INVALID",
                "capacity": 128,
                "retained_count": len(events),
                "truncated": len(events) == 128,
                "events": projected,
            }
        raw_instrument = event.get("instrument")
        event_exchange = event.get("exchange")
        if isinstance(raw_instrument, tuple) and len(raw_instrument) == 2:
            instrument, route_exchange = raw_instrument
            if event_exchange is not None and event_exchange != route_exchange:
                return {
                    "status": "BLOCKED",
                    "reason": "STRATEGY_ORDER_EVENT_ROUTE_UNBOUND",
                    "capacity": 128,
                    "retained_count": len(events),
                    "truncated": len(events) == 128,
                    "events": projected,
                }
            event_exchange = route_exchange
        else:
            instrument = raw_instrument
        matches = target_by_instrument.get(instrument, ())
        if not isinstance(instrument, str) or (
            event_exchange is not None and not isinstance(event_exchange, str)
        ):
            matches = ()
        elif event_exchange is not None:
            matches = tuple(item for item in matches if item[1] == event_exchange)
        if len(matches) != 1:
            return {
                "status": "BLOCKED",
                "reason": "STRATEGY_ORDER_EVENT_ROUTE_UNBOUND",
                "capacity": 128,
                "retained_count": len(events),
                "truncated": len(events) == 128,
                "events": projected,
            }
        target, exchange = matches[0]
        ref = event.get("ref")
        status = event.get("status")
        executed_size = event.get("executed_size")
        executed_price = event.get("executed_price")
        if (
            type(ref) is not int
            or ref <= 0
            or not isinstance(status, str)
            or not status
            or not isinstance(executed_size, str)
            or not isinstance(executed_price, str)
        ):
            return {
                "status": "BLOCKED",
                "reason": "STRATEGY_ORDER_EVENT_FIELDS_INVALID",
                "capacity": 128,
                "retained_count": len(events),
                "truncated": len(events) == 128,
                "events": projected,
            }
        projected.append(
            {
                "epoch_id": epoch_id,
                "target": target,
                "instrument": instrument,
                "exchange": exchange,
                "ref": ref,
                "status": status,
                "executed_size": executed_size,
                "executed_price": executed_price,
            }
        )
    return {
        "status": "AVAILABLE",
        "reason": None,
        "capacity": 128,
        "retained_count": len(projected),
        "truncated": len(projected) == 128,
        "events": projected,
    }


def _attach_live_epoch_failure_evidence(error, config, plan, cerebro, refresh_loop, cleanup):
    try:
        error.live_epoch_evidence = _live_epoch_failure_evidence(
            config, plan, cerebro, refresh_loop, cleanup
        )
    except Exception:
        # Diagnostics must never replace the original setup, run, or cleanup
        # failure.
        pass


def _cleanup_complete(cleanup):
    required = {"query_refresh", "broker", "store", "journal", "decision_tape"}
    rows = {item.get("resource"): item for item in cleanup}
    if not required.issubset(rows):
        return False
    loop = rows["query_refresh"]
    broker = rows["broker"]
    store = rows["store"]
    journal = rows["journal"]
    decision_tape = rows["decision_tape"]
    store_state = store.get("shutdown_state")
    store_ok = (store.get("status") == "NOT_CREATED" and store_state == "NOT_CREATED") or (
        store.get("status") in {"RETURNED", "CLOSED_BY_BROKER"} and store_state == "PASS"
    )
    store_ok = store_ok and _ctp_factor_source_shutdown_complete(
        store.get("ctp_factor_source_shutdown")
    )
    broker_status = broker.get("status")
    if broker_status in {"PASS", "OBSERVATION_ONLY", "OBSERVATION_ONLY_NONFLAT"}:
        broker_ok = broker.get("store_shutdown_state") == "PASS"
    elif broker_status in {"NOT_RUN", "NOT_CREATED"}:
        # Setup failures may stop the Store directly before the Broker starts.
        broker_ok = store_ok
    else:
        broker_ok = False
    return (
        loop.get("joined") is True
        and broker_ok
        and store_ok
        and journal.get("status") in {"CLOSED", "NOT_CREATED"}
        and decision_tape.get("status") in {"CLOSED", "NOT_CREATED"}
    )


def _validated_live_store_config(row):
    """Validate the exact config/api_kwargs shape without exposing values."""

    _mapping(row, "live Store config")
    if set(row) != {"config", "api_kwargs"}:
        raise RunnerError("LIVE_STORE_CONFIG_FIELDS_INVALID")
    config_values = dict(_mapping(row["config"], "live Store config.config"))
    api_kwargs = dict(_mapping(row["api_kwargs"], "live Store config.api_kwargs"))
    if (
        "api_cls" in config_values
        or "api_cls" in api_kwargs
        or "api" in config_values
        or "api" in api_kwargs
    ):
        raise RunnerError("LIVE_STORE_CONFIG_INJECTION_DENIED")
    return config_values, api_kwargs


def _live_env_config(config, *, override=None):
    """Read the legacy environment input or validate an in-process override."""

    if override is not None:
        return _validated_live_store_config(override)
    name = _text(config["live"]["store_config_env"], "live.store_config_env")
    payload = os.environ.get(name)
    if payload is None:
        raise RunnerError("LIVE_STORE_CONFIG_ENV_MISSING", name)
    try:
        row = json.loads(payload)
    except json.JSONDecodeError:
        raise RunnerError("LIVE_STORE_CONFIG_ENV_INVALID", name) from None
    return _validated_live_store_config(row)


class SimNowProfileValidationError(ValueError):
    """A safe, value-free reason that the live CTP profile was not admitted."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _sdk_profile_contract() -> (
    Tuple[Callable[..., Any], Optional[Callable[..., Any]], Callable[..., Any]]
):
    try:
        import bt_api_ctp.ctp_env_selector as selector
    except ImportError:
        raise SimNowProfileValidationError("SDK_PROFILE_SELECTOR_UNAVAILABLE") from None
    official_simnow_fronts = getattr(selector, "official_simnow_fronts", None)
    verify_official_simnow_profile = getattr(selector, "verify_official_simnow_profile", None)
    official_simnow_profile_for_td_front = getattr(
        selector, "official_simnow_profile_for_td_front", None
    )
    if not callable(official_simnow_fronts) or not callable(verify_official_simnow_profile):
        raise SimNowProfileValidationError("SDK_PROFILE_SELECTOR_UNAVAILABLE")
    return (
        official_simnow_fronts,
        official_simnow_profile_for_td_front,
        verify_official_simnow_profile,
    )


def _resolve_ctp_front(options: Mapping[str, Any], address_key: str, front_key: str) -> str:
    # Match the CTP wrapper: a truthy address takes precedence over its legacy alias.
    value = options.get(address_key) or options.get(front_key)
    if value is None or value == "":
        raise SimNowProfileValidationError("CTP_FRONT_MISSING")
    if type(value) is not str:
        raise SimNowProfileValidationError("CTP_FRONT_INVALID")
    return value


def _tape_origin_partition(value: Any, member_id: str) -> dict[str, Any]:
    names = {
        "schema",
        "cohort_id",
        "epoch_id",
        "member_id",
        "source_ref",
        "source_role",
        "connection_generation",
    }
    if not isinstance(value, Mapping) or set(value) != names:
        raise RunnerError("DECISION_TAPE_ORIGIN_PARTITION_INVALID", member_id)
    generation = value["connection_generation"]
    if (
        value["schema"] != SOURCE_ORIGIN_PARTITION_SCHEMA
        or type(value["cohort_id"]) is not str
        or not value["cohort_id"]
        or type(value["epoch_id"]) is not int
        or value["epoch_id"] < 1
        or value["member_id"] != member_id
        or type(value["source_ref"]) is not str
        or not value["source_ref"]
        or value["source_role"] not in ("history", "live")
        or type(value["source_role"]) is not str
        or type(generation) not in (str, int)
        or (type(generation) is str and not generation)
        or (type(generation) is int and generation <= 0)
    ):
        raise RunnerError("DECISION_TAPE_ORIGIN_PARTITION_INVALID", member_id)
    return {name: value[name] for name in (
        "schema",
        "cohort_id",
        "epoch_id",
        "member_id",
        "source_ref",
        "source_role",
        "connection_generation",
    )}


def _origin_partition_follows(previous: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    if dict(previous) == dict(current):
        return True
    if current["epoch_id"] > previous["epoch_id"]:
        return current["cohort_id"] != previous["cohort_id"]
    return bool(
        current["epoch_id"] == previous["epoch_id"]
        and current["cohort_id"] == previous["cohort_id"]
        and current["member_id"] == previous["member_id"]
        and current["source_ref"] == previous["source_ref"]
        and previous["source_role"] == "history"
        and current["source_role"] == "live"
    )


def _claimed_ctp_profile(options: Mapping[str, Any]) -> str:
    claims = []
    for key in ("ctp_env_profile", "environment_profile"):
        if key not in options:
            continue
        value = options[key]
        if type(value) is not str or not value.strip():
            raise SimNowProfileValidationError("CTP_PROFILE_INVALID")
        claims.append(value.strip().lower())
    if len(set(claims)) > 1:
        raise SimNowProfileValidationError("CTP_PROFILE_CLAIMS_CONFLICT")
    return claims[0] if claims else ""


def validate_official_simnow_store_profile(
    config: Mapping[str, Any], api_kwargs: Mapping[str, Any]
) -> Mapping[str, Any]:
    """Validate the Store's effective fronts using the SDK's registered profile."""

    if not isinstance(config, Mapping) or not isinstance(api_kwargs, Mapping):
        raise SimNowProfileValidationError("CTP_CONFIG_MAPPINGS_REQUIRED")

    # BtApiStore applies api_kwargs after config. The CTP wrapper then selects
    # address before front aliases; resolve only that effective pair.
    options = dict(config)
    options.update(api_kwargs)
    td_front = _resolve_ctp_front(options, "td_address", "td_front")
    md_front = _resolve_ctp_front(options, "md_address", "md_front")
    profile = _claimed_ctp_profile(options)
    for key in ("environment", "ctp_environment"):
        if key in options:
            value = options[key]
            if type(value) is not str or value.strip().lower() != "simnow":
                raise SimNowProfileValidationError("CTP_ENVIRONMENT_NOT_SIMNOW")

    (
        official_simnow_fronts,
        official_simnow_profile_for_td_front,
        verify_official_simnow_profile,
    ) = _sdk_profile_contract()
    if not profile:
        if not callable(official_simnow_profile_for_td_front):
            raise SimNowProfileValidationError("CTP_PROFILE_LOOKUP_UNAVAILABLE")
        profile = official_simnow_profile_for_td_front(td_front)
    if not profile:
        raise SimNowProfileValidationError("CTP_PROFILE_NOT_OFFICIAL_SIMNOW")

    try:
        expected_td, expected_md = official_simnow_fronts(profile)
    except (KeyError, ValueError):
        raise SimNowProfileValidationError("CTP_PROFILE_NOT_OFFICIAL_SIMNOW") from None
    if (
        td_front != expected_td
        or md_front != expected_md
        or not verify_official_simnow_profile(td_front, md_front, profile)
    ):
        raise SimNowProfileValidationError("CTP_PROFILE_FRONT_MISMATCH")
    return {"verified": True, "environment": "simnow", "profile": profile}


def _write_requested(config, allow_write_flag, decision):
    write_cfg = config["live"]["allow_writes"]
    if type(write_cfg) is not bool:
        raise RunnerError("LIVE_WRITE_FLAG_INVALID")
    if allow_write_flag and not write_cfg:
        raise RunnerError("LIVE_WRITE_GRANT_MISSING_IN_CONFIG")
    if allow_write_flag and decision.effective_tier != "live":
        raise RunnerError("LIVE_WRITE_TIER_REQUIRED")
    return bool(allow_write_flag and write_cfg and decision.effective_tier == "live")


def _arm_templates(config, plan):
    raw = config["live"]["arm_templates"]
    if type(raw) is not list:
        raise RunnerError("LIVE_ARM_TEMPLATES_INVALID")
    target_routes = {
        target: (plan["routes"][product], product.exchange_id)
        for target, product in plan["product_by_target"].items()
    }
    templates = {}
    fields = {
        "target",
        "md_front",
        "strategy_identity_sha256",
        "execution_cycle_id",
        "preflight_sha256",
    }
    for item in raw:
        row = _mapping(item, "live arm template")
        if set(row) != fields:
            raise RunnerError("LIVE_ARM_TEMPLATE_FIELDS_INVALID")
        target = _text(row["target"], "arm template target")
        if target not in plan["authorized_targets"]:
            raise RunnerError("LIVE_ARM_TEMPLATE_TARGET_NOT_AUTHORIZED")
        route = target_routes[target]
        if route in templates:
            raise RunnerError("LIVE_ARM_TEMPLATE_DUPLICATE")
        template = {key: _text(row[key], key) for key in fields.difference({"target"})}
        templates[route] = template
    expected = {target_routes[target] for target in plan["authorized_targets"]}
    if set(templates) != expected:
        raise RunnerError("LIVE_ARM_TEMPLATE_ROUTE_SET_MISMATCH")
    return templates


def _install_shutdown_signal_handlers(refresh_loop):
    """Install minimal handlers that only publish a control-thread request."""

    if threading.current_thread() is not threading.main_thread():
        return {}

    def request_shutdown(_signum, _frame):
        refresh_loop.request_shutdown()

    installed = {}
    candidates = (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGBREAK", None))
    try:
        for signum in dict.fromkeys(item for item in candidates if item is not None):
            installed[signum] = signal.getsignal(signum)
            signal.signal(signum, request_shutdown)
    except (OSError, ValueError):
        for signum, previous in reversed(tuple(installed.items())):
            signal.signal(signum, previous)
        raise RunnerError("LIVE_SHUTDOWN_SIGNAL_HANDLER_UNAVAILABLE") from None
    return installed


def _restore_shutdown_signal_handlers(installed):
    for signum, previous in reversed(tuple(installed.items())):
        signal.signal(signum, previous)


def _full_route_summary(plan):
    targets = tuple(plan.get("full_selected_targets", plan["targets"]))
    product_by_target = plan.get("full_product_by_target", plan["product_by_target"])
    routes = plan.get("full_routes", plan["routes"])
    return {target: routes[product_by_target[target]] for target in targets}


def _full_authorized_targets(plan):
    return tuple(plan.get("full_authorized_targets", plan["authorized_targets"]))


def _grid_semantics_sha256(grid):
    grid_to_dict = getattr(grid, "to_dict", None)
    if not callable(grid_to_dict):
        raise RunnerError("SELECTION_EVIDENCE_GRID_UNAVAILABLE")
    grid_row = grid_to_dict()
    if type(grid_row) is not dict or set(grid_row) != {
        "schema",
        "status",
        "decision_at",
        "target_products",
        "product_trading_days",
        "calendar_hashes",
        "minutes",
    }:
        raise RunnerError("SELECTION_EVIDENCE_GRID_INVALID")
    stable_grid = {
        key: value
        for key, value in grid_row.items()
        if key not in {"decision_at", "calendar_hashes"}
    }
    return hashlib.sha256(_canonical_json_bytes(stable_grid).rstrip(b"\n")).hexdigest()


def _live_source_lineage_kind_from_days(trading_days):
    """Name one source-continuity lane by its complete exchange-day map."""

    if not isinstance(trading_days, Mapping) or not trading_days:
        raise RunnerError("LIVE_SOURCE_TRADING_DAYS_UNAVAILABLE")
    normalized = {}
    for exchange_id, trading_day in trading_days.items():
        exchange_id = _text(exchange_id, "source lineage exchange_id")
        if type(trading_day) is not date or exchange_id in normalized:
            raise RunnerError("LIVE_SOURCE_TRADING_DAYS_INVALID")
        normalized[exchange_id] = trading_day.isoformat()
    identity = {
        "schema": "backtrader.alpha003.source_lineage.trading_day_map.v1",
        "trading_days": {exchange: normalized[exchange] for exchange in sorted(normalized)},
    }
    digest = hashlib.sha256(_canonical_json_bytes(identity).rstrip(b"\n")).hexdigest()
    return "ALPHA003_GRID:trading-day-map-v1:" + digest


def _live_source_lineage_kind(plan):
    manifest = plan.get("manifest") if isinstance(plan, Mapping) else None
    rows = getattr(manifest, "trading_days", None)
    if type(rows) not in (tuple, list) or not rows:
        raise RunnerError("LIVE_SOURCE_TRADING_DAYS_UNAVAILABLE")
    trading_days = {}
    for row in rows:
        exchange_id = getattr(row, "exchange_id", None)
        trading_day = getattr(row, "current_trading_day", None)
        if exchange_id in trading_days:
            raise RunnerError("LIVE_SOURCE_TRADING_DAYS_INVALID")
        trading_days[exchange_id] = trading_day
    return _live_source_lineage_kind_from_days(trading_days)


def _reject_legacy_live_source_highwater(journal, scopes):
    if journal.source_highwater(
        scopes["account_scope"],
        scopes["strategy_scope"],
        scopes["logical_run_id"],
        "ALPHA003_GRID",
    ) is not None:
        raise RunnerError("LIVE_LEGACY_SOURCE_HIGHWATER_UNSUPPORTED")


def _selection_evidence(plan, epoch_id, *, max_bytes):
    """Return bounded, JSON-safe selection evidence bound to one epoch route set."""

    if type(max_bytes) is not int or max_bytes < 1:
        raise RunnerError("SELECTION_EVIDENCE_BYTE_BUDGET_INVALID")
    if type(epoch_id) is not int or epoch_id < 1:
        raise RunnerError("SELECTION_EVIDENCE_EPOCH_INVALID")
    manifest = plan.get("manifest") if isinstance(plan, Mapping) else None
    to_dict = getattr(manifest, "to_dict", None)
    manifest_digest = getattr(manifest, "manifest_sha256", None)
    if not callable(to_dict) or type(manifest_digest) is not str:
        raise RunnerError("SELECTION_EVIDENCE_MANIFEST_UNAVAILABLE")
    try:
        manifest_row = to_dict()
        if not isinstance(manifest_row, dict):
            raise TypeError("manifest projection is not a mapping")
        encoded_manifest = _canonical_json_bytes(manifest_row)
        if hashlib.sha256(encoded_manifest.rstrip(b"\n")).hexdigest() != manifest_digest:
            raise ValueError("manifest digest does not match its projection")
        golden_subset = plan.get("golden_targets") is not None
        routes = _full_route_summary(plan) if golden_subset else _route_summary(plan)
        authorized_targets = (
            sorted(_full_authorized_targets(plan))
            if golden_subset
            else plan.get("authorized_targets")
        )
        route_targets = set(routes)
        if (
            type(authorized_targets) not in (tuple, list)
            or not authorized_targets
            or any(type(target) is not str or not target for target in authorized_targets)
            or len(set(authorized_targets)) != len(authorized_targets)
            or not set(authorized_targets).issubset(route_targets)
        ):
            raise RunnerError("SELECTION_EVIDENCE_AUTHORIZED_TARGETS_INVALID")
        authorized_targets = list(authorized_targets)
        binding = {
            "schema": "backtrader.alpha003_epoch_selection_evidence.v1",
            "epoch_id": epoch_id,
            "selection_source": str(plan["selection_source"]),
            "selection_path": str(plan["selection_path"]),
            "source_snapshot_id": plan.get("source_snapshot_id"),
            "manifest_sha256": manifest_digest,
            "routes": routes,
            "authorized_targets": authorized_targets,
        }
        if binding["selection_source"] == "ctp_query_snapshot_equal_weight_v1":
            evidence_grid = plan.get("full_grid") if golden_subset else plan.get("grid")
            binding["grid_semantics_sha256"] = _grid_semantics_sha256(evidence_grid)
        if golden_subset:
            binding.update(
                {
                    "full_selected_targets": sorted(plan["full_selected_targets"]),
                    "active_shadow_targets": sorted(plan["active_shadow_targets"]),
                    "active_routes": _route_summary(plan),
                    "active_authorized_targets": sorted(plan["authorized_targets"]),
                    "active_grid_semantics_sha256": _grid_semantics_sha256(plan["grid"]),
                }
            )
        binding_sha256 = hashlib.sha256(_canonical_json_bytes(binding).rstrip(b"\n")).hexdigest()
        evidence = {
            **binding,
            "binding_sha256": binding_sha256,
            "manifest": manifest_row,
        }
        encoded_evidence = _canonical_json_bytes(evidence)
    except RunnerError:
        raise
    except Exception as error:
        raise RunnerError("SELECTION_EVIDENCE_SERIALIZATION_FAILED", type(error).__name__) from None
    if len(encoded_evidence) > max_bytes:
        raise RunnerError("SELECTION_EVIDENCE_BYTE_BUDGET_EXCEEDED")
    return evidence


def _validate_selection_evidence(value):
    """Verify the public hashes and shape of saved epoch selection evidence."""

    expected_keys = {
        "schema",
        "epoch_id",
        "selection_source",
        "selection_path",
        "source_snapshot_id",
        "manifest_sha256",
        "routes",
        "authorized_targets",
        "binding_sha256",
        "manifest",
    }
    golden_keys = {
        "full_selected_targets",
        "active_shadow_targets",
        "active_routes",
        "active_authorized_targets",
        "active_grid_semantics_sha256",
    }
    try:
        if not isinstance(value, Mapping):
            raise TypeError("selection evidence is not a mapping")
        if golden_keys.intersection(value):
            expected_keys.update(golden_keys)
        if value.get("selection_source") == "ctp_query_snapshot_equal_weight_v1":
            expected_keys.add("grid_semantics_sha256")
        _exact_keys(value, expected_keys, "selection evidence")
        if (
            value.get("schema") != "backtrader.alpha003_epoch_selection_evidence.v1"
            or type(value.get("epoch_id")) is not int
            or value["epoch_id"] < 1
            or type(value.get("selection_source")) is not str
            or not value["selection_source"]
            or type(value.get("selection_path")) is not str
            or not value["selection_path"]
            or type(value.get("source_snapshot_id")) not in (str, type(None))
            or type(value.get("manifest_sha256")) is not str
            or type(value.get("binding_sha256")) is not str
            or not isinstance(value.get("manifest"), dict)
            or not isinstance(value.get("routes"), dict)
            or type(value.get("authorized_targets")) is not list
            or (
                value["selection_source"] == "ctp_query_snapshot_equal_weight_v1"
                and (
                    type(value.get("grid_semantics_sha256")) is not str
                    or len(value["grid_semantics_sha256"]) != 64
                    or any(
                        character not in "0123456789abcdef"
                        for character in value["grid_semantics_sha256"]
                    )
                )
            )
        ):
            raise TypeError("selection evidence fields are invalid")
        if value["selection_source"] not in {
            "saved_bundle_legacy",
            "ctp_query_snapshot_equal_weight_v1",
        }:
            raise TypeError("selection evidence source is unsupported")
        if value["selection_source"] == "ctp_query_snapshot_equal_weight_v1":
            if type(value["source_snapshot_id"]) is not str or not value["source_snapshot_id"]:
                raise TypeError("query selection snapshot is missing")
        routes = value["routes"]
        if not routes or any(
            type(target) is not str
            or not target
            or type(instrument) is not str
            or not instrument
            for target, instrument in routes.items()
        ):
            raise TypeError("selection routes are invalid")
        authorized = value["authorized_targets"]
        if (
            not authorized
            or any(type(target) is not str or not target for target in authorized)
            or len(authorized) != len(set(authorized))
            or not set(authorized).issubset(routes)
        ):
            raise TypeError("authorized selection targets are invalid")
        if golden_keys.issubset(value):
            full_selected = value["full_selected_targets"]
            active_selected = value["active_shadow_targets"]
            active_routes = value["active_routes"]
            active_authorized = value["active_authorized_targets"]
            if (
                type(full_selected) is not list
                or not full_selected
                or any(type(target) is not str or not target for target in full_selected)
                or full_selected != sorted(set(full_selected))
                or full_selected != sorted(routes)
                or type(active_selected) is not list
                or not 3 <= len(active_selected) <= 5
                or any(type(target) is not str or not target for target in active_selected)
                or active_selected != sorted(set(active_selected))
                or not set(active_selected).issubset(full_selected)
                or type(active_routes) is not dict
                or set(active_routes) != set(active_selected)
                or any(
                    type(active_routes[target]) is not str
                    or active_routes[target] != routes[target]
                    for target in active_selected
                )
                or type(active_authorized) is not list
                or active_authorized != sorted(set(active_authorized))
                or not set(active_authorized).issubset(active_selected)
                or active_authorized != sorted(set(authorized).intersection(active_selected))
                or type(value["active_grid_semantics_sha256"]) is not str
                or len(value["active_grid_semantics_sha256"]) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in value["active_grid_semantics_sha256"]
                )
                or value["selection_source"] != "ctp_query_snapshot_equal_weight_v1"
            ):
                raise TypeError("golden selection evidence is invalid")
        manifest_digest = hashlib.sha256(
            _canonical_json_bytes(value["manifest"]).rstrip(b"\n")
        ).hexdigest()
        if value["manifest_sha256"] != manifest_digest:
            raise TypeError("selection manifest digest is invalid")
        binding_keys = (
            "schema",
            "epoch_id",
            "selection_source",
            "selection_path",
            "source_snapshot_id",
            "manifest_sha256",
            "routes",
            "authorized_targets",
        )
        binding = {key: value[key] for key in binding_keys}
        if "grid_semantics_sha256" in value:
            binding["grid_semantics_sha256"] = value["grid_semantics_sha256"]
        for key in golden_keys:
            if key in value:
                binding[key] = value[key]
        binding_digest = hashlib.sha256(_canonical_json_bytes(binding).rstrip(b"\n")).hexdigest()
        if value["binding_sha256"] != binding_digest:
            raise TypeError("selection binding digest is invalid")
        return dict(value)
    except Exception:
        raise RunnerError("LIVE_HISTORY_SELECTION_EVIDENCE_INVALID") from None


def _query_history_selection_projection(evidence):
    """Project stable query scope while excluding per-collection observations."""

    manifest = evidence["manifest"]
    query_snapshot = manifest.get("query_snapshot")
    if (
        manifest.get("schema") != "backtrader.futures_main_contract_manifest.v2"
        or manifest.get("status") != "READY"
        or type(manifest.get("policy")) is not dict
        or type(manifest.get("target_products")) is not list
        or type(manifest.get("trading_days")) is not list
        or type(manifest.get("calendars")) is not list
        or type(manifest.get("coverage")) is not list
        or type(manifest.get("products")) is not list
        or type(manifest.get("query_coverage")) is not list
        or type(manifest.get("source")) is not dict
        or type(query_snapshot) is not dict
        or type(query_snapshot.get("catalog_records")) is not list
    ):
        raise RunnerError("LIVE_HISTORY_SELECTION_EVIDENCE_INVALID")
    source = manifest["source"]
    catalog = source.get("catalog")
    if (
        type(catalog) is not dict
        or type(source.get("source_id")) is not str
        or type(catalog.get("source_id")) is not str
    ):
        raise RunnerError("LIVE_HISTORY_SELECTION_EVIDENCE_INVALID")

    def select_rows(rows, keys):
        if any(type(row) is not dict or not set(keys).issubset(row) for row in rows):
            raise RunnerError("LIVE_HISTORY_SELECTION_EVIDENCE_INVALID")
        return [{key: row[key] for key in keys} for row in rows]

    if any(
        type(row) is not dict
        for name in (
            "target_products",
            "trading_days",
            "calendars",
            "coverage",
            "products",
            "query_coverage",
        )
        for row in manifest[name]
    ):
        raise RunnerError("LIVE_HISTORY_SELECTION_EVIDENCE_INVALID")
    stable_calendars = [
        {
            key: value
            for key, value in row.items()
            if key not in {"available_at", "retrieved_at", "sha256"}
        }
        for row in manifest["calendars"]
    ]
    calendar_keys = {
        "exchange_id",
        "source_id",
        "version",
        "coverage_start",
        "coverage_through",
        "complete",
        "trading_days",
    }
    if any(not calendar_keys.issubset(row) for row in stable_calendars):
        raise RunnerError("LIVE_HISTORY_SELECTION_EVIDENCE_INVALID")
    stable_catalog_records = []
    seen_catalog_instruments = set()
    catalog_record_keys = {
        "product",
        "instrument_id",
        "asset_type",
        "is_trading",
        "expiry_date",
        "product_class",
    }
    for row in query_snapshot["catalog_records"]:
        if (
            type(row) is not dict
            or set(row) != catalog_record_keys
            or type(row.get("product")) is not dict
            or set(row["product"]) != {"exchange_id", "product_id"}
            or type(row.get("instrument_id")) is not str
            or not row["instrument_id"]
        ):
            raise RunnerError("LIVE_HISTORY_SELECTION_EVIDENCE_INVALID")
        product = row["product"]
        if (
            type(product.get("exchange_id")) is not str
            or not product["exchange_id"]
            or type(product.get("product_id")) is not str
            or not product["product_id"]
            or row.get("asset_type") is not None
            and type(row["asset_type"]) is not str
            or row.get("is_trading") is not None
            and type(row["is_trading"]) is not bool
            or row.get("expiry_date") is not None
            and type(row["expiry_date"]) is not str
            or row.get("product_class") is not None
            and type(row["product_class"]) is not str
        ):
            raise RunnerError("LIVE_HISTORY_SELECTION_EVIDENCE_INVALID")
        key = (product["exchange_id"], product["product_id"], row["instrument_id"])
        if key in seen_catalog_instruments:
            raise RunnerError("LIVE_HISTORY_SELECTION_EVIDENCE_INVALID")
        seen_catalog_instruments.add(key)
        stable_catalog_records.append(
            {
                "exchange_id": product["exchange_id"],
                "product_id": product["product_id"],
                "instrument_id": row["instrument_id"],
                "asset_type": row["asset_type"],
                "is_trading": row["is_trading"],
                "expiry_date": row["expiry_date"],
                "product_class": row["product_class"],
            }
        )
    stable_catalog_records.sort(
        key=lambda row: (row["exchange_id"], row["product_id"], row["instrument_id"])
    )
    grid_semantics_sha256 = evidence.get("grid_semantics_sha256")
    if type(grid_semantics_sha256) is not str:
        raise RunnerError("LIVE_HISTORY_SELECTION_EVIDENCE_INVALID")
    projection = {
        "selection_source": evidence["selection_source"],
        "routes": evidence["routes"],
        "authorized_targets": sorted(evidence["authorized_targets"]),
        "grid_semantics_sha256": grid_semantics_sha256,
        "manifest": {
            "schema": manifest["schema"],
            "policy": manifest["policy"],
            "target_products": manifest["target_products"],
            "source_ids": {
                "source_id": source["source_id"],
                "catalog_source_id": catalog["source_id"],
            },
            "trading_days": manifest["trading_days"],
            "calendars": stable_calendars,
            "catalog_records": stable_catalog_records,
            "coverage": select_rows(
                manifest["coverage"],
                (
                    "product",
                    "candidate_count",
                    "expected_instrument_ids",
                    "candidate_set_complete",
                    "ranking_values_complete",
                    "finalized",
                    "ranking_trading_day",
                    "open_interest_unit",
                    "volume_unit",
                ),
            ),
            "products": select_rows(
                manifest["products"],
                (
                    "product",
                    "in_target_pool",
                    "status",
                    "expected_prior_trading_day",
                    "ranking_trading_day",
                    "selected_instrument_id",
                ),
            ),
            "query_coverage": select_rows(
                manifest["query_coverage"],
                (
                    "product",
                    "catalog_instrument_ids",
                    "expected_quote_instrument_ids",
                    "metric_unit",
                ),
            ),
        },
    }
    if "active_shadow_targets" in evidence:
        projection.update(
            {
                "full_selected_targets": evidence["full_selected_targets"],
                "active_shadow_targets": evidence["active_shadow_targets"],
                "active_routes": evidence["active_routes"],
                "active_authorized_targets": evidence["active_authorized_targets"],
                "active_grid_semantics_sha256": evidence[
                    "active_grid_semantics_sha256"
                ],
            }
        )
    try:
        return _canonical_json_bytes(projection)
    except RunnerError:
        raise RunnerError("LIVE_HISTORY_SELECTION_EVIDENCE_INVALID") from None


def _live_shutdown_path(cerebro, result, refresh_loop):
    """Return the lifecycle path only when its corresponding proof is complete."""

    winddown_status = getattr(cerebro, "live_bar_cohort_winddown_status", None)
    winddown_reason = getattr(cerebro, "live_bar_cohort_winddown_reason", None)
    if winddown_status == "STOPPED":
        return "final_grid_winddown"

    controlled_stop_proven = (
        winddown_status == "NOT_REACHED"
        and winddown_reason == "final_batch_not_reached"
        and getattr(result, "shutdown_requested", False) is True
        and getattr(result, "shutdown_ready", False) is True
        and getattr(result, "shutdown_blocker", None) is None
        and getattr(result, "shutdown_post_join_confirmed", False) is True
        and getattr(result, "shutdown_post_join_blocker", None) is None
        and getattr(refresh_loop, "shutdown_status", None) == "PASS"
        and getattr(refresh_loop, "joined", False) is True
    )
    if controlled_stop_proven:
        return "controlled_application_stop"

    raise RunnerError(
        "LIVE_CORE_WINDDOWN_NOT_CONFIRMED",
        f"{winddown_status}:{winddown_reason}",
    )


def _new_live_capacity_run_capture(run_id, epoch_id, calendar):
    """Create process-bound count capture only for an explicit live opt-in."""
    from backtrader.research.live_capacity import LiveCapacityRunCapture

    process_id = None
    process_create_time = None
    identity_issue = None
    try:
        process_id = os.getpid()
    except Exception:
        identity_issue = "process_id_unavailable"
    if process_id is not None:
        try:
            import psutil

            process_create_time = psutil.Process(process_id).create_time()
        except Exception:
            identity_issue = "process_create_time_unavailable"
    else:
        identity_issue = "process_id_unavailable"
    try:
        slot_count = len(calendar.slots)
    except Exception:
        slot_count = 0
    return LiveCapacityRunCapture(
        run_id,
        epoch_id=epoch_id,
        calendar_id=getattr(calendar, "calendar_id", None),
        calendar_slot_count=slot_count,
        process_id=process_id,
        process_create_time=process_create_time,
        process_identity_issue=identity_issue,
    )


def _live_capacity_evidence(capture, result, cleanup, *, run_id, epoch_id, run_completed):
    if capture is None:
        return None
    if getattr(result, "_live_capacity_callback_failed", False) is True:
        capture.mark_callback_failure()
    report = dict(capture.report())
    cleanup_complete = _cleanup_complete(cleanup)
    postflight_ok = run_completed is True and cleanup_complete is True
    report["postflight"] = {
        "status": "OBSERVED" if postflight_ok else "INCOMPLETE",
        "run_id": run_id,
        "epoch_id": epoch_id,
        "cleanup_complete": cleanup_complete,
        "run_completed": run_completed is True,
    }
    if not postflight_ok:
        report["status"] = "INCOMPLETE"
        report["issues"] = tuple(
            dict.fromkeys((*report.get("issues", ()), "run_postflight_incomplete"))
        )
    return report


def _live_capacity_retirement_unproven(evidence):
    """Preserve opt-in capture while refusing to treat an unretired epoch as complete."""

    if not isinstance(evidence, Mapping):
        return None
    report = dict(evidence)
    issue = "daily_epoch_retirement_unproven"

    def with_issue(value):
        existing = value if isinstance(value, (tuple, list)) else ()
        result = tuple(existing)
        if issue not in result:
            result += (issue,)
        return result

    report["status"] = "INCOMPLETE"
    report["issues"] = with_issue(report.get("issues"))
    postflight = report.get("postflight")
    if isinstance(postflight, Mapping):
        postflight = dict(postflight)
    else:
        postflight = {}
    postflight["status"] = "INCOMPLETE"
    postflight["retirement_proven"] = False
    postflight["issues"] = with_issue(postflight.get("issues"))
    report["postflight"] = postflight
    return report


def run_live(
    config,
    config_path,
    plan,
    factor_mode,
    direction,
    *,
    decision,
    allow_write_flag,
    _live_store_config_override: Optional[Mapping[str, Any]] = None,
    _live_ready_callback: Optional[Callable[[Mapping[str, Any]], Any]] = None,
    _live_next_callback: Optional[Callable[[Mapping[str, Any]], Any]] = None,
    _capture_live_capacity: bool = False,
    previous_plan=None,
    _include_plan=False,
):
    if _live_ready_callback is not None and not callable(_live_ready_callback):
        raise RunnerError("LIVE_READY_CALLBACK_INVALID")
    if _live_next_callback is not None and not callable(_live_next_callback):
        raise RunnerError("LIVE_NEXT_CALLBACK_INVALID")
    if type(_capture_live_capacity) is not bool:
        raise RunnerError("LIVE_CAPACITY_CAPTURE_FLAG_INVALID")
    golden_targets = _validate_golden_targets_option(
        config,
        mode="live",
        decision=decision,
        allow_write_flag=allow_write_flag,
    )
    if golden_targets is not None and plan is not None:
        raise RunnerError("GOLDEN_TARGETS_QUERY_PLAN_REQUIRED")
    import backtrader as bt
    from backtrader.brokers.btapibroker import BtApiBroker
    from backtrader.stores.registered_sim import RegisteredSimStore
    from alpha003_strategy import Alpha003TargetStrategy

    from backtrader.stores.factor_execution_facts import FactorExecutionTarget

    if _live_store_config_override is not None and decision.effective_tier != "live":
        raise RunnerError("LIVE_STORE_CONFIG_OVERRIDE_REQUIRES_LIVE_MODE")

    max_targets = 256
    query_selection = plan is None
    if query_selection and config["selection"]["source"] != "ctp_query":
        raise RunnerError("CTP_QUERY_SELECTION_NOT_CONFIGURED")
    if plan is not None and len(plan["targets"]) > max_targets:
        raise RunnerError("LIVE_TARGET_CAPACITY_EXCEEDED")
    write_enabled = _write_requested(config, allow_write_flag, decision)
    loss_guard_threshold, loss_guard_max_age = _run_loss_guard_policy(
        config, write_enabled=write_enabled
    )
    age_bound = config["cohort"]["max_live_bar_age_seconds"]
    skew_bound = config["cohort"]["max_future_skew_seconds"]
    if age_bound is None or skew_bound is None:
        raise RunnerError("LIVE_BAR_AGE_PROFILE_REQUIRED")
    age_bound = _number(age_bound, "max_live_bar_age_seconds", positive=True)
    skew_bound = _number(skew_bound, "max_future_skew_seconds", nonnegative=True)
    risk_policy = _risk_policy(config)
    if write_enabled and risk_policy is None:
        raise RunnerError("LIVE_RISK_BUDGETS_REQUIRED")
    scopes = {
        name: _text(config["live"][name], f"live.{name}")
        for name in ("account_scope", "strategy_scope", "logical_run_id")
    }
    journal_path = _resolve_path(config_path, config["live"]["journal_path"], "live.journal_path")
    ready_timeout = _number(
        config["live"]["ready_timeout_seconds"], "ready_timeout_seconds", positive=True
    )
    query_timeout = _number(
        config["live"]["refresh_timeout_seconds"], "refresh_timeout_seconds", positive=True
    )
    overall_timeout = _number(
        config["live"]["refresh_overall_timeout_seconds"],
        "refresh_overall_timeout_seconds",
        positive=True,
    )
    interval = _number(
        config["live"]["refresh_interval_seconds"], "refresh_interval_seconds", positive=True
    )
    shutdown_grace = _number(
        config["live"]["shutdown_grace_seconds"],
        "live.shutdown_grace_seconds",
        positive=True,
    )
    quote_max_age = timedelta(
        seconds=_number(
            config["live"]["quote_max_age_seconds"], "live.quote_max_age_seconds", positive=True
        )
    )
    max_query_age = timedelta(
        seconds=_number(
            config["live"]["query_max_age_seconds"], "live.query_max_age_seconds", positive=True
        )
    )
    if _live_store_config_override is None:
        store_config, api_kwargs = _live_env_config(config)
    else:
        store_config, api_kwargs = _live_env_config(config, override=_live_store_config_override)
    # BtApiStore applies api_kwargs over config, then its CTP wrapper coerces
    # allow_zero_login_response with bool().  That SDK option permits an
    # empty MD login identity for quote-only use, so it cannot back a
    # write-enabled runner session.
    allow_zero_login_response = bool(
        api_kwargs.get(
            "allow_zero_login_response",
            store_config.get("allow_zero_login_response", False),
        )
    )
    if write_enabled and allow_zero_login_response:
        raise RunnerError("LIVE_ZERO_LOGIN_RESPONSE_READ_ONLY")
    simnow_profile = validate_official_simnow_store_profile(store_config, api_kwargs)
    store = None
    broker = None
    journal = None
    refresh_loop = None
    decision_tape = None
    saved_history = None
    result = None
    source_continuity = None
    strategy_ready = False
    strategy_blocker = None
    primary_error = None
    primary_traceback = None
    cleanup = []
    engine_ran = False
    broker_evidence = None
    clock = None
    query_session_ready = False
    selection_snapshot_id = None
    ctp_factor_source_shutdown_required = False
    capacity_capture = None

    def create_store():
        nonlocal store
        if store is not None:
            return store
        wrapper_api_kwargs = dict(api_kwargs)
        wrapper_api_kwargs["ctp_join_observer"] = False
        store = RegisteredSimStore(
            provider="ctp",
            backend="direct",
            allow_writes=write_enabled,
            preserve_raw_bars=True,
            config=store_config,
            api_kwargs=wrapper_api_kwargs,
        )
        if store.registered_sim_route_id != "simnow-registered-v1" or store.sdk_api is not None:
            raise RunnerError("REGISTERED_SIM_STORE_CONTRACT_INVALID")
        return store

    try:
        from backtrader.stores.execution_decision_journal import ExecutionDecisionJournal
        from backtrader.stores.factor_execution import FactorExecutionCoordinator

        if not callable(getattr(bt.Cerebro, "wake_live_bar_cohort", None)):
            raise RunnerError("LIVE_COHORT_WAKE_API_UNAVAILABLE")
        clock = RunnerWallClock()
        history_input = config["inputs"].get("history_decision_tape")
        if (
            history_input is not None
            and config["selection"]["source"] == "ctp_query"
            and not query_selection
        ):
            raise RunnerError("LIVE_HISTORY_FRESH_SELECTION_REQUIRED")
        if history_input is not None and config["selection"]["daily_bundles"]:
            raise RunnerError("LIVE_HISTORY_SELECTION_UNSUPPORTED")
        if query_selection:
            create_store()
            if not store.registered_sim_wait_ready(ready_timeout):
                raise RunnerError("LIVE_CTP_SESSION_NOT_READY")
            login_before_selection = store.registered_sim_login_facts()
            if login_before_selection.get("read_only_ready") is not True:
                raise RunnerError("LIVE_CTP_READ_ONLY_STATE_UNAVAILABLE")
            if write_enabled and login_before_selection.get("trading_ready") is not True:
                raise RunnerError("LIVE_CTP_TRADING_STATE_UNAVAILABLE")
            plan = build_ctp_query_market_plan(store, config, clock=clock)
            if len(plan["targets"]) > max_targets:
                raise RunnerError("LIVE_TARGET_CAPACITY_EXCEEDED")
            if previous_plan is not None:
                _assert_daily_plan_transition(previous_plan, plan)
            login_after_selection = store.registered_sim_login_facts()
            if any(
                login_after_selection.get(key) != login_before_selection.get(key)
                for key in ("trading_day", "connection_generation")
            ):
                raise RunnerError("LIVE_SESSION_CHANGED_DURING_SELECTION")
            plan = _apply_golden_target_subset(plan, golden_targets)
            query_session_ready = True
            selection_snapshot_id = plan["source_snapshot_id"]
        elif plan is None:
            raise RunnerError("LIVE_SELECTION_PLAN_REQUIRED")
        elif history_input is None:
            create_store()
        source_kind = _live_source_lineage_kind(plan)
        startup_time_utc = _aware_datetime(clock.utc_now(), "live startup time")
        if not _remaining_live_grid_minutes(plan["grid"], startup_time_utc):
            raise RunnerError("LIVE_GRID_HAS_NO_REMAINING_COMMON_MINUTES")
        restart_identity = _live_restart_identity(
            config,
            config_path,
            plan,
            factor_mode=factor_mode,
            direction=direction,
            simnow_profile=simnow_profile,
        )
        tape_path = config["output"]["decision_tape_path"]
        tape_budget = config["output"]["decision_tape_max_bytes"]
        if tape_path is None or tape_budget is None:
            raise RunnerError("DECISION_TAPE_PROFILE_REQUIRED")
        if type(tape_budget) is not int or tape_budget < 1:
            raise RunnerError("DECISION_TAPE_BYTE_BUDGET_INVALID")
        journal = ExecutionDecisionJournal(
            journal_path,
            max_payload_bytes=_LIVE_DECISION_JOURNAL_MAX_PAYLOAD_BYTES,
        )
        _reject_legacy_live_source_highwater(journal, scopes)
        selection_evidence = _selection_evidence(
            plan,
            config["cohort"]["epoch_id"],
            max_bytes=tape_budget,
        )
        saved_history = _load_saved_live_history(
            config,
            config_path,
            plan,
            restart_identity=restart_identity,
            selection_evidence=selection_evidence,
            now=startup_time_utc,
            journal=journal,
            scopes=scopes,
            source_kind=source_kind,
        )
        arm_templates = _arm_templates(config, plan) if write_enabled else None
        if saved_history is not None:
            history_cursor = journal.grid_cursor(
                scopes["account_scope"],
                scopes["strategy_scope"],
                saved_history["source_cohort_id"],
            )
            latest_grid_anchor = saved_history["latest_grid_anchor"]
            if latest_grid_anchor is None and history_cursor is not None:
                raise RunnerError("LIVE_HISTORY_JOURNAL_HIGHWATER_MISMATCH")
            if latest_grid_anchor is not None and (
                history_cursor is None
                or _aware_datetime(history_cursor.close_time, "history journal cursor")
                != latest_grid_anchor["close_time"]
                or history_cursor.batch_id != latest_grid_anchor["batch_id"]
                or history_cursor.epoch_id != str(saved_history["source_epoch_id"])
            ):
                raise RunnerError("LIVE_HISTORY_JOURNAL_HIGHWATER_MISMATCH")
            saved_history["prior_grid_cursor_close_time"] = (
                None if history_cursor is None else history_cursor.close_time
            )
            saved_history["prior_grid_cursor_batch_id"] = (
                None if history_cursor is None else history_cursor.batch_id
            )
            _verify_saved_history_decision_anchors(journal, scopes, saved_history)
            saved_history["prior_run_order_intents"] = journal.run_order_count(
                scopes["account_scope"], scopes["strategy_scope"], scopes["logical_run_id"]
            )
        elif journal.source_highwater(
            scopes["account_scope"],
            scopes["strategy_scope"],
            scopes["logical_run_id"],
            source_kind,
        ) is not None:
            raise RunnerError("LIVE_HISTORY_TAPE_REQUIRED_FOR_SOURCE_HIGHWATER")
        if store is None:
            create_store()
        if not query_session_ready and not store.registered_sim_wait_ready(ready_timeout):
            raise RunnerError("LIVE_CTP_SESSION_NOT_READY")
        from backtrader.feeds.ctp_factor_source import (
            CtpFactorSourceBinding,
            CtpFactorSourceCalendar,
            parse_ctp_trading_day,
        )

        if store is None:
            raise RunnerError("LIVE_CTP_STORE_UNAVAILABLE_FOR_FACTOR_SOURCE")
        ctp_factor_source_shutdown_required = True
        expected_md_generation = store.enable_ctp_factor_tick_source()
        source_login = store.registered_sim_login_facts()
        source_trading_day_text = source_login.get("trading_day")
        try:
            source_trading_day = parse_ctp_trading_day(source_trading_day_text)
        except ValueError as exc:
            raise RunnerError("LIVE_CTP_TRADING_DAY_UNAVAILABLE_FOR_FACTOR_SOURCE") from exc
        source_calendar = CtpFactorSourceCalendar.from_grid(
            plan["grid"],
            config["cohort"]["clock_domain_id"],
            plan["session_calendars"],
        )
        cutover_time_utc = _aware_datetime(clock.utc_now(), "live cohort cutover time")
        full_calendar = _make_live_calendar(
            config,
            plan["grid"],
            begin_at=(
                saved_history["first_bucket_start"]
                if saved_history is not None
                else cutover_time_utc
            ),
            ctp_trading_days=True,
        )
        calendar = full_calendar
        source_restart_marker = None
        if saved_history is not None:
            from backtrader.research.live_cohort import (
                LiveCohortError,
                LiveCohortCalendar,
            )
            from backtrader.stores.execution_decision_journal import (
                ExecutionSourceRestartMarker,
            )

            slots_by_id = {slot.slot_id: index for index, slot in enumerate(full_calendar.slots)}
            highwater_index = slots_by_id.get(saved_history["calendar_highwater"].slot_id)
            first_live = next(
                (
                    slot
                    for slot in full_calendar.slots
                    if slot.bucket_start >= cutover_time_utc
                ),
                None,
            )
            if highwater_index is None or first_live is None:
                raise RunnerError("LIVE_HISTORY_RESTART_CALENDAR_UNAVAILABLE")
            first_live_index = slots_by_id[first_live.slot_id]
            if first_live_index <= highwater_index:
                raise RunnerError("LIVE_HISTORY_RESTART_CALENDAR_ORDER_INVALID")
            if first_live_index == highwater_index + 1:
                gap_fingerprint = None
            else:
                try:
                    calendar = LiveCohortCalendar.with_restart_gap(
                        full_calendar,
                        startup_time_utc=cutover_time_utc,
                        journal_highwater=saved_history["calendar_highwater"],
                        first_live_slot_id=first_live.slot_id,
                    )
                except LiveCohortError as error:
                    raise RunnerError("LIVE_HISTORY_RESTART_GAP_INVALID") from error
                gap_fingerprint = calendar.restart_gap.fingerprint
            source_restart_marker = ExecutionSourceRestartMarker(
                prior_highwater=saved_history["source_highwater"].reference,
                gap_fingerprint=gap_fingerprint,
            )
            saved_history["restart_gap_fingerprint"] = gap_fingerprint
            saved_history["first_live_slot_id"] = first_live.slot_id
        cohort = _make_cohort(
            config,
            plan["grid"],
            calendar_override=calendar,
            ctp_trading_days=True,
        )
        if _capture_live_capacity:
            capacity_capture = _new_live_capacity_run_capture(
                scopes["logical_run_id"], config["cohort"]["epoch_id"], calendar
            )
        decision_tape = _new_decision_tape(
            config,
            config_path,
            plan,
            mode="live",
            factor_mode=factor_mode,
            direction=direction,
            source_snapshot_id=plan.get("source_snapshot_id"),
            restart_identity=restart_identity,
            selection_evidence=selection_evidence,
            calendar_fingerprint=cohort.calendar_fingerprint,
        )
        broker = BtApiBroker(
            store=store,
            provider="ctp",
            market_data_only=not write_enabled,
            force_refresh_queries=False,
            require_complete_ctp_evidence=True,
            flatten_on_stop=False,
            contract_metadata={
                target: {
                    "instrument_id": plan["routes"][plan["product_by_target"][target]],
                    "exchange_id": plan["product_by_target"][target].exchange_id,
                }
                for target in plan["targets"]
            },
        )
        grid_budget = risk_policy.max_order_intents_per_grid if risk_policy is not None else 0
        run_budget = risk_policy.max_order_intents_per_run if risk_policy is not None else 0
        coordinator = FactorExecutionCoordinator(
            broker,
            journal,
            account_scope=scopes["account_scope"],
            strategy_scope=scopes["strategy_scope"],
            logical_run_id=scopes["logical_run_id"],
            max_order_intents_per_grid=grid_budget,
            max_order_intents_per_run=run_budget,
        )
        cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
        cerebro.setbroker(broker)
        query_targets = []
        for target in plan["targets"]:
            product = plan["product_by_target"][target]
            instrument = plan["routes"][product]
            history_origin = None
            feed_options = {}
            if saved_history is not None:
                from backtrader.research.live_cohort import LiveSourceOrigin

                history_bars = saved_history["bars_by_target"][target]
                first_history = history_bars[0]
                source_ref = f"ctp-live:{target}:{instrument}"
                history_origin = LiveSourceOrigin(
                    member_id=target,
                    epoch_id=config["cohort"]["epoch_id"],
                    source_ref=source_ref,
                    source_role="history",
                    connection_generation=first_history["connection_generation"],
                    bar_id=first_history["bar_id"],
                    feed_sequence=first_history["bar_sequence"],
                    close_time=first_history["bucket_end"],
                    origin_partition=first_history["origin_partition"],
                )
                feed_options = {
                    "historical_bars": history_bars,
                    "cohort_source_origin": history_origin,
                }
            feed_options["ctp_factor_source_binding"] = CtpFactorSourceBinding(
                calendar=source_calendar,
                target_id=target,
                product=product,
                instrument_id=instrument,
                exchange_id=product.exchange_id,
                trader_trading_day=source_trading_day,
                expected_md_generation=expected_md_generation,
            )
            data = store.getdata(
                dataname=instrument,
                backfill_start=False,
                timeframe=bt.TimeFrame.Minutes,
                compression=1,
                clock=clock,
                cohort_source_mode=True,
                bar_watermark_ms=int(store_config.get("bar_watermark_ms", 500)),
                **feed_options,
            )
            cerebro.adddata(data, name=target)
            cohort.register_member(
                target,
                data,
                instrument=instrument,
                source_ref=f"ctp-live:{target}:{instrument}",
                line_fields=OHLCV_FIELDS,
                raw_fields=OHLCV_FIELDS,
                clock_domain_id=config["cohort"]["clock_domain_id"],
                timezone_id=config["cohort"]["timezone_id"],
                session_semantics=config["cohort"]["session_semantics"],
                numeric_fields=OHLCV_FIELDS,
                source_origin=history_origin,
            )
            query_targets.append(
                FactorExecutionTarget(
                    target_id=target,
                    instrument=instrument,
                    exchange=product.exchange_id,
                    data=data,
                )
            )
        if saved_history is not None:
            from backtrader.research.live_cohort import (
                LiveCohortError,
                _SAVED_HISTORY_ANCHOR_EVENT_KEY,
                _VERIFIED_HISTORY_PROOF_EVENT_KEY,
            )

            verified_anchors = saved_history.get("verified_journal_anchors")
            if not isinstance(verified_anchors, Mapping):
                raise RunnerError("LIVE_HISTORY_JOURNAL_DECISION_ANCHOR_MISMATCH")
            authorized_history_sources = {}
            for target in plan["targets"]:
                data = next(item.data for item in query_targets if item.target_id == target)
                authorized_events = []
                for event in data._cohort_history_source:
                    anchor_identity = event.get(_SAVED_HISTORY_ANCHOR_EVENT_KEY)
                    anchor = verified_anchors.get((anchor_identity, target))
                    if anchor is None:
                        raise RunnerError("LIVE_HISTORY_JOURNAL_DECISION_ANCHOR_MISMATCH")
                    try:
                        proof = cohort._issue_verified_saved_history_origin_proof(
                            data, event, anchor
                        )
                    except LiveCohortError as error:
                        raise RunnerError("LIVE_HISTORY_ORIGIN_PROOF_INVALID", target) from error
                    authorized_event = dict(event)
                    authorized_event[_VERIFIED_HISTORY_PROOF_EVENT_KEY] = proof
                    authorized_events.append(MappingProxyType(authorized_event))
                authorized_history_sources[target] = tuple(authorized_events)
            # Sign and validate every feed's complete history window before
            # replacing any source tuple that Cerebro could later consume.
            for target in plan["targets"]:
                data = next(item.data for item in query_targets if item.target_id == target)
                data._cohort_history_source = authorized_history_sources[target]
        cohort.seal()
        cerebro.add_live_bar_cohort(
            cohort,
            clock=clock,
            winddown_timeout_seconds=shutdown_grace,
        )

        login = store.registered_sim_login_facts()
        if login.get("trading_day") != source_trading_day_text:
            raise RunnerError("LIVE_SESSION_CHANGED_DURING_FACTOR_SOURCE_BINDING")
        if login.get("read_only_ready") is not True:
            raise RunnerError("LIVE_CTP_READ_ONLY_STATE_UNAVAILABLE")
        if write_enabled and login.get("trading_ready") is not True:
            raise RunnerError("LIVE_CTP_TRADING_STATE_UNAVAILABLE")
        if write_enabled:
            # Make the full validated route plan visible to the first sealed
            # Facts refresh.  Template registration is not native arming and
            # does not acquire or switch an execution capability.
            store.registered_sim_configure_arm_templates(arm_templates)

        refresh_loop = QueryRefreshLoop(
            store,
            broker,
            tuple(query_targets),
            execution_target_ids=tuple(plan["authorized_targets"]),
            commission_identity_by_target=(
                _commission_identity_by_target(config, tuple(plan["authorized_targets"]))
                if write_enabled
                else None
            ),
            commission_required_for_open=write_enabled,
            coordinator=coordinator,
            account_scope=scopes["account_scope"],
            strategy_scope=scopes["strategy_scope"],
            clock=clock,
            quote_max_age=quote_max_age,
            max_query_age=max_query_age,
            timeout=query_timeout,
            overall_timeout=overall_timeout,
            interval=interval,
            cerebro=cerebro,
            shutdown_grace_seconds=shutdown_grace,
        )
        try:
            refresh_loop.refresh_initial(wait_timeout=ready_timeout)
        except Exception as error:
            refresh_loop.last_error_code = refresh_loop._execution_error_code(error)
            if write_enabled:
                raise RunnerError("LIVE_INITIAL_QUERY_REFRESH_FAILED") from None
        if write_enabled and refresh_loop.last_error_code is not None:
            raise RunnerError("LIVE_INITIAL_QUERY_REFRESH_INCOMPLETE")

        strategy_kwargs = _make_strategy_kwargs(
            config,
            plan,
            factor_mode,
            direction,
            risk_policy,
            replay=False,
            cohort=cohort,
            account_scope=scopes["account_scope"],
            logical_run_id=scopes["logical_run_id"],
            replay_quotes=(),
            replay_instruments={},
            quote_max_age_seconds=quote_max_age.total_seconds(),
            max_query_age_seconds=max_query_age.total_seconds(),
            max_live_bar_age_seconds=age_bound,
            max_future_skew_seconds=skew_bound,
            live_ready_callback=_live_ready_callback,
            live_next_callback=_live_next_callback,
            execution_enabled=write_enabled,
            loss_guard_net_loss_threshold=loss_guard_threshold,
            loss_guard_max_observation_age_seconds=loss_guard_max_age,
            decision_tape=decision_tape,
            source_restart_marker=source_restart_marker,
            source_kind=source_kind,
            live_capacity_callback=(
                None
                if capacity_capture is None
                else lambda strategy, event: capacity_capture.observe(
                    strategy, event, store=store
                )
            ),
        )
        strategy_kwargs["control_refresh_loop"] = refresh_loop
        cerebro.addstrategy(Alpha003TargetStrategy, **strategy_kwargs)
        refresh_loop.start()
        signal_handlers = _install_shutdown_signal_handlers(refresh_loop)
        try:
            engine_ran = True
            result = cerebro.run(runonce=False, preload=False)[0]
            winddown_status = getattr(cerebro, "live_bar_cohort_winddown_status", None)
            winddown_reason = getattr(cerebro, "live_bar_cohort_winddown_reason", None)
            shutdown_path = _live_shutdown_path(cerebro, result, refresh_loop)
            strategy_shutdown_requested = (
                getattr(result, "shutdown_requested", False) is True
            )
            strategy_ready = getattr(result, "shutdown_ready", False) is True
            strategy_blocker = getattr(result, "shutdown_blocker", None)
            if not strategy_ready or strategy_blocker is not None:
                raise RunnerError(
                    "LIVE_STRATEGY_SHUTDOWN_NOT_CONFIRMED",
                    strategy_blocker if type(strategy_blocker) is str else None,
                )
            strategy_post_join_confirmed = (
                getattr(result, "shutdown_post_join_confirmed", False) is True
            )
            strategy_post_join_blocker = getattr(result, "shutdown_post_join_blocker", None)
            if not strategy_post_join_confirmed or strategy_post_join_blocker is not None:
                raise RunnerError(
                    "LIVE_STRATEGY_POST_JOIN_RETIREMENT_NOT_CONFIRMED",
                    strategy_post_join_blocker if type(strategy_post_join_blocker) is str else None,
                )
        finally:
            _restore_shutdown_signal_handlers(signal_handlers)
    except BaseException as error:
        primary_error = error
        primary_traceback = error.__traceback__
    finally:
        if refresh_loop is None:
            cleanup.append(
                {
                    "resource": "query_refresh",
                    "status": "NOT_CREATED",
                    "started": False,
                    "joined": True,
                }
            )
            refresh_joined = True
        else:
            loop_result = _cleanup_live_resource(
                cleanup,
                "query_refresh",
                refresh_loop.stop_and_join,
            )
            loop_result["started"] = refresh_loop.started
            loop_result["joined"] = refresh_loop.joined
            refresh_joined = refresh_loop.joined

        if decision_tape is None:
            cleanup.append({"resource": "decision_tape", "status": "NOT_CREATED"})
        else:
            _cleanup_live_resource(
                cleanup,
                "decision_tape",
                decision_tape.close,
                project=lambda summary: {
                    "status": "CLOSED"
                    if summary.get("closed") is True and summary.get("failed") is False
                    else "UNPROVEN",
                    "record_count": summary.get("record_count"),
                    "bytes": summary.get("bytes"),
                    "sha256": summary.get("sha256"),
                },
            )

        if broker is None:
            cleanup.append(
                {"resource": "broker", "status": "NOT_CREATED", "store_shutdown_state": "UNPROVEN"}
            )
        else:
            broker_evidence = _broker_shutdown_evidence(broker)
            if not engine_ran and broker_evidence["status"] == "NOT_STARTED":
                broker_evidence["status"] = "NOT_RUN"
            cleanup.append({"resource": "broker", **broker_evidence})

        if store is None:
            cleanup.append(
                {"resource": "store", "status": "NOT_CREATED", "shutdown_state": "NOT_CREATED"}
            )
        elif not refresh_joined:
            cleanup.append(
                {
                    "resource": "store",
                    "status": "SKIPPED_REFRESH_UNJOINED",
                    "shutdown_state": "UNPROVEN",
                }
            )
        elif engine_ran:
            try:
                store_health = store.get_command_health()
                store_projection = _store_stop_evidence(
                    store_health,
                    ctp_factor_source_required=ctp_factor_source_shutdown_required,
                )
            except BaseException:
                store_projection = {
                    "shutdown_state": "UNPROVEN",
                    "ctp_factor_source_shutdown": {
                        "required": True,
                        "status": "UNPROVEN",
                    },
                }
            broker_closed = (
                broker_evidence is not None
                and broker_evidence.get("status")
                in {"PASS", "OBSERVATION_ONLY", "OBSERVATION_ONLY_NONFLAT"}
                and broker_evidence.get("store_shutdown_state") == "PASS"
            )
            source_closed = _ctp_factor_source_shutdown_complete(
                store_projection.get("ctp_factor_source_shutdown")
            )
            if (
                broker_closed
                and store_projection.get("shutdown_state") == "PASS"
                and source_closed
            ):
                # Cerebro has already stopped the Broker, which owns this
                # Store's lifecycle. Do not make a second stop call.
                cleanup.append(
                    {"resource": "store", "status": "CLOSED_BY_BROKER", **store_projection}
                )
            else:
                cleanup.append(
                    {
                        "resource": "store",
                        "status": "SKIPPED_BROKER_SHUTDOWN_UNPROVEN",
                        **store_projection,
                    }
                )
        else:
            _cleanup_live_resource(
                cleanup,
                "store",
                store.stop,
                project=lambda summary: _store_stop_evidence(
                    summary,
                    ctp_factor_source_required=ctp_factor_source_shutdown_required,
                ),
            )

        if result is not None and decision_tape is not None:
            source_continuity = _live_source_continuity_status(
                journal,
                scopes,
                decision_tape,
                result,
                source_kind=source_kind,
            )

        if journal is None:
            cleanup.append({"resource": "journal", "status": "NOT_CREATED"})
        elif not refresh_joined:
            cleanup.append({"resource": "journal", "status": "SKIPPED_REFRESH_UNJOINED"})
        else:
            if saved_history is not None:
                saved_history["run_order_intents_after"] = journal.run_order_count(
                    scopes["account_scope"],
                    scopes["strategy_scope"],
                    scopes["logical_run_id"],
                )
            _cleanup_live_resource(
                cleanup,
                "journal",
                journal.close,
                project=lambda _result: {"status": "CLOSED"},
            )

    if primary_error is not None:
        _attach_cleanup_results(primary_error, cleanup)
        if capacity_capture is not None:
            primary_error.live_capacity = _live_capacity_evidence(
                capacity_capture,
                result,
                cleanup,
                run_id=scopes["logical_run_id"],
                epoch_id=config["cohort"]["epoch_id"],
                run_completed=False,
            )
        _attach_live_epoch_failure_evidence(
            primary_error, config, plan, locals().get("cerebro"), refresh_loop, cleanup
        )
        _attach_unclosed_live_resources(
            primary_error,
            {
                "cerebro": locals().get("cerebro"),
                "refresh_loop": refresh_loop,
                "broker": broker,
                "store": store,
                "journal": journal,
                "decision_tape": decision_tape,
            },
            cleanup,
        )
        raise primary_error.with_traceback(primary_traceback)
    if refresh_loop is not None and refresh_loop.shutdown_status != "PASS":
        error = RunnerError(
            "LIVE_SHUTDOWN_NOT_CONFIRMED",
            refresh_loop.shutdown_blocker or refresh_loop.shutdown_status,
        )
        _attach_cleanup_results(error, cleanup)
        if capacity_capture is not None:
            error.live_capacity = _live_capacity_evidence(
                capacity_capture,
                result,
                cleanup,
                run_id=scopes["logical_run_id"],
                epoch_id=config["cohort"]["epoch_id"],
                run_completed=False,
            )
        _attach_live_epoch_failure_evidence(
            error, config, plan, locals().get("cerebro"), refresh_loop, cleanup
        )
        _attach_unclosed_live_resources(
            error,
            {
                "cerebro": locals().get("cerebro"),
                "refresh_loop": refresh_loop,
                "broker": broker,
                "store": store,
                "journal": journal,
                "decision_tape": decision_tape,
            },
            cleanup,
        )
        raise error
    if not _cleanup_complete(cleanup):
        error = RunnerError("LIVE_RESOURCE_CLEANUP_INCOMPLETE")
        _attach_cleanup_results(error, cleanup)
        if capacity_capture is not None:
            error.live_capacity = _live_capacity_evidence(
                capacity_capture,
                result,
                cleanup,
                run_id=scopes["logical_run_id"],
                epoch_id=config["cohort"]["epoch_id"],
                run_completed=False,
            )
        _attach_live_epoch_failure_evidence(
            error, config, plan, locals().get("cerebro"), refresh_loop, cleanup
        )
        _attach_unclosed_live_resources(
            error,
            {
                "cerebro": locals().get("cerebro"),
                "refresh_loop": refresh_loop,
                "broker": broker,
                "store": store,
                "journal": journal,
                "decision_tape": decision_tape,
            },
            cleanup,
        )
        raise error
    if (
        source_continuity is not None
        and source_continuity["record_count"] > 0
        and source_continuity["available"] is not True
    ):
        error = RunnerError("LIVE_SOURCE_CONTINUITY_UNAVAILABLE")
        error.source_continuity = dict(source_continuity)
        _attach_cleanup_results(error, cleanup)
        if capacity_capture is not None:
            error.live_capacity = _live_capacity_evidence(
                capacity_capture,
                result,
                cleanup,
                run_id=scopes["logical_run_id"],
                epoch_id=config["cohort"]["epoch_id"],
                run_completed=False,
            )
        _attach_live_epoch_failure_evidence(
            error, config, plan, locals().get("cerebro"), refresh_loop, cleanup
        )
        raise error
    try:
        decision_tape_readback = _decision_tape_readback(
            decision_tape.path,
            decision_tape.max_bytes,
        )
        if (
            decision_tape_readback["file_id"] != decision_tape.file_id
            or decision_tape_readback["record_count"] != decision_tape.summary()["record_count"]
        ):
            raise RunnerError("DECISION_TAPE_READBACK_MISMATCH")
    except BaseException as error:
        _attach_cleanup_results(error, cleanup)
        if capacity_capture is not None:
            error.live_capacity = _live_capacity_evidence(
                capacity_capture,
                result,
                cleanup,
                run_id=scopes["logical_run_id"],
                epoch_id=config["cohort"]["epoch_id"],
                run_completed=False,
            )
        _attach_live_epoch_failure_evidence(
            error, config, plan, locals().get("cerebro"), refresh_loop, cleanup
        )
        raise
    live_capacity_evidence = _live_capacity_evidence(
        capacity_capture,
        result,
        cleanup,
        run_id=scopes["logical_run_id"],
        epoch_id=config["cohort"]["epoch_id"],
        run_completed=True,
    )
    summary = {
        "status": "LIVE_RUN_COMPLETE",
        "mode": "live",
        "epoch_id": config["cohort"]["epoch_id"],
        "selection_path": str(plan["selection_path"]),
        "selection_source": plan["selection_source"],
        "source_snapshot_id": plan.get("source_snapshot_id"),
        "selection_evidence": selection_evidence,
        "simnow_profile": {
            "verified": simnow_profile["verified"],
            "environment": simnow_profile["environment"],
            "profile": simnow_profile["profile"],
        },
        "calendar_evidence_mode": plan.get("calendar_evidence_mode"),
        "calendar_rules_sha256": plan.get("calendar_rules_sha256"),
        "selection_decision_at": plan["manifest"].decision_at.isoformat(),
        "trading_days": {
            row.exchange_id: row.current_trading_day.isoformat()
            for row in plan["manifest"].trading_days
        },
        "routes": {
            target: plan["routes"][plan["product_by_target"][target]] for target in plan["targets"]
        },
        "tier": decision.effective_tier,
        "write_mode": write_enabled,
        "factor_mode": factor_mode,
        "source_clock_domain_id": config["cohort"]["clock_domain_id"],
        "scheduler_clock": "host-utc-plus-monotonic",
        "last_signal_block_reason": getattr(result, "last_signal_block_reason", None),
        "refresh_blockers": list(getattr(refresh_loop.last_receipt, "blockers", ()))
        if refresh_loop
        else [],
        "refresh_error_code": refresh_loop.last_error_code if refresh_loop else "NOT_CREATED",
        "journal_enabled": journal is not None,
        "shutdown_status": refresh_loop.shutdown_status if refresh_loop else "NOT_REQUESTED",
        "shutdown_blocker": refresh_loop.shutdown_blocker if refresh_loop else None,
        "strategy_shutdown_ready": strategy_ready,
        "strategy_shutdown_requested": strategy_shutdown_requested,
        "strategy_shutdown_blocker": strategy_blocker,
        "strategy_shutdown_post_join_confirmed": strategy_post_join_confirmed,
        "strategy_shutdown_post_join_blocker": strategy_post_join_blocker,
        "engine_winddown_status": getattr(cerebro, "live_bar_cohort_winddown_status", None),
        "engine_winddown_reason": getattr(cerebro, "live_bar_cohort_winddown_reason", None),
        "shutdown_path": shutdown_path,
        "decision_tape": decision_tape.summary(),
        "decision_tape_readback": decision_tape_readback,
        "source_continuity": source_continuity
        if source_continuity is not None
        else {
            "status": "NOT_APPLICABLE",
            "available": False,
            "record_count": 0,
            "failure_count": 0,
            "first_error": None,
            "final_highwater_matches_tape": None,
            "reason": "NO_ROWS",
        },
        "history_resume": (
            None
            if saved_history is None
            else {
                "source_file_id": saved_history["source_file_id"],
                "source_epoch_id": saved_history["source_epoch_id"],
                "source_cohort_id": saved_history["source_cohort_id"],
                "restored_bar_count": saved_history["bar_count"],
                "first_bucket_start": _json_time(saved_history["first_bucket_start"]),
                "last_close_time": _json_time(saved_history["last_close_time"]),
                "prior_grid_cursor_close_time": saved_history["prior_grid_cursor_close_time"],
                "prior_grid_cursor_batch_id": saved_history["prior_grid_cursor_batch_id"],
                "prior_run_order_intents": saved_history["prior_run_order_intents"],
                "run_order_intents_after": saved_history["run_order_intents_after"],
                "restart_gap_fingerprint": saved_history["restart_gap_fingerprint"],
                "first_live_slot_id": saved_history["first_live_slot_id"],
            }
        ),
        "strategy_order_events": _project_strategy_order_events(
            result, plan, config["cohort"]["epoch_id"]
        ),
        "resource_shutdown": cleanup,
        "cleanup_complete": _cleanup_complete(cleanup),
    }
    if live_capacity_evidence is not None:
        summary["live_capacity"] = live_capacity_evidence
    if plan.get("golden_targets") is not None:
        summary.update(
            {
                "full_selected_targets": list(plan["full_selected_targets"]),
                "active_shadow_targets": list(plan["active_shadow_targets"]),
            }
        )
    if _include_plan:
        summary["_plan"] = plan
    return summary


def _route_summary(plan):
    if plan is None:
        return {}
    return {target: plan["routes"][plan["product_by_target"][target]] for target in plan["targets"]}


def _assert_daily_plan_transition(previous, current):
    """Keep the product pool fixed while requiring a later PIT epoch."""

    previous_products = previous.get("full_products", previous["products"])
    current_products = current.get("full_products", current["products"])
    if set(previous_products) != set(current_products):
        raise RunnerError("DAILY_SELECTION_PRODUCT_POOL_CHANGED")
    if previous["manifest"].policy != current["manifest"].policy:
        raise RunnerError("DAILY_SELECTION_POLICY_CHANGED")
    previous_authorized = previous.get("full_authorized_targets", previous["authorized_targets"])
    current_authorized = current.get("full_authorized_targets", current["authorized_targets"])
    if set(previous_authorized) != set(current_authorized):
        raise RunnerError("DAILY_SELECTION_AUTHORIZED_POOL_CHANGED")
    if set(previous["session_calendars"]) != set(current["session_calendars"]):
        raise RunnerError("DAILY_SELECTION_EXCHANGE_SET_CHANGED")
    previous_decision = _aware_datetime(
        previous["manifest"].decision_at, "previous selection decision_at"
    )
    current_decision = _aware_datetime(
        current["manifest"].decision_at, "next selection decision_at"
    )
    if current_decision <= previous_decision:
        raise RunnerError("DAILY_SELECTION_DECISION_TIME_NOT_ADVANCED")
    previous_days = {
        row.exchange_id: row.current_trading_day for row in previous["manifest"].trading_days
    }
    current_days = {
        row.exchange_id: row.current_trading_day for row in current["manifest"].trading_days
    }
    if set(previous_days) != set(current_days):
        raise RunnerError("DAILY_SELECTION_TRADING_DAY_SET_CHANGED")
    if any(current_days[exchange] <= day for exchange, day in previous_days.items()):
        raise RunnerError("DAILY_SELECTION_TRADING_DAY_NOT_ADVANCED")


def _daily_epoch_tape_path(config, config_path, *, epoch_index):
    base = _resolve_path(
        config_path,
        config["output"]["decision_tape_path"],
        "output.decision_tape_path",
    )
    if epoch_index == 0:
        return base
    return base.with_name(f"{base.stem}.epoch-{epoch_index + 1:04d}{base.suffix or '.jsonl'}")


def _live_epoch_retired(summary):
    if not isinstance(summary, Mapping):
        return False
    resources = summary.get("resource_shutdown")
    if not isinstance(resources, list):
        return False
    rows = {row.get("resource"): row for row in resources if isinstance(row, Mapping)}
    loop = rows.get("query_refresh", {})
    store = rows.get("store", {})
    return bool(
        summary.get("status") == "LIVE_RUN_COMPLETE"
        and summary.get("engine_winddown_status") == "STOPPED"
        and summary.get("strategy_shutdown_ready") is True
        and summary.get("strategy_shutdown_blocker") is None
        and summary.get("strategy_shutdown_post_join_confirmed") is True
        and summary.get("strategy_shutdown_post_join_blocker") is None
        and summary.get("shutdown_status") == "PASS"
        and summary.get("cleanup_complete") is True
        and _cleanup_complete(resources)
        and loop.get("joined") is True
        and store.get("shutdown_state") == "PASS"
    )


def _live_epoch_controlled_stopped(summary):
    """Accept an explicit app stop only after the same strict cleanup proof."""

    if not isinstance(summary, Mapping):
        return False
    resources = summary.get("resource_shutdown")
    if not isinstance(resources, list) or not all(
        isinstance(row, Mapping) for row in resources
    ):
        return False
    rows = {row.get("resource"): row for row in resources}
    loop = rows.get("query_refresh", {})
    store = rows.get("store", {})
    return bool(
        summary.get("status") == "LIVE_RUN_COMPLETE"
        and summary.get("shutdown_path") == "controlled_application_stop"
        and summary.get("engine_winddown_status") == "NOT_REACHED"
        and summary.get("engine_winddown_reason") == "final_batch_not_reached"
        and summary.get("strategy_shutdown_requested") is True
        and summary.get("strategy_shutdown_ready") is True
        and summary.get("strategy_shutdown_blocker") is None
        and summary.get("strategy_shutdown_post_join_confirmed") is True
        and summary.get("strategy_shutdown_post_join_blocker") is None
        and summary.get("shutdown_status") == "PASS"
        and summary.get("shutdown_blocker") is None
        and summary.get("cleanup_complete") is True
        and _cleanup_complete(resources)
        and loop.get("joined") is True
        and store.get("shutdown_state") == "PASS"
    )


def _run_ctp_query_live_epochs(
    config,
    config_path,
    factor_mode,
    direction,
    *,
    decision,
    allow_write_flag,
    _live_store_config_override: Optional[Mapping[str, Any]] = None,
    _capture_live_capacity: bool = False,
):
    """Query and run epochs serially, creating no next Store early."""

    if decision.effective_tier != "live":
        raise RunnerError("QUERY_SELECTION_LIVE_TIER_REQUIRED")
    count = config["selection"]["max_epochs"]
    if count > 1:
        risk_policy = _risk_policy(config)
        if risk_policy is None or risk_policy.run_end_policy != "CLOSE_ALL":
            raise RunnerError("DAILY_ROLLOVER_CLOSE_ALL_POLICY_REQUIRED")

    original_epoch = config["cohort"]["epoch_id"]
    if type(original_epoch) is not int or original_epoch < 1:
        raise RunnerError("COHORT_EPOCH_INVALID")
    summaries = []
    query_attempts = []
    assembly_attempts = []
    previous_plan = None
    previous_result = None
    failed_epoch = None
    sequence_status = "LIVE_EPOCH_SEQUENCE_COMPLETE"
    stop_reason = None
    try:
        for index in range(count):
            epoch_config = deepcopy(config)
            epoch_config["cohort"]["epoch_id"] = original_epoch + index
            epoch_config["output"]["decision_tape_path"] = str(
                _daily_epoch_tape_path(config, config_path, epoch_index=index)
            )
            if index:
                epoch_config["inputs"]["history_decision_tape"] = None
            epoch_id = epoch_config["cohort"]["epoch_id"]
            assembly_attempts.append(epoch_id)
            query_attempts.append(epoch_id)
            # run_live creates one Store, queries it after readiness, then
            # assembles the plan and engine from that same Store. This call
            # returns only after the prior epoch's cleanup has completed.
            result = run_live(
                epoch_config,
                config_path,
                None,
                factor_mode,
                direction,
                decision=decision,
                allow_write_flag=allow_write_flag,
                _live_store_config_override=_live_store_config_override,
                _capture_live_capacity=_capture_live_capacity,
                previous_plan=previous_plan,
                _include_plan=True,
            )
            plan = result.pop("_plan")
            retired = _live_epoch_retired(result)
            controlled_stop = _live_epoch_controlled_stopped(result)
            if not retired and not controlled_stop:
                failed_epoch = {
                    "epoch_id": epoch_id,
                    "selection_path": result.get("selection_path"),
                    "selection_source": result.get("selection_source"),
                    "routes": _route_summary(plan),
                    "status": "RETIREMENT_UNPROVEN",
                    "engine_winddown_status": result.get("engine_winddown_status"),
                    "strategy_shutdown_ready": result.get("strategy_shutdown_ready"),
                    "strategy_shutdown_blocker": result.get("strategy_shutdown_blocker"),
                    "strategy_shutdown_post_join_confirmed": result.get(
                        "strategy_shutdown_post_join_confirmed"
                    ),
                    "strategy_shutdown_post_join_blocker": result.get(
                        "strategy_shutdown_post_join_blocker"
                    ),
                    "shutdown_status": result.get("shutdown_status"),
                    "resource_shutdown": result.get("resource_shutdown", []),
                    "cleanup_complete": result.get("cleanup_complete") is True,
                    "live_capacity": _live_capacity_retirement_unproven(
                        result.get("live_capacity")
                    ),
                }
                raise RunnerError("DAILY_EPOCH_RETIREMENT_UNPROVEN", f"epoch={epoch_id}")
            row = {
                "epoch_id": epoch_id,
                "selection_source": plan["selection_source"],
                "selection_path": str(plan["selection_path"]),
                "source_snapshot_id": plan.get("source_snapshot_id"),
                "selection_evidence": result["selection_evidence"],
                "simnow_profile": result["simnow_profile"],
                "selection_decision_at": plan["manifest"].decision_at.isoformat(),
                "calendar_evidence_mode": result.get("calendar_evidence_mode"),
                "calendar_rules_sha256": result.get("calendar_rules_sha256"),
                "trading_days": {
                    item.exchange_id: item.current_trading_day.isoformat()
                    for item in plan["manifest"].trading_days
                },
                "routes": _route_summary(plan),
                "status": result["status"],
                "retirement_proven": retired,
                "shutdown_path": result.get("shutdown_path"),
                "shutdown_status": result["shutdown_status"],
                "strategy_shutdown_ready": result["strategy_shutdown_ready"],
                "strategy_shutdown_post_join_confirmed": result[
                    "strategy_shutdown_post_join_confirmed"
                ],
                "engine_winddown_status": result["engine_winddown_status"],
                "cleanup_complete": result["cleanup_complete"],
                "decision_tape": result["decision_tape"],
                "decision_tape_readback": result["decision_tape_readback"],
                "strategy_order_events": result.get("strategy_order_events"),
                "live_capacity": result.get("live_capacity"),
            }
            if plan.get("golden_targets") is not None:
                row.update(
                    {
                        "full_selected_targets": list(plan["full_selected_targets"]),
                        "active_shadow_targets": list(plan["active_shadow_targets"]),
                    }
                )
            summaries.append(row)
            previous_plan = plan
            previous_result = result
            if controlled_stop:
                sequence_status = "LIVE_EPOCH_SEQUENCE_STOPPED"
                stop_reason = "controlled_application_stop"
                break
    except BaseException as error:
        failed_epoch = failed_epoch or getattr(error, "live_epoch_evidence", None)
        try:
            error.epoch_results = tuple(dict(row) for row in summaries)
            error.query_epoch_attempts = tuple(query_attempts)
            error.later_bundle_reads = ()
            error.assembly_attempts = tuple(assembly_attempts)
            error.previous_epoch_routes = (
                _route_summary(previous_plan) if previous_plan is not None else None
            )
            error.previous_epoch_status = (
                previous_result.get("status") if previous_result is not None else None
            )
            if failed_epoch is not None:
                error.failed_epoch = dict(failed_epoch)
            error.next_bundle_read_count = 0
            error.next_bundle_loaded = False
            error.next_epoch_load_permitted = False
            error.next_query_permitted = False
        except Exception:
            pass
        raise

    summary = {
        "status": sequence_status,
        "mode": "live",
        "tier": decision.effective_tier,
        "write_mode": bool(allow_write_flag),
        "factor_mode": factor_mode,
        "selection_source": "ctp_query_snapshot_equal_weight_v1",
        "epoch_count": len(summaries),
        "epochs": summaries,
        "query_epoch_attempts": query_attempts,
        "later_bundle_reads": [],
        "assembly_attempts": assembly_attempts,
        "cleanup_complete": all(row["cleanup_complete"] for row in summaries),
        "next_epoch_loaded": len(summaries) > 1,
        "stop_reason": stop_reason,
    }
    if summaries and "active_shadow_targets" in summaries[-1]:
        summary.update(
            {
                "full_selected_targets": summaries[-1]["full_selected_targets"],
                "active_shadow_targets": summaries[-1]["active_shadow_targets"],
            }
        )
    return summary


def run_live_epochs(
    config,
    config_path,
    first_plan,
    factor_mode,
    direction,
    *,
    decision,
    allow_write_flag,
    _live_store_config_override: Optional[Mapping[str, Any]] = None,
    _capture_live_capacity: bool = False,
):
    """Run finite, independently assembled live epochs in bundle order.

    The next bundle is opened only after the old engine has completed its
    strategy-owned winddown and its local resources have closed with proof.
    """

    if (
        config["inputs"].get("history_decision_tape") is not None
        and config["selection"]["daily_bundles"]
    ):
        raise RunnerError("LIVE_HISTORY_SELECTION_UNSUPPORTED")
    if config["selection"]["source"] == "ctp_query":
        if config["selection"]["daily_bundles"]:
            raise RunnerError("QUERY_SELECTION_DAILY_BUNDLES_UNSUPPORTED")
        return _run_ctp_query_live_epochs(
            config,
            config_path,
            factor_mode,
            direction,
            decision=decision,
            allow_write_flag=allow_write_flag,
            _live_store_config_override=_live_store_config_override,
            _capture_live_capacity=_capture_live_capacity,
        )

    daily_paths = _daily_bundle_paths(config, config_path)
    if not daily_paths:
        return run_live(
            config,
            config_path,
            first_plan,
            factor_mode,
            direction,
            decision=decision,
            allow_write_flag=allow_write_flag,
            _live_store_config_override=_live_store_config_override,
            _capture_live_capacity=_capture_live_capacity,
        )
    if decision.effective_tier != "live":
        raise RunnerError("DAILY_ROLLOVER_LIVE_TIER_REQUIRED")
    risk_policy = _risk_policy(config)
    if risk_policy is None or risk_policy.run_end_policy != "CLOSE_ALL":
        raise RunnerError("DAILY_ROLLOVER_CLOSE_ALL_POLICY_REQUIRED")

    original_epoch = config["cohort"]["epoch_id"]
    if type(original_epoch) is not int or original_epoch < 1:
        raise RunnerError("COHORT_EPOCH_INVALID")
    paths = (first_plan["selection_path"],) + daily_paths
    summaries = []
    later_bundle_reads = []
    assembly_attempts = []
    previous_plan = first_plan
    previous_result = None
    failed_epoch = None
    try:
        for index, bundle_path in enumerate(paths):
            if index == 0:
                plan = first_plan
            else:
                # This is intentionally after the preceding run_live return:
                # no next-day bundle bytes are opened while the previous
                # Broker, feed, Strategy, or query loop is active.
                plan = load_market_plan(config, config_path, bundle_path=bundle_path)
                later_bundle_reads.append(str(bundle_path))
                _assert_daily_plan_transition(previous_plan, plan)

            epoch_config = deepcopy(config)
            epoch_config["selection"]["bundle"] = str(bundle_path)
            epoch_config["cohort"]["epoch_id"] = original_epoch + index
            epoch_config["output"]["decision_tape_path"] = str(
                _daily_epoch_tape_path(config, config_path, epoch_index=index)
            )
            assembly_attempts.append(epoch_config["cohort"]["epoch_id"])
            try:
                result = run_live(
                    epoch_config,
                    config_path,
                    plan,
                    factor_mode,
                    direction,
                    decision=decision,
                    allow_write_flag=allow_write_flag,
                    _live_store_config_override=_live_store_config_override,
                    _capture_live_capacity=_capture_live_capacity,
                )
            except BaseException as error:
                failed_epoch = getattr(error, "live_epoch_evidence", None)
                if not isinstance(failed_epoch, Mapping):
                    failed_epoch = {
                        "epoch_id": epoch_config["cohort"]["epoch_id"],
                        "selection_path": str(plan["selection_path"]),
                        "routes": _route_summary(plan),
                        "status": "FAILED_OR_BLOCKED",
                        "error_code": getattr(error, "code", type(error).__name__),
                        "cleanup_complete": False,
                    }
                else:
                    failed_epoch = dict(failed_epoch)
                failed_epoch.setdefault("error_code", getattr(error, "code", type(error).__name__))
                raise
            if not _live_epoch_retired(result):
                failed_epoch = {
                    "epoch_id": epoch_config["cohort"]["epoch_id"],
                    "selection_path": str(plan["selection_path"]),
                    "routes": _route_summary(plan),
                    "status": "RETIREMENT_UNPROVEN",
                    "engine_winddown_status": result.get("engine_winddown_status"),
                    "strategy_shutdown_ready": result.get("strategy_shutdown_ready"),
                    "strategy_shutdown_blocker": result.get("strategy_shutdown_blocker"),
                    "strategy_shutdown_post_join_confirmed": result.get(
                        "strategy_shutdown_post_join_confirmed"
                    ),
                    "strategy_shutdown_post_join_blocker": result.get(
                        "strategy_shutdown_post_join_blocker"
                    ),
                    "shutdown_status": result.get("shutdown_status"),
                    "resource_shutdown": result.get("resource_shutdown", []),
                    "cleanup_complete": result.get("cleanup_complete") is True,
                    "live_capacity": _live_capacity_retirement_unproven(
                        result.get("live_capacity")
                    ),
                }
                raise RunnerError(
                    "DAILY_EPOCH_RETIREMENT_UNPROVEN",
                    f"epoch={epoch_config['cohort']['epoch_id']}",
                )
            epoch_summary = {
                "epoch_id": epoch_config["cohort"]["epoch_id"],
                "selection_path": str(plan["selection_path"]),
                "selection_evidence": result.get("selection_evidence"),
                "simnow_profile": result.get("simnow_profile"),
                "selection_decision_at": plan["manifest"].decision_at.isoformat(),
                "trading_days": {
                    row.exchange_id: row.current_trading_day.isoformat()
                    for row in plan["manifest"].trading_days
                },
                "routes": _route_summary(plan),
                "status": result["status"],
                "retirement_proven": True,
                "shutdown_status": result["shutdown_status"],
                "strategy_shutdown_ready": result["strategy_shutdown_ready"],
                "strategy_shutdown_post_join_confirmed": result[
                    "strategy_shutdown_post_join_confirmed"
                ],
                "engine_winddown_status": result["engine_winddown_status"],
                "cleanup_complete": result["cleanup_complete"],
                "decision_tape": result["decision_tape"],
                "decision_tape_readback": result["decision_tape_readback"],
                "strategy_order_events": result.get(
                    "strategy_order_events",
                    {
                        "status": "UNAVAILABLE",
                        "reason": "STRATEGY_ORDER_EVENT_SURFACE_UNAVAILABLE",
                        "capacity": 128,
                        "retained_count": 0,
                        "truncated": None,
                        "events": [],
                    },
                ),
                "live_capacity": result.get("live_capacity"),
            }
            summaries.append(epoch_summary)
            previous_plan = plan
            previous_result = result
    except BaseException as error:
        try:
            error.epoch_results = tuple(dict(row) for row in summaries)
            error.later_bundle_reads = tuple(later_bundle_reads)
            error.assembly_attempts = tuple(assembly_attempts)
            error.previous_epoch_routes = (
                _route_summary(previous_plan) if previous_plan is not None else None
            )
            error.previous_epoch_status = (
                previous_result.get("status") if previous_result is not None else None
            )
            if failed_epoch is not None:
                error.failed_epoch = dict(failed_epoch)
            error.next_bundle_read_count = len(later_bundle_reads)
            error.next_bundle_loaded = False
            error.old_route_handling = (
                "LOCAL_RESOURCES_RETAINED"
                if failed_epoch is not None and failed_epoch.get("cleanup_complete") is not True
                else (
                    "OLD_ROUTE_UNRESOLVED_LOCAL_RESOURCES_CLOSED"
                    if failed_epoch is not None
                    and (
                        failed_epoch.get("strategy_shutdown_ready") is not True
                        or failed_epoch.get("strategy_shutdown_post_join_confirmed") is not True
                    )
                    else "LOCAL_EPOCH_CLOSE_UNPROVEN"
                )
            )
            error.next_epoch_load_permitted = False
        except Exception:
            pass
        raise

    return {
        "status": "LIVE_EPOCH_SEQUENCE_COMPLETE",
        "mode": "live",
        "tier": decision.effective_tier,
        "write_mode": bool(allow_write_flag),
        "factor_mode": factor_mode,
        "epoch_count": len(summaries),
        "epochs": summaries,
        "later_bundle_reads": later_bundle_reads,
        "assembly_attempts": assembly_attempts,
        "cleanup_complete": all(row["cleanup_complete"] for row in summaries),
        "next_epoch_loaded": len(summaries) > 1,
    }


def run(args=None, *, _live_store_config_override: Optional[Mapping[str, Any]] = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.yaml"))
    parser.add_argument("--mode", choices=("dry", "research", "replay", "live"))
    parser.add_argument("--factor-mode", choices=("native", "build"))
    parser.add_argument("--allow-write", action="store_true")
    parser.add_argument(
        "--capture-live-capacity",
        action="store_true",
        help="opt in to bounded count-only live object snapshots",
    )
    ns = parser.parse_args(args)
    config_path = ns.config.expanduser().resolve(strict=False)
    try:
        config = load_config(config_path)
        mode, tier = resolve_mode(config, ns.mode)
        if ns.capture_live_capacity and mode != "live":
            raise RunnerError("LIVE_CAPACITY_CAPTURE_REQUIRES_LIVE_MODE")
        if _live_store_config_override is not None:
            if mode != "live":
                raise RunnerError("LIVE_STORE_CONFIG_OVERRIDE_REQUIRES_LIVE_MODE")
            # Validate before plan loading or any live Store can be constructed.
            _validated_live_store_config(_live_store_config_override)
        factor_mode, direction, _preheat, _cadence = _factor_parameters(config, ns.factor_mode)
        daily_bundles = config["selection"]["daily_bundles"]
        selection_source = config["selection"]["source"]
        if config["inputs"].get("history_decision_tape") is not None and mode != "live":
            raise RunnerError("LIVE_HISTORY_LIVE_MODE_REQUIRED")
        if selection_source == "ctp_query" and mode in {"research", "replay"}:
            raise RunnerError("OFFLINE_MODE_REQUIRES_SAVED_SELECTION_BUNDLE")
        if selection_source == "ctp_query" and daily_bundles:
            raise RunnerError("QUERY_SELECTION_DAILY_BUNDLES_UNSUPPORTED")
        if daily_bundles and mode != "live":
            raise RunnerError("DAILY_ROLLOVER_LIVE_MODE_REQUIRED")
        if daily_bundles:
            if tier.effective_tier != "live":
                raise RunnerError("DAILY_ROLLOVER_LIVE_TIER_REQUIRED")
            risk_policy = _risk_policy(config)
            if risk_policy is None or risk_policy.run_end_policy != "CLOSE_ALL":
                raise RunnerError("DAILY_ROLLOVER_CLOSE_ALL_POLICY_REQUIRED")
            _daily_bundle_paths(config, config_path)
        if ns.allow_write and mode != "live":
            raise RunnerError("ALLOW_WRITE_REQUIRES_LIVE_MODE")
        if mode == "dry":
            summary = {
                "status": "DRY_VALIDATION_COMPLETE",
                "mode": mode,
                "factor_mode": factor_mode,
                **tier.as_evidence(),
            }
        elif mode == "live" and selection_source == "ctp_query":
            if tier.effective_tier != "live":
                raise RunnerError("LIVE_TIER_REQUIRED")
            summary = run_live_epochs(
                config,
                config_path,
                None,
                factor_mode,
                direction,
                decision=tier,
                allow_write_flag=ns.allow_write,
                _live_store_config_override=_live_store_config_override,
                _capture_live_capacity=ns.capture_live_capacity,
            )
            summary.update({**tier.as_evidence(), "mode": mode})
        else:
            if selection_source != "bundle":
                raise RunnerError("SAVED_SELECTION_BUNDLE_REQUIRED")
            plan = load_market_plan(config, config_path)
            if mode == "research":
                summary = run_research(config, config_path, plan, factor_mode, direction)
            elif mode == "replay":
                if tier.effective_tier not in ("replay", "live"):
                    raise RunnerError("REPLAY_TIER_REQUIRED")
                summary = run_replay(config, config_path, plan, factor_mode, direction)
            else:
                if tier.effective_tier != "live":
                    raise RunnerError("LIVE_TIER_REQUIRED")
                summary = run_live_epochs(
                    config,
                    config_path,
                    plan,
                    factor_mode,
                    direction,
                    decision=tier,
                    allow_write_flag=ns.allow_write,
                    _live_store_config_override=_live_store_config_override,
                    _capture_live_capacity=ns.capture_live_capacity,
                )
            summary.update({**tier.as_evidence(), "mode": mode})
        public_summary = dict(summary)
        public_summary.pop("_plan", None)
        print(json.dumps(public_summary, sort_keys=True, default=str))
        if summary.get("status") == "REPLAY_INCOMPLETE":
            return 2
        return 0
    except RunnerError as error:
        payload = {"status": "BLOCKED", "code": error.code, "detail": error.detail}
        if hasattr(error, "cleanup_results"):
            payload["resource_shutdown"] = list(error.cleanup_results)
            payload["cleanup_complete"] = _cleanup_complete(error.cleanup_results)
        for name in (
            "epoch_results",
            "later_bundle_reads",
            "assembly_attempts",
            "previous_epoch_routes",
            "previous_epoch_status",
            "failed_epoch",
            "next_bundle_read_count",
            "next_bundle_loaded",
            "next_epoch_load_permitted",
            "next_query_permitted",
            "query_epoch_attempts",
            "old_route_handling",
            "live_epoch_evidence",
            "query_diagnostics",
            "live_capacity",
        ):
            if hasattr(error, name):
                value = getattr(error, name)
                if name == "query_diagnostics":
                    value = _sanitize_ctp_query_diagnostics(value)
                payload[name] = value
        print(json.dumps(payload, sort_keys=True, default=str))
        return 2
    except Exception as error:
        # Keep user/provider configuration and SDK exception text out of logs.
        payload = {"status": "FAILED", "error_type": type(error).__name__}
        if hasattr(error, "cleanup_results"):
            payload["resource_shutdown"] = list(error.cleanup_results)
            payload["cleanup_complete"] = _cleanup_complete(error.cleanup_results)
        for name in (
            "epoch_results",
            "later_bundle_reads",
            "assembly_attempts",
            "previous_epoch_routes",
            "previous_epoch_status",
            "failed_epoch",
            "next_bundle_read_count",
            "next_bundle_loaded",
            "next_epoch_load_permitted",
            "next_query_permitted",
            "query_epoch_attempts",
            "old_route_handling",
            "live_epoch_evidence",
            "query_diagnostics",
        ):
            if hasattr(error, name):
                value = getattr(error, name)
                if name == "query_diagnostics":
                    value = _sanitize_ctp_query_diagnostics(value)
                payload[name] = value
        print(json.dumps(payload, sort_keys=True, default=str))
        return 1


if __name__ == "__main__":
    sys.exit(run())
