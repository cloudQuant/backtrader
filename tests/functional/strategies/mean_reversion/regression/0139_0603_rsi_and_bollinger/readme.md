# 0603 RSI 和布林带

## 策略概述

该策略是对 MT5 EA `0603_RSI_和布林带` 的 Backtrader 迁移版本。

- RSI 突破应用于 RSI 本身的 Bollinger Bands 上/下轨
- 价格必须位于分形水平之内
- 价格突破分形水平时入场
- SAR 移动止损 + 固定 SL/TP

## 核心逻辑

1. **Buy**: RSI > BB上轨（基于RSI）、价格 < 上分形 → 价格突破上分形 + indenting 时做多。
2. **Sell**: RSI < BB下轨（基于RSI）、价格 > 下分形 → 价格突破下分形 - indenting 时做空。
3. 取消：如果待挂单尚未触发且 RSI 回落到 30 以下（买入）/ 70 以上（卖出），则取消。
4. SAR 移动止损持续推进。

## 迁移说明

- 原版使用 `BuyStop`/`SellStop` 挂单；迁移版在 `next()` 中模拟价格突破触发。
- 原版 BB 应用于 RSI 句柄输出；迁移版用 `bt.indicators.BollingerBands(self.rsi, ...)` 等价实现。
- 原版分形使用 `iFractals` 标准指标；迁移版手动计算 5-bar 分形。

## 主要参数

- `rsi_period` — RSI 周期（默认 8）
- `bands_period` / `bands_deviation` — BB 周期与标准差倍数
- `sar_step` / `sar_max` — SAR 步长与最大值
- `take_profit` / `stop_loss` — TP/SL 点数
- `indenting` — 分形突破偏移点数
- `sar_trailing_stop` — SAR 移动止损缓冲点数

## 运行方式

```bash
python run.py
```
