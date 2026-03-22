# Binance BBO Alignment Demo

这个示例把 `backtrader` 和 `hftbacktest` 在同一份 Binance BBO 演示数据上的对齐结果整理成了一个可直接运行的目录。

## 目录内容

- `run_backtrader.py`
  - 只跑 `backtrader` 侧
- `run_hftbacktest.py`
  - 只跑 `hftbacktest` 侧
- `compare.py`
  - 同时运行两边并输出对比结果
- `common.py`
  - 统一默认参数与数据路径

## 默认数据

默认直接使用仓库内已有数据：

- `tests/datas/binance_bbo_demo/orderbook_ETHUSDT_20240101.jsonl`
- `tests/datas/binance_bbo_demo/tick_ETHUSDT_20240101.csv`
- `tests/datas/binance_bbo_demo/ETHUSDT_20240101.npz`

这里没有复制数据文件，而是直接引用测试数据目录，避免重复存储。

## 为什么这个例子比之前更有意义

默认把 `max_decisions` 提高到了 `500`，也就是使用这一天数据里更长的一段窗口，而不是只看前几十个决策拍。

对 `plain_grid` 来说，这会把成交数提升到 `62` 笔，明显比短窗口更有对比意义。

## 运行方式

在仓库根目录执行：

```bash
python examples/002_hft_alignment_demo/run_backtrader.py
python examples/002_hft_alignment_demo/run_hftbacktest.py
python examples/002_hft_alignment_demo/compare.py
```

也可以切换策略，例如：

```bash
python examples/002_hft_alignment_demo/compare.py --strategy queue_market_making --max-decisions 180
```

## 当前推荐默认配置

推荐默认先跑：

- `strategy=plain_grid`
- `max_decisions=500`

在当前代码下，这组参数的结果特征是：

- `num_trades` 一致
- `position` 一致
- `balance` 只存在浮点误差级别差异
- `fills` 的原始列表顺序不完全一致，但成交多重集合一致

因此 `compare.py` 会同时输出：

- 原始逐字段对比结果
- canonical 口径结果（对 `fills` 按多重集合比较）

## queue_market_making 当前状态

`queue_market_making` 在更长窗口下仍然没有完全对齐。

目前已经确认并修复的一点：

- comparison runner 的决策时钟已改为整数纳秒调度，避免 float 累加漂移让订单提前几微秒生效

当前剩余问题主要集中在 `backtrader/brokers/hft/binance_bbo_compare.py` 的 comparison 专用队列撮合语义上，尤其是：

- comparison 专用 `_NoPartialQueueExchangeModel.on_trade()`
- 长窗口下同价位重复重挂订单后的 maker / queue 生命周期

也就是说，默认示例建议用 `plain_grid` 来展示已经稳定对齐的结果；`queue_market_making` 则保留为进一步调试 `backtrader` 队列撮合语义的案例。
