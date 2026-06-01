from __future__ import annotations

import argparse
import os
import subprocess
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

from ctp_bar_examples_common import format_summary, get_strategy_class
from ctp_example_support import (
    add_live_feeds,
    attach_trade_logger,
    create_live_broker,
    create_live_store,
    load_config,
    parse_timeframe,
    run_cerebro_with_timeout,
)


def _build_parser():
    parser = argparse.ArgumentParser(description='Run MixBroker-style 5s live examples')
    parser.add_argument('--config', default='single_symbol.yaml', help='YAML config path')
    parser.add_argument('--dry-run', action='store_true', help='Validate config wiring without connecting to SimNow')
    parser.add_argument('--subprocess-child', action='store_true', help=argparse.SUPPRESS)
    return parser


def _validate_config(config):
    symbols = list(config.get('symbols') or [])
    if not symbols:
        raise ValueError('Live config requires at least one symbol')
    parse_timeframe(dict(config.get('feed') or {}).get('timeframe', 'seconds'))
    get_strategy_class(config.get('strategy'))
    dict(config.get('strategy_params') or {})
    return symbols


def main():
    args = _build_parser().parse_args()
    if not args.dry_run and not args.subprocess_child:
        cmd = [sys.executable, '-u', str(Path(__file__).resolve()), '--subprocess-child', *sys.argv[1:]]
        completed = subprocess.run(cmd, check=False)
        return int(completed.returncode)

    config, config_path = load_config(args.config, _RUN_DIR, 'single_symbol.yaml')
    symbols = _validate_config(config)

    if args.dry_run:
        print(f'Dry run OK for {config_path}')
        print(f'Strategy: {config.get("strategy")}')
        print(f'Symbols: {", ".join(symbols)}')
        print(f'Feed: {dict(config.get("feed") or {})}')
        print(f'Strategy params: {dict(config.get("strategy_params") or {})}')
        return 0

    store, connection = create_live_store(config)
    broker = create_live_broker(store, config)
    cerebro = bt.Cerebro()
    cerebro.setbroker(broker)
    add_live_feeds(cerebro, store, config)

    strategy_cls = get_strategy_class(config.get('strategy'))
    cerebro.addstrategy(strategy_cls, **dict(config.get('strategy_params') or {}))
    log_dir = attach_trade_logger(cerebro, config, config_path)

    timeout_seconds = float(config.get('run_timeout_seconds', 180))
    print(f'Running MixBroker-style 5s live example with {config_path}')
    if log_dir is not None:
        print(f'TradeLogger dir: {log_dir}')
    print(f'SimNow environment: {connection["simnow_name"]} ({connection["simnow_env"]})')
    if connection.get('requested_simnow_env') not in {'', None, connection['simnow_env']}:
        print(f'Requested SimNow env: {connection["requested_simnow_env"]}')
    print(f'Symbols: {", ".join(symbols)}')
    print(f'Timeout: {timeout_seconds:.0f}s')

    results = run_cerebro_with_timeout(cerebro, timeout_seconds=timeout_seconds)
    strategy = results[0]
    print(f'Cached cash: {broker.getcash():.2f}')
    print(f'Cached value: {broker.getvalue():.2f}')
    print(format_summary(strategy))
    return 0


if __name__ == '__main__':
    exit_code = int(main())
    if '--subprocess-child' in sys.argv:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(exit_code)
    raise SystemExit(exit_code)
