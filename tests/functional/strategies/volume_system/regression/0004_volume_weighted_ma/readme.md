# 0871 Volume_Weighted_MA

## 策略概述

该示例是 MT5 EA `Exp_Volume_Weighted_MA` 的 Backtrader 迁移版本。

原 EA 在 `H4` 信号周期上调用 `Volume_Weighted_MA` 指标，在加权均线形成 V 形反转时交易。

## 指标重建

- 对最近 `Length` 根价格按成交量加权
- 使用 tick volume 作为默认权重来源
- 生成单条 VWMA 线

## 交易逻辑

- 先降后升 → 开多并平空
- 先升后降 → 开空并平多
- 保留固定 `SL/TP`

## 文件

- `strategy_volume_weighted_ma.py`
- `run.py`
- `config.yaml`

## 用法

```bash
python run.py
```
