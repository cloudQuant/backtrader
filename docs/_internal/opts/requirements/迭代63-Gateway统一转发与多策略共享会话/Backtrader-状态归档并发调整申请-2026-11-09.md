# Backtrader 状态归档并发调整申请

日期：2026-11-09。状态：待用户确认。该申请仅针对已复核的本地状态并发问题，不改变交易语义，不授权账户操作。

## 问题和证据

`GatewayPendingHost` 的保存方法持 `pending.lock`；`rebind_identity(mode="new_instance")` 持 `run.lock` 和 `identity.lock`，检查 pending/waiting 后归档整个 state 目录。独立宿主或 CLI Store 写入不要求持有 run.lock，可能在检查后写入即将被归档的目录。现有 Gateway 宿主尚无 Broker/Store 生产调用，不能用 direct Broker 的运行锁生命周期推断它已安全。

仅延长 state 内 pending.lock 不足：POSIX 等待者可能拿到旧 inode 的锁，之后按旧路径访问新 state；Windows 重命名前又必须释放内部文件句柄。该问题通过源码与调用图确认，尚未用并发重现实验证实；实现时须先做确定性交错复现。

## 请求批准的限定调整

- 在策略根目录增加一个不随 state 归档的持久协调锁；沿用现有可信本地目录、FileLock 和原子写入设施，不新增数据库。
- 让 PendingCommandStore（包括 GatewayPendingHost）、WaitingOrderStore 的读写及 new_instance/move、身份初始化/绑定、运行锁取得遵守统一外层锁序。具体入口为 live_state/_common.py、pending.py、waiting.py、identity.py、state_dir.py 和所需内部锁辅助。
- new_instance 在同一协调临界区完成身份检查、未决检查、归档及新身份创建。已持外层锁的检查使用内部入口，避免非可重入锁自锁。运行锁获取维持非阻塞，避免长持 run.lock 的运行实例与协调锁互等。
- 检查 SequenceAllocator、快照和审计的现有独立写入口；凡会跨身份切换访问 state 的入口，纳入同一协调或明确按原实例拒绝。只调整本地状态原子性及代际核对，不改 Cerebro、Order/Position/Trade、策略调度或 provider。
- 保留旧文件格式和审计证据。升级时须停止旧版本独立写入者；协调只约束遵守新协议的进程，不宣称防恶意写入、网络文件系统或跨主机互斥。

## 验证和交付

先复现检查后保存及反向交错，再覆盖两个进程的 pending/取消/waiting 保存、重绑定中启动、失效旧 UUID、锁超时与崩溃释放、路径别名、已有 live_state/direct 回归。Windows 实机检查另列，未运行不得报通过。输出限定 diff、原始测试日志和审阅报告后，按 dev 小轮提交流程交付。

需要确认的原因：用户要求 BT 架构调整事先批准。之前的批准覆盖 Gateway pending 逻辑预留和现有 Broker/Store 接线；这里增加跨状态目录归档的统一锁协议，涉及 waiting/身份/启动等入口，不能自动视为此前批准范围。

## 状态更新（2026-11-10）

用户已于 2026-11-09 批准。R34 已按本申请实施（BT `47f12e588`）：确定性交错复现在旧代码上失败、修复后通过；覆盖两个进程、持锁崩溃、锁超时和路径别名。Windows 实机未运行，不报通过。待独立复核，未标为 ACCEPTED。
