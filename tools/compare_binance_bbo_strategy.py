from __future__ import annotations

import argparse

from backtrader.brokers.hft.binance_bbo_compare import compare_binance_bbo_strategy, comparison_to_json
from backtrader.brokers.hft.examples import get_hftbacktest_example_specs


STRATEGY_NAMES = tuple(spec.name for spec in get_hftbacktest_example_specs())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare backtrader and hftbacktest on converted Binance BBO data")
    parser.add_argument("--strategy", required=True, choices=STRATEGY_NAMES)
    parser.add_argument("--orderbook", required=True)
    parser.add_argument("--ticks", required=True)
    parser.add_argument("--market-data", required=True)
    parser.add_argument("--symbol", default="ETH/USDT")
    parser.add_argument("--tick-size", type=float, required=True)
    parser.add_argument("--lot-size", type=float, required=True)
    parser.add_argument("--decision-interval-ns", type=int, default=None)
    parser.add_argument("--maker-commission", type=float, default=None)
    parser.add_argument("--taker-commission", type=float, default=None)
    parser.add_argument("--queue-model-power", type=float, default=None)
    parser.add_argument("--max-decisions", type=int, default=None)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    result = compare_binance_bbo_strategy(
        strategy_name=args.strategy,
        orderbook_path=args.orderbook,
        tick_path=args.ticks,
        market_data_path=args.market_data,
        symbol=args.symbol,
        tick_size=args.tick_size,
        lot_size=args.lot_size,
        decision_interval_ns=args.decision_interval_ns,
        maker_commission=args.maker_commission,
        taker_commission=args.taker_commission,
        queue_model_power=args.queue_model_power,
        max_decisions=args.max_decisions,
    )
    print(comparison_to_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
