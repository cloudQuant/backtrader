# G1 双阶段 r3 与 Windows 惰性 custodian 独立 QA 复核（2026-09-27）

## 裁决

三条输入各自独立留证，均不构成真实 G1/生产验收；默认 preflight/实盘路由继续关闭。没有使用 CTP、凭据、provider、私有配置、SCM 服务或默认路由。

## 三条独立输入

| 输入 | 冻结身份与独立检查 | 结果与边界 |
|---|---|---|
| 双阶段 r3 fake host | manifest e30f2f21ab714f90c82ce33bdf9c290a533477f19fcd59f5b8d931238c38b399，36/36 payload SHA/大小匹配；独立四文件焦点 83 passed / 34.02s，exit/frame 矩阵 4 passed / 1.08s。伪造 OBSERVED frame 加 coordinator 外层 exit 2 的服务负例 1 passed。 | 服务将该 frame 降级到 UNKNOWN/worker_failed；这是 fake 状态分类回归，不证明外部 Job custodian/完整命令期限。R2 原始 33/1 flaky oracle 记录仍保留。 |
| 原始 R7 Windows inert probe | 只从不可变原始 ZIP ctp-g1-r7-windows-inert-custodian-rejection-2026-09-27.raw.zip 解包；ZIP SHA 7a642ce3af9bf92bca4af21d75f1d8a423d339b626e2867eafba7a76e21555ee，manifest SHA afdc99be96a1ad4961235e358f9069070a5bafe2d051db9f59e2ff94fc8f9d7d，14/14 项吻合。9 场景重跑。 | 同步准入 WriteFile 在 1800 ms 仍阻塞，caller Job 被杀，UNKNOWN，1813 ms；overlapped 为 UNKNOWN/exit 54、cancel_completed=0，没有持久 I/O reaper/context。作者目录 freeze 后的源码/runner 漂移单独记录，未用于复跑。 |
| R7 teardown-r2 Windows inert probe | manifest 8a46c8e16a0fa68f0229dbe995e6f34da60a2ef7ea7441655131a10c7409abde，14/14 项核验；独立副本重跑 9 场景。 | teardown 现在只在 worker exit 非 STILL_ACTIVE 且 Job 活动数为零后释放 worker 控制；两项 UNKNOWN 后均观察到 worker exit 0/Job 空。同步 caller 仍在 1800 ms 被判阻塞并强杀，完整度量 1812 ms；overlapped 仍 exit 54/cancel_completed=0，无 caller-side I/O owner/reaper。事后清理不能补算 caller deadline。 |

## Evidence ZIP 与逐项摘要

- 双阶段 r3 QA ZIP：ctp-g1-two-stage-r3-independent-qa-2026-09-27.raw.zip，SHA-256 4096b57a9db4637ed189c4d1cb5cfc96b4e19c902b6dc3dd4ab7b0036fcb1d7a；55 项，testzip 通过，逐项摘要 ctp-g1-two-stage-r3-independent-qa-2026-09-27.raw.contents.json SHA-256 96a1a4421f895c09e57ed87db8bb539763e5a8abe36a5c47f781ba3c4e59d048。内含 36 个冻结 manifest payload、QA 收据、日志与负测脚本。
- 原始 R7 使用的不可变作者 ZIP 如上；独立 R7 QA 归档 ctp-g1-r7-windows-inert-independent-qa-2026-09-27.raw.zip，SHA-256 9267220761cfab1953ba983ca0f11f6ed0c323043cefae3578b8db9bbb25287b。复核文本见 ctp-g1-r7-windows-inert-independent-qa-2026-09-27.md。
- R7 teardown-r2 QA ZIP：ctp-g1-r7-teardown-r2-independent-qa-2026-09-27.raw.zip，SHA-256 84878618021fc6fb558bce855099985ac665e5d3ea4a74f46ca7f2c67d67196c；19 项，testzip 通过，逐项摘要 ctp-g1-r7-teardown-r2-independent-qa-2026-09-27.raw.contents.json SHA-256 d14aac07689f498332d99a095e91e1686ff5cc315da8a3ce2f6f0f263dd54208。依照本次文本证据范围，ZIP 未含 .exe/.obj；它们仍在 frozen manifest/14 项独立核验中。完整作者原始包另存于 ctp-g1-r7-teardown-r2-author-2026-09-27.raw.zip。

## 归档边界

r3 与 R7T QA ZIP 分开保留，原始 R7 ZIP 与 R7T 是另一条独立输入；不把测试结果合并为一个候选，也不修改任何 frozen source、checkpoint 或 matrix。各回执与原始运行日志均保留在相应 ZIP。最终结论：G1_CLOSED。