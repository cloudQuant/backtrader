# 布林带与通道回归：squeeze 与触带反转的两种剧本

> 量化策略图鉴 · 第 09 篇 · 分类 `mean_reversion`（331 个策略）· 2026-09-02

1980 年代，John Bollinger 在遍历了各种"固定宽度通道"之后顿悟：通道宽度不该是拍脑袋的常数，而应该跟着波动率走——于是有了用标准差定宽的布林带。但有趣的是，同一副带子，交易者写出了两种完全相反的剧本：**触带反转**派认为价格碰带是被"橡皮筋"拉扯过度、要回到中轨；**squeeze 突破**派则认为带宽收窄到极致（波动率压缩）之后的第一次突破，是趋势爆发的起跑线。一个赌回归，一个赌延续——布林带成了检验"均值回归 vs 动量"这场百年争论的最公平试验场。

本仓库 `mean_reversion` 分类下约 18 个布林带与通道策略恰好两派俱全，还夹着 ADX、RSI、KDJ 各种过滤器的叠加实验。逐个看。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| Bollinger 触带反转（EA 0616） | XAUUSD M15 | 80 期 3σ 带，整根 K 线压在下带与中轨之间做多 | `test_0140_0616_bollinger.py` |
| BB Squeeze（TTM 式） | XAUUSD M15 | 布林带收进肯特纳通道后"释放"，按动量方向追突破 | `test_0224_1300_bb_squeeze.py` |
| BBands Stop | XAUUSD M15/H4 | 布林带轨道翻转生成趋势跟踪止损线 | `test_0221_1244_bbands_stop.py` |
| BB 网格加仓（N Positions） | XAUUSD M15 | 跌破下带逆势金字塔加仓至 9 个仓位，50 点 SL/TP | `test_0137_0600_bollinger_bands_n_positions.py` |
| Boll 突破 | 上证 sh600000 | 连续 2 根收上带做多，穿中轨平仓 | `test_26_boll_strategy.py` |
| Boll 反转 | 上证 sh600000 | 突破上带做空、跌破下带做多（逆势版） | `test_27_boll_reverser_strategy.py` |
| BB + EMA | 上证 sh600000 | 布林带与 EMA 双指标确认 | `test_28_boll_ema_strategy.py` |
| BB + ADX | 上证 sh600000 2000-2022 | ADX<40（无趋势）时触带回归，带价挂止损单 | `test_31_bb_adx_strategy.py` |
| BB 中轨回归 | ORCL 日线 | 跌出下带后收复中轨买入、升出上带后跌回中轨卖出 | `test_68_bollinger_bands_strategy.py` |
| BB + RSI | ORCL 日线 2010-2014 | RSI<30 且收盘低于下带做多；RSI>70 或升破上带离场 | `test_97_bb_rsi_strategy.py` |

## 深读一：BB Squeeze——波动率压缩后的爆发

TTM Squeeze 是 John Carter 的招牌：当布林带（默认 20 期 2σ）整条缩进肯特纳通道（20 期 1.5 倍 ATR）内部，市场处于"低波动挤压"状态，而波动率聚集性告诉我们——**平静之后往往不是更平静**。仓库实现（[test_0224_1300_bb_squeeze.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/mean_reversion/test_0224_1300_bb_squeeze.py)）用 squeeze 开关加动量线写成一个小状态机：

```python
params = dict(
    bb_period=20, bb_dev=2.0,    # 布林带：20 期 2σ
    kc_period=20, kc_mult=1.5,   # 肯特纳通道：20 期 1.5×ATR
    mom_period=12,               # 动量线定方向
)
squeeze_released = sq1 > 0 and sq0 < 0   # 带从通道内膨胀到通道外 → 释放
squeeze_fired   = sq1 < 0 and sq0 > 0    # 重新缩回通道内 → 点火失败

if squeeze_released and mom0 > 0:
    self.buy(size=self.p.lot)     # 释放 + 动量向上 → 追多
if squeeze_released and mom0 < 0:
    self.sell(size=self.p.lot)    # 释放 + 动量向下 → 追空
```

出场同样干脆：squeeze 重新点火（打回通道内）或动量翻向，立即离场甚至反手。3 个多月的 M15 窗口里做了 309 笔、126 胜（胜率 40.78%），但盈利因子 1.27、终值 +6,196——典型的"低胜率高盈亏比"形态，方向对了吃趋势、错了快认损。注意它是均值回归目录里的"叛徒"：squeeze 释放后它是顺势的，正好和下一篇形成镜像。

## 深读二：Bollinger 0616——最古典的触带反转

最"教科书"的版本反而参数最保守：80 期、3 倍标准差（[test_0140_0616_bollinger.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/mean_reversion/test_0140_0616_bollinger.py)）。更妙的是入场条件要求**整根 K 线**处在带与中轨之间，过滤掉上影下影的"假触碰"：

```python
self.bbands = bt.indicators.BollingerBands(self.data.close, period=80, devfactor=3.0)

buy_sig  = low < lower and high < middle    # 整根 K 线压在下带下方且不碰中轨 → 做多
sell_sig = high > upper and low > middle    # 整根 K 线顶在上带上方且不沾中轨 → 做空

# 没有止损止盈；反向信号只在浮盈时才允许先平后反手
if self.position.size > 0 and sell_sig and pnl > 0:
    self.pending_reentry = 'sell'
    self.order = self.close()
```

3σ 的带宽有多挑剔？6,050 根 M15 里它只出手了 **4 次**，全部盈利——但终值 999,218.55，扣掉手数极小（0.01 手）的利息级利润后基本原地踏步。这个基线的价值在于告诉你：把阈值收到极致，胜率可以到 100%，代价是机会几乎为零。交易系统设计的核心矛盾——**信号质量 vs 信号数量**——在这个测试里被量化得明明白白。

## 深读三：BB + ADX——用趋势强度给触带反转上保险

触带反转最怕的就是"单边趋势里接飞刀"：价格贴着上带走一个月，摸高做空的全被碾过去。经典解法是加 ADX 过滤——ADX 高说明趋势强、别逆势；ADX 低说明是震荡市、回归概率大。仓库实现（[test_31_bb_adx_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/mean_reversion/test_31_bb_adx_strategy.py)）在浦发银行 22 年日线（2000-2022，5,388 根）上跑这套逻辑：

```python
params = (('BB_MA', 20), ('BB_SD', 2), ('ADX_Period', 14), ('ADX_Max', 40))

if self.adx[0] < self.params.ADX_Max:    # 只有趋势不强时才做回归
    # 昨收在下带之下、今收回到带内 → 回归开始，买入
    if (self.data.close[-1] < self.bb.lines.bot[-1]) and \
       (self.data.close[0] >= self.bb.lines.bot[0]):
        self.order = self.buy()
        self.stopprice = self.bb.lines.bot[0]
        self.closepos = self.sell(exectype=bt.Order.Stop, price=self.stopprice)  # 带价止损单
```

两个细节值得抄：入场不是碰带而是"**收复带沿**"（从带外回到带内），等回归真的启动；同时反手挂一张以带价为触发价的止损单，跌破带立刻自动出局。即便如此，诚实的结果是 293 笔只有 59 胜、终值 99,971.15——微亏收场。而且这个测试用 `@pytest.mark.parametrize("runonce", [True, False])` 在向量化与事件驱动两种引擎下各跑一遍并要求断言同时成立，正是全库双模式对拍的一个缩影。

## 其余策略，快速点将

- **BB 网格加仓**（`test_0137`）：逆势派的激进形态——跌破下带不止一次买入，而是金字塔加到 9 个仓位摊成本，配 50 点止损止盈与追踪止损。
- **BBands Stop**（`test_0221`）：布林带反过来当**移动止损线**用——轨道翻转向下时止损线变阻力，H4 信号、M15 执行。
- **Boll 突破 vs Boll 反转**（`test_26`/`test_27`）：同一副 20/2 带，一个顺势（连收两根带上做多）一个逆势（摸带反转），同一个上证数据——天然的 A/B 对照实验。
- **BB + RSI**（`test_97`）：双重超卖确认——RSI<30 且收盘低于下带才做多，ORCL 五年只出手十几次，终值 100,120.94。
- **BB 中轨回归**（`test_68`）：不猜带沿反弹，老老实实等价格穿越中轨才进出场——用更晚的入场换更高的确定性。

## 一条命令跑起来

```bash
# 整个分类（331 个策略，runonce/runnext 双模式自动对拍）
pytest tests/functional/strategies/mean_reversion/ -v

# 只跑 BB Squeeze
pytest tests/functional/strategies/mean_reversion/test_0224_1300_bb_squeeze.py -v
```

## 为什么在这个项目上研究布林带策略

布林带家族天生适合做对照研究：同一副带子，反转与突破两个方向、几十种过滤器组合，每个变体之间的差异只有靠**同引擎、同数据、可复现**的批量回测才能分清。这正是 [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 提供的：纯 Python 引擎比原版快 46%，1,152 个策略回归测试全量断言在库；装上 C++ 后端（`pip install back-trader-cpp`）中位 128 倍加速，扫一遍"周期 × 标准差 × 过滤器"网格只是几分钟的事；runonce/runnext 双模式对拍保证每一组对照都公平。想系统比较两种剧本，从这里开始最省力。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
