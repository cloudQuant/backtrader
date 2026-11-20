"""Regression coverage for the strategy-duration refresh runner."""

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "refresh_strategy_durations.py"
SPEC = importlib.util.spec_from_file_location("refresh_strategy_durations", SCRIPT)
REFRESH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REFRESH)
CONFTEST_SPEC = importlib.util.spec_from_file_location(
    "repo_root_conftest", ROOT / "conftest.py"
)
PYTEST_CONFIG = importlib.util.module_from_spec(CONFTEST_SPEC)
CONFTEST_SPEC.loader.exec_module(PYTEST_CONFIG)
SUCCESSFUL_STRATEGY_LOG = (
    "============================= slowest durations =============================\n"
    "0.21s call     tests/functional/strategies/sample.py::test_case\n"
    "============================== 1 passed in 0.22s ==============================\n"
)


def test_makefile_uses_bounded_lower_worker_profile():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "BT_TEST_WORKERS ?= 4" in makefile
    assert "BT_TEST_TIMEOUT ?= 300" in makefile
    for target in ("test-fast", "test-strategies", "test-slow", "test-all"):
        section = makefile.split(f"{target}:", 1)[1].split("\n\n", 1)[0]
        assert "--timeout=$(BT_TEST_TIMEOUT)" in section
        assert "-n $(BT_TEST_WORKERS)" in section
    performance = makefile.split("test-performance:", 1)[1].split("\n\n", 1)[0]
    assert "--timeout=$(BT_TEST_TIMEOUT)" in performance
    assert "-n 0" in performance


@pytest.mark.parametrize("percentile", ["35", "50", "invalid", "101", "-5"])
def test_script_threshold_matches_collection_threshold(tmp_path, monkeypatch, percentile):
    data = {
        "tests/functional/strategies/a.py": 1.0,
        "tests/functional/strategies/b.py": 2.0,
        "tests/functional/strategies/c.py": 4.0,
        "tests/functional/strategies/d.py": 8.0,
        "tests/functional/strategies/e.py": 16.0,
    }
    durations_file = tmp_path / "durations.json"
    durations_file.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(PYTEST_CONFIG, "_DURATIONS_FILE", durations_file)
    monkeypatch.setenv("BT_SLOW_PERCENTILE", percentile)

    _, collection_threshold = PYTEST_CONFIG._load_slow_threshold()
    script_percentile = REFRESH.configured_percentile()
    script_threshold = REFRESH.percentile_threshold(data.values(), script_percentile)

    assert script_threshold == pytest.approx(collection_threshold)


def test_default_percentile_is_p35_and_differs_from_the_old_p50_claim(monkeypatch):
    monkeypatch.delenv("BT_SLOW_PERCENTILE", raising=False)
    durations = [1.0, 2.0, 4.0, 8.0, 16.0]

    p35 = REFRESH.percentile_threshold(durations, REFRESH.configured_percentile())
    old_p50 = REFRESH.percentile_threshold(durations, 50.0)

    assert REFRESH.configured_percentile() == 35.0
    assert p35 == pytest.approx(2.8)
    assert old_p50 == pytest.approx(4.0)
    assert p35 != old_p50


def test_refresh_defaults_match_makefile_worker_and_timeout(monkeypatch):
    monkeypatch.delenv("BT_TEST_WORKERS", raising=False)
    monkeypatch.delenv("BT_TEST_TIMEOUT", raising=False)
    cmd = REFRESH.pytest_command()

    assert "--timeout=300" in cmd
    assert cmd[cmd.index("-n") + 1] == "4"


def test_refresh_builds_makefile_profile_and_hard_wall_timeout(monkeypatch):
    monkeypatch.setenv("BT_TEST_WORKERS", "0")
    monkeypatch.setenv("BT_TEST_TIMEOUT", "120")
    captured = {}
    output = (
        "1.25s call tests/functional/strategies/sample.py::test_case\n"
        "1 passed in 1.26s\n"
    )

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, stdout=output, stderr="")

    monkeypatch.setattr(REFRESH.subprocess, "run", fake_run)
    assert REFRESH.measure() == {"tests/functional/strategies/sample.py": 1.25}
    assert "--timeout=120" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("-n") + 1] == "0"
    assert captured["timeout"] == REFRESH.PROCESS_TIMEOUT_SECONDS


def test_measure_rejects_incomplete_pytest_runs(monkeypatch):
    def failed_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd,
            1,
            stdout="1.25s call tests/functional/strategies/sample.py::test_case\n",
            stderr="failure",
        )

    monkeypatch.setattr(REFRESH, "run_pytest", failed_run)
    assert REFRESH.measure() == {}


def test_measure_catches_hard_timeout_and_preserves_existing_durations(
    monkeypatch, tmp_path
):
    durations_file = tmp_path / "durations.json"
    durations_file.write_bytes(b"previous duration snapshot")
    monkeypatch.setattr(REFRESH, "OUT", durations_file)
    monkeypatch.setattr(
        REFRESH,
        "run_pytest",
        lambda cmd: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(cmd, 0.01, output=b"partial", stderr=b"stopped")
        ),
    )
    monkeypatch.setattr(sys, "argv", [str(SCRIPT)])

    assert REFRESH.main() == 1
    assert durations_file.read_bytes() == b"previous duration snapshot"


def test_parser_accepts_actual_pytest_duration_and_summary_format():
    test_path = Path(__file__).resolve().relative_to(ROOT).as_posix()
    nodeid = test_path + "::test_run_pytest_enforces_real_child_process_timeout"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            nodeid,
            "-q",
            "--durations=0",
            "-p",
            "no:cacheprovider",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    log = (proc.stdout + proc.stderr).replace(
        test_path, "tests/functional/strategies/parser_probe.py"
    )
    assert REFRESH.parse_complete_log(log) == {
        "tests/functional/strategies/parser_probe.py": pytest.approx(
            REFRESH.parse_log(log)["tests/functional/strategies/parser_probe.py"]
        )
    }


@pytest.mark.parametrize(
    "log_text",
    [
        SUCCESSFUL_STRATEGY_LOG.split("============================== 1 passed")[0],
        SUCCESSFUL_STRATEGY_LOG.replace(
            "1 passed in 0.22s", "1 failed, 1 passed in 0.22s"
        ),
        "1 passed in 0.22s\n",
        SUCCESSFUL_STRATEGY_LOG
        + "0.02s call     tests/functional/strategies/truncated.py::test_case\n",
    ],
    ids=(
        "missing-summary",
        "failed-summary",
        "no-strategy-durations",
        "truncated-suffix-after-success",
    ),
)
def test_from_log_rejects_incomplete_or_failed_input_without_replacing_snapshot(
    tmp_path, monkeypatch, log_text
):
    durations_file = tmp_path / "durations.json"
    durations_file.write_bytes(b"previous duration snapshot")
    log_file = tmp_path / "pytest.log"
    log_file.write_text(log_text, encoding="utf-8")
    monkeypatch.setattr(REFRESH, "OUT", durations_file)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--from-log", str(log_file)])

    assert REFRESH.main() == 1
    assert durations_file.read_bytes() == b"previous duration snapshot"
    assert not list(tmp_path.glob(".test_durations.*.tmp"))


@pytest.mark.parametrize("percentile", ["nan", "inf", "-inf"])
def test_nonfinite_percentile_is_rejected_before_output_replace(
    tmp_path, monkeypatch, percentile
):
    durations_file = tmp_path / "durations.json"
    durations_file.write_bytes(b"previous duration snapshot")
    log_file = tmp_path / "pytest.log"
    log_file.write_text(SUCCESSFUL_STRATEGY_LOG, encoding="utf-8")
    monkeypatch.setattr(REFRESH, "OUT", durations_file)
    monkeypatch.setenv("BT_SLOW_PERCENTILE", percentile)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--from-log", str(log_file)])

    assert REFRESH.main() == 1
    assert durations_file.read_bytes() == b"previous duration snapshot"
    assert not list(tmp_path.glob(".test_durations.*.tmp"))


def test_from_log_replaces_durations_atomically_in_output_directory(
    tmp_path, monkeypatch
):
    durations_file = tmp_path / "durations.json"
    durations_file.write_bytes(b"previous duration snapshot")
    log_file = tmp_path / "pytest.log"
    log_file.write_text(SUCCESSFUL_STRATEGY_LOG, encoding="utf-8")
    monkeypatch.setattr(REFRESH, "OUT", durations_file)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--from-log", str(log_file)])
    real_replace = os.replace
    replaced = {}

    def checked_replace(source, destination):
        source_path = Path(source)
        destination_path = Path(destination)
        assert source_path.parent == destination_path.parent == tmp_path
        assert source_path.exists()
        replaced["source"] = source_path
        real_replace(source, destination)

    monkeypatch.setattr(REFRESH.os, "replace", checked_replace)

    assert REFRESH.main() == 0
    assert json.loads(durations_file.read_text(encoding="utf-8")) == {
        "tests/functional/strategies/sample.py": 0.21
    }
    assert "source" in replaced
    assert not replaced["source"].exists()
    assert not list(tmp_path.glob(".test_durations.*.tmp"))


def test_failed_atomic_replace_preserves_old_file_and_removes_temporary_file(
    tmp_path, monkeypatch
):
    durations_file = tmp_path / "durations.json"
    durations_file.write_bytes(b"previous duration snapshot")
    log_file = tmp_path / "pytest.log"
    log_file.write_text(SUCCESSFUL_STRATEGY_LOG, encoding="utf-8")
    monkeypatch.setattr(REFRESH, "OUT", durations_file)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--from-log", str(log_file)])

    def fail_replace(_source, _destination):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(REFRESH.os, "replace", fail_replace)

    assert REFRESH.main() == 1
    assert durations_file.read_bytes() == b"previous duration snapshot"
    assert not list(tmp_path.glob(".test_durations.*.tmp"))


def test_run_pytest_enforces_real_child_process_timeout():
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        REFRESH.run_pytest(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            timeout_seconds=0.2,
        )
    assert time.monotonic() - start < 3.0
    assert REFRESH.PROCESS_TIMEOUT_SECONDS == 7200
