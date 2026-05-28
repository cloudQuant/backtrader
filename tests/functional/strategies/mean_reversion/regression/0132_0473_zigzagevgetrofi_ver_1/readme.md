# 0473 ZigZagEvgeTrofi 版本1

## 策略概述

该策略是对 MT5 EA `0473_ZigZagEvgeTrofi_版本1` 的 backtrader 迁移版本。
原 EA 在新 bar 上读取最近的 `ZigZag` 顶点；若最近顶点位于最高价，则给出买入信号并关闭已有空头；若位于最低价，则给出卖出信号并关闭已有多头。只要最近顶点仍处于 `Urgency` 范围内，就允许继续按同方向加仓。

## 核心逻辑

1. 在每根新 K 线检查最近确认的 `ZigZag` 枢轴点
2. 最近顶点为高点时生成多头信号；最近顶点为低点时生成空头信号
3. `signal_reverse=true` 时反转信号方向
4. 若有反向持仓则先平仓
5. 当最近顶点年龄不超过 `urgency` 时，允许继续按固定手数 `lot` 同向开仓

## 主要参数

- `depth`
- `deviation`
- `backstep`
- `lot`
- `signal_reverse`
- `urgency`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- 数据区间：`2025-12-03 01:15:00` → `2026-03-10 09:00:00`
- K线数量：`6129`
- 买入次数：`1622`
- 卖出次数：`975`
- 平仓交易数：`229`
- 期末权益：`137582.60`
- 净收益：`37582.60`
- 总收益率：`37.58%`
- 胜率：`31.30%`
- Profit Factor：`1.10`
- 最大回撤：`47.55%`

## 对齐说明

- 原 EA 使用 MT5 内置 `Examples/ZigZag` 指标；当前版本使用 backtrader 内部近似的 recent-pivot ZigZag 逻辑生成信号
- 原 EA 允许在 `Urgency` 范围内重复同向开仓；当前版本保留该行为，并在 Backtrader 净头寸模型下体现为同向加仓
- 原 EA 无固定止损止盈；当前示例同样不设置固定 `SL/TP`
