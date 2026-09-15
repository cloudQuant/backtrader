# 特殊策略：ETF 轮动、跨市场套利，与那些"不属于任何流派"的实战代码

> 量化策略图鉴 · 第 35 篇 · 分类 `special`（7 个策略）· 2026-09-02

策略教科书喜欢按流派分章：趋势、均值回归、动量……但真实的交易世界里，大量策略根本无法归档——上证 50 ETF 和创业板 ETF 之间的二选一、国债期货近月与远月的价差、可转债的"双低"打分。它们共享的不是某个信号公式，而是一种工程能力：**同时喂多份数据、让它们对齐、在它们之间做相对价值的判断**。

本篇解读 `tests/functional/strategies/special/` 下的 7 个"不合群"策略。这一类的看点不在指标，而在数据工程：两只上市日期不同的 ETF 怎么对齐？几十个可转债怎么按日打分排名？期货合约到期了怎么把仓位滚到新主力合约上？每个文件都是一份可以抄走改用的答案。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| ETF 轮动 | 上证 50 ETF + 创业板 ETF 日线 | 价格/均线动量比率择强持有，双双走弱则空仓 | `test_18_etf_rotation_strategy.py` |
| 国债期货跨月套利 | 中金所 T 系列合约日线 | 近远月价差突破阈值开仓、回归平仓、自动移仓 | `test_20_arbitrage_strategy.py` |
| 可转债双低轮动 | 多只可转债日线（扩展字段） | 价格 + 转股溢价率双因子打分，月度再平衡 | `test_02_multi_extend_data.py` |
| 转股溢价率交叉 | 可转债 113013 日线 | 扩展数据线上的溢价率 SMA(10/60) 交叉 | `test_01_premium_rate_strategy.py` |
| 多源均线 | 30 只可转债日线 | 逐券 60 日均线多空、等权配置 | `test_04_simple_ma_multi_data.py` |
| Fei A'li 四价改进版 | 螺纹钢 RB889 分钟线 | 布林(200,2) + 昨日高低突破的日内双向 | `test_13_fei_strategy.py` |
| Hans123（均线过滤版） | 螺纹钢 RB889 分钟线 | 开盘前 2 根 K 线高低点为突破区间，200 均线滤网 | `test_14_hanse123_strategy.py` |

## 深读一：ETF 轮动——中国版大小盘二选一

A 股有一个经久不衰的风格现象：大盘蓝筹与中小成长极少同时领涨，风格切换的节奏却极难提前判断。与其预测，不如跟随——[test_18_etf_rotation_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/special/test_18_etf_rotation_strategy.py) 用 20 日均线把两只 ETF 的"相对强弱"变成一个可以比较的数字：

```python
# If both ETFs are below moving averages, close all positions
if sz_close < self.sz_ma[0] and cy_close < self.cy_ma[0]:
    if self.sz_pos > 0:
        self.close(sz_data)
    if self.cy_pos > 0:
        self.close(cy_data)

# If at least one ETF is above its moving average
if sz_close > self.sz_ma[0] or cy_close > self.cy_ma[0]:
    # If SSE 50 momentum indicator is larger
    if sz_close / self.sz_ma[0] > cy_close / self.cy_ma[0]:
        if self.sz_pos == 0 and self.cy_pos == 0:
            total_value = self.broker.get_value()
            lots = int(0.95 * total_value / sz_close)
            self.buy(sz_data, size=lots)
```

三个设计细节值得抄：其一，比较的不是价格而是 `close/MA` 比率——动量被归一化，两只价格量级不同的 ETF 才可比；其二，"双双低于均线则全平"给了策略一个拒绝参赛的选项，轮动策略最怕的就是两边都是下跌趋势时被迫二选一；其三，仓位用 `int(0.95 * total_value / price)` 现金公式而不是固定手数，资金曲线才能复利。回测基线（2011-09-20 起、万分之二佣金、5 万本金）：2,600 根 bar、266 次买入、265 笔交易、年化 16.19%、最大回撤 32.03%、终值 235,146.29。收益不菲，但三成回撤提醒你：风格轮动从不温柔。

## 深读二：国债期货跨月套利——理想与现实的一课

教科书里的跨期套利干净得像物理题：近远月价差高于持有成本，卖近买远，坐等收敛。[test_20_arbitrage_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/special/test_20_arbitrage_strategy.py) 把它做成了完整的工程实现——包括最难的部分，移仓：

```python
# Open position
if self.market_position == 0:
    # Open long
    if near_data.close[0] - far_data.close[0] < self.p.spread_low:
        self.buy(near_data, size=1)
        self.sell(far_data, size=1)
        self.market_position = 1
        self.holding_contract_name = [near_data, far_data]
    # Open short
    if near_data.close[0] - far_data.close[0] > self.p.spread_high:
        self.sell(near_data, size=1)
        self.buy(far_data, size=1)
        self.market_position = -1
        self.holding_contract_name = [near_data, far_data]
```

参数 `spread_low=0.06、spread_high=0.52` 定义价差通道，突破即开、回归即平。工程上真正值钱的是 `get_near_far_data()`：每根 bar 按持仓量排序找出当日最活跃的两个合约，一旦主力换月，自动平旧仓、按原方向开新仓——跨月套利的持仓寿命必然跨越主力切换日，没有移仓逻辑的套利回测都是玩具。然后是诚实的部分：T 品种 1,990 根 bar、86 笔交易跑完，夏普 **-2.24**、终值 918,003.89——这套固定阈值参数在样本内是亏钱的。价差不会无条件回归，这条断言基线比任何盈利曲线都有教育意义。

## 深读三：可转债双低——扩展数据线上的月度排名

可转债是中国市场少有的"条款游戏场"，"双低策略"（低价 + 低溢价率）是其中流传最广的打法。[test_02_multi_extend_data.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/special/test_02_multi_extend_data.py) 先教框架认识新字段——把纯债价值、转股价值、两个溢价率注册成 data line：

```python
df["close_score"] = df["close"].rank(method="average")
df["rate_score"] = df["rate"].rank(method="average")
df["total_score"] = (
    df["close_score"] * self.p.first_factor_weight
    + df["rate_score"] * self.p.second_factor_weight
)
df = df.sort_values(by=["total_score", "data_name"], ascending=[False, True])
```

价格升序排名 + 溢价率升序排名，各占 50% 权重，合成分数取前 `hold_percent=20` 名等权买入；每根 bar 检查"当月最后一个交易日"触发调仓，过期订单自动撤销。注意排名用的是 `rank()` 而不是原始值——可转债的价格和溢价率量纲迥异，排名化是因子合成的第一课。基线同样诚实：1,300 根 bar、89 笔交易、夏普 -2.97、最大回撤 4.03%——低回撤、负收益，恰是"躲进债性但没吃到趋势"的典型形态。同一套扩展字段还被 `test_01`（单券溢价率 10/60 交叉，1,384 根、21 笔、终值 104,275.87）和 `test_04`（30 只券逐券 60 日均线、4,434 根、460 笔、终值 14,535,803.03）复用，三份文件合起来就是一套"自定义数据字段从声明到使用"的完整教程。

## 其余两席，快速点将

- **Fei A'li 四价改进版**（`test_13`）：布林(200,2) 上破 + 中轨向上 + 破昨日高则做多（反向做空对称），14:55 强平。19,801 根螺纹钢分钟线跑出夏普 -2.42、终值 805,620.92——裸突破在震荡品种上的代价清单。
- **Hans123 均线过滤版**（`test_14`）：开盘前 2 根 K 线的高低点构成当日突破区间，再加 200 均线方向滤网。19,801 根、235 笔、终值 958,610.35——同样从 100 万起步，亏损不到 Fei A'li 的四分之一，一个滤网的价值量化得清清楚楚。

## 一条命令跑起来

```bash
# 整个分类（7 个策略，runonce/runnext 双模式自动对拍）
pytest tests/functional/strategies/special/ -v

# 只跑 ETF 轮动
pytest tests/functional/strategies/special/test_18_etf_rotation_strategy.py -v
```

## 为什么在这个项目上研究多数据源策略

多数据源策略是数据对齐 bug 的重灾区：两个 feed 的日期差一天、指标 warm-up 少算一根、多券仓位互相踩踏，都会悄悄改变结果。[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 把这 7 个多数据源场景全部固化进 1,152 个策略回归测试，runonce/runnext 双模式对拍、逐指标断言基线，任何引擎改动若碰歪了多数据时序都会立刻报警。纯 Python 引擎比原版快 46%，C++ 后端（`pip install back-trader-cpp`）中位 128 倍加速，让"20 只券 × 5 年 × 双模式"这种规模的对拍也能分钟级跑完。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
