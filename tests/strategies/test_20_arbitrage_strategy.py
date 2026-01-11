"""Test cases for treasury bond futures inter-delivery spread arbitrage strategy

Test spread arbitrage strategy using CFFEX futures contract data
- Load futures data using PandasDirectData
- Spread-based inter-delivery arbitrage strategy with rollover support
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os
from pathlib import Path

import pandas as pd
import backtrader as bt
from backtrader.comminfo import ComminfoFuturesPercent

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Locate data files based on script directory to avoid relative path failures"""
    repo_root = BASE_DIR.parent.parent
    search_paths = [
        BASE_DIR / "datas" / filename,
        repo_root / "tests" / "datas" / filename,
        BASE_DIR / filename,
        BASE_DIR.parent / filename,
    ]
    
    data_dir = os.environ.get("BACKTRADER_DATA_DIR")
    if data_dir:
        search_paths.append(Path(data_dir) / filename)

    for candidate in search_paths:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(f"Data file not found: {filename}")


class TreasuryFuturesSpreadArbitrageStrategy(bt.Strategy):
    """Treasury bond futures inter-delivery spread arbitrage strategy.

    This strategy implements a calendar spread arbitrage approach for treasury bond
    futures by trading the price difference between near-term and far-term contracts.
    It opens positions when the spread between contracts exceeds predefined thresholds
    and closes positions when the spread reverts.

    The strategy supports automatic contract rollover when contracts expire and uses
    open interest to determine which contracts to trade.

    Attributes:
        author: Strategy author identifier.
        params: Strategy parameters including spread thresholds.
            - spread_low (float): Lower spread threshold for opening long positions.
            - spread_high (float): Upper spread threshold for opening short positions.
        bar_num: Counter for number of bars processed.
        buy_count: Counter for buy orders executed.
        sell_count: Counter for sell orders executed.
        current_date: Current trading date being processed.
        holding_contract_name: List of currently held contracts [near, far].
        market_position: Current market position (1=long, -1=short, 0=flat).

    Example:
        >>> cerebro = bt.Cerebro()
        >>> cerebro.addstrategy(
        ...     TreasuryFuturesSpreadArbitrageStrategy,
        ...     spread_low=0.06,
        ...     spread_high=0.52
        ... )
    """
    # Strategy author
    author = 'yunjinqi'
    # Strategy parameters
    params = (
        ("spread_low", 0.06),   # Spread lower threshold, open long below this value
        ("spread_high", 0.52),  # Spread upper threshold, open short above this value
    )

    # Log corresponding information
    def log(self, txt, dt=None):
        """Log strategy information with timestamp.

        Args:
            txt (str): Text message to log.
            dt (datetime, optional): Datetime object for the log entry.
                If None, uses the current bar's datetime from the first data feed.
        """
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('{}, {}'.format(dt.isoformat(), txt))

    # Initialize strategy data
    def __init__(self):
        """Initialize strategy attributes and state variables.

        Sets up counters for tracking bars, orders, and position state.
        Initializes holding contract tracking to None.
        """
        # Common attribute variables
        self.bar_num = 0  # Number of bars run in next
        self.buy_count = 0
        self.sell_count = 0
        self.current_date = None  # Current trading day
        # Save which contract is currently held
        self.holding_contract_name = None
        self.market_position = 0

    def prenext(self):
        """Handle prenext phase by delegating to next().

        Since futures contracts have different trading dates and the data has
        thousands of bars, this method ensures the strategy logic runs during
        the prenext phase by delegating to the next() method.
        """
        # Since futures data has thousands of bars and each futures contract has different trading dates, it won't naturally enter next
        # Need to call next function in each prenext to run
        self.next()
        # pass

    # Add corresponding strategy logic in next
    def next(self):
        """Execute main strategy logic for each bar.

        This method implements the spread arbitrage strategy:
        1. Identifies near-term and far-term contracts based on open interest
        2. Opens long positions when spread is below threshold (buy near, sell far)
        3. Opens short positions when spread is above threshold (sell near, buy far)
        4. Closes positions when spread reverts
        5. Handles contract rollover when contracts expire

        The strategy uses market_position to track state:
        - 0: No position
        - 1: Long spread (long near, short far)
        - -1: Short spread (short near, long far)
        """
        # Increment bar_num by 1 each time it runs, and update trading day
        self.current_date = bt.num2date(self.datas[0].datetime[0])
        self.bar_num += 1
        near_data, far_data = self.get_near_far_data()
        if near_data is not None:
            if self.market_position!=0:
                hold_near_data = self.holding_contract_name[0]
                hold_far_data = self.holding_contract_name[1]
                near_name = hold_near_data._name
                far_name = hold_far_data._name
            else:
                near_name = None
                far_name = None 
#             self.log(f"{near_data._name},{far_data._name},{near_name},{far_name},{self.market_position},{near_data.close[0]-far_data.close[0]}")
        else:
            self.log(f"near data is None------------------------------------------")

        # Open position
        if self.market_position == 0:
            # Open long
            if near_data.close[0] - far_data.close[0] < self.p.spread_low:
                self.buy(near_data, size=1)
                self.sell(far_data, size=1)
                self.buy_count += 1
                self.sell_count += 1
                self.market_position = 1
                self.holding_contract_name = [near_data, far_data]
                self.log(f"Open position, buy: {near_data._name}, sell: {far_data._name}")
            # Open short
            if near_data.close[0] - far_data.close[0] > self.p.spread_high:
                self.sell(near_data, size=1)
                self.buy(far_data, size=1)
                self.buy_count += 1
                self.sell_count += 1
                self.market_position = -1
                self.holding_contract_name = [near_data, far_data]
                self.log(f"Open short position, buy: {far_data._name}, sell: {near_data._name}")
        # Close position
        if self.market_position == 1:
            near_data = self.holding_contract_name[0]
            far_data = self.holding_contract_name[1]
            if near_data.close[0] - far_data.close[0] > self.p.spread_high:
                self.close(near_data)
                self.close(far_data)
                self.market_position = 0
                self.holding_contract_name = [None, None]

        if self.market_position == -1:
            near_data = self.holding_contract_name[0]
            far_data = self.holding_contract_name[1]
            if near_data.close[0] - far_data.close[0] < self.p.spread_low:
                self.close(near_data)
                self.close(far_data)
                self.market_position = 0
                self.holding_contract_name = [None, None]


        # Roll over to new contract
        if self.market_position != 0:
            hold_near_data = self.holding_contract_name[0]
            hold_far_data = self.holding_contract_name[1]
            near_data, far_data = self.get_near_far_data()
            if near_data is not None:
#                 self.log(f"{near_data._name},{far_data._name}, {hold_near_data._name},{hold_far_data._name}")
                if hold_near_data._name != near_data._name or hold_far_data._name != far_data._name:
#                     self.log("----------------Contract rollover occurred-------------------")
                    near_size = self.getposition(hold_near_data).size
                    far_size = self.getposition(hold_far_data).size
                    self.close(hold_far_data)
                    self.close(hold_near_data)
                    if near_size > 0:
                        self.buy(near_data, size = abs(near_size))
                        self.sell(far_data, size = abs(far_size))
                        self.holding_contract_name = [near_data, far_data]
                    else:
                        self.sell(near_data, size = abs(near_size))
                        self.buy(far_data, size = abs(far_size))
                        self.holding_contract_name = [near_data, far_data]

    def get_near_far_data(self):
        """Identify near-term and far-term contracts based on open interest.

        This method searches through all available data feeds (excluding the index)
        to find contracts trading on the current date. It sorts them by open interest
        and returns the two most active contracts. The near-term contract is typically
        the one with lower open interest among the top two, while the far-term has
        higher open interest.

        Returns:
            list: A list containing [near_data, far_data] where:
                - near_data: Data feed object for the near-term contract (or None)
                - far_data: Data feed object for the far-term contract (or None)
                Returns [None, None] if fewer than 2 contracts are available.
        """
        # Calculate prices of near-month and far-month contracts
        target_datas = []
        for data in self.datas[1:]:
            # self.log(self.current_date)
            # self.log(bt.num2date(data.datetime[0]))
            try:
                data_date = bt.num2date(data.datetime[0])
                # self.log(f"{data._name},{data_date}")
                if self.current_date == data_date:
                    target_datas.append([data._name, data.openinterest[0], data])
            except:
                self.log(f"{data._name} is not yet listed for trading")

        target_datas = sorted(target_datas, key=lambda x: x[1])
        if len(target_datas)>=2:
            if target_datas[-1][0] > target_datas[-2][0]:
                near_data = target_datas[-2][2]
                far_data = target_datas[-1][2]
            else:
                near_data = target_datas[-1][2]
                far_data = target_datas[-2][2]
            return [near_data, far_data]
        else:
            return [None, None]

    def get_dominant_contract(self):
        """Identify the dominant (most active) contract for the current date.

        The dominant contract is determined as the contract with the largest open interest
        among all contracts trading on the current date. This is a common method for
        identifying the most liquid contract in futures markets.

        Note:
            This method currently prints the sorted contracts but returns only the name.
            The logic can be customized to define dominance differently (e.g., by volume,
            by price, or by a combination of factors).

        Returns:
            str: The name/symbol of the dominant contract.
        """
        # Use the contract with the largest open interest as the dominant contract, return the data name
        # You can define how to calculate the dominant contract according to your needs

        # Get the varieties currently trading
        target_datas = []
        for data in self.datas[1:]:
            # self.log(self.current_date)
            # self.log(bt.num2date(data.datetime[0]))
            try:
                data_date = bt.num2date(data.datetime[0])
                # self.log(f"{data._name},{data_date}")
                if self.current_date == data_date:
                    target_datas.append([data._name, data.openinterest[0]])
            except:
                self.log(f"{data._name} is not yet listed for trading")

        target_datas = sorted(target_datas, key=lambda x: x[1])
        print(target_datas)
        return target_datas[-1][0]

    def notify_order(self, order):
        """Handle order status changes and log order execution details.

        This method is called by Backtrader when an order's status changes.
        It logs various order states including submission, rejection, margin calls,
        cancellations, partial fills, and completions.

        Args:
            order (backtrader.Order): The order object with updated status.
        """
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Rejected:
            self.log(f"Rejected : order_ref:{order.ref}  data_name:{order.p.data._name}")

        if order.status == order.Margin:
            self.log(f"Margin : order_ref:{order.ref}  data_name:{order.p.data._name}")

        if order.status == order.Cancelled:
            self.log(f"Concelled : order_ref:{order.ref}  data_name:{order.p.data._name}")

        if order.status == order.Partial:
            self.log(f"Partial : order_ref:{order.ref}  data_name:{order.p.data._name}")

        if order.status == order.Completed:
            if order.isbuy():
                self.log(
                    f" BUY : data_name:{order.p.data._name} price : {order.executed.price} , cost : {order.executed.value} , commission : {order.executed.comm}")

            else:  # Sell
                self.log(
                    f" SELL : data_name:{order.p.data._name} price : {order.executed.price} , cost : {order.executed.value} , commission : {order.executed.comm}")

    def notify_trade(self, trade):
        """Handle trade lifecycle events and log trade information.

        This method is called when a trade is opened or closed. It logs the trade's
        profit/loss when closed and the entry price when opened.

        Args:
            trade (backtrader.Trade): The trade object with updated status.
        """
        # Output information when a trade ends
        if trade.isclosed:
            self.log('closed symbol is : {} , total_profit : {} , net_profit : {}'.format(
                trade.getdataname(), trade.pnl, trade.pnlcomm))
            # self.trade_list.append([self.datas[0].datetime.date(0),trade.getdataname(),trade.pnl,trade.pnlcomm])

        if trade.isopen:
            self.log('open symbol is : {} , price : {} '.format(
                trade.getdataname(), trade.price))

    def stop(self):
        """Log final strategy statistics when backtesting completes.

        This method is called at the end of the backtest to output summary
        statistics including the number of bars processed and total buy/sell orders.
        """
        self.log(f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}")


def load_futures_data(variety: str = "T"):
    """Load futures data and construct index contract

    Args:
        variety: Variety code, default is T (treasury bond futures)

    Returns:
        index_df: Index contract DataFrame
        data: Original data DataFrame
    """
    data = pd.read_csv(resolve_data_path("CFFEX_Futures_Contract_Data.csv"), index_col=0)
    data = data[data['variety'] == variety]
    data['datetime'] = pd.to_datetime(data['date'], format="%Y%m%d")
    data = data.dropna()

    # Synthesize index contract by weighting with open interest
    result = []
    for index, df in data.groupby("datetime"):
        total_open_interest = df['open_interest'].sum()
        open_price = (df['open'] * df['open_interest']).sum() / total_open_interest
        high_price = (df['high'] * df['open_interest']).sum() / total_open_interest
        low_price = (df['low'] * df['open_interest']).sum() / total_open_interest
        close_price = (df['close'] * df['open_interest']).sum() / total_open_interest
        volume = (df['volume'] * df['open_interest']).sum() / total_open_interest
        open_interest = df['open_interest'].mean()
        result.append([index, open_price, high_price, low_price, close_price, volume, open_interest])
    
    index_df = pd.DataFrame(result, columns=['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest'])
    index_df.index = pd.to_datetime(index_df['datetime'])
    index_df = index_df.drop(["datetime"], axis=1)
    
    return index_df, data


def test_treasury_futures_spread_arbitrage_strategy():
    """Test treasury bond futures inter-delivery spread arbitrage strategy

    Backtest using CFFEX futures contract data
    """
    cerebro = bt.Cerebro(stdstats=True)

    # Load futures data
    print("Loading futures data...")
    index_df, data = load_futures_data("T")
    print(f"Index data range: {index_df.index[0]} to {index_df.index[-1]}, total {len(index_df)} bars")

    # Load index contract
    feed = bt.feeds.PandasDirectData(dataname=index_df)
    cerebro.adddata(feed, name='index')
    comm = ComminfoFuturesPercent(commission=0.0002, margin=0.02, mult=10000)
    cerebro.broker.addcommissioninfo(comm, name="index")

    # Load specific contract data
    contract_count = 0
    for symbol, df in data.groupby("symbol"):
        df.index = pd.to_datetime(df['datetime'])
        df = df[['open', 'high', 'low', 'close', 'volume', 'open_interest']]
        df.columns = ['open', 'high', 'low', 'close', 'volume', 'openinterest']
        feed = bt.feeds.PandasDirectData(dataname=df)
        cerebro.adddata(feed, name=symbol)
        comm = ComminfoFuturesPercent(commission=0.0002, margin=0.02, mult=10000)
        cerebro.broker.addcommissioninfo(comm, name=symbol)
        contract_count += 1

    print(f"Successfully loaded {contract_count} contracts")

    # Set initial capital
    cerebro.broker.setcash(1000000.0)

    # Add strategy
    cerebro.addstrategy(TreasuryFuturesSpreadArbitrageStrategy, spread_low=0.06, spread_high=0.52)

    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="my_value")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade_analyzer")

    # Run backtest
    print("\nStarting backtest...")
    results = cerebro.run()

    # Get results
    strat = results[0]
    sharpe_ratio = strat.analyzers.my_sharpe.get_analysis().get("sharperatio")
    annual_return = strat.analyzers.my_returns.get_analysis().get("rnorm")
    max_drawdown = strat.analyzers.my_drawdown.get_analysis()["max"]["drawdown"] / 100
    trade_analysis = strat.analyzers.my_trade_analyzer.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("total", 0)
    final_value = cerebro.broker.getvalue()

    # Print results
    print("\n" + "=" * 50)
    print("Treasury Bond Futures Inter-Delivery Spread Arbitrage Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value}")
    print("=" * 50)

    # Assert test results (exact values)
    assert strat.bar_num == 1990, f"Expected bar_num=1990, got {strat.bar_num}"
    assert strat.buy_count == 6, f"Expected buy_count=6, got {strat.buy_count}"
    assert strat.sell_count == 6, f"Expected sell_count=6, got {strat.sell_count}"
    assert total_trades == 86, f"Expected total_trades=86, got {total_trades}"
    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert abs(sharpe_ratio - (-2.2441169934564518)) < 1e-6, f"Expected sharpe_ratio=-2.2441169934564518, got {sharpe_ratio}"
    assert abs(annual_return - (-0.010775454009696908)) < 1e-6, f"Expected annual_return=-0.010775454009696908, got {annual_return}"
    assert abs(max_drawdown - 0.08693210999999486) < 1e-6, f"Expected max_drawdown=0.08693210999999486, got {max_drawdown}"
    assert abs(final_value - 918003.8900000055) < 0.01, f"Expected final_value=918003.8900000055, got {final_value}"

    print("\nAll tests passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Treasury Bond Futures Inter-Delivery Spread Arbitrage Strategy Test")
    print("=" * 60)
    test_treasury_futures_spread_arbitrage_strategy()