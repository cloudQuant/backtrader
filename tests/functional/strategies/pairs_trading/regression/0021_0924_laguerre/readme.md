# 0924 Laguerre

## 策略概述

该示例是 MT5 EA `Exp_Laguerre` 的 Backtrader 迁移版本。

原 EA 在 `H1` 信号周期上调用 `ColorLaguerre` 指标，并依据彩色 Laguerre 线颜色切换与箭头信号开平仓。

## 指标重建

- 按原始 `Laguerre RSI` 递推公式重建 `L0/L1/L2/L3`
- 使用 `gamma=0.7` 递推平滑
- 根据 `CU/CD` 比例计算 `0-100` 区间的 `Laguerre RSI`
- 按原 `PointIndicator` 状态机重建颜色索引：
  - `1` 表示多头颜色
  - `2` 表示空头颜色
- 阈值使用 `HighLevel=85`、`MiddleLevel=50`、`LowLevel=15`

## 交易逻辑

- 当颜色由 `2 -> 1` 切换时做多
- 当颜色由 `1 -> 2` 切换时做空
- 若持有反向仓位，则在当前颜色持续为对侧颜色时按原 EA 语义平仓
- 保留固定 `SL/TP`

## 文件

- `strategy_laguerre.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
