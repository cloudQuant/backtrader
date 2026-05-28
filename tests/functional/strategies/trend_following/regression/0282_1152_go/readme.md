# 1152 GO

## 策略概述

该策略是对 MT5 EA `GO` 的 Backtrader 迁移版本。

原 EA 基于四条移动平均线价格和成交量计算 `GO` 值：

`GO=((C-O)+(H-O)+(L-O)+(C-L)+(C-H))*V`

其中 `C/O/H/L` 分别是 `Close/Open/High/Low` 价格均线值，`V` 是信号柱的成交量。

## 交易逻辑

- 若 `GO > OpenLevel`，则做多
- 若 `GO < -OpenLevel`，则做空
- 多头在 `GO < OpenLevel - CloseLevelDif` 时平仓
- 空头在 `GO > -(OpenLevel - CloseLevelDif)` 时平仓

## 风控逻辑

- `lots > 0` 时使用固定手数
- `lots = 0` 时按 `cash * maximum_risk / 1000` 估算手数
- 原 EA 中 `StopLoss` / `TakeProfit` 为内部固定 `0`，因此这里保持无固定 `SL/TP`

## 文件

- `strategy_go.py` - 数据加载、GO 公式与开平仓逻辑实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

- 数据：`XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` 到 `2026-03-10 09:00:00`
- 参数：`lots=0.1`、`maximum_risk=0.05`、`shift=1`、`ma_period=174`、`ma_shift=0`、`ma_method=ema`、`vol_volume=tick`、`open_level=0.0`、`close_level_dif=0.0`
- 信号次数：`5955`
- 已平仓交易：`224`
- TradeAnalyzer 统计交易：`225`
- 胜率：`34.22%`
- 期初资金：`100000.00`
- 期末现金：`101748.20`
- 期末权益：`101773.20`
- 净收益：`1773.20`
- 最大回撤：`7.31%`
- SQN：`0.12`

说明：样本结束时仍保留 `1` 笔多单未平仓，`open_position_size=0.1`、`open_position_price=5097.6`。
