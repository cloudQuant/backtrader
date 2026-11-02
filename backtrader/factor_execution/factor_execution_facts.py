"""Provider-neutral query evidence joined to public Backtrader snapshots.

This module consumes the bt_api_py query facade. It never reads Store
internals, provider caches, native callbacks, or venue-specific query rows.
The returned values preserve account facts separately from Strategy-owned
Broker facts; provider rows do not imply local ownership or write authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional, Tuple


class FactorExecutionFactsError(RuntimeError):
    """Finite failure at the provider-neutral facts boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class FactorExecutionTarget:
    """One Strategy data object bound to its neutral instrument identity."""

    target_id: str
    data: Any
    instrument: Any

    def __post_init__(self) -> None:
        if type(self.target_id) is not str or not self.target_id or self.target_id != self.target_id.strip():
            raise ValueError("target_id must be exact non-empty text")
        if self.data is None or self.instrument is None:
            raise ValueError("data and instrument must be explicitly bound")


@dataclass(frozen=True)
class FactorLocalPosition:
    """One public Broker position, kept in Backtrader's local quantity domain."""

    target_id: str
    instrument: Any
    quantity: Decimal
    average_price: Optional[Decimal]


@dataclass(frozen=True)
class FactorLocalOrder:
    """One copied, Strategy-owned live Backtrader order."""

    target_id: str
    order_ref: int
    client_order_id: Optional[str]
    instrument: Any
    side: str
    status: str
    quantity: Decimal
    filled_quantity: Decimal
    remaining_quantity: Decimal
    execution_unknown: bool


@dataclass(frozen=True)
class FactorOrderCorrelation:
    """A provider order joined only by the exact echoed client_order_id."""

    target_id: str
    client_order_id: str
    local_order_ref: int
    provider_order_id: str
    provider_status: str


@dataclass(frozen=True)
class FactorExecutionFacts:
    """Immutable query projection and separate local Broker facts.

    Provider values are the SDK's neutral record DTOs. They are not converted
    into BT ownership, quantity, or strategy policy facts. This object carries
    no submit/cancel authorization and has no ready-to-write flag. Call
    validate_current immediately before a decision that consumes the provider
    snapshot.
    """

    account_session_snapshot: Any
    receipt: Any
    lease: Any
    validated_at: datetime
    provider_account: Tuple[Any, ...]
    provider_positions: Tuple[Any, ...]
    provider_open_orders: Tuple[Any, ...]
    provider_instruments: Tuple[Any, ...]
    local_positions: Tuple[FactorLocalPosition, ...]
    local_orders: Tuple[FactorLocalOrder, ...]
    order_correlations: Tuple[FactorOrderCorrelation, ...]
    blockers: Tuple[str, ...]
    account_execution_snapshot: Any = None

    @property
    def session_ref(self) -> Optional[str]:
        """The exact SDK session reference carried by the session snapshot."""

        return getattr(self.account_session_snapshot, "session_ref", None)

    @property
    def source_ref(self) -> Optional[str]:
        return getattr(self.receipt, "source_ref", None)

    @property
    def generation(self) -> Optional[str]:
        return getattr(self.receipt, "generation", None)

    @property
    def receipt_digest(self) -> Optional[str]:
        return getattr(self.receipt, "receipt_digest", None)

    @property
    def fee_receipt(self) -> None:
        """No provider-neutral fee receipt is currently available."""

        return None

    @property
    def fee_status(self) -> str:
        """Fee evidence remains unavailable until a neutral receipt exists."""

        return "UNAVAILABLE"

    @property
    def fee_blockers(self) -> Tuple[str, ...]:
        return ("NEUTRAL_FEE_RECEIPT_UNAVAILABLE",)

    def validate_current(self, *, query_facade: Any, now: datetime) -> bool:
        """Delegate exact snapshot and lease currentness to the SDK owner."""

        try:
            from bt_api_py.account_execution_snapshot import (
                validate_account_execution_snapshot_binding,
            )
        except Exception:
            return False
        return validate_account_execution_snapshot_binding(
            query_facade=query_facade,
            snapshot=self.account_execution_snapshot,
            receipt=self.receipt,
            lease=self.lease,
            account_session_snapshot=self.account_session_snapshot,
            account=self.provider_account,
            positions=self.provider_positions,
            open_orders=self.provider_open_orders,
            instruments=self.provider_instruments,
            now=now,
        )


def collect_local_bt_facts(
    *,
    broker: Any,
    strategy: Any,
    query_facade: Any,
    receipt: Any,
    lease: Any,
    account_session_snapshot: Any,
    now: datetime,
    targets: Tuple[FactorExecutionTarget, ...],
) -> FactorExecutionFacts:
    """Validate one complete neutral receipt and collect public local BT facts.

    The SDK validates and types the four complete provider query families in
    one exact ``AccountExecutionSnapshot``. This function only joins that
    neutral DTO with public Broker/Strategy facts. The same SDK snapshot lease
    is revalidated after reading the Broker. No Store, cache, native API,
    private lock, or provider-specific schema is inspected; fee evidence is
    unavailable until a neutral receipt contract is published.
    """

    try:
        from bt_api_py.account_execution_snapshot import (
            AccountExecutionSnapshotError,
            read_account_execution_snapshot,
            require_account_execution_snapshot_scope,
            target_instrument_coverage_blockers,
            validate_account_execution_snapshot,
        )
        from bt_api_py.factor_order_correlation import correlate_factor_orders
        from bt_api_py.query_contracts import MarketInstrumentKey
    except Exception as error:
        raise FactorExecutionFactsError(
            "ACCOUNT_EXECUTION_SNAPSHOT_UNAVAILABLE"
        ) from error

    if broker is None or strategy is None or getattr(strategy, "broker", None) is not broker:
        raise FactorExecutionFactsError("STRATEGY_BROKER_MISMATCH")
    if (
        type(now) is not datetime
        or now.tzinfo is None
        or now.utcoffset() != timezone.utc.utcoffset(now)
    ):
        raise FactorExecutionFactsError("QUERY_VALIDATION_TIME_INVALID")
    if type(targets) not in (tuple, list) or not targets:
        raise FactorExecutionFactsError("EXECUTION_TARGETS_REQUIRED")
    if any(type(target) is not FactorExecutionTarget for target in targets):
        raise FactorExecutionFactsError("EXECUTION_TARGET_INVALID")

    target_ids = tuple(target.target_id for target in targets)
    data_ids = tuple(id(target.data) for target in targets)
    instrument_keys = tuple(target.instrument for target in targets)
    if (
        len(set(target_ids)) != len(target_ids)
        or len(set(data_ids)) != len(data_ids)
        or any(type(item) is not MarketInstrumentKey for item in instrument_keys)
        or len(set(instrument_keys)) != len(instrument_keys)
    ):
        raise FactorExecutionFactsError("EXECUTION_TARGET_BINDING_AMBIGUOUS")

    try:
        account_snapshot = read_account_execution_snapshot(
            query_facade=query_facade,
            receipt=receipt,
            lease=lease,
            account_session_snapshot=account_session_snapshot,
            now=now,
        )
    except Exception as error:
        code = getattr(error, "code", None)
        raise FactorExecutionFactsError(
            code if _finite_error_code(code) else "ACCOUNT_EXECUTION_SNAPSHOT_UNAVAILABLE"
        ) from error
    try:
        require_account_execution_snapshot_scope(
            account_snapshot,
            receipt=receipt,
            lease=lease,
            account_session_snapshot=account_session_snapshot,
        )
    except AccountExecutionSnapshotError as error:
        raise FactorExecutionFactsError(error.code) from None
    account_rows = account_snapshot.account
    position_rows = account_snapshot.positions
    provider_order_rows = account_snapshot.open_orders
    instrument_rows = account_snapshot.instruments
    target_by_data_id = {id(target.data): target for target in targets}
    blockers = target_instrument_coverage_blockers(
        tuple((target.target_id, target.instrument) for target in targets),
        instrument_rows,
    )

    local_positions = []
    getposition = getattr(broker, "getposition", None)
    if not callable(getposition):
        raise FactorExecutionFactsError("BROKER_POSITION_SNAPSHOT_UNAVAILABLE")
    for target in targets:
        try:
            position = getposition(target.data)
            quantity = _finite_decimal(getattr(position, "size", None))
            average = _optional_decimal(getattr(position, "price", None))
        except Exception as error:
            raise FactorExecutionFactsError("BROKER_POSITION_SNAPSHOT_UNAVAILABLE") from error
        if quantity is None:
            raise FactorExecutionFactsError("BROKER_POSITION_VALUE_INVALID")
        local_positions.append(
            FactorLocalPosition(
                target_id=target.target_id,
                instrument=target.instrument,
                quantity=quantity,
                average_price=average,
            )
        )

    get_orders_open = getattr(broker, "get_orders_open", None)
    if not callable(get_orders_open):
        raise FactorExecutionFactsError("BROKER_ORDER_SNAPSHOT_UNAVAILABLE")
    try:
        open_orders = get_orders_open(safe=True)
    except Exception as error:
        raise FactorExecutionFactsError("BROKER_ORDER_SNAPSHOT_UNAVAILABLE") from error
    if type(open_orders) not in (tuple, list):
        raise FactorExecutionFactsError("BROKER_ORDER_SNAPSHOT_INVALID")

    local_orders = []
    local_by_client_id = {}
    for order in tuple(open_orders):
        if getattr(order, "owner", None) is not strategy:
            continue
        alive = getattr(order, "alive", None)
        if not callable(alive) or alive() is not True:
            continue
        target = target_by_data_id.get(id(getattr(order, "data", None)))
        order_ref = getattr(order, "ref", None)
        if target is None or type(order_ref) is not int or order_ref <= 0:
            raise FactorExecutionFactsError("BROKER_ORDER_IDENTITY_UNBOUND")
        info = getattr(order, "info", None)
        getter = getattr(info, "get", None)
        if not callable(getter):
            raise FactorExecutionFactsError("BROKER_ORDER_INFO_UNAVAILABLE")
        client_order_id = getter("client_order_id")
        if client_order_id is not None and (
            type(client_order_id) is not str
            or not client_order_id
            or client_order_id != client_order_id.strip()
        ):
            raise FactorExecutionFactsError("BROKER_CLIENT_ORDER_ID_INVALID")
        created = getattr(order, "created", None)
        executed = getattr(order, "executed", None)
        quantity = _finite_decimal(getattr(created, "size", None))
        filled = _finite_decimal(getattr(executed, "size", None))
        if quantity is None or filled is None:
            raise FactorExecutionFactsError("BROKER_ORDER_QUANTITY_INVALID")
        quantity = abs(quantity)
        filled = abs(filled)
        if quantity <= 0 or filled < 0 or filled > quantity:
            raise FactorExecutionFactsError("BROKER_ORDER_QUANTITY_INVALID")
        side_getter = getattr(order, "isbuy", None)
        status_getter = getattr(order, "getstatusname", None)
        if not callable(side_getter) or not callable(status_getter):
            raise FactorExecutionFactsError("BROKER_ORDER_STATE_UNAVAILABLE")
        side_value = side_getter()
        if type(side_value) is not bool:
            raise FactorExecutionFactsError("BROKER_ORDER_STATE_INVALID")
        side = "buy" if side_value else "sell"
        status = status_getter()
        if type(status) is not str or not status:
            raise FactorExecutionFactsError("BROKER_ORDER_STATE_INVALID")
        remaining = quantity - filled
        local = FactorLocalOrder(
            target_id=target.target_id,
            order_ref=order_ref,
            client_order_id=client_order_id,
            instrument=target.instrument,
            side=side,
            status=status,
            quantity=quantity,
            filled_quantity=filled,
            remaining_quantity=remaining,
            execution_unknown=getter("execution_unknown") is True,
        )
        local_orders.append(local)
        if client_order_id is not None:
            local_by_client_id.setdefault(client_order_id, []).append(local)
        else:
            blockers.append("local_order_client_order_id_unavailable:" + str(order_ref))
    correlations, correlation_blockers = correlate_factor_orders(
        local_by_client_id,
        provider_order_rows,
        make_correlation=FactorOrderCorrelation,
    )
    blockers.extend(correlation_blockers)

    if not account_rows:
        blockers.append("provider_account_records_empty")

    after = datetime.now(timezone.utc)
    try:
        current = validate_account_execution_snapshot(
            query_facade=query_facade,
            snapshot=account_snapshot,
            now=after,
        )
    except Exception as error:
        code = getattr(error, "code", None)
        raise FactorExecutionFactsError(
            code if _finite_error_code(code) else "ACCOUNT_EXECUTION_SNAPSHOT_UNAVAILABLE"
        ) from error
    if type(current) is not bool or current is not True:
        raise FactorExecutionFactsError("ACCOUNT_EXECUTION_SNAPSHOT_STALE")

    facts = FactorExecutionFacts(
        account_session_snapshot=account_snapshot.account_session_snapshot,
        receipt=account_snapshot.receipt,
        lease=account_snapshot.lease,
        validated_at=after,
        provider_account=account_rows,
        provider_positions=position_rows,
        provider_open_orders=provider_order_rows,
        provider_instruments=instrument_rows,
        local_positions=tuple(local_positions),
        local_orders=tuple(local_orders),
        order_correlations=tuple(correlations),
        blockers=tuple(sorted(set(blockers))),
        account_execution_snapshot=account_snapshot,
    )
    return facts


def _finite_decimal(value: Any) -> Optional[Decimal]:
    if type(value) is bool or value is None:
        return None
    try:
        result = value if type(value) is Decimal else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() else None


def _optional_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    return _finite_decimal(value)


def _finite_error_code(value: Any) -> bool:
    return (
        type(value) is str
        and bool(value)
        and value == value.strip()
        and len(value) <= 96
        and value.isascii()
        and all(character.isalnum() or character in "_.-" for character in value)
    )


__all__ = [
    "FactorExecutionFacts",
    "FactorExecutionFactsError",
    "FactorExecutionTarget",
    "FactorLocalOrder",
    "FactorLocalPosition",
    "FactorOrderCorrelation",
    "collect_local_bt_facts",
]
