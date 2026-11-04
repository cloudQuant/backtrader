"""Small offline checks of the Iteration 61 paired benchmark runner."""

import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/benchmark_iter61_factor.py"
spec = importlib.util.spec_from_file_location("iter61_factor_benchmark", SCRIPT)
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def test_refuses_mismatching_outputs_and_sources():
    files = {
        "git:" + bench.REVISION + ":" + bench.LEGACY_PATH: "a",
        str(bench.CURRENT_PATH.relative_to(ROOT)): "b",
    }
    before = {"sha256": "common", "files": files}
    runs = []
    for pid, arm in enumerate(bench.ORDER, start=1):
        runs.append(
            {
                "arm": arm,
                "pid": pid,
                "exit_code": 0,
                "sources_sha256": "common",
                "source_before_sha256": "common",
                "source_after_sha256": "common",
                "strategy_sha256": "a" if arm == "A" else "b",
                "strategy_origin": (
                    "git:" + bench.REVISION + ":" + bench.LEGACY_PATH
                    if arm == "A"
                    else str(bench.CURRENT_PATH)
                ),
                "effective_runonce": True,
                "effective_preload": True,
                "output": {
                    "rows": 40,
                    "infinite_count": 0,
                    "finite_count": 2,
                    "values_sha256": "values",
                    "index_sha256": "index",
                    "nan_mask_sha256": "mask",
                },
                "environment": {"backtrader_origin": str(ROOT / "backtrader/__init__.py")},
                "coverage": [{"coverage_matches": True}],
                "tree_peak_rss_bytes": 100,
                "wall_s": 2.0,
                "cpu_s": 1.0,
            }
        )
    baseline = bench.compare(runs, before, before, 2, 20)
    assert baseline["status"] == "NOT_COMPARABLE"
    assert baseline["reasons"] == [bench.VALIDATION_DIFFERENCE] and not baseline["pairs"]
    for field in ("values_sha256", "index_sha256", "nan_mask_sha256"):
        old = runs[1]["output"][field]
        runs[1]["output"][field] = "different"
        result = bench.compare(runs, before, before, 2, 20)
        assert result["status"] == "NOT_COMPARABLE" and not result["pairs"]
        assert "output keys, values, or NaN masks differ" in result["reasons"]
        runs[1]["output"][field] = old
    runs[2]["source_before_sha256"] = "changed"
    assert (
        "source fingerprint changed around a child run"
        in bench.compare(runs, before, before, 2, 20)["reasons"]
    )


@pytest.mark.skipif(not Path(bench.SANDBOX).exists(), reason="macOS sandbox-exec unavailable")
def test_sandbox_denies_private_reads_and_network(tmp_path):
    private = tmp_path / "config.yaml"
    private.write_text("synthetic test only", encoding="utf-8")
    dotenv = tmp_path / ".env.test"
    dotenv.write_text("synthetic test only", encoding="utf-8")
    code = (
        "import socket,sys\n"
        "for path in sys.argv[1:]:\n"
        " try:\n  open(path).read(); raise SystemExit('private read allowed')\n"
        " except PermissionError: pass\n"
        "s=socket.socket()\n"
        "try:\n s.connect(('127.0.0.1', 9)); raise SystemExit('network allowed')\n"
        "except PermissionError: pass\n"
    )
    result = subprocess.run(
        [
            bench.SANDBOX,
            "-p",
            bench.PROFILE,
            bench.CONDA,
            "run",
            "-n",
            "base",
            "python",
            "-c",
            code,
            str(private),
            str(dotenv),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not Path(bench.SANDBOX).exists(), reason="macOS sandbox-exec unavailable")
def test_small_serial_runs_and_existing_output_refusal(tmp_path):
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
    ]
    run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert run.returncode == 2, run.stderr
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert [item["arm"] for item in report["runs"]] == list(bench.ORDER)
    assert all(item["exit_code"] == 0 for item in report["runs"]), report["runs"]
    assert len({item["pid"] for item in report["runs"]}) == 6
    assert all(item["rss_samples"] > 0 for item in report["runs"])
    assert report["comparison"]["status"] == "NOT_COMPARABLE"
    assert bench.VALIDATION_DIFFERENCE in report["comparison"]["reasons"]
    assert not report["comparison"]["pairs"]
    assert report["validation_contract"]["difference"] == bench.VALIDATION_DIFFERENCE
    original = (output / "report.json").read_bytes()
    retry = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert retry.returncode != 0
    assert (output / "report.json").read_bytes() == original
