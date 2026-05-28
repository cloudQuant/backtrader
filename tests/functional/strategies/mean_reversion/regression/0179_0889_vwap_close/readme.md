# 0889 VWAP_Close

## 策略概述

该示例是 MT5 EA `Exp_VWAP_Close` 的 Backtrader 迁移版本。

原 EA 在 `H6` 信号周期上调用 `VWAP_Close` 指标，在 VWAP 线 V 形反转时交易。

## 指标重建

- VWAP = `sum(close * volume) / sum(volume)` 滚动 `n` 根 bar
- 使用 tick volume

## 交易逻辑

- V-bottom（先降后升）→ 买入
- V-top（先升后降）→ 卖出
- 方向反转时平仓
- 保留固定 `SL/TP`

## 文件

- `strategy_vwap_close.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
