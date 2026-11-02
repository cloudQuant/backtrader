"""Lazy Backtrader lifecycle bridge for the SDK metadata probe."""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Sequence

_ERROR_MESSAGES = {
    "invalid_timeout": "bounded read-only metadata probe timeout is invalid",
    "invalid_datanames": "bounded read-only metadata probe datanames are invalid",
    "already_active": "bounded read-only metadata probe is already active",
    "timeout": "bounded read-only metadata probe timed out before shutdown was proven",
    "typed_metadata_incomplete": (
        "bounded read-only metadata probe returned incomplete typed metadata"
    ),
    "shutdown_incomplete": "bounded read-only metadata probe shutdown is incomplete",
    "probe_stopped": "bounded read-only metadata probe was stopped before completion",
    "probe_failed": "bounded read-only metadata probe failed",
}


class BoundedMetadataProbeError(RuntimeError):
    """Finite, non-sensitive error projection for a metadata probe."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or code not in _ERROR_MESSAGES:
            code = "probe_failed"
        self.code = code
        super().__init__(_ERROR_MESSAGES[code])



def run_store_metadata_probe(
    store,
    *,
    datanames: Sequence[str],
    timeout_seconds: float,
    error_type,
    safe_log,
) -> Dict[str, Any]:
    """Run one complete, bounded, zero-write SDK metadata lifecycle.

    The probe service owns operation ordering, its market-data-only latch,
    typed-contract validation, deadline handoff, and result projection.
    Store callbacks are limited to SDK and Store lifecycle boundaries.
    """
    from bt_api_py.bounded_metadata_probe import BoundedMetadataProbeError as SdkProbeError

    def translate(error):
        if isinstance(error, SdkProbeError):
            return BoundedMetadataProbeError(error.code)
        return error

    def validate_store():
        if not store._sdk_mode:
            raise error_type(
                "bounded read-only metadata probe requires the SDK provider"
            )
        if not store._sdk_owned_api or store._sdk_custom_api_factory:
            # The SDK exposes no immutable read-only configuration receipt;
            # restrict this probe to the Store-created default client.
            raise error_type(
                "bounded read-only metadata probe requires a Store-owned installed SDK client"
            )

    def validate_idle():
        if store._started or store._connected:
            raise error_type(
                "bounded read-only metadata probe requires an idle Store"
            )

    def prepare_session():
        # Preserve configured environments and strategy identity while
        # forcing this one-shot session into market-data-only mode.
        store._update_sdk_execution_config({"market_data_only": True})
        store.start()
        return store._api

    def close_session(shutdown_timeout):
        store.stop(timeout=shutdown_timeout)
        return store.get_command_health()

    def read_instrument(api, symbol):
        if api is not store._api:
            raise error_type("bounded read-only metadata probe API binding changed")
        return store.get_typed_instrument_spec(symbol)

    def read_funding(api, symbol):
        if api is not store._api:
            raise error_type("bounded read-only metadata probe API binding changed")
        return store.get_typed_funding_snapshot(symbol)

    def observe_error(error):
        store.sanitize_exception(error)
        safe_log("warning", "btapistore: bounded metadata probe failed")

    def project_error(error):
        if (
            isinstance(error, BoundedMetadataProbeError)
            and error.code == "typed_metadata_incomplete"
        ):
            return "typed_metadata_incomplete"
        if isinstance(error, error_type) and str(error) == (
            "bounded read-only metadata probe shutdown is incomplete"
        ):
            return "shutdown_incomplete"
        return "probe_failed"

    try:
        result = store._metadata_probe_service.run(
            datanames,
            timeout_seconds,
            validate_owner=validate_store,
            validate_idle=validate_idle,
            prepare_session=prepare_session,
            verify_market_data_only=store._verify_bounded_metadata_probe_sdk_market_data_only,
            is_market_data_only=store._is_sdk_market_data_only,
            close_session=close_session,
            read_instrument=read_instrument,
            read_funding=read_funding,
            exchange_name_for=lambda symbol: store._sdk_exchange(symbol),
            set_accept_openings=store._command_runtime.set_accept_openings,
            shutdown_proven=store._bounded_metadata_probe_shutdown_proven,
            shutdown_timeout=store._command_shutdown_timeout,
            timeout_max=threading.TIMEOUT_MAX,
            monotonic=time.monotonic,
            thread_factory=threading.Thread,
            on_error=lambda error: observe_error(translate(error)),
            error_projector=lambda error: project_error(translate(error)),
        )
    except SdkProbeError as sdk_error:
        exc = BoundedMetadataProbeError(sdk_error.code)
        if exc.code == "timeout":
            store._shutdown_state = "INCOMPLETE"
            if store._metadata_probe_service.worker_alive:
                store._command_health["read_only_metadata_probe_timeouts"] += 1
        raise error_type(str(exc)) from None
    health = dict(result["session_health"])
    health["read_only_metadata_probe_active"] = store._metadata_probe_service.is_active()
    return {
        "instrument_specs": dict(result["instrument_specs"]),
        "funding_snapshots": dict(result["funding_snapshots"]),
        "order_write_attempts": 0,
        "store_health": health,
    }


__all__ = ("BoundedMetadataProbeError", "run_store_metadata_probe")
