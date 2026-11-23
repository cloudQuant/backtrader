# 需求文档评审报告：《迭代 62 拆分计划：Backtrader 实盘 Direct 与 Gateway》

- **评审对象**：[需求文档.md](需求文档.md)（日期 2026-11-22，状态：规划草案 / REVIEW_PENDING / 未实施）
- **评审日期**：2026-11-22
- **评审人**：gemini-4-Neon
- **评审结论**：**NO-GO / 需重大修订后再进入 SPLIT-00 冻结（MAJOR REVISION REQUIRED）**
- **证据等级与审查边界**：全文为 **STATIC**（仅基于本地公开源码、配置模板与跨迭代需求/计划文档的独立交叉核对；未参考同目录及其他任何评审报告；未读取 `.env`、真实凭据或私密配置；未启动服务、未执行测试或账户操作）。下文严格区分**既定职责**、**当前实现**、**目标设计**、**未验收内容**与**本次评审建议**；任何路径存在、源码检查或既有单元测试数字均不代表行为、发行或真实账户能力已通过验收。

### 核对基线（2026-11-22 本地工作树静态快照）

| 仓库 | 分支 | 实际核对 HEAD | 草案记录 HEAD | 工作树与补充说明 |
| --- | --- | --- | --- | --- |
| `d:/source_code/backtrader` | `dev` | `cb8493f200b05a31eef47aa8ad2217b45dff5b1c` | `92b183ed10658e6f150d7ac56211a4f5794e6a8f` | 本地已前进 2 个提交（`2487275ab`、`cb8493f20`）；工作树含迭代 71 相关未提交改动（`indicator.py`、`digital_macd.py`、`factor_strategy.py` 及文档）。 |
| `D:/bt_api_py` | `dev` | `53d3ebe621ef048c7f4c47f9125740c7fa29b3ee` | `53d3ebe621ef048c7f4c47f9125740c7fa29b3ee` | 与草案一致；已同步核对 `bt_api_py/` 核心入口及 `bt_api/` 下五组件（Gateway/Execution/Risk/Monitor/Runtime）公开源码与 README。 |

---

## 一、总体评价

### 1.1 草案已确立的正确方向（值得保留）

1. **实盘双模式互斥原则清晰**：明确实盘仅保留 `Direct` 与 `Gateway` 两条互斥路径，否定混合实盘拓扑，不以静默回退或猜测默认值处理配置错误。
2. **定位务实，拒绝性能幻觉**：明确本轮拆分为“消除职责交叉与隐式选路”，不预设时延更优承诺，不改动 Backtrader 核心调度、指标计算与回测撮合语义。
3. **证据边界诚实、反例精准**：全文标明 `NOT_RUN`，未将静态代码、fake 测试或 SimNow 演练冒充生产验收；准确指出了 `btapistore.py:_configure_execution_routing` 的“Direct SDK + 远端 Execution”混合反例，以及 `AtomicIntakeService` 未接 `risk_port` 的现状。
4. **代码行号核对质量较高**：草案 §2 引用的 `btapistore.py`（7,337 行）、`btapifeed.py`（4,269 行）、`btapibroker.py`（6,675 行）、`_btapi_direct_mode.py`、`_btapi_gateway_stream.py` 以及 `bt_api_py` 的 `gateway_strategy_config.py`、`service_config.py`、`direct_api_assembly.py` 关键行号经抽核基本准确。

### 1.2 核心结构性问题与分级统计

尽管方向正确，但对照 `backtrader` 与 `D:/bt_api_py` 实际源码及迭代 60–71 既有决策，本草案在**五组件订单与风控拓扑、策略进程与服务部署边界、Backtrader 现存多路径盘点、框架参数/继承机制、本地持久化状态耦合、跨仓依赖与故障窗口**上存在多处根本冲突与严重盲区，当前形态尚不足以支撑 SPLIT-00 合同冻结。

| 级别 | 数量 | 摘要 |
| --- | ---: | --- |
| **P0（架构阻塞）** | 3 | 五组件订单/风控拓扑与现有代码及 63–65 合同直接矛盾且漏报底层硬阻塞；“五组件必配”混淆部署拓扑与策略进程端口（误判 Runtime/Monitor 形态）；Backtrader 现有 9 条交织路径盘点严重不全。 |
| **P1（高风险合同缺口）** | 5 | Backtrader 已去元类化，草案误判“metaclass params”而漏掉真实 MRO/`StoreParams`/`isinstance` 陷阱；`live_state/` 共享持久文件未纳入拆分设计；Direct/Gateway 五大框架语义不对称未建模；跨仓归属与 Python/反循环依赖矩阵缺失；持久化故障窗口顺序写反、单写者锁作用域混同。 |
| **P2（中风险落地缺口）** | 5 | 误伤“实盘写关闭只读预演”风险；22 个 `007_ctp` 示例与共享 runner 迁移未纳入交付；未与迭代 71 结构/静态门禁（Mypy 0 errors/Ruff 0 errors）对齐；运行期五组件故障域矩阵缺建议方案；SPLIT-01/04 清退时序矛盾且 SPLIT-02/03 粒度过粗。 |
| **P3（事实与文档缺陷）** | 6 | 11 处相对 Markdown 链接全部断链；Backtrader 基线 HEAD 与迭代 71 状态滞后；`bt_api_runtime` 源码现状被旧 README 误导；12 个 Broker 助手模块体量与 `ExecutionOrderRouter` 共享风险未提示；目录名含空格等。 |

---

## 二、P0 级阻塞问题（必须先裁决并修订，再进入 SPLIT-00）

### P0-1：Gateway 五组件“订单链路拓扑与风控校验归属”与现有源码及迭代 63–65 已决合同直接冲突，且漏报两条底层硬阻塞

- **草案表述**（`需求文档.md` §4 L58–60、L64；§8 S-03 L100；§11 L141）：
  - 建议 Execution 作为新策略订单意图的**唯一上游受理与编排入口**，并声称“撤销 63/65 为可选组件或未命中回原路径留下的实盘兼容口”；
  - 描述链路为：“订单意图进入已绑定的 Execution 执行入口，**经约定的授权组件核对 Risk 证据后**交给 Gateway 交易 owner 唯一派发”；“Execution 验证与订单意图对应的证据，再决定能否派发”；同时又写“沿用 63 既有边界：Gateway 不假定校验 Risk 准入”。
- **双仓源码与迭代 63–65 合同实证（STATIC）**：
  1. **现有架构与代码是“代理转发链（Proxy Chain）”，而非“Execution 验 Risk 凭证后直发 Gateway（Ticket Pattern）”**：
     - 迭代 64 已由用户决定（`U64-9/U64-10`，`迭代64/迭代计划.md:34–35, 114`）：**Risk 是位于 Gateway 之前的独立微服务进程**，订单路径为 `策略或 Execution → Risk 服务 → Gateway`。
     - `D:/bt_api_py/bt_api_py/gateway_strategy_config.py:332–337` 明确强制：一旦选中 Risk，策略客户端**禁止**持有 Gateway 的 `direct.reserve` / `direct.dispatch` 写权限（防止绕过 Risk 直打 Gateway），只允许经 `RiskServiceClient` 发起 PLACE，并用委派操作（`direct.delegated_cancel` / `direct.delegated_command_status`）在 Risk 不可用时照常查询与撤单。
     - `D:/bt_api_py/bt_api_py/gateway_api.py:6–10, 696–739, 999–1019` 已完整按“代理转发 + 委派撤单”实现。
  2. **现有 Execution 路由是“规则命中走母单，未命中走原路径（Risk→Gateway）”**：
     - 见 `backtrader/brokers/_btapi_gateway_stream.py:739–800` 与 `D:/bt_api_py/bt_api_py/execution_routing.py:1–23`：这落实的是迭代 65 用户决定 `D65-02 / D65-10 / D65-15`（策略按规则决定哪些订单进 Execution 母单，未命中返回 `ExecutionRoutingOutcome.DIRECT_PATH` 后继续走 `risk_reserve` / `Gateway`）。
     - 若草案强行要求“**全部策略订单（包括最普通单笔限价单）均必须经 Execution 受理，且撤除未命中直通口**”，则实质上推翻了 `D65-02 / D65-10 / D65-15`，且必须回答：普通单是否包装成单子单母单？Execution 宕机时普通平仓单怎么办？撤单走 Execution 还是走 Gateway 委派？
  3. **漏报了比 `AtomicIntakeService` 更底层的两条硬阻塞（当前真实代码完全无法闭环）**：
     - 草案 §7 L90 仅指出 `AtomicIntakeService` 缺 `risk_port`，但实查源码还存在三处硬阻断：
       1. `D:/bt_api_py/bt_api_py/gateway_api.py:869–873`：**`_risk_reserve()` 当前根本不发 `self._risk.reserve()` RPC，无条件返回 `GatewayRiskRoutedResult("UNKNOWN", code="RISK_OUTCOME_UNKNOWN")`**（代码注释明言：v1 无法证明 Gateway journal 首次创建，在 v2 证明接通前永久返回 UNKNOWN）；
       2. `D:/bt_api_py/bt_api_py/risk_parent_port.py:126–137`：即便接上测试用的 `ParentSubmitService` + `RiskParentPort`，其中的 **`reserve_child()` 与 `dispatch_child()` 也硬编码返回 `{"status": "UNKNOWN", "code": "risk_parent_child_unavailable"}`**；
       3. `AGENTS.md:3` 与 `D:/bt_api_py/bt_api/bt_api_risk/README.md`：迭代 64 默认启用的自成交保护 R-05 因缺活动订单共同切点真实数据，当前对所有 OPEN/CLOSE 均 fail-closed 拒绝。
- **评审建议**：
  1. 在 SPLIT-00 前必须由用户显式裁定 Gateway 交易链拓扑，消除草案内部与迭代 64/65 的矛盾：
     - **推荐方案 A（与 63–65 演进兼容）**：坚持代理转发模型，不改为“Execution 持凭证直打 Gateway”；明确区分“五组件均须已部署且通过健康/绑定预检”与“每笔单是否强制进母单切片”，若要求每笔单必经 Execution，则需在 65 补齐“透传/单子单母单 + `AtomicIntakeService` 接 `RiskParentPort` + `child dispatch` 真实写路径”并显式登记对 `D65-02/10/15` 的变更。
     - **备选方案 B（改为凭证模式）**：若确要让 Execution 验 Risk 许可后直调 Gateway，必须显式立项变更迭代 63/64 合同（重新定义 Gateway 对 Risk 凭证的验证或信任边界，否则无法防绕过）。
  2. 将 `gateway_api.py:869–873`、 `risk_parent_port.py:126–137` 与 R-05 共同切点缺口全部显式写入 §2 与 SPLIT-00 阻塞清单，并把**“Backtrader 框架双模式拆分”**与**“SDK/五组件真实写路径闭环”**在里程碑上解耦，避免 BT 拆分被 64/65 外部数据前置无限期卡死。

---

### P0-2：“五组件必配”严重混淆了“服务端部署拓扑”与“Backtrader 策略进程客户端端口”，且与 Runtime (`D66-02`)、Monitor (`D63-36/43`) 既有架构冲突

- **草案表述**（§1 L8、§2 L33/35、§4 L61–62、§5 L68、§8 S-01/S-03 L98/100）：
  - “`GatewayBtApiStore` 管**五组件端口绑定**和 Gateway 会话。”
  - “S-03：**五端口各验身份、版本、健康**并通过合同测试……Monitor 只读、Runtime 不重复派发。”
  - “Runtime：核对组件和配置，协调启动、停止、恢复、预检及诊断”（§4 L62），并在 §9 Q2 询问“Runtime 开启顺序”。
- **双仓源码与迭代 66/68 合同实证（STATIC）**：
  1. **Runtime 是策略进程的“外部父监督器”，不是 `GatewayBtApiStore` 要连接的下游 RPC 端口**：
     - 查阅 `D:/bt_api_py/bt_api/bt_api_runtime/runtime/src/bt_api_runtime/__init__.py:91–137` 及 `迭代66/迭代计划.md:48–64`：Runtime 在迭代 66 已实现独立的进程监督器与本地回环控制服务（`RuntimeSupervisor`、`PosixProcessAdapter`、`WindowsProcessAdapter`、`StopFileChannel`、`GatewayControlClient`、`EventStore`、`POST /v1/control`）。
     - 查阅 `backtrader/live_trading/`（`run_status.py`、`stop_request_file.py`、`graceful_stop.py`）与 `examples/live/007_ctp/gateway_client_runner.py:282–288, 448–475`：策略进程由 Runtime 拉起，通过 `--run-id`、`--heartbeat-interval`、`--stop-request-file`、`state/run_status.json`、`state/last_run.json` 与 Runtime 交互；`GatewayBtApiStore` **不存在也不应存在**反向连接 Runtime 的交易端口。
     - 查阅 `D:/bt_api_py/bt_api_py/service_config.py:263–268`：Runtime 只是 Gateway 控制端口（`application.direct_write` → `direct.control.*`）的客户端，用于停止无响应策略时请求 DRAIN/STOP_NEW 或代理运营 RESUME（`D66-08`）。
     - 查阅 `跨迭代合同与决策.md:198–204`（`D66-02`，用户已决定）：**Runtime 首期只监督策略进程，不监督或编排 Gateway/Risk/Execution/Monitor 四个共享服务**！草案要求 Runtime 协调五组件开启顺序，直接违背 `D66-02` 却未将其标为跨迭代决策变更。
  2. **Monitor 是旁路观测服务，其必配门禁归属 Gateway 侧（`monitor_required`），而非在每个策略进程内强绑为下单前直连端口**：
     - 查阅 `跨迭代合同与决策.md:124–133`（`D63-43`）与 `迭代68/迭代计划.md:45, 64, 97`：Gateway、Risk、Execution、Runtime 各自通过独立中继向 Monitor 推送事件/心跳；当配置 `monitor_required=True` 时，由 **Gateway 自己**根据已确认心跳年龄对账户施加 `STOP_NEW`（`D63-36`）。
     - 如果按草案字面把 Monitor 做成 `GatewayBtApiStore` 的必连“第五端口”并纳入策略写前校验，会把策略进程的网络连接面、CURVE 密钥集与清理失败面（`cleanup_confirmed`）从 3 个客户端凭空扩到 5 个，且与 Gateway 侧统一的 `monitor_required` 门禁形成双头判定冲突。
- **评审建议**：
  - 在文档中**彻底拆开两层概念**：
    1. **部署级五组件全备**（运维/预检视角）：Gateway 实盘环境必须同时运行 Gateway、Risk、Execution、Monitor、Runtime 五个服务，且 Gateway 开启 `monitor_required=True`、策略由 Runtime 监督运行；
    2. **策略进程（`GatewayBtApiStore`）客户端绑定边界**：
       - 交易/数据 RPC 端口：按裁决拓扑仅绑定 **Gateway**、**Execution**（及若保留规则分流时的 **Risk**）；
       - **Monitor 就绪证据**：优先通过 Gateway 只读状态/健康快照证明 `monitor_required=True` 且心跳健康（策略进程可选附加异步非阻塞 `ServiceTelemetryEmitter` 心跳，不阻塞下单）；
       - **Runtime 监督契约**：通过受管启动合同（如强制要求合法 `--run-id`、心跳/停止文件/优雅退出状态通道）证明策略运行在 Runtime 监督之下，而不是在 Store 内新建一个 Runtime RPC 客户端。
  - 若用户确实希望扩大 Runtime 职责去编排五服务启停，必须在 §11 显式登记为**废止/升级 `D66-02`** 的独立决策项。

---

### P0-3：Backtrader 现有 **9 条交织路径** 盘点严重不全，清退范围与代码体量存在重大盲区

- **草案表述**（§2 L18–24、§3 L39–48）：
  - 草案 §2 仅列出 3 个文件（共 18,281 行），重点只分析了 Direct、Gateway 和 `_configure_execution_routing`；§3 仅粗略提及 `ServiceReadProxy` 和 `Replay`。
- **Backtrader 源码全量实证（STATIC）**：
  - **代码规模**：实盘相关代码实际分布在 7 个目录（`stores/` 14 文件 9,785 行、`feeds/` 24 文件 12,673 行、`brokers/` 19 文件 31,403 行、`service/` 23 文件 9,543 行、`execution/` 17 文件 4,809 行、`live_state/` 19 文件 8,772 行、`live_trading/` 5 文件 2,428 行）；仅核心三文件的模式分支判断就高达 **`btapistore.py` 179 处、`btapibroker.py` 82 处、`btapifeed.py` 66 处**，且 `brokers/` 下另有 12 个 `_btapi_*`/`_execution_*` 私有模块合计 **18,871 行**。
  - **实际并存的 9 条路径与草案盲区**：

| # | 现有路径 / 分支 | 源码定位 | 草案现状 | 盲区风险 |
| --- | --- | --- | --- | --- |
| 1 | **迭代 62 Direct 写入路径** (`_sdk_mode=True & _direct_write_mode=True`) | `btapistore.py:751–756`；`_btapi_direct_mode.py`（6,363 行） | 已覆盖 | 需明确是否唯一代表目标 Direct 模式。 |
| 2 | **迭代 60 旧直连 SDK 路径** (`_sdk_mode=True & _direct_write_mode=False`，含 SDK 本地 `execution_config` / `order_journal`) | `btapistore.py:713–756`；`btapibroker.py:454–495, 2323–2545`；`direct_api_assembly.py:31–44` | **完全遗漏** | **极高**：若不明确去留，拆分后的 `DirectBtApiBroker` 内部仍会残留两套完全不同的下单、队列（`queued_receipt`）、批量事件（`event_batch_handoff`）、对账与恢复（`execution_recovery`）实现！ |
| 3 | **迭代 41/60 托管服务路径** (`ServiceExecutionSession` / `ManagedExecutionAdapter` / `managed_runtime_session` / `ServiceRecoveryBrokerMixin`) | `btapistore.py:438, 482–484`；`btapibroker.py:187, 426–430, 2329–2340, 2428–2512`；`service/service_execution_session.py`（983 行） | **完全遗漏** | **极高**：迭代 65 `D65-11` 已定退役该路径，但仍深度寄生在 `BtApiStore` 与 `BtApiBroker` 的 MRO 与提交链中，且关联大量旧测试。 |
| 4 | **迭代 63–65 Gateway 路径** (`_gateway_mode=True`, `config["gateway_strategy"]`) | `btapistore.py:650–675`；`service/gateway_config.py`（780 行）；`_btapi_gateway_stream.py`（2,123 行） | 部分覆盖 | 漏报其中已存在的 `execution_selection` 路由与 `DIRECT_PATH` 回落，以及仅涵盖 3 组件（缺 Monitor/Runtime）。 |
| 5 | **迭代 65 Direct+Execution 混合路由** (`_configure_execution_routing`) | `btapistore.py:1186–1449`；`_btapi_direct_mode.py:3228–3232, 3267–3295` | 已点名 | 未提醒它与路径 4 共用 SDK `ExecutionOrderRouter` 及 `_execution_parent_projection.py` / `_execution_routing_apply.py`（2,786 行），清退时易误伤。 |
| 6 | **62.08 MarketHub+Direct 混合路径** (`market_runtime_factory` / `forwarding_config` / `transport_mode`) | `btapistore.py:941`；`D:/bt_api_py/bt_api_py/direct_api_assembly.py:103–115` | **判断自相矛盾** | **极高**：草案 §2 L34 暗示保留“本地 MarketHub”，但 `direct_api_assembly.py:113` 明确标注 `market_runtime_factory` 是 62.08 Gateway MarketHub 行情 + Direct 下单的混合入口；放行它等于为混合实盘留后门！ |
| 7 | **实盘 Cohort / 因子源路径** (`cohort_source_mode` / `market_factor_source_binding` / `factor_execution_coordinator`) | `btapifeed.py:665, 701–706, 860–921, 1002–1062`；`_btapi_cohort.py`；`btapibroker.py:2323–2328` | **完全遗漏** | Gateway Feed 已显式拒绝 `cohort_source_mode`（`btapifeed.py:1028`），Direct Feed 与 Base Feed 是否保留该路径及额外 6+ 条 `_LIVE_COHORT_EXTRA_LINES` 线必须冻结。 |
| 8 | **Service Read Proxy 只读路径** (`_service_read_only=True`, `api=ServiceReadProxy(...)`) | `btapistore.py:395–398, 712, 3187–3195`；`service/service_read_proxy.py`；`bt_api_runtime/assembly.py` | 简略提及 | 依赖方包含 `bt_api_runtime` 的 `assembly.py` / `sdk_readonly.py`；剥离需同步跨仓影响清单。 |
| 9 | **Local Replay 与无 SDK 预置数据夹具路径** (`provider="local_replay"`、`historical_bars`/`live_bars`、借用 `api`/`api_cls`) | `btapifeed.py:822–853, 1005–1013`；`btapistore.py:467–468, 477–478, 688–721` | 部分提及 | `btrun`、`research/live.py` 及数以百计的单元测试直接依赖无 `exchange_kwargs` 或借用 `api` 的构造形态；未定义替代方案将导致 SPLIT-01 大面积回归瘫痪。 |

- **评审建议**：
  - 在 SPLIT-00 强制补齐 **《9 条现存路径处置裁决表》**，逐条冻结：归 Direct、归 Gateway、迁出为独立非实盘/测试入口，还是随 SPLIT-04 彻底退役；
  - 特别要求明确：
    1. 目标 Direct 实盘是否**只保留迭代 62 `DirectWriteCoordinator` + `live_state` 路径**，将旧 `_sdk_mode & not _direct_write_mode`、`execution_config`、`ServiceExecutionSession`、`ManagedExecutionAdapter` 全部迁出或按 `D65-11` 退役；
    2. `DirectBtApiStore` 必须显式禁止 `market_runtime_factory`、`forwarding_config`、`transport_mode` 等可接入远端服务的透传键；
    3. 明确区分**生产配置入口**与**测试替身注入端口**（如受限 `direct_api_factory` / fake 端口），避免为了拒绝“未知外部客户端”而堵死 S-02/S-03 假场所测试。

---

## 三、P1 级高风险问题（影响 SPLIT-01～04 架构可行性与安全边界）

### P1-1：对 Backtrader 参数与继承机制存在技术误判（已去元类化），漏掉三类真实 MRO / `params` / `isinstance` 陷阱

- **草案问题**（§7 L92、§8 S-06 L103）：
  - 草案把拆分主要风险描述为“直接抽基类改变 Backtrader **参数元类/MRO**”，并在 S-06 要求验收“**metaclass params** 达成契约”。
- **源码实证（STATIC）**：
  - Backtrader 早已移除 `MetaParams` / `MetaBase` 元类体系（见 `AGENTS.md:107`、`backtrader/metabase.py:1–34`、`backtrader/store.py:26–27` 注释 `# Remove MetaParams import since we'll eliminate metaclass usage`）。继续按“元类风险”建模会走偏验证重点。
  - **真正潜伏在源码中、拆分时极易踩坑的三处机制**：
    1. **`Store`（`backtrader/store.py:31–75`）**：`StoreParams.__init__` 仅执行 `getattr(self.__class__, "params", ())`，**不会沿继承链合并父类 `params`**！且 `BtApiStore` 自身不定义 `params`，全部使用 `__init__` 30+ 显式形参。若新建 `BaseBtApiStore` 时采用类属性 `params`，子类定义 `params` 会静默覆盖父类定义。
    2. **`BtApiBroker`（`backtrader/broker.py:61`、`brokers/btapibroker.py:179–190, 221–253, 2213–2233`）**：继承 `(BrokerAliasMixin, ParameterizedBase)`（描述符机制，非元类），并混入 **9 个实盘 Mixin**（10 基类 MRO），通过 `params = (...) + direct_params()` 拼接参数，且 `get_strategy_position/cash/value` 依赖 `super()` 调入 `StrategyLedgerBrokerMixin`。拆分时若简单把基类上提，既容易让 Gateway Broker 意外暴露 Direct 参数（如 `waiting_orders`、`direct_facts_timeout`），又容易打断 Mixin 间的 `super()` 委派链。
    3. **`BtApiFeed`（`feeds/livefeed.py:17`、`feeds/btapifeed.py:665–758`）**：`LiveFeedBase` 继承 `(DataBase, ABC)`（含 `ABCMeta`），`BtApiFeed` 混入 `LiveBarCohortFeedMixin` 并声明 `lines = _LIVE_COHORT_EXTRA_LINES`。更关键的是，`service/gateway_config.py:410` 硬编码了 `isinstance(data, BtApiFeed)`，全仓还有多处检查 `isinstance(..., BtApiStore / BtApiBroker / BtApiFeed)`。
- **评审建议**：
  - 修正“参数元类 / metaclass params”表述，改为验证 Backtrader 现行三套真实机制（`Store` 显式构造与 `BrokerCls`/`DataCls`、`BrokerBase` 的 `ParameterizedBase`/`ParameterDescriptor`、`LiveFeedBase` 的 `DataBase`+`ParamsMixin`+`ABCMeta`+`lines`）；
  - 在 SPLIT-00 冻结兼容壳 `BtApiStore`/`BtApiFeed`/`BtApiBroker` 的 **`isinstance` 与工厂返回类型契约**（例如是否采用 `BaseBtApi*` 为抽象基类、`BtApi*` 兼容壳通过工厂/子类关系保 `isinstance`，或同步迁移所有内部 `isinstance` 到 `BaseBtApi*` 协议）。

---

### P1-2：`backtrader/live_state/` 持久状态层的双模式文件耦合未被纳入拆分设计

- **草案问题**：草案 §6.2 要求“把原模式、绑定和能力记录持久化”，§8 S-08 要求“跨模式迁移演练保留旧模式日志与未知单”，但全文未盘点 `backtrader/live_state/`（19 文件，8,772 行）的实际存储布局。
- **源码实证（STATIC）**：
  - Direct 与 Gateway 当前**共享 `<strategy_dir>/state/` 下的同一组文件名**：`identity.json`、`sequence.json`、`run.lock`、`run_status.json`、`last_run.json`，以及最关键的 **`state/pending.json`**：
    - Direct 使用 `state/pending.json` 的 **`version = 1`**（`backtrader/live_state/pending.py:87`）+ `waiting.json` + `logs/current_position.yaml`；
    - Gateway 把 intents/records/notifications/risk routing/execution routing 全部叠加写入**同一个 `state/pending.json` 的 `version = 5 / 6 / 7 / 8`**（`service/gateway_config.py:342`），并在同目录建 `state/gateway_execution_routing.sqlite`（`gateway_config.py:21`）；
    - 旧混合路由 `_configure_execution_routing` 在同目录建另一个 SQLite（`btapistore.py:1348`）。
  - 当前 `state/identity.json` 与 `pending.json v1` **没有显式的不可变 `mode: "direct" | "gateway"` 字段**；防止混用仅靠 `pending.json` 的 schema 版本号（1 vs 5–8）被动拦截。
- **评审建议**：
  - 将 `backtrader/live_state/` 明确列为 SPLIT-00/02/03 的一级改造对象：
    1. 在策略目录身份或状态头冻结不可变模式标识（`direct` vs `gateway`），杜绝跨模式误用同一策略目录；
    2. 明确历史 Gateway `pending.json v5/v6/v7`（未含 Risk/Execution 的旧目录）和旧混合 SQLite 文件在“五组件必配”新契约下的离线只读检查、隔离与拒绝/升级规则（呼应 `D63-12` 空仓迁移原则）。

---

### P1-3：Direct 与 Gateway 五大框架行为不对称未做合同盘点，难以合理设计“薄 Base”

对比 `_btapi_direct_mode.py`（6,363 行）与 `_btapi_gateway_stream.py`（2,123 行）、`btapifeed.py`、`btapibroker.py`，二者存在 5 处显著的框架语义不对称，草案 §5 均未点明：

1. **休市跨时段持久待发单（Waiting Orders，D62-30/31）**：Direct 完整支持（`_btapi_direct_mode.py:2765–2768, 3221–3227`）；Gateway 当前不支持，且硬拒绝非 `Order.Limit` 与非空 `Order.valid`（`_btapi_gateway_stream.py:564–568`，参见 `D65-03`）。拆分后 `waiting_orders` 明确限定于 Direct，还是 Gateway 另立合同？
2. **交易日历查询路径（迭代 67）**：Direct 由 Store 读取本地只读版本化日历目录；Gateway 由 `GatewayStrategyConfig.calendar_settings` 经网络向 Gateway 查询（`gateway_client_runner.py:146–154, 194–213`，`btapifeed.py:1385, 1719`），且严禁混配本地 `calendars.feed_scope`。`BaseBtApiFeed` 必须抽象统一的只读日历端口（`CalendarQueryPort`），而非在 Feed 里按 `_gateway_strategy_config` 分支。
3. **策略级资金/持仓接口（D63-41/44）**：`btapibroker.py:2213–2260` 的 `get_strategy_position` / `get_strategy_cash` / `get_strategy_value` 目前在 Gateway 下调 `GatewayBtApi` 远端接口，在非 Gateway 下调 `super()`（旧 `StrategyLedgerBrokerMixin`），与 Direct 模式未对齐。拆分时需明确 `DirectBtApiBroker` 对这三个接口的合同。
4. **优雅停止摘要词汇不统一**：见 `examples/live/007_ctp/gateway_client_runner.py:43–88`——Direct 停止输出 `STOPPED / STOPPED_WITH_WORKING_ORDERS / STOPPED_WITH_WRITE_IN_FLIGHT / UNKNOWN`，而 Gateway 停止输出 `PASS / INCOMPLETE / FAIL / OBSERVATION_ONLY + gateway_working_orders`，目前靠示例里的私有函数 `contract_broker_summary()` 翻译。**统一停止摘要合同本应是 `BaseBtApiBroker` 最有价值的共性抽象之一**，草案却遗漏了。
5. **Feed 数据获取与时钟机制差异**：Gateway Feed 显式拒绝 `backfill_start` / `historical_bars` / `live_bars` / `cohort_source_mode` / `orderbook_as_ticks`（`btapifeed.py:1027–1029`），且在无 `qcheck` 时需要 `_GATEWAY_IDLE_POLL_SECONDS` 退避（`btapifeed.py:2552–2559`）；Direct Feed 则走 Store 队列与 `StoreEventNotifier` 唤醒、支持 SDK `market_clock_verification`。应以显式 `MarketSourcePort`（订阅、拉取、恢复原因、闲置等待、时钟资格）隔离，防止 `BaseBtApiFeed` 退化成充满 `if gateway:` 的假基类。

---

### P1-4：跨仓库职责边界、反循环依赖与 Python 版本矩阵缺失

- **源码实证（STATIC）**：
  1. **依赖方向与零直接导入红线**：按 `repository-responsibilities_zh.md` 与 `TRADING_SYSTEM_ARCHITECTURE.md`，`backtrader/` **不得直接导入** `bt_api_gateway`、`bt_api_risk`、`bt_api_execution`、`bt_api_monitor`、`bt_api_runtime`、`bt_api_transport_zmq`（当前代码保持 0 直接导入）。同时 `bt_api_runtime/runtime/pyproject.toml:11` **反向依赖** `back-trader-python>=1.4.0`——若 Backtrader 任何代码去导入 `bt_api_runtime`，将直接形成跨仓循环依赖！
  2. **配置校验目前严重泄露到 `examples/`**：`examples/live/007_ctp/gateway_client_runner.py:98–191` 中有近 100 行产品级配置校验（含 `execution => risk`、`symbols/contracts` 对齐、日历作用域校验、`gateway_resource_provider` 加载），`sa_dual_ma_direct/run.py` 等 11 个 direct 示例也各复制了一份校验逻辑。如果 SPLIT-01 只在 `BtApiStore` 内部建校验，却不把策略公共/模式配置解析合同收归 `backtrader` + `bt_api_py` 产品层，校验仍会双轨漂移。
  3. **SDK 侧改造体量未被纳入计划**：草案要求 Gateway 拒绝 `risk: "none"` 与缺失 Execution/Monitor/Runtime，但这依赖 `bt_api_py` 新增严格 Gateway 配置 profile、联合预检只读快照合同、以及五组件版本协商字段。草案没有给出跨仓依赖图和既定提交顺序（`bt_api_base` → 子仓 → `bt_api_py` gitlink → `backtrader`）。
  4. **Python 版本矩阵不一致**：`backtrader` Mypy 目标 `python_version = "3.8"`（且 `btapifeed.py:869–871` 有 Python 3.8 延迟导入兼容要求）；`bt_api_runtime` 为 `>=3.9`；`bt_api_py` 发布阻塞 CI 为 `3.11–3.13`（`3.14` canary）。S-07 必须按仓库分别锁定 Python/NumPy 版本矩阵，避免新拆分代码在 BT 的低版本兼容检查或 SDK 的高版本检查中失败。

---

### P1-5：持久化故障窗口顺序颠倒，且单写者锁的作用域边界表述混同

- **草案问题**（§2 L37、§6.1 L75、§8 S-04 L101）：
  1. **持久化窗口 1 顺序写反**：草案 L37 写“特别验收两个持久化窗口：**Risk 已保留但 Execution 尚未可靠记录**，以及 provider 可能已接收但 ACK 未落盘”。但按 `D:/bt_api_py/bt_api/bt_api_execution/README.md:54–56` 的安全次序，Execution 的 `ParentAuthority` 必须**先将不可变母单持久化落盘，再调用 Risk 预留或 Gateway 注册**（否则崩溃后根本没有记录可对账）。真正必须验收的三个高危持久化窗口应修正为：
     - **窗口 W1（BT ↔ Execution/Risk 边界）**：策略 `live_state` 已持久化路由意图并外发请求，但回复丢失/策略崩溃；
     - **窗口 W2（Execution ↔ Risk 边界）**：Execution 已持久化母单/子单意图并调用 Risk `reserve`，但 Risk 已保留额度而回执未落盘到 Execution（需按原 `risk_operation_id` 查证并决定继续或释放，防止风控额度泄漏）；
     - **窗口 W3（Risk/Gateway ↔ Provider 边界）**：Gateway 已写 `DISPATCHING`（或 Risk 已 claim）并调用原生报单，但回复丢失/进程崩溃（provider 可能已受理而 ACK 未落盘 → `UNKNOWN` 阻断与原身份对账）。
  2. **单写者锁在 Direct 与 Gateway 模式下机制和边界完全不同**：
     - Direct 模式（单账户单策略，`D62-05`）：本地 `state/run.lock` 仅防**同一策略目录**双启，无法约束同账户在其他目录或其他主机登录；
     - Gateway 模式（每账户一 Gateway，`D63-02`；同账户同策略禁双活，2026-11-14 用户决定）：存在**账户级单写者**（同主机 SQLite lease / `HostAccountRegistry`，跨主机属已知边界 INV-08，`bt_api_gateway/README.md:27–34` 明确声明不防跨主机）与**策略级单写者**（Gateway 服务端租约 + 本地 `run.lock`）。
     - 草案 §6.1 将两者揉在一起，易误导 S-04 测试去期待本地锁具备跨主机隔离能力。

---

## 四、P2 级中风险问题（工程落地、并行协作与测试设计缺口）

### P2-1：非实盘只读入口定义模糊，存在误伤“实盘只读预演（`write_admission=False` / `market_data_only=True`）”的风险

- **源码实证**：迭代 62–68 的核心安全演练实践（见 `gateway_client_runner.py:80–86`、`btapibroker.py:437–443`、迭代 66/68 联合验收记录）高度依赖**在完整的 Direct 或 Gateway 实盘拓扑上关闭写入（`write_admission=False` 或 `market_data_only=True`）**来验证行情、日历、账本、风控与监控链路。
- **草案缺口**：草案 §1 L10 与 §3 L46 笼统地把“只读观察”划出实盘双模式，未区分：
  - **（A）实盘双模式的写关闭/只读演练态**（必须保留在 Direct 与 Gateway 内部，用于上线前验证）；
  - **（B）历史 `ServiceReadProxy` 与 `local_replay` 非实盘工具**（应当彻底剥离出 live Base，避免继续污染 `BaseBtApiStore` / `BaseBtApiFeed`）。
- **建议**：显式区分（A）与（B），并在配置矩阵中为 Direct/Gateway 明确列出 `write_enabled=false`（只读预演）合法形态。

### P2-2：22 个 `examples/live/007_ctp` 示例与配置模板的迁移及 CLI 契约回归未纳入分期交付

- **源码实证**：`examples/live/007_ctp/` 包含 11 个 `*_direct` + 11 个 `*_gateway` 共 22 个目录，以及 `gateway_client_runner.py`（564 行）、`gateway_local_resources.py`、`gateway_runner_lifecycle.py`。实查 `sa_dual_ma_gateway/config.yaml`（453 行）已含 `gateway_strategy.{risk, execution}` 但缺 Monitor/Runtime 声明；`sa_dual_ma_direct/config.yaml` 无显式顶层 `mode: direct` 标签；且迭代 66 的 Runtime 监督器直接绑定这 22 个 `run.py` 的 `--run-id` / `--heartbeat-interval` / `--stop-request-file` / 退出码契约。
- **建议**：在 SPLIT-01/04 明确纳入 22 个示例（至少先迁代表性样板，再批量迁移）的配置模板升级、`gateway_client_runner.py` 产品逻辑上收，以及与迭代 66 Runtime 进程合同的回归验证。

### P2-3：未与迭代 71 并行成果、代码门禁及大单体拆解条目对齐

- **现状核实**：迭代 71 `迭代计划.md:3–6, 51, 65, 157` 显示：全仓已收敛 **`ruff 0.16.2` 0 errors** 与 **`mypy` 0 errors（696 文件，分层 overrides 且无 `ignore_errors = true`）**，且第 10 批次 `R72-STR-01/02` 正是规划 `_btapi_direct_mode.py` 与 `btapistore.py` 的结构拆分边界。
- **建议**：在 SPLIT-00 明确本拆分计划承接 `R72-STR-01/02`；将 `ruff 0.16.2` 0 errors 与 `mypy` 0 errors（特别是新拆出模块的类型覆盖、禁止新增 `ignore_errors = true`）作为每一步 SPLIT 的硬门禁，并同步协调当前工作树中的迭代 71 未提交改动。

### P2-4：运行期五组件故障域策略（§9 Q2）缺乏基于既有决策的推荐冻结矩阵

草案 §9 Q2 把运行期各组件故障时的动作策略全部留白，实际上迭代 63–68 已有高度一致的安全基线，建议修订版直接列出下表供用户一次性确认/微调：

| 故障组件 | 新开仓 | 平仓 / 减仓 | 撤单 | 策略进程行为 | 既有决策依据 |
| --- | --- | --- | --- | --- | --- |
| **Gateway 不可用** | 拒绝（fail-closed） | 拒绝（无法达场所） | 不可用（需外部应急规程） | 保持运行等待重连，**严禁回退 Direct** | `D63-03`、`INV63-05` |
| **Risk 不可用** | 拒绝（`RISK_UNAVAILABLE`） | **拒绝**（不绕过 Risk） | **放行**（经策略自身 Gateway 委派撤单） | 保持运行，等待 Risk 恢复 | `D64-02`、`S-05 a` |
| **Execution 不可用** | 拒绝（不回落 Direct） | 待裁决：未入母单是否拒绝；已入场子单见右 | 已入场子单按原归属/运营 DRAIN；母单冻结转恢复 | 保持运行，母单标 `EXECUTION_RECOVERY_PENDING` | `S-07`、新双模式原则 |
| **Monitor 中断** | **拒绝**（Gateway 自主施加账户级 `STOP_NEW`） | 按账本与风控正常放行 | **放行** | 保持运行，不因 Monitor 中断强杀 | `D63-36`、`D63-43`、`S-10` |
| **Runtime 控制失联** | 不阻断已运行策略（待确认是否允许新开） | 放行 | **放行** | 已运行策略照常；无法经 Runtime 启停/代理 RESUME；急停仍可直连 Gateway 运营端口 | `D66-02`、`D66-08` |

### P2-5：SPLIT-01 与 SPLIT-04 清退时序矛盾，且 SPLIT-02/03 粒度过粗

- **矛盾点**：SPLIT-01 要求“严禁未知/混合借由默认入口启动”，而 SPLIT-04 才“移除旧混合写入口”。若 SPLIT-01 即在默认入口拒绝所有混合配置，须明确 SPLIT-01～03 期间既有混合测试（如 `_configure_execution_routing` 单测）如何处理。
- **粒度过大**：SPLIT-02 同时拆 Store（7,337+ 行）与 Feed（4,269+ 行），SPLIT-03 一次性拆 Broker（含 `btapibroker.py` + 12 个助手模块合计 25,546 行），违背 `AGENTS.md` “小轮推进、禁止一次提交同时搬迁与改语义”原则。
- **建议**：细化为小步可合入切片：
  - `SPLIT-01a`：显式配置分层、不可变模式对象与组合根工厂（新入口 100% 严检，旧壳标弃用）；
  - `SPLIT-02a`：抽取 `BaseBtApiStore` 与所有权/生命周期协议；`SPLIT-02b`：拆出 `DirectBtApiStore` 与 `GatewayBtApiStore`；`SPLIT-02c`：抽取 `MarketSourcePort`/`CalendarQueryPort` 与 `BaseBtApiFeed` / Direct / Gateway / 独立 Replay Feed；
  - `SPLIT-03a`：抽取 `BaseBtApiBroker`（公共投影、通知与统一停止摘要合同）；`SPLIT-03b`：独立装配 `DirectBtApiBroker`；`SPLIT-03c`：独立装配 `GatewayBtApiBroker`；
  - `SPLIT-04`：清退遗留混合/托管写入口、迁移 22 个示例与文档、执行全套 S-01～S-08 离线/模拟验收。

---

## 五、P3 级问题（事实误差、链接失效与措辞精度）

1. **全篇 11 处 Markdown 相对链接全部失效（疑似从子目录上移后未同步路径）**：
   - 文档当前位于 `docs/_internal/opts/requirements/迭代62 拆分计划-Backtrader 实盘 Direct 与 Gateway/需求文档.md`：
     - L4、L120：`../迭代计划.md` 不存在 → 应为 `../迭代62-问题修复/迭代计划.md`；
     - L121、L130–139：`../../迭代63-.../迭代计划.md` 等 10 处均多了一层 `../` → 应改为单层 `../迭代63-.../迭代计划.md`（直至迭代 71）；
     - L122：`../../../../../source/developer-guide/repository-responsibilities_zh.md` 与 `../../../../../TRADING_SYSTEM_ARCHITECTURE.md` 均多了一层 `../`（越出 `docs/`）→ 应改为四层 `../../../../source/...` 与 `../../../../TRADING_SYSTEM_ARCHITECTURE.md`。
2. **Backtrader 基线 HEAD 与迭代 71 状态滞后**：
   - §2 L16 应更新 Backtrader 核对 HEAD 为 `cb8493f200b05a31eef47aa8ad2217b45dff5b1c`（或明注 2026-11-22 早期快照）；
   - §11 L139 称迭代 71“保持现有 NO-GO”，而实际 `迭代71/迭代计划.md:3–6` 在 2026-11-22 已更新为 `IN_PROGRESS / REVIEW_PENDING`（207 项中 200 项勾选，16 项待验收中 11 项已 `ACCEPTED`，余 5 项 `CONDITIONAL PASS`）。
3. **对 `bt_api_runtime` 源码现状的描述失实（§2 L35）**：
   - 草案仅根据滞后的 `bt_api_runtime/README.md` 称“Runtime 初始工件描述的是 bar 观测、只读和 market_data_only”，忽略了本地源码树中已存在的 `supervision.py`、`gateway_control.py`、`events.py`、`telemetry_relay.py` 与本地 HTTP 控制接口。应如实修正为：“源码已含策略进程监督器与本地控制面（但 README/pyproject 描述滞后未更新），且联合验收仍为 NO-GO”。
4. **未提示 `ExecutionOrderRouter` 跨路径共享风险（§2 L24）**：
   - 草案点名清退 `btapistore.py:_configure_execution_routing`（Direct+Execution 混合路径），但未说明 Gateway 路径（`_btapi_gateway_stream.py:739–800`）复用同一个 SDK `ExecutionOrderRouter` 及 `_execution_parent_projection.py` / `_execution_routing_apply.py`（2,786 行），清退混合入口时必须保留 Gateway 所需合同与模块。
5. **Broker 拆分对象清单漏列 12 个私有助手模块**：
   - §2 表格仅写 `btapibroker.py`（6,675 行）并顺带提及 `_btapi_direct_mode.py`、`_btapi_gateway_stream.py`，未列明同目录下其余 10 个 `_btapi_*`/`_execution_*` 模块（合计 18,871 行），容易严重低估 SPLIT-03 工作量与 MRO 依赖。
6. **目录命名规范提示**：
   - 当前需求目录名 `迭代62 拆分计划-Backtrader 实盘 Direct 与 Gateway` 包含多处空格，与同级所有 `迭代62-问题修复`、`迭代63-...` 目录风格不统一，在命令行/脚本/CI 路径处理时易引发转义问题，建议正式立项时规范命名。

---

## 六、建议在修订前由用户一次性拍板的 8 项关键决策

| 决策号 | 议题 | 选项 | 本次评审建议 |
| --- | --- | --- | --- |
| **Q1** | Gateway 订单与风控拓扑（解决 P0-1） | A. 延续代理转发链（`Execution → Risk → Gateway`，可选直通或全量母单）；B. 改为 Execution 验 Risk 凭证后直发 Gateway | **推荐 A**；并明确普通限价单是走“Execution 透传母单”还是允许规则分流（若全量经 Execution，则明确登记变更 `D65-02/10/15`）。 |
| **Q2** | 五组件在策略进程内的接线边界（解决 P0-2） | A. 部署拓扑 5 组件全备；策略进程仅直连交易/数据服务，Monitor 由 Gateway `monitor_required` 门禁证明，Runtime 经进程监督契约证明；B. 策略进程 `GatewayBtApiStore` 强制直连全部 5 个 RPC 端口 | **推荐 A**；且确认是否保持 `D66-02`（Runtime 首期只监督策略进程，不编排 5 服务启停）。 |
| **Q3** | 遗留 `_sdk_mode & not _direct_write_mode`、`execution_config` 与 `ServiceExecutionSession` 去留（解决 P0-3） | A. Direct 仅保留迭代 62 `DirectWriteCoordinator` + `live_state` 路径，全面退役旧 SDK 本地 journal 写路径与迭代 41/60 托管路径（呼应 `D65-11`）；B. 保留旧路径在兼容壳中 | **推荐 A**（按迭代 64/65 破坏式重构原则彻底清账，避免 Direct 内部双轨并存）。 |
| **Q4** | `market_runtime_factory`（62.08 MarketHub+Direct 混合）与 `cohort_source_mode` 归属（解决 P0-3） | A. `DirectBtApiStore` 禁止 `market_runtime_factory`/`forwarding_config`；`cohort_source_mode` 明确仅归 Direct 或独立研究入口；B. 允许 Direct 挂本地 MarketHub | **推荐 A**，彻底堵死“Gateway 行情 + Direct 下单”混合后门。 |
| **Q5** | 公开 API 形态与兼容策略（对应草案 §9 Q1） | A. 公开两套具体类（`DirectBtApi*` / `GatewayBtApi*`）+ 显式工厂，旧三类作薄兼容壳直至 SPLIT-04 清退后按决策去留，明确 `isinstance(..., BaseBtApi*)` 契约；B. 永久保留旧三类动态分发 | **推荐 A**，并在 SPLIT-00 冻结 `isinstance` 兼容性与兼容壳退出条件。 |
| **Q6** | 实盘“只读预演”与独立非实盘工具区分（解决 P2-1） | A. 保留 Direct/Gateway 的 `write_admission=False` / `market_data_only=True` 只读预演态；把 `ServiceReadProxy` 与 `local_replay` 剥离为独立非实盘类；B. 将全部只读能力移出 Direct/Gateway | **推荐 A**，否则将丧失上线前同拓扑零写入干跑验证手段。 |
| **Q7** | `live_state/` 目录隔离与旧版本 `pending.json v5–v7` 处置（解决 P1-2） | A. 在 `identity.json` 或独立模式头冻结不可变 `mode` 字段；旧 `v5–v7` 目录离线只读核验且拒绝直接以五组件 Gateway 写入，须空仓迁移或显式升级；B. 仅靠 schema 版本号区分 | **推荐 A**，满足 §6.2 原模式持久化不变量。 |
| **Q8** | 运行期五组件故障域策略（对应草案 §9 Q2） | 按本报告 §四 P2-4 推荐矩阵逐项确认 | **推荐采纳 P2-4 矩阵**，仅对“Execution 不可用时平仓单处置”与“Runtime 失联时是否禁新开仓”做最终拍板。 |

---

## 七、工程推进策略建议：双轨解耦，避免互相死锁

结合当前双仓真实状态（Backtrader 迫切需要解耦 37,000+ 行实盘单体，而 `bt_api_py` 侧 Gateway 五组件真实写路径仍受困于 `gateway_api.py:869–873` `_risk_reserve` v1 UNKNOWN、`risk_parent_port.py:126–137` 子单 UNKNOWN、迭代 64 R-05 真实切点数据与 Windows B 类安全门），建议修订草案时采用**“协议先行、双轨推进、联合放行”**策略：

1. **轨道一（Backtrader 结构拆分与严格模式边界，可在离线/UNIT/FAKE/INTEGRATION_SIM 完整落地）**：
   - 在 SPLIT-00 冻结模式配置分层、9 路径处置表、`BaseBtApi*` 端口协议（`MarketSourcePort`、`CalendarQueryPort`、统一停止摘要、`live_state` 模式印记）以及 `bt_api_py` 中立只读预检契约；
   - 按小切片完成 SPLIT-01～03 的 Backtrader 侧 Direct / Gateway 拆分、混合路径清除与 22 个示例迁移，守住 `ruff 0.16.2` 0 errors 与 `mypy` 0 errors 门禁，完成 S-01 / S-02 / S-06 / S-07 及基于契约替身的 S-03 / S-04 / S-05 / S-08 验证。
2. **轨道二（`bt_api_py` 五组件真实写路径闭环，承接迭代 63–68 剩余门）**：
   - 按 `bt_api_base → 子仓 → bt_api_py gitlink` 顺序补齐 `gateway_api._risk_reserve` v2、`AtomicIntakeService` 接入 `RiskParentPort`、`child dispatch` 真实写路径、R-05 共同切点数据、Windows B 类安全原语与五组件联合健康快照；
   - 严守红线：**在轨道二完成真实五组件联合闭环前，Gateway 模式整体保持 `NO-GO / 未放行真实账户写入`**，两轨成果最终在 SPLIT-04 之后的独立联合验收阶段合龙。

---

*评审完成 — gemini-4-Neon*
