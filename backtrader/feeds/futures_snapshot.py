"""Consume a provider-neutral, bounded futures market snapshot.

The provider SDK owns native query dispatch, native row decoding, session
identity, and scope-completeness decisions.  This module only binds one
``bt_api_py`` futures snapshot facade result to its exact freshness lease and
checks its public completeness and time bounds before Backtrader consumes it.

Provider event date/time components are audit data.  Query completion time is
not treated as a market receive clock or as proof of live market freshness.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional


_DEFAULT_MAX_COLLECTION_SECONDS = 300.0
_DEFAULT_MAX_SNAPSHOT_AGE_SECONDS = 300.0
_DEFAULT_LEASE_SECONDS = 30.0
_MAX_CONFIGURED_SECONDS = 3600.0
_MAX_QUERY_OBSERVATIONS = 8
_LEASE_PURPOSE = "backtrader.futures.snapshot.selection"
_SDK_ERROR_CODES = frozenset(
    {
        "FUTURES_MARKET_REQUEST_INVALID",
        "FUTURES_MARKET_QUERY_FAILED",
        "FUTURES_MARKET_RECEIPT_INVALID",
        "FUTURES_MARKET_LEASE_UNAVAILABLE",
        "FUTURES_MARKET_LEASE_INVALID",
    }
)


@dataclass(frozen=True)
class FuturesSnapshotQueryObservation:
    """Finite, value-free facts about one SDK facade phase."""

    stage: str
    entered: bool
    returned: bool
    elapsed_seconds: Optional[float]
    code: Optional[str]
    complete: Optional[bool]
    scope_complete: Optional[bool]


class FuturesSnapshotError(RuntimeError):
    """Stable reason that one provider-neutral futures snapshot was refused."""

    def __init__(
        self,
        code: str,
        query_observations: tuple[FuturesSnapshotQueryObservation, ...] = (),
    ) -> None:
        if type(code) is not str or not code or code != code.strip():
            code = "FUTURES_SNAPSHOT_UNAVAILABLE"
        observations = query_observations
        if (
            type(observations) is not tuple
            or len(observations) > _MAX_QUERY_OBSERVATIONS
            or any(type(item) is not FuturesSnapshotQueryObservation for item in observations)
        ):
            observations = ()
        self.code = code
        self.query_observations = observations
        super().__init__(code)


@dataclass(frozen=True)
class LeasedFuturesSnapshot:
    """The exact SDK snapshot and provider-issued lease returned by collection.

    The SDK facade is intentionally not retained here.  The caller that owns
    it must pass that same facade together with ``snapshot`` and ``lease`` to
    the selector, which revalidates the lease immediately before and after
    consuming the snapshot.
    """

    snapshot: Any
    lease: Any


def _fail(
    code: str,
    observations: tuple[FuturesSnapshotQueryObservation, ...] = (),
) -> None:
    raise FuturesSnapshotError(code, observations)


def _duration(value: Any, code: str) -> float:
    if type(value) not in (int, float):
        _fail(code)
    number = float(value)
    if not math.isfinite(number) or number <= 0 or number > _MAX_CONFIGURED_SECONDS:
        _fail(code)
    return number


def _now_utc() -> datetime:
    """Private clock seam for deterministic source-level verification."""

    return datetime.now(timezone.utc)


def _utc(value: Any) -> Optional[datetime]:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        return None
    if value.utcoffset() != timedelta(0):
        return None
    return value.astimezone(timezone.utc)


def _load_sdk_contract() -> tuple:
    try:
        from bt_api_py.futures_contracts import (
            FUTURES_CATALOG_FAMILY,
            FUTURES_DEPTH_FAMILY,
            FUTURES_QUOTES_FAMILY,
            FUTURES_SESSION_FAMILY,
            FuturesAssetType,
            FuturesCatalogDisposition,
            FuturesCatalogRecord,
            FuturesContractKind,
            FuturesDepthRecord,
            FuturesMarketSnapshotRequest,
            FuturesQuantityUnit,
            FuturesQuoteRecord,
            FuturesSessionRecord,
            FuturesSessionStatus,
            FuturesVolumeSemantics,
            QueryBatchReceipt,
            QueryCompleteness,
            QueryRequest,
            QuerySnapshot,
            QuerySnapshotLease,
        )
        from bt_api_py.futures_market_facade import (
            FuturesMarketSnapshot,
            FuturesMarketSnapshotError,
            FuturesMarketSnapshotFacade,
        )
    except ImportError:
        _fail("FUTURES_MARKET_SDK_UNAVAILABLE")
    return (
        FUTURES_CATALOG_FAMILY,
        FUTURES_DEPTH_FAMILY,
        FUTURES_QUOTES_FAMILY,
        FUTURES_SESSION_FAMILY,
        FuturesAssetType,
        FuturesCatalogDisposition,
        FuturesCatalogRecord,
        FuturesContractKind,
        FuturesSessionStatus,
        FuturesVolumeSemantics,
        FuturesDepthRecord,
        FuturesMarketSnapshot,
        FuturesMarketSnapshotError,
        FuturesMarketSnapshotFacade,
        FuturesMarketSnapshotRequest,
        FuturesQuantityUnit,
        FuturesQuoteRecord,
        FuturesSessionRecord,
        QueryBatchReceipt,
        QueryCompleteness,
        QueryRequest,
        QuerySnapshot,
        QuerySnapshotLease,
    )


def _observation(
    *,
    stage: str,
    entered: bool,
    returned: bool,
    start: float,
    end: float,
    code: Optional[str] = None,
    complete: Optional[bool] = None,
    scope_complete: Optional[bool] = None,
) -> FuturesSnapshotQueryObservation:
    elapsed = end - start
    elapsed_seconds = (
        float(elapsed)
        if type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0
        else None
    )
    return FuturesSnapshotQueryObservation(
        stage=stage,
        entered=entered,
        returned=returned,
        elapsed_seconds=elapsed_seconds,
        code=code,
        complete=complete,
        scope_complete=scope_complete,
    )


def _validate_composite(
    snapshot: Any,
    request: Any,
    *,
    contract: tuple,
) -> tuple:
    (
        catalog_family,
        depth_family,
        quotes_family,
        session_family,
        asset_type_enum,
        catalog_disposition_type,
        catalog_record_type,
        contract_kind_type,
        session_status_type,
        volume_semantics_type,
        depth_record_type,
        snapshot_type,
        _snapshot_error_type,
        _facade_type,
        request_type,
        quantity_unit_type,
        quote_record_type,
        session_record_type,
        receipt_type,
        completeness_type,
        query_request_type,
        query_snapshot_type,
        _lease_type,
    ) = contract

    if type(request) is not request_type or type(snapshot) is not snapshot_type:
        _fail("FUTURES_SNAPSHOT_TYPE_INVALID")
    if getattr(snapshot, "request", None) != request:
        _fail("FUTURES_SNAPSHOT_REQUEST_MISMATCH")

    receipt = getattr(snapshot, "receipt", None)
    coverage = getattr(snapshot, "coverage", None)
    if type(receipt) is not receipt_type or coverage is None:
        _fail("FUTURES_SNAPSHOT_EVIDENCE_MISSING")
    if getattr(receipt, "complete", None) is not True:
        _fail("FUTURES_SNAPSHOT_RECEIPT_INCOMPLETE")
    if getattr(snapshot, "complete", None) is not True:
        _fail("FUTURES_SNAPSHOT_INCOMPLETE")
    if getattr(coverage, "complete", None) is not True:
        _fail("FUTURES_SNAPSHOT_COVERAGE_INCOMPLETE")
    if getattr(coverage, "scope_complete", None) is not True:
        _fail("FUTURES_SNAPSHOT_SCOPE_INCOMPLETE")

    source_ref = getattr(snapshot, "source_ref", None)
    generation = getattr(snapshot, "generation", None)
    if (
        type(source_ref) is not str
        or not source_ref
        or type(generation) is not str
        or not generation
        or receipt.source_ref != source_ref
        or receipt.generation != generation
    ):
        _fail("FUTURES_SNAPSHOT_SOURCE_BINDING_INVALID")

    expected_refs = request.family_request_refs
    expected_family = {
        session_family: "session_snapshot",
        catalog_family: "catalog_snapshot",
        quotes_family: "quote_snapshot",
    }
    if request.include_depth:
        expected_family[depth_family] = "depth_snapshot"
    receipt_requests = tuple(getattr(receipt, "requests", ()))
    request_map = {item.request_ref: item for item in receipt_requests}
    if (
        len(request_map) != len(receipt_requests)
        or set(request_map) != set(expected_refs.values())
    ):
        _fail("FUTURES_SNAPSHOT_REQUEST_SET_MISMATCH")

    selected = []
    for family, snapshot_attr in expected_family.items():
        query_snapshot = getattr(snapshot, snapshot_attr, None)
        if type(query_snapshot) is not query_snapshot_type:
            _fail("FUTURES_SNAPSHOT_FAMILY_MISSING")
        query_request = query_snapshot.request
        request_ref = expected_refs.get(family)
        expected_request = (
            query_request_type(
                request_ref=request_ref,
                family=family,
                filters=request.filters_for(family),
                required=True,
                require_complete_scope=True,
            )
            if request_ref is not None
            else None
        )
        if (
            request_ref is None
            or expected_request is None
            or query_request.request_ref != request_ref
            or query_request.family != family
            or query_request != expected_request
            or request_map.get(request_ref) != query_request
        ):
            _fail("FUTURES_SNAPSHOT_FAMILY_REQUEST_MISMATCH")
        if (
            query_snapshot.completeness is not completeness_type.COMPLETE
            or query_snapshot.is_complete is not True
            or query_snapshot.scope_complete is not True
            or query_snapshot.source_ref != source_ref
            or query_snapshot.generation != generation
            or query_snapshot.snapshot_ref not in receipt.complete_snapshot_refs
        ):
            _fail("FUTURES_SNAPSHOT_FAMILY_INCOMPLETE")
        selected.append((family, query_snapshot))

        coverage_name = family[len("futures_") :] if family.startswith("futures_") else family
        family_coverage = getattr(coverage, coverage_name, None)
        if (
            family_coverage is None
            or getattr(family_coverage, "complete", None) is not True
            or family_coverage.request_ref != request_ref
            or family_coverage.filters != expected_request.filters
            or family_coverage.source_ref != source_ref
            or family_coverage.generation != generation
            or family_coverage.snapshot_ref != query_snapshot.snapshot_ref
            or family_coverage.started_at != query_snapshot.started_at
            or family_coverage.completed_at != query_snapshot.completed_at
            or family_coverage.observed_at != query_snapshot.observed_at
            or family_coverage.records_digest != query_snapshot.records_digest
            or family_coverage.record_count != query_snapshot.record_count
        ):
            _fail("FUTURES_SNAPSHOT_FAMILY_COVERAGE_MISMATCH")

    if any(
        type(record) is not catalog_record_type
        for record in tuple(getattr(snapshot, "catalog", ()))
    ):
        _fail("FUTURES_SNAPSHOT_CATALOG_SCHEMA_INVALID")
    if any(
        type(record) is not quote_record_type
        for record in tuple(getattr(snapshot, "quotes", ()))
    ):
        _fail("FUTURES_SNAPSHOT_QUOTE_SCHEMA_INVALID")
    if any(
        type(record) is not depth_record_type
        for record in tuple(getattr(snapshot, "depth", ()))
    ):
        _fail("FUTURES_SNAPSHOT_DEPTH_SCHEMA_INVALID")
    if any(
        type(record) is not session_record_type
        for record in tuple(getattr(snapshot, "sessions", ()))
    ):
        _fail("FUTURES_SNAPSHOT_SESSION_SCHEMA_INVALID")

    projected_fields = {
        session_family: ("session_snapshot", "sessions", session_record_type),
        catalog_family: ("catalog_snapshot", "catalog", catalog_record_type),
        quotes_family: ("quote_snapshot", "quotes", quote_record_type),
    }
    if request.include_depth:
        projected_fields[depth_family] = ("depth_snapshot", "depth", depth_record_type)
    for family, (snapshot_attr, records_attr, record_type) in projected_fields.items():
        query_snapshot = getattr(snapshot, snapshot_attr, None)
        try:
            source_projection = tuple(
                record_type.from_dict(record).to_dict()
                for record in query_snapshot.records
            )
            composite_projection = tuple(
                record.to_dict() for record in getattr(snapshot, records_attr, ())
            )
        except Exception:
            _fail("FUTURES_SNAPSHOT_RECORD_PROJECTION_INVALID")
        if composite_projection != source_projection:
            _fail("FUTURES_SNAPSHOT_RECORD_DIGEST_BINDING_INVALID")

    sessions = tuple(snapshot.sessions)
    if not sessions:
        _fail("FUTURES_SNAPSHOT_SESSION_SCOPE_EMPTY")
    route_sessions = tuple(item for item in sessions if item.venue is None)
    venue_sessions = tuple(item for item in sessions if item.venue is not None)
    if len(route_sessions) > 1 or (route_sessions and venue_sessions):
        _fail("FUTURES_SNAPSHOT_SESSION_SCOPE_MIXED_OR_DUPLICATE")
    route_session = route_sessions[0] if route_sessions else None
    session_by_venue = {item.venue: item for item in venue_sessions}
    if len(session_by_venue) != len(venue_sessions):
        _fail("FUTURES_SNAPSHOT_SESSION_DUPLICATE")
    if any(item.environment != request.environment for item in sessions):
        _fail("FUTURES_SNAPSHOT_SESSION_ENVIRONMENT_MISMATCH")
    if request.require_active_session and any(
        item.session_status is not session_status_type.ACTIVE for item in sessions
    ):
        _fail("FUTURES_SNAPSHOT_ACTIVE_SESSION_REQUIRED")
    if (
        request.venues is not None
        and route_session is None
        and set(session_by_venue) != set(request.venues)
    ):
        _fail("FUTURES_SNAPSHOT_SESSION_SCOPE_MISMATCH")
    if request.trading_day is not None and any(
        item.trading_day != request.trading_day for item in sessions
    ):
        _fail("FUTURES_SNAPSHOT_TRADING_DAY_MISMATCH")
    catalog = tuple(snapshot.catalog)
    quotes = tuple(snapshot.quotes)
    depth = tuple(snapshot.depth)
    observed_venues = {
        item.instrument.venue for item in (*catalog, *quotes, *depth)
    }
    expected_trading_days = (
        {
            venue: route_session.trading_day
            for venue in (request.venues if request.venues is not None else observed_venues)
        }
        if route_session is not None
        else {venue: item.trading_day for venue, item in session_by_venue.items()}
    )
    trading_days = getattr(snapshot, "trading_days", None)
    if (
        not hasattr(trading_days, "items")
        or dict(trading_days) != expected_trading_days
        or getattr(snapshot, "route_trading_day", None)
        != (route_session.trading_day if route_session is not None else None)
    ):
        _fail("FUTURES_SNAPSHOT_TRADING_DAYS_MISMATCH")

    if any(
        row.disposition is catalog_disposition_type.UNKNOWN
        or row.contract_kind is contract_kind_type.UNKNOWN
        or row.asset_type is asset_type_enum.UNKNOWN
        for row in catalog
    ):
        _fail("FUTURES_SNAPSHOT_CATALOG_CLASSIFICATION_UNKNOWN")
    if any(
        row.disposition is catalog_disposition_type.INCLUDED
        and row.contract_kind not in request.contract_kinds
        for row in catalog
    ):
        _fail("FUTURES_SNAPSHOT_CATALOG_SCOPE_MISMATCH")
    if any(
        row.instrument.environment != request.environment
        for row in catalog
    ):
        _fail("FUTURES_SNAPSHOT_CATALOG_ENVIRONMENT_MISMATCH")
    if route_session is None and any(
        row.instrument.venue not in session_by_venue for row in catalog
    ):
        _fail("FUTURES_SNAPSHOT_CATALOG_VENUE_OUT_OF_SCOPE")
    included_instruments = {
        row.instrument
        for row in catalog
        if (
            row.disposition is catalog_disposition_type.INCLUDED
            and row.contract_kind in request.contract_kinds
            and row.is_trading is True
            and row.expiry_date is not None
        )
    }
    if len(included_instruments) != sum(
        row.disposition is catalog_disposition_type.INCLUDED
        and row.contract_kind in request.contract_kinds
        and row.is_trading is True
        and row.expiry_date is not None
        for row in catalog
    ):
        _fail("FUTURES_SNAPSHOT_CATALOG_DUPLICATE")
    quote_instruments = {row.instrument for row in quotes}
    if len(quote_instruments) != len(quotes) or quote_instruments != included_instruments:
        _fail("FUTURES_SNAPSHOT_QUOTE_COVERAGE_MISMATCH")
    for quote in quotes:
        if quote.instrument.environment != request.environment:
            _fail("FUTURES_SNAPSHOT_QUOTE_ENVIRONMENT_MISMATCH")
        quote_session = session_by_venue.get(quote.instrument.venue, route_session)
        if quote_session is None:
            _fail("FUTURES_SNAPSHOT_QUOTE_VENUE_OUT_OF_SCOPE")
        if quote.trading_day != quote_session.trading_day:
            _fail("FUTURES_SNAPSHOT_QUOTE_TRADING_DAY_MISMATCH")
        for field_name in request.required_quote_fields:
            if getattr(quote, field_name) is None:
                _fail("FUTURES_SNAPSHOT_QUOTE_FIELD_MISSING")

    if set(coverage.expected_instruments) != included_instruments:
        _fail("FUTURES_SNAPSHOT_EXPECTED_INSTRUMENTS_MISMATCH")
    if (
        coverage.missing_quote_instruments
        or coverage.missing_quote_fields
        or coverage.quote_unit_mismatches
        or coverage.quote_semantic_mismatches
        or coverage.depth_unit_mismatches
        or coverage.unclassified_instruments
        or coverage.blockers
    ):
        _fail("FUTURES_SNAPSHOT_COVERAGE_BLOCKED")
    required_quote_fields = set(request.required_quote_fields)
    unit_requirements = []
    if "open_interest" in required_quote_fields:
        unit_requirements.append(
            ("open_interest_unit", request.required_open_interest_unit)
        )
    if required_quote_fields.intersection({"volume", "bid_volume", "ask_volume"}):
        unit_requirements.append(("volume_unit", request.required_volume_unit))
    for quote in quotes:
        for unit_field, required_unit in unit_requirements:
            actual_unit = getattr(quote, unit_field)
            if (
                type(actual_unit) is not quantity_unit_type
                or (
                    required_unit is not None
                    and (
                        actual_unit is quantity_unit_type.UNKNOWN
                        or actual_unit is not required_unit
                    )
                )
            ):
                _fail("FUTURES_SNAPSHOT_QUOTE_UNIT_MISMATCH")
        if "volume" in required_quote_fields:
            actual_semantics = quote.volume_semantics
            required_semantics = request.required_volume_semantics
            if type(actual_semantics) is not volume_semantics_type or (
                required_semantics is not None
                and (
                    actual_semantics is volume_semantics_type.UNKNOWN
                    or actual_semantics is not required_semantics
                )
            ):
                _fail("FUTURES_SNAPSHOT_QUOTE_VOLUME_SEMANTICS_MISMATCH")
    if request.include_depth:
        depth_instruments = {item.instrument for item in snapshot.depth}
        if (
            len(depth_instruments) != len(snapshot.depth)
            or depth_instruments != included_instruments
            or coverage.missing_depth_instruments
            or any(item.complete_state is not True for item in snapshot.depth)
            or any(
                item.instrument.environment != request.environment
                or session_by_venue.get(item.instrument.venue, route_session) is None
                or item.trading_day
                != session_by_venue.get(item.instrument.venue, route_session).trading_day
                or len(item.bids) < request.depth_levels
                or len(item.asks) < request.depth_levels
                or type(item.volume_unit) is not quantity_unit_type
                or (
                    request.required_depth_volume_unit is not None
                    and (
                        item.volume_unit is quantity_unit_type.UNKNOWN
                        or item.volume_unit is not request.required_depth_volume_unit
                    )
                )
                for item in snapshot.depth
            )
        ):
            _fail("FUTURES_SNAPSHOT_DEPTH_COVERAGE_MISMATCH")
    elif snapshot.depth_snapshot is not None or snapshot.depth or coverage.depth is not None:
        _fail("FUTURES_SNAPSHOT_UNREQUESTED_DEPTH_PRESENT")

    freshness_status = getattr(snapshot, "freshness_status", None)
    if getattr(freshness_status, "value", freshness_status) != "unavailable":
        _fail("FUTURES_SNAPSHOT_CLOCK_STATUS_UNSUPPORTED")

    return tuple(selected)


def _validate_time_bounds(
    snapshot: Any,
    selected: tuple,
    *,
    now: datetime,
    max_collection_seconds: float,
    max_snapshot_age_seconds: float,
) -> datetime:
    coverage = snapshot.coverage
    coverage_by_family = {
        coverage.session.family: coverage.session,
        coverage.catalog.family: coverage.catalog,
        coverage.quotes.family: coverage.quotes,
    }
    if coverage.depth is not None:
        coverage_by_family[coverage.depth.family] = coverage.depth

    selected_coverages = []
    starts = []
    completions = []
    expiries = []
    for family, query_snapshot in selected:
        family_coverage = coverage_by_family.get(family)
        if family_coverage is None:
            _fail("FUTURES_SNAPSHOT_FAMILY_COVERAGE_MISSING")
        started = _utc(family_coverage.started_at)
        completed = _utc(family_coverage.completed_at)
        observed = _utc(family_coverage.observed_at)
        if started is None or completed is None or observed is None:
            _fail("FUTURES_SNAPSHOT_TIME_EVIDENCE_MISSING")
        if started > completed or observed < completed or observed > now:
            _fail("FUTURES_SNAPSHOT_TIME_ORDER_INVALID")
        if _utc(query_snapshot.started_at) != started:
            _fail("FUTURES_SNAPSHOT_TIME_BINDING_INVALID")
        if _utc(query_snapshot.completed_at) != completed:
            _fail("FUTURES_SNAPSHOT_TIME_BINDING_INVALID")
        if _utc(query_snapshot.observed_at) != observed:
            _fail("FUTURES_SNAPSHOT_TIME_BINDING_INVALID")
        age = (now - completed).total_seconds()
        if age < 0 or age > max_snapshot_age_seconds:
            _fail("FUTURES_SNAPSHOT_TOO_OLD")
        starts.append(started)
        completions.append(completed)
        expiries.append(completed + timedelta(seconds=max_snapshot_age_seconds))
        selected_coverages.append(family_coverage)

    if not starts or (max(completions) - min(starts)).total_seconds() > max_collection_seconds:
        _fail("FUTURES_SNAPSHOT_COLLECTION_SPAN_EXCEEDED")

    composite_completed = _utc(getattr(snapshot, "completed_at", None))
    receipt = snapshot.receipt
    receipt_started = _utc(getattr(receipt, "started_at", None))
    receipt_completed = _utc(getattr(receipt, "completed_at", None))
    composite_observed = _utc(getattr(snapshot, "observed_at", None))
    observed_times = [_utc(item.observed_at) for item in selected_coverages]
    if (
        composite_completed is None
        or receipt_started is None
        or receipt_completed is None
        or _utc(getattr(snapshot, "requested_at", None)) != receipt_started
        or composite_completed != receipt_completed
        or composite_completed < max(completions)
        or receipt_started > min(starts)
        or (receipt_completed - receipt_started).total_seconds() > max_collection_seconds
        or composite_observed is None
        or any(value is None for value in observed_times)
        or composite_observed != max(observed_times)
        or composite_observed > now
    ):
        _fail("FUTURES_SNAPSHOT_COMPOSITE_TIME_INVALID")
    return min(expiries)


def _validate_provider_lease(
    snapshot_facade: Any,
    snapshot: Any,
    lease: Any,
    *,
    error_type: type,
    stage: str,
    observations: list[FuturesSnapshotQueryObservation],
) -> None:
    phase_start = time.monotonic()
    validation_now = _utc(_now_utc())
    if validation_now is None:
        _fail("FUTURES_SNAPSHOT_CLOCK_UNAVAILABLE", tuple(observations))
    try:
        current = snapshot_facade.validate_lease(snapshot, lease, now=validation_now)
    except error_type as error:
        phase_end = time.monotonic()
        code = getattr(error, "code", None)
        if type(code) is not str or code not in _SDK_ERROR_CODES:
            code = "FUTURES_MARKET_LEASE_INVALID"
        observations.append(
            _observation(
                stage=stage,
                entered=True,
                returned=False,
                start=phase_start,
                end=phase_end,
                code=code,
                complete=True,
                scope_complete=True,
            )
        )
        _fail("FUTURES_SNAPSHOT_" + code, tuple(observations))
    except Exception:
        phase_end = time.monotonic()
        observations.append(
            _observation(
                stage=stage,
                entered=True,
                returned=False,
                start=phase_start,
                end=phase_end,
                code="FUTURES_MARKET_LEASE_INVALID",
                complete=True,
                scope_complete=True,
            )
        )
        _fail("FUTURES_SNAPSHOT_LEASE_VALIDATION_FAILED", tuple(observations))
    phase_end = time.monotonic()
    observations.append(
        _observation(
            stage=stage,
            entered=True,
            returned=True,
            start=phase_start,
            end=phase_end,
            complete=True,
            scope_complete=True,
        )
    )
    if type(current) is not bool or current is not True:
        _fail("FUTURES_SNAPSHOT_LEASE_NOT_CURRENT", tuple(observations))


def collect_futures_snapshot(
    snapshot_facade: Any,
    request: Any,
    *,
    max_collection_seconds: float = _DEFAULT_MAX_COLLECTION_SECONDS,
    max_snapshot_age_seconds: float = _DEFAULT_MAX_SNAPSHOT_AGE_SECONDS,
    lease_seconds: float = _DEFAULT_LEASE_SECONDS,
) -> LeasedFuturesSnapshot:
    """Collect and lease one exact provider-neutral futures snapshot.

    The caller supplies the exact SDK ``FuturesMarketSnapshotRequest``.  In
    particular, this function never guesses venues or a futures trading day
    from BT state or the local wall clock.  The provider facade must attest
    complete session/catalog/quote scope, including per-venue trading days and
    cross-family coverage.  Optional depth is queried only when the explicit
    request asks for it. ``max_snapshot_age_seconds`` bounds the age of query
    completion evidence; it does not qualify provider event time or market
    freshness, which remain unavailable in the neutral SDK contract.
    """

    contract = _load_sdk_contract()
    (
        _catalog_family,
        _depth_family,
        _quotes_family,
        _session_family,
        _asset_type_enum,
        _catalog_disposition_type,
        _catalog_record_type,
        _contract_kind_type,
        _session_status_type,
        _volume_semantics_type,
        _depth_record_type,
        snapshot_type,
        snapshot_error_type,
        facade_type,
        request_type,
        _quantity_unit_type,
        _quote_record_type,
        _session_record_type,
        _receipt_type,
        _completeness_type,
        _query_request_type,
        _query_snapshot_type,
        lease_type,
    ) = contract
    if type(snapshot_facade) is not facade_type or type(request) is not request_type:
        _fail("FUTURES_SNAPSHOT_INPUT_INVALID")

    collection_limit = _duration(max_collection_seconds, "FUTURES_COLLECTION_LIMIT_INVALID")
    age_limit = _duration(max_snapshot_age_seconds, "FUTURES_SNAPSHOT_AGE_LIMIT_INVALID")
    lease_limit = _duration(lease_seconds, "FUTURES_SNAPSHOT_LEASE_LIMIT_INVALID")
    if lease_limit > age_limit:
        _fail("FUTURES_SNAPSHOT_LEASE_EXCEEDS_AGE_LIMIT")

    initial_now = _utc(_now_utc())
    if initial_now is None:
        _fail("FUTURES_SNAPSHOT_CLOCK_UNAVAILABLE")
    started_monotonic = time.monotonic()
    deadline = initial_now + timedelta(seconds=collection_limit)
    observations: list[FuturesSnapshotQueryObservation] = []

    phase_start = time.monotonic()
    try:
        snapshot = snapshot_facade.refresh(request, deadline=deadline)
    except snapshot_error_type as error:
        phase_end = time.monotonic()
        code = getattr(error, "code", None)
        if type(code) is not str or code not in _SDK_ERROR_CODES:
            code = "FUTURES_MARKET_QUERY_FAILED"
        observations.append(
            _observation(
                stage="refresh",
                entered=True,
                returned=False,
                start=phase_start,
                end=phase_end,
                code=code,
            )
        )
        _fail("FUTURES_SNAPSHOT_" + code, tuple(observations))
    except Exception:
        phase_end = time.monotonic()
        observations.append(
            _observation(
                stage="refresh",
                entered=True,
                returned=False,
                start=phase_start,
                end=phase_end,
                code="FUTURES_MARKET_QUERY_FAILED",
            )
        )
        _fail("FUTURES_SNAPSHOT_PROVIDER_QUERY_FAILED", tuple(observations))

    phase_end = time.monotonic()
    observations.append(
        _observation(
            stage="refresh",
            entered=True,
            returned=True,
            start=phase_start,
            end=phase_end,
            complete=getattr(snapshot, "complete", None)
            if type(getattr(snapshot, "complete", None)) is bool
            else None,
            scope_complete=getattr(getattr(snapshot, "coverage", None), "scope_complete", None)
            if type(getattr(getattr(snapshot, "coverage", None), "scope_complete", None)) is bool
            else None,
        )
    )
    if phase_end - started_monotonic > collection_limit:
        _fail("FUTURES_SNAPSHOT_COLLECTION_TIMEOUT", tuple(observations))
    if type(snapshot) is not snapshot_type:
        _fail("FUTURES_SNAPSHOT_TYPE_INVALID", tuple(observations))

    now = _utc(_now_utc())
    if now is None:
        _fail("FUTURES_SNAPSHOT_CLOCK_UNAVAILABLE", tuple(observations))
    if (
        getattr(snapshot, "complete", None) is not True
        or getattr(getattr(snapshot, "coverage", None), "complete", None) is not True
        or getattr(getattr(snapshot, "coverage", None), "scope_complete", None) is not True
    ):
        _fail("FUTURES_SNAPSHOT_INCOMPLETE", tuple(observations))
    preliminary_coverages = [
        snapshot.coverage.session,
        snapshot.coverage.catalog,
        snapshot.coverage.quotes,
    ]
    if request.include_depth:
        if snapshot.coverage.depth is None:
            _fail("FUTURES_SNAPSHOT_DEPTH_COVERAGE_MISSING", tuple(observations))
        preliminary_coverages.append(snapshot.coverage.depth)
    preliminary_completions = [_utc(item.completed_at) for item in preliminary_coverages]
    if any(item is None for item in preliminary_completions):
        _fail("FUTURES_SNAPSHOT_TIME_EVIDENCE_MISSING", tuple(observations))
    if any(now < item or (now - item).total_seconds() > age_limit for item in preliminary_completions):
        _fail("FUTURES_SNAPSHOT_TOO_OLD", tuple(observations))
    age_expiry = min(item + timedelta(seconds=age_limit) for item in preliminary_completions)
    lease_expiry = min(now + timedelta(seconds=lease_limit), age_expiry)
    if lease_expiry <= now:
        _fail("FUTURES_SNAPSHOT_LEASE_WINDOW_EXPIRED", tuple(observations))

    phase_start = time.monotonic()
    try:
        lease = snapshot_facade.acquire_lease(
            snapshot,
            purpose=_LEASE_PURPOSE,
            expires_at=lease_expiry,
        )
    except snapshot_error_type as error:
        phase_end = time.monotonic()
        code = getattr(error, "code", None)
        if type(code) is not str or code not in _SDK_ERROR_CODES:
            code = "FUTURES_MARKET_LEASE_UNAVAILABLE"
        observations.append(
            _observation(
                stage="lease_acquire",
                entered=True,
                returned=False,
                start=phase_start,
                end=phase_end,
                code=code,
                complete=True,
                scope_complete=True,
            )
        )
        _fail("FUTURES_SNAPSHOT_" + code, tuple(observations))
    except Exception:
        phase_end = time.monotonic()
        observations.append(
            _observation(
                stage="lease_acquire",
                entered=True,
                returned=False,
                start=phase_start,
                end=phase_end,
                code="FUTURES_MARKET_LEASE_UNAVAILABLE",
                complete=True,
                scope_complete=True,
            )
        )
        _fail("FUTURES_SNAPSHOT_LEASE_UNAVAILABLE", tuple(observations))

    phase_end = time.monotonic()
    if type(lease) is not lease_type:
        _fail("FUTURES_SNAPSHOT_LEASE_TYPE_INVALID", tuple(observations))
    observations.append(
        _observation(
            stage="lease_acquire",
            entered=True,
            returned=True,
            start=phase_start,
            end=phase_end,
            complete=True,
            scope_complete=True,
        )
    )

    _validate_provider_lease(
        snapshot_facade,
        snapshot,
        lease,
        error_type=snapshot_error_type,
        stage="lease_pre_consume",
        observations=observations,
    )
    try:
        selected = _validate_composite(snapshot, request, contract=contract)
    except FuturesSnapshotError as error:
        _fail(error.code, tuple(observations))
    post_validation_now = _utc(_now_utc())
    if post_validation_now is None:
        _fail("FUTURES_SNAPSHOT_CLOCK_UNAVAILABLE", tuple(observations))
    age_expiry = _validate_time_bounds(
        snapshot,
        selected,
        now=post_validation_now,
        max_collection_seconds=collection_limit,
        max_snapshot_age_seconds=age_limit,
    )
    if lease.expires_at > age_expiry:
        _fail("FUTURES_SNAPSHOT_LEASE_EXCEEDS_AGE_LIMIT", tuple(observations))
    if time.monotonic() - started_monotonic > collection_limit:
        _fail("FUTURES_SNAPSHOT_COLLECTION_TIMEOUT", tuple(observations))

    # Bind the exact snapshot to the provider-issued lease before handing both
    # to the selector.  The selector revalidates this pair around consumption.
    receipt = snapshot.receipt
    if (
        lease.receipt_digest != receipt.receipt_digest
        or lease.source_ref != receipt.source_ref
        or lease.generation != receipt.generation
        or lease.snapshot_refs != receipt.complete_snapshot_refs
    ):
        _fail("FUTURES_SNAPSHOT_LEASE_BINDING_INVALID", tuple(observations))
    _validate_provider_lease(
        snapshot_facade,
        snapshot,
        lease,
        error_type=snapshot_error_type,
        stage="lease_post_consume",
        observations=observations,
    )
    if time.monotonic() - started_monotonic > collection_limit:
        _fail("FUTURES_SNAPSHOT_COLLECTION_TIMEOUT", tuple(observations))
    return LeasedFuturesSnapshot(snapshot=snapshot, lease=lease)


__all__ = [
    "FuturesSnapshotError",
    "FuturesSnapshotQueryObservation",
    "LeasedFuturesSnapshot",
    "collect_futures_snapshot",
]
