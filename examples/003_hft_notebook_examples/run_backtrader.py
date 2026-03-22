from __future__ import annotations

import argparse

from backtrader.brokers.hft.binance_bbo_compare import engine_result_to_json, run_binance_bbo_backtrader_strategy

from common import add_common_arguments, resolve_paths, resolve_runtime


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the backtrader side of migrated hftbacktest notebook strategies")
    return add_common_arguments(parser, include_strategy=True)


def main() -> int:
    args = _build_parser().parse_args()
    paths = resolve_paths(args)
    runtime = resolve_runtime(args)
    result = run_binance_bbo_backtrader_strategy(
        strategy_name=args.strategy,
        orderbook_path=paths["orderbook"],
        tick_path=paths["ticks"],
        market_data_path=paths["market_data"],
        symbol=runtime["symbol"],
        tick_size=runtime["tick_size"],
        lot_size=runtime["lot_size"],
        decision_interval_ns=runtime["decision_interval_ns"],
        maker_commission=runtime["maker_commission"],
        taker_commission=runtime["taker_commission"],
        queue_model_power=runtime["queue_model_power"],
        max_decisions=args.max_decisions,
    )
    print(engine_result_to_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
