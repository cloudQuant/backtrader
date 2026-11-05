# tickbroker_pair_arbitrage

空 `rb2701` / 多 `hc2701`，tick 价差偏离短期滚动均值时入场（`PairTickArbitrageStrategy`），用 `TickBroker` 在内存 tick 流上回测。

```bash
python examples/backtest/007_ctp/tickbroker_pair_arbitrage/run.py
python examples/backtest/007_ctp/tickbroker_pair_arbitrage/run.py --config other.yaml
```

| 文件 | 内容 |
| --- | --- |
| `pair_tick_arbitrage_strategy.py` | 期货策略基类与 `PairTickArbitrageStrategy`，与 `examples/live/007_ctp/tickbroker_pair_arbitrage/` 中的同名文件相同 |
| `run.py` | 配置加载、`TradeLogger`、内存行情构造、`TickBroker` 回测入口 |
| `config.yaml` | Broker、策略参数和内置行情场景（`scenario`） |

- 离线运行：行情是 `config.yaml` 中的内存场景，不使用实盘 Store、凭据或网络；内置场景完成 1 个往返交易，退出码 0。
- 默认启用 `TradeLogger`，日志写到本目录被 git 忽略的 `logs/config/<时间戳>/`；设置
  `trade_logger: {enabled: false}` 可关闭。
- 来源：原 `examples/unified/007_ctp/ctp_tickbroker_examples/backtest/pair_arbitrage.yaml`。
