#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

# Import necessary libraries and modules
# import collections
import datetime
import backtrader as bt
from backtrader.utils.py3 import iteritems
import pandas as pd  # For data manipulation and analysis
import numpy as np   # For numerical operations
import empyrical as ep  # For financial performance metrics calculation

# Import backtrader analyzers that will be used as components
from . import TimeReturn, PositionsValue, Transactions, GrossLeverage


# PyFolio analysis module (pyfolio的分析模块)
class PyFolio(bt.Analyzer):
    """This analyzer uses 4 children analyzers to collect data and transforms it
    in to a data set compatible with ``pyfolio``

    Children Analyzer
      - ``TimeReturn``

        Used to calculate the returns of the global portfolio value

      - ``PositionsValue``

        Used to calculate the value of the positions per data. It sets the
        ``headers`` and ``cash`` parameters to ``True``

      - ``Transactions``

        Used to record each transaction on a data (size, price, value). Sets
        the ``headers`` parameter to ``True``

      - ``GrossLeverage``

        Keeps track of the gross leverage (how much the strategy is invested)

    Params:
      These are passed transparently to the children

      - timeframe (default: ``bt.TimeFrame.Days``)

        If ``None`` then the timeframe of the 1st data of the system will be
        used

      - compression (default: `1``)

        If ``None`` then the compression of the 1st data of the system will be
        used

    Both ``timeframe`` and ``compression`` are set following the default
    behavior of ``pyfolio`` which is working with *daily* data and upsample it
    to obtain values like yearly returns.

    Methods:

      - get_analysis

        Returns a dictionary with returns as values and the datetime points for
        each return as keys
    """
    # Parameters (参数)
    params = (
        ('timeframe', bt.TimeFrame.Days),  # Default timeframe is Days
        ('compression', 1)  # Default compression is 1
    )

    # Initialization (初始化)
    def __init__(self):
        # Create a dictionary with timeframe and compression settings
        dtfcomp = dict(timeframe=self.p.timeframe,
                       compression=self.p.compression)

        # Initialize the four child analyzers
        self._returns = TimeReturn(**dtfcomp)  # Calculate strategy returns
        self._positions = PositionsValue(headers=True, cash=True)  # Track position values
        self._transactions = Transactions(headers=True)  # Record all transactions
        self._gross_lev = GrossLeverage()  # Track gross leverage

    # Collect analysis results when strategy stops (停止的时候，获取几个分析结果)
    def stop(self):
        super(PyFolio, self).stop()
        # Store results from each analyzer in the rets dictionary
        self.rets['returns'] = self._returns.get_analysis()  # Get returns data
        self.rets['positions'] = self._positions.get_analysis()  # Get positions data
        self.rets['transactions'] = self._transactions.get_analysis()  # Get transactions data
        self.rets['gross_lev'] = self._gross_lev.get_analysis()  # Get leverage data

    # Process the results from the four analyzers to create pyfolio-compatible inputs (对上面四个analyzer的结果进行调整，以便得到pyfolio需要的输入的信息)
    def get_pf_items(self):
        """
        Returns a tuple of 4 elements which can be used for further processing with
          ``pyfolio``
          returns, positions, transactions, gross_leverage

        Because the objects are meant to be used as direct input to ``pyfolio``
        this method makes a local import of ``pandas`` to convert the internal
        *backtrader* results to *pandas DataFrames* which is the expected input
        by, for example, ``pyfolio.create_full_tear_sheet``

        The method will break if ``pandas`` is not installed
        """
        # keep import local to avoid disturbing installations with no pandas
        # Process returns data (处理returns)
        # Convert returns to pandas DataFrame
        cols = ['index', 'return']
        returns = pd.DataFrame.from_records(iteritems(self.rets['returns']),
                                            index=cols[0], columns=cols)
        returns.index = pd.to_datetime(returns.index)
        returns.index = returns.index.tz_localize('UTC')
        rets = returns['return']
        # Process positions data (处理position)
        # Convert positions to pandas DataFrame
        pss = self.rets['positions']
        # ps = [[k] + v[-2:] for k, v in iteritems(pss)]
        ps = [[k] + v for k, v in iteritems(pss)]
        cols = ps.pop(0)  # headers are in the first entry
        positions = pd.DataFrame.from_records(ps[1:], columns=cols)
        positions.index = pd.to_datetime(positions['Datetime'])
        del positions['Datetime']
        positions.index = positions.index.tz_localize('UTC')
        # Process transactions data (处理transactions)
        # Convert transactions to pandas DataFrame
        txss = self.rets['transactions']
        txs = list()
        # The transactions have a common key (date) and can potentially happend
        # for several assets. The dictionary has a single key and a list of
        # lists. Each sublist contains the fields of a transaction
        # Hence the double loop to undo the list indirection
        for k, v in iteritems(txss):
            for v2 in v:
                txs.append([k] + v2)
        cols = txs.pop(0)  # headers are in the first entry
        transactions = pd.DataFrame.from_records(txs, index=cols[0], columns=cols)
        transactions.index = pd.to_datetime(transactions.index)
        transactions.index = transactions.index.tz_localize('UTC')
        # Process gross leverage data (处理leverage)
        # Convert leverage data to pandas DataFrame
        cols = ['index', 'gross_lev']
        gross_lev = pd.DataFrame.from_records(iteritems(self.rets['gross_lev']),
                                              index=cols[0], columns=cols)
        gross_lev.index = pd.to_datetime(gross_lev.index)
        gross_lev.index = gross_lev.index.tz_localize('UTC')
        glev = gross_lev['gross_lev']
        # Return all processed data together (返回所有的结果)
        # Returns tuple of (returns, positions, transactions, gross_leverage)
        return rets, positions, transactions, glev

    def _get_order_type(self, row):
        """Determine order type (buy/sell) based on trade type and amount
        
        Args:
            row: DataFrame row with TRADE_TYPE and amount
            
        Returns:
            String representing order type: '买入' (buy) or '卖出' (sell)
        """
        if row['TRADE_TYPE'] == '开仓':  # Opening position
            return '买入' if row['amount'] > 0 else '卖出'  # Buy if positive amount, else sell
        elif row['TRADE_TYPE'] == '平仓':  # Closing position
            return '卖出' if row['amount'] > 0 else '买入'  # Sell if positive amount, else buy
        return np.nan  # Unknown (或者 '未知')

    def _compute_profit_loss(self, trade_info, open_type, close_type):
        """Calculate profit/loss for matched open and close positions
        
        Args:
            trade_info: DataFrame containing trade information
            open_type: String indicating position opening type ('开多'/'开空')
            close_type: String indicating position closing type ('平多'/'平空')
            
        Returns:
            DataFrame with profit/loss calculated for each trade
        """
        # Filter trades by order type
        open_trades = trade_info[trade_info['ORDER_TYPE'] == open_type].copy()
        close_trades = trade_info[trade_info['ORDER_TYPE'] == close_type].copy()

        # Reset indices for easier matching
        open_trades = open_trades.reset_index()
        close_trades = close_trades.reset_index()

        # Match open and close trades to calculate profit/loss
        for i in range(min(len(open_trades), len(close_trades))):
            open_idx = open_trades.loc[i, 'index']
            close_idx = close_trades.loc[i, 'index']
            # Profit/loss = closing amount - opening amount (盈亏 = 平仓金额 - 开仓金额)
            profit = abs(close_trades.loc[i, 'TRADE_AMT']) - abs(open_trades.loc[i, 'TRADE_AMT'])
            # For short positions, reverse the sign of profit
            if open_type == "开空":
                profit = -1 * profit
            trade_info.loc[open_idx, 'PROFIT_LOSS'] = 0  # Opening positions have no P/L (开仓本身盈亏为0)
            trade_info.loc[close_idx, 'PROFIT_LOSS'] = profit  # Assign P/L to closing trade
        return trade_info

    def _get_trade_info(self, trade_info, symbol_name, current_user_name="", pair_num=None):
        """Process transaction data into a standardized trade information format
        
        Args:
            trade_info: Raw transaction data from backtrader
            symbol_name: Name of the trading symbol/instrument
            current_user_name: Username for record-keeping
            pair_num: Number indicating how trades are paired (for open/close matching)
            
        Returns:
            DataFrame with standardized trade information
        """
        current_date = datetime.date.today()
        target_columns = ['TRADE_DATE', 'ENTRUST_DATE', 'O_CODE', 'KIND',
                          'TRADE_TYPE', 'ORDER_TYPE', 'TRADE_NUM', 'TRADE_PRICE', 'TRADE_AMT',
                          'ENTRUST_NUM', 'ENTRUST_PRICE', 'STATUS', 'PROFIT_LOSS', 'COMMISSION',
                          'CREATE_DATE', 'CREATE_USER', 'UPDATE_DATE', 'UPDATE_USER', 'D_FLAG']
        trade_info['TRADE_DATE'] = pd.to_datetime(trade_info.index.strftime('%Y-%m-%d'))
        trade_info['ENTRUST_DATE'] = trade_info['TRADE_DATE']
        trade_info['O_CODE'] = trade_info['symbol']
        trade_info['KIND'] = symbol_name
        trade_info = trade_info.reset_index(drop=True)  # 重置索引以确保按行号编号
        # 根据行号设置 TRADE_TYPE
        if pair_num is not None:
            trade_info['TRADE_TYPE'] = trade_info.index.map(lambda i: '开仓' if i % pair_num in [0] else '平仓')
            trade_info['ORDER_TYPE'] = trade_info.apply(self._get_order_type, axis=1)
            trade_info['TRADE_NUM'] = trade_info.index // pair_num + 1
            trade_info['TRADE_PRICE'] = trade_info['price']
            trade_info['TRADE_AMT'] = -1 * trade_info['value']
            trade_info['ENTRUST_NUM'] = trade_info['amount']
            trade_info['ENTRUST_PRICE'] = trade_info['price']
            trade_info['STATUS'] = "完成"
        # Create empty profit/loss column (建立空盈亏列)
        trade_info['PROFIT_LOSS'] = None
        # Process long positions (处理多头)
        trade_info = self._compute_profit_loss(trade_info, open_type='开多', close_type='平多')
        # Process short positions (处理空头)
        trade_info = self._compute_profit_loss(trade_info, open_type='开空', close_type='平空')
        # Convert profit/loss to float type (was None) (转换为 float 类型（原先为 None）)
        trade_info['PROFIT_LOSS'] = trade_info['PROFIT_LOSS'].astype(float)
        trade_info['COMMISSION'] = trade_info['value'] * 0.00001
        trade_info['CREATE_DATE'] = current_date
        trade_info['CREATE_USER'] = current_user_name
        trade_info['UPDATE_DATE'] = current_date
        trade_info['UPDATE_USER'] = current_user_name
        trade_info['D_FLAG'] = 0
        # print(trade_info[['TRADE_DATE',"ORDER_TYPE", "TRADE_AMT", 'PROFIT_LOSS']])
        trade_info = trade_info.fillna(0)
        trade_info = trade_info[target_columns]
        return trade_info

    def _get_performance_indicators(self, results, returns, benchmark_returns, current_user_name):
        """
        利用Backtrader回测框架运行策略返回的结果计算业绩指标、交易详情。
        Parameters
        ----------
        results: backtrader策略运行返回结果
        benchmark_returns: DataFrame, 基准的收益率序列
        current_user_name: str, 当前用户名称

        Returns
        -------
        performance_dict : dict
            包含以下绩效指标与序列结果：
              PROFIT : float
                  策略收益（%）
              PROFIT_Y : float
                  策略年化收益（%）
              SUPERIOR_PROFIT : float
                  超额收益（%）
              BASE_PROFIT : float
                  基准收益（%）
              ALPHA : float
                  alpha
              Beta : float
                  beta
              SHARPE_RATIO: float
                  夏普率
              WIN_RATIO: float
                  胜率
              RRR: float
                  盈亏比
              MDD: float
                  最大回撤
              SORTINO_RATIO: float
                  索提诺比率
              DAILY_SUPERIOR_PROFIT: float
                  日均超额收益
              MDD_SUPERIOR_PROFIT: float
                  超额收益最大回撤
              SP_SHARPE_RATIO: float
                  超额收益夏普比率
              DAILY_WIN_RATIO: float
                  日胜率
              WIN_NUM: float
                   盈利次数
              LOSS_NUM: float
                   亏损次数
              INFO_RATIO: float
                    信息比率
              VIX: float
                   策略波动率
              BASE_VIX: float
                   基准波动率
              DATE_REGION: str
                   最大回测区间
              CREATE_DATE: datetime | str
                    创建日期
              CREATE_USER: str
                    创建用户
              UPDATE_DATE: datetime | str
                    更新时间
              UPDATE_USER: str
                    更新用户
              D_FLAG: str
                    有效性标志，0代表有效，1代表无效

        trade_records：list of list
                  交易详情，每行表示一笔交易，字段依次为：日期,委托时间,标的,交易类型,下单类型,成交额,委托价格,状态,平仓盈亏,成交价,成交数量,委托数量,手续费,品种,最后更新时间

        Examples
        --------
        >>> performance_dict_, trade_records_ = self._get_performance_indicators(results, benchmark_returns, current_user_name)
        >>> print(performance_dict_)
        >>> print(trade_records_)

        """
        # 此处需要补充完整所有指标的计算逻辑
        current_date = datetime.date.today()
        # sharpe_ratio = results[0].analyzers.my_sharpe.get_analysis()['sharperatio']
        # annual_return = results[0].analyzers.my_returns.get_analysis()['rnorm']
        # max_drawdown = results[0].analyzers.my_drawdown.get_analysis()["max"]["drawdown"] / 100

        df = pd.concat([benchmark_returns, returns], axis=1, join="inner")
        df = df[['returns', 'return']]
        df.columns = ['benchmark', 'return']
        df['super'] = df['return'] - df['benchmark']
        print(df)
        # 获取夏普率、年化收益率、最大回测率、交易次数
        b_mdd = round(results[0].analyzers.my_drawdown.get_analysis()["max"]["drawdown"], 2)
        # trade_num = results[0].analyzers.my_trade_analyzer.get_analysis()['total']['total']
        # 获取盈利次数、亏损次数、盈利平均、亏损平均、盈利比例、平均盈亏比
        win_num = results[0].analyzers.my_trade_analyzer.get_analysis()['won']['total']
        lost_num = results[0].analyzers.my_trade_analyzer.get_analysis()['lost']['total']
        win_average = results[0].analyzers.my_trade_analyzer.get_analysis()['won']['pnl']['average']
        lost_average = results[0].analyzers.my_trade_analyzer.get_analysis()['lost']['pnl']['average']
        b_win_ratio = round(win_num / (win_num + lost_num), 4)
        b_rrr = np.nan if lost_average == 0 else round((win_average / abs(lost_average) * 100), 4)
        b_profit = round(ep.cum_returns_final(returns) * 100, 2)
        b_profit_y = round(ep.annual_return(returns) * 100, 2)
        b_base_profit = round(ep.cum_returns_final(df['benchmark']) * 100, 2)
        b_superior_profit = round((b_profit - b_base_profit), 2)
        _b_alpha, _b_beta = ep.alpha_beta(df['return'], df['benchmark'])
        b_alpha = round(_b_alpha, 4)
        b_beta = round(_b_beta, 4)
        # b_sharpe_ratio = round(ep.sharpe_ratio(df['return']), 4)
        b_sharpe_ratio = round(ep.sharpe_ratio(returns, risk_free=0, period="daily"), 4)
        b_sortino_ratio = round(ep.sortino_ratio(returns), 4)
        b_daily_superior_profit = round(df['super'].mean() * 100, 2)
        b_mdd_superior_profit = round(ep.max_drawdown(df['super']) * 100, 2)
        b_sp_sharpe_ratio = round(ep.sharpe_ratio(df['super'], risk_free=0, period="daily"), 4)
        b_daily_win_ratio = b_win_ratio
        b_info_ratio = round(ep.information_ratio(df['super']), 4)
        b_vix = round(ep.annual_volatility(df['return']), 4)
        b_base_vix = round(ep.annual_volatility(df['benchmark']), 4)
        b_date_region = ep.get_max_drawdown_period(df['return'])

        performance_dict = {"PROFIT": b_profit,
                            "PROFIT_Y": b_profit_y,
                            "SUPERIOR_PROFIT": b_superior_profit,
                            "BASE_PROFIT": b_base_profit,
                            "ALPHA": b_alpha,
                            "Beta": b_beta,
                            "SHARPE_RATIO": b_sharpe_ratio,
                            "WIN_RATIO": b_win_ratio,
                            "RRR": b_rrr,
                            "MDD": b_mdd,
                            "SORTINO_RATIO": b_sortino_ratio,
                            "DAILY_SUPERIOR_PROFIT": b_daily_superior_profit,
                            "MDD_SUPERIOR_PROFIT": b_mdd_superior_profit,
                            "SP_SHARPE_RATIO": b_sp_sharpe_ratio,
                            "DAILY_WIN_RATIO": b_daily_win_ratio,
                            "WIN_NUM": win_num,
                            "LOSS_NUM": lost_num,
                            "INFO_RATIO": b_info_ratio,
                            "VIX": b_vix,
                            "BASE_VIX": b_base_vix,
                            "DATE_REGION": b_date_region,
                            "CREATE_DATE": current_date,
                            "CREATE_USER": current_user_name,
                            "UPDATE_DATE": current_date,
                            "UPDATE_USER": current_user_name,
                            "D_FLAG": 0
                            }
        return performance_dict

    def get_format_results(self, results, benchmark_returns, symbol_name, current_user_name):
        """Generate formatted performance results and trade records
        
        This method creates two key outputs for strategy evaluation:
        1. A performance dictionary with various metrics (returns, ratios, etc.)
        2. A trade records dataframe with detailed information about each trade
        
        Args:
            results: Strategy backtest results
            benchmark_returns: Returns of the benchmark for comparison
            symbol_name: Name of the trading symbol/instrument
            current_user_name: Username for record-keeping
            
        Returns:
            Tuple containing (performance_dict, trade_records)
        """
        # Get the basic pyfolio items (returns, positions, transactions, leverage)
        returns, positions, transactions, gross_lev = self.get_pf_items()
        # Format the date index
        returns.index = pd.to_datetime(returns.index.strftime('%Y-%m-%d'))
        # Calculate performance indicators
        performance_dict = self._get_performance_indicators(results, returns, benchmark_returns, current_user_name)
        # Process transaction data into standardized trade information
        trade_records_list = self._get_trade_info(transactions, symbol_name, pair_num=1)
        # Convert to DataFrame for easier manipulation
        trade_records = pd.DataFrame(trade_records_list)
        return performance_dict, trade_records