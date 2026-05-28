# 1161 Universal_Investor

## 策略概述

该策略是对 MT5 EA `1161_Universal_Investor` 的 Backtrader 迁移版本。

原 EA 使用同周期 `EMA` 与 `LWMA` 的相对位置和方向来决定入场方向，并在反向关系出现时平仓。

## 交易逻辑

- 当 `LWMA > EMA`，且 `LWMA` 与 `EMA` 均向上时做多
- 当 `LWMA < EMA`，且 `LWMA` 与 `EMA` 均向下时做空
- 持有多单时，若 `LWMA < EMA` 则平仓
- 持有空单时，若 `LWMA > EMA` 则平仓

## 资金管理

- `lots > 0` 时使用固定手数
- `lots = 0` 时按 `cash * maximum_risk / 1000` 估算手数
- 若启用 `decrease_factor`，则在连续亏损后递减新开仓手数

## 文件

- `strategy_universal_investor.py` - 数据加载、EMA/LWMA 信号与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

- 数据：`XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` 到 `2026-03-10 09:00:00`
- 参数：`moving_period=23`、`lots=0.1`、`maximum_risk=0.05`、`decrease_factor=0.0`
- 信号次数：`3861`
- 已平仓交易：`135`
- TradeAnalyzer 统计交易：`136`
- 胜率：`33.82%`
- 期初资金：`100000.00`
- 期末现金：`104526.90`
- 期末权益：`104551.90`
- 净收益：`4551.90`
- 最大回撤：`5.75%`
- SQN：`0.44`

说明：样本结束时仍保留 `1` 笔未平仓多单，持仓数量 `0.1`、开仓价 `5123.33`，因此 `TradeAnalyzer` 统计交易数与已平仓交易数存在 `1` 笔差异。
