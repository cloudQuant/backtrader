#!/usr/bin/env python
"""Test data generation tool for Iteration 138.

Generates synthetic tick, orderbook, funding rate, and bar data files
in CSV and JSONL formats for testing and benchmarking.

Usage::

    # Generate all data types
    python tools/generate_test_data.py --output-dir tests/datas/tick_data

    # Generate only ticks
    python tools/generate_test_data.py --type tick --rows 100000

    # Generate with custom symbol
    python tools/generate_test_data.py --symbol ETH/USDT --base-price 3000
"""

import argparse
import csv
import json
import math
import os
import random
import sys
import time


def generate_ticks(num_rows, symbol='BTC/USDT', base_price=50000.0,
                   volatility=0.0002, start_ts=1700000000.0, interval_ms=50):
    """Generate synthetic tick data.

    Args:
        num_rows: Number of ticks to generate.
        symbol: Trading pair symbol.
        base_price: Starting price.
        volatility: Per-tick price volatility (fraction).
        start_ts: Starting unix timestamp.
        interval_ms: Average interval between ticks in milliseconds.

    Yields:
        dict with tick fields.
    """
    price = base_price
    ts = start_ts

    for i in range(num_rows):
        # Random walk price
        change = random.gauss(0, volatility * price)
        price = max(price + change, base_price * 0.5)

        # Random volume (log-normal)
        volume = round(random.lognormvariate(-1, 1.5), 6)

        # Random direction
        direction = 'buy' if random.random() > 0.5 else 'sell'

        # Random interval
        dt = random.expovariate(1.0 / interval_ms) / 1000.0
        ts += dt

        yield {
            'timestamp': round(ts, 6),
            'symbol': symbol,
            'price': round(price, 2),
            'volume': volume,
            'direction': direction,
            'trade_id': f't{i}',
        }


def generate_orderbook(num_rows, symbol='BTC/USDT', base_price=50000.0,
                       depth=20, volatility=0.0001,
                       start_ts=1700000000.0, interval_ms=100):
    """Generate synthetic order book snapshots.

    Yields:
        dict with orderbook fields.
    """
    mid_price = base_price
    ts = start_ts

    for i in range(num_rows):
        mid_price += random.gauss(0, volatility * mid_price)
        mid_price = max(mid_price, base_price * 0.5)

        spread = mid_price * random.uniform(0.0001, 0.001)
        best_bid = round(mid_price - spread / 2, 2)
        best_ask = round(mid_price + spread / 2, 2)

        bids = []
        asks = []
        for d in range(depth):
            bid_price = round(best_bid - d * mid_price * 0.0001, 2)
            ask_price = round(best_ask + d * mid_price * 0.0001, 2)
            bid_vol = round(random.lognormvariate(0, 1.5), 4)
            ask_vol = round(random.lognormvariate(0, 1.5), 4)
            bids.append([bid_price, bid_vol])
            asks.append([ask_price, ask_vol])

        dt = random.expovariate(1.0 / interval_ms) / 1000.0
        ts += dt

        yield {
            'timestamp': round(ts, 6),
            'symbol': symbol,
            'bids': bids,
            'asks': asks,
        }


def generate_funding(num_rows, symbol='BTC/USDT', base_price=50000.0,
                     start_ts=1700000000.0, interval_s=28800):
    """Generate synthetic funding rate data (every 8h by default).

    Yields:
        dict with funding fields.
    """
    price = base_price
    ts = start_ts

    for i in range(num_rows):
        # Funding rate: small random around 0.01%
        rate = random.gauss(0.0001, 0.0003)
        rate = max(min(rate, 0.01), -0.01)

        price += random.gauss(0, 0.001 * price)
        price = max(price, base_price * 0.5)

        ts += interval_s + random.gauss(0, 10)

        yield {
            'timestamp': round(ts, 6),
            'symbol': symbol,
            'rate': round(rate, 8),
            'mark_price': round(price, 2),
            'next_funding_time': round(ts + interval_s, 6),
            'predicted_rate': round(rate * random.uniform(0.8, 1.2), 8),
        }


def generate_bars(num_rows, symbol='BTC/USDT', base_price=50000.0,
                  volatility=0.005, start_ts=1700000000.0, interval_s=60):
    """Generate synthetic OHLCV bar data.

    Yields:
        dict with bar fields.
    """
    price = base_price
    ts = start_ts

    for i in range(num_rows):
        open_price = price
        # Random walk within bar
        moves = [random.gauss(0, volatility * price) for _ in range(10)]
        cumulative = [open_price]
        for m in moves:
            cumulative.append(cumulative[-1] + m)

        high = max(cumulative)
        low = max(min(cumulative), open_price * 0.9)
        close = cumulative[-1]
        close = max(close, open_price * 0.9)

        volume = round(random.lognormvariate(3, 1.5), 4)
        ts += interval_s

        price = close

        yield {
            'timestamp': round(ts, 6),
            'symbol': symbol,
            'open': round(open_price, 2),
            'high': round(high, 2),
            'low': round(low, 2),
            'close': round(close, 2),
            'volume': volume,
        }


def write_tick_csv(filepath, rows):
    """Write tick data to CSV."""
    with open(filepath, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'timestamp', 'symbol', 'price', 'volume', 'direction', 'trade_id',
        ])
        writer.writeheader()
        count = 0
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def write_orderbook_jsonl(filepath, rows):
    """Write orderbook data to JSONL (JSON fields don't work well in CSV)."""
    count = 0
    with open(filepath, 'w') as f:
        for row in rows:
            f.write(json.dumps(row) + '\n')
            count += 1
    return count


def write_funding_csv(filepath, rows):
    """Write funding rate data to CSV."""
    with open(filepath, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'timestamp', 'rate', 'mark_price', 'next_funding_time', 'predicted_rate',
        ])
        writer.writeheader()
        count = 0
        for row in rows:
            out = {k: row[k] for k in writer.fieldnames if k in row}
            writer.writerow(out)
            count += 1
    return count


def write_bar_csv(filepath, rows):
    """Write bar data to CSV."""
    with open(filepath, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'timestamp', 'symbol', 'open', 'high', 'low', 'close', 'volume',
        ])
        writer.writeheader()
        count = 0
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def write_jsonl(filepath, rows):
    """Write any data to JSONL format."""
    count = 0
    with open(filepath, 'w') as f:
        for row in rows:
            f.write(json.dumps(row) + '\n')
            count += 1
    return count


def main():
    """Generate synthetic test data for backtrader testing and benchmarking.

    Parses command-line arguments and generates specified types of test data
    including tick data, order book snapshots, funding rates, and OHLCV bars.
    Output can be in CSV, JSONL, or both formats.

    The function uses argparse to handle the following options:
        --output-dir: Directory for output files (default: tests/datas/tick_data)
        --type: Data type to generate (tick, orderbook, funding, bar, all)
        --rows: Number of rows to generate (default: 10000)
        --symbol: Trading symbol (default: BTC/USDT)
        --base-price: Starting price (default: 50000.0)
        --seed: Random seed for reproducibility (default: 42)
        --format: Output format - csv, jsonl, or both (default: both)

    Returns:
        None. Results are written to files in the specified output directory.
    """
    parser = argparse.ArgumentParser(
        description='Generate synthetic test data for Iteration 138'
    )
    parser.add_argument('--output-dir', default='tests/datas/tick_data',
                        help='Output directory')
    parser.add_argument('--type', choices=['tick', 'orderbook', 'funding', 'bar', 'all'],
                        default='all', help='Data type to generate')
    parser.add_argument('--rows', type=int, default=10000,
                        help='Number of rows to generate')
    parser.add_argument('--symbol', default='BTC/USDT', help='Trading symbol')
    parser.add_argument('--base-price', type=float, default=50000.0,
                        help='Base price')
    parser.add_argument('--seed', type=int, default=42, help='Random seed')
    parser.add_argument('--format', choices=['csv', 'jsonl', 'both'],
                        default='both', help='Output format')

    args = parser.parse_args()
    random.seed(args.seed)
    os.makedirs(args.output_dir, exist_ok=True)

    data_types = [args.type] if args.type != 'all' else ['tick', 'orderbook', 'funding', 'bar']

    for dtype in data_types:
        print(f"Generating {args.rows} {dtype} records for {args.symbol}...")

        if dtype == 'tick':
            gen = lambda: generate_ticks(args.rows, args.symbol, args.base_price)
            if args.format in ('csv', 'both'):
                path = os.path.join(args.output_dir, f'{dtype}_{args.symbol.replace("/", "_")}.csv')
                n = write_tick_csv(path, gen())
                print(f"  → {path} ({n} rows)")
            if args.format in ('jsonl', 'both'):
                path = os.path.join(args.output_dir, f'{dtype}_{args.symbol.replace("/", "_")}.jsonl')
                n = write_jsonl(path, gen())
                print(f"  → {path} ({n} rows)")

        elif dtype == 'orderbook':
            gen = lambda: generate_orderbook(args.rows, args.symbol, args.base_price)
            path = os.path.join(args.output_dir, f'{dtype}_{args.symbol.replace("/", "_")}.jsonl')
            n = write_orderbook_jsonl(path, gen())
            print(f"  → {path} ({n} rows)")

        elif dtype == 'funding':
            gen = lambda: generate_funding(args.rows, args.symbol, args.base_price)
            if args.format in ('csv', 'both'):
                path = os.path.join(args.output_dir, f'{dtype}_{args.symbol.replace("/", "_")}.csv')
                n = write_funding_csv(path, gen())
                print(f"  → {path} ({n} rows)")
            if args.format in ('jsonl', 'both'):
                path = os.path.join(args.output_dir, f'{dtype}_{args.symbol.replace("/", "_")}.jsonl')
                n = write_jsonl(path, gen())
                print(f"  → {path} ({n} rows)")

        elif dtype == 'bar':
            gen = lambda: generate_bars(args.rows, args.symbol, args.base_price)
            if args.format in ('csv', 'both'):
                path = os.path.join(args.output_dir, f'{dtype}_{args.symbol.replace("/", "_")}.csv')
                n = write_bar_csv(path, gen())
                print(f"  → {path} ({n} rows)")
            if args.format in ('jsonl', 'both'):
                path = os.path.join(args.output_dir, f'{dtype}_{args.symbol.replace("/", "_")}.jsonl')
                n = write_jsonl(path, gen())
                print(f"  → {path} ({n} rows)")

    print("Done.")


if __name__ == '__main__':
    main()
