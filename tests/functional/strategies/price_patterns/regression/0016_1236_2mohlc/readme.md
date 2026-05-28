# 1236 2MoHLC

## 策略概述

该策略是对 MT5 EA `1236_Exp_2MoHLC` 的 Backtrader 迁移版本。
原 EA 读取 `2MoHLC_` 指标的两条中轴通道线，并依据云颜色切换或价格突破云带来执行反手交易。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `H4`
2. 分别计算 `Period1` 与 `Period2` 窗口内的 `((HH + LL) / 2)` 中轴
3. `mode=1` 时，按两条中轴线的相对高低变化生成云颜色切换信号
4. `mode=2` 时，按价格向上突破云上沿/向下跌破云下沿生成信号
5. 信号出现时平掉反向仓位，并按原 EA 参数允许时反手开仓

## 主要参数

- `indicator_minutes`
- `mode`
- `period1`
- `period2`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

默认配置对应原 EA 默认的 `Breakdown` 模式。
如果要复刻 `CloudColor` 版本，可把 `config.yaml` 中 `mode` 改为 `1`。
