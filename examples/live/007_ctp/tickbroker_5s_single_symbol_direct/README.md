# tickbroker_5s_single_symbol_direct

rb2701 tick 输入、5 秒 bar 的单品种均线策略。 `SingleSymbolMaStrategy` 经 CTP 直连（迭代 62 direct 模式）在 SimNow 运行：`BtApiStore` 启用 SDK 写入准入、不配置 execution，
`BtApiBroker` 走直连路径。首次初始化、重启对账、待发单、UNKNOWN 人工核验和停止行为见
[上级 README](../README.md)。

```bash
python run.py --dry-run
python run.py --first-init --env-file /path/to/.env   # 只在第一次，账户须空仓且无挂单
python run.py --env-file /path/to/.env --run-seconds 600
```

| 文件 | 内容 |
| --- | --- |
| `single_symbol_ma_strategy.py` | `SingleSymbolMaStrategy`；与 `examples/backtest/007_ctp/tickbroker_5s_single_symbol` 中的同名文件内容相同 |
| `run.py` | 配置校验、凭据读取（不打印）、Store/Broker/Feed 装配、TradeLogger、带超时运行，最后输出对账与停止摘要 |
| `config.yaml` | 合约与交易所、CTP 前置档案、写入准入、Broker 直连参数、feed、策略参数（`order_exectype: limit`、`close_offset: auto`） |

运行后本目录会出现 `state/`（策略身份、局部序号、未决标记、待发单、审计）和 `logs/`（`current_position.yaml`
对账基线及每次运行的 TradeLogger 日志）。不要在两个进程中同时运行同一目录；需要并行时复制目录并分别首次初始化。
