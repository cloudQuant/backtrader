# 0799 e-Regr

## 策略概述

该策略是对 MT5 EA `0799_e-Regr` 的 Backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，并在回测内重采样到 `H1` / `D1`，保留了原 EA 的核心结构：

- 基于 `i-Regr` 回归通道计算上轨、中轨、下轨
- 价格触碰下轨做多、触碰上轨做空
- 价格回到中轨时平仓
- 前一日 `D1` 波动过大时禁止交易
- 可选 trailing stop 参数框架

## 核心逻辑

1. 在 `H1` 周期上，用最近 `regr_bars + 1` 根收盘价拟合多项式回归通道
2. 计算中轨，并按残差标准差与 `regr_kstd` 得到上下轨
3. 当价格触碰下轨时做多
4. 当价格触碰上轨时做空
5. 持仓后在价格回到中轨时离场
6. 如果上一根 `D1` 的振幅超过 `protection * point`，则当根禁止开仓
7. 如启用 trailing，则在盈利达到阈值后按固定距离推移止损

## 主要参数

参数定义在 `config.yaml` 中，主要包括：

- `trade_time`
- `lots`
- `stop_loss`
- `take_profit`
- `protection`
- `regr_degree`
- `regr_kstd`
- `regr_bars`
- `trailing_on`
- `trailing_start`
- `trailing_size`
- `repeat_n`

## 当前数据与运行方式

当前使用数据：

- `../../../datas/XAUUSD_M15.csv`

运行命令：

```bash
python run.py
```

如果需要绘图：

```bash
python run.py --plot
```

## 当前回测结果

当前参数下的回测结果：

- Trades: `0`
- Net P&L: `0.00`
- Win Rate: `0.00%`
- Profit Factor: `None`
- Max Drawdown: `0.00%`

## 对齐说明

- 原 EA 依赖 MT5 自定义指标 `i-Regr`；当前版本在 Python 中直接重建多项式回归通道
- 原 EA 使用 `H1` 交易与 `D1` 日波动保护；当前版本用 `XAUUSD M15` 数据重采样近似实现
- 原 EA 会循环下单 `RepeatN` 次；当前版本用聚合仓位 `lots * repeat_n` 近似复现总暴露
