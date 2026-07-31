"""Trusted local configuration loaded at process start."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .errors import InvalidRequest


def _root_map(raw: str | None) -> dict[str, Path]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InvalidRequest("root maps must be valid JSON objects") from exc
    if not isinstance(value, dict):
        raise InvalidRequest("root maps must be JSON objects")
    result: dict[str, Path] = {}
    for key, path in value.items():
        if not isinstance(key, str) or not key.replace("_", "").replace("-", "").isalnum():
            raise InvalidRequest(f"invalid root id: {key!r}")
        candidate = Path(path).expanduser().resolve(strict=False)
        result[key] = candidate
    return result


def _positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise InvalidRequest(f"{name} must be a positive integer") from exc
    if value < 1:
        raise InvalidRequest(f"{name} must be a positive integer")
    return value


@dataclass(frozen=True)
class Settings:
    state_root: Path
    source_roots: dict[str, Path] = field(default_factory=dict)
    target_roots: dict[str, Path] = field(default_factory=dict)
    runtimes: dict[str, Path] = field(default_factory=dict)
    max_dataset_bytes: int = 64 * 1024 * 1024
    max_preview_rows: int = 200
    max_run_seconds: int = 300

    @classmethod
    def from_env(cls) -> "Settings":
        state = Path(
            os.environ.get(
                "BACKTRADER_MCP_STATE_ROOT",
                str(Path.home() / ".local" / "share" / "backtrader-mcp"),
            )
        ).expanduser()
        return cls(
            state_root=state.resolve(strict=False),
            source_roots=_root_map(os.environ.get("BACKTRADER_MCP_SOURCE_ROOTS")),
            target_roots=_root_map(os.environ.get("BACKTRADER_MCP_TARGET_ROOTS")),
            runtimes=_root_map(os.environ.get("BACKTRADER_MCP_RUNTIMES")),
            max_dataset_bytes=_positive_int(
                "BACKTRADER_MCP_MAX_DATASET_BYTES",
                64 * 1024 * 1024,
            ),
            max_preview_rows=_positive_int("BACKTRADER_MCP_MAX_PREVIEW_ROWS", 200),
            max_run_seconds=_positive_int("BACKTRADER_MCP_MAX_RUN_SECONDS", 300),
        )

    def initialize(self) -> None:
        self.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.state_root, 0o700)
        for child in ("cas", "drafts", "jobs", "locks", "transactions"):
            (self.state_root / child).mkdir(parents=True, exist_ok=True, mode=0o700)
