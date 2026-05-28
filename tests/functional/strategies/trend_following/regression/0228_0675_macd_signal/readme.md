# 0675 MACD 信号

## 策略概述

该策略是对 MT5 EA `0675_MACD_信号` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心结构：

- `ATR(200)` 生成动态阈值
- `MACD MAIN - SIGNAL` 跨越阈值时入场
- `Delta` 反向跨越零轴时平仓
- 固定 `TP`
- trailing stop

## 核心逻辑

1. 计算 `ATR(200)`，得到 `rr = ATR * LEVEL`。
2. 计算 `Delta = MACD.main - MACD.signal`。
3. 若 `Delta > rr` 且前一根 `Delta1 < rr`，则做多。
4. 若 `Delta < -rr` 且前一根 `Delta1 > -rr`，则做空。
5. 多单期间若 `Delta < 0` 则平仓；空单期间若 `Delta > 0` 则平仓。
6. 按固定 `take_profit` 和 `trailing_stop` 管理持仓。

## 迁移说明

- 原 EA 还包含账户资金检查与 MT5 交易包装类调用；迁移版仅保留信号与净头寸管理核心。
- 原版没有固定止损，只有固定止盈和 trailing stop；迁移版保持这一结构。

## 主要参数

- `take_profit`
- `lots`
- `trailing_stop`
- `pfast`
- `pslow`
- `psignal`
- `level`

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与首版可运行脚手架已建立。
- 待后续补做本地回测校验，再同步台账中的验证结果。
