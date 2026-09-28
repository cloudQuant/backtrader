# G6 配置到会话/请求的字段绑定反例（2026-09-26）

**结论：41 项 primitive/source compatibility 通过，完整授权适配器未接受。** 该基线已修复 trust snapshot 250ms freshness 截止与普通 key-map 可变性；真实 V17 r4 Store 探针在截止前领取成功、截止后拒绝且行保留 READY。它没有 native dispatch。

独立对抗用例用临时 Ed25519 key 和 fake revocation/fence，签发与合成封存配置不符的请求：Store 登录 BrokerID/UserID 不符，逻辑请求 BrokerID/InvestorID/UserID、InstrumentID、ExchangeID 也不符，仍通过 authority 并到达实际 Store CLAIMED。签名与 command/session 字节绑定不能替代配置字段一致性检查。修复必须在领取路径强制核对 fresh config、实际 session 与请求字段；SDK lease 本身没有 config resolver。

原始 V17 r4 反例 stdout、runner 与来源哈希已保留。V18 r0 compatibility focus 也有 41 passed 日志；QA 曾观察到 V18 同类 claim，但该次没有单独保存原始 stdout，因此本页不把 V17 log 冒充 V18 原始证据。旧主仓四文件只有原始 hash/focus XML，未另外保存源码副本，无法用后续工作树替代。

QA 整理时误将 runner 重跑到正在修改的 main resolver，新的代码在 claim 前拒绝。该 unfrozen 结果仅归档为诊断，不算修复独立验收。异常留下一个仅含合成数据的临时 SQLite 目录；显式 PowerShell 清理被命令自动审批策略拒绝，未绕过策略重试。新冻结版本另行复验。

未读取真实配置/凭据，未构造 SDK native client，未访问 provider 或派发真实操作。

## 原始证据

- [机器回执](ctp-g6-sealed-request-binding-counterexample-2026-09-26.json)
- [原始证据包](ctp-g6-sealed-request-binding-counterexample-2026-09-26.raw.zip)，SHA-256 `42619e140a3dd9e5ba8863506413146a82936defd9266a4e874ac59f66c05c90`。
