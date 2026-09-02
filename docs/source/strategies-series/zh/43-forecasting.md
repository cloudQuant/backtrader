# 预测策略：ARIMA 与预测振荡器——猜方向的学问

> 量化策略图鉴 · 第 43 篇 · 分类 `forecasting`（3 个策略）· 2026-09-02

量化圈有个老笑话：经济学家预测了过去五次衰退中的九次。预测市场——尤其是预测价格——名声更差。有效市场假说的极端版本甚至断言：价格的一切线性可预测性都会被套利抹平。

但"预测失败"不等于"预测无用"。把问题拆开看：预测明天的**幅度**（涨 0.83% 还是 1.2%）几乎不可能，预测**方向**（明天收阳还是收阴）在趋势市里胜率略高于抛硬币——而方向性头寸只需要方向对，配合截断亏损、放大盈利的出场规则，55% 的方向胜率也能堆出正期望。本篇的三个策略都走这条路：ARIMA 用自回归的语言描述"明天的收益和今天有多大关系"，预测振荡器度量"价格偏离回归预测线多远"——它们都不预测目标价，只回答一个二元问题：涨，还是不涨。

`tests/functional/strategies/forecasting/` 下只有 3 个策略，本篇一篇讲完。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| ARIMA 时序预测 | XAUUSD 日线 2022-2025 | ARIMA(1,0,1) 滚动预测次日收益，为正则持多 | `test_0001_arima_time_series_forecast.py` |
| 预测振荡器 | XAUUSD 15 分钟→12 小时 | 价格相对线性回归预测的偏差，T3 平滑线交叉 | `test_0002_1003_forecastoscilator.py` |
| EMA 预测 | XAUUSD 15 分钟 + 6 小时 | H6 快慢 EMA 交叉预测延续，M15 执行 | `test_0003_1010_ema_prediction.py` |

## 深读：ARIMA——用自回归语言猜明天

ARIMA(p, d, q) 的三个参数是三种记忆：p 阶自回归（今天的收益记得住前 p 天）、d 次差分（先平稳化）、q 阶移动平均（记得住前 q 天的冲击）。选 ARIMA(1,0,1) 而不是更大刀阔斧的阶数，本身就是一个观点：日收益序列里值得建模的依赖结构非常浅——昨天的事记得一点、昨天的冲击也记得一点，再多就是过拟合历史噪声了。金融时序的经典 stylized fact 也支持这种克制：收益率自相关本来就弱，显著的是波动聚集，而后者是 GARCH 家族的地盘，不是 ARIMA 的。[test_0001_arima_time_series_forecast.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/forecasting/test_0001_arima_time_series_forecast.py) 在日收益序列上滚动预测：

```python
for idx in range(train_window, len(out)):
    if fitted_model is None or (idx - train_window) % refit_interval == 0:
        train_series = returns.iloc[idx - train_window:idx].reset_index(drop=True)
        fitted_model = ARIMA(train_series, order=selected_order).fit()   # (1, 0, 1)
    forecast = fitted_model.forecast(steps=1)
    forecasts[idx] = float(forecast.iloc[0])

out["signal"] = np.where(out["forecast_return"] > forecast_threshold, 1.0, 0.0)
out["target_pct"] = out["signal"] * target_percent      # 为正 → 95% 仓位，否则空仓
```

三个参数值得咀嚼：训练窗口 252 天（一年）、**每 20 天重拟合一次**、预测阈值为 0——预测值为正就持多、为负就空仓，不做空。固定间隔重拟合是 **walk-forward** 思想的低成本版本：模型永远只见过"过去"，每 20 天吸收一次新信息，杜绝了用未来数据污染训练集的 lookahead 偏差。这也解释了为什么特征工程放在 pandas 里预计算、`next()` 只负责按 `target_pct` 调仓——模型拟合与订单执行分属两个世界，中间只隔一张信号表。

回测（黄金 2022-2025，期货式 100 倍乘数合约）：1,032 根日 K 里 740 天发出多头信号、292 天空仓，但只有 6 次调仓、2 笔完整交易（2 胜 0 负），终值 2,151,710.03。两个提醒：其一，杠杆放大了数字的观感，保证金 1%、乘数 100 的合约下 95% 名义仓位意味着巨大的名义敞口；其二，2 笔交易的样本量说明——**预测信号几乎是个慢变量**，ARIMA 在黄金上捕捉到的更可能是"数月级别的漂移"而非逐日波动，信号在正负之间并不频繁切换（全程仅 5 次切换）。方向确实能猜对，但靠的是趋势的惯性，不是水晶球。

## 其余策略，快速点将

- **预测振荡器**（`test_0002`）：MT4/MT5 指标 Forecast Oscillator 的移植——价格相对线性回归预测值的百分比偏差，用 Tillson T3 平滑后与原线交叉触发，12 小时周期上运算。111 根 K 线 21 笔交易，胜率 52.4% 但终值 999,479.5——高频打平，手续费敏感者的教材。
- **EMA 预测**（`test_0003`）：双时间框架结构——H6 上快慢 EMA（周期 1 与 2，激进到接近价格本身）交叉定方向，M15 执行下单，1000 点止损、2000 点止盈。55 笔交易胜率 40%，终值 1,000,475.90、Sharpe 0.80：又一个"胜率不重要"的例证。

三个策略合起来看，"预测"在实盘语境下的含义已经很清楚：**不是算出明天的价格，而是给今天一个可执行的方向判断，再用出场规则把小胜率拼成正期望**。预测模型的精度提升一个百分点很难，止损纪律的改善却立竿见影——研究预测策略，最后学到的往往是仓位管理。

## 一条命令跑起来

```bash
# 整个分类（3 个策略）
pytest tests/functional/strategies/forecasting/ -v

# 只跑 ARIMA 预测
pytest tests/functional/strategies/forecasting/test_0001_arima_time_series_forecast.py -v
```

## 为什么在这个项目上研究预测策略

滚动重拟合 + 逐日回放的 walk-forward 回测，计算量是普通策略的数倍——每根 K 线背后都藏着一次模型拟合。[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 纯 Python 引擎比原版快 46%，C++ 后端（`pip install back-trader-cpp`）中位 128 倍加速，让重拟合间隔从 20 天压到 5 天成为几分钟就能验证的实验；1,152 个策略回归测试与 runonce/runnext 双模式对拍保证预测管道的每个数值可复现、可对比——研究预测，先要能预测你的回测结果。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
