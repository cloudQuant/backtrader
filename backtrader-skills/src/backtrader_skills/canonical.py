"""Canonical JSON, hashing, and atomic file helpers."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

from .errors import ContractError, PathPolicyError


def _normalize(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractError("canonical JSON rejects NaN and Infinity")
        return 0.0 if value == 0.0 else value
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractError("canonical JSON object keys must be strings")
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in normalized:
                raise ContractError("canonical JSON keys collide after Unicode NFC normalization")
            normalized[normalized_key] = _normalize(item)
        return normalized
    if hasattr(value, "to_dict"):
        return _normalize(value.to_dict())
    raise ContractError(f"unsupported canonical JSON type: {type(value).__name__}")


def canonical_bytes(value: Any) -> bytes:
    """Return the UTF-8 canonical representation used by every product hash."""

    return json.dumps(
        _normalize(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def bytes_hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            Path(temp_name).unlink()
        except FileNotFoundError:
            pass


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_bytes(path, canonical_bytes(value) + b"\n")


def resolve_inside(root: Path, relative: str, *, must_exist: bool = False) -> Path:
    """Resolve a user-relative path without allowing absolute, parent, or symlink escape."""

    candidate_text = Path(relative)
    if candidate_text.is_absolute() or ".." in candidate_text.parts:
        raise PathPolicyError("path must be relative and cannot contain '..'")
    canonical_root = root.resolve(strict=True)
    candidate = canonical_root.joinpath(candidate_text)
    resolved = candidate.resolve(strict=must_exist)
    if resolved != canonical_root and canonical_root not in resolved.parents:
        raise PathPolicyError("path escapes the configured root")
    return resolved


def safe_identifier(value: str, *, field: str = "identifier") -> str:
    if not value or len(value) > 96:
        raise ContractError(f"{field} must contain 1 to 96 characters")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
    if any(character not in allowed for character in value):
        raise ContractError(f"{field} contains unsupported characters")
    return value
