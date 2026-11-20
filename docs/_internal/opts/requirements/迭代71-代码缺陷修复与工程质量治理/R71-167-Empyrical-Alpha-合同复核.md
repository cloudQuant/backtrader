# R71-167：Empyrical ALPHA 年化合同复核

日期：2026-11-20

## 决策

保留 `backtrader/analyzers/pyfolio.py` 当前的日均回归截距复利年化：

```text
alpha_series = strategy_return - beta * benchmark_return  # includes the intercept
ols_residual = alpha_series - mean(alpha_series)
ALPHA = (1 + mean(alpha_series)) ** 252 - 1
```

用户已明确选择兼容 Empyrical 0.5.5 的行为。当前代码的这个差异不按“应改为线性年化”的缺陷处理；本候选只增加回归与版本合同记录，不改生产数学，也不改 TODO 状态。

## 版本差异与复现

Empyrical 0.5.5 的 `alpha_aligned` 将日均 `alpha_series` 按年复利：`(1 + nanmean(alpha_series)) ** annualizer - 1`。其中 `alpha_series = y - beta * x` 仍包含回归截距；严格 OLS residual 是 `alpha_series - mean(alpha_series)`。Empyrical 0.5.0 则为 `nanmean(alpha_series) * annualizer`；项目的 10bp/day 示例因此分别得到约 28.6434% 和 25.2%。Empyrical 0.5.3 发布说明记录了 `alpha_aligned` 年化修复，解释了两版公式差异。

新增回归使用五个非恒定基准收益：`[-2%, -1%, 0%, 1%, 2%]`；策略收益按 `0.1% + 2 * benchmark + ols_residual` 构造，其中 `ols_residual = [0.1%, -0.2%, 0.2%, -0.2%, 0.1%]` 是非零、零均值且与基准正交的严格 OLS 残差。独立 OLS 参考得到 beta 为 2，`alpha_series` 均值（回归截距）为 0.1%；`alpha_series` 本身仍包含截距，严格 OLS 残差则为 `alpha_series - mean(alpha_series)`。由此：

- Empyrical 0.5.5 复利年化：`(1 + 0.001) ** 252 - 1 = 0.2864340444`，报告四位小数为 `0.2864`。
- Empyrical 0.5.0 线性年化：`0.001 * 252 = 0.252`，即 `25.2%`。
- 差值约为 `0.0344340444`，即 `3.4434` 个百分点。

测试在真实 Cerebro 生成的 PyFolio analyzer 上调用报告计算路径，不导入可选 Empyrical 包；期望值由测试内独立 OLS 及两种公式计算。

## 来源

- [Empyrical 0.5.0 `stats.py`](https://github.com/quantopian/empyrical/blob/0.5.0/empyrical/stats.py)：`alpha_aligned` 以均值乘年化因子。
- [Empyrical 0.5.3 release notes](https://github.com/quantopian/empyrical/releases/tag/0.5.3)：记录 `alpha_aligned` 年化修复。
- [Empyrical 0.5.5 source](https://github.com/quantopian/empyrical/blob/b8f59f9/empyrical/stats.py)：复利公式；本地 0.5.5 安装源码及该公式的数值结果已核对。
