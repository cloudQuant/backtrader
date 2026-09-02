# 因子动量与轮动：ESG、PCA、低波动与 52 周新高

> 量化策略图鉴 · 第 14 篇 · 分类 `momentum`（45 个策略）· 2026-09-02

裸动量很好懂，但机构真正在用的是"动量 + X"：动量叠低波动、动量叠残差 alpha、动量叠 PCA 主成分。叠法的理由很现实——动量本身会遭遇剧烈崩溃（momentum crash），叠加一个与其相关性低的因子，是性价比最高的风控。行为金融也送来助攻：George 与 Hwang 2004 年发现，**股价距离 52 周高点有多近**，比常规动量因子更能预测未来收益——解释是锚定偏差，投资者盯着 52 周高点这个显眼锚，导致接近新高时"该涨的没涨完"。

本篇从 `momentum` 分类的 45 个策略中，挑出因子叠加与轮动家族逐一拆解。它们几乎全部跑在 XAUUSD 2008-2025 的日线上——黄金这 18 年既有 2011-2015 的漫长熊市，也有 2019-2025 的大牛市，是检验因子组合成色的好考场。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| 贵金属 ROC 轮动 | 金银铂钯日线 | 21/63/252 日复合 ROC 打分，每月轮入最强金属 | `test_0010_momentum_rotation_roc.py` |
| 52 周新高效应 | XAUUSD 日线 | 收盘进入滚动高点 75%-98% 区间且站上 200SMA 入场 | `test_0014_52week_high_effect.py` |
| Alpha 动量 | GLD/GDX/XAGUSD/IEF 日线 | 对 IVV 滚动回归取 alpha，做多大 alpha、做空小 alpha | `test_0017_alpha_momentum.py` |
| PCA 动量 | XAUUSD 日线 | 标准化收益的 63 日累积和作为主成分代理，上穿 0 做多 | `test_0019_pca_momentum_quantstrat.py` |
| 低波动+动量复合 | XAUUSD 日线 | 低波动排名与动量排名取平均，复合分 >0.6 持有、<0.4 清仓 | `test_0023_lowvol_momentum_value_momentum.py` |
| 双周期动量 | XAUUSD 日线 | 20 日与 60 日动量同为正才做多 | `test_0024_online_momentum.py` |
| ESG 动量 | XAUUSD 日线 | 120 日动量为正 + 60 日低波动排名 >0.5 才入场 | `test_0025_esg_momentum.py` |
| 五因子动量组合 | IVV/IWM/GLD/IEF/DBC 日线 | 经典/残差/趋势/重叠/短周期五个动量分信号反比波动加权 | `test_0026_momentum_combination_strategy.py` |
| Elder 冲动系统 | XAUUSD M15 | EMA 定方向、MACD 柱定动能，K 线涂色绿红蓝 | `test_0031_1052_elder_impulse.py` |
| 区间扩张指数 REI | XAUUSD M15+H8 | 有界振荡器度量区间扩张/收缩，阈值穿越入场 | `test_0032_1054_range_expansion_index.py` |
| 锚定动量 | XAUUSD M15+H4 | 100×(EMA/SMA−1) 度量动量，上下阈值对称穿越 | `test_0033_1228_anchored_momentum.py` |

## 深读一：Momentum Rotation ROC——横截面轮动的诚实答卷

[test_0010_momentum_rotation_roc.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/momentum/test_0010_momentum_rotation_roc.py) 在金银铂钯四个贵金属上做横截面轮动。打分用三个周期的 ROC 加权混合（权重 0.2/0.3/0.5，长期占比最重）：

```python
periods = [int(x) for x in params.get('roc_periods', [21, 63, 252])]
weights = [float(x) for x in params.get('roc_weights', [0.2, 0.3, 0.5])]
for period, weight in zip(periods, weights):
    roc = (close_df - close_df.shift(period)) / close_df.shift(period) * 100.0
    score_df = score_df.add(roc * weight, fill_value=0.0)
...
selected = day_scores.head(top_n).index.tolist()   # top_n=1，每月只持最强
for symbol in selected:
    current_weights[symbol] = 1.0 / top_n
```

结果堪称"反营销"：终值 894,549，**总收益 −10.55%**，最大回撤 46.41%，Sharpe 0.03——尽管胜率有 60%。原因不难找：四个贵金属彼此相关性极高，"轮动"实际是在同一根趋势线上反复换车，2013-2015 贵金属齐跌时无处分散。回归测试把这个亏损结果钉进断言，价值正在于此：**横截面动量需要真正低相关的资产池**，这不是参数能修好的。它同时示范了信号前置的工程范式——打分、排名、权重全部在 pandas 里预计算成信号列，`next()` 只负责按 flag 下单，回测引擎因此可以放心走向量化快路径。

## 深读二：ESG Momentum——动量 × 低波动的正交叠加

[test_0025_esg_momentum.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/momentum/test_0025_esg_momentum.py) 名字里带 ESG，内核是"动量 + 稳定性"的组合过滤。特征只有三行：

```python
out['momentum'] = out['close'].pct_change(mom_period)        # 120 日动量
vol = ret.rolling(vol_period).std()                           # 60 日收益波动
out['vol_score'] = 1.0 - vol.rolling(min(252, len(vol))).rank(pct=True)  # 波动越低分越高
out['signal'] = ((out['momentum'] > 0) & (out['vol_score'] > 0.5)).astype(float)
```

每 63 个交易日检查一次：动量为正**且**波动率处于历史低半区才持有，任一条件破坏就清仓。同一份黄金数据，这个"双条件"版本终值 3,857,492（**+285.75%**），胜率 81.25%，最大回撤 19.19%，Sharpe 0.90——对比第 13 篇裸时序动量的 23.30% 回撤，低波动过滤确实削掉了最痛的一段。动量负责方向、低波动负责质量，这就是"因子叠加强化"最直观的教材案例。63 天的低频再平衡同样值得注意：它把动量最常见的成本杀手——过度交易——直接锁死，整个 18 年只动了二十几次仓位。

## 深读三：52 周新高效应——不突破，只贴近

[test_0014_52week_high_effect.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/momentum/test_0014_52week_high_effect.py) 把 George-Hwang 的发现规则化。它不追突破，而是在"接近但未达到"滚动高点时入场：

```python
rolling_high = out['high'].rolling(lookback_days).max().shift(1)   # lookback_weeks=26
ratio = out['close'] / rolling_high
trend_ma = out['close'].rolling(trend_ma_days).mean()              # 200SMA
near_high = ((ratio >= lower_threshold) & (ratio <= upper_threshold)).astype(float)  # 0.75~0.98
trend_filter = (out['close'] > trend_ma).astype(float)
entry_signal = ((near_high > 0.5) & (trend_filter > 0.5)).astype(float)
```

出场三选一：ratio 跌破 0.7、收盘跌回 200SMA 之下、或持仓满 63 天。终值 2,992,579（+199.26%），胜率 32.65%、盈利因子靠长尾盈利撑起，Sharpe 0.57，最大回撤 30.61%。注意一个实现细节：配置里 `lookback_weeks=26`，滚动窗口实际是 26 周（130 个交易日）而非名字里的 52 周——**策略名与参数是两回事，读源码时永远以参数为准**，这也是回归测试把参数写死在文件里的意义。

## 其余策略，快速点将

- **Alpha 动量**（`test_0017`）：对 IVV 做滚动回归取截距 alpha，多高 alpha 空低 alpha——横截面动量的"市场中性改造"。
- **五因子组合**（`test_0026`）：经典 12 个月、残差、长期均线趋势、重叠周期、短周期五个动量信号排名后反比波动加权，是本分类工程最重的一个。
- **PCA 动量**（`test_0019`）：用标准化收益的滚动累积和当主成分代理，绕开真正的矩阵分解。
- **低波动+动量复合分**（`test_0023`）：两个因子各自百分位排名取平均，0.6/0.4 双阈值带滞回，比单阈值抗折腾。
- **Elder 冲动系统**（`test_0031`）：Alexander Elder 的三色 K 线——EMA13 定趋势、MACD 柱定动能，颜色翻转即交易。
- **锚定动量**（`test_0033`）：100×(EMA−SMA)/SMA，用两条均线的Spread度量动量，对称阈值穿越入场。

## 一条命令跑起来

```bash
# 整个分类（45 个策略）
pytest tests/functional/strategies/momentum/ -v

# 只跑 ESG 动量
pytest tests/functional/strategies/momentum/test_0025_esg_momentum.py -v
```

内联回归测试在 `runonce=True` 下对终值、胜率、回撤逐项断言；参数化测试则以 runonce/runnext 双模式对拍，两种引擎数值不一致即刻报警。

## 为什么在这个项目上研究因子动量

因子叠加的评估是典型的"大量回测、频繁迭代"：换一个权重、加一个过滤就要重跑全程。[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 纯 Python 引擎比原版快 46%，C++ 后端（`pip install back-trader-cpp`）中位 128 倍加速，让 0.2/0.3/0.5 换成 0.3/0.3/0.4 这种实验从分钟级降到秒级。1,152 个策略回归测试加指标断言基线，保证你比较的是因子效果，而不是引擎漂移；runonce/runnext 双模式对拍则守住向量化与事件驱动的一致性底线。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
