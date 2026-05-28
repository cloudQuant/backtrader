# 0650 AIS1

## 策略概述

该策略是对 MT5 EA `0650_AIS1` 的 Backtrader 迁移版本。

- 基于前一 bar 的高低点与均值分析
- 收盘高于均值且当前突破前高 → 做多
- 收盘低于均值且当前跌破前低 → 做空
- 动态 SL/TP 基于前 bar 的波幅
- 移动止损

## 核心逻辑

1. 计算前一 bar 的 `(High + Low) / 2` 均值。
2. 若前 bar 收盘高于均值，且当前价突破前高 → 做多。
3. 若前 bar 收盘低于均值，且当前价跌破前低 → 做空。
4. SL 距离 = 前 bar 波幅 × `stop_factor`。
5. TP 距离 = 前 bar 波幅 × `take_factor`。
6. 持仓期间根据 `trail_factor` 做移动止损。

## 迁移说明

- 原 EA 使用 D1 和 H4 两个时间框架的 OHLC；迁移版简化为单时间框架的前 bar 高低。
- 原 EA 使用动态手数管理（保证金占比）；迁移版简化为固定手数。
- 原 EA 限定 EURUSD；示例替换为 XAUUSD 以适配工作区数据。

## 主要参数

- `take_factor`
- `stop_factor`
- `trail_factor`
- `trail_stepping`
- `lots`

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与首版可运行脚手架已建立。
- 待后续补做本地回测校验。
