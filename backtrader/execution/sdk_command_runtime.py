"""Backtrader projections for the SDK-owned bounded command runtime."""

from __future__ import annotations

def _project_receipt(command, operation, receipt_id, priority, depth, rejection):
    receipt = {
        "kind": "command_receipt", "command": operation, "receipt_id": receipt_id,
        "bt_order_ref": command.get("bt_order_ref"),
        "client_order_id": command.get("client_order_id"),
        "status": "rejected" if rejection else "submitted",
        "queued": not bool(rejection), "priority": priority, "queue_depth": depth,
    }
    if rejection:
        receipt.update(error_code=rejection,
                       error_msg="SDK command queue cannot safely accept this command")
    return receipt

def _project_command_drop(command, reason):
    return {
        "reason": str(reason), "command": str(command.get("operation") or ""),
        "bt_order_ref": command.get("bt_order_ref"),
        "client_order_id": command.get("client_order_id"),
        "exchange_name": command.get("venue"),
        "session_generation": command.get("session_generation"),
    }

def _project_health(snapshot):
    """Return a finite mapping compatible with existing Store health keys."""

    counters = dict(snapshot.counters)
    for suffix in ("ingress", "delivered", "dropped"):
        key = "completion_" + suffix
        if key in counters:
            counters["broker_update_" + suffix] = counters.pop(key)
    return {
        **counters,
        "queue_capacity": snapshot.queue_capacity,
        "reserved_capacity": snapshot.reserved_capacity,
        "queue_depth": snapshot.queue_depth,
        "inflight": snapshot.inflight,
        "publications_pending": snapshot.publications_pending,
        "accepting_openings": snapshot.accepting_openings,
        "accepting_commands": snapshot.accepting_commands,
        "worker_alive": snapshot.worker_alive,
        "last_error_code": snapshot.last_error_code,
        "session_generation": snapshot.generation,
        "worker_generation": snapshot.worker_generation,
        "stop_requested": snapshot.stop_requested,
        "accepting_completions": snapshot.accepting_completions,
        "restart_blocked_by_worker": snapshot.restart_blocked_by_worker,
        "completion_queue_capacity": snapshot.completion_capacity,
        "broker_update_queue_depth": snapshot.completion_depth,
        "broker_update_ingress": snapshot.completion_ingress,
        "broker_update_delivered": snapshot.completion_delivered,
        "broker_update_dropped": snapshot.completion_dropped,
        "broker_update_conservation": snapshot.completion_conserved,
        "command_drop_records": [dict(row) for row in snapshot.command_drop_records],
        "broker_update_drop_records": [
            dict(row) for row in snapshot.completion_drop_records
        ],
    }

def SdkCommandRuntime(**kwargs):
    """Construct the SDK runtime lazily with Backtrader receipt projections."""
    from bt_api_py.queued_command_runtime import QueuedCommandRuntime
    return QueuedCommandRuntime(
        **kwargs, project_receipt=_project_receipt,
        project_command_drop=_project_command_drop, project_health=_project_health,
        completion_overflow_reason="broker_update_queue_overflow",
    )

__all__ = ("SdkCommandRuntime",)
