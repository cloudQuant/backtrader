from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

STRATEGY_CONFIG = {
    "basis_alpha_market_making": {
        "data_subdir": "btcusdt_20240102",
        "symbol": "BTC/USDT",
        "tick_size": 0.1,
        "lot_size": 0.001,
        "decision_interval_ns": 100_000_000,
        "maker_commission": -0.00005,
        "taker_commission": 0.0007,
        "queue_model_power": 3.0,
        "market_data_name": "BTCUSDT_20240102.npz",
        "orderbook_name": "orderbook_BTCUSDT_20240102.jsonl",
        "ticks_name": "tick_BTCUSDT_20240102.csv",
        "latency_name": "latency_20240102.npz",
    },
    "apt_alpha_market_making": {
        "data_subdir": "btcusdt_20240102",
        "symbol": "BTC/USDT",
        "tick_size": 0.1,
        "lot_size": 0.001,
        "decision_interval_ns": 100_000_000,
        "maker_commission": -0.00005,
        "taker_commission": 0.0007,
        "queue_model_power": 3.0,
        "market_data_name": "BTCUSDT_20240102.npz",
        "orderbook_name": "orderbook_BTCUSDT_20240102.jsonl",
        "ticks_name": "tick_BTCUSDT_20240102.csv",
        "latency_name": "latency_20240102.npz",
    },
    "glft_market_making": {
        "data_subdir": "ethusdt_20240101",
        "symbol": "ETH/USDT",
        "tick_size": 0.01,
        "lot_size": 0.001,
        "decision_interval_ns": 100_000_000,
        "maker_commission": -0.00005,
        "taker_commission": 0.0007,
        "queue_model_power": 2.0,
        "market_data_name": "ETHUSDT_20240101.npz",
        "orderbook_name": "orderbook_ETHUSDT_20240101.jsonl",
        "ticks_name": "tick_ETHUSDT_20240101.csv",
        "latency_name": "latency_20240101.npz",
    },
}

EXAMPLE_ROOT = Path(__file__).resolve().parent
DEFAULT_DATA_ROOT = EXAMPLE_ROOT / "data"
STRATEGY_NAMES = tuple(STRATEGY_CONFIG)
DEFAULT_STRATEGY = STRATEGY_NAMES[0]
DEFAULT_MAX_DECISIONS = 200


def default_paths(strategy: str, data_root: Path) -> dict[str, Path]:
    config = STRATEGY_CONFIG[strategy]
    root = Path(data_root) / config["data_subdir"]
    if strategy == "glft_market_making" and not root.exists():
        root = EXAMPLE_ROOT.parent / "002_hft_alignment_demo" / "data"
    return {
        "root": root,
        "orderbook": root / config["orderbook_name"],
        "ticks": root / config["ticks_name"],
        "market_data": root / config["market_data_name"],
        "latency": root / config["latency_name"],
    }


def resolve_runtime(args) -> dict[str, float | int | str]:
    config = STRATEGY_CONFIG[args.strategy]
    return {
        "symbol": args.symbol or config["symbol"],
        "tick_size": float(args.tick_size if args.tick_size is not None else config["tick_size"]),
        "lot_size": float(args.lot_size if args.lot_size is not None else config["lot_size"]),
        "decision_interval_ns": int(args.decision_interval_ns if args.decision_interval_ns is not None else config["decision_interval_ns"]),
        "maker_commission": float(args.maker_commission if args.maker_commission is not None else config["maker_commission"]),
        "taker_commission": float(args.taker_commission if args.taker_commission is not None else config["taker_commission"]),
        "queue_model_power": float(args.queue_model_power if args.queue_model_power is not None else config["queue_model_power"]),
    }


def add_common_arguments(parser: argparse.ArgumentParser, include_strategy: bool = True) -> argparse.ArgumentParser:
    if include_strategy:
        parser.add_argument("--strategy", default=DEFAULT_STRATEGY, choices=STRATEGY_NAMES)
    parser.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--tick-size", type=float, default=None)
    parser.add_argument("--lot-size", type=float, default=None)
    parser.add_argument("--decision-interval-ns", type=int, default=None)
    parser.add_argument("--max-decisions", type=int, default=DEFAULT_MAX_DECISIONS)
    parser.add_argument("--maker-commission", type=float, default=None)
    parser.add_argument("--taker-commission", type=float, default=None)
    parser.add_argument("--queue-model-power", type=float, default=None)
    return parser


def resolve_paths(args) -> dict[str, Path]:
    return default_paths(args.strategy, Path(args.data_root))


def fill_counter(fills) -> Counter:
    return Counter((item.side, round(float(item.price), 8), round(float(item.size), 8)) for item in fills)
