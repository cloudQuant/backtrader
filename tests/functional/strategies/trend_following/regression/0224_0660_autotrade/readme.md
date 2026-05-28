# 0660 Autotrade

## 策略概述

该策略是对 MT5 EA `0660_Autotrade` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心结构：

- 同时设置 `BuyStop` 与 `SellStop` 两个突破挂单
- 只允许一笔真实仓位存活
- 挂单有过期时间
- 成交后按利润/稳定小 K 线条件或绝对盈亏阈值平仓
- 平仓时撤销另一侧未触发意图

## 核心逻辑

1. 当没有持仓且没有等待触发意图时，围绕当前价设置上下两个突破价位。
2. 若价格向上突破上方价位，则视作 `BuyStop` 被触发并开多。
3. 若价格向下突破下方价位，则视作 `SellStop` 被触发并开空。
4. 若挂单在 `expiration_minutes` 内未触发，则废弃并重新等待下一轮。
5. 开仓后：
   - 若浮盈超过 `min_profit` 且上一根 bar 足够稳定，则平仓
   - 若浮盈或浮亏达到 `absolute_fixation`，则平仓

## 迁移说明

- 原 EA 使用 MT5 原生挂单；迁移版在 Backtrader 中用“待触发意图价位”近似重建挂单生命周期。
- 原 EA 要求对冲账户，但其核心约束是“同时仅允许一笔仓位”，迁移版按单净仓实现。
- 示例使用 `XAUUSD_M15.csv` 并按 `H1` 压缩运行，以适配当前工作区可用数据文件。

## 主要参数

- `indent`
- `min_profit`
- `expiration_minutes`
- `absolute_fixation`
- `stabilization`
- `lots`

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与首版可运行脚手架已建立。
- 待后续补做本地回测校验，再同步台账中的验证结果。
