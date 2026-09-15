# 波动率通道：Keltner、SuperTrend 与吊灯止损，ATR 的一百种用法

> 量化策略图鉴 · 第 29 篇 · 分类 `volatility`（9 个策略）· 2026-09-02

技术指标里若评"最佳通用性"，ATR（平均真实波幅）当仁不让：它不问方向，只丈量市场今天"晃多宽"。本仓库 `tests/functional/strategies/volatility/` 的 9 个策略，几乎全部建立在同一种思想上——**用 ATR 给价格装一条会呼吸的通道**：波动大时通道自动变宽、减少假信号，波动小时收紧、贴近价格。通道上轨是动态阻力，下轨是动态支撑，价格与通道的相对位置便定义了趋势与退出。

这条思想谱系名人辈出：Chester Keltner 在 1960 年代提出用固定比例画通道，Linda Raschke 在 1980 年代改用 ATR 带宽，成为今天的 Keltner 通道；SuperTrend 把 ATR 通道简化成一条翻转线；Chuck LeBeau 的"吊灯退出"则用最高价减 N 倍 ATR 做跟踪止损，名字来自止损线像吊灯一样从天花板垂下来。本篇深读这三个源头。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| Keltner 多合约 | 螺纹钢期货多合约 | 通道突破双向交易 + 主力合约自动移仓 | `test_08_kelter_strategy.py` |
| MACD + ATR | YHOO 日线 2005-2014 | MACD 金叉 + 逆势过滤入场，ATR 跟踪止损保护 | `test_36_macd_atr_strategy.py` |
| Keltner 通道（backhacker 版） | ORCL 日线 2010-2014 | EMA 中轨 ± 2×ATR，突破上轨入场、跌破中轨离场 | `test_70_keltner_channel_strategy.py` |
| SuperTrend | ORCL 日线 2010-2014 | ATR(10)×3 动态支撑阻力线，方向翻转即交易 | `test_81_supertrend_strategy.py` |
| SuperTrend 指标版 | ORCL 日线 2010-2014 | 同思想的另一份参数化实现 | `test_88_supertrend_indicator_strategy.py` |
| 自适应 SuperTrend | ORCL 日线 2010-2014 | 乘数随 ATR 动态自调的 SuperTrend | `test_89_adaptive_supertrend_strategy.py` |
| Keltner 通道 | ORCL 日线 2010-2014 | 同通道思想的详细注释版（与 test_70 同基线） | `test_108_keltner_channel_strategy.py` |
| 吊灯退出 | ORCL 日线 2010-2014 | SMA8/15 交叉 + 22 日最高价 − 3×ATR 吊灯止损 | `test_111_chandelier_exit_strategy.py` |
| SuperTrend + RSI | ORCL 日线 2010-2014 | 价格在 SuperTrend 线上且 RSI 过阈值才入场 | `test_114_supertrend_rsi_strategy.py` |

## 深读一：SuperTrend——一条会翻转的 ATR 通道

SuperTrend 是"通道"的极简形态：不画上下两条带，只保留**当前趋势方向上的那一条线**——多头时是脚下 ATR×乘数的动态支撑，空头时是头顶的动态阻力；价格穿越，线就翻到另一侧，趋势宣告反转。[test_81_supertrend_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/volatility/test_81_supertrend_strategy.py) 的交易逻辑浓缩在 `next()` 里：

```python
params = dict(
    stake=10,
    period=10,          # ATR 周期
    multiplier=3.0,     # ATR 乘数
)

def next(self):
    self.bar_num += 1
    if self.order:
        return

    # Buy when trend turns up
    if not self.position:
        if self.supertrend.direction[0] == 1 and self.supertrend.direction[-1] == -1:
            self.order = self.buy(size=self.p.stake)
    else:
        # Sell when trend turns down
        if self.supertrend.direction[0] == -1:
            self.order = self.sell(size=self.p.stake)
```

方向线从 -1 翻到 +1 的那一根 K 线买入，翻回 -1 即卖出——入场与退出是同一个事件，天然对称，不需要单独的止损规则（止损就"长"在 SuperTrend 线上）。诚实的基线：ORCL 2010-2014、10 万初始资金、0.1% 佣金下，1,247 根 K 线终值 99,999.23——**基本持平略亏**，Sharpe -0.0038，最大回撤 11.22%。裸 SuperTrend 在震荡居多的个股上会被反复翻转侵蚀，这为 `test_114` 的 RSI 过滤版留下了改进空间（后述）。

## 深读二：Keltner 通道——ATR 版的布林带

[test_108_keltner_channel_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/volatility/test_108_keltner_channel_strategy.py) 与布林带的区别一句话说清：**布林带用收盘价标准差，Keltner 用 ATR**。标准差只看收盘价分布，会被跳空与长影线之外的低波动"缩口"误导；ATR 把最高、最低、跳空全部计入，带宽对真实波动更敏感。通道三件套：EMA 中轨，上下轨各偏移 2 倍 ATR：

```python
params = dict(
    stake=10,
    period=20,      # EMA 周期
    atr_mult=2.0,   # ATR 乘数
)

def next(self):
    self.bar_num += 1
    if self.order:
        return

    if not self.position:
        # 收盘价突破上轨：多头动量确认
        if self.data.close[0] > self.kc.top[0]:
            self.order = self.buy(size=self.p.stake)
    else:
        # 跌回中轨（EMA）：趋势衰减，离场
        if self.data.close[0] < self.kc.mid[0]:
            self.order = self.close()
```

入场用上轨（要够强的突破才算数），退出却只回到中轨——通道突破策略的经典不对称设计：让利润有回到均值的余地，而不必等到跌穿下轨才走。基线：ORCL 2010-2014，1,238 根 K 线，终值 100,039.51，Sharpe 0.2796，最大回撤仅 5.50%——本分类回撤控制最好的基线之一。`test_70` 是同一思想的另一份参数化实现，断言与这份完全一致（终值 100,039.51、Sharpe 0.2796），恰好构成"同一规则、两份实现、互相印证"的回归对照。

## 深读三：吊灯退出——从天花板垂下来的止损线

Chuck LeBeau 的吊灯退出（Chandelier Exit）不产生入场信号，只回答一个问题：**趋势单什么时候交还给市场**。答案是：跟踪止损线 = 持仓期间的最高价 − N×ATR，像吊灯一样从最高点垂下，只升不降。[test_111_chandelier_exit_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/volatility/test_111_chandelier_exit_strategy.py) 用它配合均线交叉：

```python
params = dict(
    stake=10,
    sma_fast=8,     # 快均线
    sma_slow=15,    # 慢均线
    ce_period=22,   # 吊灯回看期
    ce_mult=3,      # ATR 乘数
)

def next(self):
    self.bar_num += 1
    if self.order:
        return

    if not self.position:
        # SMA golden cross AND price above Chandelier Short
        if self.sma_fast[0] > self.sma_slow[0] and self.data.close[0] > self.ce.short[0]:
            self.order = self.buy(size=self.p.stake)
    else:
        # SMA death cross AND price below Chandelier Long
        if self.sma_fast[0] < self.sma_slow[0] and self.data.close[0] < self.ce.long[0]:
            self.order = self.close()
```

入场要均线金叉**且**价格站在吊灯短线之上（波动结构健康）；退出要均线死叉**且**价格跌破吊灯长线（趋势与波动结构同时恶化）——两条件与运算，把均线择时与波动率保护焊在一起。基线：1,235 根 K 线，终值 100,018.36，Sharpe 0.1430，最大回撤 8.41%。22 日期、3 倍 ATR 正是 LeBeau 论述中的常用量级，源码即文献。

## 其余策略，快速点将

- **Keltner 多合约**（`test_08`）：螺纹钢期货上验证通道突破 + 主力合约自动移仓——把"通道思想"放进中国期货的真实合约切换场景。
- **SuperTrend + RSI**（`test_114`）：给裸 SuperTrend 加 RSI 动量确认，ORCL 基线终值 100,085.04、Sharpe 0.8988——本分类最优，一个过滤器值这么多。
- **SuperTrend 指标版 / 自适应版**（`test_88/89`）：同一思想的两个变体，基线分别为终值 99,977.89 与 99,936.86——自适应乘数并未必然带来改善。
- **MACD + ATR**（`test_36`）：YHOO 上 46 笔交易 17 胜 28 负，MACD 逆势入场 + `atr * atrdist` 跟踪止损，止损工程比信号本身精彩。

## 一条命令跑起来

```bash
# 整个分类（9 个策略，每个都做 runonce/runnext 双模式对拍）
pytest tests/functional/strategies/volatility/ -v

# 只跑 SuperTrend
pytest tests/functional/strategies/volatility/test_81_supertrend_strategy.py -v

# 只跑吊灯退出
pytest tests/functional/strategies/volatility/test_111_chandelier_exit_strategy.py -v
```

与迁移型分类不同，本分类 9 个测试全部用 `@pytest.mark.parametrize("runonce", [True, False])` 参数化——向量化与事件驱动两种引擎各跑一遍，指标必须逐位一致，通道计算里任何一处索引错位都逃不过对拍。

## 为什么在这个项目上研究波动率通道

通道类策略是检验回测引擎最好的试金石：ATR 的滚动窗口、通道线的递推携带、翻转点的边界判断，处处是向量化与事件驱动容易分歧的地方。[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 恰好在这上面下重注：runonce/runnext 双模式对拍 + 逐策略指标断言基线（1,152 个策略回归测试），乘数从 3.0 改成 2.5 之后曲线怎么动、是否超出基线，一目了然。纯 Python 引擎比原版快 46%；装上 C++ 后端（`pip install back-trader-cpp`）中位 128 倍加速，ATR 周期 × 乘数的二维参数网格，几分钟扫完。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
