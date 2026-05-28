# 0033 Simple Three Inside Pattern EA

## 策略概述

该策略是对 MT5 EA `0033_简单的三内图案_EA/simple_three_inside_pattern_ea.mq5` 的 backtrader 迁移版本。
原 EA 在 `H1` 周期上识别“三内上涨 / 三内下跌”三根 K 线形态，并使用固定手数、固定止损止盈进行交易。

## 核心逻辑

1. 仅当当前没有持仓时才允许新开仓。
2. 使用最近 3 根已完成的 `H1` K 线识别形态：
   - 看涨三内：前一根大阴线，随后一根内包阳线，再随后一根突破前高的阳线
   - 看跌三内：前一根大阳线，随后一根内包阴线，再随后一根跌破前低的阴线
3. 触发形态后按固定手数开仓。
4. 开仓后立即挂出固定 `SL/TP`：
   - `SL = 500` 点
   - `TP = 500` 点

## 主要参数

主要参数定义在 `config.yaml`：

- `stop_loss`
- `take_profit`
- `lot`
- `magic_number`
- `point_size`

## 当前数据与运行方式

当前验证方式：

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 回测中预重采样为 `H1`

运行命令：

```bash
python3 run.py
```

如果需要绘图：

```bash
python3 run.py --plot
```

## 对齐说明

- 原 EA 用 `OnTimer` 每 60 秒检查一次 `H1` 历史；当前回测版本直接在 `H1` bar 上执行同等形态判断
- 原 EA 使用固定手数、固定止损止盈；当前版本保持这一点
- 当前版本保留了“只允许单仓存在”的主逻辑
