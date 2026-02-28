#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Quick strategy logic validation test script.

Tests strategy signal generation using simulated data,
no exchange connection required.
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np
import backtrader as bt

# Add project path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / 'examples'))

# Import from examples directory
from backtrader_ccxt_okx_dogs_bollinger import BollingerBandsStrategy


class TestStrategy(BollingerBandsStrategy):
    """Test strategy version with additional debugging information."""

    def next(self):
        """Called on each bar.

        Implements the core trading logic:
        - Check stop loss for existing positions
        - Buy when price breaks above upper Bollinger Band
        - Sell when price falls below lower Bollinger Band
        """
        # Ensure no pending orders
        if self.order:
            return

        # Ensure sufficient data (at least period+1 bars)
        if len(self.data) < self.p.period + 1:
            return

        # Get current price and indicator values
        current_price = self.data.close[0]
        upper_band = self.top[0]
        lower_band = self.bot[0]
        atr_value = self.atr[0]

        # Check if indicator values are valid
        if any(x is None for x in [current_price, upper_band, lower_band, atr_value]):
            return

        # Get current position size (spot)
        position_size = self.getposition().size

        # Calculate order size (based on USDT amount)
        size = self.p.order_size / current_price

        # Print status every 10 bars
        if len(self.data) % 10 == 0:
            print(f"\n[Bar {len(self.data)}]")
            print(f"  Price: ${current_price:.6f}")
            print(f"  Upper Band: ${upper_band:.6f}")
            print(f"  Lower Band: ${lower_band:.6f}")
            print(f"  ATR: {atr_value:.6f}")
            print(f"  Position: {position_size:.2f}")

            if position_size > 0:
                print(f"  Stop Loss: ${self.long_stop_price:.6f}")

        # === Spot Long Logic ===
        # Check stop loss
        if position_size > 0 and self.long_stop_price is not None:
            if current_price <= self.long_stop_price:
                print(f"\n[Signal] Stop Loss Triggered: Current=${current_price:.6f}, Stop=${self.long_stop_price:.6f}")
                self.order = self.sell(size=position_size)
                self.long_stop_price = None
                self.entry_price = None
                return

        # Break above upper band -> Buy
        if position_size == 0 and current_price > upper_band:
            print(f"\n[Signal] Upper Band Breakout -> Buy: Price=${current_price:.6f}, Upper=${upper_band:.6f}")
            self.order = self.buy(size=size)
            self.entry_price = current_price
            self.long_stop_price = current_price - (atr_value * self.p.atr_mult)

        # Fall below lower band -> Sell
        elif position_size > 0 and current_price < lower_band:
            print(f"\n[Signal] Lower Band Breakdown -> Sell: Price=${current_price:.6f}, Lower=${lower_band:.6f}")
            self.order = self.sell(size=position_size)
            self.long_stop_price = None
            self.entry_price = None


def generate_test_data():
    """Generate simulated test data.

    Returns:
        pd.DataFrame: DataFrame with OHLCV data containing 200 bars
        of simulated price data based on DOGS current price.
    """
    print("=" * 80)
    print("Generating Test Data")
    print("=" * 80)

    # Generate 200 bars of 1-minute simulated data
    np.random.seed(42)

    # Base price $0.00004 (DOGS current price)
    base_price = 0.00004

    # Generate price data (random walk)
    n = 200
    returns = np.random.normal(0.001, 0.02, n)  # 1% volatility
    prices = [base_price]

    for ret in returns:
        prices.append(prices[-1] * (1 + ret))

    # Generate OHLCV data
    data = []
    from datetime import datetime, timedelta
    start_time = datetime(2025, 1, 20, 0, 0, 0)

    for i in range(n):
        close = prices[i]
        # Add some random fluctuation
        high = close * (1 + abs(np.random.normal(0, 0.01)))
        low = close * (1 - abs(np.random.normal(0, 0.01)))
        open_price = low + (high - low) * np.random.random()
        volume = np.random.randint(1000000, 10000000)

        data.append({
            'datetime': start_time + timedelta(minutes=i),
            'open': open_price,
            'high': high,
            'low': low,
            'close': close,
            'volume': volume,
        })

    df = pd.DataFrame(data)
    print(f"Generated {len(df)} bars of OHLCV data")
    print(f"Price Range: ${df['close'].min():.6f} - ${df['close'].max():.6f}")
    print(f"Average Price: ${df['close'].mean():.6f}")

    return df


class TestFeed(bt.feeds.PandasData):
    """Test data feed for backtrader.

    Attributes:
        params: Data feed parameters mapping column names.
    """
    params = (
        ('datetime', None),
        ('open', -1),
        ('high', -1),
        ('low', -1),
        ('close', -1),
        ('volume', -1),
        ('openinterest', -1),
    )


def run_test():
    """Run the strategy logic test.

    Generates test data, creates a Cerebro engine with the test strategy,
    runs the backtest, and prints performance results.
    """
    # Generate test data
    df = generate_test_data()

    # Create Cerebro
    cerebro = bt.Cerebro()

    # Add strategy
    cerebro.addstrategy(
        TestStrategy,
        period=60,
        devfactor=2.0,
        order_size=0.4,
        atr_period=14,
        atr_mult=2.0,
    )

    # Set initial capital
    cerebro.broker.setcash(10.0)
    cerebro.broker.setcommission(commission=0.001)  # 0.1% fee

    # Add data
    data = TestFeed(dataname=df)
    cerebro.adddata(data)

    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    # Run
    print("\n" + "=" * 80)
    print("Running Strategy Test")
    print("=" * 80)
    print(f"Initial Capital: {cerebro.broker.getvalue():.2f} USDT")
    print()

    try:
        results = cerebro.run()
        strat = results[0]

        # Print results
        print("\n" + "=" * 80)
        print("Test Results")
        print("=" * 80)

        if hasattr(strat.analyzers, 'trades'):
            trades = strat.analyzers.trades.get_analysis()
            if 'total' in trades:
                total = trades['total']['total']
                print(f"Total Trades: {total}")

            if 'won' in trades:
                won = trades['won']['total']
                print(f"Winning Trades: {won}")

            if 'lost' in trades:
                lost = trades['lost']['total']
                print(f"Losing Trades: {lost}")

            if 'win' in trades:
                win_rate = trades['win']
                print(f"Win Rate: {win_rate:.2%}")

        if hasattr(strat.analyzers, 'returns'):
            returns = strat.analyzers.returns.get_analysis()
            if 'rtot' in returns:
                print(f"Total Return: {returns['rtot']:.2%}")

        final_value = cerebro.broker.getvalue()
        print(f"\nFinal Capital: {final_value:.2f} USDT")
        print(f"Total Profit: {final_value - 10.0:.2f} USDT")
        print(f"Return Rate: {(final_value - 10.0) / 10.0 * 100:.2f}%")

        print("\n" + "=" * 80)
        print("[OK] Strategy Test Complete!")
        print("=" * 80)

    except Exception as e:
        print(f"\n[ERROR] Test Failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    run_test()
