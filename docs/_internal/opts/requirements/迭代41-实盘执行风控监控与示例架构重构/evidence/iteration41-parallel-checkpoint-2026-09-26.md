# 迭代 41：2026-09-26 并行开发与验收检查点

**裁决：`LOCAL_OFFLINE_CONTRACTS / NO_WRITE / LIVE_NO_GO`。** 本页记录本次并行开发的本地可复核增量。合成测试、源码合成 wheel、TCP 传输或 SQLite 租约都不构成真实 CTP 会话、模拟账号报撤单或生产账号验收。没有读取私有 CTP 配置内容、启用已消耗的 I11/I12 marker、提交真实订单或开放默认写入口。

## 已完成的本地证据

| 范围 | 本地结果 | 证据限制 |
| --- | --- | --- |
| Windows inert guardian | 原 owner→guardian→sleep worker 的五模块焦点曾为 `77 passed`；预启动 AF_PIPE 服务和进程级负测证明 backend 阻塞时调用者先超时，服务/child 仍活，杀死 guardian 后 Job 才清理 child。新增未注册的外层独立进程监督者在 owner 死亡后按同一 monotonic deadline 请求终止 outer Job、写 `UNKNOWN` 回执并观察 guardian/child 退出。七模块兼容 venv 两次 `84 passed`、1 条现存 pytest 配置警告；根代理同环境复跑 `84 passed`。 | outer supervisor 的 Job 终止请求有截止时点，但回执可在截止后写入；supervisor 自身、同步 Win32 调用、来源信任、descriptor/密钥与 pipe/回执 ACL、普通 preflight 接线和 native 生命周期未验收，G1/G4 不通过。 |
| I9+Join/Feed Ref CTP 制品 | `2.0.4+iteration41.i9.join1` 两独立根的 wheel SHA-256 同为 `8d2d845501f43939704c9e6c61610ec1747d613a4e07485245bbb006c8242fbe`；fake focus `254 passed, 1 deselected`；新无 system-site 三轮子与依赖闭包的 RECORD、import origin、`pip check` 通过。 | 未加载 `_ctp` 或验收 native close；wheel 缺 G5 query-target 候选所需 `order_action` 证据和查询来源过滤器，**两候选不兼容**；默认 pin 不变。 |
| G5 I9 Store/worker | Store 收据在持久写入前校验 OrderRef、排队状态、优先级与深度；独立 execution target-projection worktree 的全包 `143 passed, 2 skipped`，直接 worker 缺 handle、异 Store handle 均在持久化前拒绝。新增可选 I9 源码 + Store v2 queue 的 fake smoke `11 passed`，根代理独立复跑同数；覆盖重启幂等、身份/OrderRef 不匹配、预留→收据持久化→发布、sender 超时持久 `UNKNOWN` 且重放不重发。相关无源码 Store 集 `63 passed, 1 skipped`，根代理同数复跑；普通请求 builder 仍拒绝。 | handle 是进程内 wiring guard，目标 verifier 仍可按调用注入 fake；未建立受信 SDK 来源→I9 账本→native 发送链，普通写入口依然关闭。 |
| Store/Broker 广域单元 | 从本机精确 Git 对象新建 parent/base/CTP/execution/risk/monitor 六个 detached clean checkout，HEAD 分别为 `5de97235/3de0fa4/9976bcbb/55798072/dce2c84/8498ca7d`；兼容 venv 仅使用这六个源码路径，五项原导入失败测试 `5 passed`，Store/Broker 全组 **`1121 passed, 148 skipped`**，零 warning。审计 hook 只允许本机 loopback（全组 53 个 socket bind/connect 事件），阻断外部 DNS/连接、native CTP 导入和私有 config 读取。 | 第一遍无 SDK 包的五个 `ModuleNotFoundError` 以及过严地连 loopback socketpair 都禁掉的 14 个实验性失败均为环境型；最终重跑以精确 checkout 和只允许 loopback 的 hook 为准。没有 wheel/pin、真实 provider 或账户验收。 |
| G5 原生查询目标观察 | 显式候选 SDK 源码 + fake native callback 的两文件 `9 passed`；默认已安装 SDK 下 `2 passed, 1 skipped`。 | 观察只维持最多两秒且不授权撤单；默认 SDK 缺精确接口，新 join1 wheel 也不兼容。 |
| 共享 CTP 模式 | 共享 runner 从已登记 `config.yaml` 重封，并在 fake opener 后复核；默认 pytest 兼容 venv 的代表性 runtime/Store 组合 `46 passed`。 | 最后重封至原生动作仍有配置路径竞态；默认 live profile 和写路由保持关闭。 |
| G8-P 同文件合成切换 | 既有模式 scope/receipt、旧 SimNow approval/session 与默认 live 提前拒绝测试仍有效；新增同一个合成 `config.yaml` 从 sandbox 切 live 后，旧未决 SimNow journal 不能按新 scope 接管的负测，根代理定向复跑 `1 passed`。 | 只证明旧范围不能被合成 live 请求复用；没有生产 runner、外部 fence、账号或 native 会话，G8-P 不通过。 |
| Gateway / 远端传输 | Gateway 本地 writer epoch/action claim 与事件 cursor 候选的完整子包 `69 passed`，含 WAL 初始化限定锁错误重试、数据库路径身份复核，以及最终派发时在同一 SQLite 事务核对 action claim 和 command journal 的身份/指纹/状态；根代理独立复跑同为 `69 passed`。远端 Curve/ZAP key→principal ACL 的 transport `12 passed`；parent 的严格 gateway decoder/principal adapter 与 managed composition 合计 `13 passed`。 | Fake provider 返回后 client 仍为 `UNKNOWN`、Router 为 `RETURNED_UNVERIFIED`，不当作 provider ACK。独立 QA 通过，主仓集成已按新语义定向通过；本地 SQLite 不能排除外部/跨主机 CTP 写者或证明共同 provider snapshot。 |
| Monitor 控制入口 | 注入 key/policy 的 HMAC verifier 与 durable control ingress 全包 `64 passed`，包含异步用例。 | 无部署密钥、轮换/撤销、可信 issuer/receipt policy 或生产入口。 |
| SimNow G6-S 签名审阅候选 | 未注册的 operational-window HMAC v1 审阅适配器精确签名 scope、会话、交易日、动作、风险、期限与撤销 epoch；注入 issuer policy、可信 UTC。显式注入的本机 SQLite permit/action 双键原子防重放账本覆盖重启、跨进程竞争和部分回滚；新增本机 Windows handle-based owner/DACL、祖先和 sidecar 检查、拒绝 UNC/非固定或未知卷及 untrusted `GENERIC_WRITE` ACE，并覆盖首建竞争。两文件根代理独立复跑 `77 passed`。 | 账本仅为本机候选，生产目录/ACL 部署与跨主机排他仍未验收；无部署密钥/issuer、连续本机 lease、真实回调或审批来源。ADR-41-16 option B 仍未批准，permit 的写授权标志始终 false。 |
| F14 严格收据观察候选 | 版本化 canonical envelope 与精确 scope/action/fence/四集合共同版本检查；真实 Ed25519 校验器使用注入公钥和 SHA-256 pin，显式注入本机 SQLite observation fence 持久拒绝重启、跨进程、成功 commit 后异常退出的重放；独立 QA 找到并修复 JSON `true == 1` 连接代次类型混淆及超大整数时间戳裸异常。focused 合同 `25 passed`，根代理在兼容 venv 同数独立复跑且无 warning。 | 只返回非授权 observation；没有生产信任 pin、账户控制服务、跨主机防重放、真实共同快照或最终派发栅栏。本机 DB 的 ACL/owner 未验收，G6-P/G8-P 不通过。 |
| MCP 私有路径与候选执行门 | ChangeService/JobService/worker 复核路径身份并拦截 Windows 字面量 `GenericCSVData` 私有路径；因当前没有受验 OS 网络隔离，ChangeService 在消耗审批/建 job 前、worker 在读 payload 前、Popen 前均 fail closed。四文件联合回归 `115 passed, 18 skipped`，根代理以 `--no-cov` 独立复跑同数；18 项候选生命周期测试按隔离状态跳过，原有较宽运行门时为 `129 passed, 1 skipped`。 | 当前 Windows/POSIX 均无已接入的进程树网络隔离后端；动态路径和路径式 I/O TOCTOU 仍未由 OS 边界证明。AC41-84 未运行，候选执行目前禁用。 |
| CI | 本机合成 Windows CTP 关闭入口 smoke `1 passed`、workflow 契约 `7 passed`；新增 Ubuntu POSIX 文件系统 job 的本地契约 `5 passed`；新 pytest/asyncio 约束在 CPython 3.8 目标解析通过。 | hosted Ubuntu/Windows job 及其 artifact 尚未实际运行；本机不能替代远端 PASS。 |

I13 查询来源与 `order_action` 对 I9+Join1 的三路合并在 `client.py` 有 14 处生命周期/回调冲突。隔离 `D:\bt_api_ctp_i13_g5_manual_candidate_20260926` 人工 fake-only 源码候选现把 Join/Release single-flight、原生 callback source 与 order/action evidence 同锁提交、query request filters 及 feed action 关联字段放在一起；五文件焦点 **`264 passed, 1 deselected, 2 warnings`**，根代理独立复跑同数。逐项决议见该候选 `audit/g5-i13-i9join-conflict-decisions.md`。排除项依赖原仓深路径，临时复制测试目录不满足；warnings 为本解释器没有匹配 `_ctp` 扩展和复制后 ticker mark 未注册。独立 QA 确认 `request_filters` 是 caller 请求意图而非 native getter 回读，SDK 可接受的仅 `OrderSysID+ExchangeID` 撤单目标与 I9 mapper 要求的完整目标元组不匹配，也没有 envelope/verifier→I9 Store 持久 callback 调用。候选还缺 I13 managed-cancel 身份参数与 response envelope、bounded stop receipt、event queue wrapper/API consumer 完整兼容及 package version/export 审查；普通 Store 的 I9 reservation/receipt 到 typed SDK 请求仍未连通。**没有统一 wheel、默认 pin 或 G5 managed artifact**，仍为 `BLOCKED`。原 ancestry 审计保存在 `D:\bt_api_ctp_i13_delta_audit_20260926\I13-I9Join1-source-audit.md`，不将 patch-id 等价误写为 Git ancestry。

[官方 SimNow 发布材料核对](ctp-native-join-vendor-question-audit-2026-09-26.md)只查到 full v6.7.7 与 Mini V1.7.0 分列的下载项及 Mini 手册的基本 Init/Join/Release 描述。所列两个 full v6.7.7 发布项明确仅更新 Trader API、不涉及 MD，不能证明本地 MD DLL 来源。Mini 手册没有给出本地 full v6.7.7 所需的 callback 排空、活动 Join 唤醒、Release 并发/有界关闭或成功登录身份字段回显保证；本机 DLL/header 尚未对应到官方归档字节，G4 仍为 `UNKNOWN`。

## 本轮广域回归状态

Store/Broker 的根代理独立复核将临时审计 runner 的 native 检测从会误判 `bt_api_ctp` 整个 Python 包的后缀匹配改为精确叶名 `_ctp` / `ctp_wrap`，然后在上表同六个固定 checkout 上重新运行：**`1121 passed, 148 skipped`**，10.37 秒，退出码 0，无 warning。审计输出仍为 53 个 loopback 事件，外部/DNS、native import、私有配置读取拦截尝试均为空，已加载 native CTP 模块为空。此结果没有因错误包拦截而增加跳过；Python hook 只作为本次测试观察，不是 OS 隔离证明。

随后的跳过原因静态检查确认 `tests/test_utils/optional_sdk.py` 先查 distribution metadata：CTP 的 13 个 wrapper 测试调用位置在 metadata 缺失时先跳过，源码出现在 `PYTHONPATH` 不代表 client 已被测试。上述广域结果因此只支持实际执行的 fake/inproc 范围，不能证明 CTP Python client 兼容性或 installed wheel。单独标注的临时源码 metadata 兼容测试已完成，暴露的失败与后续修复见下节；它也不能替代 wheel/RECORD/import-origin 验收。

在全新 pytest 8.2.2 / pytest-asyncio 0.24.0 隔离环境、默认插件下，`tests/unit/runtime` 和八个 `tests/integration/test_iteration41_*.py`（仅排除 runtime 的 one-shot 文件）在最新 F14 时间输入拒绝、本机 replay 与 SimNow Windows 卷/ACE 收紧后的广域复跑为 **`1674 passed, 27 skipped, 2 xfailed, 0 failed`**，pytest 用时 99.92 秒，退出码 0，无 warning。Gateway 集成定向证明 fake provider 调用一次、Router `RETURNED_UNVERIFIED`、client `UNKNOWN`、重复提交不重派，legacy Store 直连为零。此广域范围不含 guardian script 模块；七模块外层 inert supervisor 结果为 `84 passed`，见上表。此前同范围旧代码结果为 `1669 passed, 27 skipped, 2 xfailed`，不替代当前代码状态。这些通过只覆盖离线 fake/inproc 路径，不代表真实 provider 或账户验收。

## 尚未通过的上线门

Guardian 的后续窄范围修复已加入当前用户 protected DACL 与真实 handle 回读、`dwPipeMode` 的远程客户端拒绝、两个 pipe instance 上限，以及 HMAC 响应和实际请求消息各自的 impersonated SID 检查；异常路径不再重复关闭 handle。最终 service 文件作者与根代理独立复跑均为 **`11 passed`**，根代理用时 24.28 秒、1 条现存 pytest 配置警告。此前七模块 `89 passed` 在最终 instance 上限调整之前，不能冒充最终全组结果。当前用户 ACL 不提供外部部署信任根，也没有证明全命令硬截止，G1 仍未通过。

隔离 CTP SDK 人工合成候选的受管撤单参数已补齐：完整目标和身份先验证，随后发送由单次快照构造并 getter 回读一致的独立 native field，防止调用方在验证后修改原字段。其历史焦点为 `277 passed, 1 deselected, 2 warnings`，独立 QA 窄范围 `19 passed, 1 warning`。后续 query getter 回读区分了字符串 filter 的意图/实际值，以及 option trade-cost 的 typed 数值参数；忽略、截断、归一化、缺 getter 和类型不一致均在 ReqQry 前拒绝。新五文件作者焦点 **`292 passed, 1 deselected, 2 warnings`**；根代理对最终 34 项 target 使用精确 CTP 候选与 clean base `3de0fa4` 源码独立复跑 **`34 passed, 1 warning`**。兼容 venv 的首轮 3 项失败来自缺 aiohttp，随后全局 Python 加同一源码路径、关闭无关 pytest 插件后通过；native 扩展仍未加载。私有 `_execute_query` 不是同进程隔离边界，getter 证据不证明 provider 按该过滤器执行或原子快照。完整 I13 构造参数、登录观察、certificate、bounded stop 和事件 queue wrapper 仍在合成；没有统一 wheel/pin 或真实 provider 验收。

I9 callback→ledger 适配器已修复两次 poll 间的崩溃窗口，并将旧 v11 已 resolved guard 保守迁为永久 source lifecycle fence；cleanup 异常也不能覆盖固定脱敏错误。v12 焦点作者与独立 QA 均 `112 passed, 2 skipped`。随后与 `5579807` 质量改动及 `c10ccf5f` target projection 链合成为隔离 execution commit **`2946e52`**，schema 升至 **13**，按 DDL 前表清单区分 projection-v11、过渡 callback-v11 和 permanent-fence-v12，歧义/损坏 lineage 拒绝升级；迁移、二次打开、同 Store 单次 target handle 与事务 TTL 检查的联合焦点作者及独立 QA 均 **`124 passed, 2 skipped`**。Ruff 清理后的 `07404fa` 加经济事实 wire 两文件，全包 **`174 passed, 2 skipped`**；相同内容已在本地提交为 **`6aa4d7c3dd05aeb635e85191e75afb9e660dd618`**，工作区干净、未 push。这条 fence 目前没有可信 terminal/queue-drain/reconciliation 解锁协议，成功 callback 或 close 也不解除，因此启用它后不能 claim 第二笔账户命令；这不是可运行 G5 写路径。

AC41-48 的隔离 risk 候选现有按策略/账户双限额原子预留、不可复用分配版本、明确计价单位、本地只读 ledger snapshot 和精确 Snapshot→mapper 接线。独立 QA 曾复现同库另一 gate 提高 cap、关闭 allocation 或移除单位即可绕过；不可变 account policy binding 修复后三种攻击均以 `RISK_POLICY_BINDING_MISMATCH` 拒绝，snapshot 明确不完整，独立复核未发现剩余阻断。六文件全包在最后两项小改动之前独立 **`201 passed`**；补充 snapshot 金额的运算规模上限、零分配返回 `STRATEGY_ALLOCATION_EXHAUSTED` 后，作者完整 **`203 passed, 0 skipped`**，独立 instrument/mapper **`32 passed`**，真实 SQLite risk→主仓 bridge/Store/Broker→mapper→reserve/validate 链再次通过，native import 与 socket 均被阻止。跨策略两进程各申请 600、账户上限 1000 的 barrier 用例只有一个获准；低 Decimal precision 的大数加一、占用精确求和也通过独立 Fraction oracle。

根代理新增的 `NotionalAllocationSizer` 经 Broker→Store→runtime risk reader 获取本地额度，复用 SDK instrument assessor 向下对齐数量，提交仍须独立 reserve。大金额/微小固定费的指数跨度负测曾建议超额 100 手，共享精度与精确 fee 等式修复后建议 99；helper 与原纯估值历史焦点 `51 passed, 6 mapper deselected`，追加运算规模测试后的 helper **`27 passed`**，主仓新旧 sizer/bridge/reader 联合 **`85 passed`**。这只支持名义金额和保守数量保留量，非 margin 预算或完整账户持仓；只有 position cap 而无 notional cap 时 snapshot/mapper/sizer 仍拒绝，不能据此称完整 AC41-48 已通过。

AC41-53 的 canonical execution AccountSnapshot/ExecutionQualityRecord 已兼容追加 scope、金额/执行链路、逐字段来源/区间与完整性，并提供脱敏 versioned wire；monitor 候选按 scope/cursor 有界查询/导出且重验公开 FactPage 的 500 条上限。缺外部活动截至快照的覆盖证据、quality side 或必需经济事实不能标 COMPLETE。账户 facts 不带策略归因，历史 arrival 允许自己的明确区间；raw account_ref 不进入导出。作者和独立 QA 的 monitor 全包均 **`59 passed`**，wire **`13 passed`**；跨包回环保留已含 fee 的权益 `100090`，没有再扣 `10`。独立全包使用兼容 asyncio venv，无 skip，`--noconftest` 仅绕开原测试对深目录层级的路径假设。monitor 四文件已本地提交为 **`82e5282ea6aff6a52874f5cf62e86a8df984bde0`**，工作区干净、未 push。没有接入真实账户/成交/funding/FX/结算来源或 TradeLogger，不能由这些 wire/出口测试推导真实交易事实已验收。

parent SDK 的 typed cancel identity 合同已本地提交为 **`7f154b61a2719a702989429a6ff361c620688a35`**（基于 `5de97235`），只提交七个源码/测试文件，四个原有子模块指针变更保留为未暂存，未 push。作者及独立 QA 的焦点 **`65 passed`**；固定 execution `5579807` 的真实 SQLite reservation→CANCEL stage→typed projection→parent mirror/consume 源码 smoke 通过。该 DTO 只是非授权身份回显，public sync/async/forwarding 撤单仍在 backend 前拒绝；没有 native/SDK 队列发送，没有外部 account actor，也没有把来源 metadata 冒充安装制品。

可选 SDK 源码兼容补跑已完成：13 处 CTP gate 展开为 `15 passed`，确实导入了固定源码的 Python client。使用临时 `SOURCE-ONLY` metadata 的 Store/Broker 扩大范围为 **`1261 passed, 11 failed, 1 skipped`**（20.38 秒）；9 项是 Store 与固定 parent SDK 的 `runtime_order_id` DTO 参数不兼容，2 项是 fake-port 拒绝消息正则不一致。根代理修复非 CTP 撤单仍传 CTP 专用 keyword 和同一 authority 拒绝消息后，这 6 项独立复跑 `6 passed`（1.70 秒），Ruff/diff 检查通过。另 5 项 CTP DTO 兼容性失败仍未关闭：固定 parent 使用嵌套 `ctp_order_identity`，旧 Store 使用顶层 runtime ID，不能靠丢弃身份或放宽 managed gate 解决。扩大范围的 pytest exit 为 1；审计 runner exit 86 是两次 `_ctp` import 被阻而进入 Python fallback，已加载 native 为空；外网/DNS及私有配置读取尝试为空。这些结果取代“可选 SDK 源码组已全绿”的推断，不替代已安装制品验收。

- **G1–G4：** 无受信来源和整条命令硬截止；当前没有同一已 pin 制品、配置、前置的 TD/MD 原生正面登录、完整查询、匹配 tick 与 `Join/Release` 关闭证据。
- **G5：** 唯一 OrderRef/command 权威尚未从可信原生查询、Store、I9、SDK outbox 到最终 native sender 连成一条；旧双权威、候选 SDK 版本分裂及取消目标来源仍阻断。
- **G6-S / G7-S：** SimNow 有界逐动作许可尚未批准或接入；真实模拟账号结算、最小报单、订单确认、成功撤单及账户回查均未运行。
- **G6-P / G8-P：** 无已验证的独立账户级跨主机 writer fence 与同版本资金/委托/成交/持仓全量快照，也无 production 会话、凭据/审批来源或真实账号验收。`live/managed_live_direct` 仍提前拒绝。
- **AI/CI：** MCP worker 的 OS 网络隔离与路径竞态未关闭；hosted CI 尚无通过回执。

## 后续接线检查点

风控默认导入边界进一步修复为 clean local commit
**`2201316f5ea196d164b3045d02648fe857989b92`**（基于 `94ec45d9`）：root/core
保留既有公开分析类名称，改为显式访问时才加载，普通硬准入不再间接加载 NumPy、
scikit-learn、SciPy 或 pandas。全包 **206 passed、1 条现存配置 warning**；独立新
测试 **3 passed**，另核对 9 个导出的类型身份、`dir()` 不加载和缺依赖异常透出。
fresh `-I` 子进程在阻断分析/provider imports 和 socket I/O 后完成真实 SQLite
reserve。依赖 metadata 暂保持原有必需项，因此 lazy import 仅改变运行时导入边界。
三包的[可复现构建与严格安装环境验收](capability-artifacts-strict-consumer-2026-09-26.md)
已完成：base `3de0fa4`、risk `2201316f`、monitor `f3583e7` 各自两次构建的完整
wheel 字节一致，实际 consumer venv 的 `python -I` 测试为 risk **206 passed**、
monitor **90 passed**，RECORD、payload、import origin 与 pip check 通过。
初次全局解释器注入 site-packages 的 hybrid 结果已降级，不用作隔离验收。
此 base 源版本为 0.15.4；risk metadata 0.1.0 与模块版本 1.0.0 不一致，保持如实
记录。未统一 parent/CTP/execution wheel，不更新默认 pin 或 release/live 状态。

上述 risk 版本不一致随后由本地干净 commit **`d4bc03047ebfc2b416259aba313fafca7a0dffcc`**
单行修复；[替换制品复验](risk-version-consumer-2026-09-26.md)的两份 wheel 字节一致，
SHA-256 `d7e7bb28cfd049be3aa0b50f1e9deb7a83e97f24da3bc9bce51dc6f599a5202f`。
真实隔离 consumer 全包 **206 passed**，模块/metadata 都为 0.1.0；base/monitor
复用旧已验 wheel，没有重测其功能套件。旧 manifest 保留原字节。

parent MD credential consumer 已保存 local commit
**`62e683bc5ec9a04117e39f4a5dcbba1f6e3b16ec`**（基于 `7f154b61`），只提交两个
源码/测试文件，原四个未暂存子模块指针保留。作者及独立合同测试 **82 passed**，
独立额外负测 **21 passed**。MD `request_id` 与 generation 分别校验并允许不同；
要求 SDK 原子只读 `active_md_identity`、构造绑定的 front/account 与 feed/stream/
state profile 一致。没有虚构 SDK profile 字段；此为同进程可信代码合同，不是
对恶意 Python 代码的隔离。对应 SDK MD lifecycle 仍在独立 fake 审查，尚无统一 wheel。

[Python 3.8 默认导入修复](core-python38-import-fix-2026-09-26.md)解决了默认 Store
导入链上的 `dataclass(slots=True)` 兼容性回归。实际默认导入成功且 SDK 未加载；
扩展后的本机核心 harness 为 **111 passed、8 skipped**，现代解释器相关焦点为
**35 passed**。未替代 hosted CI 或 managed SDK 的 Python 版本要求。

另新增 [BM59-M 独立进程测量脚本与 smoke](monitor-bm59-harness-smoke-2026-09-26.md)。
60 条合成测量事件全部持久化并被唯一消费，CPU 短测超出 5% 单核目标，脚本如实
返回 exit 2。正式 30 分钟、串行、五轮与双平台性能验收未运行，不能以此关闭 BM59。

monitor 的批内连接复用候选保存为 clean commit
**`f3583e744922d556a6015576f386c2d26e3aae51`**。每条 ACK 仍独立 WAL/FULL 事务，
callback 在事务外，连接不跨 `consume()` 缓存；public 参数校验与 method override
兼容。作者全包 **90 passed**；独立初版优化全包 **86 passed**，末次兼容修复
窄复验 **4 passed**。根代理 smoke `f` 的 CPU 仍为 **6.25%**，门槛失败，不能声称
性能已通过；完整明细和原始文件 hash 见上方链接。严格安装制品全包复验为
**90 passed**，范围见上方三包制品证据。

经济事实 v2 的 monitor 源码已保存为 clean local commit
`b9ac86be99e66e7c3747febb3e33b6489c7d9cfc`，作者全包 **65 passed、0 skipped**。
它新增明确的累计数量/VWAP/费用 basis、journal generation 类型和绑定 schema/type/full
scope 的 cursor，旧 v1 COMPLETE 只读导出为有效 INCOMPLETE 并保留原始存储标签。
新 execution 原子事件接口把 duplicate/no-op 的 `None` 与持久 review latch 后的异常
区分开；当前作者焦点为 facade/wire **35**、Store **18**、monitor read model **25**、
主仓 pull-only publisher integration **1**，均通过。execution v15 仍有并行修改，
这些数不能写成最新全包验收。monitor `b9ac86be` 的独立全包同为 **65 passed**，
但独立 malformed-wire probe 发现 direct monitor append 接受负 quantity/零 VWAP，
与 execution DTO 不一致；正值约束修复及后续 commit 的验收仍在进行，不能仅据测试
计数宣称该切片已完全通过。

上述 monitor validator 修复及 legacy v1 field-level completeness 修复随后保存为
clean commit **`eac1e8823f81c5d0276dde305b6d69acc29595d8`**，作者与独立 reviewer
全包均为 **82 passed、6 条现存环境 warning**。独立 direct read/export probe 确认
raw v1 仍保持原始 COMPLETE，而有效总状态及 quantity/VWAP/fee 均显示 INCOMPLETE；
非正数量/VWAP 等拒绝，signed negative fee 仍合法。此前 `82e5282e`、`b9ac86be`、
`b4edd6fb` 仅为各阶段快照，不代表最新源码。

Framework 增量投影仍在实现与审查：除了事件经济字段绑定、post-apply 实际 qty/VWAP/fee
核对和 source-session fence，还必须补齐 SDK commit 后、框架 claim 前崩溃的主动 outbox
恢复路径。仅重收 callback 会得到 SDK duplicate `None`，不能恢复遗漏记账；journal 单测
能接受人工历史事件也不能证明 Store/Broker 操作链恢复。当前 AC27 未据此关闭。

旧 Store DTO 参数修复已在固定 parent `7f154b61`、execution `6aa4d7c3` 和 base
`3de0fa4` 的干净源码上复验：`test_btapistore_normalized.py` **`44 passed`**。
内部 runtime ID/OrderRef 关联和 managed 早期拒绝保留，legacy 请求省略 parent 不支持的
顶层身份 keyword。相邻 Store/I9 源码焦点为 **`209 passed, 1 failed`**；剩余 smoke
仍直接 stage CANCEL，未提供新 execution 合同要求的 fresh verified target handle。
它须按当前合同补齐真实同 Store 的 fake verifier/handle 测试，不能跳过或减弱拒绝。
独立非派发 parent request builder 正在实现，尚未开放普通 managed enqueue。

该历史 smoke 随后按当前同 Store fresh target 合同修复，builder 补齐最终 typed
command/reservation/approval 与原始 projection 的完整回读。独立 fake 焦点为
**27 passed、1 个被新不可变性测试替代的旧复现未选取**：覆盖已确认订单到 OPEN、
部分成交到 PARTIAL 的合法撤单 DTO，以及终态、倒退、跨 scope、篡改拒绝。
输出仍为 `dispatch_authorized=False`，无 native 或普通 enqueue 接线。

Framework source-outbox 恢复已补齐实际 fresh Bridge/Broker 操作链，作者与 reviewer
焦点均为 **41 passed**；独立临时四项故障注入覆盖 read/claim/complete 失败和活动
事件内容冲突，全部通过。正常 risk reject/block 与
`cancelled_by_cancel_intent` 事件随后补齐，撤单在同一事务冻结事件时刻经济快照。
独立复核还修复了累计成交增长、费用未知时沿用旧手续费的错误；旧费用仅保留于
旧不可变事件。新焦点独立 **49 passed**、实际 facade reject/block 到 Broker
消费 **2 passed**。另两项真实 Broker 复现发现合法 float 运算被 Decimal 精确比较
误判：累计 VWAP `0.2` 得到 `0.20000000000000004`，signed fee `-0.3` 得到
`-0.30000000000000004`，均在记账后留下 CLAIMED 并 fence 下一 intent。
随后修复普通舍入误判，作者焦点达到 **57 passed**；根代理实际 Python 3.8.20
导入与七项 ULP helper 窄验通过且未加载 SDK。但独立真实 Broker 又复现大数相消：
累计量 `1e15→1e15+1`、均价 `1→1.0000000000000001` 时新增单价错误地为 `1`
而非 Decimal 所隐含的约 `1.1`；累计手续费 `1e12→1e12+0.0001` 时新增费用
错误地为 `0.0001220703125`，约多 22%。两例均曾错误推进 cursor 而无 fence。
57 项冻结已撤回，随后改为从相邻不可变源事件用 `Fraction(Decimal)` 精确计算
新增价格和费用，再各转换一次 float。累计字段仍与 claim 绑定，但 Broker 接收
明确的增量价格/费用，避免重复做大数累计差分；不可表示的数量、非有限数及
非零增量下溢在 claim 前拒绝。最终三文件焦点作者 **64 passed / 4.75s**，独立
QA **64 passed / 4.60s**；两条原舍入误判、大数量价格 `1.1`、大累计费用 `.0001`、
普通 `.01` 费用增量和 signed rebate 均正确记账，下一订单可接受。独立恢复、
reject/block 与四项故障注入也通过。冻结 `managed_execution.py` SHA-256 为
`3353051390b28e869749cd7c0a9e38e741b63ef1f536831555bbb6e4b5a67362`。
这一结论仅关闭 AC27 的 source-outbox 与精确增量投影切片；双模多数据组合测试、
统一制品和完整账户集成仍需验收，不能将 AC41-27 整条提前标为 PASS。

[F10 核心完整策略集](f10-core-strategies-2026-09-26.md)作为独立回归已完成：
**1286 passed、0 failed、0 skipped、13 warnings、312.48s、exit 0**。
1662 个 core/strategy/config 路径的运行前后 SHA 清单完全一致，导入本仓；根代理
独立解析 JUnit 和核对 hash。AC27 变更仅在 runtime 层与非策略测试，未改冻结
核心库；该通过不覆盖 AC27、F10 双模/受影响示例集成、性能或真实交易。
首次 qa1 退出 5 且未产生 JUnit，保留为原因未证实的调用/setup 失败；qa2 完整通过。

SDK 的 certificate、终态登录观察与关闭回执合成后，旧 fake 夹具因手填登录状态而
出现的 87 项失败已通过真实 fake SPI 认证/终态登录流程修复；五文件最终焦点为
**`302 passed, 1 deselected`**（排除项依赖原父仓目录布局）。根本的身份门没有放宽。
后续同步 Join 回执修正经独立 **`45 passed`**：实际 source `MdClient` 产生的成功
同步 Join/Release 回执被主仓未修改的 shutdown consumer 接受，活动 Join 则拒绝。
没有 observer 时报告 `thread_alive=False`，Join 是否完成仍独立校验；同步 `stop()`
仍可能超时，不能据此称整个命令有硬截止。这些是源码/fake 结果，未加载原生扩展。
源码、已迁入候选的测试及来源审计已保存为干净本地 commit
**`07012dda628c8c0d7fefa6e1b925f7f8b3f8f518`**，没有 wheel/pin；certificate/login
焦点另为 **`45 passed`**，compileall、范围内 Ruff 和 diff 检查通过。MD/profile、
parent `active_md_identity`/credential 全链与完整 ingress 仍未闭合。

主代理随后在该 commit 的独立 clean checkout 上完整复验七文件，得到
**`347 passed, 1 deselected, 2 warnings in 57.38s`，exit 0**。
实际模块来源正确，没有加载 native CTP，也没有外部网络或私有配置访问；仅允许
Windows asyncio 所需的数值本机回环。该审计不构成 OS 隔离或制品证明，详见
[固定 SDK 独立复验](ctp-sdk07012-independent-source-audit-2026-09-26.md)。

多命令实现将单个账户的长寿命事件 owner 与每笔命令分开。设计审查确认 generated
TraderSpi 有 **155** 个回调，现有 Python override 仅 **23** 个；事件入口必须从
SPI 注册前覆盖完整列表，逐项区分可路由执行事件、只读审计、生命周期变化和未支持
金融活动。原生 Req 调用不能持 SDK/SQLite 锁，回调须先持久化 inbox；收到本地派发
结果后才应用 execution 投影。当前这条新路径仍在实现，旧永久 fence 不解除。

后续 SDK Trader fake 焦点作者与独立 reviewer 均曾得到 **141 passed**，但该冻结点
已因新发现的问题撤回：native `None`/bool/float 不能等同整数 `0` 的本地排队回执；
startup `KeyboardInterrupt` 曾留下引用计数，阻碍延迟关闭。作者改为 exact int 0、
`finally` 归还引用后，Trader 专属焦点为 **29 passed**，尚待联合最终复验。
独立 bounded fake 还证明 MD startup 持锁调用 `Init` 时，另一线程的真实 SDK
连接回调须等该锁释放，违反锁外原生调用合同；这是代码级死锁风险，不是对厂商
真实 `Init` 必然等待的断言。随后已完成 MD 锁外调用、引用排空与关闭修复；再合入
ABI submitter 接缝、shutdown SPI 夹具与重复 detach 修复，最终作者与独立 QA 的
14 文件并集均 **457 passed**。13 个文件已本地提交为干净候选
**`f90568c15196f1507f13d3fe0ad661f92d270bee`**，根代理复核 81 个 Python 源 hash
与 457 项 JUnit。此前 141/29/60/64 等只保留为开发检查点；详见
[最终 SDK 源码证据](ctp-sdk-f90568-managed-ingress-2026-09-26.md)。没有据此升级
native 生命周期、安装制品或真实账号状态。

execution v16 仍在补实际 account inbox/router、trade 去重与迁移。只读审查发现
命令 session 摘要未完全匹配当前 Store 登录绑定、callback record 的类名鸭子匹配、
同 owner 多 consumer 可能导致误 poison，以及 stage 后 queue receipt 失败缺少
typed UNKNOWN 路径，均已交实现方修复。无密钥摘要和进程内 capability 仅约束
可信代码接线，不证明原生来源不可伪造或隔离不可信 Python。账户经济查询后的
永久 fence 尚无受信完整 baseline 恢复来源，不解除它来制造可写状态。
新主仓 `ctp_i9_account_session_candidate.py` 开始连接 owner→SDK sink→session claim
→native lease→local receipt→inbox；仍未登记、无真实 lifecycle supervisor 或制品 pin，
两笔报单一笔撤单的最终 fake E2E 尚未完成。

execution v16 初版作者全包 **213 passed / 2 skipped**，只读快照独立覆盖
30 项与真实两进程同库 claim 竞争；经济查询后仍拒绝派发。随后实际主仓 E2E
发现 `OnRspOrderInsert` 的合法 terminal flag 被 action-only guard 误拒绝。
214 项修复检查点恢复了该路由，但独立 QA 又发现 `OnRtnOrder` 错误接受 terminal
flag，正在补完整 callback 形状矩阵。因此这两个快照均不作整体最终接受，保留
其已通过的窄范围证据，不以包内绿灯代替主仓实际端到端链路。

完整 callback 形状矩阵随后修复为作者 **219 passed / 2 skipped**、最终补丁独立
**10 passed**，快照 manifest 为 `c03ddaa7173ca9405f0d4450a1576c22abf8bcc4a212474d2229d790aef45090`。
实际主仓组合恢复两笔 submit/apply，但 fresh-target cancel 继续失败：CTP 本地
header/SWIG 将 `OrderActionRef` 定为 int，而 execution、SDK、parent 和主仓 typed
binding 使用文本标识或错误地要求等于 RequestID。真实 setter 会在 Req 前拒绝，
fake callback 也被严格入口拒绝。主仓正向撤单红测保留，当前组合 **22 passed / 1 failed**，
不以 UNKNOWN 负测替代成功撤单。

v17/V2 修复已开始：Store 在 stage 事务中独立分配账户范围、跨 session/day 不重用的
正整数 ActionRef；这是本地保守合同，不是从厂商资料推导的唯一性承诺。逻辑审批
payload 与 Store 生成的 native payload 分开绑定；SUBMIT 两者相等，CANCEL 只增加
Store 分配的整数，禁止 caller 覆盖。旧 v1 文本记录保留原字节/hash，仅供审计并
保持封锁，不能通过强制转 int 获得派发权限。SDK/parent/主仓组合正在联动，因此
f90568 wheel 验收暂停，先前源码通过仅为检查点。两次 f90568 构建还遇到 Windows
临时路径过长，未产生最终 SDK wheel；该失败也保留，不记为制品通过。

主仓已增加真实 Cerebro 的多数据/部分成交/手续费双模 fixture，以及买开、卖平多、
卖开空、买平空的 Broker 投影回归。根代理联合两项曾通过 **2 passed / 1.76s**，
之后只加强逐 feed 通知顺序及非空账本失配断言。最终最新 bundle 将再次覆盖它们。
F10 的 1286 项仍是其已保存源清单的有效历史结果；本轮 V2 将修改 Store 适配文件，
因此最终核心 source tuple 冻结后须再做完整策略回归，不能套用旧清单。

事实出口正在增加明确的累计数量/VWAP/费用 basis、本地 journal generation 类型和
不可变事件时点值。单笔 partial 的后续增长还需独立接入 framework checkpoint；
monitor 累计快照通过不代表 Broker 增量入账已通过。持仓和费用投影会复用现有累计
差分逻辑，并另验重复、迟到、崩溃和 signed rebate。

当前 writer 清单另有静态漂移：只读扫描为 **283 files / 221 writer / 49 dynamic**，
旧 JSON 为 281/210/49；verifier 正确返回 **`REJECTED / exit 2`**。差额来自已核对的
资源 close 和类更名。清单待代码稳定后按 ID 合并证据，不能覆盖现有审核字段，也
不能把静态清单完整性当作所有 writer 已准入。无 adapter 的 legacy CTP 组件仍有
原生 fallback，必须与受管 runtime 的关闭边界分开陈述；历史 API 保留不代表
Iteration 41 live profile 已登记。

下一次状态更新必须以同一代码/制品版本的广域回归、远端 CI artifact 和逐门正面 provider 证据为依据；不得从本页的离线计数推导真实交易可用。

## 五分钟监控诊断与 V2 接合进度

[BM59-M 五分钟 Windows 诊断](monitor-bm59-five-minute-diagnostic-2026-09-26.md)完整消费 6000 条测量事件，CPU 单核约 4.03%，但两段共四条生产迟到超过 50ms，结果保持 `SMOKE_ONLY / exit 2 / NOT_ACCEPTED_FULL_MATRIX`。原始 CSV、结果、临时脚本及逐文件 hash 已入证据目录，正式双平台五轮 30 分钟矩阵未运行。

V17/V2 修复仍在接合：执行库拥有账户级原生整数 ActionRef 分配；逻辑 request 与 native request 分开封存，前者禁止 caller 提供 ActionRef。SDK 已冻结为干净本地提交 `2fe2ba9d78bab6477aa4e232795aad35a14f2313`，V2 焦点由作者和独立 QA 各通过 44 项，独立 14 文件并集通过 472 项。作者并集的 parent `PYTHONPATH` 错指向 package 子目录，曾回落到另一脏 parent；原记录保留并更正，随后同进程断言正确 parent root 的实际模块来源后重跑唯一相关 normalizer 节点，1 项通过。独立并集原本使用正确 parent root，但只保留工具输出和书面收据，没有原始 JUnit。详见 [SDK V2 来源复核](ctp-sdk-v2-2fe2ba-source-review-2026-09-26.md)。这些结果不是已安装 wheel 或完整 parent 制品证明。

首版 V17 快照 manifest 为 `23c8a499c14a597d5e869a9a4cac9bad9f448ab0028e5ec51d96a516ed6d919d`，作者全包为 224 passed / 2 skipped。主仓真实 Store→SDK fake 组合已通过携带匹配 RequestID 和省略该字段的两笔报单；撤单也到达 fake `ReqOrderAction`，随后回调关联查询错误使用 CANCEL 行为空的 `order_ref`，应使用其 `cancel_target_order_ref` 并保持精确动作关联。此失败及原快照保留，正在窄修并重新冻结，不能将 SDK 或包内通过升级为 G5 撤单验收。父级 cancel 合同作者 41 passed；最终三库制品和主仓广域回归仍待这一接合完成。

[Inert 监督链独立完整复验](ctp-inert-supervisor-95-review-2026-09-26.md)为七模块 **95 passed**，修复测试侧 JSON 可见性和保守清理分支断言，并补固定阶段诊断；两项更早完整运行失败的原因未判定，原始证据保留。G1、普通 preflight 和真实 native close 均未升级。

## V17 冻结后的实际组合与剩余撤单门

execution 已本地提交为 `bb2cd24cdaf9fb64f6b95010ee8619b0c6a35589`，最终 r4 作者全包 230 passed / 2 skipped。独立 QA 找到并推动修复了空账户的 terminal SUBMIT 和合法前缀但跨账户外键损坏两个迁移遗漏；[冻结源码、合成库、复现与独立验收](ctp-execution-v17-independent-review-2026-09-26.md)均已保存。此前快照保留为开发记录。

主仓四个 Store 文件作者与独立 QA 均为 60 passed、零跳过；parent V2 三文件本地提交 `e53b6b559bdc378d144cca5917814d0ac5beb2c1`，独立合同 41 passed，原四个脏 Gitlink 未暂存。主仓 account-session 组合文件最终 32 passed：实际 fake SDK 先进入 durable OnRtnTrade 2 单位，再收到目标订单 partial 2/5，撤单请求响应 ACK 后收到原 SUBMIT 关联的 CANCELLED/已成交 2/剩余 3；订单累计观察与 trade fact 保持 2/MATCHED，旧 target handle 不可复用。

这一结果只证明 G5 接合。独立静态审查确认 V17 尚无账户级“撤单目标未终态就拒绝新 SUBMIT”的谓词；第三笔在目标终态后成功，并不能证明终态前已被阻止。撤单 action ACK 仍非终态；V18 将复用同账本的 verified target terminal ingress，持久记录撤单完成条件，并在所有 claim 路径检查，不能把响应 ACK 直接改成 terminal。

G1 正并行实现固定只读操作、owner token 的 CreateProcessAsUserW/Job、限长匿名结果管道和受保护 ProgramData descriptor。已修复中断窗口遗漏 RevertToSelf、失败 CloseHandle 不可重试等局部问题；完整新链尚未冻结，也没有部署或真实 provider 验收。[BM57 direct 基准工具](bm57-direct-harness-review-2026-09-26.md)的独立四项合同与 smoke 已通过，正式性能矩阵未运行。

## Store/parent 证据归档与静态清单刷新

[Store/parent V2 回执](ctp-store-parent-v2-source-review-2026-09-26.md)已归档独立 60/41 项、作者组合 32 项，以及 root 核对的 12 个源文件。独立 pytest 没有同进程 origin capture，且使用的 V17 快照不同；这些限制逐项保留，未合并为统一制品通过。

此前静态清单漂移已按 ID 合并。[本轮刷新](writer-inventory-refresh-2026-09-26.md)为 287 files / 221 writer / 49 dynamic / 0 parse errors，258 个现存审核记录保留、12 个新资源释放候选待审核、1 个旧更名条目留在历史 delta；相关 9 项测试通过。270 个候选仍均为 REVIEW_REQUIRED/NOT_AVAILABLE，不改变交易准入。

## SDK 制品检查点、MD/profile 补齐与 V18 独立审查

[2fe2ba 制品回执](ctp-sdk-2fe2ba-repro-strict-consumer-2026-09-26.md)已归档：固定工具链和 `LINK=/Brepro` 的两个 wheel 字节一致，90 个成员由 root 再核对；最终 no-system consumer 的 296 项由作者执行。早期全局环境结果降为诊断，重复使用 XML 导致旧版本原字节丢失的限制明确保留。该历史 wheel 不含后续构造接口修复。

广域回归发现干净 SDK 缺少运行时实际传入的 `md_front` / `ctp_env_profile`，因此七个查询证据测试失败。干净提交 `29f8ff171f61a71038328a7067e0909bf44774b2` 补入 paired keyword-only 参数及只读构造绑定；[root 独立两文件组合](ctp-sdk-md-profile-29f8ff-source-review-2026-09-26.md)为 63 passed，四文件首尾 hash 一致、native/network/private-config 被阻断。新 wheel 使用独立输出构建。

V18 r0 manifest `0372771FBB91D3A6C6CC8D859EB4C68B6BBE65368A8672A8312F4AE9FA6E46B1` 冻结于 `D:\temp\iteration41_v18_cancel_postcondition_r0`，作者全包 235 passed / 2 skipped。独立 QA 已通过四文件 155 passed / 2 skipped，仍在用真实 V17 库副本验证可能发出撤单的迁移、跨 scope/day SUBMIT 阻断、终态与成交证据顺序及矛盾后的永久封锁；不以作者包内绿灯提前关闭 G5/G6。

G6 签名许可适配器的初版 25 项与实际 V17 Store fake 组合通过后，独立 QA 发现返回凭据寿命未受两份信任快照的 250ms freshness 截止约束，另有可变 key map；当前判定为待修复复验。具体 sealed-config resolver 仍在开发。G1 的实际 client-write ACL 和匹配时间戳 pyc 攻击已复现；保护代码的完整性 writer 集与 source-only child bootstrap/依赖 finder 正在修复和组合，不能以 `-B` 宣称禁用 pyc 读取。默认 pin、普通 preflight 和真实写路由均保持关闭。

## V18 接受范围、新发现缺口与完整策略/BM57 归档

V18 的 [155 项独立测试和六库迁移](ctp-execution-v18-independent-review-2026-09-26.md)现已完成局部验收；本地 commit `33d132d6` 与冻结快照五个变更文件在 CRLF/LF 归一化后完全一致。它不解决同 broker/user 在 simulation 与 production 环境下产生不同 account_key 的问题。独立 QA 已用真实 V18 Store 公共 API 构造 sim UNKNOWN/live 可领取和 sim POISONED/live 可建 owner 的旧库，V19 正增加 Store 内部派生的 canonical account-family owner，覆盖 lease、claim、callback 等事务边界。V18 不存原 account_ref，不能从旧摘要反推跨环境映射，旧非空库必须显式迁移或永久拒绝接管。当前切片不实现未经可信 drain/关闭证明的 owner handoff。

另一个主桥接回归证实 strategy.one 在撤单 UNKNOWN 落库后、risk freeze 前中断，strategy.two 原恢复只查自身 scope 而可能继续发送。正在加入持 account writer lease 的跨策略未决撤单枚举与持久 risk freeze；不得借 generic fake acknowledgement 清除未知状态。

G6 的 freshness/key-map 修复与具体 resolver 基线通过 41 项，真实 V18 Store 独立验证了 249ms 截止后保留 READY；但进一步对抗用例证明签名许可仍可携带与 config 不符的 login account、request account/contract/exchange 并到达 CLAIMED。现增加强制的 fresh sealed config→实际 session→逻辑 request 字段绑定，后续冻结后重新独立复验。41 项基线不是完整授权接受。

[SDK 29f8ff1 strict consumer](ctp-sdk-29f8ff-repro-strict-consumer-2026-09-26.md)现为 308 passed，两份 SDK wheel SHA 相同且 90 成员一致；root 独立核对 443 项安装字节与 RECORD。[parent 76d5e0e](ctp-parent-76d5e0e-repro-wheel-2026-09-26.md)两次独立源码归档构建的 156 成员一致，未进行新的统一消费者测试。

[策略 R1](iteration41-strategies-final-r1-2026-09-26.md)1,286 passed / 0 skipped，输入 1,944 文件清单在运行前后相同，root 全部重核；环境 before/after 文件实际都在运行后生成，已明确纠正其证据限制。[BM57 Windows](iteration41-bm57-windows-full-r1-2026-09-26.md)五轮正式采样的四项配对比值中位数均达到 ≤1.05，第一与第四轮部分尾延迟超限也原样保留；Linux 未运行，BM59 长时矩阵仍未接受。

G1 新客户端读取固定非秘密 descriptor，以 OS service SID/PID/SCM 绑定 pipe，不让 owner-token worker 与请求者共享 HMAC key。当前进展仍不证明 SCM 部署或实际 worker 生命周期。启动前 CPython 已加载 encodings，当前 Anaconda base 对 Users 可写；仅保护 venv exe 或在 bootstrap 后加 finder 不足。正在增加外部固定摘要的 CPython distribution manifest、启动前 ACL/文件与目录句柄保护，System32 属受信 OS 边界而不扫描整个 Windows。默认 pin、普通 preflight 与真实交易仍关闭。


## G6 v2、V19 r1 与 G1 r5/r2 后续归档

- [G6 v2 独立复验](ctp-g6-v2-bound-fields-defer-independent-review-2026-09-26.md)：75 项及八签名字段错配反例拒绝；base 0.15.4/source-only metadata 限制和测试 E731 均保留。CLAIMED 后最终 freshness r3 正在独立 QA。
- [V19 r1 Store 核心](ctp-execution-v19-r1-independent-review-2026-09-26.md)：账户 family owner、generic/CTP UNKNOWN claim gate、V18 迁移 fence、release/reopen ABA 修复得到独立 SQLite/public-API 证据；root 核对 28 份源码/test、29 份 QA 文件和九份合成库。作者全包 240/2 属作者 manifest 记录；固定账本 V20 工厂和 clean-close owner handoff 不在此验收内。
- 主仓 67 项桥接扩大回归出现 63 passed / 4 failed。两项旧 Store double 缺新接口；真实 offline L2 fixture 仍 pin execution 0.1.0，与当前 0.2.0 不符；另一个 cancellation fake journal authority 恢复仍待定位。不得把这些失败当作新 gate 正常拒绝而略过。
- [G1 anchor r5 / Guardian r1–r2](ctp-g1-anchor-r5-guardian-r1-r2-independent-review-2026-09-26.md)：独立 68/38/39 项已归档，r2 仅修新 OS-token route 的进程 fail-stop，legacy helper 残余另修。跨 Session stdout 继承由新有界命名管道替代中；全部 request-specific anchor/config/dependency/receipt 工作须移入由独立固定服务监督的子进程树。客户端 timeout 或 kernel kill-on-close 本身不等于已观察到 Job empty。
- [旧路径账本切换合同](ctp-v19-account-ledger-cutover-design-2026-09-26.md)要求复用原有账户 journal 文件与 flow lock，拒绝旧历史后才可建立新的精确账户身份；公开组合不接受 caller Store/path/root，不新建第二账本绕过未决状态。

以上没有使用真实配置/账户、原生 provider、真实服务安装或交易请求。统一 wheel、整合回归、平台/长时矩阵和真实 CTP 验收仍未完成。

## V20 结构检查、CLAIMED 时间边界与服务编排增量

- 根代理使用 V20 r0 实际工厂复现同名 trigger 改坏后仍被接受；[反例与安全重启审计](ctp-v20-schema-counterexample-and-clean-handoff-audit-2026-09-26.md)保存原始合成库和两次脚本。首次脚本没有显式关闭 DDL 连接，提前记录的持久化哈希已更正；错误 schema 被接受的结论在显式关闭连接后再次复现。V20 r1 已加入代码定义的完整 schema 比对，作者 256 passed / 2 skipped，独立 QA 正进行。
- claimed-phase 新修复使用最终 trusted-clock sample 核对原 Store binding expiry，作者 98 项通过。此前独立测试从 main CWD 导入 mutable runtime，故其“冻结 r3”通过和反例来源归属暂时无效；原日志保留为诊断，使用独立 CWD 与进程内 origin/hash guard 重跑。后续完整冻结 r4 仍需单独复验。
- [Guardian pre-orchestration](ctp-g1-guardian-preorchestration-independent-review-2026-09-26.md)独立 41+1 通过；7 项 Revert/fail-stop 是 41 的子集。两 helper 失败立即终止路径已局部接受，未运行真实终止 API或服务部署。
- Windows 官方要求同一 Job 中进程同 Session，故 Session0 coordinator 不能直接包含原交互 Session worker。后续设计将 owner primary-token 的固定 Session0 变更限制在单请求服务身份 coordinator 内，保留用户安全属性并检查 SeTcb/恢复；仅开发与离线验证，未改变实际 token 或安装服务。三个 result schema 与独立 token-bootstrap 控制管道正在实现。
- SDK29 的 eager DTO 导入令三根 sealed runtime 意外需要 requests。新隔离修订 `e75b70a8103fa21e5da3a446c35b7ca6a8047d41` 使用保留 API 的 lazy exports，作者容器测试 134 passed；后续双构建/严格消费尚未完成，旧 SDK29 wheel 不被覆盖。

用户要求的真实模拟交易和实盘交易尚未验收；默认 route 继续关闭。全部本轮记录仍为离线开发和合成测试结果。
