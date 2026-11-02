"""Offline, bounded Alpha003 validation for one saved live DecisionTape.

This module is deliberately a consumer of a same-run safe plan projection and
an already-written DecisionTape.  It never opens a Store, Broker, CTP client,
private configuration, or SQLite journal.  Factor values are recomputed by
ordinary Cerebro and the production FactorStrategy in each requested mode.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from collections.abc import Mapping
from typing import Any, Optional


UTC = timezone.utc
EXPECTED_SCHEMA = "backtrader.iteration51.saved_factor_plan_projection.v1"
FACTOR_NAME = "alpha003"
PANEL_LINE = "factor"
MAX_TAPE_BYTES = 64 * 1024 * 1024
MAX_PLAN_BYTES = 64 * 1024 * 1024
MAX_TARGETS = 256
MAX_GRID_MINUTES = 512
EXPECTED_GRID_MINUTES = 195
_GRID_KEYS = {
    "schema",
    "status",
    "decision_at",
    "target_products",
    "product_trading_days",
    "calendar_hashes",
    "minutes",
}
_MEMBER_KEYS = {"product", "trading_day", "session_date", "action_day", "session_id"}
_PRODUCT_KEYS = {"exchange_id", "product_id"}
_OHLCV_FIELDS = ("open", "high", "low", "close", "volume", "openinterest")
_RUNNER_MODULE = None
_ALPHA_MODULE = None


class SavedTapeValidationError(ValueError):
    """A fixed-code validation failure with no tape payload in its message."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise SavedTapeValidationError(code)


def _runner_module():
    """Load the public 028 runner by its fixed repository-relative source path."""
    global _RUNNER_MODULE
    if _RUNNER_MODULE is not None:
        return _RUNNER_MODULE
    root = Path(__file__).resolve().parents[1]
    runner_path = root / "examples" / "unified" / "028_alpha003_simnow_minute" / "run.py"
    if not runner_path.is_file():
        _fail("PUBLIC_RUNNER_SOURCE_UNAVAILABLE")
    sibling = str(runner_path.parent)
    inserted = sibling not in sys.path
    if inserted:
        sys.path.insert(0, sibling)
    name = "_iteration51_saved_factor_tape_public_runner"
    try:
        spec = importlib.util.spec_from_file_location(name, runner_path)
        if spec is None or spec.loader is None:
            _fail("PUBLIC_RUNNER_SOURCE_UNAVAILABLE")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        _RUNNER_MODULE = module
        return module
    finally:
        if inserted:
            try:
                sys.path.remove(sibling)
            except ValueError:
                pass


def _alpha_module():
    """Load the public strategy factory without importing an example config."""
    global _ALPHA_MODULE
    if _ALPHA_MODULE is not None:
        return _ALPHA_MODULE
    root = Path(__file__).resolve().parents[1]
    source = root / "examples" / "unified" / "028_alpha003_simnow_minute" / "alpha003_strategy.py"
    if not source.is_file():
        _fail("ALPHA003_SOURCE_UNAVAILABLE")
    name = "_iteration51_saved_factor_tape_alpha003_strategy"
    spec = importlib.util.spec_from_file_location(name, source)
    if spec is None or spec.loader is None:
        _fail("ALPHA003_SOURCE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    _ALPHA_MODULE = module
    return module


def _mapping(value: Any, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(code)
    return value


def _text(value: Any, code: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        _fail(code)
    return value


def _sha256_text(value: Any, code: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        _fail(code)
    return value


def _utc_datetime(value: Any, code: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif type(value) is str:
        raw = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            result = datetime.fromisoformat(raw)
        except ValueError:
            _fail(code)
    else:
        _fail(code)
    if result.tzinfo is None or result.utcoffset() is None:
        _fail(code)
    result = result.astimezone(UTC)
    if result.utcoffset() != timedelta(0):
        _fail(code)
    return result


def _utc_iso(value: Any, code: str) -> str:
    return _utc_datetime(value, code).isoformat().replace("+00:00", "Z")


def _iso_date(value: Any, code: str) -> str:
    if type(value) is not str:
        _fail(code)
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        _fail(code)
    if parsed.isoformat() != value:
        _fail(code)
    return value


def _canonical_bytes(value: Any) -> bytes:
    try:
        result = _runner_module()._canonical_json_bytes(value)
    except SavedTapeValidationError:
        raise
    except Exception:
        _fail("PLAN_PROJECTION_SERIALIZATION_FAILED")
    if type(result) is not bytes:
        _fail("PLAN_PROJECTION_SERIALIZATION_FAILED")
    return result


def _product_pair(value: Any, code: str) -> tuple[str, str]:
    row = _mapping(value, code)
    if set(row) != _PRODUCT_KEYS:
        _fail(code)
    exchange = _text(row["exchange_id"], code)
    product = _text(row["product_id"], code)
    return exchange, product


def _product_from_object(value: Any, code: str) -> tuple[str, str]:
    exchange = getattr(value, "exchange_id", None)
    product = getattr(value, "product_id", None)
    return _text(exchange, code), _text(product, code)


def _manifest_projection(plan: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    manifest = plan.get("manifest")
    to_dict = getattr(manifest, "to_dict", None)
    digest = getattr(manifest, "manifest_sha256", None)
    if not callable(to_dict):
        _fail("PLAN_MANIFEST_UNAVAILABLE")
    row = to_dict()
    if type(row) is not dict:
        _fail("PLAN_MANIFEST_INVALID")
    encoded = _canonical_bytes(row)
    calculated = hashlib.sha256(encoded.rstrip(b"\n")).hexdigest()
    if type(digest) is not str or digest != calculated:
        _fail("PLAN_MANIFEST_HASH_MISMATCH")
    return row, calculated


def project_expected_plan(
    plan: Mapping[str, Any], *, clock_domain_id: str, calendar_id: str
) -> dict[str, Any]:
    """Project one actual, ready CTP plan into a JSON-safe comparison contract.

    The projection stores every planned close and member route/day/session, not
    a grid inferred from tape rows.  It is intentionally limited to the
    repository's bounded CTP plan sizes and omits quote values and the full
    selection manifest payload.
    """
    plan = _mapping(plan, "PLAN_MAPPING_REQUIRED")
    clock_domain_id = _text(clock_domain_id, "PLAN_CLOCK_DOMAIN_INVALID")
    calendar_id = _text(calendar_id, "PLAN_CALENDAR_ID_INVALID")
    if plan.get("selection_source") != "ctp_query_snapshot_equal_weight_v1":
        _fail("PLAN_SELECTION_SOURCE_INVALID")
    selection_path = _text(plan.get("selection_path"), "PLAN_SELECTION_PATH_INVALID")
    source_snapshot_id = _text(
        plan.get("source_snapshot_id"), "PLAN_SOURCE_SNAPSHOT_INVALID"
    )
    if not selection_path.startswith("ctp-query://"):
        _fail("PLAN_SELECTION_PATH_INVALID")

    grid = plan.get("grid")
    to_dict = getattr(grid, "to_dict", None)
    if not callable(to_dict):
        _fail("PLAN_GRID_UNAVAILABLE")
    grid_row = to_dict()
    if type(grid_row) is not dict or set(grid_row) != _GRID_KEYS:
        _fail("PLAN_GRID_INVALID")
    if grid_row.get("schema") != "backtrader.futures_common_minute_grid.v1":
        _fail("PLAN_GRID_SCHEMA_INVALID")
    if grid_row.get("status") != "READY":
        _fail("PLAN_GRID_NOT_READY")

    targets_raw = plan.get("targets")
    product_by_target = plan.get("product_by_target")
    target_by_product = plan.get("target_by_product")
    routes = plan.get("routes")
    if (
        not isinstance(targets_raw, (tuple, list))
        or not targets_raw
        or len(targets_raw) > MAX_TARGETS
        or any(type(item) is not str or not item for item in targets_raw)
        or len(set(targets_raw)) != len(targets_raw)
        or not isinstance(product_by_target, Mapping)
        or not isinstance(target_by_product, Mapping)
        or not isinstance(routes, Mapping)
    ):
        _fail("PLAN_TARGETS_INVALID")
    targets = tuple(sorted(targets_raw))
    product_to_target: dict[tuple[str, str], str] = {}
    route_projection: dict[str, dict[str, str]] = {}
    for target in targets:
        product = product_by_target.get(target)
        if product is None or target_by_product.get(product) != target:
            _fail("PLAN_PRODUCT_TARGET_BINDING_INVALID")
        pair = _product_from_object(product, "PLAN_PRODUCT_TARGET_BINDING_INVALID")
        if f"{pair[0]}.{pair[1]}" != target or pair in product_to_target:
            _fail("PLAN_PRODUCT_TARGET_BINDING_INVALID")
        instrument = routes.get(product)
        if type(instrument) is not str or not instrument or instrument != instrument.strip():
            _fail("PLAN_ROUTE_INVALID")
        product_to_target[pair] = target
        route_projection[target] = {
            "exchange_id": pair[0],
            "product_id": pair[1],
            "instrument_id": instrument,
        }
    grid_products = grid_row.get("target_products")
    if type(grid_products) is not list:
        _fail("PLAN_GRID_TARGETS_INVALID")
    grid_product_pairs = tuple(_product_pair(item, "PLAN_GRID_TARGETS_INVALID") for item in grid_products)
    if len(grid_product_pairs) != len(set(grid_product_pairs)) or set(grid_product_pairs) != set(
        product_to_target
    ):
        _fail("PLAN_GRID_TARGETS_INVALID")

    authorized_raw = plan.get("authorized_targets")
    if (
        not isinstance(authorized_raw, (tuple, list))
        or not authorized_raw
        or any(type(item) is not str or item not in targets for item in authorized_raw)
        or len(set(authorized_raw)) != len(authorized_raw)
    ):
        _fail("PLAN_AUTHORIZED_TARGETS_INVALID")
    authorized = sorted(authorized_raw)

    product_days_raw = grid_row.get("product_trading_days")
    if type(product_days_raw) is not list or len(product_days_raw) != len(targets):
        _fail("PLAN_GRID_TRADING_DAYS_INVALID")
    product_days: dict[str, tuple[str, ...]] = {}
    for item in product_days_raw:
        row = _mapping(item, "PLAN_GRID_TRADING_DAYS_INVALID")
        if set(row) != {"product", "trading_days"}:
            _fail("PLAN_GRID_TRADING_DAYS_INVALID")
        pair = _product_pair(row["product"], "PLAN_GRID_TRADING_DAYS_INVALID")
        target = product_to_target.get(pair)
        days = row["trading_days"]
        if (
            target is None
            or target in product_days
            or type(days) is not list
            or not days
            or any(type(day) is not str for day in days)
            or len(days) != len(set(days))
        ):
            _fail("PLAN_GRID_TRADING_DAYS_INVALID")
        product_days[target] = tuple(_iso_date(day, "PLAN_GRID_TRADING_DAYS_INVALID") for day in days)

    minutes_raw = grid_row.get("minutes")
    if (
        type(minutes_raw) is not list
        or len(minutes_raw) != EXPECTED_GRID_MINUTES
        or len(minutes_raw) > MAX_GRID_MINUTES
    ):
        _fail("PLAN_GRID_MINUTES_INVALID")
    minutes: list[dict[str, Any]] = []
    previous_close = None
    for slot_index, minute_value in enumerate(minutes_raw):
        minute = _mapping(minute_value, "PLAN_GRID_MINUTE_INVALID")
        if set(minute) != {"close_time", "members"}:
            _fail("PLAN_GRID_MINUTE_INVALID")
        close_text = _utc_iso(minute["close_time"], "PLAN_GRID_CLOSE_INVALID")
        close_at = _utc_datetime(close_text, "PLAN_GRID_CLOSE_INVALID")
        if previous_close is not None and close_at <= previous_close:
            _fail("PLAN_GRID_CLOSE_ORDER_INVALID")
        previous_close = close_at
        member_values = minute["members"]
        if type(member_values) is not list or len(member_values) != len(targets):
            _fail("PLAN_GRID_MEMBERS_INVALID")
        member_projection: dict[str, dict[str, str]] = {}
        for raw_member in member_values:
            member = _mapping(raw_member, "PLAN_GRID_MEMBER_INVALID")
            if set(member) != _MEMBER_KEYS:
                _fail("PLAN_GRID_MEMBER_INVALID")
            pair = _product_pair(member["product"], "PLAN_GRID_MEMBER_INVALID")
            target = product_to_target.get(pair)
            if target is None or target in member_projection:
                _fail("PLAN_GRID_MEMBER_SET_INVALID")
            trading_day = _iso_date(member["trading_day"], "PLAN_GRID_MEMBER_DAY_INVALID")
            if trading_day not in product_days.get(target, ()):
                _fail("PLAN_GRID_MEMBER_DAY_INVALID")
            session_date = _iso_date(member["session_date"], "PLAN_GRID_MEMBER_SESSION_INVALID")
            action_day = _iso_date(member["action_day"], "PLAN_GRID_MEMBER_SESSION_INVALID")
            session_id = _text(member["session_id"], "PLAN_GRID_MEMBER_SESSION_INVALID")
            member_projection[target] = {
                "exchange_id": pair[0],
                "product_id": pair[1],
                "instrument_id": route_projection[target]["instrument_id"],
                "bucket_start": (close_at - timedelta(minutes=1)).isoformat().replace(
                    "+00:00", "Z"
                ),
                "close_time": close_text,
                "trading_day": trading_day,
                "session_segment": session_id,
                "session_date": session_date,
                "action_day": action_day,
                "session_id": session_id,
            }
        if set(member_projection) != set(targets):
            _fail("PLAN_GRID_MEMBER_SET_INVALID")
        minutes.append(
            {
                "slot_index": slot_index,
                "close_time": close_text,
                "members": {target: member_projection[target] for target in targets},
            }
        )
    try:
        grid_semantics_sha256 = _runner_module()._grid_semantics_sha256(grid)
    except SavedTapeValidationError:
        raise
    except Exception:
        _fail("PLAN_GRID_HASH_UNAVAILABLE")
    grid_semantics_sha256 = _sha256_text(grid_semantics_sha256, "PLAN_GRID_HASH_INVALID")
    grid_evidence_sha256 = getattr(grid, "evidence_sha256", None)
    if grid_evidence_sha256 is not None:
        grid_evidence_sha256 = _sha256_text(grid_evidence_sha256, "PLAN_GRID_EVIDENCE_HASH_INVALID")
    manifest_row, manifest_sha256 = _manifest_projection(plan)
    decision_at = _utc_iso(grid_row["decision_at"], "PLAN_DECISION_TIME_INVALID")

    result = {
        "schema": EXPECTED_SCHEMA,
        "selection_source": "ctp_query_snapshot_equal_weight_v1",
        "selection_path": selection_path,
        "source_snapshot_id": source_snapshot_id,
        "manifest_sha256": manifest_sha256,
        "grid_semantics_sha256": grid_semantics_sha256,
        "grid_sha256": grid_evidence_sha256,
        "decision_at": decision_at,
        "calendar_id": calendar_id,
        "clock_domain_id": clock_domain_id,
        "targets": list(targets),
        "authorized_targets": authorized,
        "routes": route_projection,
        "minutes": minutes,
    }
    if len(_canonical_bytes(result)) > MAX_PLAN_BYTES:
        _fail("PLAN_PROJECTION_BYTE_BUDGET_EXCEEDED")
    # Prove the manifest projection was safe to serialize without retaining it.
    if len(_canonical_bytes(manifest_row)) > MAX_PLAN_BYTES:
        _fail("PLAN_MANIFEST_BYTE_BUDGET_EXCEEDED")
    return result


def _validate_expected(expected: Any) -> dict[str, Any]:
    expected = _mapping(expected, "EXPECTED_PLAN_INVALID")
    required = {
        "schema",
        "selection_source",
        "selection_path",
        "source_snapshot_id",
        "manifest_sha256",
        "grid_semantics_sha256",
        "grid_sha256",
        "decision_at",
        "calendar_id",
        "clock_domain_id",
        "targets",
        "authorized_targets",
        "routes",
        "minutes",
    }
    if set(expected) != required or expected.get("schema") != EXPECTED_SCHEMA:
        _fail("EXPECTED_PLAN_INVALID")
    result = dict(expected)
    if result["selection_source"] != "ctp_query_snapshot_equal_weight_v1":
        _fail("EXPECTED_PLAN_SOURCE_INVALID")
    for key in ("selection_path", "source_snapshot_id", "calendar_id", "clock_domain_id"):
        _text(result[key], "EXPECTED_PLAN_TEXT_INVALID")
    if not result["selection_path"].startswith("ctp-query://"):
        _fail("EXPECTED_PLAN_SELECTION_PATH_INVALID")
    for key in ("manifest_sha256", "grid_semantics_sha256"):
        _sha256_text(result[key], "EXPECTED_PLAN_HASH_INVALID")
    if result["grid_sha256"] is not None:
        _sha256_text(result["grid_sha256"], "EXPECTED_PLAN_HASH_INVALID")
    _utc_datetime(result["decision_at"], "EXPECTED_PLAN_TIME_INVALID")
    targets = result["targets"]
    if (
        type(targets) is not list
        or not targets
        or len(targets) > MAX_TARGETS
        or any(type(target) is not str or not target for target in targets)
        or targets != sorted(set(targets))
    ):
        _fail("EXPECTED_PLAN_TARGETS_INVALID")
    authorized = result["authorized_targets"]
    if (
        type(authorized) is not list
        or not authorized
        or any(type(target) is not str or not target for target in authorized)
        or authorized != sorted(set(authorized))
        or not set(authorized).issubset(set(targets))
    ):
        _fail("EXPECTED_PLAN_AUTHORIZED_TARGETS_INVALID")
    routes = _mapping(result["routes"], "EXPECTED_PLAN_ROUTES_INVALID")
    if set(routes) != set(targets):
        _fail("EXPECTED_PLAN_ROUTES_INVALID")
    for target, route in routes.items():
        row = _mapping(route, "EXPECTED_PLAN_ROUTE_INVALID")
        if set(row) != {"exchange_id", "product_id", "instrument_id"}:
            _fail("EXPECTED_PLAN_ROUTE_INVALID")
        if f"{_text(row['exchange_id'], 'EXPECTED_PLAN_ROUTE_INVALID')}.{_text(row['product_id'], 'EXPECTED_PLAN_ROUTE_INVALID')}" != target:
            _fail("EXPECTED_PLAN_ROUTE_INVALID")
        _text(row["instrument_id"], "EXPECTED_PLAN_ROUTE_INVALID")
    minutes = result["minutes"]
    if (
        type(minutes) is not list
        or len(minutes) != EXPECTED_GRID_MINUTES
        or len(minutes) > MAX_GRID_MINUTES
    ):
        _fail("EXPECTED_PLAN_MINUTES_INVALID")
    previous_close = None
    for index, raw_minute in enumerate(minutes):
        minute = _mapping(raw_minute, "EXPECTED_PLAN_MINUTE_INVALID")
        if (
            set(minute) != {"slot_index", "close_time", "members"}
            or type(minute["slot_index"]) is not int
            or minute["slot_index"] != index
        ):
            _fail("EXPECTED_PLAN_MINUTE_INVALID")
        close_at = _utc_datetime(minute["close_time"], "EXPECTED_PLAN_MINUTE_INVALID")
        if previous_close is not None and close_at <= previous_close:
            _fail("EXPECTED_PLAN_MINUTES_INVALID")
        previous_close = close_at
        members = _mapping(minute["members"], "EXPECTED_PLAN_MEMBERS_INVALID")
        if set(members) != set(targets):
            _fail("EXPECTED_PLAN_MEMBERS_INVALID")
        for target, raw_member in members.items():
            member = _mapping(raw_member, "EXPECTED_PLAN_MEMBER_INVALID")
            member_keys = {
                "exchange_id",
                "product_id",
                "instrument_id",
                "bucket_start",
                "close_time",
                "trading_day",
                "session_segment",
                "session_date",
                "action_day",
                "session_id",
            }
            if set(member) != member_keys:
                _fail("EXPECTED_PLAN_MEMBER_INVALID")
            route = routes[target]
            if any(member[key] != route[key] for key in ("exchange_id", "product_id", "instrument_id")):
                _fail("EXPECTED_PLAN_MEMBER_ROUTE_INVALID")
            if _utc_datetime(member["close_time"], "EXPECTED_PLAN_MEMBER_TIME_INVALID") != close_at:
                _fail("EXPECTED_PLAN_MEMBER_TIME_INVALID")
            start = _utc_datetime(member["bucket_start"], "EXPECTED_PLAN_MEMBER_TIME_INVALID")
            if start != close_at - timedelta(minutes=1):
                _fail("EXPECTED_PLAN_MEMBER_BUCKET_INVALID")
            for field in ("trading_day", "session_date", "action_day"):
                _iso_date(member[field], "EXPECTED_PLAN_MEMBER_DAY_INVALID")
            _text(member["session_segment"], "EXPECTED_PLAN_MEMBER_SESSION_INVALID")
            _text(member["session_id"], "EXPECTED_PLAN_MEMBER_SESSION_INVALID")
    if len(_canonical_bytes(result)) > MAX_PLAN_BYTES:
        _fail("EXPECTED_PLAN_BYTE_BUDGET_EXCEEDED")
    return result


def _normalize_day(value: Any) -> str:
    if type(value) is str and len(value) == 8 and value.isascii() and value.isdecimal():
        try:
            return datetime.strptime(value, "%Y%m%d").date().isoformat()
        except ValueError:
            _fail("TAPE_MEMBER_DAY_INVALID")
    return _iso_date(value, "TAPE_MEMBER_DAY_INVALID")


def _finite_number(value: Any, code: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or value is None:
        _fail(code)
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        _fail(code)
    if not math.isfinite(number) or (nonnegative and number < 0):
        _fail(code)
    return number


def _validate_factor_value(row: Any) -> tuple[Optional[float], str, Optional[str]]:
    point = _mapping(row, "TAPE_FACTOR_POINT_INVALID")
    expected_keys = {
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
    if set(point) != expected_keys:
        _fail("TAPE_FACTOR_POINT_INVALID")
    value_row = _mapping(point["value"], "TAPE_FACTOR_VALUE_INVALID")
    if set(value_row) != {"finite", "value", "float64_hex"} or type(value_row["finite"]) is not bool:
        _fail("TAPE_FACTOR_VALUE_INVALID")
    hex_value = value_row["float64_hex"]
    if type(hex_value) is not str or not hex_value:
        _fail("TAPE_FACTOR_VALUE_INVALID")
    if value_row["finite"]:
        number = _finite_number(value_row["value"], "TAPE_FACTOR_VALUE_INVALID")
        if number.hex() != hex_value:
            _fail("TAPE_FACTOR_VALUE_INVALID")
    else:
        if value_row["value"] is not None or hex_value != "nan":
            _fail("TAPE_FACTOR_VALUE_INVALID")
        number = None
    status = _text(point["status"], "TAPE_FACTOR_STATUS_INVALID")
    if status not in {"OUTPUT_AVAILABLE", "OUTPUT_UNAVAILABLE"}:
        _fail("TAPE_FACTOR_STATUS_INVALID")
    reason = point["reason"]
    if reason is not None:
        reason = _text(reason, "TAPE_FACTOR_REASON_INVALID")
    if (number is not None) != (status == "OUTPUT_AVAILABLE"):
        _fail("TAPE_FACTOR_STATUS_VALUE_MISMATCH")
    if (number is not None) != (reason is None):
        _fail("TAPE_FACTOR_REASON_VALUE_MISMATCH")
    if type(point["present"]) is not bool or type(point["complete"]) is not bool:
        _fail("TAPE_FACTOR_MEMBERSHIP_INVALID")
    quality = _text(point["quality"], "TAPE_FACTOR_QUALITY_INVALID")
    role = _text(point["source_role"], "TAPE_FACTOR_SOURCE_INVALID")
    member_id = _text(point["member_id"], "TAPE_FACTOR_SOURCE_INVALID")
    if point["source_ref"] is not None:
        _text(point["source_ref"], "TAPE_FACTOR_SOURCE_INVALID")
    if type(point["sequence"]) is not int or point["sequence"] < 1:
        _fail("TAPE_FACTOR_SEQUENCE_INVALID")
    generation = point["generation"]
    if type(generation) is not int or generation < 1:
        _fail("TAPE_FACTOR_GENERATION_INVALID")
    return number, status, reason


def _hash_file(path: Path, limit: int) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    _fail("TAPE_BYTE_BUDGET_EXCEEDED")
                digest.update(chunk)
    except SavedTapeValidationError:
        raise
    except OSError:
        _fail("TAPE_READ_FAILED")
    return size, digest.hexdigest()


def _selection_evidence_matches(header: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    evidence = header.get("selection_evidence")
    if not isinstance(evidence, Mapping):
        _fail("TAPE_SELECTION_EVIDENCE_MISSING")
    if (
        evidence.get("selection_source") != expected["selection_source"]
        or evidence.get("selection_path") != expected["selection_path"]
        or evidence.get("source_snapshot_id") != expected["source_snapshot_id"]
        or evidence.get("manifest_sha256") != expected["manifest_sha256"]
        or evidence.get("grid_semantics_sha256") != expected["grid_semantics_sha256"]
        or evidence.get("routes")
        != {target: expected["routes"][target]["instrument_id"] for target in expected["targets"]}
        or evidence.get("authorized_targets") != expected["authorized_targets"]
    ):
        _fail("TAPE_SELECTION_BINDING_MISMATCH")


def _check_decision_membership(
    decision: Any,
    *,
    expected: Mapping[str, Any],
    row: Mapping[str, Any],
    factor_points: Mapping[str, Mapping[str, Any]],
    source_sha256: str,
    source_factor_mode: str,
    direction: int,
) -> None:
    """Check only the saved factor-to-eligible membership projection.

    The strategy's target-selection and order-planning algorithms are not part
    of this offline factor parity check.
    """
    if decision is None:
        return
    decision = _mapping(decision, "TAPE_DECISION_INVALID")
    required = {
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
        "authorized_targets",
        "eligible_targets",
        "targets",
    }
    if set(decision) != required:
        _fail("TAPE_DECISION_FIELDS_INVALID")
    if (
        decision["factor_name"] != FACTOR_NAME
        or decision["mode"] != source_factor_mode
        or decision["execution_mode"] != "LIVE"
        or type(decision["direction"]) is not int
        or decision["direction"] != direction
        or decision["source_sha256"] != source_sha256
        or decision["cohort_id"] != row["cohort_id"]
        or decision["batch_id"] != row["batch_id"]
        or _utc_datetime(decision["close_time"], "TAPE_DECISION_TIME_INVALID")
        != _utc_datetime(row["close_time"], "TAPE_DECISION_TIME_INVALID")
        or _utc_datetime(decision["available_at"], "TAPE_DECISION_TIME_INVALID")
        != _utc_datetime(row["available_at"], "TAPE_DECISION_TIME_INVALID")
        or decision["authorized_targets"] != expected["authorized_targets"]
    ):
        _fail("TAPE_DECISION_BINDING_MISMATCH")
    status = _text(decision["status"], "TAPE_DECISION_STATUS_INVALID")
    if status not in {"TARGETS_READY", "BLOCKED"}:
        _fail("TAPE_DECISION_STATUS_INVALID")
    eligible = decision["eligible_targets"]
    if (
        type(eligible) is not list
        or any(type(target) is not str or target not in expected["authorized_targets"] for target in eligible)
        or len(eligible) != len(set(eligible))
        or not set(eligible).issubset(expected["authorized_targets"])
    ):
        _fail("TAPE_DECISION_MEMBERSHIP_INVALID")
    if status == "TARGETS_READY":
        available_members = {
            target
            for target in expected["authorized_targets"]
            if factor_points[target]["status"] == "OUTPUT_AVAILABLE"
            and factor_points[target]["present"] is True
            and factor_points[target]["complete"] is True
            and factor_points[target]["quality"] == "GOOD"
        }
        if set(eligible) != available_members:
            _fail("TAPE_DECISION_MEMBERSHIP_INVALID")


def _run_factor_strategy(
    expected: Mapping[str, Any], raw_by_target: Mapping[str, Mapping[str, list[float]]], *, factor_mode: str, direction: int
) -> dict[str, Any]:
    try:
        import backtrader as bt
        import pandas as pd
        from backtrader.research import FactorStrategy, align_to_grid, operators
        from backtrader.research.specs import ResearchSpec
    except ImportError:
        _fail("RESEARCH_RUNTIME_UNAVAILABLE")
    spec_factory = _alpha_module().make_alpha003_factor_spec
    closes = [_utc_datetime(minute["close_time"], "EXPECTED_PLAN_TIME_INVALID") for minute in expected["minutes"]]
    if len(closes) != len(expected["minutes"]):
        _fail("EXPECTED_PLAN_MINUTES_INVALID")
    grid = pd.DataFrame(
        {"open_time": [close - timedelta(minutes=1) for close in closes]},
        index=pd.DatetimeIndex(closes, name="close_time"),
    )
    research = ResearchSpec(
        grid=grid,
        start=closes[0],
        end=closes[-1],
        targets=expected["targets"],
        source_timezone="UTC",
        snapshot_id=expected["source_snapshot_id"],
        price_basis="ctp_saved_decision_tape_ohlcv_v1",
        calendar_id=expected["calendar_id"],
        frequency="1min",
    )
    cerebro = bt.Cerebro(stdstats=False)
    for target in expected["targets"]:
        fields = raw_by_target[target]
        frame = pd.DataFrame(
            {name: fields[name] for name in _OHLCV_FIELDS},
            index=pd.DatetimeIndex(closes, name="close_time"),
        )
        aligned = align_to_grid(frame, research, target, data_version=expected["source_snapshot_id"])
        cerebro.adddata(aligned.feed, name=target)

    factor_spec = spec_factory(mode=factor_mode, direction=direction)
    if (
        factor_spec.name != FACTOR_NAME
        or factor_spec.panel_line != PANEL_LINE
        or factor_spec.direction != direction
        or factor_spec.mode != factor_mode
    ):
        _fail("ALPHA003_FACTOR_SPEC_INVALID")
    cerebro.addstrategy(FactorStrategy, research=research, factors={factor_spec.name: factor_spec})

    def denied_order(*_args, **_kwargs):
        _fail("UNEXPECTED_FACTOR_VALIDATOR_ORDER_CALL")

    cerebro.broker.submit = denied_order
    cerebro.broker.cancel = denied_order
    try:
        strategies = cerebro.run()
    except SavedTapeValidationError:
        raise
    except Exception:
        _fail("FACTOR_STRATEGY_EXECUTION_FAILED")
    if type(strategies) is not list or len(strategies) != 1:
        _fail("FACTOR_STRATEGY_RESULT_INVALID")
    strategy = strategies[0]
    panel = strategy.get_panel()
    factor = strategy.factor_instances.get(FACTOR_NAME)
    nodes = getattr(factor, "_nodes", None)
    if not isinstance(nodes, Mapping):
        _fail("ALPHA003_GRAPH_UNAVAILABLE")
    reason_names = {float(item): item.name for item in operators.OperatorReason}
    values: dict[str, list[float]] = {}
    reasons: dict[str, list[Optional[str]]] = {}
    for target_index, target in enumerate(expected["targets"]):
        node = nodes.get("negate_%d" % target_index)
        if node is None:
            _fail("ALPHA003_FINAL_NODE_MISSING")
        try:
            node_values = [float(value) for value in node.lines.value.array]
            raw_reasons = [float(value) for value in node.lines.reason.array]
        except (AttributeError, TypeError, ValueError):
            _fail("ALPHA003_OUTPUT_UNAVAILABLE")
        if len(node_values) != len(closes) or len(raw_reasons) != len(closes):
            _fail("ALPHA003_OUTPUT_GRID_MISMATCH")
        mapped_reasons: list[Optional[str]] = []
        for reason in raw_reasons:
            name = reason_names.get(reason)
            if name is None:
                _fail("ALPHA003_REASON_UNKNOWN")
            mapped_reasons.append(None if name == "READY" else name)
        panel_series = panel.factors[FACTOR_NAME].xs(target, level="asset")
        if len(panel_series) != len(closes) or tuple(
            panel_series.index.to_pydatetime()
        ) != tuple(closes):
            _fail("ALPHA003_PANEL_GRID_MISMATCH")
        for index, (node_value, panel_value) in enumerate(zip(node_values, panel_series.to_list())):
            panel_value = float(panel_value)
            if math.isfinite(node_value) != math.isfinite(panel_value):
                _fail("ALPHA003_PANEL_NODE_MISMATCH")
            if math.isfinite(node_value) and node_value.hex() != panel_value.hex():
                _fail("ALPHA003_PANEL_NODE_MISMATCH")
        values[target] = node_values
        reasons[target] = mapped_reasons
    return {
        "source_sha256": factor_spec.source_sha256,
        "panel_line": factor_spec.panel_line,
        "targets": tuple(expected["targets"]),
        "closes": tuple(closes),
        "values": values,
        "reasons": reasons,
    }


def validate_saved_factor_tape(
    path: Path,
    *,
    expected: Mapping[str, Any],
    expected_file_id: str,
    expected_sha256: str,
    expected_bytes: int,
    expected_record_count: int,
    factor_mode: str,
    direction: int,
    preheat_bars: int,
    required_live_ready: int = 100,
    max_bytes: int = MAX_TAPE_BYTES,
) -> dict[str, Any]:
    """Verify one exact saved live tape and recompute Alpha003 with Cerebro.

    ``factor_mode`` selects the offline calculation mode. The tape header's
    factor mode is retained as source provenance and need not equal it, which
    permits the same immutable tape to be checked in both native and build.
    """
    expected = _validate_expected(expected)
    if type(factor_mode) is not str or factor_mode not in {"native", "build"}:
        _fail("FACTOR_MODE_INVALID")
    if type(direction) is not int or direction not in (-1, 1):
        _fail("FACTOR_DIRECTION_INVALID")
    if type(preheat_bars) is not int or preheat_bars < 1:
        _fail("PREHEAT_BARS_INVALID")
    if type(required_live_ready) is not int or required_live_ready < 100:
        _fail("LIVE_READY_REQUIREMENT_INVALID")
    if (
        type(max_bytes) is not int
        or max_bytes < 1
        or max_bytes > MAX_TAPE_BYTES
        or type(expected_bytes) is not int
        or expected_bytes < 1
        or expected_bytes > max_bytes
        or type(expected_record_count) is not int
        or expected_record_count != len(expected["minutes"])
    ):
        _fail("TAPE_BUDGET_OR_COUNT_INVALID")
    expected_file_id = _text(expected_file_id, "TAPE_FILE_ID_INVALID")
    expected_sha256 = _sha256_text(expected_sha256, "TAPE_SHA256_INVALID")
    tape_path = Path(path)
    try:
        if tape_path.is_symlink() or not tape_path.is_file():
            _fail("TAPE_PATH_INVALID")
        if tape_path.stat().st_size != expected_bytes:
            _fail("TAPE_BYTE_COUNT_MISMATCH")
    except SavedTapeValidationError:
        raise
    except OSError:
        _fail("TAPE_PATH_INVALID")
    size_before, digest_before = _hash_file(tape_path, max_bytes)
    if size_before != expected_bytes or digest_before != expected_sha256:
        _fail("TAPE_PIN_MISMATCH")

    runner = _runner_module()
    try:
        iterator = iter(runner.iter_decision_tape(tape_path, max_bytes=max_bytes))
        header = next(iterator)
    except StopIteration:
        _fail("TAPE_HEADER_MISSING")
    except SavedTapeValidationError:
        raise
    except Exception:
        _fail("TAPE_READ_FAILED")
    if (
        header.get("record_type") != "HEADER"
        or header.get("mode") != "live"
        or header.get("file_id") != expected_file_id
        or header.get("calendar_id") != expected["calendar_id"]
        or header.get("source_snapshot_id") != expected["source_snapshot_id"]
        or header.get("targets") != expected["targets"]
        or type(header.get("direction")) is not int
        or header.get("direction") != direction
        or type(header.get("factor_mode")) is not str
        or header.get("factor_mode") not in {"native", "build"}
    ):
        _fail("TAPE_HEADER_BINDING_MISMATCH")
    if header.get("grid_sha256") not in (None, expected["grid_sha256"]):
        _fail("TAPE_GRID_HASH_MISMATCH")
    _selection_evidence_matches(header, expected)

    source_rows: dict[str, dict[str, list[float]]] = {
        target: {name: [] for name in _OHLCV_FIELDS} for target in expected["targets"]
    }
    expected_factor_rows: dict[str, list[dict[str, Any]]] = {
        target: [] for target in expected["targets"]
    }
    cohort_id = None
    epoch_id = None
    calendar_version = None
    timezone_ids = set()
    target_source_identity: dict[str, tuple[Any, ...]] = {}
    previous_feed_sequences: dict[str, int] = {}
    previous_received: dict[str, int] = {}
    last_batch_id = None
    seen_batch_ids: set[str] = set()
    live_ready_rows = 0
    finite_witnesses: set[str] = set()
    finite_targets: set[str] = set()
    two_candidate_witness_rows = 0
    saved_factor_source_sha256 = None
    saved_factor_plan_id = None
    record_count = 0

    try:
        for record_count, raw_row in enumerate(iterator, start=1):
            if record_count > len(expected["minutes"]):
                _fail("TAPE_EXTRA_DECISION_RECORD")
            row = raw_row
            planned = expected["minutes"][record_count - 1]
            if (
                row.get("record_type") != "DECISION"
                or type(row.get("record_index")) is not int
                or row.get("record_index") != record_count
                or type(row.get("slot_index")) is not int
                or row.get("slot_index") != planned["slot_index"]
                or row.get("calendar_id") != expected["calendar_id"]
                or _utc_datetime(row.get("close_time"), "TAPE_CLOSE_TIME_INVALID")
                != _utc_datetime(planned["close_time"], "EXPECTED_PLAN_TIME_INVALID")
            ):
                _fail("TAPE_GRID_COVERAGE_MISMATCH")
            available_at = _utc_datetime(row.get("available_at"), "TAPE_AVAILABILITY_INVALID")
            close_at = _utc_datetime(row["close_time"], "TAPE_CLOSE_TIME_INVALID")
            if available_at < close_at:
                _fail("TAPE_AVAILABILITY_INVALID")
            current_cohort = _text(row.get("cohort_id"), "TAPE_COHORT_INVALID")
            current_batch = _text(row.get("batch_id"), "TAPE_BATCH_INVALID")
            current_epoch = row.get("epoch_id")
            current_calendar_version = _text(row.get("calendar_version"), "TAPE_CALENDAR_VERSION_INVALID")
            if type(current_epoch) is not int or current_epoch < 1:
                _fail("TAPE_EPOCH_INVALID")
            if record_count == 1:
                cohort_id, epoch_id, calendar_version = (
                    current_cohort,
                    current_epoch,
                    current_calendar_version,
                )
            elif (
                current_cohort != cohort_id
                or current_epoch != epoch_id
                or current_calendar_version != calendar_version
            ):
                _fail("TAPE_EPOCH_BINDING_CHANGED")
            if current_batch in seen_batch_ids:
                _fail("TAPE_BATCH_DUPLICATED")
            last_batch_id = current_batch
            seen_batch_ids.add(current_batch)
            if (
                row.get("header_record_id") != header.get("record_id")
                or row.get("selection_evidence_sha256")
                != header["selection_evidence"]["binding_sha256"]
            ):
                _fail("TAPE_HEADER_BINDING_MISMATCH")

            members = _mapping(row.get("members"), "TAPE_MEMBERS_INVALID")
            factor_block = _mapping(row.get("factors"), "TAPE_FACTORS_INVALID")
            factor_rows = _mapping(factor_block.get("factors"), "TAPE_FACTOR_BLOCK_INVALID")
            if set(members) != set(expected["targets"]) or set(factor_rows) != {FACTOR_NAME}:
                _fail("TAPE_TARGET_MEMBERSHIP_MISMATCH")
            factor = _mapping(factor_rows[FACTOR_NAME], "TAPE_FACTOR_METADATA_INVALID")
            if (
                factor.get("mode") != header.get("factor_mode")
                or type(factor.get("direction")) is not int
                or factor.get("direction") != direction
                or factor.get("panel_line") != PANEL_LINE
            ):
                _fail("TAPE_FACTOR_METADATA_MISMATCH")
            factor_source_sha = _sha256_text(factor.get("source_sha256"), "TAPE_FACTOR_SOURCE_INVALID")
            factor_plan_id = _text(factor_block.get("plan_id"), "TAPE_FACTOR_PLAN_INVALID")
            if saved_factor_source_sha256 is None:
                saved_factor_source_sha256 = factor_source_sha
                saved_factor_plan_id = factor_plan_id
            elif (
                factor_source_sha != saved_factor_source_sha256
                or factor_plan_id != saved_factor_plan_id
            ):
                _fail("TAPE_FACTOR_PLAN_OR_SOURCE_CHANGED")
            values = _mapping(factor.get("values"), "TAPE_FACTOR_VALUES_INVALID")
            if set(values) != set(expected["targets"]):
                _fail("TAPE_FACTOR_MEMBERSHIP_MISMATCH")

            checked_points: dict[str, Mapping[str, Any]] = {}
            row_finite_candidates: dict[str, float] = {}
            for target in expected["targets"]:
                planned_member = planned["members"][target]
                member = _mapping(members[target], "TAPE_MEMBER_INVALID")
                required_member_fields = {
                    "cohort_id",
                    "calendar_id",
                    "epoch_id",
                    "slot_index",
                    "slot_id",
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
                    "quality_flags",
                    "event_source",
                    "received_monotonic_ns",
                    "raw_values",
                }
                if set(member) != required_member_fields:
                    _fail("TAPE_MEMBER_FIELDS_INVALID")
                if (
                    member["cohort_id"] != cohort_id
                    or member["calendar_id"] != expected["calendar_id"]
                    or type(member["epoch_id"]) is not int
                    or member["epoch_id"] != epoch_id
                    or type(member["slot_index"]) is not int
                    or member["slot_index"] != planned["slot_index"]
                    or _text(member["slot_id"], "TAPE_SLOT_ID_INVALID") == ""
                    or member["instrument"] != planned_member["instrument_id"]
                    or _utc_datetime(member["close_time"], "TAPE_MEMBER_TIME_INVALID") != close_at
                    or _utc_datetime(member["bucket_start"], "TAPE_MEMBER_BUCKET_INVALID")
                    != _utc_datetime(planned_member["bucket_start"], "TAPE_MEMBER_BUCKET_INVALID")
                    or _normalize_day(member["trading_day"]) != planned_member["trading_day"]
                    or member["session_segment"] != planned_member["session_segment"]
                    or member["clock_domain_id"] != expected["clock_domain_id"]
                    or member["complete"] is not True
                    or member["present"] is not True
                    or member["quality"] != "GOOD"
                    or member["quality_flags"] != []
                ):
                    _fail("TAPE_MEMBER_PLAN_OR_QUALITY_MISMATCH")
                _text(member["source_ref"], "TAPE_MEMBER_SOURCE_INVALID")
                source_role = _text(member["source_role"], "TAPE_MEMBER_SOURCE_INVALID")
                if source_role != "live":
                    _fail("TAPE_MEMBER_SOURCE_ROLE_INVALID")
                _text(member["timezone_id"], "TAPE_MEMBER_TIMEZONE_INVALID")
                _text(member["event_source"], "TAPE_MEMBER_SOURCE_INVALID")
                _text(member["bar_id"], "TAPE_MEMBER_BAR_ID_INVALID")
                timezone_ids.add(member["timezone_id"])
                generation = member["connection_generation"]
                sequence = member["feed_sequence"]
                received = member["received_monotonic_ns"]
                if type(generation) is not int or generation < 1:
                    _fail("TAPE_MEMBER_GENERATION_INVALID")
                if type(sequence) is not int or sequence < 1:
                    _fail("TAPE_MEMBER_SEQUENCE_INVALID")
                if type(received) is not int or received < 1:
                    _fail("TAPE_MEMBER_RECEIPT_TIME_INVALID")
                if _utc_datetime(member["available_at"], "TAPE_MEMBER_AVAILABILITY_INVALID") < close_at:
                    _fail("TAPE_MEMBER_AVAILABILITY_INVALID")
                if _utc_datetime(member["available_at"], "TAPE_MEMBER_AVAILABILITY_INVALID") > available_at:
                    _fail("TAPE_MEMBER_AVAILABILITY_INVALID")
                identity = (
                    generation,
                    member["source_role"],
                    member["source_ref"],
                    member["timezone_id"],
                    member["event_source"],
                )
                if target in target_source_identity and target_source_identity[target] != identity:
                    _fail("TAPE_MEMBER_SOURCE_BINDING_CHANGED")
                target_source_identity[target] = identity
                if sequence <= previous_feed_sequences.get(target, 0):
                    _fail("TAPE_MEMBER_SEQUENCE_ORDER_INVALID")
                if received < previous_received.get(target, 0):
                    _fail("TAPE_MEMBER_RECEIPT_ORDER_INVALID")
                previous_feed_sequences[target] = sequence
                previous_received[target] = received
                raw_values = _mapping(member["raw_values"], "TAPE_RAW_VALUES_INVALID")
                if set(raw_values) != set(_OHLCV_FIELDS):
                    _fail("TAPE_RAW_FIELDS_INVALID")
                for field in _OHLCV_FIELDS:
                    number = _finite_number(
                        raw_values[field],
                        "TAPE_RAW_VALUE_INVALID",
                        nonnegative=field in {"volume", "openinterest"},
                    )
                    source_rows[target][field].append(number)

                point = _mapping(values[target], "TAPE_FACTOR_POINT_INVALID")
                number, _status, _reason = _validate_factor_value(point)
                if (
                    point["present"] is not True
                    or point["complete"] is not True
                    or point["quality"] != member["quality"]
                    or point["source_role"] != member["source_role"]
                    or point["member_id"] != target
                    or point["source_ref"] != member["source_ref"]
                    or point["sequence"] != sequence
                    or point["generation"] != generation
                ):
                    _fail("TAPE_FACTOR_RECEIPT_MISMATCH")
                expected_factor_rows[target].append(dict(point))
                checked_points[target] = point
                if number is not None and planned["slot_index"] >= preheat_bars - 1:
                    finite_witnesses.add(number.hex())
                    finite_targets.add(target)
                    if target in expected["authorized_targets"]:
                        row_finite_candidates[target] = number

            if (
                len(row_finite_candidates) >= 2
                and len({value.hex() for value in row_finite_candidates.values()}) >= 2
            ):
                two_candidate_witness_rows += 1

            readiness = row.get("readiness")
            readiness_reasons = row.get("readiness_reasons")
            if (
                type(readiness) is not str
                or readiness not in {"WARMUP", "LIVE_READY"}
                or type(readiness_reasons) is not list
                or any(type(reason) is not str or not reason for reason in readiness_reasons)
            ):
                _fail("TAPE_READINESS_INVALID")
            if readiness == "LIVE_READY" and readiness_reasons:
                _fail("TAPE_READINESS_REASON_MISMATCH")
            index = planned["slot_index"]
            if (index >= preheat_bars - 1) != (readiness == "LIVE_READY"):
                _fail("TAPE_WARMUP_CUTOFF_MISMATCH")
            # The member loop above has already required a complete, present,
            # GOOD cohort.  LIVE_READY describes that batch; a factor may
            # still legitimately be unavailable (for example a constant
            # series produces a post-warmup correlation DOMAIN_ERROR/NaN).
            if readiness == "LIVE_READY":
                live_ready_rows += 1
            decision = row.get("target_decision")
            _check_decision_membership(
                decision,
                expected=expected,
                row=row,
                factor_points=checked_points,
                source_sha256=factor_source_sha,
                source_factor_mode=header["factor_mode"],
                direction=direction,
            )
    except SavedTapeValidationError:
        raise
    except Exception:
        _fail("TAPE_RECORD_INVALID")

    if record_count != expected_record_count or record_count != len(expected["minutes"]):
        _fail("TAPE_GRID_COVERAGE_MISMATCH")
    if len(timezone_ids) != 1:
        _fail("TAPE_TIMEZONE_BINDING_INVALID")
    if saved_factor_source_sha256 is None or saved_factor_plan_id is None:
        _fail("TAPE_FACTOR_PLAN_INVALID")
    offline = _run_factor_strategy(
        expected,
        source_rows,
        factor_mode=factor_mode,
        direction=direction,
    )
    if offline["source_sha256"] != saved_factor_source_sha256:
        _fail("TAPE_FACTOR_SOURCE_MISMATCH")
    value_comparisons = 0
    reason_comparisons = 0
    membership_comparisons = 0
    for target_index, target in enumerate(expected["targets"]):
        for index, (actual, actual_reason, saved) in enumerate(
            zip(offline["values"][target], offline["reasons"][target], expected_factor_rows[target])
        ):
            saved_value = saved["value"]
            if math.isfinite(actual):
                if (
                    saved_value["finite"] is not True
                    or saved_value["float64_hex"] != actual.hex()
                    or float(saved_value["value"]).hex() != actual.hex()
                ):
                    _fail("TAPE_FACTOR_VALUE_MISMATCH")
            elif saved_value["finite"] is not False or saved_value["float64_hex"] != "nan":
                _fail("TAPE_FACTOR_VALUE_MISMATCH")
            if saved["reason"] != actual_reason:
                _fail("TAPE_FACTOR_REASON_MISMATCH")
            if saved["present"] is not True or saved["complete"] is not True:
                _fail("TAPE_FACTOR_MEMBERSHIP_MISMATCH")
            value_comparisons += 1
            reason_comparisons += 1
            membership_comparisons += 1
    if live_ready_rows < required_live_ready:
        _fail("TAPE_LIVE_READY_COUNT_INSUFFICIENT")
    if len(finite_witnesses) < 2:
        _fail("TAPE_DISTINCT_FINITE_WITNESS_INSUFFICIENT")
    if len(finite_targets) < 2:
        _fail("TAPE_DISTINCT_TARGET_WITNESS_INSUFFICIENT")
    if two_candidate_witness_rows < 1:
        _fail("TAPE_TWO_CANDIDATE_WITNESS_INSUFFICIENT")
    size_after, digest_after = _hash_file(tape_path, max_bytes)
    if size_after != expected_bytes or digest_after != expected_sha256:
        _fail("TAPE_CHANGED_DURING_VALIDATION")
    return {
        "status": "PASS",
        "evidence_level": "SAVED_DECISION_TAPE_OFFLINE_CEREBRO_PARITY_ONLY",
        "file_id": expected_file_id,
        "tape_sha256": expected_sha256,
        "tape_bytes": expected_bytes,
        "decision_record_count": record_count,
        "target_count": len(expected["targets"]),
        "grid_minute_count": len(expected["minutes"]),
        "grid_semantics_sha256": expected["grid_semantics_sha256"],
        "offline_factor_mode": factor_mode,
        "source_factor_mode": header["factor_mode"],
        "direction": direction,
        "preheat_bars": preheat_bars,
        "live_ready_rows": live_ready_rows,
        "required_live_ready": required_live_ready,
        "distinct_finite_witnesses": len(finite_witnesses),
        "two_candidate_witness_rows": two_candidate_witness_rows,
        "value_comparisons": value_comparisons,
        "reason_comparisons": reason_comparisons,
        "membership_comparisons": membership_comparisons,
        "timezone_id": next(iter(timezone_ids)),
        "clock_domain_id": expected["clock_domain_id"],
        "calendar_id": expected["calendar_id"],
        "orders_submitted": 0,
        "provider_calls": 0,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tape", required=True, type=Path)
    parser.add_argument("--expected-plan-json", required=True, type=Path)
    parser.add_argument("--file-id", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--bytes", required=True, type=int)
    parser.add_argument("--record-count", required=True, type=int)
    parser.add_argument("--factor-mode", choices=("native", "build"), required=True)
    parser.add_argument("--direction", type=int, choices=(-1, 1), required=True)
    parser.add_argument("--preheat-bars", type=int, required=True)
    parser.add_argument("--required-live-ready", type=int, default=100)
    parser.add_argument("--max-bytes", type=int, default=MAX_TAPE_BYTES)
    ns = parser.parse_args(argv)
    try:
        with ns.expected_plan_json.open("rb") as handle:
            expected_bytes = handle.read(MAX_PLAN_BYTES + 1)
        if len(expected_bytes) > MAX_PLAN_BYTES:
            _fail("EXPECTED_PLAN_BYTE_BUDGET_EXCEEDED")
        expected = json.loads(expected_bytes.decode("utf-8"))
        result = validate_saved_factor_tape(
            ns.tape,
            expected=expected,
            expected_file_id=ns.file_id,
            expected_sha256=ns.sha256,
            expected_bytes=ns.bytes,
            expected_record_count=ns.record_count,
            factor_mode=ns.factor_mode,
            direction=ns.direction,
            preheat_bars=ns.preheat_bars,
            required_live_ready=ns.required_live_ready,
            max_bytes=ns.max_bytes,
        )
    except SavedTapeValidationError as error:
        print(json.dumps({"status": "FAIL", "code": error.code}, sort_keys=True))
        return 1
    except (OSError, UnicodeError, json.JSONDecodeError):
        print(json.dumps({"status": "FAIL", "code": "EXPECTED_PLAN_READ_FAILED"}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
