# 1164 gpfTCPivotStop

## 策略概述

该策略是对 MT5 EA `1164_gpfTCPivotStop` 的 Backtrader 迁移版本。

原 EA 使用上一交易日的日线高低收计算标准枢轴位和三档支撑/阻力位，在价格收盘穿越主枢轴 `Pivot` 时开仓，并按支撑/阻力档位设置止损与止盈。

## 交易逻辑

- 用前一日 `high/low/close` 计算 `Pivot`、`Support1-3`、`Resist1-3`
- 当上一根已完成柱的收盘价上穿 `Pivot` 时做多
- 当上一根已完成柱的收盘价下穿 `Pivot` 时做空
- 若启用 `is_trade_day`，则在 `23:00` 直接平掉当日持仓

## 风控逻辑

- `target_profit` 选择对应层级的 `SL/TP`
- 若启用 `mod_sl`，到达第一目标位后将止损推到开仓价附近
- `lots = 0` 时按 `cash * max_risk / 1000` 估算手数
- 若连续亏损超过 1 笔，则按 `decrease_factor` 递减新开仓手数

## 文件

- `strategy_gpftcpivotstop.py` - 数据加载、枢轴位与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

- 数据：`XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` 到 `2026-03-10 09:00:00`
- 参数：`lots=0.1`、`target_profit=3`、`is_trade_day=false`、`mod_sl=false`
- 信号次数：`142`
- 已平仓交易：`10`
- TradeAnalyzer 统计交易：`11`
- 胜率：`63.64%`
- 期初资金：`100000.00`
- 期末现金：`97275.47`
- 期末权益：`97300.47`
- 净收益：`-2699.53`
- 最大回撤：`9.05%`
- SQN：`-0.41`

说明：样本结束时仍保留 `1` 笔未平仓多单，持仓数量 `0.1`、开仓价 `5171.12`，因此 `TradeAnalyzer` 统计交易数与已平仓交易数存在 `1` 笔差异。
