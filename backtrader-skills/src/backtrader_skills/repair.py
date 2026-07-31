"""Deterministic repair by returning to validated IR and re-rendering."""

from __future__ import annotations

from typing import Any

from .canonical import load_json
from .drafts import DraftManager
from .errors import ContractError
from .runtime import RuntimePaths

RENDER_REPAIR_CODES = {
    "BT_DIRECT_STRATEGY_SUPER_REDUNDANT",
    "BT_GENERATED_MARKER_MISSING",
    "PY_SYNTAX_ERROR",
}


def preview_repair(paths: RuntimePaths, draft_id: str) -> dict[str, Any]:
    """Re-render the stored StrategySpec; never patch arbitrary candidate source."""

    manager = DraftManager(paths)
    draft_root, _ = manager.get(draft_id)
    report_path = draft_root / "validation-report.json"
    spec_path = draft_root / "strategy-spec.json"
    if not report_path.is_file() or not spec_path.is_file():
        raise ContractError("repair requires a validated product-generated draft")
    report = load_json(report_path)
    codes = {item["code"] for item in report.get("diagnostics", [])}
    unsafe = codes - RENDER_REPAIR_CODES
    if unsafe:
        raise ContractError(
            "diagnostics require a StrategySpec change and cannot be source-patched",
            details={"codes": sorted(unsafe)},
        )
    repaired = manager.preview(load_json(spec_path))
    return {
        "schema_version": "repair-preview-v1",
        "source_draft_id": draft_id,
        "method": "validated-ir-rerender",
        "handled_codes": sorted(codes),
        "new_draft": repaired,
    }


def preview_spec_repair(
    paths: RuntimePaths,
    revised_spec: dict[str, Any],
    validation_report: dict[str, Any],
) -> dict[str, Any]:
    """Render an AI/user-revised typed spec while preserving the failed evidence link."""

    if validation_report.get("schema_version") != "validation-report-v1":
        raise ContractError("repair evidence must be ValidationReport v1")
    diagnostics = validation_report.get("diagnostics")
    if not isinstance(diagnostics, list) or not diagnostics:
        raise ContractError("repair evidence must contain at least one diagnostic")
    repaired = DraftManager(paths).preview(revised_spec)
    return {
        "schema_version": "repair-preview-v1",
        "source_validation_hash": validation_report.get("validation_hash"),
        "method": "typed-ir-revision-and-rerender",
        "handled_codes": sorted(
            {
                str(item.get("code"))
                for item in diagnostics
                if isinstance(item, dict) and item.get("code")
            }
        ),
        "new_draft": repaired,
    }
