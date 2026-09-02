# 量化策略图鉴：1,152 个策略的系统化解读

> 系列编号：总览 · 更新日期：2026-09-02

「量化策略图鉴」是一个连载系列，系统解读本仓库 [tests/functional/strategies](https://github.com/cloudQuant/backtrader/tree/main/tests/functional/strategies) 下的 **1,152 个策略回测**。它们覆盖 **30 个策略分类**——从海龟交易法、Dual Thrust 这样的经典突破，到 HMM 状态切换、卡尔曼滤波配对交易，再到网格马丁、期权到期周效应——每一个都是**可直接运行、带精确断言的完整回测**，而不是伪代码或玩具示例。

这个系列面向三类读者：

- **量化学习者**：把每个分类当作一门"策略小课"，看懂思想、公式与代码实现；
- **Backtrader 用户**：1,152 个即拿即用的策略模板，覆盖从指标调用到期货佣金的工程细节；
- **策略研究者**：每个测试都在 `runonce` / `runnext` 双模式下对拍并断言指标快照，是研究"信号 → 绩效"关系的可靠起点。

## 为什么值得读

市面上介绍策略的文章很多，但大多止步于"思想 + 伪代码"。本系列的每一个策略都有三个硬约束：

1. **真实数据**：XAUUSD（黄金）M15/D1、螺纹钢/玻璃期货分钟线、ORCL 股票日线等真实历史数据；
2. **精确断言**：回测输出的资金曲线终值、夏普比率、最大回撤等指标与基线逐一比对（例如 Donchian 通道测试断言 `final_value` 误差 < 0.01）；
3. **双模式对拍**：每个策略同时在向量化（`runonce=True`）与事件驱动（`runonce=False`）两种引擎模式下运行并要求结果一致——这是引擎正确性的回归保障。

支撑这一切的是 [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 高性能引擎：纯 Python 模式比原版快 46%，C++/pybind11 后端中位加速 128 倍，全仓库 3,200+ 测试守护正确性。

## 系列目录

> 全部 43 篇已发布（2026-09-02 完成系列全部篇目）。

### 趋势跟踪（trend_following，340 个策略）

| # | 标题 | 状态 |
|---|------|------|
| 01 | 均线交叉趋势系统：从金叉死叉到 HMA 变体 | ✅ |
| 02 | 通道与水平位突破：海龟交易法家族 | ✅ |
| 03 | MACD 趋势系统：柱状图、零轴与多周期共振 | ✅ |
| 04 | 趋势强度与跟踪止损：ADX、Supertrend、NRTR | ✅ |
| 05 | 振荡器与 K 线确认的趋势入场 | ✅ |
| 06 | 统计模型与主题趋势：HMM、数字滤波、黄金/宏观/加密 | ✅ |

### 均值回归（mean_reversion，331 个策略）

| # | 标题 | 状态 |
|---|------|------|
| 07 | RSI 超买超卖族：Connors RSI2 与 67 个变体 | ✅ |
| 08 | 振荡器反转：Stochastic、CCI、KDJ、Blau 系列 | ✅ |
| 09 | 布林带与通道回归：squeeze、触带反转 | ✅ |
| 10 | K 线反转形态：三乌鸦、三白兵与指标确认 | ✅ |
| 11 | 经典量化规则：Double 7s、连跌计数、波动率冲击 | ✅ |
| 12 | 结构回归与 MT5 EA 移植：NRTR、Renko、价差收敛 | ✅ |

### 动量（momentum，45 个策略）

| # | 标题 | 状态 |
|---|------|------|
| 13 | 双动量与时序动量：Gary Antonacci 框架与黄金动量变体 | ✅ |
| 14 | 因子动量与轮动：ESG、PCA、低波动叠加 | ✅ |

### 价格形态（price_patterns，44 个策略）

| # | 标题 | 状态 |
|---|------|------|
| 15 | K 线形态交易：吞没、晨星、锤子与振荡器确认 | ✅ |
| 16 | 结构形态与特殊图表：NR7、分形、箱体、Heikin Ashi、Renko | ✅ |

### 综合研究（others，69 个策略）

| # | 标题 | 状态 |
|---|------|------|
| 17 | 日历与事件效应：缺口、隔夜、月初月末 | ✅ |
| 18 | 统计度量与组合策略：Kelly、Hurst、Markowitz、市场宽度 | ✅ |

### 专题分类（每类一篇）

| # | 分类 | 策略数 | 状态 |
|---|------|--------|------|
| 19 | volatility_systems · 波动率系统与状态切换（HMM regime、VIX） | 32 | ✅ |
| 20 | multi_indicator_system · 多指标系统（CCI+MACD+通道共振） | 29 | ✅ |
| 21 | calendar_effects · 日历效应（Sell in May、换月、FOMC） | 28 | ✅ |
| 22 | misc · 杂项精选（TD Sequential、逢跌买入） | 28 | ✅ |
| 23 | asset_allocation · 资产配置（60/40、风险平价、HRP、CPPI） | 23 | ✅ |
| 24 | pairs_trading · 配对交易（金银协整、卡尔曼滤波、Copula） | 22 | ✅ |
| 25 | machine_learning · 机器学习（KMeans、RNN、强化学习、模糊逻辑） | 21 | ✅ |
| 26 | commodity_currency · 商品货币（宏观因子、COT、实际利率） | 21 | ✅ |
| 27 | risk_management · 风险管理（回撤保护、对冲、风险预算） | 19 | ✅ |
| 28 | breakout · 突破策略（Donchian、Dual Thrust、R-Breaker） | 6 | ✅ |
| 29 | volatility · 波动率通道（Keltner、Supertrend、吊灯止损） | 9 | ✅ |
| 30 | multi_indicator · 经典单指标（威廉、KD、TRIX、终极振荡） | 9 | ✅ |
| 31 | grid_trading · 网格交易（均价网格、马丁格尔） | 9 | ✅ |
| 32 | volume_system · 成交量系统（VWMA、Ergodic Tick Volume） | 7 | ✅ |
| 33 | time_session_system · 时段交易（夜盘通道、开盘定价） | 7 | ✅ |
| 34 | time_based · 定时与数据回放（Timer、重采样） | 7 | ✅ |
| 35 | special · 特殊策略（ETF 轮动、套利、多数据源） | 7 | ✅ |
| 36 | rotation · 轮动（月度排名、安全资产切换） | 6 | ✅ |
| 37 | pivot_fibonacci_system · 枢轴与斐波那契 | 6 | ✅ |
| 38 | order_types · 订单类型实战（Bracket、OCO、StopTrail） | 6 | ✅ |
| 39 | options · 期权策略（到期周效应、备兑卖出） | 5 | ✅ |
| 40 | advanced · 高级功能（参数优化、多数据、信号) | 5 | ✅ |
| 41 | sentiment · 情绪策略（恐贪指数、PCR、VIX、BTC 情绪） | 4 | ✅ |
| 42 | carry_trading · 套息交易（利差收割、商品 carry） | 4 | ✅ |
| 43 | forecasting · 预测（ARIMA、Forecast Oscillator） | 3 | ✅ |

## 每篇文章的固定结构

- **分类速览**：本分类全部策略一览表（名称、核心思想、数据）；
- **思想脉络**：这类策略为什么存在，背后的市场假设；
- **代表策略深读**：2-3 个经典策略的完整逻辑拆解，含可运行代码片段；
- **上手运行**：一条 `pytest` 命令复现回测；
- **延伸阅读**：系列内关联文章。

## 快速开始

```bash
git clone https://github.com/cloudQuant/backtrader.git
cd backtrader && pip install -U .

# 运行某个分类的全部策略回测（以 breakout 为例）
pytest tests/functional/strategies/breakout/ -v

# 运行单个策略（runonce/runnext 双模式自动对拍）
pytest tests/functional/strategies/breakout/test_10_r_breaker_strategy.py -v
```

## 相关资源

- 英文版系列：[Strategy Compendium](../en/00-overview.md)
- 项目主仓库：[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader)（高性能引擎）
- 生态：[backtrader-mcp](https://github.com/cloudQuant/backtrader-mcp)（MCP Server）· [backtrader_web](https://github.com/cloudQuant/backtrader_web)（AI for Investor 平台）· [fincore](https://github.com/cloudQuant/fincore)（绩效与风险分析）
- 社区：[中文社区站点](https://aifortrader.cn/) · [中文文档](https://backtrader-zh.readthedocs.io/zh-cn/latest/)

> 风险提示：本系列仅供教育与研究目的。所有回测基于历史数据，算法交易存在重大亏损风险，历史业绩不代表未来表现。
