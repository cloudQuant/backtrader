"""Cross-repo INTEGRATION_SIM tests uniting Backtrader Track 1 with SDK Track 2 (T-R2-01..09).

Evidence level: INTEGRATION_SIM (real SQLite journals and real SDK modules across
bt_api_base, bt_api_gateway, bt_api_risk, bt_api_execution, bt_api_monitor,
bt_api_py, and backtrader; zero network sockets and zero real exchange accounts).
"""

from __future__ import annotations

import ast
import datetime
import hashlib
import json
import pathlib
import sqlite3
import sys
import uuid
from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backtrader.brokers.gateway_btapi_broker import GatewayBtApiBroker
from backtrader.stores._btapi_errors import LiveCompositionError
from backtrader.stores.btapi_composition import (
    FORBIDDEN_DIRECT_SUBPACKAGES,
    LiveRunBinding,
    parse_gateway_readiness_proof,
    validate_gateway_readiness_proof,
)

NOW_NS = 1_700_000_000_000_000_000
SHARED_KEY = b"t" * 32


def _sha(value: object) -> str:
    raw = json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(raw.encode("ascii")).hexdigest()


def test_backtrader_package_maintains_zero_direct_optional_sdk_imports():
    """Confirm backtrader/ still has 0 direct imports of the 6 optional SDK service packages."""
    bt_root = pathlib.Path(__file__).resolve().parents[3] / "backtrader"
    forbidden = set(FORBIDDEN_DIRECT_SUBPACKAGES)
    violations: list[str] = []
    for py_file in bt_root.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8", errors="ignore"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in forbidden:
                        violations.append(f"{py_file.relative_to(bt_root)}:{alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                top = node.module.split(".")[0]
                if top in forbidden:
                    violations.append(f"{py_file.relative_to(bt_root)}:{node.module}")
    assert violations == []


def test_track2_gateway_issuer_to_sdk_client_to_backtrader_broker_checkpoint1():
    """Real bt_api_gateway issuer -> bt_api_py client -> BT composition & GatewayBtApiBroker."""
    from bt_api_gateway.readiness_proof import (
        STRICT_STRATEGY_DEFAULT_OPERATIONS,
        GatewayReadinessProofIssuer,
    )
    from bt_api_py.gateway_readiness_client import GatewayReadinessClient

    issuer = GatewayReadinessProofIssuer(
        gateway_service_id="gw-svc-prod-sim",
        gateway_instance_id="gw-inst-01",
        gateway_scope_ref="scope-ctp-simnow",
        risk_service_ref="risk-svc-01",
        risk_protocol_version="2.0",
        execution_service_ref="exec-svc-01",
        execution_protocol_version="2.0",
        monitor_service_ref="mon-svc-01",
        monitor_protocol_version="1.0",
        runtime_service_ref="rt-svc-01",
        issuer_key_id="gw-hmac-v1",
        shared_key=SHARED_KEY,
    )

    att = issuer.issue_attestation(
        account_scope="acct-simnow-01",
        strategy_scope="strat-007-ma",
        route="CTP___FUTURE",
        strategy_principal_operations=STRICT_STRATEGY_DEFAULT_OPERATIONS,
        risk_state="READY",
        execution_state="READY",
        last_acked_heartbeat_age_ms=80,
        monitor_stop_new_active=False,
        registered_run_id="run-track2-001",
        now_ns=NOW_NS,
    )
    client = GatewayReadinessClient(
        lambda: att.to_mapping(),
        expected_account_scope="acct-simnow-01",
        expected_strategy_scope="strat-007-ma",
        expected_route="CTP___FUTURE",
        expected_run_id="run-track2-001",
        shared_key=SHARED_KEY,
        require_attestation=True,
        clock_ns=lambda: NOW_NS + 1_000,
    )
    base_proof = client.verify_ready()

    # Backtrader composition accepts bt_api_base.GatewayReadinessProof directly via to_mapping()
    binding = LiveRunBinding(
        mode="gateway",
        position_mode="dual_side",
        market_data_only=False,
        account_scope="acct-simnow-01",
        strategy_scope="strat-007-ma",
        route="CTP___FUTURE",
    )
    bt_proof = validate_gateway_readiness_proof(
        base_proof,
        expected_binding=binding,
        expected_run_id="run-track2-001",
        now_ns=NOW_NS + 2_000,
    )
    assert parse_gateway_readiness_proof(base_proof) == bt_proof

    # GatewayBtApiBroker Checkpoint 1 directly consumes bt_api_base.GatewayReadinessProof via store
    broker = object.__new__(GatewayBtApiBroker)
    broker._run_binding = binding
    broker.p = SimpleNamespace(market_data_only=False)
    broker.store = SimpleNamespace(gateway_readiness_proof=base_proof)
    broker._expected_run_id = "run-track2-001"
    broker._require_readiness_proof = True
    broker._strict_gateway_no_direct_path = True

    checked = broker.check_gateway_dispatch_preconditions(
        action="open",
        now_ns=NOW_NS + 3_000,
    )
    assert checked == bt_proof

    # Proof allowing DIRECT_PATH bypass is refused at Checkpoint 1
    bypass_proof = issuer.issue_proof(
        account_scope="acct-simnow-01",
        strategy_scope="strat-007-ma",
        route="CTP___FUTURE",
        strategy_principal_operations=STRICT_STRATEGY_DEFAULT_OPERATIONS,
        risk_state="READY",
        execution_state="READY",
        execution_direct_path_disabled=False,
        last_acked_heartbeat_age_ms=80,
        monitor_stop_new_active=False,
        registered_run_id="run-track2-001",
        now_ns=NOW_NS,
    )
    broker.store = SimpleNamespace(gateway_readiness_proof=bypass_proof)
    with pytest.raises(LiveCompositionError) as bypass_exc:
        broker.check_gateway_dispatch_preconditions(action="open", now_ns=NOW_NS + 3_000)
    assert bypass_exc.value.code == "GATEWAY_DIRECT_PATH_BYPASS_FORBIDDEN"

    # Risk outage blocks open, while delegated cancel remains allowed (D62S-04 / D62S-09b)
    outage_proof = issuer.issue_proof(
        account_scope="acct-simnow-01",
        strategy_scope="strat-007-ma",
        route="CTP___FUTURE",
        strategy_principal_operations=STRICT_STRATEGY_DEFAULT_OPERATIONS,
        risk_state="UNREACHABLE",
        execution_state="READY",
        last_acked_heartbeat_age_ms=80,
        monitor_stop_new_active=False,
        registered_run_id="run-track2-001",
        now_ns=NOW_NS,
    )
    broker.store = SimpleNamespace(gateway_readiness_proof=outage_proof)
    with pytest.raises(LiveCompositionError) as outage_exc:
        broker.check_gateway_dispatch_preconditions(action="open", now_ns=NOW_NS + 3_000)
    assert outage_exc.value.code == "GATEWAY_READINESS_UNREACHABLE"
    cancel_checked = broker.check_gateway_dispatch_preconditions(
        action="cancel", now_ns=NOW_NS + 3_000
    )
    assert cancel_checked is not None
    assert cancel_checked.delegated_cancel_enabled is True


def test_track2_execution_pass_v2_and_forbid_direct_path_end_to_end():
    """Real PASS v2 schedule + ExecutionOrderRouter forbid_direct_path=True (T-R2-09)."""
    from bt_api_base.frozen_algorithm_plan import algorithm_plan_digest
    from bt_api_base.market_protocol import MarketInstrumentKey
    from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
    from bt_api_execution.algorithm_config import ScheduleRegistry
    from bt_api_execution.algorithm_schedule import ScheduleFacts
    from bt_api_execution.frozen_algorithm_plan import validate_algorithm_plan
    from bt_api_py._contracts.models import OrderRequest, OrderType, Side
    from bt_api_py.execution_routing import (
        ExecutionOrderRouter,
        ExecutionRoutingOutcome,
        install_execution_routing_tables,
        parse_execution_routing,
    )
    from bt_api_py.gateway_direct_client import (
        GatewayClientRoute,
        GatewayCommandBinding,
        build_gateway_order_intent,
    )

    instrument = MarketInstrumentKey("ctp", "SHFE", "simnow", "future", "rb2701", "rb2701")
    registry = ScheduleRegistry()

    # PASS v2 market order schedule & frozen plan validate cleanly
    market_cfg = {
        "class": "PASS",
        "version": 2,
        "binding": {
            "deadline_ns": 1000,
            "quantity_step": "1",
            "parent_limit": None,
            "price_step": "0.5",
            "retry_limit": 0,
        },
        "params": {"order_type": "market"},
    }
    sched = registry.create(market_cfg)
    decision = sched.decide(
        ScheduleFacts(
            now_ns=100,
            deadline_ns=1000,
            available=Decimal("3"),
            step=Decimal("1"),
            parent_limit=None,
            price_step=Decimal("0.5"),
            plan_index=0,
            retry_limit=0,
            retry_used=0,
            children=(),
            session_open=True,
            day_ready=True,
            facts_complete=True,
            authority_valid=True,
        )
    )
    assert decision.reason == "READY"
    assert decision.proposal is not None
    assert decision.proposal.quantity == Decimal("3")
    assert decision.proposal.limit_price is None

    plan = {
        "schema_version": 1,
        "plan_version": "plan-v2",
        "build_id": "build-track2",
        "schedule": sched.snapshot(),
    }
    spec = {
        "expires_at_ns": 1000,
        "plan_version": "plan-v2",
        "plan_digest": algorithm_plan_digest(plan),
        "order_type": "market",
        "limit_price": None,
    }
    validate_algorithm_plan(plan, spec, registry=registry, build_id="build-track2")

    # ExecutionOrderRouter forbid_direct_path=True blocks unmatched DIRECT_PATH bypass
    routing_cfg = parse_execution_routing(
        {
            "schema_version": 2,
            "algorithm_build_id": "build-track2",
            "component": "exec-inst-1",
            "account_ref": "acct-1",
            "strategy_ref": "strat-1",
            "execution_domain_ref": "dom-1",
            "grant_revision": "grant-v1",
            "delegation": {"delegation_id": "del-1", "principal_ref": "exec-p"},
            "instruments": [instrument.to_dict()],
            "rules": [
                {
                    "id": "limit-only-rule",
                    "match": {"instrument": instrument.to_dict(), "order_types": ["limit"]},
                    "scheme": {"name": "pass-v1", "version": 1},
                    "algorithm": {"class": "PASS", "version": 2, "params": {}},
                    "deadline": {"kind": "absolute", "at": "2099-12-31T15:00:00Z"},
                    "time_in_force": "DAY",
                    "trading_day": "20261123",
                    "schedule_binding": {
                        "quantity_step": "1",
                        "price_step": "0.5",
                        "retry_limit": 0,
                    },
                }
            ],
        }
    )
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.execute("BEGIN")
    install_execution_routing_tables(db)
    db.execute("COMMIT")
    router = ExecutionOrderRouter(
        db=db,
        config=routing_cfg,
        execution_port=object(),
        risk_selected=True,
        forbid_direct_path=True,
    )
    scope = WireScope(
        execution_domain_ref="dom-1",
        account_ref="acct-1",
        strategy_ref="strat-1",
        run_id="run-1",
    )
    route = GatewayClientRoute(
        mount="broker.direct_write",
        service_id="gw-svc",
        instance_id="gw-inst",
        scope_ref="scope-1",
        scope=scope,
        identity=WireIdentity(
            role=WireRole.STRATEGY_CLIENT,
            principal_ref="strat-p",
            actor_ref="strat-1",
        ),
    )
    intent = build_gateway_order_intent(
        GatewayCommandBinding("j-1", "acct-1", "strat-1", "strat-p"),
        route,
        OrderRequest(
            symbol="rb2701",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
            price=None,
            account_id="acct-1",
            client_order_id="cli-1",
            idempotency_key="mkt-unmatched-1",
            exchange_id="SHFE",
            offset="open",
        ),
        ttl_seconds=5.0,
    )
    res = router.route(intent)
    assert res.outcome is ExecutionRoutingOutcome.EXECUTION_REJECTED
    assert res.code == "GATEWAY_DIRECT_PATH_BYPASS_FORBIDDEN"


def test_track2_gateway_v2_first_reserve_and_r05_cutpoint_and_five_component_health(tmp_path):
    """Real Gateway SQLite journal v2 first-reserve + R-05 order-cut + Monitor health + Runtime contract."""
    from bt_api_base.direct_write_protocol import DirectExecutionEventKind, DirectOrderStatus
    from bt_api_base.gateway_delegation_protocol import GatewayDelegatedCommand
    from bt_api_base.gateway_direct_protocol import gateway_payload_digest
    from bt_api_base.gateway_execution_stream_protocol import GatewayExecutionObservation
    from bt_api_base.gateway_risk_first_reserve_v2 import (
        GatewayRiskFirstReserveRequestV2,
        risk_first_reserve_nonce_digest,
    )
    from bt_api_base.market_protocol import MarketInstrumentKey
    from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
    from bt_api_execution.risk_child_bridge import ExecutionRiskChildBridge
    from bt_api_gateway.active_order_cutpoint import build_gateway_order_cut_snapshot
    from bt_api_gateway.direct_command_journal import GatewayDirectCommandJournal
    from bt_api_gateway.direct_delegation import GatewayDelegateGrant, authorize_delegated_command
    from bt_api_gateway.risk_v2_first_reserve_coordinator import GatewayRiskFirstReserveV2Coordinator
    from bt_api_gateway.session_guard import LocalAccountSessionGuard
    from bt_api_monitor.five_component_health import (
        ComponentObservation,
        evaluate_five_component_health,
    )
    from bt_api_py.direct_api_assembly import DirectApiAssembly, DirectApiAssemblyError
    from bt_api_py.gateway_strategy_config import (
        STRICT_FIVE_COMPONENT_PROFILE,
        GatewayStrategyConfigError,
        parse_gateway_strategy_config,
    )
    from bt_api_risk.pretrade.v2_child_coordinator import verify_gateway_v2_first_reserve_proof

    instrument = MarketInstrumentKey("ctp", "SHFE", "simnow", "future", "rb2701", "rb2701")

    # 1. Gateway v2 first-reserve proof verified by bt_api_risk verifier (T-R2-03)
    guard_dir = tmp_path / "guard"
    guard_dir.mkdir()
    guard = LocalAccountSessionGuard(guard_dir, "acct-simnow", "owner-1")
    generation = guard.acquire()
    journal = GatewayDirectCommandJournal.create(
        tmp_path / "gw_db", "acct-simnow", generation=generation
    )
    journal.enable_controls(guard)
    journal.enable_strategy_ledger(guard)
    journal.enable_account_extensions(guard)
    coordinator = GatewayRiskFirstReserveV2Coordinator(journal, guard)

    @contextmanager
    def _fence():
        yield

    try:
        payload = {
            "account_id": "acct-simnow",
            "idempotency_key": "integ-v2-1",
            "symbol": "rb2701",
            "exchange_id": "SHFE",
            "side": "buy",
            "offset": "open",
            "volume": 1,
            "price": "3500",
        }
        identity = WireIdentity(
            role=WireRole.SERVICE, principal_ref="risk-p", actor_ref="risk-a"
        )
        scope = WireScope(
            execution_domain_ref="dom-1",
            account_ref="acct-simnow",
            strategy_ref="strat-1",
            run_id="run-1",
        )
        cmd = GatewayDelegatedCommand(
            account_scope="acct-simnow",
            strategy_scope="strat-1",
            execution_domain_ref="dom-1",
            actor_principal="risk-p",
            actor_ref="risk-a",
            actor_kind="risk",
            run_id="run-1",
            request_key="integ-v2-1",
            payload_digest=gateway_payload_digest(payload),
            instrument=instrument,
            grant_revision="grant-v1",
        )
        grant = GatewayDelegateGrant(
            identity=identity,
            account_scope="acct-simnow",
            strategy_scope="strat-1",
            execution_domain_ref="dom-1",
            actor_kind="risk",
            revision="grant-v1",
            instruments=frozenset({instrument}),
            operations=frozenset({"direct.reserve", "direct.dispatch"}),
        )
        permit = authorize_delegated_command(
            SimpleNamespace(
                identity=identity, scope=scope, principal_ref="risk-p", registration_id="reg-1"
            ),
            grant,
            cmd,
            "direct.reserve",
            payload,
            registry_recheck=lambda _: True,
            current_grant=lambda: grant,
            instrument_recheck=lambda i: i == instrument,
        )
        v2_req = GatewayRiskFirstReserveRequestV2(
            command=cmd,
            risk_service_id="risk-svc-1",
            risk_instance_id="risk-inst-1",
            strategy_principal="strat-p",
            risk_registration_id="reg-1",
            risk_service_epoch="epoch-1",
            risk_permit_id="perm-integ-1",
            risk_view_digest="ab" * 32,
            attempt_nonce_digest=risk_first_reserve_nonce_digest(b"m" * 32),
            requested_ttl_ms=5000,
        )
        v2_res = coordinator.reserve_first_v2(
            v2_req, payload, delegation_permit=permit, reservation_fence=_fence
        )
        verified = verify_gateway_v2_first_reserve_proof(v2_req, v2_res.to_mapping())
        assert verified.journal_id == journal.journal_id
        assert verified.reservation_id == v2_res.reservation_id
    finally:
        guard.release()

    # 2. Gateway R-05 order-cut snapshot shape (T-R2-06)
    obs = GatewayExecutionObservation(
        account_scope="acct-simnow",
        route="CTP___FUTURE",
        trading_day="20261123",
        instrument=instrument,
        kind=DirectExecutionEventKind.ORDER,
        side="sell",
        offset="open",
        order_quantity="1",
        filled_quantity="0",
        limit_price="3500",
        status=DirectOrderStatus.ACCEPTED,
        native_identity_digest=_sha("ord-1"),
        identity_key_digests=(_sha(["ref", "ord-1"]),),
        venue_key_digest=None,
    )
    cut = build_gateway_order_cut_snapshot(
        account_scope="acct-simnow",
        journal_id="j-1",
        owner_generation="gen-1",
        fact_epoch="11" * 32,
        fact_watermark=1,
        source_binding_ref="22" * 32,
        current_session_trading_day="20261123",
        registration_id="reg-1",
        service_epoch="srv-epoch-1",
        query_observations=(obs,),
    )
    assert cut.header["query_row_count"] == 1

    # 3. Execution W2 bridge + strict profile + strict direct guard (T-R2-01, T-R2-05, T-R2-07)
    trace: list[str] = []
    bridge = ExecutionRiskChildBridge(
        SimpleNamespace(
            reserve_parent=lambda p: (trace.append("risk_parent"), {"status": "RESERVED"})[1]
        )
    )
    _, outcome = bridge.commit_and_reserve_parent(
        parent_ref="p-1",
        commit_parent=lambda: (trace.append("exec_commit"), {"ok": True})[1],
        risk_payload={"parent_ref": "p-1"},
    )
    assert outcome.status == "RESERVED"
    assert trace == ["exec_commit", "risk_parent"]

    with pytest.raises(GatewayStrategyConfigError, match="GATEWAY_RISK_REQUIRED"):
        parse_gateway_strategy_config(
            {"risk": "none", "execution": "none", "exchange_name": "CTP___FUTURE"},
            profile=STRICT_FIVE_COMPONENT_PROFILE,
        )

    with pytest.raises(DirectApiAssemblyError) as dir_exc:
        DirectApiAssembly.from_options(
            options={"market_runtime_factory": object()},
            exchange_kwargs={},
            execution_config={},
            api_factory=lambda **kw: kw,
            api=None,
            expected_exchange_names=("CTP___FUTURE",),
            execution_option_keys=(),
            market_data_only=True,
            strict_direct=True,
        )
    assert dir_exc.value.code == "DIRECT_SERVICE_KEY_FORBIDDEN"

    # 4. Monitor five-component health + Runtime Windows B-class supervision (T-R2-08)
    def comp(name: str):
        return ComponentObservation(
            component=name,
            service_ref=f"{name}-svc",
            protocol_version="1.0",
            state="READY",
            observed_at_ns=NOW_NS - 1000,
            max_age_ns=30_000_000_000,
        )

    health = evaluate_five_component_health(
        gateway=comp("gateway"),
        risk=comp("risk"),
        execution=comp("execution"),
        monitor=comp("monitor"),
        runtime=comp("runtime"),
        now_ns=NOW_NS,
        monitor_required=True,
        last_acked_heartbeat_age_ms=50,
    )
    assert health.all_ready is True

    # Load bt_api_runtime from local checkout if not site-installed
    rt_contracts = pathlib.Path(r"D:\bt_api_py\bt_api\bt_api_runtime\contracts\src")
    rt_src = pathlib.Path(r"D:\bt_api_py\bt_api\bt_api_runtime\runtime\src")
    if rt_contracts.exists() and rt_src.exists():
        for p in (str(rt_contracts), str(rt_src)):
            if p not in sys.path:
                sys.path.insert(0, p)
        from bt_api_runtime.supervision.stop_file import StopFileChannel
        from bt_api_runtime.supervision.windows_b_contract import (
            WindowsStopFileStrategyController,
        )

        class _Clock:
            def utc_now(self) -> str:
                return datetime.datetime(2026, 11, 23, 12, 0, 0, tzinfo=datetime.UTC).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )

        ctrl = WindowsStopFileStrategyController(StopFileChannel(str(tmp_path), clock=_Clock()))
        stop_res = ctrl.request_graceful_stop(
            unit_name="ctp_007",
            strategy_uuid=str(uuid.uuid4()),
            run_id=str(uuid.uuid4()),
            command_id=str(uuid.uuid4()),
        )
        assert stop_res.delivered is True
        assert ctrl.on_runtime_control_disconnect() == "keep_running"
