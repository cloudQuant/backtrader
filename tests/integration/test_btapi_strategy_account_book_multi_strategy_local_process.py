"""Two Cerebro Strategies read separate owner books through one Broker.

This local synthetic integration node starts a real SDK ServiceHost with CURVE
authentication and SQLite state. It verifies the Backtrader Strategy binding
and runtime lifecycle, not provider/account acceptance.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import multiprocessing
import os
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

from backtrader.stores.service_execution_session import (  # noqa: E402
    ServiceExecutionSession,
    ServiceExecutionSessionConfigError,
    ServiceStrategyAccountBookRoute,
)
from backtrader.stores.service_strategy_account_book import (  # noqa: E402
    ServiceStrategyAccountBookError,
)
from tests.fixtures.fake_btapi import FakeBtApiClient, make_store  # noqa: E402

_DOMAIN = "paper:backtrader-multi-strategy-book"
_SERVICE_ID = "bt-multi-book-service"
_SERVICE_PRINCIPAL = "bt-multi-book-service-principal"
_INSTANCE_ID = "bt-multi-book-owner"
_SERVICE_SCOPE_REF = "bt-multi-book-root-v1"
_SERVER_SECURITY_REF = "bt-multi-book-server-curve-v1"
_CLIENT_SECURITY_REF = "bt-multi-book-client-curve-v1"
_ACCOUNT = "account.synthetic.shared"
_STRATEGY_A = "strategy.synthetic.alpha"
_STRATEGY_B = "strategy.synthetic.beta"
_PRINCIPAL_A = "bt-multi-book-alpha-principal"
_PRINCIPAL_B = "bt-multi-book-beta-principal"
_ORDER_SCOPE_A = "bt-multi-book-alpha-orders-v1"
_QUERY_SCOPE_A = "bt-multi-book-alpha-query-v1"
_QUERY_SCOPE_B = "bt-multi-book-beta-query-v1"
_TRANSPORT_REF = "bt-multi-book-connect-v1"
_LISTENER_REF = "bt-multi-book-listener-v1"
_MAX_MESSAGE_BYTES = 65_536
_INSTRUMENT = "PAPER:SIM:BTC-USDT"
_WIRE_SCOPE_A = WireScope(_DOMAIN, account_ref=_ACCOUNT, strategy_ref=_STRATEGY_A)
_WIRE_SCOPE_B = WireScope(_DOMAIN, account_ref=_ACCOUNT, strategy_ref=_STRATEGY_B)
_FINANCIAL_BASELINE_CASH = {_STRATEGY_A: Decimal("1000"), _STRATEGY_B: Decimal("500")}
_FINANCIAL_BASELINE_POSITION = {_STRATEGY_A: Decimal("2"), _STRATEGY_B: Decimal("1")}
_FINANCIAL_BASELINE_COST = {_STRATEGY_A: Decimal("200"), _STRATEGY_B: Decimal("45")}
_FINANCIAL_CASH_AFTER_FILL = {_STRATEGY_A: Decimal("939.97"), _STRATEGY_B: Decimal("500")}
_FINANCIAL_POSITION_AFTER_FILL = {_STRATEGY_A: Decimal("2.5"), _STRATEGY_B: Decimal("1")}
_FINANCIAL_COST_AFTER_FILL = {_STRATEGY_A: Decimal("260"), _STRATEGY_B: Decimal("45")}
_FINANCIAL_FEES_AFTER_FILL = {_STRATEGY_A: Decimal("0.03"), _STRATEGY_B: Decimal("0")}
_FINANCIAL_BASELINE_REF = "bt-multi-strategy-financial-baseline-r1"
_FINANCIAL_DIRECTORY_REVISION = "bt-multi-strategy-financial-owners-r1"
_FINANCIAL_METADATA_VERSION = "bt-multi-strategy-spot-r1"
_FINANCIAL_FILL_ID = "bt-multi-strategy-financial-fill-1"
_SOURCE_ROOT_ENV = {
    "sdk": "BT_STRATEGY_FINANCIAL_SDK_ROOT",
    "base": "BT_STRATEGY_FINANCIAL_BASE_ROOT",
    "execution": "BT_STRATEGY_FINANCIAL_EXECUTION_ROOT",
    "transport": "BT_STRATEGY_FINANCIAL_TRANSPORT_ROOT",
}


def _loaded_source_origins():
    import bt_api_base.service_protocol as base_protocol
    import bt_api_execution.store as execution_store
    import bt_api_py.service_execution_account_books as account_books
    import bt_api_py.service_host as service_host
    import bt_api_py.service_runtime as service_runtime
    import bt_api_transport_zmq.service_v2 as service_transport

    return {
        "sdk": {
            "account_books": str(Path(account_books.__file__).resolve()),
            "service_host": str(Path(service_host.__file__).resolve()),
            "service_runtime": str(Path(service_runtime.__file__).resolve()),
        },
        "base": {"service_protocol": str(Path(base_protocol.__file__).resolve())},
        "execution": {"store": str(Path(execution_store.__file__).resolve())},
        "transport": {"service_v2": str(Path(service_transport.__file__).resolve())},
    }


def _assert_source_origins(origins):
    for package, modules in origins.items():
        configured_root = os.environ.get(_SOURCE_ROOT_ENV[package])
        expected_root = Path(configured_root).resolve() if configured_root else None
        for module_name, raw_path in modules.items():
            module_path = Path(raw_path).resolve()
            if not module_path.is_file():
                raise AssertionError(f"{package}.{module_name} source file is missing")
            if expected_root is not None and not module_path.is_relative_to(expected_root):
                raise AssertionError(
                    f"{package}.{module_name} loaded outside its fixed source export"
                )
    return origins


def _report_source_origins(label, origins):
    if any(os.environ.get(name) for name in _SOURCE_ROOT_ENV.values()):
        print(
            f"{label} source origins: {json.dumps(origins, sort_keys=True)}",
            flush=True,
        )


def _endpoint() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return f"tcp://127.0.0.1:{probe.getsockname()[1]}"


def _service_config(endpoint: str) -> dict:
    return {
        "service_config_schema_version": 1,
        "process_role": "service",
        "service_id": _SERVICE_ID,
        "scope_ref": _SERVICE_SCOPE_REF,
        "transport_ref": _LISTENER_REF,
        "registration_policy_ref": "bt-multi-book-registration-v1",
        "service_requirements_ref": "bt-multi-book-requirements-v1",
        "components": {
            "execution": {
                "config_schema_version": 2,
                "settings": {
                    "instance_id": _INSTANCE_ID,
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


def _client_config(
    endpoint: str,
    *,
    strategy_ref: str,
    include_writer: bool,
    order_scope_ref: str | None,
    query_scope_ref: str,
) -> dict:
    bindings = []
    if include_writer:
        bindings.append(
            {
                "mount": "broker.orders",
                "service_id": _SERVICE_ID,
                "instance_id": _INSTANCE_ID,
                "scope_ref": order_scope_ref,
                "transport_ref": _TRANSPORT_REF,
                "account_ref": _ACCOUNT,
            }
        )
    bindings.append(
        {
            "mount": "broker.order_query",
            "service_id": _SERVICE_ID,
            "instance_id": _INSTANCE_ID,
            "scope_ref": query_scope_ref,
            "transport_ref": _TRANSPORT_REF,
            "account_ref": _ACCOUNT,
        }
    )
    return {
        "client_config_schema_version": 1,
        "process_role": "strategy_client",
        "registration": {"strategy_ref": strategy_ref},
        "clients": {
            "execution": {
                "config_schema_version": 1,
                "settings": {
                    "bindings": bindings,
                    "options": {"request_timeout_ms": 2_000},
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
                        "request_timeout_ms": 2_000,
                        "high_water_mark": 32,
                        "max_message_bytes": _MAX_MESSAGE_BYTES,
                    },
                }
            },
        },
    }


class _NoOrderDispatch:
    """A synthetic service that records and rejects every write."""

    def __init__(self):
        self.submit_count = 0
        self.cancel_count = 0

    def submit(self, _intent):
        self.submit_count += 1
        raise AssertionError("the local read-only integration must not dispatch an order")

    def cancel(self, _intent):
        self.cancel_count += 1
        raise AssertionError("the local read-only integration must not dispatch a cancel")


class _ClosedAdmissionGate:
    def reserve(self, _intent):
        raise AssertionError("the local read-only integration must not reserve a write")

    def claim_before_dispatch(self, _intent):
        raise AssertionError("the local read-only integration must not admit a cancel")


class _FinancialSeedPermit:
    def __init__(self, permit_id: str) -> None:
        self.permit_id = permit_id


class _FinancialSeedAdmission:
    """Synthetic leaf used only to persist one typed local execution fill."""

    def reserve(self, intent):
        return _FinancialSeedPermit(f"financial-seed-{intent.intent_id}")

    def validate(self, permit_id, intent):
        if permit_id != f"financial-seed-{intent.intent_id}":
            raise AssertionError("unexpected synthetic financial seed permit")
        return _FinancialSeedPermit(permit_id)

    def settle(self, permit_id):
        if not permit_id.startswith("financial-seed-"):
            raise AssertionError("unexpected synthetic financial seed permit")

    def release(self, permit_id, reason):
        if not permit_id.startswith("financial-seed-") or not reason:
            raise AssertionError("unexpected synthetic financial seed release")


def _financial_owner_directory(execution_scopes):
    from bt_api_execution import (
        FinancialOwnerDirectoryV1,
        FinancialOwnerKind,
        FinancialOwnerV1,
    )

    return FinancialOwnerDirectoryV1(
        execution_scopes[0].account_key,
        _FINANCIAL_DIRECTORY_REVISION,
        "synthetic-trusted-bt-strategy-owner-directory-r1",
        tuple(
            FinancialOwnerV1(FinancialOwnerKind.STRATEGY, strategy_ref, scope.key)
            for strategy_ref, scope in zip((_STRATEGY_A, _STRATEGY_B), execution_scopes)
        ),
    )


def _seed_persisted_financial_projection(store, execution_scopes):
    """Persist one typed baseline and one synthetic fill through Execution APIs."""

    from bt_api_execution import (
        AccountFinancialBaselineV1,
        CurrencyAmountV1,
        ExecutionState,
        FinancialActivityBatchV1,
        FinancialInstrumentSpecV1,
        FinancialLedgerCutV1,
        FinancialLedgerPolicyV1,
        FinancialOwnerBaselineV1,
        FinancialSourceKind,
        FinancialWatermarkV1,
        ManagedExecutionFacade,
        OrderIntent,
        OwnerPositionCostV1,
        ProviderAccountFinancialSnapshotV1,
        ProviderObservation,
        Side,
    )

    directory = _financial_owner_directory(execution_scopes)
    scope = execution_scopes[0]
    facade = ManagedExecutionFacade(
        store,
        scope,
        writer_id="bt-multi-strategy-financial-seed-writer",
        admission_gate=_FinancialSeedAdmission(),
    )
    lease = None
    try:
        intent = OrderIntent.limit(
            intent_id=_FINANCIAL_FILL_ID,
            scope=scope,
            signal_id="bt-multi-strategy-financial-fill-signal-1",
            instrument=_INSTRUMENT,
            side=Side.BUY,
            quantity=Decimal("1.0"),
            price=Decimal("120"),
            metadata_version=_FINANCIAL_METADATA_VERSION,
        )
        facade.submit(
            intent,
            lambda order: ProviderObservation.accepted(
                order.intent_id, "synthetic-provider-order-financial-fill-1"
            ),
        )
        lease = facade.acquire_writer_lease()
        execution_baseline = store.capture_account_financial_execution_cursors(scope, lease)
        baseline_ns = max(time.time_ns(), execution_baseline.as_of_ns)
        execution_wm = FinancialWatermarkV1(
            FinancialSourceKind.EXECUTION_OUTBOX,
            "sqlite-execution-outbox",
            execution_baseline.journal_generation,
            execution_baseline.cursor,
            execution_baseline.as_of_ns,
        )
        facts_wm = FinancialWatermarkV1(
            FinancialSourceKind.ACCOUNT_FACTS,
            "synthetic-provider-financial-account-facts",
            "bt-multi-book-provider-financial-facts-r1",
            1,
            baseline_ns,
        )
        activity_wm = FinancialWatermarkV1(
            FinancialSourceKind.ACCOUNT_ACTIVITY,
            "synthetic-provider-financial-account-activity",
            "bt-multi-book-provider-financial-activity-r1",
            0,
            baseline_ns,
        )
        baseline_cut = FinancialLedgerCutV1(
            scope.account_key,
            directory.revision,
            baseline_ns,
            (execution_wm, facts_wm, activity_wm),
        )
        baseline_account = ProviderAccountFinancialSnapshotV1(
            scope.account_key,
            facts_wm.source_ref,
            facts_wm.generation,
            facts_wm.cursor,
            facts_wm.as_of_ns,
            (CurrencyAmountV1("USDT", Decimal("1500")),),
            ((_INSTRUMENT, Decimal("3")),),
            (CurrencyAmountV1("USDT", Decimal("0")),),
        )
        baseline = AccountFinancialBaselineV1(
            scope.account_key,
            _FINANCIAL_BASELINE_REF,
            1,
            "synthetic-trusted-baseline-authority-r1",
            "synthetic-trusted-financial-baseline-source-r1",
            directory.revision,
            baseline_cut,
            baseline_account,
            tuple(
                FinancialOwnerBaselineV1(
                    owner,
                    (CurrencyAmountV1("USDT", _FINANCIAL_BASELINE_CASH[owner.owner_ref]),),
                    (
                        OwnerPositionCostV1(
                            _INSTRUMENT,
                            _FINANCIAL_BASELINE_POSITION[owner.owner_ref],
                            _FINANCIAL_BASELINE_COST[owner.owner_ref],
                            "USDT",
                            metadata_version=_FINANCIAL_METADATA_VERSION,
                        ),
                    ),
                    (CurrencyAmountV1("USDT", Decimal("0")),),
                )
                for owner in directory.owners
            ),
            execution_cursors=execution_baseline,
        )
        store.install_account_financial_baseline(
            baseline,
            directory,
            writer_scope=scope,
            writer_lease=lease,
        )

        facade.record_provider_observation_event(
            ProviderObservation(
                intent.intent_id,
                ExecutionState.PARTIALLY_FILLED,
                provider_order_id="synthetic-provider-order-financial-fill-1",
                filled_quantity=Decimal("0.5"),
                average_price=Decimal("120"),
                cumulative_commission=Decimal("0.03"),
                cumulative_commission_currency="USDT",
            )
        )
        now_ns = time.time_ns()
        generation = str(store.journal_source_identity()["generation"])
        _count, _first, _last, execution_cursor = store.execution_outbox_bounds()
        current_execution = FinancialWatermarkV1(
            FinancialSourceKind.EXECUTION_OUTBOX,
            "sqlite-execution-outbox",
            generation,
            execution_cursor,
            now_ns,
        )
        current_facts = FinancialWatermarkV1(
            FinancialSourceKind.ACCOUNT_FACTS,
            facts_wm.source_ref,
            facts_wm.generation,
            2,
            now_ns,
        )
        current_activity = FinancialWatermarkV1(
            FinancialSourceKind.ACCOUNT_ACTIVITY,
            activity_wm.source_ref,
            activity_wm.generation,
            0,
            now_ns,
        )
        current_cut = FinancialLedgerCutV1(
            scope.account_key,
            directory.revision,
            now_ns,
            (current_execution, current_facts, current_activity),
        )
        current_account = ProviderAccountFinancialSnapshotV1(
            scope.account_key,
            current_facts.source_ref,
            current_facts.generation,
            current_facts.cursor,
            current_facts.as_of_ns,
            (CurrencyAmountV1("USDT", Decimal("1439.97")),),
            ((_INSTRUMENT, Decimal("3.5")),),
            (CurrencyAmountV1("USDT", Decimal("0.03")),),
        )
        store.reconcile_account_financials(
            baseline,
            directory,
            current_account=current_account,
            current_cut=current_cut,
            activity_batch=FinancialActivityBatchV1(
                current_activity.source_ref,
                current_activity.generation,
                0,
                0,
                now_ns,
                (),
            ),
            instrument_specs={
                _INSTRUMENT: FinancialInstrumentSpecV1(
                    _INSTRUMENT,
                    _FINANCIAL_METADATA_VERSION,
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
            writer_scope=scope,
            writer_lease=lease,
            now_ns=now_ns,
        )
    finally:
        if lease is not None:
            store.release_lease(scope, lease.owner_id, fencing_token=lease.fencing_token)
        facade.close()

    persisted = store.read_account_financial_projection(
        scope.account_key,
        expected_directory=directory,
    )
    if not persisted.complete:
        raise AssertionError("synthetic persisted financial projection is incomplete")
    return directory


def _financial_database_state(path):
    with sqlite3.connect(path) as connection:
        return (
            connection.execute("SELECT COUNT(*) FROM execution_outbox").fetchone()[0],
            connection.execute("SELECT COUNT(*) FROM account_financial_baselines").fetchone()[0],
            connection.execute("SELECT COUNT(*) FROM account_financial_events").fetchone()[0],
            connection.execute(
                "SELECT baseline_version, scanned_sequence, projection_sha256, input_sha256 "
                "FROM account_financial_ledger_heads"
            ).fetchone(),
        )


def _stored_financial_execution_baseline(store, account_key):
    row = store._connection.execute(
        "SELECT execution_cursor, baseline_json FROM account_financial_baselines "
        "WHERE account_key = ? AND version = 1",
        (account_key,),
    ).fetchone()
    if row is None:
        raise AssertionError("the trusted synthetic financial baseline was not persisted")
    baseline_payload = json.loads(row[1])
    cut = baseline_payload["cut"]
    execution_watermark = next(
        row for row in cut["watermarks"] if row["source_kind"] == "execution_outbox"
    )
    return int(row[0]), int(cut["captured_at_ns"]), execution_watermark["generation"]


class _SyntheticOwnerFacts:
    """Complete deterministic facts for two owners within one account."""

    def __init__(
        self,
        execution_scopes,
        financial_directory,
        baseline_execution_cursor,
        baseline_ns,
        baseline_journal_generation,
    ):
        self._execution_scopes = tuple(execution_scopes)
        self._financial_directory = financial_directory
        self._baseline_execution_cursor = baseline_execution_cursor
        self._baseline_ns = baseline_ns
        self._baseline_journal_generation = baseline_journal_generation
        self.read_count = 0
        self.financial_directory_read_count = 0
        self.last_cut = None

    def authorize_account_view(self, **_kwargs) -> bool:
        return False

    def authorize_manual_book_view(self, **_kwargs) -> bool:
        return False

    def read_financial_owner_directory(self, *, account_key):
        if account_key != self._execution_scopes[0].account_key:
            raise AssertionError("financial directory requested for an unexpected account")
        self.financial_directory_read_count += 1
        return self._financial_directory

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

        if account_key != self._execution_scopes[0].account_key:
            raise AssertionError("account-book source received an unexpected account")
        self.read_count += 1
        self.last_cut = (journal_generation, execution_cursor)
        baseline_ns = self._baseline_ns
        if journal_generation != self._baseline_journal_generation:
            raise AssertionError("execution journal generation changed after baseline")
        current_ns = max(time.time_ns(), baseline_ns + 3)
        directory_revision = "synthetic-two-owner-directory-r1"
        provider_generation = "synthetic-two-owner-provider-r1"
        scopes = tuple(
            ExecutionOwnerScope(
                execution_scope,
                AllocationOwnerKind.STRATEGY,
                strategy_ref,
                wire_scope,
            )
            for strategy_ref, execution_scope, wire_scope in (
                (_STRATEGY_A, self._execution_scopes[0], _WIRE_SCOPE_A),
                (_STRATEGY_B, self._execution_scopes[1], _WIRE_SCOPE_B),
            )
        )
        directory = ExecutionScopeDirectory(
            account_key=account_key,
            source="synthetic-trusted-owner-registry",
            source_ref="synthetic-two-owner-registry-r1",
            revision=directory_revision,
            covers_from_ns=baseline_ns,
            as_of_ns=current_ns,
            scopes=scopes,
        )
        baseline_snapshot = ExecutionAccountSnapshot(
            account_key=account_key,
            source="synthetic-net-position-snapshot",
            source_ref="synthetic-two-owner-baseline-r1",
            generation=provider_generation,
            journal_generation=journal_generation,
            as_of_ns=baseline_ns,
            execution_cursor=self._baseline_execution_cursor,
            position_mode="NET",
            positions=(PositionFact(_INSTRUMENT, Decimal("3.0")),),
            cumulative_fees=(CurrencyAmount("USDT", Decimal("0")),),
            fee_coverage_start_ns=baseline_ns,
        )
        allocation_baseline = ExecutionAllocationBaseline(
            account_key=account_key,
            source="synthetic-trusted-strategy-ledger",
            source_ref="synthetic-two-owner-baseline-r1",
            revision="synthetic-two-owner-baseline-revision-r1",
            scope_directory_revision=directory_revision,
            provider_generation=provider_generation,
            journal_generation=journal_generation,
            as_of_ns=baseline_ns,
            execution_cursor=self._baseline_execution_cursor,
            positions=tuple(
                OwnerPosition(
                    AllocationOwnerKind.STRATEGY,
                    strategy_ref,
                    _INSTRUMENT,
                    _FINANCIAL_BASELINE_POSITION[strategy_ref],
                )
                for strategy_ref in (_STRATEGY_A, _STRATEGY_B)
            ),
        )
        activity = ExternalActivitySnapshot(
            account_key=account_key,
            source="synthetic-complete-provider-activity",
            source_ref="synthetic-two-owner-activity-r1",
            generation=provider_generation,
            coverage_start_ns=baseline_ns,
            coverage_end_ns=current_ns,
            fills=(),
            orders=(),
        )
        current_snapshot = ExecutionAccountSnapshot(
            account_key=account_key,
            source=baseline_snapshot.source,
            source_ref="synthetic-two-owner-current-r1",
            generation=provider_generation,
            journal_generation=journal_generation,
            as_of_ns=current_ns,
            execution_cursor=execution_cursor,
            position_mode="NET",
            positions=(PositionFact(_INSTRUMENT, Decimal("3.5")),),
            cumulative_fees=(CurrencyAmount("USDT", Decimal("0.03")),),
            fee_coverage_start_ns=baseline_ns,
        )
        return ExecutionAccountBookReadInputsV1(
            directory,
            baseline_snapshot,
            current_snapshot,
            allocation_baseline,
            activity,
        )


def _host_process(
    control, raw_config, registry_path: str, store_path: str, keys, seed_financial: bool
) -> None:
    from bt_api_execution import ExecutionScope, SqliteExecutionStore
    from bt_api_py.service_components import ComponentResources

    config = parse_service_config(raw_config)
    store = SqliteExecutionStore(store_path)
    execution_scopes = (
        ExecutionScope("PAPER", "simulation", _ACCOUNT, _STRATEGY_A, "20261015"),
        ExecutionScope("PAPER", "simulation", _ACCOUNT, _STRATEGY_B, "20261015"),
    )
    dispatch = _NoOrderDispatch()
    gate = _ClosedAdmissionGate()
    host = None
    try:
        if seed_financial:
            financial_directory = _seed_persisted_financial_projection(store, execution_scopes)
        else:
            financial_directory = _financial_owner_directory(execution_scopes)
            persisted = store.read_account_financial_projection(
                execution_scopes[0].account_key,
                expected_directory=financial_directory,
            )
            if not persisted.complete:
                raise AssertionError("reopened synthetic financial projection is incomplete")
        baseline_cursor, baseline_ns, baseline_generation = _stored_financial_execution_baseline(
            store, execution_scopes[0].account_key
        )
        source = _SyntheticOwnerFacts(
            execution_scopes,
            financial_directory,
            baseline_cursor,
            baseline_ns,
            baseline_generation,
        )
        authority = TrustedServiceAuthority(
            identity=WireIdentity(WireRole.SERVICE, _SERVICE_PRINCIPAL, _SERVICE_ID),
            scope=WireScope(_DOMAIN),
            scope_ref=config.scope_ref,
            scope_version="bt-multi-book-scope-v1",
            security_ref=_SERVER_SECURITY_REF,
            security_version="curve-key-v1",
            registration_policy_ref=config.registration_policy_ref,
            registration_policy_version="bt-multi-book-registration-v1",
            service_requirements_ref=config.service_requirements_ref,
            service_requirements_version="bt-multi-book-requirements-v1",
            curve_public_key=keys["server_public"],
            curve_secret_key=keys["server_secret"],
            principals={
                keys["client_a_public"]: _PRINCIPAL_A,
                keys["client_b_public"]: _PRINCIPAL_B,
            },
            grants={
                _PRINCIPAL_A: (
                    PrincipalGrant(
                        WireIdentity(WireRole.STRATEGY_CLIENT, _PRINCIPAL_A, _STRATEGY_A),
                        (
                            ResourceGrant(
                                _INSTANCE_ID,
                                "service.order_entry",
                                _ORDER_SCOPE_A,
                                _WIRE_SCOPE_A,
                                frozenset({"orders.submit", "orders.cancel"}),
                            ),
                            ResourceGrant(
                                _INSTANCE_ID,
                                "service.order_query",
                                _QUERY_SCOPE_A,
                                _WIRE_SCOPE_A,
                                frozenset({"orders.query", "execution.account_books.query"}),
                            ),
                        ),
                    ),
                ),
                _PRINCIPAL_B: (
                    PrincipalGrant(
                        WireIdentity(WireRole.STRATEGY_CLIENT, _PRINCIPAL_B, _STRATEGY_B),
                        (
                            ResourceGrant(
                                _INSTANCE_ID,
                                "service.order_query",
                                _QUERY_SCOPE_B,
                                _WIRE_SCOPE_B,
                                frozenset({"orders.query", "execution.account_books.query"}),
                            ),
                        ),
                    ),
                ),
            },
        )

        def resource_provider(component, instance_id, _options, _scope):
            if component != "execution" or instance_id != _INSTANCE_ID:
                raise AssertionError("unexpected service resource request")
            return ComponentResources.borrowed(
                {
                    "store": store,
                    "targets": {
                        _WIRE_SCOPE_A: execution_scopes[0],
                        _WIRE_SCOPE_B: execution_scopes[1],
                    },
                    "dispatch": dispatch,
                    "admission": {"order_gate": gate, "cancel_gate": gate},
                    "account_books": source,
                },
                ready=lambda: True,
            )

        host = ServiceHost(config, authority, registry_path, resource_provider)
        host.start()
        execution_changes_at_ready = store._connection.total_changes
        source_origins = _assert_source_origins(_loaded_source_origins())
        control.send(("ready", host.endpoint, host.state, source_origins))
        while True:
            host.serve_once(timeout_ms=20)
            if not control.poll():
                continue
            command = control.recv()
            if command == ("metrics",):
                control.send(
                    (
                        "metrics",
                        source.read_count,
                        source.financial_directory_read_count,
                        dispatch.submit_count,
                        dispatch.cancel_count,
                        store._connection.total_changes - execution_changes_at_ready,
                    )
                )
            elif command == ("close",):
                host.close()
                store.close()
                control.send(("closed", host.state))
                return
            else:
                raise AssertionError("unknown synthetic service-host command")
    except BaseException as error:
        if host is not None and host.state not in {"closed", "failed"}:
            with suppress(BaseException):
                host.close()
        with suppress(BaseException):
            store.close()
        with suppress(Exception):
            control.send(("host_error", getattr(error, "code", type(error).__name__)))
        raise
    finally:
        control.close()


def _receive(pipe, timeout: float = 20.0):
    if not pipe.poll(timeout):
        raise TimeoutError("timed out waiting for the synthetic ServiceHost")
    return pipe.recv()


def _start_host(tmp_path, *, seed_financial: bool):
    context = multiprocessing.get_context("spawn")
    endpoint = _endpoint()
    server_public, server_secret = zmq.curve_keypair()
    client_a_public, client_a_secret = zmq.curve_keypair()
    client_b_public, client_b_secret = zmq.curve_keypair()
    keys = {
        "server_public": server_public,
        "server_secret": server_secret,
        "client_a_public": client_a_public,
        "client_a_secret": client_a_secret,
        "client_b_public": client_b_public,
        "client_b_secret": client_b_secret,
    }
    parent_pipe, child_pipe = context.Pipe(duplex=True)
    process = context.Process(
        target=_host_process,
        args=(
            child_pipe,
            _service_config(endpoint),
            str(tmp_path / "multi-book-registry.sqlite3"),
            str(tmp_path / "multi-book-execution.sqlite3"),
            keys,
            seed_financial,
        ),
        name="bt-multi-strategy-account-book-service",
    )
    process.start()
    child_pipe.close()
    host = {"pipe": parent_pipe, "process": process, "forced_cleanup": False}
    try:
        ready = _receive(parent_pipe)
        if not isinstance(ready, tuple) or not ready or ready[0] != "ready":
            raise AssertionError(f"synthetic ServiceHost startup failed: {ready!r}")
        assert ready[1] == endpoint
        _assert_source_origins(ready[3])
        host["source_origins"] = ready[3]
        _report_source_origins("spawned ServiceHost", ready[3])
    except BaseException:
        _close_host(host, require_normal=False)
        raise
    return endpoint, keys, host


def _close_host(host, *, require_normal: bool) -> None:
    pipe = host["pipe"]
    process = host["process"]
    close_reply = None
    close_error = None
    process_exitcode = None
    try:
        if not pipe.closed and process.is_alive():
            pipe.send(("close",))
            close_reply = _receive(pipe, timeout=20.0)
    except BaseException as error:
        close_error = error
    finally:
        process.join(20)
        if process.is_alive():
            host["forced_cleanup"] = True
            process.terminate()
            process.join(5)
        if process.is_alive():
            host["forced_cleanup"] = True
            process.kill()
            process.join(5)
        if not process.is_alive():
            process_exitcode = process.exitcode
        if not pipe.closed:
            pipe.close()
        if not process.is_alive():
            process.close()
    if require_normal:
        if close_error is not None:
            raise AssertionError("synthetic ServiceHost normal close failed") from close_error
        assert close_reply == ("closed", "closed"), (
            "synthetic ServiceHost did not confirm normal close",
            close_reply,
        )
        assert process_exitcode == 0
        assert host["forced_cleanup"] is False


def _scope_resolver(strategy_ref: str, query_scope_ref: str, order_scope_ref: str | None = None):
    scopes = {query_scope_ref: WireScope(_DOMAIN, account_ref=_ACCOUNT, strategy_ref=strategy_ref)}
    if order_scope_ref is not None:
        scopes[order_scope_ref] = WireScope(
            _DOMAIN, account_ref=_ACCOUNT, strategy_ref=strategy_ref
        )
    return scopes


def _client_runtime(endpoint, keys, *, strategy_ref, principal, client_suffix, scopes):
    client_public = keys[f"client_{client_suffix}_public"]
    client_secret = keys[f"client_{client_suffix}_secret"]
    config = parse_client_config(
        _client_config(
            endpoint,
            strategy_ref=strategy_ref,
            include_writer=client_suffix == "a",
            order_scope_ref=_ORDER_SCOPE_A if client_suffix == "a" else None,
            query_scope_ref=_QUERY_SCOPE_A if client_suffix == "a" else _QUERY_SCOPE_B,
        )
    )
    requested_operations = {
        "broker.order_query": frozenset({"orders.query", "execution.account_books.query"})
    }
    if client_suffix == "a":
        requested_operations["broker.orders"] = frozenset({"orders.submit", "orders.cancel"})
    return ServiceClientRuntime(
        config,
        identity=WireIdentity(WireRole.STRATEGY_CLIENT, principal, strategy_ref),
        run_id=f"bt-multi-book-{strategy_ref}-same-run-r1",
        scope_resolver=scopes.__getitem__,
        peer_resolver=lambda _service_id: WireIdentity(
            WireRole.SERVICE, _SERVICE_PRINCIPAL, _SERVICE_ID
        ),
        transport_factory=ZmqTransportFactory(
            {
                _CLIENT_SECURITY_REF: ClientCurveKeys(
                    keys["server_public"], client_public, client_secret
                )
            }
        ),
        requested_operations=requested_operations,
    )


class _AccountBookStrategy(bt.Strategy):
    params = (
        ("strategy_ref", None),
        ("account_ref", None),
        ("risk_budget", None),
        ("attempt_order", False),
    )

    def start(self):
        self.rejected_order = None
        self._order_attempted = False
        self.correct_binding = self.broker.bind_strategy_account_book(
            self,
            strategy_ref=self.p.strategy_ref,
            account_ref=self.p.account_ref,
        )
        try:
            self.broker.get_strategy_account_book_view(
                strategy_ref=self.p.strategy_ref,
                account_ref="account.untrusted-route",
            )
        except ServiceExecutionSessionConfigError as error:
            self.wrong_account_route_code = error.code
        else:  # pragma: no cover - a missing account route must fail locally
            self.wrong_account_route_code = "unexpectedly_available"
        self.wrong_strategy_binding_code = None
        if self.p.strategy_ref == _STRATEGY_B:
            try:
                self.broker.bind_strategy_account_book(
                    self,
                    strategy_ref=_STRATEGY_A,
                    account_ref=_ACCOUNT,
                )
            except ServiceExecutionSessionConfigError as error:
                self.wrong_strategy_binding_code = error.code

    def next(self):
        snapshot = self.account_book.snapshot()
        book_position = self.account_book.getposition(self.data)
        try:
            self.account_book.getcash()
        except ServiceStrategyAccountBookError as error:
            cash_error = error.code
        else:  # pragma: no cover - this contract has no cash
            cash_error = "unexpectedly_available"
        try:
            self.account_book.getvalue()
        except ServiceStrategyAccountBookError as error:
            value_error = error.code
        else:  # pragma: no cover - this contract has no valuation basis
            value_error = "unexpectedly_available"
        self.account_observation = {
            "snapshot": snapshot,
            "book_position": book_position,
            "cash_error": cash_error,
            "cash": self.account_book.getcash(currency="USDT"),
            "cumulative_fees": snapshot.cumulative_fees_by_currency,
            "position_cost": snapshot.position_costs.get(_INSTRUMENT),
            "financial_source": snapshot.financial_source,
            "financial_freshness": snapshot.financial_freshness,
            "financial_cut_relationship": snapshot.financial_cut_relationship,
            "financial_ledger_cut": snapshot.financial_ledger_cut,
            "value_error": value_error,
            "account_cash": self.broker.getcash(),
            "account_value": self.broker.getvalue(),
            "account_position": self.broker.getposition(self.data),
            "risk_budget": self.p.risk_budget,
        }
        if self.p.attempt_order and not self._order_attempted:
            self._order_attempted = True
            self.rejected_order = self.buy(data=self.data, size=1.0)


class _DuplicateIdentityStrategy(bt.Strategy):
    params = (("strategy_ref", _STRATEGY_A), ("account_ref", _ACCOUNT))

    def start(self):
        self.account_book = self.broker.get_strategy_account_book_view(
            strategy_ref=self.p.strategy_ref,
            account_ref=self.p.account_ref,
        )
        try:
            self.broker.bind_strategy_account_book(
                self,
                strategy_ref=self.p.strategy_ref,
                account_ref=self.p.account_ref,
            )
        except ServiceExecutionSessionConfigError as error:
            self.duplicate_identity_code = error.code
        else:  # pragma: no cover - a bound route cannot be shared by two instances
            self.duplicate_identity_code = "unexpectedly_available"
        self.rejected_order = None
        self._order_attempted = False

    def next(self):
        if not self._order_attempted:
            self._order_attempted = True
            self.rejected_order = self.buy(data=self.data, size=1.0)


def _cerebro(broker):
    frame = pandas.DataFrame(
        {
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1.0],
            "openinterest": [0.0],
        },
        index=[dt.datetime(2026, 10, 16)],
    )
    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    cerebro.setbroker(broker)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame), name=_INSTRUMENT)
    cerebro.addstrategy(
        _AccountBookStrategy,
        strategy_ref=_STRATEGY_A,
        account_ref=_ACCOUNT,
        risk_budget=9_999_999.0,
    )
    cerebro.addstrategy(
        _AccountBookStrategy,
        strategy_ref=_STRATEGY_B,
        account_ref=_ACCOUNT,
        risk_budget=8_888_888.0,
        attempt_order=True,
    )
    cerebro.addstrategy(_DuplicateIdentityStrategy)
    return cerebro


def _run_two_strategy_cerebro(endpoint, keys):
    primary_runtime = None
    second_runtime = None
    store = None
    try:
        primary_runtime = _client_runtime(
            endpoint,
            keys,
            strategy_ref=_STRATEGY_A,
            principal=_PRINCIPAL_A,
            client_suffix="a",
            scopes=_scope_resolver(_STRATEGY_A, _QUERY_SCOPE_A, _ORDER_SCOPE_A),
        )
        second_runtime = _client_runtime(
            endpoint,
            keys,
            strategy_ref=_STRATEGY_B,
            principal=_PRINCIPAL_B,
            client_suffix="b",
            scopes=_scope_resolver(_STRATEGY_B, _QUERY_SCOPE_B),
        )
        _report_source_origins(
            "Cerebro client process",
            _assert_source_origins(_loaded_source_origins()),
        )
        store = make_store(
            api=FakeBtApiClient(
                balance={"cash": 12_345.0, "value": 54_321.0},
                positions=[{"instrument": _INSTRUMENT, "volume": 9.0, "price": 77.0}],
            ),
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
            primary_runtime,
            mount="broker.orders",
            scope_ref=_ORDER_SCOPE_A,
            query_mount="broker.order_query",
            query_scope_ref=_QUERY_SCOPE_A,
            strategy_account_book_routes=(
                ServiceStrategyAccountBookRoute(
                    strategy_ref=_STRATEGY_B,
                    account_ref=_ACCOUNT,
                    runtime=second_runtime,
                    mount="broker.order_query",
                    scope_ref=_QUERY_SCOPE_B,
                    owned=True,
                ),
            ),
        )

        strategies = session.run(_cerebro(broker))
        return strategies, session, broker
    finally:
        if store is not None and store.is_connected:
            with suppress(Exception):
                store.stop()
        for runtime in (second_runtime, primary_runtime):
            if runtime is not None and runtime.state not in {"closed", "failed"}:
                with suppress(Exception):
                    runtime.close()


def _assert_two_owner_cerebro_result(strategies, session, broker):
    assert session.state == "closed"
    assert session.cleanup_report.errors == ()
    assert session.cleanup_report.store_connected is False
    assert session.cleanup_report.runtime_state == "closed"
    assert len(strategies) == 3
    alpha, beta, duplicate = strategies
    assert alpha.broker is beta.broker is duplicate.broker is broker
    assert alpha.correct_binding is alpha.account_book
    assert beta.correct_binding is beta.account_book
    assert alpha.account_book.strategy_ref == _STRATEGY_A
    assert beta.account_book.strategy_ref == _STRATEGY_B
    with pytest.raises(AttributeError, match="immutable"):
        beta.account_book.strategy_ref = _STRATEGY_A

    signatures = []
    for strategy, expected_ref in ((alpha, _STRATEGY_A), (beta, _STRATEGY_B)):
        expected_quantity = _FINANCIAL_POSITION_AFTER_FILL[expected_ref]
        expected_cost = _FINANCIAL_COST_AFTER_FILL[expected_ref]
        observation = strategy.account_observation
        snapshot = observation["snapshot"]
        assert strategy.wrong_account_route_code == "ACCOUNT_BOOK_ROUTE_UNAVAILABLE"
        assert snapshot.strategy_ref == expected_ref
        assert snapshot.account_ref == _ACCOUNT
        assert snapshot.positions == {_INSTRUMENT: expected_quantity}
        assert snapshot.financial_available is True
        assert snapshot.cost_basis_complete is True
        assert snapshot.financial_source == "PERSISTED_EXECUTION_FINANCIAL_PROJECTION"
        assert snapshot.financial_freshness == "PERSISTED_CUT_NOT_LIVE_SOURCE_VERIFIED"
        assert snapshot.financial_cut_relationship == "INDEPENDENT_OF_LEGACY_ACCOUNT_BOOK_CUT"
        assert snapshot.financial_ledger_cut is not None
        assert snapshot.financial_ledger_cut.account_key != _ACCOUNT
        assert observation["book_position"].size == pytest.approx(float(expected_quantity))
        assert observation["book_position"].price == pytest.approx(
            float(expected_cost / expected_quantity)
        )
        assert observation["cash_error"] == "STRATEGY_CASH_CURRENCY_REQUIRED"
        assert observation["cash"] == _FINANCIAL_CASH_AFTER_FILL[expected_ref]
        assert observation["cumulative_fees"] == {"USDT": _FINANCIAL_FEES_AFTER_FILL[expected_ref]}
        assert observation["position_cost"].cost_basis == expected_cost
        assert observation["position_cost"].cost_currency == "USDT"
        assert observation["position_cost"].product_model == "SPOT"
        assert observation["position_cost"].metadata_version == _FINANCIAL_METADATA_VERSION
        assert observation["financial_source"] == "PERSISTED_EXECUTION_FINANCIAL_PROJECTION"
        assert observation["financial_freshness"] == "PERSISTED_CUT_NOT_LIVE_SOURCE_VERIFIED"
        assert observation["financial_cut_relationship"] == "INDEPENDENT_OF_LEGACY_ACCOUNT_BOOK_CUT"
        assert observation["financial_ledger_cut"].watermarks
        assert observation["value_error"] == "STRATEGY_VALUE_UNAVAILABLE"
        assert observation["account_cash"] == pytest.approx(12_345.0)
        assert observation["account_value"] == pytest.approx(54_321.0)
        assert observation["account_position"].size == pytest.approx(9.0)
        assert observation["risk_budget"] > observation["account_cash"]
        signatures.append(
            (
                snapshot.positions,
                snapshot.cash_by_currency,
                snapshot.position_costs,
                snapshot.cumulative_fees_by_currency,
                snapshot.current_execution_cursor,
                snapshot.financial_ledger_cut,
                observation["book_position"].size,
                observation["book_position"].price,
            )
        )

    assert beta.wrong_strategy_binding_code == "STRATEGY_IDENTITY_MISMATCH"
    assert beta.rejected_order is not None
    assert beta.rejected_order.getstatusname() == "Rejected"
    assert beta.rejected_order.info.error_code == "strategy_writer_route_mismatch"
    assert duplicate.duplicate_identity_code == "STRATEGY_ROUTE_ALREADY_BOUND"
    assert duplicate.rejected_order is not None
    assert duplicate.rejected_order.getstatusname() == "Rejected"
    assert duplicate.rejected_order.info.error_code == "strategy_writer_strategy_not_bound"
    return tuple(signatures)


def _host_metrics(host):
    host["pipe"].send(("metrics",))
    return _receive(host["pipe"])


def test_two_strategies_bind_distinct_read_books_on_one_shared_broker(tmp_path):
    endpoint, keys, host = _start_host(tmp_path, seed_financial=True)
    try:
        before = _host_metrics(host)
        assert before == ("metrics", 0, 0, 0, 0, 0)
        first_strategies, first_session, first_broker = _run_two_strategy_cerebro(endpoint, keys)
        first_signature = _assert_two_owner_cerebro_result(
            first_strategies, first_session, first_broker
        )
        first_metrics = _host_metrics(host)
        assert first_metrics == ("metrics", 6, 6, 0, 0, 0)
    finally:
        _close_host(host, require_normal=True)

    database_path = tmp_path / "multi-book-execution.sqlite3"
    persisted_rows_before_restart = _financial_database_state(database_path)
    assert persisted_rows_before_restart[1] == 1
    assert persisted_rows_before_restart[2] >= 1
    assert persisted_rows_before_restart[3] is not None

    endpoint, keys, reopened_host = _start_host(tmp_path, seed_financial=False)
    try:
        before = _host_metrics(reopened_host)
        assert before == ("metrics", 0, 0, 0, 0, 0)
        second_strategies, second_session, second_broker = _run_two_strategy_cerebro(endpoint, keys)
        second_signature = _assert_two_owner_cerebro_result(
            second_strategies, second_session, second_broker
        )
        reopened_metrics = _host_metrics(reopened_host)
        assert reopened_metrics == ("metrics", 6, 6, 0, 0, 0)
    finally:
        _close_host(reopened_host, require_normal=True)

    persisted_rows_after_restart = _financial_database_state(database_path)
    assert persisted_rows_after_restart == persisted_rows_before_restart
    assert second_signature == first_signature


def test_preflight_empty_run_and_refresh_setup_release_owned_runtime_claims(monkeypatch):
    endpoint = _endpoint()
    server_public, _server_secret = zmq.curve_keypair()
    client_a_public, client_a_secret = zmq.curve_keypair()
    client_b_public, client_b_secret = zmq.curve_keypair()
    keys = {
        "server_public": server_public,
        "client_a_public": client_a_public,
        "client_a_secret": client_a_secret,
        "client_b_public": client_b_public,
        "client_b_secret": client_b_secret,
    }
    primary_runtime = _client_runtime(
        endpoint,
        keys,
        strategy_ref=_STRATEGY_A,
        principal=_PRINCIPAL_A,
        client_suffix="a",
        scopes=_scope_resolver(_STRATEGY_A, _QUERY_SCOPE_A, _ORDER_SCOPE_A),
    )
    second_runtime = _client_runtime(
        endpoint,
        keys,
        strategy_ref=_STRATEGY_B,
        principal=_PRINCIPAL_B,
        client_suffix="b",
        scopes=_scope_resolver(_STRATEGY_B, _QUERY_SCOPE_B),
    )

    def make_session():
        return ServiceExecutionSession(
            primary_runtime,
            mount="broker.orders",
            scope_ref=_ORDER_SCOPE_A,
            query_mount="broker.order_query",
            query_scope_ref=_QUERY_SCOPE_A,
            strategy_account_book_routes=(
                ServiceStrategyAccountBookRoute(
                    strategy_ref=_STRATEGY_B,
                    account_ref=_ACCOUNT,
                    runtime=second_runtime,
                    mount="broker.order_query",
                    scope_ref=_QUERY_SCOPE_B,
                    owned=True,
                ),
            ),
        )

    session = make_session()
    with pytest.raises(ServiceExecutionSessionConfigError, match="INVALID_BROKER"):
        session.run(bt.Cerebro())
    assert session.cleanup_report.runtime_close_attempted is False
    assert primary_runtime.state == second_runtime.state == "new"

    # Construction with the same owned runtimes proves the rejected preflight
    # released both ownership fences without starting or closing either one.
    empty_session = make_session()
    store = make_store(api=FakeBtApiClient(), provider="btapi")
    broker = store.getbroker()
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.setbroker(broker)
    assert empty_session.run(cerebro) == []
    assert empty_session.state == "closed_unstarted"
    assert empty_session.cleanup_report.runtime_close_attempted is False
    assert primary_runtime.state == second_runtime.state == "new"

    # The no-data return also relinquishes ownership, so a further caller can
    # make a fresh decision with those still-new runtimes.
    final_session = make_session()
    with pytest.raises(ServiceExecutionSessionConfigError, match="INVALID_BROKER"):
        final_session.run(bt.Cerebro())
    assert primary_runtime.state == second_runtime.state == "new"

    refresh_session = make_session()
    valid_store = make_store(api=FakeBtApiClient(), provider="btapi")
    valid_broker = valid_store.getbroker()
    original_import = __import__

    def fail_refresh_loop_import(name, *args, **kwargs):
        if name == "backtrader.stores.service_refresh_loop":
            raise ImportError("synthetic refresh-loop import failure")
        return original_import(name, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr("builtins.__import__", fail_refresh_loop_import)
        with pytest.raises(ImportError, match="synthetic refresh-loop import failure"):
            refresh_session.run(_cerebro(valid_broker))
    assert refresh_session.state == "rejected"
    assert refresh_session.cleanup_report.errors[0] == "REFRESH_LOOP_SETUP_FAILED"
    assert refresh_session.cleanup_report.runtime_close_attempted is False
    assert primary_runtime.state == second_runtime.state == "new"

    replacement_session = make_session()
    with pytest.raises(ServiceExecutionSessionConfigError, match="INVALID_BROKER"):
        replacement_session.run(bt.Cerebro())
    assert primary_runtime.state == second_runtime.state == "new"
    with suppress(Exception):
        primary_runtime.close()
    with suppress(Exception):
        second_runtime.close()
