# bt_api_py V2 独立对抗审查

> 历史快照：本文保留 V2 审查当时可复现的问题，不是 2026-09-08 最终候选状态。
> 后续修复和未闭合阻断项以 `final-implementation-review.md` 为准；原反例和结论不回写。

- 审查对象：`/Users/yunjinqi/Documents/new_projects/bt_api_py`
- 审查性质：独立只读代码、离线故障注入与测试审查
- 审查结论：`NO-GO`
- SDK Gate：`FAIL`
- 联网与凭据读取：`NOT_RUN`

审查时 root SDK 聚焦回归 152 项、Binance 11 项、OKX 14 项通过。下列反例仍可直接复现，
因此局部回归通过不能形成单 writer、迁移或 L2 连续性验收。

## P0 阻断项

| ID | 反例 | 影响 | 必须修复 |
| --- | --- | --- | --- |
| SDK2-P0-001 | 同一 provider/environment/credential 使用两个任意 `account_id` label 和两个 journal，两个 session 都能持锁 | 同一真实账户出现两个 writer | lease identity 加入非秘密 credential fingerprint/认证账户证明；label 仅作展示分区，不能取得第二 authority |
| SDK2-P0-002 | `fork()` 后父子继承 session、owner、epoch；固定 `time_ns` 后两边生成并持久化同一 client ID | 重复单号、双写 | 每次 ID 分配、journal append 和 dispatch 前校验 PID、owner token、registry epoch；fork 子进程必须重新建 session |
| SDK2-P0-003 | migration 报 `COMPLETE`，目标 row 仍含旧顶层 account label，与新 ledger identity 冲突，目标重开报 `unreadable_journal` | cutover 结果不可用 | 规范化所有 identity 字段；验收必须以目标身份真实 reopen |
| SDK2-P0-004 | remote reconcile 期间旧 writer 追加，migration 仍 `COMPLETE`；目标 1 行、sealed source 2 行 | 静默丢 intent | freeze 必须由旧 writer 在 append 时强制执行；发布前重读 hash/size/epoch；变化即中止且不得发布 |
| SDK2-P0-005 | 目标 authority/registry 先发布，旧源随后 seal 失败 | 两套 authority 可同时存在 | prepared/committed 可恢复事务；所有故障点可 resume/rollback；完成收据只在旧源不可写且新目标可重开后产生 |
| SDK2-P0-006 | Binance 没有生产首次 REST snapshot seed；gap 后也无自动 reseed；旧 snapshot bridge 验证失败前已经入队 | 永久无盘口或下游使用无效盘口 | 生产 initial seed/reseed 调度；锁住 WS buffer 与 REST seed；bridge 成功后才发布；失败发 stale/gap 事件 |
| SDK2-P0-007 | OKX gap/checksum failure 只清本地状态，没有 resubscribe/reseed 或显式 stale event | 策略可能继续使用最后旧盘口 | 自动恢复、退避和显式连续性事件；恢复快照成功前交易就绪必须 false |

## P1 缺口

1. 同一 identity 同时用于 spot/swap 时列表未去重，会自锁。
2. fencing epoch/owner 已写日志，但 load 与 append 未强制验证。
3. migration 的 embedded identity 可绕过 claim；remote reconcile 没有回显并绑定 source hash、
   epoch、identity 和订单集合；目标存在检查有 TOCTOU。
4. direct crypto Decimal wire 保持字符串，ZMQ schema/router 仍降为 float；canonical scale 尚未唯一。
5. OKX `books50-l2-tbt`/`books-sbe-tbt` 同时走 generic 和 L2 分支，单消息双发。
6. L2 sequence 容器转为 float，超过 `2**53` 失真；状态缺 WS/REST 并发锁。
7. 根 credential preflight 对空白、冲突 alias、`subscribe_account=False` 和错误分类覆盖不足。

## 已确认的正确基础

- Binance/OKX direct order mapper 使用非科学计数法 Decimal 字符串。
- write coroutine 取消会先把执行状态持久化为 unknown，再传播 `CancelledError`。
- 历史普通 `def async_* -> None` 会回退同步 twin，不把 `None` 当成 ACK。
- Binance 连续性使用 `pu == prior u`，OKX 使用 `prevSeqId == prior seqId`。
- 私有 REST/WSS 已有局部缺凭据 zero-I/O guard。

所有 P0 必须有独立反例测试；迁移必须通过故障点矩阵、并发追加与目标真实重开，L2 必须通过
首次 seed、gap 自动恢复、无效 snapshot 零发布和超大 sequence，SDK Gate 才能转为 `PASS`。
