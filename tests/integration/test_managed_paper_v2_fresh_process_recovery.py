"""Managed-paper V2 fresh-process recovery: crash after durable checkpoint.

One real ServiceHost (execution owner + paper matching + account-books reads),
CURVE-authenticated clients, the SDK execution component, a durable SQLite
client journal, the Backtrader Broker and the Session.run(Cerebro) path are
real local components. The provider observation, admission decision, paper
quote leaf and account-owner snapshots are explicit synthetic leaves.

Design facts (design-locked):
* The strategy process is killed with os._exit(97) inside the user
  notify_trade callback after the durable trade checkpoint is written and
  before the journal acknowledgement row is updated.
* A fresh process restarts the SAME logical run on the SAME journal and the
  SAME host, releases the stale consumer lease with the token reported by the
  first process, waits for the host registry to expire the dead registration,
  and must reach the READY replay path: no second dispatch, no duplicate
  Trade, hydrated Trade equal to the checkpoint, and the pending ACK replayed.

This test is not provider, account, or formal-case evidence.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import multiprocessing
import os
import shutil
import socket
import sqlite3
import time
from contextlib import suppress
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("bt_api_py")
if importlib.util.find_spec("bt_api_execution") is None:
    pytest.skip("bt_api_execution package is not installed", allow_module_level=True)
zmq = pytest.importorskip("zmq")
pandas = pytest.importorskip("pandas")

import backtrader as bt  # noqa: E402
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope  # noqa: E402
from bt_api_py.service_config import parse_client_config, parse_service_config  # noqa: E402
from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority  # noqa: E402
from bt_api_py.service_registry import PrincipalGrant, ResourceGrant  # noqa: E402
from bt_api_py.service_runtime import (  # noqa: E402
    ClientCurveKeys,
    ServiceClientRuntime,
    ZmqTransportFactory,
)

from backtrader.feeds.service_recovery_quotes import (  # noqa: E402
    ServiceRecoveryQuoteBindingMixin,
)
from backtrader.stores.service_execution_session import (  # noqa: E402
    ServiceExecutionSession,
)
from tests.fixtures.fake_btapi import FakeBtApiClient, make_store  # noqa: E402

_DOMAIN = "paper:managed-paper-v2-fresh-process-recovery"
_SERVICE_ID = "managed-paper-v2-recovery-service"
_SERVICE_PRINCIPAL = "managed-paper-v2-recovery-service-principal"
_SERVICE_INSTANCE = "managed-paper-v2-recovery-owner"
_STRATEGY = "strategy.managed-paper.v2-recovery"
_PRINCIPAL = "managed-paper-v2-recovery-principal"
_ACCOUNT = "account.managed-paper.v2-recovery"
_SERVICE_SCOPE_REF = "managed-paper-v2-recovery-root-v1"
_ORDER_SCOPE_REF = "managed-paper-v2-recovery-orders-v1"
_QUERY_SCOPE_REF = "managed-paper-v2-recovery-query-v1"
_SERVER_SECURITY_REF = "managed-paper-v2-recovery-server-curve-v1"
_CLIENT_SECURITY_REF = "managed-paper-v2-recovery-client-curve-v1"
_LISTENER_REF = "managed-paper-v2-recovery-listener-v1"
_TRANSPORT_REF = "managed-paper-v2-recovery-connect-v1"
_REQUEST_TIMEOUT_MS = 2_000
_MAX_MESSAGE_BYTES = 65_536
_TRADING_DAY = "20261016"

_INSTRUMENT = "BTC-USDT"
_METADATA_VERSION = "paper-instrument-v1"
_INTENT_ID = "managed-paper-v2-recovery-intent-r1"
_SIGNAL_ID = "managed-paper-v2-recovery-signal-r1"
_RUN_ID = "managed-paper-v2-recovery-run-r1"
_FILL_QUANTITY = Decimal("1.25")
_FILL_PRICE = Decimal("10.02")
_FILL_FEE = Decimal("0.0125")
_INITIAL_CASH = Decimal("100")
_BOOK_CASH_AFTER_FILL = Decimal("87.4625")
_POSITION_COST_BASIS_AFTER_FILL = Decimal("12.525")

_QUOTE_SOURCE_REF = "paper-host-synthetic-quotes-v1"
_QUOTE_GENERATION = "paper-host-quote-generation-v1"
_QUOTE_CURSOR = 1
# Fixed past instant: the host match time is a live wall-clock reading, so the
# recovery binding must be strictly older for run1 and the run2 replay.
_QUOTE_AS_OF_NS = 1_700_000_000_000_000_000
_DIRECTORY_REVISION = "managed-paper-v2-recovery-directory-r1"

_SCOPE = WireScope(_DOMAIN, account_ref=_ACCOUNT, strategy_ref=_STRATEGY)

_CRASH_EXITCODE = 97
_HOST_READY_TIMEOUT = 60.0
_CRASH_WAIT_TIMEOUT = 180.0
_RUN2_WAIT_TIMEOUT = 240.0
_REGISTRY_WAIT_TIMEOUT = 150.0
_RUN2_ATTEMPTS = 3


def _endpoint() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return f"tcp://127.0.0.1:{probe.getsockname()[1]}"


def _curve_keys() -> dict:
    server_public, server_secret = zmq.curve_keypair()
    client_public, client_secret = zmq.curve_keypair()
    return {
        "server_public": server_public,
        "server_secret": server_secret,
        "client_public": client_public,
        "client_secret": client_secret,
    }


def _service_config(endpoint: str) -> dict:
    return {
        "service_config_schema_version": 1,
        "process_role": "service",
        "service_id": _SERVICE_ID,
        "scope_ref": _SERVICE_SCOPE_REF,
        "transport_ref": _LISTENER_REF,
        "registration_policy_ref": "managed-paper-v2-recovery-registration-v1",
        "service_requirements_ref": "managed-paper-v2-recovery-requirements-v1",
        "components": {
            "execution": {
                "config_schema_version": 2,
                "settings": {
                    "instance_id": _SERVICE_INSTANCE,
                    "bind_ports": ["service.order_entry", "service.order_query"],
                    "options": {"role": "account_owner"},
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                _LISTENER_REF: {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_bind": endpoint},
                    "security_profile_ref": _SERVER_SECURITY_REF,
                    "options": {
                        "high_water_mark": 32,
                        "max_message_bytes": _MAX_MESSAGE_BYTES,
                    },
                }
            },
        },
    }


def _client_config(endpoint: str) -> dict:
    return {
        "client_config_schema_version": 1,
        "process_role": "strategy_client",
        "registration": {"strategy_ref": _STRATEGY},
        "clients": {
            "execution": {
                "config_schema_version": 1,
                "settings": {
                    "bindings": [
                        {
                            "mount": "broker.orders",
                            "service_id": _SERVICE_ID,
                            "instance_id": _SERVICE_INSTANCE,
                            "scope_ref": _ORDER_SCOPE_REF,
                            "transport_ref": _TRANSPORT_REF,
                            "account_ref": _ACCOUNT,
                        },
                        {
                            "mount": "broker.order_query",
                            "service_id": _SERVICE_ID,
                            "instance_id": _SERVICE_INSTANCE,
                            "scope_ref": _QUERY_SCOPE_REF,
                            "transport_ref": _TRANSPORT_REF,
                            "account_ref": _ACCOUNT,
                        },
                    ],
                    "options": {"request_timeout_ms": _REQUEST_TIMEOUT_MS},
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                _TRANSPORT_REF: {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_connect": endpoint},
                    "security_profile_ref": _CLIENT_SECURITY_REF,
                    "options": {
                        "request_timeout_ms": _REQUEST_TIMEOUT_MS,
                        "high_water_mark": 32,
                        "max_message_bytes": _MAX_MESSAGE_BYTES,
                    },
                }
            },
        },
    }


def _authority(config, keys):
    service_identity = WireIdentity(WireRole.SERVICE, _SERVICE_PRINCIPAL, _SERVICE_ID)
    write_grant = ResourceGrant(
        _SERVICE_INSTANCE,
        "service.order_entry",
        _ORDER_SCOPE_REF,
        _SCOPE,
        frozenset({"orders.submit", "orders.cancel"}),
    )
    read_grant = ResourceGrant(
        _SERVICE_INSTANCE,
        "service.order_query",
        _QUERY_SCOPE_REF,
        _SCOPE,
        frozenset({"orders.query", "execution.account_books.query"}),
    )
    return TrustedServiceAuthority(
        identity=service_identity,
        scope=WireScope(_DOMAIN),
        scope_ref=config.scope_ref,
        scope_version="managed-paper-v2-recovery-service-scope-v1",
        security_ref=_SERVER_SECURITY_REF,
        security_version="curve-key-v1",
        registration_policy_ref=config.registration_policy_ref,
        registration_policy_version="managed-paper-v2-recovery-policy-v1",
        service_requirements_ref=config.service_requirements_ref,
        service_requirements_version="managed-paper-v2-recovery-requirements-v1",
        curve_public_key=keys["server_public"],
        curve_secret_key=keys["server_secret"],
        principals={keys["client_public"]: _PRINCIPAL},
        grants={
            _PRINCIPAL: (
                PrincipalGrant(
                    WireIdentity(WireRole.STRATEGY_CLIENT, _PRINCIPAL, _STRATEGY),
                    (write_grant, read_grant),
                ),
            )
        },
    )


def _paper_domain():
    from bt_api_execution import PAPER_MODEL_REF, PaperInstrumentV1, PaperOwnerDomainV1

    return PaperOwnerDomainV1(
        execution_domain_ref=_DOMAIN,
        simulation_account_ref=_ACCOUNT,
        experiment_ref="paper-host-experiment-v1",
        strategy_ref=_STRATEGY,
        model_ref=PAPER_MODEL_REF,
        model_version="1",
        quote_source_ref=_QUOTE_SOURCE_REF,
        cash_currency="USDT",
        initial_cash=_INITIAL_CASH,
        initial_fees=Decimal("0"),
        fee_rate=Decimal("0.001"),
        fee_quantum=Decimal("0.0001"),
        max_quote_age_ns=30_000_000_000,
        instruments=(
            PaperInstrumentV1(
                _INSTRUMENT,
                _METADATA_VERSION,
                "BTC",
                "USDT",
                Decimal("0.25"),
                Decimal("0.01"),
            ),
        ),
        opening_positions=(),
    )


class _SyntheticQuoteSource:
    """Server-owned deterministic quote leaf; never reads a live provider."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def read_quote(self, instrument: str):
        from bt_api_execution import PaperQuoteV1

        self.calls.append(instrument)
        if instrument != _INSTRUMENT:
            return None
        return PaperQuoteV1(
            source_ref=_QUOTE_SOURCE_REF,
            generation=_QUOTE_GENERATION,
            cursor=_QUOTE_CURSOR,
            instrument=instrument,
            metadata_version=_METADATA_VERSION,
            quote_currency="USDT",
            bid=Decimal("10.00"),
            ask=_FILL_PRICE,
            bid_quantity=Decimal("5"),
            ask_quantity=Decimal("5"),
            as_of_ns=time.time_ns(),
        )


def _paper_components(store, *, execution_scope, close_calls):
    from bt_api_execution import (
        PAPER_PROVIDER,
        ExecutionAdmissionValidatorRegistry,
        ExecutionBasicAdmissionGate,
        ExecutionProviderValidatorV1,
        OrderType,
        PaperMatchingPort,
        PositionEffect,
        Side,
        TimeInForce,
    )

    domain = _paper_domain()
    quote_source = _SyntheticQuoteSource()
    dispatch = PaperMatchingPort(domain, quote_source)
    validator = ExecutionProviderValidatorV1(
        provider_id=PAPER_PROVIDER,
        validator_id="managed-paper-v2-recovery-market-policy-v1",
        version="1",
        dispatch_port=dispatch,
        instrument_map={_INSTRUMENT: _INSTRUMENT},
        quantity_steps={_INSTRUMENT: Decimal("0.25")},
        max_quantities={_INSTRUMENT: Decimal("10")},
        price_ticks={_INSTRUMENT: Decimal("0.01")},
        supported_order_types=(OrderType.MARKET,),
        supported_time_in_force=(TimeInForce.FOK,),
        supported_actions=((Side.BUY, PositionEffect.OPEN),),
        supports_reduce_only=False,
    )
    admission = ExecutionBasicAdmissionGate(
        store,
        ExecutionAdmissionValidatorRegistry((validator,)),
        permit_ttl_ns=60_000_000_000,
    )

    def close_resources() -> None:
        store.close()
        close_calls[0] += 1

    return {
        "domain": domain,
        "quote_source": quote_source,
        "dispatch": dispatch,
        "admission": admission,
        "close": close_resources,
    }


class _ManagedAccountBooksSource:
    """Trusted owner resource: legacy snapshots plus recovery-directory reads."""

    def __init__(self, store, targets, execution_scope) -> None:
        from bt_api_execution import (
            AllocationOwnerKind,
            ExecutionOwnerScope,
            ExecutionScopeDirectory,
        )

        self._store = store
        self._targets = dict(targets)
        self._execution_scope = execution_scope
        self._as_of_ns = time.time_ns()
        self.read_count = 0
        self.financial_reads = 0
        self._financial_directory = None
        rows = []
        for wire_scope, scope in self._targets.items():
            kind = (
                AllocationOwnerKind.STRATEGY
                if wire_scope.strategy_ref is not None
                else AllocationOwnerKind.MANUAL_BOOK
            )
            owner_ref = (
                scope.strategy_id
                if wire_scope.strategy_ref is not None
                else wire_scope.manual_book_ref
            )
            rows.append(
                ExecutionOwnerScope(scope, kind, owner_ref, wire_scope)
            )
        # Equality-stable: the recovery adapter reads this directory before and
        # after one snapshot operation and rejects a changed revision/content.
        self._recovery_directory = ExecutionScopeDirectory(
            account_key=execution_scope.account_key,
            source="trusted-managed-paper-owner-registry",
            source_ref="managed-paper-v2-recovery-owner-directory-source",
            revision=_DIRECTORY_REVISION,
            covers_from_ns=self._as_of_ns,
            as_of_ns=self._as_of_ns,
            scopes=tuple(rows),
        )

    def set_financial_directory(self, directory) -> None:
        self._financial_directory = directory

    def authorize_account_view(self, *, principal_ref, identity, scope, account_key) -> bool:
        return False

    def read_financial_owner_directory(self, *, account_key):
        if self._financial_directory is None:
            raise RuntimeError("financial directory not installed")
        if account_key != self._execution_scope.account_key:
            raise AssertionError("financial directory requested for another account")
        return self._financial_directory

    def read_scope_directory(self, *, account_key):
        if account_key != self._execution_scope.account_key:
            raise AssertionError("scope directory requested for another account")
        return self._recovery_directory

    def _paper_book(self):
        return self._store.read_paper_book(self._execution_scope)

    def read_inputs(self, *, account_key, journal_generation, execution_cursor):
        from bt_api_execution import (
            AllocationOwnerKind,
            CurrencyAmount,
            ExecutionAccountSnapshot,
            ExecutionAllocationBaseline,
            ExecutionOwnerScope,
            ExecutionScopeDirectory,
            ExternalActivitySnapshot,
            OwnerPosition,
            PositionFact,
        )

        from bt_api_py.service_execution_account_books import ExecutionAccountBookReadInputsV1

        if account_key != self._execution_scope.account_key:
            raise AssertionError("account-book source received another account")
        self.read_count += 1
        as_of_ns = max(time.time_ns(), self._as_of_ns + 3)
        directory = ExecutionScopeDirectory(
            account_key=account_key,
            source="trusted-managed-paper-owner-registry",
            source_ref="managed-paper-v2-recovery-owner-directory-source",
            revision=_DIRECTORY_REVISION,
            covers_from_ns=self._as_of_ns,
            as_of_ns=as_of_ns,
            scopes=tuple(
                ExecutionOwnerScope(
                    scope,
                    (
                        AllocationOwnerKind.STRATEGY
                        if wire_scope.strategy_ref is not None
                        else AllocationOwnerKind.MANUAL_BOOK
                    ),
                    (
                        scope.strategy_id
                        if wire_scope.strategy_ref is not None
                        else wire_scope.manual_book_ref
                    ),
                    wire_scope,
                )
                for wire_scope, scope in self._targets.items()
            ),
        )
        provider_generation = "managed-paper-account-generation-v1"
        baseline_snapshot = ExecutionAccountSnapshot(
            account_key=account_key,
            source="managed-paper-synthetic-account-snapshots",
            source_ref="managed-paper-baseline-snapshot-r1",
            generation=provider_generation,
            journal_generation=journal_generation,
            as_of_ns=self._as_of_ns,
            execution_cursor=0,
            position_mode="NET",
            positions=(PositionFact(_INSTRUMENT, Decimal("0")),),
            cumulative_fees=(CurrencyAmount("USDT", Decimal("0")),),
            fee_coverage_start_ns=self._as_of_ns,
        )
        allocation_baseline = ExecutionAllocationBaseline(
            account_key=account_key,
            source="trusted-managed-paper-virtual-position-ledger",
            source_ref="managed-paper-virtual-baseline-r1",
            revision="managed-paper-virtual-baseline-revision-1",
            scope_directory_revision=_DIRECTORY_REVISION,
            provider_generation=provider_generation,
            journal_generation=journal_generation,
            as_of_ns=self._as_of_ns,
            execution_cursor=0,
            positions=(
                OwnerPosition(
                    AllocationOwnerKind.STRATEGY,
                    _STRATEGY,
                    _INSTRUMENT,
                    Decimal("0"),
                ),
            ),
        )
        external_activity = ExternalActivitySnapshot(
            account_key=account_key,
            source="managed-paper-synthetic-account-activity",
            source_ref="managed-paper-activity-window-r1",
            generation=provider_generation,
            coverage_start_ns=self._as_of_ns,
            coverage_end_ns=as_of_ns,
            fills=(),
            orders=(),
        )
        book = self._paper_book()
        current_quantity = next(
            (
                row.quantity
                for row in book.positions
                if row.instrument == _INSTRUMENT
            ),
            Decimal("0"),
        )
        current_snapshot = ExecutionAccountSnapshot(
            account_key=account_key,
            source=baseline_snapshot.source,
            source_ref="managed-paper-current-snapshot-r1",
            generation=provider_generation,
            journal_generation=journal_generation,
            as_of_ns=as_of_ns,
            execution_cursor=execution_cursor,
            position_mode="NET",
            positions=(PositionFact(_INSTRUMENT, current_quantity),),
            cumulative_fees=(CurrencyAmount("USDT", book.cumulative_fees),),
            fee_coverage_start_ns=self._as_of_ns,
        )
        return ExecutionAccountBookReadInputsV1(
            directory,
            baseline_snapshot,
            current_snapshot,
            allocation_baseline,
            external_activity,
        )


def _seed_financial_projection(
    store,
    execution_scope,
    *,
    revision_suffix,
    cash,
    position_quantity,
    position_cost_basis,
    fees,
    baseline_version=1,
    watermark_suffix="r1",
    facts_cursor_start=1,
):
    """Install one persisted owner financial cut through Execution's ledger.

    ``baseline_version`` must advance on every republish (the ledger binds a
    (account_key, version) row immutably and rejects rebinding the same
    version to different facts).  ``watermark_suffix`` names the provider
    account-facts/activity generations: republished cuts must keep the
    generation installed with the first baseline and only advance cursors.
    """

    from bt_api_execution import (
        AccountFinancialBaselineV1,
        FinancialActivityBatchV1,
        FinancialInstrumentSpecV1,
        FinancialLedgerCutV1,
        FinancialLedgerPolicyV1,
        FinancialOwnerBaselineV1,
        FinancialOwnerDirectoryV1,
        FinancialOwnerKind,
        FinancialOwnerV1,
        FinancialSourceKind,
        FinancialWatermarkV1,
        OwnerPositionCostV1,
        ProviderAccountFinancialSnapshotV1,
    )
    from bt_api_execution.account_financial_ledger import CurrencyAmountV1

    account_key = execution_scope.account_key
    owner = FinancialOwnerV1(FinancialOwnerKind.STRATEGY, _STRATEGY, execution_scope.key)
    directory = FinancialOwnerDirectoryV1(
        account_key,
        f"managed-paper-financial-directory-{revision_suffix}",
        "managed-paper-financial-owner-source-r1",
        (owner,),
    )
    lease = store.acquire_or_renew_lease(
        execution_scope, f"managed-paper-financial-seed-{revision_suffix}", ttl_ns=30_000_000_000
    )
    try:
        cursor_snapshot = store.capture_account_financial_execution_cursors(
            execution_scope, lease
        )
        captured_at_ns = max(time.time_ns(), cursor_snapshot.as_of_ns)
        execution_baseline = FinancialWatermarkV1(
            FinancialSourceKind.EXECUTION_OUTBOX,
            "sqlite-execution-outbox",
            cursor_snapshot.journal_generation,
            cursor_snapshot.cursor,
            cursor_snapshot.as_of_ns,
        )
        facts_baseline = FinancialWatermarkV1(
            FinancialSourceKind.ACCOUNT_FACTS,
            "managed-paper-provider-account-facts",
            f"managed-paper-facts-generation-{watermark_suffix}",
            facts_cursor_start,
            captured_at_ns,
        )
        activity_baseline = FinancialWatermarkV1(
            FinancialSourceKind.ACCOUNT_ACTIVITY,
            "managed-paper-provider-account-activity",
            f"managed-paper-activity-generation-{watermark_suffix}",
            0,
            captured_at_ns,
        )
        baseline_cut = FinancialLedgerCutV1(
            account_key,
            directory.revision,
            captured_at_ns,
            (execution_baseline, facts_baseline, activity_baseline),
        )
        snapshot_positions = (
            ()
            if position_quantity == 0
            else ((_INSTRUMENT, position_quantity),)
        )
        baseline_account = ProviderAccountFinancialSnapshotV1(
            account_key,
            facts_baseline.source_ref,
            facts_baseline.generation,
            facts_baseline.cursor,
            captured_at_ns,
            (CurrencyAmountV1("USDT", cash),),
            snapshot_positions,
            (CurrencyAmountV1("USDT", fees),),
        )
        owner_costs = (
            ()
            if position_quantity == 0
            else (
                OwnerPositionCostV1(
                    _INSTRUMENT,
                    position_quantity,
                    position_cost_basis,
                    "USDT",
                    metadata_version=f"managed-paper-spot-{revision_suffix}",
                ),
            )
        )
        baseline = AccountFinancialBaselineV1(
            account_key,
            f"managed-paper-financial-baseline-{revision_suffix}",
            baseline_version,
            f"managed-paper-baseline-authority-{revision_suffix}",
            f"managed-paper-baseline-source-{revision_suffix}",
            directory.revision,
            baseline_cut,
            baseline_account,
            (
                FinancialOwnerBaselineV1(
                    owner,
                    (CurrencyAmountV1("USDT", cash),),
                    owner_costs,
                    (CurrencyAmountV1("USDT", fees),),
                ),
            ),
            execution_cursors=cursor_snapshot,
        )
        store.install_account_financial_baseline(
            baseline,
            directory,
            writer_scope=execution_scope,
            writer_lease=lease,
        )

        now_ns = time.time_ns()
        execution_current = FinancialWatermarkV1(
            FinancialSourceKind.EXECUTION_OUTBOX,
            "sqlite-execution-outbox",
            cursor_snapshot.journal_generation,
            cursor_snapshot.cursor,
            now_ns,
        )
        facts_current = FinancialWatermarkV1(
            FinancialSourceKind.ACCOUNT_FACTS,
            facts_baseline.source_ref,
            facts_baseline.generation,
            facts_cursor_start + 1,
            now_ns,
        )
        activity_current = FinancialWatermarkV1(
            FinancialSourceKind.ACCOUNT_ACTIVITY,
            activity_baseline.source_ref,
            activity_baseline.generation,
            0,
            now_ns,
        )
        current_cut = FinancialLedgerCutV1(
            account_key,
            directory.revision,
            now_ns,
            (execution_current, facts_current, activity_current),
        )
        current_account = ProviderAccountFinancialSnapshotV1(
            account_key,
            facts_current.source_ref,
            facts_current.generation,
            facts_current.cursor,
            now_ns,
            (CurrencyAmountV1("USDT", cash),),
            snapshot_positions,
            (CurrencyAmountV1("USDT", fees),),
        )
        activity = FinancialActivityBatchV1(
            activity_current.source_ref,
            activity_current.generation,
            0,
            0,
            now_ns,
            (),
        )
        store.reconcile_account_financials(
            baseline,
            directory,
            current_account=current_account,
            current_cut=current_cut,
            activity_batch=activity,
            instrument_specs={
                _INSTRUMENT: FinancialInstrumentSpecV1(
                    _INSTRUMENT,
                    f"managed-paper-spot-{revision_suffix}",
                    "SPOT",
                    "BTC",
                    "USDT",
                )
            },
            policy=FinancialLedgerPolicyV1(
                "USDT",
                10**19,
                10**19,
                10**19,
                "USDT",
                10**19,
                10**19,
            ),
            writer_scope=execution_scope,
            writer_lease=lease,
            now_ns=now_ns,
        )
    finally:
        store.release_lease(
            execution_scope,
            lease.owner_id,
            fencing_token=lease.fencing_token,
        )
    return directory


def _host_process(control, raw_config, registry_path: str, store_path: str, keys) -> None:
    from bt_api_execution import ExecutionScope, SqliteExecutionStore
    from bt_api_py.service_components import ComponentResources

    config = parse_service_config(raw_config)
    store = SqliteExecutionStore(store_path)
    execution_scope = ExecutionScope(
        "paper", "paper", _ACCOUNT, _STRATEGY, "managed-paper-v2-recovery-day-v1"
    )
    targets = {_SCOPE: execution_scope}
    source = _ManagedAccountBooksSource(store, targets, execution_scope)
    close_calls = [0]
    quote_sources: list[_SyntheticQuoteSource] = []
    state: dict = {"seed_ok": False, "seed_note": None, "recut_ok": None, "recut_note": None}
    host = None

    def _seed(
        suffix,
        cash,
        quantity,
        cost_basis,
        fees,
        *,
        baseline_version=1,
        watermark_suffix="r1",
        facts_cursor_start=1,
    ):
        directory = _seed_financial_projection(
            store,
            execution_scope,
            revision_suffix=suffix,
            cash=cash,
            position_quantity=quantity,
            position_cost_basis=cost_basis,
            fees=fees,
            baseline_version=baseline_version,
            watermark_suffix=watermark_suffix,
            facts_cursor_start=facts_cursor_start,
        )
        source.set_financial_directory(directory)

    try:
        try:
            _seed("r1", _INITIAL_CASH, Decimal("0"), Decimal("0"), Decimal("0"))
            state["seed_ok"] = True
        except BaseException as error:
            state["seed_note"] = f"{type(error).__name__}:{error}"[:400]

        def resource_provider(component, instance_id, _options, _scope):
            if component != "execution" or instance_id != _SERVICE_INSTANCE:
                raise AssertionError("unexpected managed-paper recovery resource request")
            parts = _paper_components(
                store,
                execution_scope=execution_scope,
                close_calls=close_calls,
            )
            quote_sources.append(parts["quote_source"])
            return ComponentResources.owned(
                {
                    "store": store,
                    "targets": targets,
                    "dispatch": parts["dispatch"],
                    "admission": {"basic_admission_gate": parts["admission"]},
                    "paper_owner_domain": parts["domain"],
                    "account_books": source,
                },
                ready=lambda: True,
                close=parts["close"],
            )

        def metrics() -> dict:
            record = store.get(_INTENT_ID, scope=execution_scope)
            receipt = store.get_paper_match_receipt(_INTENT_ID, scope=execution_scope)
            book = store.read_paper_book(execution_scope)
            events = store.read_outbox(scope=execution_scope, after_sequence=0, limit=100)
            provider_events = tuple(
                event for event in events if event.event_type == "provider_observation"
            )
            return {
                "record_state": None if record is None else record.state.value,
                "dispatch_attempts": None if record is None else record.dispatch_attempts,
                "filled_quantity": (
                    None if record is None else str(record.filled_quantity)
                ),
                "average_price": (
                    None
                    if record is None or record.average_price is None
                    else str(record.average_price)
                ),
                "cumulative_commission": (
                    None
                    if record is None or record.cumulative_commission is None
                    else str(record.cumulative_commission)
                ),
                "receipt_state": None if receipt is None else receipt.state.value,
                "receipt_domain": None if receipt is None else receipt.execution_domain_ref,
                "receipt_experiment": None if receipt is None else receipt.experiment_ref,
                "receipt_quote": (
                    None
                    if receipt is None
                    else (
                        receipt.quote.source_ref,
                        receipt.quote.generation,
                        receipt.quote.cursor,
                    )
                ),
                "receipt_price": None if receipt is None else str(receipt.fill_price),
                "receipt_fee": None if receipt is None else str(receipt.fee_amount),
                "receipt_cash_delta": (
                    None if receipt is None else str(receipt.cash_delta)
                ),
                "receipt_position_delta": (
                    None if receipt is None else str(receipt.position_delta)
                ),
                "book_cash": str(book.cash),
                "book_currency": book.cash_currency,
                "book_fees": str(book.cumulative_fees),
                "book_positions": tuple(
                    (row.instrument, str(row.quantity), str(row.average_cost))
                    for row in book.positions
                ),
                "book_receipts": book.receipt_count,
                "book_cursor": book.execution_cursor,
                "book_generation": book.execution_journal_generation,
                "quote_calls": tuple(
                    quote_sources[0].calls if quote_sources else ()
                ),
                "provider_event_count": len(provider_events),
                "read_count": source.read_count,
                "seed_ok": state["seed_ok"],
                "seed_note": state["seed_note"],
                "recut_ok": state["recut_ok"],
                "recut_note": state["recut_note"],
            }

        host = ServiceHost(
            config,
            _authority(config, keys),
            registry_path,
            resource_provider,
        )
        host.start()
        control.send(("ready", host.endpoint, host.state, state["seed_ok"], state["seed_note"]))
        while True:
            if control.poll():
                command = control.recv()
                if command == ("metrics",):
                    control.send(("metrics", metrics()))
                    continue
                if command == ("recut",):
                    try:
                        _seed(
                            "r2",
                            _BOOK_CASH_AFTER_FILL,
                            _FILL_QUANTITY,
                            _POSITION_COST_BASIS_AFTER_FILL,
                            _FILL_FEE,
                            baseline_version=2,
                            watermark_suffix="r1",
                            facts_cursor_start=2,
                        )
                        state["recut_ok"] = True
                    except BaseException as error:
                        state["recut_ok"] = False
                        state["recut_note"] = f"{type(error).__name__}:{error}"[:400]
                    control.send(("recut", state["recut_ok"], state["recut_note"]))
                    continue
                if command == ("close",):
                    host.close()
                    control.send(
                        (
                            "closed",
                            host.state,
                            tuple(host.summary["cleanup_failures"]),
                            close_calls[0],
                            tuple(quote_sources[0].calls) if quote_sources else (),
                        )
                    )
                    return
                raise AssertionError("unknown managed-paper recovery host command")
            host.serve_once(timeout_ms=20)
    except BaseException as error:
        if host is not None and host.state not in {"closed", "failed"}:
            with suppress(BaseException):
                host.close()
        with suppress(Exception):
            control.send(("host_error", getattr(error, "code", type(error).__name__), str(error)[:400]))
        raise
    finally:
        if close_calls[0] == 0:
            with suppress(Exception):
                store.close()
            close_calls[0] += 1
        control.close()


class _ManagedPaperQuoteFeed(ServiceRecoveryQuoteBindingMixin, bt.feeds.PandasData):
    """PandasData that freezes the managed-paper quote onto each loaded bar."""

    def _load(self):
        loaded = super()._load()
        if loaded:
            self._record_service_recovery_quote_bar(
                bar_index=len(self),
                datetime_hex=float(self.lines.datetime[0]).hex(),
            )
        return loaded


class _ManagedV2RecoveryStrategy(bt.Strategy):
    params = (
        ("pipe", None),
        ("crash_on_fill", False),
        ("strategy_ref", _STRATEGY),
        ("account_ref", _ACCOUNT),
    )

    def start(self):
        # The documented binding (examples/service_execution_session README):
        # the session's strategy_order_route_error fence rejects any submit
        # from an explicit strategy that was never bound to its account-book
        # view (strategy_writer_strategy_not_bound), even when the writer
        # scope and route otherwise match.
        self.account_book_binding = self.broker.bind_strategy_account_book(
            self,
            strategy_ref=self.p.strategy_ref,
            account_ref=self.p.account_ref,
        )
        self.order = None
        self.submit_calls = 0
        self.order_statuses = []
        self.trade_callbacks = []
        self.hydrated = []
        self.crash_sent = False
        trades_by_feed = getattr(self, "_trades", None) or {}
        for tradeid, trades in sorted(trades_by_feed.get(self.data, {}).items()):
            # ``_trades[data][tradeid]`` holds the ordered Trade list for the
            # id; each checkpoint replays exactly one trade here.
            for trade in trades:
                self.hydrated.append(
                    (
                        tradeid,
                        float(trade.size),
                        float(trade.price),
                        float(trade.commission),
                        bool(trade.isopen),
                        bool(trade.isclosed),
                    )
                )

    def next(self):
        if self.hydrated:
            # READY replay: the durable checkpoint already owns this trade.
            return
        if self.order is not None:
            return
        self.submit_calls += 1
        self.order = self.buy(
            data=self.data,
            size=float(_FILL_QUANTITY),
            exectype=bt.Order.Market,
            managed_order_type="MARKET",
            managed_intent_id=_INTENT_ID,
            managed_signal_id=_SIGNAL_ID,
            managed_instrument=_INSTRUMENT,
            managed_position_effect="OPEN",
            managed_metadata_version=_METADATA_VERSION,
            managed_instrument_metadata_digest="a" * 64,
            offset="open",
            reduce_only=False,
        )

    def notify_order(self, order):
        info = getattr(order, "info", None)
        error_code = None
        error_msg = None
        if info is not None:
            error_code = getattr(info, "error_code", None)
            error_msg = getattr(info, "error_msg", None)
            if error_code is None and isinstance(info, dict):
                error_code = info.get("error_code")
                error_msg = info.get("error_msg")
        self.order_statuses.append(
            (
                order.getstatusname(),
                float(order.executed.size),
                float(order.executed.comm),
                error_code,
                error_msg,
            )
        )

    def notify_trade(self, trade):
        self.trade_callbacks.append(
            (
                trade.tradeid,
                float(trade.size),
                float(trade.price),
                float(trade.commission),
                bool(trade.isopen),
            )
        )
        if (
            self.p.crash_on_fill
            and not self.crash_sent
            and self.p.pipe is not None
            and trade.isopen
        ):
            self.crash_sent = True
            # Designed crash window: the durable checkpoint was written before
            # this user callback and the journal ACK only follows its return.
            self.p.pipe.send(
                (
                    "crash_window",
                    self.submit_calls,
                    tuple(self.order_statuses),
                    tuple(self.trade_callbacks),
                    tuple(getattr(self, "hydrated", ())),
                    trade.tradeid,
                )
            )
            os._exit(_CRASH_EXITCODE)


def _build_cerebro(broker, pipe, crash_on_fill):
    dates = [dt.datetime(2026, 10, 16) + dt.timedelta(days=day) for day in range(4)]
    closes = [10.10, 10.20, 10.30, 10.40]
    frame = pandas.DataFrame(
        {
            "open": closes,
            "high": [price + 0.5 for price in closes],
            "low": [price - 0.5 for price in closes],
            "close": closes,
            "volume": [10.0] * len(closes),
            "openinterest": [0.0] * len(closes),
        },
        index=dates,
    )
    feed = _ManagedPaperQuoteFeed(dataname=frame)
    feed.note_service_recovery_quote(
        source_ref=_QUOTE_SOURCE_REF,
        generation=_QUOTE_GENERATION,
        cursor=_QUOTE_CURSOR,
        instrument=_INSTRUMENT,
        as_of_ns=_QUOTE_AS_OF_NS,
    )
    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    cerebro.setbroker(broker)
    cerebro.adddata(feed, name=_INSTRUMENT)
    cerebro.addstrategy(_ManagedV2RecoveryStrategy, pipe=pipe, crash_on_fill=crash_on_fill)
    return cerebro


def _strategy_facts(strategy, broker, session, runtime) -> dict:
    cached = broker.get_cached_report_state().get("positions", {})
    key = broker._position_key(strategy.data)
    position = cached.get(key)
    return {
        "submit_calls": strategy.submit_calls,
        "order_statuses": tuple(strategy.order_statuses),
        "trade_callbacks": tuple(strategy.trade_callbacks),
        "hydrated": tuple(strategy.hydrated),
        "cached_position": (
            None
            if position is None
            else (
                float(position.size),
                None if position.price is None else float(position.price),
            )
        ),
        "session_state": session.state,
        "cleanup_errors": tuple(session.cleanup_report.errors),
        "runtime_state": runtime.state,
    }


def _run_process(
    control,
    endpoint: str,
    keys,
    run_id: str,
    journal_path: str,
    crash_on_fill: bool,
    stale_lease_token,
) -> None:
    from backtrader.stores.service_execution_recovery import (
        ServiceExecutionRecoveryJournal,
        ServiceExecutionRecoveryNamespace,
    )

    journal = None
    runtime = None
    store = None
    try:
        journal = ServiceExecutionRecoveryJournal(journal_path)
        if stale_lease_token is not None:
            namespace = ServiceExecutionRecoveryNamespace(
                account_ref=_ACCOUNT,
                strategy_ref=_STRATEGY,
                logical_run_id=run_id,
            )
            journal.release_consumer_lease(namespace, stale_lease_token)
        runtime = ServiceClientRuntime(
            parse_client_config(_client_config(endpoint)),
            identity=WireIdentity(WireRole.STRATEGY_CLIENT, _PRINCIPAL, _STRATEGY),
            run_id=run_id,
            scope_resolver=lambda _scope_ref: _SCOPE,
            peer_resolver=lambda _service_id: WireIdentity(
                WireRole.SERVICE, _SERVICE_PRINCIPAL, _SERVICE_ID
            ),
            transport_factory=ZmqTransportFactory(
                {
                    _CLIENT_SECURITY_REF: ClientCurveKeys(
                        keys["server_public"], keys["client_public"], keys["client_secret"]
                    )
                }
            ),
            requested_operations={
                "broker.orders": frozenset({"orders.submit", "orders.cancel"}),
                "broker.order_query": frozenset(
                    {"orders.query", "execution.account_books.query"}
                ),
            },
        )
        store = make_store(
            api=FakeBtApiClient(balance={"cash": 1_000.0}, positions=[], open_orders=[]),
            provider="btapi",
        )
        broker = store.getbroker(
            validation_enabled=False,
            cash_check_enabled=False,
            account_refresh_interval=3_600.0,
            positions_refresh_interval=3_600.0,
            open_orders_refresh_interval=3_600.0,
        )
        session = ServiceExecutionSession(
            runtime,
            mount="broker.orders",
            scope_ref=_ORDER_SCOPE_REF,
            query_mount="broker.order_query",
            query_scope_ref=_QUERY_SCOPE_REF,
            recovery_journal=journal,
            logical_run_id=run_id,
            recovery_event_version=2,
        )
        control.send(("configured", session._recovery_consumer_token))
        cerebro = _build_cerebro(broker, control, crash_on_fill)
        strategies = session.run(cerebro)
        strategy = strategies[0]
        control.send(("run_done", _strategy_facts(strategy, broker, session, runtime)))
    except BaseException as error:
        context_error = error.__context__ or error.__cause__
        with suppress(Exception):
            control.send(
                (
                    "run_error",
                    getattr(error, "code", type(error).__name__),
                    str(error)[:800],
                    (
                        ""
                        if context_error is None
                        else f"{type(context_error).__name__}:{context_error}"[:800]
                    ),
                )
            )
        directory = os.environ.get("IT10_BTV2_EVIDENCE_DIR")
        if directory:
            import traceback

            # The managed-recovery fence raises ``RuntimeError ... from None``
            # and suppresses the original projection error.  Walk the explicit
            # cause/context chain so the evidence keeps the inner failure.
            chain_parts = []
            seen_errors = set()
            current = error
            while current is not None and id(current) not in seen_errors:
                seen_errors.add(id(current))
                chain_parts.append(
                    "".join(
                        traceback.format_exception(
                            type(current), current, current.__traceback__
                        )
                    )
                )
                current = current.__cause__ or current.__context__
            with suppress(Exception):
                (Path(directory) / "run-child-error.log").write_text(
                    "\n--- chained ---\n".join(chain_parts), encoding="utf-8"
                )
        # Capture the local reconciliation verdict (and its reason string)
        # for both pipe and evidence, since the strategy fences the generic
        # message.  Everything here is best-effort diagnostics only.
        with suppress(Exception):
            diagnostics: dict = {}
            adapter = None
            with suppress(Exception):
                adapter = getattr(session, "adapter", None)
            diagnostics["reconciliation"] = getattr(
                adapter, "recovery_owner_position_reconciliation", None
            )
            namespace = ServiceExecutionRecoveryNamespace(
                account_ref=_ACCOUNT,
                strategy_ref=_STRATEGY,
                logical_run_id=run_id,
            )
            baseline = journal.recovery_baseline(namespace)
            diagnostics["baseline"] = baseline
            if baseline is not None:
                with suppress(Exception):
                    diagnostics["events_complete"] = (
                        journal._trade_projection_events_complete(namespace, baseline)
                    )
            diagnostics["snapshot_orders"] = journal.snapshot_orders(
                namespace, matched_only=False
            )
            payload = json.dumps(diagnostics, default=str, sort_keys=True)
            control.send(("run_diagnostics", payload[:4000]))
            if directory:
                (Path(directory) / f"run-child-diagnostics-{run_id}.json").write_text(
                    payload, encoding="utf-8"
                )
        raise
    finally:
        if store is not None and getattr(store, "is_connected", False):
            with suppress(Exception):
                store.stop()
        if runtime is not None and runtime.state not in {"closed", "failed"}:
            with suppress(Exception):
                runtime.close()
        with suppress(Exception):
            control.close()


def _receive(pipe, timeout: float = 30.0):
    if not pipe.poll(timeout):
        raise TimeoutError("managed-paper recovery pipe missed its response bound")
    return pipe.recv()


def _collect_until_exit(pipe, process, timeout: float):
    messages = []

    def drain() -> None:
        while True:
            try:
                messages.append(pipe.recv())
            except (EOFError, OSError):
                return

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            has_data = pipe.poll(0.5)
        except (BrokenPipeError, OSError):
            drain()
            break
        if has_data:
            try:
                messages.append(pipe.recv())
            except (EOFError, OSError):
                break
            continue
        if not process.is_alive():
            drain()
            break
    process.join(30)
    return messages, process.exitcode, process.is_alive()


def _reap(process, pipe) -> dict:
    forced = False
    process.join(30)
    if process.is_alive():
        forced = True
        process.terminate()
        process.join(10)
    if process.is_alive():
        forced = True
        process.kill()
        process.join(10)
    exitcode = process.exitcode if not process.is_alive() else None
    with suppress(Exception):
        if not pipe.closed:
            pipe.close()
    return {"exitcode": exitcode, "forced_cleanup": forced}


def _host_command(host, command):
    host["pipe"].send(command)
    return _receive(host["pipe"], timeout=60.0)


def _journal_forensics(path: str) -> dict:
    connection = sqlite3.connect(path)
    try:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        ]
        facts = {"tables": tuple(sorted(tables))}
        if "service_recovery_event_receipts" in tables:
            facts["receipt_count"] = connection.execute(
                "SELECT COUNT(*) FROM service_recovery_event_receipts"
            ).fetchone()[0]
        else:
            facts["receipt_count"] = None
        callbacks = ()
        if "service_recovery_callbacks" in tables:
            callbacks = tuple(
                connection.execute(
                    "SELECT receipt_id, delivery_attempts, acknowledged_at_ns"
                    " FROM service_recovery_callbacks"
                ).fetchall()
            )
        facts["callbacks"] = callbacks
        facts["pending"] = tuple(
            row for row in callbacks if row[2] is None
        )
        checkpoint = None
        for table in tables:
            columns = [
                row[1] for row in connection.execute(f"PRAGMA table_info({table})")
            ]
            if "trade_state_json" in columns:
                rows = connection.execute(f"SELECT * FROM {table}").fetchall()
                checkpoint = {
                    "table": table,
                    "columns": tuple(columns),
                    "rows": tuple(
                        tuple(None if item is None else str(item) for item in row)
                        for row in rows
                    ),
                }
                break
        facts["checkpoint"] = checkpoint
        return facts
    finally:
        connection.close()


def _registry_pending(path: str):
    """Return rows still blocking a same-run write claim, best effort."""

    connection = sqlite3.connect(path)
    try:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        ]
        waiting = []
        if "sessions" in tables:
            columns = [
                row[1] for row in connection.execute("PRAGMA table_info(sessions)")
            ]
            expiry = next(
                (name for name in columns if "expire" in name.lower()), None
            )
            if expiry is not None:
                for (value,) in connection.execute(f"SELECT {expiry} FROM sessions"):
                    if value is None:
                        continue
                    number = float(value)
                    now = time.time_ns() if number > 10**15 else time.time()
                    if number > now:
                        waiting.append(("sessions", expiry, number))
        if "strategy_write_claims" in tables:
            columns = [
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(strategy_write_claims)"
                )
            ]
            if "active_registration_id" in columns:
                for (value,) in connection.execute(
                    "SELECT active_registration_id FROM strategy_write_claims"
                ):
                    if value is not None:
                        waiting.append(
                            ("strategy_write_claims", "active_registration_id", value)
                        )
        return waiting
    finally:
        connection.close()


def _wait_registry_release(path: str, timeout: float):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = _registry_pending(path)
        except sqlite3.Error as error:
            last = [("sqlite_error", type(error).__name__, str(error))]
        if not last:
            return ()
        time.sleep(1.0)
    return tuple(last)


def _dump_evidence(name: str, payload) -> None:
    directory = os.environ.get("IT10_BTV2_EVIDENCE_DIR")
    if not directory:
        return
    target = Path(directory) / name
    with suppress(Exception):
        target.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )


def _copy_evidence_artifacts(sources) -> None:
    directory = os.environ.get("IT10_BTV2_EVIDENCE_DIR")
    if not directory:
        return
    for label, source in sources.items():
        with suppress(Exception):
            if Path(source).is_file():
                shutil.copy2(source, Path(directory) / f"artifact-{label}.sqlite3")


def test_managed_paper_v2_fresh_process_recovery_is_exactly_once(tmp_path):
    context = multiprocessing.get_context("spawn")
    endpoint = _endpoint()
    keys = _curve_keys()
    registry_path = str(tmp_path / "managed-paper-v2-registry.sqlite3")
    store_path = str(tmp_path / "managed-paper-v2-execution.sqlite3")
    journal_path = str(tmp_path / "managed-paper-v2-recovery-journal.sqlite3")

    host = None
    run1 = None
    run2 = None
    facts: dict = {}
    try:
        host_pipe = context.Pipe(duplex=True)
        host_process = context.Process(
            target=_host_process,
            args=(
                host_pipe[1],
                _service_config(endpoint),
                registry_path,
                store_path,
                keys,
            ),
            name="managed-paper-v2-recovery-host",
        )
        host_process.start()
        host_pipe[1].close()
        host = {"pipe": host_pipe[0], "process": host_process}
        ready = _receive(host["pipe"], timeout=_HOST_READY_TIMEOUT)
        assert ready[0] == "ready", ready
        assert ready[1] == endpoint
        assert ready[2] == "started"
        facts["financial_seed_ok"] = ready[3]
        facts["financial_seed_note"] = ready[4]

        # Run 1: one real paper fill, then the designed crash inside the user
        # trade callback before the journal acknowledgement is written.
        run1_pipe = context.Pipe(duplex=True)
        run1 = context.Process(
            target=_run_process,
            args=(
                run1_pipe[1],
                endpoint,
                keys,
                _RUN_ID,
                journal_path,
                True,
                None,
            ),
            name="managed-paper-v2-recovery-run1",
        )
        run1.start()
        run1_pipe[1].close()
        configured1 = _receive(run1_pipe[0], timeout=60.0)
        assert configured1[0] == "configured", configured1
        run1_token = configured1[1]
        assert type(run1_token) is str and run1_token

        messages1, exitcode1, alive1 = _collect_until_exit(
            run1_pipe[0], run1, _CRASH_WAIT_TIMEOUT
        )
        assert alive1 is False, (messages1, exitcode1)
        crash_messages = [item for item in messages1 if item and item[0] == "crash_window"]
        if not crash_messages:
            _dump_evidence("run1-unexpected.json", messages1)
        assert crash_messages, messages1
        crash = crash_messages[0]
        facts["run1_crash_message"] = crash
        assert exitcode1 == _CRASH_EXITCODE, (exitcode1, messages1)
        assert crash[1] == 1  # exactly one submit
        assert crash[5] is not None  # tradeid observed in the callback

        pre_forensics = _journal_forensics(journal_path)
        facts["journal_pre_restart"] = pre_forensics
        _dump_evidence("journal-pre-restart.json", pre_forensics)
        assert pre_forensics["receipt_count"] is not None
        assert pre_forensics["receipt_count"] >= 1
        assert len(pre_forensics["pending"]) >= 1
        assert pre_forensics["checkpoint"] is not None
        checkpoint_text = "\n".join(
            "|".join(row) for row in pre_forensics["checkpoint"]["rows"]
        )
        assert "READY" in checkpoint_text
        for value in ("1.25", "10.02", "0.0125"):
            assert value in checkpoint_text, pre_forensics["checkpoint"]

        metrics_after_crash = _host_command(host, ("metrics",))
        assert metrics_after_crash[0] == "metrics"
        metrics1 = metrics_after_crash[1]
        facts["host_metrics_after_crash"] = metrics1
        _dump_evidence("host-metrics-after-crash.json", metrics1)
        assert metrics1["record_state"] == "FILLED"
        assert metrics1["dispatch_attempts"] == 1
        assert metrics1["filled_quantity"] == "1.25"
        assert metrics1["average_price"] == "10.02"
        assert metrics1["cumulative_commission"] == "0.0125"
        assert metrics1["receipt_state"] == "FILLED"
        assert metrics1["receipt_domain"] == _DOMAIN
        assert metrics1["receipt_experiment"] == "paper-host-experiment-v1"
        assert metrics1["receipt_quote"] == (_QUOTE_SOURCE_REF, _QUOTE_GENERATION, _QUOTE_CURSOR)
        assert metrics1["book_cash"] == "87.4625"
        assert metrics1["book_fees"] == "0.0125"
        assert metrics1["book_positions"] == ((_INSTRUMENT, "1.25", "10.02"),)
        assert metrics1["book_receipts"] == 1
        assert metrics1["quote_calls"] == (_INSTRUMENT,)
        assert metrics1["provider_event_count"] == 1

        # The dead run's host registration must expire before the same logical
        # run may claim its write route again.
        registry_wait = _wait_registry_release(registry_path, _REGISTRY_WAIT_TIMEOUT)
        facts["registry_wait"] = registry_wait

        recut_reply = _host_command(host, ("recut",))
        assert recut_reply[0] == "recut"
        facts["recut_ok"] = recut_reply[1]
        facts["recut_note"] = recut_reply[2]

        # Run 2 attempts: the same logical run_id on the same journal and host.
        run2_reply = None
        for attempt in range(1, _RUN2_ATTEMPTS + 1):
            run2_pipe = context.Pipe(duplex=True)
            run2 = context.Process(
                target=_run_process,
                args=(
                    run2_pipe[1],
                    endpoint,
                    keys,
                    _RUN_ID,
                    journal_path,
                    False,
                    run1_token,
                ),
                name=f"managed-paper-v2-recovery-run2-a{attempt}",
            )
            run2.start()
            run2_pipe[1].close()
            try:
                configured2 = _receive(run2_pipe[0], timeout=60.0)
            except TimeoutError:
                configured2 = None
            if configured2 is not None and configured2[0] == "configured":
                try:
                    run2_reply = _receive(run2_pipe[0], timeout=_RUN2_WAIT_TIMEOUT)
                except TimeoutError:
                    run2_reply = None
            else:
                run2_reply = configured2
            reap = _reap(run2, run2_pipe[0])
            if run2_reply is not None and run2_reply[0] == "run_done":
                facts["run2_reap"] = reap
                break
            blocked = (
                run2_reply is not None
                and run2_reply[0] == "run_error"
                and "DUPLICATE_ACTIVE_RUN" in str(run2_reply)
            )
            facts[f"run2_attempt_{attempt}"] = {"reply": run2_reply, "reap": reap}
            if not blocked or attempt == _RUN2_ATTEMPTS:
                raise AssertionError(f"run2 failed: {run2_reply!r} reap={reap!r}")
            time.sleep(10.0)

        assert run2_reply is not None and run2_reply[0] == "run_done", run2_reply
        run2_facts = run2_reply[1]
        facts["run2_facts"] = run2_facts
        _dump_evidence("run2-facts.json", run2_facts)
        assert run2_facts["session_state"] == "closed"
        assert run2_facts["cleanup_errors"] == ()
        assert run2_facts["runtime_state"] == "closed"
        assert run2_facts["submit_calls"] == 0

        # Hydrated Trade equals the durable checkpoint (exactly one trade).
        assert len(run2_facts["hydrated"]) == 1, run2_facts["hydrated"]
        hydrated = run2_facts["hydrated"][0]
        assert hydrated[1] == pytest.approx(1.25)
        assert hydrated[2] == pytest.approx(10.02)
        assert hydrated[3] == pytest.approx(0.0125)
        assert hydrated[4] is True  # still open

        # ACK replay: the pending callback is delivered once in run2 with the
        # same trade identity; no duplicate Trade/order was created.
        assert len(run2_facts["trade_callbacks"]) == 1, run2_facts["trade_callbacks"]
        replay = run2_facts["trade_callbacks"][0]
        assert replay[0] == hydrated[0]
        assert replay[1] == pytest.approx(1.25)
        assert replay[2] == pytest.approx(10.02)
        assert replay[3] == pytest.approx(0.0125)

        post_forensics = _journal_forensics(journal_path)
        facts["journal_post_restart"] = post_forensics
        _dump_evidence("journal-post-restart.json", post_forensics)
        assert post_forensics["pending"] == ()
        assert post_forensics["receipt_count"] == pre_forensics["receipt_count"]
        pre_callbacks = {row[0]: row for row in pre_forensics["callbacks"]}
        post_callbacks = {row[0]: row for row in post_forensics["callbacks"]}
        for receipt_id, attempts, acknowledged in pre_forensics["callbacks"]:
            if acknowledged is not None:
                continue
            assert receipt_id in post_callbacks, post_forensics
            _, post_attempts, post_acknowledged = post_callbacks[receipt_id]
            assert post_acknowledged is not None
            assert post_attempts >= attempts + 1

        # Exactly-once at the host: still one dispatch, one quote read, one
        # provider observation, one receipt.
        final = _host_command(host, ("metrics",))
        assert final[0] == "metrics"
        metrics2 = final[1]
        facts["host_metrics_final"] = metrics2
        _dump_evidence("host-metrics-final.json", metrics2)
        assert metrics2["dispatch_attempts"] == 1
        assert metrics2["record_state"] == "FILLED"
        assert metrics2["filled_quantity"] == "1.25"
        assert metrics2["book_receipts"] == 1
        assert metrics2["quote_calls"] == (_INSTRUMENT,)
        assert metrics2["provider_event_count"] == 1
    finally:
        if run1 is not None and run1.is_alive():
            run1.terminate()
            run1.join(10)
            if run1.is_alive():
                run1.kill()
                run1.join(10)
        if run2 is not None and run2.is_alive():
            run2.terminate()
            run2.join(10)
            if run2.is_alive():
                run2.kill()
                run2.join(10)
        if host is not None:
            try:
                if not host["process"].is_alive():
                    raise AssertionError("host died early")
                close_reply = _host_command(host, ("close",))
                facts["host_close_reply"] = close_reply
                assert close_reply[0] == "closed"
                assert close_reply[1] == "closed"
                assert close_reply[2] == ()
            except BaseException as close_error:
                facts["host_close_error"] = f"{type(close_error).__name__}:{close_error}"[:300]
            _reap(host["process"], host["pipe"])
        _copy_evidence_artifacts(
            {
                "journal": journal_path,
                "registry": registry_path,
                "execution-store": store_path,
            }
        )
        _dump_evidence("orchestrator-facts.json", facts)
