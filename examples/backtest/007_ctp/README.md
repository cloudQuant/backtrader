# 007 — CTP 风格期货回测示例

原 `examples/unified/007_ctp` 的**回测部分**（实盘部分见
[`examples/live/007_ctp`](../../live/007_ctp/README.md)）。每个策略一个文件夹，文件夹内自带
`README.md + config.yaml + <name>_strategy.py + run.py`，不依赖其他目录的脚本，可单独复制使用。
全部离线运行：行情是 `config.yaml` 中的内存场景，不使用实盘 Store、凭据或网络。

| 文件夹 | Broker | 数据 | 策略 |
| --- | --- | --- | --- |
| `bbroker_5s_single_symbol/` | `BackBroker` | pandas 5 秒 bar feed | `SingleSymbolMaStrategy` 单品种均线 |
| `bbroker_5s_pair_arbitrage/` | `BackBroker` | pandas 5 秒 bar feed | `PairSpreadStrategy` 价差套利 |
| `mixbroker_5s_single_symbol/` | `MixBroker` | tick + 5 秒 bar `MixedChannel` | `SingleSymbolMaStrategy` 单品种均线 |
| `mixbroker_5s_pair_arbitrage/` | `MixBroker` | tick + 5 秒 bar `MixedChannel` | `PairSpreadStrategy` 价差套利 |
| `tickbroker_5s_single_symbol/` | `TickBroker` | 由 5 秒 bar 合成的 tick | `SingleSymbolMaStrategy` 单品种均线 |
| `tickbroker_5s_pair_arbitrage/` | `TickBroker` | 由 5 秒 bar 合成的 tick | `PairSpreadStrategy` 价差套利 |
| `mixbroker_single_symbol/` | `MixBroker` | tick + bar `MixedChannel` | `SingleSymbolMixStrategy` bar 信号 + tick 执行 |
| `mixbroker_pair_arbitrage/` | `MixBroker` | tick + bar `MixedChannel` | `PairMixArbitrageStrategy` 公允价差套利 |
| `tickbroker_single_symbol/` | `TickBroker` | 纯 tick | `SingleSymbolTickStrategy` tick 动量 |
| `tickbroker_pair_arbitrage/` | `TickBroker` | 纯 tick | `PairTickArbitrageStrategy` tick 价差套利 |

```bash
python examples/backtest/007_ctp/bbroker_5s_single_symbol/run.py
python examples/backtest/007_ctp/tickbroker_pair_arbitrage/run.py --config config.yaml
```

每个配置在内置场景上完成 1 个往返交易，退出码 0。同名文件夹在 `examples/live/007_ctp/` 下有对应的实盘版本，
两边的 `<name>_strategy.py` 内容相同，只有 `config.yaml` 与 `run.py` 不同；修改策略时请两边同步。
