# CTP SDK：完整回调入口与锁外生命周期源码验收

日期：2026-09-26。裁决：`LOCAL_SOURCE_FAKE_PASS / NO_WRITE / LIVE_NO_GO`。

**后续实际组合阻断：** 主仓两笔 submit 路径通过后，fresh-target cancel 暴露
`OrderActionRef` 跨层类型错误：本地 CTP header 为 `int`，SWIG setter/getter 也是
int，而 SDK/执行账本候选使用文本 `action.<digest>`。真实 setter 会拒绝该值；
严格 callback capture 也会拒绝。以下 457 项保留为 f90568 源码检查点，不能证明
可用的 native cancel 合同。SDK 制品验收已暂停，正在统一整数分配/持久化/关联。

隔离候选在基线 `07012dda628c8c0d7fefa6e1b925f7f8b3f8f518` 上，仅提交本轮
13 个已审文件为 **`f90568c15196f1507f13d3fe0ad661f92d270bee`**，提交后工作树干净，
未 push。完整 wheel、native/provider 会话、execution v16 与主仓组合另行验收。

## 已核对的行为

- Trader SPI 的全部 **155** 个回调有固定分类和有界、不可变字段快照；sink 在
  native 创建/注册前安装，先 durable append/精确 ACK，再调用旧 handler。
  密码、认证码、自由文本 ErrorMsg 等不进入快照；账户关联字段仍是私有账本数据。
- 账户 owner 与每笔命令分离。Store-issued session/native binding、确切 API/SPI、
  source generation 和 one-shot lease 在派发前后复核。
- 原生 startup/Req 不持 SDK 状态锁。引用计数在异常（含 BaseException）路径归还；
  stop 与 callback 竞争时，旧 API/SPI 留存至引用排空和必要的 Join 完成再释放。
- MD 的跨线程连接 callback、RegisterSpi 中 stop、阻塞 Init 期间 stop、Join 前
  不 Release 等均有有界 fake 验证。它们不证明厂商的真实 Init/Join/Release 有界。
- Req 仅精确 `int(0)` 可作为本地排队结果；None/bool/float/nonzero 均拒绝。
  Req 期间 stop、断线、API 或 SPI 替换会得到 ambiguous 并 poison owner。
  本地排队不等于 provider ACK。

## 回归与修复经过

新入口焦点通过后，独立 QA 将旧 shutdown/feed/query/identity 测试合并复跑，暴露
真实 ABI submitter 接缝被不必要的 Req getter 提前遮蔽，以及五个裸 `object()`
SPI 夹具不再符合必需来源属性。修复使用注入 submitter 的分支、保留稳定 ABI 错码，
并使夹具实际检验 source generation/epoch/API 属性。扩大关闭测试还发现 no-Join
延迟清理会两次 `RegisterSpi(None)`，现由 Release 路径只负责一次 detach。

原 `parents[3]` 猜测父仓位置的测试也改为正常包导入；最终测试显式提供固定 parent
与 base 来源，没有永久排除该测试。此前 `449 passed/8 failed` 与
`450 passed/6 failed/1 deselected` 为保留的失败检查点，不能改写为一路通过。

最终 14 文件并集：作者留存日志 **457 passed、2 warnings、52.29s**；独立 reviewer
同集合 **457 passed、2 warnings、55.57s**。Ruff、py_compile 和 scoped diff 检查通过。
两条 warning 分别是关闭相关插件后的 pytest 配置项，以及没有匹配本机的 `_ctp`
扩展而进入 Python fallback。测试没有加载 native、访问 provider 或私有账户。

根代理解析留存 JUnit，核对 457 项、零 failure/error/skip，并重新验证清单中全部
**81** 个 Python 源文件哈希。额外独立有界测试在 ReqOrderInsert 进行时替换 API
或 SPI，两条均返回 ambiguous、poison owner、线程退出。SDK→Store 的潜在反向
锁序取决于注入 verifier；本次未发现已部署的反向 verifier，不能称观察到生产死锁。

## 可复核材料

- [JSON 回执与工件哈希](ctp-sdk-f90568-managed-ingress-2026-09-26.json)
- [457 项 JUnit](ctp-sdk-f90568-managed-ingress-2026-09-26.junit.xml)、[stdout](ctp-sdk-f90568-managed-ingress-2026-09-26.log)
- [完整 Python 源哈希](ctp-sdk-f90568-managed-ingress-2026-09-26.sources.sha256)、[13 个修改文件哈希](ctp-sdk-f90568-managed-ingress-2026-09-26.changed.sha256)
- [精确命令](ctp-sdk-f90568-managed-ingress-2026-09-26.command.txt)

这是显式源码集成结果，依赖 parent `62e683bc`、base `3de0fa4` 与主仓。
不构成 installed-wheel、原生 ABI、真实身份/行情/查询/结算、交易或默认路由验收。
