"""Hash-bound prepare/approve/apply workflow with recoverable directory replacement."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .drafts import DraftService
from .errors import Conflict, InvalidRequest, NotFound
from .locks import LockManager
from .security import TokenSigner, confined_path
from .settings import Settings
from .state import StateStore
from .util import atomic_write, file_hash, sha256_json, utc_now


def _tree_manifest(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    if root.is_symlink() or not root.is_dir():
        raise InvalidRequest("target strategy path must be a directory or absent")
    manifest: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise InvalidRequest("target tree cannot contain symlinks")
        if path.is_dir():
            continue
        if not path.is_file():
            raise InvalidRequest("target tree contains a non-regular file")
        manifest[str(path.relative_to(root))] = file_hash(path)
    return manifest


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class ChangeService:
    def __init__(
        self,
        settings: Settings,
        state: StateStore,
        signer: TokenSigner,
        locks: LockManager,
        drafts: DraftService,
    ):
        self.settings = settings
        self.state = state
        self.signer = signer
        self.locks = locks
        self.drafts = drafts

    def _target(self, root_id: str, relative_dir: str) -> Path:
        root = self.settings.target_roots.get(root_id)
        if root is None:
            raise NotFound(f"target root not registered: {root_id}")
        root.mkdir(parents=True, exist_ok=True)
        return confined_path(root, relative_dir, must_exist=False)

    def prepare_strategy_changes(
        self,
        draft_id: str,
        validation_token: str,
        target_root_id: str,
        target_relative_dir: str,
        expected_target_hashes: dict[str, str],
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not isinstance(expected_target_hashes, dict) or any(
            not isinstance(path, str) or not isinstance(digest, str)
            for path, digest in expected_target_hashes.items()
        ):
            raise InvalidRequest("expected_target_hashes must be a path-to-sha256 object")
        request = {
            "draft_id": draft_id,
            "validation_token_hash": sha256_json(validation_token),
            "target_root_id": target_root_id,
            "target_relative_dir": target_relative_dir,
            "expected_target_hashes": expected_target_hashes,
        }
        prior = self.state.idempotent_get("prepare_strategy_changes", idempotency_key, request)
        if prior is not None:
            return prior
        verified = self.drafts.verify_validation(draft_id, validation_token)
        draft = verified["draft"]
        target = self._target(target_root_id, target_relative_dir)
        actual = _tree_manifest(target)
        if actual != expected_target_hashes:
            raise Conflict("target tree does not match the exact expected preimage hashes")
        actions = []
        for relative, digest in draft["manifest"].items():
            actions.append(
                {
                    "path": relative,
                    "action": "create" if relative not in actual else "replace",
                    "before_sha256": actual.get(relative),
                    "after_sha256": digest,
                }
            )
        for relative, digest in actual.items():
            if relative not in draft["manifest"]:
                actions.append(
                    {
                        "path": relative,
                        "action": "delete",
                        "before_sha256": digest,
                        "after_sha256": None,
                    }
                )
        actions.sort(key=lambda item: item["path"])
        change_id = f"change_{uuid.uuid4().hex}"
        binding = {
            "change_id": change_id,
            "draft_id": draft_id,
            "draft_revision": draft["revision"],
            "draft_manifest_hash": draft["manifest_hash"],
            "validation_id": verified["validation"]["validation_id"],
            "validation_report_hash": verified["validation"]["validation_hash"],
            "target_root_id": target_root_id,
            "target_relative_dir": target_relative_dir,
            "target_preimage_hashes": actual,
            "actions": actions,
        }
        change_hash = sha256_json(binding)
        token = self.signer.issue(
            "change",
            {"change_id": change_id, "change_hash": change_hash},
            ttl_seconds=1800,
        )
        record = {
            **binding,
            "change_hash": change_hash,
            "status": "prepared",
            "created_at": utc_now(),
        }
        self.state.put("change", change_id, record)
        response = {
            "change_set_id": change_id,
            "change_token": token,
            "change_hash": change_hash,
            "actions": actions,
            "approval_command": f"backtrader-mcp approve --change-set {change_id} "
            f"--change-token '{token}'",
        }
        self.state.idempotent_put("prepare_strategy_changes", idempotency_key, request, response)
        self.state.audit("change.prepared", change_id, {"change_hash": change_hash})
        return response

    def approve_change(self, change_id: str, change_token: str) -> dict[str, Any]:
        claims = self.signer.verify(change_token, "change")
        change = self.state.get("change", change_id)
        if (
            claims.get("change_id") != change_id
            or claims.get("change_hash") != change["change_hash"]
            or change["status"] != "prepared"
        ):
            raise Conflict("change token does not bind the prepared change")
        expires = datetime.now(timezone.utc) + timedelta(minutes=15)
        return self.state.create_approval(
            "change",
            change_id,
            change["change_hash"],
            expires.isoformat(),
        )

    def apply_strategy_changes(
        self,
        change_set_id: str,
        change_token: str,
        approval_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        request = {
            "change_set_id": change_set_id,
            "change_token_hash": sha256_json(change_token),
            "approval_id": approval_id,
        }
        prior = self.state.idempotent_get("apply_strategy_changes", idempotency_key, request)
        if prior is not None:
            return prior
        claims = self.signer.verify(change_token, "change")
        with self.locks.acquire(f"change:{change_set_id}"):
            change = self.state.get("change", change_set_id)
            if (
                claims.get("change_id") != change_set_id
                or claims.get("change_hash") != change["change_hash"]
            ):
                raise Conflict("change token does not bind this change set")
            if change["status"] == "applied":
                raise Conflict("change set was already applied with another idempotency key")
            verified = self.drafts.get_draft(change["draft_id"])
            if (
                verified["revision"] != change["draft_revision"]
                or verified["manifest_hash"] != change["draft_manifest_hash"]
            ):
                raise Conflict("draft changed after prepare")
            target = self._target(change["target_root_id"], change["target_relative_dir"])
            if _tree_manifest(target) != change["target_preimage_hashes"]:
                raise Conflict("target changed after prepare")
            self.state.consume_approval(approval_id, "change", change_set_id, change["change_hash"])
            self._replace_tree(change, verified, target)

            def mark_applied(current: dict[str, Any]) -> dict[str, Any]:
                current["status"] = "applied"
                current["applied_at"] = utc_now()
                current["target_postimage_hashes"] = _tree_manifest(target)
                return current

            applied = self.state.update("change", change_set_id, mark_applied)
            response = {
                "change_set_id": change_set_id,
                "status": "applied",
                "target_root_id": change["target_root_id"],
                "target_relative_dir": change["target_relative_dir"],
                "target_manifest_hash": sha256_json(applied["target_postimage_hashes"]),
            }
            self.state.idempotent_put("apply_strategy_changes", idempotency_key, request, response)
            self.state.audit("change.applied", change_set_id, response)
            return response

    def _replace_tree(self, change: dict[str, Any], draft: dict[str, Any], target: Path) -> None:
        parent = target.parent
        parent.mkdir(parents=True, exist_ok=True)
        change_id = change["change_id"]
        stage = parent / f".backtrader-mcp-{change_id}.stage"
        backup = parent / f".backtrader-mcp-{change_id}.backup"
        journal = self.settings.state_root / "transactions" / f"{change_id}.json"
        if stage.exists() or backup.exists() or journal.exists():
            raise Conflict("an unfinished target transaction already exists")
        stage.mkdir(mode=0o700)
        try:
            source_root = self.drafts._path(draft["draft_id"])
            for relative, expected_hash in draft["manifest"].items():
                source = confined_path(source_root, relative, must_exist=True)
                if file_hash(source) != expected_hash:
                    raise Conflict("draft file changed during apply")
                destination = stage / relative
                atomic_write(destination, source.read_bytes(), mode=0o600)
            _fsync_directory(stage)
            transaction = {
                "change_id": change_id,
                "target": str(target),
                "stage": str(stage),
                "backup": str(backup),
                "phase": "staged",
            }
            atomic_write(journal, json.dumps(transaction, sort_keys=True).encode(), mode=0o600)
            if target.exists():
                os.replace(target, backup)
                _fsync_directory(parent)
                transaction["phase"] = "backup_moved"
                atomic_write(journal, json.dumps(transaction, sort_keys=True).encode(), mode=0o600)
            os.replace(stage, target)
            _fsync_directory(parent)
            transaction["phase"] = "applied"
            atomic_write(journal, json.dumps(transaction, sort_keys=True).encode(), mode=0o600)
            if backup.exists():
                shutil.rmtree(backup)
            journal.unlink()
        except BaseException:
            if not target.exists() and backup.exists():
                os.replace(backup, target)
            if stage.exists():
                shutil.rmtree(stage)
            raise

    def recover_transactions(self) -> list[str]:
        recovered: list[str] = []
        root = self.settings.state_root / "transactions"
        for journal in root.glob("change_*.json"):
            transaction = json.loads(journal.read_text(encoding="utf-8"))
            target = Path(transaction["target"])
            stage = Path(transaction["stage"])
            backup = Path(transaction["backup"])
            phase = transaction["phase"]
            if phase == "staged":
                if not target.exists() and backup.exists():
                    os.replace(backup, target)
                if stage.exists():
                    shutil.rmtree(stage)
            elif phase == "backup_moved":
                if target.exists():
                    if backup.exists():
                        shutil.rmtree(backup)
                elif stage.exists():
                    os.replace(stage, target)
                    if backup.exists():
                        shutil.rmtree(backup)
                elif backup.exists():
                    os.replace(backup, target)
            elif phase == "applied" and backup.exists():
                shutil.rmtree(backup)
            journal.unlink(missing_ok=True)
            recovered.append(transaction["change_id"])
        return recovered
