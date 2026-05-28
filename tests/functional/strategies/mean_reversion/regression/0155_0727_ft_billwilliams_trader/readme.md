# 0727 FT BillWillams 交易者

## 策略概述

该策略是对 MT5 EA `0727_FT_BillWillams_交易者` 的 Backtrader 迁移版本。
当前实现聚焦原 EA 的默认工作流：

- 使用经典 5-bar 分形识别突破位
- 使用 Alligator 牙齿/嘴唇/下颚做过滤
- 分形突破后入场
- 反向信号与牙齿线跌破/突破触发退出
- 固定 `SL/TP`

## 迁移范围

迁移版优先覆盖原 EA 最核心的自动执行路径：

- 默认 `TypeEntry=2`
- 经典分形模式
- 红线过滤
- 趋势过滤
- 反向信号关闭
- 牙齿线退出

原版中更细的回撤重入、角度型 trailing 细节未完全展开到本示例。

## 核心逻辑

1. 识别最近确认完成的 5-bar 分形。
2. 为买卖方向分别维护当前有效突破价。
3. 当收盘价突破有效分形位时进场。
4. 若价格重新跌破/突破 Alligator 牙齿，或出现反向有效突破，则离场。

## 主要参数

- `count_bars_fractal`
- `indent`
- `type_entry`
- `red_control`
- `trend_alig_control`
- `close_drop_teeth`
- `close_revers_signal`

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 当前版本是对默认核心路径的聚焦迁移，不是原 EA 所有可选模式的逐项 1:1 复刻。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
