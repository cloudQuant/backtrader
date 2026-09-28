"""Resolve optional Iteration 41 SDK sources for source-only integration tests.

Acceptance runners should set ``BT_API_TEST_SOURCE_ROOTS`` to a JSON object of
exact source-root paths. The fallback is only for ordinary developer test runs:
it resolves importable top-level modules from the current interpreter without
importing them or guessing a neighboring checkout.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from typing import Mapping, Sequence

import pytest


SOURCE_ROOTS_ENV = "BT_API_TEST_SOURCE_ROOTS"
GUARD_ROOT_ENV = "BT_API_TEST_GUARD_ROOT"
METADATA_ROOT_ENV = "BT_API_TEST_METADATA_ROOT"

_MODULES = {
    "parent": "bt_api_py",
    "base": "bt_api_base",
    "ctp": "bt_api_ctp",
    "execution": "bt_api_execution",
    "risk": "bt_api_risk",
    "monitor": "bt_api_monitor",
    "gateway": "bt_api_gateway",
    "transport_zmq": "bt_api_transport_zmq",
    "agent": "backtrader_agent",
    "skills": "backtrader_skills",
    "mcp": "backtrader_mcp",
}


class Iteration41SourceRootError(ValueError):
    """An explicit source-root map is malformed or incomplete."""


def _parse_mapping(raw: str) -> Mapping[str, object]:
    def reject_duplicate_keys(pairs):
        mapping = {}
        for key, value in pairs:
            if key in mapping:
                raise Iteration41SourceRootError(
                    f"{SOURCE_ROOTS_ENV} contains duplicate key {key!r}"
                )
            mapping[key] = value
        return mapping

    try:
        parsed = json.loads(raw, object_pairs_hook=reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise Iteration41SourceRootError(
            f"{SOURCE_ROOTS_ENV} must contain a JSON object: {exc}"
        ) from exc
    if not isinstance(parsed, dict):
        raise Iteration41SourceRootError(f"{SOURCE_ROOTS_ENV} must contain a JSON object")
    unknown = sorted(set(parsed) - set(_MODULES))
    if unknown:
        raise Iteration41SourceRootError(
            f"{SOURCE_ROOTS_ENV} has unknown source keys: {', '.join(unknown)}"
        )
    return parsed


def _mapped_paths(keys: Sequence[str], mapping: Mapping[str, object]) -> tuple[str, ...]:
    missing = [key for key in keys if key not in mapping]
    if missing:
        raise Iteration41SourceRootError(
            f"{SOURCE_ROOTS_ENV} is missing required source keys: {', '.join(missing)}"
        )

    paths = []
    for key in keys:
        raw_path = mapping[key]
        if not isinstance(raw_path, str) or not raw_path:
            raise Iteration41SourceRootError(
                f"{SOURCE_ROOTS_ENV}[{key!r}] must be a non-empty absolute path"
            )
        path = Path(raw_path)
        if not path.is_absolute():
            raise Iteration41SourceRootError(
                f"{SOURCE_ROOTS_ENV}[{key!r}] must be absolute: {raw_path!r}"
            )
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise Iteration41SourceRootError(
                f"{SOURCE_ROOTS_ENV}[{key!r}] does not exist: {raw_path!r}"
            ) from exc
        if not resolved.is_dir():
            raise Iteration41SourceRootError(
                f"{SOURCE_ROOTS_ENV}[{key!r}] is not a directory: {raw_path!r}"
            )
        module_name = _MODULES[key]
        package_dir = resolved / module_name
        module_file = resolved / f"{module_name}.py"
        if not (package_dir / "__init__.py").is_file() and not module_file.is_file():
            raise Iteration41SourceRootError(
                f"{SOURCE_ROOTS_ENV}[{key!r}] does not contain regular top-level module "
                f"{module_name!r}: {raw_path!r}"
            )
        paths.append(str(resolved))
    return tuple(paths)


def _module_roots(module_name: str) -> tuple[str, ...] | None:
    """Return import roots for one top-level module without importing it."""
    spec = importlib.util.find_spec(module_name)
    if spec is None:
        return None

    locations = spec.submodule_search_locations
    if locations is not None:
        roots = []
        for location in locations:
            package_dir = Path(location).resolve(strict=True)
            if not package_dir.is_dir():
                return None
            roots.append(str(package_dir.parent))
        return tuple(dict.fromkeys(roots)) or None

    origin = spec.origin
    if not origin or origin in {"built-in", "frozen"}:
        return None
    module_file = Path(origin).resolve(strict=True)
    if not module_file.is_file():
        return None
    return (str(module_file.parent),)


def iteration41_source_paths(*keys: str) -> tuple[str, ...]:
    """Resolve ordered source roots, using an explicit map when provided.

    With ``BT_API_TEST_SOURCE_ROOTS`` set, every requested key must have an
    absolute existing directory; malformed maps raise instead of falling back.
    Without it, optional packages are located only through top-level
    ``find_spec`` calls. Missing packages follow the integration suite's
    existing optional-dependency skip convention.
    """
    if not keys:
        raise Iteration41SourceRootError("at least one Iteration 41 source key is required")
    unknown = [key for key in keys if key not in _MODULES]
    if unknown:
        raise Iteration41SourceRootError(f"unknown Iteration 41 source key(s): {unknown!r}")
    if len(set(keys)) != len(keys):
        raise Iteration41SourceRootError("Iteration 41 source keys must not contain duplicates")

    raw_mapping = os.environ.get(SOURCE_ROOTS_ENV)
    if raw_mapping is not None:
        return _mapped_paths(keys, _parse_mapping(raw_mapping))

    roots = []
    for key in keys:
        module_name = _MODULES[key]
        resolved = _module_roots(module_name)
        if resolved is None:
            pytest.skip(f"optional Iteration 41 source module {module_name!r} is unavailable")
        roots.extend(resolved)
    return tuple(dict.fromkeys(roots))


def iteration41_child_pythonpath(source_paths: Sequence[str]) -> str:
    """Build a child PYTHONPATH from resolved roots and an optional test guard.

    Deliberately does not append the caller's existing ``PYTHONPATH``. This
    prevents a stale sibling checkout from silently shadowing pinned sources.
    """
    paths = []
    guard_root = os.environ.get(GUARD_ROOT_ENV)
    if guard_root is not None:
        guard = Path(guard_root)
        if not guard.is_absolute() or not guard.is_dir():
            raise Iteration41SourceRootError(
                f"{GUARD_ROOT_ENV} must be an existing absolute directory"
            )
        paths.append(str(guard.resolve()))
    paths.extend(source_paths)
    metadata_root = os.environ.get(METADATA_ROOT_ENV)
    if metadata_root is not None:
        metadata = Path(metadata_root)
        if not metadata.is_absolute() or not metadata.is_dir():
            raise Iteration41SourceRootError(
                f"{METADATA_ROOT_ENV} must be an existing absolute directory"
            )
        paths.append(str(metadata.resolve()))
    return os.pathsep.join(paths)
