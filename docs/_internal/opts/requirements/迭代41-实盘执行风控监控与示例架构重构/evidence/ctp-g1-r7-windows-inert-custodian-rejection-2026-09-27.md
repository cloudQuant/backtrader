# G1 r7 真实 Windows 惰性 Job/IPC 探针（2026-09-27）

裁决：`REJECTED / G1_CLOSED`。此隔离 C++/Python 探针首次用真实 Windows Job、进程和命名管道构造预热 worker：先创建挂起进程并分配 Job，验证成员关系及 `ActiveProcesses=1`，再恢复 worker、等待 READY/IPC，并启动独立 caller Job。正常路径观察精确 worker 退出和 Job 清空后才释放控制；三进程后代场景观察到 `ActiveProcesses 3→0`。这些是惰性 OS 机制证据，没有 CTP SDK、凭据、provider 或默认 preflight。

九个场景中，同步 named-pipe `WriteFile` 在 1800 ms 请求期限仍卡住，外层只得终止 caller Job；整段耗时 1828 ms，caller 未正常返回，worker 控制仍在 `UNKNOWN` 下保留。overlapped 路径返回 `UNKNOWN` 时 `cancel_completed=0`，没有持续存活的 I/O owner/reaper，不能证明 OVERLAPPED 与 buffer 可安全释放。其它卡住场景只是在 create_process/pipe/token/receipt **之后**注入阻塞，未证明这些 Win32 调用内部有截止。预热及 IPC 连接在预算前；custodian 与 watchdog 仍在同一 harness 进程，外层 Python runner 不持有 Job 句柄。因而完整 caller-return 截止与独立句柄托管仍未建立。

冻结 manifest SHA-256 `afdc99be96a1ad4961235e358f9069070a5bafe2d051db9f59e2ff94fc8f9d7d`，14 项 payload 大小/摘要经 root 核对。作者回执 SHA-256 `4ea445c32e5ef34102b7b29b4d122982d4a1161766eb703a31d097e05c99119e`；场景 JSON SHA-256 `d95f9e73009e9ae7d52f97a572c559b5ee32c65a7d81058598af5f624f9d0caa`。[原始归档](ctp-g1-r7-windows-inert-custodian-rejection-2026-09-27.raw.zip)含源代码、构建日志/制品和原始场景，共 17 项，ZIP 完整性及内部摘要通过，SHA-256 `7a642ce3af9bf92bca4af21d75f1d8a423d339b626e2867eafba7a76e21555ee`。[独立 QA](ctp-g1-r7-windows-inert-independent-qa-2026-09-27.md)从该 ZIP 展开并复核 14/14 项，在新的 Windows 副本重放九个场景：同步准入仍在 1800 ms 截止卡住，实际 1813 ms 且需终止 caller Job；overlapped 仍无已完成取消或 I/O owner。[QA 原始包](ctp-g1-r7-windows-inert-independent-qa-2026-09-27.raw.zip) SHA-256 `9267220761cfab1953ba983ca0f11f6ed0c323043cefae3578b8db9bbb25287b`。G1 的受信服务部署和完整截止仍不通过。

归档完成后，作者在原 `D:\temp` 目录追加 teardown 观测，导致 `g1_win_lazy_probe.cpp` 和 `run_r7_scenarios.py` 与旧 manifest 不再匹配。root 的归档前 14/14 核验与不可变 ZIP 仍对应上文原版；后续独立 QA 从该 ZIP 的原版字节展开。新增 teardown 观测须另起版本、manifest 和回执，不得覆盖本记录。
