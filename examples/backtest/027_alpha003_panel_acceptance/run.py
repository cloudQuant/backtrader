"""Compute the offline native Alpha003 example and export its factor panel."""

# ruff: noqa: E402 -- select the checkout before importing Backtrader declarations.

import argparse
import json
import math
from pathlib import Path
import sys


def _add_checkout_root():
    """Use this checkout in-place; a copied example uses installed Backtrader."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "backtrader" / "__init__.py").is_file():
            sys.path.insert(0, str(parent))
            return


_add_checkout_root()

import backtrader as bt
import pandas as pd
import yaml

from alpha003_strategy import Alpha003Indicator
from backtrader.research import FactorIndicator, FactorStrategy, ResearchSpec, prealign_bars


OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")


def make_inputs():
    """Build the unchanged AF45-003 ten-grid, three-asset deterministic fixture."""
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


def _validate_grid(grid):
    try:
        grid_index = pd.DatetimeIndex(tuple(grid))
    except (TypeError, ValueError) as exc:
        raise ValueError("grid must contain timezone-aware timestamps") from exc
    if (
        grid_index.tz is None
        or not grid_index.is_unique
        or not grid_index.is_monotonic_increasing
        or not len(grid_index)
    ):
        raise ValueError("grid must contain unique increasing timezone-aware timestamps")
    return grid_index.tz_convert("UTC")


def _validated_feed_frame(frame, grid_index):
    if not isinstance(frame, pd.DataFrame):
        raise ValueError("each input must be a pandas DataFrame")
    if (
        not isinstance(frame.index, pd.DatetimeIndex)
        or frame.index.tz is None
        or not frame.index.is_unique
        or not frame.index.is_monotonic_increasing
    ):
        raise ValueError("each feed requires unique increasing timezone-aware timestamps")
    if not frame.columns.is_unique or not set(OHLCV_COLUMNS).issubset(frame.columns):
        raise ValueError("each feed requires all five OHLCV columns")

    source = frame.loc[:, list(OHLCV_COLUMNS)]
    try:
        has_infinity = any(
            math.isinf(float(value))
            for row in source.itertuples(index=False, name=None)
            for value in row
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("source OHLCV values must be numeric or NaN") from exc
    if has_infinity:
        raise ValueError("source OHLCV must not contain infinity")

    source_index = source.copy()
    source_index.index = source.index.tz_convert("UTC")
    if not source_index.index.isin(grid_index).all():
        raise ValueError("input timestamps must belong to the explicit grid")
    return source_index


def make_research(grid_index, assets):
    """Declare this demonstration's synthetic calendar and research window."""
    index = pd.DatetimeIndex(grid_index, name="close_time")
    return ResearchSpec(
        grid=pd.DataFrame({"open_time": index - pd.Timedelta(hours=8)}, index=index),
        start=index[0],
        end=index[-1],
        targets=tuple(assets),
        source_timezone="UTC",
        snapshot_id="af45_003_v1",
        price_basis="synthetic_unadjusted_ohlcv",
        calendar_id="af45_003_explicit_daily_grid_v1",
        frequency="1day",
    )


def run_experiment(inputs, grid, *, runonce=False, asset_order=None, factor_classes=None):
    """Run native FactorIndicators in Cerebro and return the collecting strategy."""
    if (
        not isinstance(inputs, dict)
        or not inputs
        or any(not isinstance(asset, str) or not asset for asset in inputs)
    ):
        raise ValueError("inputs must contain named assets")
    grid_index = _validate_grid(grid)
    order = list(inputs) if asset_order is None else list(asset_order)
    if len(order) != len(inputs) or set(order) != set(inputs):
        raise ValueError("asset_order must contain every asset exactly once")

    research = make_research(grid_index, order)
    cerebro = bt.Cerebro(stdstats=False)
    for asset in order:
        source = _validated_feed_frame(inputs[asset], grid_index)
        aligned = prealign_bars(source, research, asset, data_version="af45_003_v1")
        cerebro.adddata(aligned.feed, name=asset)

    classes = {"alpha003": Alpha003Indicator} if factor_classes is None else factor_classes
    if not isinstance(classes, dict) or not classes:
        raise ValueError("factor_classes must contain at least one named Indicator class")
    factors = {
        name: {
            "indicator": indicator_class,
            "params": {},
            "panel_line": "factor",
            "field_bindings": {
                field: "feed:target:" + field for field in indicator_class.formula_fields
            },
        }
        for name, indicator_class in classes.items()
    }
    cerebro.addstrategy(FactorStrategy, factors=factors, research=research)
    return cerebro.run(runonce=runonce, preload=True)[0]


def _input_rows(inputs):
    rows = []
    for asset, frame in inputs.items():
        part = frame.loc[:, list(OHLCV_COLUMNS)].copy()
        part.insert(0, "asset", asset)
        part.insert(0, "time", frame.index)
        rows.append(part.reset_index(drop=True))
    return pd.concat(rows, ignore_index=True)


def _dataset_rows(dataset):
    dataset = dataset.raw_factors
    if not isinstance(dataset, pd.DataFrame):
        raise TypeError("ResearchDataset.raw_factors must return a pandas DataFrame")
    if not {"time", "asset"}.issubset(dataset.columns):
        dataset = dataset.reset_index()
    if not {"time", "asset"}.issubset(dataset.columns):
        raise ValueError("factor dataset must contain time and asset")
    return dataset


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
            json.dumps(
                {
                    "status": "RUNNING",
                    "evidence_level": "ITERATION45_R0_NATIVE_ALPHA003_ONLY",
                    "acceptance": "NOT_EVALUATED_BY_EXAMPLE_RUNNER",
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        inputs = make_inputs()
        strategy = run_experiment(inputs, inputs["A"].index.to_pydatetime())
        factor_rows = _dataset_rows(strategy.get_dataset())
        indicator = strategy.factor_instances["alpha003"]
        diagnostics = pd.DataFrame(indicator.diagnostics)

        _input_rows(inputs).to_csv(output / "input_bars.csv", index=False)
        diagnostics.to_csv(output / "node_values.csv", index=False)
        factor_rows.to_csv(output / "factor_values.csv", index=False)
        report = {
            "status": "COMPLETED",
            "evidence_level": "ITERATION45_R0_NATIVE_ALPHA003_ONLY",
            "acceptance": "NOT_EVALUATED_BY_EXAMPLE_RUNNER",
            "formula": "-correlation(rank(open), rank(volume), 10)",
            "panel_mode": indicator.panel_mode,
            "lookback_h": indicator.lookback_h(period=indicator.p.period),
            "backtrader_origin": str(Path(bt.__file__).resolve()),
            "research_origin": str(
                Path(sys.modules[FactorIndicator.__module__].__file__).resolve()
            ),
            "factor_evaluation_count": indicator.evaluation_count,
            "grid_call_counts": indicator.grid_call_counts,
            "grid_rows": len(inputs["A"].index),
            "asset_count": len(inputs),
            "output_files": ["input_bars.csv", "node_values.csv", "factor_values.csv"],
        }
        (output / "run_summary.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
        )
        last_time = inputs["A"].index[-1].to_pydatetime()
        print(factor_rows.loc[factor_rows["time"] == last_time].to_string(index=False))
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
