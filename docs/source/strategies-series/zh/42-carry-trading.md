# 套息交易：躺着收利差的科学，与 2008 年那场大雨

> 量化策略图鉴 · 第 42 篇 · 分类 `carry_trading`（4 个策略）· 2026-09-02

借入 0.1% 利率的日元，换成 5% 利率的澳元，什么都不做就有约 5% 的利差——套息交易（carry trade）曾被称为"世界上唯一免费的午餐"。2008 年金融危机撕掉了菜单：恐慌中日元急升，全球套息盘同时拆仓，AUD/JPY 数月暴跌，"收租的"一次性吐回几年的租金。**carry 不是免费午餐，而是承担尾部风险的溢价**——学术圈给它起了个直白的名字：carry crash。

为什么利差会存在？一种解释是"押上汇率贬值风险的对价"：高息货币的利率高，往往因为通胀高、央行紧，长期看汇率趋于走弱；低息货币（避险货币）在危机中反而升值。所以 carry 的每日收益是小额正数，危机日是巨额负数——收益分布像"捡硬币躺在压路机前面"。理解了这个结构，你就能理解本篇四个策略的共同取向：**用对冲、中性化与止损，把压路机往远处推一推**。

本篇解读 `tests/functional/strategies/carry_trading/` 下的 4 个回测。它们面对同一个工程难题——MT5 导出的历史数据里没有利率与期货期限结构——并给出了值得学习的答案：**用代理变量重构 carry**。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| 黄金-利率套息 | XAUUSD + IEF 日线 2008-2025 | 滚动 beta 推金价公允值，残差 z-score 赌收敛 | `test_0001_0031_gold_rate_carry.py` |
| 黄金相对价值 | 金/银/铂 日线 2010-2025 | 两对贵金属价差 z-score 反转交易 | `test_0002_0050_gold_relative_value.py` |
| FX 套息 | AUD/NZD/GBP/EURUSD 日线 | 基线 carry 分 + 长趋势 − 近波动构造代理，多高空低 | `test_0003_0393_carry_trading_strategy.py` |
| 商品套息 | DBC/GLD/金银铂钯 日线 | 短长窗口收益差近似 carry，截面排名多高空低 | `test_0004_0394_commodity_carry_strategy.py` |

## 深读一：FX 套息——没有利率数据，就造一个

[test_0003_0393_carry_trading_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/carry_trading/test_0003_0393_carry_trading_strategy.py) 的题眼是这段代理构造：

```python
trend = px['close'].pct_change(trend_window)      # 126 日长期趋势
vol = px['close'].pct_change().rolling(vol_window).std()  # 21 日波动
baseline = float(baseline_scores.get(symbol, 0.0))
carry_proxy = baseline + trend - vol
```

三个成分各有含义：`baseline_carry_scores` 编码先验的利差排序（AUDUSD 0.03、NZDUSD 0.025、GBPUSD 0.01、EURUSD -0.002）；长窗口趋势捕捉"高息货币的汇率漂移"；减去近期波动惩罚"动荡的高息货币"。**高息 + 趋势 + 平静 = 好 carry**——这正是学术文献里 carry 因子的典型行为画像。

每 21 天再平衡：四对货币按代理分排名，做多前 2、做空后 2（各腿上限 25% 名义本金），多空对冲后**近似美元中性**。回测 2008-2025 共 4,549 根 K 线、217 次调仓、200 笔交易，结果诚实得刺眼：终值 912,208.05（**-8.8%**）、Sharpe -0.27、胜率 41%。代理 carry 并没有复现利差收益——价格趋势项喧宾夺主了。这本身就是工程教训：**代理变量引入的偏差，会把因子策略变成另一个策略**。

## 深读二：黄金-利率套息——把 carry 变成一对协整关系

另一条路线不排名、而是配对。[test_0001_0031_gold_rate_carry.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/carry_trading/test_0001_0031_gold_rate_carry.py) 把黄金与利率代理 ETF（IEF）当作协整对，滚动回归求出金价对利率的"公允锚"，再对残差下注：

```python
gold_log = np.log(out['close'])
rate_log = np.log(out['rate_proxy_close'])
cov = gold_log.rolling(relationship_window).cov(rate_log)      # 126 日
var = rate_log.rolling(relationship_window).var().replace(0, np.nan)
out['beta'] = cov / var
out['fair_value'] = out['beta'] * rate_log
out['spread'] = gold_log - out['fair_value']                   # 残差
out['spread_z'] = rolling_zscore(out['spread'], relationship_window)

long_mask = (out['rate_z'] > entry_z) & (out['spread_z'] < -spread_entry_z)   # 利率拉伸且金价偏低
short_mask = (out['rate_z'] < -entry_z) & (out['spread_z'] > spread_entry_z)
```

进场要求两个条件同时成立：利率端处于 1 个标准差的极端，且金价相对公允值向**相反方向**偏离 0.5 个标准差——赌的是错杀与回归。出场在残差收敛到 ±0.2 以内，外加 3 倍 ATR 的硬止损兜底（仓位 25%，允许做空）。双 z-score 条件的设计比"价差偏离就进场"严谨一档：它要求**驱动端（利率）与被驱动端（金价）同时给出极端读数**，过滤掉了大量单边噪声。

4,258 根 K 线、117 笔交易，胜率 41% 但盈亏比撑起 profit factor 1.13，终值 1,032,287.54（+3.2%）。低胜率 + 靠盈亏比吃饭，正是均值回归家族的性格签名。

## 其余策略，快速点将

- **黄金相对价值**（`test_0002`）：金/银、金/铂两对价差 z-score 反转，按资产聚合权重、限制总敞口，`order_target_percent` 调仓。125 笔交易 profit factor 0.97——精准地不赚钱。
- **商品套息**（`test_0004`）：用"短期窗口收益 − 缩放后的长期窗口收益"近似期限结构 carry，六样商品截面排名、多前二空后二。118 次调仓后终值 1,306,885.25（+30.7%，Sharpe 0.52）——同是代理 carry，换一筐资产结果天差地别，再次印证本篇主题：carry 是风险溢价，不是物理定律。

## 一条命令跑起来

```bash
# 整个分类（4 个策略）
pytest tests/functional/strategies/carry_trading/ -v

# 只跑 FX 套息
pytest tests/functional/strategies/carry_trading/test_0003_0393_carry_trading_strategy.py -v
```

## 为什么在这个项目上研究套息交易

多资产对齐、逐日再平衡、多空双腿下单——套息回测把框架的并发数据流与订单簿压到满载。[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 的 runonce/runnext 双模式对拍确保多数据对齐在两种引擎下结果一致，1,152 个策略回归测试把每次调仓的成交数与终值钉成基线；纯 Python 引擎比原版快 46%，C++ 后端（`pip install back-trader-cpp`）中位 128 倍加速——足够把 21 天再平衡改成 5 天、把四对货币换成八对，系统性摸清代理 carry 的参数敏感度。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；套息交易在市场剧变时可能出现远超利差收益的亏损。
