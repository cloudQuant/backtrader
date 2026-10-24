"""Ordinary Broker integration for the registered direct-sim execution route.

The Strategy API remains Backtrader's normal ``buy``, ``sell`` and ``cancel``
methods.  A coordinator binds one exact Broker, Store and SQLite journal, then
requires each live write to consume a declared immutable intent inside a
durable decision scope.  The Store remains responsible for native permission
and synchronous dispatch; this module never arms, queries, or calls the SDK.
"""

from __future__ import annotations

import contextvars
import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any, Optional, Tuple

from .execution_decision_journal import (
    ExecutionDecisionJournal,
    ExecutionDecisionJournalError,
    ExecutionDecisionKey,
    ExecutionIntentKey,
    ExecutionIntentRecord,
)
from .factor_position_book import FactorPositionBook


_ORDER_REF = re.compile(r"^[1-9][0-9]{0,19}$")
_DISPATCH_OPERATIONS = {"SUBMIT": "insert", "CANCEL": "cancel"}


class FactorExecutionError(RuntimeError):
    """A decision or ordinary Broker write failed closed."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ExecutionPositionSnapshot:
    """No-I/O copy of one Broker position projection."""

    data_name: str
    instrument_id: Optional[str]
    exchange_id: Optional[str]
    quantity: Decimal
    average_price: Optional[Decimal]
    long_quantity: Decimal
    short_quantity: Decimal


@dataclass(frozen=True)
class ExecutionOrderSnapshot:
    """No-I/O copy of one live local Broker order and exact remote identity."""

    order_ref: int
    data_name: str
    instrument_id: Optional[str]
    exchange_id: Optional[str]
    side: str
    position_effect: Optional[str]
    status: str
    remaining_quantity: Decimal
    owner_strategy_scope: Optional[str]
    owner_intent_id: Optional[str]
    execution_unknown: bool
    cancel_pending: bool
    external_order_ref: Optional[str]
    order_sys_id: Optional[str]
    front_id: Optional[int]
    session_id: Optional[int]


@dataclass(frozen=True)
class FactorDispatchAttempt:
    """One claimed intent immediately before the ordinary Store call."""

    intent: ExecutionIntentRecord
    operation: str
    instrument_id: str
    exchange_id: str
    order_ref: str
    before_sequence: int


@dataclass(frozen=True)
class ExecutionTradeReconciliationItem:
    """Durable disposition of one exact full-query trade observation."""

    observation_id: str
    status: str
    intent_id: Optional[str] = None
    receipt_id: Optional[str] = None
    execution_id: Optional[str] = None
    blocker_code: Optional[str] = None


@dataclass(frozen=True)
class ExecutionTradeReconciliationPage:
    """Bounded trade-recovery page suitable for refresh and no-I/O proof."""

    items: Tuple[ExecutionTradeReconciliationItem, ...]
    observation_count: int
    offset: int
    next_offset: Optional[int]
    truncated: bool


@dataclass(frozen=True)
class ExecutionTerminalReconciliationItem:
    """Disposition of one complete-query terminal order observation."""

    observation_id: str
    status: str
    intent_id: Optional[str] = None
    reconciliation_id: Optional[str] = None
    blocker_code: Optional[str] = None


@dataclass(frozen=True)
class ExecutionTerminalReconciliationPage:
    """Bounded order-query recovery results for runner/control refresh."""

    items: Tuple[ExecutionTerminalReconciliationItem, ...]
    observation_count: int
    offset: int
    next_offset: Optional[int]
    truncated: bool


def execution_position_snapshot(broker: Any, data: Any) -> ExecutionPositionSnapshot:
    """Read Broker's actual cached position without invoking a Store method."""

    if data is None:
        raise FactorExecutionError("POSITION_DATA_REQUIRED")
    data_name = broker._position_key(data)
    position = broker.positions.get(data_name)
    if position is None:
        quantity = Decimal(0)
        average = None
    else:
        quantity = _decimal_or_zero(getattr(position, "size", None))
        average = _decimal_optional(getattr(position, "price", None))
    long_position = getattr(broker, "long_positions", {}).get(data_name)
    short_position = getattr(broker, "short_positions", {}).get(data_name)
    if long_position is not None or short_position is not None:
        long_quantity = _decimal_or_zero(getattr(long_position, "size", None))
        short_quantity = _decimal_or_zero(getattr(short_position, "size", None))
    else:
        long_quantity = max(quantity, Decimal(0))
        short_quantity = max(-quantity, Decimal(0))
    instrument_id, exchange_id = _contract_route(broker, data_name)
    return ExecutionPositionSnapshot(
        data_name=data_name,
        instrument_id=instrument_id,
        exchange_id=exchange_id,
        quantity=quantity,
        average_price=average,
        long_quantity=long_quantity,
        short_quantity=short_quantity,
    )


def execution_order_snapshot(broker: Any) -> Tuple[ExecutionOrderSnapshot, ...]:
    """Return the bounded-in-process, alive local Broker orders without I/O."""

    result = []
    for order in tuple(getattr(broker, "orders", {}).values()):
        try:
            if not order.alive():
                continue
            info = getattr(order, "info", {})
            get = getattr(info, "get", lambda name, default=None: default)
            data_name = broker._position_key(order.data)
            instrument_id, exchange_id = _contract_route(broker, data_name)
            remote_order_ref = _first_text(
                get("external_order_ref"),
                get("ctp_order_ref"),
                get("order_ref"),
            )
            order_sys_id = _first_text(get("order_sys_id"), get("OrderSysID"))
            position_effect = _first_text(get("factor_position_effect"))
            if position_effect is not None:
                position_effect = position_effect.upper()
                if position_effect not in ("OPEN", "CLOSE"):
                    position_effect = None
            result.append(
                ExecutionOrderSnapshot(
                    order_ref=int(order.ref),
                    data_name=data_name,
                    instrument_id=instrument_id,
                    exchange_id=exchange_id,
                    side="BUY" if order.isbuy() else "SELL",
                    position_effect=position_effect,
                    status=str(order.getstatusname()),
                    remaining_quantity=_decimal_or_zero(broker._order_remaining_qty(order)),
                    owner_strategy_scope=_first_text(get("factor_strategy_scope")),
                    owner_intent_id=_first_text(get("factor_intent_id")),
                    execution_unknown=get("execution_unknown") is True,
                    cancel_pending=bool(
                        get("cancel_requested_remote")
                        or get("cancel_intent_active")
                        or get("managed_execution_cancel_pending")
                    ),
                    external_order_ref=remote_order_ref,
                    order_sys_id=order_sys_id,
                    front_id=_positive_int(get("front_id")),
                    session_id=_positive_int(get("session_id")),
                )
            )
        except (AttributeError, TypeError, ValueError, InvalidOperation) as error:
            # A partial order list would make a clean working-order projection
            # indistinguishable from an empty one. Fail the whole snapshot so
            # the caller cannot authorize from incomplete Broker evidence.
            raise FactorExecutionError("BROKER_ORDER_SNAPSHOT_UNPROJECTABLE") from error
    return tuple(result)


class FactorExecutionCoordinator:
    """Bind one exact Broker, registered Store and durable journal."""

    def __init__(
        self,
        broker: Any,
        journal: ExecutionDecisionJournal,
        *,
        account_scope: str,
        strategy_scope: str,
        logical_run_id: str,
        max_order_intents_per_grid: int,
        max_order_intents_per_run: int,
    ) -> None:
        if broker is None or getattr(broker, "store", None) is None:
            raise FactorExecutionError("BROKER_STORE_REQUIRED")
        if not isinstance(journal, ExecutionDecisionJournal):
            raise FactorExecutionError("EXECUTION_JOURNAL_REQUIRED")
        store = broker.store
        if getattr(store, "registered_sim_route_id", None) != "simnow-registered-v1":
            raise FactorExecutionError("REGISTERED_SIM_ROUTE_REQUIRED")
        if type(getattr(store, "allow_writes", None)) is not bool:
            raise FactorExecutionError("REGISTERED_SIM_WRITE_GATE_UNOBSERVED")
        for name, value in (
            ("account_scope", account_scope),
            ("strategy_scope", strategy_scope),
            ("logical_run_id", logical_run_id),
        ):
            if not _exact_identifier(value):
                raise FactorExecutionError("INVALID_" + name.upper())
        if type(max_order_intents_per_grid) is not int or max_order_intents_per_grid < 0:
            raise FactorExecutionError("INVALID_GRID_ORDER_BUDGET")
        if type(max_order_intents_per_run) is not int or max_order_intents_per_run < 0:
            raise FactorExecutionError("INVALID_RUN_ORDER_BUDGET")
        current = getattr(broker, "factor_execution_coordinator", None)
        if current is not None and current is not self:
            raise FactorExecutionError("BROKER_COORDINATOR_ALREADY_BOUND")
        self.broker = broker
        self.store = store
        self.journal = journal
        self.position_book = FactorPositionBook(journal)
        self.account_scope = account_scope
        self.strategy_scope = strategy_scope
        self.logical_run_id = logical_run_id
        self.max_order_intents_per_grid = max_order_intents_per_grid
        self.max_order_intents_per_run = max_order_intents_per_run
        self._active_scope = contextvars.ContextVar(
            "factor_execution_scope_{}".format(id(self)), default=None
        )
        broker.factor_execution_coordinator = self

    def grid_cursor(self, cohort_id: str):
        return self.journal.grid_cursor(self.account_scope, self.strategy_scope, cohort_id)

    def run_order_count(self) -> int:
        return self.journal.run_order_count(
            self.account_scope, self.strategy_scope, self.logical_run_id
        )

    def decision_capacity_snapshot(self):
        """Expose bounded journal usage and physical DB/WAL diagnostics."""

        return self.journal.decision_capacity_snapshot()

    def execution_intent_snapshot(self, *, limit: int = 128):
        return self.journal.execution_intent_snapshot(limit=limit)

    def reconcile_trade_observations(
        self, facts: Any, *, limit: int = 128, offset: int = 0
    ) -> ExecutionTradeReconciliationPage:
        """Durably consume one bounded page of complete CTP trade-query rows.

        This is a runner/control-refresh operation. It performs no Store or
        provider calls and must not be called from Strategy projection. Each
        row is committed with its callback receipt and position-book update;
        replay is idempotent by both query observation ID and provider trade ID.
        """

        observations = self._validated_trade_observations(facts)
        _validate_page(limit, offset, maximum=512)
        selected = observations[offset : offset + limit]
        items = tuple(
            self._reconcile_one_trade_observation(facts, observation) for observation in selected
        )
        next_offset = offset + len(selected)
        truncated = next_offset < len(observations)
        return ExecutionTradeReconciliationPage(
            items=items,
            observation_count=len(observations),
            offset=offset,
            next_offset=next_offset if truncated else None,
            truncated=truncated,
        )

    def trade_reconciliation_snapshot(
        self, facts: Any, *, limit: int = 128, offset: int = 0
    ) -> ExecutionTradeReconciliationPage:
        """Read bounded proof that exact query rows already reached the book."""

        observations = self._validated_trade_observations(facts)
        _validate_page(limit, offset, maximum=512)
        selected = observations[offset : offset + limit]
        items = tuple(
            self._trade_observation_status(facts, observation) for observation in selected
        )
        next_offset = offset + len(selected)
        truncated = next_offset < len(observations)
        return ExecutionTradeReconciliationPage(
            items=items,
            observation_count=len(observations),
            offset=offset,
            next_offset=next_offset if truncated else None,
            truncated=truncated,
        )

    def reconcile_terminal_order_observations(
        self, facts: Any, *, limit: int = 128, offset: int = 0
    ) -> ExecutionTerminalReconciliationPage:
        """Persist complete orders-query terminal evidence and release order locks.

        This method consumes only already refreshed immutable facts. It does
        no Store/provider I/O. A row releases its pending-order slot only when
        the complete CTP positions query and the Broker's cached position
        agree on signed and side quantities at a snapshot no older than the
        terminal row. A non-flat result releases the order slot while leaving
        the separate factor-position owner intact for a later risk-reducing
        CLOSE.
        """

        observations = self._validated_terminal_order_observations(facts)
        _validate_page(limit, offset, maximum=512)
        selected = observations[offset : offset + limit]
        trade_blockers = self._terminal_trade_projection_blockers(facts, selected)
        items = tuple(
            self._reconcile_one_terminal_order(
                facts,
                observation,
                trade_blocker=trade_blockers.get((observation.instrument, observation.exchange)),
            )
            for observation in selected
        )
        next_offset = offset + len(selected)
        truncated = next_offset < len(observations)
        return ExecutionTerminalReconciliationPage(
            items=items,
            observation_count=len(observations),
            offset=offset,
            next_offset=next_offset if truncated else None,
            truncated=truncated,
        )

    def terminal_order_reconciliation_snapshot(
        self, facts: Any, *, limit: int = 128, offset: int = 0
    ) -> ExecutionTerminalReconciliationPage:
        """Return no-I/O proof that each terminal row freed its order lock."""

        observations = self._validated_terminal_order_observations(facts)
        _validate_page(limit, offset, maximum=512)
        selected = observations[offset : offset + limit]
        items = tuple(self._terminal_order_status(facts, observation) for observation in selected)
        next_offset = offset + len(selected)
        truncated = next_offset < len(observations)
        return ExecutionTerminalReconciliationPage(
            items=items,
            observation_count=len(observations),
            offset=offset,
            next_offset=next_offset if truncated else None,
            truncated=truncated,
        )

    def _validated_trade_observations(self, facts: Any) -> Tuple[Any, ...]:
        from .factor_execution_facts import FactorExecutionFacts

        if not isinstance(facts, FactorExecutionFacts):
            raise FactorExecutionError("EXECUTION_FACTS_REQUIRED")
        if (
            facts.account_scope != self.account_scope
            or facts.strategy_scope != self.strategy_scope
            or facts.snapshot_id is None
            or facts.available_at is None
        ):
            raise FactorExecutionError("TRADE_FACTS_SCOPE_MISMATCH")
        provenance = [item for item in facts.query_provenance if item.family == "trades_result"]
        if len(provenance) != 1:
            raise FactorExecutionError("TRADE_QUERY_PROVENANCE_AMBIGUOUS")
        source = provenance[0]
        if (
            source.request_type != "trades"
            or type(source.request_id) is not int
            or source.request_id <= 0
            or type(source.connection_generation) is not int
            or source.connection_generation <= 0
            or not _exact_identifier(source.account_fingerprint)
            or not _valid_trading_day(source.trading_day)
            or source.source_owned is not True
            or source.query_complete is not True
            or source.scope_complete is not True
            or source.completed_at is None
            or not _time_not_after(source.completed_at, facts.available_at)
            or facts.account is None
            or source.account_fingerprint != facts.account.account_fingerprint
            or source.connection_generation != facts.account.connection_generation
            or source.trading_day != facts.account.trading_day
        ):
            raise FactorExecutionError("TRADE_QUERY_NOT_COMPLETE_AND_CURRENT")
        rows = facts.trade_observations
        if type(rows) is not tuple:
            raise FactorExecutionError("TRADE_OBSERVATIONS_NOT_IMMUTABLE")
        if len(rows) > 512:
            raise FactorExecutionError("TRADE_OBSERVATION_SNAPSHOT_LIMIT")
        for row in rows:
            if (
                row.evidence_kind != "complete_trades_query_observation"
                or row.snapshot_id != facts.snapshot_id
                or row.request_id != source.request_id
                or row.connection_generation != source.connection_generation
                or row.account_fingerprint != source.account_fingerprint
                or row.trading_day != source.trading_day
                or not _same_time(row.available_at, source.completed_at)
                or row.side not in ("BUY", "SELL")
                or row.position_effect not in ("OPEN", "CLOSE")
                or not _exact_identifier(row.order_ref)
                or not _exact_identifier(row.instrument)
                or not _exact_identifier(row.exchange)
                or not _exact_identifier(row.trade_id)
                or not _exact_identifier(row.observation_id)
                or not isinstance(row.volume, Decimal)
                or not row.volume.is_finite()
                or row.volume <= 0
                or not isinstance(row.price, Decimal)
                or not row.price.is_finite()
                or row.price <= 0
                or _aware_utc(row.trade_time_utc) is None
                or _datetime_epoch_ns(row.trade_time_utc)
                != _ctp_trade_time_ns(row.trade_date, row.trade_time)
                or (
                    row.fee is not None
                    and (not isinstance(row.fee, Decimal) or not row.fee.is_finite() or row.fee < 0)
                )
            ):
                raise FactorExecutionError("TRADE_OBSERVATION_IDENTITY_INVALID")
        return rows

    def _validated_terminal_order_observations(self, facts: Any) -> Tuple[Any, ...]:
        from .factor_execution_facts import FactorExecutionFacts

        if not isinstance(facts, FactorExecutionFacts):
            raise FactorExecutionError("EXECUTION_FACTS_REQUIRED")
        if (
            facts.account_scope != self.account_scope
            or facts.strategy_scope != self.strategy_scope
            or facts.snapshot_id is None
            or facts.available_at is None
            or facts.account is None
            or facts.account.snapshot_id != facts.snapshot_id
        ):
            raise FactorExecutionError("TERMINAL_FACTS_SCOPE_MISMATCH")
        orders = _one_query_provenance(facts, "orders_result", "orders")
        positions = _one_query_provenance(facts, "positions_result", "positions")
        if not _same_query_identity(orders, positions) or not _time_not_after(
            orders.completed_at, positions.completed_at
        ):
            raise FactorExecutionError("TERMINAL_POSITION_QUERY_NOT_CURRENT")
        if not _time_not_after(positions.completed_at, facts.available_at):
            raise FactorExecutionError("TERMINAL_FACTS_NOT_CURRENT")
        rows = facts.terminal_orders
        if type(rows) is not tuple or len(rows) > 512:
            raise FactorExecutionError("TERMINAL_OBSERVATIONS_NOT_BOUNDED")
        if orders.row_count is None or type(orders.row_count) is not int or orders.row_count > 512:
            raise FactorExecutionError("TERMINAL_ORDER_QUERY_EXCEEDS_BOUND")
        for row in rows:
            if (
                row.evidence_kind != "complete_orders_query_observation"
                or row.snapshot_id != facts.snapshot_id
                or row.request_id != orders.request_id
                or row.connection_generation != orders.connection_generation
                or row.account_fingerprint != orders.account_fingerprint
                or row.trading_day != orders.trading_day
                or not _same_time(row.available_at, orders.completed_at)
                or row.terminal_state
                not in (
                    "ALL_TRADED",
                    "PART_TRADED_NOT_QUEUEING",
                    "NO_TRADE_NOT_QUEUEING",
                    "CANCELED",
                )
                or not _exact_identifier(row.observation_id)
                or not _exact_identifier(row.order_ref)
                or not _exact_identifier(row.instrument)
                or not _exact_identifier(row.exchange)
                or (row.order_sys_id is not None and not _exact_identifier(row.order_sys_id))
            ):
                raise FactorExecutionError("TERMINAL_ORDER_OBSERVATION_INVALID")
        return rows

    def _reconcile_one_terminal_order(
        self, facts: Any, observation: Any, *, trade_blocker: Optional[str] = None
    ) -> ExecutionTerminalReconciliationItem:
        try:
            intent = self.journal.intent_by_native_order_ref(
                account_scope=self.account_scope,
                strategy_scope=self.strategy_scope,
                trading_day=observation.trading_day,
                instrument=observation.instrument,
                exchange=observation.exchange,
                order_ref=observation.order_ref,
            )
        except Exception as error:
            raise FactorExecutionError("TERMINAL_INTENT_LOOKUP_FAILED") from error
        if intent is None:
            if trade_blocker is not None:
                return ExecutionTerminalReconciliationItem(
                    observation_id=observation.observation_id,
                    status="BLOCKED",
                    blocker_code=trade_blocker,
                )
            return self._external_terminal_disposition(facts, observation)
        identity = intent.original_identity
        if (
            intent.key.action != "SUBMIT"
            or identity.get("instrument_id") != observation.instrument
            or identity.get("exchange_id") != observation.exchange
            or identity.get("order_ref") != observation.order_ref
            or identity.get("trading_day") != observation.trading_day
            or (
                identity.get("order_sys_id") is not None
                and identity.get("order_sys_id") != observation.order_sys_id
            )
        ):
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=intent.intent_id,
                blocker_code="TERMINAL_ORDER_ORIGINAL_IDENTITY_MISMATCH",
            )
        if trade_blocker is not None:
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=intent.intent_id,
                blocker_code=trade_blocker,
            )
        # A provider order can remain visible as terminal in many later full
        # account snapshots.  Its first terminal reconciliation is immutable,
        # while the account position may legitimately change after a later
        # CLOSE.  Reusing the original, identity-bound resolution here avoids
        # trying to rewrite that order's flat/non-flat checkpoint using a
        # newer position snapshot.
        prior_resolution = self.journal.instrument_resolution(intent.intent_id)
        if prior_resolution is not None:
            expected_state = _terminal_state(observation.terminal_state)
            try:
                prior_reconciliation = self.journal.reconciliation(
                    prior_resolution.reconciliation_id
                )
            except Exception as error:
                raise FactorExecutionError("TERMINAL_RECONCILIATION_STATUS_UNAVAILABLE") from error
            prior_identity = (
                prior_reconciliation.provider_identity if prior_reconciliation is not None else {}
            )
            prior_broker = _decimal_optional(prior_identity.get("broker_quantity"))
            prior_long = _decimal_optional(prior_identity.get("ctp_long_quantity"))
            prior_short = _decimal_optional(prior_identity.get("ctp_short_quantity"))
            prior_observation_id = _exact_identifier(prior_identity.get("observation_id"))
            prior_snapshot_id = _exact_identifier(prior_identity.get("snapshot_id"))
            prior_position_snapshot_id = _exact_identifier(
                prior_identity.get("position_snapshot_id")
            )
            prior_position_flat = prior_broker == 0 if prior_broker is not None else None
            prior_quantities_match = bool(
                prior_broker is not None
                and prior_long is not None
                and prior_short is not None
                and prior_long >= 0
                and prior_short >= 0
                and not (prior_long > 0 and prior_short > 0)
                and prior_broker == prior_long - prior_short
                and prior_reconciliation is not None
                and prior_reconciliation.position_flat is prior_position_flat
                and prior_resolution.position_flat is prior_position_flat
                and prior_reconciliation.position_snapshot_id == prior_position_snapshot_id
                and prior_resolution.position_snapshot_id == prior_position_snapshot_id
                and prior_snapshot_id == prior_position_snapshot_id
                and prior_reconciliation.reconciliation_id == prior_resolution.reconciliation_id
                and prior_reconciliation.outcome_code == "complete_orders_query_terminal"
                and prior_identity.get("evidence_kind") == "complete_orders_query_observation"
                and prior_observation_id == prior_reconciliation.query_id
                and prior_observation_id == prior_reconciliation.terminal_event_id
            )
            current_positions = [
                position
                for position in facts.positions
                if position.instrument == observation.instrument
                and position.exchange == observation.exchange
            ]
            current_position = current_positions[0] if len(current_positions) == 1 else None
            current_broker_quantity = (
                getattr(current_position, "broker_quantity", None)
                if current_position is not None
                else None
            )
            current_attributed_quantity = (
                getattr(current_position, "attributed_signed_quantity", None)
                if current_position is not None
                else None
            )
            current_position_matches_projection = bool(
                current_position is not None
                and _terminal_position_consistent(current_position, facts)
                and isinstance(current_broker_quantity, Decimal)
                and (
                    (
                        isinstance(current_attributed_quantity, Decimal)
                        and current_attributed_quantity.is_finite()
                        and current_attributed_quantity == current_broker_quantity
                        and (
                            current_broker_quantity == 0
                            or (
                                current_position.owner_strategy_scope == self.strategy_scope
                                and _exact_identifier(current_position.owner_intent_id)
                            )
                        )
                    )
                    or (current_broker_quantity == 0 and current_attributed_quantity is None)
                )
            )
            prior_identity_matches = (
                prior_resolution.account_scope == self.account_scope
                and prior_resolution.instrument == observation.instrument
                and prior_resolution.terminal_state == expected_state
                and prior_reconciliation is not None
                and prior_reconciliation.intent_id == intent.intent_id
                and prior_reconciliation.state == "KNOWN"
                and prior_reconciliation.terminal_state == expected_state
                and prior_reconciliation.terminal_event_id == prior_reconciliation.query_id
                and prior_identity.get("account_fingerprint") == observation.account_fingerprint
                and prior_identity.get("trading_day") == observation.trading_day
                and prior_identity.get("order_ref") == observation.order_ref
                and prior_identity.get("instrument") == observation.instrument
                and prior_identity.get("exchange") == observation.exchange
                and prior_identity.get("terminal_state") == observation.terminal_state
                and prior_identity.get("order_sys_id") == observation.order_sys_id
            )
            if not prior_identity_matches:
                blocker_code = "TERMINAL_RESOLUTION_CONFLICT"
            elif not prior_quantities_match:
                blocker_code = "TERMINAL_PRIOR_POSITION_BINDING_INVALID"
            elif not current_position_matches_projection:
                blocker_code = "TERMINAL_CURRENT_POSITION_PROJECTION_MISMATCH"
            else:
                return ExecutionTerminalReconciliationItem(
                    observation_id=observation.observation_id,
                    status="RESOLVED",
                    intent_id=intent.intent_id,
                    reconciliation_id=prior_resolution.reconciliation_id,
                )
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=intent.intent_id,
                reconciliation_id=prior_resolution.reconciliation_id,
                blocker_code=blocker_code,
            )
        matches = [
            position
            for position in facts.positions
            if position.instrument == observation.instrument
            and position.exchange == observation.exchange
        ]
        if len(matches) != 1:
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=intent.intent_id,
                blocker_code="TERMINAL_POSITION_ROUTE_AMBIGUOUS",
            )
        position = matches[0]
        broker_quantity = getattr(position, "broker_quantity", None)
        long_quantity = position.long_quantity
        short_quantity = position.short_quantity
        if (
            position.snapshot_id != facts.snapshot_id
            or not _same_time(position.available_at, facts.available_at)
            or not isinstance(broker_quantity, Decimal)
            or not broker_quantity.is_finite()
            or not isinstance(long_quantity, Decimal)
            or not long_quantity.is_finite()
            or long_quantity < 0
            or not isinstance(short_quantity, Decimal)
            or not short_quantity.is_finite()
            or short_quantity < 0
            or (long_quantity > 0 and short_quantity > 0)
            or broker_quantity != long_quantity - short_quantity
        ):
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=intent.intent_id,
                blocker_code="TERMINAL_POSITION_RECONCILIATION_MISMATCH",
            )
        if any(
            order.instrument == observation.instrument and order.exchange == observation.exchange
            for order in facts.working_orders
        ):
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=intent.intent_id,
                blocker_code="TERMINAL_ROUTE_STILL_HAS_WORKING_ORDER",
            )
        terminal_state = {
            "ALL_TRADED": "FILLED",
            "PART_TRADED_NOT_QUEUEING": "FILLED",
            "NO_TRADE_NOT_QUEUEING": "REJECTED",
            "CANCELED": "CANCELLED",
        }[observation.terminal_state]
        reconciliation_id = _terminal_reconciliation_id(
            intent.intent_id,
            observation.observation_id,
            facts.snapshot_id,
            broker_quantity,
            long_quantity,
            short_quantity,
        )
        provider_identity = {
            "evidence_kind": observation.evidence_kind,
            "observation_id": observation.observation_id,
            "snapshot_id": facts.snapshot_id,
            "request_id": observation.request_id,
            "connection_generation": observation.connection_generation,
            "account_fingerprint": observation.account_fingerprint,
            "trading_day": observation.trading_day,
            "terminal_status": observation.terminal_status,
            "terminal_state": observation.terminal_state,
            "order_ref": observation.order_ref,
            "order_sys_id": observation.order_sys_id,
            "instrument": observation.instrument,
            "exchange": observation.exchange,
            "broker_quantity": broker_quantity,
            "ctp_long_quantity": long_quantity,
            "ctp_short_quantity": short_quantity,
            "position_snapshot_id": position.snapshot_id,
            "position_available_at": _utc_text(position.available_at),
        }
        try:
            self.journal.record_reconciliation(
                intent.intent_id,
                reconciliation_id=reconciliation_id,
                query_id=observation.observation_id,
                state="KNOWN",
                provider_identity=provider_identity,
                outcome_code="complete_orders_query_terminal",
                terminal_state=terminal_state,
                terminal_event_id=observation.observation_id,
                position_snapshot_id=position.snapshot_id,
                position_flat=broker_quantity == 0,
            )
            self.journal.release_instrument_owner(
                intent.intent_id, reconciliation_id=reconciliation_id
            )
        except Exception as error:
            code = getattr(error, "code", None)
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=intent.intent_id,
                reconciliation_id=reconciliation_id,
                blocker_code=code if _exact_identifier(code) else "TERMINAL_RELEASE_NOT_DURABLE",
            )
        return ExecutionTerminalReconciliationItem(
            observation_id=observation.observation_id,
            status="RESOLVED",
            intent_id=intent.intent_id,
            reconciliation_id=reconciliation_id,
        )

    def _terminal_trade_projection_blockers(
        self, facts: Any, observations: Tuple[Any, ...]
    ) -> Mapping[Tuple[str, str], str]:
        """Do not release an order while this full query has unbound route fills."""

        routes = {(row.instrument, row.exchange) for row in observations}
        if not routes:
            return {}
        try:
            trade_observations = self._validated_trade_observations(facts)
            blocked_routes = set()
            for trade in trade_observations:
                route = (trade.instrument, trade.exchange)
                if route not in routes:
                    continue
                status = self._trade_observation_status(facts, trade)
                if status.status not in ("APPLIED", "DUPLICATE", "EXTERNAL_FLAT"):
                    blocked_routes.add(route)
        except FactorExecutionError:
            blocked_routes = routes
        return dict.fromkeys(blocked_routes, "TERMINAL_TRADE_PROJECTION_NOT_RECONCILED")

    def _terminal_order_status(
        self, facts: Any, observation: Any
    ) -> ExecutionTerminalReconciliationItem:
        try:
            intent = self.journal.intent_by_native_order_ref(
                account_scope=self.account_scope,
                strategy_scope=self.strategy_scope,
                trading_day=observation.trading_day,
                instrument=observation.instrument,
                exchange=observation.exchange,
                order_ref=observation.order_ref,
            )
        except Exception as error:
            raise FactorExecutionError("TERMINAL_INTENT_LOOKUP_FAILED") from error
        if intent is None:
            return self._external_terminal_disposition(facts, observation)
        expected_state = _terminal_state(observation.terminal_state)
        resolution = self.journal.instrument_resolution(intent.intent_id)
        if resolution is not None:
            if (
                resolution.account_scope != self.account_scope
                or resolution.instrument != observation.instrument
                or resolution.terminal_state != expected_state
            ):
                return ExecutionTerminalReconciliationItem(
                    observation_id=observation.observation_id,
                    status="BLOCKED",
                    intent_id=intent.intent_id,
                    reconciliation_id=resolution.reconciliation_id,
                    blocker_code="TERMINAL_RESOLUTION_CONFLICT",
                )
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="RESOLVED",
                intent_id=intent.intent_id,
                reconciliation_id=resolution.reconciliation_id,
            )

        matches = [
            position
            for position in facts.positions
            if position.instrument == observation.instrument
            and position.exchange == observation.exchange
        ]
        if len(matches) != 1:
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=intent.intent_id,
                blocker_code="TERMINAL_POSITION_ROUTE_AMBIGUOUS",
            )
        position = matches[0]
        broker_quantity = getattr(position, "broker_quantity", None)
        long_quantity = position.long_quantity
        short_quantity = position.short_quantity
        if not _terminal_position_consistent(position, facts):
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=intent.intent_id,
                blocker_code="TERMINAL_POSITION_RECONCILIATION_MISMATCH",
            )
        reconciliation_id = _terminal_reconciliation_id(
            intent.intent_id,
            observation.observation_id,
            facts.snapshot_id,
            broker_quantity,
            long_quantity,
            short_quantity,
        )
        try:
            reconciliation = self.journal.reconciliation(reconciliation_id)
        except Exception as error:
            raise FactorExecutionError("TERMINAL_RECONCILIATION_STATUS_UNAVAILABLE") from error
        if reconciliation is None:
            status = "UNRECONCILED"
            blocker = "TERMINAL_RECONCILIATION_NOT_RECORDED"
        elif (
            reconciliation.state == "KNOWN"
            and reconciliation.query_id == observation.observation_id
            and reconciliation.terminal_state == expected_state
            and reconciliation.terminal_event_id == observation.observation_id
            and reconciliation.position_snapshot_id == facts.snapshot_id
            and reconciliation.position_flat is (broker_quantity == 0)
        ):
            status = "UNRECONCILED"
            blocker = "TERMINAL_OWNER_RELEASE_NOT_RECORDED"
        else:
            status = "BLOCKED"
            blocker = "TERMINAL_RECONCILIATION_CONFLICT"
        return ExecutionTerminalReconciliationItem(
            observation_id=observation.observation_id,
            status=status,
            intent_id=intent.intent_id,
            reconciliation_id=reconciliation_id if reconciliation is not None else None,
            blocker_code=blocker,
        )

    def _external_terminal_disposition(
        self, facts: Any, observation: Any
    ) -> ExecutionTerminalReconciliationItem:
        """Keep unrelated terminal history out of ownership without hiding risk."""

        if self._current_route_proves_flat(
            facts, instrument=observation.instrument, exchange=observation.exchange
        ):
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="EXTERNAL_TERMINAL_FLAT",
            )
        return ExecutionTerminalReconciliationItem(
            observation_id=observation.observation_id,
            status="BLOCKED",
            blocker_code="UNMATCHED_TERMINAL_POSITION_OR_ORDER_UNRESOLVED",
        )

    def _current_route_proves_flat(self, facts: Any, *, instrument: str, exchange: str) -> bool:
        """Require post-observation current Broker/CTP flatness and no working order."""

        try:
            positions = _one_query_provenance(facts, "positions_result", "positions")
            trades = next(
                (item for item in facts.query_provenance if item.family == "trades_result"),
                None,
            )
            if trades is not None and (
                not _same_query_identity(trades, positions)
                or not _time_not_after(trades.completed_at, positions.completed_at)
            ):
                return False
        except (FactorExecutionError, AttributeError, TypeError):
            return False
        matches = [
            position
            for position in getattr(facts, "positions", ())
            if position.instrument == instrument and position.exchange == exchange
        ]
        if len(matches) != 1 or not _terminal_position_consistent(matches[0], facts):
            return False
        position = matches[0]
        if (
            position.broker_quantity != 0
            or position.long_quantity != 0
            or position.short_quantity != 0
        ):
            return False
        return not any(
            order.instrument == instrument and order.exchange == exchange
            for order in getattr(facts, "working_orders", ())
        )

    def _reconcile_one_trade_observation(
        self, facts: Any, observation: Any
    ) -> ExecutionTradeReconciliationItem:
        intent = self._intent_for_trade_observation(facts, observation)
        if intent is None:
            if self._current_route_proves_flat(
                facts, instrument=observation.instrument, exchange=observation.exchange
            ):
                return ExecutionTradeReconciliationItem(
                    observation_id=observation.observation_id,
                    status="EXTERNAL_FLAT",
                )
            return ExecutionTradeReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                blocker_code="UNMATCHED_TRADE_POSITION_OR_ORDER_UNRESOLVED",
            )
        if (
            intent.key.action != "SUBMIT"
            or intent.key.side != observation.side
            or intent.key.position_effect != observation.position_effect
        ):
            return ExecutionTradeReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=intent.intent_id,
                blocker_code="TRADE_INTENT_ECONOMICS_MISMATCH",
            )
        payload = _trade_observation_evidence(facts, observation)
        callback_id = _trade_observation_callback_id(payload["execution_id"])
        try:
            from .factor_position_book import apply_factor_execution_fill

            native_receipt = self.journal.callback_receipt(
                intent.intent_id,
                _native_trade_callback_id(
                    observation.trade_id,
                    observation.order_ref,
                    observation.instrument,
                    observation.exchange,
                ),
            )
            if native_receipt is not None and not _unusable_trade_callback_matches_observation(
                observation, native_receipt.evidence_payload
            ):
                return ExecutionTradeReconciliationItem(
                    observation_id=observation.observation_id,
                    status="BLOCKED",
                    intent_id=intent.intent_id,
                    receipt_id=native_receipt.receipt_id,
                    execution_id=payload["execution_id"],
                    blocker_code="NATIVE_TRADE_CALLBACK_QUERY_CONFLICT",
                )

            prior = self.journal.callback_receipt(intent.intent_id, callback_id)
            if prior is not None:
                if not _trade_observation_matches_evidence(observation, prior.evidence_payload):
                    return ExecutionTradeReconciliationItem(
                        observation_id=observation.observation_id,
                        status="BLOCKED",
                        intent_id=intent.intent_id,
                        receipt_id=prior.receipt_id,
                        execution_id=payload["execution_id"],
                        blocker_code="TRADE_OBSERVATION_CONFLICT",
                    )
                payload = prior.evidence_payload

            receipt, projection = self.journal.record_callback_projected(
                intent.intent_id,
                callback_id,
                payload,
                project=lambda cursor, receipt_id: apply_factor_execution_fill(
                    cursor, receipt_id=receipt_id
                ),
            )
            status = getattr(projection, "status", "BLOCKED")
            blocker = getattr(projection, "blocker_code", None)
            if status in ("APPLIED", "DUPLICATE"):
                if not receipt.acknowledged:
                    self.journal.acknowledge_callback(receipt.receipt_id)
            return ExecutionTradeReconciliationItem(
                observation_id=observation.observation_id,
                status=status,
                intent_id=intent.intent_id,
                receipt_id=receipt.receipt_id,
                execution_id=payload["execution_id"],
                blocker_code=blocker,
            )
        except Exception as error:
            raise FactorExecutionError("TRADE_RECONCILIATION_NOT_DURABLE") from error

    def _trade_observation_status(
        self, facts: Any, observation: Any
    ) -> ExecutionTradeReconciliationItem:
        intent = self._intent_for_trade_observation(facts, observation)
        if intent is None:
            if self._current_route_proves_flat(
                facts, instrument=observation.instrument, exchange=observation.exchange
            ):
                return ExecutionTradeReconciliationItem(
                    observation_id=observation.observation_id,
                    status="EXTERNAL_FLAT",
                )
            return ExecutionTradeReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                blocker_code="UNMATCHED_TRADE_POSITION_OR_ORDER_UNRESOLVED",
            )
        if (
            intent.key.action != "SUBMIT"
            or intent.key.side != observation.side
            or intent.key.position_effect != observation.position_effect
        ):
            return ExecutionTradeReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=intent.intent_id,
                blocker_code="TRADE_INTENT_ECONOMICS_MISMATCH",
            )
        payload = _trade_observation_evidence(facts, observation)
        callback_id = _trade_observation_callback_id(payload["execution_id"])
        try:
            native_receipt = self.journal.callback_receipt(
                intent.intent_id,
                _native_trade_callback_id(
                    observation.trade_id,
                    observation.order_ref,
                    observation.instrument,
                    observation.exchange,
                ),
            )
            if native_receipt is not None and not _unusable_trade_callback_matches_observation(
                observation, native_receipt.evidence_payload
            ):
                return ExecutionTradeReconciliationItem(
                    observation_id=observation.observation_id,
                    status="BLOCKED",
                    intent_id=intent.intent_id,
                    receipt_id=native_receipt.receipt_id,
                    execution_id=payload["execution_id"],
                    blocker_code="NATIVE_TRADE_CALLBACK_QUERY_CONFLICT",
                )
            prior = self.journal.callback_receipt(intent.intent_id, callback_id)
            if prior is None:
                return ExecutionTradeReconciliationItem(
                    observation_id=observation.observation_id,
                    status="UNRECONCILED",
                    intent_id=intent.intent_id,
                    execution_id=payload["execution_id"],
                    blocker_code="TRADE_RECEIPT_NOT_FOUND",
                )
            if not _trade_observation_matches_evidence(observation, prior.evidence_payload):
                return ExecutionTradeReconciliationItem(
                    observation_id=observation.observation_id,
                    status="BLOCKED",
                    intent_id=intent.intent_id,
                    receipt_id=prior.receipt_id,
                    execution_id=payload["execution_id"],
                    blocker_code="TRADE_OBSERVATION_CONFLICT",
                )
            state = self.journal.callback_projection_status(
                intent.intent_id, callback_id, prior.evidence_payload
            )
        except Exception as error:
            raise FactorExecutionError("TRADE_RECONCILIATION_STATUS_UNAVAILABLE") from error
        return ExecutionTradeReconciliationItem(
            observation_id=observation.observation_id,
            status=state.status,
            intent_id=intent.intent_id,
            receipt_id=state.receipt_id,
            execution_id=payload["execution_id"],
            blocker_code=state.blocker_code,
        )

    def _intent_for_trade_observation(self, facts: Any, observation: Any):
        try:
            intent = self.journal.intent_by_native_order_ref(
                account_scope=self.account_scope,
                strategy_scope=self.strategy_scope,
                trading_day=observation.trading_day,
                instrument=observation.instrument,
                exchange=observation.exchange,
                order_ref=observation.order_ref,
            )
        except Exception as error:
            raise FactorExecutionError("TRADE_INTENT_LOOKUP_FAILED") from error
        return intent

    def record_trade_callback(self, update: Mapping[str, Any], order: Any):
        """Persist and project one exact provider trade callback before Broker apply.

        A usable TradeDate binds the callback to the stable provider execution
        identity. Without one, retain an unprojected native receipt for later
        complete-query matching; TradingDay is never substituted for TradeDate.
        Fee and timestamp remain explicitly unknown when the native Trade row
        did not supply them; no estimated fee or process-time fallback is used.
        """

        if not isinstance(update, Mapping) or order is None:
            raise FactorExecutionError("TRADE_CALLBACK_INVALID")
        info = getattr(order, "info", {})
        get = getattr(info, "get", lambda name, default=None: default)
        intent_id = _exact_identifier(get("factor_intent_id"))
        if intent_id is None or get("factor_strategy_scope") != self.strategy_scope:
            raise FactorExecutionError("FACTOR_ORDER_INTENT_BINDING_REQUIRED")
        details = update.get("details")
        details = details if isinstance(details, Mapping) else {}
        trade_id = _first_text(
            update.get("trade_id"), update.get("TradeID"), details.get("TradeID")
        )
        order_ref = _first_text(
            update.get("order_ref"), update.get("OrderRef"), details.get("OrderRef")
        )
        expected_order_ref = _first_text(
            get("external_order_ref"), get("ctp_order_ref"), get("order_ref")
        )
        instrument_id = _first_text(
            update.get("instrument"), update.get("instrument_id"), details.get("InstrumentID")
        )
        exchange_id = _first_text(
            update.get("exchange_id"), update.get("ExchangeID"), details.get("ExchangeID")
        )
        if (
            trade_id is None
            or order_ref is None
            or expected_order_ref is None
            or order_ref != expected_order_ref
            or instrument_id != _exact_identifier(get("instrument_id"))
            or exchange_id != _exact_identifier(get("exchange_id"))
        ):
            raise FactorExecutionError("TRADE_CALLBACK_IDENTITY_MISMATCH")
        quantity = details.get("Volume", details.get("volume"))
        if quantity is None:
            quantity = update.get("size")
            if isinstance(quantity, (int, float, Decimal)) and not isinstance(quantity, bool):
                quantity = abs(quantity)
        price = update.get("price", details.get("Price"))
        fee = _first_value(
            update.get("fee"),
            details.get("Commission"),
            details.get("Fee"),
            update.get("commission"),
        )
        trade_date = _first_text(details.get("TradeDate"))
        trade_time = _first_text(details.get("TradeTime"))
        if _valid_trading_day(trade_date) is None:
            trading_day = _first_text(
                details.get("TradingDay"), update.get("trading_day"), update.get("TradingDay")
            )
            callback_id = _native_trade_callback_id(trade_id, order_ref, instrument_id, exchange_id)
            raw_evidence = {
                "event_type": "unresolved_trade_callback",
                "evidence_kind": "native_trade_callback_unusable_trade_date",
                "provider_trade_id": trade_id,
                "order_ref": order_ref,
                "order_sys_id": _first_text(details.get("OrderSysID")),
                "instrument_id": instrument_id,
                "exchange": exchange_id,
                "side": "BUY" if order.isbuy() else "SELL",
                "position_effect": str(get("factor_position_effect") or "").upper(),
                "direction": _first_text(details.get("Direction")),
                "offset_flag": _first_text(details.get("OffsetFlag")),
                "quantity": quantity,
                "price": price,
                "fee": fee,
                "trade_date": trade_date,
                "trade_time": trade_time,
                "trading_day": trading_day,
            }
            try:
                receipt = self.journal.record_callback(intent_id, callback_id, raw_evidence)
            except Exception as error:
                raise FactorExecutionError("TRADE_CALLBACK_JOURNAL_FAILED") from error
            # The ordinary Broker still applies this incremental callback and
            # owns its delivery acknowledgement. Only position-book projection
            # waits for the complete query's authoritative TradeDate.
            return receipt, None, receipt.acknowledged

        filled_at_ns = _ctp_trade_time_ns(trade_date, trade_time)
        execution_id = "ctp:{}:{}".format(trade_date, trade_id)
        callback_id = "ctp-trade:" + hashlib.sha256(execution_id.encode("utf-8")).hexdigest()
        evidence = {
            "event_type": "execution_fill",
            "execution_id": execution_id,
            "provider_trade_id": trade_id,
            "order_ref": order_ref,
            "instrument_id": instrument_id,
            "exchange": exchange_id,
            "quantity": quantity,
            "price": price,
            "fee": fee,
            "filled_at_ns": filled_at_ns,
            "time_source": "CTP_TradeDate_TradeTime_UTC_PLUS_08"
            if filled_at_ns is not None
            else None,
            "evidence_kind": "native_trade_callback",
        }
        try:
            from .factor_position_book import apply_factor_execution_fill

            receipt, projection = self.journal.record_callback_projected(
                intent_id,
                callback_id,
                evidence,
                project=lambda cursor, receipt_id: apply_factor_execution_fill(
                    cursor, receipt_id=receipt_id
                ),
            )
        except Exception as error:
            raise FactorExecutionError("TRADE_CALLBACK_JOURNAL_FAILED") from error
        if receipt.acknowledged:
            return receipt, projection, True
        if getattr(projection, "status", None) not in ("APPLIED", "DUPLICATE"):
            order.addinfo(
                execution_unknown=True,
                ledger_mismatch=True,
                factor_position_projection_status=getattr(projection, "status", "UNKNOWN"),
                factor_position_projection_error=getattr(
                    projection, "blocker_code", "POSITION_PROJECTION_UNAVAILABLE"
                ),
            )
            raise FactorExecutionError("TRADE_CALLBACK_POSITION_PROJECTION_BLOCKED")
        return receipt, projection, False

    def decision_scope(
        self,
        *,
        owner: Any,
        key: ExecutionDecisionKey,
        economic_payload: Mapping[str, Any],
        intent_keys: Tuple[ExecutionIntentKey, ...],
        batch: Any,
        snapshot: Any,
        execution_facts: Any,
        inputs_complete: bool,
        expected_run_order_intents_used: int,
        remaining_exit_intent_reserve: int,
    ) -> "FactorExecutionDecisionScope":
        return FactorExecutionDecisionScope(
            self,
            owner=owner,
            key=key,
            economic_payload=economic_payload,
            intent_keys=intent_keys,
            batch=batch,
            snapshot=snapshot,
            execution_facts=execution_facts,
            inputs_complete=inputs_complete,
            expected_run_order_intents_used=expected_run_order_intents_used,
            remaining_exit_intent_reserve=remaining_exit_intent_reserve,
            risk_only=False,
        )

    def risk_decision_scope(
        self,
        *,
        owner: Any,
        key: ExecutionDecisionKey,
        economic_payload: Mapping[str, Any],
        intent_keys: Tuple[ExecutionIntentKey, ...],
        batch: Any = None,
        execution_facts: Any,
        inputs_complete: bool,
        expected_run_order_intents_used: int,
        remaining_exit_intent_reserve: int,
    ) -> "FactorExecutionDecisionScope":
        return FactorExecutionDecisionScope(
            self,
            owner=owner,
            key=key,
            economic_payload=economic_payload,
            intent_keys=intent_keys,
            batch=batch,
            snapshot=None,
            execution_facts=execution_facts,
            inputs_complete=inputs_complete,
            expected_run_order_intents_used=expected_run_order_intents_used,
            remaining_exit_intent_reserve=remaining_exit_intent_reserve,
            risk_only=True,
        )

    def active_scope(self, owner: Any) -> "FactorExecutionDecisionScope":
        scope = self._active_scope.get()
        if scope is None or scope.owner is not owner or not scope._entered:
            raise FactorExecutionError("ORDER_OUTSIDE_DURABLE_DECISION_SCOPE")
        if owner.broker is not self.broker:
            raise FactorExecutionError("STRATEGY_BROKER_MISMATCH")
        return scope

    def active_scope_for_order(self, order: Any) -> "FactorExecutionDecisionScope":
        """Resolve the current Strategy scope from an ordinary Order owner."""

        owner = getattr(order, "owner", None)
        scope = self.active_scope(owner)
        if getattr(order, "data", None) not in tuple(getattr(owner, "datas", ())):
            raise FactorExecutionError("ORDER_DATA_OUTSIDE_STRATEGY_SCOPE")
        return scope

    def _route_eligibility(self, instrument_id: str, exchange_id: str, facts: Any) -> None:
        try:
            route = self.store.registered_sim_route_eligibility(instrument_id, exchange_id)
        except Exception as error:
            raise FactorExecutionError("REGISTERED_SIM_ROUTE_UNOBSERVED") from error
        positive = (
            getattr(route, "allow_writes", None) is True
            and getattr(route, "frozen", None) is False
            and getattr(route, "sdk_frozen", None) is False
            and getattr(route, "unknown_order_count", None) == 0
            and getattr(route, "unknown_order_ids", None) == ()
            and getattr(route, "dispatching_order_ids", None) == ()
            and getattr(route, "capability_observed", None) is True
            and getattr(route, "sdk_capability_managed", None) is True
            and getattr(route, "sdk_capability_armed", None) is True
            and getattr(route, "capability_matches_route", None) is True
            and getattr(route, "instrument_query_complete", None) is True
            and getattr(route, "instrument_eligible", None) is True
            and getattr(route, "instrument_id", None) == instrument_id
            and getattr(route, "exchange_id", None) == exchange_id
            and getattr(route, "native_admission_required", None) is True
        )
        if not positive:
            raise FactorExecutionError("REGISTERED_SIM_ROUTE_NOT_READY")
        matches = [
            item
            for item in facts.route_eligibilities
            if item.instrument == instrument_id
            and item.exchange == exchange_id
            and item.eligible is True
            and item.allow_writes is True
            and item.frozen is False
            and item.capability_observed is True
            and item.capability_managed is True
            and item.capability_armed is True
            and item.capability_matches_route is True
        ]
        if len(matches) != 1:
            raise FactorExecutionError("EXECUTION_FACT_ROUTE_NOT_READY")


class FactorExecutionDecisionScope:
    """Context manager binding one immutable decision to ordinary order calls."""

    def __init__(
        self,
        coordinator: FactorExecutionCoordinator,
        *,
        owner: Any,
        key: ExecutionDecisionKey,
        economic_payload: Mapping[str, Any],
        intent_keys: Tuple[ExecutionIntentKey, ...],
        batch: Any,
        snapshot: Any,
        execution_facts: Any,
        inputs_complete: bool,
        expected_run_order_intents_used: int,
        remaining_exit_intent_reserve: int,
        risk_only: bool,
    ) -> None:
        self.coordinator = coordinator
        self.owner = owner
        self.key = key
        self.economic_payload = economic_payload
        self.intent_keys = tuple(intent_keys)
        self.batch = batch
        self.snapshot = snapshot
        self.execution_facts = execution_facts
        self.inputs_complete = inputs_complete
        self.expected_run_order_intents_used = expected_run_order_intents_used
        self.remaining_exit_intent_reserve = remaining_exit_intent_reserve
        self.risk_only = risk_only
        self.decision_id: Optional[str] = None
        self.cursor = None
        self.is_new_grid = False
        self.dispatch_allowed = False
        self.run_order_intents_used = 0
        self._token = None
        self._entered = False
        self._next_leg = 0
        self._attempted = set()
        self._attempted_indices = set()
        self._prepared = {}
        self._intent_economics: Tuple[Mapping[str, Any], ...] = ()

    def __enter__(self) -> "FactorExecutionDecisionScope":
        coordinator = self.coordinator
        if coordinator._active_scope.get() is not None:
            raise FactorExecutionError("NESTED_DECISION_SCOPE")
        self._validate_common()
        intent_economics = self.economic_payload.get("intent_economics")
        if not isinstance(intent_economics, (tuple, list)) or len(intent_economics) != len(
            self.intent_keys
        ):
            if self.intent_keys:
                raise FactorExecutionError("INTENT_ECONOMICS_REQUIRED")
            intent_economics = ()
        if any(not isinstance(item, Mapping) for item in intent_economics):
            raise FactorExecutionError("INTENT_ECONOMICS_INVALID")
        self._intent_economics = tuple(_freeze_mapping(item) for item in intent_economics)
        if len(self.intent_keys) > coordinator.max_order_intents_per_grid:
            raise FactorExecutionError("GRID_ORDER_BUDGET_EXCEEDED")
        self._validate_actions()

        if self.risk_only:
            if self.batch is not None and not self._batch_matches_key(self.batch):
                raise FactorExecutionError("RISK_BATCH_IDENTITY_MISMATCH")
            result = coordinator.journal.record_risk_decision(
                self.key,
                self.economic_payload,
                intent_keys=self.intent_keys,
                max_order_intents_per_run=coordinator.max_order_intents_per_run,
                expected_run_order_intents_used=self.expected_run_order_intents_used,
                remaining_exit_intent_reserve=self.remaining_exit_intent_reserve,
            )
        else:
            self._validate_live_grid()
            result = coordinator.journal.record_grid_decision(
                self.key,
                self.economic_payload,
                intent_keys=self.intent_keys,
                epoch_id=str(self.batch.epoch_id),
                batch_id=self.batch.batch_id,
                eligible=True,
                complete=True,
                live_ready=True,
                inputs_complete=True,
                max_order_intents_per_run=coordinator.max_order_intents_per_run,
                expected_run_order_intents_used=self.expected_run_order_intents_used,
                remaining_exit_intent_reserve=self.remaining_exit_intent_reserve,
            )
        if result.decision is None:
            raise FactorExecutionError("DECISION_NOT_DURABLE")
        self.decision_id = result.decision.decision_id
        self.cursor = result.cursor
        self.is_new_grid = result.is_new_grid
        self.dispatch_allowed = result.is_new_grid
        self.run_order_intents_used = coordinator.run_order_count()
        self._token = coordinator._active_scope.set(self)
        self._entered = True
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        try:
            if self.is_new_grid and self.decision_id is not None:
                self._abandon_unused_slots()
        finally:
            if self._token is not None:
                self.coordinator._active_scope.reset(self._token)
            self._entered = False
        return False

    def begin_order(self, order: Any, *, action: str) -> FactorDispatchAttempt:
        if not self.dispatch_allowed or not self._entered:
            raise FactorExecutionError("DECISION_REPLAY_DISPATCH_BLOCKED")
        if getattr(self.coordinator.store, "allow_writes", None) is not True:
            raise FactorExecutionError("REGISTERED_SIM_WRITES_DISABLED")
        if self._next_leg >= len(self.intent_keys):
            raise FactorExecutionError("UNDECLARED_ORDER_ACTION")
        key = self.intent_keys[self._next_leg]
        economics = dict(self._intent_economics[self._next_leg])
        if key.action != action:
            raise FactorExecutionError("ORDER_ACTION_DOES_NOT_MATCH_PLAN")
        info = getattr(order, "info", {})
        get = getattr(info, "get", lambda name, default=None: default)
        instrument_id = _exact_identifier(get("instrument_id"))
        exchange_id = _exact_identifier(get("exchange_id"))
        side = "BUY" if order.isbuy() else "SELL"
        effect = _exact_identifier(get("factor_position_effect"))
        if instrument_id != key.instrument or side != key.side or effect != key.position_effect:
            raise FactorExecutionError("ORDER_DOES_NOT_MATCH_DECLARED_INTENT")
        if get("factor_strategy_scope") != self.coordinator.strategy_scope:
            raise FactorExecutionError("ORDER_STRATEGY_SCOPE_MISMATCH")
        if economics.get("instrument") != instrument_id:
            raise FactorExecutionError("INTENT_INSTRUMENT_MISMATCH")
        if economics.get("exchange") != exchange_id:
            raise FactorExecutionError("INTENT_EXCHANGE_MISMATCH")
        if economics.get("side") != side or economics.get("position_effect") != effect:
            raise FactorExecutionError("INTENT_ECONOMICS_MISMATCH")
        metadata_bindings = (
            ("offset", "offset"),
            ("hedge_flag", "hedge_flag"),
            ("position_side", "position_side"),
            ("position_date", "position_date"),
            ("offset_flag", "offset_flag"),
            ("factor_owner_side", "owner_side"),
            ("factor_owner_position_effect", "owner_position_effect"),
            ("factor_dated_position_side", "dated_position_side"),
            ("factor_dated_query_set_id", "query_set_id"),
            ("factor_dated_snapshot_id", "snapshot_id"),
            ("factor_dated_account_fingerprint", "account_fingerprint"),
            ("factor_dated_connection_generation", "connection_generation"),
            ("factor_dated_trading_day", "trading_day"),
            ("factor_dated_available_at", "available_at"),
            ("factor_dated_source_row_ids", "source_row_ids"),
            ("factor_dated_opening_execution_ids", "opening_execution_ids"),
            ("factor_dated_close_execution_ids", "close_execution_ids"),
        )
        for info_name, economics_name in metadata_bindings:
            if economics_name in economics and get(info_name) != economics[economics_name]:
                raise FactorExecutionError(
                    "ORDER_METADATA_DOES_NOT_MATCH_INTENT_ECONOMICS:" + economics_name
                )
        requested_hedge_flag = get("hedge_flag")
        if requested_hedge_flag is not None and requested_hedge_flag != "1":
            # The direct CTP Store encoder currently emits CombHedgeFlag='1'
            # for every request.  Do not silently route a different Strategy
            # hedge bucket through that hard-coded speculation flag.
            raise FactorExecutionError("REGISTERED_SIM_HEDGE_FLAG_UNSUPPORTED")
        requested_offset = get("offset")
        if requested_offset is not None:
            allowed_offsets = (
                {"open"}
                if action == "SUBMIT" and key.position_effect == "OPEN"
                else {"close", "close_today", "close_yesterday"}
                if action == "SUBMIT" and key.position_effect == "CLOSE"
                else {"open", "close", "close_today", "close_yesterday"}
            )
            if requested_offset not in allowed_offsets:
                raise FactorExecutionError("REGISTERED_SIM_OFFSET_UNSUPPORTED")
        self.coordinator._route_eligibility(instrument_id, exchange_id, self.execution_facts)
        if action == "CANCEL":
            order_ref = _first_text(
                get("external_order_ref"), get("ctp_order_ref"), get("order_ref")
            )
            owner_intent_id = _first_text(get("factor_intent_id"))
            if order_ref is None or owner_intent_id is None:
                raise FactorExecutionError("CANCEL_REMOTE_IDENTITY_REQUIRED")
            economics.setdefault("owner_intent_id", owner_intent_id)
            identity = {
                "backtrader_order_ref": int(order.ref),
                "order_ref": order_ref,
                "order_sys_id": _first_text(get("order_sys_id")),
                "front_id": _positive_int(get("front_id")),
                "session_id": _positive_int(get("session_id")),
                "instrument_id": instrument_id,
                "exchange_id": exchange_id,
                "operation": "cancel",
            }
        else:
            account = getattr(self.execution_facts, "account", None)
            trading_day = _valid_trading_day(getattr(account, "trading_day", None))
            if trading_day is None:
                raise FactorExecutionError("TRADING_DAY_REQUIRED_FOR_ORDER_IDENTITY")
            reserved_ref = self.coordinator.store.registered_sim_reserve_order_ref()
            if not isinstance(reserved_ref, str) or _ORDER_REF.fullmatch(reserved_ref) is None:
                raise FactorExecutionError("REGISTERED_SIM_ORDER_REF_INVALID")
            order.addinfo(order_ref=reserved_ref)
            quantity = abs(_decimal_or_zero(getattr(order, "size", None)))
            if quantity <= 0:
                raise FactorExecutionError("ORDER_QUANTITY_INVALID")
            expected_quantity = _decimal_optional(economics.get("quantity"))
            if expected_quantity is None or expected_quantity != quantity:
                raise FactorExecutionError("ORDER_QUANTITY_MISMATCH")
            limit_price = getattr(getattr(order, "created", None), "price", None)
            expected_limit = economics.get("limit_price")
            if expected_limit is not None and _decimal_optional(
                expected_limit
            ) != _decimal_optional(limit_price):
                raise FactorExecutionError("ORDER_LIMIT_PRICE_MISMATCH")
            identity = {
                "backtrader_order_ref": int(order.ref),
                "order_ref": reserved_ref,
                "instrument_id": instrument_id,
                "exchange_id": exchange_id,
                "trading_day": trading_day,
                "operation": "insert",
            }
        owner_intent_id = economics.get("owner_intent_id")
        if action == "SUBMIT" and key.position_effect == "OPEN" and owner_intent_id is not None:
            raise FactorExecutionError("OPEN_MUST_NOT_NAME_EXISTING_OWNER")
        if (
            action == "SUBMIT"
            and key.position_effect == "CLOSE"
            and not _exact_identifier(owner_intent_id)
        ):
            raise FactorExecutionError("CLOSE_OWNER_REQUIRED")
        intent = self.coordinator.journal.prepare_intent(
            self.decision_id,
            key,
            economics,
            original_identity=identity,
            owner_intent_id=owner_intent_id,
        )
        self._prepared[self._next_leg] = intent.intent_id
        if intent.state != "PREPARED" or intent.dispatch_state is not None:
            raise FactorExecutionError("INTENT_NOT_DISPATCHABLE")
        history = self.coordinator.store.registered_sim_dispatch_history()
        if not isinstance(history, tuple):
            self.coordinator.journal.abandon_prepared_intent(
                intent.intent_id, reason_code="dispatch_history_unavailable"
            )
            raise FactorExecutionError("REGISTERED_SIM_DISPATCH_HISTORY_UNAVAILABLE")
        before_sequence = max(
            (
                getattr(item, "sequence", 0)
                for item in history
                if type(getattr(item, "sequence", None)) is int
            ),
            default=0,
        )
        claim = self.coordinator.journal.claim_dispatch(intent.intent_id)
        if claim is None:
            raise FactorExecutionError("DISPATCH_ALREADY_CLAIMED")
        intent = claim.intent
        self._attempted.add(intent.intent_id)
        self._attempted_indices.add(self._next_leg)
        self._prepared.pop(self._next_leg, None)
        self._next_leg += 1
        if action == "SUBMIT":
            order.addinfo(
                factor_intent_id=intent.intent_id,
                factor_strategy_scope=self.coordinator.strategy_scope,
                external_order_ref=identity["order_ref"],
            )
        else:
            order.addinfo(
                factor_cancel_intent_id=intent.intent_id,
                factor_strategy_scope=self.coordinator.strategy_scope,
                external_order_id=identity["order_ref"],
            )
        return FactorDispatchAttempt(
            intent=intent,
            operation=_DISPATCH_OPERATIONS[action],
            instrument_id=instrument_id,
            exchange_id=exchange_id,
            order_ref=identity["order_ref"],
            before_sequence=before_sequence,
        )

    def complete_order(
        self, order: Any, attempt: FactorDispatchAttempt, *, response=None, error=None
    ):
        evidence = getattr(error, "evidence", None) if error is not None else None
        if evidence is None:
            history = self.coordinator.store.registered_sim_dispatch_history()
            if isinstance(history, tuple):
                evidence = next(
                    (
                        item
                        for item in reversed(history)
                        if type(getattr(item, "sequence", None)) is int
                        and item.sequence > attempt.before_sequence
                        and getattr(item, "operation", None) == attempt.operation
                        and getattr(item, "instrument_id", None) == attempt.instrument_id
                        and getattr(item, "exchange_id", None) == attempt.exchange_id
                        and getattr(item, "order_ref", None) == attempt.order_ref
                    ),
                    None,
                )
        identity = _dispatch_identity(evidence, attempt)
        known = bool(
            evidence is not None
            and _dispatch_evidence_matches(evidence, attempt)
            and getattr(evidence, "status", None) == "KNOWN"
            and getattr(evidence, "native_return_code", None) == 0
            and getattr(evidence, "resend_permitted", True) is False
        )
        try:
            intent = self.coordinator.journal.record_dispatch_result(
                attempt.intent.intent_id,
                state="KNOWN" if known else "UNKNOWN",
                provider_identity=identity,
                outcome_code="native_ack" if known else _bounded_code(error),
            )
        except Exception as persistence_error:
            order.addinfo(
                factor_dispatch_state="UNKNOWN",
                execution_unknown=True,
                factor_dispatch_error="journal_result_persistence_failed",
            )
            raise FactorExecutionError("DISPATCH_RESULT_NOT_DURABLE") from persistence_error
        order.addinfo(
            factor_dispatch_state=intent.state,
            execution_unknown=intent.state == "UNKNOWN",
            factor_dispatch_outcome=intent.outcome_code,
        )
        return intent

    def _abandon_unused_slots(self) -> None:
        for index, key in enumerate(self.intent_keys):
            if index in self._attempted_indices:
                continue
            try:
                intent_id = self._prepared.get(index)
                if intent_id is None:
                    self.coordinator.journal.abandon_unprepared_slot(
                        self.decision_id,
                        key,
                        reason_code="decision_scope_exit_before_dispatch",
                    )
                else:
                    self.coordinator.journal.abandon_prepared_intent(
                        intent_id,
                        reason_code="decision_scope_exit_before_dispatch",
                    )
            except ExecutionDecisionJournalError as error:
                # DISPATCHING/UNKNOWN must remain unresolved and owned. A
                # repeated exact abandonment is already durable history.
                if error.code not in (
                    "INTENT_ABANDONMENT_CONFLICT",
                    "INTENT_NOT_ABANDONABLE",
                    "INTENT_NOT_PREPARED",
                ):
                    raise

    def _validate_common(self) -> None:
        if self.owner is None or getattr(self.owner, "broker", None) is not self.coordinator.broker:
            raise FactorExecutionError("STRATEGY_BROKER_MISMATCH")
        if not isinstance(self.key, ExecutionDecisionKey):
            raise FactorExecutionError("INVALID_DECISION_KEY")
        coordinator = self.coordinator
        if (
            self.key.account_scope != coordinator.account_scope
            or self.key.strategy_scope != coordinator.strategy_scope
            or self.key.logical_run_id != coordinator.logical_run_id
        ):
            raise FactorExecutionError("DECISION_SCOPE_IDENTITY_MISMATCH")
        if type(self.inputs_complete) is not bool or self.inputs_complete is not True:
            raise FactorExecutionError("DECISION_INPUTS_INCOMPLETE")
        from .factor_execution_facts import FactorExecutionFacts

        if self.execution_facts is None and not self.intent_keys:
            # A complete LIVE_READY eligible-grid NOOP carries no account or
            # order authority. Persist it without fabricating execution facts.
            return
        if not isinstance(self.execution_facts, FactorExecutionFacts):
            raise FactorExecutionError("EXECUTION_FACTS_REQUIRED")
        if (
            self.execution_facts.account_scope != coordinator.account_scope
            or self.execution_facts.strategy_scope != coordinator.strategy_scope
        ):
            raise FactorExecutionError("EXECUTION_FACTS_SCOPE_MISMATCH")
        if (
            any(
                key.action == "SUBMIT" and key.position_effect == "CLOSE"
                for key in self.intent_keys
            )
            and self.execution_facts.risk_reduction_ready is not True
        ):
            raise FactorExecutionError("RISK_REDUCTION_FACTS_NOT_READY")
        if any(key.action == "CANCEL" for key in self.intent_keys) and (
            self.execution_facts.order_cancel_ready is not True
        ):
            raise FactorExecutionError("ORDER_CANCEL_FACTS_NOT_READY")

    def _validate_live_grid(self) -> None:
        from ..research.live import LiveFactorReadiness
        from ..research.live_cohort import LiveCohortBatch

        if not isinstance(self.batch, LiveCohortBatch):
            raise FactorExecutionError("COMPLETE_LIVE_BATCH_REQUIRED")
        if self.batch.status != "COMPLETE" or self.batch.cohort_id != self.key.cohort_id:
            raise FactorExecutionError("LIVE_BATCH_INCOMPLETE_OR_MISMATCHED")
        if not self._batch_matches_key(self.batch):
            raise FactorExecutionError("LIVE_BATCH_KEY_MISMATCH")
        from ..research.live import LiveFactorSnapshot

        if not isinstance(self.snapshot, LiveFactorSnapshot):
            raise FactorExecutionError("LIVE_FACTOR_SNAPSHOT_REQUIRED")
        if (
            self.snapshot.readiness is not LiveFactorReadiness.LIVE_READY
            or self.snapshot.batch_complete is not True
            or self.snapshot.cohort_id != self.batch.cohort_id
            or self.snapshot.batch_id != self.batch.batch_id
            or self.snapshot.epoch_id != self.batch.epoch_id
            or not _same_time(self.snapshot.close_time, self.batch.close_time)
        ):
            raise FactorExecutionError("LIVE_FACTOR_SNAPSHOT_NOT_READY")
        if any(
            key.action == "SUBMIT" and key.position_effect == "OPEN" for key in self.intent_keys
        ):
            if self.execution_facts.open_risk_ready is not True:
                raise FactorExecutionError("OPEN_RISK_FACTS_NOT_READY")

    def _batch_matches_key(self, batch: Any) -> bool:
        return bool(
            getattr(batch, "cohort_id", None) == self.key.cohort_id
            and getattr(batch, "batch_id", None)
            and _same_time(getattr(batch, "close_time", None), self.key.close_time)
        )

    def _validate_actions(self) -> None:
        if any(not isinstance(key, ExecutionIntentKey) for key in self.intent_keys):
            raise FactorExecutionError("INVALID_INTENT_KEY")
        if self.risk_only and any(
            key.action == "SUBMIT" and key.position_effect != "CLOSE" for key in self.intent_keys
        ):
            raise FactorExecutionError("RISK_DECISION_MAY_NOT_OPEN")


def _dispatch_identity(evidence: Any, attempt: FactorDispatchAttempt) -> Mapping[str, Any]:
    if evidence is None:
        return {
            "operation": attempt.operation,
            "instrument_id": attempt.instrument_id,
            "exchange_id": attempt.exchange_id,
            "order_ref": attempt.order_ref,
            "evidence": "unobserved",
        }
    return {
        "operation": getattr(evidence, "operation", None),
        "request_id": getattr(evidence, "request_id", None),
        "sequence": getattr(evidence, "sequence", None),
        "status": getattr(evidence, "status", None),
        "instrument_id": getattr(evidence, "instrument_id", None),
        "exchange_id": getattr(evidence, "exchange_id", None),
        "order_ref": getattr(evidence, "order_ref", None),
        "order_sys_id": getattr(evidence, "order_sys_id", None),
        "front_id": getattr(evidence, "front_id", None),
        "session_id": getattr(evidence, "session_id", None),
        "broker_id": getattr(evidence, "broker_id", None),
        "investor_id": getattr(evidence, "investor_id", None),
        "user_id": getattr(evidence, "user_id", None),
        "native_return_code": getattr(evidence, "native_return_code", None),
        "error_type": getattr(evidence, "error_type", None),
        "resend_permitted": getattr(evidence, "resend_permitted", None),
    }


def _dispatch_evidence_matches(evidence: Any, attempt: FactorDispatchAttempt) -> bool:
    """Require a native receipt to identify this exact single-use attempt."""

    return bool(
        getattr(evidence, "operation", None) == attempt.operation
        and getattr(evidence, "instrument_id", None) == attempt.instrument_id
        and getattr(evidence, "exchange_id", None) == attempt.exchange_id
        and getattr(evidence, "order_ref", None) == attempt.order_ref
        and type(getattr(evidence, "request_id", None)) is int
        and getattr(evidence, "request_id", 0) > 0
    )


def _contract_route(broker: Any, data_name: str) -> Tuple[Optional[str], Optional[str]]:
    metadata = getattr(broker, "_contract_metadata", {})
    rules = metadata.get(data_name, {}) if isinstance(metadata, Mapping) else {}
    if not rules and getattr(broker, "store", None) is not None:
        store_metadata = getattr(broker.store, "contract_metadata", {})
        if isinstance(store_metadata, Mapping):
            rules = store_metadata.get(data_name, {})
    instrument = _first_text(rules.get("instrument_id")) if isinstance(rules, Mapping) else None
    exchange = _first_text(rules.get("exchange_id")) if isinstance(rules, Mapping) else None
    if instrument is None or exchange is None:
        return None, None
    return instrument, exchange


def _exact_identifier(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value and value == value.strip() else None


def _exact_identifier_or_raise(value: Any) -> str:
    result = _exact_identifier(value)
    if result is None:
        raise FactorExecutionError("IDENTITY_REQUIRED")
    return result


def _exact_text(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value and value == value.strip() else None


def _first_text(*values: Any) -> Optional[str]:
    for value in values:
        text = _exact_text(value)
        if text is not None:
            return text
    return None


def _positive_int(value: Any) -> Optional[int]:
    """Return an observed positive native session identifier, without coercion."""

    return value if type(value) is int and value > 0 else None


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value))


def _decimal_optional(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def _decimal_or_zero(value: Any) -> Decimal:
    result = _decimal_optional(value)
    return Decimal(0) if result is None else result


def _same_time(left: Any, right: Any) -> bool:
    left_value = _aware_utc(left)
    right_value = _aware_utc(right)
    return left_value is not None and right_value is not None and left_value == right_value


def _aware_utc(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None:
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
        except ValueError:
            return None
        if parsed.tzinfo is not None and parsed.utcoffset() is not None:
            return parsed.astimezone(timezone.utc)
    return None


def _bounded_code(error: Optional[BaseException]) -> str:
    value = getattr(error, "code", None) if error is not None else None
    if (
        isinstance(value, str)
        and value
        and len(value) <= 96
        and all(character.isalnum() or character in "._:-" for character in value)
    ):
        return value
    return "dispatch_outcome_unknown"


def _first_value(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _ctp_trade_time_ns(trade_date: Optional[str], trade_time: Optional[str]) -> Optional[int]:
    """Convert exact CTP local trade fields with its UTC+08 exchange clock."""

    if trade_date is None or trade_time is None or re.fullmatch(r"\d{8}", trade_date) is None:
        return None
    normalized_time = trade_time.strip()
    for pattern in ("%H:%M:%S.%f", "%H:%M:%S"):
        try:
            parsed = datetime.strptime(trade_date + normalized_time, "%Y%m%d" + pattern)
        except ValueError:
            continue
        local = parsed.replace(tzinfo=timezone(timedelta(hours=8)))
        utc = local.astimezone(timezone.utc)
        return _datetime_epoch_ns(utc)
    return None


def _datetime_epoch_ns(value: Any) -> Optional[int]:
    """Convert an aware datetime to integer nanoseconds without float math."""

    utc = _aware_utc(value)
    if utc is None:
        return None
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = utc - epoch
    return (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000


def _trade_observation_evidence(facts: Any, observation: Any) -> Mapping[str, Any]:
    timestamp_ns = _datetime_epoch_ns(observation.trade_time_utc)
    if timestamp_ns is None:
        raise FactorExecutionError("TRADE_OBSERVATION_TIME_UNAVAILABLE")
    return {
        "event_type": "execution_fill",
        "execution_id": "ctp:{}:{}".format(observation.trade_date, observation.trade_id),
        "provider_trade_id": observation.trade_id,
        "order_ref": observation.order_ref,
        "order_sys_id": observation.order_sys_id,
        "instrument_id": observation.instrument,
        "exchange": observation.exchange,
        "quantity": observation.volume,
        "price": observation.price,
        "fee": observation.fee,
        "filled_at_ns": timestamp_ns,
        "time_source": "CTP_TradeDate_TradeTime_UTC_PLUS_08",
        "evidence_kind": observation.evidence_kind,
        "query_observation_id": observation.observation_id,
        "snapshot_id": observation.snapshot_id,
        "request_id": observation.request_id,
        "connection_generation": observation.connection_generation,
        "account_fingerprint": observation.account_fingerprint,
        "trading_day": observation.trading_day,
        "account_scope": facts.account_scope,
        "strategy_scope": facts.strategy_scope,
    }


def _trade_observation_callback_id(execution_id: str) -> str:
    return "query-trade:" + hashlib.sha256(execution_id.encode("utf-8")).hexdigest()


def _native_trade_callback_id(trade_id: str, order_ref: str, instrument: str, exchange: str) -> str:
    """Identify a raw native callback without relying on TradeDate."""

    material = "\0".join((trade_id, order_ref, instrument, exchange))
    return "native-trade:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def _unusable_trade_callback_matches_observation(
    observation: Any, evidence: Mapping[str, Any]
) -> bool:
    """Bind a date-less callback to its later complete-query trade row.

    The complete query supplies TradeDate.  It is used here only to compare a
    callback's optional TradeTime; it never rewrites or derives the callback's
    missing date or TradingDay.
    """

    if (
        evidence.get("event_type") != "unresolved_trade_callback"
        or evidence.get("evidence_kind") != "native_trade_callback_unusable_trade_date"
        or _valid_trading_day(evidence.get("trade_date")) is not None
        or evidence.get("provider_trade_id") != observation.trade_id
        or evidence.get("order_ref") != observation.order_ref
        or evidence.get("instrument_id") != observation.instrument
        or evidence.get("exchange") != observation.exchange
        or evidence.get("side") != observation.side
        or evidence.get("position_effect") != observation.position_effect
    ):
        return False

    raw_quantity = _decimal_optional(evidence.get("quantity"))
    raw_price = _decimal_optional(evidence.get("price"))
    if raw_quantity != observation.volume or raw_price != observation.price:
        return False
    raw_fee = _decimal_optional(evidence.get("fee"))
    if (
        evidence.get("fee") is not None
        and observation.fee is not None
        and raw_fee != observation.fee
    ):
        return False

    raw_order_sys_id = evidence.get("order_sys_id")
    if (
        raw_order_sys_id is not None
        and observation.order_sys_id is not None
        and raw_order_sys_id != observation.order_sys_id
    ):
        return False

    raw_direction = evidence.get("direction")
    if raw_direction is not None and raw_direction != observation.direction:
        return False
    raw_offset = evidence.get("offset_flag")
    if raw_offset is not None and observation.offset_flag is not None:
        if raw_offset != observation.offset_flag:
            return False

    raw_trading_day = evidence.get("trading_day")
    if raw_trading_day is not None:
        if (
            _valid_trading_day(raw_trading_day) is None
            or raw_trading_day != observation.trading_day
        ):
            return False

    raw_trade_time = evidence.get("trade_time")
    if raw_trade_time is not None:
        callback_time_ns = _ctp_trade_time_ns(observation.trade_date, raw_trade_time)
        if callback_time_ns is not None:
            query_time_ns = _datetime_epoch_ns(observation.trade_time_utc)
            if callback_time_ns != query_time_ns:
                return False
    return True


def _trade_observation_matches_evidence(observation: Any, evidence: Mapping[str, Any]) -> bool:
    expected_execution = "ctp:{}:{}".format(observation.trade_date, observation.trade_id)
    expected_ns = _datetime_epoch_ns(observation.trade_time_utc)
    stored_quantity = _decimal_optional(evidence.get("quantity"))
    stored_price = _decimal_optional(evidence.get("price"))
    stored_fee = _decimal_optional(evidence.get("fee"))
    return bool(
        evidence.get("event_type") == "execution_fill"
        and evidence.get("execution_id") == expected_execution
        and evidence.get("provider_trade_id") == observation.trade_id
        and evidence.get("order_ref") == observation.order_ref
        and evidence.get("instrument_id") == observation.instrument
        and evidence.get("exchange") == observation.exchange
        and stored_quantity == observation.volume
        and stored_price == observation.price
        and evidence.get("filled_at_ns") == expected_ns
        and (observation.fee is None or stored_fee == observation.fee)
        and (
            evidence.get("order_sys_id") is None
            or observation.order_sys_id is None
            or evidence.get("order_sys_id") == observation.order_sys_id
        )
    )


def _valid_trading_day(value: Any) -> Optional[str]:
    if type(value) is not str or re.fullmatch(r"\d{8}", value) is None:
        return None
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return None
    return value


def _validate_page(limit: Any, offset: Any, *, maximum: int) -> None:
    if type(limit) is not int or not 1 <= limit <= maximum:
        raise FactorExecutionError("INVALID_RECOVERY_PAGE_LIMIT")
    if type(offset) is not int or not 0 <= offset <= 1_000_000:
        raise FactorExecutionError("INVALID_RECOVERY_PAGE_OFFSET")


def _time_not_after(left: Any, right: Any) -> bool:
    left_utc = _aware_utc(left)
    right_utc = _aware_utc(right)
    return left_utc is not None and right_utc is not None and left_utc <= right_utc


def _terminal_state(value: str) -> Optional[str]:
    return {
        "ALL_TRADED": "FILLED",
        "PART_TRADED_NOT_QUEUEING": "FILLED",
        "NO_TRADE_NOT_QUEUEING": "REJECTED",
        "CANCELED": "CANCELLED",
    }.get(value)


def _terminal_reconciliation_id(
    intent_id: str,
    observation_id: str,
    snapshot_id: str,
    broker_quantity: Decimal,
    long_quantity: Decimal,
    short_quantity: Decimal,
) -> str:
    material = "|".join(
        (
            intent_id,
            observation_id,
            snapshot_id,
            str(broker_quantity),
            str(long_quantity),
            str(short_quantity),
        )
    )
    return "terminal-query:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def _terminal_position_consistent(position: Any, facts: Any) -> bool:
    broker_quantity = getattr(position, "broker_quantity", None)
    long_quantity = getattr(position, "long_quantity", None)
    short_quantity = getattr(position, "short_quantity", None)
    return bool(
        position.snapshot_id == facts.snapshot_id
        and _same_time(position.available_at, facts.available_at)
        and isinstance(broker_quantity, Decimal)
        and broker_quantity.is_finite()
        and isinstance(long_quantity, Decimal)
        and long_quantity.is_finite()
        and long_quantity >= 0
        and isinstance(short_quantity, Decimal)
        and short_quantity.is_finite()
        and short_quantity >= 0
        and not (long_quantity > 0 and short_quantity > 0)
        and broker_quantity == long_quantity - short_quantity
    )


def _one_query_provenance(facts: Any, family: str, request_type: str) -> Any:
    matches = [item for item in facts.query_provenance if item.family == family]
    if len(matches) != 1:
        raise FactorExecutionError("QUERY_PROVENANCE_AMBIGUOUS:" + family)
    source = matches[0]
    if (
        source.request_type != request_type
        or type(source.request_id) is not int
        or source.request_id <= 0
        or type(source.connection_generation) is not int
        or source.connection_generation <= 0
        or _valid_trading_day(source.trading_day) is None
        or not _exact_identifier(source.account_fingerprint)
        or source.source_owned is not True
        or source.query_complete is not True
        or source.scope_complete is not True
        or source.completed_at is None
        or type(source.row_count) is not int
        or source.row_count < 0
    ):
        raise FactorExecutionError("QUERY_PROVENANCE_INCOMPLETE:" + family)
    account = facts.account
    if (
        account is None
        or account.account_fingerprint != source.account_fingerprint
        or account.connection_generation != source.connection_generation
        or account.trading_day != source.trading_day
    ):
        raise FactorExecutionError("QUERY_ACCOUNT_BINDING_MISMATCH:" + family)
    return source


def _same_query_identity(left: Any, right: Any) -> bool:
    return bool(
        left.account_fingerprint == right.account_fingerprint
        and left.connection_generation == right.connection_generation
        and left.trading_day == right.trading_day
    )


def _utc_text(value: Any) -> Optional[str]:
    utc = _aware_utc(value)
    if utc is None:
        return None
    return utc.isoformat().replace("+00:00", "Z")


__all__ = (
    "ExecutionOrderSnapshot",
    "ExecutionPositionSnapshot",
    "ExecutionTerminalReconciliationItem",
    "ExecutionTerminalReconciliationPage",
    "FactorDispatchAttempt",
    "FactorExecutionCoordinator",
    "FactorExecutionDecisionScope",
    "FactorExecutionError",
    "execution_order_snapshot",
    "execution_position_snapshot",
)
