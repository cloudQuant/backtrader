from __future__ import annotations

import argparse
from pathlib import Path

from backtrader.brokers.hft import convert_binance_bbo_zip_pair, generate_latency_from_hft_events


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert Binance bookTicker + trades zip files into hftbacktest/backtrader replay inputs")
    parser.add_argument("--book-ticker-zip", required=True, help="Path to Binance bookTicker zip file")
    parser.add_argument("--trades-zip", required=True, help="Path to Binance trades zip file")
    parser.add_argument("--output-dir", required=True, help="Directory where converted files will be written")
    parser.add_argument("--bt-symbol", default=None, help="Override backtrader symbol, e.g. ETH/USDT")
    parser.add_argument("--exchange", default="binance", help="Exchange name to embed in backtrader replay files")
    parser.add_argument("--asset-type", default="futures", help="Asset type to embed in backtrader replay files")
    parser.add_argument("--start-ms", type=int, default=None, help="Optional inclusive lower bound in epoch milliseconds")
    parser.add_argument("--end-ms", type=int, default=None, help="Optional inclusive upper bound in epoch milliseconds")
    parser.add_argument("--max-book-rows", type=int, default=None, help="Optional cap for bookTicker rows")
    parser.add_argument("--max-trade-rows", type=int, default=None, help="Optional cap for trades rows")
    parser.add_argument("--generate-latency", action="store_true", help="Also generate latency npz beside the hftbacktest npz")
    parser.add_argument("--latency-output", default=None, help="Optional latency npz path; defaults to latency_<date>.npz in output dir")
    parser.add_argument("--mul-entry", type=float, default=4.0, help="Order entry latency multiplier")
    parser.add_argument("--offset-entry-ns", type=int, default=0, help="Order entry latency offset in nanoseconds")
    parser.add_argument("--mul-resp", type=float, default=3.0, help="Order response latency multiplier")
    parser.add_argument("--offset-resp-ns", type=int, default=0, help="Order response latency offset in nanoseconds")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    result = convert_binance_bbo_zip_pair(
        book_ticker_zip_path=args.book_ticker_zip,
        trades_zip_path=args.trades_zip,
        output_directory=args.output_dir,
        bt_symbol=args.bt_symbol,
        exchange=args.exchange,
        asset_type=args.asset_type,
        start_ms=args.start_ms,
        end_ms=args.end_ms,
        max_book_rows=args.max_book_rows,
        max_trade_rows=args.max_trade_rows,
    )

    print(f"Converted {result.symbol} {result.date}")
    print(f"- hftbacktest npz: {result.hft_npz_path}")
    print(f"- backtrader ticks: {result.backtrader_ticks_path}")
    print(f"- backtrader orderbook: {result.backtrader_orderbook_path}")
    print(f"- book rows: {result.book_rows}")
    print(f"- trade rows: {result.trade_rows}")
    print(f"- final event count: {result.final_event_count}")

    if args.generate_latency:
        latency_output = Path(args.latency_output) if args.latency_output else Path(args.output_dir) / f"latency_{result.date.replace('-', '')}.npz"
        latency = generate_latency_from_hft_events(
            hft_npz_path=result.hft_npz_path,
            output_path=latency_output,
            mul_entry=args.mul_entry,
            offset_entry_ns=args.offset_entry_ns,
            mul_resp=args.mul_resp,
            offset_resp_ns=args.offset_resp_ns,
        )
        print(f"- latency npz: {latency.latency_npz_path}")
        print(f"- latency rows: {latency.row_count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
