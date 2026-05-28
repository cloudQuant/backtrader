# 0721 MacdPatternTraderAll

## 策略概述

该策略是对 MT5 EA `0721_MacdPatternTraderAll` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心结构：

- 维护 6 套独立 `MACD` pattern 参数
- 每根新 bar 依次检查所有启用的 pattern
- 每个 pattern 都按最近 `MACD` 形态比例变化触发多空入场
- 止损/止盈来自最近若干 bars 的极值推导
- 结合一组中长期 `MA` 做盈利后的主动离场管理

## 迁移范围

原 EA 依赖 `PartialClosing.mqh` 做部分平仓。迁移版为保证 Backtrader 示例简洁可运行，做了如下取舍：

- 保留 6 个 pattern 的入场结构
- 保留基于 bars 极值的 `SL/TP` 推导
- 保留 `MA` 条件性主动离场
- 将原版的部分平仓简化为条件触发的整仓离场

## 核心逻辑

1. 每个 pattern 使用自己的一组 `MACD fast/slow` 参数。
2. 比较 `macd[1]`、`macd[2]`、`macd[3]` 的比例变化，识别形态。
3. 命中后按 pattern 配置计算止损 bars 与止盈 bars。
4. 持仓后，除 `SL/TP` 外，还会结合 `EMA/SMA` 条件提前离场。

## 主要参数

- `patterns`
- `perema1`
- `perema2`
- `persma3`
- `perema4`
- `lots`

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 当前版本聚焦“六个 pattern + 常规持仓管理”的核心路径，未逐项复刻原 EA 的部分平仓细节。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
