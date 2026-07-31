"""Create-only native host adapter installer."""

import json
from pathlib import Path
import shlex
from typing import Any, Dict, List, Mapping

from .canonical import atomic_write_bytes, atomic_write_json, read_json, sha256_bytes
from .errors import AgentError

RESOURCE_ROOT = Path(__file__).resolve().parent / "resources" / "adapters"
ADAPTER_RESOURCE_FILES: Mapping[str, Mapping[str, str]] = {
    "claude": {
        ".claude/agents/backtrader-agent.md": "claude-code/backtrader-agent.md",
    },
    "codex": {
        ".codex/agents/backtrader-agent.toml": "codex/backtrader-agent.toml",
    },
    "opencode": {
        ".opencode/agents/backtrader-agent.md": "opencode/backtrader-agent.md",
    },
    "openclaw": {
        ".openclaw/workspaces/backtrader-agent/README.md": "openclaw/workspace/README.md",
        ".openclaw/workspaces/backtrader-agent/AGENTS.md": "openclaw/workspace/AGENTS.md",
        ".openclaw/workspaces/backtrader-agent/IDENTITY.md": "openclaw/workspace/IDENTITY.md",
    },
}


class AdapterInstaller:
    @staticmethod
    def _resource_text(relative_path: str) -> str:
        path = RESOURCE_ROOT.joinpath(*Path(relative_path).parts)
        if not path.is_file() or path.is_symlink():
            raise AgentError(
                "BTAG-INSTALL-RESOURCE",
                "packaged host adapter resource is missing or unsafe",
            )
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _openclaw_registration(workspace: Path) -> Dict[str, Any]:
        template = json.loads(
            AdapterInstaller._resource_text(
                "openclaw/workspace/registration-manifest.template.json"
            )
        )
        quoted_workspace = shlex.quote(str(workspace))
        first_request = str(template["first_request"])
        quoted_request = shlex.quote(first_request)
        template.update(
            {
                "workspace": str(workspace),
                "registration_command": (
                    "openclaw agents add backtrader-agent "
                    f"--workspace {quoted_workspace} --non-interactive"
                ),
                "invocation_command": (
                    "openclaw agent --agent backtrader-agent " f"--message {quoted_request}"
                ),
            }
        )
        return template

    @staticmethod
    def _files(root: Path, host: str) -> Dict[str, str]:
        files = {
            destination: AdapterInstaller._resource_text(resource)
            for destination, resource in ADAPTER_RESOURCE_FILES[host].items()
        }
        if host == "openclaw":
            workspace = (root / ".openclaw/workspaces/backtrader-agent").resolve()
            registration = AdapterInstaller._openclaw_registration(workspace)
            files[".openclaw/workspaces/backtrader-agent/registration-manifest.json"] = (
                json.dumps(registration, indent=2, sort_keys=True) + "\n"
            )
        return files

    def install(self, target: Path, host: str, *, apply: bool) -> Dict[str, Any]:
        if host not in ADAPTER_RESOURCE_FILES:
            raise AgentError("BTAG-INSTALL-HOST", "host adapter is not supported")
        root = Path(target).resolve(strict=True)
        if not root.is_dir():
            raise AgentError("BTAG-INSTALL-TARGET", "install target must be a directory")
        adapter_files = self._files(root, host)
        changes: List[Dict[str, Any]] = []
        for relative, content in adapter_files.items():
            destination = root.joinpath(*Path(relative).parts)
            encoded = content.encode("utf-8")
            if destination.exists():
                if not destination.is_file() or destination.read_bytes() != encoded:
                    raise AgentError(
                        "BTAG-INSTALL-CONFLICT",
                        "existing adapter differs; create-only install refused",
                        details={"relative_path": relative},
                    )
                action = "unchanged"
            else:
                action = "create"
            changes.append(
                {
                    "relative_path": relative,
                    "action": action,
                    "sha256": sha256_bytes(encoded),
                    "size_bytes": len(encoded),
                }
            )
        if not apply:
            result: Dict[str, Any] = {
                "status": "preview",
                "host": host,
                "changes": changes,
            }
            if host == "openclaw":
                workspace = (root / ".openclaw/workspaces/backtrader-agent").resolve()
                registration = self._openclaw_registration(workspace)
                result["manual_registration"] = {
                    "required": True,
                    "command": registration["registration_command"],
                    "invoke": registration["invocation_command"],
                    "verify": registration["verification_command"],
                }
            return result
        for relative, content in adapter_files.items():
            destination = root.joinpath(*Path(relative).parts)
            if not destination.exists():
                atomic_write_bytes(destination, content.encode("utf-8"), create_only=True)
        install_manifest = {
            "schema_version": "adapter-install-manifest-v1",
            "host": host,
            "files": [
                {
                    "relative_path": relative,
                    "sha256": sha256_bytes(content.encode("utf-8")),
                }
                for relative, content in sorted(adapter_files.items())
            ],
        }
        manifest_path = root / ".backtrader-agent" / "installer" / f"{host}.json"
        if manifest_path.exists():
            if read_json(manifest_path) != install_manifest:
                raise AgentError("BTAG-INSTALL-MANIFEST", "install manifest conflicts")
        else:
            atomic_write_json(manifest_path, install_manifest, create_only=True)
        status = (
            "unchanged" if all(item["action"] == "unchanged" for item in changes) else "installed"
        )
        result = {"status": status, "host": host, "changes": changes}
        if host == "openclaw":
            workspace = (root / ".openclaw/workspaces/backtrader-agent").resolve()
            registration = self._openclaw_registration(workspace)
            result["manual_registration"] = {
                "required": True,
                "executed": False,
                "command": registration["registration_command"],
                "invoke": registration["invocation_command"],
                "verify": registration["verification_command"],
            }
        return result

    def uninstall(self, target: Path, host: str, *, apply: bool) -> Dict[str, Any]:
        root = Path(target).resolve(strict=True)
        manifest_path = root / ".backtrader-agent" / "installer" / f"{host}.json"
        if not manifest_path.exists():
            raise AgentError("BTAG-UNINSTALL-MANIFEST", "no install manifest exists for host")
        manifest = read_json(manifest_path)
        removals = []
        for item in manifest.get("files", []):
            destination = root.joinpath(*Path(item["relative_path"]).parts)
            if destination.exists():
                if sha256_bytes(destination.read_bytes()) != item["sha256"]:
                    raise AgentError(
                        "BTAG-UNINSTALL-MODIFIED",
                        "modified adapter will not be removed",
                        details={"relative_path": item["relative_path"]},
                    )
                removals.append(item["relative_path"])
        if apply:
            for relative in removals:
                root.joinpath(*Path(relative).parts).unlink()
            manifest_path.unlink()
        return {
            "status": "uninstalled" if apply else "preview",
            "host": host,
            "remove": removals,
        }
