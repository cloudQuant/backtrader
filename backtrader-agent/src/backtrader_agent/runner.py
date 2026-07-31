"""Fixed-profile child-process runner. Candidate modules are never host-imported."""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .canonical import (
    atomic_write_bytes,
    atomic_write_json,
    hash_object,
    read_json,
    sha256_bytes,
)
from .data import DatasetService
from .errors import AgentError
from .engines import inspect_engine
from .report import ReportRenderer, normalize_metrics
from .roots import RootRegistry
from .sessions import SessionStore
from .tokens import TokenAuthority

IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,127}$")
RESULT_PREFIX = "BACKTRADER_AGENT_RESULT="
ENGINE_PROBE = (
    "import json,pathlib,backtrader;"
    "print(json.dumps({'path':str(pathlib.Path(backtrader.__file__).resolve()),"
    "'version':getattr(backtrader,'__version__','unknown')},sort_keys=True))"
)


def _resource_limits(timeout_seconds: int):
    def set_limits() -> None:
        try:
            import resource

            resource.setrlimit(resource.RLIMIT_CPU, (timeout_seconds + 2, timeout_seconds + 2))
            resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))
            address_limit = 2 * 1024 * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (address_limit, address_limit))
        except (ImportError, OSError, ValueError):
            # The command remains allowlisted and timeout-bound where a specific
            # POSIX resource limit is unavailable.
            return

    return set_limits


class ControlledRunner:
    MAX_OUTPUT_BYTES = 1024 * 1024

    def __init__(self, roots: RootRegistry, state_root: Path, authority: TokenAuthority) -> None:
        self.roots = roots
        self.state_root = Path(state_root)
        self.authority = authority
        self.action_root = self.state_root / "actions"

    @staticmethod
    def compute_run_subject(
        applied: Dict[str, Any],
        dataset: Dict[str, Any],
        validation_token: Dict[str, Any],
        *,
        mode: str,
    ) -> str:
        if mode not in {"runonce", "runnext"}:
            raise AgentError("BTAG-RUN-MODE", "mode must be runonce or runnext")
        return hash_object(
            {
                "applied_artifact_hash": applied["applied_artifact_hash"],
                "dataset_manifest_hash": dataset["manifest_hash"],
                "validation_token_id": validation_token["token_id"],
                "mode": mode,
                "profile": "controlled-runner-v1",
            }
        )

    def _verify_applied(self, applied: Dict[str, Any]) -> None:
        payload = {
            key: value
            for key, value in applied.items()
            if key not in {"applied_artifact_hash", "applied_record_hash", "status"}
        }
        if hash_object(payload) != applied.get("applied_artifact_hash"):
            raise AgentError("BTAG-RUN-ARTIFACT-HASH", "applied artifact hash is invalid")
        if applied.get("generated_by") != "backtrader-agent":
            raise AgentError("BTAG-RUN-ORIGIN", "runner only accepts product-generated artifacts")
        required = {
            "artifact_record_hash",
            "dataset_id",
            "dataset_manifest_hash",
            "session_id",
            "spec_hash",
            "validation_token_hash",
            "validation_token_id",
        }
        if any(not isinstance(applied.get(field), str) for field in required):
            raise AgentError("BTAG-RUN-PROVENANCE", "applied artifact provenance is incomplete")
        record = self.authority.load_bound_record(
            "applied-artifact",
            applied["session_id"],
            applied["applied_artifact_hash"],
        )
        canonical_applied = {
            key: value for key, value in applied.items() if key != "applied_record_hash"
        }
        if (
            applied.get("applied_record_hash") != record.get("record_hash")
            or record.get("applied_artifact") != canonical_applied
        ):
            raise AgentError(
                "BTAG-RUN-PROVENANCE",
                "applied artifact does not match its signed product record",
            )
        session = SessionStore(self.state_root).load(applied["session_id"])
        artifacts = session.get("artifacts", {})
        expected = {
            "applied_artifact_hash": applied["applied_artifact_hash"],
            "applied_record_hash": applied["applied_record_hash"],
            "artifact_hash": applied["artifact_hash"],
            "artifact_record_hash": applied["artifact_record_hash"],
            "approved_spec_hash": applied["spec_hash"],
            "change_manifest_hash": applied["change_manifest_hash"],
            "dataset_id": applied["dataset_id"],
            "dataset_manifest_hash": applied["dataset_manifest_hash"],
            "validation_token_hash": applied["validation_token_hash"],
            "validation_token_id": applied["validation_token_id"],
        }
        if any(artifacts.get(key) != value for key, value in expected.items()):
            raise AgentError(
                "BTAG-RUN-PROVENANCE",
                "applied artifact does not match the product session checkpoint",
            )

    def _verify_registered_dataset(self, dataset: Dict[str, Any]) -> Dict[str, Any]:
        payload = {key: value for key, value in dataset.items() if key != "manifest_hash"}
        if hash_object(payload) != dataset.get("manifest_hash"):
            raise AgentError("BTAG-RUN-DATASET-HASH", "dataset manifest hash is invalid")
        if dataset.get("schema_version") != "dataset-manifest-v1":
            raise AgentError("BTAG-RUN-DATASET-HASH", "dataset manifest version is invalid")
        registered = DatasetService(self.roots, self.state_root).load(str(dataset["dataset_id"]))
        if registered != dataset:
            raise AgentError(
                "BTAG-RUN-DATASET-REGISTRY",
                "runner accepts only the exact registered DatasetManifest",
            )
        return registered

    def _action_path(self, key: str) -> Path:
        if not IDEMPOTENCY_RE.fullmatch(key):
            raise AgentError("BTAG-IDEMPOTENCY-KEY", "idempotency key is malformed")
        return self.action_root / f"run-{sha256_bytes(key.encode('utf-8'))}.json"

    @staticmethod
    def _persist_exact_bytes(path: Path, content: bytes) -> None:
        if path.exists():
            if path.is_symlink() or not path.is_file() or path.read_bytes() != content:
                raise AgentError(
                    "BTAG-RUN-CONFLICT",
                    "persisted run artifact conflicts with the approved effect",
                )
            return
        try:
            atomic_write_bytes(path, content, create_only=True)
        except AgentError as exc:
            if exc.code != "BTAG-WRITE-EXISTS":
                raise
            if path.is_symlink() or not path.is_file() or path.read_bytes() != content:
                raise AgentError(
                    "BTAG-RUN-CONFLICT",
                    "persisted run artifact conflicts with the approved effect",
                ) from exc

    @classmethod
    def _persist_exact_json(cls, path: Path, value: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".json-stage-", dir=str(path.parent)) as name:
            staged = Path(name) / "value.json"
            atomic_write_json(staged, value, create_only=True)
            cls._persist_exact_bytes(path, staged.read_bytes())

    def _render_reports_resumable(
        self,
        run_root: Path,
        result: Dict[str, Any],
    ) -> Dict[str, str]:
        run_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=f".{result['run_id']}.report-stage-",
            dir=str(run_root.parent),
        ) as name:
            staged_root = Path(name)
            report_files = ReportRenderer().render(staged_root, result)
            for filename in (
                report_files["result"],
                report_files["markdown"],
                report_files["html"],
            ):
                self._persist_exact_bytes(
                    run_root / filename,
                    (staged_root / filename).read_bytes(),
                )
        return report_files

    @staticmethod
    def _verify_persisted_result(
        result: Dict[str, Any],
        *,
        run_id: str,
        mode: str,
        applied: Dict[str, Any],
        dataset: Dict[str, Any],
        validation_token: Dict[str, Any],
        run_token: Dict[str, Any],
    ) -> None:
        payload = {key: value for key, value in result.items() if key != "result_hash"}
        extension = result.get("extensions", {}).get("backtrader_agent", {})
        if (
            result.get("run_id") != run_id
            or result.get("status") != "passed"
            or hash_object(payload) != result.get("result_hash")
            or extension.get("mode") != mode
            or extension.get("dataset_manifest_hash") != dataset["manifest_hash"]
            or extension.get("applied_artifact_hash") != applied["applied_artifact_hash"]
            or extension.get("validation_token_id") != validation_token["token_id"]
            or extension.get("run_token_id") != run_token["token_id"]
        ):
            raise AgentError(
                "BTAG-RUN-CONFLICT",
                "persisted run result conflicts with the approved effect",
            )

    @staticmethod
    def _verify_persisted_manifest(
        run_root: Path,
        result: Dict[str, Any],
        expected: Dict[str, Any],
    ) -> None:
        manifest_path = run_root / "run-manifest.json"
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise AgentError("BTAG-RUN-CONFLICT", "persisted run manifest is absent or unsafe")
        manifest = read_json(manifest_path)
        payload = {key: value for key, value in manifest.items() if key != "manifest_hash"}
        if (
            manifest != expected
            or hash_object(payload) != manifest.get("manifest_hash")
            or manifest.get("manifest_hash")
            != result.get("extensions", {}).get("backtrader_agent", {}).get("manifest_hash")
        ):
            raise AgentError("BTAG-RUN-CONFLICT", "persisted run manifest is invalid")

    @staticmethod
    def _redact_stderr(
        stderr: str,
        *,
        state_root: Path,
        entrypoint: Path,
        descriptors: List[Dict[str, Any]],
    ) -> str:
        redacted = stderr[-2000:]
        replacements = {
            str(state_root.resolve()): "<state>",
            str(entrypoint.parent.resolve()): "<artifact>",
            str(Path(sys.executable).resolve().parent): "<runtime>",
        }
        replacements.update(
            {str(Path(item["path"]).resolve()): "<dataset>" for item in descriptors}
        )
        for value, label in sorted(replacements.items(), key=lambda item: -len(item[0])):
            redacted = redacted.replace(value, label)
        redacted = re.sub(
            r"(?<![A-Za-z0-9_])/(?:[A-Za-z0-9._~+@%=-]+/)*[A-Za-z0-9._~+@%=-]+",
            "<path>",
            redacted,
        )
        redacted = re.sub(
            r"\b[A-Za-z]:\\(?:[^\\\s:'\"]+\\)*[^\\\s:'\"]+",
            "<path>",
            redacted,
        )
        return redacted

    @staticmethod
    def _begin_or_resume_session(
        sessions: SessionStore,
        *,
        session_id: str,
        subject: str,
        effect_id: str,
        idempotency_key: str,
        run_token: Dict[str, Any],
    ) -> None:
        session = sessions.load(session_id)
        state = session["state"]
        if state in {"RUNNING", "PAUSED"}:
            if (
                session.get("artifacts", {}).get("run_subject_hash") != subject
                or session.get("artifacts", {}).get("run_effect_id") != effect_id
                or session.get("approvals", {}).get("execute") != run_token["token_id"]
            ):
                raise AgentError(
                    "BTAG-RUN-SESSION",
                    "interrupted session belongs to another approved effect",
                )
            if state == "RUNNING":
                return
            action_type = "controlled-run-resume"
        elif state == "RUN_APPROVED":
            action_type = "controlled-run-start"
        else:
            raise AgentError(
                "BTAG-RUN-SESSION",
                "session is not ready to start or resume this approved run",
            )
        sessions.transition(
            session_id,
            "RUNNING",
            action_type,
            {"run_subject": subject},
            idempotency_key=idempotency_key,
            approval_token_id=run_token["token_id"],
            effect_references={
                "run_subject_hash": subject,
                "run_effect_id": effect_id,
            },
        )

    @classmethod
    def _finish_successful_session(
        cls,
        sessions: SessionStore,
        *,
        session_id: str,
        subject: str,
        effect_id: str,
        idempotency_key: str,
        run_token: Dict[str, Any],
        result: Dict[str, Any],
        report_hash: str,
    ) -> None:
        session = sessions.load(session_id)
        if session["state"] in {"RUN_APPROVED", "PAUSED"}:
            cls._begin_or_resume_session(
                sessions,
                session_id=session_id,
                subject=subject,
                effect_id=effect_id,
                idempotency_key=idempotency_key,
                run_token=run_token,
            )
            session = sessions.load(session_id)
        if session["state"] == "RUNNING":
            sessions.transition(
                session_id,
                "PASSED",
                "controlled-run-passed",
                {"run_result": result["result_hash"]},
                idempotency_key=idempotency_key,
                approval_token_id=run_token["token_id"],
                effect_references={"run_result_hash": result["result_hash"]},
            )
            session = sessions.load(session_id)
        if session["state"] == "PASSED":
            sessions.transition(
                session_id,
                "REPORTED",
                "report-render",
                {"report": report_hash},
                idempotency_key=idempotency_key,
                effect_references={"report_hash": report_hash},
            )
            session = sessions.load(session_id)
        if session["state"] == "REPORTED":
            sessions.transition(
                session_id,
                "COMPLETED",
                "session-complete",
                {"run_result": result["result_hash"]},
                idempotency_key=idempotency_key,
            )
            session = sessions.load(session_id)
        if session["state"] != "COMPLETED":
            raise AgentError(
                "BTAG-RUN-SESSION",
                "successful run could not complete its legal session transitions",
            )

    def _dataset_descriptors(self, dataset: Dict[str, Any]) -> List[Dict[str, Any]]:
        descriptors: List[Dict[str, Any]] = []
        transforms = {
            item["parameters"]["feed"]: item
            for item in dataset.get("transforms", [])
            if isinstance(item, dict)
            and isinstance(item.get("parameters"), dict)
            and isinstance(item["parameters"].get("feed"), str)
        }
        for feed in dataset.get("feeds", []):
            relative = (
                feed.get("extensions", {}).get("backtrader_agent", {}).get("cas_relative_path")
            )
            if not isinstance(relative, str):
                raise AgentError("BTAG-RUN-DATASET", "dataset has no registered CAS path")
            path = (self.state_root / relative).resolve(strict=True)
            try:
                path.relative_to(self.state_root.resolve())
            except ValueError as exc:
                raise AgentError("BTAG-RUN-DATASET", "dataset CAS path escapes state root") from exc
            data = path.read_bytes()
            if sha256_bytes(data) != feed.get("normalized_sha256"):
                raise AgentError("BTAG-RUN-DATASET-HASH", "dataset CAS bytes changed")
            descriptors.append(
                {
                    "name": feed["name"],
                    "role": feed["role"],
                    "path": str(path),
                    "adapter": feed["format"],
                    "timeframe": feed.get("timeframe", "Days"),
                    "compression": int(feed.get("compression", 1)),
                    "canonical_columns": list(feed.get("canonical_columns", [])),
                    "transform": transforms.get(feed["name"]),
                }
            )
        return descriptors

    def _verify_files(self, applied: Dict[str, Any]) -> Path:
        entrypoint: Optional[Path] = None
        for item in applied.get("files", []):
            path = self.roots.resolve(
                applied["target_root_id"], item["relative_path"], require_file=True
            )
            if sha256_bytes(path.read_bytes()) != item["sha256"]:
                raise AgentError("BTAG-RUN-SOURCE-HASH", "applied source changed after approval")
            if item["relative_path"] == applied.get("entrypoint"):
                entrypoint = path
        if entrypoint is None:
            raise AgentError("BTAG-RUN-ENTRYPOINT", "controlled entrypoint is absent")
        name = entrypoint.name
        profile = applied.get("profile")
        if profile == "python_bundle" and name != "run.py":
            raise AgentError("BTAG-RUN-PROFILE", "bundle entrypoint must be run.py")
        if profile == "single_test" and not name.startswith("test_"):
            raise AgentError("BTAG-RUN-PROFILE", "test entrypoint must be a generated test")
        return entrypoint

    @staticmethod
    def _child_environment(
        descriptors: List[Dict[str, Any]],
        mode: str,
        engine_root: Optional[Path] = None,
    ) -> Dict[str, str]:
        environment = {
            "PATH": "/usr/bin:/bin",
            "TMPDIR": "/tmp",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "BACKTRADER_AGENT_DATASETS_JSON": json.dumps(
                descriptors, sort_keys=True, separators=(",", ":")
            ),
            "BACKTRADER_AGENT_MODE": mode,
        }
        if engine_root is not None:
            environment["PYTHONPATH"] = str(engine_root)
        return environment

    def _resolve_engine(
        self,
        validation_token: Dict[str, Any],
    ) -> Tuple[Optional[Path], Dict[str, Any]]:
        bindings = validation_token.get("bindings", {})
        root_id = bindings.get("engine_root_id")
        if root_id is None:
            return None, {
                "hash": bindings.get("engine_hash"),
                "kind": "active-python-environment",
            }
        descriptor = inspect_engine(self.roots, str(root_id))
        if descriptor["engine_hash"] != bindings.get("engine_hash"):
            raise AgentError(
                "BTAG-ENGINE-HASH",
                "registered Backtrader engine changed after validation",
            )
        record = self.roots.get_record(str(root_id))
        root = Path(record["path"]).resolve(strict=True)
        probe = subprocess.run(
            [sys.executable, "-c", ENGINE_PROBE],
            cwd=self.state_root,
            env=self._child_environment([], "runonce", root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
            check=False,
            shell=False,
        )
        try:
            attestation = json.loads(probe.stdout.decode("utf-8"))
            imported = Path(attestation["path"]).resolve(strict=True)
            relative_import = imported.relative_to(root).as_posix()
        except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
            raise AgentError(
                "BTAG-ENGINE-IMPORT",
                "registered Backtrader engine could not be imported from its bound root",
            ) from exc
        if (
            probe.returncode != 0
            or not relative_import.startswith("backtrader/")
            or (
                descriptor["version"] != "unknown"
                and attestation.get("version") != descriptor["version"]
            )
        ):
            raise AgentError(
                "BTAG-ENGINE-IMPORT",
                "child-process Backtrader import does not match the registered engine",
            )
        return root, {
            "hash": descriptor["engine_hash"],
            "kind": "registered-local",
            "root_id": descriptor["root_id"],
            "version": descriptor["version"],
            "version_file_sha256": descriptor["version_file_sha256"],
            "import_relative_path": relative_import,
        }

    def run(
        self,
        applied: Dict[str, Any],
        dataset: Dict[str, Any],
        validation_token: Dict[str, Any],
        run_token: Dict[str, Any],
        *,
        mode: str,
        idempotency_key: str,
        timeout_seconds: int = 120,
    ) -> Dict[str, Any]:
        if timeout_seconds < 1 or timeout_seconds > 600:
            raise AgentError("BTAG-RUN-TIMEOUT", "timeout must be between 1 and 600 seconds")
        self._verify_applied(applied)
        dataset = self._verify_registered_dataset(dataset)
        self.authority.verify(
            validation_token,
            kind="validation",
            subject_hash=applied["artifact_hash"],
            required_bindings={
                "artifact_record_hash": applied["artifact_record_hash"],
                "dataset_hash": dataset["manifest_hash"],
                "dataset_id": dataset["dataset_id"],
                "session_id": applied["session_id"],
                "spec_hash": applied["spec_hash"],
            },
        )
        if (
            applied["dataset_id"] != dataset["dataset_id"]
            or applied["dataset_manifest_hash"] != dataset["manifest_hash"]
            or applied["validation_token_hash"] != hash_object(validation_token)
            or applied["validation_token_id"] != validation_token["token_id"]
        ):
            raise AgentError(
                "BTAG-RUN-PROVENANCE",
                "applied artifact, validation, and registered dataset bindings disagree",
            )
        subject = self.compute_run_subject(applied, dataset, validation_token, mode=mode)
        self.authority.verify(
            run_token,
            kind="run",
            subject_hash=subject,
            required_bindings={
                "applied_artifact_hash": applied["applied_artifact_hash"],
                "applied_record_hash": applied["applied_record_hash"],
                "artifact_hash": applied["artifact_hash"],
                "artifact_record_hash": applied["artifact_record_hash"],
                "change_manifest_hash": applied["change_manifest_hash"],
                "validation_token_id": validation_token["token_id"],
                "validation_token_hash": hash_object(validation_token),
                "dataset_hash": dataset["manifest_hash"],
                "dataset_id": dataset["dataset_id"],
                "mode": mode,
                "session_id": applied["session_id"],
                "spec_hash": applied["spec_hash"],
            },
        )
        action_path = self._action_path(idempotency_key)
        request_hash = hash_object(
            {
                "action": "controlled-run",
                "subject_hash": subject,
                "run_token_id": run_token["token_id"],
                "timeout_seconds": timeout_seconds,
            }
        )
        effect_id = hash_object(
            {
                "idempotency_key": idempotency_key,
                "request_hash": request_hash,
            }
        )
        run_id = f"run-{subject[:20]}"
        run_root = self.state_root / "runs" / run_id
        engine_root, engine_descriptor = self._resolve_engine(validation_token)
        run_manifest: Dict[str, Any] = {
            "schema_version": "run-manifest-v1",
            "run_id": run_id,
            "artifact_hash": applied["artifact_hash"],
            "dataset_id": dataset["dataset_id"],
            "engine": engine_descriptor,
            "environment_hash": (
                validation_token["bindings"].get("environment_hash")
                if re.fullmatch(
                    r"[0-9a-f]{64}",
                    str(validation_token["bindings"].get("environment_hash", "")),
                )
                else hash_object(validation_token["bindings"].get("environment_hash"))
            ),
            "run_profile": {
                "name": "controlled-runner-v1",
                "output_profile": applied["profile"],
                "mode": mode,
                "entrypoint": Path(applied["entrypoint"]).name,
                "timeout_seconds": timeout_seconds,
            },
            "approval_id": run_token["approval_id"],
            "extensions": {
                "backtrader_agent": {
                    "applied_artifact_hash": applied["applied_artifact_hash"],
                    "applied_record_hash": applied["applied_record_hash"],
                    "dataset_manifest_hash": dataset["manifest_hash"],
                    "validation_token_id": validation_token["token_id"],
                }
            },
        }
        run_manifest["manifest_hash"] = hash_object(run_manifest)
        sessions = SessionStore(self.state_root)
        if action_path.exists():
            recorded = read_json(action_path)
            if recorded.get("request_hash") != request_hash:
                raise AgentError(
                    "BTAG-IDEMPOTENCY-CONFLICT",
                    "idempotency key was already used for another run",
                )
            result = recorded.get("result")
            if not isinstance(result, dict):
                raise AgentError("BTAG-RUN-CONFLICT", "recorded run result is invalid")
            self._verify_persisted_result(
                result,
                run_id=run_id,
                mode=mode,
                applied=applied,
                dataset=dataset,
                validation_token=validation_token,
                run_token=run_token,
            )
            self._verify_persisted_manifest(run_root, result, run_manifest)
            report_files = self._render_reports_resumable(run_root, result)
            self._finish_successful_session(
                sessions,
                session_id=applied["session_id"],
                subject=subject,
                effect_id=effect_id,
                idempotency_key=idempotency_key,
                run_token=run_token,
                result=result,
                report_hash=report_files["report_hash"],
            )
            return result
        self.authority.consume(run_token, effect_id=effect_id)

        entrypoint = self._verify_files(applied)
        descriptors = self._dataset_descriptors(dataset)
        self._begin_or_resume_session(
            sessions,
            session_id=applied["session_id"],
            subject=subject,
            effect_id=effect_id,
            idempotency_key=idempotency_key,
            run_token=run_token,
        )
        persisted_result_path = run_root / "run-result.json"
        if persisted_result_path.exists():
            result = read_json(persisted_result_path)
            self._verify_persisted_result(
                result,
                run_id=run_id,
                mode=mode,
                applied=applied,
                dataset=dataset,
                validation_token=validation_token,
                run_token=run_token,
            )
            self._verify_persisted_manifest(run_root, result, run_manifest)
            report_files = self._render_reports_resumable(run_root, result)
            self._persist_exact_json(
                action_path,
                {
                    "schema_version": "idempotent-action-v1",
                    "request_hash": request_hash,
                    "result": result,
                },
            )
            self._finish_successful_session(
                sessions,
                session_id=applied["session_id"],
                subject=subject,
                effect_id=effect_id,
                idempotency_key=idempotency_key,
                run_token=run_token,
                result=result,
                report_hash=report_files["report_hash"],
            )
            return result
        if applied["profile"] == "python_bundle":
            argv = [sys.executable, entrypoint.name]
        else:
            argv = [
                sys.executable,
                "-m",
                "pytest",
                entrypoint.name,
                "-q",
                "-s",
                "-p",
                "no:cacheprovider",
            ]
        environment = self._child_environment(descriptors, mode, engine_root)

        def mark_failed(code: str) -> None:
            current = sessions.load(applied["session_id"])
            if current["state"] == "RUNNING":
                sessions.transition(
                    applied["session_id"],
                    "FAILED",
                    "controlled-run-failed",
                    {"diagnostic": hash_object({"code": code, "subject": subject})},
                    idempotency_key=idempotency_key,
                    approval_token_id=run_token["token_id"],
                    effect_references={"run_failure_code": code},
                )

        started = time.monotonic()
        try:
            completed = subprocess.run(
                argv,
                cwd=str(entrypoint.parent),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout_seconds,
                check=False,
                shell=False,
                preexec_fn=_resource_limits(timeout_seconds) if os.name == "posix" else None,
            )
        except subprocess.TimeoutExpired as exc:
            mark_failed("BTAG-RUN-TIMEOUT")
            raise AgentError("BTAG-RUN-TIMEOUT", "controlled child process timed out") from exc
        duration = time.monotonic() - started
        stdout = completed.stdout
        stderr = completed.stderr
        if len(stdout) > self.MAX_OUTPUT_BYTES or len(stderr) > self.MAX_OUTPUT_BYTES:
            mark_failed("BTAG-RUN-OUTPUT")
            raise AgentError("BTAG-RUN-OUTPUT", "child output exceeded the byte quota")
        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")
        if completed.returncode != 0:
            redacted = self._redact_stderr(
                stderr_text,
                state_root=self.state_root,
                entrypoint=entrypoint,
                descriptors=descriptors,
            )
            mark_failed("BTAG-RUN-FAILED")
            raise AgentError(
                "BTAG-RUN-FAILED",
                "controlled child process failed",
                details={"returncode": completed.returncode, "stderr": redacted},
            )
        payload = None
        for line in stdout_text.splitlines():
            if line.startswith(RESULT_PREFIX):
                try:
                    payload = json.loads(line[len(RESULT_PREFIX) :])
                except json.JSONDecodeError as exc:
                    mark_failed("BTAG-RUN-RESULT")
                    raise AgentError(
                        "BTAG-RUN-RESULT", "child emitted malformed structured result"
                    ) from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("metrics"), dict):
            mark_failed("BTAG-RUN-RESULT")
            raise AgentError("BTAG-RUN-RESULT", "child emitted no structured metrics")
        try:
            metrics = normalize_metrics(payload["metrics"])
        except AgentError:
            mark_failed("BTAG-RUN-METRIC")
            raise

        self._persist_exact_json(run_root / "run-manifest.json", run_manifest)
        persisted_manifest = run_root / "run-manifest.json"
        result: Dict[str, Any] = {
            "schema_version": "run-result-v1",
            "run_id": run_id,
            "status": "passed",
            "metrics": metrics,
            "diagnostics": [],
            "artifacts": [
                {
                    "path": "run-manifest.json",
                    "role": "run_manifest",
                    "bytes": persisted_manifest.stat().st_size,
                    "sha256": sha256_bytes(persisted_manifest.read_bytes()),
                }
            ],
            "extensions": {
                "backtrader_agent": {
                    "mode": mode,
                    "duration_seconds": round(duration, 6),
                    "dataset_manifest_hash": dataset["manifest_hash"],
                    "applied_artifact_hash": applied["applied_artifact_hash"],
                    "manifest_hash": run_manifest["manifest_hash"],
                    "validation_token_id": validation_token["token_id"],
                    "run_token_id": run_token["token_id"],
                    "environment_policy": {
                        "home_forwarded": False,
                        "inherited_environment": False,
                    },
                    "limitations": [
                        "P0 uses a timeout- and quota-bound local child process, not an OS sandbox.",
                        "P0 does not claim verified network isolation.",
                        "Only product-generated, hash-approved candidates are executable.",
                    ],
                }
            },
        }
        result["result_hash"] = hash_object(result)
        try:
            report_files = self._render_reports_resumable(run_root, result)
        except (AgentError, OSError) as exc:
            raise AgentError(
                "BTAG-RUN-PERSIST",
                "run output persistence was interrupted; retry the same effect",
            ) from exc
        record = {
            "schema_version": "idempotent-action-v1",
            "request_hash": request_hash,
            "result": result,
        }
        self._persist_exact_json(action_path, record)
        self._finish_successful_session(
            sessions,
            session_id=applied["session_id"],
            subject=subject,
            effect_id=effect_id,
            idempotency_key=idempotency_key,
            run_token=run_token,
            result=result,
            report_hash=report_files["report_hash"],
        )
        return result
