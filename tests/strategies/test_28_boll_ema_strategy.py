"""BollEMA 布林带+EMA策略测试用例

使用上证股票数据 sh600000.csv 测试布林带+EMA组合策略
- 使用 GenericCSVData 加载本地数据文件
- 通过 self.datas[0] 规范访问数据

参考来源: backtrader-example/strategies/bollema.py
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


class BollEMAStrategy(bt.Strategy):
    """BollEMA 布林带+EMA策略

    策略逻辑：
    - 价格突破上轨 + EMA > 中轨 + 前3根K线在中轨之上 -> 开多
    - 价格突破下轨 + EMA < 中轨 + 前3根K线在中轨之下 -> 开空
    - 止损或EMA穿越中轨时平仓
    
    使用数据：
    - datas[0]: 股票价格数据
    """

    params = (
        ("period_boll", 136),
        ("period_ema", 99),
        ("boll_diff", 0.5),    # 布林带宽度阈值
        ("price_diff", 0.3),   # 止损价差
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

        # 布林带指标
        self.boll = bt.indicators.BollingerBands(self.data0, period=self.p.period_boll)
        # EMA指标
        self.ema = bt.indicators.ExponentialMovingAverage(self.data0.close, period=self.p.period_ema)

        # 交易状态
        self.marketposition = 0
        self.last_price = 0

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

    def notify_order(self, order):
        """订单状态通知"""
        if order.status == order.Completed:
            self.last_price = order.executed.price

    def gt_last_mid(self):
        """前3根K线收盘价在中轨之上"""
        data = self.data0
        return (data.close[-1] > self.boll.mid[-1] and 
                data.close[-2] > self.boll.mid[-2] and 
                data.close[-3] > self.boll.mid[-3])

    def lt_last_mid(self):
        """前3根K线收盘价在中轨之下"""
        data = self.data0
        return (data.close[-1] < self.boll.mid[-1] and 
                data.close[-2] < self.boll.mid[-2] and 
                data.close[-3] < self.boll.mid[-3])

    def close_gt_up(self):
        """收盘价连续高于上轨"""
        data = self.data0
        return data.close[0] > self.boll.top[0] and data.close[-1] > self.boll.top[-1]

    def close_lt_dn(self):
        """收盘价连续低于下轨"""
        data = self.data0
        return data.close[0] < self.boll.bot[0] and data.close[-1] < self.boll.bot[-1]

    def next(self):
        self.bar_num += 1

        data = self.data0
        up = self.boll.top[0]
        mid = self.boll.mid[0]
        dn = self.boll.bot[0]
        ema = self.ema[0]
        diff = up - dn

        if self.marketposition == 0:
            # 开多条件
            if self.close_gt_up() and ema > mid and self.gt_last_mid() and diff > self.p.boll_diff:
                size = int(self.broker.getcash() / data.close[0])
                if size > 0:
                    self.buy(data, size=size)
                    self.marketposition = 1
                    self.buy_count += 1
            # 开空条件
            if self.close_lt_dn() and ema < mid and self.lt_last_mid() and diff > self.p.boll_diff:
                size = int(self.broker.getcash() / data.close[0])
                if size > 0:
                    self.sell(data, size=size)
                    self.marketposition = -1
                    self.sell_count += 1
        elif self.marketposition == 1:
            # 多头止损或EMA<=中轨平仓
            if self.last_price - data.close[0] > self.p.price_diff or ema <= mid:
                self.close()
                self.marketposition = 0
                self.sell_count += 1
        elif self.marketposition == -1:
            # 空头止损或EMA>=中轨平仓
            if data.close[0] - self.last_price > self.p.price_diff or ema >= mid:
                self.close()
                self.marketposition = 0
                self.buy_count += 1

    def stop(self):
        """策略结束时输出统计"""
        total_trades = self.win_count + self.loss_count
        win_rate = (self.win_count / total_trades * 100) if total_trades > 0 else 0
        self.log(
            f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}, "
            f"wins={self.win_count}, losses={self.loss_count}, win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}",
            force=True
        )


def test_boll_ema_strategy():
    """测试 BollEMA 布林带+EMA策略"""
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

    cerebro.addstrategy(BollEMAStrategy, period_boll=136, period_ema=99, boll_diff=0.5, price_diff=0.3)

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
    print("BollEMA 布林带+EMA策略回测结果:")
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

    assert strat.bar_num == 5280
    assert strat.buy_count == 43, f"Expected buy_count=43, got {strat.buy_count}"
    assert strat.sell_count == 44, f"Expected sell_count=44, got {strat.sell_count}"
    assert strat.win_count == 10, f"Expected win_count=10, got {strat.win_count}"
    assert strat.loss_count == 26, f"Expected loss_count=26, got {strat.loss_count}"
    assert total_trades == 37, f"Expected total_trades=37, got {total_trades}"
    assert abs(final_value - 705655.57) <1e-2,  f"Expected final_value=705655.57, got {final_value}"
    assert abs(sharpe_ratio-0.33646909650176043)<1e-6, f"sharpe_ratio={sharpe_ratio} out of range"
    assert abs(annual_return-0.09519461079565394)<1e-6, f"annual_return={annual_return} out of range"
    assert abs(max_drawdown-0.4537757234136652)<1e-6, f"max_drawdown={max_drawdown} out of range"

    print("\n测试通过!")



if __name__ == "__main__":
    print("=" * 60)
    print("BollEMA 布林带+EMA策略测试")
    print("=" * 60)
    test_boll_ema_strategy()
