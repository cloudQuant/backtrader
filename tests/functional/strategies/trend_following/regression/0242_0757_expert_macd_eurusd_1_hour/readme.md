# 0757 交易系统 MACD EURUSD 1 小时

## 策略概述

该策略是对 MT5 EA `0757_交易系统_MACD_EURUSD_1_小时` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的主要结构：

- 使用固定参数 `MACD(5,15,3)`
- 按多根 `MACD main/signal` 序列形态判断入场
- 持仓后按 `MACD main` 拐头平仓
- 同时支持固定点数 trailing stop

## 核心逻辑

1. 读取最近 4 根 `MACD main` 与 `signal` 值。
2. 当 `signal` 三连降后回升、`main` 形成低点抬高并从负值区域穿回正阈值时做多。
3. 当 `signal` 三连升后回落、`main` 形成高点降低并从正值区域跌回负阈值时做空。
4. 持有多单时，若当前 `MACD main < 上一根 MACD main` 则平多；空单则对称平仓。
5. 当浮盈超过 `Trailing` 点后，按固定距离推移保护止损。

## 主要参数

- `trailing`
- `risk`
- `macd_fast`
- `macd_slow`
- `macd_signal`

## 对齐说明

- 原 EA 名称虽然写着 `EURUSD 1 Hour`，但代码实际使用 `Symbol()` 与 `Period()`，并未把交易对象硬编码到逻辑分支中。
- 原源码用 `LotsOptimized()` 按资金比例估算手数；当前版本按相同思路用 `cash * risk / 1000` 近似。
- 原实现用 `Pause` 控制 trailing 修改频率；当前 bar 级迁移直接按新 bar 检查 trailing 条件。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
