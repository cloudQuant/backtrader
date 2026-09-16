# 资产配置：60/40、风险平价与永久组合——赚 beta 的艺术

> 量化策略图鉴 · 第 23 篇 · 分类 `asset_allocation`（23 个策略）· 2026-09-02

择时策略问"什么时候买"，配置策略问"买多少、买什么"——一字之差，世界观迥异。择时者相信能预测方向，配置者承认预测很难，转而依靠资产间的低相关性分散风险，赚市场本身的钱（beta）。1926 年经济学家们就提出股债组合理论，而"60/40"（60% 股票+40% 债券）统治机构组合长达大半个世纪，直到 2008 年金融危机暴露它的软肋：危机来临时股债相关性飙升，60/40 一起沉船。风险平价（Risk Parity）由此崛起——Bridgewater 的 All Weather 把"钱按风险等分而不是按金额等分"变成了万亿级生意。

本篇解读 `tests/functional/strategies/asset_allocation/` 下的 23 个配置策略：从朴素的 60/40 趋势增强版，到 Harry Browne 的永久组合、CPPI 组合保险，再到 Lopez de Prado 的层次风险平价（HRP）。全部是多资产、可复现的完整回测。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| 60/40 趋势增强 | XAUUSD 日线 2008-2025 | SMA200 过滤：线上 60% 仓位、线下降到 30%，63 天再平衡 | `test_0011_sixty_forty_portfolio.py` |
| 永久组合 | GLD/IVV/IEF 日线 | 股/债/金/现金各 25%，年度+阈值再平衡 | `test_0007_permanent_portfolio.py` |
| CPPI 组合保险 | XAUUSD 日线 | 80% 峰值保底线，垫子×3 倍杠杆定敞口 | `test_0017_cppi_portfolio_insurance.py` |
| 层次风险平价 HRP | XAUUSD 日线 | 层次聚类+二分递归定权，无需求逆协方差 | `test_0012_hierarchical_risk_parity.py` |
| TAA 风险平价趋势 | DBC/GLD/IEF/IVV 日线 | 风险平价权重叠加趋势过滤 | `test_0008_taa_risk_parity_trend.py` |
| HERC | XAUUSD 日线 | HRP 的层级等风险贡献变体 | `test_0015_herc_portfolio.py` |
| 黄金 60/40 增强 | XAUUSD/IVV/IEF 日线 | 传统 60/40 加入黄金腿 | `test_0002_gold_60_40_enhancement.py` |
| 黄金增强 60/40 | GTIP/IEF/IVV/XAUUSD | 加通胀保值债的四资产版 | `test_0003_gold_enhanced_60_40.py` |
| 三一组合 | XAUUSD 日线 | 4% 法则的提取率组合 | `test_0005_trinity_portfolio_gold.py` |
| 反脆弱组合 | XAUUSD 日线 | 凸性优先的杠铃结构 | `test_0014_anti_fragile_portfolio.py` |
| 波动率管理 | XAUUSD 日线 | 目标波动率反比定仓 | `test_0004_volatility_managed_portfolio_gold.py` |
| 最优黄金配置 | DBC/GLD/IEF/IVV 日线 | 黄金在多资产中的权重寻优 | `test_0018_optimal_gold_allocation_strategy.py` |
| 加密最优配置 | GLD/IBIT/IEF/IVV 日线 | 比特币ETF进组合 | `test_0019_crypto_optimal_allocation_strategy.py` |
| 自适应配置 AAA | DBC/GLD/IEF/IVV 日线 | 动量+波动率双因子调权 | `test_0022_adaptive_asset_allocation_strategy.py` |
| 战术资产配置 TAA | GLD/IEF/IVV 日线 | 信号驱动的动态偏离 | `test_0023_tactical_asset_allocation.py` |
| 复合配置 | BIL/EFA/GTIP/IEF/IVV 日线 | 五资产多信号复合 | `test_0010_composite_asset_allocation.py` |
| 聚合时机 | XAUUSD 日线 | 多信号聚合的时机选择 | `test_0013_taa_aggregate_timing.py` |

## 深读一：60/40 趋势增强——给经典装上止损

[test_0011_sixty_forty_portfolio.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/asset_allocation/test_0011_sixty_forty_portfolio.py) 是经典 60/40 的"趋势过滤版"。它用单资产（黄金）近似股腿、用降杠杆近似债腿：价格在 SMA200 之上时目标敞口 60%，跌破则砍到 30%——"线下半仓"本质上是给组合装了软止损。信号侧：

```python
out["ma"] = out["close"].rolling(ma_period).mean()          # ma_period = 200
out["trend_up"] = (out["close"] > out["ma"]).astype(float)
# 每 rebalance_days = 63 天打一次再平衡标记
```

策略侧在再平衡日按趋势调仓，偏离超过 10% 才动手：

```python
target_weight = self.p.equity_weight if trend_up else 0.30   # 0.60 / 0.30
if abs(current_size - target_size) > target_size * 0.1:
    self.pending_order = self.close()                        # 先平后调
```

**回测结果**：XAUUSD 日线 2008-2025、100 万本金，17 年只调仓 19 次，13 胜 6 负（胜率 68.4%），终值 2,542,114（+154.2%），利润因子 5.24，最大回撤仅 11.9%，Sharpe 0.770。低频+趋势过滤的组合拳，回撤控制远好于买入持有（对照全目录：简单持有同段黄金的回撤要大得多）。想看"不加过滤的 60/40"长什么样？`test_0002` 与 `test_0003` 提供了多资产版本对照。

## 深读二：永久组合——25%×4 的极简哲学

Harry Browne 1981 年提出永久组合（Permanent Portfolio）：股票、债券、黄金、现金各 25%，赌的是"未来永远处于繁荣/衰退/通胀/通缩四态之一，且每态总有一类资产受益"。实现（[test_0007_permanent_portfolio.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/asset_allocation/test_0007_permanent_portfolio.py)）用 GLD/IVV/IEF 三只 ETF 日线加上现金腿：

```python
params = dict(
    target_weights={'GLD': 0.25, 'IVV': 0.25, 'IEF': 0.25},
    cash_weight=0.25,
    rebalance_threshold=0.05,          # 一般资产漂移带 5%
    gold_rebalance_threshold=0.02,     # 黄金波动大，给更紧的 2%
)
```

再平衡触发是"年度 + 阈值"双轨制，这正是实盘配置的标准工程：

```python
if current_year != self.last_rebalance_year:
    self._rebalance()                          # 每年第一个交易日强制再平衡
    return
if self._needs_threshold_rebalance():          # 漂移超带，提前纠偏
    self.threshold_rebalance_count += 1
    self._rebalance()
```

**回测结果**：2008-2025、4,518 个交易日，共触发 50 次再平衡（其中 32 次是阈值触发——黄金腿的 2% 紧带果然忙碌），终值 4,268,547（+326.9%），年化 8.43%，最大回撤 32.3%，Sharpe 0.659。注意：这段区间黄金与美股都是大牛，数字偏乐观；但"金腿用更紧的漂移带"这类细节，是教科书不写、回测才会告诉你的。

## 深读三：CPPI——用数学保本

CPPI（Constant Proportion Portfolio Insurance，常数比例组合保险）是 1980 年代为"保本基金"发明的技术：设定一条不能跌破的底线（floor），组合市值高出底线的部分叫"垫子"（cushion），风险资产敞口 = 垫子 × 乘数。涨得越多垫子越厚、敞口越大；跌的时候垫子收缩、自动减仓，理论上永不击穿底线。实现（[test_0017_cppi_portfolio_insurance.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/asset_allocation/test_0017_cppi_portfolio_insurance.py)）：

```python
running_max = out['close'].cummax()
floor_value = running_max * floor_pct                  # floor_pct = 0.8，峰值的 80%
out['cushion_pct'] = (out['close'] - floor_value) / out['close']
out['exposure'] = (out['cushion_pct'] * cppi_mult).clip(0.0, 1.0)   # multiplier = 3.0
```

每 21 天再平衡一次，敞口高于 10% 才建仓、低于 5% 清仓。**回测结果**：35 笔交易、14 胜 20 负（胜率只有 40%），终值 1,533,999（+53.4%），Sharpe 0.447。胜率不到一半却稳稳盈利——盈亏不对称才是 CPPI 的性格：3 倍乘数让上涨时垫子迅速放大敞口，下跌时快速缩表。它的敌人是"Gap 风险"（一步跳空击穿底线），日线级 20% 的缓冲垫在 2008 式崩盘里是否够用，值得你自己改参数验证。

## 其余策略，快速点将

- **HRP/HERC**（`test_0012` / `test_0015`）：Lopez de Prado 在《Advances in Financial Machine Learning》中提出的协方差求逆替代方案——层次聚类 + 二分递归，权重稳定可解释，是风险平价的现代版本。
- **双资产杠杆组合**（`test_0009`）：只配风险资产+现金两腿的最小可行配置。
- **波动率配置族**（`test_0020` / `test_0021`）：按目标波动率在股债间切换。
- **随机数据组合寻优**（`test_0006`）：在 GDX/XAGUSD/XAUUSD 上演示组合优化管线。
- **开盘到开盘 TAA**（`test_0016`）：以开盘价而非收盘价执行再平衡，检验执行时点敏感性。

## 一条命令跑起来

```bash
# 整个分类（23 个策略）
pytest tests/functional/strategies/asset_allocation/ -v

# 只跑永久组合
pytest tests/functional/strategies/asset_allocation/test_0007_permanent_portfolio.py -v
```

## 为什么在这个项目上研究资产配置

配置策略的回测瓶颈在多资产对齐与再平衡调度：几十年的日线、多份数据、成百上千次再平衡事件，每一次都涉及现金计算与多腿下单顺序。[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 把这些都做成了经过 1,152 个策略回归测试检验的基建：纯 Python 引擎比原版快 46%，C++ 后端（`pip install back-trader-cpp`）中位 128 倍加速，再平衡频率、漂移带宽度这类参数扫描不再是过夜任务；runonce/runnext 双模式对拍与指标断言基线，确保你比较的是配置思想的差异，而不是引擎的数值漂移。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
