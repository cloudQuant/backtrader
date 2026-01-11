"""Treasury Futures MACD Strategy Test Case

Test MACD strategy using CFFEX futures contract data
- Load futures data using PandasDirectData
- Futures strategy based on MACD indicator, supports rollover
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


class TreasuryFuturesMacdStrategy(bt.Strategy):
    # Strategy author
    author = 'yunjinqi'
    # Strategy parameters
    params = (("period_me1", 10),
              ("period_me2", 20),
              ("period_dif", 9),

              )

    # Log corresponding information
    def log(self, txt, dt=None):
        ''' Logging function fot this strategy'''
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('{}, {}'.format(dt.isoformat(), txt))

    # Initialize strategy data
    def __init__(self):
        # Common attribute variables
        self.bar_num = 0  # Number of bars next has run
        self.buy_count = 0
        self.sell_count = 0
        self.current_date = None  # Current trading day
        # Calculate MACD indicator
        self.ema_1 = bt.indicators.ExponentialMovingAverage(self.datas[0].close, period=self.p.period_me1)
        self.ema_2 = bt.indicators.ExponentialMovingAverage(self.datas[0].close, period=self.p.period_me2)
        self.dif = self.ema_1 - self.ema_2
        self.dea = bt.indicators.ExponentialMovingAverage(self.dif, period=self.p.period_dif)
        self.macd = (self.dif - self.dea) * 2
        # Save which contract is currently held
        self.holding_contract_name = None

    def prenext(self):
        # Since futures data has thousands of bars and each futures contract has different trading dates, it won't naturally enter next
        # Need to call next function in each prenext to run
        self.next()
        # pass

    # Add corresponding strategy logic in next
    def next(self):
        # Increment bar_num by 1 each time it runs and update trading day
        self.current_date = bt.num2date(self.datas[0].datetime[0])
        self.bar_num += 1
        # self.log(f"{self.bar_num},{self.datas[0]._name},{self.broker.getvalue()}")
        # self.log(f"{self.ema_1[0]},{self.ema_2[0]},{self.dif[0]},{self.dea[0]},{self.macd[0]}")
        data = self.datas[0]
        # Open position, close existing first then open new
        # Close long position
        if self.holding_contract_name is not None and self.getpositionbyname(self.holding_contract_name).size > 0 and \
                data.close[0] < self.ema_1[0]:
            data = self.getdatabyname(self.holding_contract_name)
            self.close(data)
            self.holding_contract_name = None
        # Close short position
        if self.holding_contract_name is not None and self.getpositionbyname(self.holding_contract_name).size < 0 and \
                data.close[0] > self.ema_1[0]:
            data = self.getdatabyname(self.holding_contract_name)
            self.close(data)
            self.holding_contract_name = None

        # Open long position
        if self.holding_contract_name is None and self.ema_1[-1] < self.ema_2[-1] and self.ema_1[0] > self.ema_2[0] and \
                self.macd[0] > 0:
            dominant_contract = self.get_dominant_contract()
            next_data = self.getdatabyname(dominant_contract)
            self.buy(next_data, size=1)
            self.buy_count += 1
            self.holding_contract_name = dominant_contract

        # Open short position
        if self.holding_contract_name is None and self.ema_1[-1] > self.ema_2[-1] and self.ema_1[0] < self.ema_2[0] and \
                self.macd[0] < 0:
            dominant_contract = self.get_dominant_contract()
            next_data = self.getdatabyname(dominant_contract)
            self.sell(next_data, size=1)
            self.sell_count += 1
            self.holding_contract_name = dominant_contract

        # Rollover to next contract
        if self.holding_contract_name is not None:
            dominant_contract = self.get_dominant_contract()
            # If a new dominant contract appears, start rolling over
            if dominant_contract != self.holding_contract_name:
                # Next dominant contract
                next_data = self.getdatabyname(dominant_contract)
                # Current contract position size and data
                size = self.getpositionbyname(self.holding_contract_name).size  # Position size
                data = self.getdatabyname(self.holding_contract_name)
                # Close the old one
                self.close(data)
                # Open the new one
                if size > 0:
                    self.buy(next_data, size=abs(size))
                if size < 0:
                    self.sell(next_data, size=abs(size))
                self.holding_contract_name = dominant_contract

    def get_dominant_contract(self):

        # Use contract with largest open interest as dominant contract, return data name
        # Can define how to calculate dominant contract according to needs

        # Get varieties currently trading
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
                self.log(f"{data._name} not yet listed for trading")

        target_datas = sorted(target_datas, key=lambda x: x[1])
        print(target_datas)
        return target_datas[-1][0]

    def notify_order(self, order):

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
        # Output information when a trade ends
        if trade.isclosed:
            self.log('closed symbol is : {} , total_profit : {} , net_profit : {}'.format(
                trade.getdataname(), trade.pnl, trade.pnlcomm))
            # self.trade_list.append([self.datas[0].datetime.date(0),trade.getdataname(),trade.pnl,trade.pnlcomm])

        if trade.isopen:
            self.log('open symbol is : {} , price : {} '.format(
                trade.getdataname(), trade.price))

    def stop(self):
        self.log(f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}")


def load_futures_data(variety: str = "T"):
    """Load futures data and construct index contract

    Args:
        variety: Variety code, default is T (Treasury futures)

    Returns:
        index_df: Index contract DataFrame
        data: Original data DataFrame
    """
    data = pd.read_csv(resolve_data_path("CFFEX Futures Contract Data.csv"), index_col=0)
    data = data[data['variety'] == variety]
    data['datetime'] = pd.to_datetime(data['date'], format="%Y%m%d")
    data = data.dropna()

    # Synthesize index contract weighted by open interest
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


def test_treasury_futures_macd_strategy():
    """Test treasury futures MACD strategy

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
    comm = ComminfoFuturesPercent(commission=0.0002, margin=0.1, mult=10)
    cerebro.broker.addcommissioninfo(comm, name="index")

    # Load specific contract data
    contract_count = 0
    for symbol, df in data.groupby("symbol"):
        df.index = pd.to_datetime(df['datetime'])
        df = df[['open', 'high', 'low', 'close', 'volume', 'open_interest']]
        df.columns = ['open', 'high', 'low', 'close', 'volume', 'openinterest']
        feed = bt.feeds.PandasDirectData(dataname=df)
        cerebro.adddata(feed, name=symbol)
        comm = ComminfoFuturesPercent(commission=0.0002, margin=0.1, mult=10)
        cerebro.broker.addcommissioninfo(comm, name=symbol)
        contract_count += 1

    print(f"Successfully loaded {contract_count} contracts")

    # Set initial capital
    cerebro.broker.setcash(1000000.0)

    # Add strategy
    cerebro.addstrategy(TreasuryFuturesMacdStrategy, period_me1=10, period_me2=20, period_dif=9)

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
    print("Treasury Futures MACD Strategy Backtest Results:")
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
    assert strat.buy_count == 38, f"Expected buy_count=38, got {strat.buy_count}"
    assert strat.sell_count == 38, f"Expected sell_count=38, got {strat.sell_count}"
    assert total_trades == 90, f"Expected total_trades=90, got {total_trades}"
    assert abs(sharpe_ratio - (-700.977360693882)) < 1e-6, f"Expected sharpe_ratio=-700.977360693882, got {sharpe_ratio}"
    assert abs(annual_return - (-2.2430503547013427e-06)) < 1e-12, f"Expected annual_return=-2.2430503547013427e-06, got {annual_return}"
    assert abs(max_drawdown - 6.587175196273877e-05) < 1e-9, f"Expected max_drawdown=6.587175196273877e-05, got {max_drawdown}"
    assert abs(final_value - 999982.2871600012) < 0.01, f"Expected final_value=999982.2871600012, got {final_value}"

    print("\nAll tests passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Treasury Futures MACD Strategy Test")
    print("=" * 60)
    test_treasury_futures_macd_strategy()
