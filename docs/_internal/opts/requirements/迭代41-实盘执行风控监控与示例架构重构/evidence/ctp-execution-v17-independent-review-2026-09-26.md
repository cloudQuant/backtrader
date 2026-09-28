# CTP execution V17：整数 ActionRef 与迁移的独立验收

**结论：仅接受已审的分配器、回调关联与迁移切片。** 本地提交为 `bb2cd24cdaf9fb64f6b95010ee8619b0c6a35589`，没有 push。r4 冻结清单 SHA-256 为 `be9415becf2a6a3fe32e667aae5437322d3b311c82db75f931c5ff8fe15cc0c1`。这不是 G5/G6 整体、统一 wheel、真实 SimNow 或 production 验收。

## 改动

- 账户范围的持久 ActionRef 分配器只产生正整数 int32，跨 scope/session/day 不复用。RequestID 独立，数值相同不代表两个身份可以互换。
- 原逻辑 payload 保持不变；SUBMIT 的 native payload 与逻辑值相同，CANCEL 只增加 Store 在 stage 事务中分配的整数 ActionRef。V2 native binding 同时绑定两个摘要和精确命令身份。
- CANCEL 回调查询使用 `cancel_target_order_ref`，随后继续校验 RequestID、ActionRef、目标和 session，覆盖同一目标的两条撤单关联。
- V16 历史文本 ActionRef 原值、请求 JSON 和 hash 保留，不强制转型为新派发权限。历史 CANCEL 所属账户保持永久 fence；旧未决派发保守转换为 UNKNOWN。
- 升级前检查全部历史 dispatch 的账户/scope 格式及 SQLite 外键完整性。损坏时整个升级回滚，不用空账户或错误账户建立无效 fence。

## 测试与独立发现

作者完整包为 **230 passed / 2 skipped**，Ruff、compileall 和 diff-check 通过。独立 reviewer 没有重跑完整 230 项；其实际范围为：

| 范围 | 独立证据 |
| --- | --- |
| 分配器、schema 焦点 | 6 passed |
| 原生 callback 映射和整数关联 | 15 passed |
| 两进程同账户竞争 | 独立连接同时 stage，获得不同编号；另一账户独立从 1 开始 |
| int32 上界、耗尽、重开及类型 | 最大值可分配，下一次拒绝且无额外命令；bool/text/溢出拒绝 |
| V16 历史迁移 | 历史值不变、跨 scope/day fence、READY/CLAIMED 不再派发、错误账户回滚 |
| 最终 r4 迁移焦点 | 4 passed，另有两套独立损坏库复现与回滚核对 |

独立 QA 先后找到了两个缺陷：r1 只验证 CANCEL 的账户字段，遗漏 terminal SUBMIT；r2 只验证合法前缀，遗漏账户与 reservation/scope 的关联损坏。最终基线库外键错误数为 0，仅修改 command 的账户键后产生 3 个错误；r4 拒绝该库并保留 schema 16、原行和错误集合。此结论证明已测的数据库完整性拒绝，不宣称 SQLite 文件具有防恶意管理员篡改能力。

r3→r4 只有一项持久回归测试变动，生产源码相同。分配器、allocation readback 和 stage 方法的抽取源码 hash 在早期快照到 r4 之间相同，已通过的并发/边界检查按该范围复用。原始独立收据把首版快照称为 r1，而作者把它称为 r0；完整路径与 SHA-256 是输入身份依据，短标签不作版本证明。

## 尚存缺口

V17 把撤单请求响应 ACK 与目标订单终态分开保存，但没有在账户 SUBMIT claim 中强制等待撤单目标终态。ACK 后、目标尚未确认终态时，新 SUBMIT 仍可能获准 claim。后续 V18 必须在同一账本中增加可追溯的撤单完成条件和统一 gate，不能把 ACK 改名为终态。这一已知限制排除在本次签收之外。

SDK native 来源、真实查询、审批密钥/撤销、账户级外部 writer fence、最终 service-owned dispatch、默认 route、平台和真实会话仍须另验。所有检查均使用合成 SQLite/fake 数据，没有访问私有 CTP 配置、凭据、真实 provider 或原生客户端。

## 原始材料

根代理逐项复核了 28 个冻结源码/测试/配置文件和 37 个 QA 材料的 hash。见[结构化收据](ctp-execution-v17-independent-review-2026-09-26.json)与[源码、复现脚本、合成库及日志](ctp-execution-v17-independent-review-2026-09-26.raw.zip)。原始包 SHA-256 为 `3296fe41dbbb4a11bc25454b83e589ca9c09ddcb9bcf28887ac64fcf37f96a6c`。失败快照、复现和最终修复记录均保留。
