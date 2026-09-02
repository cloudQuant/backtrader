# 结构回归与 MT5 EA 移植：NRTR 自适应包络、Renko 砖块与价差收敛

> 量化策略图鉴 · 第 12 篇 · 分类 `mean_reversion`（约 84 个策略）· 2026-09-02

MQL 社区可能是世界上最大的策略作坊：MT4/MT5 论坛与市场上流传着数以万计的 EA（Expert Advisor），其中不乏构思精巧的结构化反转系统。但它们大多活在一个尴尬的状态——只能用 MT5 自带的策略测试器验证，没有版本控制、没有断言、换个数据就说不清了。

这个仓库做了一件笨重但有价值的事：把 MQL 生态的 EA 成批移植进可验证的 Python 引擎。mean_reversion 分类 331 个测试中，**256 个在文件头标注 `source_ea`**——每个移植都保留原 EA 的参数语义（点值、手数、止损止盈点数），再用 XAUUSD M15 真实数据回测并把结果钉成断言。本篇挑出其中"结构回归"一脉：NRTR 自适应包络、Renko 砖块、时段云带，再配上价差收敛的统计回归两兄弟。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| NRTR_Revers | XAUUSD M15 | ATR(3)×3.0 构造 NRTR 包络，穿越切换多空 | `test_0049_0166_nrtr_revers.py` |
| StepMA_NRTR | XAUUSD M15 执行 + H1 信号 | 波动率自适应步长的阶梯 MA + NRTR 棘轮 | `test_0180_0907_stepma_nrtr.py` |
| Renko_Level_EA | XAUUSD M15 | 30 点固定砖块 Renko 网格，砖向即方向 | `test_0115_0355_renko_level_ea.py` |
| Hans 云带 TM+ | XAUUSD M15 执行 + M30 信号 | 时段高低点 ±100 点构造云带，突破入场 | `test_0054_0177_exp_hans_indicator_cloud_system_tm_plus.py` |
| Hans 云带（原版） | XAUUSD M15 | 同思想的单数据流版本 | `test_0053_0176_exp_hans_indicator_cloud_system.py` |
| BykovTrend ReOpen | XAUUSD M15 执行 + H4 信号 | BykovTrend 信号线翻转 + 重开逻辑 | `test_0158_0733_exp_bykovtrend_reopen.py` |
| 协整价差回归 | XAUUSD D1 2008-2025 | 价差 z-score<-2 买入，\|z\|<0.5 离场 | `test_0009_cointegration_mean_reversion_gold.py` |
| 配对交易（V/MA） | V、MA 股票日线 500 根 | OLS 滚动 z-score ±2.5 配对，0.6/0.4 配资 | `test_63_pairs_trading_strategy.py` |
| 布林带配对 | 双资产日线 | 布林带触轨替代 z-score 阈值 | `test_83_pair_trade_bollinger_strategy.py` |
| Stoch 交叉 EA | XAUUSD H1 | 随机指标交叉的 EA 化实现 | `test_0043_0060_stoch_cross_ea_h1.py` |
| Extreme EA | XAUUSD M15 | 极值反转系统 | `test_0050_0167_extreme_ea.py` |
| RSI_RFTL EA | XAUUSD M15 | RSI + 数字滤波趋势线组合 | `test_0051_0171_rsi_rftl_ea.py` |

## 深读一：NRTR_Revers——会呼吸的反转包络

NRTR（Nick Rypock Trailing Reverse）的核心想法：把"趋势线"做成一条**随波动率呼吸的包络线**，价格穿越就宣布趋势翻转。[test_0049_0166_nrtr_revers.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/mean_reversion/test_0049_0166_nrtr_revers.py) 的状态机：

```python
atr_prev = float(self.atr[-1])
different = float(self.p.coeff_of_volatility) * atr_prev     # ATR(3) × 3.0
reverse_distance = self.p.reverse_pips * self.p.point_size
half_period = max(1, int(round(self.p.atr_period / 2.0)))
close_1 = float(self.data0_feed.close[-1])

if self.trade_state == 'buy':
    low = self._window_low(2, max(1, self.p.atr_period - 1))
    line = low - different                          # NRTR 支撑线 = 窗口低点 - 3×ATR
    low2 = self._window_low(self.p.atr_period - half_period + 1, half_period)
    if (line - close_1 > different) or (low2 - line >= reverse_distance):
        self.trade_state = 'sell'                   # 跌破包络，切换空头状态
```

风控完全保留了 MQL 习惯：**50 点止损 / 1000 点止盈 / 15 点跟踪止损、步长 45 点**（`trailing_stop_pips=15`、`trailing_step_pips=45`），止损与止盈单用 OCO 绑定。注意止损 50 点与止盈 1000 点的悬殊比例——原 EA 的意图是"小止损博大趋势"，但跟踪止损 15 点意味着价格只要回调 15 点就开始挪止损，步长 45 点又要求新止损价至少比旧价优 45 点才值得撤单重挂，三个参数共同决定了离场的节奏。回测很有教育意义：6,129 根 K 线做了 **3,057 笔**交易（本窗口内 buy_count=0、sell_count=3057——状态机只在翻空时进场），胜率 45.6%，终值 900,003.99。15 点跟踪止损 × 15 分钟 K 线，注定了高换手和磨损；把跟踪步长放大十倍会发生什么，正是这套模板留给你的第一个实验。

## 深读二：Hans 云带 TM+——双时间框架与时段结构

[test_0054_0177_exp_hans_indicator_cloud_system_tm_plus.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/mean_reversion/test_0054_0177_exp_hans_indicator_cloud_system_tm_plus.py) 是移植工程的教科书案例：**M15 数据流负责执行，同源数据重采样成 M30 负责信号**，云带来自日内时段结构：

```python
if 4 * 60 <= hour_min < 8 * 60:        # 第一时段 04:00-08:00
    high1 = float(row['high']) if high1 is None else max(high1, float(row['high']))
    low1 = float(row['low']) if low1 is None else min(low1, float(row['low']))
elif 8 * 60 <= hour_min < 12 * 60:     # 第二时段 08:00-12:00
    high2 = float(row['high']) if high2 is None else max(high2, float(row['high']))
    low2 = float(row['low']) if low2 is None else min(low2, float(row['low']))

offset = float(pips_for_entry) * float(point_size)   # 100 点缓冲
if hour_min >= 12 * 60 and high2 is not None and low2 is not None:
    active_upper = high2 + offset      # 午后：云带 = 第二时段高低点 ± 100 点
    active_lower = low2 - offset
elif hour_min >= 8 * 60 and high1 is not None and low1 is not None:
    active_upper = high1 + offset      # 上午：云带 = 第一时段高低点 ± 100 点
    active_lower = low1 - offset
```

收盘突破上轨记为看涨色、跌破下轨记为看跌色，颜色状态翻转即入场，再挂 1,000 点止损 / 2,000 点止盈的 bracket 单，可选 1,500 分钟限时离场（`time_trade=True`）。结果：111 多 + 67 空共 177 笔，终值 995,611。它真正值钱的是**工程骨架**——时区换算（`local_timezone=0` → `dest_timezone=4`）、双数据流对齐、bracket 挂单管理，这些在 MQL 里散落一地的细节，在这里成了一个可拷贝的 Python 模板。

## 深读三：价差收敛两兄弟——z-score 的单资产与双资产版

结构回归的尽头是统计回归：不猜价格结构，直接押"偏离会回来"。单资产版 [test_0009_cointegration_mean_reversion_gold.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/mean_reversion/test_0009_cointegration_mean_reversion_gold.py)：

```python
out['spread_std'] = out['spread'].rolling(window=lookback).std()    # lookback=100
out['zscore'] = (out['spread'] - out['spread_mean']) / out['spread_std']
out['entry_signal'] = (out['zscore'] < -zscore_threshold).astype(float)   # z < -2.0
out['exit_signal'] = (abs(out['zscore']) < 0.5).astype(float)             # 回到 ±0.5 内
```

双资产版 [test_63_pairs_trading_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/mean_reversion/test_63_pairs_trading_strategy.py) 用 Visa/Mastercard 这对经典冤家，OLS 滚动算 z-score：

```python
self.transform = btind.OLS_TransformationN(self.data0, self.data1,
                                           period=self.p.period)   # period=20
self.zscore = self.transform.zscore

if (self.zscore[0] > self.upper_limit) and (self.status != 1):     # z > 2.5 做空价差
    self.sell(data=self.data0, size=(x + self.qty1))
    self.buy(data=self.data1, size=(y + self.qty2))
elif ((self.zscore[0] < self.up_medium and self.zscore[0] > self.low_medium)):
    self.close(self.data0)                                          # |z| < 0.5 平仓
    self.close(self.data1)
# z < lower_limit(-2.5) 的做多价差分支与空头分支完全对称，此处从略
```

配资还有个小聪明：偏离 50 日均线更多的腿分 60% 仓位、另一腿 40%。结果对照很有味道：黄金单资产版 52 笔、胜率 63.46%、终值 1,289,841.82；V/MA 配对版 451 根 K 线终值 99,699.43（10 万起步，微亏，最大回撤仅 1.157%）。另外 test_63 是少数参数化 `runonce=True/False` 双模式对拍的测试——**同一策略在向量化与事件驱动两种引擎下必须给出分毫不差的结果**，这是移植正确性的最终裁判。

## 其余策略，快速点将

- **Renko_Level_EA**（`test_0115`）：30 点固定砖块的 Renko 网格叠在收盘价上，新砖方向即交易方向——2,011 笔、终值 1,000,625.90、夏普 0.68，本组少见的正夏普；砖块化天然过滤了小于 30 点的往返噪声。
- **StepMA_NRTR**（`test_0180`）：H1 信号 + M15 执行，`kv=1.0` 缩放的波动率步长棘轮，114 笔、终值 999,689.90。
- **BykovTrend ReOpen**（`test_0158`）：H4 周期 `risk=3, ssp=9` 的信号线 + M15 执行，信号期内允许反复进场（ReOpen 的含义正在于此），32 笔、终值 995,770。
- **Hans 云带原版**（`test_0053`）：TM+ 的前身，单数据流版本，适合对照"升级款改了什么"——多出来的那条 M30 信号流与时区处理就是主要差异。
- **布林带配对**（`test_0083`）：用布林带触轨替代 z-score 阈值的配对变体，把统计离差换成了通道几何。

## 一条命令跑起来

```bash
# 整个分类（331 个策略）
pytest tests/functional/strategies/mean_reversion/ -v

# 只跑 NRTR_Revers
pytest tests/functional/strategies/mean_reversion/test_0049_0166_nrtr_revers.py -v

# 双模式对拍示例（runonce=True/False 参数化）
pytest tests/functional/strategies/mean_reversion/test_63_pairs_trading_strategy.py -v
```

## 为什么在这个项目上研究 EA 移植

把 256 个 MQL 生态的策略搬进可验证的 Python 引擎，改变的不只是语言：每个移植都获得指标断言基线（终值、胜率、夏普、SQN 逐项锁定）和部分策略的 runonce/runnext 双模式对拍，"我改了一点代码"和"结果变了"从此可以被精确归因。[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 纯 Python 引擎比原版快 46%，1,152 个策略回归测试守护正确性；C++ 后端（`pip install back-trader-cpp`）中位 128 倍加速，让"扫一遍 NRTR 的系数 × 步长"从周末项目变成午休实验。MQL 社区二十年的策略直觉，第一次可以被系统性地证伪——或证实。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
