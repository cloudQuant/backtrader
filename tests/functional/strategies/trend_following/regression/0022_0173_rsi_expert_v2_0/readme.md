# 0173 RSI_Expert_v2.0

## 策略来源

- MT5 源码：`ea/0173_RSI_Expert_v2.0/rsi_expert_v2.0.mq5`

## 策略逻辑

- 仅在新柱线上检查信号。
- `RSI` 从下向上穿越 `rsi_level_down` 时产生多头候选；从上向下穿越 `rsi_level_up` 时产生空头候选。
- 当 `ma_trade=forward` 时，只有快慢均线方向与 `RSI` 候选方向一致才开仓；当 `ma_trade=revers` 时均线方向反向解释；当 `ma_trade=off` 时只使用 `RSI`。
- 出现相反信号时，先平反向仓再反手开仓。
- 保留固定 `SL/TP`、trailing stop，以及上一笔亏损后下一笔手数翻倍的 martingale 开关。

## 与源码一致/差异说明

- 保留了源码里的 `RSI + 可选 MA 过滤 + 可选 martingale` 主流程。
- 原版通过 `OnTradeTransaction` 更新最近一笔平仓是否亏损；当前 backtrader 版本在 `notify_trade` 中按已平仓结果更新同一状态。
- 原说明示例未提供仓库内可直接回测的原始品种数据，这里使用 `XAUUSD_M15.csv` 做可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_rsi_expert_v2_0.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
