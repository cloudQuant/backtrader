# 0914 NonLagDot

## 策略概述

该示例是 MT5 EA `Exp_NonLagDot` 的 Backtrader 迁移版本。

原 EA 在 `H1` 信号周期上调用 `NonLagDot` 指标，并在颜色翻转时交易。

## 指标重建

- 使用 `iMA(Length, Type, Price)` 作为基础 MA
- 通过余弦核加权对 MA 值进行非滞后平滑
- 颜色：`0`=灰色, `1`=品红（下跌）, `2`=绿色（上涨）
- 支持 `Filter`（最小变化点数）和 `Deviation`（偏差百分比）

## 交易逻辑

- 颜色从 `1→2`（品红→绿）→ 做多
- 颜色从 `2→1`（绿→品红）→ 做空
- 趋势持续时的反向平仓
- 保留固定 `SL/TP`

## 文件

- `strategy_nonlagdot.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
