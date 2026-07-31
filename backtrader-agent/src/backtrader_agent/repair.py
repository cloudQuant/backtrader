"""Deterministic repair by revising intent and re-rendering owned scaffolds."""

from pathlib import Path
from typing import Any, Dict

from .canonical import hash_object
from .contracts import StrategySpec
from .errors import AgentError
from .scaffold import ArtifactRenderer
from .sessions import SessionStore


class RepairWorkflow:
    """Repair only product-owned drafts; never apply arbitrary source patches."""

    def __init__(self, state_root: Path) -> None:
        self.state_root = Path(state_root)
        self.sessions = SessionStore(self.state_root)

    def rerender(
        self,
        session_id: str,
        revised_spec: Dict[str, Any],
        dataset_manifest: Dict[str, Any],
        failure_report: Dict[str, Any],
    ) -> Dict[str, Any]:
        session = self.sessions.load(session_id)
        if session["state"] not in {"FAILED", "NEEDS_REVALIDATION"}:
            raise AgentError(
                "BTAG-REPAIR-STATE",
                "repair requires a failed or invalidated session",
                details={"state": session["state"]},
            )
        if failure_report.get("schema_version") not in {
            "validation-report-v1",
            "run-result-v1",
        }:
            raise AgentError(
                "BTAG-REPAIR-REPORT",
                "failure report must be ValidationReport v1 or RunResult v1",
            )
        if failure_report.get("status") not in {"failed", "error"}:
            raise AgentError("BTAG-REPAIR-REPORT", "failure report is not a failed result")
        diagnostics = failure_report.get("diagnostics")
        if not isinstance(diagnostics, list) or not diagnostics:
            raise AgentError(
                "BTAG-REPAIR-DIAGNOSTICS",
                "repair requires at least one structured diagnostic",
            )

        spec = StrategySpec.from_dict(revised_spec)
        previous_spec_hash = session.get("artifacts", {}).get("approved_spec_hash")
        if previous_spec_hash == spec.spec_hash:
            raise AgentError(
                "BTAG-REPAIR-NO-CHANGE",
                "revised StrategySpec must differ from the previously approved specification",
            )
        failure_hash = hash_object(failure_report)
        if session["state"] == "FAILED":
            self.sessions.transition(
                session_id,
                "REPAIRING",
                "repair-start",
                {"failure_report": failure_hash},
                effect_references={"failed_report_hash": failure_hash},
            )

        artifact = ArtifactRenderer(self.state_root).render(
            session_id,
            spec,
            dataset_manifest,
        )
        self.sessions.transition(
            session_id,
            "DRAFT_READY",
            "repair-rerender",
            {
                "failure_report": failure_hash,
                "revised_spec": spec.spec_hash,
                "artifact": artifact["artifact_hash"],
            },
            effect_references={
                "revised_spec_hash": spec.spec_hash,
                "artifact_hash": artifact["artifact_hash"],
            },
        )
        return {
            **artifact,
            "repair": {
                "schema_version": "repair-result-v1",
                "failure_report_hash": failure_hash,
                "previous_spec_hash": previous_spec_hash,
                "revised_spec_hash": spec.spec_hash,
                "old_approvals_reusable": False,
                "next_action": "validate",
            },
        }
