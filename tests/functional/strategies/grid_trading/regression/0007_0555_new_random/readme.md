# 0555 New_Random

## 策略概述

该策略是对 MT5 EA `0555_新随机数` 的 Backtrader 迁移版本。

- 支持随机方向开仓
- 支持 `BUY-SELL-BUY` 交替序列
- 支持 `SELL-BUY-SELL` 交替序列
- 使用固定 `SL/TP`

## 核心逻辑

1. 当当前无持仓时，根据 `random_mode` 选择下一笔方向。
2. `generator` 模式下用伪随机数决定多空。
3. `buy_sell_buy` / `sell_buy_sell` 模式下按固定交替序列开仓。
4. 每笔交易使用固定止损和止盈管理。

## 迁移说明

- 原版依赖 MT5 全局变量记录上一次开仓方向；迁移版用策略内部状态等价实现。
- 原版源码中序列分支存在明显实现瑕疵，迁移版按 readme 描述的预期行为实现交替序列。

## 运行方式

```bash
python run.py
```
