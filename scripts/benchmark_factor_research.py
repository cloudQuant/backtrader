"""Stage benchmark for the native factor-research examples 025/026/027.

The harness builds the same inputs the examples use and times each stage
separately so the legacy ``prealign_bars``/``get_dataset`` path and the
lightweight panel path can be compared on one machine.  Import, capability
probes and CSV writing of the examples' own summaries are excluded on purpose;
they are reported by the examples themselves.

Usage::

    python scripts/benchmark_factor_research.py --example 025 --symbols 50 \\
        --pipeline legacy --output /tmp/bench

The JSON result records the command, environment, source hashes, per-stage
wall time, peak and resident RSS, and output shapes.  Stages that do not apply
to a pipeline are ``null`` rather than 0 so an unexecuted stage cannot be read
as a fast one.
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
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = {
    "025": REPO_ROOT / "examples" / "backtest" / "025_factor_single",
    "026": REPO_ROOT / "examples" / "backtest" / "026_factor_multi",
    "027": REPO_ROOT / "examples" / "backtest" / "027_alpha003_panel_acceptance",
}
FACTOR_NAME_027 = "alpha003"


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


def _run_legacy(
    example: str,
    config: Mapping[str, Any],
    panel: Mapping[str, Any],
    stages: Dict[str, Optional[float]],
    artifacts: Dict[str, Any],
    *,
    runnext: bool,
    write_csv: bool,
    report: bool,
) -> None:
    import backtrader as bt
    from backtrader.brokers import BackBroker
    from backtrader.research import FactorStrategy
    from backtrader.research.inputs import prealign_bars

    class CountingBroker(BackBroker):
        def __init__(self) -> None:
            super().__init__()
            self.submit_count = 0
            self.cancel_count = 0

        def submit(self, order: Any) -> Any:
            self.submit_count += 1
            return super().submit(order)

        def cancel(self, order: Any) -> Any:
            self.cancel_count += 1
            return super().cancel(order)

    research = _research_spec(example, config, panel)
    factors = _factor_specs(example, config, None)

    started = time.perf_counter()
    cerebro = bt.Cerebro(stdstats=False)
    broker = CountingBroker()
    cerebro.setbroker(broker)
    aligned = []
    for asset in panel["assets"]:
        item = prealign_bars(
            panel["feeds"][asset],
            research,
            asset,
            data_version=config["data"]["data_version"],
        )
        aligned.append(item)
        cerebro.adddata(item.feed, name=asset)
    stages["align"] = time.perf_counter() - started

    cerebro.addstrategy(FactorStrategy, research=research, factors=factors)
    started = time.perf_counter()
    strategies = cerebro.run(runonce=not runnext, preload=True)
    stages["cerebro"] = time.perf_counter() - started
    if len(strategies) != 1:
        raise RuntimeError("collection did not return exactly one strategy")

    started = time.perf_counter()
    dataset = strategies[0].get_dataset()
    stages["collect"] = time.perf_counter() - started
    artifacts["broker_orders"] = [broker.submit_count, broker.cancel_count]
    artifacts["shapes"] = {
        "factors": list(dataset.raw_factors.shape),
        "availability": list(dataset.availability.shape),
        "prices": {name: list(frame.shape) for name, frame in (dataset.prices or {}).items()},
        "universe": list(dataset.universe.shape),
        "grid": len(dataset.grid),
    }

    if write_csv:
        started = time.perf_counter()
        destination = Path(artifacts["csv_path"])
        dataset.raw_factors.reset_index().to_csv(destination, index=False)
        stages["csv"] = time.perf_counter() - started
        artifacts["csv_bytes"] = destination.stat().st_size

    if report:
        from backtrader.research import write_factor_report

        periods = tuple((config.get("evaluation") or {}).get("periods", (1, 5, 20)))
        quantiles = (config.get("evaluation") or {}).get("quantiles", 5)
        max_loss = (config.get("evaluation") or {}).get("max_loss", 1.0)
        started = time.perf_counter()
        for name in factors:
            write_factor_report(
                dataset,
                name,
                Path(artifacts["report_dir"]) / ("report_%s.html" % name),
                periods=periods,
                quantiles=quantiles,
                max_loss=max_loss,
                title="bench %s %s" % (example, name),
            )
        stages["report"] = time.perf_counter() - started


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
) -> None:
    import backtrader as bt
    from backtrader.research import FactorStrategy
    from backtrader.research.align import align_to_grid
    from backtrader.research.sink import MemorySink

    research = _research_spec(example, config, panel)
    factors = _factor_specs(example, config, None)
    sink = MemorySink()

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

    cerebro.addstrategy(FactorStrategy, research=research, factors=factors, sink=sink)
    started = time.perf_counter()
    strategies = cerebro.run(runonce=not runnext, preload=True)
    stages["cerebro"] = time.perf_counter() - started
    if len(strategies) != 1:
        raise RuntimeError("collection did not return exactly one strategy")

    started = time.perf_counter()
    factor_panel = strategies[0].get_panel()
    stages["collect"] = time.perf_counter() - started
    stages["panel"] = stages["collect"]
    artifacts["shapes"] = {
        "factors": list(factor_panel.factors.shape),
        "prices_open": list(factor_panel.prices_open.shape),
        "prices_close": list(factor_panel.prices_close.shape),
        "universe": list(factor_panel.universe.shape),
        "grid": len(factor_panel.grid),
    }

    if write_csv:
        started = time.perf_counter()
        destination = Path(artifacts["csv_dir"])
        factor_panel.to_csv(destination)
        stages["csv"] = time.perf_counter() - started
        artifacts["csv_bytes"] = sum(
            path.stat().st_size for path in destination.glob("*.csv")
        )

    if report:
        from backtrader.research import write_factor_report

        periods = tuple((config.get("evaluation") or {}).get("periods", (1, 5, 20)))
        quantiles = (config.get("evaluation") or {}).get("quantiles", 5)
        max_loss = (config.get("evaluation") or {}).get("max_loss", 1.0)
        started = time.perf_counter()
        for name in factors:
            write_factor_report(
                factor_panel,
                name,
                Path(artifacts["report_dir"]) / ("report_%s.html" % name),
                periods=periods,
                quantiles=quantiles,
                max_loss=max_loss,
                title="bench %s %s" % (example, name),
            )
        stages["report"] = time.perf_counter() - started


def _run_once(args: argparse.Namespace, example: str, output: Path, index: int) -> Dict[str, Any]:
    module = _load_module(example)
    config = dict(module._load_config())
    config["data"] = dict(config["data"])
    config["data"]["max_symbols"] = args.symbols
    if args.data_dir:
        config["data"]["directory"] = args.data_dir

    run_dir = output / ("%s-%s-%d-%d" % (example, args.pipeline, args.symbols, index))
    run_dir.mkdir(parents=True, exist_ok=True)
    artifacts: Dict[str, Any] = {
        "report_dir": str(run_dir),
        "csv_path": str(run_dir / "factor_values.csv"),
        "csv_dir": str(run_dir / "panel"),
    }
    stages: Dict[str, Optional[float]] = {
        name: None
        for name in ("read", "align", "cerebro", "collect", "panel", "csv", "report")
    }
    status = "OK"
    error = None
    runnext = bool(args.runnext or example == "027")

    process_started = time.perf_counter()
    cpu_started = time.process_time()
    try:
        started = time.perf_counter()
        panel = module.load_daily_panel(config["data"])
        stages["read"] = time.perf_counter() - started
        artifacts["symbols"] = len(panel["assets"])
        artifacts["grid_rows"] = len(panel["grid"])

        runner = _run_legacy if args.pipeline == "legacy" else _run_panel
        runner(
            example,
            config,
            panel,
            stages,
            artifacts,
            runnext=runnext,
            write_csv=args.csv,
            report=args.report,
        )
        del panel
    except BaseException as exc:  # recorded, not swallowed silently
        status = "FAILED"
        error = "%s: %s" % (type(exc).__name__, exc)
        artifacts["traceback"] = traceback.format_exc()
    wall = time.perf_counter() - process_started
    cpu = time.process_time() - cpu_started
    measured = [value for value in stages.values() if value is not None]
    return {
        "example": example,
        "pipeline": args.pipeline,
        "symbols": args.symbols,
        "repeat": index,
        "runnext": runnext,
        "report": args.report,
        "csv": args.csv,
        "status": status,
        "error": error,
        "stages_s": stages,
        "stages_total_s": sum(measured),
        "wall_s": wall,
        "cpu_s": cpu,
        "peak_rss_bytes": _peak_rss(),
        "resident_rss_bytes": _rss(),
        "artifacts": artifacts,
    }


def _run_isolated(args: argparse.Namespace, example: str, index: int) -> Dict[str, Any]:
    """Run one case in a fresh process so peak RSS belongs to that case only."""
    directory = Path(args.output) / ("%s-%s-%d-%d" % (example, args.pipeline, args.symbols, index))
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
        "--pipeline",
        args.pipeline,
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
    if args.data_dir:
        command.extend(["--data-dir", args.data_dir])
    completed = subprocess.run(command, capture_output=True, text=True)
    result_path = directory / "result.json"
    if result_path.is_file():
        result = json.loads(result_path.read_text(encoding="utf-8"))
    else:
        result = {
            "example": example,
            "pipeline": args.pipeline,
            "symbols": args.symbols,
            "repeat": index,
            "status": "HARNESS_FAILED",
            "error": "child produced no result.json",
            "stages_s": {},
            "wall_s": None,
            "cpu_s": None,
            "peak_rss_bytes": -1,
            "resident_rss_bytes": -1,
            "artifacts": {},
        }
    result["child_returncode"] = completed.returncode
    result["child_stdout_tail"] = completed.stdout[-2000:]
    result["child_stderr_tail"] = completed.stderr[-2000:]
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--example", action="append", choices=sorted(EXAMPLES), required=True)
    parser.add_argument("--symbols", type=int, default=50)
    parser.add_argument("--pipeline", choices=("legacy", "panel"), default="legacy")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--runnext", action="store_true")
    parser.add_argument("--csv", action="store_true")
    parser.add_argument("--report", action="store_true")
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
    output = Path(args.output).expanduser().resolve()
    if output.exists():
        print("output directory already exists: %s" % output, file=sys.stderr)
        return 3
    output.mkdir(parents=True)
    if args.symbols < 1:
        print("--symbols must be positive", file=sys.stderr)
        return 2

    results = []
    hashes_before = {example: _source_hashes(example) for example in args.example}
    for example in args.example:
        for index in range(args.repeat):
            if args.no_isolate or args._one:
                result = _run_once(args, example, output, index)
            else:
                result = _run_isolated(args, example, index)
            results.append(result)
            print(
                "%s %s %d#%d %s wall=%.3fs peak=%.1fMB"
                % (
                    example,
                    args.pipeline,
                    args.symbols,
                    index,
                    result["status"],
                    result["wall_s"],
                    result["peak_rss_bytes"] / (1 << 20),
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
            "pandas": __import__("pandas").__version__,
            "numpy": __import__("numpy").__version__,
            "fincore": getattr(__import__("fincore"), "__version__", None)
            if _module_exists("fincore")
            else None,
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
    (output / "benchmark.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    failures = [item for item in results if item["status"] != "OK"]
    print("results: %s" % (output / "benchmark.json"))
    return 1 if failures else 0


def _module_exists(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


if __name__ == "__main__":
    raise SystemExit(main())
