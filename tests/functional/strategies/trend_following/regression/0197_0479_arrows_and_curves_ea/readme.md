# 0479 箭头和曲线 EA

## 策略概述

该策略是对 MT5 EA `0479_箭头和曲线_EA` 的 backtrader 迁移版本。
原 EA 使用 `arrows_curves` 自定义指标的买卖箭头缓冲区作为入场信号；当前版本在 backtrader 中复刻该指标的通道、翻转和箭头缓冲区逻辑，并保留单仓切换、固定 `SL/TP` 与可选 trailing stop。

## 核心逻辑

1. 基于 `SSP`、`Channel`、`Ch_Stop`、`relay` 计算高低通道与 stop 通道
2. 指标 `BuyBuffer` 非零时触发多头信号
3. 指标 `SellBuffer` 非零时触发空头信号
4. 无持仓时按信号开仓
5. 有持仓时若出现反向信号则平掉反向仓位
6. 可选按固定 `Trailing Stop + Trailing Step` 做追踪止损

## 主要参数

- `lots`
- `stop_loss_pips`
- `take_profit_pips`
- `trailing_stop_pips`
- `trailing_step_pips`
- `ssp`
- `channel`
- `ch_stop`
- `relay`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `214`
- Net P&L: `-26.80`
- Win Rate: `46.73%`
- Profit Factor: `1.00`
- Max Drawdown: `2.90%`

## 对齐说明

- 原 EA 仅在新 bar 决策；当前版本保持 bar 级执行
- 原 EA 依赖 `arrows_curves.mq5` 自定义指标；当前版本已在 backtrader 中内置等价缓冲区计算逻辑
- 原 EA 支持风险百分比算手数；当前示例默认按固定手数 `0.1` 回测
