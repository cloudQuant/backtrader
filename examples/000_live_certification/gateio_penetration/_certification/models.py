"""Strict v2 contract for managed, live provider certification."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any


class CertificationError(Exception):
    """A configuration or live-evidence failure."""


class UnsupportedCaseError(CertificationError):
    """A required provider capability is absent."""


class Risk(str, Enum):
    READ = "read"
    WRITE = "write"
    DANGEROUS = "dangerous"


class Status(str, Enum):
    PASS = "PASS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class Binding:
    venue: str
    environment_name: str
    environment_kind: str
    account_ref: str


@dataclass(frozen=True)
class Channel:
    instance: str
    channel: str
    role: str  # command_response | independent_event | query | state_snapshot


@dataclass(frozen=True)
class Attestation:
    contract_version: int
    binding: Binding
    provider_attestation_id: str
    provider_session_id: str
    channels: tuple[Channel, ...]
    source: str
    observed_at: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class InstrumentSpec:
    binding: Binding
    symbol: str
    spec_id: str
    # linear/fx_lot use a base-unit multiplier; inverse and
    # linear_quote_multiplier use a quote-denominated value per contract.
    product_type: str  # spot | linear | inverse | fx_lot | linear_quote_multiplier
    quantity_unit: str
    contract_value: Decimal
    contract_value_currency: str
    base_currency: str
    quote_currency: str
    settlement_currency: str
    price_tick: Decimal
    quantity_step: Decimal
    source: str
    source_instance: str
    source_channel: str
    observed_at: str


@dataclass(frozen=True)
class MarketReference:
    binding: Binding
    symbol: str
    price: Decimal
    provider_quote_id: str
    source: str
    source_instance: str
    source_channel: str
    observed_at: str


@dataclass(frozen=True)
class PlannedOperation:
    operation_id: str
    phase: str  # execute | cleanup
    kind: str  # read | submit | cancel
    client_order_id: str | None
    target_order_id: str | None
    symbol: str | None
    side: str | None
    quantity: Decimal
    price: Decimal
    order_type: str | None
    position_id: str | None
    reduce_only: bool
    instrument_spec_id: str | None


@dataclass(frozen=True)
class ActionPlan:
    operations: tuple[PlannedOperation, ...]
    order_count: int
    total_quantity: Decimal
    total_notional: Decimal
    notional_currency: str


@dataclass(frozen=True)
class Action:
    case_id: str
    name: str
    risk: Risk
    binding: Binding
    params: dict[str, Any]
    correlation_id: str
    client_id: str
    attested_session_id: str
    evidence_window_id: str
    plan: ActionPlan


@dataclass(frozen=True)
class OperationEvidence:
    operation_id: str
    phase: str
    kind: str
    accepted: bool
    provider_request_id: str
    provider_order_id: str | None
    client_order_id: str | None
    target_order_id: str | None
    symbol: str | None
    side: str | None
    quantity: Decimal
    price: Decimal
    order_type: str | None
    position_id: str | None
    reduce_only: bool
    instrument_spec_id: str | None
    source_instance: str
    source_channel: str
    occurred_at: str
    observed_at: str


@dataclass(frozen=True)
class Receipt:
    action: str
    correlation_id: str
    client_id: str
    accepted: bool
    binding: Binding
    source: str
    source_instance: str
    source_channel: str
    occurred_at: str
    observed_at: str
    provider_response_id: str
    operations: tuple[OperationEvidence, ...]
    created_order_ids: tuple[str, ...]
    payload: dict[str, Any]


@dataclass(frozen=True)
class Observation:
    kind: str
    correlation_id: str
    client_id: str
    binding: Binding
    source: str
    source_instance: str
    source_channel: str
    occurred_at: str
    observed_at: str
    evidence_window_id: str
    provider_event_id: str
    operation_ids: tuple[str, ...]
    provider_order_ids: tuple[str, ...]
    payload: dict[str, Any]


@dataclass(frozen=True)
class OrderState:
    order_id: str
    client_order_id: str
    symbol: str
    side: str
    price: Decimal
    order_type: str
    position_id: str | None
    reduce_only: bool
    instrument_spec_id: str | None
    status: str
    requested: Decimal
    filled: Decimal
    remaining: Decimal


@dataclass(frozen=True)
class PositionState:
    position_id: str
    symbol: str
    quantity: Decimal  # signed: long > 0, short < 0


@dataclass(frozen=True)
class BalanceState:
    currency: str
    total: Decimal


@dataclass(frozen=True)
class Fill:
    fill_id: str
    order_id: str
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal
    base_delta: Decimal
    quote_delta: Decimal
    settlement_delta: Decimal
    fee_currency: str
    fee: Decimal
    position_id: str | None
    position_delta: Decimal


@dataclass(frozen=True)
class LedgerEntry:
    entry_id: str
    currency: str
    delta: Decimal
    fill_id: str | None
    reason: str


@dataclass(frozen=True)
class StateSnapshot:
    binding: Binding
    correlation_id: str
    snapshot_id: str
    phase: str
    scope: str
    complete: bool
    pagination_complete: bool
    control_state_digest: str
    orders: tuple[OrderState, ...]
    positions: tuple[PositionState, ...]
    balances: tuple[BalanceState, ...]
    fills: tuple[Fill, ...]
    ledger: tuple[LedgerEntry, ...]
    source: str
    source_instance: str
    source_channel: str
    observed_at: str


@dataclass(frozen=True)
class Reconciliation:
    binding: Binding
    correlation_id: str
    client_id: str
    provider_reconcile_id: str
    provider_state: str
    source: str
    observed_at: str
    receipt: Receipt | None


@dataclass(frozen=True)
class CleanupReport:
    binding: Binding
    correlation_id: str
    client_id: str
    provider_reconcile_id: str
    source: str
    observed_at: str
    operations: tuple[OperationEvidence, ...]


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    status: Status
    reason: str
    receipt_count: int = 0
    observation_count: int = 0
