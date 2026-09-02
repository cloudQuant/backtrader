# 成交量系统：VWMA 与 Ergodic Tick Volume 的量价实验

> 量化策略图鉴 · 第 32 篇 · 分类 `volume_system`（7 个策略）· 2026-09-02

"量在价先"——这句华尔街老话是所有成交量分析的起点：价格可以骗人，成交量更难造假，放量的方向往往先于价格的方向。但在外汇和现货黄金市场，这句格言先要打一个补丁：这里**没有中央撮合交易所**，不存在统一的成交量。MT5 平台给出的替代品是 tick volume——每根 K 线内报价跳变的次数。实证研究长期支持一个有趣的结论：tick volume 与真实成交量的相关性非常高，足以承载"量"的角色。于是问题变成：把 tick volume 喂给经典指标，会发生什么？

本篇解读 `tests/functional/strategies/volume_system/` 下的 7 个策略。它们全部移植自真实 MT5 EA，共用一套精密的双周期架构：**M15 K 线执行下单，重采样出的 H4/H6/H8 高周期计算信号**，数据为 XAUUSD（2025-12-03 至 2026-03-10，约 6,129 根 M15，初始资金 100 万美元、零佣金、100 倍乘数）。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| Exp_Volume_Weighted_MACandle | XAUUSD M15 执行 / H4 信号 | 合成"成交量加权 K 线"，颜色翻转即交易 | `test_0001_volume_weighted_macandle.py` |
| Exp_Volume_Weighted_MA_Digit_System | XAUUSD M15 / H4 | 取整 VWMA 高低价通道 + 颜色码突破信号 | `test_0002_volume_weighted_ma_digit_system.py` |
| Exp_Volume_Weighted_MA_StDev | XAUUSD M15 / H4 | VWMA 逐棒变化除以自身标准差，1.5σ/2.5σ 分级动量信号 | `test_0003_volume_weighted_ma_stdev.py` |
| Exp_Volume_Weighted_MA | XAUUSD M15 / H4 | VWMA 斜率翻转变向，固定点数止损止盈 | `test_0004_volume_weighted_ma.py` |
| Exp_Ergodic_Ticks_Volume_OSMA | XAUUSD M15 / H8 | 双重平滑 TVI 的 OSMA 柱拐点 | `test_0005_ergodic_ticks_volume_osma.py` |
| Exp_Ergodic_Ticks_Volume_Indicator | XAUUSD M15 / H6 | Ergodic TVI 与信号线交叉 | `test_0006_ergodic_ticks_volume_indicator.py` |
| Exp_XPVT | XAUUSD M15 / H4 | 价量趋势 PVT 累计线与其 EMA 交叉 | `test_0007_xpvt.py` |

## 深读一：VWMA 斜率——比 MA 多一个"发言权"

普通均线对每根 K 线一视同仁，VWMA 则让**量大的 K 线说话更大声**：分子是 `Σ(price × volume)`，分母是 `Σ(volume)`。放量突破在 VWMA 上留下深印，缩量揉搓则几乎不移动它——这正是 [test_0004_volume_weighted_ma.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/volume_system/test_0004_volume_weighted_ma.py) 用来捕捉拐点的机制，信号是"斜率翻转"而非"价格穿越"：

```python
self.indicator = bt.indicators.VolumeWeightedMAIndicator(self.signal_data, length=self.p.length, ipc=self.p.ipc, use_tick_volume=self.p.use_tick_volume)
```

```python
v0 = self._val(self.indicator.vwma, signal_bar)
v1 = self._val(self.indicator.vwma, signal_bar + 1)
v2 = self._val(self.indicator.vwma, signal_bar + 2)
if v1 < v2:
    if self.p.buy_pos_open and v0 > v1:
        buy_open = True
    if self.p.sell_pos_close:
        sell_close = True
if v1 > v2:
    if self.p.sell_pos_open and v0 < v1:
        sell_open = True
    if self.p.buy_pos_close:
        buy_close = True
```

三根 H4 VWMA 值（`length=12`，tick volume 加权）拼出"先跌后涨"的 V 形才开多，倒 V 形开空；持仓期间由 M15 执行端挂 1,000 点止损、2,000 点止盈。注意 `use_tick_volume=True` 这个开关——MT5 导出里同时存在 tick volume 与 real volume 两列，黄金现货的真实成交量常年为零，这一族 EA 默认全部落在 tick 一侧，回测时搞混数据列是这类移植最容易犯的错。回测 54 笔交易、胜率 42.59%、盈利因子 1.154、终值 1,000,646.80——又是低胜率靠盈亏比吃饭的样本：斜率翻转信号天然滞后，入场价位不占优，靠的是 H4 级别趋势一旦走出来，2,000 点止盈远大于 1,000 点止损的不对称结构。工程上注意 `_last_signal_len` 这类"每根信号 K 线只评估一次"的门闩：双周期架构里没有它，一根 H4 会被 16 根 M15 重复消费，信号全乱。

## 深读二：Ergodic TVI——Blau 的多重平滑哲学

William Blau 在 1990 年代（《Momentum, Direction, and Divergence》）系统阐述了"Ergodic"一族指标：把任何原始量先做**双重指数平滑**滤掉噪声，再构造振荡器。TVI（Tick Volume Index）是他的思想用在 tick volume 上的样子。[test_0006_ergodic_ticks_volume_indicator.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/volume_system/test_0006_ergodic_ticks_volume_indicator.py) 的实现把整条流水线写得很清楚：

```python
up_ticks = (vol + (frame['close'].astype(float) - frame['open'].astype(float)) / point) / 2.0
down_ticks = vol - up_ticks

ema_up = apply_ma(up_ticks, xlength1, xma_method)
ema_down = apply_ma(down_ticks, xlength1, xma_method)
dema_up = apply_ma(ema_up, xlength2, xma_method)
dema_down = apply_ma(ema_down, xlength2, xma_method)

denom = (dema_up + dema_down).replace(0.0, np.nan)
tvi_calculate = 100.0 * (dema_up - dema_down) / denom
tvi = apply_ma(tvi_calculate, xlength3, xma_method)
ema_tvi = apply_ma(tvi, xlength4, xma_method)
ergodic_tvi = apply_ma(ema_tvi, xlength5, xma_method)
ergodic_signal = apply_ma(ergodic_tvi, xlength6, xma_method)
```

第一步最妙：阳线（close>open）的 tick 全记给多方，阴线记给空方，一分为二再各自双重平滑（`xlength1=xlength2=12`）——**tick volume 被升维成了"多空力量对比"**。TVI = 100×(多-空)/(多+空)，再经四道平滑得到 ergodic 线与信号线，交叉即交易。六个 `xlength` 参数对应流水线的六道工序，其中 `xlength3=1` 意味着 TVI 本身不再平滑——Blau 原文里这类旋钮的取舍，正是"平滑越深、信号越钝"这条曲线上的选点问题。H6 信号周期整段窗口只有 236 根 K 线、14 笔交易（8 胜 6 负），盈利因子 2.04、终值 1,005,203.90、最大回撤 0.34%。信号稀疏是高周期+多重平滑的必然代价，换来的是曲线的干净。

## 深读三：XPVT——把"量"乘进"价"的复利账本

PVT（Price-Volume Trend，价量趋势）是最古老的量价指标之一，思路朴素：价格上涨的 K 线把成交量加进账本，下跌则减去，形成一条累计线。[test_0007_xpvt.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/volume_system/test_0007_xpvt.py) 的 `compute_xpvt` 只有一个循环：

```python
for i in range(1, len(out)):
    prev_price = float(price.iloc[i - 1])
    curr_price = float(price.iloc[i])
    vol = float(volume.iloc[i])
    delta = 0.0 if prev_price == 0 else vol * (curr_price - prev_price) / prev_price
    pvt.iloc[i] = pvt.iloc[i - 1] + delta
sign = smooth_series(pvt, xlength, xma_method)
```

每根 H4 K 线贡献 `volume × 价格变化率`——涨 1% 放量，比涨 5% 缩量对账本的推动更大，"量在价先"被写成了一个乘法。信号线是 PVT 的 5 期 EMA，上穿做多、下穿做空。本篇最漂亮的成绩单来自这里：49 笔交易、胜率 48.98%、盈利因子 3.26、终值 1,015,722.30（+1.57%）、最大回撤 0.19%。当然，三个月的黄金数据、零成本假设，都提示这只是基线而非福音——但它至少演示了量价合成线在方向过滤上的潜力。

## 其余四席，快速点将

- **VWMA Candle**（`test_0001`）：把 VWMA 当作合成 K 线的开收盘，给"蜡烛"上色，颜色翻转即反手——VWMA 思想的形态化版本。
- **VWMA Digit System**（`test_0002`）：对 VWMA 高低价取整构成通道，收盘破上/下轨点亮颜色码，处理为突破信号。
- **VWMA StDev**（`test_0003`）：VWMA 的逐棒变化除以其滚动标准差，超 1.5σ/2.5σ 发分级信号——把动量做成了波动率标准化后的 z-score。
- **Ergodic OSMA**（`test_0005`）：与深读二同一套 TVI 流水线，但信号改为 OSMA 柱状图的拐点，跑在 H8 周期——同族指标"信号器"部分的对照件，适合研究把"交叉"换成"拐点"对信号密度与质量的影响。

## 一条命令跑起来

```bash
# 整个分类（7 个策略，固定 runonce=True，断言迁移时捕获的指标基线）
pytest tests/functional/strategies/volume_system/ -v

# 只跑 XPVT
pytest tests/functional/strategies/volume_system/test_0007_xpvt.py -v
```

## 为什么在这个项目上研究成交量系统

量价策略天然依赖双数据流（价格+tick volume）与多周期架构（M15 执行、H4+ 信号），对回测引擎的**数据管道精度**要求极高——重采样的开闭区间、K 线时间戳偏移、信号对齐差一根就全盘失真。[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 恰好以此见长：纯 Python 引擎比原版快 46%，1,152 个策略回归测试把每条流水线的胜率、盈利因子、回撤、SQN 全部钉成断言基线；装上 C++ 后端（`pip install back-trader-cpp`）更可获得中位 128 倍加速，多周期参数组合的扫描从"过夜任务"变成"喝口咖啡"。runonce/runnext 双模式对拍，则确保向量化与事件驱动两条代码路径算出同一根 VWMA。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
