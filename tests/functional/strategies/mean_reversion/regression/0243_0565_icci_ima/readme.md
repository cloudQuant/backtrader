# 0565 iCCI_iMA

## 策略概述

该策略是对 MT5 EA `0565_iCCI_iMA` 的 Backtrader 迁移版本。

- 使用 CCI 与“CCI 的 EMA”交叉做入场
- 使用另一条 CCI 的阈值/交叉做离场
- 支持固定 `SL/TP`
- 可选简单资金系数放大

## 核心逻辑

1. 计算主 `CCI` 与其 `EMA`。
2. 当 `CCI` 自下向上穿越 `EMA` 时做多；自上向下穿越时做空。
3. 多头离场：
   - `CCI_close` 自上向下跌破 `100`
   - 或主 `CCI` 向下跌破 `EMA`
4. 空头离场：
   - `CCI_close` 自下向上升破 `-100`
   - 或主 `CCI` 向上升破 `EMA`

## 迁移说明

- 原版通过 `iMA(..., handle_iCCI)` 直接对 CCI 缓冲区求 EMA；迁移版在 Backtrader 中使用 `EMA(CCI)` 等价近似。
- 原版资金管理按账户资金与 `deposit` 形成手数系数，迁移版保留了一个简化版本并做上限约束。

## 运行方式

```bash
python run.py
```
