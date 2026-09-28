# V20 r0 结构反例与账户安全重启审计

**结论：V20 r0 的结构校验未通过；clean handoff 仅完成设计审计。** 未访问真实账户、私有配置或原生 provider。

## 根代理复现的结构缺口

使用冻结 V20 r0 的真实 Store 工厂创建临时合成数据库，关闭后把 `ctp_account_store_identity_immutable_update` 的定义改为同名 `BEFORE UPDATE ... SELECT 1`。表、索引、触发器名称与账户 identity 均不变。只读分类仍返回 `CTP_EXECUTION_STORE`，工厂也成功打开，说明仅核对对象名称不能识别保护逻辑已损坏的数据库。

Store 源码 SHA-256 为 `f6d00212e6cbbc90144544996c9a6a7cf83571ae1466c4b2a896da02b7a7a117`。已显式关闭全部连接后的数据库 SHA-256 为 `b49a5807768f7b808e7dc0b1ed0141a87e8d66ae0378b8cc53f42b8b80e57181`，与打开前 `cbcee28fc96613ecaa38c487b34c083004912c63ce49ddfb5581481b7ee81238` 不同；不宣称该已接受的 writable open 没有写入。首份诊断脚本只管理事务却未显式关闭 DDL 连接，进程退出 checkpoint 使其提前记录的哈希失效，归档断言发现后已用新脚本复现，首份日志保留并标为诊断。两次都观察到错误 trigger 被接受。本例不声称隔离敌意文件控制；它直接否定当前“错误结构在普通构造/DDL 前拒绝”的合同。r1 正增加代码定义的完整 table/index/trigger 结构核对，需独立复验。

## 同文件安全重启尚未实现

独立审计绑定 V19 r1 Store 与 SDK29 源码。当前 owner 只有永久 ACTIVE/POISONED 路径；主仓 `stop()` 先写 poison，再调用无返回证据的 abstract supervisor。SDK 的可构造 stop receipt 记录局部 Join/Release 观察，但没有绑定 Store owner/session、API/SPI/source generation、最终 callback 序号及完整 drain 证明，不能用来解除账户 fence。

后续实现必须持久化 append-only owner generation 和 close attempt，先原子进入 DRAINING 阻断新发送，再由确切 SDK 来源证明调用/回调排空和 native 关闭，并在 Store 中核对全部账户历史、撤单后置条件与成交一致性。最终 CLOSED 证据及旧 lease tombstone 必须同一事务提交。任何崩溃、未知或缺少证明继续拒绝接管；不能只凭 `stop()` 返回、无活跃查询或 caller boolean 重启。进程死亡后的恢复还需要已验收的外部 supervisor。

完整只读审计及反例脚本、原始合成库见[原始归档](ctp-v20-schema-counterexample-and-clean-handoff-audit-2026-09-26.raw.zip)；[机器记录](ctp-v20-schema-counterexample-and-clean-handoff-audit-2026-09-26.json)保存来源与哈希。归档 SHA-256 `eb0a03087a3e702c47449d5463b41b94d315a83f01688e45b70aadcc1b984fbf`。此项不修改 `NO_WRITE / LIVE_NO_GO`。
