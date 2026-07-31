"""Stable public error types and codes."""

from __future__ import annotations


class SkillsError(Exception):
    """Base error carrying a stable machine-readable code."""

    code = "BTSKILL_ERROR"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class ContractError(SkillsError):
    code = "CONTRACT_INVALID"


class PathPolicyError(SkillsError):
    code = "PATH_POLICY_VIOLATION"


class IntegrityError(SkillsError):
    code = "INTEGRITY_MISMATCH"


class ApprovalError(SkillsError):
    code = "APPROVAL_REQUIRED"


class ConflictError(SkillsError):
    code = "TARGET_CONFLICT"


class ExecutionError(SkillsError):
    code = "EXECUTION_FAILED"
