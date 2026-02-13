#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Bollinger Band Strategy - Test on 2025 Data.

This script tests the Bollinger Band strategy on out-of-sample 2025 data
using the optimal parameters found from training (period=280, devfactor=2.5).

Usage:
    python bollinger_band_strategy_test.py
"""

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import warnings
from pathlib import Path

import pandas as pd
import numpy as np
import backtrader as bt
import matplotlib.pyplot as plt
import plotly.graph_objects as go
from plotly.subplots import make_subplots

warnings.filterwarnings('ignore')

BASE_DIR = Path(__file__).resolve().parent
TEST_RESULTS_DIR = BASE_DIR / "test_results"
TEST_RESULTS_DIR.mkdir(exist_ok=True)


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
    """

    params = dict(
        period=280,
        devfactor=2.5,
        stake_pct=0.95,
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
        self.position_history = []  # Track position changes

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
        self.equity_curve.append(self.broker.getvalue())
        self.dates.append(self.data.datetime.datetime(0))
        self.position_history.append(self.position.size)

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
    df = df.dropna(subset=['Date'])
    df = df.sort_values('Date')
    df = df.set_index('Date')
    df.index = pd.DatetimeIndex(df.index)
    df = df[~df.index.isna()]
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
    df.columns = ['open', 'high', 'low', 'close', 'volume']
    # Ensure numeric types
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna()
    return df


def run_backtest(df, period=280, devfactor=2.5, initial_cash=1000000.0, commission=0.0003):
    """Run backtest with given parameters.

    Returns:
        tuple: (metrics dict, strategy object, cerebro object)
    """
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=commission)

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
    )

    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0,
                       annualize=True, timeframe=bt.TimeFrame.Minutes)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    results = cerebro.run()
    strat = results[0]

    final_value = cerebro.broker.getvalue()
    total_return = (final_value - initial_cash) / initial_cash

    sharpe_analysis = strat.analyzers.sharpe.get_analysis()
    sharpe_ratio = sharpe_analysis.get('sharperatio', None)

    drawdown_analysis = strat.analyzers.drawdown.get_analysis()
    max_drawdown = drawdown_analysis.get('max', {}).get('drawdown', 0) / 100

    trade_analysis = strat.analyzers.trades.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    won_trades = trade_analysis.get('won', {}).get('total', 0)
    lost_trades = trade_analysis.get('lost', {}).get('total', 0)
    win_rate = won_trades / total_trades * 100 if total_trades > 0 else 0

    # Get average trade metrics
    avg_profit = None
    avg_loss = None
    if won_trades > 0:
        avg_profit = trade_analysis.get('won', {}).get('pnl', {}).get('average', 0)
    if lost_trades > 0:
        avg_loss = trade_analysis.get('lost', {}).get('pnl', {}).get('average', 0)

    # Profit factor
    gross_profit = trade_analysis.get('won', {}).get('pnl', {}).get('gross', 0)
    gross_loss = abs(trade_analysis.get('lost', {}).get('pnl', {}).get('gross', 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

    metrics = {
        'period': period,
        'devfactor': devfactor,
        'initial_cash': initial_cash,
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
        'avg_profit': avg_profit,
        'avg_loss': avg_loss,
        'profit_factor': profit_factor,
    }

    return metrics, strat, cerebro


def plot_equity_curve(strat, price_df, save_path=None):
    """Plot interactive equity curve with price."""
    # Create equity DataFrame
    equity_df = pd.DataFrame({
        'datetime': strat.dates,
        'portfolio_value': strat.equity_curve,
        'position': strat.position_history,
    })

    # Calculate returns
    equity_df['returns_pct'] = (equity_df['portfolio_value'] / 1000000 - 1) * 100

    # Merge with price data
    price_df_reset = price_df.reset_index()
    price_df_reset.columns = ['datetime', 'open', 'high', 'low', 'close', 'volume']

    # Align datetime
    equity_df['datetime'] = pd.to_datetime(equity_df['datetime'])
    price_df_reset['datetime'] = pd.to_datetime(price_df_reset['datetime'])

    merged = pd.merge_asof(equity_df, price_df_reset, on='datetime')

    # Create subplots
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.4, 0.3, 0.3],
        subplot_titles=('Portfolio Value & Price', 'Portfolio Returns (%)', 'Position')
    )

    # Price and portfolio value
    fig.add_trace(
        go.Scatter(
            x=merged['datetime'],
            y=merged['portfolio_value'],
            mode='lines',
            name='Portfolio Value',
            line=dict(color='#2ecc71', width=2),
            hovertemplate='%{x}<br>Value: $%{y:,.0f}<extra></extra>'
        ),
        row=1, col=1
    )

    fig.add_trace(
        go.Scatter(
            x=merged['datetime'],
            y=merged['close'],
            mode='lines',
            name='BTC Price',
            line=dict(color='#3498db', width=1),
            yaxis='y2',
            hovertemplate='%{x}<br>Price: $%{y:,.0f}<extra></extra>'
        ),
        row=1, col=1
    )

    # Returns
    fig.add_trace(
        go.Scatter(
            x=merged['datetime'],
            y=merged['returns_pct'],
            mode='lines',
            name='Returns (%)',
            line=dict(color='#9b59b6', width=2),
            fill='tozeroy',
            hovertemplate='%{x}<br>Return: %{y:.2f}%<extra></extra>'
        ),
        row=2, col=1
    )

    # Position
    colors = ['green' if p > 0 else 'red' if p < 0 else 'gray' for p in merged['position']]
    fig.add_trace(
        go.Scatter(
            x=merged['datetime'],
            y=merged['position'],
            mode='lines',
            name='Position',
            line=dict(color='gray', width=1),
            fill='tozeroy',
            hovertemplate='%{x}<br>Position: %{y:.4f}<extra></extra>'
        ),
        row=3, col=1
    )

    # Update y-axes
    fig.update_yaxes(title_text="Value ($)", row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="BTC Price ($)", row=1, col=1, secondary_y=True)
    fig.update_yaxes(title_text="Returns (%)", row=2, col=1)
    fig.update_yaxes(title_text="Position (BTC)", row=3, col=1)

    fig.update_xaxes(title_text="Date", row=3, col=1)

    fig.update_layout(
        title_text=f"Test Results (2025) - Period=280, Devfactor=2.5",
        title_font_size=18,
        height=1000,
        width=1400,
        hovermode='x unified',
        font=dict(size=12)
    )

    if save_path:
        fig.write_html(save_path)
        print(f"Interactive plot saved to: {save_path}")

    fig.show()
    return fig


def main():
    """Main function to run the test."""
    print("="*70)
    print("Bollinger Band Strategy - Test on 2025 Data")
    print("Parameters: period=280, devfactor=2.5")
    print("="*70)

    # Load data
    data_path = BASE_DIR / "DOGEUSDT_15m_20200710_20260126.csv"
    print(f"\nLoading data from: {data_path}")

    df = load_data(data_path)
    print(f"Total data points: {len(df)}")
    print(f"Date range: {df.index.min()} to {df.index.max()}")

    # Filter for 2025 test data
    df_test = df[df.index >= '2025-01-01']
    print(f"\nTest set: {len(df_test)} bars ({df_test.index.min()} to {df_test.index.max()})")

    # Run backtest
    print("\n" + "="*70)
    print("Running backtest on test data...")
    print("="*70)

    period = 280
    devfactor = 2.5
    initial_cash = 1000000.0
    commission = 0.0003

    metrics, strat, cerebro = run_backtest(
        df_test,
        period=period,
        devfactor=devfactor,
        initial_cash=initial_cash,
        commission=commission
    )

    # Print results
    print("\n" + "="*70)
    print("TEST RESULTS (2025 Data)")
    print("="*70)
    print(f"Parameters: period={period}, devfactor={devfactor}")
    print(f"Test Period: {df_test.index.min()} to {df_test.index.max()}")
    print(f"Bars Processed: {metrics['bar_num']}")
    print("-"*70)
    print(f"Initial Cash:     ${metrics['initial_cash']:,.2f}")
    print(f"Final Value:      ${metrics['final_value']:,.2f}")
    print(f"Total Return:     {metrics['total_return']*100:.2f}%")
    print(f"Sharpe Ratio:     {metrics['sharpe_ratio']:.3f}" if metrics['sharpe_ratio'] else f"Sharpe Ratio:     N/A")
    print(f"Max Drawdown:     {metrics['max_drawdown']*100:.2f}%")
    print("-"*70)
    print(f"Total Trades:     {metrics['total_trades']}")
    print(f"Winning Trades:   {metrics['won_trades']}")
    print(f"Losing Trades:    {metrics['lost_trades']}")
    print(f"Win Rate:         {metrics['win_rate']:.2f}%")
    print("-"*70)
    if metrics['avg_profit']:
        print(f"Avg Winning Trade: ${metrics['avg_profit']:,.2f}")
    if metrics['avg_loss']:
        print(f"Avg Losing Trade:  ${metrics['avg_loss']:,.2f}")
    print(f"Profit Factor:    {metrics['profit_factor']:.2f}")
    print("="*70)

    # Save equity curve
    equity_df = pd.DataFrame({
        'datetime': strat.dates,
        'portfolio_value': strat.equity_curve,
    })
    equity_path = TEST_RESULTS_DIR / "test_2025_equity.csv"
    equity_df.to_csv(equity_path, index=False)
    print(f"\nEquity curve saved to: {equity_path}")

    # Save metrics
    metrics_df = pd.DataFrame([metrics])
    metrics_path = TEST_RESULTS_DIR / "test_2025_metrics.csv"
    metrics_df.to_csv(metrics_path, index=False)
    print(f"Metrics saved to: {metrics_path}")

    # Plot equity curve
    print("\nGenerating interactive plot...")
    plot_equity_curve(
        strat,
        df_test,
        save_path=TEST_RESULTS_DIR / "test_2025_equity_plot.html"
    )

    # Comparison with training results
    print("\n" + "="*70)
    print("COMPARISON: TRAINING (2020-2024) vs TEST (2025)")
    print("="*70)

    # Load training results
    train_results_path = BASE_DIR / "backtest_results" / "equity_p280_dev2.5.csv"
    if train_results_path.exists():
        train_df = pd.read_csv(train_results_path)
        train_return = (train_df['portfolio_value'].iloc[-1] / 1000000 - 1) * 100

        print(f"Training Return (2020-2024): {train_return:.2f}%")
        print(f"Test Return (2025):           {metrics['total_return']*100:.2f}%")
        print(f"Difference:                   {metrics['total_return']*100 - train_return:.2f}%")
    else:
        print("Training results not found for comparison.")

    print("="*70)

    return metrics


if __name__ == "__main__":
    results = main()
