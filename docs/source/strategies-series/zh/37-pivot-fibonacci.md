# 枢轴点与斐波那契：全世界的日内交易员，都在看同一组数字

> 量化策略图鉴 · 第 37 篇 · 分类 `pivot_fibonacci_system`（6 个策略）· 2026-09-02

在电脑占领交易大厅之前，场内交易员每天清晨用铅笔做同一道算术题：昨日最高价加最低价加收盘价，除以三。这个数就是枢轴点（Pivot），从它出发再推出三档阻力、三档支撑——一天的价格地图十分钟画完，钉在交易台上。一百年后，这道题还在被自动计算，只是铅笔换成了 Python。

为什么这么粗糙的公式能活到现在？一种解释是**自我实现预言**：因为足够多的人看同一组数字，价格就真的会在那里反应。斐波那契回撤更是登峰造极——38.2%、50%、61.8% 这些比例没有任何物理依据，但当全市场的图表软件都用同一组比率画线时，"预期"本身就制造了支撑与阻力。本篇解读 `tests/functional/strategies/pivot_fibonacci_system/` 下的 6 个策略，全部运行在黄金（XAUUSD）的 M15 数据上，看这群"心理坐标"被量化之后长什么样。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| MostasHaR15 枢轴 | XAUUSD M15+H1 双周期 | 昨日 OHLC 推 13 级枢轴位，ADX/DI/OSMA 多重确认突破 | `test_0001_mostashar15_pivot.py` |
| SimplePivot | XAUUSD M15→日线 | 昨日高低中点定多空，永远在场、信号翻转即反手 | `test_0002_simplepivot.py` |
| PivotHeiken 3 | XAUUSD M15+D1 双周期 | 平滑 Heikin-Ashi 动量 + 日枢轴均值回归 | `test_0003_pivotheiken_3.py` |
| Fibo iSAR | XAUUSD M15 | 斐波 50% 限价入场、161% 止盈 + 双速 Parabolic SAR | `test_0004_fibo_isar.py` |
| FiboCandles | XAUUSD M15→H1 | 区间 × 斐波比率构造变色蜡烛，颜色翻转即信号 | `test_0005_fibocandles.py` |
| Volatility Pivot | XAUUSD M15→H4 | ATR 驱动的移动枢轴翻转线，趋势反转即反手 | `test_0006_volatility_pivot.py` |

## 深读一：MostasHaR15——十三级价位与四重确认

[test_0001_mostashar15_pivot.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/pivot_fibonacci_system/test_0001_mostashar15_pivot.py) 先把场内交易员的铅笔活完整复刻——昨日高、低、收推出枢轴及全部衍生位，连 M0~M5 中间档都算齐：

```python
def _pivot_levels(self):
    ...
    p = (yh + yl + yc) / 3.0
    r1 = (2.0 * p) - yl
    s1 = (2.0 * p) - yh
    r2 = p + (yh - yl)
    s2 = p - (yh - yl)
    r3 = (2.0 * p) + (yh - (2.0 * yl))
    s3 = (2.0 * p) - ((2.0 * yh) - yl)
    m5 = (r2 + r3) / 2.0
    ...
```

13 个价位把价格轴切成 12 段，策略先定位价格落在哪一段，再要求"距离上方阻力还有 14 点以上空间"才考虑入场——不买已经贴着阻力的价格。而真正让它区别于教科书枢轴策略的，是 H1 周期上的四重确认：

```python
if dif2 > 14 and self.adx[0] > 20 and self.plus_di[0] > self.plus_di[-1] and self.plus_di[0] > self.minus_di[0] and (self.ma_close[0] - self.ma_open[0]) >= ext_step and self.ma_close[-1] > self.ma_open[-1] and self.osma[0] > self.osma[-1]:
```

ADX 大于 20（有趋势）、+DI 抬头且压过 -DI（方向向上）、双 EMA 开口走阔（动能确认）、OSMA 柱增高（MACD 直方图助推）——枢轴位负责"在哪里"，四个指标共同回答"能不能"。6,001 根 M15 跑出 387 笔交易（胜 200 负 187）、终值 999,163.7：百万本金三个月搏杀 387 个来回，几乎原地踏步。日内突破策略的交易成本敏感度，这个数字说得比任何论文都直白。

## 深读二：Fibo iSAR——在 50% 回撤处挂一张限价单

[test_0004_fibo_isar.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/pivot_fibonacci_system/test_0004_fibo_isar.py) 是斐波那契交易的完整工程样本。方向由双速 Parabolic SAR 判断（快 SAR 0.02/0.2，慢 SAR 0.01/0.1），入场价则挂在这段行情的斐波那契 50% 回撤位、止盈挂在 161.8% 延展位：

```python
def _get_fibo(self, high, low, level):
    return round(low + (high - low) * level, self.p.price_digits)

...
op = self._get_fibo(max_price, min_price, self.p.fibo_entrance_level / 100.0)   # 50.0
tp = self._get_fibo(max_price, min_price, self.p.fibo_profit_level / 100.0)     # 161.0
sl = round(min_price - self.p.indent_stop_loss * self._trade_unit(), self.p.price_digits)

if self.pending_buy is None and not self._has_position_side(True):
    valid = bt.num2date(self.data0.datetime[0]) + pd.Timedelta(minutes=15 * self.p.order_valid_bars)
    self.pending_buy = self.buy(size=self.p.size, exectype=bt.Order.Limit, price=op, valid=valid)
```

三个工程细节值得抄走：其一，`exectype=bt.Order.Limit` 用限价单等回调，而不是市价追入——回撤策略的逻辑自洽就在这一个参数上；其二，`valid` 给订单设了 45 分钟（3 根 M15）的生存期，价格不给回撤机会就作废重算，避免挂着一张过期的"好价格"；其三，止损在区间极值外再垫 30 个交易单位，且随浮盈按 10/5 步长移动——入场、失效、移动止损三件事都有明确的时钟与刻度。6,128 根 bar、335 笔交易、胜 194 负 141、终值 1,005,690.9——本分类里少数站在正收益一侧的策略。

## 深读三：SimplePivot——把枢轴简化到只剩一个数

如果说前两个策略是重型机械，[test_0002_simplepivot.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/pivot_fibonacci_system/test_0002_simplepivot.py) 就是一把水果刀。它移植自 MT5 的 0315 号 EA，枢轴只取昨日高低的中点，规则只有一句：开盘价落在哪，方向就是哪——且永远在场，信号一变立刻平仓反手：

```python
def _signal_side(self):
    pivot = (float(self.data0_feed.high[-1]) + float(self.data0_feed.low[-1])) / 2.0
    current_open = float(self.data0_feed.open[0])
    previous_high = float(self.data0_feed.high[-1])
    if current_open < previous_high and current_open > pivot:
        return 'short'
    return 'long'
```

注意那个反直觉的地方：开盘价**低于**昨日高点但**高于**中点，做空；其余情况一律做多。它押注的是"开在区间上半部反而涨不动"的日内反转直觉。工程上则演示了 `notify_order` 如何编排"先平后开"的两步反手：平仓单成交后才提交新方向的入场单，避免两单并发导致仓位瞬时翻倍。约三个月的日线数据（M15 重采样而来）25 笔交易，胜 15 负 10——极简规则的胜率未必差，但那 10 次失败在"永远在场"的设定下无处可藏。

## 其余三席，快速点将

- **PivotHeiken 3**（`test_0003`）：LWMA 双重平滑的 Heikin-Ashi 中线变化率测动量，价格在枢轴下方且动量翻多才做多（均值回归取向），6,038 根 bar 打出 1,584 笔交易——本分类最高频的选手。
- **FiboCandles**（`test_0005`）：把区间乘以斐波比率（0.236/0.382/0.5/0.618/0.762 五档可选）当作"变色阈值"，K 线颜色翻转即趋势翻转，6,093 根 bar、95 笔、胜 56 负 39。
- **Volatility Pivot**（`test_0006`）：枢轴不再是固定价位，而是一条随 ATR(100)×3 倍数伸缩的移动翻转线，价格穿线即反手——4,446 根 bar 只做了 9 笔交易，是六个策略里最有耐心的一位。

## 一条命令跑起来

```bash
# 整个分类（6 个策略）
pytest tests/functional/strategies/pivot_fibonacci_system/ -v

# 只跑 Fibo iSAR
pytest tests/functional/strategies/pivot_fibonacci_system/test_0004_fibo_isar.py -v
```

## 为什么在这个项目上研究枢轴与斐波那契

这六个策略全都在 M15 数据上做双周期、限价单、订单生存期、逐 bar 移动止损——每一项都是对引擎事件驱动路径的严刑拷打，任何一环差一根 bar，MostasHaR15 那 387 笔交易的胜负分布就会改写。[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 的 1,152 个策略回归测试把每一笔的计数、胜负、终值都钉成断言基线，runonce/runnext 双模式对拍确保两种引擎路径给出同一份交易清单；纯 Python 引擎比原版快 46%，C++ 后端（`pip install back-trader-cpp`）中位 128 倍加速，让"三个月 M15 × 6 个策略"的回归跑得比盯盘还快。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
