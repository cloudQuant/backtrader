# 网格与马丁格尔：均价网格的数学与纪律

> 量化策略图鉴 · 第 31 篇 · 分类 `grid_trading`（9 个策略）· 2026-09-02

在 MT5 生态里流传最广的策略家族，不是趋势跟踪，而是网格（grid）与马丁格尔（martingale）。原因很简单：它们胜率极高、资金曲线大部分时间平滑向上，回测图漂亮得让人难以拒绝。但金融工程界对它们又长期皱眉——因为这条曲线的尾部，藏着一个等比数列。

先把数学摊开。均价网格的玩法是：浮亏就加仓，越跌加得越多，把持仓成本摊到当前价附近，然后等一次反弹把整篮子一次性解套。它的正期望有严格前提：**市场均值回归 + 保证金足以扛住最大逆行幅度**。一旦单边行情走出 N 层网格且每层按马丁倍数放大，占用保证金按 `base × (1 + 2 + 4 + … + 2^N)` 增长——这是等比数列，第 10 层时单层仓位已经是首仓的 512 倍。机构风险管理（回撤限额、杠杆约束、压力测试）几乎不允许这类头寸结构，而零售平台的高杠杆恰好为它提供了土壤——这就是同一类策略在两个世界命运迥异的全部原因。

本篇解读 `tests/functional/strategies/grid_trading/` 下的 9 个策略。它们全部移植自真实的 MT5 EA，跑在同一份 XAUUSD（黄金现货）M15 数据上（2025-12-03 至 2026-03-10，约 6,129 根 K 线，初始资金 100 万美元、零佣金、100 倍乘数），是一组难得的"同数据同规则"网格实验。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| MoneyRain | XAUUSD H1（M15 重采样） | DeMarker>0.5 做多、≤0.5 做空，固定手数+固定止损止盈 | `test_0001_moneyrain.py` |
| Very Blonde System | XAUUSD M15 | 价格远离近 10 根极值后向极值方向开仓，翻倍手数限价网格，整篮按固定金额止盈 | `test_0002_very_blonde_system.py` |
| Frank_UD | XAUUSD M15 | 多空双腿对冲网格，马丁加仓摊均价 | `test_0003_frank_ud.py` |
| VR-SETKA-3 | XAUUSD M15 | 均价网格：日内极值回撤开首仓，递增距离加层，整篮加权均价统一止盈 | `test_0004_vr_setka_3.py` |
| Exp_Loco | XAUUSD M15 执行 / H8 信号 | Loco 颜色线翻转即反手 | `test_0005_loco.py` |
| RndTrade | XAUUSD M15 | 每 60 分钟掷硬币定向开仓的随机基线 | `test_0006_0463_rndtrade.py` |
| New_Random | XAUUSD M15 | 随机/交替入场 + 对称 50 点止损止盈 | `test_0007_0555_new_random.py` |
| Truly Random Robot | XAUUSD M15 | 硬币定方向，3,000 点宽止损 + 1,000 点窄止盈 | `test_0008_1196_random_robot.py` |
| MartGreg | XAUUSD M15 | 双 MACD 反转入场，亏损后手数翻倍（封顶一次） | `test_0009_1198_martgreg.py` |

## 深读一：VR-SETKA-3——均价网格的教科书样本

[test_0004_vr_setka_3.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/grid_trading/test_0004_vr_setka_3.py) 移植自编号 0767 的 VR-SETKA-3 EA，把均价网格的三个核心构件全部摆上了台面。**首仓信号**看价格从日内极值回撤的百分比，叠加前一根 K 线的阴阳确认：

```python
def _compute_signal(self):
    if len(self) < 2 or not bool(self.p.proc):
        return 0, 0
    close_now = float(self.data.close[0])
    day_high = float(self.data.day_high[0])
    day_low = float(self.data.day_low[0])
    prev_bull = float(self.data.close[-1]) > float(self.data.open[-1])
    prev_bear = float(self.data.close[-1]) < float(self.data.open[-1])
    x = 0.0
    y = 0.0
    if close_now > day_low:
        x = round(close_now * 100.0 / day_low - 100.0, 2)
    if close_now < day_high:
        y = round(close_now * 100.0 / day_high - 100.0, 2)
    sigup = 1 if (-float(self.p.procent) <= y and prev_bull) else 0
    sigdw = 1 if (float(self.p.procent) >= x and prev_bear) else 0
    return sigup, sigdw
```

**加层距离随层数递增**——第 n 层之后，距离变宽，逆行越深、补仓越疏：`dis = (30 + 5 * n) * unit`。**手数按层数线性放大**（马丁系数）：

```python
def _next_lot(self):
    base = self._base_lot()
    if not bool(self.p.martin):
        return base
    factor = max(len(self.layers), 1)
    return self._round_lot(base * factor)
```

**出场只看一件事**：整篮加权均价上移 `plus_points`（单层时则是固定 30 点止盈），一根 K 线触到就全篮平掉——`avg + plus`，其中 `avg = Σ(entry_price × size) / Σ(size)`。三个构件合起来，就是"摊成本、等回归、一把走"。回测窗口内它交出 1,591 笔交易、胜率 67.94%、盈利因子 2.57、终值 1,077,029.70（+7.70%）——但最大回撤 18.70%，且这还只是一段约三个月、未遇极端单边的行情。

## 深读二：MartGreg——给马丁格尔装上刹车

纯网格的风险敞口无上限，聪明的做法是给翻倍逻辑**封顶**。[test_0009_1198_martgreg.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/grid_trading/test_0009_1198_martgreg.py) 的信号端并不"网格"：它在中位价 `(high+low)/2` 上算两条 MACD（快 5/20、慢 10/15，信号线 3 期），要求快线从局部低点拐头、且慢线同向确认才入场；每笔交易挂 500 点止损、1,500 点止盈。马丁格尔只出现在仓位端：

```python
def _calc_lot(self):
    cash = float(self.broker.getcash())
    base_lot = self._calc_base_lot()
    multiplier = 2 ** min(self.loss_streak, self.p.doubling_count)
    lot = self._round_volume_down(base_lot * multiplier)
    lot = min(lot, self.p.volume_max)
    while lot >= self.p.volume_min and cash < lot * self.p.margin_per_lot:
        lot = self._round_volume_down(lot - self.p.volume_step)
    if lot < self.p.volume_min:
        return 0.0
    return round(lot, 8)
```

`2 ** min(loss_streak, doubling_count)` 且 `doubling_count=1`——最多只翻一倍，连亏两次就回归基础手数；最后的 `while` 循环还在保证金不足时逐级减仓，这是把"爆仓数学"改写成"受限加仓"的两个小刹车。结果是一个反直觉的画像：687 笔交易，胜率只有 35.66%，但靠 1,500 点止盈对 500 点止损的盈亏比（加上有限的加倍），终值 1,032,971.20（+3.30%），最大回撤 5.14%——低胜率高盈亏比，与 VR-SETKA-3 的高胜率重回撤正好是马丁光谱的两端。

## 深读三：Truly Random Robot——随机入场，为什么也能不亏？

这个分类里最"离经叛道"的资产是三个随机策略，以 [test_0008_1196_random_robot.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/grid_trading/test_0008_1196_random_robot.py) 为代表：无任何指标，空仓时掷硬币（固定种子 `seed=1`）决定多空，入场后挂 3,000 点止损、1,000 点止盈。909 笔交易、胜率 66.23%、终值 1,005,472.40（+0.55%）、最大回撤仅 0.56%。

随机策略为什么值得进回归库？因为它是**对照组**。任何复杂策略在同一数据上的表现，都必须先和"随机基线"比一比：如果一套指标策略跑不赢硬币+不对称止盈止损，那它的"聪明"就值得怀疑。RndTrade（`test_0006`，每 60 分钟随机换方向，期望收益应近零）和 New_Random（`test_0007`，对称 50 点止损止盈）进一步构成随机家族内部的控制变量——方向随机、盈亏比不对称、节奏固定，三种扰动各自隔离。这是实验设计的思维，而不仅是写策略的思维。

## 其余三席，快速点将

- **MoneyRain**（`test_0001`）：DeMarker 振荡器单指标定向，迁移时把原 EA 的马丁手数简化为固定 0.01 手——又一个"信号保留、杠杆剥离"的净化样本。
- **Very Blonde System**（`test_0002`）：价格离近 10 根 K 线极值超过 240 点后向极值方向开首仓，每 35 点挂一层翻倍限价单，整篮浮盈 40 美元就走，另带保本锁利开关。
- **Frank_UD**（`test_0003`）：多空双腿对冲网格，涨跌都加仓，用虚拟权益曲线管理整体风险——对冲型网格的完整实现。
- **Exp_Loco**（`test_0005`）：H8 周期颜色线翻转即反手，严格说是趋势策略混进了网格班——拿来当"非网格对照组"反而有趣。

## 一条命令跑起来

```bash
# 整个分类（9 个策略，固定 runonce=True，断言迁移时捕获的指标基线）
pytest tests/functional/strategies/grid_trading/ -v

# 只跑 VR-SETKA-3
pytest tests/functional/strategies/grid_trading/test_0004_vr_setka_3.py -v
```

这批 MT5 移植测试每个都把胜率、盈利因子、回撤、SQN 等二十余项指标钉成基线——马丁格尔策略的尾部风险，恰恰最需要这种"每次改动都可比"的工程护栏。

## 为什么在这个项目上研究网格与马丁格尔

网格策略参数多、路径依赖强、对保证金假设极其敏感，是最容易被"调参调出幻觉"的家族——也因此最需要大规模、可复现的回测基础设施。[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 纯 Python 引擎比原版快 46%，1,152 个策略回归测试几分钟跑完；装上 C++ 后端（`pip install back-trader-cpp`）可获得中位 128 倍加速，网格层数、马丁系数、间距参数的敏感性扫描从"过夜任务"变成"喝口咖啡"。runonce/runnext 双模式对拍与指标断言基线，保证你优化的是网格本身，而不是被引擎的数值漂移误导。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
