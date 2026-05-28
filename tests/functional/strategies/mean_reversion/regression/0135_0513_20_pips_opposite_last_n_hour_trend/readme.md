# 0513 20 Pips Opposite Last N Hour Trend

## 策略概述

该策略是对 MT5 EA `0513_20_Pips_Opposite_Last_N_Hour_Trend` 的 Backtrader 迁移版本。

- 在指定小时开仓
- 方向与过去 N 小时的趋势相反
- 固定 TP，无显式 SL
- 连续亏损后按档位放大下一笔仓位

## 核心逻辑

1. 在 `trading_hour` 对应的时段，只允许一次新信号。
2. 如果当前 `H1 close` 高于 N 小时前的 `H1 close`，认为上行趋势存在，则逆势做空；反之做多。
3. 持仓只按固定 `TP` 管理。
4. 若连续亏损，下一笔按配置倍率放大，且受 `max_lot` 限制。
5. 离开指定交易小时后，清理未平持仓。

## 迁移说明

- 原版通过历史成交回溯计算最近连续亏损倍率；迁移版用已闭合 trade 的 `pnlcomm` 序列做同义近似。
- 原版使用 `H1` 趋势判断，迁移版使用 `M15` 数据重采样出 `H1`。

## 运行方式

```bash
python run.py
```
