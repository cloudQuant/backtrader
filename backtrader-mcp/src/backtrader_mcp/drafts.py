"""Private draft lifecycle and hash-bound validation capabilities."""

from __future__ import annotations

import json
import os
import uuid
import hashlib
from pathlib import Path
from typing import Any

from .contracts import SCAFFOLD_PROFILES, StrategySpec
from .errors import Conflict, InvalidRequest
from .locks import LockManager
from .scaffold import scaffold_files
from .security import TokenSigner, confined_path
from .settings import Settings
from .state import StateStore
from .util import atomic_write, file_hash, sha256_json, utc_now
from .validation import validate_sources


class DraftService:
    def __init__(
        self,
        settings: Settings,
        state: StateStore,
        signer: TokenSigner,
        locks: LockManager,
    ):
        self.settings = settings
        self.state = state
        self.signer = signer
        self.locks = locks

    def _path(self, draft_id: str) -> Path:
        return confined_path(
            self.settings.state_root / "drafts",
            draft_id,
            must_exist=True,
        )

    def _files(self, draft: dict[str, Any]) -> dict[str, str]:
        root = self._path(draft["draft_id"])
        result: dict[str, str] = {}
        for relative in draft["allowed_files"]:
            path = confined_path(root, relative, must_exist=True)
            result[relative] = path.read_text(encoding="utf-8")
        return result

    def _manifest(self, files: dict[str, str]) -> dict[str, str]:
        return {
            relative: hashlib.sha256(content.encode("utf-8")).hexdigest()
            for relative, content in sorted(files.items())
        }

    @staticmethod
    def _artifact_manifest(
        draft_id: str,
        revision: int,
        strategy_spec: dict[str, Any],
        output_profile: str,
        manifest: dict[str, str],
        files: dict[str, str],
    ) -> dict[str, Any]:
        core = {
            "schema_version": "artifact-manifest-v1",
            "spec_hash": strategy_spec["spec_hash"],
            "dataset_id": strategy_spec["dataset_id"],
            "output_profile": output_profile,
            "files": [
                {
                    "path": path,
                    "role": (
                        "strategy_spec"
                        if path.endswith(".json")
                        else "run_harness" if path == "run.py" else "strategy_source"
                    ),
                    "bytes": len(files[path].encode("utf-8")),
                    "sha256": digest,
                }
                for path, digest in sorted(manifest.items())
            ],
            "extensions": {"draft_id": draft_id, "draft_revision": revision},
        }
        artifact_hash = sha256_json(core)
        return {
            **core,
            "artifact_id": f"artifact_{artifact_hash}",
            "artifact_hash": artifact_hash,
        }

    def create_draft(
        self, strategy_spec: dict[str, Any], scaffold_profile: str | None
    ) -> dict[str, Any]:
        spec = StrategySpec.parse(strategy_spec, scaffold_profile)
        scaffold_profile = spec.output_profile
        if scaffold_profile not in SCAFFOLD_PROFILES:
            raise InvalidRequest("unknown scaffold profile")
        draft_id = f"draft_{uuid.uuid4().hex}"
        root = self.settings.state_root / "drafts" / draft_id
        root.mkdir(mode=0o700)
        os.chmod(root, 0o700)
        files = scaffold_files(spec, scaffold_profile)
        files["strategy_spec.json"] = (
            json.dumps(spec.as_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        )
        for relative, content in files.items():
            atomic_write(root / relative, content.encode("utf-8"), mode=0o600)
        manifest = self._manifest(files)
        spec_dict = spec.as_dict()
        artifact = self._artifact_manifest(
            draft_id, 1, spec_dict, scaffold_profile, manifest, files
        )
        draft = {
            "draft_id": draft_id,
            "revision": 1,
            "profile": scaffold_profile,
            "archetype": spec.archetype,
            "strategy_spec": spec_dict,
            "allowed_files": sorted(files),
            "editable_files": sorted(path for path in files if path.endswith(".py")),
            "manifest": manifest,
            "manifest_hash": sha256_json(manifest),
            "artifact_manifest": artifact,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        self.state.put("draft", draft_id, draft)
        self.state.audit("draft.created", draft_id, {"manifest_hash": draft["manifest_hash"]})
        return draft

    def get_draft(self, draft_id: str) -> dict[str, Any]:
        draft = self.state.get("draft", draft_id)
        files = self._files(draft)
        manifest = self._manifest(files)
        artifact = self._artifact_manifest(
            draft_id,
            draft["revision"],
            draft["strategy_spec"],
            draft["profile"],
            manifest,
            files,
        )
        return {
            **draft,
            "manifest": manifest,
            "manifest_hash": sha256_json(manifest),
            "artifact_manifest": artifact,
            "files": files,
        }

    def update_draft_file(
        self,
        draft_id: str,
        relative_path: str,
        content: str,
        expected_revision: int,
        expected_file_hash: str,
    ) -> dict[str, Any]:
        if not isinstance(content, str) or len(content.encode("utf-8")) > 2 * 1024 * 1024:
            raise InvalidRequest("draft file content exceeds the 2 MiB limit")
        with self.locks.acquire(f"draft:{draft_id}"):
            draft = self.state.get("draft", draft_id)
            if relative_path not in draft["editable_files"]:
                raise InvalidRequest("file is not editable in this scaffold profile")
            if draft["revision"] != expected_revision:
                raise Conflict("draft revision is stale")
            root = self._path(draft_id)
            path = confined_path(root, relative_path, must_exist=True)
            if file_hash(path) != expected_file_hash:
                raise Conflict("draft file hash is stale")
            atomic_write(path, content.encode("utf-8"), mode=0o600)
            files = self._files(draft)
            manifest = self._manifest(files)
            next_revision = draft["revision"] + 1
            artifact = self._artifact_manifest(
                draft_id,
                next_revision,
                draft["strategy_spec"],
                draft["profile"],
                manifest,
                files,
            )

            def mutate(current: dict[str, Any]) -> dict[str, Any]:
                current["revision"] = next_revision
                current["manifest"] = manifest
                current["manifest_hash"] = sha256_json(manifest)
                current["artifact_manifest"] = artifact
                current["updated_at"] = utc_now()
                return current

            updated = self.state.update("draft", draft_id, mutate)
            self.state.audit(
                "draft.updated",
                draft_id,
                {"relative_path": relative_path, "revision": updated["revision"]},
            )
        return updated

    def apply_strategy_repair(
        self,
        draft_id: str,
        validation_id: str,
        relative_path: str,
        content: str,
        expected_revision: int,
        expected_file_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        request = {
            "draft_id": draft_id,
            "validation_id": validation_id,
            "relative_path": relative_path,
            "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "expected_revision": expected_revision,
            "expected_file_hash": expected_file_hash,
        }
        prior = self.state.idempotent_get("apply_strategy_repair", idempotency_key, request)
        if prior is not None:
            return prior
        validation = self.state.get("validation", validation_id)
        draft = self.get_draft(draft_id)
        if (
            validation["draft_id"] != draft_id
            or validation["draft_revision"] != expected_revision
            or validation["report"]["artifact_hash"] != draft["artifact_manifest"]["artifact_hash"]
        ):
            raise Conflict("repair validation is stale or bound to another artifact")
        updated = self.update_draft_file(
            draft_id,
            relative_path,
            content,
            expected_revision,
            expected_file_hash,
        )
        response = {
            "draft_id": draft_id,
            "revision": updated["revision"],
            "manifest_hash": updated["manifest_hash"],
            "artifact_hash": updated["artifact_manifest"]["artifact_hash"],
            "prior_validation_id": validation_id,
            "prior_validation_invalidated": True,
        }
        self.state.idempotent_put("apply_strategy_repair", idempotency_key, request, response)
        self.state.audit("draft.repaired", draft_id, response)
        return response

    def validate_draft(self, draft_id: str, expected_revision: int) -> dict[str, Any]:
        with self.locks.acquire(f"draft:{draft_id}"):
            draft = self.get_draft(draft_id)
            if draft["revision"] != expected_revision:
                raise Conflict("draft revision is stale")
            static_report = validate_sources(draft["files"])
            validation_id = f"validation_{uuid.uuid4().hex}"
            report_core = {
                "schema_version": "validation-report-v1",
                "validation_id": validation_id,
                "artifact_hash": draft["artifact_manifest"]["artifact_hash"],
                "dataset_id": draft["strategy_spec"]["dataset_id"],
                "status": static_report["status"],
                "diagnostics": static_report["diagnostics"],
                "evidence": static_report["evidence"],
            }
            report = {
                **report_core,
                "validation_hash": sha256_json(report_core),
            }
            record = {
                "validation_id": validation_id,
                "draft_id": draft_id,
                "draft_revision": draft["revision"],
                "draft_manifest_hash": draft["manifest_hash"],
                "report": report,
                "validation_hash": report["validation_hash"],
                "created_at": utc_now(),
            }
            self.state.put("validation", validation_id, record)
            claims = {
                "validation_id": validation_id,
                "draft_id": draft_id,
                "draft_revision": draft["revision"],
                "draft_manifest_hash": draft["manifest_hash"],
                "validation_hash": report["validation_hash"],
                "status": report["status"],
            }
            token = self.signer.issue("validation", claims, ttl_seconds=1800)
            self.state.audit("draft.validated", draft_id, claims)
            return {**record, "validation_token": token}

    def verify_validation(self, draft_id: str, validation_token: str) -> dict[str, Any]:
        claims = self.signer.verify(validation_token, "validation")
        draft = self.get_draft(draft_id)
        validation = self.state.get("validation", claims.get("validation_id", ""))
        expected = {
            "draft_id": draft_id,
            "draft_revision": draft["revision"],
            "draft_manifest_hash": draft["manifest_hash"],
            "validation_hash": validation["validation_hash"],
            "status": "passed",
        }
        for key, value in expected.items():
            if claims.get(key) != value:
                raise Conflict("validation token is stale or does not bind this draft")
        if validation["report"]["status"] != "passed":
            raise Conflict("draft validation did not pass")
        return {"draft": draft, "validation": validation, "claims": claims}
