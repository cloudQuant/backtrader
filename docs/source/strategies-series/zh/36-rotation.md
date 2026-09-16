# 轮动策略：每月一次的排名，把动量从单标的变成组合游戏

> 量化策略图鉴 · 第 36 篇 · 分类 `rotation`（6 个策略）· 2026-09-02

单标的动量策略回答"它涨没涨"，轮动策略回答的是"**谁涨得最凶**"。这一问之差，把动量从时间序列变成了横截面：Moskowitz、Ooi 与 Pedersen 在 2012 年那篇著名的时序动量研究里实证了 58 个品种的惯性，而 Gary Antonacci 的双动量框架则把"相对动量选资产、绝对动量做开关"组合成了个人投资者也能执行的资产配置方案。轮动，就是相对动量的组合应用。

本篇解读 `tests/functional/strategies/rotation/` 下的 6 个策略。它们共享同一套骨架：多资产对齐 → 周期性排名 → 择强持有 → 配一个"打不过就撤"的安全资产。黄金、债券、现金构成的避险阶梯，在这里被反复演绎成不同版本。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| 黄金资产轮动 | XAUUSD/IVV/IEF/DBC 月线 2006-2025 | 3 月动量排名，前二 70/30 分仓，绝对动量不过线则遁入 IEF | `test_0001_gold_asset_rotation.py` |
| 避险资产轮动 | 金/银/日元/瑞郎/IEF 日线 2008-2025 | 多周期动量混合排名 + 63 日均线趋势确认，失败退回债券 | `test_0002_safe_haven_rotation.py` |
| 择时债券轮动 | IVV + 四只债券 ETF 日线 2008-2025 | 股票 200 日线上方持股，下方切换至最强动量债券 | `test_0003_timing_bond_rotation.py` |
| 月度排名轮动 | XAUUSD 日线 2008-2025 | 收益百分位排名进入上半区买入，跌破 0.3 平仓 | `test_0004_monthly_rotation_ranking.py` |
| 三因子 ETF 轮动 | IVV/IWM/IEF/GLD/EEM 日线 2021-2025 | 3 月动量 + 20 日动量 + 20 日波动率三因子打分，前 3 等权 | `test_0005_three_factor_etf_rotation_strategy.py` |
| 跨资产轮动 | IVV/IEF/GLD/DBC 日线 2008-2025 | 126 日收益排名取前二，单资产上限 50% | `test_0006_rotational_trading_strategy.py` |

## 深读一：黄金资产轮动——相对动量选强，绝对动量守门

[test_0001_gold_asset_rotation.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/rotation/test_0001_gold_asset_rotation.py) 是整套双动量思想的教科书实现。四个资产——金（XAUUSD）、美股（IVV）、美债（IEF）、商品（DBC）——先重采样到月末对齐，再算 3 个月动量并排名：

```python
closes = pd.DataFrame({name: frame['close'] for name, frame in monthly_frames.items()}, index=common_index)
momentum = closes / closes.shift(lookback_months) - 1.0

# ...逐月排名后分配权重...
if top1_score > threshold:
    if pd.notna(top2_score) and top2_score > threshold:
        weights[top1] = top1_weight      # 0.7
        weights[top2] = top2_weight      # 0.3
    else:
        weights[top1] = 1.0
else:
    weights[defensive_asset] = 1.0       # 遁入 IEF
```

精妙全在门槛 `threshold=0.0`：相对排名只解决"谁更强"，但若连第一名动量都不为正，说明天下大乱，资金整体撤入防御资产 IEF——相对动量负责进攻，绝对动量负责风控，Antonacci 的双动量骨架一目了然。策略侧每月检查目标权重，一变就对四个资产逐个 `order_target_percent` 再平衡。20 年月线（236 根 bar）跑出 185 次买入、59 笔交易、158 次再平衡，胜 36 负 22——20 年里只换仓 59 轮，动量策略的低换手特性可见一斑。

## 深读二：择时债券轮动——一条 200 日均线画出的风险开关

[test_0003_timing_bond_rotation.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/rotation/test_0003_timing_bond_rotation.py) 把轮动简化成一道二选一：股票 ETF（IVV）在 200 日均线上方就持股，跌破就撤入"当下动量最强的债券"：

```python
equity_close = close_df['equity']
ma200 = equity_close.rolling(ma_period).mean()
bullish = (equity_close > ma200).astype(float)

# ...债券动量：4 个期限前重加权...
momentum_scores[symbol] = (
    w1 * prices.pct_change(r1) +      # 21 日，权重 12
    w3 * prices.pct_change(r3) +      # 63 日，权重 4
    w6 * prices.pct_change(r6) +      # 126 日，权重 2
    w12 * prices.pct_change(r12)      # 252 日，权重 1
) / 4.0

signal_df['target_asset'] = signal_df['best_bond']
signal_df.loc[signal_df['equity_above_ma'] > 0.5, 'target_asset'] = 'equity'
```

注意债券打分里 12/4/2/1 的前重权重：近期动量权重是远期的 12 倍，久期各异的债券（IEF/AGG/BND/GOVT）用同一把"越新越重要"的尺子衡量。每 21 个交易日检查一次，持仓漂移超过 5% 才动手——`rebalance_threshold=0.05` 是对交易成本的尊重。基线：3,212 根 bar、16 笔交易、25 次再平衡、胜 8 负 7。2008–2025 的样本跨越了两次美股深度熊市，这条均线开关的价值不在提高收益，而在那些"股票在均线下方"的月份里你持有什么。

## 深读三：月度排名轮动——单标的也能"自轮动"

谁说轮动一定要多资产？[test_0004_monthly_rotation_ranking.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/rotation/test_0004_monthly_rotation_ranking.py) 用一个标的自己和自己比——把 63 日收益在过去一年里做百分位排名，就是在问"此刻的它，比历史上大多数时候强吗"：

```python
out['return_rank'] = out['close'].pct_change(lookback).rolling(min(252, len(out))).rank(pct=True)

# ...每 21 根 bar 置一次 rebalance_flag...
rank = float(self.data.return_rank[0])
if not self.position:
    if rank > 0.5:
        self.buy_count += 1
        self.pending_order = self.buy(size=self._get_position_size())
else:
    if rank < 0.3:
        self.sell_count += 1
        self.pending_order = self.close()
```

进场阈值 0.5、出场阈值 0.3，中间隔着一段"持仓缓冲带"——排名在 0.3~0.5 之间时什么都不做，避免排名在门槛附近抖动导致的反复开平。这种非对称缓冲是所有排名类策略最实用的小设计。黄金 18 年日线跑出 4,324 根 bar、20 笔交易、胜 12 负 7，期货式佣金（万 2、1% 保证金、100 倍乘数）下的低频节奏一目了然。

## 其余三席，快速点将

- **避险资产轮动**（`test_0002`）：金、银、日元、瑞郎（汇率取倒数变成"币种强势"序列）加债券后备，63/126 日双周期排名混合，榜首还需站上 63 日均线才算数。4,287 根 bar 只做了 3 笔完整交易、123 次再平衡、胜 3 负 0——避险资产的轮动，慢得近乎修身养性。
- **三因子 ETF 轮动**（`test_0005`）：在动量之外引入 20 日波动率因子（越低越好），0.4/0.4/0.2 加权取前三等权，2021-2025 样本 1,245 根 bar、56 次再平衡——多因子排名的模板代码。
- **跨资产轮动**（`test_0006`）：最朴素的版本：126 日收益排前二、各配 50% 上限，每 21 日再平衡，4,518 根 bar、216 次再平衡——把它当对照组，正好看清前五个策略各自多加了什么佐料。

## 一条命令跑起来

```bash
# 整个分类（6 个策略）
pytest tests/functional/strategies/rotation/ -v

# 只跑黄金资产轮动
pytest tests/functional/strategies/rotation/test_0001_gold_asset_rotation.py -v
```

## 为什么在这个项目上研究轮动策略

轮动是天然的多数据源、多周期策略：重采样、对齐、排名、再平衡每一步都可能引入数值漂移，而"排名差一名"就是完全不同的持仓。[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 用 1,152 个策略回归测试把这些场景全部钉死，runonce/runnext 双模式对拍确保向量化与事件驱动两条路径给出同一个排名；纯 Python 引擎比原版快 46%，C++ 后端（`pip install back-trader-cpp`）中位 128 倍加速，让 18 年 × 4 资产的月度重采样回测从"等结果"变成"顺手跑"。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
