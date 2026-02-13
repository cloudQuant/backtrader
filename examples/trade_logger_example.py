#!/usr/bin/env python
"""TradeLogger Observer Example - Demonstrates comprehensive logging.

This example shows how to use the TradeLogger observer for automatic
logging of orders, trades, positions, indicators, and signals.

Features demonstrated:
- Automatic order logging (order.log)
- Automatic trade logging (trade.log)
- Automatic position logging (position.log) - every bar
- Automatic indicator logging (indicator.log) - every bar
- Automatic signal logging (signal.log) - on buy/sell
- Position snapshot (current_position.yaml)
- Optional MySQL logging (disabled by default)

Usage:
    python trade_logger_example.py
"""

import datetime
import os
import sys

# Add backtrader to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import backtrader as bt


class SMAStrategy(bt.Strategy):
    """Simple SMA crossover strategy for demonstrating TradeLogger.

    Buys when close crosses above SMA, sells when close crosses below SMA.
    """

    params = (
        ('sma_period', 20),
        ('print_log', True),
    )

    def __init__(self):
        """Initialize indicators."""
        self.sma = bt.indicators.SimpleMovingAverage(
            self.data.close, period=self.p.sma_period
        )
        self.rsi = bt.indicators.RSI(self.data.close, period=14)
        self.crossover = bt.indicators.CrossOver(self.data.close, self.sma)

    def next(self):
        """Execute strategy logic."""
        if self.p.print_log:
            self.log(f'Close: {self.data.close[0]:.2f}, SMA: {self.sma[0]:.2f}, RSI: {self.rsi[0]:.2f}')

        if not self.position:
            if self.crossover > 0:
                self.log('BUY CREATE')
                self.buy()
        else:
            if self.crossover < 0:
                self.log('SELL CREATE')
                self.sell()

    def notify_order(self, order):
        """Handle order notifications."""
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'BUY EXECUTED, Price: {order.executed.price:.2f}')
            else:
                self.log(f'SELL EXECUTED, Price: {order.executed.price:.2f}')

    def notify_trade(self, trade):
        """Handle trade notifications."""
        if trade.isclosed:
            self.log(f'TRADE PROFIT, GROSS: {trade.pnl:.2f}, NET: {trade.pnlcomm:.2f}')


def run_example():
    """Run the TradeLogger example."""
    # Create cerebro instance
    cerebro = bt.Cerebro()

    # Add strategy
    cerebro.addstrategy(SMAStrategy, sma_period=15, print_log=True)

    # Use existing data file: 113013.csv (bond data)
    data_file = os.path.join(os.path.dirname(__file__), '113013.csv')
    data = bt.feeds.GenericCSVData(
        dataname=data_file,
        dtformat='%Y-%m-%d',
        datetime=2,      # TRADE_DATE
        open=3,          # OPEN_PRICE
        high=4,          # HIGH_PRICE
        low=5,           # LOW_PRICE
        close=6,         # CLOSE_PRICE
        volume=7,        # VOLUME
        openinterest=-1,
        headers=True,
    )
    cerebro.adddata(data,name="test")

    # Add TradeLogger observer - this is the key part!
    # All logging is automatic once added
    log_dir = os.path.join(os.path.dirname(__file__), 'logs')
    cerebro.addobserver(
        bt.observers.TradeLogger,
        log_dir=log_dir,
        log_orders=True,
        log_trades=True,
        log_positions=True,
        log_indicators=True,
        log_signals=True,
        log_position_snapshot=True,
        log_format='json',
        log_to_console=True,
        # MySQL disabled by default - uncomment to enable
        # mysql_enabled=True,
        # mysql_host='localhost',
        # mysql_port=3306,
        # mysql_user='root',
        # mysql_password='your_password',
        # mysql_database='backtrader',
    )

    # Set initial cash
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.001)

    # Print starting portfolio value
    print(f'Starting Portfolio Value: {cerebro.broker.getvalue():.2f}')

    # Run backtest
    cerebro.run()

    # Print final portfolio value
    print(f'Final Portfolio Value: {cerebro.broker.getvalue():.2f}')

    # Print log file locations
    print(f'\nLog files created in: {log_dir}')
    print('  - order.log      : All order status changes')
    print('  - trade.log      : All trade openings/closings')
    print('  - position.log   : Position on every bar')
    print('  - indicator.log  : Indicator values on every bar')
    print('  - signal.log     : Buy/sell signals')
    print('  - current_position.yaml : Current position snapshot')


if __name__ == '__main__':
    # Check if data file exists
    data_file = os.path.join(os.path.dirname(__file__), '113013.csv')
    if not os.path.exists(data_file):
        print(f"Error: Data file not found: {data_file}")
        print("Please ensure the example data file exists.")
        sys.exit(1)

    print("=" * 60)
    print("TradeLogger Observer Example")
    print("=" * 60)
    print()

    run_example()

    print()
    print("=" * 60)
    print("Example completed successfully!")
    print("=" * 60)
