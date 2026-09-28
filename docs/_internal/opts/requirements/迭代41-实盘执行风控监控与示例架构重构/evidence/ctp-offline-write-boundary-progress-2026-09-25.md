# CTP 同文件配置与写入边界增量证据（2026-09-25）

状态：`LOCAL_OFFLINE_CONTRACTS / NO_WRITE / LIVE_NO_GO`。本文件只记录本机离线代码、fake 测试和已核对的阻断项；不包含私有配置、账号、前置原值、密码或可重放审批。所有新增模块及旧原型都不能据此成为默认 SimNow/production 报撤单入口。

**最新独立审查（2026-09-25）：** 新的 `bt_api_py` 0.15.5 parent 候选（commit `af538469`，wheel SHA-256 前缀 `cfa83b1a`）经双次相同构建和 wheel RECORD 审计，已同时包含完整 CTP 凭据绑定与 `runtime_plugins/`；此前 `81c9ee62` wheel 只含前者，是不同来源的旧候选，不应以版本号代替精确 wheel 身份。新 parent 与 v9 `bt_api_execution` wheel 在无系统虚拟环境通过 14 条 fake/replay CLI smoke，但未联通新的 CTP dispatch/callback API；当前代码 pin 表仍无 parent，旧 CTP 三件套的外置 `pip --target` 审计也不满足 verifier 的解释器安装根合同。因此正式 managed 写入制品组合尚未通过。隔离的 CTP 源队列租约和执行桥接只处理受支持 API 的单消费者顺序，不认证 Python SPI 回调来源，也不提供账户级 writer fence。桥接并发 `next_envelope`/`close` 的 P2 已在隔离提交 `e01a076bc2972443201d9fa269fdf7bc03e893d8` 修复；独立复审用真实 `TraderClient` 队列配合假原生 API 复跑后未发现剩余 P1/P2，包内 `116 passed`。关闭抢先时已出队事件不交付并要求 `UNKNOWN` 对账，但这仍不是可信原生来源或写入授权。上述候选均无默认交易入口或真实 provider 写入。

较早主仓 checkpoint 的完整 `python -m pytest -p no:asyncio tests/unit/runtime -q --tb=short` 为 `1465 passed, 24 skipped, 1 existing PytestConfigWarning`（exit 0）；六个相关 Iteration 41 integration 文件为 `7 passed, 1 existing PytestConfigWarning`（exit 0）。这些结果在当时的主仓关闭/配置/测试夹具变更后复跑，I10 隔离 SDK 后续修复不包含在内；当前完整 runtime 计数见[迭代计划首页](../迭代计划.md)。

## 用户操作合同

当前唯一受保护、Git-ignored 的 CTP 运行配置是 `examples/013_3_sa_midfreq_simnow/runtime-ctp-private/config.yaml`。SimNow 与未来生产 CTP 使用同一物理文件和 canonical `ctp:` 字段结构；未来生产阶段由操作者在**这份文件**中改 `runtime.mode`/`runtime.preset` 以及账号、认证、MD/TD 前置、合约/交易所/HedgeFlag，不建立第二份生产配置，也不按 set 名称或时间切前置。本机 `doctor` 只确认当前文件仍解析为 `simulation/sandbox`、有 5 组显式候选、只读预检可选；它不连接账户或授权下单。默认 013_3 registration 仍没有 runner、写 capability 或生产 route。生产账号/前置目前不预填；今天仅编辑配置不能启动生产交易。

独立审计确认共享 `ctp:` parser 在同一注册目录支持 `simulation/sandbox` 与 `live/managed_live_direct` 的相同字段形状；纯生产 scope binding 也读取同一路径的 sealed config，而默认 inventory 明确将 live profile 标为 unavailable。`tests/unit/runtime/test_runtime_config.py` 的两项临时文件负测复跑为 `2 passed`：同文件切换后的默认 `doctor`/`validate`/`run`/`preflight` 均在凭据、SDK 导入、网络和执行派发之前拒绝。该测试没有读取真实私有配置或 `.env`，也不证明生产交易已就绪。

## 本轮完成的离线边界

- `ctp_production_managed_composition.py` 只对精确注册的未来 live profile 和匹配的 sealed effective 放行到已有的**非授权** admission/配置候选选择；默认 unavailable profile 在凭据、SDK、网络前拒绝。51 项 fake/配置定向测试通过，不代表 production runner 已注册。
- managed MD/TD 资源关闭现在要求同代次的精确 SDK `CtpNativeStopReceipt` 明确证明 Join、Release 与线程终止；缺失、不一致或失败则保持错误、poison session 并保留账户 lease。managed readiness callback 必须接收 MD 所有权 handoff/failure hooks；迟到的 handoff 不能被接收。4 个目标文件 60 项 fake 测试与 Ruff 通过。`stop_and_wait(timeout=2)` 的超时只限 Join 观察；同步 `stop()` 可卡住，尚无受监督 worker 提供总时限。
- SDK `managed_outbox_verification.py` 增加外部 fresh verifier 与一次性 durable claim 的离线接口，精确比较当前账户/会话、审批、请求/目标、source 与绑定摘要。后验会话改变则保持已 CLAIMED 的行并拒绝重派；外部 verifier 异常不沿异常链泄露原始内容。相关 CTP 定向 25 项、execution outbox 16 项通过。仓库仍无可信 verifier、密钥/撤销源或跨 verifier 存储与 SQLite claim 的原子事务；该接口明确不授权 native dispatch。
- Store 的可派发 fake CTP adapter 在独立复核发现可被手动挂接到真实 Store 后，已从生产 `managed_execution.py` 移入测试夹具。默认 CTP placeholder 仍先于 SDK 拒绝。Store fake 定向 22 项通过，并明确暴露“投影缺失时重试会重复派发”的反例；内存 fake 不能冒充持久 at-most-once 账本。
- I9 可复现 SDK wheel 仅以无 provider 入口、无默认路由的历史构建证据/独立 latch marker 留存；其 installed-artifact pin 因误填 wheel 内嵌 `RECORD` 哈希已清空，校验入口提前拒绝。其登录同步返回和 readiness 可见性仍有已知问题，不能连接真实账户。I10 隔离 SDK 源码已冻结在 commit `a6253a58b1ebca11f58c8836fbed757d0daf7582`、版本 `2.0.3+iteration41.i10`：`ReqUserLogin` 与 `SubscribeMarketData` 严格等待原生 `int 0` 才发布登录/订阅成功；早到有效 ACK/首 tick 使用 owned scalar snapshot 延迟交付，无效回调即时 fail closed。五文件聚焦测试独立复跑 `171 passed`，Ruff/diff clean，静态独立复核未发现阻断项。双 clean-clone wheel 已复现，两个独立安装各通过 `171` 项 fake 测试；I10 受控环境 pin、受监督只读诊断及真实 MD 观察仍待完成。此提交未用于真实 provider，也不授权交易。

## 继续阻断的验收

真实 SimNow MD 登录、订阅 ACK、首 tick、TD/MD 同代次会话、结算与原生有序关闭尚未同时通过；此前真实 TD 七类查询虽有终包，部分费率 ExchangeID 为空且 native Join 未完成。没有真实 SimNow 下单、撤单、成交、重启对账证据。生产 CTP 的独立账户、审批和真实会话尚未开始验收。

写入前还需：账户级跨用户/主机 writer fence；在该 fence 下核验登录 `MaxOrderRef` 并导入旧 OrderRef 映射；唯一持久订单/撤单账本与逐动作 fresh approval 消费；原生回调持久关联、账户范围共同快照/覆盖证明和 `UNKNOWN` 不重派恢复；SDK base/CTP/parent 三制品最终 pin；受监督的 native 生命周期与完整风险/监控接线。现有 TCP 延迟选择、离线 receipt、fake 测试或 SimNow 账号权限都不能代替这些证据。

## 后续离线写入证据切片（2026-09-25）

`bt_api_execution` v8 上两个隔离、独立复审的提交已在新的 v9 组合工作树合并：native callback 字段映射与会话 epoch 绑定，以及精确 command 的只读持久投影。组合测试 `95 passed`，独立复审未发现 P1/P2。投影分别保留本地 `QUEUED/REJECTED/UNKNOWN` 回执、provider order、cancel action 和 target order 状态；本地 queue receipt 绝不当 provider ACK。导出的 callback envelope 只接受并冻结允许的原生字段，拒绝 `Password`/`StatusMsg` 等非允许字段；跨客户端重建使用新的 source epoch 防止本地计数器复用造成事件 ID 别名。它们都不接默认路由，callback/reconciliation verifier 默认拒绝。组合工作树为 `D:\bt_api_execution_codex_v9_sdk_combined_20260925`；其提交分别为 `f640817` 与 `ed40ff8`，单独已审源提交为 `2728f97165047d28c5777ba20ee1fcbda9b564e1` 与 `717689c28ea962fc924b37ab70a0efb9604bf5de`。这些哈希只标识离线源码，不是发布或生产 pin。

CTP 包的干净基线 `ce1edd60785eb4c66fefa16a994a66946a1e068f` 另有隔离源回调记录提交 `69098921025ceaba57ca4c7cdb660e97bdf94217`。独立审阅曾发现新事件暴露原生 API/SPI 对象会形成绕过写门的 P1；最终修复为仅保留不透明 source ID、标量回调快照与未绑定的 managed session/scope，排除了队列持有可调用原生对象，4 项 fake 测试通过且复审关闭 P1。该源记录还未在有原生 CTP 扩展的环境验证真实 SWIG callback，也没有受信 adapter 把登录/来源绑定到执行账户和 scope；因此不能喂给默认 verifier 作为授权证据。`OnRspOrderInsert`、`OnErrRtnOrderInsert` 与 TradeField 的统一关联仍未覆盖。

主仓的 `ctp_dispatch_read_model.py` 是纯离线、可注入的单 command reducer。13 项 fake 测试和独立复审通过；它不认证读者或 caller-supplied projection，不改变 Broker 状态，也不冻结真实账户。后续开发必须先完成受信 CTP 回调来源、逐动作审批、账户级 writer fence、持久恢复和 Broker 主线程更新，再考虑把这些候选接到受管 SimNow 报撤单；production 还需自己的准入与真实验收，但操作者仍只更新同一受保护 `config.yaml` 的 mode/preset 与 `ctp:` 参数。

**写入缺口独立复核：** 现有 `CtpSimulationAccountWriterFence` 只是注入协议和 fake；本地 `CtpAccountFlowLease` 仅协调共同使用同一主机、用户和 state root 的进程，v9 SQLite fence 只覆盖共用该数据库的写者，不能排除其他主机或直接 CTP 客户端。已核查 CTP 查询接口是分离流，尚无跨查询共同快照版本；[ADR-41-16](../ADR-41-16-simnow-f14-writer-fence-proposal.md) 的受限 SimNow 操作声明选项仍是未批准提案，不能算 F14 已通过。即使该提案将来获准，也必须明确限定为 SimNow 小额测试，不能沿用到生产。下一个开发切片依赖顺序为：取得账户级控制或正式修订 SimNow 验收合同；完成受监督 TD/MD 身份与有序关闭；冻结唯一账本的旧 OrderRef/`MaxOrderRef` 导入与 durable claim；把可信原生回调、成交、撤单和重启对账接到该账本；最后才做真实 SimNow 极小单与撤单验收。当前任何一步均不能用配置切换、TCP 可达或假回调代替。

**v9 源回调桥接的新增离线候选：** 隔离 SDK 工作树 `D:\bt_api_execution_codex_v9_trusted_source_bridge_20260925` 在 `806828a39149bb8c52d157fed5aad3ced8bad881` 增加了登录代次/来源字段到不可变 callback envelope 的非授权映射；负测要求撤单响应的 `nRequestID` 必须为原生整数，不能强制转换。包内 fake-only 全套 `111 passed`、桥接焦点 `16 passed`、变更文件 Ruff 和桥接文件 mypy 通过，独立复审无新增 P1/P2。它仍只提供结构化来源线索：调用者可以构造源事件，也可以直接调用 Python SPI callback 方法；没有原生线程/回调来源证明，不能证实来源账号等于执行账号，事件队列也没有单消费者所有权。默认 verifier 继续拒绝，主仓没有注册或消费该桥接，不得将其 envelope 当作 provider ACK、可信账户证据或写入授权。全包 mypy 尚有 12 个未改文件中的既有错误；新增桥接文件没有 mypy 错误。

**OrderRef cutover 水位离线候选：** 另一个隔离 `bt_api_execution` 工作树 `D:\bt_api_execution_codex_orderref_watermark_20260925` 在修复提交 `f56e48f7271d0a0bd5e005aed7c74dcbbfbee3bd` 将账号级水位、同会话 cutover proof 和旧映射导入置于同一个 `SqliteExecutionStore`；首次 seed 与 reservation 同事务，未 seed 不隐式从 `000...001` 分配。独立复审先复现旧 A 会话在 B 生效后重新激活的 P1；修复后 A→B→A、跨日回退均拒绝，当前 B proof 仍可幂等，复审关闭 P1且未发现新 P1/P2。包内 fake-only 全套 `102 passed`，聚焦 `65 passed`。这些 proof、原生 `MaxOrderRef` 和 legacy 源清单仍由调用方提供，尚未从真实账户或旧账本独立认证；单数据库的部署唯一性与外部账号 writer fence 也未证明。该代码无 SDK/native/provider 接线，不是 SimNow cutover 或 F14 写入验收。
