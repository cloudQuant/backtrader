# NR7、Darvas 箱体与 Heikin Ashi：当价格结构本身成为信号

> 量化策略图鉴 · 第 16 篇 · 分类 `price_patterns`（44 个策略）· 2026-09-02

1960 年，匈牙利裔舞蹈家 Nicolas Darvas 出版了《我如何在股市赚了 200 万》——他在世界各地巡演的间隙，用《巴伦周刊》的报价电报追踪股票，靠"箱体"理论把约 2.5 万美元滚到 200 万美元。他的规则朴素得像舞蹈编排：股价在一个箱子里震荡，突破箱顶就买，跌破箱底就卖。半个多世纪后，"结构先于信号"的思想仍生生不息：Toby Crabel 发现**波幅最窄的那天（NR7）之后往往跟着波动扩张**，Munehisa 式的平滑蜡烛（Heikin Ashi）与 Renko 砖块则干脆重新定义了"一根 K 线"。

本篇拆解 `price_patterns` 分类 44 个策略中的结构与特殊图表家族：NR7 窄幅突破、分形、支撑阻力、Darvas 箱体、三线反转、Heikin Ashi 与自适应 Renko。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| NR7 窄幅突破 | XAUUSD 日线 2008-2025 | 前 6 日最窄波幅日，突破其高低入场，ATR 止损止盈 | `test_0037_nr7_pattern_breakout.py` |
| NR7 价格突破入场 | XAUUSD 日线 | NR7 + 趋势均线过滤的入场变体 | `test_0038_nr7_price_breakout_entry.py` |
| NR7 过滤出场版 | XAUUSD 日线 | NR7 突破加波动率过滤与反向信号出场 | `test_0039_nr7_breakout_filter_exit.py` |
| 支撑阻力交易者 | XAUUSD M15 | 频繁出现的价位视为支撑/阻力，价稳 + MA 多头排列入场 | `test_0040_0195_support_and_resistance_trader.py` |
| 收盘价分形 | XAUUSD M15 | 用收盘价而非高低点定义 5 周期分形，追踪高低点抬升/降低 | `test_0041_0469_close_price_fractals.py` |
| 分形最小距离 | XAUUSD M15 | 峰谷分形间距不足 N 点不交易，防震荡市反手 | `test_0043_0597_fractals_minimum_distance.py` |
| Darvas 箱体系统 | XAUUSD M15+H4 | 箱体颜色状态转换触发多空，固定点数止损止盈 | `test_0044_0853_darvasboxes_system.py` |
| 三线反转 | XAUUSD M15+H12 | 价格突破最近三根折线的极值即翻转趋势 | `test_0014_0923_3linebreak.py` |
| Heikin Ashi 变色 | XAUUSD M15 | 平滑蜡烛颜色翻转即趋势反转，翻转即反手 | `test_0015_1204_heiken_ashi.py` |
| 自适应 Renko | XAUUSD M15+H4 | 砖块尺寸随 ATR/波动自适应，趋势线出现即入场 | `test_0036_1234_adaptive_renko.py` |

## 深读一：NR7 窄幅突破——Crabel 的波动收缩定律

[test_0037_nr7_pattern_breakout.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/price_patterns/test_0037_nr7_pattern_breakout.py) 跑在黄金日线（2008-2025），完整实现了 Crabel 思想。识别 NR7 日只需一行比较：

```python
out['daily_range'] = out['high'] - out['low']
out['min_range_prev6'] = out['daily_range'].shift(1).rolling(window=lookback-1).min()
out['nr7'] = (out['daily_range'] < out['min_range_prev6']).astype(float)
out['breakout_up'] = ((out['nr7'].shift(1) > 0.5) &
                      (out['close'] > out['nr7_high'])).astype(float)
```

风险框架全部以 ATR(14) 计价，另外还有一条时间止损——**窄幅突破赌的是"立刻"扩张，拖过 5 天还没走出来就认错**：

```python
self.stop_loss = self.entry_price - self.p.stop_loss_atr * atr      # 2.5 × ATR
self.take_profit = self.entry_price + self.p.take_profit_atr * atr  # 4.0 × ATR
...
if bars_held >= self.p.time_exit:                                   # 5 根 K 线强制离场
    self.pending_order = self.close()
```

18 年成绩：终值 1,310,862.61（+31.09%），胜率 48.48%，Sharpe 0.46——但最大回撤高达 49.46%。1.6:1 的盈亏比配上接近五成的胜率，期望为正，回撤却是心脏考验：趋势系统的收益分布从来不是正态，是靠少数大波动年份扛起来的。三重出场（止损、止盈、时间）各司其职的写法也值得抄走：止损 2.5 倍 ATR 给容错，止盈 4 倍 ATR 吃足趋势，5 天时限负责把"不扩张的窄幅"尽快扫地出门。

## 深读二：Darvas 箱体——舞蹈家的遗产如何工程化

[test_0044_0853_darvasboxes_system.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/price_patterns/test_0044_0853_darvasboxes_system.py) 是一份"手写"测试（非脚本内联），把 MT5 的 Exp_DarvasBoxesSystem 移植为多周期结构：M15 执行、H4 出信号，箱体识别交给内置指标 `DarvasBoxesSystem`，交易逻辑只读它的颜色状态：

```python
c0 = float(self.ind.color[-sb]) if sb else float(self.ind.color[0])
c1 = float(self.ind.color[-(sb + 1)])
buy_open = c1 > 2.0 and c0 < 3.0 and self.p.buy_pos_open     # 颜色转入绿色区
sell_open = c1 < 2.0 and c0 > 1.0 and self.p.sell_pos_open   # 颜色转入红色区
buy_close = sell_open and self.p.buy_pos_close
sell_close = buy_open and self.p.sell_pos_close
```

出场是固定点数 bracket：止损 1000 点、止盈 2000 点（1:2）。三个月 M15 数据上 11 笔交易**全部做空**（buy_count=0、sell_count=11），3 胜 8 负，终值 999,221.40。一个反直觉的观察：这段行情里箱体系统只认得跌势——结构策略对市场状态的偏食，是回测才看得清的另一面。工程上值得学的是它的双 feed 架构：`cerebro.adddata` 挂两份数据，`self.datas[0]` 下单、`self.datas[1]` 供指标，高周期信号驱动低周期执行的标准写法。`_last_signal_len` 的去重小技巧同样实用：只有信号周期真正走出新 K 线才重新评估颜色，避免同一根 H4 内被 M15 反复触发。

## 深读三：Heikin Ashi——把 K 线重新定义一遍

普通 K 线的影线是噪声的重灾区，Heikin Ashi（平均足）用递推公式把噪声熨平：收盘价取四价均值，开盘价取**前一根 HA 开收的均值**——于是趋势中连续出现无下影的长阳，转折由颜色翻转标出。[test_0015_1204_heiken_ashi.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/price_patterns/test_0015_1204_heiken_ashi.py) 用六行完成递推：

```python
self.ha_close = (o + h + l + c) / 4.0
if self.bar_num == 1:
    self.ha_open = (o + c) / 2.0
else:
    self.ha_open = (self.ha_open + self.ha_close) / 2.0

ha_bullish = self.ha_close > self.ha_open
```

交易规则极简：颜色由阴转阳就平空反手做多，由阳转阴就平多反手做空。三个月 M15 上终值 999,417.30（−0.06%），胜率 34.14%——颜色翻转在低周期太频繁，平滑了 K 线却平滑不了交易成本为零的市场摩擦。**Heikin Ashi 的正确打开方式是当过滤器而非扳机**，用它数"连续同色 K 线"来确认趋势健康度，而不是每次变色都开一枪。

## 其余策略，快速点将

- **收盘价分形**（`test_0041`）：Williams 分形的改良——用收盘价代替高低点找极值，减少影线骗线，配合移动止损与反向信号出场。
- **分形最小距离**（`test_0043`）：峰与谷之间不足 N 点不入场——给分形反转加"最小空间"门槛，专治窄幅震荡里的反复打脸。
- **支撑阻力交易者**（`test_0040`）：统计近期反复出现的价位当支撑/阻力，价格站在频价位上方且快慢 MA 多头排列才买，cheat-on-open 模拟 EA 的开盘入场。
- **三线反转**（`test_0014`）：信号在 H12 高周期生成、M15 执行——结构策略里"高看低做"的又一范例。
- **自适应 Renko**（`test_0036`）：砖块大小随 Wilder ATR 或滚动标准差伸缩，波动大砖变大、噪声自动被吞掉——固定砖 Renko 的现代化改造。

## 一条命令跑起来

```bash
# 整个分类（44 个策略）
pytest tests/functional/strategies/price_patterns/ -v

# 只跑 NR7 突破
pytest tests/functional/strategies/price_patterns/test_0037_nr7_pattern_breakout.py -v
```

内联回归测试在 `runonce=True` 下运行并对终值、交易数、胜率逐项断言；引擎的 runonce/runnext 双模式对拍机制保证同一策略在两种执行模型下结果一致。

## 为什么在这个项目上研究价格结构

结构策略的状态机分支多（建箱、确认、突破、假突破回退），最容易在重构中悄悄变行为。[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 用 1,152 个策略回归测试把每个状态机的输出钉成指标断言基线——你重写 NR7 的 rolling 逻辑，`final_value` 偏离 1.31e+00 的容差就会被抓住。纯 Python 引擎比原版快 46%，C++ 后端（`pip install back-trader-cpp`）中位 128 倍加速，runonce/runnext 双模式对拍再加一层保险——结构可以重构，数字必须纹丝不动。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
