from __future__ import annotations

import hashlib
import json
from pathlib import Path

import backtrader_mcp.doctor as doctor_module
from backtrader_mcp.cli import main

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _tree_snapshot(root: Path) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
    directories = tuple(
        sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_dir())
    )
    files = tuple(
        sorted(
            (
                str(path.relative_to(root)),
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
            for path in root.rglob("*")
            if path.is_file()
        )
    )
    return directories, files


def _create_synthetic_runtime(tmp_path: Path) -> Path:
    runtime = tmp_path / "runtime"
    package = runtime / "backtrader"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "__version__ = '1.3.0'\n"
        "class Cerebro: pass\n"
        "class Strategy: pass\n"
        "class GenericCSVData: pass\n"
        "class PandasData: pass\n"
        "class Feeds:\n"
        "    pass\n"
        "feeds = Feeds()\n"
        "feeds.GenericCSVData = GenericCSVData\n"
        "feeds.PandasData = PandasData\n",
        encoding="utf-8",
    )
    return runtime


def _supported_distributions(monkeypatch) -> None:
    versions = {
        "backtrader-mcp": "0.1.0",
        "mcp": "2.0.0",
        "pandas": "2.2.3",
    }
    monkeypatch.setattr(doctor_module.metadata, "version", versions.__getitem__)


def _configure_roots(monkeypatch, tmp_path: Path, *, runtimes: dict[str, str]) -> Path:
    state = tmp_path / "state"
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    monkeypatch.setenv("BACKTRADER_MCP_STATE_ROOT", str(state))
    monkeypatch.setenv("BACKTRADER_MCP_SOURCE_ROOTS", json.dumps({"market": str(source)}))
    monkeypatch.setenv("BACKTRADER_MCP_TARGET_ROOTS", json.dumps({"strategies": str(target)}))
    monkeypatch.setenv("BACKTRADER_MCP_RUNTIMES", json.dumps(runtimes))
    return state


def test_doctor_cli_reports_actual_runtime_without_mutating_state(monkeypatch, tmp_path, capsys):
    _supported_distributions(monkeypatch)
    state = _configure_roots(
        monkeypatch,
        tmp_path,
        runtimes={"default": str(REPOSITORY_ROOT)},
    )

    exit_code = main(["doctor"])
    captured = capsys.readouterr()
    report = json.loads(captured.out)

    assert exit_code == 0, report["issues"]
    assert captured.err == ""
    assert report["schema_version"] == "backtrader-mcp-doctor-v1"
    assert report["status"] == "passed"
    assert report["product"]["dependencies"]["mcp"]["version"] == "2.0.0"
    runtime = report["runtimes"][0]
    assert runtime["runtime_id"] == "default"
    assert runtime["version"] == "1.3.0"
    assert runtime["origin_matches_runtime"] is True
    assert Path(runtime["module_file"]).is_relative_to(REPOSITORY_ROOT / "backtrader")
    assert runtime["capabilities"] == {
        "cerebro": True,
        "generic_csv": True,
        "pandas_data": True,
        "strategy": True,
    }
    assert report["capabilities"]["run_profiles"] == [
        "fixed_tests",
        "runnext",
        "runonce",
        "runonce_runnext_compare",
    ]
    assert not state.exists(), "doctor must remain read-only"


def test_doctor_cli_does_not_write_any_configured_root_or_runtime(monkeypatch, tmp_path, capsys):
    _supported_distributions(monkeypatch)
    runtime = _create_synthetic_runtime(tmp_path)
    state = _configure_roots(
        monkeypatch,
        tmp_path,
        runtimes={"default": str(runtime)},
    )
    before = _tree_snapshot(tmp_path)

    exit_code = main(["doctor"])
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 0, report["issues"]
    assert _tree_snapshot(tmp_path) == before
    assert not state.exists()
    assert not list(runtime.rglob("*.pyc"))
    assert not list(runtime.rglob("__pycache__"))


def test_doctor_cli_fails_closed_when_runtime_is_not_configured(monkeypatch, tmp_path, capsys):
    _supported_distributions(monkeypatch)
    _configure_roots(monkeypatch, tmp_path, runtimes={})

    exit_code = main(["doctor"])
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert report["status"] == "failed"
    assert any(issue["code"] == "runtimes_empty" for issue in report["issues"])


def test_doctor_cli_returns_stable_error_for_invalid_root_json(monkeypatch, capsys):
    monkeypatch.setenv("BACKTRADER_MCP_RUNTIMES", "not-json")

    exit_code = main(["doctor"])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "code": "invalid_request",
        "message": "root maps must be valid JSON objects",
    }


def test_doctor_cli_returns_stable_error_for_invalid_limit(monkeypatch, capsys):
    monkeypatch.setenv("BACKTRADER_MCP_MAX_RUN_SECONDS", "unbounded")

    exit_code = main(["doctor"])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "code": "invalid_request",
        "message": "BACKTRADER_MCP_MAX_RUN_SECONDS must be a positive integer",
    }
