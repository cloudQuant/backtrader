"""Two-phase artifact rendering and hash-bound application."""

from __future__ import annotations

import difflib
import secrets
from pathlib import Path
from typing import Any

from .canonical import (
    atomic_write_bytes,
    atomic_write_json,
    canonical_hash,
    file_hash,
    load_json,
    resolve_inside,
    safe_identifier,
)
from .errors import ConflictError, ContractError, IntegrityError
from .generation import render_strategy
from .runtime import RuntimePaths
from .state import TokenStore, utc_now
from .validation import validate_python

ALLOWED_GENERATED_PREFIXES = (
    "strategies/generated/",
    "tests/functional/strategies/generated/",
)


class DraftManager:
    def __init__(self, paths: RuntimePaths) -> None:
        self.paths = paths.ensure()
        self.tokens = TokenStore(paths)

    def preview(
        self,
        spec: dict[str, Any],
        *,
        expected_hashes: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        artifact = render_strategy(spec)
        expected_hashes = expected_hashes or {}
        draft_id = f"draft_{artifact.spec['spec_hash'][:12]}_{secrets.token_hex(4)}"
        draft_root = self.paths.drafts / draft_id
        files_root = draft_root / "files"
        files_root.mkdir(parents=True, exist_ok=False)
        entries: list[dict[str, Any]] = []
        for item in artifact.files:
            self._check_output_path(item.relative_path)
            draft_path = resolve_inside(files_root, item.relative_path, must_exist=False)
            atomic_write_bytes(draft_path, item.content)
            target_path = resolve_inside(self.paths.target, item.relative_path, must_exist=False)
            actual_target_hash = file_hash(target_path) if target_path.is_file() else None
            expected_target_hash = expected_hashes.get(item.relative_path)
            if actual_target_hash is None:
                change = "create"
                diff = _diff("", item.content.decode("utf-8"), item.relative_path)
            else:
                change = "update" if expected_target_hash is not None else "conflict"
                diff = _diff(
                    target_path.read_text(encoding="utf-8"),
                    item.content.decode("utf-8"),
                    item.relative_path,
                )
            entries.append(
                {
                    "path": item.relative_path,
                    "role": item.role,
                    "bytes": len(item.content),
                    "sha256": item.sha256,
                    "change": change,
                    "expected_target_hash": expected_target_hash,
                    "observed_target_hash": actual_target_hash,
                    "diff": diff,
                }
            )
        manifest = {
            "schema_version": "artifact-manifest-v1",
            "draft_id": draft_id,
            "artifact_id": artifact.artifact_id,
            "spec_hash": artifact.spec["spec_hash"],
            "dataset_id": artifact.spec["dataset_id"],
            "strategy_source_hash": artifact.strategy_source_hash,
            "output_profile": artifact.spec["output_profile"],
            "created_at": utc_now(),
            "approval_state": "prepared",
            "overwrite_policy": "create-only-unless-expected-hash",
            "files": entries,
        }
        manifest["artifact_hash"] = canonical_hash(manifest)
        atomic_write_json(draft_root / "strategy-spec.json", artifact.spec)
        atomic_write_json(draft_root / "manifest.json", manifest)
        return manifest

    def get(self, draft_id: str) -> tuple[Path, dict[str, Any]]:
        safe_identifier(draft_id, field="draft_id")
        root = self.paths.drafts / draft_id
        path = root / "manifest.json"
        if not path.is_file():
            raise ContractError(f"unknown draft_id: {draft_id}")
        manifest = load_json(path)
        expected = manifest.get("artifact_hash")
        payload = dict(manifest)
        payload.pop("artifact_hash", None)
        if expected != canonical_hash(payload):
            raise IntegrityError("draft manifest hash is invalid")
        for entry in manifest["files"]:
            self._check_output_path(entry["path"])
            candidate = resolve_inside(root / "files", entry["path"], must_exist=True)
            if file_hash(candidate) != entry["sha256"]:
                raise IntegrityError(f"draft file changed after preview: {entry['path']}")
        return root, manifest

    def validate(self, draft_id: str) -> dict[str, Any]:
        root, manifest = self.get(draft_id)
        diagnostics: list[dict[str, Any]] = []
        file_reports: list[dict[str, Any]] = []
        for entry in manifest["files"]:
            if not entry["path"].endswith(".py"):
                continue
            candidate = resolve_inside(root / "files", entry["path"], must_exist=True)
            report = validate_python(candidate)
            file_reports.append(report)
            diagnostics.extend(report["diagnostics"])
        errors = sum(item["severity"] == "error" for item in diagnostics)
        report = {
            "schema_version": "validation-report-v1",
            "validation_id": f"val_{manifest['artifact_hash'][:24]}",
            "draft_id": draft_id,
            "artifact_hash": manifest["artifact_hash"],
            "dataset_id": manifest["dataset_id"],
            "spec_hash": manifest["spec_hash"],
            "status": "passed" if errors == 0 else "failed",
            "layers": {
                "specification": "passed",
                "python_ast": "passed" if errors == 0 else "failed",
                "fork_api": (
                    "passed"
                    if not any(
                        item["code"].startswith("BT_") and item["severity"] == "error"
                        for item in diagnostics
                    )
                    else "failed"
                ),
                "security": (
                    "passed"
                    if not any(
                        item["code"].startswith("SEC_") and item["severity"] == "error"
                        for item in diagnostics
                    )
                    else "failed"
                ),
                "import_collection": "pending",
                "smoke": "pending",
                "runonce_runnext": "pending",
                "target_test": "pending",
                "baseline": "pending",
                "artifact_integrity": "passed",
            },
            "files": file_reports,
            "diagnostics": diagnostics,
            "summary": {
                "errors": errors,
                "warnings": sum(item["severity"] == "warning" for item in diagnostics),
                "passed": errors == 0,
            },
        }
        report["evidence"] = {
            "layers": report["layers"],
            "files": report["files"],
            "summary": report["summary"],
        }
        report["validation_hash"] = canonical_hash(report)
        atomic_write_json(root / "validation-report.json", report)
        token = None
        if errors == 0:
            bindings = self._write_bindings(manifest, report)
            token = self.tokens.issue("render_write", bindings)
        return {
            "validation_report": report,
            "approval_token": token,
        }

    def apply(self, draft_id: str, token_id: str) -> dict[str, Any]:
        root, manifest = self.get(draft_id)
        report_path = root / "validation-report.json"
        if not report_path.is_file():
            raise ContractError("draft must be validated before apply")
        report = load_json(report_path)
        if not report["summary"]["passed"]:
            raise ContractError("draft validation failed")
        bindings = self._write_bindings(manifest, report)
        self.tokens.verify(token_id, "render_write", bindings)

        transaction_id = f"apply_{secrets.token_hex(12)}"
        transaction_root = root / "transactions" / transaction_id
        staged_root = transaction_root / "staged"
        backup_root = transaction_root / "backup"
        staged_root.mkdir(parents=True, exist_ok=False)
        journal_entries: list[dict[str, Any]] = []

        # Preflight and stage every byte before the first target mutation.
        for entry in manifest["files"]:
            target_path = resolve_inside(self.paths.target, entry["path"], must_exist=False)
            actual_hash = file_hash(target_path) if target_path.is_file() else None
            expected_hash = entry["expected_target_hash"]
            if actual_hash is not None and expected_hash is None:
                raise ConflictError(f"create-only target already exists: {entry['path']}")
            if expected_hash is not None and actual_hash != expected_hash:
                raise ConflictError(f"target changed after preview: {entry['path']}")
            draft_path = resolve_inside(root / "files", entry["path"], must_exist=True)
            content = draft_path.read_bytes()
            if file_hash(draft_path) != entry["sha256"]:
                raise IntegrityError(f"draft bytes changed before apply: {entry['path']}")
            staged_path = resolve_inside(staged_root, entry["path"], must_exist=False)
            atomic_write_bytes(staged_path, content)
            backup_path = None
            if target_path.is_file():
                backup_path = resolve_inside(backup_root, entry["path"], must_exist=False)
                atomic_write_bytes(backup_path, target_path.read_bytes())
            journal_entries.append(
                {
                    "path": entry["path"],
                    "target_existed": target_path.is_file(),
                    "before_hash": actual_hash,
                    "after_hash": entry["sha256"],
                    "staged_path": staged_path.relative_to(transaction_root).as_posix(),
                    "backup_path": (
                        backup_path.relative_to(transaction_root).as_posix()
                        if backup_path is not None
                        else None
                    ),
                    "state": "staged",
                }
            )
        journal = {
            "schema_version": "artifact-apply-journal-v1",
            "transaction_id": transaction_id,
            "draft_id": draft_id,
            "artifact_hash": manifest["artifact_hash"],
            "state": "staged",
            "entries": journal_entries,
            "created_at": utc_now(),
            "completed_at": None,
        }
        journal_path = transaction_root / "journal.json"
        atomic_write_json(journal_path, journal)
        committed: list[dict[str, Any]] = []
        try:
            journal["state"] = "committing"
            atomic_write_json(journal_path, journal)
            for journal_entry in journal_entries:
                target_path = resolve_inside(
                    self.paths.target, journal_entry["path"], must_exist=False
                )
                staged_path = resolve_inside(
                    transaction_root, journal_entry["staged_path"], must_exist=True
                )
                self._commit_target(target_path, staged_path.read_bytes())
                if file_hash(target_path) != journal_entry["after_hash"]:
                    raise IntegrityError(
                        f"target hash mismatch after apply: {journal_entry['path']}"
                    )
                journal_entry["state"] = "committed"
                committed.append(journal_entry)
                atomic_write_json(journal_path, journal)
            self.tokens.consume(token_id, "render_write", bindings)
        except Exception as error:
            rollback_errors = self._rollback_apply(transaction_root, committed)
            journal["state"] = "rollback_failed" if rollback_errors else "rolled_back"
            journal["rollback_errors"] = rollback_errors
            journal["completed_at"] = utc_now()
            atomic_write_json(journal_path, journal)
            if rollback_errors:
                raise IntegrityError(
                    "artifact apply failed and rollback was incomplete",
                    details={"rollback_errors": rollback_errors},
                ) from error
            raise IntegrityError(
                "artifact apply failed; committed files were rolled back"
            ) from error

        applied = [
            {"path": entry["path"], "sha256": entry["after_hash"]} for entry in journal_entries
        ]
        journal["state"] = "committed"
        journal["completed_at"] = utc_now()
        atomic_write_json(journal_path, journal)
        result = {
            "schema_version": "artifact-apply-result-v1",
            "draft_id": draft_id,
            "artifact_hash": manifest["artifact_hash"],
            "transaction_id": transaction_id,
            "applied_at": utc_now(),
            "files": applied,
        }
        atomic_write_json(root / "apply-result.json", result)
        return result

    @staticmethod
    def _commit_target(target: Path, content: bytes) -> None:
        atomic_write_bytes(target, content)

    def _rollback_apply(self, transaction_root: Path, committed: list[dict[str, Any]]) -> list[str]:
        errors = []
        for entry in reversed(committed):
            target = resolve_inside(self.paths.target, entry["path"], must_exist=False)
            try:
                if entry["target_existed"]:
                    backup = resolve_inside(transaction_root, entry["backup_path"], must_exist=True)
                    atomic_write_bytes(target, backup.read_bytes())
                    if file_hash(target) != entry["before_hash"]:
                        raise IntegrityError("restored target hash mismatch")
                elif target.exists():
                    target.unlink()
                entry["state"] = "rolled_back"
            except (OSError, IntegrityError) as error:
                errors.append(f"{entry['path']}: {error}")
        return errors

    @staticmethod
    def _write_bindings(manifest: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
        return {
            "draft_id": manifest["draft_id"],
            "artifact_hash": manifest["artifact_hash"],
            "spec_hash": manifest["spec_hash"],
            "validation_hash": report["validation_hash"],
            "operation": "render_apply",
        }

    @staticmethod
    def _check_output_path(relative_path: str) -> None:
        if not any(relative_path.startswith(prefix) for prefix in ALLOWED_GENERATED_PREFIXES):
            raise ContractError(f"artifact path is outside generated roots: {relative_path}")
        if Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
            raise ContractError("artifact path is unsafe")


def _diff(before: str, after: str, path: str, *, line_limit: int = 120) -> list[str]:
    lines = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        )
    )
    if len(lines) > line_limit:
        return [*lines[:line_limit], f"... diff truncated after {line_limit} lines ..."]
    return lines
