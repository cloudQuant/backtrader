from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from backtrader.brokers.hft.examples import get_hftbacktest_demo_example_specs

EXAMPLE_ROOT = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = EXAMPLE_ROOT / "data"
DEFAULT_SYMBOL = "ETH/USDT"
STRATEGY_NAMES = tuple(spec.name for spec in get_hftbacktest_demo_example_specs())
DEFAULT_STRATEGY = STRATEGY_NAMES[0]
DEFAULT_TICK_SIZE = 0.01
DEFAULT_LOT_SIZE = 0.001
DEFAULT_DECISION_INTERVAL_NS = 100_000_000
DEFAULT_MAX_DECISIONS = 500
DEFAULT_MAKER_COMMISSION = -0.00005
DEFAULT_TAKER_COMMISSION = 0.0007
DEFAULT_QUEUE_MODEL_POWER = 3.0


def default_paths(data_dir: Path) -> dict[str, Path]:
    return {
        "orderbook": data_dir / "orderbook_ETHUSDT_20240101.jsonl",
        "ticks": data_dir / "tick_ETHUSDT_20240101.csv",
        "market_data": data_dir / "ETHUSDT_20240101.npz",
        "latency": data_dir / "latency_20240101.npz",
    }


def add_common_arguments(parser: argparse.ArgumentParser, include_strategy: bool = True) -> argparse.ArgumentParser:
    if include_strategy:
        parser.add_argument("--strategy", default=DEFAULT_STRATEGY, choices=STRATEGY_NAMES)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--tick-size", type=float, default=DEFAULT_TICK_SIZE)
    parser.add_argument("--lot-size", type=float, default=DEFAULT_LOT_SIZE)
    parser.add_argument("--decision-interval-ns", type=int, default=DEFAULT_DECISION_INTERVAL_NS)
    parser.add_argument("--max-decisions", type=int, default=DEFAULT_MAX_DECISIONS)
    parser.add_argument("--maker-commission", type=float, default=DEFAULT_MAKER_COMMISSION)
    parser.add_argument("--taker-commission", type=float, default=DEFAULT_TAKER_COMMISSION)
    parser.add_argument("--queue-model-power", type=float, default=DEFAULT_QUEUE_MODEL_POWER)
    return parser


def resolve_paths(args) -> dict[str, Path]:
    return default_paths(Path(args.data_dir))


def fill_counter(fills) -> Counter:
    return Counter((item.side, round(float(item.price), 8), round(float(item.size), 8)) for item in fills)
