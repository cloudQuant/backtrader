# 期权策略：到期周效应与备兑卖出，在别人对赌的地方捡硬币

> 量化策略图鉴 · 第 39 篇 · 分类 `options`（5 个策略）· 2026-09-02

期权市场有一条著名的不对称性：绝大多数买家亏钱，但市场离不开他们——买保险的人支付权利金，卖保险的人收取权利金。围绕这个结构，量化世界衍生出两类完全不同的打法：一类赌**日历上的规律**（期权到期周的价格漂移、pinning 效应），一类直接**站到卖方**收权利金（put write、备兑）。

pinning 的机制并不神秘：到期日临近，行权价附近堆满做市商的 gamma 敞口——价格涨过行权价他们追买、跌回行权价他们追卖，高 gamma 区间里的对冲流水反而把价格"钉"回行权价。到期周因此成了波动率、成交量与价格行为都异于平常的一周，也成了日历策略最爱的猎场。至于卖方策略，收益结构天然是"卖彩票"：多数时候收下权利金安然离场，偶尔一次大行情把几年的收入一次赔光——收益分布的左尾，才是卖方真正的商品。

本篇解读 `tests/functional/strategies/options/` 下的 5 个回测。由于回测框架不内嵌期权定价引擎，这些测试展示了另一种工程路线：用已实现波动率、合成 NAV 与近似定价公式，在纯股票/ETF 数据流上**近似建模**期权行为。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| 到期周效应（XAUUSD 版） | 黄金日线 2008-2025 | 看多月份（3/4/10/12）到期周周一做多、周五平仓，按月加权 | `test_0001_options_expiration_week_strategy.py` |
| 到期周效应（GLD 版） | GLD 日线 2008-2025 | 月度牛熊偏向定方向：牛月做多熊月做空，周一进周五出 | `test_0002_options_expiration_week.py` |
| 低波期权组合 | JEPI/PBP/IVV 日线 | 低波股票 + 备兑 + 合成 put-write 三袖组合，波动率目标与回撤风控 | `test_0003_low_volatility_options.py` |
| 期权估值 | 黄金日线 2008-2025 | 已实现波动率分位当 IV rank 代理：低于 0.2 做多、高于 0.8 离场 | `test_0004_options_valuation.py` |
| GLD 备兑卖出看跌 | GLD 日线 2010-2025 | 现金担保卖出 30 天看跌期权收权利金，波动率近似定价 | `test_0005_gld_put_write_strategy.py` |

## 深读一：到期周效应——日历里的隐藏剧本

美股个股与指数期权在每月第三个周五到期。到期周前后，做市商的对冲流水（gamma 对冲、展期）被认为会压制或推动现货价格——所谓 **pinning**：价格被"钉"在行权价附近。这套策略不去预测钉在哪里，而是赌一个更粗的方向：**某些月份的到期周存在系统性漂移**。

[test_0002_options_expiration_week.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/options/test_0002_options_expiration_week.py) 先用日历算法定位到期周，再给每个月定牛熊偏向，周一进场、周五平仓：

```python
def _third_friday(year, month):
    month_calendar = calendar.monthcalendar(year, month)
    friday_count = 0
    for week in month_calendar:
        if week[calendar.FRIDAY] != 0:
            friday_count += 1
            if friday_count == 3:
                return week[calendar.FRIDAY]          # 每月第三个周五

monday_day = third_friday - 4                          # 周一 = 周五减 4 天
in_week = monday_day <= idx.day <= third_friday
bias = 1.0 if idx.month in bullish_months else (-1.0 if idx.month in bearish_months else 0.0)
entry_signal.append(1.0 if in_week and idx.weekday() == 0 and bias != 0.0 else 0.0)
exit_signal.append(1.0 if in_week and idx.weekday() == 4 else 0.0)
```

参数里 1-5 月与 9-12 月为牛月、6-8 月为熊月（`bullish_months`/`bearish_months`），仓位 95%，止损 2%、止盈 1.5%。诚实的结论写在断言里：GLD 2008-2025 共 4,519 根 K 线、199 笔交易，胜率 49.2%，终值 947,033.84——**亏 5.3%**，Sharpe -0.02，最大回撤 32.89%。月度偏向这种硬编码日历，样本内都站不稳，是"季节性规律"最常见的研究陷阱样本。

工程上值得注意的是**特征与策略的分层**：到期周标记、月度偏向、进出场信号全部在 pandas 里离线算好，作为额外列挂进自定义 `PandasData` 数据源，`next()` 只读 `entry_signal`、`exit_signal`、`direction` 三条 line。日历逻辑（哪天是第三个周五）与交易逻辑（止损止盈）彻底解耦——前者改起来不用碰策略类，回测引擎也不用理解日历。

## 深读二：GLD Put Write——赚权利金的人，赚的是什么

卖出看跌期权（cash-secured put write）是"我愿意在这个价位接货，还先收一笔定金"的策略。收益结构天然拧巴：**大概率小赚（权利金），小概率大亏（接飞刀后深度套牢）**——胜率很高，尾部很毒。

[test_0005_gld_put_write_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/options/test_0005_gld_put_write_strategy.py) 用近似公式给期权定价，绕开了完整的 Black-Scholes：

```python
def _estimate_option_mark(self, spot, strike, days_to_expiry, realized_vol):
    vol = max(float(realized_vol or 0.0), 0.05)
    time_value = vol * math.sqrt(max(days_to_expiry, 1) / 365.0) * spot * 0.30
    intrinsic = max(0.0, float(strike) - float(spot))
    return intrinsic + time_value

strike = round(spot * 0.95 / 0.5) * 0.5    # 95% 价外，取整到 0.5 美元
```

入场过滤是"价在 200 日线上方且 RSI ≥ 30"——不在暴跌途中接刀。持仓期间逐日按新波动率重估 mark，权利金翻倍（涨 50% 即止损线）就买回平仓，否则拿到 30 天到期。这套"开仓—逐日盯市—止损/到期两条退出路径"的循环，正是真实期权卖方的日常节奏。

回测 2010-2025：92 次开仓，82 次自然到期、9 次止损，**胜率 81/91 ≈ 89%**，终值 1,156,219.97（+15.6%）。但请记住：9 次止损就是尾部风险的显形——2008 式行情里，这个数字会指数级放大。把胜率和盈亏比拆开看：89% 胜率的另一面，是止损那 9 次平均要亏掉多少才能把期望值拉平——put write 的"舒服"恰恰是它最危险的地方。

## 其余策略，快速点将

- **到期周 XAUUSD 版**（`test_0001`）：同一思想的黄金现货版，只做多年份 3/4/10/12 月且 10、12 月权重 1.2 倍——"按月加权"是日历策略里少数不那么武断的变体。
- **低波期权组合**（`test_0003`）：0.5 份 JEPI + 0.25 份 PBP + 0.25 份合成 put-write，63 天再平衡，波动率目标 12%，回撤超 20% 时风险敞口砍半——机构式的"期权收入全天候"。
- **期权估值**（`test_0004`）：不交易期权，而是把"波动率便宜/贵"当作择时信号——已实现波动率的 252 日分位低于 0.2 视为资产被低估而做多，高于 0.8 离场。

## 一条命令跑起来

```bash
# 整个分类（5 个策略）
pytest tests/functional/strategies/options/ -v

# 只跑 GLD put write
pytest tests/functional/strategies/options/test_0005_gld_put_write_strategy.py -v
```

## 为什么在这个项目上研究期权策略

期权近似建模最怕"引擎数值悄悄变了"：定价公式里的 `sqrt(days/365)`、逐日 mark-to-market 的现金流的微小漂移，都会让权利金策略的胜率统计失真。[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 的 1,152 个策略回归测试把这些数值钉死成基线断言，runonce/runnext 双模式对拍保证向量化引擎与事件驱动引擎算出同一份权利金。纯 Python 引擎比原版快 46%，C++ 后端（`pip install back-trader-cpp`）中位 128 倍加速——把 5 个策略放到不同波动率参数下批量扫描，几分钟就能看到"近似定价"对参数的敏感度。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；期权卖方存在远超权利金的尾部亏损风险。
