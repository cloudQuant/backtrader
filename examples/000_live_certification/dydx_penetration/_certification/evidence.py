"""Append-only, recursively redacted JSONL evidence with SHA-256 chaining."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets as secrets_module
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SENSITIVE_KEY = re.compile(
    r"(?:secret|pass(word|phrase)?|token|authorization|auth[_-]?(?:header|value)|basic[_-]?auth|api[_-]?key|credential|private[_-]?key|signature|cookie|endpoint|url|host)",
    re.I,
)
_IDENTIFIER_KEY = re.compile(r"(?:^|_)(?:id|ids|ref)$", re.I)
_URL = re.compile(r"https?://[^\s\"']+", re.I)
_BEARER = re.compile(r"\bBearer\s+[^\s\"']+", re.I)
_LONG_TOKEN = re.compile(r"\b[A-Za-z0-9_+\-/=]{40,}\b")
UTC = timezone.utc


def _pseudonym(value: Any, salt: bytes) -> Any:
    if isinstance(value, list):
        return [_pseudonym(item, salt) for item in value]
    if value is None:
        return None
    digest = hashlib.sha256(salt + str(value).encode("utf-8")).hexdigest()[:20]
    return f"id:{digest}"


def redact(value: Any, secrets: tuple[str, ...] = (), salt: bytes = b"") -> Any:
    """Remove sensitive keys and values at arbitrary nesting depth."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            name = str(key)
            if _SENSITIVE_KEY.search(name):
                result[name] = "[REDACTED]"
            elif name != "case_id" and _IDENTIFIER_KEY.search(name):
                result[name] = _pseudonym(item, salt)
            else:
                result[name] = redact(item, secrets, salt)
        return result
    if isinstance(value, (list, tuple, set)):
        return [redact(item, secrets, salt) for item in value]
    if isinstance(value, str):
        result = value
        for secret in sorted((s for s in secrets if s), key=len, reverse=True):
            result = result.replace(secret, "[REDACTED]")
        result = _BEARER.sub("Bearer [REDACTED]", result)
        result = _URL.sub("[REDACTED_URL]", result)
        return _LONG_TOKEN.sub("[REDACTED_TOKEN]", result)
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return redact(str(value), secrets, salt)


class EvidenceWriter:
    """A new run owns two new files; existing evidence is never overwritten."""

    def __init__(self, directory: Path, run_id: str, secrets: tuple[str, ...] = ()):
        directory.mkdir(parents=True, exist_ok=True)
        self.jsonl_path = directory / f"{run_id}.jsonl"
        self.summary_path = directory / f"{run_id}.summary.json"
        self._stream = self.jsonl_path.open("x", encoding="utf-8", newline="\n")
        self._hash = "0" * 64
        self._sequence = 0
        self._secrets = secrets
        self._salt = secrets_module.token_bytes(16)

    @property
    def final_hash(self) -> str:
        return self._hash

    def append(self, kind: str, data: dict[str, Any], *, durable: bool = False) -> None:
        self._sequence += 1
        record = {
            "sequence": self._sequence,
            "time_utc": datetime.now(UTC).isoformat(),
            "kind": kind,
            "data": redact(data, self._secrets, self._salt),
            "previous_hash": self._hash,
        }
        canonical = json.dumps(
            record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        self._hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        record["hash"] = self._hash
        self._stream.write(
            json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + "\n"
        )
        self._stream.flush()
        if durable:
            os.fsync(self._stream.fileno())

    def finish(self, summary: dict[str, Any]) -> None:
        self.append("summary", summary)
        body = {
            "summary": redact(summary, self._secrets, self._salt),
            "final_hash": self._hash,
            "record_count": self._sequence,
        }
        with self.summary_path.open("x", encoding="utf-8") as stream:
            json.dump(body, stream, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        self._stream.close()

    def close(self) -> None:
        self._stream.close()


def verify_evidence(jsonl_path: str | Path, summary_path: str | Path) -> bool:
    """Verify the append-only chain and its independently written summary anchor."""
    previous = "0" * 64
    count = 0
    last_record: dict[str, Any] | None = None
    with Path(jsonl_path).open("r", encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            digest = record.pop("hash")
            if record["previous_hash"] != previous or record["sequence"] != count + 1:
                return False
            canonical = json.dumps(
                record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
            previous = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            if previous != digest:
                return False
            count += 1
            last_record = record
    with Path(summary_path).open("r", encoding="utf-8") as stream:
        anchor = json.load(stream)
    return (
        count > 0
        and last_record is not None
        and last_record.get("kind") == "summary"
        and last_record.get("data") == anchor.get("summary")
        and anchor.get("final_hash") == previous
        and anchor.get("record_count") == count
    )
