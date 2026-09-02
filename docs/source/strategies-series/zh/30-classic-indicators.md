# 经典单指标策略：威廉、KD、TRIX 与终极振荡器的教科书之旅

> 量化策略图鉴 · 第 30 篇 · 分类 `multi_indicator`（9 个策略）· 2026-09-02

打开任何一本技术分析教材，你都会遇到同一批名字：Williams %R、随机指标 KD、CCI、TRIX、抛物线 SAR……它们大多诞生于 1970-80 年代——没有回测软件、没有 Python，作者靠手工绘图的图纸纸和计算器，把对市场的观察压缩成一条公式。其中最传奇的是 Larry Williams：1987 年他在罗宾斯世界期货交易大赛上，用一年时间把 1 万美元做到逾百万美元，收益率超过 11,000%；他的女儿（后来的演员米歇尔·威廉姆斯）16 岁时也拿下过同一赛事冠军。Williams %R 和本篇的"终极振荡器"，都出自这位交易狂人之手。

这些"教科书指标"常被讥为过时，但它们恰恰是学量化最好的起点：公式透明、参数极少、逻辑一句话说得清——出了问题你一眼就知道该怀疑哪里。本篇解读 `tests/functional/strategies/multi_indicator/` 下的 9 个单指标策略回测，其中 7 个跑在同一份 ORCL 日线数据（2010-2014，10 万美元本金、0.1% 佣金、每次 10 股）上，天然构成一场"同数据、同资金、不同指标"的对照实验。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| Williams %R | ORCL 日线 | %R 跌破 -80 后拐头做多，升破 -20 平仓 | `test_102_williams_r_strategy.py` |
| 随机指标 KD | ORCL 日线 | K 上穿 D 且 K<20 做多；K 下穿 D 且 K>80 平仓 | `test_103_stochastic_strategy.py` |
| CCI | ORCL 日线 | CCI 上穿 -100 做多，自 +100 上方跌回平仓 | `test_104_cci_strategy.py` |
| 抛物线 SAR | ORCL 日线 | 价格上穿 SAR 做多，下穿 SAR 平仓 | `test_106_parabolic_sar_strategy.py` |
| TRIX | ORCL 日线 | 三重指数均线变化率上穿/下穿零轴 | `test_107_trix_strategy.py` |
| 终极振荡器 UO | ORCL 日线 | 7/14/28 三周期合成动量，<30 做多、>70 平仓 | `test_109_ultimate_oscillator_strategy.py` |
| Aberration（期货版） | 螺纹钢 RB889 分钟线 | 200 期布林带上下轨突破开仓、回中轨平仓 | `test_12_abberation_strategy.py` |
| Aberration（股票版） | 浦发银行日线 2000-2022 | 同一布林带突破思想的 A 股实现 | `test_25_abbration_strategy.py` |
| UDVD | ORCL 日线 | K 线实体（收-开）3 期 SMA 的正负定多空 | `test_95_udvd_strategy.py` |

## 深读一：终极振荡器——Larry Williams 对"钝化"的手术

单周期振荡器有个通病：7 期反应快但噪声大，28 期可靠但慢半拍。Larry Williams 在 1985 年《Technical Analysis of Stocks & Commodities》的文章里给出的解法干脆利落——把三个周期**合成一个指标**，短周期权重最高：

```python
params = dict(
    stake=10,
    p1=7,
    p2=14,
    p3=28,
    oversold=30,
    overbought=70,
)

def __init__(self):
    self.uo = bt.indicators.UltimateOscillator(
        self.data, p1=self.p.p1, p2=self.p.p2, p3=self.p.p3
    )

def next(self):
    self.bar_num += 1

    if self.order:
        return

    if not self.position:
        # Entry: UO in oversold territory
        if self.uo[0] < self.p.oversold:
            self.order = self.buy(size=self.p.stake)
    else:
        # Exit: UO in overbought territory
        if self.uo[0] > self.p.overbought:
            self.order = self.close()
```

这是 [test_109_ultimate_oscillator_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/multi_indicator/test_109_ultimate_oscillator_strategy.py) 的全部交易逻辑——不到 20 行。注意 `bar_num` 断言是 **1229**，比同批策略少了 20-26 根：UO 需要 28 期买入压力（buying pressure）与真实波幅（true range）的完整历史，暖机期更长本身就是多周期合成的代价。

**结果是同批"教科书组"里最亮的一个**：终值 100,199.75，Sharpe 2.2256，最大回撤仅 6.37%。对比 SAR 版的 Sharpe 0.158、回撤 14.47%，多周期加权确实在降噪上做对了事情——当然，0.04% 的年化收益也提醒你：没有趋势过滤的超买超卖策略，赢的只是"体面"。

## 深读二：随机指标 KD——给交叉加一道"位置闸门"

George Lane 在 1950 年代提出的随机指标，思想是"收盘价在近期区间中的位置"：贴着高点收盘是强，贴着低点收盘是弱。但裸的 K/D 交叉信号泛滥，教科书给出的修补是**只在超卖区买、只在超买区卖**。[test_103_stochastic_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/multi_indicator/test_103_stochastic_strategy.py) 忠实实现了这条规则：

```python
def __init__(self):
    self.stoch = bt.indicators.Stochastic(
        self.data,
        period=self.p.period,
        period_dfast=self.p.period_dfast,
    )
    self.crossover = bt.indicators.CrossOver(self.stoch.percK, self.stoch.percD)

def next(self):
    self.bar_num += 1

    if self.order:
        return

    if not self.position:
        # K crosses above D and in oversold zone
        if self.crossover[0] > 0 and self.stoch.percK[0] < self.p.oversold:
            self.order = self.buy(size=self.p.stake)
    else:
        # K crosses below D and in overbought zone
        if self.crossover[0] < 0 and self.stoch.percK[0] > self.p.overbought:
            self.order = self.close()
```

参数是经典的 14/3，阈值 20/80。双闸门（交叉 + 位置）把 1,239 根 K 线里的交易压缩到只剩高质量区间：终值 100,219.02，Sharpe 0.692，最大回撤 8.50%。工程上值得学的是 `CrossOver` 这个封装——它把"上穿/下穿"的边界判断（昨天 ≤、今天 >）交给指标层，策略层只读一个正负号，可读性和出错率都优于手写比较。

## 深读三：抛物线 SAR——Wilder 的"一册宗师"遗产

J. Welles Wilder Jr. 1978 年的《New Concepts in Technical Trading Systems》大概是技术分析史上单本产出最高的书：RSI、ATR、ADX、抛物线 SAR 全部出自这里。SAR 的巧思在于**加速因子**——趋势每创新高，止损点就跟紧一步，像抛物线一样越收越快，直到把利润"逼"出来。[test_106_parabolic_sar_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/multi_indicator/test_106_parabolic_sar_strategy.py)：

```python
params = dict(
    stake=10,
    af=0.02,
    afmax=0.2,
)

def __init__(self):
    self.sar = bt.indicators.ParabolicSAR(
        self.data, af=self.p.af, afmax=self.p.afmax
    )
    self.crossover = bt.indicators.CrossOver(self.data.close, self.sar)

def next(self):
    self.bar_num += 1

    if self.order:
        return

    if not self.position:
        if self.crossover[0] > 0:
            self.order = self.buy(size=self.p.stake)
    else:
        if self.crossover[0] < 0:
            self.order = self.close()
```

af 从 0.02 起步、封顶 0.2，是 Wilder 留下的原始参数。SAR 自带"止损即信号"的优雅，但它的软肋同样有名：震荡市里被反复打脸。回测也诚实——终值 100,044.47、Sharpe 0.158、最大回撤 14.47%，1,255 根 K 线下来几乎白忙。docstring 里那句提醒写得直白：SAR 在强趋势市场最有效，震荡市请配过滤器。

## 其余五席，快速点将

- **Williams %R**（`test_102`）：Larry Williams 1973 年的产物，与 KD 同源（收盘价在区间中的位置），但只做"超卖拐头买、超买卖出"的单边摆动交易。终值 100,102.86、Sharpe 0.479。
- **CCI**（`test_104`）：Donald Lambert 1980 年为"商品周期"设计，用价格与典型价的离差除以平均绝对偏差，±100 阈值穿越入场/离场。
- **TRIX**（`test_107`）：Jack Hutson 的三重 EMA 变化率，等于给价格连过三道低通滤波，零轴穿越定多空——本批最"钝"也最抗噪的动量指标。
- **Aberration 双胞胎**（`test_12` / `test_25`）：长线通道系统的名门正派——200 期布林带、2 倍标准差，破上轨做多、破下轨做空、回中轨离场。期货版在螺纹钢分钟线上 94 笔交易、Sharpe 0.55、终值 1,079,820（本金 100 万）；股票版 22 年浦发银行日线终值 423,916.71（本金 10 万），但最大回撤 46.5%——同一思想跨市场移植，风险画像天差地别。
- **UDVD**（`test_95`）：最简的一席——K 线实体的 3 期 SMA 为正做多、为负平仓。终值 99,939.44，是全组唯一亏损者，恰好说明"越简单"不等于"越有效"。

## 一条命令跑起来

```bash
# 整个分类（9 个策略，runonce/runnext 双模式自动对拍）
pytest tests/functional/strategies/multi_indicator/ -v

# 只跑 Ultimate Oscillator
pytest tests/functional/strategies/multi_indicator/test_109_ultimate_oscillator_strategy.py -v
```

## 为什么在这个项目上研究经典指标

经典指标参数少、公式透明，最适合做**可复现的对照实验**：同一份数据、同一套资金参数，9 个指标各跑一遍，优劣立现。这正是 [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 的强项：纯 Python 引擎比原版快 46%，1,152 个策略回归测试跑完只要几分钟；装上 C++ 后端（`pip install back-trader-cpp`）可获得中位 128 倍加速，参数扫描从"过夜任务"变成"喝口咖啡"。每个策略的 Sharpe、回撤、终值都被断言钉成基线，runonce/runnext 双模式对拍保证你比较的是指标本身，而不是引擎的数值漂移。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
