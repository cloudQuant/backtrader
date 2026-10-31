# 迭代 52：同一策略源码的 Binance/OKX Demo paper 双场所验收（2026-10-31）

- 仓库/分支：Backtrader `dev`；父提交 `0c665dd56`（B1 单场所轮）
- `bt_api_runtime` 子仓：`0eee5e9` → `5078776`（`Harden direct paper session reconciliation and recovery`）
- `bt_api_py` 父仓：`7b21925a` → `1e6780a6`（`Recover provider-confirmed unknown orders`，含 runtime gitlink）
- 计划修订：[迭代52-计划修订记录.md](../迭代52-计划修订记录.md) R2
- 证据等级：SOURCE + 真实 SDK/Store/Broker + **真实 Binance USD-M Demo 与 OKX SWAP Demo 外部模拟账户**；不是生产写入、SimNow 或安装轮验收

## 1. 本轮交付

### 1.1 示例：同一策略、两个公开配置

`examples/unified/052_provider_demo_roundtrip/`（由 052_binance… 泛化）：

| 文件 | 说明 |
| --- | --- |
| `provider_demo_roundtrip_strategy.py` | 同一份普通 `bt.Strategy`；数量按 `notional/(price×contract_value)` 换算；支持 GTC 挂撤与 IOC 开/平两种按配置选择的订单风格；成交后按 tick 对齐的 reduce-only 限价 IOC 平仓；`close_delay_seconds` / `recovery_grace_seconds` 为运行时恢复留出有界窗口 |
| `config.yaml` | Binance USD-M 模板（`venue: BINANCE`，BTCUSDT，GTC 挂撤） |
| `config.okx.yaml` | OKX SWAP 模板（`venue: OKX`，BTC-USDT-SWAP，IOC 开/平，`contract_value: 0.01`，tick 0.01） |
| `run.py` | 统一配置解析、离线校验、写授权、grant、凭据按名读取、证据写入；为 shutdown 恢复提供独立 provider 查询客户端（无执行会话） |
| `entry_tier.py` | 迭代 43 判层副本 |

策略不判断 venue/provider/endpoint；venue 与产品由 `strategy_parameters` 选择，具体 SDK venue key/币种/凭据变量由代码拥有的 profile 映射。

### 1.2 Runtime（0.1.13，子仓 `5078776`）

- `preflight` 在风控基线与 readiness 之前执行账户对账（positions/open orders/unknown/active），发现残余风险立即 fail closed。
- Broker 现金检查前通过 `get_instrument_spec` 缓存合约规则（OKX `contract_value*contract_multiplier=0.01`），避免把 0.19 张合约误算为 0.19 BTC。
- `reconcile_retry_max_attempts/backoff`、`cancel_confirmation_timeout` 显式可配（默认 6×0.5s / 5s）。
- `_IdlePump` 在驱动策略 `notify_idle` 的同时，按 1s 节奏调用 provider-confirmed unknown 恢复；shutdown 前再次恢复，并把恢复事实写入报告。
- 执行 summary 保留 run 期值，shutdown 后的事实单独存 `post_execution_summary`（避免停机清零覆盖提交次数）。
- 新增 `failure_detail`（有限 ASCII 诊断）与 `set_provider_query()` 公共注入点。

### 1.3 SDK（`1e6780a6`）

`bt_api_py.reconcile_unknown_order_from_query(api, exchange_name, request, *, expected_client_order_id=None, query_record=None)`：

- 只接受当前 journal 中处于 unknown、client id 匹配、provider 记录 terminal-confirmed、非 execution-unknown 的订单；
- 订单身份（side/position_side/offset/position_mode/quantity_unit/order_ref 等）取自 journal，provider 只提供状态/成交事实（避免 OKX `order_ref` 语义冲突）；
- 通过真实 execution event 路径写 journal；只读/关闭/非 unknown/非终态一律拒绝；
- 不提交、不重试、不撤销订单；生产写入未授权。

测试：`tests/bt_api_contract/test_unknown_order_recovery.py` **5 passed**。

## 2. 分层验收

| 层级 | 命令 | 结果 |
| --- | --- | --- |
| SOURCE：runtime | `pytest tests`（runtime/contracts + local Backtrader） | **159 passed** |
| SOURCE：strategy | `pytest tests/unit/test_iteration52_provider_demo_strategy.py` | **3 passed** |
| SOURCE：SDK recovery | `pytest tests/bt_api_contract/test_unknown_order_recovery.py` | **5 passed** |
| 真实组件 + fake 叶子 | `tests/integration/test_btapi_execution_session.py` | **2 passed** |
| INSTALLED | 独立 wheel 消费 | **NOT_RUN** |
| 离线校验 | `python run.py` / `--config config.okx.yaml` | 均 exit 0 |
| live 写拒绝 | `python run.py --live` | BLOCKED / exit 2，不读凭据 |
| PAPER：Binance | `--live --allow-write` | **PASS** |
| PAPER：OKX | `--config config.okx.yaml --live --allow-write` | **PASS** |
| live 生产写入 | — | **NOT_AUTHORIZED** |

## 3. 真实 paper-account 结果

### 3.1 Binance USD-M Demo（GTC 挂单/撤单）

- run id：`i52-binance-demo-20261031T012729Z-2bd40ddf`
- 证据：`evidence/20261031T012756Z_052_binance_demo_roundtrip_PASS.json`
  （SHA-256 `8f933bcde024153e0cd6d6a728280f76c326495a2717b4acba20f00655cb0e73`）
- 事件：`open_submitted → order_submitted → order_accepted → cancel_requested → order_canceled`
- client id `064646032100`，external id `BINANCE___SWAP:28659215455`，submit receipt `2153cd75…`，cancel receipt `0d0c1ee7…`，`remote_terminal_status=canceled`，fill 0。
- store：submit 1 / cancel 1 / active 0 / unknown [] / evidence_complete **true**。
- shutdown：broker PASS、store PASS、`unknown_recovery 0/0`、cleanup `broker.stop → store.stop`。

### 3.2 OKX SWAP Demo（IOC 开仓 + reduce-only 平仓）

- run id：`i52-okx-demo-20261031T012651Z-25c3b373`
- 证据：`evidence/20261031T012716Z_052_okx_demo_roundtrip_PASS.json`
  （SHA-256 `c3bfcdec860b9728dc058f6c0026fce3d35046ea1b57d908de921d71dbf9c29f`）
- 开仓：Completed，0.19 contracts，均价 77408.46，手续费 0.073538 USDT；
  平仓：Completed，-0.19 contracts，均价 77403.33，手续费 0.073533 USDT。
- store：submit 2 / active 0 / unknown [] / fee_unresolved [] / evidence_complete **true**。
- shutdown：broker PASS、store PASS、`unknown_recovery 0/0`、cleanup 正常。
- 账户最终无持仓、无挂单（外部 OKX 客户端查询确认）。

### 3.3 过程中的真实失败与安全收尾

| 尝试 | 现象 | 处置 |
| --- | --- | --- |
| OKX GTC 首次 | submit 成功但 SDK journal 无终态回调，session UNKNOWN；shutdown INCOMPLETE | 外部只读查询确认 provider 已 canceled、fill 0；用新 recovery API 写入终态，unknown 清零 |
| OKX IOC 首次平仓 | 开仓成交，市价平仓被本地 `invalid_price_tick` 拒绝 | 外部 reduce-only 市价平仓 0.19（ordId 4056973496927465473），随后改为 tick 对齐限价 IOC |
| OKX IOC 第二次平仓 | 开仓成交，平仓被 `unresolved_or_undurable_journal` 拒绝（开仓 journal unknown 未清） | 外部 reduce-only 平仓 0.19（ordId 4056979238862532609）；runtime 增加 pump 恢复/延迟平仓 |
| OKX IOC 第三次 | 开仓成交，pump 恢复因 account id 占位符失败，平仓仍被拒 | 外部 reduce-only 平仓 0.19（ordId 4056983202479812609）；runtime 改用 journal canonical account id |
| OKX 最终 | 开仓/平仓均 Completed，pump 在窗口内清零 unknown，shutdown PASS | 计为本轮 OKX paper PASS |

所有外部平仓均为风险减少操作，只针对本轮产生的 Demo 持仓；不重发原订单、不读取私密捕获。三次平仓订单均已在 OKX 客户端查询为终态。

## 4. 发现的 SDK 缺口与边界

- **OKX 订单事件不把终态写入 journal**：broker 能从成交事件得到 Completed，但 SDK journal 仍标 unknown，导致后续写被 `unresolved_or_undurable_journal` 拒绝。本轮用 provider-confirmed 查询 + 有界 pump/grace 作为运行时补偿；**根因仍需在 SDK 事件归一化/终态确认层修复**，否则其他策略/场所仍可能遇到。
- OKX 的 `order_ref` 在查询记录中指向外部 order id，而 journal 中指向 client id；恢复 API 以 journal 身份为准，已规避。
- `broker_shutdown_state` 在本轮为 `status=PASS / reason=store_shutdown_complete`，`flat_proven=false`；账户平仓由策略完成，报告保留该事实，不把它写成账户级 flat 证明。
- 交易所查询/成交事实、账户持仓、风险快照均来自真实 Demo；未读取 `.env` 值到证据，未提交任何密钥。
- 仅两个 crypto Demo 场所；SimNow 真实流程、installed wheel、028 迁移、旧 runtime 退役（R10）仍 OPEN。
- 既有测试债务（非本轮引入）：`test_iteration43_example_layout_boundaries.py` 的 `examples/service_execution_session` 登记与 028 README 迭代 43 段落仍失败；本轮 052 叶子的形态用例通过。

## 5. 下一轮

- 修复 SDK OKX 终态确认缺口（或以 recovery 作为显式生产路径）并补充事件级回归。
- SimNow representative paper 流程（注册模拟通道）与第三个场所证据；installed wheel 消费；028 迁移；A0 未闭合项与 R10 退役门槛。
