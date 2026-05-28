# 0611 Morse Code (摩斯代码)

## 策略概述

该策略是对 MT5 EA `0611_摩斯代码` 的 Backtrader 迁移版本。

- 按预设二进制蜡烛组合（`1`=阳线，`0`=阴线）匹配入场
- 方向固定（参数选择做多或做空）
- 固定 SL/TP

## 核心逻辑

1. 将 `pattern_mask` 整数转换为二进制字符串（如 `5` → `'11'`，`6` → `'000'`）。
2. 检查前 N 根已完成 K 线是否逐一匹配该二进制模式。
3. 匹配成功时按 `pos_type` 方向开仓，设置固定 SL/TP。
4. 持仓触及 SL 或 TP 时平仓。

## 迁移说明

- 原版使用 `ENUM_PATTERN_MASK` 枚举映射 0..61 到 1~5 位二进制串；迁移版用 `mask_to_pattern()` 等价实现。
- 原版方向由 `InpPosType` 参数决定（Buy 或 Sell）；迁移版用 `pos_type` 字符串参数。
- 原版固定手数 `0.1`；迁移版保留对应参数。

## 主要参数

- `pattern_mask` — 蜡烛模式整数（默认 0，即单根阴线 `'0'`）
- `pos_type` — 交易方向（`'buy'` 或 `'sell'`）
- `take_profit` / `stop_loss` — 止盈/止损点数
- `lots` — 固定手数

## 运行方式

```bash
python run.py
```
