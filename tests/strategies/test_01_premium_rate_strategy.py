#!/usr/bin/env python
"""
可转债溢价率均线交叉策略 - 独立测试文件

这个文件包含：
1. 数据加载函数
2. 策略类定义
3. 回测运行函数
4. 指标验证函数
5. 所有 pytest 测试函数

可以完全独立运行，不依赖其他模块。

使用方法:
    # 直接运行
    python test_premium_rate_strategy.py

    # 使用 pytest 运行所有测试
    pytest test_premium_rate_strategy.py -v

    # 运行特定测试
    pytest test_premium_rate_strategy.py::test_strategy_final_value -v
"""

import os
import warnings

import pandas as pd

import backtrader as bt
from backtrader.cerebro import Cerebro
from backtrader.strategy import Strategy
from backtrader.feeds import PandasData
import backtrader.indicators as btind

# 忽略警告
warnings.filterwarnings("ignore")

# 获取数据目录
# 当前文件在 tests/strategies/test_premium_rate_strategy.py
# 数据文件在 tests/datas/ 目录下
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))  # tests/strategies
TESTS_DIR = os.path.dirname(CURRENT_DIR)  # tests
DATA_DIR = os.path.join(TESTS_DIR, "datas")  # tests/datas


# ============================================================
# 数据源定义
# ============================================================


class ExtendPandasFeed(PandasData):
    """
    扩展的Pandas数据源，添加可转债特有的字段

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
        ("datetime", None),
        ("open", 0),
        ("high", 1),
        ("low", 2),
        ("close", 3),
        ("volume", 4),
        ("openinterest", -1),
        ("pure_bond_value", 5),
        ("convert_value", 6),
        ("pure_bond_premium_rate", 7),
        ("convert_premium_rate", 8),
    )

    lines = ("pure_bond_value", "convert_value", "pure_bond_premium_rate", "convert_premium_rate")


# ============================================================
# 策略定义
# ============================================================


class PremiumRateCrossoverStrategy(Strategy):
    """
    转股溢价率均线交叉策略

    策略逻辑：
    - 使用转股溢价率（convert_premium_rate）计算移动平均线
    - 短期均线（默认10日）上穿长期均线（默认60日）时买入
    - 短期均线下穿长期均线时卖出平仓
    """

    params = (
        ("short_period", 10),
        ("long_period", 60),
        ("verbose", False),  # 是否打印日志
    )

    def log(self, txt, dt=None):
        """日志输出函数"""
        if self.p.verbose:
            dt = dt or bt.num2date(self.datas[0].datetime[0])
            print("{}, {}".format(dt.isoformat(), txt))

    def __init__(self):
        """初始化策略"""
        self.premium_rate = self.datas[0].convert_premium_rate

        self.sma_short = btind.SimpleMovingAverage(self.premium_rate, period=self.p.short_period)
        self.sma_long = btind.SimpleMovingAverage(self.premium_rate, period=self.p.long_period)

        self.crossover = btind.CrossOver(self.sma_short, self.sma_long)
        self.order = None

    def notify_order(self, order):
        """订单状态通知"""
        if order.status in [order.Submitted, order.Accepted]:
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

        self.order = None

    def notify_trade(self, trade):
        """交易通知"""
        if not trade.isclosed:
            return

        self.log(f"交易盈亏, 毛利: {trade.pnl:.2f}, 净利: {trade.pnlcomm:.2f}")

    def next(self):
        """策略核心逻辑"""
        if self.order:
            return

        if not self.position:
            if self.crossover > 0:
                premium_rate = self.premium_rate[0]
                sma_short = self.sma_short[0]
                sma_long = self.sma_long[0]
                self.log(
                    f"金叉信号 - 买入, 溢价率: {premium_rate:.2f}%, "
                    f"短期均线: {sma_short:.2f}, 长期均线: {sma_long:.2f}"
                )
                cash = self.broker.getcash()
                size = int((cash * 0.95) / self.datas[0].close[0])
                self.order = self.buy(size=size)
        else:
            if self.crossover < 0:
                premium_rate = self.premium_rate[0]
                sma_short = self.sma_short[0]
                sma_long = self.sma_long[0]
                self.log(
                    f"死叉信号 - 卖出, 溢价率: {premium_rate:.2f}%, "
                    f"短期均线: {sma_short:.2f}, 长期均线: {sma_long:.2f}"
                )
                self.order = self.close()


# ============================================================
# 辅助函数
# ============================================================


def load_bond_data(csv_file):
    """
    加载可转债数据

    参数:
        csv_file: CSV文件路径

    返回:
        处理后的DataFrame
    """
    df = pd.read_csv(csv_file)

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

    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime")
    df = df.drop(["BOND_CODE", "BOND_SYMBOL"], axis=1)
    df = df.dropna()
    df = df.astype(float)

    return df


def run_strategy(csv_file="113013.csv", initial_cash=100000.0, commission=0.0003, verbose=False):
    """
    运行回测策略

    参数:
        csv_file: 可转债数据CSV文件
        initial_cash: 初始资金
        commission: 手续费率
        verbose: 是否打印详细日志

    返回:
        tuple: (cerebro, results, time_return, metrics)
    """
    # 创建Cerebro引擎
    cerebro = Cerebro()

    # 添加策略（传递verbose参数）
    cerebro.addstrategy(PremiumRateCrossoverStrategy, verbose=verbose)

    # 加载数据
    df = load_bond_data(csv_file)
    data = ExtendPandasFeed(dataname=df)
    cerebro.adddata(data)

    # 设置初始资金和手续费
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=commission)

    # 添加分析器
    cerebro.addanalyzer(
        bt.analyzers.SharpeRatio,
        _name="sharpe",
        annualize=True,
        timeframe=bt.TimeFrame.Days,
        riskfreerate=0.0,
    )
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="time_return")

    # 运行回测
    results = cerebro.run()
    strat = results[0]

    # 获取最终资金
    final_value = cerebro.broker.getvalue()

    # 获取分析结果
    sharpe_ratio = strat.analyzers.sharpe.get_analysis()
    returns = strat.analyzers.returns.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    trades = strat.analyzers.trades.get_analysis()
    time_return = strat.analyzers.time_return.get_analysis()

    # 收集所有关键指标
    total_profit = final_value - initial_cash
    return_rate = (final_value / initial_cash - 1) * 100
    sharpe = sharpe_ratio.get("sharperatio", None)
    annual_ret = returns.get("rnorm100", None)
    max_dd = drawdown["max"]["drawdown"]
    total_trades = trades["total"].get("total", 0) if "total" in trades else 0

    metrics = {
        "final_value": final_value,
        "total_profit": total_profit,
        "return_rate": return_rate,
        "sharpe_ratio": sharpe,
        "annual_return": annual_ret,
        "max_drawdown": max_dd,
        "total_trades": total_trades,
        "initial_cash": initial_cash,
    }

    return cerebro, results, time_return, metrics


def validate_metrics(metrics, expected_metrics, tolerance=0.0001):
    """
    验证回测指标是否符合预期

    参数:
        metrics: 实际回测指标字典
        expected_metrics: 期望的指标字典
        tolerance: 允许的相对误差，默认0.0001（万分之一）

    返回:
        dict: 包含验证结果的字典
    """
    metrics_to_check = [
        ("final_value", "最终资金"),
        ("total_profit", "总收益"),
        ("return_rate", "收益率(%)"),
        ("sharpe_ratio", "夏普比率"),
        ("annual_return", "年化收益率(%)"),
        ("max_drawdown", "最大回撤(%)"),
        ("total_trades", "总交易次数"),
    ]

    all_passed = True
    details = {}

    for key, name in metrics_to_check:
        if key not in expected_metrics:
            continue

        actual = metrics.get(key)
        expected = expected_metrics[key]

        if actual is None or expected is None:
            details[key] = {"passed": None, "reason": "None value"}
            continue

        # 对于交易次数，使用精确匹配
        if key == "total_trades":
            passed = actual == expected
            details[key] = {
                "passed": passed,
                "actual": actual,
                "expected": expected,
                "error": 0 if passed else abs(actual - expected),
            }
            all_passed = all_passed and passed
        else:
            # 对于其他指标，使用相对误差容差
            if expected == 0:
                diff = abs(actual - expected)
                passed = diff <= tolerance
                details[key] = {
                    "passed": passed,
                    "actual": actual,
                    "expected": expected,
                    "abs_error": diff,
                }
            else:
                rel_error = abs((actual - expected) / expected)
                passed = rel_error <= tolerance
                details[key] = {
                    "passed": passed,
                    "actual": actual,
                    "expected": expected,
                    "rel_error": rel_error,
                }
            all_passed = all_passed and passed

    return {"passed": all_passed, "details": details}


# ============================================================
# 测试配置
# ============================================================

# 期望的回测指标
EXPECTED_METRICS = {
    "final_value": 104275.8704,
    "total_profit": 4275.8704,
    "return_rate": 4.27587040,
    "sharpe_ratio": 0.12623860749976154,
    "annual_return": 0.7334,
    "max_drawdown": 17.413,
    "total_trades": 21,
}

# 测试配置
TEST_CONFIG = {
    "csv_file": os.path.join(DATA_DIR, "113013.csv"),  # 使用绝对路径
    "initial_cash": 100000.0,
    "commission": 0.0003,
    "tolerance": 0.0001,
}


# ============================================================
# 全局变量 - 用于存储回测结果，避免重复运行
# ============================================================

# 存储回测结果的全局变量
_test_results = None


def get_test_results():
    """
    获取回测结果，确保只运行一次

    返回:
        tuple: (cerebro, results, time_return, metrics)
    """
    global _test_results

    # 如果已经运行过，直接返回结果
    if _test_results is not None:
        return _test_results

    # 首次运行，保存结果
    _test_results = run_strategy(
        csv_file=TEST_CONFIG["csv_file"],
        initial_cash=TEST_CONFIG["initial_cash"],
        commission=TEST_CONFIG["commission"],
        verbose=False,
    )

    return _test_results


# ============================================================
# Pytest 测试函数
# ============================================================


def test_strategy_final_value():
    """测试策略最终资金是否符合预期"""
    cerebro, results, time_return, metrics = get_test_results()

    expected = EXPECTED_METRICS["final_value"]
    actual = metrics["final_value"]
    rel_error = abs((actual - expected) / expected)

    assert (
        rel_error <= TEST_CONFIG["tolerance"]
    ), f"最终资金不符合预期: 实际={actual:.4f}, 期望={expected:.4f}, 相对误差={rel_error:.6f}"


def test_strategy_total_profit():
    """测试策略总收益是否符合预期"""
    cerebro, results, time_return, metrics = get_test_results()

    expected = EXPECTED_METRICS["total_profit"]
    actual = metrics["total_profit"]
    rel_error = abs((actual - expected) / expected)

    assert (
        rel_error <= TEST_CONFIG["tolerance"]
    ), f"总收益不符合预期: 实际={actual:.4f}, 期望={expected:.4f}, 相对误差={rel_error:.6f}"


def test_strategy_return_rate():
    """测试策略收益率是否符合预期"""
    cerebro, results, time_return, metrics = get_test_results()

    expected = EXPECTED_METRICS["return_rate"]
    actual = metrics["return_rate"]
    rel_error = abs((actual - expected) / expected)

    assert (
        rel_error <= TEST_CONFIG["tolerance"]
    ), f"收益率不符合预期: 实际={actual:.4f}%, 期望={expected:.4f}%, 相对误差={rel_error:.6f}"


def test_strategy_sharpe_ratio():
    """测试策略夏普比率是否符合预期"""
    cerebro, results, time_return, metrics = get_test_results()

    expected = EXPECTED_METRICS["sharpe_ratio"]
    actual = metrics["sharpe_ratio"]

    assert actual is not None, "夏普比率不应为None"

    rel_error = abs((actual - expected) / expected)

    assert (
        rel_error <= TEST_CONFIG["tolerance"]
    ), f"夏普比率不符合预期: 实际={actual:.4f}, 期望={expected:.4f}, 相对误差={rel_error:.6f}"


def test_strategy_annual_return():
    """测试策略年化收益率是否符合预期"""
    cerebro, results, time_return, metrics = get_test_results()

    expected = EXPECTED_METRICS["annual_return"]
    actual = metrics["annual_return"]

    assert actual is not None, "年化收益率不应为None"

    rel_error = abs((actual - expected) / expected)

    assert (
        rel_error <= TEST_CONFIG["tolerance"]
    ), f"年化收益率不符合预期: 实际={actual:.4f}%, 期望={expected:.4f}%, 相对误差={rel_error:.6f}"


def test_strategy_max_drawdown():
    """测试策略最大回撤是否符合预期"""
    cerebro, results, time_return, metrics = get_test_results()

    expected = EXPECTED_METRICS["max_drawdown"]
    actual = metrics["max_drawdown"]
    rel_error = abs((actual - expected) / expected)

    assert (
        rel_error <= TEST_CONFIG["tolerance"]
    ), f"最大回撤不符合预期: 实际={actual:.4f}%, 期望={expected:.4f}%, 相对误差={rel_error:.6f}"


def test_strategy_total_trades():
    """测试策略总交易次数是否符合预期"""
    cerebro, results, time_return, metrics = get_test_results()

    expected = EXPECTED_METRICS["total_trades"]
    actual = metrics["total_trades"]

    assert actual == expected, f"总交易次数不符合预期: 实际={actual}, 期望={expected}"


def test_strategy_all_metrics():
    """测试策略所有指标是否符合预期（综合测试）"""
    cerebro, results, time_return, metrics = get_test_results()

    result = validate_metrics(metrics, EXPECTED_METRICS, tolerance=TEST_CONFIG["tolerance"])

    assert result["passed"], f"策略指标验证失败，详情: {result['details']}"


def test_strategy_metrics_not_none():
    """测试策略关键指标不为None"""
    cerebro, results, time_return, metrics = get_test_results()

    assert metrics["final_value"] is not None, "最终资金不应为None"
    assert metrics["total_profit"] is not None, "总收益不应为None"
    assert metrics["return_rate"] is not None, "收益率不应为None"
    assert metrics["max_drawdown"] is not None, "最大回撤不应为None"
    assert metrics["total_trades"] is not None, "总交易次数不应为None"


def test_strategy_positive_metrics():
    """测试策略关键指标的合理性"""
    cerebro, results, time_return, metrics = get_test_results()

    assert metrics["final_value"] > 0, "最终资金应大于0"
    assert metrics["max_drawdown"] >= 0, "最大回撤应大于等于0"
    assert metrics["max_drawdown"] <= 100, "最大回撤应小于等于100%"
    assert metrics["total_trades"] >= 0, "交易次数应大于等于0"

    expected_return = (metrics["final_value"] / metrics["initial_cash"] - 1) * 100
    assert (
        abs(metrics["return_rate"] - expected_return) < 0.01
    ), f"收益率计算不一致: {metrics['return_rate']:.4f} vs {expected_return:.4f}"


# ============================================================
# 主测试函数（明显的测试入口）
# ============================================================


def test_main():
    """
    主测试函数 - 运行完整的策略测试并打印详细结果

    这个函数会：
    1. 运行回测
    2. 验证所有指标
    3. 打印详细的测试报告
    4. 使用 assert 确保测试通过
    """
    print("\n" + "=" * 70)
    print("可转债溢价率均线交叉策略 - 完整测试")
    print("=" * 70)

    # 运行回测
    print("\n正在运行回测...")
    cerebro, results, time_return, metrics = run_strategy(
        csv_file=TEST_CONFIG["csv_file"],
        initial_cash=TEST_CONFIG["initial_cash"],
        commission=TEST_CONFIG["commission"],
        verbose=False,
    )

    print("回测完成！\n")

    # 打印回测结果
    print("-" * 70)
    print("回测结果:")
    print("-" * 70)
    print(f"初始资金: {metrics['initial_cash']:.2f}")
    print(f"最终资金: {metrics['final_value']:.2f}")
    print(f"总收益: {metrics['total_profit']:.2f}")
    print(f"收益率: {metrics['return_rate']:.2f}%")
    print(f"夏普比率: {metrics['sharpe_ratio']}")
    print(f"年化收益率: {metrics['annual_return']:.2f}%")
    print(f"最大回撤: {metrics['max_drawdown']:.2f}%")
    print(f"总交易次数: {metrics['total_trades']}")

    # 验证指标
    print("\n" + "-" * 70)
    print("开始验证指标...")
    print("-" * 70)

    result = validate_metrics(metrics, EXPECTED_METRICS, tolerance=TEST_CONFIG["tolerance"])

    # 打印验证详情
    for key, name in [
        ("final_value", "最终资金"),
        ("total_profit", "总收益"),
        ("return_rate", "收益率"),
        ("sharpe_ratio", "夏普比率"),
        ("annual_return", "年化收益率"),
        ("max_drawdown", "最大回撤"),
        ("total_trades", "总交易次数"),
    ]:
        if key in result["details"]:
            detail = result["details"][key]
            if detail["passed"]:
                status = "✅ PASS"
            elif detail["passed"] is None:
                status = "⚠️  SKIP"
            else:
                status = "❌ FAIL"

            actual = detail.get("actual", "N/A")
            expected = detail.get("expected", "N/A")

            if key == "total_trades":
                print(f"{status} {name}: 实际={actual}, 期望={expected}")
            else:
                error = detail.get("rel_error", detail.get("abs_error", 0))
                print(f"{status} {name}: 实际={actual:.4f}, 期望={expected:.4f}, 误差={error:.6f}")

    # 总结
    print("\n" + "=" * 70)
    if result["passed"]:
        print("✅ 所有测试通过！策略表现符合预期。")
    else:
        print("❌ 测试失败！部分指标不符合预期。")
    print("=" * 70 + "\n")

    # 使用 assert 确保测试通过
    assert result["passed"], "策略测试失败，部分指标不符合预期！"


# ============================================================
# 命令行入口
# ============================================================

if __name__ == "__main__":
    import sys

    # 检查是否使用 pytest 运行
    if "pytest" in sys.modules:
        # 由 pytest 运行，不执行主程序
        pass
    else:
        # 直接运行，执行主测试函数
        print("直接运行测试文件...")
        test_main()
        print("\n如果要使用 pytest 运行所有测试，请执行:")
        print("  pytest test_premium_rate_strategy.py -v")
