# G6-P / G8-P 外部账户控制最小服务合同与验收计划

**状态：** `DESIGN_REVIEW_ONLY / EXTERNAL_CONTROL_NOT_VERIFIED / NO_WRITE / LIVE_NO_GO`。
这份记录是源码边界审计和后续验收计划，不是服务实现、F14 证明、审批或
route 准入。没有读取私有配置、凭据或账户数据，没有连接 CTP/provider，
没有启用默认 route。当前验收状态仍以
[CTP 当前验收矩阵](../ctp-current-acceptance-matrix.md)为准。

## 审计结论

G6-P 需要的不只是一个会返回 `True` 的外部授权函数。唯一可验证的最小架构
是由受信账户服务拥有每个账户的唯一写入入口和 CTP 凭据，接收已封存的动作，
在服务端持有账户 fence、校验同一版本的账户状态，并在同一服务的串行写入边界
内执行 provider 调用。若服务仅签发 lease/token，而 Backtrader 进程仍持有
可直接连接 CTP 的凭据，那么 lease 校验到 `ReqOrderInsert`/`ReqOrderAction`
之间仍存在竞态，旧 writer 可以绕过撤销；这不足以证明 G6-P。

当前代码给出了可复用的数据合同和 Router 边界，但没有受信外部服务、身份信任
根、服务端写入执行边界或账户快照源。由此不能证明跨主机 epoch 排他、撤销/接管、
dispatch 最终栅栏或资金/全账户委托/成交/持仓同版本快照。G6-P 保持阻断；G8-P
只能在合成配置上验证同文件、同 runner 的模式切换和旧授权失效，不因此开放
production。

## 当前候选的复用点与能力缺口

| 候选 | 可复用 | 未证明 / 不得推断 |
| --- | --- | --- |
| `backtrader_runtime/ctp_f14_external_admission.py` | `CtpF14ActionRequest` 绑定 runtime、mode/preset、账号指纹、配置/effective/registration/artifact 摘要、session/trading day/connection generation、动作/审批和撤单目标。`CtpF14ExternalAdmissionClaim` 要求账户排他、四类快照覆盖，并绑定 account fingerprint 与 fence id/epoch。 | `Protocol` 没有实现或固定信任根。`authority_receipt_digest` 只是 64 位十六进制格式，没有验签。Claim 中的 `snapshot_version` 只是非空 ID，服务端没有可验证签名或类别版本明细。`claim_f14_action()` 调 `claim_and_verify()` 后，`CtpF14ActionAdmission.assert_active()` 只是另一次远程检查；它与随后本机 native call 不原子，因此有 TOCTOU。请求还没有已接通的唯一 OrderRef/账本 handoff。 |
| `backtrader_runtime/ctp_f14_signed_receipt_contract.py`（2026-09-26 offline candidate） | Adds a versioned canonical receipt wire contract with issuer/key/audience pin injection, a local genuine Ed25519 verifier using injected public keys and SHA-256 pins, exact request/account/scope/action binding, same-version four-collection coverage, pagination flags, fence epoch and a bounded TTL. An optional host-local SQLite observation fence rejects local replay across restarts and processes. | This is an offline observation contract only: it has no service client, trusted deployment pin, durable cross-host replay ledger or admission handle. The local database does not prove cross-host replay exclusion or monotonic service epochs; its production ACL/owner is unverified. Signed assertions cannot prove account-writer exclusivity or snapshot truth; no executor/native dispatch path is exposed. |
| `tests/unit/runtime/test_ctp_f14_external_admission.py` | 合成 authority 覆盖精确 request binding、覆盖项缺失、账号/session/epoch 不一致、异常脱敏和 `assert_active() is True` 的严格布尔合同。 | 测试中的 `_FakeAuthority` 自己构造所有 claim 字段；它只验证本地类型边界，不验证签名、TLS identity、跨主机互斥、真实快照来源、最终 dispatch 或旁路拒绝。 |
| `D:\bt_api_py\bt_api\bt_api_gateway\src\bt_api_gateway\router.py` 与 `writer_authority.py` | `GatewayCommandRouter.dispatch()` 先做 principal scope/kind 检查；写命令要求 admission 返回字面 `True`，再经 SQLite writer authority 的 claim 和 `begin_action_dispatch()` 最终 epoch/lease 校验后调用唯一 executor。可复用为服务内的命令账本/路由层。 | `GatewayAccountWriterAuthority` 是同一 SQLite 文件协调的本地 writer lease/action journal。它无法约束不参与该 SQLite 协议的另一主机、用户、人工客户端或直接 CTP SDK；它不是账户服务、共同快照或券商端 fencing token。Router 当前也没有把外部快照与 native dispatch 包在一个服务端 fence 内的能力。 |
| `D:\bt_api_py\bt_api\bt_api_transport_zmq\src\bt_api_transport_zmq\server.py` | 远端 TCP 要求 CurveZMQ、ZAP peer 身份和静态 `RemotePrincipalGrant` ACL；从 payload frame `User-Id` 查 grant，限制外层 strategy scope、kind 及出现的 account/strategy identity claims。 | 静态 key→grant ACL 不是 account writer epoch，也没有外部服务撤销/接管协议或账户状态来源；它不能证明只有此服务可访问该 CTP 账号。单靠 `CURVE/ZAP` 不能授权 provider 写入或证明账户全量状态。 |
| `D:\bt_api_py\bt_api_py\runtime_plugins\gateway_transport_server.py`（parent 本地候选） | 在 transport handler 前将 ACL grant 显式映射为 `GatewayPrincipal`，调用 gateway canonical decoder 检查 `bt_api_gateway.command.v1` 和 fingerprint，再校验 scope/kind 后交给 server authority。真实本地 Curve/ZAP TCP fake 可验证桥接次序。 | 该 adapter 仍委托当前 local Router/authority。合成 writer lease、fake admission 或 fake provider 不能证明 G6-P；transport 回执也不能等同 provider acknowledgement。 |
| `D:\bt_api_py\bt_api_py\runtime_plugins\gateway_dispatch.py`（parent 本地候选） | `GatewayExecutionAuthority` 已把 managed command 转成 server runtime 的动作并调用 Router；writer authority 是显式可选注入，缺省为 `None`，不改变 fail-closed。 | 本地 candidate 的可选 writer authority seam 没有部署的跨主机 authority。正例可证明本地配线；`RETURNED_UNVERIFIED` 仍不能升级为 provider terminal evidence。父仓 Store/Broker 到唯一 CTP OrderRef/worker authority 的 handoff 仍有矩阵列出的缺口。 |

上述 `bt_api_py` 文件是当前本地候选工作树路径，未据此声称该实现已发布、安装到生产或经独立真实环境验收。

**离线 receipt-contract slice（2026-09-26）：** 新增的
`ctp_f14_signed_receipt_contract.py` 只验证 canonical envelope、注入的 issuer/key/audience
pin、精确 request/action/account/scope 绑定、fence 与 snapshot epoch、四集合共同版本和分页
完整标记、签名输入及 TTL。它输出 `CtpF14ReceiptContractObservation`，没有 `admitted=True`、
`CtpF14ActionAdmission` 工厂、`CtpF14ExternalAdmissionAuthority` 实现或 executor 接口；
除 fake 签名测试外，真实 Ed25519 测试使用临时密钥验证实现；代码不附带受信生产服务 pin。
进程内 replay/high-water cache 不持久；显式注入的本机 SQLite observation fence 可跨重启和
本机进程拒绝重放，但目录 ACL/owner 未验收，也不能充当跨主机 server dedupe/fence。验签只证明
注入 verifier 接受这些字节，不证明 issuer 实际清点/阻断所有 writer，也不证明共同快照来源
真实。此 slice 不改变 G6-P `BLOCKED / LIVE_NO_GO`、G8-P `NOT_RUN / LIVE_NO_GO` 或默认
`NO_WRITE`；真实闭环仍要求唯一 credentials/session 的外部 account actor 在同一服务端线性化
边界复查 epoch 后执行 provider 调用。该 slice 的 focused fake 与临时 Ed25519 密钥测试为
`25 passed`，兼容 venv 中根代理独立复跑同数且无 warning；另一环境有一条现存 pytest 配置警告；目标文件 Ruff 检查通过。超大整数时钟/TTL/签名时间现在统一脱敏拒绝，测试没有访问私有配置、
真实账户、provider、网络或 SDK。

## 最小受信服务接口

接口应由固定、版本化的 server API 暴露；调用者身份、服务端信任根、canonical
序列化和签名算法必须由代码/部署策略固定，不得由 config、策略 payload 或
调用方提供的 `authority_id` 决定。

### 1. 服务与账户绑定

每个 grant 必须绑定：

- 服务端 canonical provider/account identity 与 `account_fingerprint_sha256`；
- 唯一 environment、mode/preset、runtime/runner identity、strategy scope；
- 服务端分配的主机/进程身份、批准的 provider session 代次；
- 允许的动作种类和受限风险范围；
- 客户端证书 principal、受信服务端证书/签名 key id 与 audience。

账号、订单账本与审批字段不接受客户端自行映射。服务必须清点并控制该账户的
全部写入者：其他主机、OS 用户、人工终端和旧 SDK 进程要么经同一服务路由，
要么被 provider 权限、证书撤销、独立网络 egress policy 或可审计等效机制阻断。
若无法清点或技术上无法阻断旁路写者，应明确标为未证明，不得设
`account_writer_exclusive=true`。

### 2. 单调账户 fence / epoch

建议合同的最小操作：

```text
AcquireAccountFence(account_binding, owner_identity, expected_epoch?)
  -> SignedFenceLease(fence_id, monotonic_epoch, owner, scope_digest,
                      issued_at, expires_at, authority_id, key_id)
RenewAccountFence(lease, expected_epoch) -> SignedFenceLease
RevokeOrTransfer(lease, expected_epoch, quiescence_evidence)
  -> new monotonic epoch, or a redacted blocked/unknown disposition
```

账户状态必须在受信服务端持久化，epoch 在重启后不得回退/复用。取得新 epoch
要原子地撤销旧 epoch。服务只有在旧 dispatch 确认尚未开始，或旧动作已得到可验证
终态且 native owner/worker 已静止时才能交接。若旧 action `DISPATCHING`/`UNKNOWN`、
native Join pending、断线造成结果不明或回调未对账，必须保持账户冻结；lease
超时不能自动放行新 writer。续租、撤销和动作认领要使用 compare-and-swap epoch，
拒绝旧 token、重放 request、过期 claim 和重复 action id。

### 3. 同版本完整账户快照与逐动作认领

```text
ClaimActionAndSnapshot(current_lease, exact_CtpF14ActionRequest)
  -> SignedActionClaim(
       one_use_claim_id, request_digest, fence_id, fence_epoch,
       snapshot_id, snapshot_version, snapshot_digest,
       coverage_digest, per_collection_counts/cursor_completion,
       account_fingerprint, trading_day, session_generation,
       issued_at, expires_at, authority_id, key_id, signature)
```

四个必需集合必须都来自同一服务端权威 revision：
`account_funds`、**全账户** `open_orders`、`trades`、`positions`。每个集合应带相同
`snapshot_version`/provider watermark、准确账户与 TradingDay、complete pagination
标记、行数、确定性摘要和来源。委托集合必须包含外部/人工客户端、撤单/拒绝/部分成交
等有风险意义的未结状态；不能只查询本策略订单。资金、成交、持仓和委托应能用数量/
资金不变量复核。缺页、重复页、版本不一致、账户/交易日不一致、来源不明或数据过期
时拒绝 claim。

若供应商只提供独立异步 CTP 查询，不能把各自 `bIsLast`/请求终包拼成共同快照。
替代实现必须由唯一 writer 服务持有完整、可监测丢失/重复的账户事件账本，并用可信
provider watermark/结算版本证明其已追平；否则快照能力仍未满足 G6-P。

### 4. 与最后 native dispatch 同一服务端线性化

```text
DispatchClaimedAction(signed_claim, exact_immutable_command)
  -> durable DispatchReceipt(action_id, claim_id, fence_epoch,
                             command_digest, native_request_ids,
                             disposition, callback/evidence references,
                             issued_at, authority signature)
ReconcileAction(action_id, exact_account/session binding)
  -> signed terminal/provider evidence or UNKNOWN/frozen
```

`DispatchClaimedAction` 必须在执行 provider 调用的同一服务/串行账户 actor 内重新
核对当前 epoch、撤销状态、claim 是否首次消费、动作摘要、审批摘要、账户快照版本、
session 代次、风险剩余额度和有效期，然后将唯一 action 从 `CLAIMED` 原子改为
`DISPATCHING` 并进入唯一 native worker。旧 writer 即使保留旧对象也必须在服务端拒绝；
不能返回 bearer lease 给 CTP 本地进程自行调用 `ReqOrderInsert`/`ReqOrderAction`。
这是关闭 `assert_active()`→native-call TOCTOU 的关键。

网络或进程在 claim 后的任一不确定切点须持久化为 `UNKNOWN` 并冻结 action/账户；不能
将 timeout、裸 `REJECTED` 或 transport `accepted` 当作“未发送”。只有服务端能证明
provider 未收到请求时，才能记录一个明确的无发送终态。原始 provider callback/response
还需经请求 ID、OrderRef/ActionRef、session generation 和确切目标关联，并在外部
reconciliation 前继续保持 `RETURNED_UNVERIFIED`/`UNKNOWN`。

## 签名、信任根与撤销要求

- 服务到 runtime 使用双向认证（如受信 mTLS），限定证书用途、服务 identity、audience、
  account principal 和服务版本；证书链/公钥 hash 由 code-owned deployment pin 验证。
- 返回 claim、snapshot attestation、fence/epoch 与 dispatch receipt 的**完整 canonical
  bytes** 必须带签名（或审查认可的等效消息认证），不是只带 `authority_receipt_digest`
  字符串。验签先于 DTO 构造/Router admission；算法、key id、key rollover 与紧急撤销
  策略明确且有离线验签证据。
- 每次请求使用 nonce、单调 request/action id、精确 request digest、scope digest、
  epoch、issued/expiry 和 audience；服务端 durable dedupe 防止网络重放/多副本竞争。
- `expires_at` 必须由受信时钟解释。过期、未来签发时间、未知服务/key、签名不符、
  audience 不符、revoked key、epoch 回退、服务端时钟不确定都 fail closed。
- HMAC/hash、客户端证书名、ZAP grant 或 scope label 各自都不证明账户 writer 排他、
  snapshot truth 或 provider 终态；需要逐层匹配 trust root 与实际服务部署。

## G6-P 端到端验收计划

### A. 离线合同/适配器测试

在代码集成前，先使用受控 fake authority 固化协议边界，不给默认 inventory/CLI 增写入：

1. 正例：精确 request、签名 key pin、account/strategy/runtime/mode/config/artifact/session/
   action/approval/target 全绑定；四类集合使用同一 snapshot version/fence/epoch；最终
   `DispatchClaimedAction` 只进入 provider fake 一次并返回 `RETURNED_UNVERIFIED`，独立
   reconciliation 才能产出终态。
2. 逐字段篡改：账户、scope、strategy、provider/env/mode/preset、config/effective/
   registration/artifact digest、TradingDay/session/connection generation、action id/
   digest、approval、撤单 target、epoch、snapshot id/version/digest、receipt 字节。
   每种都必须在 provider fake 前拒绝，调用计数 0。
3. 签名/身份：坏签名、未知/revoked key、错误服务 audience、证书 principal 不匹配、
   nonce/action 重放、过期/未来、时钟故障、未知 schema 都拒绝；错误 detail 不泄露
   credential 或原始 provider 错误。
4. 快照完整性：缺 funds/open orders/trades/positions 任一项；只给本策略委托；分页未完、
   重复或遗漏；四集合版本不同；snapshot account/TradingDay/fence 不一致；虚报
   `complete/consistent=true` 但签名来源缺失；结算/数据源 watermark 落后。全部拒绝。
5. 隔离旧协议：只含单独 CTP query 的终包、反复相同读数、`bIsLast`、本机 SQLite lease、
   ZAP grant、client `authority_receipt_digest`、fake `assert_active=True`，都不能组成
   G6-P 正例。

### B. 跨主机并发/最后 dispatch 栅栏

使用两个真实隔离 VM/host identity（不是两个线程或一个进程的两个 fake client），对同一
外部账户服务跑可复现 barrier 测试，并留服务端审计证据：

1. 同时 Acquire：只有一个 owner 得当前 epoch；另一 owner 明确拒绝。重启服务后 epoch
   单调递增且旧 epoch 不可用。
2. 过期/撤销/转移：A 持有 epoch E，服务撤销 E 并授予 B epoch E+1；A 随后使用旧 claim
   与新 action 均被服务端最终 dispatch fence 拒绝。只断开客户端、删本地 lease 文件或
   本机 lock 不算撤销证据。
3. 最后检查 race：暂停 A 在 claim/snapshot 后、进入 `DispatchClaimedAction` 前；使 B
   接管成功后恢复 A；A native dispatch 计数必须仍为 0。反向地，若 A 已进入
   `DISPATCHING`，撤销/转移不得让 B 同时 dispatch；服务必须等到已证明终态，或保持
   UNKNOWN/frozen。
4. Snapshot race：在同版本快照后、动作 final fence 前，通过第二合法 writer、外部人工
   订单或源状态变化增加/修改订单、成交、资金或持仓；服务应比较 provider watermark/版本，
   拒绝旧 snapshot claim，或在一个原子服务端事务中按该 revision 冻结风险额度。不得仅
   因 runtime 再调用一次 `assert_active()` 放行。
5. 网络和 crash：注入 claim 前、claim 后/dispatch 前、native send 后/ACK 前、callback
   后/账本落盘前的断线与强杀。重启/接管后无自动重派；所有可能已发请求按 exact ID
   reconciliation；未知动作冻结，不释放 epoch。

### C. 旁路和身份授权测试

1. 另一个 host、OS user、过期 key、撤销证书、已降权 ZAP principal、旧 epoch 进程及手工
   CTP client 尝试直连 provider 或 gateway：服务端 ACL/账户控制应拒绝，provider write
   计数为 0。不能只断言 Python handler 未被调用；需 provider/网关、OS 权限和 egress
   网络的独立拒绝日志。
2. 策略提供伪造 principal、账户 scope、account id、strategy id、allowed kind、审批/epoch；
   server 必须从认证服务返回值重建 principal 并拒绝不匹配 claims。新旧/另一个账户/另一个
   策略间 principal 与 config seal 不能混用。
3. raw ZeroMQ `WireMessage` 绕开 Backtrader，错误 gateway schema/fingerprint、scope 或
   kind；必须停在严格 decoder/ACL 之前，不能仅依赖 client 检查。
4. 用真实隔离账号服务/网络策略证明其他 CTP credentials、旧网关版本、第二 Store worker、
   两个 server 实例不能在服务外 dispatch。同一 SQLite 路径上的本机 fake writer 只覆盖
   cooperative local processes，不替代此测试。

### D. 正向受限验收证据

只有外部服务契约、身份 pin、账户 writer 清单、snapshot source、旁路拒绝、G0–G5、原生
session/close 与审批风控均独立审核之后，才能申请具名受控账户的一次正向测试。证据包至少
含脱敏版本：外部服务 build/revision 与 signer key id、service identity、账户 fingerprint、
fence id/epoch/owner/有效期、action/request digest、同版本 snapshot 的来源/version/coverage/
count/cursor/digest、dispatch claim 和实际 callback/查询对应的 request/OrderRef/ActionRef、
session generation、最终对账结果、唯一 writer/bypass 观察、测试环境及 trusted UTC。
原文 secret/账号不能进入日志；QA 应能用预先 pin 的 public key 离线验证 claim/receipt
签名和摘要，且可由服务端审计记录核对 epoch 没有重叠。

如果 broker/CTP 没有同版本资金、全账户委托、成交、持仓 snapshot API，服务方必须展示
其权威事件账本的 watermark、事件缺口检测、全部 pagination/source 纳入规则，以及对人工/
其他用户写入的技术排除。若无法证明，G6-P 继续 `BLOCKED / LIVE_NO_GO`；本地独立查询
收据不能升级为共同快照。

## G8-P 同文件模式切换的合成验收计划

只在临时目录、合成 YAML、占位 credentials/fronts、fake providers 上验证，不读取默认私有
配置，不加载真实 SDK，不开真实 socket：

1. 从一个 canonical `config.yaml` 和固定 `runtime_id`/runner identity 开始 sandbox profile，
   使用 fake session 并记录其 mode/preset、config/effective/registration/artifact digest、
   session generation、approval scope 与 order ledger scope。
2. 明确关闭旧 fake session 后只修改同一文件的 mode/preset、合成账户认证引用、前置与
   合约；以同一 runtime/runner identity 重新解析 live profile。证明 config path、runtime
   identity 和 runner implementation 不变，但 profile/effective/config/account/session/
   approval/fence/ledger scopes 都按 production 值重新封存。
3. 旧 SimNow action permit、external claim、session receipt、writer epoch、approval、OrderRef/
   action mapping/cached principal 逐一拿去 production 请求；每项均在 credential resolver、
   SDK import/client factory/socket/native submit/cancel 前拒绝，调用计数全为 0。
4. 活动 session 中途编辑配置必须拒绝热切换；`mode/preset` 不匹配、缺字段、seal 变化、旧
   registration 或 profile unavailable 也都在敏感依赖前 fail closed。
5. 该测试只能说明 parser/shared runner identity/旧授权隔离合同可测。当前没有 G6-P 服务、
   production runner authority、统一订单账本或真实 production artifacts 时，不得把合成 live
   profile 通过称为 G8-P PASS 或运行实盘成功；matrix 仍 `NOT_RUN / LIVE_NO_GO`。

## 决策与可实施顺序

1. 先让服务/券商提供方书面确认唯一写入路径、跨主机 fence/revocation、外部账户状态 revision
   及签名认证合同；若没有这些原语，停止 strict F14/production 写入口设计。
2. 将受信服务作为唯一 account actor：让唯一执行 gateway 保持 provider credential/session，
   将 client transport 只接到 gateway，不把 CTP credential/native object 下发；部署网络和
   OS policy 拒绝直接旁路。完成离线 DTO/验签测试后，才在隔离环境验证跨主机竞争和 snapshot。
3. 将 `CtpF14ActionRequest` 绑定到同一可信 `OrderRef`/action ledger，设计服务端
   `ClaimActionAndSnapshot → DispatchClaimedAction → ReconcileAction` 的持久状态机；由
   authority 在其实际 provider 调用边界原子核对 epoch，避免把 Python `assert_active()`
   当作 native dispatch fence。
4. 完成 G6-P 服务合同及外部旁路证据后，才用 G8-P 合成同文件切换证明解析/失效隔离；再单独
   申请 production artifacts/session/risk/monitor/approval/恢复验收。任一依赖不具备时保持默认
   route 不可用。

## 仍需独立确认的外部证据

- 受信 account-control 服务/券商的正式合同、安装部署来源、source/build 摘要、运营 owner 和
  独立审计范围；真实 service/client trust root、身份签发/轮换/撤销流程。
- provider 账户能否拒绝同账户另一主机/人工/旧 credential 发起写入；如不能，服务如何观测并
  阻止这些动作，以及无法观察的风险如何明示。
- 真正的共同账户 snapshot version 来源；它是否覆盖全账户/外部订单和全分页，如何证明资金、
  委托、成交、持仓在同一 revision 和同一 fence epoch。
- 权威时间、服务断连、provider 超时、进程隔离与 takeover 的可观察规则；unknown 时账户何时
  能解冻、什么 provider/reconciliation 证据足够。
- 绑定实际父 runtime、sealed config、approved artifacts、SDK build、Store/Broker、OrderRef
  ledger、session generation、writer service、风险审批与监控的端到端正负证据。

取得并独立验收这些证据前，G6-P 与 production 仍为 `BLOCKED / LIVE_NO_GO`；不能从本地
SQLite lease、synthetic remote principal、fake snapshot、TCP reachability、ZAP、Router unit
test、SimNow S receipt 或同文件 parser test 推出真实账户排他/共同快照/production PASS。
