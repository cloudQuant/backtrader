# 双动量与时序动量：一个做开关，一个做选择

> 量化策略图鉴 · 第 13 篇 · 分类 `momentum`（45 个策略）· 2026-09-02

动量大概是学术证据最扎实的异象：Jegadeesh 与 Titman 1993 年发现"过去 6-12 个月涨得好的股票，未来 3-12 个月还倾向于涨得好"。但真正让动量走进大众资产配置视野的，是 Gary Antonacci 的双动量（Dual Momentum）框架——它把动量拆成两个正交的问题：**绝对动量问"要不要在场"，相对动量问"在场买谁"**。另一条线是 Moskowitz、Ooi 与 Pedersen 2012 年的《Time Series Momentum》：不看别人，只看资产自己过去 12 个月的收益，为正就做多——这个简单到近乎偷懒的规则，在 58 个品种上普遍成立。

本篇解读 `tests/functional/strategies/momentum/` 下 45 个策略中的双动量与时序动量家族。它们大多以黄金（XAUUSD）为主角，从 2008 年一路回测到 2025 年——覆盖了黄金从 1900 美元跌到 1050、再从 1050 涨破 2000 的完整牛熊。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| 双动量（绝对动量开关） | XAUUSD 日线 2008-2025 | 每月月末查 252 日动量，超过阈值持有否则清仓 | `test_0001_dual_momentum.py` |
| 黄金双动量（四资产轮动） | XAUUSD/IVV/IEF/GLD 月线 | 12 个月相对动量选最强，最强者非正则持现金 | `test_0002_gold_dual_momentum.py` |
| 隔夜动量 | XAUUSD 日线 | 正向跳空 + 隔夜趋势延续做多，波动率目标 + 连亏熔断 | `test_0003_gold_overnight_momentum.py` |
| 时序动量（波动率目标版） | XAUUSD 日线 | 12 个月收益定方向，目标波动 15% 定仓位，8% 止损 | `test_0005_gold_time_series_momentum.py` |
| 贵金属横截面轮动 | 金银铂钯日线 | 21/63/252 日复合 ROC 打分，每月轮入最强者 | `test_0010_momentum_rotation_roc.py` |
| 52 周新高效应 | XAUUSD 日线 | 收盘价进入滚动高点 75%-98% 区间 + 站上 200SMA 入场 | `test_0014_52week_high_effect.py` |
| Antonacci 经典双动量 | XAUUSD vs GSPY 日线 | 金强于股且绝对动量为正持金，否则持股/现金 | `test_0015_dual_momentum_strategy.py` |
| 时序动量（多空版） | XAUUSD 日线 | 12 个月收益为正做多、为负做空，月度调仓 | `test_0013_gold_time_series_momentum.py` |
| 双周期 RSI 动量 | ORCL 日线 2010-2014 | RSI14>50 且 RSI5>65 做多，RSI5 跌破 45 平仓 | `test_101_rsi_long_short_strategy.py` |
| 双动量 + Vortex | XAUUSD 日线 | 252 日绝对动量为正且 VI+>VI- 入场，二者任一转弱离场 | `test_0022_dual_momentum_vortex.py` |
| 双周期动量过滤 | XAUUSD 日线 | 20 日与 60 日动量同为正才做多，共识破裂即平仓 | `test_0024_online_momentum.py` |

## 深读一：Dual Momentum——绝对动量做开关

[test_0001_dual_momentum.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/momentum/test_0001_dual_momentum.py) 是双动量的最小实现，逻辑浓缩在特征工程与 `next()` 里：

```python
def prepare_dual_momentum_features(df, params):
    out = df.copy()
    lookback = int(params.get('lookback_period', 252))
    risk_free = float(params.get('risk_free_threshold', 0.0))
    out['momentum'] = out['close'] / out['close'].shift(lookback) - 1
    out['abs_momentum'] = (out['momentum'] > risk_free).astype(float)
    ...
```

策略侧每月只做一次检查（[test_0001_dual_momentum.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/momentum/test_0001_dual_momentum.py)）：

```python
def next(self):
    ...
    month_key = bt.num2date(self.data.datetime[0]).month
    if month_key == self.current_month:
        return
    self.current_month = month_key
    abs_momentum = float(self.data.abs_momentum[0])
    if abs_momentum > 0.5:                 # 252 日动量为正
        if not self.position:
            self.pending_order = self.buy(size=self._get_position_size(...))
    else:                                   # 动量转负，清仓避险
        if self.position:
            self.pending_order = self.close()
```

18 年间只做了 14 笔交易（5 胜 8 负 1 平），胜率仅 35.7%——但盈利因子 2.36，终值 3,789,720（初始 100 万，总收益 278.97%），最大回撤 33.71%。这就是趋势跟随的典型画像：**多数小亏换少数大赚**。注意它的仓位计算除以了合约乘数（multiplier=100），期货式保证金价差与权益的换算不会被放大 100 倍——工程上这是个常踩的坑。另一个细节是 `pending_order` 闸门：订单未终结前 `next()` 直接返回，避免同一信号月内反复下单。这类小防线单看不起眼，却是回归测试数值能逐分钱对上的前提。

## 深读二：Gold Dual Momentum——相对动量做选择

单资产动量只能回答"在不在场"。[test_0002_gold_dual_momentum.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/momentum/test_0002_gold_dual_momentum.py) 把宇宙扩到四个资产（XAUUSD 现货金、IVV 标普 500、IEF 国债、GLD 黄金 ETF），日线重采样到月末对齐，完成 Antonacci 的完整拼图：

```python
momentum = close_table / close_table.shift(formation_period) - 1.0   # 12 个月动量
best_asset.loc[valid_mask] = momentum.loc[valid_mask].idxmax(axis=1)  # 相对动量：选最强
best_return.loc[valid_mask] = momentum.loc[valid_mask].max(axis=1)
selected_asset = best_asset.where(best_return > 0, 'CASH')            # 绝对动量：最强者也亏钱就持币
```

`next()` 里只在选择变化时调仓，用 `order_target_percent` 把选中资产打到 100%。结果：204 个月里股票占 96 个月、现货金 76 个月、国债 16 个月、GLD 5 个月、现金 11 个月，切换 52 次，终值 2,078,226（+107.82%）。最值得对比的是回撤：**12.08%**，比单资产版本（33.71%）砍掉了近三分之二——绝对动量的"现金开关"加上相对动量的分散，正是双动量在配置圈流行的原因。仓位分布还讲了一个真实的故事：牛市里最强者自然轮到风险资产，熊市里"最强者也亏钱"的判断又把组合推回现金——没有人写一行"择时"代码，两个动量条件自己完成了板块迁移。

## 深读三：时序动量——给趋势装上波动率油门

[test_0005_gold_time_series_momentum.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/momentum/test_0005_gold_time_series_momentum.py) 是 Moskowitz 们思想的工程加强版。方向由 12 个月收益定（强动量满仓、弱动量半仓），仓位再乘一个波动率缩放：

```python
out['annual_vol'] = out['daily_return'].rolling(vol_lookback).std() * np.sqrt(252)   # 20 日实现波动
vol_scale = (target_vol / out['annual_vol'].replace(0, np.nan)).clip(lower=0.5, upper=1.5)
out['vol_scale'] = vol_scale.fillna(1.0)
out['base_target'] = np.where(out['momentum_return'] > strong_threshold, 1.0,      # >10% 满仓
                       np.where(out['momentum_return'] > 0, 0.5, 0.0))              # >0 半仓
out['target_pct'] = out['base_target'] * out['vol_scale']
```

波动大就自动减仓（下限 0.5 倍）、波动小就加仓（上限 1.5 倍），目标年化波动 15%，另有 8% 百分比止损兜底。18 年 19 笔交易，终值 2,758,111（+175.81%），最大回撤 23.30%，Sharpe 0.70。对比深读一：收益略低但回撤与 Sharpe 都更好——**时序动量提供 beta，波动率目标负责把它磨平**。

## 其余策略，快速点将

- **Antonacci 经典版**（`test_0015`）：金 vs GSPY 的 1v1 双动量，12 个月滚动收益直接比大小，最贴近原书 GEM 的表述。
- **多空时序动量**（`test_0013`）：同一思想的另一份实现，`long_short` 开关打开后动量为负可做空。
- **隔夜动量**（`test_0003`）：交易跳空缺口延续，cheat-on-open 在开盘价入场，还带连亏熔断——日内结构最精细的一个。
- **双动量 + Vortex**（`test_0022`）：252 日慢动量定方向，14 日 Vortex 定时机，快慢搭配的典型做法。
- **双周期 RSI**（`test_101`）：ORCL 日线上 RSI14 与 RSI5 双确认，是全分类里少数的股票日线测试。

## 一条命令跑起来

```bash
# 整个分类（45 个策略）
pytest tests/functional/strategies/momentum/ -v

# 只跑双动量
pytest tests/functional/strategies/momentum/test_0001_dual_momentum.py -v
```

分类内的内联回归测试在 `runonce=True` 下运行并对断言基线逐一校验；像 `test_101` 这类测试则以 `runonce/runnext` 双模式参数化对拍——同一策略在向量化与事件驱动两种引擎下必须给出一致的指标。

## 为什么在这个项目上研究动量策略

动量策略参数敏感、回测窗口长、调仓逻辑分支多，最怕"引擎改了、数字悄悄变了"。[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 用 1,152 个策略回归测试把每个策略的终值、胜率、回撤全部钉成断言基线；runonce/runnext 双模式对拍保证向量化与事件驱动两条代码路径数值一致。纯 Python 引擎比原版快 46%，装上 C++ 后端（`pip install back-trader-cpp`）可获得中位 128 倍加速——把 252 日窗口换成 126、188、252 三档做敏感性分析，从"过夜任务"变成"喝口咖啡"。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
