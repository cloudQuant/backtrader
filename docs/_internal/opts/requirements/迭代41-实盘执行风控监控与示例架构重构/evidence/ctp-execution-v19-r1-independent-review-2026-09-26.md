# Execution V19 r1 独立 Store 核心复验

**结论：接受本页列出的离线 Store 合同，不接受真实会话、重启交接或写入。** 冻结 manifest SHA `2558c4248d6e6a202ead02b8fc88d4ed0a3ab3a686a90e55a7fc2b02e4387e10`；Store SHA `0e4b48443a9672df662e0799def92fe2442ebb3d5427f2bfb93a5049b4fe16c8`。

作者 manifest 记录全包 **240 passed / 2 skipped**；本归档未包含全包原始日志，因此该数值明确归属于作者记录。独立 QA 的两项焦点 pytest 通过，并另执行下列真实 SQLite/public-API 检查，源路径均固定到 r1：

- 同 Store 的 sibling strategy/day 复用精确相同 family owner；跨 Store、重开和跨环境使用拒绝。两个连接竞争 simulation/live family ownership 只有一个胜者；大写 CTP alias 和非法 account-ref 拒绝。
- generic account 与 CTP family 两条 UNKNOWN 撤单路径均阻止另一策略/交易日的 submit claim，订单保持 `PENDING_DISPATCH`、attempts 为 0，无 provider 调用，也不依赖另一个 risk-freeze 写入已完成。
- V18 历史库升级到 schema 19 后持久建立 `unmapped_legacy_execution_history` fence，拒绝新 family owner。历史行/载荷保留；唯一明确允许的安全变化是 `family-live-ready-submit` 从 `READY` 转为 `UNKNOWN`，不是所有字节原样不变。

## 租约编号 ABA 的失败基线与修复

独立 r0 反例证明：释放 lease token 1 后，重取仍是 token 1；旧 WriterLease 能写入，旧 release 还能删除当前 lease。r1 不再删除编号行，而保留 `expires_at_ns=0` 的释放状态。独立 close/reopen 重放得到新 token 2，旧租约的 mutation 被拒绝、旧 release 返回 false，新租约仍能使用；两个 pytest 焦点还覆盖后续编号推进与同 Store owner 复用。

这保留后续编号，不会恢复旧版本已经删除且无其他记录的历史编号。跨版本在线切换不能把丢失历史解释为安全证明。

## 证据与范围

独立 review manifest SHA `606b93210231f71b86dbf2e7f77165cafe80f93b32ec4ff49939d8e68c042064`。[机器可读记录](ctp-execution-v19-r1-independent-review-2026-09-26.json)与[原始归档](ctp-execution-v19-r1-independent-review-2026-09-26.raw.zip)包含 r0 失败反例、r1 runners/logs、合成数据库及完整冻结 source/test 清单。

根代理重新核对 **29** 项 QA 文件和 **28** 项 source/test 文件；对归档的 **9** 份合成 SQLite 数据库以只读 immutable 模式独立执行 integrity/FK 检查，均通过且字节未变。根代理没有重跑上述独立用例。归档 59 条目，SHA-256 `bd1fbab1e5ce3e542a30463d1ac9f011827e700739cb768bad778451d2690643`。

新打开的 Store 仍不能恢复旧 CTP family-owner capability，正常关闭后安全交接尚未接受。固定账本路径工厂是后续独立切片；主仓组合回归另有失败正在处理。本记录不把这些待办判为通过，也不建立跨主机 writer fence、native/provider 会话或 `LIVE_TRADING_ADMITTED`。
