from __future__ import annotations

import argparse

from backtrader.brokers.hft.binance_bbo_compare import engine_result_to_json, run_binance_bbo_hftbacktest_strategy

from common import add_common_arguments, resolve_paths


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the hftbacktest side of the Binance BBO alignment demo")
    return add_common_arguments(parser, include_strategy=True)


def main() -> int:
    args = _build_parser().parse_args()
    paths = resolve_paths(args)
    result = run_binance_bbo_hftbacktest_strategy(
        strategy_name=args.strategy,
        orderbook_path=paths["orderbook"],
        tick_path=paths["ticks"],
        market_data_path=paths["market_data"],
        symbol=args.symbol,
        tick_size=args.tick_size,
        lot_size=args.lot_size,
        decision_interval_ns=args.decision_interval_ns,
        maker_commission=args.maker_commission,
        taker_commission=args.taker_commission,
        queue_model_power=args.queue_model_power,
        max_decisions=args.max_decisions,
    )
    print(engine_result_to_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
