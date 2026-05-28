# 0949 MACD-2

## 策略概述

该示例是 MT5 EA `Exp_MACD-2` 的 Backtrader 迁移版本。

原 EA 基于 `MACD-2` 指标信号开平仓，支持 `HISTOGRAM`、`CLOUD`、`ZERO` 三种趋势判定模式，并配合固定 `SL/TP` 管理持仓。

## 指标重建

- 使用标准 `MACD` 主线和信号线
- 按源码重建 `hist = 3 * (main - signal)`
- 重建颜色索引 `0/1/2/3/4`
- 策略支持三种原始 `TrendMode`
- 默认使用 `CLOUD` 模式与 `H4` 信号周期

## 交易逻辑

- `HISTOGRAM`：依据柱体方向变化触发
- `CLOUD`：依据主线和信号线交叉触发
- `ZERO`：依据柱体过零触发
- 使用固定 `SL/TP`

## 文件

- `strategy_macd_2.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
