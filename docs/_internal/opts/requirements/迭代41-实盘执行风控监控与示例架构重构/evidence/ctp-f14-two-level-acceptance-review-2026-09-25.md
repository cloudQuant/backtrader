# CTP F14 两级验收可行性复核（非规范证据）

**状态：** `EVIDENCE_ONLY`。本记录不是第二份决策 ADR，也不授权任何报单或撤单。唯一规范提案为 [ADR-41-16](../ADR-41-16-simnow-f14-writer-fence-proposal.md)；原先并列起草的 ADR-41-17 已撤回并整理为本复核。默认状态仍是 `NO_WRITE / LIVE_NO_GO`。

**复核范围（2026-09-26）：** 官方 [CTPIIMini API v1.2](https://www.simnow.com.cn/DocumentDown/api_3/5_2_4/CTPIIMini_API_Ver1.2.pdf)、[SFIT CTP Mini API v1.7](https://www.simnow.com.cn/DocumentDown/api_3/5_2_4/SFIT%2BCTP%2BMini%2BAPI-V1.7.0.pdf)、[SimNow 产品说明](https://www.simnow.com.cn/product.action)及仓库当前只读/受管 CTP 合同。公开 CTP 查询按各自请求 ID 和 `bIsLast` 结束；已审接口未给出资金、委托、成交、持仓的共同快照版本，也未给出跨主机账户级 writer lease。该范围性发现不排除期货公司另有私有控制服务。官方 7×24 环境不提供结算服务，不能由 TCP 可达、登录或环境名称推出交易就绪。

## SimNow 有界操作性验收的真实边界

[ADR-41-16 的 option B](../ADR-41-16-simnow-f14-writer-fence-proposal.md)可作为独立 `Level S` 研发目标：先完成具名账户/窗口/合约/数量/风险上限/撤销与残余风险授权，再经唯一持久订单账本、本机合作进程唯一 writer lease、逐动作短时许可、真实 TD/MD 就绪、当前账户/TradingDay 结算确认查询、原生订单/撤单回调、精确 provider 回查与干净 native 关闭完成一笔有界测试。未知结果永久冻结，不能自动重派。全成订单不是成功撤单正例；成交与撤单应分成不同用例。

该结果只能叫 `SIMNOW_OPERATIONAL_ATTESTATION_TESTED`，不等于 `F14_PASS`、生产准入、账户级 writer 排他或共同快照。`CtpAccountFlowLease` 只约束同本机、共享状态目录且遵守协议的参与者；其他主机、OS 用户、手动终端或旁路 SDK 客户端是否存在仍为 `UNPROVEN`。若已知同账户有并行 writer，必须停止测试；潜在但无法技术排除的 writer 是需要明确接受的残余风险，不得写作 `account_writer_exclusive=true`。

凭据轮换/撤销、专用 VM、完整应用控制和 egress 流量取证能强化证据，但已审公开 CTP 接口并不提供这些功能；不要把它们作为缺一不可的 CTP 原语。两轮读数相同也不是同版本快照。操作性静默检查应保留逐请求身份、过滤条件、终包、订单与持仓对账；任何无法解释或无法观察的账户状态都停止写入，不能靠“看起来稳定”放行。

当前代码还不能执行 Level S：`CtpSimulationAccountWriterFence` 和 `_assert_writer_fence` 明确要求外部账户级栅栏，`_require_injected_authorities` 也无条件检查它。应新增与 strict fence **不可互换**的受限 SimNow 操作窗口许可及只证明单流来源/终包的观察类型；绝不能传入一个伪造 `CtpF14ExternalAdmissionClaim` 让现有 strict 路径通过。该候选应先只在 fake/隔离测试中实现，默认 inventory、CLI 和生产分支继续拒绝，直到各项真实前置和独立验收通过。

## 生产验收的外部依赖

生产账号沿用**同一个受保护 `config.yaml`、canonical `ctp:` 字段和同一个受管 CTP runner**，但账号与 mode 切换不会继承 SimNow 审批、制品、会话或操作性证明。Strict F14 目前要求可独立验证的账户级 writer 排他及同版本完整账户状态；已审公开 CTP 查询不能单独生成这些事实。若采用券商/清算服务或客户自建网关，须证明它是唯一凭据持有和写入通道、能阻断旁路写者，并提供经独立审查的完整状态一致性合同。仅把多条本地查询哈希起来或设置本机锁不足以作为证明。缺这种外部服务或等效证据时，维持 `LIVE_NO_GO`，在[验收矩阵](../ctp-current-acceptance-matrix.md)中如实列为外部依赖。

本次复核没有读取账户或凭据、连接 provider、产生真实报撤单、安装 SDK 制品或改变默认路由。