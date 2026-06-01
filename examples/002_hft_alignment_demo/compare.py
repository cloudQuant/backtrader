from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from backtrader.brokers.hft.binance_bbo_compare import compare_binance_bbo_strategy

from common import add_common_arguments, fill_counter, resolve_paths


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare backtrader and hftbacktest on the Binance BBO alignment demo")
    return add_common_arguments(parser, include_strategy=True)


def main() -> int:
    args = _build_parser().parse_args()
    paths = resolve_paths(args)
    result = compare_binance_bbo_strategy(
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
    bt_fills = fill_counter(result.backtrader.fills)
    hft_fills = fill_counter(result.hftbacktest.fills)
    payload = {
        "canonical_matches": {
            "balance": abs(result.backtrader.balance - result.hftbacktest.balance) < 1e-5,
            "position": abs(result.backtrader.position - result.hftbacktest.position) < 1e-12,
            "num_trades": result.backtrader.num_trades == result.hftbacktest.num_trades,
            "fills_multiset": bt_fills == hft_fills,
            "fills_normalized_order": result.matches.get("fills_normalized_order", False),
        },
        "raw_comparison": asdict(result),
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
