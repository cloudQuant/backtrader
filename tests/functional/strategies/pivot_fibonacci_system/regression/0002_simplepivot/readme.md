# 0315 SimplePivot

## 策略来源

- MT5 源码：`ea/0315_SimplePivot/simplepivot.mq5`

## 策略逻辑

- 每根新柱线开始时，读取前一根柱线的 `high/low`，计算 `pivot=(high+low)/2`。
- 默认信号为做多；如果当前柱线 `open < 前一根 high` 且 `open > pivot`，则切换为做空。
- 若当前信号方向与上一笔已执行方向一致，则不重复平仓重开。
- 若信号方向翻转，则先平掉当前仓位，再开立反向新仓。

## 与源码一致/差异说明

- 保留了 SimplePivot 的单仓翻向主流程，没有附加止损、止盈或多仓逻辑。
- 原 EA 示例运行在 `EURUSD,D1`；当前版本使用现有 `XAUUSD_M15.csv` 聚合出 `D1` 柱线做近似验证。
- 当前实现采用 Backtrader 的单净仓与下一根开盘成交机制，近似原 MT5 在新柱线诞生时的市价翻向处理。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_simplepivot.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 并聚合为 `D1` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
