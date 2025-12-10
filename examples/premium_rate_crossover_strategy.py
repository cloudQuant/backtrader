#!/usr/bin/env python
"""
可转债溢价率均线金叉死叉策略

策略逻辑：
1. 计算转股溢价率的10日和60日移动平均线
2. 当10日均线上穿60日均线（金叉）时买入
3. 当10日均线下穿60日均线（死叉）时平仓

参考：
- examples/sma_crossover.py
- examples/优化策略1.py
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

# 设置中文字体
plt.rcParams["font.sans-serif"] = ["SimHei"]  # 用来正常显示中文标签
plt.rcParams["axes.unicode_minus"] = False  # 用来正常显示负号
# 忽略警告
warnings.filterwarnings("ignore")


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
        ("datetime", None),  # datetime是索引，不是数据列
        ("open", 0),  # 第1列 -> 索引0
        ("high", 1),  # 第2列 -> 索引1
        ("low", 2),  # 第3列 -> 索引2
        ("close", 3),  # 第4列 -> 索引3
        ("volume", 4),  # 第5列 -> 索引4
        ("openinterest", -1),  # 不存在该列
        ("pure_bond_value", 5),  # 第6列 -> 索引5
        ("convert_value", 6),  # 第7列 -> 索引6
        ("pure_bond_premium_rate", 7),  # 第8列 -> 索引7
        ("convert_premium_rate", 8),  # 第9列 -> 索引8
    )

    # 定义扩展的数据线
    lines = ("pure_bond_value", "convert_value", "pure_bond_premium_rate", "convert_premium_rate")


class PremiumRateCrossoverStrategy(bt.Strategy):
    """
    转股溢价率均线交叉策略

    策略逻辑：
    - 使用转股溢价率（convert_premium_rate）计算移动平均线
    - 短期均线（默认10日）上穿长期均线（默认60日）时买入
    - 短期均线下穿长期均线时卖出平仓
    """

    params = (
        ("short_period", 10),  # 短期均线周期
        ("long_period", 60),  # 长期均线周期
    )

    def log(self, txt, dt=None):
        """日志输出函数"""
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print(f"{dt.isoformat()}, {txt}")

    def __init__(self):
        """初始化策略"""
        # 获取转股溢价率数据线
        self.premium_rate = self.datas[0].convert_premium_rate

        # 计算短期和长期移动平均线
        self.sma_short = btind.SimpleMovingAverage(self.premium_rate, period=self.p.short_period)
        self.sma_long = btind.SimpleMovingAverage(self.premium_rate, period=self.p.long_period)

        # 计算均线交叉信号
        # CrossOver > 0: 短期均线上穿长期均线（金叉）
        # CrossOver < 0: 短期均线下穿长期均线（死叉）
        self.crossover = btind.CrossOver(self.sma_short, self.sma_long)

        # 记录订单
        self.order = None

    def notify_order(self, order):
        """订单状态通知"""
        if order.status in [order.Submitted, order.Accepted]:
            # 订单已提交/接受 - 无需操作
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(
                    f"买入执行, 价格: {order.executed.price:.2f}, "
                    f"成本: {order.executed.value:.2f}, "
                    f"手续费: {order.executed.comm:.2f}"
                )
            elif order.issell():
                self.log(
                    f"卖出执行, 价格: {order.executed.price:.2f}, "
                    f"成本: {order.executed.value:.2f}, "
                    f"手续费: {order.executed.comm:.2f}"
                )

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log("订单取消/保证金不足/拒绝")

        # 重置订单
        self.order = None

    def notify_trade(self, trade):
        """交易通知"""
        if not trade.isclosed:
            return

        self.log(f"交易盈亏, 毛利: {trade.pnl:.2f}, 净利: {trade.pnlcomm:.2f}")

    def next(self):
        """策略核心逻辑"""
        # 如果有未完成的订单，等待
        if self.order:
            return

        # 记录当前状态
        current_date = bt.num2date(self.datas[0].datetime[0]).strftime("%Y-%m-%d")
        premium_rate = self.premium_rate[0]
        sma_short = self.sma_short[0]
        sma_long = self.sma_long[0]

        # 检查是否已经有仓位
        if not self.position:
            # 没有仓位，检查是否金叉买入
            if self.crossover > 0:
                # 金叉信号：短期均线上穿长期均线
                self.log(
                    f"金叉信号 - 买入, 溢价率: {premium_rate:.2f}%, "
                    f"短期均线: {sma_short:.2f}, 长期均线: {sma_long:.2f}"
                )
                # 使用可用资金的95%买入（留一些作为手续费缓冲）
                cash = self.broker.getcash()
                size = int((cash * 0.95) / self.datas[0].close[0])
                self.order = self.buy(size=size)
        else:
            # 有仓位，检查是否死叉卖出
            if self.crossover < 0:
                # 死叉信号：短期均线下穿长期均线
                self.log(
                    f"死叉信号 - 卖出, 溢价率: {premium_rate:.2f}%, "
                    f"短期均线: {sma_short:.2f}, 长期均线: {sma_long:.2f}"
                )
                # 平仓
                self.order = self.close()


def load_bond_data(csv_file):
    """
    加载可转债数据

    参数:
        csv_file: CSV文件路径

    返回:
        处理后的DataFrame
    """
    print(f"正在加载数据: {csv_file}")
    df = pd.read_csv(csv_file)

    # 重命名列
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

    # 转换日期格式
    df["datetime"] = pd.to_datetime(df["datetime"])

    # 设置索引
    df = df.set_index("datetime")

    # 删除不需要的列
    df = df.drop(["BOND_CODE", "BOND_SYMBOL"], axis=1)

    # 删除缺失值
    df = df.dropna()

    # 转换为浮点数
    df = df.astype(float)

    print(f"数据加载完成: {len(df)} 条记录")
    print(f"日期范围: {df.index[0]} 至 {df.index[-1]}")

    return df


def run_strategy(csv_file="113013.csv", initial_cash=100000.0, commission=0.0003):
    """
    运行回测策略

    参数:
        csv_file: 可转债数据CSV文件
        initial_cash: 初始资金
        commission: 手续费率
    """
    print("=" * 60)
    print("可转债溢价率均线交叉策略回测系统")
    print("=" * 60)

    # 创建Cerebro引擎
    cerebro = bt.Cerebro()

    # 添加策略
    cerebro.addstrategy(PremiumRateCrossoverStrategy)

    # 加载数据
    df = load_bond_data(csv_file)

    # 创建数据源
    data = ExtendPandasFeed(dataname=df)

    # 添加数据到Cerebro
    cerebro.adddata(data)

    # 设置初始资金
    cerebro.broker.setcash(initial_cash)
    print(f"\n初始资金: {initial_cash:.2f}")

    # 设置手续费
    cerebro.broker.setcommission(commission=commission)
    print(f"手续费率: {commission*100:.2f}%")

    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="time_return")

    print("\n开始回测...")
    print("-" * 60)

    # 运行回测
    results = cerebro.run()
    strat = results[0]

    # 获取最终资金
    final_value = cerebro.broker.getvalue()

    print("-" * 60)
    print("\n回测结果:")
    print("=" * 60)
    print(f"初始资金: {initial_cash:.2f}")
    print(f"最终资金: {final_value:.2f}")
    print(f"总收益: {final_value - initial_cash:.2f}")
    print(f"收益率: {(final_value / initial_cash - 1) * 100:.2f}%")

    # 获取分析结果
    sharpe_ratio = strat.analyzers.sharpe.get_analysis()
    returns = strat.analyzers.returns.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    trades = strat.analyzers.trades.get_analysis()

    print(f"\n夏普比率: {sharpe_ratio.get('sharperatio', 'N/A')}")
    if "rnorm100" in returns:
        print(f"年化收益率: {returns['rnorm100']:.2f}%")
    print(f"最大回撤: {drawdown['max']['drawdown']:.2f}%")

    if "total" in trades:
        print(f"\n总交易次数: {trades['total'].get('total', 0)}")
        if "won" in trades["total"]:
            print(f"盈利交易: {trades['total']['won']}")
        if "lost" in trades["total"]:
            print(f"亏损交易: {trades['total']['lost']}")

    # 获取时间序列收益率用于绘图
    time_return = strat.analyzers.time_return.get_analysis()

    return cerebro, results, time_return


def plot_results(time_return, initial_cash=100000.0, csv_file="113013.csv"):
    """
    绘制回测结果图表

    参数:
        time_return: 时间序列收益率
        initial_cash: 初始资金
        csv_file: 数据文件名（用于标题）
    """
    # 转换为DataFrame
    returns_df = pd.DataFrame(list(time_return.items()), columns=["date", "return"])
    returns_df["date"] = pd.to_datetime(returns_df["date"])
    returns_df = returns_df.set_index("date")

    # 计算累计净值
    returns_df["cumulative"] = (1 + returns_df["return"]).cumprod()
    returns_df["value"] = returns_df["cumulative"] * initial_cash

    # 创建图形
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))

    # 绘制资产曲线
    ax1.plot(returns_df.index, returns_df["value"], linewidth=2, color="#1f77b4")
    ax1.set_title(f"策略资产曲线 - {csv_file}", fontsize=16, pad=20)
    ax1.set_xlabel("日期", fontsize=12)
    ax1.set_ylabel("资产价值 (元)", fontsize=12)
    ax1.grid(True, linestyle="--", alpha=0.6)

    # 格式化y轴
    def format_yuan(x, pos):
        if x >= 10000:
            return f"{x/10000:.1f}万"
        return f"{x:.0f}"

    ax1.yaxis.set_major_formatter(FuncFormatter(format_yuan))

    # 格式化x轴日期
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax1.xaxis.set_major_locator(mdates.YearLocator())
    fig.autofmt_xdate()

    # 添加起始和结束点标注
    start_value = returns_df["value"].iloc[0]
    end_value = returns_df["value"].iloc[-1]
    start_date = returns_df.index[0].strftime("%Y-%m-%d")
    end_date = returns_df.index[-1].strftime("%Y-%m-%d")

    ax1.annotate(
        f"起始: {start_date}\n{start_value:.0f}元",
        xy=(returns_df.index[0], start_value),
        xytext=(10, 10),
        textcoords="offset points",
        bbox=dict(boxstyle="round,pad=0.5", fc="yellow", alpha=0.5),
    )

    ax1.annotate(
        f"结束: {end_date}\n{end_value:.0f}元",
        xy=(returns_df.index[-1], end_value),
        xytext=(-100, 10),
        textcoords="offset points",
        bbox=dict(boxstyle="round,pad=0.5", fc="yellow", alpha=0.5),
    )

    # 绘制累计收益率
    returns_df["cumulative_pct"] = (returns_df["cumulative"] - 1) * 100
    ax2.plot(returns_df.index, returns_df["cumulative_pct"], linewidth=2, color="#2ca02c")
    ax2.set_title("累计收益率", fontsize=16, pad=20)
    ax2.set_xlabel("日期", fontsize=12)
    ax2.set_ylabel("收益率 (%)", fontsize=12)
    ax2.grid(True, linestyle="--", alpha=0.6)
    ax2.axhline(y=0, color="r", linestyle="--", alpha=0.5)

    # 格式化x轴日期
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax2.xaxis.set_major_locator(mdates.YearLocator())

    # 计算统计信息
    total_return = (end_value / start_value - 1) * 100
    days = (returns_df.index[-1] - returns_df.index[0]).days
    annual_return = ((end_value / start_value) ** (365 / days) - 1) * 100

    # 添加统计信息文本框
    stats_text = (
        f"累计收益率: {total_return:.2f}%\n年化收益率: {annual_return:.2f}%\n回测天数: {days}天"
    )
    fig.text(
        0.15,
        0.47,
        stats_text,
        bbox=dict(facecolor="white", alpha=0.8, edgecolor="gray", boxstyle="round,pad=0.5"),
    )

    plt.tight_layout()

    # 保存图片
    output_file = csv_file.replace(".csv", "_strategy_result.png")
    plt.savefig(output_file, dpi=150, bbox_inches="tight")
    print(f"\n图表已保存到: {output_file}")

    # 显示图形
    plt.show()


if __name__ == "__main__":
    # 配置参数
    CSV_FILE = "113013.csv"  # 可转债数据文件
    INITIAL_CASH = 100000.0  # 初始资金：10万元
    COMMISSION = 0.0003  # 手续费率：0.03%

    # 运行回测
    cerebro, results, time_return = run_strategy(
        csv_file=CSV_FILE, initial_cash=INITIAL_CASH, commission=COMMISSION
    )

    # 绘制结果
    print("\n正在生成图表...")
    plot_results(time_return, initial_cash=INITIAL_CASH, csv_file=CSV_FILE)

    print("\n" + "=" * 60)
    print("回测完成")
    print("=" * 60)
