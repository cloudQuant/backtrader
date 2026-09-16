# 统计度量与组合策略：从凯利公式到 Markowitz，仓位本身就是信号

> 量化策略图鉴 · 第 18 篇 · 分类 `others`（69 个策略）· 2026-09-02

1956 年，贝尔实验室的 John Kelly 发表了一篇信息论论文，讨论"知道一点内幕信息的赌徒该如何下注"。数学家 Ed Thorp 把它先后带进了赌场（算牌二十一点）和华尔街（第一家量化对冲基金），公式只有一行：**最优下注比例等于优势除以赔率的波动**。同一时期，水文学家 Harold Hurst 研究尼罗河八百年的水位记录，发现水文序列的涨落偏离随机游走——这条"记忆"后来被 Mandelbrot 移植到金融市场，成为区分趋势市与均值回归市的最著名标尺。再加上 1952 年 Markowitz 的均值方差优化，三件套凑齐了本篇的主角：**当买什么不再重要，买多少和什么时候买成了策略本身**。

本篇解读 `tests/functional/strategies/others/` 下以统计度量驱动的仓位与组合策略：Kelly、Hurst、Markowitz、Omega、马氏距离动荡指数，以及多资产多空组合。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| Kelly / Optimal F | GLD 日线 2008-2025 | 滚动收益算 Kelly 仓位，趋势门控，半凯利 + 封顶 | `test_0052_kelly_optimal_f_strategy.py` |
| Hurst 指数 | GLD 日线 2008-2025 | H>0.55 跟趋势，H<0.45 做 RSI 反转 | `test_0056_hurst_exponent_strategy.py` |
| Markowitz 优化 | XAUUSD 日线 2008-2025 | 滚动 120 日年化 Sharpe 代理，每 63 日再平衡 | `test_0046_markowitz_optimization.py` |
| Omega 比率 | XAUUSD 日线 | 252 日 Omega > 1.2 持有、< 0.8 空仓 | `test_0017_omega_ratio.py` |
| Skew Kurtosis | XAUUSD 日线 | 60 日滚动偏度触发统计入场 | `test_0034_skew_kurtosis.py` |
| Probability Cones | XAUUSD 日线 | ±2σ 概率锥外沿反向押注 | `test_0042_probability_cones.py` |
| Ulcer Performance Index | IVV/IEF/GLD/DBC 日线 | 年化收益除以 Ulcer 回撤风险做轮动 | `test_0050_ulcer_performance_index_strategy.py` |
| Turbulence Index | IVV/IEF/GLD/DBC/EEM 日线 | 马氏距离动荡度映射三档固定配置 | `test_0060_turbulence_index_strategy.py` |
| Zweig Breadth Thrust | XAUUSD 日线 | 动量篮子代理的市场宽度推进信号 | `test_0018_zweig_breadth_thrust.py` |
| Market Neutral | XAUUSD 日线 | 60 日 z-score ±1.5 入场、±0.5 回归离场 | `test_0041_market_neutral.py` |
| Long Short Equity | IVV/IWM/IWD/GLD/IEF 日线 | 0.6 动量 + 0.4 低波评分，多空各取 2 | `test_0048_long_short_equity_strategy.py` |
| Fifty Fifty | XAUUSD 日线 | 一半永久持有 + 一半 200 日线趋势开关 | `test_0020_fifty_fifty.py` |

## 深读一：Kelly / Optimal F——把仓位交给数学

这个策略（[test_0052_kelly_optimal_f_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/others/test_0052_kelly_optimal_f_strategy.py)）在 GLD 日线上滚动回看 126 日收益，每根 bar 重算目标仓位，两套算法可选：

```python
def _kelly_fraction(self, returns):
    mean_return = float(np.mean(returns))
    variance = float(np.var(returns))
    if variance <= 0:
        return 0.0
    fraction = mean_return / variance                        # f* = μ / σ²
    fraction = max(0.0, fraction) * float(self.p.kelly_adjustment)  # 半凯利 0.5
    return min(fraction, float(self.p.max_fraction))         # 封顶 0.2

def _optimal_f(self, returns):
    best_f, best_score = 0.0, -1e18
    for f_value in np.arange(0.0, 1.0 + self.p.optimal_f_step, self.p.optimal_f_step):  # 步长 0.02
        wealth_path = 1.0 + f_value * returns
        if np.any(wealth_path <= 0):
            continue
        score = float(np.prod(wealth_path))                  # 最大化终端财富乘积
        if score > best_score:
            best_score, best_f = score, float(f_value)
    return min(best_f * float(self.p.optimal_f_adjustment), float(self.p.max_fraction))
```

理论 Kelly 是极限最优，但收益分布估计稍有偏差就让你破产，所以工程实现全是"刹车"：打五折（half-Kelly）、封顶 20%、再叠一道 63 日趋势门控——`trend_return <= 0` 时仓位直接归零。回测：18 年平均仓位 10.1%，终值 1,250,223.05（+25.0%），最大回撤仅 5.16%，Sharpe 0.53。有个口径彩蛋：买入 1,042 次、卖出 1,292 次的连续调仓，在 TradeAnalyzer 里只算 1 笔平仓交易——读指标先读口径，这是回归库教的第二课。

## 深读二：Hurst 指数——同一个市场的两种性格

如果价格序列有长期记忆，它的 Hurst 指数会偏离 0.5：H 接近 1 表示趋势自增强，H 接近 0 表示涨跌交替（均值回归）。这个策略（[test_0056_hurst_exponent_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/others/test_0056_hurst_exponent_strategy.py)）先估计 H，再决定"用哪套招式"：

```python
def _hurst_from_prices(values, min_lag, max_lag):        # min_lag=2, max_lag=20
    log_prices = np.log(np.asarray(values, dtype=float))
    tau, lags = [], list(range(min_lag, max_lag + 1))
    for lag in lags:
        diffs = log_prices[lag:] - log_prices[:-lag]      # 多尺度的对数价格差分
        tau.append(np.std(diffs))
    slope, _ = np.polyfit(np.log(np.asarray(lags)), np.log(np.asarray(tau)), 1)
    return float(np.clip(slope, 0.0, 1.0))                # log-log 斜率即 Hurst
```

```python
if hurst_value > float(self.p.trend_threshold):           # H > 0.55：趋势市
    target_pct = 1.0 if float(data.close[0]) > float(data.sma[0]) else -1.0   # 跟 SMA50 方向
elif hurst_value < float(self.p.mean_reversion_threshold):  # H < 0.45：均值回归市
    if float(data.rsi[0]) < 30:
        target_pct = float(self.p.mean_reversion_weight)    # RSI 超卖做多，权重 0.75
    elif float(data.rsi[0]) > 70:
        target_pct = -float(self.p.mean_reversion_weight)   # RSI 超买做空
```

H 在 150 日窗口上滚动估计，状态每 5 日才允许换一次仓。结果是一份诚实的亏损基线：108 笔、59 胜 49 负，终值 669,247.06（-33.1%）。原因也不难猜——黄金过去 18 年是出了名的趋势市场，均值回归腿屡屡被单边行情碾压。策略没失效，市场性格和历史窗口不匹配罢了。

## 深读三：Markowitz——把均值方差优化砍成一个 Sharpe 代理

完整的 Markowitz 需要协方差矩阵求逆，样本稍小就病态。这个策略（[test_0046_markowitz_optimization.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/others/test_0046_markowitz_optimization.py)）做了一次教科书级的"降维工程化"：

```python
ret = out["close"].pct_change()
mu = ret.rolling(lookback).mean() * 252                    # lookback = 120，年化均值
sigma = ret.rolling(lookback).std() * np.sqrt(252)         # 年化波动
out["sharpe_proxy"] = (mu - rf) / sigma.replace(0, np.inf) # rf = 0

# 每 63 个交易日（一个季度）落一次 rebalance_flag
if not self.position:
    if sharpe > 0:   self.pending_order = self.buy(size=...)
else:
    if sharpe < 0:   self.pending_order = self.close()
```

单资产世界里，均值方差最优解退化成"风险调整后收益为正就持有"：滚动 Sharpe 为正开多、转负清仓，一季度只看一眼。18 年仅 9 买 8 卖，终值 5,203,300.46（+420.3%）——别急着惊叹，期货模型 `mult=100, margin=0.01` 的 10 倍杠杆依然是收益的放大器。对比深读一：同样是"趋势门控 + 低频决策"，Kelly 管**比例**、Markowitz 管**开关**，仓位管理的两半刚好拼齐。

## 其余策略，快速点将

- **Omega Ratio**（`test_0017`）：不用方差只用全分布——阈值以上收益之和除以以下之和，252 日 Omega 破 1.2 持有、破 0.8 空仓，每 5 日复核。
- **Turbulence Index**（`test_0060`）：五资产收益向量到历史均值的马氏距离做"动荡温度计"，高/中/低动荡映射三套固定配置（高动荡时 IVV 仅 20%、GLD 加到 35%）。
- **Ulcer Performance Index**（`test_0050`）：年化收益除以 Ulcer Index（回撤深度的 RMS），四资产按 UPI 定期重排权重。
- **Long Short Equity**（`test_0048`）：0.6 动量分 + 0.4 低波分合成评分，多头取前 2、空头取后 2，21 日再平衡——多因子打分的最小可行版。
- **Probability Cones**（`test_0042`）：用 60 日收益均值和标准差在预期价格外沿画出上下概率锥，价格跌出下锥做多、冲出上锥做空，本质是对正态假设的赌注。
- **Zweig Breadth Thrust**（`test_0018`）：单工具没有涨跌家数，就用一篮子动量条件构造宽度代理，其 EMA 从低于 0.4 一跃站上 0.615 视作"推进"，持多 20 日。
- **Fifty Fifty**（`test_0020`）：一半资金永远持有、一半资金跟 200 日均线开关——懒人版的"核心 + 卫星"。

## 一条命令跑起来

```bash
# 整个分类（69 个策略）
pytest tests/functional/strategies/others/ -v

# 只跑 Kelly / Optimal F
pytest tests/functional/strategies/others/test_0052_kelly_optimal_f_strategy.py -v
```

这些单文件测试把 `runonce=True` 下的平均仓位、终值、回撤逐项断言成基线；仓库层面以 runonce/runnext 双模式对拍守护引擎一致性，仓位数字的任何漂移都会被立刻抓出来。

## 为什么在这个项目上研究统计度量与组合策略

统计度量策略的自由度极高——窗口、阈值、权重、再平衡频率，每个都是一个可调旋钮，扫一遍参数空间动辄上千次回测，最需要**大规模、可复现**的回测基础设施。这正是 [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 的着力点：纯 Python 引擎比原版快 46%，1,152 个策略回归测试跑完只要几分钟；装上 C++ 后端（`pip install back-trader-cpp`）可获得中位 128 倍加速，参数扫描从"过夜任务"变成"喝口咖啡"。而每个策略的指标断言基线，保证你优化的是策略本身，而不是被引擎的数值漂移误导。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
