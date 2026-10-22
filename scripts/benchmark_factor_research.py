"""Stage benchmark for the native factor-research examples 025/026/027.

The harness builds the same inputs the examples use and times each stage
separately. It measures the current lightweight panel pipeline only; the
pre-refactor ``prealign_bars``/``get_dataset`` numbers are the frozen R0a
baseline recorded in ``evidence/r0a-baseline-20261022``. This staged runner is
not an end-to-end measurement of the public ``run.py`` entrypoints.

Usage::

    python scripts/benchmark_factor_research.py --example 025 --symbols 20 \\
        --evaluate --report --output /tmp/bench

The JSON result records the command, environment, source hashes, per-stage
wall time, parent-measured process-tree wall/CPU/RSS, and output shapes. Stages
that did not run are ``null`` rather than 0. Collection and panel finalization
happen inside ``cerebro.run()``; ``collect`` is recorded as included in
``cerebro`` without an additive duration. ``panel`` measures only the separate
``get_panel()`` accessor.
For paired end-to-end runs of the public examples, use
``scripts/benchmark_factor_research_pair.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import resource
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = {
    "025": REPO_ROOT / "examples" / "backtest" / "025_factor_single",
    "026": REPO_ROOT / "examples" / "backtest" / "026_factor_multi",
    "027": REPO_ROOT / "examples" / "backtest" / "027_alpha003_panel_acceptance",
}
FACTOR_NAME_027 = "alpha003"
STAGE_NAMES = (
    "read",
    "align",
    "cerebro",
    "collect",
    "panel",
    "csv",
    "csv_read",
    "report",
    "evaluate",
)


def _load_module(example: str) -> Any:
    directory = EXAMPLES[example]
    path = directory / "run.py"
    name = "_bench_example_%s" % example
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # The examples import their sibling strategy modules by plain name, which
    # only works while the script directory is importable (python run.py).
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    spec.loader.exec_module(module)
    return module


def _rss() -> int:
    try:
        import psutil

        return int(psutil.Process().memory_info().rss)
    except Exception:  # pragma: no cover - psutil is the normal source
        return -1


def _peak_rss() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes, Linux kilobytes.
    return int(value if sys.platform == "darwin" else value * 1024)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_hashes(example: str) -> Dict[str, str]:
    paths = [
        EXAMPLES[example] / "run.py",
        EXAMPLES[example] / "config.yaml",
        REPO_ROOT / "backtrader" / "research" / "__init__.py",
        REPO_ROOT / "backtrader" / "research" / "factor_strategy.py",
        REPO_ROOT / "backtrader" / "research" / "operators.py",
        REPO_ROOT / "backtrader" / "research" / "specs.py",
        REPO_ROOT / "backtrader" / "research" / "inputs.py",
        REPO_ROOT / "backtrader" / "research" / "dataset.py",
        REPO_ROOT / "backtrader" / "research" / "panel.py",
    ]
    output = {}
    for path in paths:
        if path.is_file():
            output[str(path.relative_to(REPO_ROOT))] = _hash_file(path)
    return output


def _factor_specs(example: str, config: Mapping[str, Any], module: Any) -> Dict[str, Any]:
    from backtrader.research import FactorSpec

    if example == "025":
        from close_ma_factor_strategy import CloseMAFactor

        definition = config["factor"]
        return {
            definition["name"]: FactorSpec(
                name=definition["name"],
                indicator=CloseMAFactor,
                params=dict(definition["params"]),
                panel_line=definition["panel_line"],
                direction=definition["direction"],
                field_bindings={
                    field: "feed:target:%s" % field for field in CloseMAFactor.formula_fields
                },
            )
        }
    if example == "026":
        from multi_factor_strategy import CloseMAFactor, KDJFactor, ROCFactor

        classes = {"close_ma": CloseMAFactor, "roc": ROCFactor, "kdj_j": KDJFactor}
        factors = {}
        for name, definition in config["factors"].items():
            indicator = classes[name]
            factors[name] = FactorSpec(
                name=name,
                indicator=indicator,
                params=dict(definition["params"]),
                panel_line=definition["panel_line"],
                direction=definition["direction"],
                field_bindings={
                    field: "feed:target:%s" % field for field in indicator.formula_fields
                },
            )
        return factors
    from backtrader.research.alpha101 import get_alpha

    indicator = get_alpha(int(FACTOR_NAME_027[-3:]))
    return {
        FACTOR_NAME_027: FactorSpec(
            name=FACTOR_NAME_027,
            indicator=indicator,
            panel_line="factor",
            field_bindings={field: "feed:target:%s" % field for field in indicator.formula_fields},
        )
    }


def _research_spec(example: str, config: Mapping[str, Any], panel: Mapping[str, Any]) -> Any:
    from backtrader.research import ResearchSpec

    data_config = config["data"]
    grid = panel["grid"]
    assets = panel["assets"]
    return ResearchSpec(
        grid=grid,
        start=grid.index[panel["research_start_position"]],
        end=grid.index[panel["research_end_position"]],
        targets=assets,
        source_timezone=data_config["source_timezone"],
        snapshot_id=data_config["snapshot_id"],
        price_basis=data_config["price_basis"],
        calendar_id=data_config["calendar_id"],
        frequency=data_config["frequency"],
        feed_time_kind="close_time",
        groups=dict.fromkeys(assets, data_config["group"]),
    )


def _run_panel(
    example: str,
    config: Mapping[str, Any],
    panel: Mapping[str, Any],
    stages: Dict[str, Optional[float]],
    artifacts: Dict[str, Any],
    *,
    runnext: bool,
    write_csv: bool,
    report: bool,
    evaluate: bool,
    resident: Dict[str, int],
    stage_states: Dict[str, Dict[str, Any]],
    module: Any = None,
) -> None:
    import backtrader as bt
    from backtrader.research import FactorStrategy
    from backtrader.research.align import align_to_grid
    from backtrader.research.sink import MemorySink

    research = _research_spec(example, config, panel)
    factors = _factor_specs(example, config, None)
    sink = MemorySink()

    stage_states["align"]["status"] = "RUNNING"
    started = time.perf_counter()
    cerebro = bt.Cerebro(stdstats=False)
    for asset in panel["assets"]:
        aligned = align_to_grid(
            panel["feeds"][asset],
            research,
            asset,
            data_version=config["data"]["data_version"],
        )
        cerebro.adddata(aligned.feed, name=asset)
    stages["align"] = time.perf_counter() - started
    resident["align"] = _rss()
    stage_states["align"]["status"] = "OK"

    cerebro.addstrategy(FactorStrategy, research=research, factors=factors, sink=sink)
    stage_states["collect"]["status"] = "RUNNING"
    stage_states["cerebro"]["status"] = "RUNNING"
    started = time.perf_counter()
    strategies = cerebro.run(runonce=not runnext, preload=True)
    stages["cerebro"] = time.perf_counter() - started
    stage_states["cerebro"]["status"] = "OK"
    _mark_collection_included(stage_states)
    if len(strategies) != 1:
        raise RuntimeError("collection did not return exactly one strategy")

    stage_states["panel"]["status"] = "RUNNING"
    started = time.perf_counter()
    factor_panel = strategies[0].get_panel()
    stages["panel"] = time.perf_counter() - started
    resident["panel"] = _rss()
    stage_states["panel"]["status"] = "OK"
    artifacts["shapes"] = {
        "factors": list(factor_panel.factors.shape),
        "prices_open": list(factor_panel.prices_open.shape),
        "prices_close": list(factor_panel.prices_close.shape),
        "universe": list(factor_panel.universe.shape),
        "grid": len(factor_panel.grid),
    }

    if write_csv:
        stage_states["csv"]["status"] = "RUNNING"
        stage_states["csv_read"]["status"] = "RUNNING"
        started = time.perf_counter()
        destination = Path(artifacts["csv_dir"])
        factor_panel.to_csv(destination)
        stages["csv"] = time.perf_counter() - started
        resident["csv"] = _rss()
        artifacts["csv_bytes"] = sum(
            path.stat().st_size for path in destination.glob("*.csv")
        )
        if artifacts["csv_bytes"] <= 0:
            raise RuntimeError("CSV panel output is empty")
        stage_states["csv"]["status"] = "OK"
        started = time.perf_counter()
        from backtrader.research import FactorPanel

        FactorPanel.from_csv(
            destination,
            start=factor_panel.start,
            end=factor_panel.end,
            directions=factor_panel.directions,
            target_order=factor_panel.target_order,
            factor_order=factor_panel.factor_order,
            groups=factor_panel.groups,
        )
        stages["csv_read"] = time.perf_counter() - started
        resident["csv_read"] = _rss()
        stage_states["csv_read"]["status"] = "OK"

    if report:
        from backtrader.research import write_factor_report

        periods = tuple((config.get("evaluation") or {}).get("periods", (1, 5, 20)))
        quantiles = (config.get("evaluation") or {}).get("quantiles", 5)
        max_loss = (config.get("evaluation") or {}).get("max_loss", 1.0)
        stage_states["report"]["status"] = "RUNNING"
        report_paths = []
        started = time.perf_counter()
        for name in factors:
            report_path = Path(artifacts["report_dir"]) / ("report_%s.html" % name)
            write_factor_report(
                factor_panel,
                name,
                report_path,
                periods=periods,
                quantiles=quantiles,
                max_loss=max_loss,
                title="bench %s %s" % (example, name),
            )
            if not report_path.is_file() or report_path.stat().st_size <= 0:
                raise RuntimeError("report output is missing or empty: %s" % report_path)
            report_paths.append(str(report_path))
        stages["report"] = time.perf_counter() - started
        resident["report"] = _rss()
        artifacts["reports"] = report_paths
        stage_states["report"]["status"] = "OK"

    if evaluate:
        stage_states["evaluate"]["status"] = "RUNNING"
        from backtrader.research import evaluate_frames

        periods = tuple((config.get("evaluation") or {}).get("periods", (1, 5, 20)))
        builder = getattr(module, "_evaluation_spec", None)
        if builder is None:
            raise RuntimeError("evaluation was requested but the example has no spec builder")
        started = time.perf_counter()
        spec = builder(config, factor_panel, periods)
        result = evaluate_frames(factor_panel, spec)
        stages["evaluate"] = time.perf_counter() - started
        resident["evaluate"] = _rss()
        evaluation_status = str(
            getattr(result.status, "value", result.status)
        ).upper()
        artifacts["evaluation"] = {
            "status": evaluation_status,
            "evaluation_id": result.manifest.get("evaluation_id"),
            "result_fingerprint": result.manifest.get("result_fingerprint"),
            "tables": {
                name: list(getattr(result, name).shape)
                for name in (
                    "signals",
                    "labels",
                    "ic",
                    "ic_summary",
                    "quantile_returns",
                    "turnover",
                    "spreads",
                    "stability",
                    "correlation",
                    "comparisons",
                    "coverage",
                    "diagnostics",
                )
            },
        }
        if evaluation_status != "OK":
            stage_states["evaluate"]["status"] = "FAILED"
            raise RuntimeError("evaluation status is %s, expected OK" % evaluation_status)
        stage_states["evaluate"]["status"] = "OK"


def _stage_states(args: argparse.Namespace, example: str) -> Dict[str, Dict[str, Any]]:
    requested = {
        "read": True,
        "align": True,
        "cerebro": True,
        "collect": True,
        "panel": True,
        "csv": bool(args.csv),
        "csv_read": bool(args.csv),
        "report": bool(args.report),
        "evaluate": bool(args.evaluate),
    }
    applicable = dict.fromkeys(requested, True)
    applicable["evaluate"] = example in ("025", "026")
    nested = dict.fromkeys(requested, False)
    nested["collect"] = True
    nested_in = {"collect": "cerebro"}
    states = {}
    for name in requested:
        if not applicable[name]:
            status = "NOT_APPLICABLE"
        elif not requested[name]:
            status = "NOT_REQUESTED"
        else:
            status = "NOT_RUN"
        states[name] = {
            "requested": requested[name],
            "applicable": applicable[name],
            "status": status,
            "nested": nested[name],
            "nested_in": nested_in.get(name),
        }
    return states


def _mark_collection_included(states: Dict[str, Dict[str, Any]]) -> None:
    """Record collection as part of Cerebro's timed run, without double-counting."""
    states["collect"]["status"] = "INCLUDED_IN_CEREBRO"


def _run_once(args: argparse.Namespace, example: str, output: Path, index: int) -> Dict[str, Any]:
    module = _load_module(example)
    config = dict(module._load_config())
    config["data"] = dict(config["data"])
    config["data"]["max_symbols"] = args.symbols
    if args.data_dir:
        config["data"]["directory"] = args.data_dir

    run_dir = output / ("%s-%d-%d" % (example, args.symbols, index))
    run_dir.mkdir(parents=True, exist_ok=True)
    artifacts: Dict[str, Any] = {
        "report_dir": str(run_dir),
        "csv_path": str(run_dir / "factor_values.csv"),
        "csv_dir": str(run_dir / "panel"),
    }
    stages: Dict[str, Optional[float]] = dict.fromkeys(STAGE_NAMES)
    stage_states = _stage_states(args, example)
    resident: Dict[str, int] = {}
    status = "OK"
    error = None
    runnext = bool(args.runnext or example == "027")

    process_started = time.perf_counter()
    cpu_started = time.process_time()
    try:
        stage_states["read"]["status"] = "RUNNING"
        started = time.perf_counter()
        panel = module.load_daily_panel(config["data"])
        stages["read"] = time.perf_counter() - started
        resident["read"] = _rss()
        stage_states["read"]["status"] = "OK"
        artifacts["symbols"] = len(panel["assets"])
        artifacts["grid_rows"] = len(panel["grid"])

        _run_panel(
            example,
            config,
            panel,
            stages,
            artifacts,
            runnext=runnext,
            write_csv=args.csv,
            report=args.report,
            evaluate=args.evaluate and example in ("025", "026"),
            resident=resident,
            stage_states=stage_states,
            module=module,
        )
        if example == "027":
            artifacts["evaluation"] = {"status": "NOT_APPLICABLE"}
        del panel
    except Exception as exc:  # recorded, not swallowed silently
        status = "FAILED"
        error = "%s: %s" % (type(exc).__name__, exc)
        artifacts["traceback"] = traceback.format_exc()
        for state in stage_states.values():
            if state["status"] == "RUNNING":
                state["status"] = "FAILED"
    wall = time.perf_counter() - process_started
    cpu = time.process_time() - cpu_started
    additive_stages = [
        value
        for name, value in stages.items()
        if value is not None and not stage_states[name]["nested"]
    ]
    return {
        "example": example,
        "pipeline": "panel",
        "symbols": args.symbols,
        "repeat": index,
        "runnext": runnext,
        "report": args.report,
        "csv": args.csv,
        "status": status,
        "error": error,
        "stages_s": stages,
        "stages_total_s": sum(additive_stages),
        "wall_s": wall,
        "cpu_s": cpu,
        "peak_rss_bytes": _peak_rss(),
        "resident_rss_bytes": _rss(),
        "resident_samples": resident,
        "stage_states": stage_states,
        "stage_sum_scope": "top_level_only; collect is included in cerebro and has no separate duration",
        "artifacts": artifacts,
    }


def _run_monitored(command: list, cwd: Path, interval_s: float = 0.05) -> Dict[str, Any]:
    """Measure a fresh child and its descendants from the parent process."""
    import psutil

    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stdout_file, tempfile.TemporaryFile(
        mode="w+t", encoding="utf-8"
    ) as stderr_file:
        started = time.perf_counter()
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
        )
        cpu_by_pid: Dict[int, float] = {}
        samples = []
        peak_rss = 0

        def sample() -> None:
            nonlocal peak_rss
            try:
                root = psutil.Process(process.pid)
                processes = [root] + root.children(recursive=True)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                processes = []
            rss_total = 0
            cpu_total = 0.0
            pids = []
            for item in processes:
                try:
                    memory = item.memory_info().rss
                    cpu_times = item.cpu_times()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                cpu = float(cpu_times.user + cpu_times.system)
                rss_total += int(memory)
                cpu_total += cpu
                pids.append(item.pid)
                cpu_by_pid[item.pid] = max(cpu_by_pid.get(item.pid, 0.0), cpu)
            peak_rss = max(peak_rss, rss_total)
            samples.append(
                {
                    "elapsed_s": time.perf_counter() - started,
                    "rss_tree_bytes": rss_total,
                    "cpu_tree_s": cpu_total,
                    "pids": pids,
                }
            )

        while process.poll() is None:
            sample()
            time.sleep(interval_s)
        sample()
        returncode = process.wait()
        wall_s = time.perf_counter() - started
        stdout_file.seek(0)
        stderr_file.seek(0)
        return {
            "returncode": returncode,
            "stdout": stdout_file.read(),
            "stderr": stderr_file.read(),
            "wall_s": wall_s,
            "cpu_s": sum(cpu_by_pid.values()),
            "peak_rss_tree_bytes": peak_rss,
            "samples": samples,
        }


def _run_isolated(args: argparse.Namespace, example: str, index: int) -> Dict[str, Any]:
    """Run one case in a fresh process so peak RSS belongs to that case only."""
    directory = Path(args.output) / ("%s-%d-%d" % (example, args.symbols, index))
    if directory.exists():
        raise RuntimeError("run directory already exists: %s" % directory)
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--_one",
        "--example",
        example,
        "--symbols",
        str(args.symbols),
        "--repeat",
        "1",
        "--output",
        str(directory),
    ]
    if args.runnext:
        command.append("--runnext")
    if args.csv:
        command.append("--csv")
    if args.report:
        command.append("--report")
    if args.evaluate:
        command.append("--evaluate")
    if args.data_dir:
        command.extend(["--data-dir", args.data_dir])
    try:
        measured = _run_monitored(command, REPO_ROOT)
    except Exception as exc:
        measured = {
            "returncode": None,
            "stdout": "",
            "stderr": "",
            "wall_s": None,
            "cpu_s": None,
            "peak_rss_tree_bytes": -1,
            "samples": [],
            "error": "%s: %s" % (type(exc).__name__, exc),
        }
    result_path = directory / "result.json"
    if result_path.is_file():
        result = json.loads(result_path.read_text(encoding="utf-8"))
    else:
        result = {
            "example": example,
            "pipeline": "panel",
            "symbols": args.symbols,
            "repeat": index,
            "status": "HARNESS_FAILED",
            "error": "child produced no result.json",
            "stages_s": dict.fromkeys(STAGE_NAMES),
            "stage_states": _stage_states(args, example),
            "wall_s": None,
            "cpu_s": None,
            "peak_rss_bytes": -1,
            "resident_rss_bytes": -1,
            "artifacts": {},
        }
    result["child_wall_s"] = result.get("wall_s")
    result["child_cpu_s"] = result.get("cpu_s")
    result["child_returncode"] = measured["returncode"]
    result["child_stdout_tail"] = measured["stdout"][-2000:]
    result["child_stderr_tail"] = measured["stderr"][-2000:]
    result["wall_s"] = measured["wall_s"]
    result["cpu_s"] = measured["cpu_s"]
    result["peak_rss_bytes"] = measured["peak_rss_tree_bytes"]
    result["peak_rss_tree_bytes"] = measured["peak_rss_tree_bytes"]
    result["process_samples"] = measured["samples"]
    result["measurement_scope"] = "parent process-tree sampling"
    if measured.get("error"):
        result["status"] = "HARNESS_FAILED"
        result["error"] = measured["error"]
    elif measured["returncode"] != 0 and result.get("status") == "OK":
        result["status"] = "HARNESS_FAILED"
        result["error"] = "child exited with status %d" % measured["returncode"]
    return result


def _failed_result(args: argparse.Namespace, example: str, index: int, exc: Exception) -> Dict[str, Any]:
    """Keep setup/import failures visible in non-isolated result artifacts too."""
    return {
        "example": example,
        "pipeline": "panel",
        "symbols": args.symbols,
        "repeat": index,
        "runnext": bool(args.runnext or example == "027"),
        "report": args.report,
        "csv": args.csv,
        "status": "FAILED",
        "error": "%s: %s" % (type(exc).__name__, exc),
        "traceback": traceback.format_exc(),
        "stages_s": dict.fromkeys(STAGE_NAMES),
        "stages_total_s": 0,
        "stage_states": _stage_states(args, example),
        "stage_sum_scope": "top_level_only; collect is included in cerebro and has no separate duration",
        "wall_s": None,
        "cpu_s": None,
        "peak_rss_bytes": -1,
        "resident_rss_bytes": -1,
        "resident_samples": {},
        "artifacts": {},
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--example", action="append", choices=sorted(EXAMPLES), required=True)
    parser.add_argument("--symbols", type=int, default=50)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--runnext", action="store_true")
    parser.add_argument("--csv", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--evaluate", action="store_true")
    parser.add_argument("--data-dir")
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--no-isolate",
        action="store_true",
        help="run every case in this process (peak RSS then only bounds all cases)",
    )
    parser.add_argument("--_one", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: Optional[list] = None) -> int:
    args = _parser().parse_args(argv)
    if args.symbols < 1 or args.repeat < 1:
        print("--symbols and --repeat must be positive", file=sys.stderr)
        return 2
    if not args.no_isolate and not args._one:
        try:
            import psutil  # noqa: F401
        except ImportError:
            print("psutil is required for parent process-tree measurements", file=sys.stderr)
            return 2
    output = Path(args.output).expanduser().resolve()
    if output.exists():
        print("output directory already exists: %s" % output, file=sys.stderr)
        return 3
    output.mkdir(parents=True)
    results = []
    hashes_before = {example: _source_hashes(example) for example in args.example}
    for example in args.example:
        for index in range(args.repeat):
            try:
                if args.no_isolate or args._one:
                    result = _run_once(args, example, output, index)
                else:
                    result = _run_isolated(args, example, index)
            except Exception as exc:
                result = _failed_result(args, example, index, exc)
            results.append(result)
            print(
                "%s %s %d#%d %s wall=%s peak=%s"
                % (
                    example,
                    "panel",
                    args.symbols,
                    index,
                    result["status"],
                    "%.3fs" % result["wall_s"] if result["wall_s"] is not None else "n/a",
                    "%.1fMB" % (result["peak_rss_bytes"] / (1 << 20))
                    if result["peak_rss_bytes"] >= 0
                    else "n/a",
                ),
                flush=True,
            )
            if args._one:
                (output / "result.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                return 0 if result["status"] == "OK" else 1
    hashes_after = {example: _source_hashes(example) for example in args.example}
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT), capture_output=True, text=True
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", "backtrader/research"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        ).stdout.strip()
    except OSError:
        head, status = "", ""
    payload = {
        "command": sys.argv,
        "metadata": {
            "cwd": os.getcwd(),
            "head": head,
            "research_status": status,
            "python": sys.version,
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "pandas": _module_version("pandas"),
            "numpy": _module_version("numpy"),
            "fincore": _module_version("fincore") if _module_exists("fincore") else None,
            "hashes_before": hashes_before,
            "hashes_after": hashes_after,
            "hash_drift": {
                example: {
                    path: [value, hashes_after[example].get(path)]
                    for path, value in hashes_before[example].items()
                    if hashes_after[example].get(path) != value
                }
                for example in args.example
            },
        },
        "results": results,
    }
    if args.no_isolate or args._one:
        payload["measurement_scope"] = "current process only; parent process-tree metrics unavailable"
        for result in results:
            result["measurement_scope"] = payload["measurement_scope"]
    (output / "benchmark.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    failures = [item for item in results if item["status"] != "OK"]
    print("results: %s" % (output / "benchmark.json"))
    return 1 if failures else 0


def _module_exists(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _module_version(name: str) -> Optional[str]:
    try:
        module = __import__(name)
    except Exception:
        return None
    value = getattr(module, "__version__", None)
    return None if value is None else str(value)


if __name__ == "__main__":
    raise SystemExit(main())
