"""Offline self-tests for the graph-guard paired benchmark."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/benchmark_iter61_graph_guard.py"
spec = importlib.util.spec_from_file_location("iter61_guard_benchmark", SCRIPT)
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def test_comparison_requires_both_guard_witnesses():
    snapshot = Path("/synthetic/strategy.py")
    sources = {"sha256": "source"}
    runs = []
    for pid, arm in enumerate(bench.ORDER, 1):
        runs.append(
            {
                "arm": arm,
                "pid": pid,
                "exit_code": 0,
                "sources_sha256": "source",
                "source_before_sha256": "source",
                "source_after_sha256": "source",
                "strategy_sha256": bench.EXPECTED_A if arm == "A" else bench.EXPECTED_B,
                "strategy_origin": str(snapshot) if arm == "A" else str(bench.CURRENT_PATH),
                "effective_runonce": True,
                "effective_preload": True,
                "output": {
                    "rows": 40,
                    "finite_count": 1,
                    "infinite_count": 0,
                    "values_sha256": "value",
                    "index_sha256": "key",
                    "nan_mask_sha256": "mask",
                },
                "coverage": [{"coverage_matches": True}],
                "tree_peak_rss_bytes": 100,
                "wall_s": 2.0,
                "cpu_s": 1.0,
                "environment": {"backtrader_origin": str(ROOT / "backtrader/__init__.py")},
            }
        )
    guards = []
    for arm in ("A", "B"):
        guards.append(
            {
                "arm": arm,
                "exit_code": 0,
                "passed": True,
                "sources_sha256": "source",
                "source_before_sha256": "source",
                "source_after_sha256": "source",
                "strategy_sha256": bench.EXPECTED_A if arm == "A" else bench.EXPECTED_B,
                "strategy_origin": str(snapshot) if arm == "A" else str(bench.CURRENT_PATH),
                "environment": runs[0]["environment"],
                "collected_nodeids": ["test"],
                "pytest_version": "1",
            }
        )
    assert bench.compare(runs, guards, sources, sources, 2, 20, snapshot)["status"] == "COMPARABLE"
    guards[0]["passed"] = False
    assert (
        bench.compare(runs, guards, sources, sources, 2, 20, snapshot)["status"] == "NOT_COMPARABLE"
    )
    guards[0]["passed"] = True
    for field in ("values_sha256", "index_sha256", "nan_mask_sha256"):
        value = runs[0]["output"][field]
        runs[0]["output"][field] = "different"
        result = bench.compare(runs, guards, sources, sources, 2, 20, snapshot)
        assert result["status"] == "NOT_COMPARABLE" and not result["pairs"]
        runs[0]["output"][field] = value
    runs[0]["source_before_sha256"] = "different"
    assert (
        bench.compare(runs, guards, sources, sources, 2, 20, snapshot)["status"] == "NOT_COMPARABLE"
    )


def test_missing_or_wrong_snapshot_is_rejected(tmp_path):
    output = tmp_path / "must-not-exist"
    base = [
        bench.CONDA,
        "run",
        "-n",
        "base",
        "python",
        str(SCRIPT),
        "--assets",
        "3",
        "--days",
        "24",
        "--output-dir",
        str(output),
        "--snapshot-sha256",
        bench.EXPECTED_A,
        "--current-sha256",
        bench.EXPECTED_B,
    ]
    for snapshot in (tmp_path / "missing.py", tmp_path / "wrong.py"):
        if snapshot.name == "wrong.py":
            snapshot.write_text("synthetic", encoding="utf-8")
        result = subprocess.run(
            base + ["--snapshot", str(snapshot)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode != 0 and "snapshot is missing or its SHA-256" in result.stderr
        assert not output.exists()


@pytest.mark.skipif(
    not os.environ.get("ITER61_GUARD_SNAPSHOT"), reason="frozen snapshot not supplied"
)
def test_small_paired_measurement_and_guard_witnesses(tmp_path):
    snapshot = Path(os.environ["ITER61_GUARD_SNAPSHOT"]).resolve()
    output = tmp_path / "new-report"
    command = [
        bench.CONDA,
        "run",
        "-n",
        "base",
        "python",
        str(SCRIPT),
        "--assets",
        "3",
        "--days",
        "24",
        "--output-dir",
        str(output),
        "--snapshot",
        str(snapshot),
        "--snapshot-sha256",
        bench.EXPECTED_A,
        "--current-sha256",
        bench.EXPECTED_B,
    ]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=240)
    assert result.returncode in (0, 2), result.stderr
    report_path = output / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert [run["arm"] for run in report["runs"]] == list(bench.ORDER)
    assert all(run["exit_code"] == 0 for run in report["runs"]), report["runs"]
    assert len({run["pid"] for run in report["runs"]}) == 6
    assert [guard["arm"] for guard in report["guards"]] == ["A", "B"]
    assert all(guard["passed"] for guard in report["guards"]), report["guards"]
    assert all(
        sum(guard["counts"].values()) == sum(bench.GUARD_COUNTS) for guard in report["guards"]
    )
    assert report["comparison"]["status"] == "COMPARABLE", report["comparison"]
    assert len(report["comparison"]["pairs"]) == 3
    original = report_path.read_bytes()
    retry = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert retry.returncode != 0 and report_path.read_bytes() == original
