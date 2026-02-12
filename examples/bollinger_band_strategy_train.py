#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Bollinger Band Strategy with Parameter Optimization.

This script implements a classic Bollinger Band strategy for BTC/USDT 15-minute data.
- Training set: 2020-2024 (for parameter optimization)
- Test set: 2025 (for out-of-sample performance evaluation)

Strategy Logic:
    - Buy when price crosses above the lower band (mean reversion)
    - Sell when price crosses below the upper band
    - Alternative: Trend following - buy on upper band breakout

Usage:
    python bollinger_band_strategy.py
"""

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os
from pathlib import Path
from itertools import product
from multiprocessing import Pool, cpu_count
from functools import partial
import warnings
import sys

import pandas as pd
import numpy as np
import backtrader as bt
import matplotlib.pyplot as plt
import seaborn as sns
from tqdm import tqdm

warnings.filterwarnings('ignore')

BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "backtest_results"
RESULTS_DIR.mkdir(exist_ok=True)


class BollingerBandStrategy(bt.Strategy):
    """Bollinger Band trend following strategy.

    Strategy Rules (Trend Following):
        - Buy Signal: Price closes above the upper band (breakout)
        - Sell Signal: Price closes below the lower band (breakdown)
        - Exit Long: Price crosses back below the middle band
        - Exit Short: Price crosses back above the middle band

    Parameters:
        period: Bollinger Band period (default: 20)
        devfactor: Standard deviation multiplier (default: 2.0)
        stake_pct: Percentage of cash to use per trade (default: 0.95)
        save_equity: Whether to save equity curve data (default: False)
    """

    params = dict(
        period=20,
        devfactor=2.0,
        stake_pct=0.95,
        save_equity=False,
    )

    def __init__(self):
        """Initialize the strategy with Bollinger Bands indicator."""
        self.dataclose = self.datas[0].close
        self.datahigh = self.datas[0].high
        self.datalow = self.datas[0].low

        self.bband = bt.indicators.BollingerBands(
            self.datas[0],
            period=self.p.period,
            devfactor=self.p.devfactor
        )

        self.order = None
        self.buyprice = None
        self.buycomm = None

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

        # For equity curve tracking
        self.equity_curve = []
        self.dates = []

    def notify_order(self, order):
        """Handle order notifications."""
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return

        if order.status == order.Completed:
            if order.isbuy():
                self.buyprice = order.executed.price
                self.buycomm = order.executed.comm
                self.buy_count += 1
            else:
                self.sell_count += 1

        self.order = None

    def notify_trade(self, trade):
        """Handle trade notifications."""
        pass

    def next(self):
        """Execute strategy logic for each bar."""
        self.bar_num += 1

        # Record equity curve
        if self.p.save_equity:
            self.equity_curve.append(self.broker.getvalue())
            # Get current datetime
            self.dates.append(self.data.datetime.datetime(0))

        # Wait for Bollinger Bands to be ready
        if len(self.dataclose) < self.p.period:
            return

        if self.order:
            return

        close = self.dataclose[0]
        lower = self.bband.lines.bot[0]
        upper = self.bband.lines.top[0]
        mid = self.bband.lines.mid[0]

        # Check if values are valid (not NaN)
        if np.isnan(lower) or np.isnan(upper) or np.isnan(mid):
            return

        if not self.position:
            # No position - look for entry signals
            if close > upper:
                # Price breaks above upper band - buy (trend following)
                cash = self.broker.getvalue()
                size = (cash * self.p.stake_pct) / close
                if size > 0.001:
                    self.order = self.buy(size=size)
            elif close < lower:
                # Price breaks below lower band - sell short (trend following)
                cash = self.broker.getvalue()
                size = (cash * self.p.stake_pct) / close
                if size > 0.001:
                    self.order = self.sell(size=size)
        else:
            # Have position - look for exit signals
            pos_size = self.position.size
            if pos_size > 0:
                # Long position - exit when price crosses below middle band
                if close < mid:
                    self.order = self.close()
            else:
                # Short position - exit when price crosses above middle band
                if close > mid:
                    self.order = self.close()

    def stop(self):
        """Called when strategy finishes."""
        pass


def load_data(filepath):
    """Load and preprocess the BTC/USDT data."""
    df = pd.read_csv(filepath)
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    # Drop rows with invalid dates
    df = df.dropna(subset=['Date'])
    df = df.sort_values('Date')
    df = df.set_index('Date')
    # Ensure the index is a DatetimeIndex
    df.index = pd.DatetimeIndex(df.index)
    # Drop any rows with NaT in index
    df = df[~df.index.isna()]
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
    df.columns = ['open', 'high', 'low', 'close', 'volume']
    # Ensure numeric types
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    # Drop rows with NaN values in price columns
    df = df.dropna()
    return df


def run_backtest(df, period, devfactor, initial_cash=1000000.0, commission=0.0003, verbose=False, save_equity=False, equity_file=None):
    """Run a single backtest with given parameters.

    Args:
        df: DataFrame with OHLCV data
        period: Bollinger Band period
        devfactor: Standard deviation multiplier
        initial_cash: Initial capital
        commission: Trading commission rate
        verbose: Print detailed results
        save_equity: Whether to save equity curve data
        equity_file: Path to save equity curve CSV

    Returns:
        dict: Performance metrics
    """
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=commission)

    # Create data feed - don't specify datetime parameter, let backtrader use the index
    data_feed = bt.feeds.PandasData(
        dataname=df,
        open='open',
        high='high',
        low='low',
        close='close',
        volume='volume',
        openinterest=-1,
    )
    cerebro.adddata(data_feed)

    cerebro.addstrategy(
        BollingerBandStrategy,
        period=period,
        devfactor=devfactor,
        save_equity=save_equity,
    )

    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0, annualize=True, timeframe=bt.TimeFrame.Minutes)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    results = cerebro.run()
    strat = results[0]

    final_value = cerebro.broker.getvalue()
    total_return = (final_value - initial_cash) / initial_cash

    sharpe_analysis = strat.analyzers.sharpe.get_analysis()
    sharpe_ratio = sharpe_analysis.get('sharperatio', None)

    returns_analysis = strat.analyzers.returns.get_analysis()

    drawdown_analysis = strat.analyzers.drawdown.get_analysis()
    max_drawdown = drawdown_analysis.get('max', {}).get('drawdown', 0) / 100

    trade_analysis = strat.analyzers.trades.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    won_trades = trade_analysis.get('won', {}).get('total', 0)
    lost_trades = trade_analysis.get('lost', {}).get('total', 0)
    win_rate = won_trades / total_trades * 100 if total_trades > 0 else 0

    metrics = {
        'period': period,
        'devfactor': devfactor,
        'final_value': final_value,
        'total_return': total_return,
        'sharpe_ratio': sharpe_ratio,
        'max_drawdown': max_drawdown,
        'total_trades': total_trades,
        'won_trades': won_trades,
        'lost_trades': lost_trades,
        'win_rate': win_rate,
        'buy_count': strat.buy_count,
        'sell_count': strat.sell_count,
        'bar_num': strat.bar_num,
    }

    # Save equity curve if requested
    if save_equity and equity_file and hasattr(strat, 'equity_curve') and strat.equity_curve:
        equity_df = pd.DataFrame({
            'datetime': strat.dates,
            'portfolio_value': strat.equity_curve,
        })
        equity_df.to_csv(equity_file, index=False)
        metrics['equity_file'] = str(equity_file)

    if verbose:
        print(f"\n{'='*60}")
        print(f"Backtest Results (period={period}, devfactor={devfactor}):")
        print(f"  Initial Cash: ${initial_cash:,.2f}")
        print(f"  Final Value: ${final_value:,.2f}")
        print(f"  Total Return: {total_return*100:.2f}%")
        print(f"  Sharpe Ratio: {sharpe_ratio}")
        print(f"  Max Drawdown: {max_drawdown*100:.2f}%")
        print(f"  Total Trades: {total_trades}")
        print(f"  Win Rate: {win_rate:.2f}%")
        print(f"  Bars Processed: {strat.bar_num}")
        if save_equity and 'equity_file' in metrics:
            print(f"  Equity curve saved to: {metrics['equity_file']}")
        print(f"{'='*60}")

    return metrics


def run_single_optimization(args):
    """Run a single backtest for multiprocessing.

    Args:
        args: Tuple of (data_path, train_end_date, period, devfactor, initial_cash, commission, save_equity, results_dir)

    Returns:
        dict: Performance metrics
    """
    data_path, train_end_date, period, devfactor, initial_cash, commission, save_equity, results_dir = args
    try:
        # Load data in subprocess to avoid Windows multiprocessing issues with pandas DataFrames
        df = load_data(data_path)
        df_train = df[df.index < train_end_date]

        # Validate data
        if len(df_train) < period:
            return {
                'period': period,
                'devfactor': devfactor,
                'total_return': np.nan,
                'sharpe_ratio': np.nan,
                'max_drawdown': np.nan,
                'total_trades': 0,
                'win_rate': 0,
                'error': f'Insufficient data: {len(df_train)} bars < period {period}'
            }

        # Generate equity file path if saving
        equity_file = None
        if save_equity:
            results_dir = Path(results_dir)
            results_dir.mkdir(exist_ok=True)
            equity_file = results_dir / f"equity_p{period}_dev{devfactor}.csv"

        metrics = run_backtest(
            df_train,
            period=period,
            devfactor=devfactor,
            initial_cash=initial_cash,
            commission=commission,
            verbose=False,
            save_equity=save_equity,
            equity_file=equity_file
        )
        return metrics
    except Exception as e:
        import traceback
        error_details = f"{type(e).__name__}: {str(e)}"
        return {
            'period': period,
            'devfactor': devfactor,
            'total_return': np.nan,
            'sharpe_ratio': np.nan,
            'max_drawdown': np.nan,
            'total_trades': 0,
            'win_rate': 0,
            'error': error_details,
            'traceback': traceback.format_exc()
        }


def optimize_parameters(data_path, train_end_date, param_grid, initial_cash=1000000.0, commission=0.0003, n_processes=20, save_equity=True, results_dir=None):
    """Optimize strategy parameters on training data using multiprocessing.

    Args:
        data_path: Path to the data file
        train_end_date: End date for training data (e.g., '2025-01-01')
        param_grid: Dictionary with parameter ranges
        initial_cash: Initial capital
        commission: Trading commission rate
        n_processes: Number of parallel processes
        save_equity: Whether to save equity curve data for each parameter combination
        results_dir: Directory to save results

    Returns:
        tuple: (best_params, all_results, results_df)
    """
    print("\n" + "="*60)
    print("Starting Parameter Optimization on Training Set")
    print(f"Using {n_processes} parallel processes")
    if save_equity:
        print(f"Saving equity curves to: {results_dir}")
    print("="*60)

    periods = param_grid.get('period', [20])
    devfactors = param_grid.get('devfactor', [2.0])

    param_combinations = list(product(periods, devfactors))
    total_combinations = len(param_combinations)

    print(f"Testing {total_combinations} parameter combinations...")
    print(f"Period range: {min(periods)} to {max(periods)}")
    print(f"Devfactor values: {devfactors}")
    print()

    if results_dir is None:
        results_dir = RESULTS_DIR
    else:
        results_dir = Path(results_dir)
    results_dir.mkdir(exist_ok=True)

    args_list = [
        (data_path, train_end_date, period, devfactor, initial_cash, commission, save_equity, str(results_dir))
        for period, devfactor in param_combinations
    ]

    print("Running parallel optimization...")
    import time
    start_time = time.time()

    # Use imap_unordered with tqdm for progress bar
    all_results = []
    with Pool(processes=n_processes) as pool:
        # Use tqdm for progress bar
        for result in tqdm(pool.imap_unordered(run_single_optimization, args_list),
                          total=total_combinations,
                          desc="Optimizing",
                          unit="param",
                          ncols=100):
            all_results.append(result)

    elapsed_time = time.time() - start_time
    print(f"\nOptimization completed in {elapsed_time:.2f} seconds")

    results_df = pd.DataFrame(all_results)

    valid_results = [r for r in all_results if r.get('sharpe_ratio') is not None and r.get('total_trades', 0) > 0]

    if not valid_results:
        valid_results = [r for r in all_results if r.get('total_trades', 0) > 0]
        if valid_results:
            best = max(valid_results, key=lambda x: x.get('total_return', -999))
        else:
            best = {'period': periods[0], 'devfactor': devfactors[0], 'total_return': 0, 'sharpe_ratio': None}
    else:
        best = max(valid_results, key=lambda x: (x.get('sharpe_ratio') if x.get('sharpe_ratio') else -999))

    best_params = {'period': best['period'], 'devfactor': best['devfactor']}

    print(f"\n{'='*60}")
    print("Optimization Complete!")
    print(f"Best Parameters: period={best_params['period']}, devfactor={best_params['devfactor']}")
    print(f"Best Return: {best.get('total_return', 0)*100:.2f}%")
    print(f"Best Sharpe: {best.get('sharpe_ratio')}")
    print(f"{'='*60}")

    return best_params, all_results, results_df


def plot_heatmaps(results_df, save_path=None):
    """Plot heatmaps for total return and Sharpe ratio side by side.

    Args:
        results_df: DataFrame with optimization results
        save_path: Path to save the figure (optional)
    """
    # Check if results contain valid data
    has_valid_return = results_df['total_return'].notna().any()
    has_valid_sharpe = results_df['sharpe_ratio'].notna().any()

    if not has_valid_return and not has_valid_sharpe:
        print("\nWarning: No valid results to plot. All values are NaN.")
        if 'error' in results_df.columns:
            errors = results_df[results_df['error'].notna()]['error'].unique()
            print("Errors found:")
            for e in errors:
                print(f"  - {e}")
        return None

    fig, axes = plt.subplots(1, 2, figsize=(20, 8))

    pivot_return = results_df.pivot_table(
        values='total_return',
        index='devfactor',
        columns='period',
        aggfunc='first'
    ).sort_index(ascending=False) * 100

    pivot_sharpe = results_df.pivot_table(
        values='sharpe_ratio',
        index='devfactor',
        columns='period',
        aggfunc='first'
    ).sort_index(ascending=False)

    # Plot return heatmap if data is valid
    if pivot_return.notna().any().any():
        sns.heatmap(
            pivot_return.fillna(0),
            annot=True,
            fmt='.1f',
            cmap='RdYlGn',
            center=0,
            ax=axes[0],
            cbar_kws={'label': 'Total Return (%)'},
            annot_kws={'size': 7}
        )
        axes[0].set_xlabel('Bollinger Band Period', fontsize=12)
        axes[0].set_ylabel('Standard Deviation Factor', fontsize=12)
        axes[0].set_title('Total Return (%)', fontsize=14, fontweight='bold')
    else:
        axes[0].text(0.5, 0.5, 'No valid data', ha='center', va='center', transform=axes[0].transAxes)
        axes[0].set_title('Total Return (%) - No valid data', fontsize=14, fontweight='bold')

    # Plot Sharpe ratio heatmap if data is valid
    if pivot_sharpe.notna().any().any():
        sns.heatmap(
            pivot_sharpe.fillna(0),
            annot=True,
            fmt='.3f',
            cmap='RdYlGn',
            center=0,
            ax=axes[1],
            cbar_kws={'label': 'Sharpe Ratio'},
            annot_kws={'size': 7}
        )
        axes[1].set_xlabel('Bollinger Band Period', fontsize=12)
        axes[1].set_ylabel('Standard Deviation Factor', fontsize=12)
        axes[1].set_title('Sharpe Ratio', fontsize=14, fontweight='bold')
    else:
        axes[1].text(0.5, 0.5, 'No valid data', ha='center', va='center', transform=axes[1].transAxes)
        axes[1].set_title('Sharpe Ratio - No valid data', fontsize=14, fontweight='bold')

    plt.suptitle('Bollinger Band Strategy - Parameter Optimization Results', fontsize=16, fontweight='bold', y=1.02)
    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Heatmap saved to: {save_path}")

    plt.show()

    return fig


def main():
    """Main function to run the optimization."""
    print("="*70)
    print("Bollinger Band Strategy - Parameter Optimization")
    print("BTC/USDT 15-minute Data | Training: 2020-2024")
    print("="*70)

    data_path = BASE_DIR / "DOGEUSDT_15m_20200710_20260126.csv"
    print(f"\nLoading data from: {data_path}")

    df = load_data(data_path)
    print(f"Total data points: {len(df)}")
    print(f"Date range: {df.index.min()} to {df.index.max()}")

    df_train = df[df.index < '2025-01-01']

    print(f"\nTraining set: {len(df_train)} bars ({df_train.index.min()} to {df_train.index.max()})")

    # Run a quick test with default parameters to verify the strategy works
    print("\n" + "="*70)
    print("Running test backtest with default parameters (period=20, devfactor=2.0)...")
    print("="*70)
    test_result = run_backtest(df_train, period=20, devfactor=2.0, verbose=True)
    if test_result['total_trades'] == 0:
        print("\nWarning: Test run produced no trades. Check data and strategy logic.")
    
    param_grid = {
        'period': list(range(20, 301, 10)),
        'devfactor': [0.5, 1.0, 1.5, 2.0, 2.5,3,3.5,4]
    }
    
    initial_cash = 1000000.0
    commission = 0.0003
    
    best_params, optimization_results, results_df = optimize_parameters(
        str(data_path),
        '2025-01-01',
        param_grid,
        initial_cash=initial_cash,
        commission=commission,
        n_processes=20,
        save_equity=True,
        results_dir=str(RESULTS_DIR)
    )

    # Check for errors
    if 'error' in results_df.columns:
        error_count = results_df['error'].notna().sum()
        if error_count > 0:
            print(f"\nWarning: {error_count} parameter combinations failed with errors:")
            unique_errors = results_df[results_df['error'].notna()]['error'].unique()
            for e in unique_errors[:5]:  # Show first 5 unique errors
                print(f"  - {e}")

    results_df_sorted = results_df.sort_values('total_return', ascending=False)

    print("\n" + "="*70)
    print("TOP 20 PARAMETER COMBINATIONS (by Total Return)")
    print("="*70)
    display_cols = ['period', 'devfactor', 'total_return', 'sharpe_ratio', 'max_drawdown', 'total_trades', 'win_rate']
    # Only include columns that exist
    display_cols = [c for c in display_cols if c in results_df.columns]
    top_results = results_df_sorted[display_cols].head(20).copy()
    top_results['total_return'] = top_results['total_return'].apply(lambda x: f"{x*100:.2f}%" if pd.notna(x) else "N/A")
    if 'max_drawdown' in top_results.columns:
        top_results['max_drawdown'] = top_results['max_drawdown'].apply(lambda x: f"{x*100:.2f}%" if pd.notna(x) else "N/A")
    top_results['win_rate'] = top_results['win_rate'].apply(lambda x: f"{x:.2f}%" if pd.notna(x) else "N/A")
    print(top_results.to_string(index=False))
    print("="*70)
    
    results_csv_path = BASE_DIR / "optimization_results.csv"
    results_df.to_csv(results_csv_path, index=False)
    print(f"\nOptimization results saved to: {results_csv_path}")
    
    print("\n" + "="*70)
    print("Generating Heatmaps (Total Return & Sharpe Ratio)...")
    print("="*70)
    
    plot_heatmaps(
        results_df, 
        save_path=BASE_DIR / "heatmap_optimization.png"
    )
    
    print("\n" + "="*70)
    print("OPTIMIZATION SUMMARY")
    print("="*70)
    print(f"Best Parameters: period={best_params['period']}, devfactor={best_params['devfactor']}")
    best_row = results_df[(results_df['period'] == best_params['period']) & 
                          (results_df['devfactor'] == best_params['devfactor'])].iloc[0]
    print(f"Best Total Return: {best_row['total_return']*100:.2f}%")
    print(f"Best Sharpe Ratio: {best_row.get('sharpe_ratio', 'N/A')}")
    print(f"Best Max Drawdown: {best_row['max_drawdown']*100:.2f}%")
    print(f"Total Trades: {best_row['total_trades']}")
    print(f"Win Rate: {best_row['win_rate']:.2f}%")
    print("="*70)
    
    return best_params, results_df


if __name__ == "__main__":
    best_params, results_df = main()
