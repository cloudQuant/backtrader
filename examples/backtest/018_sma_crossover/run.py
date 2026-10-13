#!/usr/bin/env python
"""Run the self-contained SMA crossover example."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import List, Optional

import yaml


def _add_checkout_root() -> None:
    """Use the source checkout when run in place; copies use installed Backtrader."""

    for parent in Path(__file__).resolve().parents:
        if (parent / "backtrader" / "__init__.py").is_file():
            sys.path.insert(0, str(parent))
            return


_add_checkout_root()

import backtrader as bt

from sma_crossover_strategy import MA_CrossOver


def _load_config(path: Path) -> dict:
    """Load and validate the small public example configuration."""

    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError(f"configuration must be a mapping: {path}")

    fast = config.get("fast")
    slow = config.get("slow")
    if type(fast) is not int or type(slow) is not int or fast < 1 or slow <= fast:
        raise ValueError("config fast/slow must be integers with 1 <= fast < slow")
    if not isinstance(config.get("data_file"), str) or not config["data_file"]:
        raise ValueError("config data_file must be a non-empty relative or absolute path")
    if isinstance(config.get("cash"), bool) or not isinstance(config.get("cash"), (int, float)):
        raise ValueError("config cash must be a number")
    return config


def main(argv: Optional[List[str]] = None) -> int:
    """Run one deterministic local backtest and print its final portfolio value."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().with_name("config.yaml"),
    )
    args = parser.parse_args(argv)

    config_path = args.config.expanduser().resolve()
    config = _load_config(config_path)
    data_path = Path(config["data_file"]).expanduser()
    if not data_path.is_absolute():
        data_path = config_path.parent / data_path
    data_path = data_path.resolve()
    if not data_path.is_file():
        raise FileNotFoundError(f"SMA example input is missing: {data_path}")

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(float(config["cash"]))
    cerebro.adddata(bt.feeds.BacktraderCSVData(dataname=str(data_path)))
    cerebro.addstrategy(MA_CrossOver, fast=config["fast"], slow=config["slow"])
    results = cerebro.run()
    print(f"bars: {len(results[0].data)}")
    print(f"final portfolio value: {cerebro.broker.getvalue():.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
