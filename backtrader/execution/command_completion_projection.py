"""Pure projections for local Store command results."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict


def unsent_command_completion(
    command: Mapping[str, Any],
    reason: str,
    *,
    completed_monotonic_ns: int,
) -> Dict[str, Any]:
    """Build the terminal Broker envelope for a command never sent remotely.

    The caller owns the monotonic clock and decides when the command becomes
    terminal; this function only projects the supplied command facts.
    """
    return {
        "kind": "command_completion",
        "command": command.get("operation"),
        "receipt_id": command.get("receipt_id"),
        "bt_order_ref": command.get("bt_order_ref"),
        "client_order_id": command.get("client_order_id"),
        "data_name": command.get("symbol"),
        "exchange_name": command.get("venue"),
        "priority": command.get("priority"),
        "session_generation": command.get("session_generation"),
        "success": False,
        "status": "rejected",
        "execution_unknown": False,
        "definite_reject": True,
        "terminal_confirmed": True,
        "remote_write_attempted": False,
        "error_code": str(reason),
        "error_msg": "Opening command was rejected locally before remote transport",
        "completed_monotonic_ns": completed_monotonic_ns,
    }


__all__ = ("unsent_command_completion",)
