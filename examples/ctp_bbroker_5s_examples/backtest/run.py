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
from backtrader.brokers.bbroker import BackBroker

from ctp_bar_examples_common import add_bbroker_backtest_feeds, format_summary, get_strategy_class
from ctp_example_support import attach_trade_logger, load_config


def _build_parser():
    parser = argparse.ArgumentParser(description='Run BackBroker 5s backtests')
    parser.add_argument('--config', default='single_symbol.yaml', help='YAML config path')
    return parser


def main():
    args = _build_parser().parse_args()
    config, config_path = load_config(args.config, _RUN_DIR, 'single_symbol.yaml')

    broker_kwargs = dict(config.get('broker') or {})
    initial_cash = float(config.get('initial_cash', broker_kwargs.pop('cash', 100000.0)))
    cerebro = bt.Cerebro()
    cerebro.setbroker(BackBroker(cash=initial_cash, **broker_kwargs))
    strategy_cls = get_strategy_class(config.get('strategy'))
    cerebro.addstrategy(strategy_cls, **dict(config.get('strategy_params') or {}))
    log_dir = attach_trade_logger(cerebro, config, config_path)

    add_bbroker_backtest_feeds(cerebro, config)

    print(f'Running BackBroker 5s backtest with {config_path}')
    if log_dir is not None:
        print(f'TradeLogger dir: {log_dir}')
    print(f'Initial cash: {cerebro.broker.getcash():.2f}')

    results = cerebro.run()

    strategy = results[0]
    broker = cerebro.broker
    print(f'Final cash: {broker.getcash():.2f}')
    print(f'Final value: {broker.getvalue():.2f}')
    print(format_summary(strategy))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
