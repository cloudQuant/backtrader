"""Backtrader implementations of the execution journal's typed cross-domain ports.

``bt_api_execution.journal`` owns durable decision and dispatch evidence, and a
few of its code paths need facts that belong to another domain: the
application-owned strategy position projection, the application-owned fee-pair
fact projection and the application-owned registered-sim query receipt.  Those
used to be handed over as whole Python *module objects* through
``configure_backtrader_contracts`` so the SDK could reach this package's private
symbols and perform exact cross-repo class identity checks.  That entry point is
now retired (``JOURNAL_PORT_LEGACY_RETIRED``) and this module supplies the
replacement: three thin, faithful adapters over Backtrader's own functions, each
declaring the versioned abstract port the SDK validates at injection time.

Nothing here changes a trust decision.  Every adapter delegates to the same
Backtrader implementation the journal previously reached through a module
attribute, and the attestation adapter keeps the whole identity check that used
to live inside the journal:

* the receipt must be the genuine ``bt_api_ctp.receipts`` record class;
* the source store must be the genuine ``RegisteredSimStore`` class;
* the receipt must be bound to that very store object (``receipt._store``);
* the store's receipt mint/validate pair must resolve to
  ``RegisteredSimStore``'s own implementations, so no substituted or rebound
  object can pass;
* the receipt's own field shape is revalidated by ``receipt.validate_shape()``
  (owned by the CTP SDK now, not re-implemented here), the source deadline must
  still be live on this host's monotonic clock, and the Store must still return
  ``True`` when it revalidates the receipt against its still-current query.

A rejection raises :class:`JournalPortRejection`, a Backtrader-side error that
*is* an ``ExecutionDecisionJournalError`` so the journal's existing stable codes
(``KNOWN_CTP_ORDER_SYSID_QUERY_UNTRUSTED`` / ``..._STALE``) keep their meaning.

Provider SDKs stay lazily bound: importing this module imports
``bt_api_execution`` (the journal the caller already uses) but never
``bt_api_ctp``; the receipt classes are resolved per call through
:mod:`backtrader.stores.registered_sim`, which loads them lazily.
"""

from __future__ import annotations

import math
import time
from threading import Lock
from typing import Any, Optional, Tuple

from bt_api_execution.journal import (
    ExecutionDecisionJournalError,
    configure_journal_ports,
)
from bt_api_execution.journal_ports import (
    JOURNAL_PORT_SCHEMA_VERSION,
    AttestedCtpOrderIdentityQuery,
    JournalFeePairFactsPort,
    JournalPorts,
    JournalPositionAttributionPort,
    JournalRegisteredSimAttestationPort,
)

__all__ = [
    "BacktraderFeePairFactsJournalPort",
    "BacktraderJournalPortError",
    "BacktraderPositionAttributionJournalPort",
    "BacktraderRegisteredSimAttestationJournalPort",
    "JournalPortRejection",
    "bind_backtrader_journal_ports",
    "build_backtrader_journal_ports",
    "install_backtrader_journal_ports",
    "new_execution_journal",
]


_PORT_SLOT_NAMES = ("position_attribution", "fee_pair_facts", "registered_sim_attestation")


class BacktraderJournalPortError(RuntimeError):
    """This package could not supply a port the journal requires."""


class JournalPortRejection(ExecutionDecisionJournalError):
    """A port rejection carrying the journal's own stable rejection code.

    Subclassing the journal error is deliberate: the journal catches
    ``ExecutionDecisionJournalError`` when it re-attests inside its own durable
    transaction and maps any rejection to ``KNOWN_CTP_ORDER_SYSID_QUERY_STALE``.
    A foreign exception type would escape that mapping and change the durable
    outcome, so the rejection must stay inside the journal's error family while
    being minted on the Backtrader side.
    """


def _position_book_module() -> Any:
    from . import factor_position_book as module

    return module


def _facts_module() -> Any:
    from . import factor_execution_facts as module

    return module


def _registered_sim_module() -> Any:
    from . import registered_sim as module

    return module


class BacktraderPositionAttributionJournalPort(JournalPositionAttributionPort):
    """Strategy position attribution over ``backtrader.stores.factor_position_book``.

    Every method forwards the journal's live cursor unchanged, so attribution
    still commits or rolls back inside the journal's own transaction.  The
    invariants (append-only evidence, idempotent replay, consumed-flat checks and
    the positively-owned close residual) remain owned by that module.
    """

    port_version = JOURNAL_PORT_SCHEMA_VERSION

    @property
    def expected_schema_version(self) -> int:
        """The attribution schema version this package currently writes."""

        module = _position_book_module()
        version = getattr(module, "_POSITION_BOOK_SCHEMA_VERSION", None)
        if type(version) is not int or version <= 0:
            raise BacktraderJournalPortError("POSITION_BOOK_SCHEMA_VERSION_INVALID")
        return version

    def ensure_schema(self, cursor: Any) -> None:
        _position_book_module().ensure_factor_position_book_schema(cursor)

    def record_grid(
        self,
        cursor: Any,
        *,
        account_scope: str,
        strategy_scope: str,
        cohort_id: str,
        batch_id: str,
        close_time: str,
        ordinal: int,
        capacity_class: str = "BASE",
    ) -> bool:
        return bool(
            _position_book_module().record_factor_position_grid(
                cursor,
                account_scope=account_scope,
                strategy_scope=strategy_scope,
                cohort_id=cohort_id,
                batch_id=batch_id,
                close_time=close_time,
                ordinal=ordinal,
                capacity_class=capacity_class,
            )
        )

    def record_flat_checkpoint(
        self, cursor: Any, *, intent_id: str, reconciliation_id: str
    ) -> None:
        _position_book_module().record_factor_position_flat_checkpoint(
            cursor, intent_id=intent_id, reconciliation_id=reconciliation_id
        )

    def validate_close_owner(
        self,
        cursor: Any,
        *,
        account_scope: str,
        strategy_scope: str,
        instrument: str,
        exchange: str,
        owner_intent_id: str,
    ) -> None:
        _position_book_module().validate_factor_position_close_owner(
            cursor,
            account_scope=account_scope,
            strategy_scope=strategy_scope,
            instrument=instrument,
            exchange=exchange,
            owner_intent_id=owner_intent_id,
        )


class BacktraderFeePairFactsJournalPort(JournalFeePairFactsPort):
    """Fee-pair fact projection checks over ``factor_execution_facts``.

    ``is_factor_execution_facts`` uses the same exact-type predicate the journal
    applied inline before this port existed, so a look-alike object or a
    subclass this package does not mint is still rejected.
    """

    port_version = JOURNAL_PORT_SCHEMA_VERSION

    def is_factor_execution_facts(self, facts: Any) -> bool:
        try:
            facts_class = _facts_module().FactorExecutionFacts
        except ImportError as error:  # pragma: no cover - package integrity guard
            raise ExecutionDecisionJournalError("FEE_PAIR_FACTS_UNAVAILABLE") from error
        return type(facts) is facts_class

    def query_set_identifier(
        self,
        account_fingerprint: str,
        generation: int,
        trading_day: str,
        started_at: Any,
        completed_at: Any,
        query_ids: Tuple[Tuple[str, int], ...],
    ) -> str:
        # The public name keeps the SDK off this package's private symbols; the
        # digest algorithm and output are unchanged.
        return _facts_module().fee_pair_query_set_identifier(
            account_fingerprint,
            generation,
            trading_day,
            started_at,
            completed_at,
            query_ids,
        )

    def validate_source_lease(self, lease: Any, facts: Any, *, operation: str) -> bool:
        return bool(
            _facts_module().validate_fee_pair_facts_source_lease(
                lease, facts, operation=operation
            )
        )


class BacktraderRegisteredSimAttestationJournalPort(JournalRegisteredSimAttestationPort):
    """Attest one Store-minted registered-sim order-identity query receipt.

    This is the whole inline revalidation the journal used to perform, moved to
    the side that owns the classes.  It performs no database work and mutates
    nothing; it returns the neutral projection the journal persists.
    """

    port_version = JOURNAL_PORT_SCHEMA_VERSION

    def _classes(self) -> Tuple[Any, Any]:
        module = _registered_sim_module()
        try:
            receipt_class = module.RegisteredSimOrderIdentityQueryReceipt
            store_class = module.RegisteredSimStore
        except (ImportError, AttributeError) as error:
            # Without the genuine receipt record and Store there is nothing this
            # implementation could ever recognise as its own.
            raise JournalPortRejection("KNOWN_CTP_ORDER_SYSID_QUERY_UNTRUSTED") from error
        if receipt_class is None or store_class is None:
            raise JournalPortRejection("KNOWN_CTP_ORDER_SYSID_QUERY_UNTRUSTED")
        return receipt_class, store_class

    def attest_order_identity_query(
        self, receipt: Any, *, source_store: Any
    ) -> AttestedCtpOrderIdentityQuery:
        receipt_class, store_class = self._classes()

        # --- trust: the minting classes, the bound store and the Store methods.
        if type(receipt) is not receipt_class:
            raise JournalPortRejection("KNOWN_CTP_ORDER_SYSID_QUERY_UNTRUSTED")
        store = source_store
        if type(store) is not store_class or receipt._store is not store:
            raise JournalPortRejection("KNOWN_CTP_ORDER_SYSID_QUERY_UNTRUSTED")
        mint = getattr(store_class, "registered_sim_order_identity_query_receipt", None)
        validate = getattr(
            store_class, "registered_sim_validate_order_identity_query_receipt", None
        )
        if mint is None or validate is None:
            raise JournalPortRejection("KNOWN_CTP_ORDER_SYSID_QUERY_UNTRUSTED")
        store_mint = getattr(store, "registered_sim_order_identity_query_receipt", None)
        store_validate = getattr(
            store, "registered_sim_validate_order_identity_query_receipt", None
        )
        if (
            getattr(store_mint, "__func__", None) is not mint
            or getattr(store_validate, "__func__", None) is not validate
        ):
            raise JournalPortRejection("KNOWN_CTP_ORDER_SYSID_QUERY_UNTRUSTED")

        # --- currency: field shape (owned by the receipt now), live deadline and
        # the Store's own revalidation against its still-current query.
        try:
            receipt.validate_shape()
        except ValueError as error:
            raise JournalPortRejection("KNOWN_CTP_ORDER_SYSID_QUERY_STALE") from error
        except AttributeError as error:  # pragma: no cover - package integrity guard
            # A record without its own shape check cannot be trusted to be the
            # current SDK contract; fail closed instead of re-implementing it.
            raise JournalPortRejection("KNOWN_CTP_ORDER_SYSID_QUERY_UNTRUSTED") from error
        expiry = receipt.source_expires_monotonic
        if (
            type(expiry) not in (int, float)
            or not math.isfinite(expiry)
            or time.monotonic() >= expiry
        ):
            raise JournalPortRejection("KNOWN_CTP_ORDER_SYSID_QUERY_STALE")
        if validate(store, receipt) is not True:
            raise JournalPortRejection("KNOWN_CTP_ORDER_SYSID_QUERY_STALE")

        source_lock = getattr(store, "_ctp_query_result_lock", None)
        if source_lock is None:
            # The journal holds this lock across its COMMIT so the validated
            # query cannot be replaced mid-transaction; without it there is no
            # source lock to hand over.
            raise JournalPortRejection("KNOWN_CTP_ORDER_SYSID_QUERY_UNTRUSTED")

        return AttestedCtpOrderIdentityQuery(
            request_id=receipt.request_id,
            connection_generation=receipt.connection_generation,
            account_fingerprint=receipt.account_fingerprint,
            trading_day=receipt.trading_day,
            started_at_utc=receipt.started_at_utc,
            completed_at_utc=receipt.completed_at_utc,
            front_id=receipt.front_id,
            session_id=receipt.session_id,
            broker_id=receipt.broker_id,
            investor_id=receipt.investor_id,
            rows=tuple(receipt.rows),
            rows_sha256=receipt.rows_sha256,
            source_expires_monotonic=float(expiry),
            source_lock=source_lock,
        )


_PORTS: Optional[JournalPorts] = None
_PORTS_LOCK = Lock()


def build_backtrader_journal_ports() -> JournalPorts:
    """Return this package's port set, validated once and reused.

    The same instances are returned for the lifetime of the process so a
    repeated registration is a no-op for the SDK instead of a silent swap.
    """

    global _PORTS
    ports = _PORTS
    if ports is not None:
        return ports

    # The cache is process-wide because the SDK refuses to replace a different
    # instance after registration.  Serialize the first construction so two
    # importing threads cannot create competing, equally valid port sets.
    with _PORTS_LOCK:
        ports = _PORTS
        if ports is None:
            ports = JournalPorts(
                position_attribution=BacktraderPositionAttributionJournalPort(),
                fee_pair_facts=BacktraderFeePairFactsJournalPort(),
                registered_sim_attestation=BacktraderRegisteredSimAttestationJournalPort(),
            )
            _PORTS = ports
        return ports


def install_backtrader_journal_ports() -> JournalPorts:
    """Register this package's ports as the process-wide set. Idempotent.

    Used where a journal is constructed by code this package does not own (a
    test fixture or an operator entry point) and must therefore see the ports at
    construction time.  A foreign port already occupying a slot is never
    replaced here: the SDK's ``JOURNAL_PORT_ALREADY_CONFIGURED`` rejection is
    re-raised instead of silently swapping semantics.
    """

    ports = build_backtrader_journal_ports()
    try:
        configure_journal_ports(
            position_attribution=ports.position_attribution,
            fee_pair_facts=ports.fee_pair_facts,
            registered_sim_attestation=ports.registered_sim_attestation,
        )
    except ExecutionDecisionJournalError as error:
        code = getattr(error, "code", "")
        if code.startswith("JOURNAL_PORT_ALREADY_CONFIGURED"):
            raise
        raise BacktraderJournalPortError("JOURNAL_PORT_REGISTRATION_FAILED") from error
    return ports


def bind_backtrader_journal_ports(journal: Any) -> JournalPorts:
    """Require one journal to carry this package's port set; never swap it.

    Constructor injection is the preferred path: build the journal with
    :func:`new_execution_journal` (or pass ``journal_ports=`` yourself), because
    the journal creates this package's attribution tables while its own schema
    is opened.  A journal opened after :func:`install_backtrader_journal_ports`
    already captured the identical port instances.

    This therefore only registers the set process-wide (so any journal built
    later in the process sees it) and verifies the journal in front of us:
    a missing ``_ports`` slot is an SDK version mismatch, and a slot holding
    another application's ports or an intentionally empty set is refused.  Both
    fail closed -- nothing is rebound behind the journal's own construction.
    """

    ports = install_backtrader_journal_ports()
    current = getattr(journal, "_ports", None)
    if current is None:
        raise BacktraderJournalPortError("EXECUTION_JOURNAL_PORT_SLOT_MISSING")
    if type(current) is not JournalPorts:
        raise BacktraderJournalPortError("EXECUTION_JOURNAL_PORT_SET_INVALID")
    for name in _PORT_SLOT_NAMES:
        supplied = getattr(current, name)
        if supplied is None:
            raise BacktraderJournalPortError("EXECUTION_JOURNAL_PORT_UNBOUND:" + name)
        if supplied is not getattr(ports, name):
            raise BacktraderJournalPortError("EXECUTION_JOURNAL_PORT_SET_FOREIGN:" + name)
    return current


def new_execution_journal(database_path: Any, **options: Any) -> Any:
    """Construct one execution journal with Backtrader's ports injected.

    The journal creates the application-owned attribution tables while its
    schema is opened, so the ports must be present at construction time; this is
    the Backtrader-side construction entry that guarantees it.  The journal
    limits and options are forwarded unchanged.
    """

    from bt_api_execution.journal import ExecutionDecisionJournal

    if "journal_ports" in options:
        raise BacktraderJournalPortError("EXECUTION_JOURNAL_PORTS_ALREADY_SUPPLIED")
    return ExecutionDecisionJournal(
        database_path, journal_ports=build_backtrader_journal_ports(), **options
    )
