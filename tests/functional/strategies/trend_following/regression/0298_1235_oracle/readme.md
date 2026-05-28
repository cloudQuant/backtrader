# 1235 Oracle

## 策略概述

该策略是对 MT5 EA `1235_Exp_Oracle` 的 Backtrader 迁移版本。
原 EA 基于 `Oracle` 重绘指标交易，支持三种入场方式：
`breakdown`、`twist`、`disposition`。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `H4`
2. 用相同周期的 `RSI` 与 `CCI` 重建 `Oracle` 主线
3. 对主线做 `Smooth` 窗口平均得到 `Signal` 线
4. 根据模式选择入场：
   - `breakdown`：Signal 穿越零轴
   - `twist`：Signal 方向拐点
   - `disposition`：Signal 与 Oracle 主线交叉
5. 信号出现时按原 EA 规则平掉反向仓位并反手

## 主要参数

- `indicator_minutes`
- `mode`
- `oracle_period`
- `applied_price`
- `smooth`
- `recount`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

原始 `Oracle` 指标带有 `recount/redrawing` 选项，默认会使用可重绘版本。
本迁移版默认保持该行为，并沿用 EA 默认的 `twist` 模式。
