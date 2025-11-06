# 2025-10-13T00:00:00, self.bar_num = 1885
# sharpe_ratio: 0.4613345781810348
# annual_return: 0.055969750235917486
# max_drawdown: 0.23776639938068544
# trade_num: 1749


import sys
import time
import datetime
import warnings
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import matplotlib as mpl
import matplotlib.ticker as ticker
import matplotlib.dates as mdates
from matplotlib.ticker import FuncFormatter
from pathlib import Path

import backtrader as bt
from backtrader.comminfo import ComminfoFuturesPercent

# 设置中文字体
from matplotlib.font_manager import FontManager, FontProperties
import platform


BASE_DIR = Path(__file__).resolve().parent


def _log_search_paths(filename: str, paths: list[Path]) -> None:
    """输出搜索路径帮助诊断数据文件定位问题"""
    print(f"\n[resolve_data_path] searching for: {filename}")
    for idx, candidate in enumerate(paths, start=1):
        status = "FOUND" if candidate.exists() else "missing"
        print(f"  {idx}. {candidate} -> {status}")


def resolve_data_path(filename: str) -> Path:
    """根据脚本所在目录定位数据文件，避免相对路径读取失败"""

    repo_root = BASE_DIR.parent.parent

    search_paths = [
        BASE_DIR / "datas" / filename,  # tests/datas/xxxx.csv（同级datas目录）
        repo_root / "tests" / "datas" / filename,  # 仓库根目录 tests/datas/xxxx.csv
        BASE_DIR / filename,  # 当前目录
        BASE_DIR.parent / "strategies" / filename,  # tests/strategies
        repo_root / "strategies" / filename,  # 仓库根目录 strategies
        repo_root / "examples" / filename,  # 仓库根目录 examples
        repo_root / filename,  # 仓库根目录直接放置
        Path.cwd() / filename,  # 当前工作目录
        Path.cwd() / "tests" / "datas" / filename,  # 运行目录下的 tests/datas
    ]

    data_dir = os.environ.get("BACKTRADER_DATA_DIR")
    if data_dir:
        search_paths.append(Path(data_dir) / filename)

    _log_search_paths(filename, search_paths)

    for candidate in search_paths:
        if candidate.exists():
            print(f"[resolve_data_path] ✅ using: {candidate}")
            return candidate

    searched = "\n  ".join(str(path) for path in search_paths)
    raise FileNotFoundError(
        f"未找到数据文件: {filename}. 已尝试路径:\n  {searched}\n"
        "请确认数据文件存在于上述目录，或设置 BACKTRADER_DATA_DIR 环境变量。"
    )


def setup_chinese_font():
    """
    智能设置跨平台的中文字体支持
    返回最终使用的字体名称
    """
    # 获取当前操作系统
    system = platform.system()

    # 定义各平台的字体优先级列表
    font_priority = {
        'Darwin': [  # macOS
            'PingFang SC',  # 苹方，macOS 现代字体
            'Heiti SC',  # 黑体-简，macOS
            'Heiti TC',  # 黑体-繁
            'STHeiti',  # 华文黑体
            'Arial Unicode MS'  # 包含中文字符
        ],
        'Windows': [
            'SimHei',  # 黑体，Windows
            'Microsoft YaHei',  # 微软雅黑
            'KaiTi',  # 楷体
            'SimSun',  # 宋体
            'FangSong'  # 仿宋
        ],
        'Linux': [
            'WenQuanYi Micro Hei',  # 文泉驿微米黑
            'WenQuanYi Zen Hei',  # 文泉驿正黑
            'Noto Sans CJK SC',  # 思源黑体
            'DejaVu Sans',  # 备选
            'AR PL UMing CN'  # 文鼎明体
        ]
    }

    # 获取系统所有可用字体
    fm = FontManager()
    available_fonts = [f.name for f in fm.ttflist]

    # 根据当前平台选择字体列表
    candidate_fonts = font_priority.get(system, [])

    # 在可用字体中查找第一个匹配的候选字体
    selected_font = None
    for font in candidate_fonts:
        if font in available_fonts:
            selected_font = font
            break

    # 设置字体配置
    if selected_font:
        plt.rcParams['font.sans-serif'] = [selected_font] + plt.rcParams['font.sans-serif']
        print(f"✅ 已设置字体: {selected_font}")
        return selected_font
    else:
        # 回退方案：使用系统默认 sans-serif 字体
        fallback_fonts = ['DejaVu Sans', 'Arial', 'Liberation Sans']
        available_fallback = [f for f in fallback_fonts if f in available_fonts]

        if available_fallback:
            plt.rcParams['font.sans-serif'] = available_fallback + plt.rcParams['font.sans-serif']
            print(f"⚠️  使用备选字体: {available_fallback[0]}")
            return available_fallback[0]
        else:
            print("❌ 未找到合适的中文字体，使用系统默认字体")
            return None
plt.rcParams['font.sans-serif'] = [setup_chinese_font()]  # 用来正常显示中文标签
plt.rcParams['axes.unicode_minus'] = False  # 用来正常显示负号
# 忽略警告
warnings.filterwarnings('ignore')


class ExtendPandasFeed(bt.feeds.PandasData):
    """
    扩展的Pandas数据源，添加可转债特有的字段

    重要说明：
    当DataFrame使用 set_index('datetime') 后，datetime列变成索引而非数据列。
    因此列索引需要从0开始重新计算，不包括datetime。

    DataFrame结构（set_index后）：
    - 索引：datetime
    - 列0：open
    - 列1：high
    - 列2：low
    - 列3：close
    - 列4：volume
    - 列5：pure_bond_value
    - 列6：convert_value
    - 列7：pure_bond_premium_rate
    - 列8：convert_premium_rate
    """
    params = (
        ('datetime', None),  # datetime是索引，不是数据列
        ('open', 0),  # 第1列 -> 索引0
        ('high', 1),  # 第2列 -> 索引1
        ('low', 2),  # 第3列 -> 索引2
        ('close', 3),  # 第4列 -> 索引3
        ('volume', 4),  # 第5列 -> 索引4
        ('openinterest', -1),  # 不存在该列
        ('pure_bond_value', 5),  # 第6列 -> 索引5
        ('convert_value', 6),  # 第7列 -> 索引6
        ('pure_bond_premium_rate', 7),  # 第8列 -> 索引7
        ('convert_premium_rate', 8)  # 第9列 -> 索引8
    )

    # 定义扩展的数据线
    lines = ('pure_bond_value', 'convert_value', 'pure_bond_premium_rate', 'convert_premium_rate')


def clean_data():
    """清洗可转债数据"""
    df = pd.read_csv(resolve_data_path('bond_merged_all_data.csv'))
    df.columns = ['symbol', 'bond_symbol', 'datetime', 'open', 'high', 'low', 'close', 'volume',
                  'pure_bond_value', 'convert_value', 'pure_bond_premium_rate', 'convert_premium_rate']
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df[df['datetime'] > pd.to_datetime("2018-01-01")]

    datas = {}
    for symbol, data in df.groupby('symbol'):
        data = data.set_index('datetime')
        data = data.drop(['symbol', 'bond_symbol'], axis=1)
        data = data.dropna()
        datas[symbol] = data.astype("float")

    return datas


class BondConvertTwoFactor(bt.Strategy):
    # params = (('short_window',10),('long_window',60))
    params = (("first_factor_weight", 0.5),
              ("second_factor_weight", 0.5),
              ("hold_percent", 20),
              )

    def log(self, txt, dt=None):
        """log信息的功能"""
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('%s, %s' % (dt.isoformat(), txt))

    def __init__(self, *args, **kwargs):
        # 一般用于计算指标或者预先加载数据，定义变量使用
        super().__init__(*args, **kwargs)
        self.bar_num = 0
        # 保存仓位
        self.position_dict = {}
        # 当前有哪些可转债
        self.stock_dict = {}

    def prenext(self):
        self.next()

    def stop(self):
        self.log(f"self.bar_num = {self.bar_num}")

    def next(self):
        # 假设有100万资金，每次成份股调整，每个股票使用1万元
        self.bar_num += 1
        # self.log(f"self.bar_num = {self.bar_num}")
        # 前一交易日和当前的交易日
        pre_date = self.datas[0].datetime.date(-1).strftime("%Y-%m-%d")
        current_date = self.datas[0].datetime.date(0).strftime("%Y-%m-%d")
        # 2025-01-01
        current_month = current_date[5:7]
        try:
            next_date = self.datas[0].datetime.date(1).strftime("%Y-%m-%d")
            next_month = next_date[5:7]
        except Exception as e:
            next_month = current_month
            print(e)
        # 总的价值
        total_value = self.broker.get_value()
        total_cash = self.broker.get_cash()
        # self.log(f"total_value : {total_value}")
        # 第一个数据是指数，校正时间使用，不能用于交易
        # 循环所有的股票,计算股票的数目
        self.stock_dict = {}
        for data in self.datas[1:]:
            data_date = data.datetime.date(0).strftime("%Y-%m-%d")
            # 如果两个日期相等，说明股票在交易
            if current_date == data_date:
                stock_name = data._name
                if stock_name not in self.stock_dict:
                    self.stock_dict[stock_name] = 1

        # # 如果入选的股票小于100支，不使用策略
        # if len(self.stock_dict) < 30:
        #     return
        total_target_stock_num = len(self.stock_dict)
        # 现在持仓的股票数目
        total_holding_stock_num = len(self.position_dict)
        # 如果今天是调仓日
        # self.log(f"current_month={current_month}, next_month={next_month}")
        if current_month != next_month:
            # self.log(f"当前可交易的资产数目为:{total_target_stock_num}, 当前持仓的资产数目:{total_holding_stock_num}")
            # 循环资产
            position_name_list = list(self.position_dict.keys())
            for asset_name in position_name_list:
                data = self.getdatabyname(asset_name)
                size = self.getposition(data).size
                # 如果有仓位
                if size != 0:
                    self.close(data)
                    if data._name in self.position_dict:
                        self.position_dict.pop(data._name)

                # 已经下单，但是订单没有成交
                if data._name in self.position_dict and size == 0:
                    order = self.position_dict[data._name]
                    self.cancel(order)
                    self.position_dict.pop(data._name)
            # 计算因子值
            result = self.get_target_symbol()
            # 根据计算出来的累计收益率进行排序，选出前10%的股票做多，后10%的股票做空
            # new_result = sorted(result, key=lambda x: x[1])
            # self.log(f"target_result: {new_result}")
            if self.p.hold_percent > 1:
                num = self.p.hold_percent
            else:
                num = int(self.p.hold_percent * total_target_stock_num)
            buy_list = result[:num]
            self.log(f"len(self.datas)={len(self.datas)}, total_holding_stock_num={total_holding_stock_num}, len(result) = {len(result)}, len(buy_list) = {len(buy_list)}")
            # 根据计算出来的信号，买卖相应的资产
            for data_name, _cumsum_rate in buy_list:
                data = self.getdatabyname(data_name)
                # 计算理论上的手数
                now_value = total_value / num
                lots = now_value / data.close[0]
                # lots = int(lots / 100) * 100  # 计算能下的手数，取整数
                # self.log(f"buy {data_name} : {lots}, {bt.num2date(data.datetime[0])}")
                order = self.buy(data, size=lots)
                self.position_dict[data_name] = order
        # 过期订单关闭
        self.expire_order_close()

    def expire_order_close(self):
        keys_list = list(self.position_dict.keys())
        for name in keys_list:
            order = self.position_dict[name]
            data = self.getdatabyname(name)
            close = data.close
            data_date = data.datetime.date(0).strftime("%Y-%m-%d")
            current_date = self.datas[0].datetime.date(0).strftime("%Y-%m-%d")
            if data_date == current_date:
                try:
                    close[3]
                except Exception as e:
                    self.log(f"{e}")
                    self.log(f"{data._name} will be cancelled")
                    size = self.getposition(data).size
                    if size != 0:
                        self.close(data)
                    else:
                        self.cancel(order)
                    self.position_dict.pop(name)

    def get_target_symbol(self):
        # self.log("调用get_target_symbol函数")
        # 根据价格和溢价率进行打分
        # 按照价格从低到高进行排序打分,按照溢价率从低到高进行排序打分,然后按照每个50%的权重进行打分，根据打分对可转债进行排序
        # 返回结果是一个list of list, [[data1, score1], [data2, score2] ... ]
        data_name_list = []
        close_list = []
        rate_list = []
        # for data in self.datas[1:]:
        for asset in self.stock_dict:
            data = self.getdatabyname(asset)
            close = data.close[0]
            rate = data.convert_premium_rate[0]
            data_name_list.append(data._name)
            close_list.append(close)
            rate_list.append(rate)

        # 创建DataFrame
        df = pd.DataFrame({
            'data_name': data_name_list,
            'close': close_list,
            'rate': rate_list
        })

        # # 对价格进行排序并打分（从低到高，排名越靠前分数越低）
        # df['close_score'] = df['close'].rank(method='min')
        #
        # # 对溢价率进行排序并打分（从低到高，排名越靠前分数越低）
        # df['rate_score'] = df['rate'].rank(method='min')
        # 对价格进行排序并打分（从低到高，排名越靠前分数越低）
        df['close_score'] = df['close'].rank(method='min')
        # 对溢价率进行排序并打分（从低到高，排名越靠前分数越低）
        df['rate_score'] = df['rate'].rank(method='min')
        # 计算综合得分（使用权重）
        df['total_score'] = df['close_score'] * self.p.first_factor_weight + df[
            'rate_score'] * self.p.second_factor_weight
        df = df.sort_values(by=['total_score'], ascending=False)
        # print(df)
        # 转换成需要的结果格式 [[data, score], ...]
        result = []
        for _, row in df.iterrows():
            # 通过data_name找回对应的data对象
            # data = self.getdatabyname(row['data_name'])
            result.append([row['data_name'], row['total_score']])

        return result

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            # order被提交和接受
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
                self.log("buy result : buy_price : {} , buy_cost : {} , commission : {}".format(
                    order.executed.price, order.executed.value, order.executed.comm))
    
            else:  # Sell
                self.log("sell result : sell_price : {} , sell_cost : {} , commission : {}".format(
                    order.executed.price, order.executed.value, order.executed.comm))
    
    def notify_trade(self, trade):
        # 一个trade结束的时候输出信息
        if trade.isclosed:
            self.log('closed symbol is : {} , total_profit : {} , net_profit : {}'.format(
                trade.getdataname(), trade.pnl, trade.pnlcomm))
        if trade.isopen:
            self.log('open symbol is : {} , price : {} '.format(
                trade.getdataname(), trade.price))


def test_strategy(max_bonds=None, stdstats=True):
    """
    运行可转债双低策略回测

    参数:
        max_bonds: 最大添加的可转债数量，None表示添加所有。用于测试时可设置较小值
        stdstats: 是否启用标准统计观察者（默认True）
                 True: 显示现金、市值、买卖点等标准统计
                 False: 禁用标准统计，可能稍微提升性能
    """
    # 添加cerebro
    # 修复说明：之前需要设置stdstats=False是因为ExtendPandasFeed的列索引定义错误
    # 现已修复，可以正常使用stdstats=True
    cerebro = bt.Cerebro(stdstats=stdstats)

    # 添加策略
    cerebro.addstrategy(BondConvertTwoFactor)
    params = dict(
        fromdate=datetime.datetime(2018, 1, 1),
        todate=datetime.datetime(2025, 10, 10),
        timeframe=bt.TimeFrame.Days,
        dtformat="%Y-%m-%d",
    )
    # 添加指数数据
    print("正在加载指数数据...")
    index_data = pd.read_csv(resolve_data_path('bond_index_000000.csv'))
    index_data.index = pd.to_datetime(index_data['datetime'])
    index_data = index_data[index_data.index > pd.to_datetime("2018-01-01")]
    index_data = index_data.drop(['datetime'], axis=1)
    print(f"指数数据范围: {index_data.index[0]} 至 {index_data.index[-1]}, 共 {len(index_data)} 条")

    feed = ExtendPandasFeed(dataname=index_data)
    cerebro.adddata(feed, name='000000')

    # 清洗数据并添加可转债数据
    print("\n正在加载可转债数据...")
    datas = clean_data()
    print(f"总共有 {len(datas)} 只可转债")

    added_count = 0
    for symbol, data in datas.items():
        if len(data) > 30:
            # 如果设置了最大数量限制，达到限制后停止添加
            if max_bonds is not None and added_count >= max_bonds:
                break

            feed = ExtendPandasFeed(dataname=data)
            # 添加合约数据
            cerebro.adddata(feed, name=symbol)
            added_count += 1
            if added_count > 60:
                break
            # 添加交易费用
            comm = ComminfoFuturesPercent(commission=0.0001, margin=0.1, mult=1)
            cerebro.broker.addcommissioninfo(comm, name=symbol)

            # 每添加100个打印一次进度
            if added_count % 100 == 0:
                print(f"已添加 {added_count} 只可转债...")

    print(f"\n成功添加 {added_count} 只可转债数据")

    # 添加资金
    cerebro.broker.setcash(100000000.0)
    print("\n开始运行回测...")
    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.TotalValue, _name='my_value')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='my_sharpe')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='my_returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='my_drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='my_trade_analyzer')
    cerebro.addanalyzer(bt.analyzers.PyFolio, _name='pyfolio')
    # cerebro.addanalyzer(bt.analyzers.PyFolio)
    # 运行回测
    results = cerebro.run()
    value_df = pd.DataFrame([results[0].analyzers.my_value.get_analysis()]).T
    value_df.columns = ['value']
    value_df['datetime'] = pd.to_datetime(value_df.index)
    value_df['date'] = [i.date() for i in value_df['datetime']]
    value_df = value_df.drop_duplicates("date", keep="last")
    value_df = value_df[['value']]
    # value_df.to_csv("./result/参数优化结果/" + file_name + ".csv")
    sharpe_ratio = results[0].analyzers.my_sharpe.get_analysis()['sharperatio']
    annual_return = results[0].analyzers.my_returns.get_analysis()['rnorm']
    max_drawdown = results[0].analyzers.my_drawdown.get_analysis()["max"]["drawdown"] / 100
    trade_num = results[0].analyzers.my_trade_analyzer.get_analysis()['total']['total']
    print("sharpe_ratio:", sharpe_ratio)
    print("annual_return:", annual_return)
    print("max_drawdown:", max_drawdown)
    print("trade_num:", trade_num)
    assert sharpe_ratio == 0.46882103593170665
    assert annual_return == 0.056615798284517765
    assert max_drawdown == 0.24142378277185714
    assert trade_num == 1750
    strategy = results[0]
    assert strategy.bar_num == 1885
    # 2025-10-13T00:00:00, self.bar_num = 1885
    # sharpe_ratio: 0.46882103593170665
    # annual_return: 0.056615798284517765
    # max_drawdown: 0.24142378277185714
    # trade_num: 1750
    # trade_num: 1749
    return results, value_df


if __name__ == "__main__":
    # 如果需要生成指数数据，取消下面的注释
    # from 清洗数据 import generate_index_data
    # generate_index_data(input_file='bond_merged_all_data.csv', output_file='bond_index_000000.csv')

    # 运行回测策略
    # 参数说明:
    #   max_bonds=None: 添加所有可转债（可能比较慢）
    #   max_bonds=50: 只添加前50只可转债（用于快速测试）
    #   max_bonds=200: 添加200只可转债（推荐用于正式回测）

    print("=" * 60)
    print("可转债双低策略回测系统")
    print("=" * 60)

    # 运行回测 - 添加所有可转债
    # 注意：由于有958只可转债，运行可能需要较长时间
    results, value_df = test_strategy(max_bonds=None)
    # value_df = value_df[(value_df.index>pd.to_datetime("2025-01-01"))&(value_df.index<pd.to_datetime("2025-07-31"))]
    print("\n" + "=" * 60)
    print("回测结束")
    print("=" * 60)
    # # 创建图形
    # plt.figure(figsize=(14, 7))
    #
    # # 绘制价值曲线
    # plt.plot(value_df.index, value_df['value'], linewidth=2, color='#1f77b4')
    #
    # # 设置标题和标签
    # plt.title('投资组合价值曲线', fontsize=16, pad=20)
    # plt.xlabel('日期', fontsize=12)
    # plt.ylabel('组合价值 (元)', fontsize=12)
    #
    #
    # # 设置y轴格式为科学计数法
    # def format_sci(x, pos):
    #     return f"{x / 1e8:.2f}亿"
    #
    #
    # plt.gca().yaxis.set_major_formatter(FuncFormatter(format_sci))
    #
    # # 设置x轴日期格式
    # plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    # plt.gca().xaxis.set_major_locator(mdates.YearLocator())
    # plt.gcf().autofmt_xdate()  # 自动旋转日期标签
    #
    # # 添加网格
    # plt.grid(True, linestyle='--', alpha=0.6)
    #
    # # 添加起始和结束点的标注
    # start_date = value_df.index[0].strftime('%Y-%m-%d')
    # end_date = value_df.index[-1].strftime('%Y-%m-%d')
    # start_value = f"{value_df['value'].iloc[0] / 1e8:.2f}亿"
    # end_value = f"{value_df['value'].iloc[-1] / 1e8:.2f}亿"
    #
    # plt.annotate(f'起始: {start_date}\n{start_value}',
    #              xy=(value_df.index[0], value_df['value'].iloc[0]),
    #              xytext=(10, 10), textcoords='offset points',
    #              bbox=dict(boxstyle='round,pad=0.5', fc='yellow', alpha=0.5))
    #
    # plt.annotate(f'结束: {end_date}\n{end_value}',
    #              xy=(value_df.index[-1], value_df['value'].iloc[-1]),
    #              xytext=(-100, 10), textcoords='offset points',
    #              bbox=dict(boxstyle='round,pad=0.5', fc='yellow', alpha=0.5))
    #
    # # 计算并显示收益率
    # total_return = (value_df['value'].iloc[-1] / value_df['value'].iloc[0] - 1) * 100
    # annual_return = (value_df['value'].iloc[-1] / value_df['value'].iloc[0]) ** (252 / len(value_df)) - 1
    # annual_return = annual_return * 100
    #
    # plt.figtext(0.15, 0.15,
    #             f"累计收益率: {total_return:.2f}%\n年化收益率: {annual_return:.2f}%",
    #             bbox=dict(facecolor='white', alpha=0.8, edgecolor='gray', boxstyle='round,pad=0.5'))
    #
    # # 调整布局
    # plt.tight_layout()
    #
    # # 显示图形
    # plt.show()