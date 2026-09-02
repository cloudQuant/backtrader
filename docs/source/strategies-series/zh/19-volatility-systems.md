# 波动率系统与状态切换：让 HMM 听懂市场的心跳

> 量化策略图鉴 · 第 19 篇 · 分类 `volatility_systems`（32 个策略）· 2026-09-02

1963 年 Mandelbrot 留下过一句被引用了六十年的观察：价格的大幅变动倾向于紧跟大幅变动，小幅变动倾向于紧跟小幅变动——**波动率聚集**。它意味着市场不是一台参数恒定的机器，而是在"平静"与"狂暴"两种性格之间来回切换。顺着这条路，量化界发展出两套语言：一套用隐马尔可夫模型（HMM）把切换本身建模成隐含状态；另一套用 VIX 这样的"恐慌温度计"直接测量当前体温。还有一个小众但迷人的流派——航天工程师 John Ehlers 把雷达信号处理搬进技术分析，用滤波器和 Fisher 变换从价格里"解调"出市场循环。

本篇解读 `tests/functional/strategies/volatility_systems/` 下的 32 个策略：HMM 状态检测、VIX 系列代理指标、波动率分位仓位、Ehlers 循环家族。单资产策略多为 XAUUSD 日线（2008-2025）或 M15（2025-12 至 2026-03）。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| HMM Regime Detection | XAUUSD 日线 2024-2025 | 高斯 HMM 三状态 + 置信度/持续性双过滤 | `test_0007_0125_hmm_regime_detection.py` |
| VIX SPX Divergence | XAUUSD 日线 2008-2025 | 价格新高而波动率上升 → 做空脆弱行情 | `test_0011_0285_vix_spx_divergence.py` |
| Adaptive VIX MA | XAUUSD 日线 | 波动率 500 日百分位自适应 EMA | `test_0012_0302_adaptive_vix_ma.py` |
| VIX Futures Basis | XAUUSD 日线 | 10 日 vs 60 日波动率价差方向开关 | `test_0013_0320_vix_futures_basis.py` |
| Gold Volatility Position | XAUUSD 日线 | 波动率分位三档仓位 100%/75%/50% | `test_0005_0053_gold_volatility_position.py` |
| High Volatility Reap Policy | XAUUSD + IVV 日线 | 高波动风险开关的金银+股票再平衡政策 | `test_0006_0073_high_volatility_reap_policy.py` |
| Volatility Long Memory | XAUUSD 日线 | 波动率自身的 Hurst 指数分状态 | `test_0010_0206_volatility_long_memory.py` |
| Correlation Regime | IVV/IEF/GLD/DBC 日线 | 股债相关性正负决定 risk-on/off 配置 | `test_0015_0374_correlation_regime_strategy.py` |
| Bollinger Band Breakout | XAUUSD 日线 | 100 日均线 +3.0σ 入场、-1.0σ 出场 | `test_0021_bollinger_band_breakout.py` |
| Fisher Cyber Cycle | XAUUSD M15 + H8 信号 | Fisher 变换锐化 Cyber Cycle 拐点 | `test_0019_fisher_cyber_cycle.py` |
| Adaptive Cyber Cycle | XAUUSD M15 + H4 信号 | 主导周期自适应的三选一振荡器 | `test_0020_adaptive_cyber_cycle.py` |
| Cycle Period | XAUUSD M15 + H6 信号 | Hilbert 变换估计主导循环长度 | `test_0018_cycle_period.py` |

## 深读一：HMM Regime Detection——教模型自己认出牛熊

这是全分类里机器学习浓度最高的策略（[test_0007_0125_hmm_regime_detection.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/volatility_systems/test_0007_0125_hmm_regime_detection.py)）。它假设市场存在三个隐含状态，从三个可观测量里推断：对数收益、20 日年化波动率、60 日动量。每根 bar 用过去 252 日训练一个三状态高斯 HMM，每 63 日重训：

```python
model = GaussianHMM(n_components=n_states, covariance_type='full',
                    n_iter=300, random_state=42)     # n_states = 3
model.fit(train_std)
labels = _label_states(model, train_std)   # 按各状态平均标准化收益标注 BULL/BEAR/NEUTRAL

current_state = int(state_seq[-1])
current_confidence = float(proba[-1, current_state])
consistent = len(recent_states) >= smoothing_window and \
    all(s == current_state for s in recent_states[-smoothing_window:])   # 连续 5 日同状态

signed_target = 0.0
if current_confidence >= confidence_threshold and consistent:   # 置信度 ≥ 0.55
    if current_label == 'BULL':
        signed_target = min(1.0, 1.0 * current_confidence)      # 牛市做多，仓位随置信度
    elif current_label == 'BEAR':
        signed_target = max(-0.5, -0.5 * current_confidence)    # 熊市小空
```

注意两处防御：HMM 的状态编号是无意义的（0/1/2 每次重训都可能换含义），所以先按各状态的平均收益重标注成 BULL/BEAR/NEUTRAL；状态信号噪声大，所以加了"置信度过阈值 + 连续 5 日同一状态"的双重过滤，宁迟勿错。回测窗口 2024-2025 共 205 根 bar，重训 4 次，信号翻转 27 次但真正换仓仅 2 笔、两笔全胜，终值 1,014,553.76（+1.46%），SQN 4.76。工程上还有一处值得抄：文件开头 `pytest.importorskip("hmmlearn")`——可选 ML 依赖缺席时整模块优雅跳过，而不是让 CI 红一片。

## 深读二：Bollinger Band Breakout——不对称的 σ 通道

布林带突破人人都写得出，但参数的"不对称"才是这个版本（[test_0021_bollinger_band_breakout.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/volatility_systems/test_0021_bollinger_band_breakout.py)）的灵魂：

```python
out['bb_middle'] = out['close'].rolling(bb_period).mean()      # bb_period = 100
out['bb_std'] = out['close'].rolling(bb_period).std()
out['bb_upper_entry'] = out['bb_middle'] + entry_dev * out['bb_std']   # +3.0σ 才入场
out['bb_lower_exit'] = out['bb_middle'] - exit_dev * out['bb_std']     # 跌破 -1.0σ 才离场
out['entry_signal'] = (out['close'] > out['bb_upper_entry']).astype(float)
out['exit_signal'] = (out['close'] < out['bb_lower_exit']).astype(float)
```

入场要冲破 3 倍标准差——18 年的日线数据里这种事只发生 7 次；离场却只要求跌破中轨下方 1 倍标准差。门槛一高一低之间，给了趋势足够的呼吸空间，代价是回吐。结果是一张教科书式的低频趋势画像：7 次开仓仅 3 胜，胜率 42.9%，但 profit factor 2.97，终值 3,076,810.25（+207.7%），最大回撤 23.1%。**低胜率 × 高盈亏比**，与深读一的高胜率低换手恰好构成趋势策略的两副面孔。

## 深读三：Fisher Cyber Cycle——Ehlers 的信号处理流派

多数指标是统计量，Ehlers 的指标是滤波器。这个 M15 策略（[test_0019_fisher_cyber_cycle.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/volatility_systems/test_0019_fisher_cyber_cycle.py)）先把 (high+low)/2 平滑、再经二阶超级平滑器提取循环分量，然后把归一化后的循环值做 Fisher 变换——把任意分布拉成近似高斯，拐点因此变得锐利：

```python
k0 = (1.0 - 0.5 * alpha) ** 2                              # alpha = 0.07
k2 = 2.0 * (1.0 - alpha)
k3 = (1.0 - alpha) ** 2
smooth[bar] = (price[bar] + 2.0*price[bar-1] + 2.0*price[bar-2] + price[bar-3]) / 6.0
cycle[bar] = k0*(smooth[bar] - 2.0*smooth[bar-1] + smooth[bar-2]) \
             + k2*cycle[bar-1] - k3*cycle[bar-2]           # Cyber Cycle
value1[bar] = (cycle[bar] - ll) / (hh - ll)                # length=8 窗口内归一化
weighted = (4.0*vals[-1] + 3.0*vals[-2] + 2.0*vals[-3] + vals[-4]) / 10.0
scaled = 1.98 * (weighted - 0.5)
scaled = min(max(scaled, -0.999999), 0.999999)             # 钳位防 log 奇点
fish[bar] = 0.5 * math.log((1.0 + scaled) / (1.0 - scaled))  # Fisher 变换
trigger[bar] = fish[bar - 1]                                # 慢一拍的触发线
```

fish 上穿 trigger 做多、下穿做空，信号在 H8（480 分钟重采样）上计算、订单在 M15 上执行，配 1000/2000 固定点数止损止盈。三个月 18 笔交易 7 胜 11 负，终值 996,022.30（-0.40%）。亏损的基线同样被断言钉死——它证明的不是"Ehlers 不行"，而是这套参数在这段行情里没有正期望，给你留出了改进的对照面。钳位那一行 `min(max(scaled, -0.999999), 0.999999)` 是数值工程的细节美：Fisher 变换在 ±1 处发散，一行代码挡住一次 NaN 崩溃。

## 其余策略，快速点将

- **VIX SPX Divergence**（`test_0011`）：没有真 VIX 数据就用历史波动率代理——价格创新高、波动率却在上升、价波相关性断裂，三信号共振时做空，周一与波动率尖峰放大权重。
- **Adaptive VIX MA**（`test_0012`）：波动率在 500 日里的百分位直接决定 EMA 的 α（常数 4.6）——越极端的波动，均线跟得越紧。
- **Gold Volatility Position**（`test_0005`）：波动率分位 < 0.2 满仓、> 0.8 半仓、其余 75%——"别人恐惧我贪婪"的量化直译。
- **Volatility Long Memory**（`test_0010`）：对波动率序列本身算 Hurst——趋势化的波动跟均线，反持续的波动做反转。
- **Correlation Regime**（`test_0015`）：股债相关性是免费的风险气压计——显著为负配股票（risk-on），转正配债券（risk-off），中间地带均衡配置。

## 一条命令跑起来

```bash
# 整个分类（32 个策略）
pytest tests/functional/strategies/volatility_systems/ -v

# 只跑 HMM Regime Detection（需要 hmmlearn）
pytest tests/functional/strategies/volatility_systems/test_0007_0125_hmm_regime_detection.py -v
```

这些单文件测试把 `runonce=True` 下的重训次数、信号翻转数、终值逐项断言成基线；仓库层面以 runonce/runnext 双模式对拍守护引擎一致性，任何数值漂移都会被立刻抓出来。

## 为什么在这个项目上研究波动率与状态切换

状态切换策略是回测复杂度的天花板：HMM 要逐 bar 滚动重训、Ehlers 系要双周期多 feed 对齐，跑一次就够慢，遑论调参。这正是 [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 的着力点：纯 Python 引擎比原版快 46%，1,152 个策略回归测试跑完只要几分钟；装上 C++ 后端（`pip install back-trader-cpp`）可获得中位 128 倍加速，滚动重训的参数扫描从"过夜任务"变成"喝口咖啡"。而每个策略的指标断言基线，保证你优化的是策略本身，而不是被引擎的数值漂移误导。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
