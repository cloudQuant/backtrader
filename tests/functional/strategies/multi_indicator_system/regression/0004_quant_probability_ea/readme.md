# 0037 Quant Probability EA

## 策略概述

该策略是对 MT5 EA `0037_外汇概率论智能交易系统/quant_ea.mq5` 的 backtrader 迁移版本。
策略会对固定长度历史进行分组统计，估算“上涨概率 / 下跌概率”，当多头概率高于 51% 时做多，低于 49% 时做空。

## 核心逻辑

1. 使用固定历史窗口 `1000` 根 bar。
2. 每 `50` 根 bar 作为一个 cluster。
3. 对每个 cluster 统计：
   - 若价格净上涨超过 `400` 点，则计入 bullish
   - 若价格净下跌超过 `400` 点，则计入 bearish
4. 由 `bullcount / bearcount` 计算概率：
   - `bull > 51` 做多
   - `bull < 49` 做空
5. 仓位管理：
   - 可使用固定手数 `Lots`
   - 若 `Risk > 0`，则按源码中的 `balance * Risk / 100000` 规则换算手数
6. 若 `CloseSig > 0`，则在反向信号时平掉相反方向仓位。

## 主要参数

主要参数定义在 `config.yaml`：

- `history_bars`
- `lots`
- `risk`
- `stop_loss`
- `take_profit`
- `claster_bars`
- `pips`
- `magic`
- `close_sig`
- `enable_check_bars`

## 当前数据与运行方式

当前验证方式：

- 数据：`../../../datas/XAUUSD_M15.csv`
- 当前按 `M15` 直接运行

运行命令：

```bash
python3 run.py
```

如果需要绘图：

```bash
python3 run.py --plot
```

## 对齐说明

- 原 EA 默认只有在 `EnableCheckBars = true` 时才会真正交易；当前回测配置已启用该参数
- 源码中 `HISTORY_BARS = 1000` 是硬编码常量；迁移版本保留为默认参数值 `1000`
- 当前版本保留了概率阈值入场、固定/风险手数和可选反向平仓主逻辑
