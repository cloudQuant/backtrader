#!/usr/bin/env python
"""Offline guard-equivalence witnesses and paired synthetic CloseMA measurements."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import inspect
import io
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time
import types

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
CONDA = "/Users/yunjinqi/opt/anaconda3/bin/conda"
SANDBOX = "/usr/bin/sandbox-exec"
FACTOR_PATH = ROOT / "examples/backtest/025_factor_single/close_ma_factor_strategy.py"
CURRENT_PATH = ROOT / "backtrader/strategies/factor_strategy.py"
GUARD_TEST = ROOT / "tests/unit/test_iter61_factor_graph_core.py"
EXPECTED_A = "46057a1f18db3d146e81e07f7f12ff59bef661cbb1e88490614e867607855674"
EXPECTED_B = "12a97c793bbf312c47ed41701c4707cffd2a39cc3fde083525440d184a83cdda"
ORDER = ("A", "B", "B", "A", "A", "B")
GUARD_NAMES = (
    "test_cross_strategy_alias_of_factor_child_cannot_publish",
    "test_ordinary_strategy_cannot_schedule_a_factor_child",
    "test_removed_factor_rejects_before_sink_publication",
    "test_removed_nested_factor_cannot_publish",
    "test_removed_factor_below_ordinary_indicator_cannot_publish",
    "test_removed_sma_cannot_publish",
    "test_added_sma_cannot_publish",
    "test_added_nested_factor_cannot_publish",
    "test_duplicate_scheduling_edge_cannot_publish",
    "test_custom_sink_failure_is_preserved_and_closed",
    "test_last_bar_failure_does_not_finalize_sink",
)
GUARD_COUNTS = (4, 2, 2, 2, 2, 2, 2, 4, 4, 1, 9)
# Deny every network operation and common private configuration paths, while allowing
# the conda runtime and local git object database to be read.
PROFILE = r"""(version 1)
(allow default)
(deny network*)
(deny file-read* (regex #"(^|/)(\.env([^/]*)?|config\.yaml)$"))
"""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def source_fingerprint(snapshot):
    paths = sorted((ROOT / "backtrader").rglob("*.py")) + [FACTOR_PATH, SCRIPT, GUARD_TEST]
    entries = {str(path.relative_to(ROOT)): digest(path.read_bytes()) for path in paths}
    entries["snapshot"] = digest(snapshot.read_bytes()) if snapshot.is_file() else "MISSING"
    aggregate = digest(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode())
    return {"sha256": aggregate, "files": entries}


def _load_strategy(arm, snapshot):
    import backtrader.strategies.factor_strategy as current

    if arm == "A":
        source = snapshot.read_bytes()
        if digest(source) != EXPECTED_A:
            raise RuntimeError("snapshot SHA-256 differs from preregistered A")
        module = types.ModuleType("backtrader.strategies._iter61_guard_snapshot")
        module.__package__ = "backtrader.strategies"
        sys.modules[module.__name__] = module
        exec(compile(source, str(snapshot), "exec"), module.__dict__)
        return module.FactorStrategy, str(snapshot), digest(source)
    strategy = current.FactorStrategy
    path = Path(inspect.getfile(strategy)).resolve()
    sha = digest(path.read_bytes())
    if path != CURRENT_PATH or sha != EXPECTED_B:
        raise RuntimeError("current strategy origin or SHA-256 differs from preregistered B")
    return strategy, str(path), sha


def _environment():
    import backtrader as bt
    import numpy as np
    import pandas as pd

    return {
        "python": sys.executable,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "backtrader": bt.__version__,
        "backtrader_origin": str(Path(bt.__file__).resolve()),
    }


def _child(arm, assets_count, days, snapshot):
    sys.path.insert(0, str(ROOT))
    import backtrader as bt
    import numpy as np
    import pandas as pd
    from backtrader.research import FactorSpec, ResearchSpec, align_to_grid

    strategy_class, strategy_origin, strategy_hash = _load_strategy(arm, snapshot)
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
        "environment": _environment(),
        "strategy_origin": strategy_origin,
        "strategy_sha256": strategy_hash,
        "script_sha256": digest(SCRIPT.read_bytes()),
        "factor_sha256": digest(FACTOR_PATH.read_bytes()),
        "sources_sha256": source_fingerprint(snapshot)["sha256"],
    }


def _guard(arm, snapshot):
    sys.path.insert(0, str(ROOT))
    import backtrader.strategies.factor_strategy as current
    import pytest

    strategy_class, origin, sha = _load_strategy(arm, snapshot)
    current.FactorStrategy = strategy_class
    collected, reports = [], []

    class Recorder:
        def pytest_collection_finish(self, session):
            collected.extend(item.nodeid for item in session.items)

        def pytest_runtest_logreport(self, report):
            reports.append((report.nodeid, report.when, report.outcome))

    options = [
        "-q",
        "--disable-warnings",
        "-p",
        "no:cacheprovider",
        "-c",
        os.devnull,
        "--rootdir",
        str(GUARD_TEST.parent),
        "--confcutdir",
        str(GUARD_TEST.parent),
    ]
    options.extend(str(GUARD_TEST) + "::" + name for name in GUARD_NAMES)
    capture = io.StringIO()
    with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(capture):
        result = int(pytest.main(options, plugins=[Recorder()]))
    counts = {
        name: sum(
            "::" + name + "[" in nodeid or nodeid.endswith("::" + name) for nodeid in collected
        )
        for name in GUARD_NAMES
    }
    passed = (
        result == 0
        and list(counts.values()) == list(GUARD_COUNTS)
        and len(reports) == 3 * len(collected)
        and all(outcome == "passed" for _, _, outcome in reports)
    )
    return {
        "arm": arm,
        "pid": os.getpid(),
        "strategy_origin": origin,
        "strategy_sha256": sha,
        "sources_sha256": source_fingerprint(snapshot)["sha256"],
        "environment": _environment(),
        "pytest_version": pytest.__version__,
        "selected": list(GUARD_NAMES),
        "counts": counts,
        "collected_nodeids": collected,
        "reports": reports,
        "pytest_exit_code": result,
        "passed": passed,
        "diagnostic": "" if passed else capture.getvalue()[-6000:],
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


def _launch(arm, assets, days, snapshot, guard=False):
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
        "--guard" if guard else "--child",
        arm,
        "--snapshot",
        str(snapshot),
        "--snapshot-sha256",
        EXPECTED_A,
        "--current-sha256",
        EXPECTED_B,
        "--assets",
        str(assets),
        "--days",
        str(days),
    ]
    env = os.environ.copy()
    env.update(
        {
            "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "BT_SKIP_PYTEST_TMP_CLEANUP": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        }
    )
    started = time.perf_counter()
    with tempfile.TemporaryFile(mode="w+t") as output, tempfile.TemporaryFile(mode="w+t") as errors:
        process = subprocess.Popen(
            command, cwd=ROOT, env=env, stdout=output, stderr=errors, text=True
        )
        peak, samples = 0, 0
        while process.poll() is None:
            peak = max(peak, _tree_rss(process.pid))
            samples += 1
            time.sleep(0.2)
        process.wait()
        output.seek(0)
        errors.seek(0)
        stdout, stderr = output.read(), errors.read()
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


def compare(runs, guards, before, after, assets, days, snapshot):
    reasons = []
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
        expected_strategy = EXPECTED_A if run["arm"] == "A" else EXPECTED_B
        if run.get("strategy_sha256") != expected_strategy:
            reasons.append("strategy source differs")
        expected_origin = str(snapshot) if run["arm"] == "A" else str(CURRENT_PATH)
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
    if [item.get("arm") for item in guards] != ["A", "B"]:
        reasons.append("missing guard witnesses")
    elif any(
        item.get("exit_code") != 0
        or not item.get("passed")
        or item.get("sources_sha256") != before["sha256"]
        or item.get("source_before_sha256") != before["sha256"]
        or item.get("source_after_sha256") != before["sha256"]
        or item.get("strategy_sha256") != (EXPECTED_A if item["arm"] == "A" else EXPECTED_B)
        or item.get("strategy_origin")
        != (str(snapshot) if item["arm"] == "A" else str(CURRENT_PATH))
        or (valid and item.get("environment") != valid[0]["environment"])
        for item in guards
    ):
        reasons.append("guard witnesses failed or their sources/environment differ")
    elif (
        guards[0]["collected_nodeids"] != guards[1]["collected_nodeids"]
        or guards[0]["pytest_version"] != guards[1]["pytest_version"]
    ):
        reasons.append("guard witness selections or pytest versions differ")
    if reasons:
        return {"status": "NOT_COMPARABLE", "reasons": sorted(set(reasons)), "pairs": []}
    pairs = []
    for first, second in zip(runs[::2], runs[1::2]):
        a, b = (first, second) if first["arm"] == "A" else (second, first)
        pairs.append(
            {
                "order": first["arm"] + second["arm"],
                "wall_b_over_a": b["wall_s"] / a["wall_s"],
                "cpu_b_over_a": b["cpu_s"] / a["cpu_s"],
                "rss_b_over_a": b["tree_peak_rss_bytes"] / a["tree_peak_rss_bytes"],
            }
        )
    return {
        "status": "COMPARABLE",
        "reasons": [],
        "pairs": pairs,
        "median_b_over_a": {
            metric: statistics.median(pair[metric + "_b_over_a"] for pair in pairs)
            for metric in ("wall", "cpu", "rss")
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=int, default=500)
    parser.add_argument("--days", type=int, default=243)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--child", choices=("A", "B"), help=argparse.SUPPRESS)
    parser.add_argument("--guard", choices=("A", "B"), help=argparse.SUPPRESS)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--snapshot-sha256", required=True)
    parser.add_argument("--current-sha256", required=True)
    args = parser.parse_args()
    snapshot = args.snapshot.resolve()
    if args.snapshot_sha256 != EXPECTED_A or args.current_sha256 != EXPECTED_B:
        parser.error("supplied preregistered SHA-256 values do not match this benchmark")
    if not snapshot.is_file() or digest(snapshot.read_bytes()) != EXPECTED_A:
        parser.error("snapshot is missing or its SHA-256 does not match preregistered A")
    if not CURRENT_PATH.is_file() or digest(CURRENT_PATH.read_bytes()) != EXPECTED_B:
        parser.error("current strategy is missing or its SHA-256 does not match preregistered B")
    if args.assets < 1 or args.days < 20:
        parser.error("assets must be positive and days must be at least 20")
    if args.guard:
        print(json.dumps(_guard(args.guard, snapshot), sort_keys=True, allow_nan=False))
        return 0
    if args.child:
        print(
            json.dumps(
                _child(args.child, args.assets, args.days, snapshot),
                sort_keys=True,
                allow_nan=False,
            )
        )
        return 0
    if args.output_dir is None:
        parser.error("--output-dir is required and must not already exist")
    if not Path(CONDA).is_file() or not Path(SANDBOX).is_file():
        parser.error("the specified conda base and macOS sandbox-exec are required")
    args.output_dir.mkdir(parents=False, exist_ok=False)
    before = source_fingerprint(snapshot)
    guards = []
    for arm in ("A", "B"):
        guard_before = source_fingerprint(snapshot)["sha256"]
        guard = _launch(arm, args.assets, args.days, snapshot, guard=True)
        guard["source_before_sha256"] = guard_before
        guard["source_after_sha256"] = source_fingerprint(snapshot)["sha256"]
        guards.append(guard)
    runs = []
    for arm in ORDER:
        run_before = source_fingerprint(snapshot)["sha256"]
        run = _launch(arm, args.assets, args.days, snapshot)
        run["source_before_sha256"] = run_before
        run["source_after_sha256"] = source_fingerprint(snapshot)["sha256"]
        runs.append(run)
    after = source_fingerprint(snapshot)
    result = {
        "schema": "iter61-graph-guard-paired-v1",
        "order": list(ORDER),
        "assets": args.assets,
        "days": args.days,
        "rss_method": "maximum sampled sum of launcher and descendant RSS, ps at approximately 0.2 s; shared pages may be counted more than once",
        "timing_method": "child process_time and perf_counter around feed construction and Cerebro run; output digest excluded",
        "network_and_secret_guard": "sandbox-exec denies network and file reads named .env*, config.yaml",
        "validation_contract": "The listed negative guard witnesses execute independently for each arm; passing these tests is bounded evidence, not proof of every possible guard behavior.",
        "snapshot": str(snapshot),
        "expected_a_sha256": EXPECTED_A,
        "expected_b_sha256": EXPECTED_B,
        "source_before": before,
        "source_after": after,
        "runs": runs,
        "guards": guards,
        "comparison": compare(runs, guards, before, after, args.assets, args.days, snapshot),
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
