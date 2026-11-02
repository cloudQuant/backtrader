"""Backtrader command receipt projections for the SDK coordinator."""

from __future__ import annotations

from collections.abc import Mapping


def _project_completion(command):
    return {
        "kind": "command_completion",
        "command": command["operation"],
        "receipt_id": command["receipt_id"],
        "bt_order_ref": command.get("bt_order_ref"),
        "client_order_id": command.get("client_order_id"),
        "data_name": command.get("symbol"),
        "exchange_name": command.get("venue"),
        "priority": command["priority"],
        "session_generation": command.get("session_generation"),
        "completed_monotonic_ns": 0,
    }


def _project_completion_drop(update, reason):
    details = update.get("details") if isinstance(update.get("details"), Mapping) else {}
    return {
        "reason": str(reason),
        "kind": str(update.get("kind") or ""),
        "command": str(update.get("command") or ""),
        "bt_order_ref": update.get("bt_order_ref") or details.get("bt_order_ref"),
        "client_order_id": update.get("client_order_id") or details.get("client_order_id"),
        "exchange_name": update.get("exchange_name") or details.get("exchange_name"),
        "event_id": update.get("event_id") or details.get("event_id"),
        "session_generation": update.get("session_generation"),
    }


def SdkExecutionCoordinator(**kwargs):
    """Construct one SDK coordinator with Backtrader-specific projections."""
    from bt_api_py.command_coordinator import CommandOutcomeCoordinator

    return CommandOutcomeCoordinator(
        **kwargs,
        project_completion=_project_completion,
        project_completion_drop=_project_completion_drop,
    )


__all__ = ("SdkExecutionCoordinator",)
