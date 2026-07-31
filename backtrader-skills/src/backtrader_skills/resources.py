"""Locate canonical resources in a source checkout or installed distribution."""

from __future__ import annotations

import sys
from pathlib import Path

from .errors import ContractError


def resource_root() -> Path:
    source_root = Path(__file__).resolve().parents[2] / "resources"
    if source_root.is_dir():
        return source_root
    adjacent_install = (
        Path(__file__).resolve().parents[1] / "share" / "backtrader-skills" / "resources"
    )
    if adjacent_install.is_dir():
        return adjacent_install
    installed_root = Path(sys.prefix) / "share" / "backtrader-skills" / "resources"
    if installed_root.is_dir():
        return installed_root
    raise ContractError("backtrader-skills resource distribution is incomplete")


def resource_path(group: str, name: str) -> Path:
    if "/" in group or ".." in group or "/" in name or ".." in name:
        raise ContractError("resource names cannot contain path traversal")
    path = resource_root() / group / name
    if not path.is_file():
        raise ContractError(f"resource does not exist: {group}/{name}")
    return path
