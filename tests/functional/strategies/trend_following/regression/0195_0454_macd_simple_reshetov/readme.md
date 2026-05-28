# 0454 MACDSimpleReshetov

## 策略来源
- MT5 EA: `ea/0454_MACDSimpleReshetov/macdsimplereshetov.mq5`
- Backtrader 实现: `examples/0454_macd_simple_reshetov/strategy_macd_simple_reshetov.py`
- 运行脚本: `examples/0454_macd_simple_reshetov/run.py`

## 核心逻辑
- 使用 `MACD` 主线与信号线的同侧关系判断开仓方向。
- 当 `main` 与 `signal` 同号时，若 `main > 0` 且 `main > signal`，开多。
- 当 `main` 与 `signal` 同号时，若 `main < 0` 且 `main < signal`，开空。
- 始终只保留单一净头寸；若持有多单且 `main < 0`，或持有空单且 `main > 0`，则平仓退出。
- 源码不包含固定止损、固定止盈与加仓逻辑，迁移版保持相同的单仓反向平仓结构。

## 参数映射
- `Lots=2.0`
- `DF=1`
- `DS=2`
- `SignalPeriod=10`
- 对应 `MACD(fast=11, slow=13, signal=10)`

## 回测数据
- 数据：`examples/../../../datas/XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` -> `2026-03-10 09:00:00`
- Bar shift：`15` 分钟

## 回测结果
- 初始资金：`100000.00`
- 期末权益：`291834.00`
- 净收益：`191834.00`
- 收益率：`191.83%`
- 平仓交易数：`235`
- 胜率：`30.93%`
- Profit Factor：`1.35`
- 最大回撤：`37.55%`
- Sharpe：`12.90`

## 对齐说明
- MT5 源码只在新 bar 触发时读取 `MACD`，迁移版也保持逐 bar 决策。
- MT5 以 `PositionsTotal` + `magic/symbol` 约束单品种单仓；迁移版直接使用 Backtrader 单净仓语义实现同等约束。
- 原策略允许样本结束时仍保留未平仓头寸，迁移版保持该行为，期末权益包含浮动盈亏。
