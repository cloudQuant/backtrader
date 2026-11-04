#!/usr/bin/env python
"""Offline paired Iteration 61 CloseMA benchmark; results are local evidence only."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
CONDA = "/Users/yunjinqi/opt/anaconda3/bin/conda"
SANDBOX = "/usr/bin/sandbox-exec"
REVISION = "81a697e9f"
LEGACY_PATH = "backtrader/research/factor_strategy.py"
FACTOR_PATH = ROOT / "examples/backtest/025_factor_single/close_ma_factor_strategy.py"
CURRENT_PATH = ROOT / "backtrader/strategies/factor_strategy.py"
ORDER = ("A", "B", "B", "A", "A", "B")
VALIDATION_DIFFERENCE = (
    "A uses the historical strategy; B has additional full-graph and cross-strategy guards. "
    "Their validation strength differs, so formal performance comparison is invalid."
)
# Deny every network operation and common private configuration paths, while allowing
# the conda runtime and local git object database to be read.
PROFILE = r"""(version 1)
(allow default)
(deny network*)
(deny file-read* (regex #"(^|/)(\.env([^/]*)?|config\.yaml)$"))
"""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def legacy_source():
    return subprocess.run(
        ["git", "show", REVISION + ":" + LEGACY_PATH],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def source_fingerprint():
    paths = sorted((ROOT / "backtrader").rglob("*.py")) + [FACTOR_PATH, SCRIPT]
    entries = {str(path.relative_to(ROOT)): digest(path.read_bytes()) for path in paths}
    entries["git:" + REVISION + ":" + LEGACY_PATH] = digest(legacy_source())
    aggregate = digest(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode())
    return {"sha256": aggregate, "files": entries}


def _child(arm, assets_count, days):
    sys.path.insert(0, str(ROOT))
    import backtrader as bt
    import numpy as np
    import pandas as pd
    from backtrader.research import FactorSpec, ResearchSpec, align_to_grid

    if arm == "A":
        source = legacy_source()
        module = types.ModuleType("backtrader.research._iter61_perf_legacy")
        module.__package__ = "backtrader.research"
        sys.modules[module.__name__] = module
        exec(compile(source, "<" + REVISION + ":" + LEGACY_PATH + ">", "exec"), module.__dict__)
        strategy_class = module.FactorStrategy
        strategy_origin = "git:" + REVISION + ":" + LEGACY_PATH
        strategy_hash = digest(source)
    else:
        from backtrader.strategies.factor_strategy import FactorStrategy

        strategy_class = FactorStrategy
        strategy_origin = str(Path(inspect.getfile(strategy_class)).resolve())
        strategy_hash = digest(Path(strategy_origin).read_bytes())
    spec = importlib.util.spec_from_file_location("iter61_perf_close_ma", FACTOR_PATH)
    factor_module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = factor_module
    spec.loader.exec_module(factor_module)
    times = pd.date_range("2025-01-01 16:00", periods=days, freq="D", tz="UTC", name="close_time")
    assets = tuple("asset-%04d" % i for i in range(assets_count))
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": times - pd.Timedelta(hours=6)}, index=times),
        start=times[0],
        end=times[-1],
        targets=assets,
        groups=dict.fromkeys(assets, "market"),
        source_timezone="UTC",
        snapshot_id="iter61-perf-synthetic-v1",
        price_basis="synthetic",
        calendar_id="synthetic",
        frequency="1day",
        feed_time_kind="close_time",
    )
    numbers = np.arange(days, dtype=float)
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    cerebro = bt.Cerebro(stdstats=False)
    for i, asset in enumerate(assets):
        close = 10.0 + ((numbers * (i % 7 + 2) + i) % 37) / 10
        frame = pd.DataFrame(
            {
                "open": close,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": 1000 + numbers,
            },
            index=times,
        )
        cerebro.adddata(align_to_grid(frame, research, asset).feed, name=asset)
    factor = FactorSpec(
        name="close_ma",
        indicator=factor_module.CloseMAFactor,
        panel_line="factor",
        params={"period": 20},
        field_bindings={"close": "feed:target:close"},
        mode="native",
    )
    cerebro.addstrategy(strategy_class, research=research, factors={"close_ma": factor})
    strategy = cerebro.run(runonce=True, preload=True)[0]
    wall, cpu = time.perf_counter() - start_wall, time.process_time() - start_cpu
    panel = strategy.get_panel().factors
    values = panel.to_numpy(dtype=np.float64)
    mask = np.isnan(values)
    canonical = np.where(mask, 0.0, values).astype("<f8", copy=False)
    diagnostics = [
        item.lifecycle_diagnostics for item in strategy._factor_instances_by_name["close_ma"]
    ]
    return {
        "arm": arm,
        "pid": os.getpid(),
        "assets": assets_count,
        "days": days,
        "effective_runonce": bool(cerebro._dorunonce),
        "effective_preload": bool(cerebro._dopreload),
        "wall_s": wall,
        "cpu_s": cpu,
        "output": {
            "rows": len(panel),
            "columns": list(panel.columns),
            "index_names": list(panel.index.names),
            "index_sha256": digest(
                pd.util.hash_pandas_object(panel.index, index=True).values.tobytes()
            ),
            "values_sha256": digest(canonical.tobytes()),
            "nan_mask_sha256": digest(mask.tobytes()),
            "nan_count": int(mask.sum()),
            "finite_count": int(np.isfinite(values).sum()),
            "infinite_count": int(np.isinf(values).sum()),
        },
        "coverage": [
            {
                key: item[key]
                for key in (
                    "grid_count",
                    "coverage_count",
                    "coverage_matches",
                    "once_count",
                    "next_count",
                )
            }
            for item in diagnostics
        ],
        "environment": {
            "python": sys.executable,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "backtrader": bt.__version__,
            "backtrader_origin": str(Path(bt.__file__).resolve()),
        },
        "strategy_origin": strategy_origin,
        "strategy_sha256": strategy_hash,
        "script_sha256": digest(SCRIPT.read_bytes()),
        "factor_sha256": digest(FACTOR_PATH.read_bytes()),
        "sources_sha256": source_fingerprint()["sha256"],
    }


def _tree_rss(root_pid):
    result = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,rss="], capture_output=True, text=True, check=True
    )
    rows = [
        tuple(map(int, line.split()))
        for line in result.stdout.splitlines()
        if len(line.split()) == 3
    ]
    descendants = {root_pid}
    while True:
        expanded = descendants | {pid for pid, ppid, _ in rows if ppid in descendants}
        if expanded == descendants:
            break
        descendants = expanded
    return sum(rss for pid, _, rss in rows if pid in descendants) * 1024


def _launch(arm, assets, days):
    command = [
        SANDBOX,
        "-p",
        PROFILE,
        CONDA,
        "run",
        "--no-capture-output",
        "-n",
        "base",
        "python",
        str(SCRIPT),
        "--child",
        arm,
        "--assets",
        str(assets),
        "--days",
        str(days),
    ]
    env = os.environ.copy()
    env.update({"PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"})
    started = time.perf_counter()
    process = subprocess.Popen(
        command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    peak, samples = 0, 0
    while process.poll() is None:
        peak = max(peak, _tree_rss(process.pid))
        samples += 1
        time.sleep(0.2)
    stdout, stderr = process.communicate()
    launch_wall = time.perf_counter() - started
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError:
        result = {"error": "child did not produce JSON"}
    result.update(
        {
            "arm": arm,
            "exit_code": process.returncode,
            "tree_peak_rss_bytes": peak,
            "rss_samples": samples,
            "launcher_wall_s": launch_wall,
        }
    )
    if process.returncode:
        result["stderr_tail"] = stderr[-4000:]
    return result


def compare(runs, before, after, assets, days):
    reasons = [VALIDATION_DIFFERENCE]
    if before["sha256"] != after["sha256"]:
        reasons.append("source fingerprint changed during benchmark")
    if len(runs) != len(ORDER) or tuple(run.get("arm") for run in runs) != ORDER:
        reasons.append("missing or unordered AB/BA/AB runs")
    valid = [run for run in runs if run.get("exit_code") == 0 and "output" in run]
    if len(valid) != len(ORDER):
        reasons.append("one or more child runs failed")
    if len({run.get("pid") for run in valid}) != len(ORDER):
        reasons.append("independent child process identities are missing or repeated")
    for run in valid:
        output = run["output"]
        if run.get("sources_sha256") != before["sha256"]:
            reasons.append("child source fingerprint differs")
        if (
            run.get("source_before_sha256") != before["sha256"]
            or run.get("source_after_sha256") != before["sha256"]
        ):
            reasons.append("source fingerprint changed around a child run")
        expected_strategy = (
            before["files"]["git:" + REVISION + ":" + LEGACY_PATH]
            if run["arm"] == "A"
            else before["files"][str(CURRENT_PATH.relative_to(ROOT))]
        )
        if run.get("strategy_sha256") != expected_strategy:
            reasons.append("strategy source differs")
        expected_origin = (
            "git:" + REVISION + ":" + LEGACY_PATH if run["arm"] == "A" else str(CURRENT_PATH)
        )
        if run.get("strategy_origin") != expected_origin:
            reasons.append("strategy origin differs")
        if run["environment"]["backtrader_origin"] != str(ROOT / "backtrader/__init__.py"):
            reasons.append("backtrader imported outside this checkout")
        if not run.get("effective_runonce") or not run.get("effective_preload"):
            reasons.append("requested engine mode was not effective")
        if (
            output["rows"] != assets * days
            or output["infinite_count"]
            or not output["finite_count"]
        ):
            reasons.append("incomplete or non-finite output")
        if not run.get("coverage") or not all(item["coverage_matches"] for item in run["coverage"]):
            reasons.append("factor coverage is incomplete")
        if run.get("tree_peak_rss_bytes", 0) <= 0:
            reasons.append("process tree RSS unavailable")
        if run.get("wall_s", 0) <= 0 or run.get("cpu_s", 0) <= 0:
            reasons.append("child timing unavailable")
    if valid and any(run["output"] != valid[0]["output"] for run in valid[1:]):
        reasons.append("output keys, values, or NaN masks differ")
    if valid and any(run["environment"] != valid[0]["environment"] for run in valid[1:]):
        reasons.append("child environments differ")
    return {"status": "NOT_COMPARABLE", "reasons": sorted(set(reasons)), "pairs": []}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=int, default=500)
    parser.add_argument("--days", type=int, default=243)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--child", choices=("A", "B"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.assets < 1 or args.days < 20:
        parser.error("assets must be positive and days must be at least 20")
    if args.child:
        print(
            json.dumps(_child(args.child, args.assets, args.days), sort_keys=True, allow_nan=False)
        )
        return 0
    if args.output_dir is None:
        parser.error("--output-dir is required and must not already exist")
    if not Path(CONDA).is_file() or not Path(SANDBOX).is_file():
        parser.error("the specified conda base and macOS sandbox-exec are required")
    args.output_dir.mkdir(parents=False, exist_ok=False)
    before = source_fingerprint()
    runs = []
    for arm in ORDER:
        run_before = source_fingerprint()["sha256"]
        run = _launch(arm, args.assets, args.days)
        run["source_before_sha256"] = run_before
        run["source_after_sha256"] = source_fingerprint()["sha256"]
        runs.append(run)
    after = source_fingerprint()
    result = {
        "schema": "iter61-closema-paired-v1",
        "order": list(ORDER),
        "assets": args.assets,
        "days": args.days,
        "rss_method": "maximum sampled sum of launcher and descendant RSS, ps at approximately 0.2 s; shared pages may be counted more than once",
        "timing_method": "child process_time and perf_counter around feed construction and Cerebro run; output digest excluded",
        "network_and_secret_guard": "sandbox-exec denies network and file reads named .env*, config.yaml",
        "validation_contract": {
            "A": "historical strategy validation",
            "B": "current strategy includes additional full-graph and cross-strategy guards",
            "difference": VALIDATION_DIFFERENCE,
        },
        "source_before": before,
        "source_after": after,
        "runs": runs,
        "comparison": compare(runs, before, after, args.assets, args.days),
        "scope": "synthetic local pairing using current shared sources; not historical Windows equivalence",
    }
    report = args.output_dir / "report.json"
    with report.open("x", encoding="utf-8") as file:
        json.dump(result, file, indent=2, sort_keys=True, allow_nan=False)
        file.write("\n")
    print(
        json.dumps(
            {
                "report": str(report.resolve()),
                "status": result["comparison"]["status"],
                "reasons": result["comparison"]["reasons"],
            }
        )
    )
    return 0 if result["comparison"]["status"] == "COMPARABLE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
