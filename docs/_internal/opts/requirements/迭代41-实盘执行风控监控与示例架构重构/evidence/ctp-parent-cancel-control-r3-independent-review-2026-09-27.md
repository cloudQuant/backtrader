# Parent 撤单控制端 r3 独立 QA 裁决（2026-09-27）

裁决：**`FIRST_RELEASE_REJECTED`（本机有 monitor DB 写权限的并发 writer 威胁模型）；仅 local fake/offline。** 作者局部焦点能通过，但首次 RELEASED 清锁前的 readback 后窗口可使 audit 保持 RELEASED、monitor 事实被删且风险锁全清。此结论不等于远程利用，也不构成 G4、F14、CTP、生产或部署 PASS。

## 冻结输入和独立复核

- payload 根：`D:\temp\iteration41-cancel-control-r3-freeze-r1-20260927`；manifest SHA-256 `65af6f048a1148182b35a18b8998f738a306d83b5d33352bd469c809c3a8d28f`；154/154 文件匹配、无未列文件。
- evidence 根：`D:\temp\iteration41-cancel-control-r3-evidence-20260927`；manifest SHA-256 `210394a328c01695c8616189314715157ca5879a715881d378ee6c9ee07cb391`；112/112 项匹配。
- payload 独立副本 154/154 匹配。独立副本中的冻结焦点 `15 passed`。清点 manifest 只有 12 个 test 函数（参数化展开 15 项），不是任务文字中的 23 项；作者两份焦点日志也显示 15 passed。
- readback 竞态由同进程钩子和另一个本机 Python 进程分别复现。SQLite 只读 `quick_check` 覆盖 55 个数据库，均通过。

## 独立负测结果

- append 后、精确 readback 前删掉 monitor event：拒绝；control audit 留在 pending，unknown 与 release-progress 两锁都保持 active。
- 授权 callback 返回后过期、readback 后但写 RELEASED 前过期、以及 RELEASED audit 提交后清最后锁前过期：均走 fail-closed；两锁保留、`released_at` 为空或 audit 标 expired。
- CTP provider 标签在 authorizer 前拒绝；错误账户 fake authority 在创建数据库前拒绝；无真实 CTP/provider/network 调用。
- **反例（首次释放）**：只读精确 readback 成功后，另一 SQLite writer 在最终 `risk_gate.resolve_freeze(progress_cause)` 前删除 monitor 行。调用仍回报 `released=true`，control audit 为 `released` 且 `released_at` 已设置；monitor event 不存在；unknown 和 release-progress 两锁均 inactive。
- **反例（RELEASED replay）**：同一读回后删除也能返回 `released=true, idempotent=true`，且清除 replay progress lock。
- 独立进程 writer 以同一用户/本机文件权限打开该 monitor DB，删除 1 行并正常退出。这证明有 DB 写权限的本机进程可利用；没有证据证明远程越权或跨权限边界访问。当前切片无文件 ACL/所有权保护、持久读租约或跨库原子提交。

## 代码位置及归档

冻结 `cancellation_control.py` 的 `release_cancel_freeze()` 在 `1241-1256`、`1355-1369` 检查到期，`1325-1409` 完成首次 append/readback/audit/清锁；`_resume_released_command()` 在 `1618-1695` 有同类 replay 窗口；精确 readback 在 `1697-1759`，失败重申双锁在 `2010-2032`。readback 是一条只读查询，不会阻止另一个 writer 随后删除独立 monitor 库中的行。

原始独立 QA ZIP：[ctp-parent-cancel-control-r3-independent-qa-2026-09-27.raw.zip](ctp-parent-cancel-control-r3-independent-qa-2026-09-27.raw.zip)，SHA-256 `9986cd2218bbf6fd0514e18c0e33cd3b41ce0e22486d28930ba3fecd3df693d3`，90 members，89 个非清单 members 均按 QA `SHA256SUMS.txt` 的内容哈希复核，`ZipFile.testzip()` 为 OK。ZIP 收录收据、机器摘要、SHA 清单、复核脚本/日志和 readback TOCTOU 相关 SQLite 状态（含必要 WAL/SHM）；不重复打包巨大的 payload-copy。独立收据 SHA-256 `08f0eca3a3e0a2bea07647ee9207075e2faea66ea75e21a0e565139b523caf78`。归档的原始摘要清单 SHA-256 `c105749fdfb317ed6e1cc3c24e2e90c1a9a011481ecfe236f4a180e42dcc3338`。

冻结候选、主仓生产路由和默认 CTP 配置均未由该 QA 修改。主仓 bridge 的其他失败、73 项焦点以及真实操作员认证/原生终态不在此离线审查的通过范围。