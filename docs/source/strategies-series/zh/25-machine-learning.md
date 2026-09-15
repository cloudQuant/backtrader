# 机器学习策略：从 KMeans 聚类到强化学习，回测库偏爱"能断言的 ML"

> 量化策略图鉴 · 第 25 篇 · 分类 `machine_learning`（21 个策略）· 2026-09-02

提到"机器学习交易"，多数人脑中浮现的是深不见底的黑箱神经网络。但翻开本仓库 `tests/functional/strategies/machine_learning/` 的 21 个策略，你会发现另一种风景：真正能进回归测试库的 ML 策略，几乎都把模型压缩成了**一条可以断言的规则**——一个合成评分、一个聚类编号、一个伪 Q 值。

这并非偷懒，而是工程选择。黑箱输出的微小漂移就能让回测结果面目全非，而"评分超过 0.6 开多"这样的规则可以钉进测试断言，任何时候重跑都能验证引擎有没有被改坏。本篇解读这 21 个策略中的三个代表：合成评分、KMeans 状态分类，以及"假装在强化学习"的 q_score。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| KMeans K 线分类 | XAUUSD 日线 2022-2025 | 滚动 KMeans 对 ATR 归一化 K 线形态聚类，跟"活跃簇" | `test_0001_candlestick_kmeans_classification_gold.py` |
| 极端短期涨幅 | XAUUSD 日线 2008-2025 | 检测多日大涨后次日回调入场，固定持有期离场 | `test_0002_extreme_short_term_gain.py` |
| Gold ML Prediction | XAUUSD 日线 2008-2025 | RSI/均线趋势/波动率排名三分数合成，超 0.6 开多 | `test_0003_gold_ml_prediction.py` |
| Reinforcement Learning | XAUUSD 日线 2008-2025 | RSI 归一 + 价格偏离均线合成 q_score，过 ±0.2 触发 | `test_0004_reinforcement_learning.py` |
| 随机森林财务比率 | IVV/IWM/IWD/PDP/DBMF 日线 | 随机森林对合成财务比率特征分类选品种 | `test_0005_random_forest_financial_ratios_strategy.py` |
| 情绪信号 | XAUUSD 日线 2008-2025 | 收益率与成交量 z 值合成情绪代理，阈值控制敞口 | `test_0006_sentiment_signal_strategy.py` |
| Heads or Tails | XAUUSD M5 | 随机数驱动的抛硬币式开平仓（EA 移植） | `test_0007_0007_heads_or_tails.py` |
| 0187 RNN | XAUUSD M15 2025-2026 | RSI 状态 + 手工概率混合出信号，对称止损止盈 | `test_0008_0187_rnn.py` |
| SkyscraperFix + ColorAML | XAUUSD M15 执行 / H4 信号 | 双子系统信号 + 连亏后资金管理降档 | `test_0009_0238_exp_skyscraper_fix_coloraml_mmrec.py` |
| SkyscraperFix 三系统 | XAUUSD M15 执行 / H4 信号 | A/B/C 三子系统按优先级触发，分级风控 | `test_0010_0240_exp_skyscraper_fix_coloraml_x2macandle_mmrec.py` |
| AIS2 Trading Robot | XAUUSD M1 | 分钟级 EA 机器人移植（含点差过滤） | `test_0011_0384_ais2_trading_robot.py` |
| Donchain Counter | XAUUSD M15 / H1 双周期 | 高周期 Donchian 突破 + 冷却期与跟踪止损 | `test_0012_0429_donchain_counter.py` |
| Daily Breakpoint | XAUUSD H1 | 日内断点价位驱动的 EA 移植 | `test_0013_0514_daily_breakpoint.py` |
| 0688 Fuzzy Logic | XAUUSD M15 2025-2026 | Gator/WPR/RSI/Demarker/AC 五指标模糊合成打分 | `test_0014_0688_fuzzy_logic.py` |
| 0715 MTC 神经网络 + MACD | XAUUSD H1 | 神经网络指标叠加 MACD 的 EA 移植 | `test_0015_0715_mtc_neural_network_plus_macd.py` |
| ZeroLagEA-AIP | XAUUSD M15 | 零滞后均线族 EA 移植 | `test_0016_0726_zerolagea_aip_v0_0_4.py` |
| 0797 Artificial Intelligence | XAUUSD M15→M30 | 价格加减速灌进感知机式线性打分触发双向 | `test_0017_0797_artificial_intelligence.py` |
| 1086 Cronex Chaikin | XAUUSD M15 / H4 信号 | Chaikin A/D 与自适应均线交叉 | `test_0018_1086_cronex_chaikin.py` |
| 1154 Artificial Intelligence | XAUUSD M15 | 另一版感知机式 AI 指标 EA 移植 | `test_0019_1154_artificial_intelligence.py` |
| 1225 AML | XAUUSD M15 | AML 自适应均线 EA 移植 | `test_0020_1225_aml.py` |
| JBrainSig1 + Ultra RSI | XAUUSD M15 | 趋势信号引擎与平滑 RSI 动量层合成 | `test_0021_1293_jbrainsig1_ultra_rsi.py` |

## 深读一：Gold ML Prediction——三个分数，一个信号

ML 在策略里有两种典型姿势：**信号合成器**与**状态分类器**。前者把多个特征压缩成一个评分再设阈值，后者（下节的 KMeans）把市场状态离散化。[test_0003_gold_ml_prediction.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/machine_learning/test_0003_gold_ml_prediction.py) 是合成器的教科书样本——RSI 得分、均线趋势得分、波动率排名得分，三者平均：

```python
# RSI score (0-1, oversold=1)
rsi = 100 - (100 / (1 + rs))
out['rsi_score'] = 1.0 - rsi / 100.0

# MA score (fast > slow = 1)
fast_ma = out['close'].rolling(ma_fast).mean()      # ma_fast = 20
slow_ma = out['close'].rolling(ma_slow).mean()      # ma_slow = 60
out['ma_score'] = (fast_ma > slow_ma).astype(float)

# Vol score (low vol = high score)
vol = ret.rolling(vol_period).std()                 # vol_period = 20
out['vol_score'] = 1.0 - vol.rolling(min(252, len(vol))).rank(pct=True)

# Composite
out['composite_score'] = (out['rsi_score'] + out['ma_score'] + out['vol_score']) / 3.0
```

下单规则只有两行判断：`score > threshold（0.6）` 满仓做多，`score < 1.0 - threshold（0.4）` 平仓。没有模型文件、没有随机种子，一切都可复现。XAUUSD 2008-2025、100 万初始资金、0.02% 佣金下，基线断言：39 笔交易 20 胜 18 负（胜率 51.28%），终值 3,334,048.03（+233.40%），盈利因子 2.451，Sharpe 0.636，最大回撤 34.93%。注意它的三个分数全部来自价格本身——所谓"ML"，其实是一次手工特征工程。这正是回测库的偏好：**可解释、可断言、可回归**。

## 深读二：KMeans K 线聚类——70 笔全亏的样本外教训

[test_0001_candlestick_kmeans_classification_gold.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/machine_learning/test_0001_candlestick_kmeans_classification_gold.py) 是分类器姿势，也是本分类最诚实的一课。它把每根 K 线的三个比值特征（上影、下影、实体，均除以 ATR 归一化）喂给 KMeans，在 756 交易日训练窗上拟合、每 20 日重拟合一次，然后挑出"次日期望收益高于基准"的活跃簇：

```python
fitted_model = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)  # n_clusters=4
train_labels = fitted_model.fit_predict(train_x)
cluster_stats = train.groupby("cluster")["next_intraday_return"].agg(["mean", "count"])
benchmark = float(train["next_intraday_return"].mean())
eligible = cluster_stats[cluster_stats["count"] >= min_cluster_size]      # min_cluster_size=20
if not eligible.empty and float(eligible.iloc[0]["mean"]) > benchmark:
    active_cluster = float(eligible.index[0])
```

当当前 K 线被预测落入活跃簇，次日开盘买入、当日收盘前强制平仓。信号经过 `shift(1)` 对齐，避免了前视偏差。结果如何？2022-2025 年 XAUUSD 上 262 个交易日、70 笔交易——**胜 0 笔，负 70 笔**。测试断言 `win_count == 0`、`loss_count == 70`，把这场全败钉成了基线。训练窗内簇的统计优势一到样本外就蒸发，这是无监督聚类在低信噪比金融数据上的典型过拟合样本，比任何教科书说教都直观。

## 深读三：Reinforcement Learning——q_score 不是 Q 值

[test_0004_reinforcement_learning.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/machine_learning/test_0004_reinforcement_learning.py) 名字最唬人，内核却极简。它计算一个"q_score"——RSI 偏离 50 的归一值与价格偏离 50 日均线比例的均值：

```python
ma = out['close'].rolling(ma_period).mean()         # ma_period = 50
rsi_norm = (out['rsi'] - 50) / 50.0                 # rsi_period = 14
trend = (out['close'] - ma) / ma
out['q_score'] = (rsi_norm + trend) / 2.0
```

交易规则：空仓时 `q > 0.2` 买入，持仓时 `q < -0.2` 平仓。没有环境、没有奖励更新、没有 Bellman 方程——它是"强化学习式"的状态-动作映射，而非真正的 RL。工程点评：真 RL 的回测几乎不可能做成确定性回归（训练本身的随机性就会让每次结果漂移），而这种"冻结的决策函数"保留了 RL 的形，丢掉了不可复现的魂。它的基线同样老实：56 笔交易胜率 41.07%，终值 1,956,006.56（+95.60%），最大回撤 44.85%，Sharpe 0.348——赚得多，颠簸也大。

## 其余策略，快速点将

- **极端短期涨幅**（`test_0002`）：检测多日大涨的"极端事件"，等次日回调进场、固定持有期离场——事件驱动式特征工程。
- **随机森林财务比率**（`test_0005`）：真 sklearn 随机森林，对五只 ETF 的合成财务比率分类；缺 sklearn 时整个模块优雅跳过。
- **情绪信号**（`test_0006`）：没有新闻数据？用收益率 z 值 × 成交量 z 值造一个情绪代理，照样可回测。
- **0187 RNN / 0688 模糊逻辑 / 0715 神经网络+MACD / 0797、1154 感知机**（`test_0008/0014/0015/0017/0019`）：一批 MT5 EA 移植——名字带"神经网络"，实为指标库里的固定权重网络，是研究"ML 话术 vs ML 实质"的好素材。
- **1225 AML / ZeroLagEA / JBrainSig1+UltraRSI**（`test_0020/0016/0021`）：自适应均线与趋势信号引擎的 EA 族，逻辑全部确定性可断言。

## 一条命令跑起来

```bash
# 整个分类（21 个策略，runonce=True 单模式）
pytest tests/functional/strategies/machine_learning/ -v

# 只跑 Gold ML Prediction
pytest tests/functional/strategies/machine_learning/test_0003_gold_ml_prediction.py -v

# KMeans 案例（需要 scikit-learn，缺失时自动 skip）
pytest tests/functional/strategies/machine_learning/test_0001_candlestick_kmeans_classification_gold.py -v
```

本分类多为迁移自原始回归库的单文件测试，以 `runonce=True` 断言指标基线；KMeans 与随机森林两个文件依赖 sklearn，缺失时会整模块跳过而不是报错。

## 为什么在这个项目上研究机器学习策略

ML 策略最怕两件事：不可复现、过拟合不自知。[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 把对策做进了基础设施：1,152 个策略回归测试、每个策略的指标断言基线，让"70 笔全亏"这样的样本外失败被永久记录而非被悄悄调参掩盖；纯 Python 引擎比原版快 46%，参数扫描与特征实验不必过夜；装上 C++ 后端（`pip install back-trader-cpp`）更可获得中位 128 倍加速。想在策略里上真模型？先让引擎和基线配得上你的实验量。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
