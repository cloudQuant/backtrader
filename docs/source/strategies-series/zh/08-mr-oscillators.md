# 振荡器反转：Stochastic、CCI、KDJ 与 Blau 的平滑之道

> 量化策略图鉴 · 第 08 篇 · 分类 `mean_reversion`（331 个策略）· 2026-09-02

1950 年代末，George Lane 对实习生们反复念叨一句话："随机指标告诉你，收盘价坐在近期区间的哪个位置。" 这就是 Stochastic 的全部哲学：如果一轮下跌的尾声、收盘价却开始收在近几日区间的上沿，说明空头已经推不动价格了——**收盘位置比价格本身更早泄露拐点**。后来这条思路开枝散叶：Lane 的 %K/%D 演化出中国交易者最爱的 KDJ；Lambert 的 CCI 用典型价偏离均值的标准化距离衡量"极端"；William Blau 则在 1990 年代系统性地把"原始动量 → 多重平滑 → 比值归一"做成了一整个家族（TSI、Ergodic、SM Stochastic）。

有趣的是，本仓库这批 MT5 移植的振荡器策略里，最核心的改造方向出奇一致：**如何让一个天生抖动的振荡器变得可交易**——有人平滑它（DiNapoli、Blau、DSS），有人把它离散成颜色状态（CCI/RSI Histogram），有人干脆把信号搬到高周期去评估。本篇从约 57 个振荡器反转策略中挑出代表解读。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| OHLC Stochastic | XAUUSD M1→H12 | 高周期随机指标交叉 + 极值区入场，风险百分比仓位 | `test_0065_0231_ohlc_stochastic.py` |
| EA Stochastic | XAUUSD M15 | %K 与 3 根前同处 80 下方做多 / 20 上方做空，追踪止损 | `test_0238_0369_ea_stochastic.py` |
| KDJ 交易系统 | XAUUSD M15→H1 | KDJ(30,3,6) 金叉/死叉 + 中线方向确认 | `test_0239_0515_kdj_trading_system.py` |
| CCI Histogram | XAUUSD M15/H4 | CCI(14) 按 ±100 染成三色状态，颜色翻转触发 | `test_0268_0925_cci_histogram.py` |
| DiNapoli Stochastic | XAUUSD M15→H6 | 8/3/3 指数式双重平滑随机，交叉反转入场 | `test_0275_1013_dinapoli_stochastic.py` |
| Cronex CCI | XAUUSD M15 | CCI 双重平滑出快慢线再取交叉 | `test_0276_1015_cronex_cci.py` |
| Blau Ergodic | XAUUSD M15 | 三重平滑动量归一化，三种信号模式可切换 | `test_0301_1108_blau_ergodic.py` |
| Blau SM Stochastic | XAUUSD M15 | Blau 平滑版随机指标 | `test_0291_1074_blausm_stochastic.py` |
| Super Woodies CCI | XAUUSD M15/H4 | CCI(50) 与快速 TCCI(10) 的持续偏向与颜色切换 | `test_0309_1215_super_woodies_cci.py` |
| DSS Bressert | XAUUSD M15/H4 | 双重平滑随机 DSS 上穿 MIT 做多、下穿做空 | `test_0310_1227_dss_bressert.py` |

## 深读一：KDJ 交易系统——随机指标的"中国式进化"

KDJ 本质上是把 Stochastic 的 %K（区间位置）再平滑一次得到 %D，再由 `J = 3K − 2D` 拉伸出超买超卖更夸张的 J 线。仓库实现（[test_0239_0515_kdj_trading_system.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/mean_reversion/test_0239_0515_kdj_trading_system.py)）用的是完整的三线版 KDJIndicator，参数放得很宽——30 期、%K 平滑 3、%D 平滑 6：

```python
params = dict(
    m1=3, m2=6,            # %K、%D 的平滑周期
    kdj_period=30,         # 随机指标回看区间
    stop_loss=25,          # 25 点止损
    take_profit=45,        # 45 点止盈
)
self.kdj = bt.indicators.KDJIndicator(self.data_h1, m1=3, m2=6, kdj_period=30)

# 多头：KDC 中线信号由负转正（金叉），或 K 线在零轴上方且仍在上升（趋势内回调结束）
if (val_kdc_prev < 0.0 and val_kdc_current > 0.0) or \
   (val_kdc_current > 0.0 and (val_k_prev - val_k_current) < 0.0):
    self.stop_price = self._round(price - sl_dist)
    self.take_profit_price = self._round(price + tp_dist)
    self.order = self.buy(data=self.data, size=float(self.p.lots))
```

注意这里的工程结构：KDJ 挂在 **H1 重采样 feed** 上（`cerebro.resampledata(..., compression=60)`），下单却在 M15 执行 feed 上成交，并用 `last_signal_dt` 保证每根 H1 信号 K 线只反应一次。结果很"日内"：三个月 1,149 笔交易，胜率 50.22%，盈利因子 1.16，终值微涨到 1,006,404——典型的薄利多销型均值回归，赚的是纪律和点差控制的钱。

## 深读二：DiNapoli Stochastic——交易大师的"减速"改造

Joe DiNapoli 是斐波那契交易法的旗手，他对 Stochastic 的改造看似简单却改变了信号性格：原始 %K 用 8 期，然后用**递推式指数平滑**连做两次（3 期平滑出主线，再 3 期平滑出信号线）：

```python
res = 100.0 * (frame['close'] - lowest) / raw_range   # 8 期原始 %K

for value in res.tolist():
    prev_sto = prev_sto + (float(value) - prev_sto) / max(1, int(slow_k))  # 3 期平滑主线
    prev_sig = prev_sig + (prev_sto - prev_sig) / max(1, int(slow_d))      # 再 3 期平滑信号线

# 关键反转定义：主线下穿信号线 → 做多（做空动量衰竭）
buy_signal = (sto.shift(1) > sig.shift(1)) & (sto <= sig)
sell_signal = (sto.shift(1) < sig.shift(1)) & (sto >= sig)
```

注意最后一行：**主线下穿信号线是买入信号**——这是彻头彻尾的反转逻辑，赌的是振荡器从高位回落的"第一脚"之后价格跟随修复。信号在 6 小时（360 分钟）重采样框架上评估，M15 执行。3 个多月只做了 24 笔（14 胜 9 负，胜率 58.33%），终值 1,000,797.20——两次平滑把抖动滤掉之后，一个激进的 contrarian 规则变成了低频、可持有的系统。完整实现见 [test_0275_1013_dinapoli_stochastic.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/mean_reversion/test_0275_1013_dinapoli_stochastic.py)。

## 深读三：Blau Ergodic——把动量揉到"ergodic"为止

William Blau 的方法论一以贯之：**任何原始序列都太吵，多重指数平滑之后才配叫指标**。Ergodic 振荡器（[test_0301_1108_blau_ergodic.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/mean_reversion/test_0301_1108_blau_ergodic.py)）对 2 期动量做链式平滑（20→5→3），再除以同样平滑过的绝对动量做归一化，得到有界主线；主线再 EMA 一次成信号线，两者之差就是 spread 柱：

```python
params = dict(
    mode='twist',          # 三种模式：breakdown / twist / cloudtwist
    xlength=2,             # 原始动量周期
    xlength1=20, xlength2=5, xlength3=3,   # 链式平滑
    xlength4=3,            # 信号线 EMA
)
def _twist_signals(self):
    hist_now = float(self.osc.spread[current])     # spread 柱"拐头"：
    hist_prev = float(self.osc.spread[previous])   # 先降后升 → 买入
    hist_older = float(self.osc.spread[older])
    return hist_prev < hist_older and hist_now > hist_prev, \
           hist_prev > hist_older and hist_now < hist_prev
```

诚实的结局：这套参数在测试窗口做了 2,101 笔，胜率 41.88%，盈利因子 0.979，终值 997,814——**微亏**，测试把这个失败原样钉进了断言。对比前两篇深读的 1,149 笔（PF 1.16）和 24 笔（PF 1.19），你会看到一个清晰的谱系：信号越频繁，单笔优势越薄。回归测试库不删亏钱策略，因为**亏钱的基线和赚钱的基线一样值钱**——它们标定了每个信号引擎的"出厂性能"。

## 其余策略，快速点将

- **OHLC Stochastic**（`test_0065`）：M1 数据重采样到 H12 出信号，仓位按风险百分比动态计算，带追踪止损——基础设施最完整的一个。
- **EA Stochastic**（`test_0238`）：极端高频版本，3 个月 3,052 笔、1,540 胜，胜率刚过半；想研究点差与滑点对高频反转的侵蚀，这是最好的标本。
- **CCI Histogram**（`test_0268`）：CCI(14) 按 ±100 分三色，只交易颜色翻转；把连续值离散成状态机，是消除振荡器抖动的通用招数。
- **Super Woodies CCI**（`test_0309`）：Woodies CCI 流派的"全家桶"——慢 CCI(50) 定基调、快 TCCI(10) 找拐点，17 笔交易 7 胜。
- **DSS Bressert**（`test_0310`）：对随机指标做 EMA(8)+Stoch(13) 双重改造得 DSS，与信号线 MIT 的交叉驱动方向，29 笔 15 胜。

## 一条命令跑起来

```bash
# 整个分类（331 个策略，runonce/runnext 双模式自动对拍）
pytest tests/functional/strategies/mean_reversion/ -v

# 只跑 Blau Ergodic
pytest tests/functional/strategies/mean_reversion/test_0301_1108_blau_ergodic.py -v
```

## 为什么在这个项目上研究振荡器反转

振荡器家族的成员太多了：周期、平滑层数、阈值、信号模式，每个自由度都在制造"变体膨胀"——不跑够规模，你永远不知道哪个差异是真信号。这正是 [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 的主场：纯 Python 引擎比原版快 46%，1,152 个策略回归测试全量在库；C++ 后端（`pip install back-trader-cpp`）中位 128 倍加速，把"平滑层数 × 周期"的网格扫描变成分钟级实验；runonce/runnext 双模式对拍加上逐指标断言基线，确保你观察到的是策略差异，而不是引擎漂移。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
