"""Read-only Backtrader engine-root inspection and hash binding."""

import re
from pathlib import Path
from typing import Any, Dict

from .canonical import hash_object, sha256_bytes
from .errors import AgentError
from .roots import RootRegistry

VERSION_RE = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)


def inspect_engine(roots: RootRegistry, root_id: str) -> Dict[str, Any]:
    record = roots.get_record(root_id)
    if record.get("kind") != "engine" or record.get("writable"):
        raise AgentError(
            "BTAG-ENGINE-ROOT",
            "engine root must be registered read-only with kind 'engine'",
        )
    root = Path(record["path"]).resolve(strict=True)
    package = root / "backtrader"
    initializer = package / "__init__.py"
    version_file = package / "version.py"
    if not initializer.is_file() or not version_file.is_file():
        raise AgentError(
            "BTAG-ENGINE-LAYOUT",
            "engine root must contain backtrader/__init__.py and backtrader/version.py",
        )
    version_source = version_file.read_text(encoding="utf-8")
    match = VERSION_RE.search(version_source)
    descriptor: Dict[str, Any] = {
        "schema_version": "engine-runtime-v1",
        "root_id": root_id,
        "package": "backtrader",
        "version": match.group(1) if match else "unknown",
        "initializer_sha256": sha256_bytes(initializer.read_bytes()),
        "version_file_sha256": sha256_bytes(version_file.read_bytes()),
    }
    descriptor["engine_hash"] = hash_object(descriptor)
    return descriptor
