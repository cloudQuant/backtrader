"""Explicit session state, append-only hash chain, and safe recovery."""

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .canonical import (
    atomic_write_bytes,
    atomic_write_json,
    canonical_json_bytes,
    hash_object,
    read_json,
)
from .errors import AgentError

SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,79}$")
TERMINAL = {"COMPLETED", "CANCELLED", "ARCHIVED"}
TRANSITIONS = {
    "NEW": {"DATA_READY", "CANCELLED"},
    "DATA_READY": {"SPEC_DRAFT", "NEEDS_REVALIDATION", "CANCELLED"},
    "SPEC_DRAFT": {"SPEC_APPROVED", "CANCELLED"},
    "SPEC_APPROVED": {"SOURCES_SELECTED", "CANCELLED"},
    "SOURCES_SELECTED": {"DRAFT_READY", "CANCELLED"},
    "DRAFT_READY": {"VALIDATED", "NEEDS_REVALIDATION", "CANCELLED"},
    "VALIDATED": {"APPLY_PREPARED", "NEEDS_REVALIDATION", "CANCELLED"},
    "APPLY_PREPARED": {"APPLIED", "NEEDS_REVALIDATION", "CANCELLED"},
    "APPLIED": {"RUN_APPROVED", "NEEDS_REVALIDATION", "CANCELLED"},
    "RUN_APPROVED": {"RUNNING", "NEEDS_REVALIDATION", "CANCELLED"},
    "RUNNING": {"PASSED", "FAILED", "PAUSED"},
    "FAILED": {"REPAIRING", "CANCELLED"},
    "REPAIRING": {"DRAFT_READY", "CANCELLED"},
    "PASSED": {"REPORTED", "CANCELLED"},
    "REPORTED": {"COMPLETED", "CANCELLED"},
    "PAUSED": {"RUNNING", "NEEDS_REVALIDATION", "CANCELLED"},
    "NEEDS_REVALIDATION": {"DATA_READY", "DRAFT_READY", "CANCELLED"},
    "COMPLETED": {"ARCHIVED"},
    "CANCELLED": {"ARCHIVED"},
    "ARCHIVED": set(),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class SessionStore:
    def __init__(self, state_root: Path) -> None:
        self.state_root = Path(state_root)
        self.sessions_root = self.state_root / "sessions"

    def _directory(self, session_id: str) -> Path:
        if not SESSION_RE.fullmatch(session_id):
            raise AgentError("BTAG-SESSION-ID", "session ID is malformed")
        return self.sessions_root / session_id

    def _manifest_path(self, session_id: str) -> Path:
        return self._directory(session_id) / "manifest.json"

    def _journal_path(self, session_id: str) -> Path:
        return self._directory(session_id) / "journal.jsonl"

    def create(self, session_id: str, *, parent_session_id: Optional[str] = None) -> Dict[str, Any]:
        directory = self._directory(session_id)
        manifest_path = directory / "manifest.json"
        if manifest_path.exists():
            existing = read_json(manifest_path)
            if existing.get("session_id") == session_id:
                return existing
            raise AgentError("BTAG-SESSION-CONFLICT", "session path contains another session")
        directory.mkdir(parents=True, exist_ok=True)
        journal = directory / "journal.jsonl"
        atomic_write_bytes(journal, b"", create_only=True)
        manifest: Dict[str, Any] = {
            "schema_version": "agent-session-manifest-v1",
            "session_id": session_id,
            "parent_session_id": parent_session_id,
            "product": "backtrader-agent",
            "product_version": "0.1.0",
            "state": "NEW",
            "state_revision": 0,
            "last_sequence": 0,
            "last_event_hash": "0" * 64,
            "journal": "journal.jsonl",
            "allowed_next_actions": sorted(TRANSITIONS["NEW"]),
            "artifacts": {},
            "approvals": {"apply": None, "execute": None},
            "diagnostics": [],
        }
        manifest["checkpoint_hash"] = hash_object(
            {key: value for key, value in manifest.items() if key != "checkpoint_hash"}
        )
        atomic_write_json(manifest_path, manifest, create_only=True)
        return manifest

    def load(self, session_id: str) -> Dict[str, Any]:
        path = self._manifest_path(session_id)
        if not path.exists():
            raise AgentError("BTAG-SESSION-UNKNOWN", "session does not exist")
        manifest = read_json(path)
        expected = manifest.get("checkpoint_hash")
        actual = hash_object(
            {key: value for key, value in manifest.items() if key != "checkpoint_hash"}
        )
        if expected != actual:
            raise AgentError("BTAG-SESSION-CHECKPOINT", "session checkpoint hash is invalid")
        return manifest

    def _append(self, session_id: str, event: Dict[str, Any]) -> None:
        journal = self._journal_path(session_id)
        data = canonical_json_bytes(event) + b"\n"
        descriptor = os.open(str(journal), os.O_WRONLY | os.O_APPEND)
        try:
            os.write(descriptor, data)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def transition(
        self,
        session_id: str,
        to_state: str,
        action_type: str,
        input_hashes: Dict[str, str],
        *,
        idempotency_key: Optional[str] = None,
        approval_token_id: Optional[str] = None,
        effect_references: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        manifest = self.load(session_id)
        from_state = manifest["state"]
        if to_state not in TRANSITIONS.get(from_state, set()):
            raise AgentError(
                "BTAG-STATE-TRANSITION",
                "requested session state transition is not legal",
                details={"from": from_state, "to": to_state},
            )
        normalized_inputs = {str(key): str(value) for key, value in input_hashes.items()}
        effects = {str(key): str(value) for key, value in (effect_references or {}).items()}
        sequence = int(manifest["last_sequence"]) + 1
        event: Dict[str, Any] = {
            "schema_version": "agent-event-v1",
            "session_id": session_id,
            "sequence": sequence,
            "event_type": "STATE_TRANSITION",
            "action_type": action_type,
            "from_state": from_state,
            "to_state": to_state,
            "normalized_input_hashes": dict(sorted(normalized_inputs.items())),
            "idempotency_key": idempotency_key,
            "approval_token_id": approval_token_id,
            "effect_references": dict(sorted(effects.items())),
            "previous_event_hash": manifest["last_event_hash"],
            "status": "committed",
            "timestamp": _now(),
        }
        event["event_hash"] = hash_object(event)
        self._append(session_id, event)
        manifest["state"] = to_state
        manifest["state_revision"] = int(manifest["state_revision"]) + 1
        manifest["last_sequence"] = sequence
        manifest["last_event_hash"] = event["event_hash"]
        manifest["allowed_next_actions"] = sorted(TRANSITIONS[to_state])
        manifest["artifacts"].update(effects)
        if approval_token_id and to_state == "APPLIED":
            manifest["approvals"]["apply"] = approval_token_id
        if approval_token_id and to_state == "RUN_APPROVED":
            manifest["approvals"]["execute"] = approval_token_id
        manifest["checkpoint_hash"] = hash_object(
            {key: value for key, value in manifest.items() if key != "checkpoint_hash"}
        )
        atomic_write_json(self._manifest_path(session_id), manifest)
        return manifest

    def _parse_valid_prefix(self, session_id: str, data: bytes) -> Tuple[List[Dict[str, Any]], int]:
        events: List[Dict[str, Any]] = []
        offset = 0
        expected_sequence = 1
        expected_previous = "0" * 64
        for line in data.splitlines(keepends=True):
            line_start = offset
            offset += len(line)
            if not line.endswith(b"\n"):
                return events, line_start
            try:
                event = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return events, line_start
            stored_hash = event.get("event_hash")
            actual_hash = hash_object(
                {key: value for key, value in event.items() if key != "event_hash"}
            )
            if (
                event.get("session_id") != session_id
                or event.get("sequence") != expected_sequence
                or event.get("previous_event_hash") != expected_previous
                or stored_hash != actual_hash
            ):
                return events, line_start
            if event.get("to_state") not in TRANSITIONS.get(event.get("from_state"), set()):
                return events, line_start
            if events and event.get("from_state") != events[-1].get("to_state"):
                return events, line_start
            if not events and event.get("from_state") != "NEW":
                return events, line_start
            events.append(event)
            expected_sequence += 1
            expected_previous = stored_hash
        return events, len(data)

    def recover(self, session_id: str) -> Dict[str, Any]:
        directory = self._directory(session_id)
        journal = directory / "journal.jsonl"
        if not journal.exists():
            raise AgentError("BTAG-SESSION-JOURNAL", "session journal is missing")
        data = journal.read_bytes()
        events, valid_bytes = self._parse_valid_prefix(session_id, data)
        if valid_bytes < len(data):
            suffix = data[valid_bytes:]
            corrupt = directory / f"journal.corrupt.{time.time_ns()}.jsonl"
            atomic_write_bytes(corrupt, suffix, create_only=True)
            atomic_write_bytes(journal, data[:valid_bytes])
        previous = read_json(self._manifest_path(session_id))
        state = events[-1]["to_state"] if events else "NEW"
        last_hash = events[-1]["event_hash"] if events else "0" * 64
        artifacts: Dict[str, str] = {}
        approvals = {"apply": None, "execute": None}
        for event in events:
            artifacts.update(event.get("effect_references", {}))
            token_id = event.get("approval_token_id")
            if token_id and event.get("to_state") == "APPLIED":
                approvals["apply"] = token_id
            if token_id and event.get("to_state") == "RUN_APPROVED":
                approvals["execute"] = token_id
        manifest: Dict[str, Any] = {
            "schema_version": "agent-session-manifest-v1",
            "session_id": session_id,
            "parent_session_id": previous.get("parent_session_id"),
            "product": "backtrader-agent",
            "product_version": "0.1.0",
            "state": state,
            "state_revision": len(events),
            "last_sequence": len(events),
            "last_event_hash": last_hash,
            "journal": "journal.jsonl",
            "allowed_next_actions": sorted(TRANSITIONS[state]),
            "artifacts": artifacts,
            "approvals": approvals,
            "diagnostics": previous.get("diagnostics", []),
        }
        manifest["checkpoint_hash"] = hash_object(
            {key: value for key, value in manifest.items() if key != "checkpoint_hash"}
        )
        atomic_write_json(self._manifest_path(session_id), manifest)
        if state == "RUNNING":
            manifest = self.transition(
                session_id,
                "PAUSED",
                "session-recover",
                {"journal": last_hash},
            )
        return manifest

    def cancel(self, session_id: str) -> Dict[str, Any]:
        manifest = self.load(session_id)
        if manifest["state"] in TERMINAL:
            raise AgentError("BTAG-STATE-TERMINAL", "terminal session cannot be cancelled")
        return self.transition(session_id, "CANCELLED", "session-cancel", {})

    def archive(self, session_id: str) -> Dict[str, Any]:
        manifest = self.load(session_id)
        if manifest["state"] not in {"COMPLETED", "CANCELLED"}:
            raise AgentError(
                "BTAG-STATE-ARCHIVE", "only completed or cancelled sessions may archive"
            )
        return self.transition(session_id, "ARCHIVED", "session-archive", {})
