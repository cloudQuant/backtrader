# 迭代 52：B1 首个配置驱动直接 paper 竖切（Binance USD-M Demo，2026-10-31）

- Backtrader `dev` 父提交：`cdd2e35cd`（A0/A1/A2 基线）
- `bt_api_runtime` 子仓：父 `4236fa7c` → 本轮 `0eee5e9`（`Add config-driven direct Backtrader paper session`）
- `bt_api_py` 父仓：`c68b8dff` → 本轮 `7b21925a`（仅更新 runtime gitlink）
- 计划修订：[迭代52-计划修订记录.md](../迭代52-计划修订记录.md) R1-1/R1-2/R1-3
- 证据等级：SOURCE + 真实 SDK/Store/Broker + fake 传输叶子 + **真实 Binance USD-M Demo 外部模拟账户**；不是生产写入或跨场所验收

## 1. 本轮交付

### 1.1 `bt_api_runtime`（0.1.13）

- 包根改为 PEP 562 惰性导出：`import bt_api_runtime` 不加载 Backtrader、`bt_api_py` 或 `bt_api_run_contract`（专项测试用独立子进程验证）。
- 新增可选 `bt_api_runtime.direct_backtrader`：
  - `DirectProviderProfile`：代码拥有的路由引用 → SDK venue key/环境/账户币种/symbol/凭据变量名的映射；配置中的九个符号引用必须与 profile 一致。
  - `DirectCredentials`：调用方注入的凭据值，`repr` 只显示变量名。
  - `DirectWriteGrant`：run id、模式、provider/环境/symbol、UTC 到期、最大订单数、最大名义金额、`allow_live_write`；对象本身不是签名或可信签发，部署必须由自己的授权边界签发。
  - `DirectBacktraderSession`：校验 plan（schema-v2、paper/live、读写能力）、profile 与 grant；装配真实 `BtApiStore(provider="btapi", backend="direct")`、`BtApiBroker`、`BtApiFeed` 和 `Cerebro`；提供 preflight、有界 run、逆序停机、报告。
  - `_IdlePump`：live feed 阻塞 Cerebro 维护循环时，按 0.5s 驱动策略 `notify_idle`（与 013_3 的既有泵一致）。
  - `_Deadline`：会话级兜底 `runstop`。
  - 报告只含有限/脱敏字段：readiness、broker/store execution summary、shutdown、strategy facts、config sha256；不含凭据值。
- 新增 `runtime/tests/test_direct_backtrader.py`（11 项）：组合/lifecycle/清理顺序、grant 过期/错配/live 写拒绝、能力缺失、凭据缺失、报告不含秘密、包根惰性导入、idle pump。

### 1.2 Backtrader 示例（迭代 52 首个竖切）

`examples/unified/052_provider_demo_roundtrip/`（当时为 052_binance_demo_roundtrip）：

| 文件 | 职责 |
| --- | --- |
| `README.md` | 入口、写门槛、有界往返、证据边界、迭代 43 选层说明 |
| `config.yaml` | 唯一 schema-v2 用户配置（`mode: paper`，九个符号引用，策略参数，`requested_capabilities`） |
| `binance_demo_roundtrip_strategy.py` | 普通 `bt.Strategy`：市价下方 200 bps 挂单、6s 后撤单、部分成交 reduce-only 平仓、45s 硬超时 |
| `run.py` | 离线校验 / `--live` 写拒绝 / `--live --allow-write` 有界运行、凭据按名读取、证据写入 |
| `entry_tier.py` | `examples/_support/entry_tier.py` 的逐字节副本（迭代 43 契约） |

`run.py` 默认不读取 `.env` 以外的私有输入；只有 `--live --allow-write` 才解析凭据变量名。
`--preflight-only` 只做账户/readiness 读取，不下单。

### 1.3 测试

新增 Backtrader `tests/unit/test_iteration52_binance_demo_strategy.py`（3 项）：
- 按订单 `ref`（而非对象身份）匹配 Accepted/Canceled，驱动往返；
- 外来订单 ref 不改变状态；
- 部分成交后 Canceled → reduce-only 平仓。

## 2. 分层验收

| 层级 | 命令/证据 | 结果 |
| --- | --- | --- |
| SOURCE：runtime | `pytest tests`（runtime/src + contracts/src + local Backtrader） | **159 passed**，1 个既有 Quandl DeprecationWarning |
| SOURCE：strategy | `pytest tests/unit/test_iteration52_binance_demo_strategy.py` | **3 passed** |
| SOURCE：示例形态 | `pytest tests/unit/test_iteration43_example_layout_boundaries.py -k 052` | **1 passed** |
| 真实组件 + fake 叶子 | `tests/integration/test_btapi_execution_session.py`（真实 SDK/Store/Broker，fake transport backend） | **2 passed** |
| INSTALLED | 独立 wheel 消费 | **NOT_RUN**（本轮未构建/安装新 runtime wheel） |
| 离线校验 | `python run.py` | `COMPLETED / offline_validate_ok`，exit 0 |
| live 写拒绝 | `python run.py --live` | `BLOCKED / write_not_authorized`，exit 2，不读凭据 |
| PAPER ACCOUNT | `python run.py --live --allow-write ...` | **PASS**（见 §3） |
| live 生产写入 | — | **NOT_AUTHORIZED**；`allow_live_write` 恒为 false |

## 3. 真实 paper-account 结果（Binance USD-M Demo）

最终源码运行：

```text
python run.py --live --allow-write \
  --order-journal C:/Users/yunji/.bt_api_py/execution-journals/e332676837f2cfe516d740e09b99258004b7a8f2922bac2051ef9270d607baef.jsonl \
  --ledger-venues BINANCE,OKX --session-seconds 30
```

- 结果：`PASS / round_trip_canceled`，exit 0，25.2 秒。
- run id：`i52-binance-demo-20261031T010054Z-828f269a`。
- 证据：`examples/unified/052_provider_demo_roundtrip/evidence/20261031T010119Z_052_binance_demo_roundtrip_PASS.json`
  （SHA-256 `62e674acfa20383c0dee3cdee7af122ed66315e266c7ab7943773ffd57c7fdd4`，已随本轮提交）。
- 订单事实：事件 `open_submitted → order_submitted ×2 → order_accepted → cancel_requested → order_accepted → order_canceled`；
  open order `Canceled`，`remote_terminal_status=canceled`，`cancel_command_completed=true`，
  `cancel_execution_unknown=false`，`cancel_receipt_id=b1ddb8a417c3485b9555810256d66f75`；
  `approval_operation_count=2`（submit + cancel，配置上限 2）。
- 执行汇总：Store `submit_calls=1`、`cancel_calls=1`、`active_orders=0`、`unknown_ids=[]`、`evidence_complete=true`；
  Broker 同样无未知/无活动订单。
- 停机：`broker_shutdown_state.status=PASS`、`remote_flat_proven=true`、`remote_position_count=0`、
  `unknown_orders=0`；cleanup `broker.stop → store.stop`；`store_connected=false`。
- 凭据：只记录变量名 `BINANCE_DEMO_API_KEY/SECRET`、`OKX_DEMO_API_KEY/SECRET/PASSPHRASE`；证据不含值。

### 3.1 运行过程中观察到的真实约束（已修复）

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `journal: unreadable_journal` | 账户 durable ledger 由 012_1 多场所（BINANCE+OKX）写入；单场所配置解析到 OKX 行时 `required_environment_missing` | 示例显式 `--ledger-venues BINANCE,OKX` 并用既有 `.env` 中 OKX Demo 凭据声明 ledger 场所；未迁移/删除旧 journal |
| 订单本地 `Rejected` | Broker 的默认现价/现金/头寸检查或 SDK 风险门 | 前两次为 `account_risk_snapshot_stale`（默认 max age 2s）；profile 显式 `account_risk_max_age_seconds=30` 并在 preflight 初始化基线 |
| 订单只在停机时被撤 | live feed 阻塞 Cerebro 维护循环，策略 `next`/`notify_idle` 未被驱动 | runtime 增加有界 `_IdlePump`；策略改为 `notify_idle` 维护 |
| 策略未响应 Accepted/Canceled | `notify_order` 以对象身份比较，Broker 通知对象与提交对象不同 | 改为按 `order.ref` 匹配并采纳通知对象（新增 3 项回归测试） |

## 4. 边界与遗留

- 本 PASS 只覆盖 **Binance USD-M Demo 一个场所**的一笔有界 LIMIT 往返；不覆盖 OKX/SimNow 真实往返、部分成交、断线/重启恢复、多策略账户隔离或 HFT。
- OKX 在 ledger 中被声明和连接（账户快照/风险读取）但没有下单；该过程未作为 OKX 验收。
- 旧 99 案 tracker 和历史 `12 PASS / 3 BLOCKED / 84 NOT_RUN`、Optional16 `0/16` 未改写；本目录不是正式 case 的替代。
- `bt_api_base.plugins` 在连接时打印两条环境告警：`ctp` 插件缺少 `bt_api_base.gateway.registrar`，`mt5` 声明无可支持场所；二者未影响本轮 Binance 路径，但属于 SDK 插件环境的既有告警，未在本轮修复。
- 独立 wheel 安装、`bt_api_runtime` 旧包退役（R10）、028/其余示例迁移、OKX/SimNow 实际 paper 流程仍是后续轮次。
- 既有测试债务（非本轮引入）：`test_iteration43_example_layout_boundaries.py` 在 HEAD 已因 `examples/service_execution_session` 未登记和 028 README 缺少迭代 43 选层段落而失败；本轮只验证 052 叶子的形态用例通过，未修其他两例。

## 5. 下一轮

- B1 剩余：runtime validate/doctor 离线诊断、topology 显式选择与 fail-closed、schema v3（run identity/permissions）设计；旧 runtime 活跃调用方清点与迁移计划。
- C：迁移 028 到三/四件套与同一策略源码的 paper/live 配置；随后 OKX/SimNow 的真实 representative 流程。
