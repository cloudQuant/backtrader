# 1164 gpfTCPivotStop

## 策略概述

该策略是对 MT5 EA `1164_gpfTCPivotStop` 的 Backtrader 迁移版本。

原 EA 依据前一交易日的日线高低收计算 `Pivot`、`Support1-3`、`Resist1-3`，并在当前周期价格收盘穿越 `Pivot` 时开仓。

## 交易逻辑

- 使用前一日 `D1` 柱的 `high/low/close` 计算枢轴位
- 当上一根已完成柱 `close` 上穿 `Pivot` 时做多
- 当上一根已完成柱 `close` 下穿 `Pivot` 时做空
- `tgt_profit=1/2/3` 决定初始 `SL/TP` 使用第 1/2/3 级支撑阻力位
- 若启用 `is_trade_day`，则在 `23:00` 平仓
- 若启用 `mod_sl`，则在价格达到第一目标位后把止损移动到开仓价附近的保本位置

## 资金管理

- `lots > 0` 时使用固定手数
- `lots = 0` 时按 `cash * max_risk / 1000` 估算手数
- 若连续亏损超过 1 笔，则按 `decrease_factor` 递减新开仓手数

## 对齐说明

迁移版本保留了原 EA 的核心思想：

- 日线枢轴位驱动的单品种入场
- 分级目标位止盈止损
- 可选日内平仓
- 可选第一目标触发后的保本移损

未细化建模 MT5 实盘中的 `spread` 与最小止损距离检查，因此未实现源码中的第二套“过近则改用更远 SL/TP”分支。

## 文件

- `strategy_gpftc_pivot_stop.py`
- `run.py`
- `config.yaml`

## 用法

```bash
python run.py
```

## 回测结果

Pending validation.
