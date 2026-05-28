# 0928 RVI_Histogram

## 策略概述

该示例是 MT5 EA `Exp_RVI_Histogram` 的 Backtrader 迁移版本。

原 EA 基于 `RVI_Histogram` 指标信号开平仓，支持两种原始 `TrendMode`：

- `cross`：依据 `RVI` 主线与信号线交叉触发
- `levels`：依据主线进入高低阈值区后映射出的 `0/1/2` 颜色索引触发

默认参数使用 `H4` 信号周期与 `Cross` 模式。

## 指标重建

- 按标准 `RVI` 公式重建主线与信号线
- 使用 `(close-open)` 与 `(high-low)` 的四点加权平均
- 对加权后的分子分母分别做 `period` 简单平均后求比值得到主线
- 对主线再做四点加权平均得到信号线
- 同步重建 `Levels` 模式下的颜色索引：
  - `0`：主线 `> HighLevel`
  - `1`：中性区
  - `2`：主线 `< LowLevel`

## 交易逻辑

- `cross`：主线上穿信号线做多，下穿做空
- `levels`：颜色从 `>0` 进入 `0` 做多，从 `<2` 进入 `2` 做空
- 反向信号按原 EA 语义平仓并允许反手
- 保留固定 `SL/TP`

## 文件

- `strategy_rvi_histogram.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
