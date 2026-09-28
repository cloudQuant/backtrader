# CTP 同配置共享 runner：开发与验收合同

状态：`DESIGN_TARGET / SHARED_WRITE_RUNNER_NOT_REGISTERED / NO_WRITE / LIVE_NO_GO`（2026-09-26）。本页落实“SimNow 跑通后修改同一 `config.yaml` 即可请求生产运行”的操作目标；它不把当前离线配置解析误写成真实报撤单能力。

**最新局部实现：** 未登记的 `ctp_mode_scope.py` 在合成配置中验证两种 profile 使用同一 code-owned runner identity，并从同一 canonical `ctp:` 文件绑定不同 mode/receipt/account/front/contract scope；其结果固定为零权限。合成 `receipt_required` SimNow profile 已能通过 profile-aware session admission 调用注入的 fake native factory，报撤单前会重封配置。默认 013_3 仍为 `deny`、无 runner，live unavailable；最后一次重封到原生调用的并发改配置窗口仍是 P2，且真实 MD/TD 会话、Join、账户级 fence、可信审批等未验收。详见[离线证据](evidence/ctp-shared-mode-profile-offline-2026-09-25.md)。下文“代码缺口”中的 profile-aware admission 指正式受审的默认写入接线，不把这个 fake 切片视为完成。

## 操作者合同

唯一受保护文件为 `examples/013_3_sa_midfreq_simnow/runtime-ctp-private/config.yaml`。`simulation/sandbox` 与 `live/managed_live_direct` 使用相同 canonical `ctp:` 字段：`md_front`/`td_front` 或有序 `front_pairs`、`instrument_id`、`exchange_id`、`hedge_flag`、`broker_id`、`user_id`、`password`、`app_id`、`auth_code`。未来生产切换只编辑**该文件**的 `runtime.mode/preset` 与这些账号、认证、前置和合约参数，沿用同一 CLI、同一 runtime identity 和同一个受管 CTP runner；不创建生产专用配置或 runner。切换按停止旧 session/runner、编辑该文件、以同一 runtime identity 和 runner 实现重新启动新 session 的顺序进行；不支持在活动 session 内热切换 profile。前置仅按配置的完整 MD/TD pair 做有界无凭据测速：当前三次采样要求每端至少 2/3 成功，比较两端成功样本中位延迟的较大值，最低者胜、平分按配置顺序；规则和传输证据见[当前验收矩阵](ctp-current-acceptance-matrix.md)。原生登录失败不得重新选 pair，也不按 set 名称、时段或端点形状推断环境。配置文件不得包含审批开关、能力开关或风险上限放宽值。

不同模式必须重新通过各自的账户、制品、会话、审批、风险、监控与 F14 准入。旧 SimNow 的 approval、receipt、session、scope、候选 pair 选择和账号账本证明不得继承至生产。配置编辑不热切换当前 session；若活动期间文件发生变化，旧 seal/approval 必须失效并阻断动作，随后须按停止、编辑、重新启动的流程重新准入。一次 session 固定一个选定 pair，原生登录失败不得重新选前置。`--confirm-live` 只能确认当前已配置且已获批的 live 合同，不能切换 mode 或补足缺失准入。

## 代码缺口与开发顺序

1. `config.py` 已用同一 canonical `ctp:` 解析两种 mode；`test_runtime_config.py` 已证明同一路径改 mode/account/front/contract 后产生不同 seal，默认 live 在 dispatch 前拒绝。保留这条边界和旧 `ctp_production:` 的迁移兼容测试，但不把旧 `runtime-production/` 接入 operator flow。
2. 默认 013_3 inventory 目前只登记 zero-write sandbox profile，live 明确 unavailable，且无 runner/capabilities。实现一个 **mode-aware 受管 CTP runner 模块**，使同一 runtime registration 中两个经审查的 profile 指向该模块；CLI/runner 必须从 sealed profile 派发，不允许 CLI、环境变量、endpoint 或策略代码选 mode。当前 `examples/013_3_sa_midfreq_simnow/run_runtime.py` 是 replay runner，不能直接当成 CTP 写入入口。
3. 共享 runner 内保留两个强类型准入 adapter：sandbox 使用 SimNow 账号/会话/写策略，live 使用生产账号/制品/审批/风控/账户 fence。底层行情、TraderClient、Store/Broker、命令账本、回调投影与资源关闭复用同一实现；不能复制一套 production runner。现有 `ctp_simnow_managed_runtime.py` 只建立未注册 session，生产 selector 只产生非授权 scope，两者都还不是可派发的 Backtrader 策略 runner。
4. 实现 profile-aware SimNow admission、生产 live dispatch 与受管 Store/Broker 桥接；保持每模式不同的 approval 类型、签名域、key 与有效期。每个动作绑定当前 registration/profile、config/effective digest、账号、合约、候选集、选定 pair、session generation 和目标订单。`QUEUED` 不得当作 provider ACK，`UNKNOWN` 冻结并禁止重派。
5. 完成 CTP SDK/base/parent/execution 受审制品来源、原生生命周期有界监督、可信回调来源、OrderRef 唯一账本 cutover、逐动作审批、风险与监控。生产与严格 F14 另须账户级 writer fence 和共同快照（G6-P）；未通过时 live 保持 fail closed。SimNow 有界操作性分支须先批准 [ADR-41-16 option B](ADR-41-16-simnow-f14-writer-fence-proposal.md)，再完成 G6-S/G7-S 的独立准入和验收，且只能报告账户级排他/共同快照未证实的限定结果。该分支当前未批准、未接线，默认 SimNow 写入仍关闭；不得仅为测试把未注册候选接进默认 route。
6. G5 接线必须证明 Store、SDK 与唯一 worker 访问同一受信 I9 持久账本，而非仅靠可伪造的 Python `Protocol`/属性形状。SDK 的旧本地时间型 CTP OrderRef allocator、Feed 缺 Ref fallback 与 Gateway 重分配在 managed 路径全部拒绝；精确 12 位 OrderRef 要同一账本的 intent/runtime identity、`OrderRequest`、原生请求和持久 command 行逐字段绑定。只读 reservation 镜像或进程内路由 marker 均不得充当 authority。部署前还须决定 CTP managed 运行环境是否固定为 Python 3.11+，或提供与项目 Python 3.8–3.13 支持范围兼容且独立验收的 I9 实现；隔离 I9 候选当前声明 Python 3.11+。
7. 撤单目标必须由受信 CTP 查询验证器针对当前账号、交易日、合约、连接代次和 I9 预留的 `OrderRef` 签发，不能取自策略、调用方 DTO、旧 callback 或本地 outbox 回显。验证器只接受终态完整查询中唯一且仍有可撤余量的订单，并把原生查询请求/过滤条件、结果摘要、准确的 `OrderSysID`、`ExchangeID`、`FrontID`、`SessionID` 与签发代次绑定；I9 在同一账本持久化该来源并回读核对后才允许构造撤单 command，approval、入队和 worker claim 也须绑定来源摘要及短有效期。重启后新的撤单重新查询；旧的 OPEN 投影只供审计。查询结果不是同版本账户快照，不能由此宣称撤单必成功。当前 I9 与 CTP 候选没有这条 issuer→持久化→回读链，撤单继续在 staging 前拒绝。

## QA 必测矩阵

| 场景 | 预期 |
| --- | --- |
| 同一路径重启切换：先停止 SimNow session，再只编辑受保护配置的 mode/preset 与合成 `ctp:` 值，随后以同一 runtime identity 和同一 runner 实现重新启动 synthetic live session | source path、runtime identity 与 runner implementation identity 不变；新 session generation/seal/scope 改变，旧 SimNow approval/receipt 不可复用；无需第二配置或生产专用 runner。默认 inventory 仍在凭据/SDK/socket/写入前拒绝 live。运行中改文件不得被解释为热切换。 |
| mode/preset 不匹配、旧 receipt、旧账号/候选/合约/选定 pair 或 SimNow approval 用于 live | 精确拒绝，凭据解析、SDK import、client factory、submit/cancel 均为 0。 |
| 报单/撤单最后一次配置核验与原生调用并发发生配置写入、替换、目录 rename 或 reparse 改向 | 已有本机负测证明：仅持有 Windows 文件共享租约时，另一个 `FILE_WRITE_ATTRIBUTES` 句柄仍可给配置文件设置 reparse tag，因而该租约不能把最后重封与原生调用线性化。未来需可信执行边界同时独占配置及路径变更、重验配置代次/动作范围、在同一 fence 内执行唯一原生动作；仅返回可由调用方持有的 grant 也不充分。未有这样的受审实现前，写入准入保持关闭；实现仍应允许同卷无关目录正常写入。 |
| 两模式未来各自使用 fake provider | 同一共享 runner 分派到正确的强类型 admission；live 只接受 production 凭据/审批/risk/fence，sandbox 只接受 SimNow 准入，互不降级或回退到 legacy writer。 |
| 前置 TCP 可达但原生 login、query、callback、native close 任一不确定 | 不换 pair、不继续下单；写入为 0 或动作 `UNKNOWN` 冻结，并留脱敏证据。 |
| `doctor`/`validate` 与 `run --confirm-live` | 前两者离线且不加载 SDK；后者只在 live 已登记、已获批且所有门通过时进入同一 runner，否则拒绝。 |
| 同一策略经 `BtApiBroker → BtApiStore` 报单、撤单、部分成交、重启 | 唯一持久 intent/order/action/OrderRef，原生回调与查询同源匹配；本地入队不合成成交/撤单终态，未知结果不重派。 |
| 假 I9 port、伪造 reservation 类型/来源、另一个 SQLite store 或第二 worker 试图接线 | 在真实 write admission 前拒绝；fake 结构兼容测试不得被计作同一权威账本或单 worker 的正面证据。 |
| 已镜像 OrderRef 但 `OrderRequest` 的 intent/runtime scope 不匹配，或 managed Feed/Gateway 试图自行分配、覆盖、补齐 Ref | 在请求 ID、队列发布和原生调用前拒绝；旧 allocator 计数与 native write 计数均为 0，原镜像不授予派单权。 |
| 调用方给齐撤单目标、旧 OPEN 投影、重复/终态订单、查询过滤范围或代次不符、issuer 收据过期/篡改/跨账号复用 | 在 I9 staging、queue receipt、worker 和 native action 前拒绝；只有当前查询验证器签发、同一 I9 账本持久化并回读的精确目标可进入下一门，且不得把该查询当 provider ACK 或账户共同快照。 |
| CTP 转发端收到精确 CTP、空白/Unicode 别名、其他 venue 或直接构造的 `OrderCommand`，以及账号与服务端 scope 不匹配 | 仅客户端拒绝不算通过；服务端必须在 adapter/native 前按代码绑定的 venue、账号和逐动作权威拒绝，或将该转发端固定为零写入。三种写命令均须计数为 0；见 [G5 接受矩阵](ctp-current-acceptance-matrix.md)。 |
| monitor 暂停/恢复命令声称管理员 issuer、receipt 或 `manual_resume_authorized=true`，以及 outbox 消费者重启/并发重复投递 | 控制命令须先由独立受信身份与授权服务核验并绑定账号、模式、动作、有效期和防重放；仅凭 monitor control ledger 的调用方自报字段不得解除风险冻结。outbox sink 按 event ID 去重，重复投递不引发第二次动作；本地 outbox 持久化不等于生产监控或控制权威。 |
| Python 3.8 环境尝试导入仅声明 Python 3.11+ 的 I9 候选 | 明确拒绝并记录受支持的部署解释器/制品决策；不得靠 fake port 通过就宣布跨包 G5 兼容。 |

当前已存在的 parser/默认拒绝测试只是本矩阵前两行的部分负证据。真实 SimNow 最小单与撤单、完整恢复及生产账号复验仍为 `NOT_RUN`。详细门槛和当前观察见[CTP 当前验收矩阵](ctp-current-acceptance-matrix.md)；本页不修改 F14 严格门槛。
