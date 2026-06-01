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

from backtrader.brokers.mixbroker import MixBroker

from ctp_example_support import attach_trade_logger, load_config
from ctp_mix_examples_common import build_backtest_channel, format_summary, get_strategy_class


def _build_parser():
    parser = argparse.ArgumentParser(description="Run CTP-style MixBroker backtest examples")
    parser.add_argument("--config", default="single_symbol.yaml", help="YAML config path")
    return parser


def main():
    args = _build_parser().parse_args()
    config, config_path = load_config(args.config, _RUN_DIR, "single_symbol.yaml")

    broker = MixBroker(**dict(config.get("broker") or {}))
    cerebro = bt.Cerebro()
    cerebro.setbroker(broker)

    strategy_cls = get_strategy_class(config.get("strategy"))
    cerebro.addstrategy(strategy_cls, **dict(config.get("strategy_params") or {}))
    log_dir = attach_trade_logger(cerebro, config, config_path)

    print(f"Running MixBroker backtest with {config_path}")
    if log_dir is not None:
        print(f"TradeLogger dir: {log_dir}")
    print(f"Initial cash: {broker.getcash():.2f}")
    results = cerebro.run(channel=build_backtest_channel(config))

    strategy = results[0]
    print(f"Final cash: {broker.getcash():.2f}")
    print(f"Final value: {broker.getvalue():.2f}")
    print(format_summary(strategy))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
