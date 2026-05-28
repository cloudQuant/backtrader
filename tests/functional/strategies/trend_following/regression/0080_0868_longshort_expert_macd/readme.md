# 0868 LongShortExpertMACD

## 策略概述

该示例是 MT5 `LongShortExpertMACD` 的 Backtrader 迁移版本。

原 EA 基于 MetaTrader `CExpert` 框架，使用 MACD 信号并允许配置仅做多、仅做空或双向交易。

## 交易逻辑

- MACD 线上穿信号线 → 多头信号
- MACD 线下穿信号线 → 空头信号
- 通过 `allowed_positions` 控制允许方向
- 保留固定 `SL/TP`

## 文件

- `strategy_longshort_expert_macd.py`
- `run.py`
- `config.yaml`

## 用法

```bash
python run.py
```
