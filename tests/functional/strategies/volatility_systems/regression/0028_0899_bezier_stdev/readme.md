# 0899 Bezier_StDev

## 策略概述

该示例是 MT5 EA `Exp_Bezier_StDev` 的 Backtrader 迁移版本。

原 EA 在 `H4` 信号周期上调用 `Bezier_StDev` 指标，使用两种信号模式（POINT/DIRECT）进行交易。

## 指标重建

- Bezier 曲线插值：`BPeriod` 阶 Bernstein 多项式对价格的平滑
- StDev 过滤器：对 Bezier 一阶导数序列计算标准差
- `dstd > dK * StDev` → 买入信号（Bulls）
- `dstd < -dK * StDev` → 卖出信号（Bears）
- 颜色线：上升=1，下降=2，持平=0

## 交易逻辑

- **POINT 模式**：读取 Bulls/Bears 箭头缓冲区入场
- **DIRECT 模式**：读取 Bezier 线方向变化入场/平仓
- 默认：开仓用 POINT，平仓用 DIRECT
- 保留固定 `SL/TP`

## 文件

- `strategy_bezier_stdev.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
