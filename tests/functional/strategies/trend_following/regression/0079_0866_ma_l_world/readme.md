# 0866 MA L WORLD

## 策略概述

该示例是 MT5 `MA L WORLD` 的 Backtrader 迁移版本。

原 EA 基于 `CExpert` 框架，使用简单均线交叉作为入场信号，并用另一条 MA 进行尾随退出。

## 交易逻辑

- 快线均线上穿慢线 → 多头信号
- 快线均线下穿慢线 → 空头信号
- 使用 `trailing_ma_period` EMA 作为附加退出条件
- 保留固定 `SL/TP`

## 文件

- `strategy_ma_l_world.py`
- `run.py`
- `config.yaml`

## 用法

```bash
python run.py
```
