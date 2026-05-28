# 0649 真实锁定剥头皮利润 (True Scalper Profit Lock)

## 策略概述

该策略是对 MT5 EA `0649_真实锁定剥头皮利润` 的 Backtrader 迁移版本。

- EMA(3) + EMA(7) 交叉 + RSI(2) 过滤
- 可选 `Abandon` 超时平仓与强制反向/信号重判重入场
- 保本止损（盈利触发后将 SL 移至入场价附近）
- 固定 SL/TP，单仓

## 核心逻辑

1. 当 EMA(3) > EMA(7) 且 RSI 确认看跌到看涨转换 → 做多。
2. 当 EMA(3) < EMA(7) 且 RSI 确认看涨到看跌转换 → 做空。
3. 盈利达 `break_even_trigger` 点后，将止损移至入场价 + `break_even` 点。
4. 若持仓 bar 数达到 `abandon`：
   - `abandon_method_a = true` 时，平掉当前仓位并在下一次可交易机会强制反向重入。
   - `abandon_method_b = true` 时，平掉当前仓位并重新按指标条件判断方向。

## 迁移说明

- 原 EA 支持资金管理（MoneyManagement）；迁移版简化为固定手数。
- 单仓限制保留。

## 主要参数

- `stop_loss` / `take_profit`
- `rsi_value` / `rsi_method_a` / `rsi_method_b`
- `abandon_method_a` / `abandon_method_b` / `abandon`
- `break_even_trigger` / `break_even`

## 运行方式

```bash
python run.py
```
