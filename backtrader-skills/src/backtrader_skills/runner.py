"""Hash-bound preparation and fixed, isolated dual-mode execution."""

from __future__ import annotations

import ast
import json
import os
import platform
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from .canonical import (
    atomic_write_json,
    canonical_hash,
    file_hash,
    load_json,
    resolve_inside,
    safe_identifier,
)
from .compare import compare_events, compare_metrics
from .data import DataRegistry
from .drafts import DraftManager
from .errors import ContractError, ExecutionError, IntegrityError, PathPolicyError
from .reports import write_run_reports
from .runtime import RuntimePaths
from .state import TokenStore, utc_now
from .validation import validate_python

PYTHON_EXECUTABLE = Path(sys.executable).resolve()
RUN_PREFIXES = (
    "strategies/generated/",
    "tests/functional/strategies/generated/",
)
MAX_CAPTURE_BYTES = 1024 * 1024


def _candidate_relative(target: Path, candidate: Path) -> str:
    target = target.resolve()
    candidate = candidate.resolve(strict=True)
    try:
        relative = candidate.relative_to(target).as_posix()
    except ValueError as error:
        raise PathPolicyError("candidate must be inside the target checkout") from error
    if not any(relative.startswith(prefix) for prefix in RUN_PREFIXES):
        raise PathPolicyError("candidate is outside generated execution roots")
    if not candidate.is_file() or candidate.suffix != ".py":
        raise PathPolicyError("candidate must be a generated Python file")
    return relative


def _spec_hash_from_ast(candidate: Path) -> str:
    tree = ast.parse(candidate.read_text(encoding="utf-8"), filename=candidate.name)
    for class_node in [node for node in tree.body if isinstance(node, ast.ClassDef)]:
        for statement in class_node.body:
            if not isinstance(statement, ast.Assign):
                continue
            if not any(
                isinstance(target, ast.Name) and target.id == "backtrader_skills_spec_hash"
                for target in statement.targets
            ):
                continue
            if isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str):
                return statement.value.value
    raise ContractError("generated candidate does not contain a literal StrategySpec hash")


def _applied_artifact_for_candidate(
    paths: RuntimePaths, relative: str, candidate: Path
) -> dict[str, Any]:
    """Prove candidate bytes came from an approved deterministic render/apply."""

    digest = file_hash(candidate)
    manager = DraftManager(paths)
    for manifest_path in sorted(paths.drafts.glob("*/manifest.json")):
        draft_id = manifest_path.parent.name
        try:
            root, manifest = manager.get(draft_id)
        except (ContractError, IntegrityError):
            continue
        entry = next(
            (
                item
                for item in manifest["files"]
                if item["path"] == relative and item["sha256"] == digest
            ),
            None,
        )
        if entry is None:
            continue
        apply_path = root / "apply-result.json"
        if not apply_path.is_file():
            continue
        applied = load_json(apply_path)
        if (
            applied.get("draft_id") == draft_id
            and applied.get("artifact_hash") == manifest["artifact_hash"]
            and {"path": relative, "sha256": digest} in applied.get("files", [])
        ):
            return manifest
    raise ContractError(
        "candidate is not an unchanged artifact produced by an approved render/apply"
    )


def _environment(target: Path) -> dict[str, Any]:
    version_file = target / "backtrader" / "version.py"
    if not version_file.is_file():
        raise ContractError("target does not contain the expected Backtrader source package")
    entry = Path(__file__).with_name("isolate_entry.py")
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "backtrader_version_file_hash": file_hash(version_file),
        "child_entry_hash": file_hash(entry),
        "product_version": "0.1.0",
    }


class ControlledRunner:
    def __init__(self, paths: RuntimePaths) -> None:
        self.paths = paths.ensure()
        self.tokens = TokenStore(paths)
        self.datasets = DataRegistry(paths)

    def prepare(
        self, candidate: Path, dataset_id: str, *, timeout_seconds: int = 120
    ) -> dict[str, Any]:
        if not 1 <= timeout_seconds <= 600:
            raise ContractError("timeout_seconds must be between 1 and 600")
        relative = _candidate_relative(self.paths.target, candidate)
        candidate_path = resolve_inside(self.paths.target, relative, must_exist=True)
        source_artifact = _applied_artifact_for_candidate(self.paths, relative, candidate_path)
        validation = validate_python(candidate_path, generated_only=True)
        if not validation["summary"]["passed"]:
            raise ContractError(
                "candidate failed static validation",
                details={"diagnostics": validation["diagnostics"]},
            )
        dataset = self.datasets.get_manifest(dataset_id, verify=True)
        environment = _environment(self.paths.target)
        run_seed = {
            "candidate_sha256": file_hash(candidate_path),
            "dataset_manifest_hash": dataset["manifest_hash"],
            "environment_hash": canonical_hash(environment),
            "prepared_at": utc_now(),
        }
        run_id = f"run_{canonical_hash(run_seed)[:20]}"
        approval_id = f"approval_{secrets.token_hex(12)}"
        run_dir = self.paths.runs / run_id
        entry = Path(__file__).with_name("isolate_entry.py").resolve()
        manifest = {
            "schema_version": "run-manifest-v1",
            "run_id": run_id,
            "artifact_hash": file_hash(candidate_path),
            "dataset_id": dataset_id,
            "engine": {
                "name": "backtrader",
                "source": "target-checkout",
                "version_file_hash": environment["backtrader_version_file_hash"],
            },
            "run_profile": {
                "modes": ["runonce", "runnext"],
                "comparison_profile": "comparison-profile-v1",
                "timeout_seconds": timeout_seconds,
            },
            "approval_id": approval_id,
            "candidate": {
                "relative_path": relative,
                "sha256": file_hash(candidate_path),
                "strategy_spec_hash": _spec_hash_from_ast(candidate_path),
                "source_draft_id": source_artifact["draft_id"],
                "source_artifact_hash": source_artifact["artifact_hash"],
            },
            "dataset": {
                "dataset_id": dataset_id,
                "manifest_hash": dataset["manifest_hash"],
                "semantic_hash": dataset["semantic_hash"],
            },
            "environment": environment,
            "environment_hash": canonical_hash(environment),
            "modes": ["runonce", "runnext"],
            "fixed_argv": [
                str(PYTHON_EXECUTABLE),
                "-I",
                str(entry),
                "--target",
                "<target>",
                "--candidate",
                relative,
                "--dataset-id",
                dataset_id,
                "--mode",
                "<mode>",
            ],
            "cwd": "<isolated-temporary-directory>",
            "allowed_environment": [
                "PATH",
                "LANG",
                "LC_ALL",
                "TMPDIR",
                "PYTHONDONTWRITEBYTECODE",
                "PYTHONNOUSERSITE",
                "NO_PROXY",
            ],
            "timeout_seconds": timeout_seconds,
            "created_at": utc_now(),
        }
        manifest["manifest_hash"] = canonical_hash(manifest)
        run_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(run_dir / "run-manifest.json", manifest)
        atomic_write_json(run_dir / "static-validation.json", validation)
        token = self.tokens.issue("run_execution", self._bindings(manifest))
        return {"run_manifest": manifest, "approval_token": token}

    def execute(self, run_id: str, token_id: str) -> dict[str, Any]:
        safe_identifier(run_id, field="run_id")
        run_dir = self.paths.runs / run_id
        manifest_path = run_dir / "run-manifest.json"
        if not manifest_path.is_file():
            raise ContractError(f"unknown run_id: {run_id}")
        manifest = load_json(manifest_path)
        expected_manifest_hash = manifest.get("manifest_hash")
        payload = dict(manifest)
        payload.pop("manifest_hash", None)
        if expected_manifest_hash != canonical_hash(payload):
            raise IntegrityError("RunManifest hash is invalid")
        candidate_path = resolve_inside(
            self.paths.target, manifest["candidate"]["relative_path"], must_exist=True
        )
        if file_hash(candidate_path) != manifest["candidate"]["sha256"]:
            raise IntegrityError("candidate changed after execution approval was prepared")
        dataset = self.datasets.get_manifest(manifest["dataset"]["dataset_id"], verify=True)
        if dataset["manifest_hash"] != manifest["dataset"]["manifest_hash"]:
            raise IntegrityError("DatasetManifest changed after execution approval was prepared")
        if canonical_hash(_environment(self.paths.target)) != manifest["environment_hash"]:
            raise IntegrityError("execution environment changed after approval was prepared")
        bindings = self._bindings(manifest)
        self.tokens.verify(token_id, "run_execution", bindings)
        self.tokens.consume(token_id, "run_execution", bindings)
        modes = {
            mode: self._run_mode(manifest, candidate_path, mode, run_dir)
            for mode in manifest["modes"]
        }
        metric_comparison = compare_metrics(
            modes["runonce"]["metrics"], modes["runnext"]["metrics"]
        )
        event_comparison = compare_events(modes["runonce"]["events"], modes["runnext"]["events"])
        status = (
            "passed" if metric_comparison["passed"] and event_comparison["passed"] else "failed"
        )
        result = {
            "schema_version": "run-result-v1",
            "run_id": run_id,
            "manifest_hash": manifest["manifest_hash"],
            "status": status,
            "metrics": modes["runonce"]["metrics"],
            "modes": modes,
            "comparison": {"metrics": metric_comparison, "events": event_comparison},
            "artifacts": [],
            "diagnostics": [],
        }
        result["result_hash"] = canonical_hash(result)
        artifacts = write_run_reports(run_dir, result)
        result["artifacts"] = artifacts
        result["result_hash"] = canonical_hash(
            {key: value for key, value in result.items() if key != "result_hash"}
        )
        atomic_write_json(run_dir / "run-result.json", result)
        return result

    def _run_mode(
        self, manifest: dict[str, Any], candidate: Path, mode: str, run_dir: Path
    ) -> dict[str, Any]:
        if not PYTHON_EXECUTABLE.is_file():
            raise ExecutionError("the installed product Python executable is unavailable")
        entry = Path(__file__).with_name("isolate_entry.py").resolve()
        command = [
            str(PYTHON_EXECUTABLE),
            "-I",
            str(entry),
            "--target",
            str(self.paths.target),
            "--candidate",
            str(candidate),
            "--dataset-id",
            manifest["dataset"]["dataset_id"],
            "--mode",
            mode,
        ]
        working = run_dir / f"cwd-{mode}"
        working.mkdir(parents=True, exist_ok=True)
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "LANG", "LC_ALL", "TMPDIR"}
        }
        environment.update(
            {
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONNOUSERSITE": "1",
                "NO_PROXY": "*",
            }
        )
        try:
            completed = subprocess.run(
                command,
                cwd=working,
                env=environment,
                capture_output=True,
                text=True,
                timeout=manifest["timeout_seconds"],
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise ExecutionError(f"{mode} child process timed out") from error
        stdout = completed.stdout[-MAX_CAPTURE_BYTES:]
        stderr = _sanitize(completed.stderr[-MAX_CAPTURE_BYTES:], self.paths.target)
        if completed.returncode != 0:
            raise ExecutionError(
                f"{mode} child process failed",
                details={"returncode": completed.returncode, "stderr": stderr[-4000:]},
            )
        lines = [line for line in stdout.splitlines() if line.strip()]
        if not lines:
            raise ExecutionError(f"{mode} child process returned no structured result")
        try:
            result = json.loads(lines[-1])
        except json.JSONDecodeError as error:
            raise ExecutionError(f"{mode} child result was not valid JSON") from error
        result["stderr_summary"] = stderr[-4000:]
        result["stdout_truncated"] = len(completed.stdout.encode("utf-8")) > MAX_CAPTURE_BYTES
        atomic_write_json(run_dir / f"{mode}.json", result)
        return cast(dict[str, Any], result)

    @staticmethod
    def _bindings(manifest: dict[str, Any]) -> dict[str, Any]:
        return {
            "run_id": manifest["run_id"],
            "run_manifest_hash": manifest["manifest_hash"],
            "candidate_sha256": manifest["candidate"]["sha256"],
            "dataset_manifest_hash": manifest["dataset"]["manifest_hash"],
            "environment_hash": manifest["environment_hash"],
            "operation": "run_execute",
        }


def _sanitize(value: str, target: Path) -> str:
    sanitized = value.replace(str(target.resolve()), "<target>")
    sanitized = sanitized.replace(str(Path.home()), "<home>")
    return sanitized
