# 0994 iAnchMom

## 策略概述

该示例是 MT5 EA `Exp_iAnchMom` 的 Backtrader 迁移版本。

原 EA 基于 `iAnchMom` 直方图方向反转进行交易：当最近两根已完成柱的动量方向发生翻转时，触发对应的开平仓信号。

## 指标重建

- `SMA(price, 34)`
- `EMA(price, 20)`
- `iAnchMom = 100 * (EMA / SMA - 1)`
- 默认使用 `H8` 信号周期

## 交易逻辑

- 前一根已完成柱下降、最近一根已完成柱转为不低于前值时做多并平空
- 前一根已完成柱上升、最近一根已完成柱转为不高于前值时做空并平多
- 使用固定 `SL/TP`

## 文件

- `strategy_ianchmom.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
