# 配对交易：金银协整、卡尔曼滤波与 Copula——统计套利六百年谚语的科学化

> 量化策略图鉴 · 第 24 篇 · 分类 `pairs_trading`（22 个策略）· 2026-09-02

"金银比会回归"是交易员挂在嘴边几百年的直觉，但让它变成一门生意的，是 1980 年代 Morgan Stanley 的统计套利小组：Gerry Bamberger 最先发现按行业配对做空做多能对冲市场风险，Nunzio Tartaglia 的团队随后把这套"配对交易"系统化，成员里还有日后写出《黑天鹅》的 Nassim Taleb。这个年化一度惊人的小组证明了一件事：**不用预测方向也能赚钱，只需赌"价差回归"**。

配对交易的核心概念是协整而非相关：相关是"一起涨跌"，协整是"差不太多"——两只股票可以各自随机漫游，只要它们的价差始终被一条均值引力拽住，做空贵的、做多便宜的就有正期望。本篇解读 `tests/functional/strategies/pairs_trading/` 下的 22 个策略：从固定对冲比率的金银 z-score，到卡尔曼滤波动态 beta，再到用 Copula 捕捉尾部依赖的进阶版。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| 金银配对 | XAUUSD/XAGUSD 小时线 2025 | 对数价差+固定对冲比率，滚动 z-score 阈值交易 | `test_0002_gold_silver_pairs_trading.py` |
| 卡尔曼滤波配对 | XAUUSD/XAGUSD 小时线 | Kalman 动态估计对冲比率，beta 稳定性过滤 | `test_0001_gold_kalman_filter_pairs_trading.py` |
| Copula 配对 | XAUUSD/XAGUSD 日线 2018-2025 | Clayton copula 条件概率找相对错价 | `test_0007_copula_pairs_trading.py` |
| 协整价差 | 金银日线 | 协整检验定价差，z-score 入场 | `test_0003_gold_cointegration_spread.py` |
| 协整金银（回归版） | 金银日线 | Engle-Granger 式残差交易 | `test_0006_cointegrated_gold_silver.py` |
| 距离配对 | XAUUSD 日线 | Gatev 1999：标准化价格距离最小化配对 | `test_0013_distance_pairs_trading.py` |
| 多配对组合 | 金/银/铂/钯日线 | 贵金属篮子内多对同时交易 | `test_0004_gold_multi_pair_trading.py` |
| 零穿越配对 | 金银小时线 | 赌价差穿越零轴而非回归带 | `test_0005_zero_crossing_pairs.py` |
| 实战配对 | 金银小时线 | 带执行细节的工程版 | `test_0009_practical_pairs_trading.py` |
| 加元原油配对 | USDCAD/BNO 日线 | 汇率与油价的宏观配对 | `test_0014_cad_crude_pairs_strategy.py` |
| Renko/Kagi 配对 | 金银小时线 | 非标准K线过滤配对信号 | `test_0015_renko_kagi_pairs_strategy.py` |
| Copula（变体） | XAUUSD 日线 | 另一份 copula 参数化实现 | `test_0011_copula_pairs_trading.py` |
| 基础/通用配对族 | XAUUSD 日线等 | 教科书式 z-score 配对的多个实现 | `test_0008` / `test_0010` / `test_0012` / `test_0016` |
| **MT5 EA 移植族** | XAUUSD 15 分钟 | 单腿 EA 策略（对冲/挂单/TRIX/Laguerre/VLT 等） | `test_0017`–`test_0022` |

## 深读一：金银配对——z-score 三件套：入场、回归、止损

教科书配对交易的全部要素在 [test_0002_gold_silver_pairs_trading.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/pairs_trading/test_0002_gold_silver_pairs_trading.py) 里一页看完。第一步定义对数价差（固定对冲比率 `hedge_ratio=1.0`）：

```python
def _spread(self):
    gold_price = max(float(self.gold.close[0]), 1e-6)
    silver_price = max(float(self.silver.close[0]), 1e-6)
    return math.log(gold_price) - float(self.p.hedge_ratio) * math.log(silver_price)
```

第二步对价差做 192 根 K 线的滚动 z-score；第三步用三条阈值管理头寸：

```python
if not has_position:
    if zscore <= -float(self.p.entry_threshold):      # entry = 2.0，价差过低：买金卖银
        self._open_long_spread()
    elif zscore >= float(self.p.entry_threshold):     # 价差过高：卖金买银
        self._open_short_spread()
    return
if abs(zscore) <= float(self.p.exit_threshold) or abs(zscore) >= float(self.p.stop_threshold):
    self._close_all()     # exit = 0.5 回归零轴平仓；stop = 3.0 价差失控认赔
```

两腿各自按 5% 名义敞口 sizing（`max_notional_pct=0.05`）。**回测结果**：金银 H1 数据 2025-07 至 2025-12 共 2,986 根 K 线，102 笔配对交易，46 胜 56 负（胜率 45.1%），终值 990,238（-0.98%），Sharpe -1.91，最大回撤仅 1.67%。小仓位让亏损可控，但固定 `hedge_ratio=1.0` 是明显短板——金银比中枢过去二十年从 60 漂到 120，静态比率必然吃亏，这正好引出第二读。

## 深读二：卡尔曼滤波——让对冲比率自己动起来

如果价差关系会漂移，就把对冲比率 β 做成状态量在线估计。[test_0001_gold_kalman_filter_pairs_trading.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/pairs_trading/test_0001_gold_kalman_filter_pairs_trading.py) 用一维卡尔曼滤波逐根更新"1 盎司金对多少盎司银"：

```python
def update(self, price_a, price_b):
    beta_pred = self.beta
    P_pred = self.P + self.Q                       # 过程噪声 Q = 0.0005
    denominator = P_pred * price_b * price_b + self.R   # 观测噪声 R = 1.0
    K = (P_pred * price_b) / denominator           # 卡尔曼增益
    innovation = price_a - beta_pred * price_b     # 残差 = 新价差信息
    self.beta = beta_pred + K * innovation         # β 随新信息自适应
    self.P = (1.0 - K * price_b) * P_pred
    spread = price_a - self.beta * price_b
    return self.beta, spread
```

初始 `initial_beta=78.0`（大致对应历史金银比），此后完全数据驱动。更精彩的是它的"β 稳定性闸门"：近 96 根 K 线 β 的变异系数（`std/mean`）不超过 0.03 才允许开仓——关系不稳时宁可不做：

```python
if self.current_zscore <= -float(self.p.entry_threshold) and is_stable:
    self._submit_pair_orders(1, price_a, price_b)   # entry = 2.0，exit = 0.35，stop = 3.25
```

**回测结果**：同一份 H1 数据，103 次平仓（61 胜 42 负，胜率 59.2%，含 9 次止损），终值 997,507（-0.25%）。与深读一对照：胜率从 45% 提到 59%，回撤更小——动态 β 的价值不在多赚，而在少错。

## 深读三：Copula 配对——不只看价差，还看"一起极端吗"

z-score 隐含假设价差服从椭圆分布，但金银真正的耦合藏在尾部：恐慌时金涨银跌可以同时极端。Copula 直接对"联合分布"建模（[test_0007_copula_pairs_trading.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/pairs_trading/test_0007_copula_pairs_trading.py)）：先用 252 天滚动窗口的 Kendall τ 估计 Clayton copula 参数（Clayton 擅长捕捉下尾依赖），再算"给定金的当日分位，银的条件概率"：

```python
tau = stats.kendalltau(u, v).correlation
theta = 2.0 * tau / max(1e-6, 1.0 - tau)       # τ → θ
def clayton_conditional(u, v, theta):
    term1 = u ** (-(theta + 1.0))
    term2 = (u ** (-theta) + v ** (-theta) - 1.0) ** (-(theta + 1.0) / theta)
    return term1 * term2                        # P(V<=v | U=u)
```

条件概率的读法：`P(V<=v|U=u)` 接近 0，说明"金没怎么动、银却相对暴跌"——银被错杀，买银卖金（腿权按滚动 β 对冲）。信号阈值：

```python
if prob_v_given_u < entry_threshold:            # 0.05，银显著便宜
    position = 1
elif prob_v_given_u > 1.0 - entry_threshold:    # 银显著贵
    position = -1
if abs(prob_v_given_u - 0.5) <= exit_band:      # 0.10，回到中性带平仓
    position = 0
```

**回测结果**：金银日线 2018-2025 共 1,812 根，292 笔交易 136 胜（胜率 46.6%），终值 986,607（-1.34%），Sharpe -0.24。三个深读策略全都没赚大钱，这不是意外：价差越来越有效的市场里，简单的统计套利早已不是印钞机。回归测试库如实收录，正是为了给"配对交易容易吗"提供诚实的基线答案——改进方向（更长持有期、跨品种篮子、成本模型）在其余策略里各有示例。

## 其余策略，快速点将

- **距离配对**（`test_0013`）：Gatev 1999 论文的经典做法——标准化价格距离最小的一对，回归即平，最"考古"的一版。
- **多配对组合**（`test_0004`）：金/银/铂/钯四金属两两组合，分散单一价差的风险。
- **加元原油**（`test_0014`）：宏观逻辑配对——加拿大经济绑油，USDCAD 与 BNO 的价差交易。
- **Renko/Kagi**（`test_0015`）：用非标准K线给配对信号降噪。
- **EA 移植族**（`test_0017`–`test_0022`）：MT5 单腿策略（LBS、定时挂单、TRIX、最简对冲、Laguerre、VLT Trader）混住在本目录，是历史迁移的如实写照，拿来研究 15 分钟级执行细节很方便。

## 一条命令跑起来

```bash
# 整个分类（22 个策略）
pytest tests/functional/strategies/pairs_trading/ -v

# 只跑金银配对
pytest tests/functional/strategies/pairs_trading/test_0002_gold_silver_pairs_trading.py -v
```

## 为什么在这个项目上研究配对交易

配对交易是回测引擎最严格的考场：多数据源时间戳对齐、双腿同时下单、净空头的保证金计算、逐笔佣金——任何一环出错，价差信号再对也是白搭。[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 为此提供经 1,152 个策略回归测试锤炼的多资产基建：纯 Python 引擎比原版快 46%，C++ 后端（`pip install back-trader-cpp`）中位 128 倍加速，z-score 窗口、阈值、对冲模式的一轮参数扫描几分钟出结果；runonce/runnext 双模式对拍与指标断言基线，保证价差的每一次漂移来自市场而非引擎。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
