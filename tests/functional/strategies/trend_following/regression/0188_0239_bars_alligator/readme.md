# 0239 BARS Alligator

## 策略来源

- MT5 源码：`ea/0239_BARS_Alligator/bars_alligator.mq5`

## 策略逻辑

- 仅在新 bar 到来时评估信号。
- 使用 `Alligator` 三条线中的 `lips` 与 `jaw` 交叉判定开仓方向。
- 当 `lips` 从下向上穿越 `jaw` 时开多；当 `lips` 从上向下跌破 `jaw` 时开空。
- 持有多单时，如果 `lips` 从上向下跌破 `teeth` 且当前浮盈非负，则平多。
- 持有空单时，如果 `lips` 从下向上穿越 `teeth` 且当前浮盈非负，则平空。
- 入场附带固定 `SL/TP`；盈利达到 `Trailing Stop + Trailing Step` 后，开始按 trailing stop 抬高或压低止损。
- 当前实现按源码推荐的 `InpMaxPositions=1` 净头寸模式运行。

## 与源码一致/差异说明

- 保留了 `Alligator` 开平仓、固定 `SL/TP`、盈利条件平仓与 trailing stop 的核心逻辑。
- MT5 的 `iAlligator` 内置实现包含平滑与显示位移参数；backtrader 版本使用 `SMMA` 与对应 `jaw/teeth/lips` shift 的历史引用来近似该行为。
- 原 EA 支持固定手数和风险百分比两种资金管理；backtrader 版本同样保留这两种模式，其中 `risk` 模式按 `risk_cash / (stop_distance * contract_multiplier)` 近似换算手数。
- 当前仓库没有原文所用的专属样例数据，因此这里使用 `XAUUSD_M15.csv` 做可运行迁移验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_bars_alligator.py`：策略与数据加载实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后运行回测。
- `config.yaml`：策略参数、数据区间和回测配置。
