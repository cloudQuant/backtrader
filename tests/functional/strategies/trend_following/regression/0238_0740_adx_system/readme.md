# 0740 ADX 系统System

## 策略概述

该策略是对 MT5 EA `0740_ADX_系统System` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的主要结构：

- 使用 `ADX / +DI / -DI`
- 通过 `ADX` 与方向线的相对位置识别开仓
- 通过反向结构平仓
- 结合固定 `SL/TP` 与 trailing stop

## 核心逻辑

1. 读取 `ADX(14)`、`+DI`、`-DI` 的前两根数值。
2. 当 `ADX` 上行，且 `+DI` 从低于 `ADX` 变为高于 `ADX` 时做多。
3. 当 `ADX` 上行，且 `-DI` 从低于 `ADX` 变为高于 `ADX` 时做空。
4. 已持有多单时，若出现相反的 `+DI` 回落结构则平多；空单对称处理。
5. 盘中如果浮盈超过 `trailing_stop`，则把止损推进到当前价格后方。

## 主要参数

- `take_profit`
- `stop_loss`
- `trailing_stop`
- `lots`
- `adx_period`

## 对齐说明

- 原 EA 使用标准 `iADX(Symbol(), Period(), 14)`；当前版本保持同一周期。
- 入场/平仓条件不是简单 `DI` 交叉，而是 `DI` 与 `ADX` 主线之间的位置变化；迁移版沿用这一结构。
- 原版包含资金检查；当前回测示例依赖 broker 资金与保证金设置控制。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
