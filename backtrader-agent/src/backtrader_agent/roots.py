"""Opaque root registry and confined path resolution."""

import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List

from .canonical import atomic_write_json, read_json
from .errors import AgentError

ROOT_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")


class RootRegistry:
    """Stores local root paths outside portable manifests.

    Callers use a root ID and a POSIX relative path. Resolution rejects absolute
    paths, parent traversal, symlink escapes, and non-regular input files.
    """

    def __init__(self, state_root: Path) -> None:
        self.state_root = Path(state_root).resolve()
        self.path = self.state_root / "roots.json"

    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": "root-registry-v1", "roots": {}}
        return read_json(self.path)

    def register(self, root_id: str, path: Path, *, writable: bool, kind: str) -> Dict[str, Any]:
        if not ROOT_ID_RE.fullmatch(root_id):
            raise AgentError("BTAG-ROOT-ID", "root ID must be a lowercase opaque identifier")
        resolved = Path(path).resolve(strict=True)
        if not resolved.is_dir():
            raise AgentError("BTAG-ROOT-TYPE", "registered root must be a directory")
        if kind not in {"workspace", "dataset", "engine", "runtime"}:
            raise AgentError("BTAG-ROOT-KIND", "root kind is not allowlisted")
        registry = self._load()
        existing = registry["roots"].get(root_id)
        record = {"path": str(resolved), "writable": bool(writable), "kind": kind}
        if existing and existing != record:
            raise AgentError("BTAG-ROOT-CONFLICT", "root ID is already bound to another root")
        registry["roots"][root_id] = record
        atomic_write_json(self.path, registry)
        return {"root_id": root_id, "writable": bool(writable), "kind": kind}

    def list(self) -> List[Dict[str, Any]]:
        registry = self._load()
        return [
            {
                "root_id": root_id,
                "writable": item["writable"],
                "kind": item["kind"],
            }
            for root_id, item in sorted(registry["roots"].items())
        ]

    def get_record(self, root_id: str) -> Dict[str, Any]:
        record = self._load()["roots"].get(root_id)
        if record is None:
            raise AgentError("BTAG-ROOT-UNKNOWN", "root ID is not registered")
        return record

    @staticmethod
    def _validate_relative(relative_path: str) -> PurePosixPath:
        if not relative_path or "\x00" in relative_path:
            raise AgentError("BTAG-PATH-INVALID", "relative path is empty or malformed")
        candidate = PurePosixPath(relative_path.replace("\\", "/"))
        if candidate.is_absolute() or ".." in candidate.parts:
            raise AgentError(
                "BTAG-PATH-TRAVERSAL", "path must be relative and cannot traverse parents"
            )
        if candidate.parts and ":" in candidate.parts[0]:
            raise AgentError("BTAG-PATH-ABSOLUTE", "platform absolute paths are forbidden")
        return candidate

    def resolve(
        self,
        root_id: str,
        relative_path: str,
        *,
        for_write: bool = False,
        require_file: bool = False,
    ) -> Path:
        record = self.get_record(root_id)
        if for_write and not record["writable"]:
            raise AgentError("BTAG-ROOT-READONLY", "root is registered read-only")
        relative = self._validate_relative(relative_path)
        root = Path(record["path"]).resolve(strict=True)
        unresolved = root.joinpath(*relative.parts)

        # Resolve the existing parent so a symlink cannot redirect the write.
        existing_parent = unresolved.parent
        while not existing_parent.exists() and existing_parent != root:
            existing_parent = existing_parent.parent
        parent_real = existing_parent.resolve(strict=True)
        try:
            parent_real.relative_to(root)
        except ValueError as exc:
            raise AgentError("BTAG-PATH-SYMLINK", "path escapes the registered root") from exc

        if unresolved.exists():
            resolved = unresolved.resolve(strict=True)
            try:
                resolved.relative_to(root)
            except ValueError as exc:
                raise AgentError("BTAG-PATH-SYMLINK", "path escapes the registered root") from exc
            if require_file:
                mode = os.stat(resolved, follow_symlinks=False).st_mode
                if not stat.S_ISREG(mode):
                    raise AgentError("BTAG-PATH-TYPE", "input must be a regular file")
            return resolved
        if require_file:
            raise AgentError("BTAG-PATH-MISSING", "input file does not exist")
        return unresolved
