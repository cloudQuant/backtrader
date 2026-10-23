"""Public benchmark source inventories exclude ignored inputs and pin assets."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


def _runner():
    path = Path(__file__).resolve().parents[2] / "scripts/benchmark_factor_examples.py"
    spec = importlib.util.spec_from_file_location("factor_benchmark_source_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_git_inventory_ignores_local_config_and_outputs_but_pins_assets(tmp_path, monkeypatch):
    runner = _runner()
    public = {
        "fincore/__init__.py": "# package\n",
        "fincore/report/assets/chart.js": "const chart = 1;\n",
        "example/run.py": "# public entry\n",
    }
    for name, text in public.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    ignored = [tmp_path / "example/config.yaml", tmp_path / "example/output/result.json"]
    for path in ignored:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic ignored fixture", encoding="utf-8")

    def git(args, **kwargs):
        if "ls-files" in args:
            return SimpleNamespace(stdout="\0".join(public).encode() + b"\0")
        if "rev-parse" in args:
            return SimpleNamespace(stdout="a" * 40 + "\n")
        if "branch" in args:
            return SimpleNamespace(stdout="dev\n")
        assert "status" in args
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(runner.subprocess, "run", git)
    original_hash = runner._hash

    def public_hash(path):
        assert path not in ignored, "ignored configuration/output must not be read"
        return original_hash(path)

    monkeypatch.setattr(runner, "_hash", public_hash)
    before, pins = runner._source_state(tmp_path, "fincore", ("example",))
    assert set(pins) == set(public)
    asset = tmp_path / "fincore/report/assets/chart.js"
    asset.write_text("const chart = 2;\n", encoding="utf-8")
    after, changed = runner._source_state(tmp_path, "fincore", ("example",))
    assert before["source_content_sha256"] != after["source_content_sha256"]
    assert pins["fincore/report/assets/chart.js"] != changed["fincore/report/assets/chart.js"]


def test_git_inventory_rejects_missing_public_entry(tmp_path, monkeypatch):
    runner = _runner()
    monkeypatch.setattr(runner.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=b""))
    with pytest.raises(ValueError, match="omits public input"):
        runner._source_state(tmp_path, "fincore", ("example",))
