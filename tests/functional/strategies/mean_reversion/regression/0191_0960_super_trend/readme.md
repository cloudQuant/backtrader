# 0960 Super Trend

## 策略概述

该示例是 MT5 EA `Exp_Super_Trend` 的 Backtrader 迁移版本。

原 EA 基于 `CCI` 零轴翻转后的 `TrendUp/TrendDown` 状态切换开平仓，并配合固定 `SL/TP` 管理持仓。

## 指标重建

- 指标源码完整，不依赖缺失的 `SmoothAlgorithms.mqh`
- 使用内置 `CCI(PRICE_TYPICAL)` 作为趋势状态判定
- 按源码重建 `TrendUp/TrendDown` 延续规则与 `SignUp/SignDown` 反转信号
- 默认使用 `H1` 信号周期

## 交易逻辑

- 出现 `SignUp` 时做多并平空
- 出现 `SignDown` 时做空并平多
- 使用固定 `SL/TP`

## 文件

- `strategy_super_trend.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
