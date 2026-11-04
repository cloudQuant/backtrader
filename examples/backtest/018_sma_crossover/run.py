#!/usr/bin/env python
"""Run the self-contained SMA crossover example."""

from __future__ import annotations

import argparse
from pathlib import Path
import stat
import sys
from typing import List, Optional

import yaml

import backtrader as bt
from backtrader.utils.paths import data_path, find_project_root

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


def _resolve_data_file(value: str, config_path: Path) -> Path:
    """Resolve bundled fixtures from the checkout and other paths from the config."""
    supplied = Path(value).expanduser()
    if supplied.is_absolute():
        path = supplied
    elif supplied.parts[:2] == ("tests", "datas"):
        path = data_path(supplied, root=find_project_root(__file__))
    else:
        path = config_path.parent / supplied
    path = path.resolve()
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError(f"SMA example input is not a regular file: {path}")
    return path


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
    try:
        config = _load_config(config_path)
    except FileNotFoundError as exc:
        if exc.filename is None or Path(exc.filename) != config_path:
            raise
        print(
            f"BLOCKED: configuration file not found: {config_path}; "
            "provide an existing --config file",
            file=sys.stderr,
        )
        return 2
    try:
        datapath = _resolve_data_file(config["data_file"], config_path)
    except FileNotFoundError as exc:
        print(
            f"BLOCKED: SMA example input is missing: {exc}; "
            "provide an existing data_file in --config",
            file=sys.stderr,
        )
        return 2

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(float(config["cash"]))
    cerebro.adddata(bt.feeds.BacktraderCSVData(dataname=str(datapath)))
    cerebro.addstrategy(MA_CrossOver, fast=config["fast"], slow=config["slow"])
    results = cerebro.run()
    print(f"bars: {len(results[0].data)}")
    print(f"final portfolio value: {cerebro.broker.getvalue():.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
