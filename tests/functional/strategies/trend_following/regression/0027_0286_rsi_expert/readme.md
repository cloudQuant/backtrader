# 0286 RSI Expert

## 策略来源

- MT5 源码：`ea/0286_RSI_Expert/rsi_expert.mq5`

## 策略逻辑

- 当 RSI 从下向上穿越 `level_down_rsi` 时买入。
- 当 RSI 从上向下穿越 `level_up_rsi` 时卖出。
- 出现相反信号时，先平反向仓再反手开仓。
- 开仓附带固定 `SL/TP` 和 trailing；其中 `stoploss_pips=0` 表示默认关闭固定止损。
- 当前 backtrader 实现直接使用 `M15` 数据回测。

## 与源码一致/差异说明

- 保留了 `RSI` 双阈值交叉反手与 trailing 主流程。
- 原说明示例为 `USDJPY M15`，仓库当前没有对应数据，因此这里使用 `XAUUSD_M15.csv` 做可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_rsi_expert.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
