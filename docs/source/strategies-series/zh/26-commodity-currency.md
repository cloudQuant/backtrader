# 商品货币与宏观：COT 持仓报告、实际利率与三因子外汇

> 量化策略图鉴 · 第 26 篇 · 分类 `commodity_currency`（21 个策略）· 2026-09-02

澳元为什么跟铁矿石走？黄金为什么怕加息？答案藏在一条宏观驱动链里：**利率决定持仓成本，持仓成本决定资金流向，资金流向决定价格**。实际利率上行，持有无息资产黄金的机会成本升高，金价承压；风险偏好升温，资金涌向高贝塔的商品货币，AUD、NZD 对美元走强。这条链条给了宏观策略一个宿命：你必须同时看价格和价格之外的变量。

本仓库 `tests/functional/strategies/commodity_currency/` 下的 21 个策略正是围绕这条链展开的：CFTC 持仓报告、实际利率代理、股指与债券动量因子、库存与偏度横截面……每个都是单文件完整回测。本篇深读三个代表：三因子宏观外汇、COT 聪明钱、实际利率信号。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| 变点检测交易 | XAUUSD 日线 2008-2025 | 滚动收益均值/波动比检测市场结构突变 | `test_0001_gold_change_point_trading.py` |
| Walk-Forward | XAUUSD 日线 2008-2025 | 滚动窗内优化参数、窗外执行，抑制过拟合 | `test_0002_gold_walk_forward.py` |
| 因子择时 | XAUUSD/IVV/GTIP 月线 | 价值因子+动量因子给黄金定敞口 | `test_0003_gold_factor_timing.py` |
| Gold COT | XAUUSD 周线 + CFTC 报告 | 商业/投机净持仓 z 值极端时跟"聪明钱" | `test_0004_gold_cot.py` |
| 汇率预测 | XAUUSD/DXYN/EURUSD/USDJPY | 滚动线性回归用汇率多周期收益预测黄金 | `test_0005_gold_currency_prediction.py` |
| 商品趋势 | XAUUSD 日线 2008-2025 | 快慢均线经典趋势跟随系统 | `test_0006_gold_commodity_trend.py` |
| Quantpedia 组合 | XAUUSD 日线 2008-2025 | 三个 Quantpedia 式黄金异象的做多合成 | `test_0007_gold_quantpedia_strategies.py` |
| 策略生命周期 | XAUUSD 日线 2010-2025 | SMA200 策略的 Sharpe 衰减与回撤健康度评估 | `test_0008_gold_strategy_lifecycle.py` |
| ETF 排名系统 | GLD/IAU/GDX/GDXJ/BAR | 五只黄金 ETF 按风险调整动量轮动 | `test_0009_gold_ranking_system.py` |
| 实际利率信号 | XAUUSD/IEF/GTIP 日线 | 名义/通胀代理对数比率近似实际利率，降息周期持金 | `test_0010_gold_real_rate_signal.py` |
| 道指黄金比 | XAUUSD/DJIA 日线 | 金价/道指比值的均值回归与百分位排名 | `test_0011_djia_gold_ratio_strategy.py` |
| GDX 隔夜时段 | GDX 日线 | 矿业股隔夜收益的时段效应 + 50 日趋势过滤 | `test_0012_gdx_overnight_session_strategy.py` |
| ARIMA-GARCH | XAUUSD 日线 | ARIMA 预测收益方向、GARCH 定仓位比例 | `test_0013_arima_garch_gold_strategy.py` |
| 多信号择时 | XAUUSD 日线 | SMA/动量/波动率体制/RSI 四信号加权定仓位阶梯 | `test_0014_gold_market_timing.py` |
| 商品偏度 | XAU/XAG/XPT/XPD/DBC | 贵金属横截面偏度因子多空配置 | `test_0015_commodity_skewness_strategy.py` |
| Macro FX | 四货币对 + IVV/IEF | 增长/利率/趋势三因子 z 值按 beta 缩放配权 | `test_0016_macro_fx_strategy.py` |
| 金属库存 | XAU/XAG/XPT/XPD 日线 | 贵金属库存变化驱动的四品种配置 | `test_0017_metal_inventory_strategy.py` |
| FX 回归学习 | EURUSD 日线 2022-2025 | carry/动量/价值/波动特征的滚动回归信号 | `test_0018_fx_regression_learning_strategy.py` |
| KA Gold Bot | XAUUSD M5 2025-12 | 含点差过滤的 MT5 分钟级黄金机器人 | `test_0019_0019_ka_gold_bot_mt5.py` |
| SilverTrend v3 | XAUUSD M15 2025-2026 | SilverTrend 趋势指标 EA 移植 | `test_0020_0698_silvertrend_v3.py` |
| SilverTrend 双周期 | XAUUSD M15 + H1 | H1 信号流 + M15 执行流的双时间框架版 | `test_0021_0910_silvertrend.py` |

## 深读一：Macro FX——三因子 z 值，按商品敏感度缩放

[test_0016_macro_fx_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/commodity_currency/test_0016_macro_fx_strategy.py) 交易 EURUSD、AUDUSD、NZDUSD、GBPUSD 四个货币对，但信号全部来自两个不交易的宏观代理：IVV（标普 500 ETF，增长代理）与 IEF（国债 ETF，利率代理）。因子构造只有几行：

```python
growth_factor = _zscore(ivv['close'].pct_change(macro_lookback), zscore_lookback)      # 股指 63 日动量 z 值
rates_factor = _zscore(-ief['close'].pct_change(macro_lookback), zscore_lookback)      # 债券动量取反
...
raw_signal = (
    factor_weights['growth'] * growth_factor * beta +   # 0.4
    factor_weights['rates'] * rates_factor * beta +     # 0.35
    factor_weights['trend'] * pair_trend                # 0.25，货币对自身 63 日动量 z 值
)
target_percent = raw_signal.clip(lower=-signal_threshold, upper=signal_threshold) / max(signal_threshold, 1e-6) * max_pair_weight
```

设计有两处值得咀嚼。其一，**利率因子取负号**：债券上涨（收益率下行）→ 利率因子为正 → 加仓商品货币——这正是"利率→持仓成本→价格"链条的向量化表达。其二，**beta 缩放**：AUDUSD/NZDUSD 作为典型商品货币 beta=1.0 拿满宏观信号，EURUSD 0.6、GBPUSD 0.8 逐级打折；信号再截断在 ±0.5、映射到单品种 ±25% 权重上限，每 21 个交易日调一次仓。risk-on 体制下高贝塔货币被抬高，risk-off 下削减甚至反向——一套杠杆随宏观状态呼吸的机器。基线：2008-2025 年 4,331 根日线、259 笔交易，终值 1,040,485.14（+4.05%），盈利因子 1.037，最大回撤 34.82%。四货币对分散后曲线平得像货币策略该有的样子。

## 深读二：Gold COT——跟商业头寸的"聪明钱"

美国商品期货交易委员会（CFTC）每周五发布 Commitments of Traders 报告，把持仓拆成商业（套保者）与非商业（投机者）。经典假设：商业头寸是"聪明钱"，投机头寸是待收割的"群众"。[test_0004_gold_cot.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/commodity_currency/test_0004_gold_cot.py) 把这个假设写成 156 周（三年）滚动 z 值的极端判定：

```python
out['commercial_z'] = (cot_weekly['commercial_net'] - commercial_mean) / commercial_std   # zscore_window_weeks = 156
out['speculator_z'] = (cot_weekly['speculator_net'] - spec_mean) / spec_std
long_entry = (out['commercial_z'] >= extreme_threshold) & (out['speculator_z'] <= -extreme_threshold)   # ±2.0
long_exit = (out['commercial_z'] < exit_threshold) & (out['speculator_z'] > -exit_threshold)             # ±1.0
```

商业极端做多且投机极端做空时入场，两组 z 值向中性回归时离场。仓位随极端程度缩放：基础 3%、上限 5%，另有 3% 止损与"连亏 3 次暂停 4 周"的冷却。工程上这份测试尤其扎实：日线 XAUUSD 重采样到 W-FRI 周线与 CFTC 数据对齐得到 888 根可用 K 线，COT 数据本地缓存、缺失时自动从 CFTC 历史归档下载。结果同样诚实：22 笔交易胜率 36.36%，终值 997,205.05（-0.28%），盈利因子 0.749——"聪明钱"假设在这 20 年黄金上没有兑现超额收益，基线把它如实记录。

## 深读三：实际利率信号——用 ETF 对数比率代理实际利率

实际利率 = 名义利率 − 通胀预期，是黄金定价的第一变量。[test_0010_gold_real_rate_signal.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/commodity_currency/test_0010_gold_real_rate_signal.py) 的巧思在于不引入宏观数据库，直接用两只 ETF 的比值近似：

```python
ratio = nominal['close'] / inflation['close']        # IEF / GTIP
signal_df['real_rate_proxy'] = np.log(ratio)
signal_df['real_rate_change'] = ... - ....shift(signal_window)                      # 63 日变化
signal_df['real_rate_trend'] = ... - ....rolling(trend_window).mean()               # 126 日趋势
...
active = rr_change < entry_threshold and rr_trend < 0 and drawdown > -stop_loss_pct  # 0.0 / 8%
```

实际利率"在降且低于趋势"（利好黄金）且黄金自身未陷深度回撤时，按信号强度给 50%-100% 目标仓位；年化波动超过 25% 的高波动体制仓位直接减半；每月再平衡一次。2011-2025 年基线：2,748 根日线、10 笔交易，终值 1,064,691.53（+6.47%），盈利因子 1.284，最大回撤 25.10%，Sharpe 0.135。低频、低换手、逻辑直白——宏观信号策略的典型体格。

## 其余策略，快速点将

- **变点检测 / Walk-Forward**（`test_0001/0002`）：一个找市场结构突变，一个用滚动优化对抗过拟合——方法论价值大于收益价值。
- **因子择时 / Quantpedia 组合 / 多信号择时**（`test_0003/0007/0014`）：黄金版"因子动物园"，价值、动量、波动体制、RSI 各显神通。
- **汇率预测 / FX 回归学习**（`test_0005/0018`）：滚动回归两兄弟，一个用汇率预测黄金，一个在 EURUSD 上自回归。
- **道指黄金比 / GDX 隔夜**（`test_0011/0012`）：经典比率择时与矿业股时段效应。
- **ARIMA-GARCH**（`test_0013`）：计量经济学标配，预测方向 + 波动定仓二合一。
- **偏度 / 库存**（`test_0015/0017`）：贵金属横截面因子，从分布形态和实物库存两个非常规维度下注。
- **KA Gold Bot / SilverTrend×2**（`test_0019/0020/0021`）：分钟级 EA 移植，给宏观分类添了点日内烟火气。

## 一条命令跑起来

```bash
# 整个分类（21 个策略）
pytest tests/functional/strategies/commodity_currency/ -v

# 只跑 Macro FX
pytest tests/functional/strategies/commodity_currency/test_0016_macro_fx_strategy.py -v

# 只跑 Gold COT（首次运行可能需要下载 CFTC 历史归档）
pytest tests/functional/strategies/commodity_currency/test_0004_gold_cot.py -v
```

## 为什么在这个项目上研究宏观策略

宏观策略的天敌是数据管线拖沓与结果漂移：多序列对齐、重采样、外部数据源，任何一环的细微变化都会悄悄改写结论。[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 用 1,152 个策略回归测试和逐策略指标断言基线把这些漂移钉死——本篇三个深读的每一个数字，都是任何一次重跑都必须复现的断言。纯 Python 引擎比原版快 46%，多因子、多参数的宏观实验当天出结果；C++ 后端（`pip install back-trader-cpp`）中位 128 倍加速，把因子扫描从"等一晚"变成"喝口水"。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
