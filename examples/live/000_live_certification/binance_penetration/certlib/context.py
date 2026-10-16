"""Case context, result and evidence helpers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass
class CaseResult:
    case_id: str
    status: str  # PASS | FAIL | BLOCKED | UNKNOWN
    reason: str = ""
    facts: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.status not in ("PASS", "FAIL", "BLOCKED", "UNKNOWN"):
            raise ValueError(f"bad case status: {self.status}")


class CaseContext:
    """Handed to a strategy; carries config, client, evidence and a log."""

    def __init__(self, *, venue, case_id, config, topology, client, evidence_dir, live):
        self.venue = venue
        self.case_id = case_id
        self.config = config
        self.topology = topology
        self.client = client
        self.evidence_dir = Path(evidence_dir)
        self.live = live
        self.notes = []
        self.artifacts = {}
        self.tracked_orders = []

    def log(self, message: str) -> None:
        print(f"[{self.case_id}] {message}", flush=True)
        self.notes.append({"utc": utc_now(), "note": str(message)})

    def record_artifact(self, name: str, payload) -> None:
        self.artifacts[name] = payload

    def track_order(self, symbol, order_id, client_order_id=None):
        """Register an order right after placement for compensating cleanup."""
        entry = {"symbol": symbol, "order_id": order_id, "client_order_id": client_order_id, "state": "open"}
        self.tracked_orders.append(entry)
        return entry

    def mark_order_closed(self, order_id):
        for entry in self.tracked_orders:
            if entry["order_id"] == order_id:
                entry["state"] = "closed"

    def scenario(self) -> dict:
        return dict(self.config.get("scenario", {}))


def _digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def write_evidence(evidence_dir, payload) -> Path:
    evidence_dir = Path(evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    path = evidence_dir / f"{stamp}_{payload.get('case_id', 'case')}_{payload.get('status', 'x')}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def build_evidence(*, venue, case_id, case_dir, config, topology, live, result, client=None, ctx=None,
                   config_path=None, started_utc, finished_utc, env_names_present,
                   env_names_missing, grants):
    selected_config_path = (
        Path(config_path) if config_path is not None else Path(case_dir) / "config.yaml"
    )
    payload = {
        "schema": 1,
        "venue": venue,
        "case_id": case_id,
        "status": result.status,
        "reason": result.reason,
        "facts": result.facts,
        "live": bool(live),
        "grants": grants,
        "topology": topology,
        "started_utc": started_utc,
        "finished_utc": finished_utc,
        "config_sha256": _digest(selected_config_path),
        "env_keys_present": sorted(env_names_present),
        "env_keys_missing": sorted(env_names_missing),
        "client": client.describe() if client is not None and hasattr(client, "describe") else None,
        "calls": client.calls if client is not None and hasattr(client, "calls") else [],
        "notes": ctx.notes if ctx is not None else [],
        "artifacts": ctx.artifacts if ctx is not None else {},
    }
    return payload
