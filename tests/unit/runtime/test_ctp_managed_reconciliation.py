from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from backtrader_runtime.ctp_managed_reconciliation import (
    CtpManagedOrderState,
    observe_ctp_managed_order,
)
from backtrader_runtime.ctp_simulation_execution import (
    CtpSimulationCancelRequestSnapshot,
    CtpSimulationOrderSnapshot,
    CtpSimulationPositionSnapshot,
    CtpSimulationQueryResult,
    CtpSimulationSessionIdentity,
    CtpSimulationTradeSnapshot,
    CtpSimulationWriteRequest,
)


RUNTIME_ORDER_ID = "managed-order-41-001"
REGISTRATION_DIGEST = "a" * 64


class _FixtureVerifier:
    """Fake only: prove the classifier consumes the injected verifier seam."""

    def verify(self, query_kind, result, *, expected_identity, registration_digest):
        return (
            result.native_evidence == ("verified-fixture", query_kind)
            and result.identity == expected_identity
            and registration_digest == REGISTRATION_DIGEST
        )


@pytest.fixture
def identity():
    return CtpSimulationSessionIdentity(
        environment="simnow",
        sdk_profile="config_front_pair",
        td_front="tcp://trade.simnow.test:10001",
        md_front="tcp://market.simnow.test:10002",
        account_fingerprint_sha256="b" * 64,
        trading_day="20260924",
        connection_generation=7,
        production=False,
        native_gate_armed=True,
    )


def _result(kind, identity, records, *, complete=True, evidence=True):
    return CtpSimulationQueryResult(
        complete=complete,
        identity=identity,
        records=tuple(records),
        native_evidence=("verified-fixture", kind) if evidence else None,
    )


def _request():
    return CtpSimulationWriteRequest(
        action="SUBMIT",
        client_order_id=RUNTIME_ORDER_ID,
        instrument_id="rb2710",
        exchange_id="SHFE",
        side="BUY",
        quantity=5,
        limit_price=Decimal("3500"),
    )


def _order(*, status="OPEN", traded=0, client_order_id=RUNTIME_ORDER_ID):
    return CtpSimulationOrderSnapshot(
        client_order_id=client_order_id,
        instrument_id="rb2710",
        exchange_id="SHFE",
        side="BUY",
        quantity=5,
        limit_price=Decimal("3500"),
        traded_quantity=traded,
        status=status,
        order_ref="ref-001",
        order_sys_id="sys-001",
        front_id=3,
        session_id=9,
    )


def _positions(identity, *, quantity=0, kind="positions"):
    return _result(
        kind,
        identity,
        (
            CtpSimulationPositionSnapshot("rb2710", "SHFE", "BUY", quantity),
            CtpSimulationPositionSnapshot("rb2710", "SHFE", "SELL", 0),
        ),
    )


def _trade(quantity, *, trade_id="trade-001"):
    return CtpSimulationTradeSnapshot(
        client_order_id=RUNTIME_ORDER_ID,
        trade_id=trade_id,
        quantity=quantity,
        instrument_id="rb2710",
        exchange_id="SHFE",
        side="BUY",
    )


def _cancel(action_id="cancel-001", *, status="CANCELED"):
    return CtpSimulationCancelRequestSnapshot(
        action_id=action_id,
        client_order_id=RUNTIME_ORDER_ID,
        target_order_sys_id="sys-001",
        target_order_ref="ref-001",
        target_front_id=3,
        target_session_id=9,
        status=status,
    )


def _observe(identity, *, status="OPEN", traded=0, cancel_records=None, **overrides):
    orders = overrides.pop("orders", _result("orders", identity, (_order(status=status, traded=traded),)))
    trades = overrides.pop(
        "trades",
        _result("trades", identity, (_trade(traded),) if traded else ()),
    )
    positions = overrides.pop("positions", _positions(identity, quantity=traded))
    baseline = overrides.pop("baseline_positions", _positions(identity, kind="positions"))
    if cancel_records is None and "cancel_requests" not in overrides:
        cancel_query = None
        cancel_ids = ()
    elif "cancel_requests" in overrides:
        cancel_query = overrides.pop("cancel_requests")
        cancel_ids = overrides.pop("cancel_ids", ("cancel-001",))
    else:
        cancel_query = _result("cancel_requests", identity, cancel_records)
        cancel_ids = ("cancel-001",)
    return observe_ctp_managed_order(
        runtime_order_id=RUNTIME_ORDER_ID,
        request=_request(),
        expected_identity=identity,
        registration_digest=REGISTRATION_DIGEST,
        baseline_positions=baseline,
        orders=orders,
        trades=trades,
        positions=positions,
        verifier=_FixtureVerifier(),
        expected_cancel_action_ids=cancel_ids,
        cancel_requests=cancel_query,
    )


@pytest.mark.parametrize(
    ("status", "traded", "expected"),
    (
        ("OPEN", 0, CtpManagedOrderState.ACCEPTED),
        ("PARTIAL", 2, CtpManagedOrderState.PARTIALLY_FILLED),
        ("FILLED", 5, CtpManagedOrderState.FILLED),
        ("REJECTED", 0, CtpManagedOrderState.REJECTED),
    ),
)
def test_verified_complete_snapshots_classify_native_order_state(identity, status, traded, expected):
    observation = _observe(identity, status=status, traded=traded)

    assert observation.state is expected
    assert observation.observed is True
    assert observation.runtime_order_id == RUNTIME_ORDER_ID
    assert observation.account_fingerprint_sha256 == identity.account_fingerprint_sha256
    assert observation.trading_day == identity.trading_day
    assert observation.connection_generation == identity.connection_generation
    assert observation.traded_quantity == traded


def test_exact_cancel_snapshot_proves_terminal_cancel(identity):
    observation = _observe(
        identity,
        status="CANCELED",
        traded=2,
        cancel_records=(_cancel(),),
    )

    assert observation.state is CtpManagedOrderState.CANCELED
    assert observation.observed is True


@pytest.mark.parametrize("incomplete", (False, True))
def test_missing_or_non_query_result_stays_unknown(identity, incomplete):
    if incomplete:
        overrides = {"orders": _result("orders", identity, (_order(),), complete=False)}
    else:
        overrides = {"orders": None}
    observation = _observe(identity, **overrides)

    assert observation.state is CtpManagedOrderState.UNKNOWN
    assert observation.reason == "native_query_evidence_incomplete_or_unverified"


def test_unverified_snapshot_cannot_become_accepted(identity):
    orders = _result("orders", identity, (_order(),), evidence=False)

    observation = _observe(identity, orders=orders)

    assert observation.state is CtpManagedOrderState.UNKNOWN


@pytest.mark.parametrize(
    "stale",
    (
        lambda identity: replace(
            identity, connection_generation=identity.connection_generation + 1
        ),
        lambda identity: replace(identity, trading_day="20260923"),
        lambda identity: replace(identity, account_fingerprint_sha256="c" * 64),
    ),
)
def test_stale_generation_day_or_account_mismatch_stays_unknown(identity, stale):
    stale_identity = stale(identity)

    observation = _observe(identity, trades=_result("trades", stale_identity, ()))

    assert observation.state is CtpManagedOrderState.UNKNOWN


def test_duplicate_order_readback_stays_unknown(identity):
    observation = _observe(
        identity,
        orders=_result("orders", identity, (_order(), _order())),
    )

    assert observation.state is CtpManagedOrderState.UNKNOWN
    assert observation.reason == "native_order_readback_ambiguous"


def test_mismatched_order_identity_stays_unknown(identity):
    observation = _observe(
        identity,
        orders=_result("orders", identity, (_order(client_order_id="other-order"),)),
    )

    assert observation.state is CtpManagedOrderState.UNKNOWN
    assert observation.reason == "native_order_readback_mismatch"


def test_duplicate_trade_id_stays_unknown(identity):
    observation = _observe(
        identity,
        status="PARTIAL",
        traded=2,
        trades=_result("trades", identity, (_trade(1), _trade(1))),
    )

    assert observation.state is CtpManagedOrderState.UNKNOWN


def test_incomplete_position_scope_stays_unknown(identity):
    partial_positions = _result(
        "positions",
        identity,
        (CtpSimulationPositionSnapshot("rb2710", "SHFE", "BUY", 0),),
    )

    observation = _observe(identity, positions=partial_positions)

    assert observation.state is CtpManagedOrderState.UNKNOWN


def test_wrong_position_delta_stays_unknown(identity):
    observation = _observe(
        identity,
        status="PARTIAL",
        traded=2,
        positions=_positions(identity, quantity=1),
    )

    assert observation.state is CtpManagedOrderState.UNKNOWN
    assert observation.reason == "native_position_delta_mismatch"


def test_cancel_action_set_or_target_mismatch_stays_unknown(identity):
    wrong_target = replace(_cancel(), target_order_sys_id="different-sys")
    observation = _observe(
        identity,
        status="CANCELED",
        cancel_records=(wrong_target,),
    )

    assert observation.state is CtpManagedOrderState.UNKNOWN


def test_duplicate_cancel_action_readback_stays_unknown(identity):
    observation = _observe(
        identity,
        status="CANCELED",
        cancel_records=(_cancel(), _cancel()),
    )

    assert observation.state is CtpManagedOrderState.UNKNOWN


def test_cancel_request_rejected_keeps_exact_open_order_accepted(identity):
    observation = _observe(
        identity,
        status="OPEN",
        cancel_records=(_cancel(status="REJECTED"),),
    )

    assert observation.state is CtpManagedOrderState.ACCEPTED


def test_cancel_readback_must_be_present_for_expected_action(identity):
    observation = _observe(
        identity,
        status="CANCELED",
        cancel_requests=None,
    )

    assert observation.state is CtpManagedOrderState.UNKNOWN
