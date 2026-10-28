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
import json
import re
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from threading import get_ident
from types import MappingProxyType
from typing import Any, Dict, Iterator, Optional, Tuple

from .execution_decision_journal import (
    ExecutionDecisionJournal,
    ExecutionDecisionJournalError,
    ExecutionDecisionKey,
    ExecutionIntentKey,
    ExecutionIntentRecord,
    ExecutionRunLossGuardContext,
    ExecutionRunLossGuardSnapshot,
    ExecutionSourceReceipt,
    _dispatching_cancel_absence_ack_ids,
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


@dataclass(frozen=True)
class _TerminalRecoveryScopeState:
    coordinator: Any
    journal: ExecutionDecisionJournal
    lease: Any
    thread_id: int
    started_at: datetime


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
            registered_sim_ctp_identity_conflict = False
            if (
                getattr(getattr(broker, "store", None), "registered_sim_route_id", None)
                == "simnow-registered-v1"
            ):
                # RegisteredSim's generic ID cache can also be populated by
                # query or submit projections.  Those rows do not establish
                # the raw CTP callback lineage needed by the fixed route, so
                # only the dedicated callback-source field can supply an ID.
                generic_sys_id = order_sys_id
                order_sys_id = None
                registered_sim_ctp_identity_conflict = (
                    get("registered_sim_ctp_order_sys_id_conflict") is True
                )
                registered_sim_sys_id = _exact_identifier(get("registered_sim_ctp_order_sys_id"))
                registered_sim_source = get("registered_sim_ctp_order_sys_id_source")
                binding_captured = get("_registered_sim_ctp_identity_binding_captured") is True
                binding_valid = get("_registered_sim_ctp_identity_binding_valid") is True
                if (
                    binding_captured
                    and binding_valid
                    and registered_sim_source == "ctp_order_callback"
                ):
                    if (
                        registered_sim_sys_id is not None
                        and generic_sys_id is not None
                        and registered_sim_sys_id != generic_sys_id
                    ):
                        registered_sim_ctp_identity_conflict = True
                    elif registered_sim_sys_id is not None:
                        order_sys_id = registered_sim_sys_id
                if registered_sim_ctp_identity_conflict:
                    # Preserve the Broker's cached generic evidence but do
                    # not let a conflicting source identity satisfy Facts.
                    order_sys_id = None
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
                    execution_unknown=(
                        get("execution_unknown") is True or registered_sim_ctp_identity_conflict
                    ),
                    cancel_pending=bool(
                        get("cancel_requested_remote")
                        or get("cancel_intent_active")
                        or get("managed_execution_cancel_pending")
                    ),
                    external_order_ref=remote_order_ref,
                    order_sys_id=order_sys_id,
                    front_id=_positive_int(get("front_id"))
                    or _positive_int(get("factor_session_front_id")),
                    session_id=_positive_int(get("session_id"))
                    or _positive_int(get("factor_session_id")),
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
        self._terminal_recovery_scope_state = contextvars.ContextVar(
            "factor_terminal_recovery_scope_{}".format(id(self)), default=None
        )
        self._active_terminal_recovery_scope_state = None
        # Keep a Store-local fence after the Broker binding is removed or
        # replaced.  Otherwise a raw legacy OrderRef cancel could bypass the
        # account-wide durable owner lookup during this Store lifetime.
        setattr(store, "_registered_sim_durable_owner_configured", True)
        broker.factor_execution_coordinator = self

    def grid_cursor(self, cohort_id: str):
        return self.journal.grid_cursor(self.account_scope, self.strategy_scope, cohort_id)

    def run_order_count(self) -> int:
        return self.journal.run_order_count(
            self.account_scope, self.strategy_scope, self.logical_run_id
        )

    def run_loss_guard(
        self, context: ExecutionRunLossGuardContext
    ) -> Optional[ExecutionRunLossGuardSnapshot]:
        """Read explicit persisted guard state without initializing it.

        A read is diagnostic only. OPEN decisions still pass the journal's
        freshness and trip checks inside their durable transaction.
        """

        context = self._validate_run_loss_guard_context(context)
        try:
            snapshot = self.journal.run_loss_guard(
                self.account_scope, self.strategy_scope, self.logical_run_id
            )
        except ExecutionDecisionJournalError as error:
            raise FactorExecutionError(error.code) from error
        if snapshot is not None and snapshot.context != context:
            raise FactorExecutionError("RUN_LOSS_GUARD_CONTEXT_MISMATCH")
        return snapshot

    def enable_run_loss_guard(
        self,
        context: ExecutionRunLossGuardContext,
        account_facts: Any,
        *,
        net_loss_threshold: Decimal,
        max_observation_age_seconds: int,
    ) -> ExecutionRunLossGuardSnapshot:
        """Explicitly initialize a persistent policy from qualified account PnL.

        The caller supplies the policy identity and qualified total net PnL
        (realized plus unrealized, with fees counted exactly once) under the
        declared basis; this component does not choose a threshold, infer fees,
        or enable a policy as a side effect of ordinary reads or decisions. The limit
        stops new OPEN admission only; it does not guarantee a maximum final
        loss or force liquidation.
        """

        context, account, asof = self._run_loss_observation_inputs(context, account_facts)
        try:
            return self.journal.enable_run_loss_guard(
                context,
                baseline_observation_id=account.snapshot_id,
                baseline_asof=asof,
                baseline_total_net_pnl=account.total_net_pnl,
                net_loss_threshold=net_loss_threshold,
                max_observation_age_seconds=max_observation_age_seconds,
            )
        except ExecutionDecisionJournalError as error:
            raise FactorExecutionError(error.code) from error

    def record_run_loss_observation(
        self,
        context: ExecutionRunLossGuardContext,
        account_facts: Any,
    ) -> ExecutionRunLossGuardSnapshot:
        """Persist one qualified total-net-PnL observation supplied by the caller."""

        context, account, asof = self._run_loss_observation_inputs(context, account_facts)
        try:
            return self.journal.record_run_loss_observation(
                context,
                observation_id=account.snapshot_id,
                asof=asof,
                total_net_pnl=account.total_net_pnl,
            )
        except ExecutionDecisionJournalError as error:
            raise FactorExecutionError(error.code) from error

    def _validate_run_loss_guard_context(
        self, context: ExecutionRunLossGuardContext
    ) -> ExecutionRunLossGuardContext:
        if type(context) is not ExecutionRunLossGuardContext:
            raise FactorExecutionError("RUN_LOSS_GUARD_CONTEXT_INVALID")
        if (
            context.account_scope != self.account_scope
            or context.strategy_scope != self.strategy_scope
            or context.logical_run_id != self.logical_run_id
        ):
            raise FactorExecutionError("RUN_LOSS_GUARD_CONTEXT_MISMATCH")
        if (
            type(context.currency) is not str
            or _valid_trading_day(context.trading_day) != context.trading_day
            or not _exact_identifier(context.pnl_basis)
        ):
            raise FactorExecutionError("RUN_LOSS_GUARD_CONTEXT_INVALID")
        if context.currency != "CNY":
            raise FactorExecutionError("RUN_LOSS_ACCOUNT_CURRENCY_UNSUPPORTED")
        return context

    def _run_loss_observation_inputs(self, context: Any, account_facts: Any):
        context = self._validate_run_loss_guard_context(context)
        from .factor_execution_facts import FactorExecutionAccountFacts

        if type(account_facts) is not FactorExecutionAccountFacts:
            raise FactorExecutionError("RUN_LOSS_ACCOUNT_FACTS_INVALID")
        if account_facts.account_scope != self.account_scope:
            raise FactorExecutionError("RUN_LOSS_ACCOUNT_SCOPE_MISMATCH")
        if (
            account_facts.total_net_pnl_available is not True
            or account_facts.total_net_pnl_reason is not None
            or type(account_facts.total_net_pnl) is not Decimal
            or not account_facts.total_net_pnl.is_finite()
        ):
            raise FactorExecutionError("RUN_LOSS_ACCOUNT_PNL_UNQUALIFIED")
        if (
            type(account_facts.trading_day) is not str
            or _valid_trading_day(account_facts.trading_day) != context.trading_day
        ):
            raise FactorExecutionError("RUN_LOSS_ACCOUNT_TRADING_DAY_MISMATCH")
        if (
            type(account_facts.currency) is not str
            or account_facts.currency != context.currency
            or account_facts.currency != "CNY"
        ):
            raise FactorExecutionError("RUN_LOSS_ACCOUNT_CURRENCY_MISMATCH")
        if type(account_facts.snapshot_id) is not str or not _exact_identifier(
            account_facts.snapshot_id
        ):
            raise FactorExecutionError("RUN_LOSS_ACCOUNT_SNAPSHOT_ID_INVALID")
        if type(account_facts.available_at) is not datetime:
            raise FactorExecutionError("RUN_LOSS_ACCOUNT_ASOF_INVALID")
        asof = _aware_utc(account_facts.available_at)
        if asof is None:
            raise FactorExecutionError("RUN_LOSS_ACCOUNT_ASOF_INVALID")
        asof_text = asof.isoformat().replace("+00:00", "Z")
        return context, account_facts, asof_text

    def _validate_open_loss_guard_scope(
        self,
        context: Optional[ExecutionRunLossGuardContext],
        account_facts: Any,
    ) -> None:
        if context is None:
            # The journal preserves legacy callers while requiring context
            # whenever an immutable policy is configured.
            return
        context, account, asof = self._run_loss_observation_inputs(context, account_facts)
        snapshot = self.run_loss_guard(context)
        if snapshot is None:
            raise FactorExecutionError("RUN_LOSS_GUARD_NOT_CONFIGURED")
        if (
            snapshot.latest_observation_id != account.snapshot_id
            or snapshot.latest_asof != asof
            or snapshot.latest_total_net_pnl != account.total_net_pnl
        ):
            raise FactorExecutionError("RUN_LOSS_GUARD_OBSERVATION_MISMATCH")

    def decision_capacity_snapshot(self):
        """Expose bounded journal usage and physical DB/WAL diagnostics."""

        return self.journal.decision_capacity_snapshot()

    def execution_intent_snapshot(self, *, limit: int = 128):
        return self.journal.execution_intent_snapshot(
            account_scope=self.account_scope, limit=limit
        )

    def bind_known_order_sysids_from_current_query(self) -> Tuple[str, ...]:
        """Persist missing SysIDs from this Store's current complete order query.

        This is called only while facts consume a valid complete query set. It
        issues no query and never trusts callback tags or the mutable Broker
        SysID cache. The Journal rechecks each candidate against its immutable
        KNOWN submit and the Store-minted source receipt.
        """
        receipt_factory = getattr(
            self.store, "registered_sim_order_identity_query_receipt", None
        )
        if not callable(receipt_factory):
            return ("KNOWN_CTP_ORDER_SYSID_RECEIPT_UNAVAILABLE",)
        try:
            receipt = receipt_factory()
        except Exception as error:
            code = getattr(error, "code", None)
            return (
                code if _exact_identifier(code) else "KNOWN_CTP_ORDER_SYSID_RECEIPT_UNAVAILABLE",
            )
        if receipt is None:
            return ("KNOWN_CTP_ORDER_SYSID_RECEIPT_UNAVAILABLE",)
        try:
            orders = execution_order_snapshot(self.broker)
            # The Journal's configured pending-intent bound also bounds this
            # lookup. A smaller fixed page could permanently starve otherwise
            # valid owners when an account has more active known orders.
            page = self.execution_intent_snapshot(
                limit=self.journal.max_pending_intents
            )
        except Exception as error:
            code = getattr(error, "code", None)
            return (
                code if _exact_identifier(code) else "KNOWN_CTP_ORDER_SYSID_OWNER_SNAPSHOT_UNAVAILABLE",
            )
        if getattr(page, "truncated", True) is not False:
            return ("KNOWN_CTP_ORDER_SYSID_OWNER_SNAPSHOT_TRUNCATED",)
        intents_by_id = {}
        for intent in getattr(page, "items", ()):
            intent_id = getattr(intent, "intent_id", None)
            if type(intent_id) is str:
                intents_by_id.setdefault(intent_id, []).append(intent)
        orders_by_owner = {}
        for order in orders:
            owner = getattr(order, "owner_intent_id", None)
            if type(owner) is str:
                orders_by_owner.setdefault(owner, []).append(order)
        failures = []
        for owner_id, owned_orders in orders_by_owner.items():
            if len(owned_orders) != 1:
                failures.append("KNOWN_CTP_ORDER_SYSID_LOCAL_OWNER_AMBIGUOUS")
                continue
            matches = intents_by_id.get(owner_id, ())
            if len(matches) != 1:
                continue
            order = owned_orders[0]
            intent = matches[0]
            if (
                getattr(intent, "state", None) != "KNOWN"
                or getattr(intent, "dispatch_state", None) != "KNOWN"
                or getattr(intent, "key", None) is None
                or getattr(intent.key, "action", None) != "SUBMIT"
                or getattr(order, "execution_unknown", None) is not False
                or getattr(order, "cancel_pending", None) is not False
            ):
                continue
            try:
                self.journal.bind_known_ctp_order_sysid_from_query(
                    owner_id,
                    receipt,
                    source_store=self.store,
                    broker_order_ref=order.order_ref,
                    expected_side=order.side,
                    expected_position_effect=order.position_effect,
                    expected_remaining_quantity=order.remaining_quantity,
                    expected_instrument=order.instrument_id,
                    expected_exchange=order.exchange_id,
                    expected_front_id=order.front_id,
                    expected_session_id=order.session_id,
                )
            except ExecutionDecisionJournalError as error:
                failures.append(error.code)
            except Exception as error:
                code = getattr(error, "code", None)
                failures.append(
                    code if _exact_identifier(code) else "KNOWN_CTP_ORDER_SYSID_BINDING_UNAVAILABLE"
                )
        return tuple(failures)

    def dispatching_cancel_store_absence_candidates(self, *, limit: int = 128):
        return self.journal.dispatching_cancel_store_absence_candidates(
            self.account_scope, limit=limit
        )

    @contextmanager
    def terminal_recovery_scope(self, *, timeout_seconds: float = 5.0) -> Iterator[datetime]:
        """Hold the cross-process dispatch gate across terminal recovery reads.

        The caller must enter this scope before refreshing the complete query
        set and keep the same thread in the scope through projection,
        reconciliation, and Store retirement.  This fences a live
        prepare/claim/native-call/result interval and prevents another process
        from mistaking its in-flight DISPATCHING row for a crash.

        The yielded UTC time is the lower bound for every source query's
        typed start timestamp.  Facts queried before entry are rejected even
        if their cache is still otherwise fresh.
        """

        if self._terminal_recovery_scope_state.get() is not None:
            raise FactorExecutionError("DISPATCHING_RECOVERY_SCOPE_NESTED")
        gate_context = self.journal.dispatch_serialization_gate(
            timeout_seconds=timeout_seconds,
            recovery=True,
        )
        try:
            lease = gate_context.__enter__()
        except ExecutionDecisionJournalError as error:
            raise FactorExecutionError(error.code) from error
        if getattr(lease, "cross_process", None) is not True:
            gate_context.__exit__(None, None, None)
            raise FactorExecutionError("DISPATCHING_RECOVERY_REQUIRES_CROSS_PROCESS_GATE")

        started_at = datetime.now(timezone.utc)
        state = _TerminalRecoveryScopeState(
            coordinator=self,
            journal=self.journal,
            lease=lease,
            thread_id=get_ident(),
            started_at=started_at,
        )
        self._active_terminal_recovery_scope_state = state
        token = self._terminal_recovery_scope_state.set(state)
        try:
            yield started_at
        except BaseException as error:
            try:
                self._terminal_recovery_scope_state.reset(token)
            finally:
                if self._active_terminal_recovery_scope_state is state:
                    self._active_terminal_recovery_scope_state = None
            gate_context.__exit__(type(error), error, error.__traceback__)
            raise
        else:
            try:
                self._terminal_recovery_scope_state.reset(token)
            finally:
                if self._active_terminal_recovery_scope_state is state:
                    self._active_terminal_recovery_scope_state = None
            gate_context.__exit__(None, None, None)

    def reconcile_trade_observations(
        self,
        facts: Any,
        *,
        limit: int = 128,
        offset: int = 0,
        refresh_receipt: Any = None,
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
            self._reconcile_one_trade_observation(
                facts, observation, refresh_receipt=refresh_receipt
            )
            for observation in selected
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
        self,
        facts: Any,
        *,
        refresh_receipt: Any = None,
        limit: int = 128,
        offset: int = 0,
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
                refresh_receipt=refresh_receipt,
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
        self,
        facts: Any,
        observation: Any,
        *,
        trade_blocker: Optional[str] = None,
        refresh_receipt: Any = None,
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
        if intent.state == "DISPATCHING" and intent.dispatch_state is None:
            return self._reconcile_dispatching_no_fill_terminal(
                facts, observation, intent, refresh_receipt=refresh_receipt
            )
        if intent.state == "KNOWN" and intent.dispatch_state is None:
            return self._replay_known_dispatching_no_fill_terminal(
                facts, observation, intent, refresh_receipt=refresh_receipt
            )
        if intent.dispatch_state == "UNKNOWN":
            return self._reconcile_unknown_no_fill_terminal(
                facts, observation, intent, refresh_receipt=refresh_receipt
            )
        try:
            owner = self.journal.active_instrument_owner(self.account_scope, intent.key.instrument)
            cancel_intent = (
                self.journal.intent(owner.cancel_intent_id)
                if owner is not None
                and owner.intent_id == intent.intent_id
                and owner.cancel_intent_id is not None
                else None
            )
        except Exception as error:
            raise FactorExecutionError("TERMINAL_CANCEL_OWNER_LOOKUP_FAILED") from error
        if (
            cancel_intent is not None
            and cancel_intent.key.action == "CANCEL"
            and cancel_intent.dispatch_state == "UNKNOWN"
        ):
            return self._reconcile_unknown_cancel_terminal(
                facts,
                observation,
                intent,
                cancel_intent,
                refresh_receipt=refresh_receipt,
            )
        if (
            cancel_intent is not None
            and cancel_intent.key.action == "CANCEL"
            and cancel_intent.state == "DISPATCHING"
            and cancel_intent.dispatch_state is None
        ):
            return self._reconcile_dispatching_cancel_terminal(
                facts,
                observation,
                intent,
                cancel_intent,
                refresh_receipt=refresh_receipt,
            )
        # A dispatching-cancel terminal proof commits before the Store's
        # read-only local-absence assertion.  If that assertion fails, the
        # parent resolution is durable and the owner row is already released.
        # Recognize only this explicit marker here so a later complete query
        # can retry the absence assertion without adding another proof or
        # changing any dispatch-result column.  The generic prior-resolution
        # handling below remains unchanged.
        try:
            marker_resolution = self.journal.instrument_resolution(intent.intent_id)
            marker_reconciliation = (
                None
                if marker_resolution is None
                else self.journal.reconciliation(marker_resolution.reconciliation_id)
            )
        except Exception as error:
            raise FactorExecutionError("CANCEL_DISPATCHING_REPLAY_LOOKUP_FAILED") from error
        marker_identity = (
            marker_reconciliation.provider_identity if marker_reconciliation is not None else {}
        )
        if (
            isinstance(marker_identity, Mapping)
            and marker_identity.get("cancel_recovery_kind") == "dispatching_cancel"
        ):
            acknowledgement = self._dispatching_cancel_absence_ack_status(
                intent,
                marker_resolution,
                marker_reconciliation,
            )
            if acknowledgement is None:
                return self._retry_dispatching_cancel_store_absence(
                    facts,
                    observation,
                    intent,
                    marker_resolution,
                    marker_reconciliation,
                    refresh_receipt=refresh_receipt,
                )
            if acknowledgement is False:
                return self._blocked_dispatching_cancel(
                    observation,
                    intent,
                    "CANCEL_DISPATCHING_ABSENCE_ACK_CONFLICT",
                    reconciliation_id=marker_resolution.reconciliation_id,
                )
            # A valid durable absence ack permanently suppresses this special
            # Store assertion. Continue through the established generic
            # prior-resolution check below, which validates the current
            # position projection without rewriting the immutable CAS proof.
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
            elif prior_identity.get("unknown_cancel_intent_id") is not None:
                return self._retry_unknown_cancel_store_retirement(
                    facts,
                    observation,
                    intent,
                    prior_identity,
                    refresh_receipt=refresh_receipt,
                )
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

    def _reconcile_dispatching_no_fill_terminal(
        self, facts: Any, observation: Any, intent: ExecutionIntentRecord, *, refresh_receipt: Any
    ) -> ExecutionTerminalReconciliationItem:
        """Recover a process-dead, unrecorded INSERT inside a fresh-read scope."""

        scope = self._current_terminal_recovery_scope()
        if scope is None:
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=intent.intent_id,
                blocker_code="DISPATCHING_RECOVERY_SCOPE_REQUIRED",
            )

        try:
            current = self.journal.intent(intent.intent_id)
            if current is None:
                raise FactorExecutionError("DISPATCHING_INTENT_NOT_FOUND")
            if (
                current.intent_id != intent.intent_id
                or current.key != intent.key
                or dict(current.original_identity) != dict(intent.original_identity)
                or current.state not in ("DISPATCHING", "KNOWN")
                or current.dispatch_state is not None
                or current.provider_identity is not None
                or current.outcome_code is not None
            ):
                raise FactorExecutionError("DISPATCHING_RECOVERY_NOT_APPLICABLE")
            if current.state == "KNOWN":
                resolution = self.journal.instrument_resolution(current.intent_id)
                reconciliation = (
                    None
                    if resolution is None
                    else self.journal.reconciliation(resolution.reconciliation_id)
                )
                if (
                    resolution is None
                    or reconciliation is None
                    or reconciliation.outcome_code
                    != "complete_orders_query_dispatching_no_fill_terminal"
                    or reconciliation.provider_identity.get("evidence_kind")
                    != "complete_orders_query_dispatching_no_fill_terminal"
                ):
                    raise FactorExecutionError("DISPATCHING_RECOVERY_NOT_APPLICABLE")
            return self._reconcile_dispatching_no_fill_under_gate(
                facts,
                observation,
                current,
                refresh_receipt=refresh_receipt,
                recovery_started_at=scope.started_at,
            )
        except ExecutionDecisionJournalError as error:
            code = error.code
        except FactorExecutionError as error:
            code = error.code
        except Exception as error:
            observed_code = getattr(error, "code", None)
            code = (
                observed_code if _exact_identifier(observed_code) else "DISPATCHING_RECOVERY_FAILED"
            )
        return ExecutionTerminalReconciliationItem(
            observation_id=observation.observation_id,
            status="BLOCKED",
            intent_id=intent.intent_id,
            blocker_code=code,
        )

    def _reconcile_dispatching_no_fill_under_gate(
        self,
        facts: Any,
        observation: Any,
        intent: ExecutionIntentRecord,
        *,
        refresh_receipt: Any,
        recovery_started_at: datetime,
    ) -> ExecutionTerminalReconciliationItem:
        if intent.key.action != "SUBMIT" or intent.key.position_effect != "OPEN":
            raise FactorExecutionError("DISPATCHING_RECOVERY_UNSUPPORTED_INTENT")
        if intent.state == "DISPATCHING" and (
            intent.dispatch_state is not None
            or intent.provider_identity is not None
            or intent.outcome_code is not None
        ):
            raise FactorExecutionError("DISPATCHING_RECOVERY_RESULT_ALREADY_PRESENT")
        if intent.state == "KNOWN" and (
            intent.dispatch_state is not None
            or intent.provider_identity is not None
            or intent.outcome_code is not None
        ):
            raise FactorExecutionError("DISPATCHING_RECOVERY_RESULT_ALREADY_PRESENT")

        expected_session, query_set = self._validate_unknown_recovery_snapshot(
            facts,
            refresh_receipt,
            observation,
            minimum_query_started_at=recovery_started_at,
        )
        identity = intent.original_identity
        if (
            identity.get("operation") != "insert"
            or identity.get("instrument_id") != observation.instrument
            or identity.get("exchange_id") != observation.exchange
            or identity.get("order_ref") != observation.order_ref
            or identity.get("trading_day") != observation.trading_day
            or identity.get("account_fingerprint") != observation.account_fingerprint
            or identity.get("account_fingerprint") != expected_session["account_fingerprint"]
            or query_set.trading_day != identity.get("trading_day")
            or not _positive_int(identity.get("connection_generation"))
            or not _positive_int(identity.get("front_id"))
            or not _positive_int(identity.get("session_id"))
            or observation.front_id != identity.get("front_id")
            or observation.session_id != identity.get("session_id")
            or (
                identity.get("order_sys_id") is not None
                and identity.get("order_sys_id") != observation.order_sys_id
            )
        ):
            raise FactorExecutionError("DISPATCHING_ORIGINAL_ORDER_LINEAGE_MISMATCH")

        expected_terminal = {
            "5": ("CANCELED", "CANCELLED"),
            "4": ("NO_TRADE_NOT_QUEUEING", "REJECTED"),
        }.get(observation.terminal_status)
        original_volume = observation.volume_total_original
        traded_volume = observation.volume_traded
        remaining_volume = observation.volume_total
        requested_volume = _decimal_optional(intent.economic_payload.get("quantity"))
        if (
            expected_terminal is None
            or observation.terminal_state != expected_terminal[0]
            or any(
                not isinstance(value, Decimal) or not value.is_finite()
                for value in (original_volume, traded_volume, remaining_volume)
            )
            or requested_volume is None
            or requested_volume != original_volume
            or original_volume <= 0
            or original_volume != original_volume.to_integral_value()
            or traded_volume != 0
            or remaining_volume != original_volume
        ):
            raise FactorExecutionError("DISPATCHING_TERMINAL_NO_FILL_NOT_PROVEN")

        trade_rows = self._validate_unknown_recovery_row_projection(
            facts,
            observation,
            intent,
            unresolved_state="DISPATCHING",
            allow_exact_local_unknown=False,
        )
        if any(
            row.order_ref == observation.order_ref
            and row.instrument == observation.instrument
            and row.exchange == observation.exchange
            for row in trade_rows
        ):
            raise FactorExecutionError("DISPATCHING_TERMINAL_CONFLICTS_WITH_TRADE_QUERY")

        positions = [
            row
            for row in facts.positions
            if row.instrument == observation.instrument and row.exchange == observation.exchange
        ]
        if len(positions) != 1 or not _terminal_position_consistent(positions[0], facts):
            raise FactorExecutionError("DISPATCHING_POSITION_RECONCILIATION_MISMATCH")
        position = positions[0]
        broker_and_ctp_flat = (
            position.quantity == 0
            and position.broker_quantity == 0
            and position.long_quantity == 0
            and position.short_quantity == 0
            and position.attributed_signed_quantity in (None, Decimal("0"))
        )
        book_flat = (
            position.position_book_status == "FLAT"
            and position.position_book_blocker_code is None
            and position.owner_intent_id is None
            and position.owner_strategy_scope is None
        )
        pending_owner_is_this_dispatch = (
            broker_and_ctp_flat
            and position.position_book_status == "UNKNOWN"
            and position.position_book_blocker_code == "INSTRUMENT_ORDER_UNRESOLVED"
            and position.owner_intent_id is None
            and position.owner_strategy_scope is None
            and self._dispatching_pending_owner_is_exact(intent, observation)
        )
        if (
            not broker_and_ctp_flat
            or not (book_flat or pending_owner_is_this_dispatch)
            or any(
                row.instrument == observation.instrument and row.exchange == observation.exchange
                for row in facts.working_orders
            )
        ):
            raise FactorExecutionError("DISPATCHING_POSITION_NOT_FLAT_OR_ROUTE_NOT_CLEAR")

        route = self.store.registered_sim_route_eligibility(
            observation.instrument, observation.exchange
        )
        if (
            route.instrument_id != observation.instrument
            or route.exchange_id != observation.exchange
            or route.account_fingerprint != expected_session["account_fingerprint"]
            or route.connection_generation != expected_session["connection_generation"]
            or route.trading_day != expected_session["trading_day"]
            or route.current_session_account_fingerprint != expected_session["account_fingerprint"]
            or route.current_session_connection_generation
            != expected_session["connection_generation"]
            or route.current_session_trading_day != expected_session["trading_day"]
            or route.current_session_front_id != expected_session["front_id"]
            or route.current_session_id != expected_session["session_id"]
            or route.current_session_read_only_ready is not True
            or route.instrument_query_complete is not True
            or route.instrument_eligible is not True
            or route.sdk_capability_armed is not False
            or route.dispatching_order_ids != ()
            or route.unknown_order_ids != ()
        ):
            raise FactorExecutionError("DISPATCHING_RECOVERY_SESSION_OR_ROUTE_MISMATCH")

        terminal_state = expected_terminal[1]
        provider_identity = {
            "evidence_kind": "complete_orders_query_dispatching_no_fill_terminal",
            "intent_id": intent.intent_id,
            "account_scope": self.account_scope,
            "strategy_scope": self.strategy_scope,
            "observation_id": observation.observation_id,
            "terminal_event_id": observation.observation_id,
            "query_set_id": query_set.query_set_id,
            "snapshot_id": facts.snapshot_id,
            "orders_request_id": observation.request_id,
            "query_family_request_ids": query_set.query_ids,
            "query_set_started_at": _utc_text(query_set.started_at_utc),
            "query_set_completed_at": _utc_text(query_set.completed_at_utc),
            "refresh_started_at": _utc_text(refresh_receipt.started_at),
            "refresh_completed_at": _utc_text(refresh_receipt.completed_at),
            "orders_completed_at": _utc_text(observation.available_at),
            "connection_generation": observation.connection_generation,
            "account_fingerprint": observation.account_fingerprint,
            "trading_day": observation.trading_day,
            "terminal_status": observation.terminal_status,
            "terminal_state": observation.terminal_state,
            "volume_total_original": str(original_volume),
            "volume_traded": str(traded_volume),
            "volume_total": str(remaining_volume),
            "order_ref": observation.order_ref,
            "order_sys_id": observation.order_sys_id,
            "front_id": observation.front_id,
            "session_id": observation.session_id,
            "instrument": observation.instrument,
            "exchange": observation.exchange,
            "position_flat": True,
            "broker_quantity": str(position.broker_quantity),
            "ctp_long_quantity": str(position.long_quantity),
            "ctp_short_quantity": str(position.short_quantity),
            "position_snapshot_id": position.snapshot_id,
            "position_available_at": _utc_text(position.available_at),
            "original_account_fingerprint": identity["account_fingerprint"],
            "original_connection_generation": identity["connection_generation"],
            "original_trading_day": identity["trading_day"],
            "original_order_ref": identity["order_ref"],
            "original_front_id": identity["front_id"],
            "original_session_id": identity["session_id"],
            "matching_trade_count": 0,
        }
        reconciliation_id = _unknown_terminal_reconciliation_id(
            intent.intent_id, observation.observation_id, query_set.query_set_id, facts.snapshot_id
        )
        reconciliation, _resolution = self.journal.record_dispatching_no_fill_terminal(
            intent.intent_id,
            reconciliation_id=reconciliation_id,
            query_id=observation.observation_id,
            provider_identity=provider_identity,
            terminal_state=terminal_state,
            terminal_event_id=observation.observation_id,
            position_snapshot_id=position.snapshot_id,
            expected_original_identity=identity,
        )
        try:
            retired = self.store.registered_sim_retire_unknown(
                intent.intent_id,
                reconciliation.reconciliation_id,
                original_identity=identity,
                expected_session=expected_session,
                terminal_event=None,
            )
        except Exception as error:
            raise FactorExecutionError("DISPATCHING_STORE_RETIREMENT_NOT_APPLIED") from error
        if getattr(retired, "status", None) not in ("QUEUED", "ALREADY_ABSENT"):
            raise FactorExecutionError("DISPATCHING_STORE_RETIREMENT_RESULT_INVALID")
        return ExecutionTerminalReconciliationItem(
            observation_id=observation.observation_id,
            status="RESOLVED",
            intent_id=intent.intent_id,
            reconciliation_id=reconciliation.reconciliation_id,
        )

    def _replay_known_dispatching_no_fill_terminal(
        self,
        facts: Any,
        observation: Any,
        intent: ExecutionIntentRecord,
        *,
        refresh_receipt: Any,
    ) -> ExecutionTerminalReconciliationItem:
        """Reuse an exact durable no-fill result after Store retirement succeeded.

        The first recovery persists a KNOWN intent with NULL dispatch response,
        its terminal reconciliation, and the released owner atomically. Later
        account snapshots often repeat the same CTP terminal order. If the
        exact local UNKNOWN latch is gone, that read is a no-op replay and must
        not demand a recovery scope or rewrite the historical proof.
        """

        try:
            current = self.journal.intent(intent.intent_id)
            resolution = self.journal.instrument_resolution(intent.intent_id)
            if resolution is None:
                return self._blocked_known_no_fill_replay(
                    observation, intent, "DISPATCHING_NO_FILL_RESOLUTION_MISSING"
                )
            reconciliation = self.journal.reconciliation(resolution.reconciliation_id)
            if current is None or reconciliation is None:
                return self._blocked_known_no_fill_replay(
                    observation, intent, "DISPATCHING_NO_FILL_RECONCILIATION_MISSING"
                )
            if not self._known_no_fill_replay_matches(
                current, intent, resolution, reconciliation, observation
            ):
                return self._blocked_known_no_fill_replay(
                    observation,
                    intent,
                    "DISPATCHING_NO_FILL_REPLAY_CONFLICT",
                    reconciliation_id=resolution.reconciliation_id,
                )
            route = self.store.registered_sim_route_eligibility(
                observation.instrument, observation.exchange
            )
            if (
                route.instrument_id != observation.instrument
                or route.exchange_id != observation.exchange
                or route.account_fingerprint != observation.account_fingerprint
                or route.trading_day != observation.trading_day
                or route.current_session_account_fingerprint != observation.account_fingerprint
                or route.current_session_connection_generation != observation.connection_generation
                or route.current_session_trading_day != observation.trading_day
                or route.current_session_read_only_ready is not True
            ):
                return self._blocked_known_no_fill_replay(
                    observation,
                    intent,
                    "DISPATCHING_UNKNOWN_LATCH_SCOPE_MISMATCH",
                    reconciliation_id=resolution.reconciliation_id,
                )
            unknown_ids = route.unknown_order_ids
            unknown_count = route.unknown_order_count
            if (
                type(unknown_ids) is not tuple
                or type(unknown_count) is not int
                or unknown_count != len(unknown_ids)
                or any(not _exact_identifier(value) for value in unknown_ids)
                or len(set(unknown_ids)) != len(unknown_ids)
            ):
                return self._blocked_known_no_fill_replay(
                    observation,
                    intent,
                    "DISPATCHING_UNKNOWN_LATCH_UNAVAILABLE",
                    reconciliation_id=resolution.reconciliation_id,
                )
            try:
                local_orders = execution_order_snapshot(self.broker)
            except Exception:
                return self._blocked_known_no_fill_replay(
                    observation,
                    intent,
                    "DISPATCHING_LOCAL_UNKNOWN_LATCH_UNAVAILABLE",
                    reconciliation_id=resolution.reconciliation_id,
                )
            exact_local = tuple(
                row
                for row in local_orders
                if row.external_order_ref == observation.order_ref
                and row.instrument_id == observation.instrument
                and row.exchange_id == observation.exchange
            )
            exact_unknown = tuple(
                row
                for row in exact_local
                if row.owner_intent_id == intent.intent_id and row.execution_unknown is True
            )
            if exact_local and len(exact_unknown) != len(exact_local):
                return self._blocked_known_no_fill_replay(
                    observation,
                    intent,
                    "DISPATCHING_LOCAL_ORDER_STATE_CONFLICT",
                    reconciliation_id=resolution.reconciliation_id,
                )
            has_latch = observation.order_ref in unknown_ids or bool(exact_unknown)
            if has_latch:
                if unknown_ids not in ((), (observation.order_ref,)):
                    return self._blocked_known_no_fill_replay(
                        observation,
                        intent,
                        "DISPATCHING_UNKNOWN_LATCH_SET_CONFLICT",
                        reconciliation_id=resolution.reconciliation_id,
                    )
                # The exact latch remains; the existing gated recovery path
                # revalidates the same fresh query before asking Store to retire it.
                return self._reconcile_dispatching_no_fill_terminal(
                    facts, observation, current, refresh_receipt=refresh_receipt
                )
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="RESOLVED",
                intent_id=intent.intent_id,
                reconciliation_id=resolution.reconciliation_id,
            )
        except ExecutionDecisionJournalError as error:
            code = error.code
        except Exception as error:
            observed_code = getattr(error, "code", None)
            code = (
                observed_code
                if _exact_identifier(observed_code)
                else ("DISPATCHING_NO_FILL_REPLAY_UNAVAILABLE")
            )
        return self._blocked_known_no_fill_replay(observation, intent, code)

    def _known_no_fill_replay_matches(
        self, current, original, resolution, reconciliation, observation
    ) -> bool:
        identity = dict(original.original_identity)
        stored_identity = dict(reconciliation.original_identity)
        provider = reconciliation.provider_identity
        expected_state = _terminal_state(observation.terminal_state)
        if not isinstance(provider, Mapping):
            return False
        request = _decimal_optional(original.economic_payload.get("quantity"))
        observed_volumes = (
            observation.volume_total_original,
            observation.volume_traded,
            observation.volume_total,
        )
        stored_volumes = tuple(
            _decimal_optional(provider.get(name))
            for name in ("volume_total_original", "volume_traded", "volume_total")
        )
        return bool(
            current.intent_id == original.intent_id
            and current.key == original.key
            and dict(current.original_identity) == identity
            and current.state == "KNOWN"
            and current.dispatch_state is None
            and current.provider_identity is None
            and current.outcome_code is None
            and original.key.action == "SUBMIT"
            and original.key.position_effect == "OPEN"
            and identity.get("operation") == "insert"
            and resolution.intent_id == original.intent_id
            and resolution.account_scope == self.account_scope
            and resolution.instrument == observation.instrument
            and resolution.terminal_state == expected_state
            and resolution.terminal_event_id == reconciliation.terminal_event_id
            and resolution.position_flat is True
            and reconciliation.intent_id == original.intent_id
            and reconciliation.state == "KNOWN"
            and reconciliation.terminal_state == expected_state
            and reconciliation.terminal_event_id == reconciliation.query_id
            and reconciliation.outcome_code == "complete_orders_query_dispatching_no_fill_terminal"
            and reconciliation.position_flat is True
            and reconciliation.position_snapshot_id == resolution.position_snapshot_id
            and dict(stored_identity) == identity
            and provider.get("evidence_kind")
            == "complete_orders_query_dispatching_no_fill_terminal"
            and provider.get("intent_id") == original.intent_id
            and provider.get("account_scope") == self.account_scope
            and provider.get("strategy_scope") == self.strategy_scope
            and provider.get("observation_id") == reconciliation.query_id
            and provider.get("terminal_event_id") == reconciliation.terminal_event_id
            and provider.get("query_set_id") is not None
            and provider.get("snapshot_id") == reconciliation.position_snapshot_id
            and provider.get("position_snapshot_id") == resolution.position_snapshot_id
            and provider.get("position_flat") is True
            and provider.get("account_fingerprint") == identity.get("account_fingerprint")
            and provider.get("original_account_fingerprint") == identity.get("account_fingerprint")
            and provider.get("original_connection_generation")
            == identity.get("connection_generation")
            and provider.get("original_trading_day") == identity.get("trading_day")
            and provider.get("original_order_ref") == identity.get("order_ref")
            and provider.get("original_front_id") == identity.get("front_id")
            and provider.get("original_session_id") == identity.get("session_id")
            and provider.get("trading_day") == observation.trading_day
            and observation.trading_day == identity.get("trading_day")
            and provider.get("order_ref") == observation.order_ref == identity.get("order_ref")
            and provider.get("instrument")
            == observation.instrument
            == identity.get("instrument_id")
            and provider.get("exchange") == observation.exchange == identity.get("exchange_id")
            and provider.get("front_id") == observation.front_id == identity.get("front_id")
            and provider.get("session_id") == observation.session_id == identity.get("session_id")
            and provider.get("order_sys_id") == observation.order_sys_id
            and provider.get("terminal_status") == observation.terminal_status
            and provider.get("terminal_state") == observation.terminal_state
            and expected_state in ("CANCELLED", "REJECTED")
            and request is not None
            and request == stored_volumes[0] == observed_volumes[0]
            and Decimal(0) == stored_volumes[1] == observed_volumes[1]
            and stored_volumes[2] == observed_volumes[2] == request
            and provider.get("matching_trade_count") == 0
        )

    @staticmethod
    def _blocked_known_no_fill_replay(
        observation, intent, code, *, reconciliation_id=None
    ) -> ExecutionTerminalReconciliationItem:
        return ExecutionTerminalReconciliationItem(
            observation_id=observation.observation_id,
            status="BLOCKED",
            intent_id=intent.intent_id,
            reconciliation_id=reconciliation_id,
            blocker_code=code,
        )

    def _current_terminal_recovery_scope(self) -> Optional[_TerminalRecoveryScopeState]:
        scope = self._terminal_recovery_scope_state.get()
        if (
            not isinstance(scope, _TerminalRecoveryScopeState)
            or scope.coordinator is not self
            or scope.journal is not self.journal
            or self._active_terminal_recovery_scope_state is not scope
            or scope.thread_id != get_ident()
            or getattr(scope.lease, "cross_process", None) is not True
            or _aware_utc(scope.started_at) is None
        ):
            return None
        return scope

    def _dispatching_pending_owner_is_exact(
        self, intent: ExecutionIntentRecord, observation: Any
    ) -> bool:
        """Allow only the exact DISPATCHING OPEN's own empty-book reservation."""

        if (
            intent.state != "DISPATCHING"
            or intent.key.action != "SUBMIT"
            or intent.key.position_effect != "OPEN"
            or intent.key.instrument != observation.instrument
            or intent.original_identity.get("operation") != "insert"
            or intent.original_identity.get("instrument_id") != observation.instrument
            or intent.original_identity.get("exchange_id") != observation.exchange
            or intent.original_identity.get("order_ref") != observation.order_ref
        ):
            return False
        try:
            owner = self.journal.active_instrument_owner(self.account_scope, observation.instrument)
            owner_intent = None if owner is None else self.journal.intent(owner.intent_id)
        except Exception:
            return False
        return bool(
            owner is not None
            and owner.account_scope == self.account_scope
            and owner.instrument == observation.instrument
            and owner.intent_id == intent.intent_id
            and owner.state == "DISPATCHING"
            and owner.cancel_intent_id is None
            and owner_intent is not None
            and owner_intent.intent_id == intent.intent_id
            and owner_intent.state == "DISPATCHING"
            and owner_intent.dispatch_state is None
            and owner_intent.provider_identity is None
            and owner_intent.outcome_code is None
            and owner_intent.key == intent.key
            and owner_intent.key.action == "SUBMIT"
            and owner_intent.key.position_effect == "OPEN"
            and owner_intent.original_identity == intent.original_identity
        )

    def _dispatching_cancel_pending_owner_is_exact(
        self, submit_intent: ExecutionIntentRecord, cancel_intent_id: str, observation: Any
    ) -> bool:
        """Allow the exact pending cancel pair to explain its own Book uncertainty."""

        if (
            submit_intent.key.action != "SUBMIT"
            or submit_intent.state != "KNOWN"
            or submit_intent.dispatch_state != "KNOWN"
            or submit_intent.key.instrument != observation.instrument
        ):
            return False
        try:
            owner = self.journal.active_instrument_owner(self.account_scope, observation.instrument)
            cancel_intent = self.journal.intent(cancel_intent_id)
        except Exception:
            return False
        if owner is None or cancel_intent is None:
            return False
        parent_identity = submit_intent.original_identity
        cancel_identity = cancel_intent.original_identity
        return bool(
            owner.account_scope == self.account_scope
            and owner.instrument == observation.instrument
            and owner.intent_id == submit_intent.intent_id
            and owner.state == "KNOWN"
            and owner.cancel_intent_id == cancel_intent_id
            and cancel_intent.key.action == "CANCEL"
            and cancel_intent.key.instrument == observation.instrument
            and cancel_intent.owner_intent_id == submit_intent.intent_id
            and cancel_intent.state == "DISPATCHING"
            and cancel_intent.dispatch_state is None
            and cancel_intent.provider_identity is None
            and cancel_intent.outcome_code is None
            and isinstance(parent_identity, Mapping)
            and isinstance(cancel_identity, Mapping)
            and parent_identity.get("operation") == "insert"
            and cancel_identity.get("operation") == "cancel"
            and cancel_identity.get("owner_intent_id") == submit_intent.intent_id
            and all(
                parent_identity.get(name) == cancel_identity.get(name)
                for name in (
                    "account_fingerprint",
                    "connection_generation",
                    "trading_day",
                    "front_id",
                    "session_id",
                    "order_ref",
                    "instrument_id",
                    "exchange_id",
                )
            )
            and (
                "order_sys_id" not in cancel_identity
                or parent_identity.get("order_sys_id") == cancel_identity.get("order_sys_id")
            )
        )

    def _reconcile_unknown_no_fill_terminal(
        self, facts: Any, observation: Any, intent: ExecutionIntentRecord, *, refresh_receipt: Any
    ) -> ExecutionTerminalReconciliationItem:
        """Resolve one UNKNOWN insert from a complete current no-fill snapshot.

        The dispatch generation is retained as historical identity. Current
        query/session generation may change after a real reconnect, but the
        exact original account, trading day, route, OrderRef, FrontID and
        SessionID must still join the terminal CTP row.
        """
        try:
            expected_session, query_set = self._validate_unknown_recovery_snapshot(
                facts, refresh_receipt, observation
            )
        except FactorExecutionError as error:
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=intent.intent_id,
                blocker_code=error.code,
            )

        identity = intent.original_identity
        dispatch = intent.provider_identity
        if (
            intent.key.action != "SUBMIT"
            or intent.state not in ("UNKNOWN", "KNOWN")
            or intent.dispatch_state != "UNKNOWN"
            or not isinstance(dispatch, Mapping)
            or dispatch.get("operation") != "insert"
            or dispatch.get("status") != "UNKNOWN"
            or dispatch.get("resend_permitted") is not False
            or dispatch.get("instrument_id") != observation.instrument
            or dispatch.get("exchange_id") != observation.exchange
            or dispatch.get("order_ref") != observation.order_ref
            or dispatch.get("front_id") != identity.get("front_id")
            or dispatch.get("session_id") != identity.get("session_id")
            or identity.get("instrument_id") != observation.instrument
            or identity.get("exchange_id") != observation.exchange
            or identity.get("order_ref") != observation.order_ref
            or identity.get("operation") != "insert"
            or identity.get("trading_day") != observation.trading_day
            or identity.get("account_fingerprint") != observation.account_fingerprint
            or identity.get("account_fingerprint") != expected_session["account_fingerprint"]
            or not _positive_int(identity.get("connection_generation"))
            or not _positive_int(identity.get("front_id"))
            or not _positive_int(identity.get("session_id"))
            or observation.front_id != identity.get("front_id")
            or observation.session_id != identity.get("session_id")
            or (
                dispatch.get("order_sys_id") is not None
                and dispatch.get("order_sys_id") != observation.order_sys_id
            )
            or (
                identity.get("order_sys_id") is not None
                and identity.get("order_sys_id") != observation.order_sys_id
            )
        ):
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=intent.intent_id,
                blocker_code="UNKNOWN_ORIGINAL_ORDER_LINEAGE_MISMATCH",
            )

        # Recovery accepts only the exact CTP terminal codes with the full
        # order-volume tuple proving that no contract was filled.
        expected_terminal = {
            "5": ("CANCELED", "CANCELLED"),
            "4": ("NO_TRADE_NOT_QUEUEING", "REJECTED"),
        }.get(observation.terminal_status)
        original_volume = observation.volume_total_original
        traded_volume = observation.volume_traded
        remaining_volume = observation.volume_total
        intent_quantity = _decimal_optional(intent.economic_payload.get("quantity"))
        if (
            expected_terminal is None
            or observation.terminal_state != expected_terminal[0]
            or any(
                not isinstance(value, Decimal) or not value.is_finite()
                for value in (original_volume, traded_volume, remaining_volume)
            )
            or intent_quantity is None
            or intent_quantity != original_volume
            or original_volume <= 0
            or original_volume != original_volume.to_integral_value()
            or traded_volume != 0
            or remaining_volume != original_volume
        ):
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=intent.intent_id,
                blocker_code="UNKNOWN_TERMINAL_NO_FILL_NOT_PROVEN",
            )
        try:
            trade_rows = self._validate_unknown_recovery_row_projection(facts, observation, intent)
        except FactorExecutionError as error:
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=intent.intent_id,
                blocker_code=error.code,
            )
        if any(
            row.order_ref == observation.order_ref
            and row.instrument == observation.instrument
            and row.exchange == observation.exchange
            for row in trade_rows
        ):
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=intent.intent_id,
                blocker_code="UNKNOWN_TERMINAL_CONFLICTS_WITH_TRADE_QUERY",
            )

        positions = [
            row
            for row in facts.positions
            if row.instrument == observation.instrument and row.exchange == observation.exchange
        ]
        if len(positions) != 1 or not _terminal_position_consistent(positions[0], facts):
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=intent.intent_id,
                blocker_code="TERMINAL_POSITION_RECONCILIATION_MISMATCH",
            )
        position = positions[0]
        if (
            position.broker_quantity != 0
            or position.long_quantity != 0
            or position.short_quantity != 0
            or getattr(position, "attributed_signed_quantity", None) not in (None, Decimal("0"))
            or any(
                row.instrument == observation.instrument and row.exchange == observation.exchange
                for row in facts.working_orders
                if not self._is_exact_unknown_working_order(row, intent, observation)
            )
        ):
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=intent.intent_id,
                blocker_code="UNKNOWN_TERMINAL_ROUTE_NOT_FLAT_OR_CLEAR",
            )

        try:
            route = self.store.registered_sim_route_eligibility(
                observation.instrument, observation.exchange
            )
        except Exception:
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=intent.intent_id,
                blocker_code="UNKNOWN_RECOVERY_SESSION_UNOBSERVED",
            )
        if (
            route.instrument_id != observation.instrument
            or route.exchange_id != observation.exchange
            or route.account_fingerprint != expected_session["account_fingerprint"]
            or route.connection_generation != expected_session["connection_generation"]
            or route.trading_day != expected_session["trading_day"]
            or route.current_session_account_fingerprint != expected_session["account_fingerprint"]
            or route.current_session_connection_generation
            != expected_session["connection_generation"]
            or route.current_session_trading_day != expected_session["trading_day"]
            or route.current_session_front_id != expected_session["front_id"]
            or route.current_session_id != expected_session["session_id"]
            or route.current_session_read_only_ready is not True
            or route.instrument_query_complete is not True
            or route.instrument_eligible is not True
            or route.sdk_capability_armed is not False
            or route.dispatching_order_ids != ()
            or route.unknown_order_ids not in ((), (observation.order_ref,))
        ):
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=intent.intent_id,
                blocker_code="UNKNOWN_RECOVERY_SESSION_OR_ROUTE_MISMATCH",
            )

        terminal_state = expected_terminal[1]
        try:
            existing_resolution = self.journal.instrument_resolution(intent.intent_id)
            if existing_resolution is None:
                reconciliation_id = _unknown_terminal_reconciliation_id(
                    intent.intent_id,
                    observation.observation_id,
                    query_set.query_set_id,
                    facts.snapshot_id,
                )
                existing_reconciliation = None
            else:
                reconciliation_id = existing_resolution.reconciliation_id
                existing_reconciliation = self.journal.reconciliation(reconciliation_id)
        except Exception as error:
            raise FactorExecutionError("UNKNOWN_PRIOR_RECONCILIATION_UNAVAILABLE") from error
        provider_identity = {
            "evidence_kind": "complete_orders_query_unknown_no_fill_terminal",
            "observation_id": observation.observation_id,
            "query_set_id": query_set.query_set_id,
            "snapshot_id": facts.snapshot_id,
            "orders_request_id": observation.request_id,
            "connection_generation": observation.connection_generation,
            "account_fingerprint": observation.account_fingerprint,
            "trading_day": observation.trading_day,
            "terminal_status": observation.terminal_status,
            "terminal_state": observation.terminal_state,
            "volume_total_original": str(original_volume),
            "volume_traded": str(traded_volume),
            "volume_total": str(remaining_volume),
            "order_ref": observation.order_ref,
            "order_sys_id": observation.order_sys_id,
            "front_id": observation.front_id,
            "session_id": observation.session_id,
            "instrument": observation.instrument,
            "exchange": observation.exchange,
            "broker_quantity": str(position.broker_quantity),
            "ctp_long_quantity": str(position.long_quantity),
            "ctp_short_quantity": str(position.short_quantity),
            "position_snapshot_id": position.snapshot_id,
            "position_available_at": _utc_text(position.available_at),
            "original_account_fingerprint": identity["account_fingerprint"],
            "original_connection_generation": identity["connection_generation"],
            "original_trading_day": identity["trading_day"],
            "original_order_ref": identity["order_ref"],
            "original_front_id": identity["front_id"],
            "original_session_id": identity["session_id"],
        }
        try:
            if existing_resolution is None:
                self.journal.record_reconciliation(
                    intent.intent_id,
                    reconciliation_id=reconciliation_id,
                    query_id=observation.observation_id,
                    state="KNOWN",
                    provider_identity=provider_identity,
                    outcome_code="complete_orders_query_unknown_no_fill_terminal",
                    terminal_state=terminal_state,
                    terminal_event_id=observation.observation_id,
                    position_snapshot_id=position.snapshot_id,
                    position_flat=True,
                )
            elif not _unknown_terminal_resolution_matches(
                existing_resolution,
                existing_reconciliation,
                account_scope=self.account_scope,
                identity=identity,
                observation=observation,
                terminal_state=terminal_state,
                volume_total_original=original_volume,
            ):
                return ExecutionTerminalReconciliationItem(
                    observation_id=observation.observation_id,
                    status="BLOCKED",
                    intent_id=intent.intent_id,
                    reconciliation_id=reconciliation_id,
                    blocker_code="UNKNOWN_PRIOR_RECONCILIATION_CONFLICT",
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
                blocker_code=code if _exact_identifier(code) else "UNKNOWN_RECOVERY_NOT_DURABLE",
            )

        terminal_event = self._unknown_terminal_broker_event(
            facts, intent, observation, original_volume
        )
        try:
            retired = self.store.registered_sim_retire_unknown(
                intent.intent_id,
                reconciliation_id,
                original_identity=identity,
                expected_session=expected_session,
                terminal_event=terminal_event,
            )
        except Exception:
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=intent.intent_id,
                reconciliation_id=reconciliation_id,
                blocker_code="UNKNOWN_STORE_RETIREMENT_NOT_APPLIED",
            )
        if getattr(retired, "status", None) not in ("QUEUED", "ALREADY_ABSENT"):
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=intent.intent_id,
                reconciliation_id=reconciliation_id,
                blocker_code="UNKNOWN_STORE_RETIREMENT_RESULT_INVALID",
            )
        return ExecutionTerminalReconciliationItem(
            observation_id=observation.observation_id,
            status="RESOLVED",
            intent_id=intent.intent_id,
            reconciliation_id=reconciliation_id,
        )

    def _reconcile_dispatching_cancel_terminal(
        self, facts, observation, submit_intent, cancel_intent, *, refresh_receipt
    ):
        """Commit exact terminal evidence, then assert fresh Store absence."""
        try:
            evidence = self._dispatching_cancel_terminal_evidence(
                facts,
                observation,
                submit_intent,
                cancel_intent.intent_id,
                refresh_receipt=refresh_receipt,
            )
            owner = self.journal.active_instrument_owner(
                self.account_scope, submit_intent.key.instrument
            )
        except FactorExecutionError as error:
            return self._blocked_dispatching_cancel(observation, submit_intent, error.code)
        except Exception as error:
            code = getattr(error, "code", None)
            return self._blocked_dispatching_cancel(
                observation,
                submit_intent,
                code if _exact_identifier(code) else "CANCEL_DISPATCHING_EVIDENCE_UNAVAILABLE",
            )

        parent_identity = submit_intent.original_identity
        cancel_identity = cancel_intent.original_identity
        if (
            owner is None
            or owner.intent_id != submit_intent.intent_id
            or owner.cancel_intent_id != cancel_intent.intent_id
            or submit_intent.key.action != "SUBMIT"
            or submit_intent.state != "KNOWN"
            or submit_intent.dispatch_state != "KNOWN"
            or submit_intent.provider_identity is None
            or cancel_intent.key.action != "CANCEL"
            or cancel_intent.owner_intent_id != submit_intent.intent_id
            or cancel_intent.state != "DISPATCHING"
            or cancel_intent.dispatch_state is not None
            or cancel_intent.provider_identity is not None
            or cancel_intent.outcome_code is not None
            or not self._dispatching_cancel_original_identity_matches(
                submit_intent, cancel_intent.intent_id, observation, evidence["query_set"]
            )
        ):
            return self._blocked_dispatching_cancel(
                observation, submit_intent, "CANCEL_DISPATCHING_LINEAGE_MISMATCH"
            )

        query_set = evidence["query_set"]
        position = evidence["position"]
        parent_reconciliation_id, cancel_reconciliation_id = _dispatching_cancel_reconciliation_ids(
            submit_intent.intent_id,
            cancel_intent.intent_id,
            observation.observation_id,
            query_set.query_set_id,
            facts.snapshot_id,
        )
        common = evidence["current_identity"]
        parent_provider_identity = {
            "evidence_kind": "complete_orders_query_observation",
            "parent_intent_id": submit_intent.intent_id,
            "cancel_intent_id": cancel_intent.intent_id,
            "parent_reconciliation_id": parent_reconciliation_id,
            "cancel_reconciliation_id": cancel_reconciliation_id,
            **common,
        }
        cancel_provider_identity = {
            "evidence_kind": "complete_orders_query_cancel_dispatching_terminal",
            "parent_intent_id": submit_intent.intent_id,
            "cancel_intent_id": cancel_intent.intent_id,
            "parent_reconciliation_id": parent_reconciliation_id,
            "cancel_reconciliation_id": cancel_reconciliation_id,
            **common,
        }
        try:
            _child, _parent, resolution = self.journal.record_dispatching_cancel_terminal(
                submit_intent.intent_id,
                cancel_intent.intent_id,
                parent_reconciliation_id=parent_reconciliation_id,
                cancel_reconciliation_id=cancel_reconciliation_id,
                query_id=observation.observation_id,
                parent_provider_identity=parent_provider_identity,
                cancel_provider_identity=cancel_provider_identity,
                terminal_state="CANCELLED",
                terminal_event_id=observation.observation_id,
                position_snapshot_id=position.snapshot_id,
                position_flat=position.broker_quantity == 0,
                expected_parent_original_identity=parent_identity,
                expected_cancel_original_identity=cancel_identity,
            )
        except Exception as error:
            code = getattr(error, "code", None)
            return self._blocked_dispatching_cancel(
                observation,
                submit_intent,
                code if _exact_identifier(code) else "CANCEL_DISPATCHING_CAS_NOT_COMMITTED",
            )

        # Do not hold SQLite's transaction while taking Store/wrapper locks.
        return self._assert_and_record_dispatching_cancel_absence(
            facts,
            observation,
            submit_intent,
            cancel_intent.intent_id,
            resolution.reconciliation_id,
            cancel_reconciliation_id,
            evidence,
        )

    def _retry_dispatching_cancel_store_absence(
        self,
        facts,
        observation,
        submit_intent,
        resolution,
        parent_reconciliation,
        *,
        refresh_receipt,
    ):
        """Validate immutable CAS proof and retry only the read-only absence check."""
        provider = parent_reconciliation.provider_identity
        cancel_intent_id = _exact_identifier(provider.get("cancel_intent_id"))
        cancel_reconciliation_id = _exact_identifier(provider.get("cancel_reconciliation_id"))
        if cancel_intent_id is None or cancel_reconciliation_id is None:
            return self._blocked_dispatching_cancel(
                observation, submit_intent, "CANCEL_DISPATCHING_REPLAY_BINDING_INVALID"
            )
        try:
            cancel_intent = self.journal.intent(cancel_intent_id)
            child = self.journal.reconciliation(cancel_reconciliation_id)
            evidence = self._dispatching_cancel_terminal_evidence(
                facts,
                observation,
                submit_intent,
                cancel_intent_id,
                refresh_receipt=refresh_receipt,
            )
            current_owner = self.journal.active_instrument_owner(
                self.account_scope, submit_intent.key.instrument
            )
        except FactorExecutionError as error:
            return self._blocked_dispatching_cancel(
                observation,
                submit_intent,
                error.code,
                reconciliation_id=resolution.reconciliation_id,
            )
        except Exception as error:
            code = getattr(error, "code", None)
            return self._blocked_dispatching_cancel(
                observation,
                submit_intent,
                code
                if _exact_identifier(code)
                else "CANCEL_DISPATCHING_REPLAY_EVIDENCE_UNAVAILABLE",
                reconciliation_id=resolution.reconciliation_id,
            )

        child_provider = child.provider_identity if child is not None else {}
        fields = (
            "cancel_recovery_kind",
            "parent_intent_id",
            "cancel_intent_id",
            "order_ref",
            "order_sys_id",
            "instrument",
            "exchange",
            "terminal_status",
            "terminal_state",
            "volume_total_original",
            "volume_traded",
            "volume_total",
            "front_id",
            "session_id",
            "original_account_fingerprint",
            "original_connection_generation",
            "original_trading_day",
            "original_order_ref",
            "original_front_id",
            "original_session_id",
            "matching_trade_count",
            "matching_trade_volume",
            "matching_trade_digest",
            "broker_quantity",
            "ctp_long_quantity",
            "ctp_short_quantity",
            "attributed_signed_quantity",
            "position_book_owner_intent_id",
            "opening_fee_total",
            "opening_fees_known",
        )
        current = evidence["current_identity"]
        if (
            cancel_intent is None
            or cancel_intent.key.action != "CANCEL"
            or cancel_intent.owner_intent_id != submit_intent.intent_id
            or cancel_intent.state != "KNOWN"
            or cancel_intent.dispatch_state is not None
            or cancel_intent.provider_identity is not None
            or cancel_intent.outcome_code is not None
            or child is None
            or child.intent_id != cancel_intent_id
            or child.state != "KNOWN"
            or child.outcome_code != "complete_orders_query_cancel_dispatching_terminal"
            or child.terminal_state != "CANCELLED"
            or child.terminal_event_id != child.query_id
            or child.position_snapshot_id != resolution.position_snapshot_id
            or child.position_flat is not resolution.position_flat
            or not isinstance(child_provider, Mapping)
            or child_provider.get("evidence_kind")
            != "complete_orders_query_cancel_dispatching_terminal"
            or child_provider.get("parent_reconciliation_id") != resolution.reconciliation_id
            or child_provider.get("cancel_reconciliation_id") != cancel_reconciliation_id
            or resolution.intent_id != submit_intent.intent_id
            or resolution.account_scope != self.account_scope
            or resolution.instrument != observation.instrument
            or resolution.terminal_state != "CANCELLED"
            or parent_reconciliation.intent_id != submit_intent.intent_id
            or parent_reconciliation.state != "KNOWN"
            or parent_reconciliation.outcome_code != "complete_orders_query_terminal"
            or parent_reconciliation.terminal_state != "CANCELLED"
            or parent_reconciliation.terminal_event_id != parent_reconciliation.query_id
            or parent_reconciliation.position_snapshot_id != resolution.position_snapshot_id
            or parent_reconciliation.position_flat is not resolution.position_flat
            or not isinstance(provider, Mapping)
            or provider.get("evidence_kind") != "complete_orders_query_observation"
            or provider.get("cancel_recovery_kind") != "dispatching_cancel"
            or provider.get("cancel_reconciliation_id") != cancel_reconciliation_id
            or provider.get("observation_id") != parent_reconciliation.query_id
            or provider.get("observation_id") != parent_reconciliation.terminal_event_id
            or provider.get("position_snapshot_id") != resolution.position_snapshot_id
            or provider.get("position_flat") is not resolution.position_flat
            or provider.get("parent_reconciliation_id") != resolution.reconciliation_id
            or provider.get("cancel_intent_id") != cancel_intent_id
            or any(provider.get(name) != current.get(name) for name in fields)
            or any(child_provider.get(name) != current.get(name) for name in fields)
            or current_owner is not None
        ):
            return self._blocked_dispatching_cancel(
                observation,
                submit_intent,
                "CANCEL_DISPATCHING_REPLAY_CONFLICT",
                reconciliation_id=resolution.reconciliation_id,
            )

        acknowledgement_id, acknowledgement_query_id = _dispatching_cancel_absence_ack_ids(
            submit_intent.intent_id,
            cancel_intent_id,
            resolution.reconciliation_id,
            cancel_reconciliation_id,
        )
        try:
            acknowledgement = self.journal.reconciliation(acknowledgement_id)
        except Exception:
            return self._blocked_dispatching_cancel(
                observation,
                submit_intent,
                "CANCEL_DISPATCHING_ABSENCE_ACK_LOOKUP_FAILED",
                reconciliation_id=resolution.reconciliation_id,
            )
        if acknowledgement is not None:
            if not _dispatching_cancel_absence_ack_record_matches(
                acknowledgement,
                parent_intent_id=submit_intent.intent_id,
                cancel_intent_id=cancel_intent_id,
                parent_reconciliation_id=resolution.reconciliation_id,
                cancel_reconciliation_id=cancel_reconciliation_id,
                original_identity=submit_intent.original_identity,
                acknowledgement_id=acknowledgement_id,
                acknowledgement_query_id=acknowledgement_query_id,
            ):
                return self._blocked_dispatching_cancel(
                    observation,
                    submit_intent,
                    "CANCEL_DISPATCHING_ABSENCE_ACK_CONFLICT",
                    reconciliation_id=resolution.reconciliation_id,
                )
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="RESOLVED",
                intent_id=submit_intent.intent_id,
                reconciliation_id=resolution.reconciliation_id,
            )

        return self._assert_and_record_dispatching_cancel_absence(
            facts,
            observation,
            submit_intent,
            cancel_intent_id,
            resolution.reconciliation_id,
            cancel_reconciliation_id,
            evidence,
        )

    def _dispatching_cancel_absence_ack_status(
        self, submit_intent, resolution, parent_reconciliation
    ):
        provider = parent_reconciliation.provider_identity
        if not isinstance(provider, Mapping):
            return False
        cancel_intent_id = _exact_identifier(provider.get("cancel_intent_id"))
        cancel_reconciliation_id = _exact_identifier(provider.get("cancel_reconciliation_id"))
        parent_reconciliation_id = _exact_identifier(resolution.reconciliation_id)
        if (
            cancel_intent_id is None
            or cancel_reconciliation_id is None
            or parent_reconciliation_id is None
            or provider.get("parent_intent_id") != submit_intent.intent_id
            or provider.get("parent_reconciliation_id") != parent_reconciliation_id
        ):
            return False
        acknowledgement_id, acknowledgement_query_id = _dispatching_cancel_absence_ack_ids(
            submit_intent.intent_id,
            cancel_intent_id,
            parent_reconciliation_id,
            cancel_reconciliation_id,
        )
        try:
            acknowledgement = self.journal.reconciliation(acknowledgement_id)
        except Exception:
            return False
        if acknowledgement is None:
            return None
        return _dispatching_cancel_absence_ack_record_matches(
            acknowledgement,
            parent_intent_id=submit_intent.intent_id,
            cancel_intent_id=cancel_intent_id,
            parent_reconciliation_id=parent_reconciliation_id,
            cancel_reconciliation_id=cancel_reconciliation_id,
            original_identity=submit_intent.original_identity,
            acknowledgement_id=acknowledgement_id,
            acknowledgement_query_id=acknowledgement_query_id,
        )

    def _assert_and_record_dispatching_cancel_absence(
        self,
        facts,
        observation,
        submit_intent,
        cancel_intent_id,
        parent_reconciliation_id,
        cancel_reconciliation_id,
        evidence,
    ):
        acknowledgement_id, acknowledgement_query_id = _dispatching_cancel_absence_ack_ids(
            submit_intent.intent_id,
            cancel_intent_id,
            parent_reconciliation_id,
            cancel_reconciliation_id,
        )
        try:
            absence = self.store.registered_sim_assert_original_order_absent(
                original_identity=submit_intent.original_identity,
                expected_session=evidence["expected_session"],
            )
        except Exception:
            return self._blocked_dispatching_cancel(
                observation,
                submit_intent,
                "CANCEL_DISPATCHING_STORE_ABSENCE_NOT_PROVEN",
                reconciliation_id=parent_reconciliation_id,
            )
        if absence != "ALREADY_ABSENT":
            return self._blocked_dispatching_cancel(
                observation,
                submit_intent,
                "CANCEL_DISPATCHING_STORE_ABSENCE_RESULT_INVALID",
                reconciliation_id=parent_reconciliation_id,
            )
        expected_session = evidence["expected_session"]
        original_identity = dict(submit_intent.original_identity)
        acknowledgement_provider = {
            "evidence_kind": "LOCAL_STORE_ABSENCE",
            "cancel_recovery_kind": "dispatching_cancel_store_absence_ack",
            "store_assertion": absence,
            "parent_intent_id": submit_intent.intent_id,
            "cancel_intent_id": cancel_intent_id,
            "parent_reconciliation_id": parent_reconciliation_id,
            "cancel_reconciliation_id": cancel_reconciliation_id,
            "cas_parent_reconciliation_id": parent_reconciliation_id,
            "cas_cancel_reconciliation_id": cancel_reconciliation_id,
            "acknowledgement_query_id": acknowledgement_query_id,
            "query_observation_id": observation.observation_id,
            "query_set_id": evidence["query_set"].query_set_id,
            "snapshot_id": facts.snapshot_id,
            "original_identity": original_identity,
            "original_order_ref": original_identity.get("order_ref"),
            "instrument": observation.instrument,
            "exchange": observation.exchange,
            "current_session": dict(expected_session),
        }
        try:
            acknowledgement = self.journal.record_reconciliation(
                submit_intent.intent_id,
                reconciliation_id=acknowledgement_id,
                query_id=acknowledgement_query_id,
                state="KNOWN",
                provider_identity=acknowledgement_provider,
                outcome_code="LOCAL_STORE_ABSENCE",
            )
        except Exception:
            return self._blocked_dispatching_cancel(
                observation,
                submit_intent,
                "CANCEL_DISPATCHING_ABSENCE_ACK_NOT_DURABLE",
                reconciliation_id=parent_reconciliation_id,
            )
        if not _dispatching_cancel_absence_ack_record_matches(
            acknowledgement,
            parent_intent_id=submit_intent.intent_id,
            cancel_intent_id=cancel_intent_id,
            parent_reconciliation_id=parent_reconciliation_id,
            cancel_reconciliation_id=cancel_reconciliation_id,
            original_identity=original_identity,
            acknowledgement_id=acknowledgement_id,
            acknowledgement_query_id=acknowledgement_query_id,
        ):
            return self._blocked_dispatching_cancel(
                observation,
                submit_intent,
                "CANCEL_DISPATCHING_ABSENCE_ACK_CONFLICT",
                reconciliation_id=parent_reconciliation_id,
            )
        return ExecutionTerminalReconciliationItem(
            observation_id=observation.observation_id,
            status="RESOLVED",
            intent_id=submit_intent.intent_id,
            reconciliation_id=parent_reconciliation_id,
        )

    def _dispatching_cancel_terminal_evidence(
        self, facts, observation, submit_intent, cancel_intent_id, *, refresh_receipt
    ):
        """Validate complete fresh query, fill, position, and route proof."""

        scope = self._current_terminal_recovery_scope()
        if scope is None:
            raise FactorExecutionError("DISPATCHING_RECOVERY_SCOPE_REQUIRED")
        expected_session, query_set = self._validate_unknown_recovery_snapshot(
            facts,
            refresh_receipt,
            observation,
            minimum_query_started_at=scope.started_at,
        )
        # The validator above requires this exact current SDK session to be
        # read-only-ready. Preserve that observed fact in the durable marker
        # and local-absence acknowledgement session projection.
        expected_session = {**expected_session, "read_only_ready": True}
        identity = submit_intent.original_identity
        if not self._dispatching_cancel_original_identity_matches(
            submit_intent, cancel_intent_id, observation, query_set
        ):
            raise FactorExecutionError("CANCEL_DISPATCHING_ORIGINAL_IDENTITY_MISMATCH")
        if (
            observation.evidence_kind != "complete_orders_query_observation"
            or observation.terminal_status != "5"
            or observation.terminal_state != "CANCELED"
            or observation.account_fingerprint != expected_session["account_fingerprint"]
            or observation.connection_generation != expected_session["connection_generation"]
            or observation.trading_day != expected_session["trading_day"]
            or facts.account is None
            or facts.account.account_fingerprint != expected_session["account_fingerprint"]
            or facts.account.connection_generation != expected_session["connection_generation"]
            or facts.account.trading_day != expected_session["trading_day"]
        ):
            raise FactorExecutionError("CANCEL_DISPATCHING_TERMINAL_ROW_MISMATCH")

        volume_total_original = observation.volume_total_original
        volume_traded = observation.volume_traded
        volume_total = observation.volume_total
        requested = _decimal_optional(submit_intent.economic_payload.get("quantity"))
        if (
            any(
                not isinstance(value, Decimal)
                or not value.is_finite()
                or value != value.to_integral_value()
                for value in (volume_total_original, volume_traded, volume_total)
            )
            or requested is None
            or requested != volume_total_original
            or volume_total_original <= 0
            or volume_traded < 0
            or volume_traded >= volume_total_original
            or volume_total <= 0
            or volume_total_original - volume_traded != volume_total
        ):
            raise FactorExecutionError("CANCEL_DISPATCHING_VOLUME_TUPLE_INVALID")

        trade_rows = self._validate_unknown_recovery_row_projection(
            facts,
            observation,
            submit_intent,
            unresolved_intent_id=cancel_intent_id,
            unresolved_state="DISPATCHING",
            cancel_intent_id=cancel_intent_id,
            allow_exact_local_unknown=False,
        )
        matching_trades = tuple(
            row
            for row in trade_rows
            if row.order_ref == observation.order_ref
            and row.instrument == observation.instrument
            and row.exchange == observation.exchange
        )
        matching_volume = sum((row.volume for row in matching_trades), Decimal(0))
        if matching_volume != volume_traded or any(
            row.trading_day != identity.get("trading_day")
            or row.side != submit_intent.key.side
            or row.position_effect != submit_intent.key.position_effect
            or (
                observation.order_sys_id is not None
                and row.order_sys_id != observation.order_sys_id
            )
            for row in matching_trades
        ):
            raise FactorExecutionError("CANCEL_DISPATCHING_TRADE_VOLUME_MISMATCH")

        trade_page = self.trade_reconciliation_snapshot(facts, limit=512, offset=0)
        if (
            trade_page.offset != 0
            or trade_page.truncated
            or trade_page.next_offset is not None
            or trade_page.observation_count != len(trade_page.items)
            or trade_page.observation_count != len(trade_rows)
        ):
            raise FactorExecutionError("CANCEL_DISPATCHING_TRADE_PROOF_INCOMPLETE")
        trade_status = {item.observation_id: item for item in trade_page.items}
        proof_rows = []
        for row in matching_trades:
            status = trade_status.get(row.observation_id)
            if (
                status is None
                or status.status not in ("APPLIED", "DUPLICATE")
                or status.intent_id != submit_intent.intent_id
                or not _exact_identifier(status.receipt_id)
                or not _exact_identifier(status.execution_id)
            ):
                raise FactorExecutionError("CANCEL_DISPATCHING_TRADE_NOT_DURABLE")
            proof_rows.append(
                (
                    row.trade_id,
                    status.execution_id,
                    row.order_ref,
                    row.order_sys_id,
                    row.instrument,
                    row.exchange,
                    row.direction,
                    row.side,
                    row.offset,
                    row.position_effect,
                    row.trading_day,
                    row.trade_date,
                    row.trade_time,
                    row.trade_time_utc.isoformat(),
                    row.hedge_flag,
                    row.offset_flag,
                    str(row.volume),
                    str(row.price),
                    None if row.fee is None else str(row.fee),
                )
            )
        # Observation and receipt IDs are query-local. Each current observation
        # was just joined to its durable receipt/execution above; the replay
        # digest instead binds the stable exact trade/economics set.
        trade_digest = hashlib.sha256(
            json.dumps(
                sorted(
                    proof_rows,
                    key=lambda values: json.dumps(values, ensure_ascii=True, separators=(",", ":")),
                ),
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode("ascii")
        ).hexdigest()

        positions = tuple(
            row
            for row in facts.positions
            if row.instrument == observation.instrument and row.exchange == observation.exchange
        )
        if len(positions) != 1 or not _terminal_position_consistent(positions[0], facts):
            raise FactorExecutionError("CANCEL_DISPATCHING_POSITION_RECONCILIATION_MISMATCH")
        position = positions[0]
        broker_quantity = position.broker_quantity
        if position.quantity != broker_quantity:
            raise FactorExecutionError("CANCEL_DISPATCHING_POSITION_ATTRIBUTION_MISMATCH")
        if broker_quantity == 0:
            flat_attribution = (
                isinstance(position.attributed_signed_quantity, Decimal)
                and position.attributed_signed_quantity.is_finite()
                and position.attributed_signed_quantity == Decimal(0)
            )
            flat_attribution_missing_or_zero = (
                position.attributed_signed_quantity is None or flat_attribution
            )
            causal_pending_owner = (
                position.position_book_status == "UNKNOWN"
                and position.position_book_blocker_code == "INSTRUMENT_ORDER_UNRESOLVED"
                and self._dispatching_cancel_pending_owner_is_exact(
                    submit_intent, cancel_intent_id, observation
                )
            )
            is_flat = (
                position.position_book_status == "FLAT"
                and position.position_book_blocker_code is None
                and flat_attribution_missing_or_zero
            )
            is_exact_pending_flat = causal_pending_owner and flat_attribution_missing_or_zero
            if (
                not (is_flat or is_exact_pending_flat)
                or position.owner_intent_id is not None
                or position.owner_strategy_scope is not None
            ):
                if not flat_attribution_missing_or_zero:
                    raise FactorExecutionError("CANCEL_DISPATCHING_POSITION_ATTRIBUTION_MISMATCH")
                raise FactorExecutionError("CANCEL_DISPATCHING_POSITION_BOOK_FLAT_MISMATCH")
        else:
            if position.attributed_signed_quantity != broker_quantity:
                raise FactorExecutionError("CANCEL_DISPATCHING_POSITION_ATTRIBUTION_MISMATCH")
            causal_pending_owner = (
                position.position_book_status == "UNKNOWN"
                and position.position_book_blocker_code == "INSTRUMENT_ORDER_UNRESOLVED"
                and self._dispatching_cancel_pending_owner_is_exact(
                    submit_intent, cancel_intent_id, observation
                )
            )
            if (
                not (
                    position.position_book_status == "MATCHED"
                    and position.position_book_blocker_code is None
                    or causal_pending_owner
                )
                or not _exact_identifier(position.owner_intent_id)
                or position.owner_strategy_scope != self.strategy_scope
                or position.opening_fees_known is not True
                or not isinstance(position.opening_fee_total, Decimal)
                or not position.opening_fee_total.is_finite()
                or position.opening_fee_total < 0
                or (
                    submit_intent.key.position_effect == "OPEN"
                    and position.owner_intent_id != submit_intent.intent_id
                )
                or (
                    submit_intent.key.position_effect == "CLOSE"
                    and (
                        not _exact_identifier(submit_intent.economic_payload.get("owner_intent_id"))
                        or position.owner_intent_id
                        != submit_intent.economic_payload.get("owner_intent_id")
                    )
                )
            ):
                raise FactorExecutionError("CANCEL_DISPATCHING_POSITION_BOOK_OWNER_MISMATCH")
            if not _exact_identifier(position.target_id):
                raise FactorExecutionError("CANCEL_DISPATCHING_POSITION_TARGET_UNAVAILABLE")
            proof = self.position_book.dated_snapshot(facts, target_id=position.target_id)
            if (
                proof.status != "MATCHED"
                or proof.ready is not True
                or proof.target_id != position.target_id
                or proof.instrument != observation.instrument
                or proof.exchange != observation.exchange
                or proof.query_set_id != query_set.query_set_id
                or proof.account_fingerprint != query_set.account_fingerprint
                or proof.connection_generation != query_set.connection_generation
                or proof.trading_day != query_set.trading_day
                or proof.snapshot_id != facts.snapshot_id
                or not proof.buckets
                or any(
                    bucket.ready is not True
                    or bucket.owner_strategy_scope != self.strategy_scope
                    or bucket.owner_intent_id != position.owner_intent_id
                    for bucket in proof.buckets
                )
            ):
                raise FactorExecutionError("CANCEL_DISPATCHING_DATED_POSITION_BOOK_MISMATCH")

        route = self.store.registered_sim_route_eligibility(
            observation.instrument, observation.exchange
        )
        if (
            route.instrument_id != observation.instrument
            or route.exchange_id != observation.exchange
            or route.account_fingerprint != expected_session["account_fingerprint"]
            or route.connection_generation != expected_session["connection_generation"]
            or route.trading_day != expected_session["trading_day"]
            or route.current_session_account_fingerprint != expected_session["account_fingerprint"]
            or route.current_session_connection_generation
            != expected_session["connection_generation"]
            or route.current_session_trading_day != expected_session["trading_day"]
            or route.current_session_front_id != expected_session["front_id"]
            or route.current_session_id != expected_session["session_id"]
            or route.current_session_read_only_ready is not True
            or route.instrument_query_complete is not True
            or route.instrument_eligible is not True
            or route.sdk_capability_armed is not False
            or route.dispatching_order_ids != ()
            or route.unknown_order_ids != ()
        ):
            raise FactorExecutionError("CANCEL_DISPATCHING_ROUTE_OR_SESSION_MISMATCH")

        current_identity = {
            "cancel_recovery_kind": "dispatching_cancel",
            "parent_intent_id": submit_intent.intent_id,
            "cancel_intent_id": cancel_intent_id,
            "observation_id": observation.observation_id,
            "query_set_id": query_set.query_set_id,
            "snapshot_id": facts.snapshot_id,
            "connection_generation": observation.connection_generation,
            "account_fingerprint": observation.account_fingerprint,
            "trading_day": observation.trading_day,
            "order_ref": observation.order_ref,
            "order_sys_id": observation.order_sys_id,
            "instrument": observation.instrument,
            "exchange": observation.exchange,
            "front_id": observation.front_id,
            "session_id": observation.session_id,
            "terminal_status": observation.terminal_status,
            "terminal_state": observation.terminal_state,
            "volume_total_original": str(volume_total_original),
            "volume_traded": str(volume_traded),
            "volume_total": str(volume_total),
            "current_session": dict(expected_session),
            "original_account_fingerprint": identity["account_fingerprint"],
            "original_connection_generation": identity["connection_generation"],
            "original_trading_day": identity["trading_day"],
            "original_order_ref": identity["order_ref"],
            "original_front_id": identity["front_id"],
            "original_session_id": identity["session_id"],
            "original_order_sys_id": identity.get("order_sys_id"),
            "matching_trade_count": len(matching_trades),
            "matching_trade_volume": str(matching_volume),
            "matching_trade_digest": trade_digest,
            "broker_quantity": str(broker_quantity),
            "ctp_long_quantity": str(position.long_quantity),
            "ctp_short_quantity": str(position.short_quantity),
            "attributed_signed_quantity": str(position.attributed_signed_quantity),
            "position_book_owner_intent_id": position.owner_intent_id,
            "opening_fee_total": str(position.opening_fee_total),
            "opening_fees_known": position.opening_fees_known,
            "position_snapshot_id": position.snapshot_id,
            "position_flat": broker_quantity == 0,
        }
        return {
            "expected_session": expected_session,
            "query_set": query_set,
            "position": position,
            "current_identity": current_identity,
        }

    def _dispatching_cancel_original_identity_matches(
        self, submit_intent, cancel_intent_id, observation, query_set
    ):
        identity = submit_intent.original_identity
        try:
            cancel_intent = self.journal.intent(cancel_intent_id)
        except Exception:
            return False
        cancel_identity = cancel_intent.original_identity if cancel_intent is not None else None
        return bool(
            submit_intent.key.action == "SUBMIT"
            and submit_intent.state == "KNOWN"
            and submit_intent.dispatch_state == "KNOWN"
            and cancel_intent is not None
            and cancel_intent.key.action == "CANCEL"
            and cancel_intent.owner_intent_id == submit_intent.intent_id
            and isinstance(cancel_identity, Mapping)
            and cancel_identity.get("operation") == "cancel"
            and cancel_identity.get("owner_intent_id") == submit_intent.intent_id
            and identity.get("operation") == "insert"
            and _exact_identifier(identity.get("account_fingerprint"))
            and identity.get("account_fingerprint") == query_set.account_fingerprint
            and identity.get("account_fingerprint") == observation.account_fingerprint
            and identity.get("trading_day") == query_set.trading_day
            and identity.get("trading_day") == observation.trading_day
            and _positive_int(identity.get("connection_generation"))
            and _positive_int(identity.get("front_id"))
            and _positive_int(identity.get("session_id"))
            and all(
                identity.get(name) == cancel_identity.get(name)
                for name in (
                    "account_fingerprint",
                    "connection_generation",
                    "trading_day",
                    "front_id",
                    "session_id",
                )
            )
            and identity.get("instrument_id") == observation.instrument
            and identity.get("exchange_id") == observation.exchange
            and identity.get("order_ref") == observation.order_ref
            and identity.get("instrument_id") == cancel_identity.get("instrument_id")
            and identity.get("exchange_id") == cancel_identity.get("exchange_id")
            and identity.get("order_ref") == cancel_identity.get("order_ref")
            and observation.front_id == identity.get("front_id")
            and observation.session_id == identity.get("session_id")
            and (
                identity.get("order_sys_id") is None
                or identity.get("order_sys_id") == observation.order_sys_id
            )
            and (
                "order_sys_id" not in cancel_identity
                or identity.get("order_sys_id") == cancel_identity.get("order_sys_id")
            )
            and submit_intent.key.instrument == observation.instrument
            and submit_intent.key.position_effect in ("OPEN", "CLOSE")
        )

    @staticmethod
    def _blocked_dispatching_cancel(observation, submit_intent, code, *, reconciliation_id=None):
        return ExecutionTerminalReconciliationItem(
            observation_id=observation.observation_id,
            status="BLOCKED",
            intent_id=submit_intent.intent_id,
            reconciliation_id=reconciliation_id,
            blocker_code=code,
        )

    def _reconcile_unknown_cancel_terminal(
        self,
        facts: Any,
        observation: Any,
        submit_intent: ExecutionIntentRecord,
        cancel_intent: ExecutionIntentRecord,
        *,
        refresh_receipt: Any,
    ) -> ExecutionTerminalReconciliationItem:
        """Resolve an UNKNOWN CANCEL from a complete no-fill terminal query.

        The CANCEL intent is a child of the original SUBMIT. The terminal row
        belongs to that original native order, while the wrapper UNKNOWN latch
        belongs to the single CANCEL dispatch. Both identities are checked and
        persisted before the Store is allowed to retire the latch.
        """
        try:
            expected_session, query_set = self._validate_unknown_recovery_snapshot(
                facts, refresh_receipt, observation
            )
        except FactorExecutionError as error:
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=submit_intent.intent_id,
                blocker_code=error.code,
            )

        parent_identity = submit_intent.original_identity
        cancel_identity = cancel_intent.original_identity
        dispatch = cancel_intent.provider_identity
        owner = self.journal.active_instrument_owner(
            self.account_scope, submit_intent.key.instrument
        )
        if (
            owner is None
            or owner.intent_id != submit_intent.intent_id
            or owner.cancel_intent_id != cancel_intent.intent_id
            or submit_intent.key.action != "SUBMIT"
            or submit_intent.state != "KNOWN"
            or submit_intent.dispatch_state != "KNOWN"
            or submit_intent.key.position_effect != "OPEN"
            or cancel_intent.key.action != "CANCEL"
            or cancel_intent.state not in ("UNKNOWN", "KNOWN")
            or cancel_intent.dispatch_state != "UNKNOWN"
            or cancel_intent.owner_intent_id != submit_intent.intent_id
            or not isinstance(dispatch, Mapping)
            or dispatch.get("operation") != "cancel"
            or dispatch.get("status") != "UNKNOWN"
            or dispatch.get("resend_permitted") is not False
            or not _positive_int(dispatch.get("request_id"))
            or dispatch.get("instrument_id") != observation.instrument
            or dispatch.get("exchange_id") != observation.exchange
            or dispatch.get("order_ref") != observation.order_ref
            or dispatch.get("front_id") != parent_identity.get("front_id")
            or dispatch.get("session_id") != parent_identity.get("session_id")
            or cancel_identity.get("operation") != "cancel"
            or cancel_identity.get("owner_intent_id") != submit_intent.intent_id
            or cancel_identity.get("order_ref") != observation.order_ref
            or cancel_identity.get("instrument_id") != observation.instrument
            or cancel_identity.get("exchange_id") != observation.exchange
            or cancel_identity.get("front_id") != parent_identity.get("front_id")
            or cancel_identity.get("session_id") != parent_identity.get("session_id")
            or cancel_identity.get("account_fingerprint") != observation.account_fingerprint
            or cancel_identity.get("account_fingerprint") != expected_session["account_fingerprint"]
            or cancel_identity.get("trading_day") != observation.trading_day
            or cancel_identity.get("connection_generation")
            != expected_session["connection_generation"]
            or not _positive_int(cancel_identity.get("connection_generation"))
            or parent_identity.get("account_fingerprint") != observation.account_fingerprint
            or parent_identity.get("trading_day") != observation.trading_day
            or not _positive_int(parent_identity.get("front_id"))
            or not _positive_int(parent_identity.get("session_id"))
            or observation.front_id != parent_identity.get("front_id")
            or observation.session_id != parent_identity.get("session_id")
            or dispatch.get("order_sys_id") not in (None, observation.order_sys_id)
            or cancel_identity.get("order_sys_id") not in (None, observation.order_sys_id)
            or parent_identity.get("order_sys_id") not in (None, observation.order_sys_id)
        ):
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=submit_intent.intent_id,
                blocker_code="UNKNOWN_CANCEL_ORIGINAL_ORDER_LINEAGE_MISMATCH",
            )

        # A cancel query proves this OPEN order ended without a fill only when
        # CTP reports its exact canceled status and the full volume tuple.
        original_volume = observation.volume_total_original
        traded_volume = observation.volume_traded
        remaining_volume = observation.volume_total
        submit_quantity = _decimal_optional(submit_intent.economic_payload.get("quantity"))
        if (
            observation.terminal_status != "5"
            or observation.terminal_state != "CANCELED"
            or any(
                not isinstance(value, Decimal) or not value.is_finite()
                for value in (original_volume, traded_volume, remaining_volume)
            )
            or submit_quantity is None
            or submit_quantity != original_volume
            or original_volume <= 0
            or original_volume != original_volume.to_integral_value()
            or traded_volume != 0
            or remaining_volume != original_volume
        ):
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=submit_intent.intent_id,
                blocker_code="UNKNOWN_CANCEL_NO_FILL_NOT_PROVEN",
            )

        try:
            trade_rows = self._validate_unknown_recovery_row_projection(
                facts,
                observation,
                submit_intent,
                unresolved_intent_id=cancel_intent.intent_id,
                cancel_intent_id=cancel_intent.intent_id,
            )
        except FactorExecutionError as error:
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=submit_intent.intent_id,
                blocker_code=error.code,
            )
        if any(
            row.order_ref == observation.order_ref
            and row.instrument == observation.instrument
            and row.exchange == observation.exchange
            for row in trade_rows
        ):
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=submit_intent.intent_id,
                blocker_code="UNKNOWN_CANCEL_TERMINAL_CONFLICTS_WITH_TRADE_QUERY",
            )

        positions = [
            row
            for row in facts.positions
            if row.instrument == observation.instrument and row.exchange == observation.exchange
        ]
        if len(positions) != 1 or not _terminal_position_consistent(positions[0], facts):
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=submit_intent.intent_id,
                blocker_code="TERMINAL_POSITION_RECONCILIATION_MISMATCH",
            )
        position = positions[0]
        if (
            position.broker_quantity != 0
            or position.long_quantity != 0
            or position.short_quantity != 0
            or getattr(position, "attributed_signed_quantity", None) not in (None, Decimal("0"))
            or any(
                row.instrument == observation.instrument
                and row.exchange == observation.exchange
                and not self._is_exact_unknown_working_order(
                    row,
                    submit_intent,
                    observation,
                    cancel_intent_id=cancel_intent.intent_id,
                )
                for row in facts.working_orders
            )
        ):
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=submit_intent.intent_id,
                blocker_code="UNKNOWN_CANCEL_ROUTE_NOT_FLAT_OR_CLEAR",
            )

        try:
            route = self.store.registered_sim_route_eligibility(
                observation.instrument, observation.exchange
            )
        except Exception:
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=submit_intent.intent_id,
                blocker_code="UNKNOWN_RECOVERY_SESSION_UNOBSERVED",
            )
        if (
            route.instrument_id != observation.instrument
            or route.exchange_id != observation.exchange
            or route.account_fingerprint != expected_session["account_fingerprint"]
            or route.connection_generation != expected_session["connection_generation"]
            or route.trading_day != expected_session["trading_day"]
            or route.current_session_account_fingerprint != expected_session["account_fingerprint"]
            or route.current_session_connection_generation
            != expected_session["connection_generation"]
            or route.current_session_trading_day != expected_session["trading_day"]
            or route.current_session_front_id != expected_session["front_id"]
            or route.current_session_id != expected_session["session_id"]
            or route.current_session_read_only_ready is not True
            or route.instrument_query_complete is not True
            or route.instrument_eligible is not True
            or route.sdk_capability_armed is not False
            or route.dispatching_order_ids != ()
            or route.unknown_order_ids not in ((), (observation.order_ref,))
        ):
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=submit_intent.intent_id,
                blocker_code="UNKNOWN_RECOVERY_SESSION_OR_ROUTE_MISMATCH",
            )

        child_reconciliation_id = _unknown_terminal_reconciliation_id(
            cancel_intent.intent_id,
            observation.observation_id,
            query_set.query_set_id,
            facts.snapshot_id,
        )
        parent_reconciliation_id = _terminal_reconciliation_id(
            submit_intent.intent_id,
            observation.observation_id,
            facts.snapshot_id,
            position.broker_quantity,
            position.long_quantity,
            position.short_quantity,
        )
        child_provider_identity = {
            "evidence_kind": "complete_orders_query_cancel_unknown_no_fill_terminal",
            "observation_id": observation.observation_id,
            "query_set_id": query_set.query_set_id,
            "snapshot_id": facts.snapshot_id,
            "orders_request_id": observation.request_id,
            "connection_generation": observation.connection_generation,
            "account_fingerprint": observation.account_fingerprint,
            "trading_day": observation.trading_day,
            "terminal_status": observation.terminal_status,
            "terminal_state": observation.terminal_state,
            "volume_total_original": str(original_volume),
            "volume_traded": str(traded_volume),
            "volume_total": str(remaining_volume),
            "order_ref": observation.order_ref,
            "order_sys_id": observation.order_sys_id,
            "front_id": observation.front_id,
            "session_id": observation.session_id,
            "instrument": observation.instrument,
            "exchange": observation.exchange,
            "parent_intent_id": submit_intent.intent_id,
            "cancel_intent_id": cancel_intent.intent_id,
            "original_account_fingerprint": parent_identity["account_fingerprint"],
            "original_connection_generation": parent_identity["connection_generation"],
            "original_trading_day": parent_identity["trading_day"],
            "original_order_ref": parent_identity["order_ref"],
            "original_front_id": parent_identity["front_id"],
            "original_session_id": parent_identity["session_id"],
            "position_snapshot_id": position.snapshot_id,
        }
        parent_provider_identity = {
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
            "broker_quantity": str(position.broker_quantity),
            "ctp_long_quantity": str(position.long_quantity),
            "ctp_short_quantity": str(position.short_quantity),
            "position_snapshot_id": position.snapshot_id,
            "position_available_at": _utc_text(position.available_at),
            "unknown_cancel_intent_id": cancel_intent.intent_id,
            "unknown_cancel_reconciliation_id": child_reconciliation_id,
        }
        try:
            self.journal.record_reconciliation(
                cancel_intent.intent_id,
                reconciliation_id=child_reconciliation_id,
                query_id=observation.observation_id,
                state="KNOWN",
                provider_identity=child_provider_identity,
                outcome_code="complete_orders_query_cancel_unknown_no_fill_terminal",
                terminal_state="CANCELLED",
                terminal_event_id=observation.observation_id,
                position_snapshot_id=position.snapshot_id,
                position_flat=True,
            )
            self.journal.record_reconciliation(
                submit_intent.intent_id,
                reconciliation_id=parent_reconciliation_id,
                query_id=observation.observation_id,
                state="KNOWN",
                provider_identity=parent_provider_identity,
                outcome_code="complete_orders_query_terminal",
                terminal_state="CANCELLED",
                terminal_event_id=observation.observation_id,
                position_snapshot_id=position.snapshot_id,
                position_flat=True,
            )
            self.journal.release_instrument_owner(
                submit_intent.intent_id,
                reconciliation_id=parent_reconciliation_id,
            )
        except Exception as error:
            code = getattr(error, "code", None)
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=submit_intent.intent_id,
                reconciliation_id=parent_reconciliation_id,
                blocker_code=code
                if _exact_identifier(code)
                else "UNKNOWN_CANCEL_RECOVERY_NOT_DURABLE",
            )

        event = self._unknown_cancel_terminal_broker_event(
            submit_intent, cancel_intent, observation, original_volume
        )
        try:
            retired = self.store.registered_sim_retire_unknown(
                cancel_intent.intent_id,
                child_reconciliation_id,
                original_identity=cancel_identity,
                expected_session=expected_session,
                terminal_event=event,
            )
        except Exception:
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=submit_intent.intent_id,
                reconciliation_id=parent_reconciliation_id,
                blocker_code="UNKNOWN_STORE_RETIREMENT_NOT_APPLIED",
            )
        if getattr(retired, "status", None) not in ("QUEUED", "ALREADY_ABSENT"):
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=submit_intent.intent_id,
                reconciliation_id=parent_reconciliation_id,
                blocker_code="UNKNOWN_STORE_RETIREMENT_RESULT_INVALID",
            )
        return ExecutionTerminalReconciliationItem(
            observation_id=observation.observation_id,
            status="RESOLVED",
            intent_id=submit_intent.intent_id,
            reconciliation_id=parent_reconciliation_id,
        )

    def _retry_unknown_cancel_store_retirement(
        self,
        facts: Any,
        observation: Any,
        submit_intent: ExecutionIntentRecord,
        parent_provider_identity: Mapping[str, Any],
        *,
        refresh_receipt: Any,
    ) -> ExecutionTerminalReconciliationItem:
        cancel_intent_id = _exact_identifier(
            parent_provider_identity.get("unknown_cancel_intent_id")
        )
        child_reconciliation_id = _exact_identifier(
            parent_provider_identity.get("unknown_cancel_reconciliation_id")
        )
        if cancel_intent_id is None or child_reconciliation_id is None:
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=submit_intent.intent_id,
                blocker_code="UNKNOWN_CANCEL_RETIREMENT_BINDING_INVALID",
            )
        try:
            child = self.journal.intent(cancel_intent_id)
            child_reconciliation = self.journal.reconciliation(child_reconciliation_id)
            expected_session, query_set = self._validate_unknown_recovery_snapshot(
                facts, refresh_receipt, observation
            )
        except Exception as error:
            code = getattr(error, "code", None)
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=submit_intent.intent_id,
                blocker_code=code
                if _exact_identifier(code)
                else "UNKNOWN_CANCEL_RETIREMENT_EVIDENCE_UNAVAILABLE",
            )
        identity = submit_intent.original_identity
        child_identity = child.original_identity if child is not None else {}
        child_provider = child.provider_identity if child is not None else {}
        child_query = child_reconciliation.provider_identity if child_reconciliation else {}
        expected_quantity = _decimal_optional(submit_intent.economic_payload.get("quantity"))
        observed_volumes = (
            _decimal_optional(observation.volume_total_original),
            _decimal_optional(observation.volume_traded),
            _decimal_optional(observation.volume_total),
        )
        persisted_volumes = tuple(
            _decimal_optional(child_query.get(name))
            for name in ("volume_total_original", "volume_traded", "volume_total")
        )
        if (
            expected_quantity is None
            or expected_quantity <= 0
            or expected_quantity != expected_quantity.to_integral_value()
            or observation.terminal_status != "5"
            or observation.terminal_state != "CANCELED"
            or observed_volumes != (expected_quantity, Decimal("0"), expected_quantity)
            or persisted_volumes != observed_volumes
        ):
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=submit_intent.intent_id,
                reconciliation_id=child_reconciliation_id,
                blocker_code="UNKNOWN_CANCEL_TERMINAL_VOLUME_CONFLICT",
            )
        if (
            child is None
            or child.key.action != "CANCEL"
            or child.owner_intent_id != submit_intent.intent_id
            or child.state != "KNOWN"
            or child.dispatch_state != "UNKNOWN"
            or not isinstance(child_provider, Mapping)
            or child_provider.get("operation") != "cancel"
            or child_provider.get("status") != "UNKNOWN"
            or child_provider.get("resend_permitted") is not False
            or child_provider.get("order_ref") != observation.order_ref
            or child_provider.get("instrument_id") != observation.instrument
            or child_provider.get("exchange_id") != observation.exchange
            or child_provider.get("front_id") != identity.get("front_id")
            or child_provider.get("session_id") != identity.get("session_id")
            or not isinstance(child_identity, Mapping)
            or child_identity.get("operation") != "cancel"
            or child_identity.get("owner_intent_id") != submit_intent.intent_id
            or child_identity.get("order_ref") != observation.order_ref
            or child_identity.get("account_fingerprint") != query_set.account_fingerprint
            or child_identity.get("trading_day") != query_set.trading_day
            or child_identity.get("front_id") != identity.get("front_id")
            or child_identity.get("session_id") != identity.get("session_id")
            or child_reconciliation is None
            or child_reconciliation.intent_id != child.intent_id
            or child_reconciliation.state != "KNOWN"
            or child_reconciliation.terminal_state != "CANCELLED"
            or child_reconciliation.outcome_code
            != "complete_orders_query_cancel_unknown_no_fill_terminal"
            or child_reconciliation.position_flat is not True
            or child_reconciliation.position_snapshot_id is None
            or not isinstance(child_query, Mapping)
            or child_query.get("parent_intent_id") != submit_intent.intent_id
            or child_query.get("cancel_intent_id") != child.intent_id
            or child_query.get("order_ref") != observation.order_ref
            or child_query.get("instrument") != observation.instrument
            or child_query.get("exchange") != observation.exchange
            or child_query.get("terminal_status") != "5"
            or child_query.get("terminal_state") != "CANCELED"
            or child_query.get("account_fingerprint") != observation.account_fingerprint
            or child_query.get("trading_day") != observation.trading_day
        ):
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=submit_intent.intent_id,
                reconciliation_id=child_reconciliation_id,
                blocker_code="UNKNOWN_CANCEL_RETIREMENT_BINDING_INVALID",
            )

        try:
            route = self.store.registered_sim_route_eligibility(
                observation.instrument, observation.exchange
            )
        except Exception:
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=submit_intent.intent_id,
                blocker_code="UNKNOWN_RECOVERY_SESSION_UNOBSERVED",
            )
        if (
            route.unknown_order_ids == ()
            and self.store.registered_sim_status().get("frozen") is False
        ):
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="RESOLVED",
                intent_id=submit_intent.intent_id,
                reconciliation_id=self.journal.instrument_resolution(
                    submit_intent.intent_id
                ).reconciliation_id,
            )
        if route.unknown_order_ids != (observation.order_ref,):
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=submit_intent.intent_id,
                reconciliation_id=child_reconciliation_id,
                blocker_code="UNKNOWN_CANCEL_STORE_STATE_MISMATCH",
            )
        try:
            trade_rows = self._validate_unknown_recovery_row_projection(
                facts,
                observation,
                submit_intent,
                unresolved_intent_id=cancel_intent_id,
                cancel_intent_id=cancel_intent_id,
            )
        except FactorExecutionError as error:
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=submit_intent.intent_id,
                reconciliation_id=child_reconciliation_id,
                blocker_code=error.code,
            )
        if any(
            row.order_ref == observation.order_ref
            and row.instrument == observation.instrument
            and row.exchange == observation.exchange
            for row in trade_rows
        ):
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=submit_intent.intent_id,
                reconciliation_id=child_reconciliation_id,
                blocker_code="UNKNOWN_CANCEL_TERMINAL_CONFLICTS_WITH_TRADE_QUERY",
            )
        positions = [
            row
            for row in facts.positions
            if row.instrument == observation.instrument and row.exchange == observation.exchange
        ]
        if (
            len(positions) != 1
            or not _terminal_position_consistent(positions[0], facts)
            or positions[0].broker_quantity != 0
            or positions[0].long_quantity != 0
            or positions[0].short_quantity != 0
            or getattr(positions[0], "attributed_signed_quantity", None) not in (None, Decimal("0"))
        ):
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=submit_intent.intent_id,
                reconciliation_id=child_reconciliation_id,
                blocker_code="UNKNOWN_CANCEL_ROUTE_NOT_FLAT_OR_CLEAR",
            )
        event = self._unknown_cancel_terminal_broker_event(
            submit_intent,
            child,
            observation,
            _decimal_optional(submit_intent.economic_payload.get("quantity")),
        )
        try:
            retired = self.store.registered_sim_retire_unknown(
                child.intent_id,
                child_reconciliation_id,
                original_identity=child_identity,
                expected_session=expected_session,
                terminal_event=event,
            )
        except Exception:
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=submit_intent.intent_id,
                reconciliation_id=child_reconciliation_id,
                blocker_code="UNKNOWN_STORE_RETIREMENT_NOT_APPLIED",
            )
        if getattr(retired, "status", None) not in ("QUEUED", "ALREADY_ABSENT"):
            return ExecutionTerminalReconciliationItem(
                observation_id=observation.observation_id,
                status="BLOCKED",
                intent_id=submit_intent.intent_id,
                reconciliation_id=child_reconciliation_id,
                blocker_code="UNKNOWN_STORE_RETIREMENT_RESULT_INVALID",
            )
        resolution = self.journal.instrument_resolution(submit_intent.intent_id)
        return ExecutionTerminalReconciliationItem(
            observation_id=observation.observation_id,
            status="RESOLVED",
            intent_id=submit_intent.intent_id,
            reconciliation_id=resolution.reconciliation_id if resolution else None,
        )

    def _unknown_cancel_terminal_broker_event(
        self,
        submit_intent: ExecutionIntentRecord,
        cancel_intent: ExecutionIntentRecord,
        observation: Any,
        quantity: Optional[Decimal],
    ) -> Optional[Mapping[str, Any]]:
        identity = submit_intent.original_identity
        bt_ref = identity.get("backtrader_order_ref")
        if type(bt_ref) is not int or bt_ref <= 0:
            return None
        order = getattr(self.broker, "orders", {}).get(bt_ref)
        if order is None or not order.alive():
            return None
        info = getattr(order, "info", {})
        get = getattr(info, "get", lambda name, default=None: default)
        external_ref = _first_text(get("external_order_ref"), get("ctp_order_ref"))
        side = "BUY" if order.isbuy() else "SELL"
        order_quantity = _decimal_optional(getattr(order, "size", None))
        expected_order_quantity = (
            quantity if side == "BUY" else (-quantity if quantity is not None else None)
        )
        executed_quantity = _decimal_optional(getattr(order.executed, "size", None))
        remaining_quantity = _decimal_optional(self.broker._order_remaining_qty(order))
        if (
            quantity is None
            or quantity <= 0
            or quantity != quantity.to_integral_value()
            or not bool(get("execution_unknown", False))
            or get("cancel_execution_unknown") is not True
            or get("cancel_intent_active") is not True
            or get("factor_intent_id") != submit_intent.intent_id
            or get("factor_cancel_intent_id") != cancel_intent.intent_id
            or get("factor_strategy_scope") != self.strategy_scope
            or get("instrument_id") != observation.instrument
            or get("exchange_id") != observation.exchange
            or external_ref != observation.order_ref
            or side != submit_intent.key.side
            or get("factor_position_effect") != submit_intent.key.position_effect
            or _positive_int(get("front_id")) != identity.get("front_id")
            or _positive_int(get("session_id")) != identity.get("session_id")
            or order_quantity != expected_order_quantity
            or executed_quantity != 0
            or remaining_quantity != quantity
        ):
            raise FactorExecutionError("UNKNOWN_CANCEL_BROKER_ORDER_LINEAGE_MISMATCH")
        size = int(quantity)
        price = _decimal_optional(getattr(order.created, "price", None))
        details = {
            "OrderRef": observation.order_ref,
            "OrderSysID": observation.order_sys_id or "",
            "InstrumentID": observation.instrument,
            "ExchangeID": observation.exchange,
            "FrontID": identity["front_id"],
            "SessionID": identity["session_id"],
            "OrderStatus": observation.terminal_status,
            "VolumeTotalOriginal": size,
            "VolumeTraded": 0,
            "VolumeTotal": size,
        }
        return {
            "kind": "order",
            "bt_order_ref": bt_ref,
            "order_ref": observation.order_ref,
            "order_sys_id": observation.order_sys_id,
            "external_order_id": observation.order_sys_id,
            "data_name": getattr(getattr(order, "data", None), "_name", ""),
            "instrument": observation.instrument,
            "exchange_id": observation.exchange,
            "front_id": identity["front_id"],
            "session_id": identity["session_id"],
            "status": "canceled",
            "side": side.lower(),
            "offset": str(submit_intent.economic_payload.get("offset", "open")),
            "price": float(price) if price is not None else 0.0,
            "size": size,
            "filled": 0,
            "remaining": size,
            "terminal_confirmed": True,
            "execution_unknown": False,
            "factor_intent_id": submit_intent.intent_id,
            "factor_cancel_intent_id": cancel_intent.intent_id,
            "details": details,
        }

    def _validate_unknown_recovery_snapshot(
        self,
        facts: Any,
        refresh_receipt: Any,
        observation: Any,
        *,
        minimum_query_started_at: Optional[datetime] = None,
    ):
        from .factor_execution_facts import (
            _BASE_FAMILIES,
            FactorExecutionRefreshReceipt,
            _query_set_matches,
        )

        if type(refresh_receipt) is not FactorExecutionRefreshReceipt:
            raise FactorExecutionError("UNKNOWN_RECOVERY_REFRESH_RECEIPT_REQUIRED")
        minimum_started_at = (
            None if minimum_query_started_at is None else _aware_utc(minimum_query_started_at)
        )
        if minimum_query_started_at is not None and minimum_started_at is None:
            raise FactorExecutionError("DISPATCHING_RECOVERY_SCOPE_INVALID")
        if (
            refresh_receipt.cancelled
            or refresh_receipt.deadline_reached
            or refresh_receipt.blockers
            or refresh_receipt.pending_families
            or tuple(refresh_receipt.requested_families[: len(_BASE_FAMILIES)]) != _BASE_FAMILIES
            or tuple(refresh_receipt.attempted_families[: len(_BASE_FAMILIES)]) != _BASE_FAMILIES
            or facts.available_at is None
            or not _time_not_after(refresh_receipt.started_at, refresh_receipt.completed_at)
            or not _time_not_after(facts.available_at, refresh_receipt.completed_at)
        ):
            raise FactorExecutionError("UNKNOWN_RECOVERY_REFRESH_RECEIPT_INCOMPLETE")
        if minimum_started_at is not None and not _time_not_after(
            minimum_started_at, refresh_receipt.started_at
        ):
            raise FactorExecutionError("DISPATCHING_RECOVERY_QUERY_PREDATES_SCOPE")
        receipt_facts = tuple(
            item for item in refresh_receipt.query_provenance if item.family in _BASE_FAMILIES
        )
        facts_facts = tuple(
            item for item in facts.query_provenance if item.family in _BASE_FAMILIES
        )
        if (
            tuple(item.family for item in receipt_facts) != _BASE_FAMILIES
            or receipt_facts != facts_facts
            or any(
                item.source_owned is not True
                or item.query_complete is not True
                or item.scope_complete is not True
                or item.request_id is None
                or item.account_fingerprint is None
                or item.connection_generation is None
                or item.trading_day is None
                for item in receipt_facts
            )
        ):
            raise FactorExecutionError("UNKNOWN_RECOVERY_QUERY_PROVENANCE_MISMATCH")
        if minimum_started_at is not None and any(
            not _time_not_after(minimum_started_at, item.started_at) for item in receipt_facts
        ):
            raise FactorExecutionError("DISPATCHING_RECOVERY_QUERY_PREDATES_SCOPE")
        query_set = refresh_receipt.query_set
        if (
            query_set is None
            or query_set.query_set_id != facts.query_set_id
            or not _query_set_matches(
                query_set,
                receipt_facts,
                now=refresh_receipt.completed_at,
                max_age=timedelta(seconds=60),
            )
            or query_set.account_fingerprint != facts.account.account_fingerprint
            or query_set.connection_generation != facts.account.connection_generation
            or query_set.trading_day != facts.account.trading_day
            or not _time_not_after(refresh_receipt.started_at, query_set.started_at_utc)
            or not _time_not_after(query_set.started_at_utc, query_set.completed_at_utc)
            or not _time_not_after(query_set.completed_at_utc, refresh_receipt.completed_at)
        ):
            raise FactorExecutionError("UNKNOWN_RECOVERY_QUERY_SET_MISMATCH")
        if minimum_started_at is not None and not _time_not_after(
            minimum_started_at, query_set.started_at_utc
        ):
            raise FactorExecutionError("DISPATCHING_RECOVERY_QUERY_PREDATES_SCOPE")
        try:
            route = self.store.registered_sim_route_eligibility(
                observation.instrument, observation.exchange
            )
        except Exception as error:
            raise FactorExecutionError("UNKNOWN_RECOVERY_SESSION_UNOBSERVED") from error
        expected = {
            "account_fingerprint": query_set.account_fingerprint,
            "connection_generation": query_set.connection_generation,
            "trading_day": query_set.trading_day,
            "front_id": route.current_session_front_id,
            "session_id": route.current_session_id,
        }
        if (
            route.account_fingerprint != query_set.account_fingerprint
            or route.connection_generation != query_set.connection_generation
            or route.trading_day != query_set.trading_day
            or route.current_session_account_fingerprint != query_set.account_fingerprint
            or route.current_session_connection_generation != query_set.connection_generation
            or route.current_session_trading_day != query_set.trading_day
            or route.current_session_read_only_ready is not True
            or not _positive_int(expected["front_id"])
            or not _positive_int(expected["session_id"])
            or route.sdk_capability_armed is not False
            or route.dispatching_order_ids != ()
            or route.unknown_order_ids not in ((), (observation.order_ref,))
        ):
            raise FactorExecutionError("UNKNOWN_RECOVERY_SESSION_OR_ROUTE_MISMATCH")
        return (
            expected,
            query_set,
        )

    def _validate_unknown_recovery_row_projection(
        self,
        facts: Any,
        observation: Any,
        intent: ExecutionIntentRecord,
        *,
        unresolved_intent_id: Optional[str] = None,
        unresolved_state: str = "UNKNOWN",
        cancel_intent_id: Optional[str] = None,
        allow_exact_local_unknown: bool = True,
    ) -> Tuple[Any, ...]:
        """Require every raw order/trade row to survive projection unambiguously.

        The current UNKNOWN local order can also appear in ``working_orders``
        while the remote full orders query already reports its terminal row.
        That single expected overlap is valid. Other missing, malformed, or
        duplicate source rows cannot be treated as evidence of absence.
        """
        order_source = _one_query_provenance(facts, "orders_result", "orders")
        trade_source = _one_query_provenance(facts, "trades_result", "trades")
        trade_rows = self._validated_trade_observations(facts)
        if trade_source.row_count != len(trade_rows):
            raise FactorExecutionError("UNKNOWN_RECOVERY_TRADE_ROWS_INCOMPLETE")

        projected_order_keys = set()
        for row in tuple(facts.terminal_orders) + tuple(facts.working_orders):
            order_ref = _exact_identifier(getattr(row, "order_ref", None))
            instrument = _exact_identifier(getattr(row, "instrument", None))
            exchange = _exact_identifier(getattr(row, "exchange", None))
            if order_ref is None or instrument is None or exchange is None:
                raise FactorExecutionError("UNKNOWN_RECOVERY_ORDER_ROWS_INCOMPLETE")
            projected_order_keys.add((order_ref, instrument, exchange))
        if order_source.row_count != len(projected_order_keys):
            raise FactorExecutionError("UNKNOWN_RECOVERY_ORDER_ROWS_INCOMPLETE")

        # A same-engine UNKNOWN remains locally working until Broker.next drains
        # the normal terminal update queue. Its exact absence from the remote
        # active map and its unresolved journal state are the only benign
        # projection blockers during that short interval.
        matching_local_unknown = (
            tuple(
                row
                for row in facts.working_orders
                if row.instrument == observation.instrument
                and row.exchange == observation.exchange
                and self._is_exact_unknown_working_order(
                    row, intent, observation, cancel_intent_id=cancel_intent_id
                )
            )
            if allow_exact_local_unknown
            else ()
        )
        if len(matching_local_unknown) > 1:
            raise FactorExecutionError("UNKNOWN_RECOVERY_ORDER_ROWS_AMBIGUOUS")
        if not allow_exact_local_unknown and any(
            row.instrument == observation.instrument and row.exchange == observation.exchange
            for row in facts.working_orders
        ):
            raise FactorExecutionError("DISPATCHING_RECOVERY_ROUTE_HAS_WORKING_ORDER")
        unresolved_intent_id = unresolved_intent_id or intent.intent_id
        if unresolved_state not in ("UNKNOWN", "DISPATCHING"):
            raise FactorExecutionError("UNKNOWN_RECOVERY_INTENT_STATE_INVALID")
        allowed = {"journal_intent_unresolved:{}:{}".format(unresolved_state, unresolved_intent_id)}
        if matching_local_unknown:
            local_ref = matching_local_unknown[0].broker_order_ref
            if type(local_ref) is not int or local_ref <= 0:
                raise FactorExecutionError("UNKNOWN_RECOVERY_ORDER_ROWS_INCOMPLETE")
            allowed.update(
                {
                    "broker_working_order_not_remote_active:{}".format(observation.order_ref),
                    "working_order_execution_state_unobserved:{}".format(local_ref),
                }
            )
            if cancel_intent_id is not None:
                allowed.add("working_order_cancel_state_unobserved:{}".format(local_ref))
        source_projection_prefixes = (
            "remote_order_row_shape_invalid",
            "remote_orders_rows_unobserved",
            "remote_order_trading_day_unobserved_or_mismatch",
            "remote_order_identity_or_state_unobserved",
            "remote_order_identity_duplicate:",
            "remote_terminal_order_trading_day_mismatch:",
            "remote_terminal_order_identity_duplicate:",
            "remote_working_order_",
            "remote_broker_order_",
            "broker_order_",
            "working_order_",
            "broker_working_order_",
            "journal_intent_",
            "remote_trade_rows_unobserved",
            "remote_trade_row_shape_invalid",
            "remote_trade_trading_day_mismatch:",
            "remote_trade_fields_unobserved:",
            "remote_trade_time_after_query:",
            "remote_trade_id_duplicate:",
        )
        for blocker in facts.blockers:
            if blocker in allowed:
                continue
            if blocker.startswith(source_projection_prefixes):
                raise FactorExecutionError("UNKNOWN_RECOVERY_SOURCE_ROWS_AMBIGUOUS")
        return trade_rows

    def _is_exact_unknown_working_order(
        self,
        row: Any,
        intent: ExecutionIntentRecord,
        observation: Any,
        *,
        cancel_intent_id: Optional[str] = None,
    ) -> bool:
        identity = intent.original_identity
        return bool(
            row.order_ref == observation.order_ref
            and row.instrument == observation.instrument
            and row.exchange == observation.exchange
            and row.owner_strategy_scope == self.strategy_scope
            and row.owner_intent_id == intent.intent_id
            and row.execution_unknown is True
            and row.position_effect == "OPEN"
            and row.side == intent.key.side
            and row.broker_order_ref == identity.get("backtrader_order_ref")
            and row.front_id == identity.get("front_id")
            and row.session_id == identity.get("session_id")
            and (row.order_sys_id is None or row.order_sys_id == observation.order_sys_id)
            and (
                cancel_intent_id is None
                or (row.cancel_pending is True and _exact_identifier(cancel_intent_id) is not None)
            )
        )

    def _unknown_terminal_broker_event(
        self, facts: Any, intent: ExecutionIntentRecord, observation: Any, quantity: Decimal
    ) -> Optional[Mapping[str, Any]]:
        identity = intent.original_identity
        bt_ref = identity.get("backtrader_order_ref")
        if type(bt_ref) is not int or bt_ref <= 0:
            return None
        order = getattr(self.broker, "orders", {}).get(bt_ref)
        if order is None or not order.alive():
            return None
        info = getattr(order, "info", {})
        get = getattr(info, "get", lambda name, default=None: default)
        external_ref = _first_text(get("external_order_ref"), get("ctp_order_ref"))
        side = "BUY" if order.isbuy() else "SELL"
        order_size = _decimal_optional(getattr(order, "size", None))
        expected_order_size = quantity if side == "BUY" else -quantity
        if (
            not bool(get("execution_unknown", False))
            or get("factor_intent_id") != intent.intent_id
            or get("factor_strategy_scope") != self.strategy_scope
            or get("instrument_id") != observation.instrument
            or get("exchange_id") != observation.exchange
            or external_ref != observation.order_ref
            or side != intent.key.side
            or get("factor_position_effect") != "OPEN"
            or get("factor_session_account_fingerprint") != identity.get("account_fingerprint")
            or get("factor_session_trading_day") != identity.get("trading_day")
            or get("factor_session_front_id") != identity.get("front_id")
            or get("factor_session_id") != identity.get("session_id")
            or order_size != expected_order_size
            or quantity != quantity.to_integral_value()
        ):
            raise FactorExecutionError("UNKNOWN_BROKER_ORDER_LINEAGE_MISMATCH")
        size = int(quantity)
        canceled = observation.terminal_state == "CANCELED"
        details = {
            "OrderRef": observation.order_ref,
            "OrderSysID": observation.order_sys_id or "",
            "InstrumentID": observation.instrument,
            "ExchangeID": observation.exchange,
            "FrontID": identity["front_id"],
            "SessionID": identity["session_id"],
            "OrderStatus": observation.terminal_status,
            "VolumeTotalOriginal": size,
            "VolumeTraded": 0,
            "VolumeTotal": size,
        }
        return {
            "kind": "order",
            "bt_order_ref": bt_ref,
            "order_ref": observation.order_ref,
            "order_sys_id": observation.order_sys_id,
            "external_order_id": observation.order_sys_id,
            "data_name": getattr(getattr(order, "data", None), "_name", ""),
            "instrument": observation.instrument,
            "exchange_id": observation.exchange,
            "front_id": identity["front_id"],
            "session_id": identity["session_id"],
            "status": "canceled" if canceled else "rejected",
            "side": side.lower(),
            "offset": str(intent.economic_payload.get("offset", "open")),
            "price": float(_decimal_optional(intent.economic_payload.get("limit_price")) or 0),
            "size": size,
            "filled": 0,
            "remaining": size,
            "terminal_confirmed": True,
            "execution_unknown": False,
            "details": details,
        }

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
        self, facts: Any, observation: Any, *, refresh_receipt: Any = None
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

            date_less_native_receipt = self.journal.callback_receipt(
                intent.intent_id,
                _native_trade_callback_id(
                    observation.trade_id,
                    observation.order_ref,
                    observation.instrument,
                    observation.exchange,
                ),
            )
            if (
                date_less_native_receipt is not None
                and not _unusable_trade_callback_matches_observation(
                    observation, date_less_native_receipt.evidence_payload
                )
            ):
                return ExecutionTradeReconciliationItem(
                    observation_id=observation.observation_id,
                    status="BLOCKED",
                    intent_id=intent.intent_id,
                    receipt_id=date_less_native_receipt.receipt_id,
                    execution_id=payload["execution_id"],
                    blocker_code="NATIVE_TRADE_CALLBACK_QUERY_CONFLICT",
                )

            native_receipt = self.journal.callback_receipt(
                intent.intent_id,
                _native_execution_trade_callback_id(payload["execution_id"]),
            )
            if native_receipt is not None and (
                native_receipt.evidence_payload.get("event_type") != "execution_fill"
                or native_receipt.evidence_payload.get("evidence_kind") != "native_trade_callback"
                or not _trade_observation_matches_evidence(
                    observation, native_receipt.evidence_payload
                )
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

            disposition_already_persisted = False
            disposition_proof = None
            disposition_blocker = None
            if native_receipt is not None and not native_receipt.acknowledged:
                existing_disposition = self.journal.callback_query_disposition(
                    native_receipt.receipt_id
                )
                if existing_disposition is not None:
                    if (
                        prior is None
                        or existing_disposition.query_receipt_id != prior.receipt_id
                        or existing_disposition.intent_id != intent.intent_id
                        or existing_disposition.execution_id != payload["execution_id"]
                        or not _callback_query_disposition_matches_observation(
                            existing_disposition,
                            intent,
                            observation,
                            account_scope=self.account_scope,
                            strategy_scope=self.strategy_scope,
                        )
                    ):
                        return ExecutionTradeReconciliationItem(
                            observation_id=observation.observation_id,
                            status="BLOCKED",
                            intent_id=intent.intent_id,
                            receipt_id=native_receipt.receipt_id,
                            execution_id=payload["execution_id"],
                            blocker_code="CALLBACK_QUERY_DISPOSITION_CONFLICT",
                        )
                    disposition_already_persisted = True
                else:
                    try:
                        disposition_proof = self._callback_query_disposition_proof(
                            facts,
                            refresh_receipt,
                            observation,
                            intent,
                        )
                    except FactorExecutionError as error:
                        disposition_blocker = error.code

            def project(cursor, receipt_id):
                result = apply_factor_execution_fill(cursor, receipt_id=receipt_id)
                if getattr(result, "status", None) not in ("APPLIED", "DUPLICATE"):
                    return result
                self.journal.acknowledge_callback_in_transaction(cursor, receipt_id)
                if native_receipt is not None and not native_receipt.acknowledged:
                    if disposition_already_persisted:
                        return result
                    if disposition_proof is None:
                        if disposition_blocker is None:
                            return result, "CALLBACK_QUERY_RESTART_PROOF_UNAVAILABLE"
                        return result, disposition_blocker
                    try:
                        self.journal.record_callback_query_disposition(
                            cursor,
                            native_receipt_id=native_receipt.receipt_id,
                            query_receipt_id=receipt_id,
                            intent_id=intent.intent_id,
                            execution_id=payload["execution_id"],
                            proof_payload=disposition_proof,
                        )
                    except ExecutionDecisionJournalError as error:
                        if error.code in {
                            "CALLBACK_QUERY_RESTART_NOT_PROVEN",
                            "CALLBACK_QUERY_RESTART_ORIGIN_UNKNOWN",
                        }:
                            return result, error.code
                        raise
                return result

            receipt, projected = self.journal.record_callback_projected(
                intent.intent_id,
                callback_id,
                payload,
                project=project,
            )
            if isinstance(projected, tuple):
                projection, disposition_blocker = projected
            else:
                projection = projected
            status = getattr(projection, "status", "BLOCKED")
            blocker = getattr(projection, "blocker_code", None)
            if blocker is None:
                blocker = disposition_blocker
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

    def _callback_query_disposition_proof(
        self, facts: Any, refresh_receipt: Any, observation: Any, intent: ExecutionIntentRecord
    ) -> Mapping[str, Any]:
        """Build a current five-query proof for one exact native callback fill."""

        from .factor_execution_facts import (
            _BASE_FAMILIES,
            FactorExecutionRefreshReceipt,
            _query_set_matches,
        )

        if type(refresh_receipt) is not FactorExecutionRefreshReceipt:
            raise FactorExecutionError("CALLBACK_QUERY_REFRESH_RECEIPT_REQUIRED")
        if (
            refresh_receipt.cancelled
            or refresh_receipt.deadline_reached
            or refresh_receipt.blockers
            or refresh_receipt.pending_families
            or tuple(refresh_receipt.requested_families[: len(_BASE_FAMILIES)]) != _BASE_FAMILIES
            or tuple(refresh_receipt.attempted_families[: len(_BASE_FAMILIES)]) != _BASE_FAMILIES
            or not _time_not_after(refresh_receipt.started_at, refresh_receipt.completed_at)
            or facts.available_at is None
            or not _time_not_after(facts.available_at, refresh_receipt.completed_at)
        ):
            raise FactorExecutionError("CALLBACK_QUERY_REFRESH_RECEIPT_INCOMPLETE")
        receipt_facts = tuple(
            item for item in refresh_receipt.query_provenance if item.family in _BASE_FAMILIES
        )
        facts_facts = tuple(
            item for item in facts.query_provenance if item.family in _BASE_FAMILIES
        )
        if (
            tuple(item.family for item in receipt_facts) != _BASE_FAMILIES
            or receipt_facts != facts_facts
            or any(
                item.source_owned is not True
                or item.query_complete is not True
                or item.scope_complete is not True
                or type(item.request_id) is not int
                or item.request_id <= 0
                or type(item.connection_generation) is not int
                or item.connection_generation <= 0
                or not _exact_identifier(item.account_fingerprint)
                or not _valid_trading_day(item.trading_day)
                or item.started_at is None
                or item.completed_at is None
                or not _time_not_after(item.started_at, item.completed_at)
                or not _time_not_after(item.completed_at, refresh_receipt.completed_at)
                for item in receipt_facts
            )
        ):
            raise FactorExecutionError("CALLBACK_QUERY_REFRESH_PROVENANCE_MISMATCH")
        query_set = refresh_receipt.query_set
        now = datetime.now(timezone.utc)
        if (
            query_set is None
            or query_set.query_set_id != facts.query_set_id
            or not _query_set_matches(
                query_set,
                receipt_facts,
                now=now,
                max_age=timedelta(seconds=60),
            )
            or not _time_not_after(refresh_receipt.started_at, query_set.started_at_utc)
            or not _time_not_after(query_set.started_at_utc, query_set.completed_at_utc)
            or not _time_not_after(query_set.completed_at_utc, refresh_receipt.completed_at)
            or not _time_not_after(refresh_receipt.completed_at, now)
            or now - _aware_utc(refresh_receipt.completed_at) > timedelta(seconds=60)
            or facts.account is None
            or query_set.account_fingerprint != facts.account.account_fingerprint
            or query_set.connection_generation != facts.account.connection_generation
            or query_set.trading_day != facts.account.trading_day
        ):
            raise FactorExecutionError("CALLBACK_QUERY_REFRESH_QUERY_SET_MISMATCH")
        if (
            facts.account.account_scope != self.account_scope
            or facts.strategy_scope != self.strategy_scope
            or observation.account_fingerprint != query_set.account_fingerprint
            or observation.connection_generation != query_set.connection_generation
            or observation.trading_day != query_set.trading_day
            or not _time_not_after(observation.available_at, query_set.completed_at_utc)
        ):
            raise FactorExecutionError("CALLBACK_QUERY_REFRESH_TRADE_SCOPE_MISMATCH")
        try:
            route = self.store.registered_sim_route_eligibility(
                observation.instrument, observation.exchange
            )
        except Exception as error:
            raise FactorExecutionError("CALLBACK_QUERY_CURRENT_SESSION_UNAVAILABLE") from error
        if (
            route.instrument_id != observation.instrument
            or route.exchange_id != observation.exchange
            or route.account_fingerprint != query_set.account_fingerprint
            or route.connection_generation != query_set.connection_generation
            or route.trading_day != query_set.trading_day
            or route.current_session_account_fingerprint != query_set.account_fingerprint
            or route.current_session_connection_generation != query_set.connection_generation
            or route.current_session_trading_day != query_set.trading_day
            or route.current_session_read_only_ready is not True
        ):
            raise FactorExecutionError("CALLBACK_QUERY_CURRENT_SESSION_MISMATCH")

        identity = intent.original_identity
        original = {
            "account_scope": self.account_scope,
            "strategy_scope": self.strategy_scope,
            "trading_day": identity.get("trading_day"),
            "instrument": identity.get("instrument_id"),
            "exchange": identity.get("exchange_id"),
            "order_ref": identity.get("order_ref"),
            "front_id": identity.get("front_id"),
            "session_id": identity.get("session_id"),
            "order_sys_id": identity.get("order_sys_id"),
        }
        if (
            intent.key.action != "SUBMIT"
            or intent.key.instrument != observation.instrument
            or intent.key.side != observation.side
            or intent.key.position_effect != observation.position_effect
            or identity.get("operation") != "insert"
            or identity.get("account_fingerprint") != query_set.account_fingerprint
            or identity.get("trading_day") != observation.trading_day
            or identity.get("instrument_id") != observation.instrument
            or identity.get("exchange_id") != observation.exchange
            or identity.get("order_ref") != observation.order_ref
            or not _positive_int(identity.get("front_id"))
            or not _positive_int(identity.get("session_id"))
            or (
                identity.get("order_sys_id") is not None
                and identity.get("order_sys_id") != observation.order_sys_id
            )
        ):
            raise FactorExecutionError("CALLBACK_QUERY_ORIGINAL_IDENTITY_MISMATCH")

        order_rows = tuple(facts.working_orders) + tuple(facts.terminal_orders)
        matching_orders = tuple(
            row
            for row in order_rows
            if row.order_ref == observation.order_ref
            and row.instrument == observation.instrument
            and row.exchange == observation.exchange
            and row.front_id == identity["front_id"]
            and row.session_id == identity["session_id"]
            and (
                identity.get("order_sys_id") is None or row.order_sys_id == identity["order_sys_id"]
            )
            and (observation.order_sys_id is None or row.order_sys_id == observation.order_sys_id)
        )
        if len(matching_orders) != 1:
            raise FactorExecutionError("CALLBACK_QUERY_ORDER_MATCH_NOT_UNIQUE")
        matched_order = matching_orders[0]
        if (
            not _positive_int(matched_order.front_id)
            or not _positive_int(matched_order.session_id)
            or not _exact_identifier(matched_order.order_ref)
            or not _exact_identifier(matched_order.instrument)
            or not _exact_identifier(matched_order.exchange)
            or (
                matched_order.order_sys_id is not None
                and not _exact_identifier(matched_order.order_sys_id)
            )
        ):
            raise FactorExecutionError("CALLBACK_QUERY_ORDER_IDENTITY_INVALID")

        return {
            "original_order": original,
            "matched_order": {
                "front_id": matched_order.front_id,
                "session_id": matched_order.session_id,
                "order_ref": matched_order.order_ref,
                "instrument": matched_order.instrument,
                "exchange": matched_order.exchange,
                "order_sys_id": matched_order.order_sys_id,
            },
            "trade": {
                "trade_id": observation.trade_id,
                "trade_date": observation.trade_date,
                "trade_time": observation.trade_time,
                "query_set_id": query_set.query_set_id,
                "observation_id": observation.observation_id,
                "snapshot_id": observation.snapshot_id,
                "request_id": observation.request_id,
                "account_fingerprint": observation.account_fingerprint,
                "connection_generation": observation.connection_generation,
                "trading_day": observation.trading_day,
                "side": observation.side,
                "position_effect": observation.position_effect,
                "order_sys_id": observation.order_sys_id,
                "quantity": observation.volume,
                "price": observation.price,
                "fee": observation.fee,
                "filled_at_ns": _datetime_epoch_ns(observation.trade_time_utc),
            },
            "query_set": {
                "query_set_id": query_set.query_set_id,
                "account_fingerprint": query_set.account_fingerprint,
                "connection_generation": query_set.connection_generation,
                "trading_day": query_set.trading_day,
                "started_at_utc": _utc_text(query_set.started_at_utc),
                "completed_at_utc": _utc_text(query_set.completed_at_utc),
                "available_at_utc": _utc_text(query_set.completed_at_utc),
                "family_request_ids": query_set.query_ids,
            },
        }

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
            "order_sys_id": _first_text(details.get("OrderSysID")),
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
        loss_guard_context: Optional[ExecutionRunLossGuardContext] = None,
        source_receipt: Optional[ExecutionSourceReceipt] = None,
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
            loss_guard_context=loss_guard_context,
            source_receipt=source_receipt,
        )

    def record_source_receipt(
        self,
        *,
        key: ExecutionDecisionKey,
        batch: Any,
        source_receipt: ExecutionSourceReceipt,
    ) -> Any:
        """Persist an ineligible source batch without opening a dispatch scope."""
        if not isinstance(key, ExecutionDecisionKey):
            raise FactorExecutionError("INVALID_DECISION_KEY")
        if (
            key.account_scope != self.account_scope
            or key.strategy_scope != self.strategy_scope
            or key.logical_run_id != self.logical_run_id
        ):
            raise FactorExecutionError("DECISION_SCOPE_IDENTITY_MISMATCH")
        if self._active_scope.get() is not None:
            raise FactorExecutionError("NESTED_DECISION_SCOPE")
        if (
            type(source_receipt) is not ExecutionSourceReceipt
            or batch is None
            or not self._batch_matches_source_key(batch, key)
            or source_receipt.batch_id != batch.batch_id
            or source_receipt.epoch_id != batch.epoch_id
            or source_receipt.close_time != _utc_text(batch.close_time)
        ):
            raise FactorExecutionError("SOURCE_RECEIPT_BATCH_MISMATCH")
        return self.journal.record_grid_decision(
            key,
            {},
            intent_keys=(),
            epoch_id=str(batch.epoch_id),
            batch_id=batch.batch_id,
            eligible=False,
            complete=True,
            live_ready=False,
            inputs_complete=False,
            source_receipt=source_receipt,
        )

    @staticmethod
    def _batch_matches_source_key(batch: Any, key: ExecutionDecisionKey) -> bool:
        return bool(
            getattr(batch, "cohort_id", None) == key.cohort_id
            and getattr(batch, "close_time", None) is not None
            and getattr(batch, "batch_id", None) is not None
            and _same_time(getattr(batch, "close_time", None), key.close_time)
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

    def _route_eligibility(
        self, instrument_id: str, exchange_id: str, facts: Any
    ) -> Dict[str, Any]:
        try:
            route = self.store.registered_sim_route_eligibility(instrument_id, exchange_id)
        except Exception as error:
            raise FactorExecutionError("REGISTERED_SIM_ROUTE_UNOBSERVED") from error
        account = getattr(facts, "account", None)
        expected = {
            "account_fingerprint": getattr(account, "account_fingerprint", None),
            "connection_generation": getattr(account, "connection_generation", None),
            "trading_day": getattr(account, "trading_day", None),
        }
        if (
            not isinstance(expected["account_fingerprint"], str)
            or not expected["account_fingerprint"]
            or type(expected["connection_generation"]) is not int
            or expected["connection_generation"] <= 0
            or not isinstance(expected["trading_day"], str)
            or _valid_trading_day(expected["trading_day"]) is None
        ):
            raise FactorExecutionError("EXECUTION_FACT_SESSION_IDENTITY_UNAVAILABLE")
        expected["front_id"] = _positive_int(getattr(route, "current_session_front_id", None))
        expected["session_id"] = _positive_int(getattr(route, "current_session_id", None))
        if expected["front_id"] is None or expected["session_id"] is None:
            raise FactorExecutionError("EXECUTION_FACT_NATIVE_SESSION_IDENTITY_UNAVAILABLE")
        query_identity_matches = (
            getattr(route, "account_fingerprint", None) == expected["account_fingerprint"]
            and getattr(route, "connection_generation", None) == expected["connection_generation"]
            and getattr(route, "trading_day", None) == expected["trading_day"]
        )
        current_session_matches = (
            getattr(route, "current_session_account_fingerprint", None)
            == expected["account_fingerprint"]
            and getattr(route, "current_session_connection_generation", None)
            == expected["connection_generation"]
            and getattr(route, "current_session_trading_day", None) == expected["trading_day"]
            and getattr(route, "current_session_trading_ready", None) is True
        )
        templates_configured = getattr(route, "arm_templates_configured", None)
        template_configured = getattr(route, "arm_template_configured", None)
        arm_api_available = getattr(route, "arm_api_available", None)
        active_grant_matches = (
            getattr(route, "sdk_capability_managed", None) is True
            and getattr(route, "sdk_capability_armed", None) is True
            and getattr(route, "capability_matches_route", None) is True
        )
        if templates_configured is True:
            route_arm_ready = template_configured is True and arm_api_available is True
        elif templates_configured is False:
            # Explicit-arm compatibility applies only when the wrapper has no
            # template map at all. A missing key in a configured map is never
            # an implicit fallback.
            route_arm_ready = template_configured is False and active_grant_matches
        else:
            route_arm_ready = False
        positive = (
            getattr(route, "allow_writes", None) is True
            and getattr(route, "frozen", None) is False
            and getattr(route, "sdk_frozen", None) is False
            and getattr(route, "unknown_order_count", None) == 0
            and getattr(route, "unknown_order_ids", None) == ()
            and getattr(route, "dispatching_order_ids", None) == ()
            and getattr(route, "capability_observed", None) is True
            and route_arm_ready
            and query_identity_matches
            and current_session_matches
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
            and item.connection_generation == expected["connection_generation"]
            and item.trading_day == expected["trading_day"]
            and item.current_session_account_fingerprint == expected["account_fingerprint"]
            and item.current_session_connection_generation == expected["connection_generation"]
            and item.current_session_trading_day == expected["trading_day"]
            and item.current_session_trading_ready is True
            and item.arm_templates_configured is templates_configured
            and item.arm_template_configured is template_configured
            and item.arm_api_available is arm_api_available
            and (
                (templates_configured is True and template_configured is True)
                or (
                    templates_configured is False
                    and template_configured is False
                    and item.capability_managed is True
                    and item.capability_armed is True
                    and item.capability_matches_route is True
                )
            )
        ]
        if len(matches) != 1:
            raise FactorExecutionError("EXECUTION_FACT_ROUTE_NOT_READY")
        return expected


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
        loss_guard_context: Optional[ExecutionRunLossGuardContext] = None,
        source_receipt: Optional[ExecutionSourceReceipt] = None,
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
        self.loss_guard_context = loss_guard_context
        self.source_receipt = source_receipt
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
        self._dispatch_gate_context = None
        self._dispatch_gate_claimed = False

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
                loss_guard_context=self.loss_guard_context,
                source_receipt=self.source_receipt,
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
            self._finish_dispatch_gate()
        return False

    def begin_order(self, order: Any, *, action: str) -> FactorDispatchAttempt:
        if self._dispatch_gate_context is not None:
            raise FactorExecutionError("DISPATCH_GATE_SCOPE_ALREADY_ACTIVE")
        gate_context = self.coordinator.journal.dispatch_serialization_gate()
        try:
            gate_context.__enter__()
        except ExecutionDecisionJournalError as error:
            raise FactorExecutionError(error.code) from error
        self._dispatch_gate_context = gate_context
        self._dispatch_gate_claimed = False
        try:
            return self._begin_order_under_dispatch_gate(order, action=action)
        except BaseException:
            self._finish_dispatch_gate()
            raise

    def _begin_order_under_dispatch_gate(self, order: Any, *, action: str) -> FactorDispatchAttempt:
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
        expected_session = self.coordinator._route_eligibility(
            instrument_id, exchange_id, self.execution_facts
        )
        session_info = {
            "factor_session_account_fingerprint": expected_session["account_fingerprint"],
            "factor_session_connection_generation": expected_session["connection_generation"],
            "factor_session_trading_day": expected_session["trading_day"],
            "factor_session_front_id": expected_session["front_id"],
            "factor_session_id": expected_session["session_id"],
        }
        for name, value in session_info.items():
            existing = get(name)
            # A cancel reuses the original Order object, whose session tags
            # describe the earlier submit. The current fully reconciled
            # cancellation decision supersedes those tags; a new submit may
            # not carry caller-selected session identity.
            if action != "CANCEL" and existing is not None and existing != value:
                raise FactorExecutionError("ORDER_SESSION_IDENTITY_MISMATCH")
        order.addinfo(**session_info)
        try:
            # Arm or switch the exact SDK grant while the decision is bound to
            # the query-set session. This precedes order-ref reservation and
            # the durable dispatch claim, so a missing template, stale session
            # or rejected arm cannot reach the native Store method.
            self.coordinator.store.registered_sim_ensure_arm(
                instrument_id,
                exchange_id,
                expected_session=expected_session,
            )
        except Exception as error:
            raise FactorExecutionError("REGISTERED_SIM_ARM_NOT_READY") from error
        if action == "CANCEL":
            order_ref = _first_text(
                get("external_order_ref"), get("ctp_order_ref"), get("order_ref")
            )
            owner_intent_id = _first_text(get("factor_intent_id"))
            if order_ref is None or owner_intent_id is None:
                raise FactorExecutionError("CANCEL_REMOTE_IDENTITY_REQUIRED")
            current_order_sys_id = self._known_cancel_order_sys_id(
                order,
                owner_intent_id=owner_intent_id,
                order_ref=order_ref,
                instrument_id=instrument_id,
                exchange_id=exchange_id,
                expected_session=expected_session,
            )
            cached_order_sys_id = _first_text(get("order_sys_id"))
            if cached_order_sys_id is not None and cached_order_sys_id != current_order_sys_id:
                raise FactorExecutionError("CANCEL_REMOTE_SYSID_CONFLICT")
            # The source query and durable binding are the authority when the
            # original submit response/callback did not carry OrderSysID.  Keep
            # the immutable submit dispatch record untouched; this only fills
            # the framework order projection used by the Store's CANCEL path.
            order.addinfo(order_sys_id=current_order_sys_id)
            economics.setdefault("owner_intent_id", owner_intent_id)
            identity = {
                "backtrader_order_ref": int(order.ref),
                "order_ref": order_ref,
                "order_sys_id": current_order_sys_id,
                # The current query-bound session is authoritative. Older
                # Backtrader orders may carry only the namespaced factor
                # session tags, and the binding above has already checked
                # those tags against this exact FrontID/SessionID pair.
                "front_id": expected_session["front_id"],
                "session_id": expected_session["session_id"],
                "instrument_id": instrument_id,
                "exchange_id": exchange_id,
                "account_fingerprint": expected_session["account_fingerprint"],
                "connection_generation": expected_session["connection_generation"],
                "trading_day": expected_session["trading_day"],
                "owner_intent_id": owner_intent_id,
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
                "account_fingerprint": expected_session["account_fingerprint"],
                "connection_generation": expected_session["connection_generation"],
                "trading_day": trading_day,
                "front_id": expected_session["front_id"],
                "session_id": expected_session["session_id"],
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
            loss_guard_context=self.loss_guard_context,
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
        claim = self.coordinator.journal.claim_dispatch(
            intent.intent_id,
            loss_guard_context=self.loss_guard_context,
        )
        if claim is None:
            raise FactorExecutionError("DISPATCH_ALREADY_CLAIMED")
        intent = claim.intent
        self._dispatch_gate_claimed = True
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

    def _known_cancel_order_sys_id(
        self,
        order: Any,
        *,
        owner_intent_id: str,
        order_ref: str,
        instrument_id: str,
        exchange_id: str,
        expected_session: Mapping[str, Any],
    ) -> str:
        """Return only the SysID joined through this scope's bound live facts."""
        facts = self.execution_facts
        working_matches = tuple(
            row
            for row in getattr(facts, "working_orders", ())
            if getattr(row, "owner_intent_id", None) == owner_intent_id
            and getattr(row, "broker_order_ref", None) == int(order.ref)
            and getattr(row, "order_ref", None) == order_ref
            and getattr(row, "instrument", None) == instrument_id
            and getattr(row, "exchange", None) == exchange_id
        )
        intent_matches = tuple(
            item
            for item in getattr(facts, "execution_intents", ())
            if getattr(item, "intent_id", None) == owner_intent_id
        )
        if len(working_matches) != 1 or len(intent_matches) != 1:
            raise FactorExecutionError("CANCEL_REMOTE_SYSID_BINDING_UNAVAILABLE")
        working = working_matches[0]
        intent = intent_matches[0]
        binding = getattr(intent, "order_sys_id_binding", None)
        account = getattr(facts, "account", None)
        original = getattr(intent, "original_identity", None)
        provider = getattr(intent, "provider_identity", None)
        binding_sys_id = (
            _first_text(binding.get("order_sys_id")) if isinstance(binding, Mapping) else None
        )
        provider_sys_id = (
            _first_text(provider.get("order_sys_id")) if isinstance(provider, Mapping) else None
        )
        callback_identity_matches = bool(
            binding is None
            and provider_sys_id is not None
            and provider_sys_id == getattr(working, "order_sys_id", None)
            and isinstance(provider, Mapping)
            and provider.get("order_ref") == order_ref
            and isinstance(original, Mapping)
            and original.get("order_sys_id") in (None, "", provider_sys_id)
        )
        sys_id = binding_sys_id if binding_sys_id is not None else provider_sys_id
        local_info = getattr(order, "info", {})
        get = getattr(local_info, "get", lambda name, default=None: default)
        if not (
            sys_id is not None
            and getattr(facts, "account_scope", None) == self.coordinator.account_scope
            and getattr(facts, "strategy_scope", None) == self.coordinator.strategy_scope
            and getattr(intent, "account_scope", None) == self.coordinator.account_scope
            and getattr(intent, "strategy_scope", None) == self.coordinator.strategy_scope
            and getattr(intent, "action", None) == "SUBMIT"
            and getattr(intent, "state", None) == "KNOWN"
            and getattr(intent, "dispatch_state", None) == "KNOWN"
            and getattr(working, "state", None) in ("ACCEPTED", "PARTIAL")
            and getattr(working, "execution_unknown", None) is False
            and getattr(working, "cancel_pending", None) is False
            and getattr(working, "owner_strategy_scope", None)
                == self.coordinator.strategy_scope
            and getattr(working, "order_sys_id", None) == sys_id
            and (
                callback_identity_matches
                or (
                    isinstance(binding, Mapping)
                    and binding.get("intent_id") == owner_intent_id
                    and binding.get("account_scope") == self.coordinator.account_scope
                    and binding.get("strategy_scope") == self.coordinator.strategy_scope
                    and binding.get("account_fingerprint")
                        == expected_session.get("account_fingerprint")
                    and binding.get("connection_generation")
                        == expected_session.get("connection_generation")
                    and binding.get("trading_day") == expected_session.get("trading_day")
                    and binding.get("instrument") == instrument_id
                    and binding.get("exchange") == exchange_id
                    and binding.get("order_ref") == order_ref
                    and binding.get("front_id") == expected_session.get("front_id")
                    and binding.get("session_id") == expected_session.get("session_id")
                    and type(binding.get("query_request_id")) is int
                    and binding.get("query_request_id") > 0
                    and _exact_identifier(binding.get("query_rows_sha256"))
                    and _exact_identifier(binding.get("matched_row_sha256"))
                )
            )
            and isinstance(original, Mapping)
            and original.get("operation") == "insert"
            and original.get("backtrader_order_ref") == int(order.ref)
            and original.get("order_ref") == order_ref
            and original.get("instrument_id") == instrument_id
            and original.get("exchange_id") == exchange_id
            and original.get("account_fingerprint")
                == expected_session.get("account_fingerprint")
            and original.get("connection_generation")
                == expected_session.get("connection_generation")
            and original.get("trading_day") == expected_session.get("trading_day")
            and original.get("front_id") == expected_session.get("front_id")
            and original.get("session_id") == expected_session.get("session_id")
            and isinstance(provider, Mapping)
            and provider.get("order_ref") == order_ref
            and (provider.get("order_sys_id") in (None, "", sys_id))
            and getattr(account, "account_fingerprint", None)
                == expected_session.get("account_fingerprint")
            and getattr(account, "connection_generation", None)
                == expected_session.get("connection_generation")
            and getattr(account, "trading_day", None) == expected_session.get("trading_day")
            and getattr(working, "front_id", None) == expected_session.get("front_id")
            and getattr(working, "session_id", None) == expected_session.get("session_id")
            and get("execution_unknown") is not True
        ):
            raise FactorExecutionError("CANCEL_REMOTE_SYSID_BINDING_MISMATCH")
        return sys_id

    def complete_order(
        self, order: Any, attempt: FactorDispatchAttempt, *, response=None, error=None
    ):
        try:
            result = self._complete_order_under_dispatch_gate(
                order, attempt, response=response, error=error
            )
        except BaseException:
            self._finish_dispatch_gate()
            raise
        self._dispatch_gate_claimed = False
        self._finish_dispatch_gate()
        return result

    def _complete_order_under_dispatch_gate(
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

    def _finish_dispatch_gate(self) -> None:
        gate_context = self._dispatch_gate_context
        if gate_context is None:
            return
        self._dispatch_gate_context = None
        if self._dispatch_gate_claimed:
            try:
                self.coordinator.journal._retain_dispatch_serialization_gate(gate_context)
            except Exception:
                # If the gate cannot be retained, do not silently proceed to
                # another write in this process. Keep the context reachable.
                self._dispatch_gate_context = gate_context
                raise
            return
        gate_context.__exit__(None, None, None)

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
        if any(
            key.action == "SUBMIT" and key.position_effect == "OPEN"
            for key in self.intent_keys
        ):
            # An exact durable decision readback is not a new admission. Let
            # the journal perform its canonical key/economics/intent equality
            # check first; only a missing row needs fresh caller facts here.
            # New intent preparation and every PREPARED claim still recheck
            # the persisted guard at their own journal transaction boundary.
            if self.loss_guard_context is not None and (
                coordinator.journal.decision_for_key(self.key) is None
            ):
                coordinator._validate_open_loss_guard_scope(
                    self.loss_guard_context,
                    self.execution_facts.account,
                )
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


def _native_execution_trade_callback_id(execution_id: str) -> str:
    return "ctp-trade:" + hashlib.sha256(execution_id.encode("utf-8")).hexdigest()


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
        and (observation.fee is None or stored_fee is None or stored_fee == observation.fee)
        and (
            evidence.get("order_sys_id") is None
            or observation.order_sys_id is None
            or evidence.get("order_sys_id") == observation.order_sys_id
        )
    )


def _callback_query_disposition_matches_observation(
    disposition: Any,
    intent: ExecutionIntentRecord,
    observation: Any,
    *,
    account_scope: str,
    strategy_scope: str,
) -> bool:
    """Match a later source row to the immutable first-query disposition."""

    proof = getattr(disposition, "proof_payload", None)
    if not isinstance(proof, Mapping):
        return False
    original = proof.get("original_order")
    matched = proof.get("matched_order")
    trade = proof.get("trade")
    query_set = proof.get("query_set")
    identity = intent.original_identity
    expected_execution_id = "ctp:{}:{}".format(observation.trade_date, observation.trade_id)
    expected_original = {
        "account_scope": account_scope,
        "strategy_scope": strategy_scope,
        "trading_day": identity.get("trading_day"),
        "instrument": identity.get("instrument_id"),
        "exchange": identity.get("exchange_id"),
        "order_ref": identity.get("order_ref"),
        "front_id": identity.get("front_id"),
        "session_id": identity.get("session_id"),
        "order_sys_id": identity.get("order_sys_id"),
    }
    if (
        disposition.disposition_code != "QUERY_MATCHED_BROKER_ACK_UNOBSERVED_AFTER_RESTART"
        or disposition.intent_id != intent.intent_id
        or disposition.execution_id != expected_execution_id
        or proof.get("execution_id") != expected_execution_id
        or not isinstance(original, Mapping)
        or dict(original) != expected_original
        or not isinstance(matched, Mapping)
        or not isinstance(trade, Mapping)
        or not isinstance(query_set, Mapping)
        or intent.key.action != "SUBMIT"
        or intent.key.instrument != observation.instrument
        or intent.key.side != observation.side
        or intent.key.position_effect != observation.position_effect
        or observation.trading_day != identity.get("trading_day")
        or observation.account_fingerprint != identity.get("account_fingerprint")
        or observation.order_ref != identity.get("order_ref")
        or observation.instrument != identity.get("instrument_id")
        or observation.exchange != identity.get("exchange_id")
        or matched.get("order_ref") != identity.get("order_ref")
        or matched.get("front_id") != identity.get("front_id")
        or matched.get("session_id") != identity.get("session_id")
        or matched.get("instrument") != identity.get("instrument_id")
        or matched.get("exchange") != identity.get("exchange_id")
        or query_set.get("account_fingerprint") != observation.account_fingerprint
        or query_set.get("trading_day") != observation.trading_day
        or trade.get("trade_id") != observation.trade_id
        or trade.get("trade_date") != observation.trade_date
        or trade.get("trade_time") != observation.trade_time
        or trade.get("account_fingerprint") != observation.account_fingerprint
        or trade.get("trading_day") != observation.trading_day
        or trade.get("side") != observation.side
        or trade.get("position_effect") != observation.position_effect
        or trade.get("filled_at_ns") != _datetime_epoch_ns(observation.trade_time_utc)
        or query_set.get("query_set_id") != trade.get("query_set_id")
        or query_set.get("connection_generation") != trade.get("connection_generation")
    ):
        return False
    proof_sys_id = trade.get("order_sys_id")
    if (
        proof_sys_id is not None
        and observation.order_sys_id is not None
        and proof_sys_id != observation.order_sys_id
    ):
        return False
    if (
        matched.get("order_sys_id") is not None
        and observation.order_sys_id is not None
        and matched.get("order_sys_id") != observation.order_sys_id
    ):
        return False
    stored_quantity = _decimal_optional(trade.get("quantity"))
    stored_price = _decimal_optional(trade.get("price"))
    stored_fee = _decimal_optional(trade.get("fee"))
    return bool(
        stored_quantity == observation.volume
        and stored_price == observation.price
        and (stored_fee is None or observation.fee is None or stored_fee == observation.fee)
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


def _unknown_terminal_reconciliation_id(
    intent_id: str, observation_id: str, query_set_id: str, snapshot_id: str
) -> str:
    material = json.dumps(
        (intent_id, observation_id, query_set_id, snapshot_id),
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return "unknown-terminal:" + hashlib.sha256(material.encode("ascii")).hexdigest()


def _dispatching_cancel_reconciliation_ids(
    parent_intent_id: str,
    cancel_intent_id: str,
    observation_id: str,
    query_set_id: str,
    snapshot_id: str,
) -> Tuple[str, str]:
    material = json.dumps(
        (parent_intent_id, cancel_intent_id, observation_id, query_set_id, snapshot_id),
        ensure_ascii=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(material.encode("ascii")).hexdigest()
    return "dispatching-cancel-parent:" + digest, "dispatching-cancel-child:" + digest


def _dispatching_cancel_absence_ack_record_matches(
    record: Any,
    *,
    parent_intent_id: str,
    cancel_intent_id: str,
    parent_reconciliation_id: str,
    cancel_reconciliation_id: str,
    original_identity: Mapping[str, Any],
    acknowledgement_id: str,
    acknowledgement_query_id: str,
) -> bool:
    provider = getattr(record, "provider_identity", None)
    current_session = provider.get("current_session") if isinstance(provider, Mapping) else None
    original = dict(original_identity)
    return bool(
        getattr(record, "reconciliation_id", None) == acknowledgement_id
        and getattr(record, "intent_id", None) == parent_intent_id
        and dict(getattr(record, "original_identity", {})) == original
        and getattr(record, "query_id", None) == acknowledgement_query_id
        and getattr(record, "state", None) == "KNOWN"
        and getattr(record, "outcome_code", None) == "LOCAL_STORE_ABSENCE"
        and getattr(record, "terminal_state", None) is None
        and getattr(record, "terminal_event_id", None) is None
        and getattr(record, "position_snapshot_id", None) is None
        and getattr(record, "position_flat", None) is None
        and isinstance(provider, Mapping)
        and isinstance(current_session, Mapping)
        and provider.get("evidence_kind") == "LOCAL_STORE_ABSENCE"
        and provider.get("cancel_recovery_kind") == "dispatching_cancel_store_absence_ack"
        and provider.get("store_assertion") == "ALREADY_ABSENT"
        and provider.get("parent_intent_id") == parent_intent_id
        and provider.get("cancel_intent_id") == cancel_intent_id
        and provider.get("parent_reconciliation_id") == parent_reconciliation_id
        and provider.get("cancel_reconciliation_id") == cancel_reconciliation_id
        and provider.get("cas_parent_reconciliation_id") == parent_reconciliation_id
        and provider.get("cas_cancel_reconciliation_id") == cancel_reconciliation_id
        and provider.get("acknowledgement_query_id") == acknowledgement_query_id
        and _exact_identifier(provider.get("query_observation_id"))
        and _exact_identifier(provider.get("query_set_id"))
        and _exact_identifier(provider.get("snapshot_id"))
        and provider.get("original_identity") == original
        and provider.get("original_order_ref") == original.get("order_ref")
        and provider.get("instrument") == original.get("instrument_id")
        and provider.get("exchange") == original.get("exchange_id")
        and current_session.get("account_fingerprint") == original.get("account_fingerprint")
        and current_session.get("trading_day") == original.get("trading_day")
        and type(current_session.get("connection_generation")) is int
        and current_session.get("connection_generation") > 0
        and type(current_session.get("front_id")) is int
        and current_session.get("front_id") > 0
        and type(current_session.get("session_id")) is int
        and current_session.get("session_id") > 0
        and current_session.get("read_only_ready") is True
    )


def _unknown_terminal_resolution_matches(
    resolution: Any,
    reconciliation: Any,
    *,
    account_scope: str,
    identity: Mapping[str, Any],
    observation: Any,
    terminal_state: str,
    volume_total_original: Decimal,
) -> bool:
    """Validate a prior durable no-fill resolution before retrying Store retirement."""
    provider = getattr(reconciliation, "provider_identity", None)
    if not isinstance(provider, Mapping):
        return False
    expected_fields = {
        "order_ref": observation.order_ref,
        "order_sys_id": observation.order_sys_id,
        "front_id": identity.get("front_id"),
        "session_id": identity.get("session_id"),
        "instrument": observation.instrument,
        "exchange": observation.exchange,
        "account_fingerprint": observation.account_fingerprint,
        "trading_day": observation.trading_day,
        "terminal_status": observation.terminal_status,
        "terminal_state": observation.terminal_state,
        "volume_total_original": str(volume_total_original),
        "volume_traded": "0",
        "volume_total": str(volume_total_original),
        "original_account_fingerprint": identity.get("account_fingerprint"),
        "original_connection_generation": identity.get("connection_generation"),
        "original_trading_day": identity.get("trading_day"),
        "original_order_ref": identity.get("order_ref"),
        "original_front_id": identity.get("front_id"),
        "original_session_id": identity.get("session_id"),
    }
    return bool(
        getattr(resolution, "terminal_state", None) == terminal_state
        and getattr(resolution, "position_flat", None) is True
        and getattr(resolution, "account_scope", None) == account_scope
        and getattr(resolution, "instrument", None) == observation.instrument
        and getattr(reconciliation, "reconciliation_id", None)
        == getattr(resolution, "reconciliation_id", None)
        and getattr(reconciliation, "intent_id", None) == getattr(resolution, "intent_id", None)
        and getattr(reconciliation, "state", None) == "KNOWN"
        and getattr(reconciliation, "outcome_code", None)
        == "complete_orders_query_unknown_no_fill_terminal"
        and getattr(reconciliation, "terminal_state", None) == terminal_state
        and getattr(reconciliation, "terminal_event_id", None)
        == getattr(reconciliation, "query_id", None)
        and getattr(reconciliation, "position_flat", None) is True
        and getattr(reconciliation, "position_snapshot_id", None)
        == provider.get("position_snapshot_id")
        and provider.get("evidence_kind") == "complete_orders_query_unknown_no_fill_terminal"
        and _exact_identifier(provider.get("observation_id"))
        and _exact_identifier(provider.get("query_set_id"))
        and _exact_identifier(provider.get("snapshot_id"))
        and provider.get("observation_id") == reconciliation.query_id
        and provider.get("snapshot_id") == provider.get("position_snapshot_id")
        and all(provider.get(name) == value for name, value in expected_fields.items())
    )


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
