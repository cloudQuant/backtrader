# 0132 Exp_SpearmanRankCorrelation_Histogram

## 策略概述

该样例是对 MT5 EA `0132_Exp_SpearmanRankCorrelation_Histogram` 的 Backtrader 迁移版。
原 EA 基于 `SpearmanRankCorrelation_Histogram` 指标的颜色状态交易，默认在 `H4` 周期上运行；支持三种入场/离场算法，默认模式为 `TradeMode 1`，即按零轴上下区域与颜色切换来同时处理开仓和反向平仓。

## 迁移思路

1. 使用现有 `M15` 数据重采样到 `H4`
2. 在 Backtrader 中重建 `SpearmanRankCorrelation_Histogram` 的 Spearman 排名相关系数计算
3. 还原颜色区间：`0/1/2/3/4`
4. 按默认 `TradeMode 1` 实现开仓与反向平仓规则
5. 保留单净头寸与固定 `SL/TP` 主流程

## 主要参数

- `fixed_lot`
- `stop_loss_pips`
- `take_profit_pips`
- `trade_mode`
- `range_n`
- `direction`
- `in_high_level`
- `in_low_level`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`（内部重采样到 `H4`）
- 运行：`./run.py`
- 绘图：`./run.py --plot`

## 当前回测结果

- Trades: `27`
- Net P&L: `3126.40`
- Win Rate: `48.15%`
- Profit Factor: `1.94`
- Max Drawdown: `2.98%`

## 对齐说明

- 原 EA 调用自定义 `SpearmanRankCorrelation_Histogram` 指标；当前版本直接在 Backtrader 中重建 Spearman 排名相关逻辑与颜色状态
- 原 EA 支持三种 `TradeMode`；当前版本保留对应三套分支，默认按 `TradeMode 1` 运行
- 原 EA 允许风险手数；当前版本先覆盖固定手数下的主策略逻辑
