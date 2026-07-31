"""Canonical JSON, hashing, and atomic persistence helpers."""

import hashlib
import json
import math
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Dict

from .errors import AgentError

HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _normalize(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise AgentError("BTAG-JSON-FINITE", "canonical JSON rejects NaN and Infinity")
        return 0.0 if value == 0.0 else value
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        normalized: Dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise AgentError("BTAG-JSON-KEY", "canonical JSON keys must be strings")
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in normalized:
                raise AgentError(
                    "BTAG-JSON-KEY",
                    "canonical JSON keys collide after Unicode NFC normalization",
                )
            normalized[normalized_key] = _normalize(item)
        return normalized
    if hasattr(value, "to_dict"):
        return _normalize(value.to_dict())
    raise AgentError(
        "BTAG-JSON-TYPE",
        f"unsupported canonical JSON type: {type(value).__name__}",
    )


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _normalize(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def hash_object(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def read_json(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError) as exc:
        raise AgentError("BTAG-JSON-READ", "JSON artifact could not be read") from exc
    if not isinstance(value, dict):
        raise AgentError("BTAG-JSON-TYPE", "JSON artifact must be an object")
    return value


def atomic_write_bytes(path: Path, data: bytes, *, create_only: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if create_only and path.exists():
        raise AgentError("BTAG-WRITE-EXISTS", "create-only target already exists")
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if create_only and path.exists():
            raise AgentError("BTAG-WRITE-EXISTS", "create-only target already exists")
        os.replace(str(temporary), str(path))
        try:
            directory_fd = os.open(str(path.parent), os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_json(path: Path, value: Dict[str, Any], *, create_only: bool = False) -> None:
    atomic_write_bytes(path, canonical_json_bytes(value) + b"\n", create_only=create_only)


def content_hashes(files: Dict[str, bytes]) -> Dict[str, str]:
    return {name: sha256_bytes(content) for name, content in sorted(files.items())}
