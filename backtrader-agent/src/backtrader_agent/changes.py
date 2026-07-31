"""Two-phase, hash-bound, confined change preparation and application."""

import difflib
import re
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List

from .canonical import (
    atomic_write_bytes,
    atomic_write_json,
    hash_object,
    read_json,
    sha256_bytes,
)
from .errors import AgentError
from .roots import RootRegistry
from .scaffold import load_product_artifact_record
from .sessions import SessionStore
from .tokens import TokenAuthority

IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,127}$")


def _safe_relative(value: str) -> PurePosixPath:
    candidate = PurePosixPath(value.replace("\\", "/"))
    if not value or candidate.is_absolute() or ".." in candidate.parts:
        raise AgentError("BTAG-CHANGE-PATH", "change paths must be confined relative paths")
    return candidate


def _role(source: str) -> str:
    name = PurePosixPath(source).name
    if name == "run.py":
        return "runner"
    if name == "config.yaml":
        return "config"
    if name.startswith("test_"):
        return "strategy"
    if name.startswith("strategy_"):
        return "strategy"
    return "support"


class ChangeManager:
    def __init__(self, roots: RootRegistry, state_root: Path, authority: TokenAuthority) -> None:
        self.roots = roots
        self.state_root = Path(state_root)
        self.authority = authority
        self.action_root = self.state_root / "actions"
        self.transaction_root = self.state_root / "transactions"

    def prepare(
        self,
        *,
        session_id: str,
        draft_root: Path,
        files: List[Dict[str, str]],
        target_root_id: str,
        validation_token: Dict[str, Any],
    ) -> Dict[str, Any]:
        self.authority.verify(
            validation_token,
            kind="validation",
            subject_hash=validation_token.get("subject_hash", ""),
            required_bindings={"session_id": session_id},
        )
        draft = Path(draft_root).resolve(strict=True)
        artifact_path = draft / "artifact-manifest.json"
        if not artifact_path.is_file():
            raise AgentError(
                "BTAG-CHANGE-ARTIFACT",
                "draft is missing its validated artifact manifest",
            )
        artifact = read_json(artifact_path)
        artifact_payload = {key: value for key, value in artifact.items() if key != "artifact_hash"}
        product_record = load_product_artifact_record(
            self.state_root,
            session_id,
            str(artifact.get("artifact_hash", "")),
            self.authority,
        )
        expected_draft = (self.state_root / product_record["draft_relative_path"]).resolve(
            strict=True
        )
        extension = artifact.get("extensions", {}).get("backtrader_agent", {})
        if (
            hash_object(artifact_payload) != artifact.get("artifact_hash")
            or artifact.get("artifact_hash") != validation_token["subject_hash"]
            or draft != expected_draft
            or sha256_bytes(artifact_path.read_bytes()) != product_record["manifest_sha256"]
            or extension.get("generated_by") != "backtrader-agent"
            or extension.get("session_id") != session_id
            or extension.get("dataset_manifest_hash") != product_record["dataset_manifest_hash"]
            or validation_token.get("bindings", {}).get("artifact_record_hash")
            != product_record["record_hash"]
            or validation_token.get("bindings", {}).get("spec_hash") != product_record["spec_hash"]
            or validation_token.get("bindings", {}).get("dataset_id")
            != product_record["dataset_id"]
            or validation_token.get("bindings", {}).get("dataset_hash")
            != product_record["dataset_manifest_hash"]
        ):
            raise AgentError(
                "BTAG-CHANGE-ARTIFACT",
                "draft artifact is not bound to the validation token",
            )
        artifact_files = {item["path"]: item for item in artifact.get("files", [])}
        if not files or len(files) > 8:
            raise AgentError("BTAG-CHANGE-COUNT", "change set must contain 1 to 8 files")
        changes: List[Dict[str, Any]] = []
        targets = set()
        for item in files:
            source_relative = _safe_relative(item["source"])
            target_relative = _safe_relative(item["target"])
            target_text = target_relative.as_posix()
            if target_text in targets:
                raise AgentError("BTAG-CHANGE-DUPLICATE", "target path is duplicated")
            targets.add(target_text)
            source = draft.joinpath(*source_relative.parts).resolve(strict=True)
            try:
                source.relative_to(draft)
            except ValueError as exc:
                raise AgentError("BTAG-CHANGE-SOURCE", "draft source escapes draft root") from exc
            if not source.is_file() or source.is_symlink():
                raise AgentError("BTAG-CHANGE-SOURCE", "draft source must be a regular file")
            content = source.read_bytes()
            artifact_file = artifact_files.get(source_relative.as_posix())
            if artifact_file is None or artifact_file.get("sha256") != sha256_bytes(content):
                raise AgentError(
                    "BTAG-CHANGE-ARTIFACT",
                    "change source is not in the validated artifact",
                )
            if len(content) > 256 * 1024:
                raise AgentError("BTAG-CHANGE-SIZE", "change file exceeds byte quota")
            target = self.roots.resolve(
                target_root_id, target_text, for_write=True, require_file=False
            )
            if target.exists() and not target.is_file():
                raise AgentError("BTAG-CHANGE-TARGET", "target exists but is not a file")
            old_bytes = target.read_bytes() if target.exists() else b""
            old_hash = sha256_bytes(old_bytes) if target.exists() else None
            try:
                old_text = old_bytes.decode("utf-8").splitlines(keepends=True)
                new_text = content.decode("utf-8").splitlines(keepends=True)
                diff = "".join(
                    difflib.unified_diff(
                        old_text,
                        new_text,
                        fromfile=f"a/{target_text}",
                        tofile=f"b/{target_text}",
                    )
                )
            except UnicodeDecodeError:
                diff = f"binary {len(old_bytes)} -> {len(content)} bytes"
            changes.append(
                {
                    "source_relative_path": source_relative.as_posix(),
                    "target_relative_path": target_text,
                    "role": _role(source_relative.as_posix()),
                    "source_hash": sha256_bytes(content),
                    "expected_target_hash": old_hash,
                    "size_bytes": len(content),
                    "diff": diff[:128_000],
                }
            )
        profile = (
            "python_bundle"
            if any(change["source_relative_path"] == "run.py" for change in changes)
            else "single_test"
        )
        entrypoint = next(
            (
                change["target_relative_path"]
                for change in changes
                if (
                    change["source_relative_path"] == "run.py"
                    if profile == "python_bundle"
                    else change["source_relative_path"].startswith("test_")
                )
            ),
            None,
        )
        portable: Dict[str, Any] = {
            "schema_version": "change-manifest-v1",
            "change_id": "",
            "session_id": session_id,
            "target_root_id": target_root_id,
            "profile": profile,
            "entrypoint": entrypoint,
            "artifact_hash": validation_token["subject_hash"],
            "artifact_record_hash": product_record["record_hash"],
            "spec_hash": product_record["spec_hash"],
            "dataset_id": artifact["dataset_id"],
            "dataset_manifest_hash": product_record["dataset_manifest_hash"],
            "validation_token_id": validation_token["token_id"],
            "validation_token_hash": hash_object(validation_token),
            "policy": "create-or-expected-hash",
            "changes": changes,
        }
        identity = hash_object(
            {key: value for key, value in portable.items() if key != "change_id"}
        )
        portable["change_id"] = f"change-{identity[:20]}"
        portable["manifest_hash"] = hash_object(portable)
        result = {**portable, "_draft_path": str(draft)}
        sessions = SessionStore(self.state_root)
        session = sessions.load(session_id)
        if (
            session.get("artifacts", {}).get("artifact_hash") != portable["artifact_hash"]
            or session.get("artifacts", {}).get("approved_spec_hash") != portable["spec_hash"]
            or session.get("artifacts", {}).get("dataset_id") != portable["dataset_id"]
            or session.get("artifacts", {}).get("dataset_manifest_hash")
            != portable["dataset_manifest_hash"]
            or session.get("artifacts", {}).get("validation_hash")
            != validation_token.get("bindings", {}).get("validation_hash")
            or session.get("artifacts", {}).get("validation_token_id")
            != validation_token.get("token_id")
            or session.get("artifacts", {}).get("validation_token_hash")
            != portable["validation_token_hash"]
            or session.get("artifacts", {}).get("artifact_record_hash")
            != product_record["record_hash"]
        ):
            raise AgentError(
                "BTAG-CHANGE-SESSION",
                "session evidence does not match the validated product artifact",
            )
        self.authority.store_bound_record(
            "prepared-change",
            session_id,
            portable["manifest_hash"],
            {
                "change_manifest": portable,
                "draft_relative_path": product_record["draft_relative_path"],
                "validation_token_hash": portable["validation_token_hash"],
            },
        )
        if session["state"] == "VALIDATED":
            sessions.transition(
                session_id,
                "APPLY_PREPARED",
                "changes-prepare",
                {
                    "artifact": portable["artifact_hash"],
                    "change_manifest": portable["manifest_hash"],
                },
                effect_references={"change_manifest_hash": portable["manifest_hash"]},
            )
        elif (
            session["state"] != "APPLY_PREPARED"
            or session.get("artifacts", {}).get("change_manifest_hash") != portable["manifest_hash"]
        ):
            raise AgentError(
                "BTAG-CHANGE-SESSION",
                "session is not ready for this prepared change",
            )
        return result

    def _action_path(self, key: str) -> Path:
        if not IDEMPOTENCY_RE.fullmatch(key):
            raise AgentError("BTAG-IDEMPOTENCY-KEY", "idempotency key is malformed")
        return self.action_root / f"{sha256_bytes(key.encode('utf-8'))}.json"

    def _transaction_directory(self, change_id: str) -> Path:
        if not re.fullmatch(r"change-[0-9a-f]{20}", change_id):
            raise AgentError("BTAG-CHANGE-ID", "change ID is malformed")
        return self.transaction_root / change_id

    @staticmethod
    def _replace_target(
        index: int,
        target: Path,
        staged: Path,
        create_only: bool,
    ) -> None:
        del index
        atomic_write_bytes(target, staged.read_bytes(), create_only=create_only)

    @staticmethod
    def _write_transaction(path: Path, transaction: Dict[str, Any]) -> None:
        atomic_write_json(path, transaction)

    def _rollback_transaction(
        self,
        transaction_path: Path,
        transaction: Dict[str, Any],
        resolved_by_path: Dict[str, Path],
    ) -> None:
        transaction_directory = transaction_path.parent
        for entry in reversed(transaction["entries"]):
            target = resolved_by_path[entry["target_relative_path"]]
            actual_hash = sha256_bytes(target.read_bytes()) if target.exists() else None
            if actual_hash == entry["expected_target_hash"]:
                entry["applied"] = False
                continue
            if actual_hash != entry["source_hash"]:
                raise AgentError(
                    "BTAG-CHANGE-ROLLBACK",
                    "transaction target has an unexpected recovery image",
                )
            backup_relative = entry.get("backup_relative_path")
            if backup_relative is None:
                if target.exists():
                    target.unlink()
            else:
                backup = transaction_directory / backup_relative
                backup_bytes = backup.read_bytes()
                if sha256_bytes(backup_bytes) != entry["expected_target_hash"]:
                    raise AgentError(
                        "BTAG-CHANGE-ROLLBACK",
                        "transaction backup hash is invalid",
                    )
                atomic_write_bytes(target, backup_bytes)
            restored_hash = sha256_bytes(target.read_bytes()) if target.exists() else None
            if restored_hash != entry["expected_target_hash"]:
                raise AgentError(
                    "BTAG-CHANGE-ROLLBACK",
                    "transaction rollback did not restore the preimage",
                )
            entry["applied"] = False
        transaction["state"] = "ROLLED_BACK"
        self._write_transaction(transaction_path, transaction)

    def _prepare_transaction(
        self,
        change_manifest: Dict[str, Any],
        effect_id: str,
        resolved: List[tuple],
    ) -> tuple:
        directory = self._transaction_directory(change_manifest["change_id"])
        directory.mkdir(parents=True, exist_ok=True)
        transaction_path = directory / "transaction.json"
        resolved_by_path = {
            change["target_relative_path"]: target for change, target, _ in resolved
        }
        if transaction_path.exists():
            existing = read_json(transaction_path)
            if (
                existing.get("change_manifest_hash") != change_manifest["manifest_hash"]
                or existing.get("effect_id") != effect_id
            ):
                raise AgentError(
                    "BTAG-CHANGE-TRANSACTION",
                    "change transaction identity conflicts with an existing journal",
                )
            if existing.get("state") == "APPLYING":
                self._rollback_transaction(transaction_path, existing, resolved_by_path)
            elif existing.get("state") == "COMMITTED":
                for entry in existing["entries"]:
                    target = resolved_by_path[entry["target_relative_path"]]
                    if (
                        not target.exists()
                        or sha256_bytes(target.read_bytes()) != entry["source_hash"]
                    ):
                        raise AgentError(
                            "BTAG-CHANGE-TRANSACTION",
                            "committed transaction target no longer matches",
                        )
                return transaction_path, existing

        stage_directory = directory / "stage"
        backup_directory = directory / "backup"
        stage_directory.mkdir(parents=True, exist_ok=True)
        backup_directory.mkdir(parents=True, exist_ok=True)
        entries = []
        for index, (change, target, content) in enumerate(resolved):
            staged = stage_directory / f"{index}.bin"
            atomic_write_bytes(staged, content)
            backup_relative = None
            if target.exists():
                backup = backup_directory / f"{index}.bin"
                atomic_write_bytes(backup, target.read_bytes())
                backup_relative = backup.relative_to(directory).as_posix()
            entries.append(
                {
                    "index": index,
                    "target_relative_path": change["target_relative_path"],
                    "expected_target_hash": change["expected_target_hash"],
                    "source_hash": change["source_hash"],
                    "staged_relative_path": staged.relative_to(directory).as_posix(),
                    "backup_relative_path": backup_relative,
                    "applied": False,
                }
            )
        transaction = {
            "schema_version": "change-transaction-v1",
            "change_id": change_manifest["change_id"],
            "change_manifest_hash": change_manifest["manifest_hash"],
            "effect_id": effect_id,
            "state": "PREPARED",
            "entries": entries,
        }
        self._write_transaction(transaction_path, transaction)
        return transaction_path, transaction

    def _apply_transaction(
        self,
        transaction_path: Path,
        transaction: Dict[str, Any],
        resolved: List[tuple],
    ) -> None:
        if transaction["state"] == "COMMITTED":
            return
        directory = transaction_path.parent
        resolved_by_path = {
            change["target_relative_path"]: target for change, target, _ in resolved
        }
        transaction["state"] = "APPLYING"
        self._write_transaction(transaction_path, transaction)
        try:
            for entry in transaction["entries"]:
                target = resolved_by_path[entry["target_relative_path"]]
                staged = directory / entry["staged_relative_path"]
                self._replace_target(
                    int(entry["index"]),
                    target,
                    staged,
                    entry["expected_target_hash"] is None,
                )
                if sha256_bytes(target.read_bytes()) != entry["source_hash"]:
                    raise AgentError(
                        "BTAG-CHANGE-POSTIMAGE",
                        "target hash verification failed",
                    )
                entry["applied"] = True
                self._write_transaction(transaction_path, transaction)
        except (AgentError, OSError) as exc:
            try:
                self._rollback_transaction(transaction_path, transaction, resolved_by_path)
            except AgentError as rollback_error:
                raise AgentError(
                    "BTAG-CHANGE-ROLLBACK",
                    "multi-file change failed and rollback could not be verified",
                ) from rollback_error
            raise AgentError(
                "BTAG-CHANGE-TRANSACTION",
                "multi-file change failed and was rolled back",
            ) from exc
        transaction["state"] = "COMMITTED"
        self._write_transaction(transaction_path, transaction)

    @staticmethod
    def _expected_applied_artifact(
        change_manifest: Dict[str, Any],
        change_token: Dict[str, Any],
    ) -> Dict[str, Any]:
        applied_files = [
            {
                "relative_path": change["target_relative_path"],
                "role": change["role"],
                "sha256": change["source_hash"],
                "size_bytes": change["size_bytes"],
            }
            for change in change_manifest["changes"]
        ]
        portable: Dict[str, Any] = {
            "schema_version": "applied-artifact-v1",
            "applied_artifact_id": f"applied-{change_manifest['manifest_hash'][:20]}",
            "generated_by": "backtrader-agent",
            "session_id": change_manifest["session_id"],
            "target_root_id": change_manifest["target_root_id"],
            "profile": change_manifest["profile"],
            "entrypoint": change_manifest["entrypoint"],
            "artifact_hash": change_manifest["artifact_hash"],
            "artifact_record_hash": change_manifest["artifact_record_hash"],
            "spec_hash": change_manifest["spec_hash"],
            "dataset_id": change_manifest["dataset_id"],
            "dataset_manifest_hash": change_manifest["dataset_manifest_hash"],
            "change_manifest_hash": change_manifest["manifest_hash"],
            "validation_token_id": change_manifest["validation_token_id"],
            "validation_token_hash": change_manifest["validation_token_hash"],
            "approval_id": change_token["approval_id"],
            "files": applied_files,
        }
        portable["applied_artifact_hash"] = hash_object(portable)
        return {
            **portable,
            "status": "applied",
        }

    def _signed_action_record(
        self,
        request_hash: str,
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        portable: Dict[str, Any] = {
            "schema_version": "idempotent-action-v1",
            "request_hash": request_hash,
            "result": result,
        }
        portable["record_hash"] = hash_object(portable)
        return {
            **portable,
            "signature": self.authority.sign_product_record(portable),
        }

    def _load_action_record(self, path: Path) -> Dict[str, Any]:
        if not path.is_file() or path.is_symlink():
            raise AgentError(
                "BTAG-IDEMPOTENCY-RECORD",
                "idempotent action record is not a regular product-owned file",
            )
        payload = self.authority.verify_product_record(read_json(path))
        expected_hash = payload.get("record_hash")
        actual_hash = hash_object(
            {key: value for key, value in payload.items() if key != "record_hash"}
        )
        if (
            payload.get("schema_version") != "idempotent-action-v1"
            or expected_hash != actual_hash
            or not isinstance(payload.get("request_hash"), str)
            or not isinstance(payload.get("result"), dict)
        ):
            raise AgentError(
                "BTAG-IDEMPOTENCY-RECORD",
                "idempotent action record is malformed or has an invalid hash",
            )
        return payload

    def _validate_cached_result(
        self,
        recorded: Dict[str, Any],
        change_manifest: Dict[str, Any],
        change_token: Dict[str, Any],
    ) -> Dict[str, Any]:
        expected_artifact = self._expected_applied_artifact(change_manifest, change_token)
        applied_record = self.authority.load_bound_record(
            "applied-artifact",
            change_manifest["session_id"],
            expected_artifact["applied_artifact_hash"],
        )
        expected_result = {
            **expected_artifact,
            "applied_record_hash": applied_record["record_hash"],
        }
        if (
            applied_record.get("applied_artifact") != expected_artifact
            or recorded.get("result") != expected_result
        ):
            raise AgentError(
                "BTAG-IDEMPOTENCY-RESULT",
                "cached apply result does not match the signed artifact and original bindings",
            )
        return expected_result

    def _ensure_applied_session(
        self,
        result: Dict[str, Any],
        change_token: Dict[str, Any],
        *,
        idempotency_key: str,
    ) -> None:
        sessions = SessionStore(self.state_root)
        session_id = result["session_id"]
        session = sessions.load(session_id)
        if session["state"] == "APPLY_PREPARED":
            sessions.transition(
                session_id,
                "APPLIED",
                "changes-apply",
                {"applied_artifact": result["applied_artifact_hash"]},
                idempotency_key=idempotency_key,
                approval_token_id=change_token["token_id"],
                effect_references={
                    "applied_artifact_hash": result["applied_artifact_hash"],
                    "applied_record_hash": result["applied_record_hash"],
                },
            )
        elif session["state"] == "APPLIED":
            if (
                session.get("artifacts", {}).get("applied_artifact_hash")
                != result["applied_artifact_hash"]
                or session.get("artifacts", {}).get("applied_record_hash")
                != result["applied_record_hash"]
            ):
                raise AgentError(
                    "BTAG-CHANGE-SESSION",
                    "session is bound to another applied artifact",
                )
        else:
            raise AgentError(
                "BTAG-CHANGE-SESSION",
                "session is no longer ready to commit this applied artifact",
            )

    def apply(
        self,
        change_manifest: Dict[str, Any],
        change_token: Dict[str, Any],
        *,
        idempotency_key: str,
    ) -> Dict[str, Any]:
        portable = {
            key: value
            for key, value in change_manifest.items()
            if not key.startswith("_") and key != "manifest_hash"
        }
        if hash_object(portable) != change_manifest.get("manifest_hash"):
            raise AgentError("BTAG-CHANGE-HASH", "change manifest hash is invalid")
        canonical_manifest = {
            **portable,
            "manifest_hash": change_manifest["manifest_hash"],
        }
        prepared_record = self.authority.load_bound_record(
            "prepared-change",
            str(change_manifest.get("session_id", "")),
            str(change_manifest.get("manifest_hash", "")),
        )
        if prepared_record.get("change_manifest") != canonical_manifest:
            raise AgentError(
                "BTAG-CHANGE-RECORD",
                "change manifest does not match the signed prepared change",
            )
        session = SessionStore(self.state_root).load(change_manifest["session_id"])
        expected_session = {
            "artifact_hash": change_manifest["artifact_hash"],
            "artifact_record_hash": change_manifest["artifact_record_hash"],
            "approved_spec_hash": change_manifest["spec_hash"],
            "change_manifest_hash": change_manifest["manifest_hash"],
            "dataset_id": change_manifest["dataset_id"],
            "dataset_manifest_hash": change_manifest["dataset_manifest_hash"],
            "validation_token_hash": change_manifest["validation_token_hash"],
            "validation_token_id": change_manifest["validation_token_id"],
        }
        if session.get("state") not in {"APPLY_PREPARED", "APPLIED"} or any(
            session.get("artifacts", {}).get(key) != value
            for key, value in expected_session.items()
        ):
            raise AgentError(
                "BTAG-CHANGE-SESSION",
                "change manifest no longer matches its prepared session",
            )
        change_bindings = {
            "artifact_hash": change_manifest["artifact_hash"],
            "artifact_record_hash": change_manifest["artifact_record_hash"],
            "change_manifest_hash": change_manifest["manifest_hash"],
            "dataset_hash": change_manifest["dataset_manifest_hash"],
            "dataset_id": change_manifest["dataset_id"],
            "session_id": change_manifest["session_id"],
            "spec_hash": change_manifest["spec_hash"],
            "validation_token_hash": change_manifest["validation_token_hash"],
            "validation_token_id": change_manifest["validation_token_id"],
        }
        self.authority.verify(
            change_token,
            kind="change",
            subject_hash=change_manifest["manifest_hash"],
            required_bindings=change_bindings,
        )
        action_path = self._action_path(idempotency_key)
        request_hash = hash_object(
            {
                "action": "changes-apply",
                "manifest_hash": change_manifest["manifest_hash"],
                "token_id": change_token["token_id"],
            }
        )
        if action_path.exists():
            recorded = self._load_action_record(action_path)
            if recorded.get("request_hash") != request_hash:
                raise AgentError(
                    "BTAG-IDEMPOTENCY-CONFLICT",
                    "idempotency key was already used for another request",
                )
            cached_result = self._validate_cached_result(
                recorded,
                canonical_manifest,
                change_token,
            )
            self._ensure_applied_session(
                cached_result,
                change_token,
                idempotency_key=idempotency_key,
            )
            return cached_result

        effect_id = hash_object(
            {
                "idempotency_key": idempotency_key,
                "request_hash": request_hash,
            }
        )
        self.authority.consume(change_token, effect_id=effect_id)

        draft = (self.state_root / prepared_record["draft_relative_path"]).resolve(strict=True)
        try:
            draft.relative_to(self.state_root.resolve())
        except ValueError as exc:
            raise AgentError(
                "BTAG-CHANGE-SOURCE",
                "signed prepared draft escapes the private state root",
            ) from exc
        resolved: List[tuple] = []
        for change in change_manifest["changes"]:
            source_rel = _safe_relative(change["source_relative_path"])
            source = draft.joinpath(*source_rel.parts).resolve(strict=True)
            try:
                source.relative_to(draft)
            except ValueError as exc:
                raise AgentError("BTAG-CHANGE-SOURCE", "source escapes draft root") from exc
            content = source.read_bytes()
            if sha256_bytes(content) != change["source_hash"]:
                raise AgentError("BTAG-CHANGE-SOURCE-HASH", "draft bytes changed after prepare")
            target = self.roots.resolve(
                change_manifest["target_root_id"],
                change["target_relative_path"],
                for_write=True,
            )
            resolved.append((change, target, content))

        transaction_path = (
            self._transaction_directory(change_manifest["change_id"]) / "transaction.json"
        )
        if transaction_path.exists():
            transaction_path, transaction = self._prepare_transaction(
                change_manifest,
                effect_id,
                resolved,
            )
        else:
            for change, target, _ in resolved:
                actual_preimage = sha256_bytes(target.read_bytes()) if target.exists() else None
                if actual_preimage != change["expected_target_hash"]:
                    raise AgentError(
                        "BTAG-CHANGE-PREIMAGE",
                        "target changed after preview; prepare a new change manifest",
                    )
            transaction_path, transaction = self._prepare_transaction(
                change_manifest,
                effect_id,
                resolved,
            )
        if transaction["state"] != "COMMITTED":
            for change, target, _ in resolved:
                actual_preimage = sha256_bytes(target.read_bytes()) if target.exists() else None
                if actual_preimage != change["expected_target_hash"]:
                    raise AgentError(
                        "BTAG-CHANGE-PREIMAGE",
                        "target changed after preview; prepare a new change manifest",
                    )
        self._apply_transaction(transaction_path, transaction, resolved)

        applied_artifact = self._expected_applied_artifact(
            canonical_manifest,
            change_token,
        )
        applied_record = self.authority.store_bound_record(
            "applied-artifact",
            change_manifest["session_id"],
            applied_artifact["applied_artifact_hash"],
            {"applied_artifact": applied_artifact},
        )
        result = {
            **applied_artifact,
            "applied_record_hash": applied_record["record_hash"],
        }
        atomic_write_json(
            action_path,
            self._signed_action_record(request_hash, result),
            create_only=True,
        )
        self._ensure_applied_session(
            result,
            change_token,
            idempotency_key=idempotency_key,
        )
        return result
