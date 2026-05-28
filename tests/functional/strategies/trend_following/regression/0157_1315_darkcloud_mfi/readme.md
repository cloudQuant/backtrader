# 1315 Dark Cloud Cover / Piercing Line + MFI

## 策略概述

该策略是对 MT5 EA `1315_基于乌云盖顶_刺穿线和MFI的交易信号` 的 backtrader 迁移版本。

- 乌云盖顶 / 刺穿线反转形态识别
- MFI 作为入场确认
- MFI 穿越超买超卖区域离场

## 核心逻辑

1. 识别 `Dark Cloud Cover` 看跌反转形态
2. 识别 `Piercing Line` 看涨反转形态
3. 当出现 `Piercing Line` 且 `MFI < 40` 时做多
4. 当出现 `Dark Cloud Cover` 且 `MFI > 60` 时做空
5. 持仓后根据 MFI 穿越超买 / 超卖边界离场

## 主要参数

参数定义在 `config.yaml` 中，主要包括：

- `mfi_period` / `mfi_entry_long` / `mfi_entry_short`
- `mfi_exit_upper` / `mfi_exit_lower`
- `ma_period` / `lot`

## 运行方式

```bash
python run.py
python run.py --plot
```

## 当前回测结果

待验证后更新。

## 对齐说明

- 原 EA 基于标准 `CCandlePattern` 类识别乌云盖顶 / 刺穿线
- 当前版本对形态规则做了可运行近似实现，并保留 MFI 过滤框架
