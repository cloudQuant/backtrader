# 1030 Well_Martin

## 策略概述

该示例是对 MT5 EA `1030_Well_Martin` 的 Backtrader 迁移版本。
策略在 `M15` 周期上使用 `Bollinger Bands` 与 `ADX`，当价格突破布林带外侧且趋势强度较低时入场；若上一笔交易亏损，则下一笔按 `KLot` 倍增手数，超过 `MaxLot` 后恢复到初始 `Lot`。

## 原始信号逻辑

1. 计算 `BBands(period=84, dev=1.8)` 与 `ADX(period=40)`
2. 当 `ADX[1] < 45` 且收盘价跌破上一根柱的下轨时做多
3. 当 `ADX[1] < 45` 且收盘价突破上一根柱的上轨时做空
4. 每次仅保留单一持仓
5. 若上一笔平仓亏损，则下一笔手数按 `KLot=2` 倍增；超过 `MaxLot=5` 后回到 `Lot=0.1`

## 迁移说明

- 保留单持仓与亏损后手数倍增逻辑
- 保留固定 `SL/TP`
- 原 EA 的 `Stealth` 可见止损标签不迁移为图表对象，仅保留等价的内部风控行为
- 原始 `EURUSD M15` 建议在当前项目统一样本下改为 `XAUUSD M15` 做框架内验证

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`
