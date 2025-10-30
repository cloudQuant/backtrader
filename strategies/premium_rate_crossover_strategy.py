#!/usr/bin/env python
# -*- coding: utf-8 -*-
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
import sys
import datetime
import warnings
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import FuncFormatter

import backtrader as bt
import backtrader.indicators as btind

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei']  # 用来正常显示中文标签
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


class PremiumRateCrossoverStrategy(bt.Strategy):
    """
    转股溢价率均线交叉策略
    
    策略逻辑：
    - 使用转股溢价率（convert_premium_rate）计算移动平均线
    - 短期均线（默认10日）上穿长期均线（默认60日）时买入
    - 短期均线下穿长期均线时卖出平仓
    """
    
    params = (
        ('short_period', 10),   # 短期均线周期
        ('long_period', 60),    # 长期均线周期
    )
    
    def log(self, txt, dt=None):
        """日志输出函数"""
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('%s, %s' % (dt.isoformat(), txt))
    
    def __init__(self):
        """初始化策略"""
        # 获取转股溢价率数据线
        self.premium_rate = self.datas[0].convert_premium_rate
        
        # 计算短期和长期移动平均线
        self.sma_short = btind.SimpleMovingAverage(
            self.premium_rate, 
            period=self.p.short_period
        )
        self.sma_long = btind.SimpleMovingAverage(
            self.premium_rate, 
            period=self.p.long_period
        )
        
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
                    f'买入执行, 价格: {order.executed.price:.2f}, '
                    f'成本: {order.executed.value:.2f}, '
                    f'手续费: {order.executed.comm:.2f}'
                )
            elif order.issell():
                self.log(
                    f'卖出执行, 价格: {order.executed.price:.2f}, '
                    f'成本: {order.executed.value:.2f}, '
                    f'手续费: {order.executed.comm:.2f}'
                )
        
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log('订单取消/保证金不足/拒绝')
        
        # 重置订单
        self.order = None
    
    def notify_trade(self, trade):
        """交易通知"""
        if not trade.isclosed:
            return
        
        self.log(
            f'交易盈亏, 毛利: {trade.pnl:.2f}, 净利: {trade.pnlcomm:.2f}'
        )
    
    def next(self):
        """策略核心逻辑"""
        # 如果有未完成的订单，等待
        if self.order:
            return
        
        # 记录当前状态
        current_date = bt.num2date(self.datas[0].datetime[0]).strftime('%Y-%m-%d')
        premium_rate = self.premium_rate[0]
        sma_short = self.sma_short[0]
        sma_long = self.sma_long[0]
        
        # 检查是否已经有仓位
        if not self.position:
            # 没有仓位，检查是否金叉买入
            if self.crossover > 0:
                # 金叉信号：短期均线上穿长期均线
                self.log(
                    f'金叉信号 - 买入, 溢价率: {premium_rate:.2f}%, '
                    f'短期均线: {sma_short:.2f}, 长期均线: {sma_long:.2f}'
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
                    f'死叉信号 - 卖出, 溢价率: {premium_rate:.2f}%, '
                    f'短期均线: {sma_short:.2f}, 长期均线: {sma_long:.2f}'
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
    df.columns = ['BOND_CODE', 'BOND_SYMBOL', 'datetime', 'open', 'high', 'low', 
                  'close', 'volume', 'pure_bond_value', 'convert_value', 
                  'pure_bond_premium_rate', 'convert_premium_rate']
    
    # 转换日期格式
    df['datetime'] = pd.to_datetime(df['datetime'])
    
    # 设置索引
    df = df.set_index('datetime')
    
    # 删除不需要的列
    df = df.drop(['BOND_CODE', 'BOND_SYMBOL'], axis=1)
    
    # 删除缺失值
    df = df.dropna()
    
    # 转换为浮点数
    df = df.astype(float)
    
    print(f"数据加载完成: {len(df)} 条记录")
    print(f"日期范围: {df.index[0]} 至 {df.index[-1]}")
    
    return df


def run_strategy(csv_file='113013.csv', initial_cash=100000.0, commission=0.0003):
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
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe',
                        annualize=True, timeframe=bt.TimeFrame.Days, 
                        riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='time_return')
    
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
    if 'rnorm100' in returns:
        print(f"年化收益率: {returns['rnorm100']:.2f}%")
    print(f"最大回撤: {drawdown['max']['drawdown']:.2f}%")
    
    if 'total' in trades:
        print(f"\n总交易次数: {trades['total'].get('total', 0)}")
        if 'won' in trades['total']:
            print(f"盈利交易: {trades['total']['won']}")
        if 'lost' in trades['total']:
            print(f"亏损交易: {trades['total']['lost']}")
    
    # 获取时间序列收益率用于绘图
    time_return = strat.analyzers.time_return.get_analysis()
    
    # 收集所有关键指标
    total_profit = final_value - initial_cash
    return_rate = (final_value / initial_cash - 1) * 100
    sharpe = sharpe_ratio.get('sharperatio', None)
    annual_ret = returns.get('rnorm100', None)
    max_dd = drawdown['max']['drawdown']
    total_trades = trades['total'].get('total', 0) if 'total' in trades else 0
    
    metrics = {
        'final_value': final_value,
        'total_profit': total_profit,
        'return_rate': return_rate,
        'sharpe_ratio': sharpe,
        'annual_return': annual_ret,
        'max_drawdown': max_dd,
        'total_trades': total_trades,
        'initial_cash': initial_cash
    }
    
    return cerebro, results, time_return, metrics


def plot_results(time_return, initial_cash=100000.0, csv_file='113013.csv', show=False):
    """
    绘制回测结果图表
    
    参数:
        time_return: 时间序列收益率
        initial_cash: 初始资金
        csv_file: 数据文件名（用于标题）
        show: 是否显示图形，默认False（仅保存不显示）
    """
    # 转换为DataFrame
    returns_df = pd.DataFrame(list(time_return.items()), columns=['date', 'return'])
    returns_df['date'] = pd.to_datetime(returns_df['date'])
    returns_df = returns_df.set_index('date')
    
    # 计算累计净值
    returns_df['cumulative'] = (1 + returns_df['return']).cumprod()
    returns_df['value'] = returns_df['cumulative'] * initial_cash
    
    # 创建图形
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))
    
    # 绘制资产曲线
    ax1.plot(returns_df.index, returns_df['value'], linewidth=2, color='#1f77b4')
    ax1.set_title(f'策略资产曲线 - {csv_file}', fontsize=16, pad=20)
    ax1.set_xlabel('日期', fontsize=12)
    ax1.set_ylabel('资产价值 (元)', fontsize=12)
    ax1.grid(True, linestyle='--', alpha=0.6)
    
    # 格式化y轴
    def format_yuan(x, pos):
        if x >= 10000:
            return f'{x/10000:.1f}万'
        return f'{x:.0f}'
    
    ax1.yaxis.set_major_formatter(FuncFormatter(format_yuan))
    
    # 格式化x轴日期
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax1.xaxis.set_major_locator(mdates.YearLocator())
    fig.autofmt_xdate()
    
    # 添加起始和结束点标注
    start_value = returns_df['value'].iloc[0]
    end_value = returns_df['value'].iloc[-1]
    start_date = returns_df.index[0].strftime('%Y-%m-%d')
    end_date = returns_df.index[-1].strftime('%Y-%m-%d')
    
    ax1.annotate(f'起始: {start_date}\n{start_value:.0f}元',
                 xy=(returns_df.index[0], start_value),
                 xytext=(10, 10), textcoords='offset points',
                 bbox=dict(boxstyle='round,pad=0.5', fc='yellow', alpha=0.5))
    
    ax1.annotate(f'结束: {end_date}\n{end_value:.0f}元',
                 xy=(returns_df.index[-1], end_value),
                 xytext=(-100, 10), textcoords='offset points',
                 bbox=dict(boxstyle='round,pad=0.5', fc='yellow', alpha=0.5))
    
    # 绘制累计收益率
    returns_df['cumulative_pct'] = (returns_df['cumulative'] - 1) * 100
    ax2.plot(returns_df.index, returns_df['cumulative_pct'], linewidth=2, color='#2ca02c')
    ax2.set_title('累计收益率', fontsize=16, pad=20)
    ax2.set_xlabel('日期', fontsize=12)
    ax2.set_ylabel('收益率 (%)', fontsize=12)
    ax2.grid(True, linestyle='--', alpha=0.6)
    ax2.axhline(y=0, color='r', linestyle='--', alpha=0.5)
    
    # 格式化x轴日期
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax2.xaxis.set_major_locator(mdates.YearLocator())
    
    # 计算统计信息
    total_return = (end_value / start_value - 1) * 100
    days = (returns_df.index[-1] - returns_df.index[0]).days
    annual_return = ((end_value / start_value) ** (365 / days) - 1) * 100
    
    # 添加统计信息文本框
    stats_text = f"累计收益率: {total_return:.2f}%\n年化收益率: {annual_return:.2f}%\n回测天数: {days}天"
    fig.text(0.15, 0.47, stats_text,
             bbox=dict(facecolor='white', alpha=0.8, edgecolor='gray', boxstyle='round,pad=0.5'))
    
    plt.tight_layout()
    
    # 保存图片
    output_file = csv_file.replace('.csv', '_strategy_result.png')
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"\n图表已保存到: {output_file}")
    
    # 关闭图形以释放内存
    plt.close(fig)
    
    # 仅在show=True时显示图形
    if show:
        plt.show()


def validate_metrics(metrics, expected_metrics, tolerance=0.0001, verbose=True):
    """
    验证回测指标是否符合预期（不抛出异常，仅返回结果）
    
    参数:
        metrics: 实际回测指标字典
        expected_metrics: 期望的指标字典
        tolerance: 允许的相对误差，默认0.0001（万分之一）
        verbose: 是否打印详细信息
    
    返回:
        dict: 包含验证结果的字典
            - 'passed': bool, 是否全部通过
            - 'details': dict, 每个指标的验证详情
    """
    if verbose:
        print("\n" + "=" * 60)
        print("开始验证回测指标")
        print("=" * 60)
    
    # 需要验证的指标列表
    metrics_to_check = [
        ('final_value', '最终资金'),
        ('total_profit', '总收益'),
        ('return_rate', '收益率(%)'),
        ('sharpe_ratio', '夏普比率'),
        ('annual_return', '年化收益率(%)'),
        ('max_drawdown', '最大回撤(%)'),
        ('total_trades', '总交易次数')
    ]
    
    all_passed = True
    details = {}
    
    for key, name in metrics_to_check:
        if key not in expected_metrics:
            continue
            
        actual = metrics.get(key)
        expected = expected_metrics[key]
        
        # 跳过None值
        if actual is None or expected is None:
            if verbose:
                print(f"⚠️  {name}: 跳过验证（值为None）")
            details[key] = {'passed': None, 'reason': 'None value'}
            continue
        
        # 对于交易次数，使用精确匹配
        if key == 'total_trades':
            passed = (actual == expected)
            details[key] = {
                'passed': passed,
                'actual': actual,
                'expected': expected,
                'error': 0 if passed else abs(actual - expected)
            }
            if verbose:
                if passed:
                    print(f"✅ {name}: {actual} (期望: {expected})")
                else:
                    print(f"❌ {name}: {actual} (期望: {expected}) - 不匹配")
            all_passed = all_passed and passed
        else:
            # 对于其他指标，使用相对误差容差
            if expected == 0:
                # 如果期望值为0，使用绝对误差
                diff = abs(actual - expected)
                passed = (diff <= tolerance)
                details[key] = {
                    'passed': passed,
                    'actual': actual,
                    'expected': expected,
                    'abs_error': diff
                }
                if verbose:
                    if passed:
                        print(f"✅ {name}: {actual:.4f} (期望: {expected:.4f}, 差异: {diff:.6f})")
                    else:
                        print(f"❌ {name}: {actual:.4f} (期望: {expected:.4f}, 差异: {diff:.6f}) - 超出容差")
            else:
                # 计算相对误差
                rel_error = abs((actual - expected) / expected)
                passed = (rel_error <= tolerance)
                details[key] = {
                    'passed': passed,
                    'actual': actual,
                    'expected': expected,
                    'rel_error': rel_error
                }
                if verbose:
                    if passed:
                        print(f"✅ {name}: {actual:.4f} (期望: {expected:.4f}, 相对误差: {rel_error:.6f})")
                    else:
                        print(f"❌ {name}: {actual:.4f} (期望: {expected:.4f}, 相对误差: {rel_error:.6f}) - 超出容差")
            all_passed = all_passed and passed
    
    if verbose:
        print("=" * 60)
        if all_passed:
            print("✅ 所有指标验证通过！")
        else:
            print("❌ 部分指标验证失败！")
        print("=" * 60)
    
    return {
        'passed': all_passed,
        'details': details
    }


# ============================================================
# Pytest 测试函数
# ============================================================

# 期望的回测指标（基于历史运行结果）
# 这些值是根据113013可转债在特定时间段内的实际回测结果确定的
# 如果数据或策略发生变化，需要更新这些期望值
EXPECTED_METRICS = {
    'final_value': 104275.8704,     # 最终资金
    'total_profit': 4275.8704,      # 总收益
    'return_rate': 4.27587040,      # 收益率(%)
    'sharpe_ratio': 0.12623860749976154,  # 夏普比率
    'annual_return': 0.7334,        # 年化收益率(%)
    'max_drawdown': 17.413,         # 最大回撤(%)
    'total_trades': 21              # 总交易次数
}

# 测试配置
TEST_CONFIG = {
    'csv_file': '113013.csv',
    'initial_cash': 100000.0,
    'commission': 0.0003,
    'tolerance': 0.0001  # 万分之一
}


def test_strategy_final_value():
    """测试策略最终资金是否符合预期"""
    cerebro, results, time_return, metrics = run_strategy(
        csv_file=TEST_CONFIG['csv_file'],
        initial_cash=TEST_CONFIG['initial_cash'],
        commission=TEST_CONFIG['commission']
    )
    
    expected = EXPECTED_METRICS['final_value']
    actual = metrics['final_value']
    rel_error = abs((actual - expected) / expected)
    
    assert rel_error <= TEST_CONFIG['tolerance'], \
        f"最终资金不符合预期: 实际={actual:.4f}, 期望={expected:.4f}, 相对误差={rel_error:.6f}"


def test_strategy_total_profit():
    """测试策略总收益是否符合预期"""
    cerebro, results, time_return, metrics = run_strategy(
        csv_file=TEST_CONFIG['csv_file'],
        initial_cash=TEST_CONFIG['initial_cash'],
        commission=TEST_CONFIG['commission']
    )
    
    expected = EXPECTED_METRICS['total_profit']
    actual = metrics['total_profit']
    rel_error = abs((actual - expected) / expected)
    
    assert rel_error <= TEST_CONFIG['tolerance'], \
        f"总收益不符合预期: 实际={actual:.4f}, 期望={expected:.4f}, 相对误差={rel_error:.6f}"


def test_strategy_return_rate():
    """测试策略收益率是否符合预期"""
    cerebro, results, time_return, metrics = run_strategy(
        csv_file=TEST_CONFIG['csv_file'],
        initial_cash=TEST_CONFIG['initial_cash'],
        commission=TEST_CONFIG['commission']
    )
    
    expected = EXPECTED_METRICS['return_rate']
    actual = metrics['return_rate']
    rel_error = abs((actual - expected) / expected)
    
    assert rel_error <= TEST_CONFIG['tolerance'], \
        f"收益率不符合预期: 实际={actual:.4f}%, 期望={expected:.4f}%, 相对误差={rel_error:.6f}"


def test_strategy_sharpe_ratio():
    """测试策略夏普比率是否符合预期"""
    cerebro, results, time_return, metrics = run_strategy(
        csv_file=TEST_CONFIG['csv_file'],
        initial_cash=TEST_CONFIG['initial_cash'],
        commission=TEST_CONFIG['commission']
    )
    
    expected = EXPECTED_METRICS['sharpe_ratio']
    actual = metrics['sharpe_ratio']
    
    # 夏普比率可能为None
    assert actual is not None, "夏普比率不应为None"
    
    rel_error = abs((actual - expected) / expected)
    
    assert rel_error <= TEST_CONFIG['tolerance'], \
        f"夏普比率不符合预期: 实际={actual:.4f}, 期望={expected:.4f}, 相对误差={rel_error:.6f}"


def test_strategy_annual_return():
    """测试策略年化收益率是否符合预期"""
    cerebro, results, time_return, metrics = run_strategy(
        csv_file=TEST_CONFIG['csv_file'],
        initial_cash=TEST_CONFIG['initial_cash'],
        commission=TEST_CONFIG['commission']
    )
    
    expected = EXPECTED_METRICS['annual_return']
    actual = metrics['annual_return']
    
    # 年化收益率可能为None
    assert actual is not None, "年化收益率不应为None"
    
    rel_error = abs((actual - expected) / expected)
    
    assert rel_error <= TEST_CONFIG['tolerance'], \
        f"年化收益率不符合预期: 实际={actual:.4f}%, 期望={expected:.4f}%, 相对误差={rel_error:.6f}"


def test_strategy_max_drawdown():
    """测试策略最大回撤是否符合预期"""
    cerebro, results, time_return, metrics = run_strategy(
        csv_file=TEST_CONFIG['csv_file'],
        initial_cash=TEST_CONFIG['initial_cash'],
        commission=TEST_CONFIG['commission']
    )
    
    expected = EXPECTED_METRICS['max_drawdown']
    actual = metrics['max_drawdown']
    rel_error = abs((actual - expected) / expected)
    
    assert rel_error <= TEST_CONFIG['tolerance'], \
        f"最大回撤不符合预期: 实际={actual:.4f}%, 期望={expected:.4f}%, 相对误差={rel_error:.6f}"


def test_strategy_total_trades():
    """测试策略总交易次数是否符合预期"""
    cerebro, results, time_return, metrics = run_strategy(
        csv_file=TEST_CONFIG['csv_file'],
        initial_cash=TEST_CONFIG['initial_cash'],
        commission=TEST_CONFIG['commission']
    )
    
    expected = EXPECTED_METRICS['total_trades']
    actual = metrics['total_trades']
    
    assert actual == expected, \
        f"总交易次数不符合预期: 实际={actual}, 期望={expected}"


def test_strategy_all_metrics():
    """测试策略所有指标是否符合预期（综合测试）"""
    cerebro, results, time_return, metrics = run_strategy(
        csv_file=TEST_CONFIG['csv_file'],
        initial_cash=TEST_CONFIG['initial_cash'],
        commission=TEST_CONFIG['commission']
    )
    
    # 使用 validate_metrics 进行验证
    result = validate_metrics(
        metrics, 
        EXPECTED_METRICS, 
        tolerance=TEST_CONFIG['tolerance'],
        verbose=False  # 在pytest中不显示详细信息
    )
    
    # 使用assert断言
    assert result['passed'], \
        f"策略指标验证失败，详情: {result['details']}"


def test_strategy_metrics_not_none():
    """测试策略关键指标不为None"""
    cerebro, results, time_return, metrics = run_strategy(
        csv_file=TEST_CONFIG['csv_file'],
        initial_cash=TEST_CONFIG['initial_cash'],
        commission=TEST_CONFIG['commission']
    )
    
    # 检查关键指标不为None
    assert metrics['final_value'] is not None, "最终资金不应为None"
    assert metrics['total_profit'] is not None, "总收益不应为None"
    assert metrics['return_rate'] is not None, "收益率不应为None"
    assert metrics['max_drawdown'] is not None, "最大回撤不应为None"
    assert metrics['total_trades'] is not None, "总交易次数不应为None"


def test_strategy_positive_metrics():
    """测试策略关键指标的合理性"""
    cerebro, results, time_return, metrics = run_strategy(
        csv_file=TEST_CONFIG['csv_file'],
        initial_cash=TEST_CONFIG['initial_cash'],
        commission=TEST_CONFIG['commission']
    )
    
    # 检查指标的合理性
    assert metrics['final_value'] > 0, "最终资金应大于0"
    assert metrics['max_drawdown'] >= 0, "最大回撤应大于等于0"
    assert metrics['max_drawdown'] <= 100, "最大回撤应小于等于100%"
    assert metrics['total_trades'] >= 0, "交易次数应大于等于0"
    
    # 检查收益率的一致性
    expected_return = (metrics['final_value'] / metrics['initial_cash'] - 1) * 100
    assert abs(metrics['return_rate'] - expected_return) < 0.01, \
        f"收益率计算不一致: {metrics['return_rate']:.4f} vs {expected_return:.4f}"


if __name__ == "__main__":
    # 配置参数
    CSV_FILE = TEST_CONFIG['csv_file']
    INITIAL_CASH = TEST_CONFIG['initial_cash']
    COMMISSION = TEST_CONFIG['commission']
    
    # 运行回测
    cerebro, results, time_return, metrics = run_strategy(
        csv_file=CSV_FILE,
        initial_cash=INITIAL_CASH,
        commission=COMMISSION
    )
    
    # 绘制结果（不显示，仅保存）
    print("\n正在生成图表...")
    plot_results(time_return, initial_cash=INITIAL_CASH, csv_file=CSV_FILE, show=False)
    
    print("\n" + "=" * 60)
    print("回测完成")
    print("=" * 60)
    
    # 执行验证测试（显示详细信息）
    result = validate_metrics(metrics, EXPECTED_METRICS, tolerance=TEST_CONFIG['tolerance'], verbose=True)
    
    # 使用assert确保测试通过
    assert result['passed'], "回测指标验证失败！"

