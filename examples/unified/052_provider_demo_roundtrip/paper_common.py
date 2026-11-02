"""Shared neutral helpers for the iteration-52 provider paper entry.

``run.py`` (Binance/OKX) and ``simnow_runner.py`` (SimNow) both use these
venue-agnostic strategy/evidence helpers. Credential parsing and provider
configuration belong to the SDK; this module reads no credentials or private
configuration and opens no provider connection.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]


def strategy_params(params: dict) -> dict:
    """The strategy parameter mapping derived from the validated config."""
    return {
        "notional_usdt": float(params["notional_usdt"]),
        "step_size": float(params["step_size"]),
        "tick_size": float(params["tick_size"]),
        "contract_value": float(params["contract_value"]),
        "quantity_unit": str(params["quantity_unit"]),
        "offset_bps": float(params["offset_bps"]),
        "time_in_force": str(params.get("time_in_force", "GTC")),
        "cancel_after_seconds": float(params["cancel_after_seconds"]),
        "hard_timeout_seconds": float(params["hard_timeout_seconds"]),
    }


def write_evidence(payload: dict) -> Path:
    """Write one git-ignored evidence JSON next to this example and return it."""
    evidence_dir = HERE / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    venue = str((payload.get("venue") or "BINANCE")).lower()
    path = evidence_dir / f"{stamp}_052_{venue}_demo_roundtrip_{payload['status']}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def summarize(payload: dict) -> dict:
    """The compact one-line stdout summary printed for every outcome."""
    report = payload.get("report") or {}
    facts = report.get("strategy_facts") or {}
    return {
        "status": payload["status"],
        "reason": payload.get("reason"),
        "venue": payload.get("venue"),
        "phase": facts.get("phase"),
        "open_status": (facts.get("open_order") or {}).get("status"),
        "close_status": (facts.get("close_order") or {}).get("status"),
        "cancel_requested": facts.get("cancel_requested"),
        "run_id": report.get("run_id"),
        "evidence": payload.get("evidence_path"),
    }

def row_value(row: Any, *names: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        for name in names:
            if row.get(name) is not None:
                return row[name]
        return default
    for name in names:
        value = getattr(row, name, None)
        if value is not None:
            return value
    return default


def finite_number(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def public_login_facts(login: Mapping[str, Any]) -> Dict[str, Any]:
    """Project value-free login facts (no front/session identifiers)."""
    return {
        "trading_day": str(login.get("trading_day") or ""),
        "connection_generation": int(login.get("connection_generation") or 0),
        "read_only_ready": bool(login.get("read_only_ready")),
        "trading_ready": bool(login.get("trading_ready")),
    }
