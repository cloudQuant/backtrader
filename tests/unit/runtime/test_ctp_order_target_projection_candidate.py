"""Offline contract tests for the unregistered G5 target observation."""

from __future__ import annotations

import inspect
from datetime import datetime, timezone

import pytest

from backtrader_runtime.ctp_simulation_execution import CtpSimulationExecutionError
from backtrader_runtime.ctp_simulation_query_evidence import (
    CtpSimulationOrderTargetObservation,
    CtpTraderClientQueryEvidenceVerifier,
)


def test_order_target_api_accepts_no_caller_row_or_clock():
    parameters = inspect.signature(
        CtpTraderClientQueryEvidenceVerifier.verify_order_target
    ).parameters
    assert tuple(parameters) == (
        "self",
        "scope",
        "reservation",
        "native_query_evidence",
    )


def test_order_target_observation_is_explicitly_non_authorizing():
    descriptor = CtpSimulationOrderTargetObservation.authorizes_cancel
    assert descriptor.fget(None) is False

    with pytest.raises(CtpSimulationExecutionError) as exc_info:
        CtpSimulationOrderTargetObservation(
            registration_digest="a" * 64,
            reservation_digest="b" * 64,
            request_digest="c" * 64,
            source_digest="d" * 64,
            request_id=1,
            request_type="orders",
            account_fingerprint="e" * 16,
            trading_day="20260923",
            connection_generation=1,
            order_ref="000000000123",
            order_sys_id="offline-order-123",
            exchange_id="SHFE",
            front_id=17,
            session_id=19,
            quantity=2,
            traded_quantity=0,
            remaining_quantity=2,
            issued_monotonic_ns=10,
            expires_monotonic_ns=20,
            expires_at_utc=datetime.now(timezone.utc),
            _seal=object(),
            _issuer=object(),
        )

    assert exc_info.value.reason == "native_order_target_observation_unissued"
