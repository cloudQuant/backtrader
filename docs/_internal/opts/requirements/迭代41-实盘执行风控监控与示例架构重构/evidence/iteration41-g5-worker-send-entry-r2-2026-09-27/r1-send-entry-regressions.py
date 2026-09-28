"""Expected R2 sender-boundary invariants, run against the frozen R1 candidate.

These tests are intentionally red on R1. They document the smallest API and
entry-boundary failures an isolated R2 must close; they are not an SDK test.
"""
from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path

import pytest


R1 = Path(r"D:\temp\iteration41-g5-worker-projection-r2-boundary-20260927\r1-frozen-candidate")
IMPLEMENTATION = R1 / "implementation"
sys.path[:0] = [
    str(IMPLEMENTATION / "sdk" / "src"),
    str(IMPLEMENTATION),
    str(IMPLEMENTATION / "tests"),
]
_spec = importlib.util.spec_from_file_location(
    "r2_frozen_r1_test_helpers",
    IMPLEMENTATION / "tests" / "test_g5_single_worker_action_handoff.py",
)
assert _spec is not None and _spec.loader is not None
_helpers = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _helpers
_spec.loader.exec_module(_helpers)

from bt_api_execution.ctp_single_worker_candidate import (  # noqa: E402
    CtpManagedSingleWorkerCandidate,
    CtpNativeDispatchResult,
)
from bt_api_execution.errors import ContractValidationError  # noqa: E402


def _queued_worker(tmp_path: Path, name: str):
    store, authority, scope, lease = _helpers._open(tmp_path / name)
    order = _helpers._seed_order(authority, scope, lease)
    action = _helpers._reserve_action(authority, scope, lease, order)
    prepared = _helpers._prepared(order)
    worker = CtpManagedSingleWorkerCandidate(store, scope, lease, authority)
    projection = _helpers._target_projection(store, order, prepared)
    binding = worker.stage_prepared_dispatch(
        prepared,
        cancel_target_projection=projection,
        action_identity=action,
    )
    command = store.read_ctp_dispatch_command(scope, prepared.command_id)
    assert command is not None
    binding = worker.record_managed_queue_receipt(
        prepared.command_id, binding, _helpers._queue(binding, command)
    )
    return store, scope, prepared, worker, binding, projection


def test_r2_dispatch_api_does_not_accept_arbitrary_sender_callable():
    parameters = inspect.signature(
        CtpManagedSingleWorkerCandidate.dispatch_managed_command
    ).parameters
    assert "sender" not in parameters, (
        "R1 exposes a caller-controlled sender callback; the native call must be "
        "owned by a code-owned synchronous port"
    )


def test_sync_wrapper_side_effect_cannot_precede_awaitable_rejection(tmp_path):
    store, scope, prepared, worker, binding, _projection = _queued_worker(
        tmp_path, "sync-wrapper-awaitable.sqlite3"
    )
    sender_entries: list[str] = []
    fake_native_entries: list[str] = []
    coroutine_body: list[str] = []

    async def deferred_result(_command):
        coroutine_body.append("coroutine-body")
        return CtpNativeDispatchResult("QUEUED", {"queued": True})

    def sync_wrapper(_command):
        sender_entries.append("wrapper-entered")
        # Model a wrapper with an observable side effect before it returns an
        # awaitable. The real R2 entry port must not call such a wrapper.
        fake_native_entries.append("native-call-before-returning-awaitable")
        return deferred_result(_command)

    try:
        rejected_before_claim = False
        try:
            result = worker.dispatch_managed_command(
                prepared.command_id, binding, sync_wrapper
            )
        except (ContractValidationError, TypeError):
            rejected_before_claim = True
            result = None
        command = store.read_ctp_dispatch_command(scope, prepared.command_id)
        assert command is not None
        assert (
            sender_entries == []
            and fake_native_entries == []
            and coroutine_body == []
            and rejected_before_claim
            and (result is None or result.sender_called is False)
            and command.status == "READY"
        ), (
            "R1 enters a synchronous wrapper before discovering its awaitable "
            f"result: entries={sender_entries!r}, native={fake_native_entries!r}, "
            f"called={None if result is None else result.sender_called}, "
            f"preclaim_reject={rejected_before_claim}, status={command.status}"
        )
    finally:
        store.close()


def test_expiry_at_native_entry_is_rechecked_inside_code_owned_port(tmp_path):
    store, scope, prepared, worker, binding, projection = _queued_worker(
        tmp_path, "expiry-inside-sender.sqlite3"
    )
    expires_at_ns = projection.projection.expires_at_ns
    clock = {"now": expires_at_ns - 1}
    store._monotonic_now_ns = lambda: clock["now"]
    fake_native_entries: list[int] = []

    def arbitrary_delayed_sender(_command):
        # Simulate arbitrary Python between the worker's pre-entry check and
        # the native API call. A code-owned synchronous port must put its final
        # freshness check after this delay and before ReqOrderAction.
        clock["now"] = expires_at_ns
        fake_native_entries.append(clock["now"])
        return CtpNativeDispatchResult("QUEUED", {"queued": True})

    try:
        rejected_before_claim = False
        try:
            result = worker.dispatch_managed_command(
                prepared.command_id, binding, arbitrary_delayed_sender
            )
        except (ContractValidationError, TypeError):
            rejected_before_claim = True
            result = None
        command = store.read_ctp_dispatch_command(scope, prepared.command_id)
        assert command is not None
        assert (
            fake_native_entries == []
            and rejected_before_claim
            and (result is None or result.sender_called is False)
            and command.status == "READY"
        ), (
            "R1 checks freshness before entering the arbitrary sender only; it "
            f"allowed fake native entry at {fake_native_entries!r}, "
            f"preclaim_reject={rejected_before_claim}, "
            f"state={None if result is None else result.worker_state}/{command.status}"
        )
    finally:
        store.close()
