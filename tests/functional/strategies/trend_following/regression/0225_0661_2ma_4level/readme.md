# 0661 2MA 4Level

## 策略概述

该策略是对 MT5 EA `0661_2MA_4Level` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心结构：

- 一条快 `MA`
- 一条慢 `MA`
- 围绕慢线的四个偏移水平
- 快线穿越这些水平时触发交易
- 固定 `SL/TP`

## 核心逻辑

1. 使用快慢两条移动平均线。
2. 以慢线为中心构造以下偏移水平：
   - `+most_top_level`
   - `+top_level`
   - `-lower_level`
   - `-lowermost_level`
3. 快线从下向上穿越慢线本体或任一偏移水平时做多。
4. 快线从上向下穿越慢线本体或任一偏移水平时做空。
5. 每次开仓后使用固定 `SL/TP` 管理持仓。

## 迁移说明

- 原 EA 要求对冲账户，但实际交易逻辑是单仓风格；迁移版按单净仓实现。
- 原版支持配置不同 MA 方法与价格类型；当前首版迁移按源码默认设置重建：`SMMA + PRICE_MEDIAN`。
- 示例使用 `XAUUSD_M15.csv` 并按 `H1` 压缩运行，以适配当前工作区可用数据文件。

## 主要参数

- `take_profit`
- `stop_loss`
- `ma_period_fast`
- `ma_period_slow`
- `most_top_level`
- `top_level`
- `lower_level`
- `lowermost_level`

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与首版可运行脚手架已建立。
- 待后续补做本地回测校验，再同步台账中的验证结果。
