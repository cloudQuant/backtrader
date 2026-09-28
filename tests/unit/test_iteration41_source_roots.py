"""Contracts for the source-root resolver used by Iteration 41 tests."""

from __future__ import annotations

import importlib.machinery
import json

import pytest

from tests.test_utils import iteration41_source_roots as source_roots


def test_explicit_source_map_rejects_missing_required_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(
        source_roots.SOURCE_ROOTS_ENV,
        json.dumps({"parent": str(tmp_path)}),
    )

    with pytest.raises(source_roots.Iteration41SourceRootError, match="missing required"):
        source_roots.iteration41_source_paths("parent", "base")


def test_explicit_source_map_rejects_relative_or_missing_roots(monkeypatch) -> None:
    monkeypatch.setenv(
        source_roots.SOURCE_ROOTS_ENV,
        json.dumps({"base": "relative/source"}),
    )

    with pytest.raises(source_roots.Iteration41SourceRootError, match="must be absolute"):
        source_roots.iteration41_source_paths("base")


def test_explicit_map_resolves_ai_source_keys_in_requested_order(monkeypatch, tmp_path) -> None:
    roots = {key: tmp_path / key for key in ("agent", "skills", "mcp")}
    module_names = {
        "agent": "backtrader_agent",
        "skills": "backtrader_skills",
        "mcp": "backtrader_mcp",
    }
    for key, path in roots.items():
        package_dir = path / module_names[key]
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").touch()
    monkeypatch.setenv(
        source_roots.SOURCE_ROOTS_ENV,
        json.dumps({key: str(path) for key, path in roots.items()}),
    )

    assert source_roots.iteration41_source_paths("agent", "skills", "mcp") == tuple(
        str(roots[key].resolve()) for key in ("agent", "skills", "mcp")
    )


def test_default_resolution_uses_top_level_find_spec_without_importing(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.delenv(source_roots.SOURCE_ROOTS_ENV, raising=False)
    package_dir = tmp_path / "site-packages" / "bt_api_execution"
    package_dir.mkdir(parents=True)
    calls = []

    def fake_find_spec(module_name):
        calls.append(module_name)
        spec = importlib.machinery.ModuleSpec(module_name, loader=None, is_package=True)
        spec.submodule_search_locations = [str(package_dir)]
        return spec

    monkeypatch.setattr(source_roots.importlib.util, "find_spec", fake_find_spec)

    assert source_roots.iteration41_source_paths("execution") == (
        str(package_dir.parent.resolve()),
    )
    assert calls == ["bt_api_execution"]


def test_default_resolution_skips_missing_optional_module(monkeypatch) -> None:
    monkeypatch.delenv(source_roots.SOURCE_ROOTS_ENV, raising=False)
    monkeypatch.setattr(source_roots.importlib.util, "find_spec", lambda _name: None)

    with pytest.raises(pytest.skip.Exception, match="optional Iteration 41 source module"):
        source_roots.iteration41_source_paths("base")


def test_explicit_source_map_rejects_empty_or_wrong_package_root(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(
        source_roots.SOURCE_ROOTS_ENV,
        json.dumps({"base": str(tmp_path)}),
    )

    with pytest.raises(source_roots.Iteration41SourceRootError, match="does not contain"):
        source_roots.iteration41_source_paths("base")


def test_explicit_source_map_rejects_namespace_only_package_root(monkeypatch, tmp_path) -> None:
    (tmp_path / "bt_api_base").mkdir()
    monkeypatch.setenv(
        source_roots.SOURCE_ROOTS_ENV,
        json.dumps({"base": str(tmp_path)}),
    )

    with pytest.raises(source_roots.Iteration41SourceRootError, match="regular top-level module"):
        source_roots.iteration41_source_paths("base")
