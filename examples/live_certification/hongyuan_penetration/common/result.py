"""Unified PASS / FAIL / BLOCKED result model and persistence."""
from __future__ import annotations

import datetime as _dt
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_BLOCKED = 2

VALID_STATUSES = ("PASS", "FAIL", "BLOCKED")


@dataclass
class CaseResult:
    """Structured result for a single certification case."""

    case_id: str
    case_name: str
    status: str  # PASS / FAIL / BLOCKED
    started_at: str = ""
    finished_at: str = ""
    duration_seconds: float = 0.0
    env: str = ""
    evidence: List[str] = field(default_factory=list)
    failure_reason: str = ""
    next_action: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def exit_code(self) -> int:
        return {"PASS": EXIT_PASS, "FAIL": EXIT_FAIL, "BLOCKED": EXIT_BLOCKED}.get(
            self.status, EXIT_FAIL
        )


def save_result(result: CaseResult, report_dir: str | Path) -> Path:
    """Persist *result* as ``report_dir/result.json``."""
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / "result.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(result.to_dict(), fh, ensure_ascii=False, indent=2)
    return path


class CaseTimer:
    """Context-manager that tracks wall-clock time for a case execution."""

    def __init__(self, case_id: str, case_name: str, env: str = ""):
        self.case_id = case_id
        self.case_name = case_name
        self.env = env
        self._start: _dt.datetime | None = None

    def __enter__(self):
        self._start = _dt.datetime.now()
        return self

    def __exit__(self, *exc):
        pass

    def pass_result(self, evidence=None, details=None) -> CaseResult:
        return self._build("PASS", evidence=evidence, details=details)

    def fail_result(self, reason: str, evidence=None, details=None) -> CaseResult:
        return self._build("FAIL", reason=reason, evidence=evidence, details=details)

    def blocked_result(
        self, reason: str, next_action: str = "", evidence=None, details=None
    ) -> CaseResult:
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
        return CaseResult(
            case_id=self.case_id,
            case_name=self.case_name,
            status=status,
            started_at=self._start.isoformat() if self._start else "",
            finished_at=now.isoformat(),
            duration_seconds=elapsed,
            env=self.env,
            evidence=evidence or [],
            failure_reason=reason,
            next_action=next_action,
            details=details or {},
        )
