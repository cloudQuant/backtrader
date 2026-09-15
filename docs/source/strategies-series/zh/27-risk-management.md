# 风险管理策略：波动率目标、分级回撤保护与危机对冲

> 量化策略图鉴 · 第 27 篇 · 分类 `risk_management`（19 个策略）· 2026-09-02

策略研究圈有个老笑话：新手问"这策略赚多少"，机构问"这策略回撤多少"。过去二十年机构配置技术里普及最快的两项，恰恰都不预测收益：**波动率目标**（vol targeting）——按目标波动率反推仓位，让组合的风险预算恒定；**回撤保护**——净值回撤越深、杠杆越低，用分级响应代替一把梭的止损。再叠加"危机 alpha"（gold、CTA 类资产在股灾中反而上涨的特性），就凑齐了本篇的三大主题。

本仓库 `tests/functional/strategies/risk_management/` 下收录 19 个策略：10 个真正的风险管理策略，外加一批 EA 迁移时归入此分类的均线族（下文如实说明）。深读三个代表：多级回撤保护、月线均线尾部风控、risk-on/risk-off 体制开关。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| Probit 风险建模 | XAUUSD 日线 2008-2025 | 滚动 probit 模型估计下行风险概率，切换满仓/空仓 | `test_0001_probit_risk_modeling_gold.py` |
| 多市场对冲 | GLD/GDX/IDU/IVV 日线 | 公用事业弱动量买黄金、强动量空矿商的条件对冲 | `test_0002_gold_multi_market_hedge.py` |
| 尾部风险均线预警 | XAUUSD 日线 2008-2025 | 收盘跌破 10 月均线即砍半仓的月度体制开关 | `test_0003_tail_risk_ma_warning.py` |
| 回撤保护 | XAUUSD 日线 2008-2025 | 波动率目标仓位 + 3%/6%/10% 多级回撤阈值降杠杆 | `test_0004_drawdown_protection.py` |
| 债券风险溢价 | 股票 + 债券 ETF | 股债目标权重配置，回撤超限即降风险 | `test_0005_bond_risk_premium.py` |
| 管理期货对冲 | XAUUSD 日线 | 快慢均线管理期货开关，定名义比例仓位 | `test_0006_managed_futures_hedge.py` |
| 危机对冲 | XAUUSD 日线 2008-2025 | 回撤破位或波动率超高分位即入场做多的避险策略 | `test_0007_crisis_hedge.py` |
| Risk On Risk Off | XAUUSD 日线 2008-2025 | 波动率低于阈值且价格在均线上方才持多 | `test_0008_risk_on_risk_off.py` |
| 风险溢价价值 | XAUUSD 日线 | 多周期收益 ÷ 波动率的风险调整评分定多空 | `test_0009_risk_premium_value.py` |
| 网格_delta 对冲 | XAUUSD 日线 | 对称价格网格 + 目标敞口随价格穿越递变，带再中置 | `test_0010_grid_trading_delta_hedge_strategy.py` |
| 0040 均线交叉 | XAUUSD 日线 | EA 移植均线交叉（均线族） | `test_0011_0040_moving_average_crossover.py` |
| 0150 平滑均线 | XAUUSD 日线 | EA 移植平滑均线（均线族） | `test_0012_0150_smoothing_average.py` |
| 0300 交叉均线 | XAUUSD 日线 | EA 移植交叉均线（均线族） | `test_0013_0300_crossing_moving_average.py` |
| 0375 改进均线 | XAUUSD 日线 | EA 移植改进均线（均线族） | `test_0014_0375_modified_moving_averages.py` |
| 0407 EA 均线 | XAUUSD 日线 | EA 移植均线（均线族） | `test_0015_0407_ea_moving_average.py` |
| 0705 均线交易系统 | XAUUSD 日线 | EA 移植均线系统（均线族） | `test_0016_0705_moving_average_trade_system.py` |
| 1120 均线 | XAUUSD 日线 | EA 移植均线（均线族） | `test_0017_1120_moving_average.py` |
| 1273 修正均线 | XAUUSD 日线 | EA 移植修正均线（均线族） | `test_0018_1273_corrected_average.py` |
| 1276 均线函数 | XAUUSD 日线 | EA 移植均线（均线族） | `test_0019_1276_movingaverage_fn.py` |

## 深读一：Drawdown Protection——波动率目标乘以回撤阶梯，再加平滑

[test_0004_drawdown_protection.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/risk_management/test_0004_drawdown_protection.py) 是机构风控的微缩模型。第一层是波动率目标：目标波动 12%，当前波动越高仓位越低，并截断在 [0.25, 1.0]：

```python
if current_vol > 0:
    vol_position = self.p.target_vol / current_vol      # target_vol = 0.12
    return max(0.25, min(1.0, vol_position))
```

第二层是回撤分级：价格相对滚动高点的回撤（`(close - cummax) / cummax`）每突破一档阈值，仓位系数降一级（文档口径 3%/6%/10% 对应 1.0/0.75/0.5/0.25）：

```python
if drawdown < -self.p.dd_threshold_1:      # 0.03
    return self.p.position_level_1         # 1.0
elif drawdown < -self.p.dd_threshold_2:    # 0.06
    return self.p.position_level_2         # 0.75
elif drawdown < -self.p.dd_threshold_3:    # 0.10
    return self.p.position_level_3         # 0.5
else:
    return self.p.position_level_4         # 0.25
```

两层取 `min` 后，还要过平滑与再平衡带两道缓冲：

```python
target_position = min(dd_position, vol_position)
smoothed_position = (self.current_position_pct * (1 - self.p.smoothing_factor) +
                     target_position * self.p.smoothing_factor)          # smoothing_factor = 0.15
if abs(smoothed_position - self.current_position_pct) > 0.05:            # 变化超 5% 才动手
    ... self.order_target_size(target=target_size)
```

**工程点评（本篇最重要的一段）**：仔细读上面阶梯的分支顺序——由于 `drawdown` 恒为非正值，`drawdown < -0.03` 一旦成立就直接返回 1.0，0.75/0.5 两档实际不可达；浅回撤反而落入 else 拿 0.25。迁移基线锁定的正是这份代码的**真实行为**而非文档意图——2008-2025 年 4,618 根日线、289 次再平衡、终值 2,732,100.12（+173.21%）、Sharpe 0.616、最大回撤 31.43%。这正是断言基线的价值：如果你修复这个阶梯顺序，基线会立刻变红，提醒你"改动"本身需要被审视与重新记录，而不是无声漂移。

## 深读二：Tail Risk MA Warning——10 月均线的月度体制开关

2008 年金融危机后，"跌破 10 月均线就减仓"从期货老手的土办法升格为学术文献里的尾部风险缓解模型（Meb Faber 的经典研究用的正是 10 月均线）。[test_0003_tail_risk_ma_warning.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/risk_management/test_0003_tail_risk_ma_warning.py) 完整复刻了这条规则：

```python
monthly_close = out['close'].groupby(month_end_index).last()
monthly_ma = monthly_close.rolling(ma_period).mean()                # ma_period = 10 个月
monthly_risk_state = (monthly_close < monthly_ma).astype(float)
active_risk_state = monthly_risk_state.shift(1).reindex(month_end_index).fillna(0.0)  # 防"前视"
out['target_pct'] = np.where(out['risk_state'] >= 0.5, risk_position, normal_position)  # 0.5 / 1.0
```

三个细节见功力：日线数据按月分组取月末收盘，信号按月粒度生成；`shift(1)` 把体制状态延后一个月生效——上月末跌破均线，本月才降仓，杜绝用当月信息交易当月；再平衡设 2% 容差带，避免目标在边界上抖动导致频繁下单。2008-2025 年基线：216 个自然月中 68 个月处于风险状态（31.48%），状态切换 32 次；24 个月跌幅超过 5% 的"大亏月"里 16 个月（66.67%）发生在均线之下——体制开关确实把多数大亏月挡在了门外。终值 3,806,875.01（+280.69%），Sharpe 0.555，最大回撤 39.41%（黄金 2011-2015 熊市面前，减半仓也只能缓解、不能免疫）。

## 深读三：Risk On Risk Off——两个开关定义一种体制

[test_0008_risk_on_risk_off.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/risk_management/test_0008_risk_on_risk_off.py) 把华尔街口中的"risk-on/risk-off"压缩成两个条件的与运算：

```python
out['realized_vol'] = ret.rolling(vol_period).std() * np.sqrt(252)         # vol_period = 60
out['trend'] = (out['close'] > out['close'].rolling(ma_period).mean()).astype(float)  # ma_period = 100
out['risk_on'] = ((out['realized_vol'] < vol_threshold) & (out['trend'] > 0.5)).astype(float)  # 0.20
```

年化波动率低于 20% **且**价格站在 100 日均线上方，才算 risk-on，满仓持多；任一条件失守即清仓观望。基线给了个耐人寻味的分布：81 笔交易只赢 23 笔（胜率 28.40%），盈利因子却高达 3.75——典型的"体制过滤"形态：多数小止损 + 少数大趋势，终值 3,881,633.30（+288.16%），Sharpe 0.746，SQN 2.27，最大回撤 19.44%，是三个深读中回撤控制最好的一个。

## 其余策略，快速点将

- **Probit 风险建模**（`test_0001`）：用 probit 回归估计"近期大跌概率"，超过阈值就空仓——统计模型当风控开关用。
- **多市场对冲 / 危机对冲**（`test_0002/0007`）：前者黄金多 + 矿商空的相对价值组合，后者专门在股灾体制里买黄金吃"危机 alpha"。
- **债券风险溢价 / 管理期货对冲 / 风险溢价价值**（`test_0005/0006/0009`）：股债配比降风险、CTA 式趋势开关、收益/波动比评分——三类经典机构配方。
- **网格 delta 对冲**（`test_0010`）：对称网格买低卖高，目标敞口随价格穿越逐格调整，定期或破带再中置。
- **均线族（test_0011-0019）**：如实说明——这 9 个是 EA 迁移时按来源归入本分类的均线策略（0040/0150/0300/0375/0407/0705/1120/1273/1276），本身不含风控逻辑，当作"风险管理的邻居"浏览即可。

## 一条命令跑起来

```bash
# 整个分类（19 个策略）
pytest tests/functional/strategies/risk_management/ -v

# 只跑 Drawdown Protection
pytest tests/functional/strategies/risk_management/test_0004_drawdown_protection.py -v

# 只跑尾部风险均线预警
pytest tests/functional/strategies/risk_management/test_0003_tail_risk_ma_warning.py -v
```

## 为什么在这个项目上研究风险管理

风控策略的效果藏在长周期、多体制的细节里，最经不起引擎数值漂移的折腾。[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 用 1,152 个策略回归测试与逐策略指标断言基线，把"回撤阶梯的分支顺序"这类微妙行为也固定成可复现的事实；runonce/runnext 双模式对拍确保向量化与事件驱动两条执行路径给出同一份风险曲线。纯 Python 引擎比原版快 46%，C++ 后端（`pip install back-trader-cpp`）中位 128 倍加速——够你把 3%/6%/10% 的阈值扫成一片参数高原，看看自己站的到底是山峰还是平原。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
