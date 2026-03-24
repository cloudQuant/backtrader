from __future__ import annotations

import argparse
import sys
from pathlib import Path

_RUN_DIR = Path(__file__).resolve().parent
_EXAMPLE_ROOT = _RUN_DIR.parent
_EXAMPLES_ROOT = _EXAMPLE_ROOT.parent
_REPO_ROOT = _EXAMPLES_ROOT.parent

for _path in (_RUN_DIR, _EXAMPLE_ROOT, _EXAMPLES_ROOT, _REPO_ROOT):
    _text = str(_path)
    if _text not in sys.path:
        sys.path.insert(0, _text)

import backtrader as bt

from ctp_example_support import (
    add_live_feeds,
    attach_trade_logger,
    create_live_broker,
    create_live_store,
    load_config,
    run_cerebro_with_timeout,
)
from ctp_tick_examples_common import format_summary, get_strategy_class


def _build_parser():
    parser = argparse.ArgumentParser(description="Run CTP SimNow TickBroker-style live examples")
    parser.add_argument("--config", default="single_symbol.yaml", help="YAML config path")
    return parser


def main():
    args = _build_parser().parse_args()
    config, config_path = load_config(args.config, _RUN_DIR, "single_symbol.yaml")

    store, connection = create_live_store(config)
    broker = create_live_broker(store, config)
    cerebro = bt.Cerebro()
    cerebro.setbroker(broker)
    add_live_feeds(cerebro, store, config)

    strategy_cls = get_strategy_class(config.get("strategy"))
    cerebro.addstrategy(strategy_cls, **dict(config.get("strategy_params") or {}))
    log_dir = attach_trade_logger(cerebro, config, config_path)

    timeout_seconds = float(config.get("run_timeout_seconds", 120))
    print(f"Running TickBroker-style live example with {config_path}")
    if log_dir is not None:
        print(f"TradeLogger dir: {log_dir}")
    print(f"SimNow environment: {connection['simnow_name']} ({connection['simnow_env']})")
    if connection.get("requested_simnow_env") not in {"", None, connection["simnow_env"]}:
        print(f"Requested SimNow env: {connection['requested_simnow_env']}")
    print(f"Symbols: {', '.join(config.get('symbols') or [])}")
    print(f"Timeout: {timeout_seconds:.0f}s")

    results = run_cerebro_with_timeout(cerebro, timeout_seconds=timeout_seconds)
    strategy = results[0]
    print(f"Cached cash: {broker.getcash():.2f}")
    print(f"Cached value: {broker.getvalue():.2f}")
    print(format_summary(strategy))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
