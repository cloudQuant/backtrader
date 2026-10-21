"""Compute the offline Alpha003 prototype and export its factor panel."""

# ruff: noqa: E402 -- select the checkout before importing Backtrader or local declarations.

import argparse
import json
import math
from pathlib import Path
import sys


def _add_checkout_root():
    """In-place examples use this checkout; copied examples use installed BT."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "backtrader" / "__init__.py").is_file():
            sys.path.insert(0, str(parent))
            return


_add_checkout_root()

import backtrader as bt
import pandas as pd
import yaml

from alpha003_strategy import Alpha003Indicator
from factor_strategy import FactorStrategy


def make_inputs():
    """AF45-003: three assets, ten synthetic daily closed bars; no downloads."""
    grid = pd.date_range("2020-01-01 16:00", periods=10, freq="D", tz="UTC")
    inputs = {}
    for column, asset in enumerate(("A", "B", "C")):
        order = [(day + column) % 3 + 1 for day in range(10)]
        volume = [100 * (4 - value if day < 9 else value) for day, value in enumerate(order)]
        inputs[asset] = pd.DataFrame(
            {
                "open": [10 + value for value in order],
                "high": 20.0,
                "low": 0.5,
                "close": 10.0,
                "volume": volume,
            },
            index=grid,
            dtype=float,
        )
    return inputs


def run_experiment(inputs, grid, *, runonce=False, asset_order=None, factor_classes=None):
    """The same Cerebro/template wiring can be reused for other supported graphs."""
    grid = tuple(grid)
    if not inputs or any(not isinstance(asset, str) or not asset for asset in inputs):
        raise ValueError("inputs must contain named assets")
    grid_index = pd.DatetimeIndex(grid)
    if (
        grid_index.tz is None
        or not grid_index.is_unique
        or not grid_index.is_monotonic_increasing
        or not len(grid_index)
    ):
        raise ValueError("grid must contain unique increasing timezone-aware timestamps")
    order = list(inputs) if asset_order is None else list(asset_order)
    if len(order) != len(inputs) or set(order) != set(inputs):
        raise ValueError("asset_order must contain every asset exactly once")
    cerebro = bt.Cerebro(stdstats=False)
    for asset in order:
        frame = inputs[asset]
        if (
            not isinstance(frame.index, pd.DatetimeIndex)
            or frame.index.tz is None
            or not frame.index.is_unique
            or not frame.index.is_monotonic_increasing
        ):
            raise ValueError("each feed requires unique increasing timezone-aware timestamps")
        if not frame.columns.is_unique or not {"open", "high", "low", "close", "volume"}.issubset(
            frame.columns
        ):
            raise ValueError("each feed requires all five OHLCV columns")
        # Reject source infinities before a Feed can normalize or mask them.
        if any(
            math.isinf(float(value))
            for row in frame[["open", "high", "low", "close", "volume"]].itertuples(
                index=False, name=None
            )
            for value in row
        ):
            raise ValueError("source OHLCV must not contain infinity")
        if not frame.index.isin(grid_index).all():
            raise ValueError("input timestamps must belong to the explicit grid")
        cerebro.adddata(bt.feeds.PandasData(dataname=frame.copy()), name=asset)
    classes = {"alpha003": Alpha003Indicator} if factor_classes is None else factor_classes
    factors = {
        name: {
            "indicator": cls,
            "execution": "panel",
            "operator_profile": "alpha101-v1",
            "field_bindings": {"open": "feedline:open", "volume": "feedline:volume"},
        }
        for name, cls in classes.items()
    }
    cerebro.addstrategy(FactorStrategy, factors=factors, grid=tuple(grid))
    return cerebro.run(runonce=runonce, preload=True)[0]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.yaml"))
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    output = None
    try:
        config_path = args.config.resolve()
        config = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))
        if (
            not isinstance(config, dict)
            or config.get("factor") != "alpha003"
            or config.get("operator_profile") != "alpha101-v1"
            or config.get("fixture") != "af45_003_v1"
            or not isinstance(config.get("output_dir"), str)
        ):
            raise ValueError("this example fixes Alpha003/alpha101-v1/af45_003_v1")
        output = args.output_dir or Path(config["output_dir"])
        if not output.is_absolute():
            output = config_path.parent / output
        output.mkdir(parents=True, exist_ok=True)
        (output / "run_summary.json").write_text(
            json.dumps({"status": "RUNNING", "evidence_level": "LOCAL_ALPHA003_PROTOTYPE_ONLY"}),
            encoding="utf-8",
        )

        inputs = make_inputs()
        strategy = run_experiment(inputs, inputs["A"].index.to_pydatetime())
        dataset = strategy.get_dataset()
        dataset.to_csv(output / "factor_values.csv")
        strategy.get_diagnostics().to_csv(output / "node_values.csv", index=False)
        pd.concat(inputs, names=["asset", "time"]).to_csv(output / "input_bars.csv")
        report = {
            "status": "COMPLETED",
            "evidence_level": "LOCAL_ALPHA003_PROTOTYPE_ONLY",
            "formula": "-correlation(rank(open), rank(volume), 10)",
            "operator_profile": "alpha101-v1",
            "backtrader_origin": str(Path(bt.__file__).resolve()),
            "backtrader_version": bt.__version__,
            "evaluation_counts": strategy.engine.evaluation_counts,
        }
        (output / "run_summary.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
        )
        print(dataset.loc[inputs["A"].index[-1]].to_string())
        print("COMPLETED: Alpha003 factor panel exported")
        print("Results:", output.resolve())
        return 0
    except (FileNotFoundError, ImportError) as exc:
        if output is not None and output.is_dir():
            (output / "run_summary.json").write_text(
                json.dumps({"status": "BLOCKED", "reason": str(exc)}), encoding="utf-8"
            )
        print("BLOCKED:", exc, file=sys.stderr)
        return 2
    except Exception as exc:
        if output is not None and output.is_dir():
            (output / "run_summary.json").write_text(
                json.dumps({"status": "FAIL", "reason": str(exc)}), encoding="utf-8"
            )
        print("FAIL:", type(exc).__name__, str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
