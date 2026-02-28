#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Bollinger Bands Breakout Strategy Parameter Optimization Script.

Optimizes Bollinger Bands strategy parameters using local Binance historical
data to find the optimal parameter combinations.

Data Source: Binance public data (ZIP/CSV format)
Strategy: Bollinger Bands breakout + ATR dynamic stop loss

Optimized Parameters:
    - period: Bollinger Bands period (10-100)
    - devfactor: Standard deviation multiplier (1.5-3.0)
    - atr_period: ATR period (7-21)
    - atr_mult: ATR stop loss multiplier (1.0-3.0)

Usage:
    python examples/optimize_bollinger_strategy.py --data-dir /path/to/data
    python examples/optimize_bollinger_strategy.py --data-dir "J:/binance-public-data/data/futures/um/monthly/klines/MINAUSDT/15m" --start-date 2024-01-01 --end-date 2024-12-31
"""

import os
import sys
import zipfile
import io
import argparse
from datetime import datetime
from pathlib import Path
from multiprocessing import Pool, cpu_count
from functools import partial

import pandas as pd
import backtrader as bt


# =============================================================================
# Data Loader - Load Binance ZIP/CSV Data
# =============================================================================

class BinanceZipCSVData(bt.feeds.PandasData):
    """Binance ZIP/CSV data loader.

    Binance data format:
    open_time, open, high, low, close, volume, close_time,
    quote_volume, count, taker_buy_volume, taker_buy_quote_volume, ignore
    """

    # Use column indices instead of column names (-1 means column not used)
    params = (
        ('datetime', None),  # Use DataFrame index as datetime
        ('open', 'open'),
        ('high', 'high'),
        ('low', 'low'),
        ('close', 'close'),
        ('volume', 'volume'),
        ('openinterest', None),
    )


def load_binance_data(data_dir: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """Load Binance ZIP/CSV data.

    Args:
        data_dir: Data directory path containing ZIP files.
        start_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD).

    Returns:
        Combined DataFrame with all loaded data.

    Raises:
        FileNotFoundError: If no ZIP files found in the directory.
        ValueError: If no data could be loaded from the ZIP files.
    """
    data_path = Path(data_dir)
    all_data = []

    # Get all ZIP files and sort them
    zip_files = sorted(data_path.glob('*.zip'))

    if not zip_files:
        raise FileNotFoundError(f"No ZIP files found in {data_dir}")

    print(f"Found {len(zip_files)} data files")

    for zip_file in zip_files:
        try:
            with zipfile.ZipFile(zip_file, 'r') as z:
                # Get CSV files inside the ZIP
                csv_files = [f for f in z.namelist() if f.endswith('.csv')]
                if not csv_files:
                    continue

                # Read CSV
                with z.open(csv_files[0]) as f:
                    df = pd.read_csv(f)
                    all_data.append(df)

        except Exception as e:
            print(f"Warning: Unable to read {zip_file}: {e}")
            continue

    if not all_data:
        raise ValueError("No data loaded from ZIP files")

    # Combine all data
    combined = pd.concat(all_data, ignore_index=True)

    # Convert timestamps
    combined['datetime'] = pd.to_datetime(combined['open_time'], unit='ms')

    # Ensure numeric types
    for col in ['open', 'high', 'low', 'close', 'volume']:
        combined[col] = pd.to_numeric(combined[col], errors='coerce')

    # Sort by time and remove duplicates
    combined = combined.sort_values('datetime').drop_duplicates(subset=['datetime'])

    # Date filtering
    if start_date:
        combined = combined[combined['datetime'] >= start_date]
    if end_date:
        combined = combined[combined['datetime'] <= end_date]

    # Set index
    combined = combined.set_index('datetime')

    print(f"Data loading complete: {len(combined)} records")
    print(f"Time range: {combined.index.min()} to {combined.index.max()}")

    return combined


# =============================================================================
# Bollinger Bands Breakout Strategy (Backtest Version)
# =============================================================================

class BollingerBandsStrategy(bt.Strategy):
    """Bollinger Bands breakout strategy (supports long and short).

    Trading logic:
    - Break above upper band -> Open long position
    - Break below middle band -> Close long position
    - Break below lower band -> Open short position
    - Break above middle band -> Close short position
    - ATR dynamic stop loss
    """

    params = (
        ('period', 60),           # Bollinger Bands period
        ('devfactor', 2.0),       # Standard deviation multiplier
        ('atr_period', 14),       # ATR period
        ('atr_mult', 2.0),        # ATR stop loss multiplier
        ('order_pct', 0.95),      # Percentage of capital to use per order
        ('use_stop_loss', True),  # Whether to enable stop loss
        ('printlog', False),      # Whether to print logs
    )

    def __init__(self):
        """Initialize strategy indicators and state."""
        # Bollinger Bands indicator
        self.bollinger = bt.indicators.BollingerBands(
            self.data.close,
            period=self.p.period,
            devfactor=self.p.devfactor
        )

        # ATR indicator
        self.atr = bt.indicators.ATR(
            self.data,
            period=self.p.atr_period
        )

        # Bollinger Bands lines
        self.mid = self.bollinger.mid
        self.top = self.bollinger.top
        self.bot = self.bollinger.bot

        # Trading state
        self.order = None
        self.long_stop_price = None
        self.short_stop_price = None
        self.entry_price = None

        # Statistics
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, txt, dt=None):
        """Log a message if logging is enabled.

        Args:
            txt: Message text to log.
            dt: Datetime for the log entry.
        """
        if self.p.printlog:
            dt = dt or self.datas[0].datetime.date(0)
            print(f'{dt.isoformat()} {txt}')

    def notify_order(self, order):
        """Handle order status updates.

        Args:
            order: The order object with updated status.
        """
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'BUY @ {order.executed.price:.6f}, Size: {order.executed.size}')
            else:
                self.log(f'SELL @ {order.executed.price:.6f}, Size: {order.executed.size}')

        self.order = None

    def notify_trade(self, trade):
        """Handle trade completion notifications.

        Args:
            trade: The trade object.
        """
        if trade.isclosed:
            self.trade_count += 1
            if trade.pnl > 0:
                self.win_count += 1
            else:
                self.loss_count += 1
            self.log(f'TRADE PNL: Gross={trade.pnl:.4f}, Net={trade.pnlcomm:.4f}')

    def next(self):
        """Main strategy logic called on each bar."""
        # Wait for order completion
        if self.order:
            return

        # Ensure sufficient data
        if len(self.data) < self.p.period + 1:
            return

        current_price = self.data.close[0]
        upper_band = self.top[0]
        lower_band = self.bot[0]
        middle_band = self.mid[0]
        atr_value = self.atr[0]

        # Check indicator validity
        if any(x is None or x != x for x in [current_price, upper_band, lower_band, middle_band, atr_value]):
            return

        position_size = self.position.size

        # Calculate order quantity
        if position_size == 0:
            cash = self.broker.getcash()
            size = int((cash * self.p.order_pct) / current_price)
            if size <= 0:
                return
        else:
            size = abs(position_size)

        # === Stop loss check ===
        if self.p.use_stop_loss:
            # Long position stop loss
            if position_size > 0 and self.long_stop_price:
                if current_price <= self.long_stop_price:
                    self.log(f'LONG STOP LOSS @ {current_price:.6f}')
                    self.order = self.sell(size=position_size)
                    self.long_stop_price = None
                    self.entry_price = None
                    return

            # Short position stop loss
            elif position_size < 0 and self.short_stop_price:
                if current_price >= self.short_stop_price:
                    self.log(f'SHORT STOP LOSS @ {current_price:.6f}')
                    self.order = self.buy(size=abs(position_size))
                    self.short_stop_price = None
                    self.entry_price = None
                    return

        # === Entry logic ===
        if position_size == 0:
            # Break above upper band -> open long
            if current_price > upper_band:
                self.log(f'LONG ENTRY: price={current_price:.6f} > upper={upper_band:.6f}')
                self.order = self.buy(size=size)
                self.entry_price = current_price
                self.long_stop_price = current_price - (atr_value * self.p.atr_mult)
                return

            # Break below lower band -> open short
            elif current_price < lower_band:
                self.log(f'SHORT ENTRY: price={current_price:.6f} < lower={lower_band:.6f}')
                self.order = self.sell(size=size)
                self.entry_price = current_price
                self.short_stop_price = current_price + (atr_value * self.p.atr_mult)
                return

        # === Exit logic ===
        elif position_size > 0:
            # Break below middle band -> close long
            if current_price < middle_band:
                self.log(f'LONG EXIT: price={current_price:.6f} < mid={middle_band:.6f}')
                self.order = self.sell(size=position_size)
                self.long_stop_price = None
                self.entry_price = None
                return

        elif position_size < 0:
            # Break above middle band -> close short
            if current_price > middle_band:
                self.log(f'SHORT EXIT: price={current_price:.6f} > mid={middle_band:.6f}')
                self.order = self.buy(size=abs(position_size))
                self.short_stop_price = None
                self.entry_price = None
                return

    def stop(self):
        """Output statistics when strategy ends."""
        win_rate = self.win_count / self.trade_count * 100 if self.trade_count > 0 else 0
        self.log(f'Period={self.p.period}, Dev={self.p.devfactor:.1f}, '
                f'ATR_P={self.p.atr_period}, ATR_M={self.p.atr_mult:.1f}, '
                f'Trades={self.trade_count}, WinRate={win_rate:.1f}%, '
                f'Final={self.broker.getvalue():.2f}', dt=self.datas[0].datetime.date(0))




# =============================================================================
# Main Functions
# =============================================================================

def run_single_backtest(data_df, params):
    """Run a single backtest with given parameters.

    Args:
        data_df: DataFrame containing historical price data.
        params: Dictionary of strategy parameters.

    Returns:
        Dictionary containing backtest results.
    """
    cerebro = bt.Cerebro()

    # Add data
    data = BinanceZipCSVData(dataname=data_df)
    cerebro.adddata(data)

    # Add strategy
    cerebro.addstrategy(
        BollingerBandsStrategy,
        period=params['period'],
        devfactor=params['devfactor'],
        atr_period=params['atr_period'],
        atr_mult=params['atr_mult'],
        printlog=False
    )

    # Set initial capital and commission
    cerebro.broker.setcash(10000.0)
    cerebro.broker.setcommission(commission=0.0004)  # 0.04% commission

    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    # Run backtest
    results = cerebro.run()
    strat = results[0]

    # Collect results
    final_value = cerebro.broker.getvalue()
    sharpe = strat.analyzers.sharpe.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    trades = strat.analyzers.trades.get_analysis()

    # Extract trading statistics
    total_trades = trades.get('total', {}).get('closed', 0)
    won = trades.get('won', {}).get('total', 0)
    win_rate = won / total_trades * 100 if total_trades > 0 else 0

    return {
        'params': params,
        'final_value': final_value,
        'return_pct': (final_value - 10000) / 10000 * 100,
        'sharpe_ratio': sharpe.get('sharperatio', 0) or 0,
        'max_drawdown': drawdown.get('max', {}).get('drawdown', 0) or 0,
        'total_trades': total_trades,
        'win_rate': win_rate,
    }


def run_backtest_with_dict(params, data_dict):
    """Run single backtest from dictionary format data (for multiprocessing).

    Args:
        params: Strategy parameter dictionary.
        data_dict: Data dictionary (dates, open, high, low, close, volume).

    Returns:
        Backtest result dictionary.
    """
    try:
        # Convert dictionary back to DataFrame
        import pandas as pd
        data_df = pd.DataFrame({
            'open': data_dict['open'],
            'high': data_dict['high'],
            'low': data_dict['low'],
            'close': data_dict['close'],
            'volume': data_dict['volume'],
        })
        data_df.index = pd.to_datetime(data_dict['dates'], unit='ms')

        return run_single_backtest(data_df, params)
    except Exception as e:
        print(f"Backtest failed: {params}, error: {e}")
        return None


def _print_result_inline(current: int, total: int, result: dict):
    """Print single backtest result (single-line format).

    Args:
        current: Current completed count.
        total: Total count.
        result: Backtest result dictionary.
    """
    p = result['params']
    ret = result['return_pct']
    sharpe = result['sharpe_ratio']
    dd = result['max_drawdown']
    trades = result['total_trades']
    win_rate = result['win_rate']

    # Format output
    print(f"[{current}/{total}] "
          f"P={p['period']:3d} D={p['devfactor']:.1f} "
          f"ATR_P={p['atr_period']:2d} ATR_M={p['atr_mult']:.1f} | "
          f"Return: {ret:6.2f}% | "
          f"Sharpe: {sharpe:5.2f} | "
          f"DD: {dd:5.2f}% | "
          f"Trades: {trades:3d} | "
          f"WinRate: {win_rate:5.1f}%")


def run_optimization(data_dir: str,
                     start_date: str = None,
                     end_date: str = None,
                     use_multiprocessing: bool = True,
                     cpu_usage: float = 0.8):
    """Run parameter optimization.

    Args:
        data_dir: Data directory path.
        start_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD).
        use_multiprocessing: Whether to use multiprocessing.
        cpu_usage: CPU usage ratio (0.1-1.0), default 0.8 (80%).

    Returns:
        List of sorted result dictionaries.
    """
    print("=" * 70)
    print("Bollinger Bands Strategy Parameter Optimization")
    print("=" * 70)

    # Load data
    print("\n[1] Loading data...")
    data_df = load_binance_data(data_dir, start_date, end_date)

    # Convert data to serializable format (for multiprocessing)
    # Convert DataFrame to dict format for pickle serialization
    data_dict = {
        'dates': data_df.index.astype('int64').tolist(),  # Convert to unix timestamp
        'open': data_df['open'].tolist(),
        'high': data_df['high'].tolist(),
        'low': data_df['low'].tolist(),
        'close': data_df['close'].tolist(),
        'volume': data_df['volume'].tolist(),
    }

    # Define parameter space
    print("\n[2] Defining parameter space...")
    param_space = []

    # Parameter ranges
    periods = [20, 30, 40, 50, 60, 80, 100]
    devfactors = [1.5, 2.0, 2.5, 3.0]
    atr_periods = [7, 10, 14, 20]
    atr_mults = [1.0, 1.5, 2.0, 2.5, 3.0]

    for period in periods:
        for devfactor in devfactors:
            for atr_period in atr_periods:
                for atr_mult in atr_mults:
                    param_space.append({
                        'period': period,
                        'devfactor': devfactor,
                        'atr_period': atr_period,
                        'atr_mult': atr_mult,
                    })

    total_combinations = len(param_space)
    print(f"Total parameter combinations: {total_combinations}")

    # Calculate CPU cores
    total_cores = cpu_count()
    n_workers = max(1, int(total_cores * cpu_usage))
    print(f"Detected {total_cores} CPU cores, using {n_workers} ({cpu_usage*100:.0f}%)")

    # Run optimization
    print("\n[3] Running optimization...")

    if use_multiprocessing and total_combinations > 10 and n_workers > 1:
        # Multiprocess optimization
        print(f"Using multiprocessing for parallel computation...")

        # Create wrapper function, fixing data_dict parameter
        worker_func = partial(run_backtest_with_dict, data_dict=data_dict)

        with Pool(processes=n_workers) as pool:
            # Use imap_unordered for progress tracking
            results = []
            completed = 0
            for result in pool.imap_unordered(worker_func, param_space):
                completed += 1
                if result is not None:
                    results.append(result)
                    # Display results in real-time
                    _print_result_inline(completed, total_combinations, result)
                else:
                    print(f"[{completed}/{total_combinations}] Backtest failed")

    else:
        # Single-process optimization
        print("Using single-process computation...")
        results = []
        for i, params in enumerate(param_space):
            try:
                result = run_single_backtest(data_df, params)
                results.append(result)
                # Display results in real-time
                _print_result_inline(i + 1, total_combinations, result)
            except Exception as e:
                print(f"[{i + 1}/{total_combinations}] Parameter combination failed: {params}, error: {e}")

    # Analyze results
    print("\n[4] Analyzing results...")

    if not results:
        print("No valid backtest results!")
        return

    # Sort by return percentage
    results_sorted = sorted(results, key=lambda x: x['return_pct'], reverse=True)

    # Output Top 20 results
    print("\n" + "=" * 100)
    print("Top 20 Parameter Combinations (sorted by return)")
    print("=" * 100)
    print(f"{'Rank':<5} {'Period':<8} {'DevFactor':<10} {'ATR_P':<8} {'ATR_M':<8} "
          f"{'Return%':<10} {'Sharpe':<8} {'MaxDD%':<10} {'Trades':<8} {'WinRate%':<10}")
    print("-" * 100)

    for i, r in enumerate(results_sorted[:20], 1):
        p = r['params']
        print(f"{i:<5} {p['period']:<8} {p['devfactor']:<10.1f} {p['atr_period']:<8} {p['atr_mult']:<8.1f} "
              f"{r['return_pct']:<10.2f} {r['sharpe_ratio']:<8.2f} {r['max_drawdown']:<10.2f} "
              f"{r['total_trades']:<8} {r['win_rate']:<10.1f}")

    # Output best parameters
    best = results_sorted[0]
    print("\n" + "=" * 70)
    print("Best Parameter Combination")
    print("=" * 70)
    print(f"Bollinger Period (period):        {best['params']['period']}")
    print(f"Std Dev Multiplier (devfactor):   {best['params']['devfactor']}")
    print(f"ATR Period (atr_period):          {best['params']['atr_period']}")
    print(f"ATR Stop Multiplier (atr_mult):   {best['params']['atr_mult']}")
    print("-" * 70)
    print(f"Final Capital:    ${best['final_value']:.2f}")
    print(f"Total Return:     {best['return_pct']:.2f}%")
    print(f"Sharpe Ratio:     {best['sharpe_ratio']:.2f}")
    print(f"Max Drawdown:     {best['max_drawdown']:.2f}%")
    print(f"Total Trades:     {best['total_trades']}")
    print(f"Win Rate:         {best['win_rate']:.1f}%")
    print("=" * 70)

    # Save results to CSV
    output_file = Path(data_dir).parent / 'optimization_results.csv'
    df_results = pd.DataFrame([
        {
            'period': r['params']['period'],
            'devfactor': r['params']['devfactor'],
            'atr_period': r['params']['atr_period'],
            'atr_mult': r['params']['atr_mult'],
            'return_pct': r['return_pct'],
            'sharpe_ratio': r['sharpe_ratio'],
            'max_drawdown': r['max_drawdown'],
            'total_trades': r['total_trades'],
            'win_rate': r['win_rate'],
            'final_value': r['final_value'],
        }
        for r in results_sorted
    ])
    df_results.to_csv(output_file, index=False)
    print(f"\nResults saved to: {output_file}")

    return results_sorted


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Bollinger Bands Strategy Parameter Optimization',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
    # Use default parameters (80%% CPU)
    python %(prog)s --data-dir /path/to/data

    # Specify date range
    python %(prog)s --data-dir /path/to/data --start-date 2024-01-01 --end-date 2024-12-31

    # Use 50%% CPU
    python %(prog)s --data-dir /path/to/data --cpu-usage 0.5

    # Disable multiprocessing
    python %(prog)s --data-dir /path/to/data --no-multiprocessing
        '''
    )

    parser.add_argument(
        '--data-dir',
        type=str,
        required=True,
        help='Binance data directory path (containing ZIP files)'
    )
    parser.add_argument(
        '--start-date',
        type=str,
        default=None,
        help='Start date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--end-date',
        type=str,
        default=None,
        help='End date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--cpu-usage',
        type=float,
        default=0.8,
        help='CPU usage ratio (0.1-1.0), default 0.8 (80%%)'
    )
    parser.add_argument(
        '--no-multiprocessing',
        action='store_true',
        help='Disable multiprocessing'
    )

    args = parser.parse_args()

    # Validate CPU usage parameter
    if not 0.1 <= args.cpu_usage <= 1.0:
        parser.error('--cpu-usage must be between 0.1 and 1.0')

    # Run optimization
    run_optimization(
        data_dir=args.data_dir,
        start_date=args.start_date,
        end_date=args.end_date,
        use_multiprocessing=not args.no_multiprocessing,
        cpu_usage=args.cpu_usage
    )
