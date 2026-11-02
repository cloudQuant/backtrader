"""JSON round-trip for point-in-time futures selection inputs.

The loader rebuilds the selector's typed inputs from public source snapshots
and calls :func:`select_main_contracts` again.  A serialized status or mapping
is never used as selection authority.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional, Sequence, Tuple

from .futures_main_contract import (
    ExchangeTradingCalendar,
    ExchangeTradingDay,
    FuturesContractRecord,
    MainContractManifest,
    MainContractPolicy,
    MainContractRankingSnapshot,
    ProductKey,
    ProductRankingCoverage,
    select_main_contracts,
)


_BUNDLE_SCHEMA = "backtrader.futures_selection_bundle.v1"
_DAY_CALENDAR_SCHEMA = "backtrader.exchange_trading_calendar.v1"


class SelectionBundleInputError(ValueError):
    """Raised when a public selection bundle is malformed or unsupported."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SelectionBundleInputError("{}_MUST_BE_OBJECT".format(name.upper()))
    return value


def _list(value: Any, name: str) -> Tuple[Any, ...]:
    if type(value) is not list:
        raise SelectionBundleInputError("{}_MUST_BE_ARRAY".format(name.upper()))
    return tuple(value)


def _text(value: Any, name: str, *, optional: bool = False) -> Optional[str]:
    if optional and value is None:
        return None
    if type(value) is not str or not value or value != value.strip():
        raise SelectionBundleInputError("{}_INVALID_TEXT".format(name.upper()))
    return value


def _date(value: Any, name: str, *, optional: bool = False) -> Optional[date]:
    if optional and value is None:
        return None
    if type(value) is not str:
        raise SelectionBundleInputError("{}_INVALID_DATE".format(name.upper()))
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise SelectionBundleInputError("{}_INVALID_DATE".format(name.upper())) from None
    if parsed.isoformat() != value:
        raise SelectionBundleInputError("{}_INVALID_DATE".format(name.upper()))
    return parsed


def _datetime(value: Any, name: str) -> datetime:
    if type(value) is not str:
        raise SelectionBundleInputError("{}_INVALID_DATETIME".format(name.upper()))
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        raise SelectionBundleInputError("{}_INVALID_DATETIME".format(name.upper())) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SelectionBundleInputError("{}_NAIVE_DATETIME".format(name.upper()))
    return parsed


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise SelectionBundleInputError("{}_INVALID_INTEGER".format(name.upper()))
    return value


def _boolean(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise SelectionBundleInputError("{}_INVALID_BOOLEAN".format(name.upper()))
    return value


def _product(value: Any, name: str = "product") -> ProductKey:
    row = _mapping(value, name)
    return ProductKey(
        _text(row.get("exchange_id"), name + ".exchange_id"),
        _text(row.get("product_id"), name + ".product_id"),
    )


def _number(value: Any) -> Any:
    """Restore exact JSON decimal strings while preserving invalid source values."""

    if type(value) is str:
        try:
            number = Decimal(value)
        except (InvalidOperation, ValueError):
            return value
        return number if number.is_finite() else value
    if isinstance(value, Decimal):
        return value
    if value is None or type(value) in (bool, int, float):
        return value
    raise SelectionBundleInputError("RANKING_VALUE_UNSUPPORTED_TYPE")


def _wire_number(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if value is None or type(value) in (bool, int, float, str):
        return value
    raise SelectionBundleInputError("RANKING_VALUE_UNSUPPORTED_TYPE")


def _coverage_from_dict(value: Any) -> ProductRankingCoverage:
    row = _mapping(value, "coverage_row")
    return ProductRankingCoverage(
        product=_product(row.get("product"), "coverage.product"),
        candidate_count=_integer(row.get("candidate_count"), "candidate_count"),
        expected_instrument_ids=tuple(
            _text(item, "expected_instrument_id")
            for item in _list(row.get("expected_instrument_ids"), "expected_instrument_ids")
        ),
        ranking_instrument_ids=tuple(
            _text(item, "ranking_instrument_id")
            for item in _list(row.get("ranking_instrument_ids"), "ranking_instrument_ids")
        ),
        candidate_set_complete=_boolean(
            row.get("candidate_set_complete"), "candidate_set_complete"
        ),
        ranking_values_complete=_boolean(
            row.get("ranking_values_complete"), "ranking_values_complete"
        ),
        finalized=_boolean(row.get("finalized"), "finalized"),
        latest_available=_boolean(row.get("latest_available"), "latest_available"),
        ranking_trading_day=_date(
            row.get("ranking_trading_day"), "ranking_trading_day", optional=True
        ),
        open_interest_unit=_text(
            row.get("open_interest_unit"), "open_interest_unit", optional=True
        ),
        volume_unit=_text(row.get("volume_unit"), "volume_unit", optional=True),
    )


def _candidate_from_dict(value: Any) -> FuturesContractRecord:
    row = _mapping(value, "candidate")
    asset_type = _text(row.get("asset_type"), "asset_type", optional=True)
    is_trading = row.get("is_trading")
    if is_trading is not None:
        is_trading = _boolean(is_trading, "is_trading")
    return FuturesContractRecord(
        product=_product(row.get("product"), "candidate.product"),
        instrument_id=_text(row.get("instrument_id"), "instrument_id"),
        asset_type=asset_type,
        is_trading=is_trading,
        expiry_date=_date(row.get("expiry_date"), "expiry_date", optional=True),
        open_interest=_number(row.get("open_interest")),
        volume=_number(row.get("volume")),
    )


def _ranking_from_dict(value: Any) -> MainContractRankingSnapshot:
    row = _mapping(value, "ranking")
    return MainContractRankingSnapshot(
        source_id=_text(row.get("source_id"), "ranking.source_id"),
        snapshot_id=_text(row.get("snapshot_id"), "ranking.snapshot_id"),
        source_sha256=_text(row.get("source_sha256"), "ranking.source_sha256"),
        available_at=_datetime(row.get("available_at"), "ranking.available_at"),
        retrieved_at=_datetime(row.get("retrieved_at"), "ranking.retrieved_at"),
        catalog_source_id=_text(row.get("catalog_source_id"), "catalog_source_id"),
        catalog_snapshot_id=_text(row.get("catalog_snapshot_id"), "catalog_snapshot_id"),
        catalog_sha256=_text(row.get("catalog_sha256"), "catalog_sha256"),
        catalog_available_at=_datetime(row.get("catalog_available_at"), "catalog_available_at"),
        catalog_retrieved_at=_datetime(row.get("catalog_retrieved_at"), "catalog_retrieved_at"),
        coverage=tuple(
            _coverage_from_dict(item) for item in _list(row.get("coverage"), "ranking.coverage")
        ),
        candidates=tuple(
            _candidate_from_dict(item)
            for item in _list(row.get("candidates"), "ranking.candidates")
        ),
    )


def _day_calendar_from_dict(value: Any) -> ExchangeTradingCalendar:
    row = _mapping(value, "calendar")
    if row.get("schema") != _DAY_CALENDAR_SCHEMA:
        raise SelectionBundleInputError("CALENDAR_SCHEMA_UNSUPPORTED")
    days = tuple(
        _date(item, "calendar.trading_day")
        for item in _list(row.get("trading_days"), "calendar.trading_days")
    )
    return ExchangeTradingCalendar(
        exchange_id=_text(row.get("exchange_id"), "calendar.exchange_id"),
        source_id=_text(row.get("source_id"), "calendar.source_id"),
        version=_text(row.get("version"), "calendar.version"),
        available_at=_datetime(row.get("available_at"), "calendar.available_at"),
        retrieved_at=_datetime(row.get("retrieved_at"), "calendar.retrieved_at"),
        coverage_start=_date(row.get("coverage_start"), "calendar.coverage_start"),
        coverage_through=_date(row.get("coverage_through"), "calendar.coverage_through"),
        trading_days=days,
        complete=_boolean(row.get("complete"), "calendar.complete"),
    )


def _calendar_from_dict(value: Any) -> ExchangeTradingCalendar:
    row = _mapping(value, "calendar")
    schema = row.get("schema")
    if schema == _DAY_CALENDAR_SCHEMA:
        return _day_calendar_from_dict(row)
    if schema == "backtrader.exchange_session_calendar.v1":
        from .futures_sessions import load_exchange_session_calendar

        return load_exchange_session_calendar(row).to_main_contract_calendar()
    raise SelectionBundleInputError("CALENDAR_SCHEMA_UNSUPPORTED")


def _calendar_to_dict(calendar: Any) -> Mapping[str, Any]:
    if isinstance(calendar, ExchangeTradingCalendar):
        return {
            "schema": _DAY_CALENDAR_SCHEMA,
            "exchange_id": calendar.exchange_id,
            "source_id": calendar.source_id,
            "version": calendar.version,
            "available_at": calendar.available_at.isoformat(),
            "retrieved_at": calendar.retrieved_at.isoformat(),
            "coverage_start": calendar.coverage_start.isoformat(),
            "coverage_through": calendar.coverage_through.isoformat(),
            "complete": calendar.complete,
            "trading_days": [day.isoformat() for day in calendar.trading_days],
        }
    # The import is intentionally local: session planning can be used without
    # importing the JSON selection adapter.
    from .futures_sessions import ExchangeSessionCalendar

    if isinstance(calendar, ExchangeSessionCalendar):
        return calendar.to_dict()
    raise SelectionBundleInputError("CALENDAR_TYPE_UNSUPPORTED")


def selection_bundle_to_dict(
    snapshot: MainContractRankingSnapshot,
    target_products: Sequence[ProductKey],
    current_trading_days: Sequence[ExchangeTradingDay],
    calendars: Sequence[Any],
    *,
    decision_at: datetime,
    policy: MainContractPolicy,
    selection_claim: Optional[MainContractManifest] = None,
) -> dict[str, Any]:
    """Serialize typed public source inputs for deterministic offline replay.

    ``selection_claim`` is carried for audit comparison only.  Loading always
    reruns the pure selector from the input snapshots.
    """

    if not isinstance(snapshot, MainContractRankingSnapshot):
        raise ValueError("snapshot must be MainContractRankingSnapshot")
    if not isinstance(policy, MainContractPolicy):
        raise ValueError("policy must be MainContractPolicy")
    if not isinstance(decision_at, datetime) or decision_at.tzinfo is None:
        raise ValueError("decision_at must be timezone-aware")
    products = tuple(target_products)
    if any(not isinstance(item, ProductKey) for item in products):
        raise ValueError("target_products must contain ProductKey records")
    day_rows = tuple(current_trading_days)
    if any(not isinstance(item, ExchangeTradingDay) for item in day_rows):
        raise ValueError("current_trading_days must contain ExchangeTradingDay records")
    document = {
        "schema": _BUNDLE_SCHEMA,
        "decision_at": decision_at.isoformat(),
        "target_products": [
            {"exchange_id": product.exchange_id, "product_id": product.product_id}
            for product in products
        ],
        "policy": {
            "policy_id": policy.policy_id,
            "minimum_trading_days_to_expiry": policy.minimum_trading_days_to_expiry,
        },
        "ranking": {
            "source_id": snapshot.source_id,
            "snapshot_id": snapshot.snapshot_id,
            "source_sha256": snapshot.source_sha256,
            "available_at": snapshot.available_at.isoformat(),
            "retrieved_at": snapshot.retrieved_at.isoformat(),
            "catalog_source_id": snapshot.catalog_source_id,
            "catalog_snapshot_id": snapshot.catalog_snapshot_id,
            "catalog_sha256": snapshot.catalog_sha256,
            "catalog_available_at": snapshot.catalog_available_at.isoformat(),
            "catalog_retrieved_at": snapshot.catalog_retrieved_at.isoformat(),
            "coverage": [
                {
                    "product": {
                        "exchange_id": row.product.exchange_id,
                        "product_id": row.product.product_id,
                    },
                    "candidate_count": row.candidate_count,
                    "expected_instrument_ids": list(row.expected_instrument_ids),
                    "ranking_instrument_ids": list(row.ranking_instrument_ids),
                    "candidate_set_complete": row.candidate_set_complete,
                    "ranking_values_complete": row.ranking_values_complete,
                    "finalized": row.finalized,
                    "latest_available": row.latest_available,
                    "ranking_trading_day": row.ranking_trading_day.isoformat()
                    if row.ranking_trading_day is not None
                    else None,
                    "open_interest_unit": row.open_interest_unit,
                    "volume_unit": row.volume_unit,
                }
                for row in snapshot.coverage
            ],
            "candidates": [
                {
                    "product": {
                        "exchange_id": row.product.exchange_id,
                        "product_id": row.product.product_id,
                    },
                    "instrument_id": row.instrument_id,
                    "asset_type": row.asset_type,
                    "is_trading": row.is_trading,
                    "expiry_date": row.expiry_date.isoformat()
                    if row.expiry_date is not None
                    else None,
                    "open_interest": _wire_number(row.open_interest),
                    "volume": _wire_number(row.volume),
                }
                for row in snapshot.candidates
            ],
        },
        "current_trading_days": [
            {
                "exchange_id": row.exchange_id,
                "trading_day": row.trading_day.isoformat(),
            }
            for row in day_rows
        ],
        "calendars": [_calendar_to_dict(calendar) for calendar in calendars],
    }
    if selection_claim is not None:
        if not isinstance(selection_claim, MainContractManifest):
            raise ValueError("selection_claim must be MainContractManifest or None")
        document["selection_claim"] = selection_claim.to_dict()
    return document


def load_selection_bundle(document: Mapping[str, Any]) -> MainContractManifest:
    """Rebuild typed snapshot inputs and reselect; never trust a saved claim.

    A bundle may include ``selection_claim`` as an audit artifact.  That value
    is deliberately ignored: the returned manifest is generated anew from
    decision time, target product identities, ranking rows, TradingDays,
    calendars, and policy.
    """

    row = _mapping(document, "bundle")
    if row.get("schema") != _BUNDLE_SCHEMA:
        raise SelectionBundleInputError("SELECTION_BUNDLE_SCHEMA_UNSUPPORTED")
    decision_at = _datetime(row.get("decision_at"), "decision_at")
    targets = tuple(
        _product(item, "target_product")
        for item in _list(row.get("target_products"), "target_products")
    )
    policy_row = _mapping(row.get("policy"), "policy")
    policy = MainContractPolicy(
        policy_id=_text(policy_row.get("policy_id"), "policy_id"),
        minimum_trading_days_to_expiry=_integer(
            policy_row.get("minimum_trading_days_to_expiry"),
            "minimum_trading_days_to_expiry",
        ),
    )
    ranking = _ranking_from_dict(row.get("ranking"))
    current_days = tuple(
        ExchangeTradingDay(
            exchange_id=_text(item.get("exchange_id"), "current_day.exchange_id"),
            trading_day=_date(item.get("trading_day"), "current_day.trading_day"),
        )
        for item in (
            _mapping(item, "current_trading_day")
            for item in _list(row.get("current_trading_days"), "current_trading_days")
        )
    )
    calendars = tuple(
        _calendar_from_dict(item) for item in _list(row.get("calendars"), "calendars")
    )
    return select_main_contracts(
        ranking,
        targets,
        current_days,
        calendars,
        decision_at=decision_at,
        policy=policy,
    )


__all__ = [
    "SelectionBundleInputError",
    "load_selection_bundle",
    "selection_bundle_to_dict",
]
