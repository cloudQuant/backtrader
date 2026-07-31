"""Four-host, manifest-driven local skill installation and protected uninstall."""

from __future__ import annotations

import secrets
import sys
from pathlib import Path
from typing import Any, cast

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
from .runtime import RuntimePaths
from .state import TokenStore, utc_now

HOST_PATHS = {
    "claude": ".claude/skills",
    "codex": ".agents/skills",
    "opencode": ".opencode/skills",
    "openclaw": "skills",
}
SKILL_NAMES = (
    "backtrader-strategy-author",
    "backtrader-strategy-review",
    "backtrader-strategy-test",
)


def distribution_root() -> Path:
    source = Path(__file__).resolve().parents[2]
    if (source / "skills").is_dir():
        return source
    adjacent = Path(__file__).resolve().parents[1] / "share" / "backtrader-skills"
    if (adjacent / "skills").is_dir():
        return adjacent
    installed = Path(sys.prefix) / "share" / "backtrader-skills"
    if (installed / "skills").is_dir():
        return installed
    raise ContractError("installed distribution does not contain canonical skills")


def host_destination(target: Path, host: str) -> Path:
    try:
        relative = HOST_PATHS[host]
    except KeyError as error:
        raise ContractError(f"unsupported host: {host}") from error
    return resolve_inside(target.resolve(), relative, must_exist=False)


class SkillInstaller:
    def __init__(self, paths: RuntimePaths) -> None:
        self.paths = paths.ensure()
        self.tokens = TokenStore(paths)

    def preview_install(self, host: str) -> dict[str, Any]:
        destination = host_destination(self.paths.target, host)
        source_root = distribution_root() / "skills"
        files: list[dict[str, Any]] = []
        for skill_name in SKILL_NAMES:
            source_skill = source_root / skill_name
            if not (source_skill / "SKILL.md").is_file():
                raise IntegrityError(f"canonical skill is incomplete: {skill_name}")
            for source in sorted(path for path in source_skill.rglob("*") if path.is_file()):
                relative_within_skill = source.relative_to(source_skill)
                relative_target = Path(skill_name) / relative_within_skill
                target_file = destination / relative_target
                existing_hash = file_hash(target_file) if target_file.is_file() else None
                files.append(
                    {
                        "source": f"skills/{skill_name}/{relative_within_skill.as_posix()}",
                        "target": (Path(HOST_PATHS[host]) / relative_target).as_posix(),
                        "sha256": file_hash(source),
                        "bytes": source.stat().st_size,
                        "status": "create" if existing_hash is None else "conflict",
                        "existing_hash": existing_hash,
                    }
                )
        plan_id = f"install_{host}_{secrets.token_hex(6)}"
        plan = {
            "schema_version": "skill-install-plan-v1",
            "plan_id": plan_id,
            "host": host,
            "target_layout": HOST_PATHS[host],
            "created_at": utc_now(),
            "files": files,
            "conflicts": sum(item["status"] == "conflict" for item in files),
        }
        plan["plan_hash"] = canonical_hash(plan)
        atomic_write_json(self.paths.installs / f"{plan_id}.json", plan)
        token = self.tokens.issue(
            "install_write",
            {"plan_id": plan_id, "plan_hash": plan["plan_hash"], "operation": "install"},
        )
        return {"plan": plan, "approval_token": token}

    def apply_install(self, plan_id: str, token_id: str) -> dict[str, Any]:
        plan = self._load_plan(plan_id, "skill-install-plan-v1")
        bindings = {
            "plan_id": plan_id,
            "plan_hash": plan["plan_hash"],
            "operation": "install",
        }
        self.tokens.verify(token_id, "install_write", bindings)
        if plan["conflicts"]:
            raise ConflictError("installation is create-only and the preview contains conflicts")
        source_root = distribution_root()
        installed_files = []
        for entry in plan["files"]:
            source = resolve_inside(source_root, entry["source"], must_exist=True)
            if file_hash(source) != entry["sha256"]:
                raise IntegrityError("canonical skill changed after install preview")
            target = resolve_inside(self.paths.target, entry["target"], must_exist=False)
            if target.exists():
                raise ConflictError(f"install target appeared after preview: {entry['target']}")
            atomic_write_bytes(target, source.read_bytes())
            installed_files.append(
                {
                    "path": entry["target"],
                    "sha256": entry["sha256"],
                    "bytes": entry["bytes"],
                }
            )
        self.tokens.consume(token_id, "install_write", bindings)
        install_manifest = {
            "schema_version": "skill-install-manifest-v1",
            "host": plan["host"],
            "target_layout": plan["target_layout"],
            "source_plan_hash": plan["plan_hash"],
            "installed_at": utc_now(),
            "files": installed_files,
        }
        install_manifest["manifest_hash"] = canonical_hash(install_manifest)
        destination = self.paths.installs / f"installed-{plan['host']}.json"
        atomic_write_json(destination, install_manifest)
        return install_manifest

    def preview_uninstall(self, host: str) -> dict[str, Any]:
        if host not in HOST_PATHS:
            raise ContractError(f"unsupported host: {host}")
        installed_path = self.paths.installs / f"installed-{host}.json"
        if not installed_path.is_file():
            raise ContractError(f"no install manifest exists for host: {host}")
        installed = load_json(installed_path)
        expected = installed.get("manifest_hash")
        payload = dict(installed)
        payload.pop("manifest_hash", None)
        if expected != canonical_hash(payload):
            raise IntegrityError("install manifest hash is invalid")
        files = []
        for entry in installed["files"]:
            target = resolve_inside(self.paths.target, entry["path"], must_exist=False)
            current_hash = file_hash(target) if target.is_file() else None
            if current_hash is None:
                status = "already_missing"
            elif current_hash == entry["sha256"]:
                status = "remove"
            else:
                status = "preserve_modified"
            files.append(
                {
                    "path": entry["path"],
                    "installed_hash": entry["sha256"],
                    "current_hash": current_hash,
                    "status": status,
                }
            )
        plan_id = f"uninstall_{host}_{secrets.token_hex(6)}"
        plan = {
            "schema_version": "skill-uninstall-plan-v1",
            "plan_id": plan_id,
            "host": host,
            "install_manifest_hash": installed["manifest_hash"],
            "created_at": utc_now(),
            "files": files,
        }
        plan["plan_hash"] = canonical_hash(plan)
        atomic_write_json(self.paths.installs / f"{plan_id}.json", plan)
        token = self.tokens.issue(
            "uninstall_write",
            {"plan_id": plan_id, "plan_hash": plan["plan_hash"], "operation": "uninstall"},
        )
        return {"plan": plan, "approval_token": token}

    def apply_uninstall(self, plan_id: str, token_id: str) -> dict[str, Any]:
        plan = self._load_plan(plan_id, "skill-uninstall-plan-v1")
        bindings = {
            "plan_id": plan_id,
            "plan_hash": plan["plan_hash"],
            "operation": "uninstall",
        }
        self.tokens.verify(token_id, "uninstall_write", bindings)
        removed = []
        preserved = []
        for entry in plan["files"]:
            target = resolve_inside(self.paths.target, entry["path"], must_exist=False)
            current_hash = file_hash(target) if target.is_file() else None
            if entry["status"] == "remove":
                if current_hash != entry["installed_hash"]:
                    raise ConflictError(
                        f"installed file changed after uninstall preview: {entry['path']}"
                    )
                target.unlink()
                removed.append(entry["path"])
            elif entry["status"] == "preserve_modified":
                preserved.append(entry["path"])
        self.tokens.consume(token_id, "uninstall_write", bindings)
        result = {
            "schema_version": "skill-uninstall-result-v1",
            "host": plan["host"],
            "removed": removed,
            "preserved_modified": preserved,
            "completed_at": utc_now(),
        }
        atomic_write_json(self.paths.installs / f"uninstalled-{plan['host']}.json", result)
        return result

    def _load_plan(self, plan_id: str, schema_version: str) -> dict[str, Any]:
        safe_identifier(plan_id, field="plan_id")
        path = self.paths.installs / f"{plan_id}.json"
        if not path.is_file():
            raise ContractError(f"unknown install plan: {plan_id}")
        plan = load_json(path)
        if plan.get("schema_version") != schema_version:
            raise ContractError("install plan has the wrong operation type")
        expected = plan.get("plan_hash")
        payload = dict(plan)
        payload.pop("plan_hash", None)
        if expected != canonical_hash(payload):
            raise IntegrityError("install plan hash is invalid")
        return cast(dict[str, Any], plan)
