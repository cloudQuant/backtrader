"""No-provider tests for the fixed MD diagnostic projection."""

from __future__ import annotations

import json

import pytest

from backtrader_runtime.ctp_sdk_market_readonly import CtpSdkMarketReadOnlyError
from backtrader_runtime.ctp_simnow_md_diagnostic import _close_projection, _emit


@pytest.mark.parametrize(
    ("close_state", "stop_returned", "join_pending"),
    [
        ("native_stop_method_unknown", False, False),
        ("native_stop_method_invalid", False, False),
        ("native_stop_receipt_unknown", True, False),
        ("native_stop_receipt_inconsistent", True, False),
        ("native_stop_incomplete", True, False),
        ("native_join_pending", True, True),
        ("native_join_state_unknown", True, False),
        ("stop_failed", False, False),
    ],
)
def test_incomplete_native_close_is_never_reported_closed(
    close_state: str, stop_returned: bool, join_pending: bool
) -> None:
    error = CtpSdkMarketReadOnlyError(
        "market_client_stop_failed",
        close_state=close_state,
        client_stop_returned=stop_returned,
    )
    assert _close_projection(error) == {
        "client_stop_returned": stop_returned,
        "probe_session_closed": False,
        "native_join_pending": join_pending,
        "native_shutdown_uncertain": True,
    }


def test_returned_stop_and_non_market_failure_have_distinct_projection() -> None:
    error = CtpSdkMarketReadOnlyError(
        "market_login_timeout",
        close_state="stop_returned",
        client_stop_returned=True,
    )
    assert _close_projection(error) == {
        "client_stop_returned": True,
        "probe_session_closed": True,
        "native_join_pending": False,
        "native_shutdown_uncertain": False,
    }
    assert _close_projection(ValueError("provider message")) == {
        "client_stop_returned": False,
        "probe_session_closed": False,
        "native_join_pending": False,
        "native_shutdown_uncertain": False,
    }
    unreturned = CtpSdkMarketReadOnlyError(
        "market_client_stop_failed", close_state="stop_returned"
    )
    assert _close_projection(unreturned)["probe_session_closed"] is False


def test_fixed_json_callback_fields_never_include_provider_payload(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _emit(
        status="rejected",
        reason="market_client_stop_failed",
        stage="market_data",
        login_callback_count=1,
        login_callback_disposition="request_id_mismatch",
        login_request_id_relation="zero",
        login_response_error_status="nonzero",
        client_stop_returned=True,
        native_join_pending=True,
        native_shutdown_uncertain=True,
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["login_callback_count"] == 1
    assert payload["login_callback_disposition"] == "request_id_mismatch"
    assert payload["login_request_id_relation"] == "zero"
    assert payload["login_response_error_status"] == "nonzero"
    assert payload["trading_writes"] == payload["settlement_writes"] == 0
    assert payload["order_submission_authorized"] is False
    assert not any(key in payload for key in ("broker_id", "user_id", "password", "md_front"))
