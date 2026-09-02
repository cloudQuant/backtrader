# K 线反转形态：三只乌鸦、三白兵，与一场四种确认器的对照实验

> 量化策略图鉴 · 第 10 篇 · 分类 `mean_reversion`（约 14 个策略）· 2026-09-02

蜡烛图是十八世纪日本大米市场商人本间宗久一族的发明，"三只乌鸦""三白兵"这些名字在酒田战法里已经躺了两百多年。1991 年 Steve Nison 的《Japanese Candlestick Charting Techniques》把它们带进西方，从此每个看盘软件都会画出锤子线和吞没形态。

但形态本身几乎不构成优势——这是反直觉的第二层：**真正值得研究的变量是"确认器"**。三根长阳线之后追多，可能是趋势的延续，也可能是衰竭的尾声；差别往往取决于你用什么指标来"盖章"。本仓库恰好藏着一套天然的对照组：[test_0225](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/mean_reversion/test_0225_1343_three_crows_soldiers_rsi.py) 到 [test_0228](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/mean_reversion/test_0228_1346_three_crows_soldiers_stoch.py) 四个测试，**同一份数据、同一个形态检测器，只换确认器**（RSI / MFI / CCI / Stochastic），其余一字不差。这是研究"哪个确认指标更好"能找到的最干净的实验设计。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| 三乌鸦/三白兵 + RSI | XAUUSD M15 | 三白兵且 RSI(37)<40 买，三乌鸦且 RSI>60 卖 | `test_0225_1343_three_crows_soldiers_rsi.py` |
| 三乌鸦/三白兵 + MFI | XAUUSD M15 | 同上，换成成交量加权的 MFI(37)，阈值 40/60 | `test_0226_1344_three_crows_soldiers_mfi.py` |
| 三乌鸦/三白兵 + CCI | XAUUSD M15 | CCI(37)<-50 买、>50 卖，±80 穿越离场 | `test_0227_1345_three_crows_soldiers_cci.py` |
| 三乌鸦/三白兵 + Stoch | XAUUSD M15 | 慢随机 %K47/%D9，%D<30 买、>70 卖 | `test_0228_1346_three_crows_soldiers_stoch.py` |
| 蜡烛图均值回归 | XAUUSD D1 2008-2025 | RSI(2)<5 且锤子/看涨吞没，持有 5 日 | `test_0035_candlestick_mean_reversion.py` |
| 复合蜡烛反转 | XAUUSD M15 | 最多 3 根 K 线合并成"复合锤子"，SL=2×蜡烛尺寸 | `test_0229_1347_reversal_candles.py` |
| CandelsHighOpen | XAUUSD M15 | 4 根 K 线高点与开盘价同向单调 + SAR 跟踪止损 | `test_0173_0777_candels_high_open.py` |
| 卡尔曼滤波蜡烛 | XAUUSD M15 | 对 OHLC 各跑卡尔曼滤波，"滤波蜡烛"变色即反转 | `test_0186_0951_kalmanfiltercandle.py` |
| ThreeCandles | XAUUSD M15 | 两根同向 K 线后的受控回调三棒形态 | `test_0143_0636_exp_threecandles.py` |
| X2MA 蜡烛 | XAUUSD M15 | 两级平滑 MA 构造蜡烛，颜色翻转触发 | `test_0068_0234_exp_x2macandle_mmrec.py` |
| FineTuningMA 蜡烛 | XAUUSD M15 | 加权价格细调均线蜡烛 + bracket 出场 | `test_0048_0154_exp_finetuningmacandle.py` |
| XPeriod 蜡烛系统 | XAUUSD M15 | 周期化平滑蜡烛颜色状态机 | `test_0102_0298_exp_xperiodcandlesystem_tm_plus.py` |
| MACD 蜡烛 | XAUUSD M15 | MACD 值构造蜡烛颜色 | `test_0187_0952_macdcandle.py` |
| FRAMA 蜡烛 | XAUUSD M15 | 分形自适应均线蜡烛颜色 | `test_0194_0970_framacandle.py` |

## 深读一：三白兵检测器——形态的"工程化定义"

先看四个测试共享的形态检测器（[test_0225_1343_three_crows_soldiers_rsi.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/mean_reversion/test_0225_1343_three_crows_soldiers_rsi.py)）。教科书说"三根连续长阳"，代码必须回答：多长算长？怎么算连续？

```python
def _three_white_soldiers(self):
    if len(self.data) < 4:
        return False
    avg = self._avg_body()          # 近 51 根 K 线的平均实体
    if avg <= 0:
        return False
    return (
        (float(self.data.close[-3]) - float(self.data.open[-3]) > avg) and
        (float(self.data.close[-2]) - float(self.data.open[-2]) > avg) and
        (float(self.data.close[-1]) - float(self.data.open[-1]) > avg) and
        (self._mid_point(-2) > self._mid_point(-3)) and
        (self._mid_point(-1) > self._mid_point(-2))
    )

# 入场（RSI 版）：形态 + 确认器
# if self._three_white_soldiers() and rsi_1 < 40: self.buy(...)
# if self._three_black_crows() and rsi_1 > 60:  self.sell(...)
```

两个工程细节值得咀嚼：**"长实体"是相对的**——必须大于近期平均实体，而不是绝对点数，这样同一套阈值才能同时适用于平静盘整和暴力行情；**"连续"用中点上移判定**，过滤掉三根大阳线但重心不动的高波动假形态。四个变体里 `ma_period`（平均实体的窗口）也不尽相同：RSI 版用 51、MFI/CCI 版用 13、Stoch 版用 5——移植时连这些细节差异都被原样保留，恰好构成另一个可研究的维度。

**对照实验的结果**。四份测试都在同一窗口（XAUUSD M15，2025-12-03 至 2026-03-10，6,129 根 K 线）上运行：RSI 版只触发 1 笔交易，净亏 2,083.40（终值 997,916.60）；MFI 版 7 笔，胜率 42.86%，终值 999,408.80；Stoch 版 4 笔，胜率 25%，终值 999,394.30；CCI 版仅断言了最基本的活动性。三个月窗口内信号稀疏，**结论不是"哪个确认器更好"，而是这套矩阵正是做该研究的正确姿势**——把确认器当唯一变量，数据、成本、断言全部锁死，换一段更长的历史数据即可复用。

## 深读二：锤子 + RSI(2)——经典组合的诚实基线

[test_0035_candlestick_mean_reversion.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/mean_reversion/test_0035_candlestick_mean_reversion.py) 在 XAUUSD 日线上跑了 2008-2025 整整 18 年：RSI(2) 跌破 5 的极端超卖，再要求锤子或看涨吞没确认，持有 5 天离场。

```python
def detect_hammer(open_price, high, low, close):
    body = abs(close - open_price)
    lower_shadow = pd.concat([open_price, close], axis=1).min(axis=1) - low
    upper_shadow = high - pd.concat([open_price, close], axis=1).max(axis=1)
    total_range = high - low
    is_hammer = (
        (total_range > 0) & (body > 0) &
        (lower_shadow >= 2 * body) &      # 下影线 >= 2 倍实体
        (upper_shadow <= body * 0.5)      # 上影线 <= 0.5 倍实体
    )
    return is_hammer.astype(float)

# 入场：RSI(2) < 5 且 锤子 或 看涨吞没
out['entry_signal'] = (
    (out['rsi'] < rsi_oversold) &
    ((out['hammer'] > 0.5) | (out['bullish_engulfing'] > 0.5))
).astype(float)
```

**诚实的回测结果**：18 年里 52 笔交易，胜率 48.08%，终值 836,509.26——从 100 万亏到 83.6 万（-16.35%），盈亏比 0.639。测试用 `abs(final_value - 836509.26) < 0.83` 把这个亏损钉成了基线。它教给你的正是回归测试库的价值观：**形态确认没有自动带来优势，"教科书直觉"必须先过历史数据这一关**。作为练习，试着把 `rsi_oversold` 调回常用的 30、或去掉形态确认只留 RSI(2)，看看断言会怎样崩开。

## 深读三：卡尔曼滤波蜡烛——当形态学家遇上状态估计

如果不用固定窗口的平均实体，而是让"蜡烛"自己随噪声自适应呢？[test_0186_0951_kalmanfiltercandle.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/mean_reversion/test_0186_0951_kalmanfiltercandle.py) 移植自 MT5 EA，对 open/high/low/close **各跑一条卡尔曼滤波**（`k=1.0`），拼出一根"滤波蜡烛"：

```python
def next(self):
    source_price = indicator_source_price(self.data, 0)
    # （首根 K 线的初始化分支从略）
    prev_value = float(self.lines.value[-1]) - float(self.p.price_shift_points)
    distance = source_price - prev_value
    error = prev_value + distance * self.sqrt100        # sqrt(k/100)
    self._velocity += distance * self.k100              # k/100
    filtered = error + self._velocity + float(self.p.price_shift_points)
    self.lines.value[0] = filtered

# KalmanFilterCandleIndicator：滤波 OHLC 拼蜡烛，再判色
# if o < c:  color = 2   # 看涨
# elif o > c: color = 0  # 看跌
```

策略交易"滤波蜡烛的颜色翻转"：翻红开多、翻绿开空，配 1,000 点止损 / 2,000 点止盈。结果很有教育意义：6,127 根 K 线里做了 **497 笔**交易，胜率只有 29.38%，终值 997,343.30——低胜率靠止盈两倍于止损来续命，最终仍略亏。滤波抹掉了噪声，也抹掉了形态本身的节奏，这是所有"平滑反转"系统的共性代价：滤波越强，信号越滞后，翻转越频繁。想救活它，方向不在调 `k`，而在给翻转信号加一道确认（比如上一根滤波蜡烛的斜率），这正好可以借回深读一的确认器矩阵。

## 其余策略，快速点将

- **复合蜡烛反转**（`test_0229`）：把最多 3 根 K 线合并成一根"复合蜡烛"再找锤子影线，止损直接用 `2.0 × 蜡烛尺寸` 定价——形态尺度和风控尺度自洽。
- **CandelsHighOpen**（`test_0173`）：四根 K 线的高点、开盘价双双单调上行才算"冲动"，Parabolic SAR 充当移动止损，504 笔交易胜率 52.58%。
- **ThreeCandles**（`test_0143`）：两根同向 K 线后跟一根"受控回调"，回调不破首根区间即入场——把"回踩不破"这个古老直觉代码化。
- **X2MA / FRAMA / MACD 蜡烛家族**（`test_0068` / `test_0194` / `test_0187`）：把任意指标输出伪装成蜡烛颜色，颜色翻转即信号——一个可无限扩展的模板。
- **XPeriod 蜡烛系统**（`test_0102`）：周期参数化的平滑蜡烛状态机，TM+ 版本还带时段管理。

## 一条命令跑起来

```bash
# 整个 mean_reversion 分类（331 个策略回测）
pytest tests/functional/strategies/mean_reversion/ -v

# 只跑三乌鸦/三白兵 × RSI
pytest tests/functional/strategies/mean_reversion/test_0225_1343_three_crows_soldiers_rsi.py -v

# 四种确认器对照实验，一次跑齐
pytest tests/functional/strategies/mean_reversion/test_0225_1343_three_crows_soldiers_rsi.py \
       tests/functional/strategies/mean_reversion/test_0226_1344_three_crows_soldiers_mfi.py \
       tests/functional/strategies/mean_reversion/test_0227_1345_three_crows_soldiers_cci.py \
       tests/functional/strategies/mean_reversion/test_0228_1346_three_crows_soldiers_stoch.py -v
```

每个测试都带指标断言基线（终值、胜率、夏普逐项比对），部分测试同时在 `runonce=True/False` 双引擎模式下对拍——你改的不只是策略，任何引擎侧的数值漂移都会在这里报警。

## 为什么在这个项目上研究 K 线反转形态

形态识别是最容易被"感觉良好"绑架的领域：同一根锤子线，换个人划窗口结论就不同。[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 把它变成可复现科学：纯 Python 引擎比原版快 46%，1,152 个策略回归测试几分钟跑完；装上 C++ 后端（`pip install back-trader-cpp`）可获得中位 128 倍加速，"四种确认器哪个好"这类矩阵实验可以从"论文级工程"降级为"下午茶实验"。runonce/runnext 双模式对拍加上指标断言基线，保证你比较的是确认器，而不是引擎 bug。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
