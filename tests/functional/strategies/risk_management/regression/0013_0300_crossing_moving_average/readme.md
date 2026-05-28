# 0300 Crossing Moving Average

## 策略来源

- MT5 源码：`ea/0300_移动平均线交叉/crossing_moving_average.mq5`

## 策略逻辑

- 仅在新 bar 上运行。
- 使用两条移动平均线在相邻两根柱上的交叉作为主信号。
- 使用 `Momentum` 方向过滤：做多要求动量大于阈值且继续抬升，做空要求动量小于负阈值且继续走弱。
- 反向信号出现时先平对侧仓位，再按当前方向开仓。
- 保留固定手数、固定止损止盈、可选 trailing stop。

## 与源码一致/差异说明

- 保留了双均线交叉、Momentum 过滤、反手先平旧仓和 trailing 主流程。
- 原 EA 使用 MQL5 `iMA` 的 `ma_shift` 读取移位均线；当前版本以 Backtrader 均线值配合历史索引近似该移位逻辑。
- 原始实现直接在图表周期运行；当前回测使用仓库可用的 `XAUUSD_M15.csv` 数据进行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_crossing_moving_average.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
