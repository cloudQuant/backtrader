# 0653 RSI EA

## 策略概述

该策略是对 MT5 EA `0653_RSI_EA` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心结构：

- RSI 超买/超卖区域触发开仓
- 可选信号反转平仓
- 可选固定 `SL/TP` 和移动止损
- 单仓限制

## 核心逻辑

1. 当 `RSI` 从下方穿越 `rsi_buy_level` 时做多。
2. 当 `RSI` 从上方穿越 `rsi_sell_level` 时做空。
3. 若 `close_by_signal = true`：
   - 持多时 RSI 下穿 `rsi_sell_level` 则平仓
   - 持空时 RSI 上穿 `rsi_buy_level` 则平仓
4. 可选 `SL/TP` 和 `trailing_stop` 管理持仓。

## 迁移说明

- 原 EA 要求对冲账户但只允许同一方向最多 1 仓位；迁移版按单净仓实现。
- 原版使用 `CMoneyFixedMargin` 做手数管理；迁移版简化为固定手数参数。
- 示例使用 `XAUUSD_M15.csv` 并按 `H1` 压缩运行。

## 主要参数

- `rsi_period`
- `rsi_buy_level`
- `rsi_sell_level`
- `stop_loss`
- `take_profit`
- `trailing_stop`
- `close_by_signal`
- `open_buy` / `open_sell`

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与首版可运行脚手架已建立。
- 待后续补做本地回测校验，再同步台账中的验证结果。
