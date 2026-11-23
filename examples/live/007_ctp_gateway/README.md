# 007 — CTP SimNow 实盘示例（Gateway 模式）

原 `examples/live/007_ctp` 中的 **Gateway 模式**实盘策略（11 个 `*_gateway/` 文件夹），已按迭代 62 拆分计划与 Direct 直连版本拆分为独立目录：

- 回测版本：[`examples/backtest/007_ctp`](../../backtest/007_ctp/README.md)
- Direct 直连版本：[`examples/live/007_ctp_direct`](../007_ctp_direct/README.md)

每个策略文件夹包含 `README.md`、`config.yaml`（显式 `mode: gateway`）、`<name>_strategy.py` 与 `run.py`，共享本目录内的 `gateway_client_runner.py`、`gateway_local_resources.py`、`gateway_runner_lifecycle.py` 和 `calendar_gate.py`。所有 Gateway 策略经单一组合根 `create_gateway_store` 装配 `GatewayBtApiStore` / `GatewayBtApiFeed` / `GatewayBtApiBroker`（强绑定 `LiveRunBinding(mode="gateway")` 与 `ProcessModeFence`），不加载任何交易所直连写路径。

| 文件夹 | 策略 | 合约 |
| --- | --- | --- |
| `sa_dual_ma_gateway/` | `DualMAStrategy`：纯碱 1 分钟双均线 | SA701（郑商所） |
| `bbroker_5s_single_symbol_gateway/` | `SingleSymbolMaStrategy`：tick 输入，策略内聚合 5 秒 bar | rb2701 |
| `bbroker_5s_pair_arbitrage_gateway/` | `PairSpreadStrategy`：tick 输入，5 秒价差 | rb2701 / hc2701 |
| `mixbroker_5s_single_symbol_gateway/` | `SingleSymbolMaStrategy`：5 秒 bar 输入 | rb2701 |
| `mixbroker_5s_pair_arbitrage_gateway/` | `PairSpreadStrategy`：5 秒 bar 输入 | rb2701 / hc2701 |
| `tickbroker_5s_single_symbol_gateway/` | `SingleSymbolMaStrategy` | rb2701 |
| `tickbroker_5s_pair_arbitrage_gateway/` | `PairSpreadStrategy` | rb2701 / hc2701 |
| `mixbroker_single_symbol_gateway/` | `SingleSymbolMixStrategy` | rb2701 |
| `mixbroker_pair_arbitrage_gateway/` | `PairMixArbitrageStrategy` | rb2701 / hc2701 |
| `tickbroker_single_symbol_gateway/` | `SingleSymbolTickStrategy` | rb2701 |
| `tickbroker_pair_arbitrage_gateway/` | `PairTickArbitrageStrategy` | rb2701 / hc2701 |

## 运行与离线校验

```bash
# 离线校验配置（不读取密钥、不联网）
python examples/live/007_ctp_gateway/sa_dual_ma_gateway/run.py --dry-run
# 首次初始化本地身份（完成后停止，供运营在 Gateway/Risk/Execution 登记）
python examples/live/007_ctp_gateway/sa_dual_ma_gateway/run.py --first-init
# 升级本地状态后正常运行（需先启动并授权独立 Gateway 五组件服务）
python examples/live/007_ctp_gateway/sa_dual_ma_gateway/run.py --upgrade-state
python examples/live/007_ctp_gateway/sa_dual_ma_gateway/run.py --run-seconds 600
```

## Gateway 运营与策略说明（迭代 63 / 迭代 62 拆分）
### 共享 Gateway 的启动（运营侧）

Gateway 是独立的账户级服务进程，由 SDK 的 `bt-gateway-operator` 启动，凭据和授权只来自运营方受保护的资源文件（`BT_API_CTP_GATEWAY_RESOURCES_FILE` 指向的 0600 JSON），从不写进策略配置。可交易 profile 为 `ctp-simnow-trading`：仅 SimNow 账户可开启写入（INV63-08，其他环境开启写入时以 `GATEWAY_WRITE_REQUIRES_BROKER_CONFIRMATION` 拒绝启动），派发按用户决定 B（单次 claim 后在途），结算确认按决定 A（每交易日一次耐久尝试，可信回读才算成功，结果不明只回读不重发）。只读 profile 为 `ctp-local-readonly`。示例与文件格式见 bt_api_py 的 `examples/services/ctp-gateway-simnow-trading.example.md`。

```bash
bt-gateway-operator --config ctp-gateway-simnow-trading.example.yaml --dry-run   # 离线：只解析配置并解析已安装 profile
BT_API_CTP_GATEWAY_RESOURCES_FILE=/PRIVATE/DIRECTORY/resource.json \
  bt-gateway-operator --config ctp-gateway-simnow-trading.example.yaml            # 连接配置的 SimNow 前置
```

会话：一个 Gateway 只维持该账户的一个 TD 会话和按需的 MD 会话，所有策略共用。首启：新策略先在策略侧 `--first-init` 并由运营把身份登记进资源文件。停止：SIGINT/SIGTERM 经 owner 关闭 Gateway；停止策略不会停止 Gateway，停止 Gateway 也不会撤销或重发策略委托。Gateway 不可用：策略等待或拒绝，不回退 direct，不推断委托已撤销。手工交易：账户上的手工或其他来源成交归 external，不计入任何策略持仓。以上离线检查与合成测试不是 SimNow 或真实账户证据。

平仓：Gateway 模式下平仓（`close`、`close_today`、`close_yesterday`）前，策略须从 Gateway 读取自己的可平量，因此运营方须启用策略账本：资源包加 `"strategy_ledger": {"upgrade_from_v10": true}`，运营配置加 `strategy_ledger_enabled: true`（journal 由 v10 升级到 v11，不降级）。11 个 `_gateway` 示例已请求 `direct.strategy_position` 与 `direct.strategy_close_capacity`。未启用时，平仓在发出前即被拒（`STRATEGY_POSITION_UNAVAILABLE`），开仓不受影响。

异常退出：Gateway 被强杀或崩溃后，重启会报 `SESSION_RECONCILIATION_REQUIRED`，等待不会自行解除。运营方用以下命令对账：

```bash
bt-gateway-operator --config <operator.yaml> --reconcile-session --operator <id> --reason <原因>
```

该命令确认旧进程已不存在，且 journal 中无结果未知的下单、撤单或结算确认，写入审计记录后再关闭旧会话记录。若被拒，先到交易所核对账户。详见 SDK 文档 `examples/services/ctp-gateway-simnow-trading.example.md`。策略进程被强杀后，需等其注册租约到期才能以同一身份重新启动。

### 策略侧

11 个 `_gateway` 目录复用各自原策略，但行情及订单都经同一账户级独立 Gateway。先启动并授权 Gateway，再启动策略；策略进程不创建 Gateway 子进程、CTP 会话或读取 CTP 凭据，不支持旧 `gateway.orders`、`--orders` 和 `--managed-boot-check`。每个策略必须具有独立已登记身份和本地持久状态，不能复用他人身份。

```bash
conda run -n base python examples/live/007_ctp_gateway/sa_dual_ma_gateway/run.py --dry-run
conda run -n base python examples/live/007_ctp_gateway/sa_dual_ma_gateway/run.py --run-seconds 600
```

11 个 Gateway 模板默认选择独立 Risk 和 Execution 客户端；服务地址、身份、账户、策略、运行作用域及授权均为占位，部署时须分别与实际服务一致，并使用独立安全 profile 和受保护密钥文件。每个合约均有开仓及三种平仓限价路由，平仓引用和授权由运营填写。模板中的交易日、允许交易日和绝对截止时间均为已过期的有限演示值；匹配这些限价规则的订单因截止时间过期而被拒绝，未匹配订单仍按 NO_MATCH 和 Risk 合同处理；运营须按实际授权逐项替换，不从本地时钟推断交易日。`--run-id` 用于进程状态和停止控制，不是配置中的逻辑交易 run；Gateway、Risk、Execution 三条 route 的逻辑交易 run 须一致，重启时保持原值。变更逻辑交易 run 需要显式受信恢复，不授予跨代重发权限。Store 在持有运行锁时升级 v8。 当前 v8 状态绑定原 Execution 路由配置，修改交易日或期限会改变配置身份，跨日滚动尚不支持；不得删除日志或重建状态来绕过该限制。Runtime 管理和 Monitor 观察由独立服务组合提供，模板不证明完整订单链路。默认自成交检查缺少完整来源切点时，Risk 对 OPEN/CLOSE 失败关闭。

`config.yaml` 为公开占位配置，须与实际 Gateway 的账户、策略、会话、合约和授权配置对齐。默认 `local_files` 加载器从受保护文件读取 CURVE 密钥，并要求首次显式 `--first-init` 创建本地身份及示例初始化标记、登记授权后再 `--upgrade-state`；标记仅防误用，不证明账户空仓、writer fence 或授权；也可选择安装可信 `bt_api_py.gateway_example_resources` entry point。密钥不应放进 YAML、命令行或日志；加载器不授予账户权限。文件权限、初始化和受信工厂接口见各示例 README；离线 `--dry-run` 不加载密钥也不联网。

Gateway 会话/行情断线不触发 direct 回退或假设委托已取消；策略停止不会停止共享 Gateway。行情时钟校准默认关闭，必须显式提供受信 SNTP 配置且两端证据有效才可能取得交易资格。策略资金与权益是可选功能（各 Gateway 示例目录的 README 说明如何开启）；策略资金和可平仓账本、真实 CTP 一致基线、部分订单类型与完整恢复尚未验收；合成测试和离线配置检查均不是 SimNow 或真实账户证据。详见各目录 README 与迭代 63 验收矩阵。
