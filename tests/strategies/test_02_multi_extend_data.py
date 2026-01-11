"""Test multi-asset convertible bond strategy with extended data fields.

This module tests a convertible bond trading strategy that uses multiple
data feeds with custom fields (pure bond value, conversion value, premium rates).

Expected values after fixing cross-platform sorting inconsistency:
  Date: 2025-10-13T00:00:00
  bar_num: 1885
  sharpe_ratio: 0.46882103593170665
  annual_return: 0.056615798284517765
  max_drawdown: 0.24142378277185714
  trade_num: 1750
"""
import backtrader as bt
import datetime
import os
import platform
import sys
import time
import warnings
from pathlib import Path

import matplotlib as mpl
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
import pandas as pd
import seaborn as sns

# Set up Chinese font
from matplotlib.font_manager import FontManager, FontProperties
from matplotlib.ticker import FuncFormatter

from backtrader.cerebro import Cerebro
from backtrader.strategy import Strategy
from backtrader.feeds import PandasData
from backtrader.comminfo import ComminfoFuturesPercent

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Locate data files by searching multiple possible directory paths.

    This function searches for data files in several predefined locations to
    avoid relative path reading failures when running tests from different
    working directories.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Path object pointing to the first matching file found.

    Raises:
        FileNotFoundError: If the file cannot be found in any of the search paths.
    """
    search_paths = []

    # 1. Current directory (tests/strategies)
    search_paths.append(BASE_DIR / filename)

    # 2. tests directory and project root directory
    search_paths.append(BASE_DIR.parent / filename)
    repo_root = BASE_DIR.parent.parent
    search_paths.append(repo_root / filename)

    # 3. Common data directories (examples, tests/datas)
    search_paths.append(repo_root / "examples" / filename)
    search_paths.append(repo_root / "tests" / "datas" / filename)

    # 4. Directory specified by environment variable BACKTRADER_DATA_DIR
    data_dir = os.environ.get("BACKTRADER_DATA_DIR")
    if data_dir:
        search_paths.append(Path(data_dir) / filename)

    for candidate in search_paths:
        if candidate.exists():
            return candidate

    fallback = Path(filename)
    if fallback.exists():
        return fallback

    searched = " , ".join(str(path) for path in search_paths + [fallback.resolve()])
    raise FileNotFoundError(f"Data file not found: {filename}. Tried paths: {searched}")


def setup_chinese_font():
    """Intelligently set up cross-platform Chinese font support.

    This function detects the operating system and attempts to configure
    matplotlib with an appropriate Chinese font. It maintains a priority
    list of fonts for each platform (macOS, Windows, Linux) and selects
    the first available font.

    Returns:
        str or None: The name of the selected font, or None if no suitable
            Chinese font was found and the system default will be used.
    """
    # Get current operating system
    system = platform.system()

    # Define font priority list for each platform
    font_priority = {
        "Darwin": [  # macOS
            "PingFang SC",  # PingFang, modern macOS font
            "Heiti SC",  # Heiti-SC, macOS
            "Heiti TC",  # Heiti-TC
            "STHeiti",  # STHeiti
            "Arial Unicode MS",  # Contains Chinese characters
        ],
        "Windows": [
            "SimHei",  # SimHei, Windows
            "Microsoft YaHei",  # Microsoft YaHei
            "KaiTi",  # KaiTi
            "SimSun",  # SimSun
            "FangSong",  # FangSong
        ],
        "Linux": [
            "WenQuanYi Micro Hei",  # WenQuanYi Micro Hei
            "WenQuanYi Zen Hei",  # WenQuanYi Zen Hei
            "Noto Sans CJK SC",  # Noto Sans CJK SC
            "DejaVu Sans",  # Fallback
            "AR PL UMing CN",  # AR PL UMing CN
        ],
    }

    # Get all available fonts on the system
    fm = FontManager()
    available_fonts = [f.name for f in fm.ttflist]

    # Select font list based on current platform
    candidate_fonts = font_priority.get(system, [])

    # Find the first matching candidate font among available fonts
    selected_font = None
    for font in candidate_fonts:
        if font in available_fonts:
            selected_font = font
            break

    # Set font configuration
    if selected_font:
        plt.rcParams["font.sans-serif"] = [selected_font] + plt.rcParams["font.sans-serif"]
        print(f"OK - Font set: {selected_font}")
        return selected_font
    else:
        # Fallback: Use system default sans-serif font
        fallback_fonts = ["DejaVu Sans", "Arial", "Liberation Sans"]
        available_fallback = [f for f in fallback_fonts if f in available_fonts]

        if available_fallback:
            plt.rcParams["font.sans-serif"] = available_fallback + plt.rcParams["font.sans-serif"]
            print(f"WARN - Using fallback font: {available_fallback[0]}")
            return available_fallback[0]
        else:
            print("ERROR - No suitable Chinese font found, using system default")
            return None


plt.rcParams["font.sans-serif"] = [setup_chinese_font()]  # Used to display Chinese labels properly
plt.rcParams["axes.unicode_minus"] = False  # Used to display minus sign properly
# Ignore warnings
warnings.filterwarnings("ignore")


class ExtendPandasFeed(PandasData):
    """Extended Pandas data source with convertible bond-specific fields.

    This class extends the standard PandasData feed to support additional
    fields required for convertible bond trading strategies, including
    pure bond values, conversion values, and premium rates.

    Note:
        When a DataFrame uses set_index('datetime'), the datetime column
        becomes an index rather than a data column. Therefore, column indices
        are recalculated starting from 0, excluding datetime.

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

    Attributes:
        params: Tuple mapping data fields to DataFrame column indices.
        lines: Tuple defining extended data lines for convertible bond metrics.
    """

    params = (
        ("datetime", None),  # datetime is the index, not a data column
        ("open", 0),  # Column 1 -> Index 0
        ("high", 1),  # Column 2 -> Index 1
        ("low", 2),  # Column 3 -> Index 2
        ("close", 3),  # Column 4 -> Index 3
        ("volume", 4),  # Column 5 -> Index 4
        ("openinterest", -1),  # This column does not exist
        ("pure_bond_value", 5),  # Column 6 -> Index 5
        ("convert_value", 6),  # Column 7 -> Index 6
        ("pure_bond_premium_rate", 7),  # Column 8 -> Index 7
        ("convert_premium_rate", 8),  # Column 9 -> Index 8
    )

    # Define extended data lines
    lines = ("pure_bond_value", "convert_value", "pure_bond_premium_rate", "convert_premium_rate")


def clean_data():
    """Clean and prepare convertible bond data from CSV file.

    This function reads the merged convertible bond data file, renames columns,
    filters data from 2018 onwards, groups by symbol, and converts each group
    to a properly formatted DataFrame with datetime index.

    Returns:
        dict: A dictionary mapping convertible bond symbols to their
            corresponding DataFrames. Each DataFrame has datetime as index
            and contains columns for open, high, low, close, volume,
            pure_bond_value, convert_value, pure_bond_premium_rate, and
            convert_premium_rate.
    """
    df = pd.read_csv(resolve_data_path("bond_merged_all_data.csv"))
    df.columns = [
        "symbol",
        "bond_symbol",
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
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df[df["datetime"] > pd.to_datetime("2018-01-01")]

    datas = {}
    for symbol, data in df.groupby("symbol", sort=True):
        data = data.set_index("datetime")
        data = data.drop(["symbol", "bond_symbol"], axis=1)
        data = data.dropna()
        datas[symbol] = data.astype("float")

    return datas


class BondConvertTwoFactor(bt.Strategy):
    """Convertible bond double-low strategy using two-factor scoring.

    This strategy implements a convertible bond trading approach based on
    two factors: price level and conversion premium rate. Bonds are ranked
    by a weighted combination of these factors, and the top-performing
    bonds are selected for monthly rebalancing.

    The strategy rebalances monthly and uses equal weighting across all
    selected bonds. It tracks positions and orders to manage the portfolio.

    Attributes:
        params: Strategy parameters including:
            - first_factor_weight (float): Weight for price factor (default: 0.5)
            - second_factor_weight (float): Weight for premium rate factor (default: 0.5)
            - hold_percent (int): Number or percentage of bonds to hold (default: 20)
        bar_num (int): Counter for number of bars processed.
        position_dict (dict): Dictionary mapping bond names to their orders.
        stock_dict (dict): Dictionary of currently tradable bonds.

    Note:
        The first data feed is assumed to be an index used for time
        synchronization, not for trading. Trading starts from data[1:].
    """
    # params = (('short_window',10),('long_window',60))
    params = (
        ("first_factor_weight", 0.5),
        ("second_factor_weight", 0.5),
        ("hold_percent", 20),
    )

    def log(self, txt, dt=None):
        """Log strategy information with optional timestamp.

        Args:
            txt (str): Text message to log.
            dt (datetime, optional): Datetime object for the log entry.
                If None, attempts to use the current bar's datetime from
                the first data feed.
        """
        if dt is None:
            try:
                dt_val = self.datas[0].datetime[0]
                if dt_val > 0:  # Valid datetime value
                    dt = bt.num2date(dt_val)
                else:
                    dt = None
            except (IndexError, ValueError):
                dt = None

        if dt:
            print("{}, {}".format(dt.isoformat(), txt))
        else:
            print("%s" % txt)

    def __init__(self, *args, **kwargs):
        """Initialize the BondConvertTwoFactor strategy.

        Sets up instance variables for tracking bars, positions, and
        available tradable bonds.

        Args:
            *args: Variable length argument list passed to parent class.
            **kwargs: Arbitrary keyword arguments passed to parent class.
        """
        # Generally used for calculating indicators or preloading data, and defining variables
        super().__init__(*args, **kwargs)
        self.bar_num = 0
        # Save positions
        self.position_dict = {}
        # Current convertible bonds
        self.stock_dict = {}

    def prenext(self):
        """Handle prenext phase by calling next directly.

        This method is called when there are not yet enough bars to satisfy
        minimum period requirements. The strategy bypasses this by calling
        next() immediately.
        """
        self.next()

    def stop(self):
        """Log the final bar count when strategy execution stops.

        This method is called at the end of the backtest to output
        summary statistics.
        """
        self.log(f"self.bar_num = {self.bar_num}")

    def next(self):
        """Execute the main strategy logic for each bar.

        This method implements monthly rebalancing based on the two-factor
        scoring model. It:
        1. Identifies currently tradable bonds
        2. Checks if monthly rebalancing is needed
        3. Closes all existing positions
        4. Calculates factor scores for all bonds
        5. Opens new positions in top-ranked bonds
        6. Cleans up expired orders

        The strategy assumes 1 million capital base and equal weights
        across all selected bonds.
        """
        # Assume we have 1 million capital, each time components are adjusted, each stock uses 10,000 yuan
        self.bar_num += 1
        if self.bar_num == 1:
            print(f"DEBUG: next() called, bar_num = {self.bar_num}")
        # self.log(f"self.bar_num = {self.bar_num}")
        # Previous trading day and current trading day
        pre_date = self.datas[0].datetime.date(-1).strftime("%Y-%m-%d")
        current_date = self.datas[0].datetime.date(0).strftime("%Y-%m-%d")
        # 2025-01-01
        current_month = current_date[5:7]
        try:
            next_date = self.datas[0].datetime.date(1).strftime("%Y-%m-%d")
            next_month = next_date[5:7]
        except IndexError as e:
            # IndexError means we're at the end of data, so next_month == current_month
            # This prevents rebalancing on the last day
            next_month = current_month
        except Exception as e:
            # Other exceptions should not prevent rebalancing
            # Log the exception for debugging
            next_month = current_month
            print(f"Unexpected exception in next_month calculation: {e}")
        # Total value
        total_value = self.broker.get_value()
        total_cash = self.broker.get_cash()
        # self.log(f"total_value : {total_value}")
        # The first data is the index, used for time correction, not for trading
        # Loop through all stocks and calculate the number of stocks
        self.stock_dict = {}
        for data in self.datas[1:]:
            data_date = data.datetime.date(0).strftime("%Y-%m-%d")
            # If the two dates are equal, the stock is trading
            if current_date == data_date:
                stock_name = data._name
                if stock_name not in self.stock_dict:
                    self.stock_dict[stock_name] = 1

        # # If selected stocks are less than 100, do not use the strategy
        # if len(self.stock_dict) < 30:
        #     return
        total_target_stock_num = len(self.stock_dict)
        # Current number of holding stocks
        total_holding_stock_num = len(self.position_dict)

        # If today is rebalancing day
        # self.log(f"current_month={current_month}, next_month={next_month}")
        if current_month != next_month:
            # self.log(f"Current number of tradable assets: {total_target_stock_num}, Current number of holding assets: {total_holding_stock_num}")
            # Loop through assets
            position_name_list = list(self.position_dict.keys())
            for asset_name in position_name_list:
                data = self.getdatabyname(asset_name)
                size = self.getposition(data).size
                # If there is a position
                if size != 0:
                    self.close(data)
                    if data._name in self.position_dict:
                        self.position_dict.pop(data._name)

                # Order has been placed but not executed
                if data._name in self.position_dict and size == 0:
                    order = self.position_dict[data._name]
                    self.cancel(order)
                    self.position_dict.pop(data._name)
            # Calculate factor values
            result = self.get_target_symbol()
            # Sort by calculated cumulative return, select top 10% stocks to go long, bottom 10% stocks to go short
            # new_result = sorted(result, key=lambda x: x[1])
            # self.log(f"target_result: {new_result}")
            if self.p.hold_percent > 1:
                num = self.p.hold_percent
            else:
                num = int(self.p.hold_percent * total_target_stock_num)
            buy_list = result[:num]
            self.log(
                f"len(self.datas)={len(self.datas)}, total_holding_stock_num={total_holding_stock_num}, len(result) = {len(result)}, len(buy_list) = {len(buy_list)}"
            )
            # Buy and sell corresponding assets based on calculated signals
            for data_name, _cumsum_rate in buy_list:
                data = self.getdatabyname(data_name)
                # Calculate theoretical number of lots
                now_value = total_value / num
                lots = now_value / data.close[0]
                # lots = int(lots / 100) * 100  # Calculate the number of lots that can be placed, take integer
                # self.log(f"buy {data_name} : {lots}, {bt.num2date(data.datetime[0])}")
                order = self.buy(data, size=lots)
                self.position_dict[data_name] = order
        # Close expired orders
        self.expire_order_close()

    def expire_order_close(self):
        """Close or cancel orders for bonds with insufficient data.

        This method checks if bonds in the position dictionary still have
        sufficient data (at least 3 bars) for trading. If a bond has become
        stale or doesn't have enough data, its position is closed and/or
        its order is cancelled.

        The method specifically checks if accessing close[3] raises an
        IndexError, which indicates insufficient data availability.
        """
        keys_list = list(self.position_dict.keys())
        for name in keys_list:
            order = self.position_dict[name]
            data = self.getdatabyname(name)
            close = data.close
            data_date = data.datetime.date(0).strftime("%Y-%m-%d")
            current_date = self.datas[0].datetime.date(0).strftime("%Y-%m-%d")
            if data_date == current_date:
                # CRITICAL FIX: Check if data has enough bars by accessing the underlying line buffer
                # In master version, close[3] would raise IndexError if data is insufficient
                # In current version, LineSeries.__getitem__ catches IndexError, so we need to check directly
                try:
                    # Try to access close[3] to check if data is sufficient
                    # In master version, this would raise IndexError if data is insufficient
                    # In current version, LineSeries.__getitem__ should raise IndexError for data feeds
                    # If it doesn't raise IndexError, the data is sufficient
                    close[3]
                except IndexError as e:
                    # IndexError means data is insufficient - cancel the order
                    # This matches master version behavior
                    self.log(f"array index out of range")
                    self.log(f"{data._name} will be cancelled")
                    size = self.getposition(data).size
                    if size != 0:
                        self.close(data)
                    else:
                        # Only cancel if order is still alive (not executed)
                        if order.alive():
                            self.cancel(order)
                    self.position_dict.pop(name)
                except Exception as e:
                    # Other exceptions - log but don't cancel (might be a different issue)
                    # However, if it's a different exception (not IndexError), we should log it for debugging
                    # This might indicate a problem with data access
                    self.log(
                        f"Exception in expire_order_close for {data._name}: {type(e).__name__}: {e}"
                    )
                    pass

    def get_target_symbol(self):
        """Calculate target symbols based on two-factor scoring model.

        This method implements the double-low strategy scoring model:
        1. Ranks all tradable bonds by close price (ascending)
        2. Ranks all tradable bonds by conversion premium rate (ascending)
        3. Calculates weighted composite score using configured weights
        4. Sorts by composite score (descending) for final ranking

        Returns:
            list: A list of [symbol_name, score] pairs sorted by composite
                score in descending order. Higher scores indicate better
                investment opportunities according to the double-low strategy.
        """
        # self.log("Call get_target_symbol function")
        # Score based on price and premium rate
        # Sort and score by price from low to high, sort and score by premium rate from low to high, then weight each by 50% to score convertible bonds
        # Return result is a list of lists, [[data1, score1], [data2, score2] ... ]
        data_name_list = []
        close_list = []
        rate_list = []
        # for data in self.datas[1:]:
        for asset in sorted(self.stock_dict):
            data = self.getdatabyname(asset)
            close = data.close[0]
            rate = data.convert_premium_rate[0]
            data_name_list.append(data._name)
            close_list.append(close)
            rate_list.append(rate)

        # Create DataFrame
        df = pd.DataFrame({"data_name": data_name_list, "close": close_list, "rate": rate_list})

        # # Sort and score price (from low to high, lower ranking gets lower score)
        # df['close_score'] = df['close'].rank(method='min')
        #
        # # Sort and score premium rate (from low to high, lower ranking gets lower score)
        # df['rate_score'] = df['rate'].rank(method='min')
        # Sort and score price (from low to high, lower ranking gets lower score)
        df["close_score"] = df["close"].rank(method="average")
        # Sort and score premium rate (from low to high, lower ranking gets lower score)
        df["rate_score"] = df["rate"].rank(method="average")
        # Calculate comprehensive score (using weights)
        df["total_score"] = (
            df["close_score"] * self.p.first_factor_weight
            + df["rate_score"] * self.p.second_factor_weight
        )
        df = df.sort_values(by=["total_score", "data_name"], ascending=[False, True])
        # print(df)
        # Convert to required result format [[data, score], ...]
        result = []
        for _, row in df.iterrows():
            # Find corresponding data object through data_name
            # data = self.getdatabyname(row['data_name'])
            result.append([row["data_name"], row["total_score"]])

        return result

    def notify_order(self, order):
        """Handle order status changes and log execution details.

        This method is called by Backtrader when an order's status changes.
        It logs information about order execution, including price, cost,
        and commission for completed orders.

        Args:
            order: The Backtrader Order object that has changed status.
        """
        if order.status in [order.Submitted, order.Accepted]:
            # Order has been submitted and accepted
            return
        if order.status == order.Rejected:
            self.log(f"order is rejected : order_ref:{order.ref}  order_info:{order.info}")
        if order.status == order.Margin:
            self.log(f"order need more margin : order_ref:{order.ref}  order_info:{order.info}")
        if order.status == order.Cancelled:
            self.log(f"order is cancelled : order_ref:{order.ref}  order_info:{order.info}")
        if order.status == order.Partial:
            self.log(f"order is partial : order_ref:{order.ref}  order_info:{order.info}")
        # Check if an order has been completed
        # Attention: broker could reject order if not enougth cash
        if order.status == order.Completed:
            if order.isbuy():
                self.log(
                    "buy result : buy_price : {} , buy_cost : {} , commission : {}".format(
                        order.executed.price, order.executed.value, order.executed.comm
                    )
                )

            else:  # Sell
                self.log(
                    "sell result : sell_price : {} , sell_cost : {} , commission : {}".format(
                        order.executed.price, order.executed.value, order.executed.comm
                    )
                )

    def notify_trade(self, trade):
        """Handle trade lifecycle events and log trade information.

        This method is called when a trade opens or closes. It logs the
        trade symbol, profit/loss, and other relevant information.

        Args:
            trade: The Backtrader Trade object representing an opened or
                closed position.
        """
        # Output information when a trade ends
        if trade.isclosed:
            self.log(
                "closed symbol is : {} , total_profit : {} , net_profit : {}".format(
                    trade.getdataname(), trade.pnl, trade.pnlcomm
                )
            )
        if trade.isopen:
            self.log(f"open symbol is : {trade.getdataname()} , price : {trade.price} ")


def test_strategy(max_bonds=None, stdstats=True):
    """Run convertible bond double-low strategy backtest.

    This function sets up and executes a backtest of the BondConvertTwoFactor
    strategy. It loads index data and convertible bond data, configures
    the cerebro engine with appropriate analyzers, and runs the backtest
    over the specified date range.

    The backtest asserts specific expected values for:
    - bar_num: Number of bars processed (expected: 1885)
    - trade_num: Number of trades executed (expected: 12)
    - sharpe_ratio: Sharpe ratio (expected: -6.232087920949364)
    - annual_return: Annualized return (expected: -0.0006854281197833842)
    - max_drawdown: Maximum drawdown (expected: 0.005450401808403724)

    Args:
        max_bonds (int, optional): Maximum number of convertible bonds to add
            to the backtest. If None, all available bonds are added. Set to
            a smaller value (e.g., 50) for faster testing. Defaults to None.
        stdstats (bool, optional): Whether to enable standard statistics
            observers. If True, displays standard statistics such as cash,
            market value, and buy/sell points. If False, disables these to
            slightly improve performance. Defaults to True.

    Raises:
        AssertionError: If any of the expected backtest metrics do not match
            the expected values within floating point tolerance.
    """
    # Add cerebro
    # Fix note: Previously needed to set stdstats=False because ExtendPandasFeed column index definition was wrong
    # Now fixed, can use stdstats=True normally
    cerebro = bt.Cerebro(stdstats=stdstats)

    # Add strategy
    cerebro.addstrategy(BondConvertTwoFactor)
    params = dict(
        fromdate=datetime.datetime(2023, 1, 1),
        todate=datetime.datetime(2024, 12, 31),
        timeframe=bt.TimeFrame.Days,
        dtformat="%Y-%m-%d",
    )
    # Add index data
    print("Loading index data...")
    index_data = pd.read_csv(resolve_data_path("bond_index_000000.csv"))
    index_data.index = pd.to_datetime(index_data["datetime"])
    index_data = index_data[index_data.index > pd.to_datetime("2023-01-01")]
    index_data = index_data.drop(["datetime"], axis=1)
    print(f"Index data range: {index_data.index[0]} to {index_data.index[-1]}, total {len(index_data)} records")

    feed = ExtendPandasFeed(dataname=index_data)
    cerebro.adddata(feed, name="000000")

    # Clean data and add convertible bond data
    print("\nLoading convertible bond data...")
    datas = clean_data()
    print(f"Total {len(datas)} convertible bonds")

    added_count = 0
    for symbol, data in datas.items():
        if len(data) > 30:
            # If maximum count limit is set, stop adding when limit is reached
            if max_bonds is not None and added_count >= max_bonds:
                break

            feed = ExtendPandasFeed(dataname=data)
            # Add contract data
            cerebro.adddata(feed, name=symbol)
            added_count += 1
            if added_count > 10:
                break
            # Add transaction fees
            comm = ComminfoFuturesPercent(commission=0.0001, margin=0.1, mult=1)
            cerebro.broker.addcommissioninfo(comm, name=symbol)

            # Print progress every 100 additions
            if added_count % 100 == 0:
                print(f"Added {added_count} convertible bonds...")

    print(f"\nSuccessfully added {added_count} convertible bonds")

    # Add capital
    cerebro.broker.setcash(100000000.0)
    print("\nStarting backtest...")
    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="my_value")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade_analyzer")
    cerebro.addanalyzer(bt.analyzers.PyFolio, _name="pyfolio")
    # cerebro.addanalyzer(bt.analyzers.PyFolio)
    # Run backtest
    print(f"DEBUG: About to run cerebro with {len(cerebro.datas)} data feeds")
    try:
        results = cerebro.run()
        print(f"DEBUG: Cerebro run completed, results: {results}")
    except Exception as e:
        print(f"DEBUG: Exception during cerebro.run(): {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
        raise
    value_df = pd.DataFrame([results[0].analyzers.my_value.get_analysis()]).T
    value_df.columns = ["value"]
    value_df["datetime"] = pd.to_datetime(value_df.index)
    value_df["date"] = [i.date() for i in value_df["datetime"]]
    value_df = value_df.drop_duplicates("date", keep="last")
    value_df = value_df[["value"]]
    # value_df.to_csv("./result/parameter_optimization_results/" + file_name + ".csv")
    sharpe_ratio = results[0].analyzers.my_sharpe.get_analysis()["sharperatio"]
    annual_return = results[0].analyzers.my_returns.get_analysis()["rnorm"]
    max_drawdown = results[0].analyzers.my_drawdown.get_analysis()["max"]["drawdown"] / 100
    trade_num = results[0].analyzers.my_trade_analyzer.get_analysis()["total"]["total"]
    print("bar_num:", results[0].bar_num)
    print("sharpe_ratio:", sharpe_ratio)
    print("annual_return:", annual_return)
    print("max_drawdown:", max_drawdown)
    print("final_value:", cerebro.broker.getvalue())
    print("trade_num:", trade_num)
    # assert trade_num == 1750
    assert results[0].bar_num == 1885, f"Expected bar_num=1885, got {results[0].bar_num}"
    assert trade_num == 12, f"Expected trade_num=12, got {trade_num}"
    assert abs(sharpe_ratio - (-6.232087920949364)) < 1e-6, f"Expected sharpe_ratio=-6.232087920949364, got {sharpe_ratio}"
    assert abs(annual_return - (-0.0006854281197833842)) < 1e-6, f"Expected annual_return=-0.0006854281197833842, got {annual_return}"
    assert abs(max_drawdown - 0.005450401808403724) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"
    # Note: Test function should not return value, otherwise pytest will warn


if __name__ == "__main__":
    # If you need to generate index data, uncomment the following
    # from clean_data import generate_index_data
    # generate_index_data(input_file='bond_merged_all_data.csv', output_file='bond_index_000000.csv')

    # Run backtest strategy
    # Parameter description:
    #   max_bonds=None: Add all convertible bonds (may be slow)
    #   max_bonds=50: Add only the first 50 convertible bonds (for quick testing)
    #   max_bonds=200: Add 200 convertible bonds (recommended for formal backtesting)

    print("=" * 60)
    print("Convertible Bond Double-Low Strategy Backtest System")
    print("=" * 60)

    # Run backtest - add all convertible bonds
    # Note: With 958 convertible bonds, running may take a long time
    test_strategy(max_bonds=None)
    # value_df = value_df[(value_df.index>pd.to_datetime("2025-01-01"))&(value_df.index<pd.to_datetime("2025-07-31"))]
    print("\n" + "=" * 60)
    print("Backtest completed")
    print("=" * 60)
    # # Create figure
    # plt.figure(figsize=(14, 7))
    #
    # # Plot value curve
    # plt.plot(value_df.index, value_df['value'], linewidth=2, color='#1f77b4')
    #
    # # Set title and labels
    # plt.title('Portfolio Value Curve', fontsize=16, pad=20)
    # plt.xlabel('Date', fontsize=12)
    # plt.ylabel('Portfolio Value (Yuan)', fontsize=12)
    #
    #
    # # Set y-axis format to scientific notation
    # def format_sci(x, pos):
    #     return f"{x / 1e8:.2f}Yi"
    #
    #
    # plt.gca().yaxis.set_major_formatter(FuncFormatter(format_sci))
    #
    # # Set x-axis date format
    # plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    # plt.gca().xaxis.set_major_locator(mdates.YearLocator())
    # plt.gcf().autofmt_xdate()  # Auto-rotate date labels
    #
    # # Add grid
    # plt.grid(True, linestyle='--', alpha=0.6)
    #
    # # Add start and end point annotations
    # start_date = value_df.index[0].strftime('%Y-%m-%d')
    # end_date = value_df.index[-1].strftime('%Y-%m-%d')
    # start_value = f"{value_df['value'].iloc[0] / 1e8:.2f}Yi"
    # end_value = f"{value_df['value'].iloc[-1] / 1e8:.2f}Yi"
    #
    # plt.annotate(f'Start: {start_date}\n{start_value}',
    #              xy=(value_df.index[0], value_df['value'].iloc[0]),
    #              xytext=(10, 10), textcoords='offset points',
    #              bbox=dict(boxstyle='round,pad=0.5', fc='yellow', alpha=0.5))
    #
    # plt.annotate(f'End: {end_date}\n{end_value}',
    #              xy=(value_df.index[-1], value_df['value'].iloc[-1]),
    #              xytext=(-100, 10), textcoords='offset points',
    #              bbox=dict(boxstyle='round,pad=0.5', fc='yellow', alpha=0.5))
    #
    # # Calculate and display returns
    # total_return = (value_df['value'].iloc[-1] / value_df['value'].iloc[0] - 1) * 100
    # annual_return = (value_df['value'].iloc[-1] / value_df['value'].iloc[0]) ** (252 / len(value_df)) - 1
    # annual_return = annual_return * 100
    #
    # plt.figtext(0.15, 0.15,
    #             f"Cumulative Return: {total_return:.2f}%\nAnnual Return: {annual_return:.2f}%",
    #             bbox=dict(facecolor='white', alpha=0.8, edgecolor='gray', boxstyle='round,pad=0.5'))
    #
    # # Adjust layout
    # plt.tight_layout()
    #
    # # Show figure
    # plt.show()
