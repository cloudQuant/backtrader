# Execution V18 撤单后账户封锁独立验收

日期：2026-09-26。结论：**所测 V18 本地 Store 合同通过**。

冻结快照为 `D:\temp\iteration41_v18_cancel_postcondition_r0`，基于 V17
`bb2cd24cdaf9fb64f6b95010ee8619b0c6a35589` 的五文件补丁。manifest SHA-256：

`0372771fbb91d3a6c6cc8d859eb4c68b6bbe65368a8672a8312f4ae9fa6e46b1`

root 独立重核 manifest 中全部 33 个文件、七份原始 V17 数据库、QA 回执与 JUnit，
保存 60 项原始材料。测试由独立 QA 执行；root 没有重复运行其测试。

## 已验证的合同

V17 的动态基线中，撤单请求 ACK 且目标订单非终态时，第二笔 SUBMIT 曾成功进入
CLAIMED；这只是 claim 复现，原生调用计数为零。V18 在同一数据库事务中登记
撤单完成条件，并以账户键阻止后续 SUBMIT claim，直到准确的目标订单终态与
已验证成交数量一致。

- 独立四文件测试：**155 passed / 2 skipped**。两个 skip 是当前 SDK 缺少
  callback queue consumer lease 的既有测试，不能算原生或安装组合通过。
- ACK 不解除封锁；订单终态与成交不一致仍阻断。终态先到/成交后到，以及相反
  顺序，都要求数量匹配才解除相应条件。
- claim 前发现目标已终态时，撤单拒绝；已经解除后出现矛盾，事务回滚仍保留
  durable owner poison。
- 新 V18 数据库的公开 API 动态测试：第一天未决撤单阻止另一策略、第二天的
  SUBMIT claim，命令保持 READY、`native_call_inflight=0`。

作者另外报告全包 **235 passed / 2 skipped**、Ruff 与 compileall 通过；该计数
未并入独立 155 项。

## 真实 V17 合成库迁移

每个源库先复制，再由 V18 打开并再次重开；原始库哈希保持不变。

| V17 状态 | V18 观察 |
| --- | --- |
| 未 claim 的 READY cancel | 转 UNKNOWN，不生成可能已发出的撤单完成条件 |
| generic CLAIMED / 已完成并收到 ActionACK | UNMAPPABLE pending，保持封锁 |
| 真实 session-owner 绑定的 CLAIMED | EXACT pending，关联唯一原 SUBMIT/owner |
| session-owner 绑定的 COMPLETED + ActionACK | EXACT pending；ACK 不能解除 |
| session-owner 绑定的 COMPLETED、无 callback ledger | EXACT pending，没有另一个旧 source fence 掩盖该条件 |

六种迁移/重开均为 schema 18，外键检查无错误，完成条件未被误解除。存在旧
callback ledger 的样本还会获得其既有生命周期 fence；QA 明确区分了这层封锁，
没有把 stage 早期拒绝当成 claim gate 的动态证明。

## 限制和后续

独立命令以冻结目录及 `PYTHONPATH=src` 执行，没有保留完整的同进程模块来源
清单。跨交易日动态测试使用 generic/no-owner 路径，因为 Store 的现行 durable
owner 合同不允许同账户第二个 owner；它与迁移 EXACT 样本是两份不同证据。
没有另加多笔撤单共享一个目标终态的并发压力测试。

V18 的账户键仍包含 environment。新共用模拟/实盘组合需要另一个持久化的
跨模式账户占用检查，不能从本次同账户键封锁推导该检查已经存在。
真实 SDK/provider、会话真实性、G1/G6 与 live 准入均未由本次测试关闭。

机器回执：[JSON](ctp-execution-v18-independent-review-2026-09-26.json)。
源码、数据库、脚本、迁移结果与日志：[原始材料](ctp-execution-v18-independent-review-2026-09-26.raw.zip)，
SHA-256 `792612e0bff309a79dd0965a96a29b4aff12fded55eb100389879cd29353c6fd`。

## 后续提交映射复核

根代理用 `git show` 核对 V18 提交 `33d132d6f9d16f64cc229f576435b0fafc6bfab1` 的全部五个变更文件：统一 CRLF/LF 后与冻结快照完全相同。四个快照文件采用 CRLF、commit blob 采用 LF，因此未声称原始字节摘要相同；两组摘要均保留在机器回执。此映射不覆盖后续 V19 修改，原始快照包未改写。
