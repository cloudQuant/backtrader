# mixbroker_single_symbol_gateway

rb2701 tick 输入的单品种混合策略（可按 tick 数强制开平，用于验证订单闭环）。这是 `SingleSymbolMixStrategy` 的 Gateway 版本（迭代 62，62.08）。`run.py` 先启动本目录的 Gateway 进程
（`gateway_host.py`），策略的行情全部来自 Gateway CTP MarketHub；下单目前走 SDK 直连写入准入
（与 `../mixbroker_single_symbol_direct/` 相同的直连 Broker，本目录就是一个独立的策略实例）。

**订单经 Gateway 托管执行运行时（`gateway.orders: managed`）目前不可用**：`run.py` 会在读取凭据之前
输出 `BLOCKED`（`managed_gateway_execution_unavailable`），原因见上级 README 的“缺口”一节。

## 运行（SimNow 标准环境交易时段）

```bash
python run.py --dry-run                                    # 离线校验配置并构建 Gateway 档案
python gateway_host.py --env-file /path/to/.env --check-seconds 60    # 只核验 Gateway 行情
python run.py --first-init --env-file /path/to/.env        # 只在第一次，账户须空仓且无挂单
python run.py --env-file /path/to/.env --run-seconds 600   # 以后每次
python gateway_host.py --env-file /path/to/.env --managed-boot-check  # 托管运行时在 SDK 准入下的启动核验（不下单）
```

| 文件 | 内容 |
| --- | --- |
| `single_symbol_mix_strategy.py` | `SingleSymbolMixStrategy`；与 `../mixbroker_single_symbol_direct/` 中的同名文件内容相同 |
| `run.py` | 启动 Gateway 子进程并经管道取得本次运行的 CURVE 连接，`BtApiStore(..., market_runtime_factory=...)` 从 Gateway 取行情，直连 Broker 下单，带超时运行后输出对账与停止摘要并关闭 Gateway |
| `gateway_host.py` | Gateway 进程：SDK `ctp_gateway_composition` 组装的 CTP MarketHub（订阅频道 `tick`，键环境 `demo`）；`--check-seconds` 单独核验行情，`--managed-boot-check` 在 SDK 写入准入下启动并关闭托管运行时 |
| `config.yaml` | 合约与交易所、`gateway`（SimNow 档案、订单路径、核验时长、托管准入）、直连写入准入、Broker、feed、策略参数 |

凭据从 `SIMNOW_USER_ID` / `SIMNOW_PASSWORD`（或 `--env-file`）读取：`run.py` 用于本进程的直连交易会话，
Gateway 子进程自己读取用于行情会话；两边都不打印。CURVE 密钥每次运行新生成，只经进程间管道传递。

## 行情时钟

Gateway 转发的 tick 保留 CTP 来源时间与 Gateway 接收时间；本进程在 SDK 中按直连同样的规则做时钟资格判断
（NTP 证据加交易会话登录时的交易所时间）。无法核验的 tick 只用于指标，不作为下单依据（D62-21/27）。

## 对账、恢复与状态

下单走直连，因此状态和恢复与直连版本相同，但属于本目录：`state/`（策略身份、局部序号、未决标记、待发单）
和 `logs/current_position.yaml`（对账基线）。首次运行要 `--first-init` 且账户空仓、无挂单；
以后每次启动按直连规则核对持仓与挂单（详见上级 README 的直连部分）。不要和 `_direct` 目录同时交易同一账户的同一合约。

托管路径（`--orders managed`）的状态归属应是执行服务的持久日志，不使用本目录的 `state/`；
它目前没有可用的启动证明和恢复依据，因此空仓首次启动和带仓/挂单重启都明确不可用。
