# 突破策略：从海龟法则到 Dual Thrust 与 R-Breaker

> 量化策略图鉴 · 第 28 篇 · 分类 `breakout`（6 个策略）· 2026-09-02

如果你只能学一类策略，那应该是突破（Breakout）。它逻辑最朴素——"价格创出新高就买"——却孕育了史上最著名的交易实验：1980 年代 Richard Dennis 用一套 Donchian 通道突破规则，把 23 名毫无经验的学员培养成平均年化 80% 的"海龟交易员"，证明交易可以被系统化传授。

本篇解读本仓库 `tests/functional/strategies/breakout/` 下的 6 个突破策略回测：两个 Donchian 变体、期货日内双雄 Dual Thrust 与 R-Breaker，以及量价突破和价格通道。每个都是单文件完整回测，一条命令即可复现。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| Donchian 通道（经典版） | ORCL 日线 2010-2014 | 突破 20 日最高价入场，跌破 20 日最低价出场 | `test_105_donchian_channel_strategy.py` |
| Donchian 通道（backhacker 版） | ORCL 日线 | 同思想的另一个参数化实现 | `test_66_donchian_channel_strategy.py` |
| Dual Thrust | 玻璃期货 FG889 分钟线 | N 日波动幅度构造上下轨，开盘价锚定的日内突破 | `test_09_dual_thrust_strategy.py` |
| R-Breaker | 螺纹钢 RB889 分钟线 | 昨日高低收推算六级价位，突破与反转双逻辑 | `test_10_r_breaker_strategy.py` |
| 量价突破 | ORCL 日线 | 放量 + RSI 过滤的突破入场 | `test_115_volume_breakout_strategy.py` |
| 价格通道 | ORCL 日线 | 创 N 日新高做多，跌破 M 日新低平仓 | `test_117_price_channel_strategy.py` |

## 深读一：Donchian 通道——海龟的起点

Richard Dennis 的海龟法则核心只有一句话：**价格突破 N 日最高价就买入，跌破 N 日最低价就卖出**。Donchian 通道把这个思想变成了两条线——通道上轨是 N 日最高价，下轨是 N 日最低价。

仓库里的实现（[test_105_donchian_channel_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/breakout/test_105_donchian_channel_strategy.py)）干净到可以用 20 行讲清楚：

```python
class DonchianChannelStrategy(bt.Strategy):
    params = dict(stake=10, period=20)

    def __init__(self):
        self.highest = bt.indicators.Highest(self.data.high, period=self.p.period)
        self.lowest = bt.indicators.Lowest(self.data.low, period=self.p.period)

    def next(self):
        if not self.position:
            if self.data.close[0] > self.highest[-1]:   # 突破上轨，买入
                self.order = self.buy(size=self.p.stake)
        else:
            if self.data.close[0] < self.lowest[-1]:    # 跌破下轨，离场
                self.order = self.close()
```

注意 `self.highest[-1]` 的 `-1`：比较的是**上一根 K 线**的通道值，避免用"当根最高价突破当根最高价"的自我指涉——这是新手常犯的偏差之一。

**诚实的回测结果**。这个朴素版本在 ORCL 2010-2014 数据上、计入 0.1% 佣金后，终值 99,965.62（初始 100,000）——**略亏**。测试断言 `abs(final_value - 99965.62) < 0.01`，把这个"不赚钱"钉死成了基线。这正是回归测试库的价值观：**策略不是用来表演的，是用来比较的**。没有过滤的裸突破在震荡市会被反复打脸；你在后续篇目会看到加一个 ADX 趋势过滤、或叠加成交量确认后，同一思想可以脱胎换骨。

## 深读二：Dual Thrust——期货日内突破的标配

Dual Thrust 是国内外期货日内交易流传最广的策略框架之一（[test_09_dual_thrust_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/breakout/test_09_dual_thrust_strategy.py)）。它在玻璃期货 FG889 分钟线上运行，分三步：

**第一步：用过去 N 日（默认 10 日）的波动构造 Range。**

```python
hh = max(day_high_list[-look_back:])    # N 日最高价
lc = min(day_close_list[-look_back:])   # N 日最低收盘价
hc = max(day_close_list[-look_back:])   # N 日最高收盘价
ll = min(day_low_list[-look_back:])     # N 日最低价
range_price = max(hh - lc, hc - ll)     # 取两者较大值，更保守
```

**第二步：以当日开盘价为锚，上下各偏移 k 倍 Range 得到买卖触发线。**

```python
upper_line = now_open + k1 * range_price   # k1 = 0.5
lower_line = now_open - k2 * range_price   # k2 = 0.5
```

**第三步：盘中触及轨道就入场，方向反转直接反手，14:55 强制平仓隔夜清零。**

这套设计的精妙在于：开盘价锚定让轨道随每天的位置自适应，Range 又随波动率伸缩——波动大时轨道更宽、减少假突破；`max(HH-LC, HC-LL)` 的取法让波段估计偏保守。Dual Thrust 也是理解中国期货市场交易时段的好例子：代码里夜盘 21:00-23:00 与日盘 9:00-11:00 的时段判断，正是国内品种的真实节奏。

## 深读三：R-Breaker——一套价位，两种逻辑

如果说 Dual Thrust 是"单边追击"，R-Breaker（[test_10_r_breaker_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/breakout/test_10_r_breaker_strategy.py)）则是**趋势与反转的双面手**——它常年出现在国内外日内策略榜单上，被戏称为"日内交易者的瑞士军刀"。

它用昨日的高（H）、低（L）、收（C）推算五个价位：

```python
pivot = (pre_high + pre_low + pre_close) / 3
r1 = pivot + 0.5 * (pre_high - pre_low)   # 观察阻力
r3 = pivot + 1.0 * (pre_high - pre_low)   # 突破阻力
s1 = pivot - 0.5 * (pre_high - pre_low)   # 观察支撑
s3 = pivot - 1.0 * (pre_high - pre_low)   # 突破支撑
```

两套规则共享这组价位：

- **趋势模式**：空仓时，收盘价突破 R3 追多、跌破 S3 追空——认为强突破会延续；
- **反转模式**：持多时若价格回落跌破 R1（涨不动了），立即平多并**反手开空**；持空时升破 S1 则平空反手做多。

最后同样 14:55 清仓。趋势模式赚"突破后的一波流"，反转模式赚"假突破的回马枪"——同一组价位，涨跌两种剧本都有预案，这是 R-Breaker 长盛不衰的原因。

测试工程上还有一处值得注意：它使用 `ComminfoFuturesPercent` 按 10% 保证金、10 倍乘数给螺纹钢定价，从 50,000 起步——日内期货策略的保证金与合约乘数处理，模板拿来就能改。

## 其余三席，快速点将

- **量价突破**（`test_115`）：突破必须有量。成交量显著高于其均线时才认 entry，RSI 超买或达到最大持有期离场——把"放量验证"这个古老直觉工程化。
- **价格通道**（`test_117`）：Turtle 家族的极简变体——创 N 日新高做多、跌破 M 日新低平仓。入场周期 N 与出场周期 M 分离，是所有通道策略可调的第一个旋钮。
- **Donchian backhacker 版**（`test_66`）：同一思想的另一份参数化实现，适合用来对照"同一规则、不同实现"的工程差异。

## 一条命令跑起来

```bash
# 整个分类（6 个策略，runonce/runnext 双模式自动对拍）
pytest tests/functional/strategies/breakout/ -v

# 只跑 R-Breaker
pytest tests/functional/strategies/breakout/test_10_r_breaker_strategy.py -v
```

每个测试都会在向量化（`runonce=True`）与事件驱动（`runonce=False`）两种引擎模式下各跑一遍并比对指标——引擎改版若引入偏差，这里第一时间报警。

## 为什么在这个项目上研究突破策略

突破策略信号稀疏、持仓周期长、参数敏感，最需要**大规模、可复现**的回测基础设施。这正是 [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 的着力点：纯 Python 引擎比原版快 46%，1,152 个策略回归测试跑完只要几分钟；装上 C++ 后端（`pip install back-trader-cpp`）可获得中位 128 倍加速，参数扫描从"过夜任务"变成"喝口咖啡"。而每个策略的指标断言基线，保证你优化的是策略本身，而不是被引擎的数值漂移误导。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
