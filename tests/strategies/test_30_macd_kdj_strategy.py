"""MACDKDJ MACD+KDJ策略测试用例

使用上证股票数据 sh600000.csv 测试MACD+KDJ组合策略
- 使用 GenericCSVData 加载本地数据文件
- 通过 self.datas[0] 规范访问数据

参考来源: backtrader-example/strategies/macdkdj.py
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os
from pathlib import Path

import pandas as pd
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """根据脚本所在目录定位数据文件，避免相对路径读取失败"""
    search_paths = [
        BASE_DIR / filename,
        BASE_DIR.parent / filename,
        BASE_DIR.parent.parent / filename,
        BASE_DIR.parent.parent / "tests" / "datas" / filename,
    ]

    data_dir = os.environ.get("BACKTRADER_DATA_DIR")
    if data_dir:
        search_paths.append(Path(data_dir) / filename)

    for candidate in search_paths:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(f"未找到数据文件: {filename}")


class KDJ(bt.Indicator):
    """KDJ 指标"""
    lines = ('K', 'D', 'J')

    params = (
        ('period', 9),
        ('period_dfast', 3),
        ('period_dslow', 3),
    )

    def __init__(self):
        self.kd = bt.indicators.StochasticFull(
            self.data,
            period=self.p.period,
            period_dfast=self.p.period_dfast,
            period_dslow=self.p.period_dslow,
        )
        self.l.K = self.kd.percD
        self.l.D = self.kd.percDSlow
        self.l.J = self.K * 3 - self.D * 2


class MACDKDJStrategy(bt.Strategy):
    """MACDKDJ MACD+KDJ策略

    策略逻辑：
    - MACD金叉 -> 买入
    - KDJ死叉 -> 卖出
    - MACD金叉平空，KDJ死叉平多
    
    使用数据：
    - datas[0]: 股票价格数据
    """

    params = (
        ('macd_fast_period', 12),
        ('macd_slow_period', 26),
        ('macd_signal_period', 9),
        ('kdj_fast_period', 9),
        ('kdj_slow_period', 3),
    )

    def log(self, txt, dt=None, force=False):
        """日志输出功能"""
        if not force:
            return
        dt = dt or self.datas[0].datetime.datetime(0)
        print(f"{dt.isoformat()}, {txt}")

    def __init__(self):
        # 记录统计数据
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.sum_profit = 0.0
        self.win_count = 0
        self.loss_count = 0
        self.trade_count = 0

        # 获取数据引用
        self.data0 = self.datas[0]

        # MACD指标
        self.macd = bt.indicators.MACD(
            self.data0,
            period_me1=self.p.macd_fast_period,
            period_me2=self.p.macd_slow_period,
            period_signal=self.p.macd_signal_period
        )
        # KDJ指标
        self.kdj = KDJ(
            self.data0,
            period=self.p.kdj_fast_period,
            period_dfast=self.p.kdj_slow_period,
            period_dslow=self.p.kdj_slow_period
        )

        # 交易状态
        self.marketposition = 0

    def notify_trade(self, trade):
        """交易完成通知"""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnl > 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.sum_profit += trade.pnl

    def next(self):
        self.bar_num += 1
        data = self.data0

        # MACD金叉条件
        macd_golden_cross = (self.macd.macd[0] > self.macd.signal[0] and 
                            self.macd.macd[-1] < self.macd.signal[-1])
        # KDJ死叉条件
        kdj_death_cross = (self.kdj.K[0] < self.kdj.D[0] and 
                          self.kdj.K[-1] > self.kdj.D[-1])

        if self.marketposition == 0:
            # MACD金叉买入
            if macd_golden_cross:
                size = int(self.broker.getcash() / data.close[0])
                if size > 0:
                    self.buy(size=size)
                    self.marketposition = 1
                    self.buy_count += 1
            # KDJ死叉卖出
            elif kdj_death_cross:
                size = int(self.broker.getcash() / data.close[0])
                if size > 0:
                    self.sell(size=size)
                    self.marketposition = -1
                    self.sell_count += 1
        elif self.marketposition == -1:
            # 空头：MACD金叉平仓
            if macd_golden_cross:
                self.close()
                self.marketposition = 0
                self.buy_count += 1
        elif self.marketposition == 1:
            # 多头：KDJ死叉平仓
            if kdj_death_cross:
                self.close()
                self.marketposition = 0
                self.sell_count += 1

    def stop(self):
        """策略结束时输出统计"""
        total_trades = self.win_count + self.loss_count
        win_rate = (self.win_count / total_trades * 100) if total_trades > 0 else 0
        self.log(
            f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}, "
            f"wins={self.win_count}, losses={self.loss_count}, win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}",
            force=True
        )


def test_macd_kdj_strategy():
    """测试 MACDKDJ MACD+KDJ策略"""
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("正在加载上证股票数据...")
    data_path = resolve_data_path("sh600000.csv")
    df = pd.read_csv(data_path)
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.sort_values('datetime')
    df = df.set_index('datetime')
    df = df[(df.index >= '2000-01-01') & (df.index <= '2022-12-31')]
    df = df[df['close'] > 0]
    
    df = df[['open', 'high', 'low', 'close', 'volume']]
    
    data_feed = bt.feeds.PandasData(
        dataname=df,
        datetime=None,
        open=0,
        high=1,
        low=2,
        close=3,
        volume=4,
        openinterest=-1,
    )
    cerebro.adddata(data_feed, name="SH600000")

    cerebro.addstrategy(
        MACDKDJStrategy,
        macd_fast_period=12,
        macd_slow_period=26,
        macd_signal_period=9,
        kdj_fast_period=9,
        kdj_slow_period=3,
    )

    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="my_value")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade_analyzer")

    print("开始运行回测...")
    results = cerebro.run()

    strat = results[0]
    sharpe_ratio = strat.analyzers.my_sharpe.get_analysis().get("sharperatio")
    annual_return = strat.analyzers.my_returns.get_analysis().get("rnorm")
    drawdown_info = strat.analyzers.my_drawdown.get_analysis()
    max_drawdown = drawdown_info["max"]["drawdown"] / 100 if drawdown_info["max"]["drawdown"] else 0
    trade_analysis = strat.analyzers.my_trade_analyzer.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("total", 0)
    final_value = cerebro.broker.getvalue()

    print("\n" + "=" * 50)
    print("MACDKDJ MACD+KDJ策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  win_count: {strat.win_count}")
    print(f"  loss_count: {strat.loss_count}")
    print(f"  sum_profit: {strat.sum_profit:.2f}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    assert strat.bar_num == 5382, f"Expected bar_num=5382, got {strat.bar_num}"
    assert strat.buy_count == 215, f"Expected buy_count=215, got {strat.buy_count}"
    assert strat.sell_count == 216, f"Expected sell_count=216, got {strat.sell_count}"
    assert total_trades == 212, f"Expected total_trades=212, got {total_trades}"
    assert abs(final_value - 5870.49) < 0.01, f"Expected final_value=5870.49, got {final_value}"
    assert abs(sharpe_ratio - (-0.12656086550315188)) < 1e-6, f"Expected sharpe_ratio=-0.12656086550315188, got {sharpe_ratio}"
    assert abs(annual_return - (-0.12361020751082702)) < 1e-6, f"Expected annual_return=-0.12361020751082702, got {annual_return}"
    assert abs(max_drawdown - 0.9863327709363255) < 1e-6, f"Expected max_drawdown=0.9863327709363255, got {max_drawdown}"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("MACDKDJ MACD+KDJ策略测试")
    print("=" * 60)
    test_macd_kdj_strategy()
