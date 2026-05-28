# 1320 Meeting Lines + MFI

## 策略概述

该策略是对 MT5 EA `1320_MQL5_向导_-_基于_牛市约会线_熊市约会线形态的交易信号_+_MFI` 的 Backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，保留了原 EA 的核心结构：

- 牛市 / 熊市约会线（Meeting Lines）反转形态识别
- MFI 作为入场确认过滤
- 基于 MFI 阈值穿越的离场

## 核心逻辑

1. 识别最近两根已完成 K 线是否构成 `Bullish Meeting Lines` 或 `Bearish Meeting Lines`
2. 当识别出牛市约会线，且 `MFI < 40` 时做多
3. 当识别出熊市约会线，且 `MFI > 60` 时做空
4. 持有多单时，MFI 在 `30 / 70` 阈值发生反向穿越时平多
5. 持有空单时，MFI 在 `30 / 70` 阈值发生反向穿越时平空

## 主要参数

参数定义在 `config.yaml` 中，主要包括：

- `mfi_period`
- `mfi_entry_long`
- `mfi_entry_short`
- `mfi_exit_upper`
- `mfi_exit_lower`
- `ma_period`
- `lot`
- `point`
- `price_digits`

## 当前数据与运行方式

当前使用数据：

- `../../../datas/XAUUSD_M15.csv`

运行命令：

```bash
python run.py
```

如果需要绘图：

```bash
python run.py --plot
```

## 当前回测结果

当前参数下的回测结果：
 
 - Trades: `0`
 - Net P&L: `0.00`
 - 说明：在当前 `XAUUSD M15` 数据区间内，Meeting Lines + MFI 的组合未触发有效开仓信号。

## 对齐说明

- 原 EA 属于 MQL5 Wizard 的蜡烛形态 + MFI 确认模块
- 当前 Backtrader 版本沿用了 `Meeting Lines` 形态识别，并按原文阈值实现了 MFI 入场/离场逻辑
- 由于 Backtrader 采用 bar close 驱动，订单执行时点与 MT5 向导 EA 可能存在细微差异
