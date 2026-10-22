"""Run the native Alpha003 factor over the observed daily A-share panel."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"
EXAMPLE_ID = "027_alpha003_panel_acceptance"
FACTOR_NAME = "alpha003"


def _add_checkout_root() -> None:
    """Use this checkout in-place; a copied example uses installed Backtrader."""
    for parent in SCRIPT_DIR.parents:
        if (parent / "backtrader" / "__init__.py").is_file():
            root = str(parent)
            if root not in sys.path:
                sys.path.insert(0, root)
            return


_add_checkout_root()


def _load_config(path: Path = CONFIG_PATH) -> Dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("the example requires PyYAML to read config.yaml") from exc
    with path.open("r", encoding="utf-8") as source:
        value = yaml.safe_load(source)
    if not isinstance(value, dict) or value.get("example_id") != EXAMPLE_ID:
        raise ValueError("config.yaml does not describe %s" % EXAMPLE_ID)
    return value


def _resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (SCRIPT_DIR / path).resolve()


def load_daily_panel(data_config: Mapping[str, Any]) -> Dict[str, Any]:
    """Load the observed daily CSV panel and its shared session grid."""
    import pandas as pd

    directory = data_config.get("directory")
    if not isinstance(directory, str) or not directory:
        raise FileNotFoundError("daily data directory not found: %s" % directory)
    root = _resolve_path(directory)
    manifest_path = root / "_metadata" / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("daily data directory not found: %s" % root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = list(manifest["output"]["symbols"])

    limit = data_config.get("max_symbols", 0)
    if type(limit) is not int or limit < 0:
        raise ValueError("max_symbols must be a non-negative integer")
    if limit and limit < len(entries):
        step = len(entries) / float(limit)
        entries = [entries[int(index * step)] for index in range(limit)]

    calendar = pd.read_csv(root / "_metadata" / "observed_calendar.csv")
    if calendar.empty:
        raise ValueError("observed_calendar.csv is empty")
    timezone_name = data_config["source_timezone"]
    open_times = (
        pd.DatetimeIndex(pd.to_datetime(calendar["first_trade_time"]))
        .tz_localize(timezone_name)
        .tz_convert("UTC")
    )
    close_times = (
        pd.DatetimeIndex(pd.to_datetime(calendar["last_trade_time"]))
        .tz_localize(timezone_name)
        .tz_convert("UTC")
    )
    grid = pd.DataFrame(
        {"open_time": open_times},
        index=pd.DatetimeIndex(close_times, name="close_time"),
    )

    feeds = {}
    assets = []
    for entry in entries:
        frame = pd.read_csv(root / entry["file"], dtype={"trade_date": "string"})
        if frame.empty:
            continue
        symbol = entry["symbol"]
        frame.index = pd.DatetimeIndex(pd.to_datetime(frame["trade_time"]), name="close_time")
        feeds[symbol] = frame.loc[:, ["open", "high", "low", "close", "volume"]].astype("float64")
        assets.append(symbol)
    return {
        "grid": grid,
        "assets": tuple(assets),
        "feeds": feeds,
        "research_start_position": 0,
        "research_end_position": len(grid) - 1,
    }


def _run_factor(config: Mapping[str, Any], panel: Mapping[str, Any]) -> Tuple[Any, Any, Any]:
    import backtrader as bt
    from backtrader.research import (
        FactorSpec,
        FactorStrategy,
        MemorySink,
        ResearchSpec,
        align_to_grid,
    )
    from backtrader.research.alpha101 import get_alpha

    data_config = config["data"]
    grid = panel["grid"]
    first = panel["research_start_position"]
    last = panel["research_end_position"]
    assets = panel["assets"]
    research = ResearchSpec(
        grid=grid,
        start=grid.index[first],
        end=grid.index[last],
        targets=assets,
        source_timezone=data_config["source_timezone"],
        snapshot_id=data_config["snapshot_id"],
        price_basis=data_config["price_basis"],
        calendar_id=data_config["calendar_id"],
        frequency=data_config["frequency"],
        feed_time_kind="close_time",
        groups=dict.fromkeys(assets, data_config["group"]),
    )
    indicator = get_alpha(3)
    factor = FactorSpec(
        name=FACTOR_NAME,
        indicator=indicator,
        panel_line="factor",
        field_bindings={field: "feed:target:%s" % field for field in indicator.formula_fields},
    )
    cerebro = bt.Cerebro(stdstats=False)
    for asset in assets:
        aligned = align_to_grid(
            panel["feeds"][asset],
            research,
            asset,
            data_version=data_config["data_version"],
        )
        cerebro.adddata(aligned.feed, name=asset)
    cerebro.addstrategy(
        FactorStrategy, research=research, factors={FACTOR_NAME: factor}, sink=MemorySink()
    )
    strategies = cerebro.run(runonce=False, preload=True)
    if len(strategies) != 1:
        raise RuntimeError("the factor run did not return exactly one strategy")
    return strategies[0], strategies[0].get_panel(), indicator


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Exit codes: 0 means factor_values.csv and summary.json were written; "
            "2 means invalid or missing input; 3 means an output I/O failure."
        ),
    )
    parser.add_argument(
        "--output-dir", required=True, help="new output directory; relative to this script"
    )
    parser.add_argument("--data-dir", help="daily data directory; overrides config.yaml")
    parser.add_argument(
        "--max-symbols",
        type=int,
        help="evenly sampled symbol count; 0 uses every symbol in the manifest",
    )
    parser.add_argument(
        "--report", action="store_true", help="write a bilingual HTML factor report"
    )
    parser.add_argument(
        "--report-language", choices=("zh", "en"), default="zh", help="default report language"
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    started = time.perf_counter()
    try:
        config = _load_config()
        if config.get("factor") != FACTOR_NAME or config.get("operator_profile") != "alpha101-v2":
            raise ValueError("this example fixes factor=alpha003 and operator_profile=alpha101-v2")
        if args.data_dir:
            config["data"]["directory"] = args.data_dir
        if args.max_symbols is not None:
            config["data"]["max_symbols"] = args.max_symbols
        output_dir = _resolve_path(args.output_dir)
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir()
    except (ImportError, RuntimeError) as exc:
        print("BLOCKED: %s" % exc, file=sys.stderr)
        return 2
    except OSError as exc:
        print("OUTPUT_ERROR: %s" % exc, file=sys.stderr)
        return 3
    except (TypeError, ValueError) as exc:
        print("INVALID_INPUT: %s" % exc, file=sys.stderr)
        return 2

    try:
        panel = load_daily_panel(config.get("data", {}))
        _, collected, indicator = _run_factor(config, panel)
        factors = collected.factors.reset_index()
        factors.to_csv(output_dir / "factor_values.csv", index=False)
        report = None
        if args.report:
            from backtrader.research import write_factor_report

            try:
                report = write_factor_report(
                    collected,
                    FACTOR_NAME,
                    output_dir / ("factor_report_%s.html" % FACTOR_NAME),
                    language=args.report_language,
                    title="027 alpha003 · full-market daily",
                )
                print("REPORT: %s" % report)
            except Exception as exc:
                print("REPORT SKIPPED: %s" % exc, file=sys.stderr)
        summary = {
            "status": "COMPLETED",
            "factor": FACTOR_NAME,
            "operator_profile": indicator.operator_profile,
            "indicator": indicator.__module__ + "." + indicator.__qualname__,
            "symbols": len(collected.target_order),
            "dates": len(collected.grid),
            "cells": len(factors),
            "finite": int(factors[FACTOR_NAME].notna().sum()),
            "output": "factor_values.csv",
            "report": None if report is None else str(report),
            "elapsed_seconds": round(time.perf_counter() - started, 2),
        }
        (output_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(
            "%s: COMPLETED (%d symbols x %d dates)"
            % (EXAMPLE_ID, summary["symbols"], summary["dates"])
        )
        return 0
    except FileNotFoundError as exc:
        print("BLOCKED: %s" % exc, file=sys.stderr)
        return 2
    except ImportError as exc:
        print("BLOCKED: %s" % exc, file=sys.stderr)
        return 2
    except OSError as exc:
        print("OUTPUT_ERROR: %s" % exc, file=sys.stderr)
        return 3
    except (TypeError, ValueError) as exc:
        print("INVALID_INPUT: %s" % exc, file=sys.stderr)
        return 2
    except Exception as exc:
        print("FAILED: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
