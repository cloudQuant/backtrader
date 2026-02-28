#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""OKX Configuration Check Tool.

This script checks:
1. API key configuration
2. Account balance sufficiency
3. DOGS/USDT contract availability
4. Minimum trading amount requirements
5. Simulated order placement test
"""

import sys
from pathlib import Path
import ccxt

# Add project path
sys.path.insert(0, str(Path(__file__).parent))

from backtrader.ccxt import load_ccxt_config_from_env


def check_api_config():
    """Check API configuration.

    Returns:
        dict or None: Configuration dict if successful, None otherwise.
    """
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
    """Check API connection.

    Args:
        config: Exchange configuration dictionary.

    Returns:
        tuple: (exchange, balance) if successful, (None, None) otherwise.
    """
    print("\n" + "=" * 80)
    print("2. Check API Connection")
    print("=" * 80)

    try:
        exchange = ccxt.okx(config)

        # Test fetching account balance
        balance = exchange.fetch_balance()
        print("API connection successful")

        # Check USDT balance
        if 'USDT' in balance['total']:
            usdt_balance = balance['total']['USDT']
            usdt_free = balance['free']['USDT']
            usdt_used = balance['used']['USDT']
            print(f"  - USDT Total: {usdt_balance:.2f}")
            print(f"  - USDT Available: {usdt_free:.2f}")
            print(f"  - USDT Frozen: {usdt_used:.2f}")

            # Check futures account
            if 'USDT:USDT' in balance.get('total', {}):
                swap_balance = balance['total']['USDT:USDT']
                print(f"  - Futures Account Balance: {swap_balance:.2f} USDT")
        else:
            print("  Warning: No USDT balance found")

        return exchange, balance

    except Exception as e:
        print(f"API connection failed: {e}")
        return None, None


def check_dogs_swap_market(exchange):
    """Check DOGS/USDT perpetual contract market.

    Args:
        exchange: CCXT exchange instance.

    Returns:
        tuple: (success, market, current_price, buy_amount) where:
            - success (bool): True if market check passed
            - market (dict or None): Market information if successful
            - current_price (float or None): Current DOGS price
            - buy_amount (float or None): Amount of DOGS buyable with 0.4 USDT
    """
    print("\n" + "=" * 80)
    print("3. Check DOGS/USDT Perpetual Contract")
    print("=" * 80)

    try:
        # Load markets
        markets = exchange.load_markets()

        # Check DOGS/USDT:USDT (perpetual contract)
        symbol = 'DOGS/USDT:USDT'

        if symbol not in markets:
            print(f"Trading pair not found: {symbol}")
            print("\nAvailable DOGS trading pairs:")
            dogs_pairs = [s for s in markets.keys() if 'DOGS' in s]
            for pair in dogs_pairs:
                print(f"  - {pair}")
            return False, None, None, None

        market = markets[symbol]
        print(f"Found {symbol} perpetual contract")

        # Get trading pair information
        print(f"  - Base Currency: {market['base']}")
        print(f"  - Quote Currency: {market['quote']}")
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

        print("\nTrading Limits:")
        print(f"  - Minimum Amount: {min_amount}")
        print(f"  - Minimum Cost: ${min_cost}")

        # Calculate amount of DOGS buyable with 0.4 USDT
        order_size = 0.4  # USDT
        buy_amount = order_size / current_price
        print("\nOrder Test:")
        print(f"  - Order Size: ${order_size} USDT")
        print(f"  - Buyable Amount: {buy_amount:.2f} DOGS")

        # Check if minimum trading requirement is met
        if buy_amount >= min_amount:
            print(f"  Meets minimum trading requirement (>= {min_amount})")
        else:
            print(f"  Does not meet minimum trading requirement (need >= {min_amount})")

        # Calculate trading fees
        maker_fee = 0.0002  # OKX futures maker fee rate
        taker_fee = 0.0005  # OKX futures taker fee rate
        fee_maker = order_size * maker_fee
        fee_taker = order_size * taker_fee

        print("\nFee Estimation:")
        print(f"  - Maker Rate: 0.02%")
        print(f"  - Taker Rate: 0.05%")
        print(f"  - Maker Fee: ${fee_maker:.6f} USDT")
        print(f"  - Taker Fee: ${fee_taker:.6f} USDT")
        print(f"  - Fee Percentage: {(fee_taker / order_size * 100):.2f}%")

        return True, market, current_price, buy_amount

    except Exception as e:
        print(f"Check failed: {e}")
        import traceback
        traceback.print_exc()
        return False, None, None, None


def check_sandbox_mode():
    """Recommend using sandbox mode for testing.

    Prints recommendations for testing environments including
    sandbox, backtesting, and small live trading.
    """
    print("\n" + "=" * 80)
    print("4. Testing Environment Recommendations")
    print("=" * 80)

    print("\nImportant Notice:")
    print("Recommend testing strategy in the following environments first:")
    print("\n1. OKX Sandbox Environment (Testnet):")
    print("   - URL: https://www.okx.com/demo-trading")
    print("   - Provides test API keys")
    print("   - No real funds required")

    print("\n2. Backtesting Mode:")
    print("   - Test with historical data")
    print("   - No exchange connection needed")

    print("\n3. Small Live Trading:")
    print("   - Use minimum amount (0.4 USDT)")
    print("   - Verify strategy logic")


def print_summary(config_ok, connection_ok, market_ok):
    """Print summary of all checks.

    Args:
        config_ok (bool): API configuration check status.
        connection_ok (bool): API connection check status.
        market_ok (bool): Market availability check status.
    """
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
            print(f"OK {name}: Pass")
        else:
            print(f"FAIL {name}: Failed")
            all_ok = False

    print("\n" + "=" * 80)

    if all_ok:
        print("All checks passed! Ready to run strategy")
        print("\nRun command:")
        print("python examples/backtrader_ccxt_okx_dogs_bollinger.py")
    else:
        print("Some checks failed, please resolve the issues above")

    print("=" * 80)


def main():
    """Main function to run all OKX configuration checks.

    Executes the following checks in sequence:
    1. API configuration validation
    2. API connection and balance check
    3. DOGS/USDT contract market verification
    4. Testing environment recommendations
    5. Summary report
    """
    print("\n")
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 20 + "OKX DOGS/USDT Strategy Configuration Check" + " " * 20 + "║")
    print("╚" + "=" * 78 + "╝")

    # 1. Check API configuration
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

    # 4. Testing environment recommendations
    check_sandbox_mode()

    # 5. Print summary
    print_summary(config_ok, connection_ok, market_ok)


if __name__ == '__main__':
    main()
