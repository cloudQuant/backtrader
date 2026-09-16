# 日历与事件效应：缺口的三种命运，与只出现在隔夜的收益

> 量化策略图鉴 · 第 17 篇 · 分类 `others`（69 个策略）· 2026-09-02

如果把 K 线图上的每根柱子抹掉，只留下日历——周一到周五、月初与月末、季末与一月——你会发现相当一部分"行情"其实是日历的形状。学术界从 1970 年代起就注意到周末效应、月初效应、一月效应这些日历异象；而另一类异象藏在 K 线的缝隙里：开盘价与昨日收盘价之间那条肉眼几乎看不见的跳空缺口，民间谚语说"缺口必回补"，但真实的缺口有三种命运——回补、延续、反转，每种命运背后都有一套可回测的策略。

隔夜与日内的分裂同样反直觉：一根日 K 线的收益可以拆成"昨收到今开"的隔夜部分和"今开到今收"的日内部分，研究发现两者承担的风险溢价完全不同——这让"只持有隔夜"或"只持有日内"成了严肃的研究课题。

本篇解读 `tests/functional/strategies/others/` 下的日历与事件类策略。除特别标注外，单资产策略均使用 XAUUSD（现货黄金）日线，窗口 2008-2025。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| Gap N Go Fade | XAUUSD 日线 2008-2025 | 50 日新低后强势跳空做空，固定持有 2 日 | `test_0001_gap_n_go_fade_from_50_day_low.py` |
| Gap Down | XAUUSD 日线 | 跳空低开超 -1% 做多反弹，持有 5 日 | `test_0040_gap_down.py` |
| Unfilled Gap | XAUUSD 日线 | 未回补上跳缺口成簇 + 创滚动新高做多 | `test_0030_unfilled_gap.py` |
| Overnight Intraday | XAUUSD 日线 | 隔夜收益 20 日均线为正持有多头 | `test_0037_overnight_intraday.py` |
| Overnight Sentiment | XAUUSD 日线 | 隔夜收益均值超 0.1% 视作情绪信号 | `test_0045_overnight_sentiment.py` |
| Monday Drop Bounce | XAUUSD 日线 | 连跌 3 日 + 周一大跌超 2% 后抄底 | `test_0002_monday_drop_bounce.py` |
| Friday Bounce | XAUUSD 日线 | 周五恰逢 50 日低点反弹，下周一开盘买入 | `test_0014_friday_bounce.py` |
| Day of Month Timing | XAUUSD + BIL 日线 | 月末信号日按 MA200 趋势在金/现金间轮动 | `test_0026_day_of_month_timing.py` |
| End of Quarter | XAUUSD + XAGUSD 日线 | 季末金银价差 pair 交易 | `test_0021_end_of_quarter.py` |
| January Effect | IWM/IVV/IWD 日线 | 1 月买入上一年表现最弱的资产 | `test_0049_january_effect_strategy.py` |
| 52 Week High Effect | XAUUSD 日线 | 收盘处于 252 日高点 90%-95% 带内每月做多 | `test_0003_52_week_high_effect.py` |
| Dead Cat Bounce | XAUUSD 日线 | -3% 大跌后连涨 3 日确认反弹做多 | `test_0043_dead_cat_bounce.py` |

## 深读一：Gap N Go Fade——50 日新低后的跳空，为什么做空

直觉上，创出 50 日新低之后出现一根强势高开的阳线，是"底部反转"的教科书信号。这个策略（[test_0001_gap_n_go_fade_from_50_day_low.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/others/test_0001_gap_n_go_fade_from_50_day_low.py)）偏偏反着做：跌势末端的跳空高开更像情绪的一次性宣泄，宣泄完继续跌。它在 setup 出现当日开空，持有 `hold_days=2` 天定时离场。

Setup 判定是四道条件的 AND：

```python
out['prior_day_new_low'] = out['new_50d_low'].shift(1).fillna(0.0)   # 昨日刚创 50 日新低
out['gap_up_abs'] = out['open'] - out['prev_close']
pct_gap_trigger = out['gap_up_abs'] > (out['prev_close'] * gap_threshold_pct)  # 0.3%
atr_gap_trigger = out['gap_up_abs'] > (out['atr'] * gap_atr_multiple)          # 0.5 × ATR(14)
out['significant_gap_up'] = (pct_gap_trigger | atr_gap_trigger).astype(float)  # 满足其一即显著
out['gap_unfilled'] = (out['close'] > out['prev_close']).astype(float)   # 全天未回补缺口
out['close_above_open'] = (out['close'] > out['open']).astype(float)     # 阳线确认

out['setup_signal'] = (
    (out['prior_day_new_low'] > 0.5) & (out['significant_gap_up'] > 0.5)
    & (out['gap_unfilled'] > 0.5) & (out['close_above_open'] > 0.5)
).astype(float)
```

两处工程细节值得抄走：跳空的"显著"用百分比与 ATR 双触发取或——波动大的月份 0.3% 不算事，ATR 那条腿会自动抬高门槛；离场不设止损止盈，纯靠固定持有期，杜绝"扛单等回本"的人性漏洞。回测非常稀疏：18 年 4,588 根 bar 只触发 6 次，3 胜 3 负，终值 1,030,141.98（+3.01%），profit factor 1.56，最大回撤仅 3.27%。它不是印钞机，但每个数字都被断言锁死，是衡量"同思想不同过滤器"的干净起点。

## 深读二：Overnight Intraday——把一根日 K 线拆成两个市场

这个策略（[test_0037_overnight_intraday.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/others/test_0037_overnight_intraday.py)）的信号朴素到令人怀疑人生：

```python
out['overnight_ret'] = (out['open'] - out['close'].shift(1)) / out['close'].shift(1)  # 隔夜收益
out['intraday_ret'] = (out['close'] - out['open']) / out['open']                      # 日内收益
out['overnight_ma'] = out['overnight_ret'].rolling(lookback).mean()                   # lookback = 20
out['signal'] = (out['overnight_ma'] > threshold).astype(float)                       # threshold = 0.0
```

隔夜收益的 20 日均线为正 → 市场在夜里被持续买进 → 持有多头 5 天，然后重新评估。`next()` 里就是"信号开仓、计时平仓"两件事。

结果：593 笔交易，胜率 56.2%，终值 4,235,224.89（+323.5%），Sharpe 0.64，SQN 3.21——先别激动，看一眼经纪商配置：`margin=0.01, multiplier=100` 的期货模型，等于 10 倍杠杆，最大回撤 30.27% 就是杠杆的代价。这也正是回归测试库的价值：数字不会骗人，但口径会——不知道杠杆就读收益，是回测第一坑。

## 深读三：Day of Month Timing——月末那一天的纪律

日历效应最容易过拟合的地方，是"哪一天调仓"可以无限微调。这个策略（[test_0026_day_of_month_timing.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/others/test_0026_day_of_month_timing.py)）选择把再平衡钉死在每月最后一个交易日（`signal_day=0`），其余日子一概不动：

```python
signal_df["ma200"] = gold_df["close"].rolling(ma_period).mean()        # ma_period = 200
above_ma = (signal_df["gold_close"] > signal_df["ma200"]).astype(float)
signal_df["confirm_count"] = above_ma.rolling(confirm_days).sum()      # confirm_days = 5
signal_df["bullish_signal"] = (signal_df["confirm_count"] >= confirm_days).astype(float)

signal_df["seasonal_multiplier"] = 1.0
signal_df.loc[month_numbers.isin(bullish_months), "seasonal_multiplier"] = bull_multiplier  # [1,9,10,11,12] × 1.1
signal_df.loc[month_numbers.isin(bearish_months), "seasonal_multiplier"] = bear_multiplier  # [6,7,8] × 0.75

signal_df.loc[signal_df["target_asset"] == "gold", "gold_target"] = \
    base_position * signal_df["seasonal_multiplier"]                   # base_position = 0.95
signal_df["gold_target"] = signal_df["gold_target"].clip(lower=0.0, upper=1.0)
```

给趋势投票需要连续 5 日站在 MA200 上方；1/9/10/11/12 月仓位乘 1.1，6/7/8 月乘 0.75；且只有目标权重与当前权重偏离超 5% 才真的下单。18 年 177 次再平衡，终值 3,050,417.26。注意它的逐笔战绩只有 4 胜 16 负——轮动策略的收益来自仓位路径而非单笔胜负，这个口径差异值得每个读回测报告的人记住。

## 其余策略，快速点将

- **Gap Down**（`test_0040`）：与深读一互为镜像——低开超 1% 做多赌回补，持有 5 日。同是缺口，方向假设完全相反，正好对照。
- **Monday Drop Bounce**（`test_0002`）：连跌 3 日后在周一再跌 2%，恐慌宣泄到极点时买入，持有 5 日。
- **Friday Bounce**（`test_0014`）：周五恰逢 50 日低点且当日收出反弹阳线，视为高可靠拐点，下周一开盘进场。
- **January Effect**（`test_0049`）：1 月整月持有上一年表现最弱的资产（IWM/IVV/IWD 三选一），2 月首个交易日清仓。
- **52 Week High Effect**（`test_0003`）：不追创新高，只在收盘位于 252 日高点 90%-95% 的"锚定带"内、且近 30 日没碰过新高时，每月开多持有 21 日。
- **Unfilled Gap**（`test_0030`）：统计仍开放的上跳缺口，2 个以上未回补且密集出现、价格创 30 日新高时追多，缺口下沿做止损。

## 一条命令跑起来

```bash
# 整个分类（69 个策略）
pytest tests/functional/strategies/others/ -v

# 只跑 Gap N Go Fade
pytest tests/functional/strategies/others/test_0001_gap_n_go_fade_from_50_day_low.py -v
```

这些单文件测试把 `runonce=True` 下的成交数、终值、回撤逐项断言成基线；仓库层面以 runonce/runnext 双模式对拍守护引擎一致性，策略数字的任何漂移都会被立刻抓出来。

## 为什么在这个项目上研究日历与事件效应

日历与事件策略信号稀疏、样本极小（18 年 6 笔交易的深读一就是典型），单次回测的偶然性巨大，最需要**大规模、可复现**的回归基础设施。这正是 [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 的着力点：纯 Python 引擎比原版快 46%，1,152 个策略回归测试跑完只要几分钟；装上 C++ 后端（`pip install back-trader-cpp`）可获得中位 128 倍加速，把"换个信号日再试一遍"从过夜任务变成喝口咖啡。而每个策略的指标断言基线，保证你优化的是策略本身，而不是被引擎的数值漂移误导。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
