"""Run the self-contained Iteration 45 single-factor research example."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"
EXAMPLE_ID = "025_factor_single"


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
    import json

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


def _create_research_spec(config: Mapping[str, Any], panel: Mapping[str, Any]) -> Any:
    from backtrader.research import ResearchSpec

    data_config = config["data"]
    grid = panel["grid"]
    first = panel["research_start_position"]
    last = panel["research_end_position"]
    groups = dict.fromkeys(panel["assets"], data_config["group"])
    return ResearchSpec(
        grid=grid,
        start=grid.index[first],
        end=grid.index[last],
        targets=panel["assets"],
        source_timezone=data_config["source_timezone"],
        snapshot_id=data_config["snapshot_id"],
        price_basis=data_config["price_basis"],
        calendar_id=data_config["calendar_id"],
        frequency=data_config["frequency"],
        feed_time_kind="close_time",
        groups=groups,
    )


def _evaluation_spec(config: Mapping[str, Any], panel: Any, periods: Sequence[int]) -> Any:
    from fincore.factor_analysis.research import ResearchEvaluationSpec

    data_config = config["data"]
    grid = panel.grid
    research_times = grid.index[(grid.index >= panel.start) & (grid.index <= panel.end)]
    configured = config["evaluation"]
    segments = {}
    for name, definition in configured.get("segments", {}).items():
        first = definition["research_bar_start"]
        last = definition["research_bar_end"]
        if (
            type(first) is not int
            or type(last) is not int
            or not (0 <= first <= last < len(research_times))
        ):
            raise ValueError("configured segment positions must fall inside the research grid")
        segments[name] = (research_times[first], research_times[last], definition["role"])
    return ResearchEvaluationSpec(
        targets=panel.target_order,
        start=panel.start,
        end=panel.end,
        snapshot_id=data_config["snapshot_id"],
        price_basis=data_config["price_basis"],
        calendar_id=data_config["calendar_id"],
        frequency=data_config["frequency"],
        source_timezone=data_config["source_timezone"],
        feed_time_kind="close_time",
        periods=tuple(periods),
        label=configured["label"],
        precomputed_entry=configured["precomputed_entry"],
        quantiles=configured["quantiles"],
        min_assets=configured["min_assets"],
        min_quantile_assets=configured["min_quantile_assets"],
        preprocess=configured["preprocess"],
        max_loss=configured["max_loss"],
        stability_lags=tuple(configured["stability_lags"]),
        direction_overrides={},
        combinations=configured.get("combinations", {}),
        comparisons=configured.get("comparisons", {}),
        segments=segments,
    )


def _run_native_collection(
    config: Mapping[str, Any], panel: Mapping[str, Any], runnext: bool
) -> Tuple[Any, Any, Any]:
    import backtrader as bt
    from backtrader.brokers import BackBroker
    from backtrader.research import FactorSpec, FactorStrategy, MemorySink, align_to_grid
    from close_ma_factor_strategy import CloseMAFactor

    class CountingBroker(BackBroker):
        def __init__(self):
            super().__init__()
            self.submit_count = 0
            self.cancel_count = 0

        def submit(self, order):
            self.submit_count += 1
            return super().submit(order)

        def cancel(self, order):
            self.cancel_count += 1
            return super().cancel(order)

    research = _create_research_spec(config, panel)
    factor = FactorSpec(
        name=config["factor"]["name"],
        indicator=CloseMAFactor,
        params=dict(config["factor"]["params"]),
        panel_line=config["factor"]["panel_line"],
        direction=config["factor"]["direction"],
        field_bindings={field: "feed:target:%s" % field for field in CloseMAFactor.formula_fields},
    )
    cerebro = bt.Cerebro(stdstats=False)
    broker = CountingBroker()
    cerebro.setbroker(broker)
    for asset in panel["assets"]:
        aligned = align_to_grid(
            panel["feeds"][asset],
            research,
            asset,
            data_version=config["data"]["data_version"],
        )
        cerebro.adddata(aligned.feed, name=asset)
    cerebro.addstrategy(
        FactorStrategy, research=research, factors={factor.name: factor}, sink=MemorySink()
    )
    strategies = cerebro.run(runonce=not runnext, preload=True)
    if len(strategies) != 1:
        raise RuntimeError("the native collection did not return exactly one strategy")
    return strategies[0], strategies[0].get_panel(), broker


def _parse_periods(values: Optional[Sequence[int]], default: Sequence[int]) -> Tuple[int, ...]:
    result = tuple(default if values is None else values)
    if not result or any(type(value) is not int or value <= 0 for value in result):
        raise ValueError("periods must be one or more positive integers")
    if len(set(result)) != len(result):
        raise ValueError("periods must not contain duplicates")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Exit codes: 0 means factor_values.csv and summary.json were written; inspect "
            "summary.json for evaluation and report status. A reusable CSV panel is persisted "
            "only with --save-panel. "
            "factor_values.csv is still written when the fincore research API is unavailable; "
            "1 means the evaluation "
            "failed or is UNEVALUABLE; 2 means invalid or missing input; 3 means an output I/O "
            "failure."
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
        "--save-panel", action="store_true", help="also write the CSV panel for offline reevaluation"
    )
    parser.add_argument(
        "--panel", help="saved CSV panel directory for offline reevaluation"
    )
    parser.add_argument("--periods", nargs="+", type=int, help="label horizons for this evaluation")
    parser.add_argument(
        "--report", action="store_true", help="write a bilingual HTML factor report"
    )
    parser.add_argument(
        "--report-language", choices=("zh", "en"), default="zh", help="default report language"
    )
    parser.add_argument(
        "--no-charts", action="store_true", help="write tables without PNG rendering"
    )
    parser.add_argument("--runnext", action="store_true", help="use Backtrader's event-driven loop")
    return parser


def _evaluation_unavailable(exc: BaseException) -> bool:
    if getattr(exc, "code", None) == "DEPENDENCY_UNAVAILABLE":
        return True
    return isinstance(exc, ImportError) and "fincore" in str(exc)


def _write_summary(output_dir: Path, status: str, **extra: Any) -> None:
    import json

    payload = {"status": status, "output_dir": str(output_dir)}
    payload.update(extra)
    (output_dir / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = _load_config()
        if args.data_dir:
            config["data"]["directory"] = args.data_dir
        if args.max_symbols is not None:
            config["data"]["max_symbols"] = args.max_symbols
        periods = _parse_periods(args.periods, config["evaluation"]["periods"])
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
        broker = None
        if args.panel:
            from backtrader.research import FactorPanel

            research = _create_research_spec(config, load_daily_panel(config["data"]))
            panel = FactorPanel.from_csv(
                _resolve_path(args.panel),
                start=research.start,
                end=research.end,
                directions={config["factor"]["name"]: config["factor"]["direction"]},
                target_order=research.targets,
                factor_order=[config["factor"]["name"]],
                groups=research.groups,
            )
        else:
            prices = load_daily_panel(config["data"])
            _, panel, broker = _run_native_collection(config, prices, args.runnext)
            if (broker.submit_count, broker.cancel_count) != (0, 0):
                raise RuntimeError("research-only Cerebro run submitted or cancelled an order")

        if args.save_panel:
            panel.to_csv(output_dir / "panel")
        panel.factors.reset_index().to_csv(output_dir / "factor_values.csv", index=False)
        report = None
        if args.report:
            from backtrader.research import write_factor_report

            try:
                report = write_factor_report(
                    panel,
                    config["factor"]["name"],
                    output_dir / ("factor_report_%s.html" % config["factor"]["name"]),
                    periods=periods,
                    quantiles=config["evaluation"]["quantiles"],
                    max_loss=config["evaluation"]["max_loss"],
                    label=config["evaluation"]["label"],
                    language=args.report_language,
                    title="025 factor_single · %s" % config["factor"]["name"],
                )
                print("REPORT: %s" % report)
            except Exception as exc:
                print("REPORT SKIPPED: %s" % exc, file=sys.stderr)

        try:
            from backtrader.research import evaluate_frames

            result = evaluate_frames(panel, _evaluation_spec(config, panel, periods))
        except Exception as exc:
            if not _evaluation_unavailable(exc):
                raise
            print("EVALUATION SKIPPED: %s" % exc, file=sys.stderr)
            _write_summary(
                output_dir,
                "PANEL_ONLY",
                reason=str(exc),
                symbols=len(panel.target_order),
                dates=len(panel.grid),
                report=None if report is None else str(report),
            )
            return 0

        status_value = getattr(result, "status", None)
        status = str(getattr(status_value, "value", status_value)).upper()
        if status not in {"OK", "PARTIAL"}:
            print("FAILED: evaluation status %s" % status, file=sys.stderr)
            _write_summary(output_dir, "FAILED", evaluation_status=status)
            return 1

        result.export(output_dir / "evaluation", charts=not args.no_charts)
        manifest = getattr(result, "manifest", {}) or {}
        evaluation_id = getattr(result, "evaluation_id", None)
        if evaluation_id is None and hasattr(manifest, "get"):
            evaluation_id = manifest.get("evaluation_id")
        extra = {
            "evaluation_status": status,
            "evaluation_id": evaluation_id,
            "symbols": len(panel.target_order),
            "dates": len(panel.grid),
            "report": None if report is None else str(report),
        }
        if broker is not None:
            extra["broker"] = {"submit": broker.submit_count, "cancel": broker.cancel_count}
        _write_summary(output_dir, "COMPLETED", **extra)
        print("%s: %s" % (EXAMPLE_ID, status))
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
