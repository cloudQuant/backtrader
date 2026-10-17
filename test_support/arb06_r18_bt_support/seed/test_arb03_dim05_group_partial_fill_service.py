"""Fixed-source integration test for ARB03/DIM05 group semantics.

ARB03 — a first-leg IOC remainder cancel after a strictly positive partial
fill, followed by a rejected hedge leg, must settle as RECOVERY_REQUIRED with
the exact residual base units and the ``hedge_residual_unresolved`` error.

DIM05 — one account may own both legs on two different contracts of the same
underlying (spot and perp): the first-leg partial fill sizes the hedge on the
second contract, and the group keeps exactly one account reservation.

The tests use spawned CURVE hosts (two accounts for ARB03, one for DIM05) and
the normal upstream/client registration paths. Provider leaves are synthetic
SQLite-backed fixtures; the tests do not load credentials or contact an
exchange. The old-contract exit/roll path is not expressible through the
coordinator contract (group legs are OPEN-effect IOC only), so it is reported
as a gap rather than simulated.
"""

from __future__ import annotations

import multiprocessing
import socket
import sqlite3
import time
from collections.abc import Mapping
from contextlib import suppress
from decimal import Decimal
from functools import partial
from pathlib import Path
from types import MappingProxyType
from typing import Any

import zmq
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_execution import (
    AccountScopedGroupAdmissionAdapter,
    ExecutionScope,
    ExecutionState,
    GroupOrderSnapshot,
    GroupOrderState,
    OrderIntent,
    OrderType,
    PortfolioGroupBudgetPolicy,
    Side,
    SqliteExecutionStore,
    SqliteOrderGroupStore,
    TimeInForce,
    build_instrument_risk_group_budget_quote,
    group_leg_intent_id,
    risk_account_scope_fingerprint,
)
from bt_api_execution import GroupReservationPhase  # R3 additive import for zero/full/hedge-partial nodes
from bt_api_risk import (
    INSTRUMENT_METADATA_DIGEST_TAG,
    AccountScope,
    DispatchEvidenceClass,
    DurableRiskAdmissionAdapter,
    DurableRiskGate,
    ExposureAccountingMode,
    InstrumentRiskAdmissionMapper,
    InstrumentRiskMetadata,
    InstrumentRiskRegistry,
    RiskPolicy,
)

from bt_api_py.bt_api import BtApi
from bt_api_py.service_components import ComponentResources
from bt_api_py.service_config import parse_client_config, parse_service_config
from bt_api_py.service_execution_group import (
    GroupAccountRoute,
    GroupCoordinatorTarget,
    GroupInstrumentRule,
)
from bt_api_py.service_execution_group_authority import (
    ExecutionGroupAuthority,
    ExecutionStoreGroupCompletionVerifier,
)
from bt_api_py.service_execution_group_client import (
    AcceptedGroupBindingStore,
    GroupOriginRunBindingStore,
)
from bt_api_py.service_execution_group_proofs import (
    GroupProofJournal,
    GroupProofRuntimeBundle,
    GroupProofSource,
    GroupProofTarget,
)
from bt_api_py.service_execution_group_proofs import (
    GroupReservationTarget as ProofReservationTarget,
)
from bt_api_py.service_host import (
    ServiceHost,
    TrustedServiceAuthority,
    TrustedServiceClients,
)
from bt_api_py.service_registry import (
    PrincipalGrant,
    ResourceGrant,
    TrustedGroupReservationPolicy,
    TrustedGroupResolutionPolicy,
    TrustedGroupWritePolicy,
)
from bt_api_py.service_risk_order_entry import RiskBtApiProviderContract, RiskOrderTarget
from bt_api_py.service_risk_order_journal import RiskOrderJournal
from bt_api_py.service_runtime import (
    ClientCurveKeys,
    ServiceClientRuntime,
    ZmqTransportFactory,
)
from tests.unit._service_group_provider_fixtures import (
    _V2_FILL_SCHEMA,
    _V2_INSTRUMENT,
    _V2_METADATA_VERSION,
    _V2_ORDER_SCHEMA,
    _V2SyntheticBtApiFeed,
)

_DOMAIN = "paper:group-partial-fill"
_STRATEGY = "strategy-group-partial-fill"
_RUN = "run-group-partial-fill-001"
_PORTFOLIO = "portfolio-group-partial-fill"
_ARB03_ACCOUNTS = ("account-a", "account-b")
_DIM05_ACCOUNTS = ("account-a",)
_PERP_INSTRUMENT = "BTC-USD-PERP"
_COORDINATOR_SERVICE_ID = "group-coordinator-service"
_COORDINATOR_INSTANCE_ID = "group-coordinator"
_COORDINATOR_PRINCIPAL = "group-coordinator-principal"
_STRATEGY_PRINCIPAL = "group-strategy-principal"
_COORDINATOR_SCOPE_REF = "group-strategy-route-v1"
_MAX_MESSAGE_BYTES = 65_536
_REQUEST_TIMEOUT_MS = 5_000
_SERVER_OPTIONS = {"high_water_mark": 32, "max_message_bytes": _MAX_MESSAGE_BYTES}
_GROUP_ARB03 = "group-arb03-partial-cancel-01"
_GROUP_DIM05 = "group-dim05-dual-contract-02"
# R3 additive scenario IDs (first-leg zero/full fill, hedge-leg partial cancel).
_GROUP_ARB03_NO_FILL = "group-arb03-first-leg-no-fill-03"
_GROUP_ARB03_FULL_FILL = "group-arb03-first-leg-full-fill-04"
_GROUP_ARB03_HEDGE_PARTIAL = "group-arb03-hedge-partial-cancel-05"


def _endpoint() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"tcp://127.0.0.1:{port}"


def _component(
    instance_id: str,
    ports: tuple[str, ...],
    role: str,
    *,
    portfolio_ref: str | None = None,
) -> dict[str, Any]:
    options: dict[str, Any] = {"role": role}
    if portfolio_ref is not None:
        options["portfolio_ref"] = portfolio_ref
    return {
        "config_schema_version": 2,
        "settings": {
            "instance_id": instance_id,
            "bind_ports": list(ports),
            "options": options,
        },
    }


def _profile(endpoint: str, *, server: bool, security_ref: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "backend": "zmq",
        "config_schema_version": 1,
        "endpoints": {"rpc_bind" if server else "rpc_connect": endpoint},
        "security_profile_ref": security_ref,
        "options": dict(_SERVER_OPTIONS),
    }
    if not server:
        result["options"]["request_timeout_ms"] = _REQUEST_TIMEOUT_MS
    return result


def _account_service_config(
    account_ref: str, endpoint: str, server_security_ref: str
) -> dict[str, Any]:
    return {
        "service_config_schema_version": 1,
        "process_role": "service",
        "service_id": f"group-owner-service-{account_ref}",
        "scope_ref": f"group-owner-root-{account_ref}",
        "transport_ref": "listener-v1",
        "registration_policy_ref": "group-registration-policy-v1",
        "service_requirements_ref": "group-service-requirements-v1",
        "components": {
            "execution": _component(
                f"group-execution-owner-{account_ref}",
                ("service.order_entry", "service.order_query"),
                "group_account_owner",
            ),
            "risk": _component(
                f"group-risk-reservations-{account_ref}",
                ("service.group_reservations",),
                "group_reservations",
            ),
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                "listener-v1": _profile(endpoint, server=True, security_ref=server_security_ref)
            },
        },
    }


def _route_refs(account_ref: str) -> tuple[str, str, str]:
    return (
        f"reservation-route-{account_ref}",
        f"order-entry-route-{account_ref}",
        f"order-query-route-{account_ref}",
    )


def _coordinator_service_config(
    endpoint: str,
    server_security_ref: str,
    account_configs: dict[str, dict[str, Any]],
    account_endpoints: dict[str, str],
    accounts: tuple[str, ...],
) -> dict[str, Any]:
    execution_bindings: list[dict[str, Any]] = []
    risk_bindings: list[dict[str, Any]] = []
    profiles: dict[str, dict[str, Any]] = {
        "listener-v1": _profile(endpoint, server=True, security_ref=server_security_ref)
    }
    for account_ref in accounts:
        account_service_id = account_configs[account_ref]["service_id"]
        account_execution = account_configs[account_ref]["components"]["execution"]["settings"]
        account_risk = account_configs[account_ref]["components"]["risk"]["settings"]
        account_security_ref = f"coordinator-client-security-{account_ref}"
        transport_ref = f"coordinator-client-{account_ref}"
        profiles[transport_ref] = _profile(
            account_endpoints[account_ref],
            server=False,
            security_ref=account_security_ref,
        )
        reservation_ref, order_ref, query_ref = _route_refs(account_ref)
        execution_bindings.extend(
            (
                {
                    "mount": "upstream.orders",
                    "service_id": account_service_id,
                    "instance_id": account_execution["instance_id"],
                    "scope_ref": order_ref,
                    "account_ref": account_ref,
                    "transport_ref": transport_ref,
                },
                {
                    "mount": "upstream.order_query",
                    "service_id": account_service_id,
                    "instance_id": account_execution["instance_id"],
                    "scope_ref": query_ref,
                    "account_ref": account_ref,
                    "transport_ref": transport_ref,
                },
            )
        )
        risk_bindings.append(
            {
                "mount": "upstream.account_reservations",
                "service_id": account_service_id,
                "instance_id": account_risk["instance_id"],
                "scope_ref": reservation_ref,
                "account_ref": account_ref,
                "transport_ref": transport_ref,
            }
        )

    def client_block(bindings: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "config_schema_version": 1,
            "settings": {
                "bindings": bindings,
                "options": {
                    "request_timeout_ms": _REQUEST_TIMEOUT_MS,
                    "heartbeat_interval_seconds": 5,
                },
            },
        }

    return {
        "service_config_schema_version": 1,
        "process_role": "service",
        "service_id": _COORDINATOR_SERVICE_ID,
        "scope_ref": "group-coordinator-root",
        "transport_ref": "listener-v1",
        "registration_policy_ref": "group-coordinator-registration-v1",
        "service_requirements_ref": "group-coordinator-requirements-v1",
        "components": {
            "execution": _component(
                _COORDINATOR_INSTANCE_ID,
                ("service.order_group_entry",),
                "group_coordinator",
                portfolio_ref=_PORTFOLIO,
            )
        },
        "clients": {
            "execution": client_block(execution_bindings),
            "risk": client_block(risk_bindings),
        },
        "communication": {"config_schema_version": 1, "profiles": profiles},
    }


def _strategy_client_config(endpoint: str, server_security_ref: str) -> dict[str, Any]:
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
                            "mount": "broker.order_groups",
                            "service_id": _COORDINATOR_SERVICE_ID,
                            "instance_id": _COORDINATOR_INSTANCE_ID,
                            "scope_ref": _COORDINATOR_SCOPE_REF,
                            "portfolio_ref": _PORTFOLIO,
                            "transport_ref": "strategy-client-v1",
                        }
                    ],
                    "options": {
                        "request_timeout_ms": _REQUEST_TIMEOUT_MS,
                        "heartbeat_interval_seconds": 5,
                    },
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                "strategy-client-v1": _profile(
                    endpoint, server=False, security_ref=server_security_ref
                )
            },
        },
    }


def _stable_strategy_scope(accounts: tuple[str, ...]) -> WireScope:
    return WireScope(
        _DOMAIN,
        account_refs=accounts,
        strategy_ref=_STRATEGY,
        portfolio_ref=_PORTFOLIO,
    )


def _owner_scope(account_ref: str) -> WireScope:
    return WireScope(
        _DOMAIN,
        account_ref=account_ref,
        strategy_ref=_STRATEGY,
        portfolio_ref=_PORTFOLIO,
    )


def _execution_scope(account_ref: str) -> ExecutionScope:
    return ExecutionScope("fixture", "simulation", account_ref, _STRATEGY, "20261016")


def _metadata(instrument: str, reference_ns: int) -> InstrumentRiskMetadata:
    return InstrumentRiskMetadata(
        instrument=instrument,
        metadata_version=_V2_METADATA_VERSION,
        as_of_ns=reference_ns - 1_000_000_000,
        expires_at_ns=reference_ns + 3_600_000_000_000,
        tick_size=Decimal("0.01"),
        quantity_step=Decimal("0.001"),
        contract_multiplier=Decimal("1"),
        max_gross_notional=Decimal("100000"),
        taker_fee_bps=Decimal("0"),
        fixed_fee=Decimal("0"),
        max_slippage_bps=Decimal("0"),
        quantity_unit="base",
        valuation_unit="USD",
    )


def _budget_binding(
    metadatas: tuple[InstrumentRiskMetadata, ...],
) -> tuple[PortfolioGroupBudgetPolicy, object]:
    policy = PortfolioGroupBudgetPolicy(
        portfolio_ref=_PORTFOLIO,
        policy_id="group-partial-fill-budget-v1",
        policy_version=1,
        valuation_unit="USD",
        max_group_gross_notional=Decimal("1000000"),
        max_active_gross_notional=Decimal("10000000"),
        max_active_groups=100,
    )
    builder = partial(
        build_instrument_risk_group_budget_quote,
        registry=InstrumentRiskRegistry(metadatas),
    )
    return policy, builder


def _risk_policy() -> RiskPolicy:
    return RiskPolicy(
        "service-group-risk-policy-v1",
        Decimal("100000"),
        max_increase_count=10,
        permit_ttl_seconds=240,
        require_strategy_allocation=False,
        notional_unit="USD",
        exposure_accounting_mode=ExposureAccountingMode.RESERVATIONS_ONLY,
    )


class _InstrumentMappedV2SyntheticFeed(_V2SyntheticBtApiFeed):
    """Check the real DirectBackend mapper arguments before the fake leaf write."""

    def __init__(
        self,
        ledger_path: str,
        initial_states: tuple[str, ...],
        provider_account: str,
        expected_orders: tuple[tuple[str, str, str, str], ...],
    ) -> None:
        super().__init__(ledger_path, initial_states, provider_account)
        self._expected_orders: list[tuple[str, str, str, str]] = list(expected_orders)

    def remaining(self) -> tuple[tuple[str, str, str, str], ...]:
        return tuple(self._expected_orders)

    def make_order(
        self,
        symbol: str,
        volume: float,
        price: float,
        order_type: str,
        *,
        client_order_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        assert self._expected_orders, f"unexpected provider write for {symbol}"
        expected_symbol, expected_volume, expected_price, expected_type = (
            self._expected_orders.pop(0)
        )
        assert symbol == expected_symbol
        assert Decimal(str(volume)) == Decimal(expected_volume)
        assert Decimal(str(price)) == Decimal(expected_price)
        assert order_type == expected_type
        assert client_order_id.startswith("grp-") and len(client_order_id) == 44
        assert kwargs == {
            "offset": "open",
            "post_only": False,
            "reduce_only": False,
            "time_in_force": "IOC",
        }
        return super().make_order(
            symbol,
            volume,
            price,
            order_type,
            client_order_id=client_order_id,
            **kwargs,
        )


class _UnusedExecutionDispatch:
    """Group proof sessions must own all provider writes."""

    def submit(self, _intent: OrderIntent) -> object:
        raise AssertionError("ordinary dispatcher bypassed the group proof session")

    def cancel(self, _intent: object) -> object:
        raise AssertionError("group-only owner must not dispatch cancellation")


class _AccountResourceGraph:
    def __init__(
        self,
        *,
        bt_api: BtApi,
        execution_store: SqliteExecutionStore,
        proof_journal: GroupProofJournal,
        risk_gate: DurableRiskGate,
        accepted_store: AcceptedGroupBindingStore,
        authority: ExecutionGroupAuthority,
        provider: _InstrumentMappedV2SyntheticFeed,
        risk_scope: AccountScope,
        execution_scope: ExecutionScope,
        owner_scope: WireScope,
        risk_admission: DurableRiskAdmissionAdapter,
        account_admission: AccountScopedGroupAdmissionAdapter,
        bundle: GroupProofRuntimeBundle,
    ) -> None:
        self.bt_api = bt_api
        self.execution_store = execution_store
        self.proof_journal = proof_journal
        self.risk_gate = risk_gate
        self.accepted_store = accepted_store
        self.authority = authority
        self.provider = provider
        self.risk_scope = risk_scope
        self.execution_scope = execution_scope
        self.owner_scope = owner_scope
        self.risk_admission = risk_admission
        self.account_admission = account_admission
        self.bundle = bundle
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        failures: list[BaseException] = []
        for close in (
            self.authority.close,
            self.accepted_store.close,
            self.risk_gate.close,
            self.proof_journal.close,
            self.execution_store.close,
            self.bt_api.close,
        ):
            try:
                close()
            except BaseException as error:
                failures.append(error)
        if failures:
            raise RuntimeError("synthetic account resource close failed") from failures[0]


def _new_account_resource_graph(
    account_ref: str,
    paths: dict[str, str],
    initial_states: tuple[str, ...],
    metadata_reference_ns: int,
    instruments: tuple[str, ...],
    expected_orders: tuple[tuple[str, str, str, str], ...],
) -> _AccountResourceGraph:
    provider_account = f"provider-{account_ref}"
    provider = _InstrumentMappedV2SyntheticFeed(
        paths["provider"], initial_states, provider_account, expected_orders
    )

    from bt_api_py._venue_mappers import MAPPERS

    MAPPERS["FIXTURE___SPOT"] = MAPPERS["BINANCE___SPOT"]

    bt_api = BtApi(debug=False)
    bt_api.exchange_feeds["FIXTURE___SPOT"] = provider
    execution_scope = _execution_scope(account_ref)
    owner_scope = _owner_scope(account_ref)
    risk_scope = AccountScope("fixture", provider_account, "simulation")
    metadatas = tuple(_metadata(instrument, metadata_reference_ns) for instrument in instruments)
    registry = InstrumentRiskRegistry(metadatas)
    risk_target = RiskOrderTarget(
        account_scope=risk_scope,
        strategy_id=_STRATEGY,
        exchange_name="FIXTURE___SPOT",
        provider_account_id=provider_account,
        registry=registry,
    )
    execution_store = SqliteExecutionStore(paths["execution"])
    risk_order_journal = RiskOrderJournal(
        paths["risk_order_journal"], writer_id=f"group-risk-order-{account_ref}"
    )
    proof_journal = GroupProofJournal(paths["proof"], writer_id=f"group-proof-{account_ref}")
    provider_contract = RiskBtApiProviderContract(
        exchange_name="FIXTURE___SPOT",
        profile_id="service-group-provider-v2",
        order_schema=_V2_ORDER_SCHEMA,
        fill_schema=_V2_FILL_SCHEMA,
        client_order_id_query=True,
        client_order_id_query_unique=True,
        complete_order_snapshot=True,
        complete_fill_history=True,
        provider_accepts_client_order_id=True,
        provider_status_mapping=(
            ("cancelled", "canceled"),
            ("expired", "expired"),
            ("filled", "completed"),
            ("open", "accepted"),
            ("partial", "partial"),
            ("rejected", "rejected"),
        ),
        supported_order_types=("LIMIT",),
        supported_time_in_force=("IOC",),
        supported_position_effects=("OPEN",),
        normalizer_schema="bt-api-order-source-provenance-v2",
        order_revision_field="order_revision",
        fill_revision_field="fill_revision",
        fill_watermark_field="fill_watermark",
        fee_amount_field="fee_amount",
        fee_currency_field="fee_currency",
        quote_currency_by_instrument=tuple((item.instrument, "USD") for item in metadatas),
    )
    proof_target = GroupProofTarget(
        execution_scope=execution_scope,
        risk_target=risk_target,
        provider_contract=provider_contract,
        bt_api=bt_api,
        execution_store=execution_store,
        risk_order_journal=risk_order_journal,
        evidence_class=DispatchEvidenceClass.SIMULATION_JOURNAL,
    )
    proof_source = GroupProofSource(proof_journal, {owner_scope: proof_target})
    risk_gate = DurableRiskGate(
        paths["risk_gate"],
        _risk_policy(),
        execution_journal_authority=proof_source,
    )
    risk_gate.set_strategy_allocation(
        risk_scope,
        _STRATEGY,
        "group-allocation-v1",
        max_notional=Decimal("100000"),
        notional_unit="USD",
    )
    mapper = InstrumentRiskAdmissionMapper(
        risk_scope,
        registry,
        clock_ns=time.time_ns,
        allocation_reader=lambda routed_scope: risk_gate.get_strategy_allocation(
            risk_scope, routed_scope.strategy_id
        ),
        wire_account_ref=account_ref,
    )
    risk_admission = DurableRiskAdmissionAdapter(risk_gate, mapper)
    account_admission = AccountScopedGroupAdmissionAdapter(risk_admission, account_scope=risk_scope)
    proof_reservation_target = ProofReservationTarget(risk_scope, risk_admission)
    bundle = GroupProofRuntimeBundle(
        risk_admission,
        account_admission,
        MappingProxyType({owner_scope: proof_reservation_target}),
        MappingProxyType({owner_scope: proof_target}),
        proof_source,
    )
    bundle.require_runtime_bundle(
        account_scoped_admission=account_admission,
        risk_admission=risk_admission,
    )
    accepted_store = AcceptedGroupBindingStore(paths["accepted"])
    authority = ExecutionGroupAuthority(
        paths["group_authority"],
        completion_verifier=ExecutionStoreGroupCompletionVerifier(
            execution_store, execution_scopes=(execution_scope,)
        ),
    )
    return _AccountResourceGraph(
        bt_api=bt_api,
        execution_store=execution_store,
        proof_journal=proof_journal,
        risk_gate=risk_gate,
        accepted_store=accepted_store,
        authority=authority,
        provider=provider,
        risk_scope=risk_scope,
        execution_scope=execution_scope,
        owner_scope=owner_scope,
        risk_admission=risk_admission,
        account_admission=account_admission,
        bundle=bundle,
    )


def _account_host_process(
    control,
    raw_config: dict[str, Any],
    registry_path: str,
    paths: dict[str, str],
    account_ref: str,
    server_public: bytes,
    server_secret: bytes,
    coordinator_client_public: bytes,
    metadata_reference_ns: int,
    initial_states: tuple[str, ...],
    instruments: tuple[str, ...],
    expected_orders: tuple[tuple[str, str, str, str], ...],
) -> None:
    config = parse_service_config(raw_config)
    account_scope = _owner_scope(account_ref)
    coordinator_service_id = _COORDINATOR_SERVICE_ID
    coordinator_identity = WireIdentity(
        WireRole.SERVICE, _COORDINATOR_PRINCIPAL, coordinator_service_id
    )
    execution_instance = f"group-execution-owner-{account_ref}"
    risk_instance = f"group-risk-reservations-{account_ref}"
    reservation_ref, entry_ref, query_ref = _route_refs(account_ref)
    write_policy = TrustedGroupWritePolicy(
        execution_instance,
        _COORDINATOR_PRINCIPAL,
        coordinator_identity,
        entry_ref,
        account_scope,
        _RUN,
    )
    resolution_policy = TrustedGroupResolutionPolicy(
        execution_instance,
        _COORDINATOR_PRINCIPAL,
        coordinator_identity,
        entry_ref,
        account_scope,
        _RUN,
        account_ref,
    )
    reservation_policy = TrustedGroupReservationPolicy(
        risk_instance,
        _COORDINATOR_PRINCIPAL,
        coordinator_identity,
        reservation_ref,
        account_scope,
        _RUN,
        account_ref,
    )
    resources: _AccountResourceGraph | None = None
    host: ServiceHost | None = None

    def resource_provider(component, _instance_id, _options, _scope):
        nonlocal resources
        if resources is None:
            resources = _new_account_resource_graph(
                account_ref,
                paths,
                initial_states,
                metadata_reference_ns,
                instruments,
                expected_orders,
            )
        if component == "execution":
            return ComponentResources.borrowed(
                {
                    "store": resources.execution_store,
                    "dispatch": _UnusedExecutionDispatch(),
                    "accepted_group_store": resources.accepted_store,
                    "group_authority": resources.authority.guard,
                    "group_runtime_bundle": resources.bundle,
                },
                ready=lambda: True,
            )
        if component == "risk":
            return ComponentResources.borrowed(
                {
                    "accepted_group_store": resources.accepted_store,
                    "group_runtime_bundle": resources.bundle,
                },
                ready=lambda: True,
            )
        raise AssertionError("unexpected component in fixed account host")

    try:
        host = ServiceHost(
            config,
            TrustedServiceAuthority(
                identity=WireIdentity(
                    WireRole.SERVICE,
                    f"group-owner-service-principal-{account_ref}",
                    config.service_id,
                ),
                scope=WireScope(_DOMAIN),
                scope_ref=config.scope_ref,
                scope_version="group-service-scope-v1",
                security_ref=f"account-server-security-{account_ref}",
                security_version=f"curve-keys-{account_ref}-v1",
                registration_policy_ref=config.registration_policy_ref,
                registration_policy_version="group-registration-v1",
                service_requirements_ref=config.service_requirements_ref,
                service_requirements_version="group-requirements-v1",
                curve_public_key=server_public,
                curve_secret_key=server_secret,
                principals={coordinator_client_public: _COORDINATOR_PRINCIPAL},
                grants={
                    _COORDINATOR_PRINCIPAL: (
                        PrincipalGrant(
                            coordinator_identity,
                            (
                                ResourceGrant(
                                    execution_instance,
                                    "service.order_entry",
                                    entry_ref,
                                    account_scope,
                                    frozenset(
                                        {
                                            "orders.submit_group_leg",
                                            "orders.resolve_group_leg",
                                        }
                                    ),
                                ),
                                ResourceGrant(
                                    execution_instance,
                                    "service.order_query",
                                    query_ref,
                                    account_scope,
                                    frozenset({"orders.query_group_leg"}),
                                ),
                                ResourceGrant(
                                    risk_instance,
                                    "service.group_reservations",
                                    reservation_ref,
                                    account_scope,
                                    frozenset(
                                        {
                                            "reservations.reserve",
                                            "reservations.query",
                                            "reservations.release",
                                        }
                                    ),
                                ),
                            ),
                        ),
                    )
                },
                group_write_policies=(write_policy,),
                group_reservation_policies=(reservation_policy,),
                group_resolution_policies=(resolution_policy,),
            ),
            registry_path,
            resource_provider,
        )
        host.start()
        control.send(("ready", host.endpoint))
        while True:
            if control.poll(0):
                command = control.recv()
                if command == "close":
                    host.close()
                    control.send(("closed", host.state))
                    return
                if isinstance(command, tuple) and command[0] == "activate":
                    registration_id = command[1]
                    registry = host._registry
                    if registry is None or resources is None:
                        raise AssertionError("Host registration resources are unavailable")
                    contexts = registry.active_registration_contexts(
                        instance_id=execution_instance,
                        port="service.order_entry",
                    )
                    matches = tuple(
                        item for item in contexts if item.context.registration_id == registration_id
                    )
                    assert len(matches) == 1
                    registration = matches[0]
                    assert registration.context.identity == coordinator_identity
                    assert registration.context.scope == account_scope
                    assert registration.strategy_write_run_id == _RUN
                    generation = resources.authority.control.activate(
                        registration.context,
                        execution_scope=resources.execution_scope,
                        risk_account_scope_key=resources.risk_scope.key,
                    )
                    control.send(("activated", generation.registration_id, generation.generation))
                elif isinstance(command, tuple) and command[0] == "status":
                    if resources is None:
                        raise AssertionError("account resources are unavailable")
                    writes, counters = resources.provider.snapshot()
                    control.send(
                        (
                            "status",
                            writes,
                            counters,
                            resources.authority.pending_holds(),
                            resources.provider.remaining(),
                        )
                    )
            host.serve_once(15)
    except BaseException as error:
        if host is not None and host.state not in {"closed", "failed"}:
            with suppress(BaseException):
                host.close()
        with suppress(Exception):
            control.send(("error", getattr(error, "code", type(error).__name__)))
        raise
    finally:
        if host is not None and host.state != "closed":
            with suppress(BaseException):
                host.close()
        if resources is not None:
            resources.close()
        control.close()


def _coordinator_host_process(
    control,
    raw_config: dict[str, Any],
    raw_account_configs: dict[str, dict[str, Any]],
    registry_path: str,
    group_store_path: str,
    run_bindings_path: str,
    account_endpoints: dict[str, str],
    account_server_public: dict[str, bytes],
    coordinator_server_public: bytes,
    coordinator_server_secret: bytes,
    coordinator_client_public: bytes,
    coordinator_client_secret: bytes,
    strategy_client_public: bytes,
    metadata_reference_ns: int,
    accounts: tuple[str, ...],
    rule_specs: dict[str, dict[str, str]],
) -> None:
    config = parse_service_config(raw_config)
    account_configs = {
        account: parse_service_config(raw_account_configs[account]) for account in accounts
    }
    service_identity = WireIdentity(
        WireRole.SERVICE, _COORDINATOR_PRINCIPAL, _COORDINATOR_SERVICE_ID
    )
    strategy_identity = WireIdentity(WireRole.STRATEGY_CLIENT, _STRATEGY_PRINCIPAL, _STRATEGY)
    strategy_scope = _stable_strategy_scope(accounts)
    account_scope_by_ref: dict[str, WireScope] = {}
    peer_by_service: dict[str, WireIdentity] = {}
    security_profiles: dict[str, ClientCurveKeys] = {}
    for account_ref in accounts:
        reservation_ref, entry_ref, query_ref = _route_refs(account_ref)
        account_scope = _owner_scope(account_ref)
        for scope_ref in (reservation_ref, entry_ref, query_ref):
            account_scope_by_ref[scope_ref] = account_scope
        account_service_id = account_configs[account_ref].service_id
        peer_by_service[account_service_id] = WireIdentity(
            WireRole.SERVICE,
            f"group-owner-service-principal-{account_ref}",
            account_service_id,
        )
        security_profiles[f"coordinator-client-security-{account_ref}"] = ClientCurveKeys(
            server_key=account_server_public[account_ref],
            public_key=coordinator_client_public,
            secret_key=coordinator_client_secret,
        )

    trusted_clients = TrustedServiceClients(
        scope_resolver=lambda scope_ref: account_scope_by_ref[scope_ref],
        peer_resolver=lambda service_id: peer_by_service[service_id],
        transport_factory=ZmqTransportFactory(security_profiles),
        requested_operations={
            "upstream.orders": frozenset({"orders.submit_group_leg", "orders.resolve_group_leg"}),
            "upstream.order_query": frozenset({"orders.query_group_leg"}),
            "upstream.account_reservations": frozenset(
                {
                    "reservations.reserve",
                    "reservations.query",
                    "reservations.release",
                }
            ),
        },
    )
    route_targets: dict[str, GroupAccountRoute] = {}
    for account_ref in accounts:
        provider_account = f"provider-{account_ref}"
        risk_scope = AccountScope("fixture", provider_account, "simulation")
        execution_scope = _execution_scope(account_ref)
        reservation_ref, entry_ref, query_ref = _route_refs(account_ref)
        instruments: dict[str, GroupInstrumentRule] = {}
        for instrument, base_units in rule_specs[account_ref].items():
            metadata = _metadata(instrument, metadata_reference_ns)
            instruments[instrument] = GroupInstrumentRule(
                metadata=metadata,
                base_units_per_order_unit=Decimal(base_units),
                allowed_order_types=frozenset({OrderType.LIMIT}),
            )
        route_targets[account_ref] = GroupAccountRoute(
            execution_scope=execution_scope,
            risk_scope_fingerprint=risk_account_scope_fingerprint(risk_scope.key),
            reservation_scope_ref=reservation_ref,
            order_scope_ref=entry_ref,
            query_scope_ref=query_ref,
            instruments=instruments,
        )
    budget_instruments = tuple(
        sorted({instrument for account in accounts for instrument in rule_specs[account]})
    )
    budget_policy, budget_quote_builder = _budget_binding(
        tuple(_metadata(instrument, metadata_reference_ns) for instrument in budget_instruments)
    )
    coordinator_target = GroupCoordinatorTarget(
        scope_ref=_COORDINATOR_SCOPE_REF,
        accounts=route_targets,
        max_group_lifetime_ns=300_000_000_000,
        portfolio_budget_policy=budget_policy,
        budget_quote_builder=budget_quote_builder,
    )
    resources: dict[str, object] = {}
    host: ServiceHost | None = None

    def resource_provider(component, _instance_id, _options, _scope):
        if component != "execution":
            raise AssertionError("coordinator host must contain only its fixed component")
        group_store = SqliteOrderGroupStore(group_store_path)
        run_bindings = GroupOriginRunBindingStore(run_bindings_path)
        resources.update({"store": group_store, "run_bindings": run_bindings})
        return ComponentResources.borrowed(
            {
                "store": group_store,
                "targets": {strategy_scope: coordinator_target},
                "run_bindings": run_bindings,
            },
            ready=lambda: True,
        )

    try:
        host = ServiceHost(
            config,
            TrustedServiceAuthority(
                identity=service_identity,
                scope=WireScope(_DOMAIN),
                scope_ref=config.scope_ref,
                scope_version="coordinator-scope-v1",
                security_ref="coordinator-server-security-v1",
                security_version="coordinator-curve-v1",
                registration_policy_ref=config.registration_policy_ref,
                registration_policy_version="coordinator-registration-v1",
                service_requirements_ref=config.service_requirements_ref,
                service_requirements_version="coordinator-requirements-v1",
                curve_public_key=coordinator_server_public,
                curve_secret_key=coordinator_server_secret,
                principals={strategy_client_public: _STRATEGY_PRINCIPAL},
                grants={
                    _STRATEGY_PRINCIPAL: (
                        PrincipalGrant(
                            strategy_identity,
                            (
                                ResourceGrant(
                                    _COORDINATOR_INSTANCE_ID,
                                    "service.order_group_entry",
                                    _COORDINATOR_SCOPE_REF,
                                    strategy_scope,
                                    frozenset({"groups.submit", "groups.query"}),
                                ),
                            ),
                        ),
                    )
                },
            ),
            registry_path,
            resource_provider,
            service_directory={
                _COORDINATOR_SERVICE_ID: config,
                **{
                    account_configs[account].service_id: account_configs[account]
                    for account in accounts
                },
            },
            trusted_clients=trusted_clients,
        )
        host.start()
        upstream = host.upstream
        if upstream is None or not upstream.healthy:
            raise AssertionError("coordinator Host upstream did not become healthy")
        upstream_bindings = tuple(
            (
                binding.mount,
                binding.scope.account_ref,
                binding.scope_ref,
                binding.registration_id,
                tuple(sorted(binding.operations)),
            )
            for binding in upstream.bindings
            if binding.active
        )
        control.send(("ready", host.endpoint, upstream_bindings))
        while True:
            if control.poll(0):
                command = control.recv()
                if command == "close":
                    host.close()
                    control.send(("closed", host.state, upstream.state))
                    return
            host.serve_once(15)
    except BaseException as error:
        if host is not None and host.state not in {"closed", "failed"}:
            with suppress(BaseException):
                host.close()
        with suppress(Exception):
            control.send(("error", getattr(error, "code", type(error).__name__)))
        raise
    finally:
        if host is not None and host.state != "closed":
            with suppress(BaseException):
                host.close()
        for name in ("run_bindings", "store"):
            resource = resources.get(name)
            close = getattr(resource, "close", None)
            if callable(close):
                close()
        control.close()


def _receive(control, *, timeout: float = 20.0) -> tuple[Any, ...]:
    assert control.poll(timeout), "spawned ServiceHost did not answer within its bound"
    message = control.recv()
    assert message and message[0] != "error", message
    return message


def _stop_process(process, control) -> None:
    failures: list[str] = []
    try:
        if process.is_alive():
            control.send("close")
            if not control.poll(20):
                failures.append("Host did not complete its normal close")
            else:
                closed = control.recv()
                if not closed or closed[0] != "closed":
                    failures.append(f"Host returned a nonterminal close result: {closed!r}")
        process.join(20)
        if process.is_alive():
            failures.append("Host process remained alive after bounded normal-close wait")
        elif process.exitcode != 0:
            failures.append(f"Host process exited with code {process.exitcode}")
    except BaseException as error:
        failures.append(f"Host normal-close handshake raised {type(error).__name__}")
        process.join(20)
        if process.is_alive():
            failures.append("Host process remained alive after handshake error")
        elif process.exitcode != 0:
            failures.append(f"Host process exited with code {process.exitcode}")
    finally:
        with suppress(BaseException):
            control.close()
        if not process.is_alive():
            with suppress(BaseException):
                process.close()
    if failures:
        raise AssertionError("; ".join(failures))


def _provider_snapshot(path: Path) -> tuple[tuple[str, ...], dict[str, int]]:
    with sqlite3.connect(path) as connection:
        writes = tuple(
            str(row[0])
            for row in connection.execute(
                "SELECT client_order_id FROM provider_writes ORDER BY sequence"
            )
        )
        counters = {
            str(row[0]): int(row[1])
            for row in connection.execute("SELECT name, count FROM provider_counters ORDER BY name")
        }
        faults = connection.execute("SELECT COUNT(*) FROM provider_faults").fetchone()[0]
    assert faults == 0
    return writes, counters


def _intent(
    group_id: str,
    leg_id: str,
    account_ref: str,
    side: Side,
    deadline_ns: int,
    metadata: InstrumentRiskMetadata,
    quantity: Decimal,
) -> OrderIntent:
    return OrderIntent.limit(
        intent_id=group_leg_intent_id(group_id, leg_id),
        scope=_execution_scope(account_ref),
        signal_id=f"{group_id}-{leg_id}",
        instrument=metadata.instrument,
        side=side,
        quantity=quantity,
        price=Decimal("100"),
        time_in_force=TimeInForce.IOC,
        metadata_version=metadata.metadata_version,
        deadline_ns=deadline_ns,
        tags={INSTRUMENT_METADATA_DIGEST_TAG: metadata.digest},
    )


def _group_request(
    group_id: str,
    metadata_reference_ns: int,
    legs: tuple[tuple[str, str, Side, Decimal, str], ...],
) -> dict[str, Any]:
    now_ns = time.time_ns()
    deadline_ns = now_ns + 120_000_000_000
    payload_legs = []
    for leg_id, account_ref, side, quantity, instrument in legs:
        metadata = _metadata(instrument, metadata_reference_ns)
        payload_legs.append(
            {
                "leg_id": leg_id,
                "account_ref": account_ref,
                "intent": _intent(
                    group_id,
                    leg_id,
                    account_ref,
                    side,
                    deadline_ns,
                    metadata,
                    quantity,
                ).to_payload(),
            }
        )
    return {
        "group_id": group_id,
        "deadline_ns": deadline_ns,
        "first_leg_id": "leg-a",
        "legs": payload_legs,
    }


def _submit_and_query(runtime: ServiceClientRuntime, request: dict[str, Any]) -> GroupOrderSnapshot:
    reply = runtime.call(
        "broker.order_groups",
        "groups.submit",
        request,
        portfolio_ref=_PORTFOLIO,
    )
    assert reply["ok"] is True, reply
    assert reply["code"] == "OK", reply
    adapter_result = reply["result"]
    assert adapter_result["found"] is True, adapter_result
    snapshot = GroupOrderSnapshot.from_payload(_plain_runtime_json(adapter_result["snapshot"]))
    query = runtime.call(
        "broker.order_groups",
        "groups.query",
        {"group_id": request["group_id"]},
        portfolio_ref=_PORTFOLIO,
    )
    assert query["ok"] is True, query
    assert query["code"] == "OK", query
    assert query["result"]["found"] is True, query
    queried_snapshot = GroupOrderSnapshot.from_payload(
        _plain_runtime_json(query["result"]["snapshot"])
    )
    assert queried_snapshot == snapshot
    return snapshot


def _plain_runtime_json(value: object) -> object:
    """Project authenticated immutable runtime containers for stored-JSON DTOs."""

    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise TypeError("runtime JSON object keys must be strings")
        return {key: _plain_runtime_json(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_plain_runtime_json(item) for item in value]
    return value


class _GroupCluster:
    """Spawned account/coordinator hosts plus the strategy client runtime."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        accounts: tuple[str, ...],
        instruments: dict[str, tuple[str, ...]],
        initial_states: dict[str, tuple[str, ...]],
        expected_orders: dict[str, tuple[tuple[str, str, str, str], ...]],
        rule_specs: dict[str, dict[str, str]],
    ) -> None:
        self.accounts = accounts
        self.instruments = instruments
        self.initial_states = initial_states
        self.expected_orders = expected_orders
        self.rule_specs = rule_specs
        self.metadata_reference_ns = time.time_ns()
        self.account_paths: dict[str, dict[str, str]] = {
            account: {
                name: str(tmp_path / f"{account}-{name}.sqlite3")
                for name in (
                    "registry",
                    "provider",
                    "execution",
                    "risk_order_journal",
                    "proof",
                    "risk_gate",
                    "accepted",
                    "group_authority",
                )
            }
            for account in accounts
        }
        self.coordinator_paths = {
            "registry": str(tmp_path / "coordinator-registry.sqlite3"),
            "groups": str(tmp_path / "coordinator-groups.sqlite3"),
            "run_bindings": str(tmp_path / "coordinator-run-bindings.sqlite3"),
        }
        self.account_endpoints = {account: _endpoint() for account in accounts}
        self.account_server_keys = {account: zmq.curve_keypair() for account in accounts}
        self.coordinator_server_public, self.coordinator_server_secret = zmq.curve_keypair()
        self.coordinator_client_public, self.coordinator_client_secret = zmq.curve_keypair()
        self.strategy_client_public, self.strategy_client_secret = zmq.curve_keypair()
        self.account_configs = {
            account: _account_service_config(
                account,
                self.account_endpoints[account],
                f"account-server-security-{account}",
            )
            for account in accounts
        }
        self.coordinator_endpoint = _endpoint()
        self.coordinator_raw = _coordinator_service_config(
            self.coordinator_endpoint,
            "coordinator-server-security-v1",
            self.account_configs,
            self.account_endpoints,
            accounts,
        )
        self.account_processes: dict[str, Any] = {}
        self.account_controls: dict[str, Any] = {}
        self.coordinator_process: Any = None
        self.coordinator_control: Any = None
        self.strategy_runtime: ServiceClientRuntime | None = None
        self.strategy_started = False
        self.upstream_bindings: tuple[tuple[Any, ...], ...] = ()

    def __enter__(self) -> _GroupCluster:
        try:
            self._start_all()
        except BaseException:
            with suppress(BaseException):
                self.close()
            raise
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> bool:
        self.close()
        return False

    def _start_all(self) -> None:
        account_context = multiprocessing.get_context("spawn")
        for account_ref in self.accounts:
            parent_control, child_control = account_context.Pipe(duplex=True)
            process = account_context.Process(
                name=f"group-account-host-{account_ref}",
                target=_account_host_process,
                args=(
                    child_control,
                    self.account_configs[account_ref],
                    self.account_paths[account_ref]["registry"],
                    self.account_paths[account_ref],
                    account_ref,
                    self.account_server_keys[account_ref][0],
                    self.account_server_keys[account_ref][1],
                    self.coordinator_client_public,
                    self.metadata_reference_ns,
                    self.initial_states[account_ref],
                    self.instruments[account_ref],
                    self.expected_orders[account_ref],
                ),
            )
            try:
                process.start()
            except BaseException:
                child_control.close()
                parent_control.close()
                raise
            child_control.close()
            self.account_processes[account_ref] = process
            self.account_controls[account_ref] = parent_control
            startup = _receive(parent_control)
            assert startup[0] == "ready", startup
            assert startup[1] == self.account_endpoints[account_ref]

        coordinator_context = multiprocessing.get_context("spawn")
        coordinator_parent, coordinator_child = coordinator_context.Pipe(duplex=True)
        self.coordinator_process = coordinator_context.Process(
            name="group-coordinator-host",
            target=_coordinator_host_process,
            args=(
                coordinator_child,
                self.coordinator_raw,
                self.account_configs,
                self.coordinator_paths["registry"],
                self.coordinator_paths["groups"],
                self.coordinator_paths["run_bindings"],
                self.account_endpoints,
                {
                    account: self.account_server_keys[account][0]
                    for account in self.accounts
                },
                self.coordinator_server_public,
                self.coordinator_server_secret,
                self.coordinator_client_public,
                self.coordinator_client_secret,
                self.strategy_client_public,
                self.metadata_reference_ns,
                self.accounts,
                self.rule_specs,
            ),
        )
        try:
            self.coordinator_process.start()
        except BaseException:
            coordinator_child.close()
            coordinator_parent.close()
            self.coordinator_control = None
            self.coordinator_process = None
            raise
        coordinator_child.close()
        self.coordinator_control = coordinator_parent
        coordinator_ready = _receive(self.coordinator_control)
        assert coordinator_ready[0] == "ready", coordinator_ready
        assert coordinator_ready[1] == self.coordinator_endpoint
        self.upstream_bindings = coordinator_ready[2]
        expected_upstream = (
            {("upstream.orders", account, _route_refs(account)[1]) for account in self.accounts}
            | {
                ("upstream.order_query", account, _route_refs(account)[2])
                for account in self.accounts
            }
            | {
                ("upstream.account_reservations", account, _route_refs(account)[0])
                for account in self.accounts
            }
        )
        expected_upstream_operations = {
            "upstream.orders": frozenset({"orders.submit_group_leg", "orders.resolve_group_leg"}),
            "upstream.order_query": frozenset({"orders.query_group_leg"}),
            "upstream.account_reservations": frozenset(
                {"reservations.reserve", "reservations.query", "reservations.release"}
            ),
        }
        assert len(self.upstream_bindings) == len(expected_upstream) == 3 * len(self.accounts)
        assert all(
            registration_id
            and operations == tuple(sorted(expected_upstream_operations[mount]))
            for mount, _account, _scope_ref, registration_id, operations in self.upstream_bindings
        )
        assert {
            (mount, account, scope_ref)
            for mount, account, scope_ref, _registration_id, _operations in self.upstream_bindings
        } == expected_upstream

        order_registration_ids = {
            account: next(
                registration_id
                for mount, bound_account, _scope_ref, registration_id, _operations in (
                    self.upstream_bindings
                )
                if mount == "upstream.orders" and bound_account == account
            )
            for account in self.accounts
        }
        for account_ref in self.accounts:
            control = self.account_controls[account_ref]
            control.send(("activate", order_registration_ids[account_ref]))
            activation = _receive(control)
            assert activation[0] == "activated", activation
            assert activation[1] == order_registration_ids[account_ref]
            assert type(activation[2]) is int and activation[2] > 0

        strategy_identity = WireIdentity(WireRole.STRATEGY_CLIENT, _STRATEGY_PRINCIPAL, _STRATEGY)
        coordinator_identity = WireIdentity(
            WireRole.SERVICE, _COORDINATOR_PRINCIPAL, _COORDINATOR_SERVICE_ID
        )
        strategy_runtime = ServiceClientRuntime(
            parse_client_config(
                _strategy_client_config(self.coordinator_endpoint, "strategy-client-security-v1")
            ),
            identity=strategy_identity,
            scope_resolver=lambda _scope_ref: _stable_strategy_scope(self.accounts),
            peer_resolver=lambda _service_id: coordinator_identity,
            transport_factory=ZmqTransportFactory(
                {
                    "strategy-client-security-v1": ClientCurveKeys(
                        server_key=self.coordinator_server_public,
                        public_key=self.strategy_client_public,
                        secret_key=self.strategy_client_secret,
                    )
                }
            ),
            run_id=_RUN,
            requested_operations={
                "broker.order_groups": frozenset({"groups.submit", "groups.query"})
            },
        )
        self.strategy_runtime = strategy_runtime
        strategy_receipt = strategy_runtime.start()
        self.strategy_started = True
        assert strategy_receipt.degraded_count == 0
        assert len(strategy_receipt.bindings) == 1
        strategy_binding = strategy_receipt.bindings[0]
        assert strategy_binding.mount == "broker.order_groups"
        assert strategy_binding.scope.account_refs == self.accounts
        assert strategy_binding.scope.run_id == _RUN
        assert strategy_binding.operations == frozenset({"groups.submit", "groups.query"})

    def submit_group(self, request: dict[str, Any]) -> GroupOrderSnapshot:
        assert self.strategy_runtime is not None
        return _submit_and_query(self.strategy_runtime, request)

    def status(self, account_ref: str) -> tuple[Any, ...]:
        control = self.account_controls[account_ref]
        control.send(("status",))
        status = _receive(control)
        assert status[0] == "status", status
        return status

    def close(self) -> None:
        cleanup_failures: list[BaseException] = []
        if self.strategy_runtime is not None and self.strategy_started:
            runtime = self.strategy_runtime
            try:
                runtime.close()
                assert runtime.state == "closed"
                assert runtime.unregister_uncertainties == 0
            except BaseException as error:
                cleanup_failures.append(error)
            finally:
                self.strategy_started = False
        if self.coordinator_process is not None and self.coordinator_control is not None:
            try:
                _stop_process(self.coordinator_process, self.coordinator_control)
            except BaseException as error:
                cleanup_failures.append(error)
            finally:
                self.coordinator_process = None
                self.coordinator_control = None
        for account_ref in reversed(self.accounts):
            process = self.account_processes.pop(account_ref, None)
            control = self.account_controls.pop(account_ref, None)
            if process is not None and control is not None:
                try:
                    _stop_process(process, control)
                except BaseException as error:
                    cleanup_failures.append(error)
        if cleanup_failures:
            raise AssertionError(
                "one or more normal Host shutdowns failed: "
                + "; ".join(type(error).__name__ for error in cleanup_failures)
            ) from cleanup_failures[0]


def _leg_outbox(
    store: SqliteExecutionStore, scope: ExecutionScope, intent_id: str
) -> tuple[Any, ...]:
    events = store.read_outbox(after_sequence=0, limit=1000, scope=scope)
    return tuple(event for event in events if event.intent_id == intent_id)


def _assert_provider_writes(path: Path, expected: int) -> None:
    writes, counters = _provider_snapshot(path)
    assert len(writes) == expected
    assert len(set(writes)) == expected
    assert set(counters) == {"order_queries", "fill_queries"}
    assert counters == {"order_queries": expected, "fill_queries": expected}


def _risk_legs(account_paths: dict[str, dict[str, str]], account_ref: str, group_id: str):
    scope = AccountScope("fixture", f"provider-{account_ref}", "simulation")
    gate = DurableRiskGate(account_paths[account_ref]["risk_gate"], _risk_policy())
    try:
        vector = gate.read_group_vector_snapshot(scope, group_id)
        return tuple((leg.leg_id, leg.claimed, leg.resolved) for leg in vector.legs)
    finally:
        gate.close()


def _assert_holds_resolved(
    account_paths: dict[str, dict[str, str]], account_ref: str, group_id: str
) -> None:
    execution_scope = _execution_scope(account_ref)
    authority_store = SqliteExecutionStore(account_paths[account_ref]["execution"])
    authority = ExecutionGroupAuthority(
        account_paths[account_ref]["group_authority"],
        completion_verifier=ExecutionStoreGroupCompletionVerifier(
            authority_store,
            execution_scopes=(execution_scope,),
        ),
    )
    try:
        assert authority.pending_holds() == ()
    finally:
        authority.close()
        authority_store.close()


def test_arb03_partial_cancel_first_leg_and_rejected_hedge_recovery(tmp_path: Path) -> None:
    """First-leg IOC partial cancel plus a rejected hedge leg needs recovery."""

    with _GroupCluster(
        tmp_path,
        accounts=_ARB03_ACCOUNTS,
        instruments={account: (_V2_INSTRUMENT,) for account in _ARB03_ACCOUNTS},
        initial_states={"account-a": ("cancelled:1.5",), "account-b": ("rejected",)},
        expected_orders={
            "account-a": ((_V2_INSTRUMENT, "2", "100", "buy-limit"),),
            "account-b": ((_V2_INSTRUMENT, "3", "100", "sell-limit"),),
        },
        rule_specs={
            "account-a": {_V2_INSTRUMENT: "2"},
            "account-b": {_V2_INSTRUMENT: "1"},
        },
    ) as cluster:
        snapshot = cluster.submit_group(
            _group_request(
                _GROUP_ARB03,
                cluster.metadata_reference_ns,
                (
                    ("leg-a", "account-a", Side.BUY, Decimal("2"), _V2_INSTRUMENT),
                    ("leg-b", "account-b", Side.SELL, Decimal("4"), _V2_INSTRUMENT),
                ),
            )
        )
        assert snapshot.state is GroupOrderState.RECOVERY_REQUIRED
        assert snapshot.error_code == "hedge_residual_unresolved"
        assert snapshot.residual_base_units == Decimal("3")
        assert len(snapshot.legs) == 2
        assert len(snapshot.reservations) == 2
        assert tuple(item.account_ref for item in snapshot.reservations) == ("account-a", "account-b")

        leg_a = next(leg for leg in snapshot.legs if leg.leg_id == "leg-a")
        leg_b = next(leg for leg in snapshot.legs if leg.leg_id == "leg-b")

        assert leg_a.submitted_intent is not None
        assert leg_a.submitted_intent.instrument == _V2_INSTRUMENT
        assert leg_a.submitted_intent.quantity == Decimal("2")
        first = leg_a.child_status
        assert first is not None
        assert first.state is ExecutionState.CANCELLED
        assert first.filled_quantity == Decimal("1.5")
        assert first.average_price == Decimal("100")
        assert first.cumulative_commission == Decimal("-0.05")
        assert first.cumulative_commission_currency == "USD"
        assert first.trade_count == 1
        assert first.order_revision == 1
        assert first.provider_order_id is not None
        assert leg_a.claim_receipt is not None
        assert leg_a.resolution_receipt is not None
        resolution_a = leg_a.resolution_receipt
        assert resolution_a.resolution_kind == "TERMINAL_EXPOSURE_RESOLVED"
        assert resolution_a.final_state is ExecutionState.CANCELLED
        assert resolution_a.requested_quantity == Decimal("2")
        assert resolution_a.filled_quantity == Decimal("1.5")
        assert resolution_a.trade_count == 1
        assert resolution_a.dispatch_latch_active is False

        assert leg_b.submitted_intent is not None
        assert leg_b.submitted_intent.instrument == _V2_INSTRUMENT
        assert leg_b.submitted_intent.quantity == Decimal("3")
        second = leg_b.child_status
        assert second is not None
        assert second.state is ExecutionState.REJECTED
        assert second.filled_quantity == Decimal("0")
        assert second.trade_count == 0
        assert second.cumulative_commission is None
        assert second.reason_code == "provider_rejected"
        assert leg_b.resolution_receipt is not None
        resolution_b = leg_b.resolution_receipt
        assert resolution_b.resolution_kind == "TERMINAL_NO_FILL_RESOLVED"
        assert resolution_b.final_state is ExecutionState.REJECTED
        assert resolution_b.requested_quantity == Decimal("3")
        assert resolution_b.filled_quantity == Decimal("0")
        assert resolution_b.trade_count == 0
        assert resolution_b.dispatch_latch_active is False

        for account_ref in _ARB03_ACCOUNTS:
            status = cluster.status(account_ref)
            assert status[4] == (), f"unconsumed provider expectations on {account_ref}"

    persisted_groups = SqliteOrderGroupStore(cluster.coordinator_paths["groups"])
    try:
        persisted = persisted_groups.get(_PORTFOLIO, _GROUP_ARB03)
        assert persisted == snapshot
        events = persisted_groups.events(_PORTFOLIO, _GROUP_ARB03)
    finally:
        persisted_groups.close()
    assert any(event.event_type == "GROUP_RECOVERY_REQUIRED" for event in events)
    sized = tuple(event for event in events if event.event_type == "HEDGE_LEG_SIZED")
    assert len(sized) == 1
    assert sized[0].payload["quantity"] == "3.000"
    resolved_events = tuple(
        event
        for event in events
        if event.event_type == "GROUP_DISPATCH_RESOLUTION_RECORDED"
        and event.payload.get("leg_id") == "leg-a"
    )
    assert len(resolved_events) == 1
    assert resolved_events[0].payload["resolution_kind"] == "TERMINAL_EXPOSURE_RESOLVED"

    execution_scope_a = _execution_scope("account-a")
    execution_scope_b = _execution_scope("account-b")
    intent_a = group_leg_intent_id(_GROUP_ARB03, "leg-a")
    intent_b = group_leg_intent_id(_GROUP_ARB03, "leg-b")
    store_a = SqliteExecutionStore(cluster.account_paths["account-a"]["execution"])
    try:
        record_a = store_a.get(intent_a, scope=execution_scope_a)
        assert record_a is not None
        assert record_a.state is ExecutionState.CANCELLED
        assert record_a.filled_quantity == Decimal("1.5")
        assert record_a.average_price == Decimal("100")
        assert record_a.cumulative_commission == Decimal("-0.05")
        assert record_a.provider_order_id is not None
        assert record_a.dispatch_attempts == 1
        assert record_a.unknown_reason is None
        assert record_a.review_required is False
        events_a = _leg_outbox(store_a, execution_scope_a, intent_a)
        assert tuple(event.event_type for event in events_a) == (
            "intent_recorded",
            "intent_admitted",
            "dispatch_claimed",
            "provider_observation",
            "provider_observation",
        )
        assert events_a[3].state is ExecutionState.PARTIALLY_FILLED
        assert events_a[4].state is ExecutionState.CANCELLED
        assert events_a[3].payload["filled_quantity"] == "1.5"
        assert events_a[3].payload == events_a[4].payload
    finally:
        store_a.close()

    store_b = SqliteExecutionStore(cluster.account_paths["account-b"]["execution"])
    try:
        record_b = store_b.get(intent_b, scope=execution_scope_b)
        assert record_b is not None
        assert record_b.state is ExecutionState.REJECTED
        assert record_b.filled_quantity == Decimal("0")
        assert record_b.average_price is None
        assert record_b.cumulative_commission is None
        assert record_b.provider_order_id is not None
        assert record_b.dispatch_attempts == 1
        assert record_b.unknown_reason is None
        assert record_b.review_required is False
        events_b = _leg_outbox(store_b, execution_scope_b, intent_b)
        assert tuple(event.event_type for event in events_b) == (
            "intent_recorded",
            "intent_admitted",
            "dispatch_claimed",
            "provider_observation",
        )
        assert events_b[3].state is ExecutionState.REJECTED
        assert events_b[3].payload.get("reason_code") == "provider_rejected"
    finally:
        store_b.close()

    assert _risk_legs(cluster.account_paths, "account-a", _GROUP_ARB03) == (
        ("leg-a", True, True),
    )
    assert _risk_legs(cluster.account_paths, "account-b", _GROUP_ARB03) == (
        ("leg-b", True, True),
    )
    for account_ref in _ARB03_ACCOUNTS:
        _assert_holds_resolved(cluster.account_paths, account_ref, _GROUP_ARB03)
        _assert_provider_writes(Path(cluster.account_paths[account_ref]["provider"]), 1)


def test_dim05_single_account_dual_contract_partial_fill_hedge_paired(tmp_path: Path) -> None:
    """One account owns a spot and a perp leg; the sized hedge completes it."""

    with _GroupCluster(
        tmp_path,
        accounts=_DIM05_ACCOUNTS,
        instruments={"account-a": (_V2_INSTRUMENT, _PERP_INSTRUMENT)},
        initial_states={"account-a": ("cancelled:1.5", "filled")},
        expected_orders={
            "account-a": (
                (_V2_INSTRUMENT, "2", "100", "buy-limit"),
                (_PERP_INSTRUMENT, "3", "100", "sell-limit"),
            )
        },
        rule_specs={"account-a": {_V2_INSTRUMENT: "2", _PERP_INSTRUMENT: "1"}},
    ) as cluster:
        snapshot = cluster.submit_group(
            _group_request(
                _GROUP_DIM05,
                cluster.metadata_reference_ns,
                (
                    ("leg-a", "account-a", Side.BUY, Decimal("2"), _V2_INSTRUMENT),
                    ("leg-b", "account-a", Side.SELL, Decimal("4"), _PERP_INSTRUMENT),
                ),
            )
        )
        assert snapshot.state is GroupOrderState.PAIRED
        assert snapshot.error_code is None
        assert snapshot.residual_base_units == 0
        assert len(snapshot.legs) == 2
        assert len(snapshot.reservations) == 1
        assert snapshot.reservations[0].account_ref == "account-a"
        assert len(snapshot.reservations[0].legs) == 2

        leg_a = next(leg for leg in snapshot.legs if leg.leg_id == "leg-a")
        leg_b = next(leg for leg in snapshot.legs if leg.leg_id == "leg-b")

        assert leg_a.submitted_intent is not None
        assert leg_a.submitted_intent.instrument == _V2_INSTRUMENT
        assert leg_a.submitted_intent.quantity == Decimal("2")
        first = leg_a.child_status
        assert first is not None
        assert first.state is ExecutionState.CANCELLED
        assert first.filled_quantity == Decimal("1.5")
        assert first.trade_count == 1
        assert leg_a.resolution_receipt is not None
        assert leg_a.resolution_receipt.resolution_kind == "TERMINAL_EXPOSURE_RESOLVED"
        assert leg_a.resolution_receipt.final_state is ExecutionState.CANCELLED
        assert leg_a.resolution_receipt.filled_quantity == Decimal("1.5")

        assert leg_b.submitted_intent is not None
        assert leg_b.submitted_intent.instrument == _PERP_INSTRUMENT
        assert leg_b.submitted_intent.quantity == Decimal("3")
        second = leg_b.child_status
        assert second is not None
        assert second.state is ExecutionState.FILLED
        assert second.filled_quantity == Decimal("3")
        assert second.average_price == Decimal("100")
        assert second.cumulative_commission == Decimal("-0.05")
        assert second.trade_count == 1
        assert leg_b.resolution_receipt is not None
        resolution_b = leg_b.resolution_receipt
        assert resolution_b.resolution_kind == "TERMINAL_EXPOSURE_RESOLVED"
        assert resolution_b.final_state is ExecutionState.FILLED
        assert resolution_b.requested_quantity == Decimal("3")
        assert resolution_b.filled_quantity == Decimal("3")
        assert resolution_b.trade_count == 1
        assert resolution_b.dispatch_latch_active is False

        status = cluster.status("account-a")
        assert status[4] == (), "unconsumed provider expectations on account-a"

    persisted_groups = SqliteOrderGroupStore(cluster.coordinator_paths["groups"])
    try:
        persisted = persisted_groups.get(_PORTFOLIO, _GROUP_DIM05)
        assert persisted == snapshot
        events = persisted_groups.events(_PORTFOLIO, _GROUP_DIM05)
    finally:
        persisted_groups.close()
    assert any(event.event_type == "GROUP_PAIRED" for event in events)
    sized = tuple(event for event in events if event.event_type == "HEDGE_LEG_SIZED")
    assert len(sized) == 1
    assert sized[0].payload["quantity"] == "3.000"

    execution_scope = _execution_scope("account-a")
    intent_a = group_leg_intent_id(_GROUP_DIM05, "leg-a")
    intent_b = group_leg_intent_id(_GROUP_DIM05, "leg-b")
    store = SqliteExecutionStore(cluster.account_paths["account-a"]["execution"])
    try:
        record_a = store.get(intent_a, scope=execution_scope)
        assert record_a is not None
        assert record_a.state is ExecutionState.CANCELLED
        assert record_a.filled_quantity == Decimal("1.5")
        events_a = _leg_outbox(store, execution_scope, intent_a)
        assert tuple(event.event_type for event in events_a) == (
            "intent_recorded",
            "intent_admitted",
            "dispatch_claimed",
            "provider_observation",
            "provider_observation",
        )
        record_b = store.get(intent_b, scope=execution_scope)
        assert record_b is not None
        assert record_b.state is ExecutionState.FILLED
        assert record_b.filled_quantity == Decimal("3")
        assert record_b.average_price == Decimal("100")
        events_b = _leg_outbox(store, execution_scope, intent_b)
        assert tuple(event.event_type for event in events_b) == (
            "intent_recorded",
            "intent_admitted",
            "dispatch_claimed",
            "provider_observation",
        )
        assert events_b[3].state is ExecutionState.FILLED
        assert events_b[3].payload["filled_quantity"] == "3.000"
    finally:
        store.close()

    assert _risk_legs(cluster.account_paths, "account-a", _GROUP_DIM05) == (
        ("leg-a", True, True),
        ("leg-b", True, True),
    )
    _assert_holds_resolved(cluster.account_paths, "account-a", _GROUP_DIM05)
    _assert_provider_writes(Path(cluster.account_paths["account-a"]["provider"]), 2)


def test_arb03_first_leg_zero_fill_closes_group_without_hedge(tmp_path: Path) -> None:
    """First-leg zero fill (REJECTED) closes the group with no hedge dispatch.

    The provider rejects the IOC first leg with zero fill. The group must
    terminate as CLOSED / GROUP_CLOSED_NO_EXPOSURE: the unclaimed hedge
    reservation is released, the second leg is never submitted (no intent, no
    provider write), and the residual base is exactly zero. A zero-fill
    CANCELLED first leg would be UNKNOWN by the source gate, so the accepted
    zero-fill form under test is REJECTED (REJECTED_NO_FILL proof kind).
    """

    with _GroupCluster(
        tmp_path,
        accounts=_ARB03_ACCOUNTS,
        instruments={account: (_V2_INSTRUMENT,) for account in _ARB03_ACCOUNTS},
        initial_states={"account-a": ("rejected",), "account-b": ()},
        expected_orders={
            "account-a": ((_V2_INSTRUMENT, "2", "100", "buy-limit"),),
            "account-b": (),
        },
        rule_specs={
            "account-a": {_V2_INSTRUMENT: "2"},
            "account-b": {_V2_INSTRUMENT: "1"},
        },
    ) as cluster:
        snapshot = cluster.submit_group(
            _group_request(
                _GROUP_ARB03_NO_FILL,
                cluster.metadata_reference_ns,
                (
                    ("leg-a", "account-a", Side.BUY, Decimal("2"), _V2_INSTRUMENT),
                    ("leg-b", "account-b", Side.SELL, Decimal("4"), _V2_INSTRUMENT),
                ),
            )
        )
        assert snapshot.state is GroupOrderState.CLOSED
        assert snapshot.error_code is None
        assert snapshot.residual_base_units == Decimal("0")
        assert len(snapshot.legs) == 2
        assert len(snapshot.reservations) == 2
        assert tuple(item.account_ref for item in snapshot.reservations) == ("account-a", "account-b")

        leg_a = next(leg for leg in snapshot.legs if leg.leg_id == "leg-a")
        leg_b = next(leg for leg in snapshot.legs if leg.leg_id == "leg-b")

        assert leg_a.submitted_intent is not None
        assert leg_a.submitted_intent.instrument == _V2_INSTRUMENT
        assert leg_a.submitted_intent.quantity == Decimal("2")
        first = leg_a.child_status
        assert first is not None
        assert first.state is ExecutionState.REJECTED
        assert first.filled_quantity == Decimal("0")
        assert first.average_price is None
        assert first.cumulative_commission is None
        assert first.trade_count == 0
        assert first.reason_code == "provider_rejected"
        assert first.provider_order_id is not None
        assert leg_a.claim_receipt is not None
        assert leg_a.resolution_receipt is not None
        resolution_a = leg_a.resolution_receipt
        assert resolution_a.resolution_kind == "TERMINAL_NO_FILL_RESOLVED"
        assert resolution_a.final_state is ExecutionState.REJECTED
        assert resolution_a.requested_quantity == Decimal("2")
        assert resolution_a.filled_quantity == Decimal("0")
        assert resolution_a.trade_count == 0
        assert resolution_a.dispatch_latch_active is False

        # The hedge leg is never submitted: no intent, claim, status or receipt.
        assert leg_b.submitted_intent is None
        assert leg_b.child_status is None
        assert leg_b.claim_receipt is None
        assert leg_b.resolution_receipt is None

        # Budget/lease conservation: every account reservation is released.
        by_account = {item.account_ref: item for item in snapshot.reservations}
        assert by_account["account-a"].phase is GroupReservationPhase.RELEASED
        assert by_account["account-b"].phase is GroupReservationPhase.RELEASED
        assert tuple(
            (leg.leg_id, leg.claimed, leg.resolved) for leg in by_account["account-a"].legs
        ) == (("leg-a", True, True),)
        assert tuple(
            (leg.leg_id, leg.claimed, leg.resolved) for leg in by_account["account-b"].legs
        ) == (("leg-b", False, False),)

        for account_ref in _ARB03_ACCOUNTS:
            status = cluster.status(account_ref)
            assert status[4] == (), f"unconsumed provider expectations on {account_ref}"

    persisted_groups = SqliteOrderGroupStore(cluster.coordinator_paths["groups"])
    try:
        persisted = persisted_groups.get(_PORTFOLIO, _GROUP_ARB03_NO_FILL)
        assert persisted == snapshot
        events = persisted_groups.events(_PORTFOLIO, _GROUP_ARB03_NO_FILL)
    finally:
        persisted_groups.close()
    closed = tuple(event for event in events if event.event_type == "GROUP_CLOSED_NO_EXPOSURE")
    assert len(closed) == 1
    assert closed[0].payload["first_leg_id"] == "leg-a"
    assert closed[0].payload["reason"] == "terminal_no_fill"
    assert not any(event.event_type == "HEDGE_LEG_SIZED" for event in events)
    assert not any(event.event_type == "GROUP_PAIRED" for event in events)
    assert not any(event.event_type == "GROUP_RECOVERY_REQUIRED" for event in events)
    resolved_events = tuple(
        event
        for event in events
        if event.event_type == "GROUP_DISPATCH_RESOLUTION_RECORDED"
        and event.payload.get("leg_id") == "leg-a"
    )
    assert len(resolved_events) == 1
    assert resolved_events[0].payload["resolution_kind"] == "TERMINAL_NO_FILL_RESOLVED"
    released = tuple(event for event in events if event.event_type == "RESERVATION_RELEASED")
    assert len(released) == 2
    assert {event.payload["account_ref"] for event in released} == set(_ARB03_ACCOUNTS)

    execution_scope_a = _execution_scope("account-a")
    intent_a = group_leg_intent_id(_GROUP_ARB03_NO_FILL, "leg-a")
    store_a = SqliteExecutionStore(cluster.account_paths["account-a"]["execution"])
    try:
        record_a = store_a.get(intent_a, scope=execution_scope_a)
        assert record_a is not None
        assert record_a.state is ExecutionState.REJECTED
        assert record_a.filled_quantity == Decimal("0")
        assert record_a.average_price is None
        assert record_a.cumulative_commission is None
        assert record_a.provider_order_id is not None
        assert record_a.dispatch_attempts == 1
        assert record_a.unknown_reason is None
        assert record_a.review_required is False
        events_a = _leg_outbox(store_a, execution_scope_a, intent_a)
        assert tuple(event.event_type for event in events_a) == (
            "intent_recorded",
            "intent_admitted",
            "dispatch_claimed",
            "provider_observation",
        )
        assert events_a[3].state is ExecutionState.REJECTED
        assert events_a[3].payload.get("reason_code") == "provider_rejected"
    finally:
        store_a.close()

    assert _risk_legs(cluster.account_paths, "account-a", _GROUP_ARB03_NO_FILL) == (
        ("leg-a", True, True),
    )
    assert _risk_legs(cluster.account_paths, "account-b", _GROUP_ARB03_NO_FILL) == (
        ("leg-b", False, False),
    )
    for account_ref in _ARB03_ACCOUNTS:
        _assert_holds_resolved(cluster.account_paths, account_ref, _GROUP_ARB03_NO_FILL)
    _assert_provider_writes(Path(cluster.account_paths["account-a"]["provider"]), 1)
    _assert_provider_writes(Path(cluster.account_paths["account-b"]["provider"]), 0)


def test_arb03_first_leg_full_fill_sizes_hedge_exactly_once(tmp_path: Path) -> None:
    """First-leg full fill sizes the hedge to the filled base and pairs.

    The first leg fills its complete requested quantity (base 4 = 2 x 2). The
    requested hedge of 6 must be resized down to exactly base 4 (step 0.001),
    dispatched exactly once, and fully filled so the group closes PAIRED with
    residual base 0 and no recovery event.
    """

    with _GroupCluster(
        tmp_path,
        accounts=_ARB03_ACCOUNTS,
        instruments={account: (_V2_INSTRUMENT,) for account in _ARB03_ACCOUNTS},
        initial_states={"account-a": ("filled",), "account-b": ("filled",)},
        expected_orders={
            "account-a": ((_V2_INSTRUMENT, "2", "100", "buy-limit"),),
            "account-b": ((_V2_INSTRUMENT, "4", "100", "sell-limit"),),
        },
        rule_specs={
            "account-a": {_V2_INSTRUMENT: "2"},
            "account-b": {_V2_INSTRUMENT: "1"},
        },
    ) as cluster:
        snapshot = cluster.submit_group(
            _group_request(
                _GROUP_ARB03_FULL_FILL,
                cluster.metadata_reference_ns,
                (
                    ("leg-a", "account-a", Side.BUY, Decimal("2"), _V2_INSTRUMENT),
                    ("leg-b", "account-b", Side.SELL, Decimal("6"), _V2_INSTRUMENT),
                ),
            )
        )
        assert snapshot.state is GroupOrderState.PAIRED
        assert snapshot.error_code is None
        assert snapshot.residual_base_units == Decimal("0")
        assert len(snapshot.legs) == 2
        assert len(snapshot.reservations) == 2
        assert tuple(item.account_ref for item in snapshot.reservations) == ("account-a", "account-b")

        leg_a = next(leg for leg in snapshot.legs if leg.leg_id == "leg-a")
        leg_b = next(leg for leg in snapshot.legs if leg.leg_id == "leg-b")

        assert leg_a.submitted_intent is not None
        assert leg_a.submitted_intent.instrument == _V2_INSTRUMENT
        assert leg_a.submitted_intent.quantity == Decimal("2")
        first = leg_a.child_status
        assert first is not None
        assert first.state is ExecutionState.FILLED
        assert first.filled_quantity == Decimal("2")
        assert first.average_price == Decimal("100")
        assert first.cumulative_commission == Decimal("-0.05")
        assert first.cumulative_commission_currency == "USD"
        assert first.trade_count == 1
        assert first.order_revision == 1
        assert first.provider_order_id is not None
        assert leg_a.resolution_receipt is not None
        resolution_a = leg_a.resolution_receipt
        assert resolution_a.resolution_kind == "TERMINAL_EXPOSURE_RESOLVED"
        assert resolution_a.final_state is ExecutionState.FILLED
        assert resolution_a.requested_quantity == Decimal("2")
        assert resolution_a.filled_quantity == Decimal("2")
        assert resolution_a.trade_count == 1
        assert resolution_a.dispatch_latch_active is False

        # The hedge is resized from the requested 6 down to base 4 (= 2 x 2).
        assert leg_b.submitted_intent is not None
        assert leg_b.submitted_intent.instrument == _V2_INSTRUMENT
        assert leg_b.submitted_intent.quantity == Decimal("4.000")
        assert leg_b.submitted_intent.quantity != Decimal("6")
        second = leg_b.child_status
        assert second is not None
        assert second.state is ExecutionState.FILLED
        assert second.filled_quantity == Decimal("4")
        assert second.average_price == Decimal("100")
        assert second.cumulative_commission == Decimal("-0.05")
        assert second.trade_count == 1
        assert leg_b.resolution_receipt is not None
        resolution_b = leg_b.resolution_receipt
        assert resolution_b.resolution_kind == "TERMINAL_EXPOSURE_RESOLVED"
        assert resolution_b.final_state is ExecutionState.FILLED
        assert resolution_b.requested_quantity == Decimal("4")
        assert resolution_b.filled_quantity == Decimal("4")
        assert resolution_b.trade_count == 1
        assert resolution_b.dispatch_latch_active is False

        for account_ref in _ARB03_ACCOUNTS:
            status = cluster.status(account_ref)
            assert status[4] == (), f"unconsumed provider expectations on {account_ref}"

    persisted_groups = SqliteOrderGroupStore(cluster.coordinator_paths["groups"])
    try:
        persisted = persisted_groups.get(_PORTFOLIO, _GROUP_ARB03_FULL_FILL)
        assert persisted == snapshot
        events = persisted_groups.events(_PORTFOLIO, _GROUP_ARB03_FULL_FILL)
    finally:
        persisted_groups.close()
    assert sum(event.event_type == "GROUP_PAIRED" for event in events) == 1
    assert not any(event.event_type == "GROUP_RECOVERY_REQUIRED" for event in events)
    sized = tuple(event for event in events if event.event_type == "HEDGE_LEG_SIZED")
    assert len(sized) == 1
    assert sized[0].payload["quantity"] == "4.000"
    assert sized[0].payload["first_filled_quantity"] == "2"
    paired = next(event for event in events if event.event_type == "GROUP_PAIRED")
    assert paired.payload["first_filled_quantity"] == "2"
    assert paired.payload["second_filled_quantity"] == "4.000"
    assert paired.payload["residual_base_units"] == "0"

    execution_scope_a = _execution_scope("account-a")
    execution_scope_b = _execution_scope("account-b")
    intent_a = group_leg_intent_id(_GROUP_ARB03_FULL_FILL, "leg-a")
    intent_b = group_leg_intent_id(_GROUP_ARB03_FULL_FILL, "leg-b")
    store_a = SqliteExecutionStore(cluster.account_paths["account-a"]["execution"])
    try:
        record_a = store_a.get(intent_a, scope=execution_scope_a)
        assert record_a is not None
        assert record_a.state is ExecutionState.FILLED
        assert record_a.filled_quantity == Decimal("2")
        assert record_a.average_price == Decimal("100")
        assert record_a.cumulative_commission == Decimal("-0.05")
        assert record_a.provider_order_id is not None
        assert record_a.dispatch_attempts == 1
        assert record_a.unknown_reason is None
        assert record_a.review_required is False
        events_a = _leg_outbox(store_a, execution_scope_a, intent_a)
        assert tuple(event.event_type for event in events_a) == (
            "intent_recorded",
            "intent_admitted",
            "dispatch_claimed",
            "provider_observation",
        )
        assert events_a[3].state is ExecutionState.FILLED
        assert events_a[3].payload["filled_quantity"] == "2"
    finally:
        store_a.close()

    store_b = SqliteExecutionStore(cluster.account_paths["account-b"]["execution"])
    try:
        record_b = store_b.get(intent_b, scope=execution_scope_b)
        assert record_b is not None
        assert record_b.state is ExecutionState.FILLED
        assert record_b.filled_quantity == Decimal("4")
        assert record_b.average_price == Decimal("100")
        assert record_b.cumulative_commission == Decimal("-0.05")
        assert record_b.provider_order_id is not None
        assert record_b.dispatch_attempts == 1
        assert record_b.unknown_reason is None
        assert record_b.review_required is False
        events_b = _leg_outbox(store_b, execution_scope_b, intent_b)
        assert tuple(event.event_type for event in events_b) == (
            "intent_recorded",
            "intent_admitted",
            "dispatch_claimed",
            "provider_observation",
        )
        assert events_b[3].state is ExecutionState.FILLED
        assert events_b[3].payload["filled_quantity"] == "4.000"
    finally:
        store_b.close()

    assert _risk_legs(cluster.account_paths, "account-a", _GROUP_ARB03_FULL_FILL) == (
        ("leg-a", True, True),
    )
    assert _risk_legs(cluster.account_paths, "account-b", _GROUP_ARB03_FULL_FILL) == (
        ("leg-b", True, True),
    )
    for account_ref in _ARB03_ACCOUNTS:
        _assert_holds_resolved(cluster.account_paths, account_ref, _GROUP_ARB03_FULL_FILL)
        _assert_provider_writes(Path(cluster.account_paths[account_ref]["provider"]), 1)


def test_arb03_hedge_leg_partial_cancel_requires_recovery(tmp_path: Path) -> None:
    """Hedge-leg IOC partial cancel leaves residual base and requires recovery.

    The first leg cancels with 1.5/2 filled (base 3); the hedge is sized to 3
    and cancels after a 2-unit partial fill (base 2). The 1-base shortfall must
    surface as RECOVERY_REQUIRED / hedge_residual_unresolved with both leg
    resolutions recorded and no oversell of the first-leg exposure.
    """

    with _GroupCluster(
        tmp_path,
        accounts=_ARB03_ACCOUNTS,
        instruments={account: (_V2_INSTRUMENT,) for account in _ARB03_ACCOUNTS},
        initial_states={"account-a": ("cancelled:1.5",), "account-b": ("cancelled:2",)},
        expected_orders={
            "account-a": ((_V2_INSTRUMENT, "2", "100", "buy-limit"),),
            "account-b": ((_V2_INSTRUMENT, "3", "100", "sell-limit"),),
        },
        rule_specs={
            "account-a": {_V2_INSTRUMENT: "2"},
            "account-b": {_V2_INSTRUMENT: "1"},
        },
    ) as cluster:
        snapshot = cluster.submit_group(
            _group_request(
                _GROUP_ARB03_HEDGE_PARTIAL,
                cluster.metadata_reference_ns,
                (
                    ("leg-a", "account-a", Side.BUY, Decimal("2"), _V2_INSTRUMENT),
                    ("leg-b", "account-b", Side.SELL, Decimal("4"), _V2_INSTRUMENT),
                ),
            )
        )
        assert snapshot.state is GroupOrderState.RECOVERY_REQUIRED
        assert snapshot.error_code == "hedge_residual_unresolved"
        assert snapshot.residual_base_units == Decimal("1")
        assert len(snapshot.legs) == 2
        assert len(snapshot.reservations) == 2
        assert tuple(item.account_ref for item in snapshot.reservations) == ("account-a", "account-b")

        leg_a = next(leg for leg in snapshot.legs if leg.leg_id == "leg-a")
        leg_b = next(leg for leg in snapshot.legs if leg.leg_id == "leg-b")

        assert leg_a.submitted_intent is not None
        assert leg_a.submitted_intent.quantity == Decimal("2")
        first = leg_a.child_status
        assert first is not None
        assert first.state is ExecutionState.CANCELLED
        assert first.filled_quantity == Decimal("1.5")
        assert first.trade_count == 1
        resolution_a = leg_a.resolution_receipt
        assert resolution_a is not None
        assert resolution_a.resolution_kind == "TERMINAL_EXPOSURE_RESOLVED"
        assert resolution_a.final_state is ExecutionState.CANCELLED
        assert resolution_a.filled_quantity == Decimal("1.5")

        # The hedge was sized to base 3 (1.5 x 2) from the requested 4.
        assert leg_b.submitted_intent is not None
        assert leg_b.submitted_intent.quantity == Decimal("3.000")
        second = leg_b.child_status
        assert second is not None
        assert second.state is ExecutionState.CANCELLED
        assert second.filled_quantity == Decimal("2")
        assert second.average_price == Decimal("100")
        assert second.cumulative_commission == Decimal("-0.05")
        assert second.trade_count == 1
        assert second.order_revision == 1
        assert second.reason_code is None
        assert second.provider_order_id is not None
        assert leg_b.resolution_receipt is not None
        resolution_b = leg_b.resolution_receipt
        assert resolution_b.resolution_kind == "TERMINAL_EXPOSURE_RESOLVED"
        assert resolution_b.final_state is ExecutionState.CANCELLED
        assert resolution_b.requested_quantity == Decimal("3")
        assert resolution_b.filled_quantity == Decimal("2")
        assert resolution_b.trade_count == 1
        assert resolution_b.dispatch_latch_active is False

        for account_ref in _ARB03_ACCOUNTS:
            status = cluster.status(account_ref)
            assert status[4] == (), f"unconsumed provider expectations on {account_ref}"

    persisted_groups = SqliteOrderGroupStore(cluster.coordinator_paths["groups"])
    try:
        persisted = persisted_groups.get(_PORTFOLIO, _GROUP_ARB03_HEDGE_PARTIAL)
        assert persisted == snapshot
        events = persisted_groups.events(_PORTFOLIO, _GROUP_ARB03_HEDGE_PARTIAL)
    finally:
        persisted_groups.close()
    assert any(event.event_type == "GROUP_RECOVERY_REQUIRED" for event in events)
    assert not any(event.event_type == "GROUP_PAIRED" for event in events)
    sized = tuple(event for event in events if event.event_type == "HEDGE_LEG_SIZED")
    assert len(sized) == 1
    assert sized[0].payload["quantity"] == "3.000"
    resolved_b_events = tuple(
        event
        for event in events
        if event.event_type == "GROUP_DISPATCH_RESOLUTION_RECORDED"
        and event.payload.get("leg_id") == "leg-b"
    )
    assert len(resolved_b_events) == 1
    assert resolved_b_events[0].payload["resolution_kind"] == "TERMINAL_EXPOSURE_RESOLVED"

    execution_scope_a = _execution_scope("account-a")
    execution_scope_b = _execution_scope("account-b")
    intent_a = group_leg_intent_id(_GROUP_ARB03_HEDGE_PARTIAL, "leg-a")
    intent_b = group_leg_intent_id(_GROUP_ARB03_HEDGE_PARTIAL, "leg-b")
    store_a = SqliteExecutionStore(cluster.account_paths["account-a"]["execution"])
    try:
        record_a = store_a.get(intent_a, scope=execution_scope_a)
        assert record_a is not None
        assert record_a.state is ExecutionState.CANCELLED
        assert record_a.filled_quantity == Decimal("1.5")
        assert record_a.dispatch_attempts == 1
        assert record_a.unknown_reason is None
        assert record_a.review_required is False
        events_a = _leg_outbox(store_a, execution_scope_a, intent_a)
        assert tuple(event.event_type for event in events_a) == (
            "intent_recorded",
            "intent_admitted",
            "dispatch_claimed",
            "provider_observation",
            "provider_observation",
        )
        assert events_a[3].state is ExecutionState.PARTIALLY_FILLED
        assert events_a[4].state is ExecutionState.CANCELLED
        assert events_a[3].payload["filled_quantity"] == "1.5"
        assert events_a[3].payload == events_a[4].payload
    finally:
        store_a.close()

    store_b = SqliteExecutionStore(cluster.account_paths["account-b"]["execution"])
    try:
        record_b = store_b.get(intent_b, scope=execution_scope_b)
        assert record_b is not None
        assert record_b.state is ExecutionState.CANCELLED
        assert record_b.filled_quantity == Decimal("2")
        assert record_b.average_price == Decimal("100")
        assert record_b.cumulative_commission == Decimal("-0.05")
        assert record_b.provider_order_id is not None
        assert record_b.dispatch_attempts == 1
        assert record_b.unknown_reason is None
        assert record_b.review_required is False
        events_b = _leg_outbox(store_b, execution_scope_b, intent_b)
        assert tuple(event.event_type for event in events_b) == (
            "intent_recorded",
            "intent_admitted",
            "dispatch_claimed",
            "provider_observation",
            "provider_observation",
        )
        assert events_b[3].state is ExecutionState.PARTIALLY_FILLED
        assert events_b[4].state is ExecutionState.CANCELLED
        assert events_b[3].payload["filled_quantity"] == "2"
        assert events_b[3].payload == events_b[4].payload
    finally:
        store_b.close()

    assert _risk_legs(cluster.account_paths, "account-a", _GROUP_ARB03_HEDGE_PARTIAL) == (
        ("leg-a", True, True),
    )
    assert _risk_legs(cluster.account_paths, "account-b", _GROUP_ARB03_HEDGE_PARTIAL) == (
        ("leg-b", True, True),
    )
    for account_ref in _ARB03_ACCOUNTS:
        _assert_holds_resolved(cluster.account_paths, account_ref, _GROUP_ARB03_HEDGE_PARTIAL)
        _assert_provider_writes(Path(cluster.account_paths[account_ref]["provider"]), 1)
