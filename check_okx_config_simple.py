#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""OKX Configuration Check Tool - Simple version without Unicode characters."""

import sys
from pathlib import Path
import ccxt

# Add project path
sys.path.insert(0, str(Path(__file__).parent))

from backtrader.ccxt import load_ccxt_config_from_env


def check_api_config():
    """Check API configuration"""
    print("=" * 80)
    print("1. Check API Configuration")
    print("=" * 80)

    try:
        config = load_ccxt_config_from_env('okx')
        print("[OK] API keys loaded successfully")
        print(f"  - apiKey: {'*' * 20}{config.get('apiKey', '')[-4:]}")
        print(f"  - secret: {'*' * 20}{config.get('secret', '')[-4:]}")
        print(f"  - password: {'*' * 20}{config.get('password', '')[-4:]}")
        return config
    except Exception as e:
        print(f"[FAIL] API configuration failed: {e}")
        print("\nPlease configure in .env file:")
        print("OKX_API_KEY=your_api_key")
        print("OKX_SECRET=your_secret")
        print("OKX_PASSWORD=your_password")
        return None


def check_api_connection(config):
    """Check API connection"""
    print("\n" + "=" * 80)
    print("2. Check API Connection")
    print("=" * 80)

    try:
        exchange = ccxt.okx(config)

        # Test fetching balance
        balance = exchange.fetch_balance()
        print("[OK] API connection successful")

        # Check USDT balance
        if 'USDT' in balance['total']:
            usdt_balance = balance['total']['USDT']
            usdt_free = balance['free']['USDT']
            usdt_used = balance['used']['USDT']
            print(f"  - USDT Total: {usdt_balance:.2f}")
            print(f"  - USDT Available: {usdt_free:.2f}")
            print(f"  - USDT Used: {usdt_used:.2f}")

            # Check swap account
            if 'USDT:USDT' in balance.get('total', {}):
                swap_balance = balance['total']['USDT:USDT']
                print(f"  - Swap Account Balance: {swap_balance:.2f} USDT")
        else:
            print("  [WARN] USDT balance not found")

        return exchange, balance

    except Exception as e:
        print(f"[FAIL] API connection failed: {e}")
        import traceback
        traceback.print_exc()
        return None, None


def check_dogs_swap_market(exchange):
    """Check DOGS/USDT perpetual contract"""
    print("\n" + "=" * 80)
    print("3. Check DOGS/USDT Perpetual Contract")
    print("=" * 80)

    try:
        # Load markets
        markets = exchange.load_markets()

        # Check DOGS/USDT:USDT (perpetual contract)
        symbol = 'DOGS/USDT:USDT'

        if symbol not in markets:
            print(f"[FAIL] {symbol} not found")
            print("\nAvailable DOGS pairs:")
            dogs_pairs = [s for s in markets.keys() if 'DOGS' in s]
            for pair in dogs_pairs:
                print(f"  - {pair}")
            return False

        market = markets[symbol]
        print(f"[OK] Found {symbol} perpetual contract")

        # Get market info
        print(f"  - Base: {market['base']}")
        print(f"  - Quote: {market['quote']}")
        print(f"  - Type: {market['type']}")
        print(f"  - Active: {market['active']}")

        # Get current price
        ticker = exchange.fetch_ticker(symbol)
        current_price = ticker['last']
        print(f"  - Current Price: ${current_price:.6f}")

        # Get trading limits
        limits = market['limits']
        min_amount = limits['amount']['min']
        min_cost = limits['cost']['min']

        print(f"\nTrading Limits:")
        print(f"  - Min Amount: {min_amount}")
        print(f"  - Min Cost: ${min_cost}")

        # Calculate amount for 0.4 USDT order
        order_size = 0.4  # USDT
        buy_amount = order_size / current_price
        print(f"\nOrder Test:")
        print(f"  - Order Size: ${order_size} USDT")
        print(f"  - Buyable Amount: {buy_amount:.2f} DOGS")

        # Check if meets minimum requirement
        if buy_amount >= min_amount:
            print(f"  [OK] Meets minimum requirement (>= {min_amount})")
        else:
            print(f"  [FAIL] Does not meet minimum requirement (need >= {min_amount})")

        # Calculate fees
        maker_fee = 0.0002  # OKX swap maker fee
        taker_fee = 0.0005  # OKX swap taker fee
        fee_maker = order_size * maker_fee
        fee_taker = order_size * taker_fee

        print(f"\nFee Estimation:")
        print(f"  - Maker Fee Rate: 0.02%")
        print(f"  - Taker Fee Rate: 0.05%")
        print(f"  - Maker Fee: ${fee_maker:.6f} USDT")
        print(f"  - Taker Fee: ${fee_taker:.6f} USDT")
        print(f"  - Fee Percentage: {(fee_taker / order_size * 100):.2f}%")

        return True, market, current_price, buy_amount

    except Exception as e:
        print(f"[FAIL] Check failed: {e}")
        import traceback
        traceback.print_exc()
        return False, None, None, None


def print_recommendations():
    """Print testing recommendations"""
    print("\n" + "=" * 80)
    print("4. Testing Recommendations")
    print("=" * 80)

    print("\n[IMPORTANT] Suggestions:")
    print("Please test the strategy in the following environments:")
    print("\n1. OKX Sandbox (Demo Trading):")
    print("   - URL: https://www.okx.com/demo-trading")
    print("   - Provides test API keys")
    print("   - No real money involved")

    print("\n2. Paper Trading:")
    print("   - Use historical data for testing")
    print("   - No exchange connection needed")

    print("\n3. Small Live Trading:")
    print("   - Use minimum amount (0.4 USDT)")
    print("   - Verify strategy logic")


def print_summary(config_ok, connection_ok, market_ok):
    """Print summary"""
    print("\n" + "=" * 80)
    print("Check Summary")
    print("=" * 80)

    checks = [
        ("API Configuration", config_ok),
        ("API Connection", connection_ok),
        ("DOGS/USDT Contract", market_ok),
    ]

    all_ok = True
    for name, status in checks:
        if status:
            print(f"[OK] {name}: Passed")
        else:
            print(f"[FAIL] {name}: Failed")
            all_ok = False

    print("\n" + "=" * 80)

    if all_ok:
        print("[OK] All checks passed! You can run the strategy now")
        print("\nRun command:")
        print("python examples/backtrader_ccxt_okx_dogs_bollinger.py")
    else:
        print("[FAIL] Some checks failed, please fix the issues above")

    print("=" * 80)


def main():
    """Main function"""
    print("\n")
    print("=" * 80)
    print(" " * 15 + "OKX DOGS/USDT Strategy Configuration Check")
    print("=" * 80)

    # 1. Check API config
    config = check_api_config()
    config_ok = config is not None

    # 2. Check API connection
    if config_ok:
        exchange, balance = check_api_connection(config)
        connection_ok = exchange is not None
    else:
        exchange, balance = None, None
        connection_ok = False

    # 3. Check DOGS/USDT contract
    if connection_ok:
        market_ok, market, price, amount = check_dogs_swap_market(exchange)
    else:
        market_ok = False

    # 4. Recommendations
    print_recommendations()

    # 5. Print summary
    print_summary(config_ok, connection_ok, market_ok)


if __name__ == '__main__':
    main()
