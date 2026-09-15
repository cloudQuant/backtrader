# 日历效应：Sell in May、换月窗口与 FOMC——给最古老的市场谚语做体检

> 量化策略图鉴 · 第 21 篇 · 分类 `calendar_effects`（28 个策略）· 2026-09-02

"Sell in May and go away"——这句谚语据说可以追溯到伦敦金融城还在用马车运钞票的年代：天气转暖，绅士们收拾行装去乡间度假，市场流动性枯竭，不如五月清仓、十一月回来。听起来像段子，但它是学术文献里被反复检验次数最多的异象之一：统计上，11 月到次年 4 月的收益确实长期强于 5 月到 10 月。

日历效应是量化里最"玄"也最"硬"的一类：玄在它的经济学解释至今众说纷纭（避税卖出？分红再投资？度假情绪？），硬在它完全由日期驱动——规则简单到没有过拟合的藏身之处，任何人都能用一条命令复现。

本篇解读 `tests/functional/strategies/calendar_effects/` 下的 28 个日历与事件策略：黄金季节性家族、换月窗口、期权到期与四巫日、FOMC 与非农等事件驱动窗口。全部基于真实数据回测，赚的亏的都摆在断言里。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| Sell in May（季节版） | XAUUSD 日线 2008-2025 | 11 月初买入、5 月初卖出，只在 11 月-次年 4 月持有 | `test_0008_0103_sell_in_may.py` |
| Turn of Month | XAUUSD 日线 2008-2025 | 每月最后 3 天+下月头 3 天满仓，窗口外空仓，2% 止损 | `test_0020_0407_turn_of_month_strategy.py` |
| 黄金 FOMC 效应 | XAUUSD 日线 2008-2025 | FOMC 代理日前 5 天建仓，趋势过滤+波动率止损 | `test_0022_0016_gold_fomc_effect.py` |
| 黄金日历效应 | XAUUSD 日线 | 按月度分组的季节性持仓 | `test_0001_0005_gold_calendar_effect.py` |
| 黄金换月（两版） | XAUUSD 日线 | 换月窗口做多的两种参数化 | `test_0002_0007_gold_turn_of_month.py` / `test_0004_0027_gold_turn_of_month.py` |
| 黄金季节性 | XAUUSD 日线 | 历史月度收益统计定方向 | `test_0003_0017_gold_seasonality.py` |
| 季节窗口/轮动 | XAUUSD 日线 | 指定月份窗口持有；多窗口轮动 | `test_0005_0039_gold_seasonal_windows.py` / `test_0006_0043_gold_seasonality_rotation.py` |
| 月末季节性 | XAUUSD 日线 | 只吃月末几天的漂移 | `test_0007_0097_gold_end_of_month_seasonality.py` |
| 感恩节季节性 | XAUUSD 日线 | 感恩节前后的节日窗口 | `test_0009_0256_thanksgiving_seasonality.py` |
| 12 月 OPEX | XAUUSD 日线 | 12 月期权到期周的波动规律 | `test_0010_0258_december_opex_seasonality.py` |
| 四巫日 | XAUUSD 日线 | 季度期权/期货同日到期的波动 | `test_0011_0266_quad_witching_seasonal_strategy.py` |
| 8 月卖出 | XAUUSD 日线 | 反向验证"夏季弱势" | `test_0017_0401_seasonal_sell_august_strategy.py` |
| 比特币季节异常 | IBIT 日线 | 比特币ETF的月度异象 | `test_0014_0364_bitcoin_seasonal_anomalies_strategy.py` |
| 比特币季节性 | XAUUSD 小时线 | 另一份加密季节性实现 | `test_0016_0387_bitcoin_seasonality_strategy.py` |
| 加息周期黄金 | XAUUSD/GTIP/IEF 日线 | 利率周期定位黄金敞口 | `test_0023_0079_rate_hike_cycle_gold.py` |
| 非农新高 | XAUUSD 日线 | 非农公布前后的多头窗口 | `test_0024_0276_jobs_report_new_high_strategy.py` |
| 避开财报 | XAUUSD 日线 | 事件窗口外持仓、临近事件空仓 | `test_0025_0282_avoid_earnings_strategy.py` |
| 大选前漂移 | XAUUSD 日线 | 美国大选年的选前做多窗口 | `test_0026_0306_pre_election_drift.py` |
| 外汇新闻交易 | EURUSD 日线 | 新闻事件窗口的动量跟随 | `test_0027_0397_fx_news_trading_strategy.py` |
| 专家新闻 | XAUUSD 15 分钟 | 事件日历驱动的高频窗口交易 | `test_0028_expert_news.py` |

## 深读一：Sell in May——谚语的实证检验

这是全分类最"原教旨"的一个策略（[test_0008_0103_sell_in_may.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/calendar_effects/test_0008_0103_sell_in_may.py)）：规则只有一条——11 月第一个交易日附近买入，5 月第一个交易日附近卖出，其余时间空仓。信号生成干净得像教科书：

```python
out['month'] = out.index.month
buy_signal = out['month'] == buy_month     # buy_month = 11
sell_signal = out['month'] == sell_month   # sell_month = 5
prev_month = out['month'].shift(1)
buy_entry = (prev_month != buy_month) & buy_signal    # 仅在"进入11月"那根K线触发
sell_entry = (prev_month != sell_month) & sell_signal
out['holding'] = ((out['month'] >= buy_month) | (out['month'] <= 4)).astype(float)
```

注意 `holding` 的写法：11、12 月用 `>= 11` 抓，1-4 月用 `<= 4` 抓——跨年区间的布尔逻辑是日历策略最常写错的地方。策略侧的 `next()` 只在信号翻转时下单：空仓遇 `buy_signal` 全仓买入，持仓遇 `sell_signal` 平仓。

**回测结果**：XAUUSD 日线 2008-2025、初始 100 万、万二佣金加 1% 保证金，17 年只做了 18 笔交易，胜 12 负 6（胜率 66.7%），终值 2,875,338——总收益 +187.5%，利润因子 4.93，最大回撤 28.9%，Sharpe 0.546。这些数字不是宣传语，是测试断言：`abs(final_value - 2875338.15) < 2.88` 之类一行行钉在文件里。当然要诚实地说：黄金本身 2008-2025 走了大牛市，这个策略吃到的相当一部分是 beta；它的真正价值在于提供了"全年持有 vs 只持 6 个月"的对照起点——仓库里另有 `test_0015_0366` 独立实现可供对拍。

## 深读二：Turn of Month——把"月初月末"变成窗口函数

换月效应（Turn of Month）指资产收益集中在月末最后几天与月初头几天的现象，主流解释包括工资/养老金定投现金流与机构再平衡。本篇的实现（[test_0020_0407_turn_of_month_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/calendar_effects/test_0020_0407_turn_of_month_strategy.py)）用 groupby-rank 把窗口定义得非常精确：

```python
fwd_rank = pd.Series(range(len(out)), index=out.index).groupby(current_period).transform(
    lambda x: x.rank(method='first'))
rev_rank = pd.Series(range(len(out)), index=out.index).groupby(current_period).transform(
    lambda x: x.rank(ascending=False, method='first'))
out['is_month_end_window'] = (rev_rank <= last_days).astype(float)      # last_days = 3
out['is_month_start_window'] = (fwd_rank <= first_days).astype(float)   # first_days = 3
in_window = (out['is_month_end_window'] > 0.5) | (out['is_month_start_window'] > 0.5)
out['entry_signal'] = (in_window & (~prev_in_window)).astype(float)
out['exit_signal'] = ((~in_window) & prev_in_window).astype(float)
```

策略侧入场即 `order_target_percent(target=1.0)` 满仓，同时挂 2% 百分比止损：`self.stop_price = close * (1.0 - self.p.stop_loss_pct)`——这是"日历窗口+风控"的标准工程组合。

**回测结果**：同一份 XAUUSD 日线，4,638 根 K 线里有 1,296 根处于窗口内（约 28% 的时间），共 210 笔交易、115 胜 94 负（胜率 54.8%），终值 2,000,333（+100.0%），利润因子 1.50，Sharpe 0.562。只用不到三成的在市时间拿到这个结果，正是换月效应的卖点。文件里还有个细节值得学：pandas 3.x 的 `fillna(False)` 不再隐式降型，作者特意保持 object dtype 以保证 2.x/3.x 信号一致——版本兼容意识写进了注释。

## 深读三：FOMC 效应——事件驱动的日历策略

日历效应不只"月份"，还包括"事件日"。[test_0022_0016_gold_fomc_effect.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/calendar_effects/test_0022_0016_gold_fomc_effect.py) 研究美联储议息会议前后的黄金漂移。由于回测无法拿到真实 FOMC 日历，它用代理规则合成：

```python
FOMC_MONTHS = (1, 3, 5, 6, 7, 9, 11, 12)
# 取每月第 3 个周三作为 FOMC 代理日，再对齐到最近的交易日
stop_pct = float(np.clip(stop_vol_multiplier * stop_pct * math.sqrt(pre_event_days),
                         min_stop_pct, max_stop_pct))   # 2.0×波动×√5，夹在 [1%, 5%]
if historical_drift > 0 and current_trend > 0:
    direction = 1    # 历史会前漂移为正且当前趋势向上，才做多
```

仓位管理很克制：每次事件只用 3% 名义敞口（`event_position_pct=0.03`），连亏 3 次后暂停 1 个事件。**回测结果**：69 笔交易，33 胜 36 负，终值 994,992（-0.50%），Sharpe -0.17，最大回撤仅 1.29%。亏钱，但亏得明明白白——小仓位+严止损让它成了"低风险地验证一个不成立假设"的范本。想要正收益版本？同目录的 `test_0024`（非农新高）与 `test_0026`（大选前漂移）提供了对照。

## 其余策略，快速点将

- **季节性拼图**（`test_0012_0275` / `test_0013_0281`）：季节翻转与多窗口复合，把单月效应组装成组合信号。
- **商品季节性抢跑**（`test_0019_0406`，GLD 数据）：在季节性需求兑现前提前布局。
- **文化日历黄金**（`test_0021_0412`，GLD 数据）：中国春节、印度排灯节等实物金需求旺季的窗口策略。
- **加息周期黄金**（`test_0023_0079`）：三数据源（XAUUSD/GTIP/IEF）联动，用通胀保值债与国债定位利率周期。
- **expert_news**（`test_0028`，XAUUSD 15 分钟线）：全分类唯一的分钟级实现，演示高频数据上的事件窗口工程。

## 一条命令跑起来

```bash
# 整个分类（28 个策略）
pytest tests/functional/strategies/calendar_effects/ -v

# 只跑 Sell in May
pytest tests/functional/strategies/calendar_effects/test_0008_0103_sell_in_may.py -v
```

## 为什么在这个项目上研究日历效应

日历策略规则简单、信号稀疏，恰恰最需要"大量变体横向对比"的基础设施：同一个谚语在黄金、比特币、外汇上是否都成立？窗口宽一天窄一天差多少？这正是 [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 的用武之地：纯 Python 引擎比原版快 46%，1,152 个策略回归测试几分钟跑完；装上 C++ 后端（`pip install back-trader-cpp`）获得中位 128 倍加速，扫参数像翻日历一样快。runonce/runnext 双模式对拍与指标断言基线，保证你比较的是策略差异，而不是引擎噪声。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
