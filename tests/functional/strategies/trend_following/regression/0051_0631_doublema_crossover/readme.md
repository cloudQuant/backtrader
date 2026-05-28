# 0631 DoubleMA Crossover EA

## 策略概述

该策略是对 MT5 EA `0631_DoubleMA_Crossover_EA` 的 Backtrader 迁移版本。

- 双 MA 交叉 + 突破幅度过滤
- 可选移动止损（含三级阶梯）
- 时间过滤（迁移版省略）
- 固定 SL/TP，单仓

## 核心逻辑

1. `MA_fast - MA_slow > breakout_level` → 做多。
2. `MA_slow - MA_fast > breakout_level` → 做空。
3. 反向交叉平仓。
4. 可选 trailing stop。

## 迁移说明

- 原 EA 有时间过滤（StartHour/StopHour）和周五全平仓；迁移版省略时间逻辑。
- 原 EA 有三级阶梯式 trailing stop；迁移版简化为单级 trailing。
- 原 EA 限定18个货币对；迁移版不做品种限制。

## 主要参数

- `fast_ma_period` / `slow_ma_period`
- `breakout_level` / `signal_candle`
- `stop_loss` / `take_profit`
- `use_trailing_stop` / `trailing_stop`

## 运行方式

```bash
python run.py
```
