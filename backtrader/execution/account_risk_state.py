"""Bind Store lifecycle and identity fences to SDK account-risk state."""

from __future__ import annotations

import os
import time
from typing import Any, Dict


def read_store_account_risk_snapshot(
    store, api: Any, *, initialize_baseline: bool = False, error_type, safe_log
) -> Dict[str, Any]:
    """Adapt Store configuration and SDK evidence workflows to risk state."""
    from bt_api_py.account_risk_state import (
        project_account_risk_snapshot,
        unavailable_account_risk_snapshot,
    )
    stream_generation = store._stream_generation
    try:
        identity_expectations = store._sdk_identity_expectations()
    except Exception as exc:
        store.sanitize_exception(exc)
        safe_log("warning", "btapistore: account-risk identity declarations unavailable")
        code = store._safe_exception_code(exc, "account_risk_identity_unproven")
        snapshot = unavailable_account_risk_snapshot(
            sorted(str(route) for route in store._sdk_exchanges),
            configured_loss_limit=store._sdk_execution_config_value(
                "account_maximum_loss_bps"
            ),
            error_code=code,
        )
        return store._account_risk_state.cache_snapshot(
            snapshot, stream_generation
        )

    def capture_identity_binding(candidate, expectations):
        if (
            candidate is not api
            or store._api is not api
            or store._stream_generation != stream_generation
            or expectations is not identity_expectations
        ):
            raise error_type("account_risk_identity_route_changed")
        return store._capture_sdk_identity_binding(
            candidate,
            expectations,
            stream_generation=stream_generation,
        )

    def validate_identity_binding(candidate, binding, expectations):
        if (
            candidate is not api
            or store._api is not api
            or store._stream_generation != stream_generation
            or expectations is not identity_expectations
        ):
            return False
        return store._validate_sdk_identity_binding(
            candidate,
            binding,
            expectations,
            stream_generation=stream_generation,
        )

    def get_snapshot_reader(candidate, binding, *, initialize_baseline):
        if (
            candidate is not api
            or store._api is not api
            or store._stream_generation != stream_generation
        ):
            raise error_type("account_risk_identity_route_changed")
        reader = getattr(candidate, "account_risk_snapshot_for_identity_binding", None)
        if not callable(reader):
            raise error_type("account_risk_snapshot_unavailable")
        snapshot = reader(binding, initialize_baseline=initialize_baseline)
        if (
            store._api is not api
            or store._stream_generation != stream_generation
        ):
            raise error_type("account_risk_identity_route_changed")
        return snapshot

    def validate_account_risk_snapshot(candidate, snapshot, binding):
        if (
            candidate is not api
            or store._api is not api
            or store._stream_generation != stream_generation
            or getattr(snapshot, "identity_binding", None) is not binding
        ):
            return False
        validator = getattr(candidate, "validate_account_risk_snapshot", None)
        if not callable(validator):
            return False
        valid = validator(snapshot)
        return (
            valid
            if store._api is api and store._stream_generation == stream_generation
            else False
        )

    snapshot = store._account_risk_state.read_snapshot(
        api,
        generation=stream_generation,
        configured_routes=store._sdk_exchanges,
        configured_loss_limit=store._sdk_execution_config_value(
            "account_maximum_loss_bps"
        ),
        initialize_baseline=initialize_baseline,
        identity_expectations=identity_expectations,
        capture_identity_binding=capture_identity_binding,
        validate_identity_binding=validate_identity_binding,
        get_snapshot_reader=get_snapshot_reader,
        validate_account_risk_snapshot=validate_account_risk_snapshot,
        project_typed_snapshot=project_account_risk_snapshot,
        exception_code=store._safe_exception_code,
        sanitize_exception=store.sanitize_exception,
        observe_error=lambda _exc: safe_log(
            "warning", "btapistore:13634 fallback on Exception"
        ),
        owner_pid=os.getpid(),
        monotonic_ns=time.monotonic_ns,
    )
    if store._api is not api or store._stream_generation != stream_generation:
        return unavailable_account_risk_snapshot(
            store._sdk_exchanges,
            configured_loss_limit=store._sdk_execution_config_value(
                "account_maximum_loss_bps"
            ),
            error_code="account_risk_identity_binding_changed",
        )
    return snapshot


__all__ = ("read_store_account_risk_snapshot",)
