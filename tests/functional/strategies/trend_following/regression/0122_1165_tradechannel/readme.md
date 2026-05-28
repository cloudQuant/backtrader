# 1165 TradeChannel

## 策略概述

该策略是对 MT5 EA `1165_TradeChannel` 的 Backtrader 迁移版本。

原 EA 基于固定长度价格通道计算上轨、下轨和参考级别 `Pivot=(Resist+Support+Close)/3`，并结合 ATR 通道外止损与尾随止损进行管理。

## 交易逻辑

- 基于最近 `channel_period` 根已完成 K 线计算 `Resist`、`Support`
- 基于再向前平移一根柱的同长度窗口计算 `ResistPrev`、`SupportPrev`
- 若上一根最高价触及稳定上轨，或上一根收盘位于 `Pivot` 之上且低于稳定上轨，则产生多头信号
- 若上一根最低价触及稳定下轨，或上一根收盘位于 `Pivot` 之下且高于稳定下轨，则产生空头信号
- 多头在上一根最高价再次触及稳定上轨时平仓
- 空头在上一根最低价再次触及稳定下轨时平仓

## 风控与资金管理

- 多单止损设为 `Support - ATR`
- 空单止损设为 `Resist + ATR`
- 若启用 `trailing`，则按固定点数向有利方向抬升/下压止损
- `lots = 0` 时按 `cash * max_risk / 1000` 估算手数
- 若连续亏损超过 1 笔，则按 `decrease_factor` 递减新开仓手数

## 文件

- `strategy_tradechannel.py` - 数据加载、通道逻辑与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

- 数据：`XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` 到 `2026-03-10 09:00:00`
- 参数：`lots=0.1`、`atr_period=4`、`channel_period=20`、`trailing=300`
- 信号次数：`396`
- 已平仓交易：`395`
- TradeAnalyzer 统计交易：`396`
- 胜率：`87.88%`
- 期初资金：`100000.00`
- 期末现金：`109242.98`
- 期末权益：`109267.98`
- 净收益：`9267.98`
- 最大回撤：`5.07%`
- SQN：`1.59`

说明：样本结束时仍保留 `1` 笔未平仓空单，持仓数量 `-0.1`、开仓价 `5052.90`，因此 `TradeAnalyzer` 统计交易数与已平仓交易数存在 `1` 笔差异。
