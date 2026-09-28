"""Strict SDK shutdown receipt checks for native CTP clients.

The managed SimNow path may release its account lease only after the SDK's
exact public stop receipt proves native Join/Release cleanup completed.
The SDK's ``stop_and_wait`` first calls synchronous ``stop()`` and only then
applies its timeout to native Join observation. This helper does not bound the
total wall-clock duration of that call; a hard deadline requires a supervising
process that can terminate a stuck caller.
"""

from __future__ import annotations

from typing import Any


_STOP_WAIT_TIMEOUT_SECONDS = 2.0


def _native_stop_receipt_type() -> type | None:
    """Return only the public receipt class from the expected SDK module."""

    try:
        from bt_api_ctp.ctp.client import CtpNativeStopReceipt
    except Exception:
        return None
    if (
        type(CtpNativeStopReceipt) is not type
        or CtpNativeStopReceipt.__module__ != "bt_api_ctp.ctp.client"
        or CtpNativeStopReceipt.__name__ != "CtpNativeStopReceipt"
    ):
        return None
    return CtpNativeStopReceipt


def stop_ctp_native_client(client: Any) -> bool:
    """Attempt one SDK stop and accept only a coherent SDK receipt.

    This intentionally has no ``stop()`` fallback. A legacy method or a
    duck-typed receipt may perform cleanup, but neither can prove it completed
    and therefore neither can authorize releasing the account lease.

    The 2-second timeout passed to ``stop_and_wait`` bounds only its native
    Join wait. The SDK calls ``stop()`` synchronously before that wait, so this
    function itself has no hard wall-clock bound.
    """

    try:
        expected_type = _native_stop_receipt_type()
    except BaseException:
        expected_type = None

    try:
        expected_generation = getattr(client, "connection_generation")
    except BaseException:
        expected_generation = None
    try:
        stop_and_wait = getattr(client, "stop_and_wait")
    except BaseException:
        return False
    if not callable(stop_and_wait):
        return False

    try:
        receipt = stop_and_wait(timeout=_STOP_WAIT_TIMEOUT_SECONDS)
    except BaseException:
        return False

    if expected_type is None or type(receipt) is not expected_type:
        return False
    try:
        generation = receipt.connection_generation
        join_required = receipt.join_required
        join_completed = receipt.join_completed
        native_released = receipt.native_released
        thread_alive = receipt.thread_alive
        timed_out = receipt.timed_out
        complete = receipt.complete
    except BaseException:
        return False

    if (
        type(expected_generation) is not int
        or expected_generation < 0
        or type(generation) is not int
        or generation != expected_generation
        or type(join_required) is not bool
        or type(join_completed) is not bool
        or type(native_released) is not bool
        or type(thread_alive) is not bool
        or type(timed_out) is not bool
        or type(complete) is not bool
    ):
        return False

    derived_complete = (
        native_released
        and (not join_required or join_completed)
        and thread_alive is False
        and not timed_out
    )
    return bool(
        complete is True
        and derived_complete
        and native_released is True
        and (join_required is False or join_completed is True)
        and thread_alive is False
        and timed_out is False
    )


__all__ = ["stop_ctp_native_client"]
