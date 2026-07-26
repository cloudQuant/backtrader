"""Unified PASS / FAIL / BLOCKED result model and persistence."""
from __future__ import annotations

import datetime as _dt
import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from common.certification import get_certification_scenario

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_BLOCKED = 2

VALID_STATUSES = ("PASS", "FAIL", "BLOCKED")


def _collect_observed_events(value: Any, parent_key: str = "") -> set[str]:
    """Extract event names from nested result details."""
    events: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            events.update(_collect_observed_events(item, str(key)))
    elif isinstance(value, (list, tuple, set)):
        if "event" in parent_key or parent_key in {"events", "remote"}:
            events.update(str(item) for item in value if isinstance(item, str))
        for item in value:
            events.update(_collect_observed_events(item, parent_key))
    elif isinstance(value, str) and ("event" in parent_key or parent_key in {"events", "remote"}):
        events.add(value)
    return events


def _collect_evidence_field_names(value: Any) -> set[str]:
    """Extract available evidence field names from nested result details."""
    fields: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            fields.add(str(key))
            fields.update(_collect_evidence_field_names(item))
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            fields.update(_collect_evidence_field_names(item))
    return fields


@dataclass
class CaseResult:
    """Structured result for a single certification case."""

    case_id: str
    case_name: str
    status: str  # PASS / FAIL / BLOCKED
    scenario_id: str = ""
    scenario_name: str = ""
    category: str = ""
    trace_id: str = ""
    started_at: str = ""
    finished_at: str = ""
    duration_seconds: float = 0.0
    simnow_env: str = ""
    required_events: List[str] = field(default_factory=list)
    evidence_fields: List[str] = field(default_factory=list)
    pass_conditions: List[str] = field(default_factory=list)
    optional: bool = False
    observed_events: List[str] = field(default_factory=list)
    missing_required_events: List[str] = field(default_factory=list)
    required_events_present: bool = False
    missing_evidence_fields: List[str] = field(default_factory=list)
    evidence_fields_present: bool = False
    evidence: List[str] = field(default_factory=list)
    failure_reason: str = ""
    next_action: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    audit_events: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert case result to dictionary.

        Returns:
            Dictionary representation of the case result.
        """
        return asdict(self)

    def exit_code(self) -> int:
        """Get exit code for the case result.

        Returns:
            Exit code: 0 for PASS, 1 for FAIL, 2 for BLOCKED.
        """
        return {"PASS": EXIT_PASS, "FAIL": EXIT_FAIL, "BLOCKED": EXIT_BLOCKED}.get(
            self.status, EXIT_FAIL
        )


def save_result(result: CaseResult, report_dir: str | Path) -> Path:
    """Persist *result* as ``report_dir/result.json``."""
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    if result.audit_events:
        audit_path = report_dir / "audit.jsonl"
        with open(audit_path, "w", encoding="utf-8") as fh:
            for event in result.audit_events:
                fh.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        audit_path_text = str(audit_path)
        if audit_path_text not in result.evidence:
            result.evidence.append(audit_path_text)

    path = report_dir / "result.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(result.to_dict(), fh, ensure_ascii=False, indent=2)
    return path


class CaseTimer:
    """Context-manager that tracks wall-clock time for a case execution."""

    def __init__(self, case_id: str, case_name: str, simnow_env: str = ""):
        """Initialize case timer.

        Args:
            case_id: Case identifier.
            case_name: Name of the case.
            simnow_env: SimNow environment key (optional).
        """
        self.case_id = case_id
        self.case_name = case_name
        self.simnow_env = simnow_env
        self.trace_id = self._new_trace_id()
        self._start: _dt.datetime | None = None

    def __enter__(self):
        """Start the timer when entering context.

        Returns:
            Self reference.
        """
        self._start = _dt.datetime.now()
        return self

    def __exit__(self, *exc):
        """Exit the context manager."""
        pass

    def pass_result(self, evidence=None, details=None) -> CaseResult:
        """Create a PASS result.

        Args:
            evidence: Evidence files or data.
            details: Additional details dictionary.

        Returns:
            CaseResult with PASS status.
        """
        return self._build("PASS", evidence=evidence, details=details)

    def fail_result(self, reason: str, evidence=None, details=None) -> CaseResult:
        """Create a FAIL result.

        Args:
            reason: Failure reason string.
            evidence: Evidence files or data.
            details: Additional details dictionary.

        Returns:
            CaseResult with FAIL status.
        """
        return self._build("FAIL", reason=reason, evidence=evidence, details=details)

    def blocked_result(
        self, reason: str, next_action: str = "", evidence=None, details=None
    ) -> CaseResult:
        """Create a BLOCKED result.

        Args:
            reason: Reason for blocking.
            next_action: Recommended next action.
            evidence: Evidence files or data.
            details: Additional details dictionary.

        Returns:
            CaseResult with BLOCKED status.
        """
        return self._build(
            "BLOCKED",
            reason=reason,
            next_action=next_action,
            evidence=evidence,
            details=details,
        )

    def _build(
        self,
        status: str,
        reason: str = "",
        next_action: str = "",
        evidence=None,
        details=None,
    ) -> CaseResult:
        now = _dt.datetime.now()
        elapsed = (
            round((now - self._start).total_seconds(), 2) if self._start else 0.0
        )
        details = details or {}
        scenario = get_certification_scenario(self.case_id)
        observed_events = sorted(_collect_observed_events(details))
        evidence_field_names = _collect_evidence_field_names(details)
        missing_required_events = [
            event for event in scenario.required_events if event not in observed_events
        ]
        missing_evidence_fields = [
            field for field in scenario.evidence_fields if field not in evidence_field_names
        ]
        final_status = status
        final_reason = reason
        if status == "PASS" and (missing_required_events or missing_evidence_fields):
            final_status = "FAIL"
            missing_parts = []
            if missing_required_events:
                missing_parts.append("events=" + ",".join(missing_required_events))
            if missing_evidence_fields:
                missing_parts.append("fields=" + ",".join(missing_evidence_fields))
            final_reason = (
                reason
                or "Missing required certification evidence: " + "; ".join(missing_parts)
            )
        audit_event = {
            "event_type": "certification_case_result",
            "event_id": str(uuid.uuid4()),
            "trace_id": self.trace_id,
            "case_id": self.case_id,
            "scenario_id": scenario.scenario_id,
            "scenario_name": scenario.name,
            "category": scenario.category,
            "status": final_status,
            "severity": "ERROR" if final_status == "FAIL" else "INFO",
            "timestamp": now.isoformat(),
            "simnow_env": self.simnow_env,
            "message": final_reason or (
                "case passed" if final_status == "PASS" else final_status.lower()
            ),
            "required_events": list(scenario.required_events),
            "evidence_fields": list(scenario.evidence_fields),
            "observed_events": observed_events,
            "missing_required_events": missing_required_events,
            "missing_evidence_fields": missing_evidence_fields,
            "required_events_present": not missing_required_events,
            "evidence_fields_present": not missing_evidence_fields,
            "evidence": evidence or [],
            "details": details,
        }
        return CaseResult(
            case_id=self.case_id,
            case_name=self.case_name,
            status=final_status,
            scenario_id=scenario.scenario_id,
            scenario_name=scenario.name,
            category=scenario.category,
            trace_id=self.trace_id,
            started_at=self._start.isoformat() if self._start else "",
            finished_at=now.isoformat(),
            duration_seconds=elapsed,
            simnow_env=self.simnow_env,
            required_events=list(scenario.required_events),
            evidence_fields=list(scenario.evidence_fields),
            pass_conditions=list(scenario.pass_conditions),
            optional=scenario.optional,
            observed_events=observed_events,
            missing_required_events=missing_required_events,
            required_events_present=not missing_required_events,
            missing_evidence_fields=missing_evidence_fields,
            evidence_fields_present=not missing_evidence_fields,
            evidence=evidence or [],
            failure_reason=final_reason,
            next_action=next_action,
            details=details,
            audit_events=[audit_event],
        )

    @staticmethod
    def _new_trace_id() -> str:
        timestamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        return f"ctp-cert-{timestamp}-{uuid.uuid4().hex[:8]}"
