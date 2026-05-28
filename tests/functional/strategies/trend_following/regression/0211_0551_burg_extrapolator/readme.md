# 0551 Burg_Extrapolator

## 策略概述

该策略是对 MT5 EA `0551_Burg_Extrapolator` 的 Backtrader 迁移版本。

- 使用过去 `past_bars` 根开盘价构建 Burg 自回归预测
- 根据未来预测振幅触发开仓或平仓信号
- 支持固定 `SL/TP` 与 trailing stop

## 核心逻辑

1. 使用过去开盘价序列构造输入样本。
2. 可选使用 `MOM` 或 `ROC` 变换；否则对价格做去均值处理。
3. 用 Burg 递推估计 AR 系数，并外推未来价格路径。
4. 若预测上行空间超过 `min_profit` 则做多；若预测下行空间超过 `min_profit` 则做空。
5. 若预测反向波动超过 `max_loss`，则对当前持仓给出平仓信号。

## 迁移说明

- 原版允许同方向最多 `ntmax` 笔持仓；迁移版在 Backtrader 单净仓模型下近似为单仓版本。
- 原版 Burg 计算和持仓分支中存在一些 MT5 代码级细节与分支瑕疵；迁移版按其核心思想实现为可运行的 Burg 预测策略。

## 运行方式

```bash
python run.py
```
