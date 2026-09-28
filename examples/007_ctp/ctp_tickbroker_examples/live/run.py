"""CTP TickBroker live trading runner with SimNow.

This module runs live trading examples using BtApiStore and BtApiBroker
connected to SimNow for testing with tick-level data.
"""
from __future__ import annotations

# This fence must remain before every legacy framework, CTP, or provider import.
import sys as _iteration41_sys
from pathlib import Path as _Iteration41Path

_ITERATION41_RUNTIME_DIR = _Iteration41Path(__file__).resolve().parents[2] / "runtime"
_ITERATION41_REPOSITORY_ROOT = _ITERATION41_RUNTIME_DIR.parents[2]
if str(_ITERATION41_REPOSITORY_ROOT) not in _iteration41_sys.path:
    _iteration41_sys.path.insert(0, str(_ITERATION41_REPOSITORY_ROOT))

from backtrader_runtime.legacy import (  # noqa: E402
    legacy_direct_execution_error as _iteration41_legacy_direct_execution_error,
    run_legacy_config_first_cli as _iteration41_run_legacy_config_first_cli,
)


def _run_config_first_cli(argv=None) -> int:
    return _iteration41_run_legacy_config_first_cli(_ITERATION41_RUNTIME_DIR, argv)


def main(*args, **kwargs):
    del args, kwargs
    raise _iteration41_legacy_direct_execution_error("examples/007_ctp/ctp_tickbroker_examples/live/run.py")


if __name__ == "__main__":
    raise SystemExit(_run_config_first_cli())

import argparse
import sys
from pathlib import Path

_RUN_DIR = Path(__file__).resolve().parent
_EXAMPLE_ROOT = _RUN_DIR.parent
_EXAMPLES_ROOT = _EXAMPLE_ROOT.parent
_REPO_ROOT = _EXAMPLES_ROOT.parent.parent

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


def _legacy_main():
    raise _iteration41_legacy_direct_execution_error(
        "examples/007_ctp/ctp_tickbroker_examples/live/run.py"
    )

    """Run the CTP TickBroker live trading example.

    Returns:
        int: Exit code (0 for success).
    """
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


# Iteration 41 retains this historical body for review only; direct execution is disabled.
if False:  # pragma: no cover - retired direct entrypoint

    raise SystemExit(main())
