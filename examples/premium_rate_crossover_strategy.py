#!/usr/bin/env python
"""
Convertible bond premium rate moving average crossover strategy.

Strategy logic:
1. Calculate 10-day and 60-day moving averages of conversion premium rate
2. Buy when 10-day MA crosses above 60-day MA (golden cross)
3. Close position when 10-day MA crosses below 60-day MA (death cross)

References:
- examples/sma_crossover.py
- examples/optimized_strategy_1.py
"""
import datetime
import sys
import warnings

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import FuncFormatter

import backtrader as bt
import backtrader.indicators as btind

# Set Chinese font
plt.rcParams["font.sans-serif"] = ["SimHei"]  # For proper Chinese label display
plt.rcParams["axes.unicode_minus"] = False  # For proper minus sign display
# Ignore warnings
warnings.filterwarnings("ignore")


class ExtendPandasFeed(bt.feeds.PandasData):
    """
    Extended Pandas data feed with convertible bond specific fields.

    Important note:
    After DataFrame uses set_index('datetime'), datetime column becomes index not data column.
    Therefore column indices need to be recalculated from 0, excluding datetime.

    DataFrame structure (after set_index):
    - Index: datetime
    - Column 0: open
    - Column 1: high
    - Column 2: low
    - Column 3: close
    - Column 4: volume
    - Column 5: pure_bond_value
    - Column 6: convert_value
    - Column 7: pure_bond_premium_rate
    - Column 8: convert_premium_rate
    """

    params = (
        ("datetime", None),  # datetime is index, not data column
        ("open", 0),  # Column 1 -> index 0
        ("high", 1),  # Column 2 -> index 1
        ("low", 2),  # Column 3 -> index 2
        ("close", 3),  # Column 4 -> index 3
        ("volume", 4),  # Column 5 -> index 4
        ("openinterest", -1),  # Column does not exist
        ("pure_bond_value", 5),  # Column 6 -> index 5
        ("convert_value", 6),  # Column 7 -> index 6
        ("pure_bond_premium_rate", 7),  # Column 8 -> index 7
        ("convert_premium_rate", 8),  # Column 9 -> index 8
    )

    # Define extended data lines
    lines = ("pure_bond_value", "convert_value", "pure_bond_premium_rate", "convert_premium_rate")


class PremiumRateCrossoverStrategy(bt.Strategy):
    """
    Conversion premium rate moving average crossover strategy.

    Strategy logic:
    - Use conversion premium rate (convert_premium_rate) to calculate moving averages
    - Buy when short-term MA (default 10-day) crosses above long-term MA (default 60-day)
    - Sell and close position when short-term MA crosses below long-term MA
    """

    params = (
        ("short_period", 10),  # Short-term MA period
        ("long_period", 60),  # Long-term MA period
    )

    def log(self, txt, dt=None):
        """Log output function."""
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print(f"{dt.isoformat()}, {txt}")

    def __init__(self):
        """Initialize strategy."""
        # Get conversion premium rate data line
        self.premium_rate = self.datas[0].convert_premium_rate

        # Calculate short-term and long-term moving averages
        self.sma_short = btind.SimpleMovingAverage(self.premium_rate, period=self.p.short_period)
        self.sma_long = btind.SimpleMovingAverage(self.premium_rate, period=self.p.long_period)

        # Calculate MA crossover signal
        # CrossOver > 0: Short-term MA crosses above long-term MA (golden cross)
        # CrossOver < 0: Short-term MA crosses below long-term MA (death cross)
        self.crossover = btind.CrossOver(self.sma_short, self.sma_long)

        # Record order
        self.order = None

    def notify_order(self, order):
        """Order status notification."""
        if order.status in [order.Submitted, order.Accepted]:
            # Order submitted/accepted - no action needed
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(
                    f"Buy executed, Price: {order.executed.price:.2f}, "
                    f"Cost: {order.executed.value:.2f}, "
                    f"Commission: {order.executed.comm:.2f}"
                )
            elif order.issell():
                self.log(
                    f"Sell executed, Price: {order.executed.price:.2f}, "
                    f"Cost: {order.executed.value:.2f}, "
                    f"Commission: {order.executed.comm:.2f}"
                )

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log("Order canceled/insufficient margin/rejected")

        # Reset order
        self.order = None

    def notify_trade(self, trade):
        """Trade notification."""
        if not trade.isclosed:
            return

        self.log(f"Trade P&L, Gross: {trade.pnl:.2f}, Net: {trade.pnlcomm:.2f}")

    def next(self):
        """Core strategy logic."""
        # If there's a pending order, wait
        if self.order:
            return

        # Record current state
        current_date = bt.num2date(self.datas[0].datetime[0]).strftime("%Y-%m-%d")
        premium_rate = self.premium_rate[0]
        sma_short = self.sma_short[0]
        sma_long = self.sma_long[0]

        # Check if already has position
        if not self.position:
            # No position, check for golden cross buy signal
            if self.crossover > 0:
                # Golden cross signal: short-term MA crosses above long-term MA
                self.log(
                    f"Golden cross signal - Buy, Premium rate: {premium_rate:.2f}%, "
                    f"Short MA: {sma_short:.2f}, Long MA: {sma_long:.2f}"
                )
                # Use 95% of available cash to buy (leave some as commission buffer)
                cash = self.broker.getcash()
                size = int((cash * 0.95) / self.datas[0].close[0])
                self.order = self.buy(size=size)
        else:
            # Has position, check for death cross sell signal
            if self.crossover < 0:
                # Death cross signal: short-term MA crosses below long-term MA
                self.log(
                    f"Death cross signal - Sell, Premium rate: {premium_rate:.2f}%, "
                    f"Short MA: {sma_short:.2f}, Long MA: {sma_long:.2f}"
                )
                # Close position
                self.order = self.close()


def load_bond_data(csv_file):
    """
    Load convertible bond data.

    Args:
        csv_file: CSV file path

    Returns:
        Processed DataFrame
    """
    print(f"Loading data: {csv_file}")
    df = pd.read_csv(csv_file)

    # Rename columns
    df.columns = [
        "BOND_CODE",
        "BOND_SYMBOL",
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "pure_bond_value",
        "convert_value",
        "pure_bond_premium_rate",
        "convert_premium_rate",
    ]

    # Convert date format
    df["datetime"] = pd.to_datetime(df["datetime"])

    # Set index
    df = df.set_index("datetime")

    # Drop unnecessary columns
    df = df.drop(["BOND_CODE", "BOND_SYMBOL"], axis=1)

    # Drop missing values
    df = df.dropna()

    # Convert to float
    df = df.astype(float)

    print(f"Data loaded: {len(df)} records")
    print(f"Date range: {df.index[0]} to {df.index[-1]}")

    return df


def run_strategy(csv_file="113013.csv", initial_cash=100000.0, commission=0.0003):
    """
    Run backtest strategy.

    Args:
        csv_file: Convertible bond data CSV file
        initial_cash: Initial capital
        commission: Commission rate
    """
    print("=" * 60)
    print("Convertible Bond Premium Rate MA Crossover Strategy Backtest")
    print("=" * 60)

    # Create Cerebro engine
    cerebro = bt.Cerebro()

    # Add strategy
    cerebro.addstrategy(PremiumRateCrossoverStrategy)

    # Load data
    df = load_bond_data(csv_file)

    # Create data feed
    data = ExtendPandasFeed(dataname=df)

    # Add data to Cerebro
    cerebro.adddata(data)

    # Set initial capital
    cerebro.broker.setcash(initial_cash)
    print(f"\nInitial capital: {initial_cash:.2f}")

    # Set commission
    cerebro.broker.setcommission(commission=commission)
    print(f"Commission rate: {commission*100:.2f}%")

    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="time_return")

    print("\nStarting backtest...")
    print("-" * 60)

    # Run backtest
    results = cerebro.run()
    strat = results[0]

    # Get final capital
    final_value = cerebro.broker.getvalue()

    print("-" * 60)
    print("\nBacktest results:")
    print("=" * 60)
    print(f"Initial capital: {initial_cash:.2f}")
    print(f"Final capital: {final_value:.2f}")
    print(f"Total profit: {final_value - initial_cash:.2f}")
    print(f"Return rate: {(final_value / initial_cash - 1) * 100:.2f}%")

    # Get analysis results
    sharpe_ratio = strat.analyzers.sharpe.get_analysis()
    returns = strat.analyzers.returns.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    trades = strat.analyzers.trades.get_analysis()

    print(f"\nSharpe ratio: {sharpe_ratio.get('sharperatio', 'N/A')}")
    if "rnorm100" in returns:
        print(f"Annual return: {returns['rnorm100']:.2f}%")
    print(f"Max drawdown: {drawdown['max']['drawdown']:.2f}%")

    if "total" in trades:
        print(f"\nTotal trades: {trades['total'].get('total', 0)}")
        if "won" in trades["total"]:
            print(f"Winning trades: {trades['total']['won']}")
        if "lost" in trades["total"]:
            print(f"Losing trades: {trades['total']['lost']}")

    # Get time series returns for plotting
    time_return = strat.analyzers.time_return.get_analysis()

    return cerebro, results, time_return


def plot_results(time_return, initial_cash=100000.0, csv_file="113013.csv"):
    """
    Plot backtest result charts.

    Args:
        time_return: Time series returns
        initial_cash: Initial capital
        csv_file: Data filename (for title)
    """
    # Convert to DataFrame
    returns_df = pd.DataFrame(list(time_return.items()), columns=["date", "return"])
    returns_df["date"] = pd.to_datetime(returns_df["date"])
    returns_df = returns_df.set_index("date")

    # Calculate cumulative net value
    returns_df["cumulative"] = (1 + returns_df["return"]).cumprod()
    returns_df["value"] = returns_df["cumulative"] * initial_cash

    # Create figure
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))

    # Plot asset curve
    ax1.plot(returns_df.index, returns_df["value"], linewidth=2, color="#1f77b4")
    ax1.set_title(f"Strategy Asset Curve - {csv_file}", fontsize=16, pad=20)
    ax1.set_xlabel("Date", fontsize=12)
    ax1.set_ylabel("Asset Value (Yuan)", fontsize=12)
    ax1.grid(True, linestyle="--", alpha=0.6)

    # Format y-axis
    def format_yuan(x, pos):
        if x >= 10000:
            return f"{x/10000:.1f}w"
        return f"{x:.0f}"

    ax1.yaxis.set_major_formatter(FuncFormatter(format_yuan))

    # Format x-axis dates
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax1.xaxis.set_major_locator(mdates.YearLocator())
    fig.autofmt_xdate()

    # Add start and end point annotations
    start_value = returns_df["value"].iloc[0]
    end_value = returns_df["value"].iloc[-1]
    start_date = returns_df.index[0].strftime("%Y-%m-%d")
    end_date = returns_df.index[-1].strftime("%Y-%m-%d")

    ax1.annotate(
        f"Start: {start_date}\n{start_value:.0f} Yuan",
        xy=(returns_df.index[0], start_value),
        xytext=(10, 10),
        textcoords="offset points",
        bbox=dict(boxstyle="round,pad=0.5", fc="yellow", alpha=0.5),
    )

    ax1.annotate(
        f"End: {end_date}\n{end_value:.0f} Yuan",
        xy=(returns_df.index[-1], end_value),
        xytext=(-100, 10),
        textcoords="offset points",
        bbox=dict(boxstyle="round,pad=0.5", fc="yellow", alpha=0.5),
    )

    # Plot cumulative returns
    returns_df["cumulative_pct"] = (returns_df["cumulative"] - 1) * 100
    ax2.plot(returns_df.index, returns_df["cumulative_pct"], linewidth=2, color="#2ca02c")
    ax2.set_title("Cumulative Returns", fontsize=16, pad=20)
    ax2.set_xlabel("Date", fontsize=12)
    ax2.set_ylabel("Return (%)", fontsize=12)
    ax2.grid(True, linestyle="--", alpha=0.6)
    ax2.axhline(y=0, color="r", linestyle="--", alpha=0.5)

    # Format x-axis dates
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax2.xaxis.set_major_locator(mdates.YearLocator())

    # Calculate statistics
    total_return = (end_value / start_value - 1) * 100
    days = (returns_df.index[-1] - returns_df.index[0]).days
    annual_return = ((end_value / start_value) ** (365 / days) - 1) * 100

    # Add statistics text box
    stats_text = (
        f"Cumulative return: {total_return:.2f}%\nAnnual return: {annual_return:.2f}%\nBacktest days: {days}"
    )
    fig.text(
        0.15,
        0.47,
        stats_text,
        bbox=dict(facecolor="white", alpha=0.8, edgecolor="gray", boxstyle="round,pad=0.5"),
    )

    plt.tight_layout()

    # Save image
    output_file = csv_file.replace(".csv", "_strategy_result.png")
    plt.savefig(output_file, dpi=150, bbox_inches="tight")
    print(f"\nChart saved to: {output_file}")

    # Show figure
    plt.show()


if __name__ == "__main__":
    # Configuration parameters
    CSV_FILE = "113013.csv"  # Convertible bond data file
    INITIAL_CASH = 100000.0  # Initial capital: 100,000 yuan
    COMMISSION = 0.0003  # Commission rate: 0.03%

    # Run backtest
    cerebro, results, time_return = run_strategy(
        csv_file=CSV_FILE, initial_cash=INITIAL_CASH, commission=COMMISSION
    )

    # Plot results
    print("\nGenerating charts...")
    plot_results(time_return, initial_cash=INITIAL_CASH, csv_file=CSV_FILE)

    print("\n" + "=" * 60)
    print("Backtest completed")
    print("=" * 60)
