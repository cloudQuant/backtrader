import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

import backtrader as bt
from backtrader.comminfo import ComminfoFundingRate


# Additional indicators added beyond trading information
class GenericFundingRateCsv(bt.feeds.GenericCSVData):
    # Add two lines, each line name is the name of the additional columns in the CSV file
    lines = (
        "quote_volume",
        "count",
        "taker_buy_volume",
        "taker_buy_quote_volume",
        "mark_price_open",
        "mark_price_close",
        "current_funding_rate",
    )

    # The index of each new variable should be determined based on your CSV file, starting from 0
    params = (
        ("quote_volume", 6),
        ("count", 7),
        ("taker_buy_volume", 8),
        ("taker_buy_quote_volume", 9),
        ("mark_price_open", 10),
        ("mark_price_close", 11),
        ("current_funding_rate", 12),
    )

    def get_name(self):
        return self._name


def get_data_root(symbol):
    # Get absolute path of current file
    current_file_path = Path(__file__).resolve()
    # Get directory of current file
    current_dir_path = current_file_path.parent
    # Get parent directory
    parent_dir_path = current_dir_path.parent
    # Join parent directory and datas directory
    data_root = parent_dir_path.joinpath("datas")
    # Join datas directory and symbol file name
    data_file_path = data_root.joinpath(f"fake_kline_{symbol}.csv")
    print("data_file_path", data_file_path)
    return data_file_path


# When using, we can directly use our new class to read data
class FundingRateStrategy(bt.Strategy):
    params = ()

    def log(self, txt, dt=None):
        """Logging function for this strategy"""
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print(f"{dt.isoformat()}, {txt}")

    def __init__(self):
        self.bar_num = 0
        # self.gas_avg_funding_rate = bt.indicators.SMA(
        #     self.getdatabyname("gasusdt").current_funding_rate, period=30)
        # self.token_avg_funding_rate = bt.indicators.SMA(
        #     self.getdatabyname("tokenusdt").current_funding_rate, period=30)
        self.data_name_list = ["gasusdt", "tokenusdt"]

    def prenext(self):
        pass
        # for name in self.data_name_list:
        #     data = self.getdatabyname(name)
        #     self.log(
        #         f"data_name: {data._name}, "
        #         f"close:{data.close[0]},"
        #         f"funding_rate:{data.current_funding_rate[0]},")

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            # Order submitted and accepted
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
        # Attention: broker could reject order if not enough cash
        if order.status == order.Completed:
            if order.isbuy():
                self.log(
                    f"{order.data.get_name()} buy order : "
                    f"price : {round(order.executed.price, 6)} , "
                    f"size : {round(order.executed.size, 6)} , "
                    f"margin : {round(order.executed.value, 6)} , "
                    f"cost : {round(order.executed.comm, 6)}"
                )

            else:  # Sell
                self.log(
                    f"{order.data.get_name()} sell order : "
                    f"price : {round(order.executed.price, 6)} , "
                    f"size : {round(order.executed.size, 6)} , "
                    f"margin : {round(order.executed.value, 6)} , "
                    f"cost : {round(order.executed.comm, 6)}"
                )

    def notify_trade(self, trade):
        # Output information when a trade ends
        if trade.isclosed:
            self.log(
                f"closed symbol is : {trade.getdataname()} , "
                f"total_profit : {round(trade.pnl, 6)} , "
                f"net_profit : {round(trade.pnlcomm, 6)}"
            )
        if trade.isopen:
            self.log(f"open symbol is : {trade.getdataname()} , price : {trade.price} ")

    def next(self):
        # Some simplified advanced usage is not used, just to demonstrate basic usage
        # When trading, buy/sell fake_gasusdt and fake_tokenusdt based on conditions
        self.bar_num += 1
        # for name in self.data_name_list:
        #     data = self.getdatabyname(name)
        #     self.log(
        #         f"data_name: {data._name}, "
        #         f"close:{data.close[0]},"
        #         f"funding_rate:{data.current_funding_rate[0]},")
        # If current position is 0
        gas_data = self.getdatabyname("gasusdt")
        token_data = self.getdatabyname("tokenusdt")
        gas_position = self.getposition(gas_data).size
        token_position = self.getposition(token_data).size
        total_value = self.broker.getvalue()
        gas_price = gas_data.close[0]
        token_price = token_data.close[0]
        # If current position is 0 and current funding rate is greater than average funding rate, buy
        if gas_position == 0 and token_position == 0:
            target_gas_size = 1000000 / gas_price
            target_token_size = 1000000 / token_price
            self.log(f"total_value = {total_value} , ")
            self.sell(data=token_data, size=target_token_size)
            self.buy(data=gas_data, size=target_gas_size)
            # self.log(f"gas_avg_funding_rate = {self.gas_avg_funding_rate[0]}")
            # self.log(f"token_avg_funding_rate = {self.token_avg_funding_rate[0]}")
            # If gas average funding rate is greater than token average funding rate, sell gas, buy token
            # if self.gas_avg_funding_rate[0] > self.token_avg_funding_rate[0]:
            #     self.sell(data=gas_data, size=target_gas_size)
            #     self.buy(data=token_data, size=target_token_size)
            # To generate funding rate, buy fake gas and token simultaneously

            # If token average funding rate is greater than gas average funding rate, sell token, buy gas
            # elif self.token_avg_funding_rate[0] > self.gas_avg_funding_rate[0]:
            #     self.sell(data=token_data, size=target_token_size)
            #     self.buy(data=gas_data, size=target_gas_size)
        if gas_position != 0 or token_position != 0:
            try:
                _gas_price = gas_data.close[2]
                _token_price = gas_data.close[2]
            except Exception as e:
                self.log(e)
                self.close(gas_data)
                self.close(token_data)
                self.log(f"{gas_data.get_name()} close position")
                self.log(f"{token_data.get_name()} close position")
        # elif gas_position < 0 and self.gas_avg_funding_rate[0] < self.token_avg_funding_rate[0]:
        #     # If gas average funding rate is greater than token average funding rate, close position, reverse sell
        #     self.buy(gas_data, size=abs(gas_position))
        #     self.sell(token_data, size=abs(token_position))
        #     target_gas_size = 1000000 / gas_price
        #     target_token_size = 1000000 / token_price
        #     self.sell(data=token_data, size=target_token_size)
        #     self.buy(data=gas_data, size=target_gas_size)
        # elif gas_position > 0 and self.gas_avg_funding_rate[0] > self.token_avg_funding_rate[0]:
        #     # self.close(gas_data)
        #     # self.close(token_data)
        #     self.sell(gas_data, size=abs(gas_position))
        #     self.buy(gas_data, size=abs(token_position))
        #     target_gas_size = 1000000 / gas_price
        #     target_token_size = 1000000 / token_price
        #     self.sell(data=gas_data, size=target_gas_size)
        #     self.buy(data=token_data, size=target_token_size)


def run_strategy():
    cerebro = bt.Cerebro()
    symbol_list = ["gasusdt", "tokenusdt"]
    for symbol in symbol_list:
        # Since it's datetime, add a parameter so backtrader can recognize dates in the same format as CSV file
        # data_path = "../datas/merge_kline_and_funding_rate_" + symbol + ".csv"
        data_file_path = get_data_root(symbol)
        gas_feed = GenericFundingRateCsv(
            dataname=data_file_path,
            **{
                "dtformat": "%Y-%m-%d %H:%M:%S",
                "timeframe": bt.TimeFrame.Minutes,
                "compression": 60,
                # "fromdate": datetime.datetime(2024, 11, 15)
            },
        )
        # Add gasusdt data to cerebro
        cerebro.adddata(gas_feed, name=symbol)
        # Add commission fee, 0.06% (6/10000)
        comm = ComminfoFundingRate(commission=0.0000, margin=0.10, mult=1)
        cerebro.broker.addcommissioninfo(comm, name=symbol)

    # Set initial capital to 1 million
    cerebro.broker.setcash(1000000.0)
    # Add strategy
    cerebro.addstrategy(FundingRateStrategy)
    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="my_value")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade_analyzer")

    # cerebro.addanalyzer(bt.analyzers.PyFolio)
    # Run backtest
    results = cerebro.run()
    # sharpe_ratio = results[0].analyzers.my_sharpe.get_analysis()['sharperatio']
    # annual_return = results[0].analyzers.my_returns.get_analysis()['rnorm']
    # max_drawdown = results[0].analyzers.my_drawdown.get_analysis()["max"]["drawdown"] / 100
    # trade_num = results[0].analyzers.my_trade_analyzer.get_analysis()['total']['total']
    value_df = pd.DataFrame([results[0].analyzers.my_value.get_analysis()]).T
    value_df.columns = ["value"]
    value_df["datetime"] = pd.to_datetime(value_df.index)
    value_df.index = value_df["datetime"]
    value_df["date"] = [i.date() for i in value_df["datetime"]]
    value_df = value_df.drop_duplicates("date", keep="last")
    value_df = value_df[["value"]]
    return value_df
    # value_df.plot()
    # plt.show()
    # Plot
    # cerebro.plot()


def get_expected_value():
    # Read data
    gas_data_file_path = get_data_root("gasusdt")
    token_data_file_path = get_data_root("tokenusdt")
    init_gas_data = pd.read_csv(gas_data_file_path, index_col=0)
    init_token_data = pd.read_csv(token_data_file_path, index_col=0)

    # Find common start date + 1 for both datasets
    begin_date = max(init_gas_data.index[1], init_token_data.index[1])

    # Slice from common start date
    gas_data = init_gas_data.loc[begin_date:].copy()  # Use .copy() to avoid SettingWithCopyWarning
    token_data = init_token_data.loc[begin_date:].copy()  # Use .copy() to avoid SettingWithCopyWarning
    # print(gas_data.head(2))
    # print(token_data.head(2))
    # Calculate next_funding_rate and value
    gas_data["next_funding_rate"] = gas_data["current_funding_rate"].shift(-1)
    gas_data["value"] = -1 * gas_data["next_funding_rate"] * 1000000

    token_data["next_funding_rate"] = token_data["current_funding_rate"].shift(-1)
    token_data["value"] = -1 * token_data["next_funding_rate"] * (-1000000)

    # Fill NaN values
    gas_data["value"] = gas_data["value"].fillna(0)
    token_data["value"] = token_data["value"].fillna(0)

    # Create new DataFrame
    df = pd.DataFrame(index=init_gas_data.index)
    df["value"] = gas_data["value"] + token_data["value"]
    df["value"] = df["value"].fillna(0)
    # df.to_csv("expected_value_daily.csv")

    # Calculate cumulative value
    df["cumsum_value"] = df["value"].cumsum()
    df["cumsum_value"] = df["cumsum_value"] + 1000000

    # Process dates
    df["datetime"] = pd.to_datetime(df.index)
    df["date"] = df["datetime"].dt.date

    # Remove duplicates and keep last value
    df = df.drop_duplicates("date", keep="last")

    # Select needed columns
    df = df[["cumsum_value"]]
    df.columns = ["value"]
    # df.to_csv("expected_value.csv")
    return df


def test_base_funding_rate():
    actual_value_df = run_strategy()
    actual_value_list = actual_value_df["value"].tolist()
    expected_value_df = get_expected_value()
    expected_value_list = expected_value_df["value"].tolist()
    for actual_value, expected_value in zip(actual_value_list, expected_value_list):
        assert abs(actual_value - expected_value) < 1e-6

    # assert actual_value_df['value'].tolist() == expected_value_df['value'].tolist()


if __name__ == "__main__":
    test_base_funding_rate()
