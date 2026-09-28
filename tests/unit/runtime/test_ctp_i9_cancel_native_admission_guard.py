"""Dependency-free tests for the I9 candidate's pre-field CANCEL gate."""

from types import SimpleNamespace

import pytest

from backtrader_runtime.ctp_i9_account_session_candidate import (
    CtpI9AccountSessionCandidateError,
    _native_field_after_admission,
)


def test_cancel_without_admission_rejects_before_native_field_factory():
    calls = []
    owner = object()
    candidate = SimpleNamespace(
        _native_call_admission=None,
        _owner=owner,
        _verify_native_call=lambda *_args: calls.append("verify"),
        _native_field_factory=lambda *_args: calls.append("field"),
    )

    with pytest.raises(
        CtpI9AccountSessionCandidateError,
        match="CANCEL requires final native-call admission",
    ):
        _native_field_after_admission(
            candidate,
            SimpleNamespace(operation="CANCEL"),
            {"OrderRef": "000000000001"},
        )

    assert calls == []


def test_cancel_admission_runs_before_native_field_factory():
    calls = []
    owner = object()

    def admission(received_owner, binding, verified):
        assert received_owner is owner
        assert verified is binding
        calls.append("admission")

    candidate = SimpleNamespace(
        _native_call_admission=admission,
        _owner=owner,
        _verify_native_call=lambda received_owner, binding: admission(
            received_owner, binding, binding
        ),
        _native_field_factory=lambda operation, payload: calls.append(
            ("field", operation, dict(payload))
        ),
    )
    binding = SimpleNamespace(operation="CANCEL")

    _native_field_after_admission(candidate, binding, {"OrderRef": "000000000001"})

    assert calls == [
        "admission",
        ("field", "CANCEL", {"OrderRef": "000000000001"}),
    ]
