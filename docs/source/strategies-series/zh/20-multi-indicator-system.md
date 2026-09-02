# 多指标共振：当 CCI 遇上 MACD 和 Camel 通道

> 量化策略图鉴 · 第 20 篇 · 分类 `multi_indicator_system`（29 个策略）· 2026-09-02

单个指标是独裁者：MACD 说买就买，错了也没人拦。多指标系统想建立的是议会——趋势、动量、通道各占一席，但议会怎么议事分成两派。**投票制**（AND 逻辑）：所有指标全部同意才准开仓，一票否决，代价是信号极少；**评分制**（加权求和）：每个指标投出 ±100 分，加权合计越过阈值就行动，灵活却悄悄引入了权重这个新旋钮。MQL5 社区把这个方法论做成了产业——MetaQuotes 官方的 MQL5 Wizard 能像拼乐高一样把信号模块组合成 EA，本仓库就收录了一批它的移植作品。

本篇解读 `tests/functional/strategies/multi_indicator_system/` 下的 29 个策略。除 Kaufman 效率比用日线外，多数跑在 XAUUSD M15 上（2025-12-03 至 2026-03-10）。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| Kaufman Efficiency Ratio | XAUUSD 日线 2008-2025 | ER>0.3 趋势确认后才认 KAMA 突破 | `test_0001_0092_kaufman_efficiency_ratio.py` |
| Three Indicators | XAUUSD M15 | MACD 斜率 + Stochastic 区间 + RSI 状态三票同向 | `test_0008_three_indicators.py` |
| Camel CCI MACD | XAUUSD M15 | CCI + MACD + EMA 通道三重共振开仓 | `test_0014_steve_cartwright_trader_camel_cci_macd.py` |
| MACD Stochastic | XAUUSD M15 | MACD 交叉 + 随机指标确认 + 时段过滤 | `test_0016_macd_stochastic.py` |
| MQL5 Wizard MACD PSAR | XAUUSD M15 | 评分制合成 MACD 动量与 PSAR 趋势 | `test_0020_mql5_wizard_macd_parabolic_sar.py` |
| SAR + ADX + SMA100 | XAUUSD M15 | SAR 定方向、ADX>20 定强度、SMA 定趋势 | `test_0027_sar_adx_sma.py` |
| ICT Concepts EA | XAUUSD M15 | 高周期偏差 + 流动性扫荡 + MSS/FVG 结构 | `test_0006_ict_concepts_ea.py` |
| Universum 3.0 | XAUUSD M15 | DeMarker 方向偏向 + 马丁格尔加仓 | `test_0022_universum_3_0.py` |
| Perceptron | XAUUSD M15 | 五个指标喂进感知机加权评分 | `test_0028_perceptron.py` |
| Binary Wave | XAUUSD M15 | 七个指标加权合成一条波浪再平滑 | `test_0029_binary_wave.py` |

## 深读一：Steve Cartwright Camel CCI MACD——一票否决制的三驾马车

这是投票制的范本（[test_0014_steve_cartwright_trader_camel_cci_macd.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/multi_indicator_system/test_0014_steve_cartwright_trader_camel_cci_macd.py)）。三类指标各管一段：CCI(30) 管动量极端度，MACD(12,26,9) 管动量方向，EMA 通道（所谓 camel 驼峰通道）管价格位置。四道 AND 全过才准做多：

```python
self.camel_high = bt.indicators.ExponentialMovingAverage(
    self.data.high, period=self.p.ma_period_ma_high)        # 40 期最高价的 EMA
self.camel_low = bt.indicators.ExponentialMovingAverage(
    self.data.low, period=self.p.ma_period_ma_low)          # 5 期最低价的 EMA
self.macd = bt.indicators.MACD(self.data.close,
    period_me1=12, period_me2=26, period_signal=9)
self.cci = bt.indicators.CCI(self.data, period=self.p.ma_period_cci)   # 30

if cci_prev > 100 and macd_main_prev > 0 \
        and macd_main_prev > macd_signal_prev \
        and close_prev > camel_high_prev:                   # 四票全绿，做多
    self.order = self.buy(size=self.p.lot)

if cci_prev < -100 and macd_main_prev < 0 \
        and macd_main_prev < macd_signal_prev \
        and close_prev < camel_low_prev:                    # 空头完全镜像
    self.order = self.sell(size=self.p.lot)
```

离场也讲"共识破裂"：持多时 MACD 主线跌回信号线下方、或 CCI 跌回 100 之内、或触及 40 pips 固定止盈，三者任一触发即平仓。两处工程细节：所有判断用 `[-1]` 前一根 K 线的值，杜绝当根自我指涉的未来函数；camel 高低轨周期刻意不对称（40 vs 5），上轨慢、下轨快，多头给的容忍比空头大。三个月 6,071 根 M15 跑出 687 笔、352 胜 335 负，终值 1,038,763.00（+3.88%）——高频微利型，收益全靠胜率优势一点点磨出来。

## 深读二：MQL5 Wizard MACD + Parabolic SAR——评分制的教科书与反面教材

MQL5 Wizard 的标准玩法是"信号模块投票"：每个模块输出 ±100 分乘以权重，总分过线开仓。这个移植（[test_0020_mql5_wizard_macd_parabolic_sar.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/multi_indicator_system/test_0020_mql5_wizard_macd_parabolic_sar.py)）用 MACD 管动量、PSAR 管趋势：

```python
def _macd_score(self):
    if self.macd.macd[0] > self.macd.signal[0]:
        return 100.0 * float(self.p.signal_macd_weight)     # 权重 0.9
    if self.macd.macd[0] < self.macd.signal[0]:
        return -100.0 * float(self.p.signal_macd_weight)
    return 0.0

def _sar_score(self):
    if self.data.close[0] > self.sar[0]:
        return 100.0 * float(self.p.signal_sar_weight)      # 权重 0.1
    if self.data.close[0] < self.sar[0]:
        return -100.0 * float(self.p.signal_sar_weight)
    return 0.0

def _signal_value(self):
    return self._macd_score() + self._sar_score()           # 理论区间 [-100, +100]
```

`signal_threshold_open=20`：总分 ≥ +20 开多、≤ -20 开空；离场三选一——固定 50/115 点（point 单位）止损止盈，或总分走到反向 100（`signal_threshold_close`），即两个指标彻底翻脸。仔细看这份"民主"：MACD 一票值 90 分，PSAR 只值 10 分，而开仓门槛才 20 分——**MACD 单独就能开门，PSAR 只是礼仪性投票**。评分制表面平滑了分歧，权重却决定了谁在独裁。回测给了它一记响亮的耳光：3,077 笔交易、48.6% 胜率、profit factor 0.915、终值 910,005.00（-9.0%），在零佣金的 M15 数据上照样稳定亏——M15 级别的高频换手里，微弱的信号优势扛不住哪怕一丁点摩擦。这个亏损基线被断言完整钉死，是研究"组合方法论如何失效"的绝佳对照组。

## 多指标系统的过拟合陷阱

把两个深读放在一起，还能看见第三层问题：投票制和评分制都在增加指标的同时增加了参数——Camel 策略有 4 个周期参数加止盈点数，Wizard 策略有 6 个权重与阈值。29 个策略里不乏七指标加权（Binary Wave）、五指标感知机（Perceptron）这样的重装部队。每加一个旋钮，拟合历史的能力就强一分，样本外的可靠度就暗降一分。这正是回归测试库存在的意义：**先把每个组合的原始成绩钉死在基线里，任何"优化"都必须在相同数据、相同口径下与前作硬碰硬**。

## 其余策略，快速点将

- **Kaufman Efficiency Ratio**（`test_0001`）：效率比 ER = 净位移/路程，> 0.3 才算有效趋势，此时跟随 KAMA 自适应均线突破——先用"市场值不值得跟"过滤，再谈方向。
- **Three Indicators**（`test_0008`）：MACD 斜率、Stochastic 区间、RSI 状态三个方向旗全为非负做多、全为非正做空——最朴素的三票多数决。
- **SAR + ADX + SMA100**（`test_0027`）：方向（价格在 SAR 哪边）× 强度（ADX > 20）× 趋势（SMA100 上下）三维对齐，指标分工的典范。
- **Perceptron**（`test_0028`）：MA 交叉、RSI、CCI、动量、AO 五路信号加权进一个感知机，输出方向偏置——评分制的神经网络极简版。
- **Binary Wave**（`test_0029`）：MA/MACD/OSMA/CCI/动量比/RSI/ADX 七指标加权合成波浪再平滑，翻越零轴进出——把"议会"压缩成一条曲线。
- **ICT Concepts EA**（`test_0006`）：不走经典指标路线，改用价格结构——高周期定偏差、流动性扫荡后看市场结构转变（MSS）与公允价值缺口（FVG），多目标分批止盈。
- **Universum 3.0**（`test_0022`）：DeMarker 高于 0.5 做多、低于做空，亏损后按马丁格尔加倍仓位，直到连亏上限熔断——组合信号不赚钱时用资金管理硬扛的反面示范。

## 一条命令跑起来

```bash
# 整个分类（29 个策略）
pytest tests/functional/strategies/multi_indicator_system/ -v

# 只跑 Camel CCI MACD
pytest tests/functional/strategies/multi_indicator_system/test_0014_steve_cartwright_trader_camel_cci_macd.py -v
```

这些单文件测试把 `runonce=True` 下的开仓数、胜负数、终值逐项断言成基线；仓库层面以 runonce/runnext 双模式对拍守护引擎一致性，任何数值漂移都会被立刻抓出来。

## 为什么在这个项目上研究多指标系统

多指标系统参数密度全场最高，一个策略动辄七八个旋钮，组合爆炸让全参数扫描动辄上万次回测，最需要**大规模、可复现**的回归基础设施。这正是 [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 的着力点：纯 Python 引擎比原版快 46%，1,152 个策略回归测试跑完只要几分钟；装上 C++ 后端（`pip install back-trader-cpp`）可获得中位 128 倍加速，把"第七个指标值不值得加"从直觉问题变成可计算问题。而每个策略的指标断言基线，保证你优化的是策略本身，而不是被引擎的数值漂移误导。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
