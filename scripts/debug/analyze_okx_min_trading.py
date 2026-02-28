#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Analyze minimum trading capital requirements for OKX trading pairs.

This script:
1. Fetches all OKX trading pair information
2. Calculates minimum trading amount for each pair (in USDT)
3. Sorts by required capital from low to high
4. Recommends trading pairs suitable for small capital testing
"""

import ccxt
import sys
from pathlib import Path

# Add project path
sys.path.insert(0, str(Path(__file__).parent))


def fetch_okx_markets():
    """Fetch OKX market information.

    Returns:
        tuple: (exchange, markets) where:
            - exchange: CCXT OKX instance
            - markets: Dictionary of market information
    """
    print("Connecting to OKX exchange...")
    exchange = ccxt.okx({
        'enableRateLimit': True,
    })

    print("Loading market data...")
    markets = exchange.load_markets()
    return exchange, markets


def analyze_min_trading_amount(exchange, markets, base_currency='USDT'):
    """Analyze minimum trading amount for trading pairs.

    Args:
        exchange: CCXT exchange instance.
        markets: Dictionary of market information.
        base_currency: Base currency for analysis, default USDT.

    Returns:
        list: List containing analysis results for each trading pair.
            Each element is a dict with keys: symbol, base, quote,
            price, min_amount, min_cost, required_usdt, maker_fee, taker_fee.
    """
    results = []

    print(f"\nAnalyzing {base_currency} trading pairs...")

    for symbol, market in markets.items():
        # Only analyze USDT trading pairs
        if not market['quote'] == base_currency:
            continue

        # Only analyze spot trading
        if market['type'] != 'spot':
            continue

        # Only analyze active trading pairs
        if not market['active']:
            continue

        try:
            # Get current price
            ticker = exchange.fetch_ticker(symbol)
            current_price = ticker['last']

            if current_price is None or current_price == 0:
                continue

            # Get minimum trading volume limits
            limits = market['limits']
            min_amount = limits['amount']['min']  # Minimum amount
            min_cost = limits['cost']['min']      # Minimum cost (USDT)

            # Calculate actual minimum capital required
            # OKX minimum trading amount is usually the greater of min_cost and (min_amount * price)
            if min_cost is not None and min_cost > 0:
                required_usdt = min_cost
            elif min_amount is not None and min_amount > 0:
                required_usdt = min_amount * current_price
            else:
                # Use default if no explicit limit
                required_usdt = 1.0  # Default minimum 1 USDT

            # Get trading fee tier
            # OKX default maker fee: 0.08%, taker fee: 0.1%
            maker_fee = 0.0008  # 0.08%
            taker_fee = 0.001   # 0.1%

            result = {
                'symbol': symbol,
                'base': market['base'],      # Base currency (e.g., BTC)
                'quote': market['quote'],    # Quote currency (USDT)
                'price': current_price,
                'min_amount': min_amount,
                'min_cost': min_cost,
                'required_usdt': required_usdt,
                'maker_fee': maker_fee,
                'taker_fee': taker_fee,
            }

            results.append(result)

        except Exception as e:
            # Skip trading pairs that fail to fetch
            continue

    return results


def print_analysis_results(results, top_n=20):
    """Print analysis results.

    Args:
        results: List of analysis results.
        top_n: Number of top results to display.
    """
    if not results:
        print("No available trading pairs found")
        return

    # Sort by required USDT from low to high
    sorted_results = sorted(results, key=lambda x: x['required_usdt'])

    print(f"\n{'='*100}")
    print(f"OKX {results[0]['quote']} Trading Pair Minimum Capital Analysis ({len(results)} pairs)")
    print(f"{'='*100}\n")

    # Print header
    print(f"{'Rank':<5} {'Pair':<20} {'Current Price':<15} {'Min Amount(USDT)':<18} {'Buyable Qty':<15}")
    print(f"{'-'*100}")

    # Print top N
    for i, result in enumerate(sorted_results[:top_n], 1):
        symbol = result['symbol']
        price = result['price']
        required = result['required_usdt']

        # Calculate buyable amount
        buyable_amount = required / price

        print(f"{i:<5} {symbol:<20} ${price:<14.4f} ${required:<17.2f} {buyable_amount:<15.6f}")

    print(f"\n{'='*100}")

    # Statistics
    min_required = sorted_results[0]['required_usdt']
    max_required = sorted_results[-1]['required_usdt']
    avg_required = sum(r['required_usdt'] for r in sorted_results) / len(sorted_results)

    print(f"\nStatistics:")
    print(f"  Minimum Trading Amount: ${min_required:.2f} USDT")
    print(f"  Maximum Trading Amount: ${max_required:.2f} USDT")
    print(f"  Average Trading Amount: ${avg_required:.2f} USDT")

    # Recommend trading pairs for small capital testing (less than 10 USDT)
    print(f"\nRecommended Pairs for Small Capital Testing (< 10 USDT):")
    small_trades = [r for r in sorted_results if r['required_usdt'] <= 10]
    if small_trades:
        for i, result in enumerate(small_trades[:10], 1):
            print(f"  {i}. {result['symbol']}: ${result['required_usdt']:.2f} USDT")
    else:
        print("  No trading pairs found under 10 USDT")


def recommend_best_pairs(results, budget_usdt):
    """Recommend best trading pairs based on budget.

    Args:
        results: List of analysis results.
        budget_usdt: User budget in USDT.
    """
    sorted_results = sorted(results, key=lambda x: x['required_usdt'])

    print(f"\n{'='*100}")
    print(f"Recommended Trading Pairs for ${budget_usdt} USDT Budget")
    print(f"{'='*100}\n")

    # Find trading pairs within budget
    affordable = [r for r in sorted_results if r['required_usdt'] <= budget_usdt]

    if not affordable:
        print(f"Sorry, budget ${budget_usdt} USDT is insufficient for any trading")
        print(f"Minimum required: ${sorted_results[0]['required_usdt']:.2f} USDT")
        return

    print(f"Total {len(affordable)} trading pairs fit your budget\n")

    # Recommendation strategy: select high volume, stable coins
    # Here simply recommend top few
    print("Recommended Trading Pairs (sorted by capital requirement):")
    print(f"{'Rank':<5} {'Pair':<20} {'Required Amount':<15} {'Trades Possible':<15} {'Suggested Use'}")
    print(f"{'-'*100}")

    for i, result in enumerate(affordable[:10], 1):
        trades_possible = int(budget_usdt / result['required_usdt'])
        symbol = result['symbol']
        required = result['required_usdt']

        # Give suggestions based on coin type
        base = result['base']
        if base in ['BTC', 'ETH']:
            usage = "Mainstream coins, suitable for long-term holding"
        elif base in ['SOL', 'ADA', 'DOT', 'AVAX']:
            usage = "Popular blockchain coins, moderate volatility"
        elif base in['DOGE', 'SHIB', 'PEPE']:
            usage = "Meme coins, high volatility, be cautious"
        else:
            usage = "Suitable for testing and practice"

        print(f"{i:<5} {symbol:<20} ${required:<14.2f} {trades_possible:<15} {usage}")


def main():
    """Main function to analyze OKX minimum trading amounts.

    Fetches market data, analyzes minimum capital requirements,
    prints results and recommendations for different budget levels.
    """
    try:
        # Fetch market data
        exchange, markets = fetch_okx_markets()

        # Analyze USDT trading pairs
        results = analyze_min_trading_amount(exchange, markets, 'USDT')

        # Print analysis results
        print_analysis_results(results, top_n=30)

        # Analyze different budget ranges
        budgets = [1, 5, 10, 20, 50, 100]
        print(f"\n{'='*100}")
        print("Number of Tradable Pairs by Budget:")
        print(f"{'='*100}\n")

        for budget in budgets:
            affordable = len([r for r in results if r['required_usdt'] <= budget])
            print(f"  Budget ${budget:3d} USDT: {affordable:3d} tradable pairs")

        # Additional analysis: low price coins (suitable for small capital)
        print(f"\n{'='*100}")
        print("Low Price Coin Recommendations (price < $0.1, can buy large quantity with little capital):")
        print(f"{'='*100}\n")

        low_price = [r for r in results if r['price'] < 0.1]
        low_price_sorted = sorted(low_price, key=lambda x: x['price'])

        print(f"{'Rank':<5} {'Pair':<20} {'Price':<15} {'$1 Can Buy':<15} {'$10 Can Buy':<15}")
        print(f"{'-'*100}")

        for i, result in enumerate(low_price_sorted[:15], 1):
            price = result['price']
            buy_1_usdt = 1.0 / price
            buy_10_usdt = 10.0 / price

            print(f"{i:<5} {result['symbol']:<20} ${price:<14.6f} {buy_1_usdt:<15.2f} {buy_10_usdt:<15.2f}")

        print(f"\n{'='*100}")
        print("Analysis Complete!")
        print(f"{'='*100}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
