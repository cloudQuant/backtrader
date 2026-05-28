# 0910 SilverTrend

## 策略概述

该示例是 MT5 EA `Exp_SilverTrend` 的 Backtrader 迁移版本。

原 EA 在 `H1` 信号周期上调用 `SilverTrend_Signal` 指标，并在趋势翻转箭头出现时交易。

## 指标重建

- 计算 `SSP` 周期内的平均波幅、最高价 `SsMax`、最低价 `SsMin`
- `K = RISK * 100`
- `smin = SsMin + (SsMax - SsMin) * K / 100`
- `smax = SsMax - (SsMax - SsMin) * K / 100`
- `close < smin` → 下降趋势，`close > smax` → 上升趋势
- 趋势翻转时生成买入/卖出箭头

## 交易逻辑

- 箭头信号 + 历史回扫反向平仓
- 保留固定 `SL/TP`

## 文件

- `strategy_silvertrend.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
