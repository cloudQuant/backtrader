# G1 r7 teardown-r2 作者增量（2026-09-27）

裁决：`AUTHOR_WINDOWS_INERT_DIAGNOSTIC / G1_CLOSED`。原 r7 归档后，作者将 teardown 观测移到新的独立目录与 manifest；原 r7 证据保持为独立版本。新增回执明确区分 caller-facing 决定时和之后的 worker 清理：同步管道准入在 1800 ms 截止仍卡住、1828 ms 后必须杀 caller Job，决定时 worker Job 仍有一个活动进程且控制保留；决定后的 graceful shutdown 才观察 worker exit 0、Job 空，然后释放句柄。overlapped 准入仍以 `cancel_completed=0` 返回 `UNKNOWN`，也只有决定后清理，未持续持有 pending I/O 的 reaper/context。事后清理不能补算进入请求返回预算。

新 manifest SHA-256 `8a46c8e16a0fa68f0229dbe995e6f34da60a2ef7ea7441655131a10c7409abde`，14/14 项 payload 大小/摘要经 root 核对。[原始归档](ctp-g1-r7-teardown-r2-author-2026-09-27.raw.zip)保存新源码、编译制品、九场景原始日志与回执，共 17 项，ZIP 完整性及内部摘要通过，SHA-256 `25e10f4992fcd9c22863220bed00206c2aea169a1fd4cf4324fc787fcea95515`。独立 QA 已完成；冻结副本复跑结果见下方独立 QA 复核。该惰性原型仍无外部受信 custodian、完整同步调用截止、CTP native close 或默认 preflight 接线。

## 独立 QA 复核（2026-09-27）

独立 QA 按 manifest 8a46c8e16a0fa68f0229dbe995e6f34da60a2ef7ea7441655131a10c7409abde 复制并核验 14/14 payload；九场景均在 6 秒外层 watchdog 内返回。独立复跑的同步准入仍在 1800 ms 后阻塞、杀 caller Job，UNKNOWN 决定时 worker Job 仍有一个活动进程；本次时长 1812 ms。之后 teardown 才观察 worker exit 0、Job 活动数 0 并释放 worker 控制。该事后清理不满足请求返回期限。

overlapped 准入仍是 UNKNOWN、caller exit 54、cancel_completed=0；之后的 worker 清理证明只约束 worker Job，不能补出 caller-side pending I/O reaper/context。结论保持 AUTHOR_WINDOWS_INERT_DIAGNOSTIC / G1_CLOSED，不接入 CTP/default preflight。独立记录见 ctp-g1-two-stage-r3-independent-review-2026-09-27.md；QA evidence ZIP SHA-256 为 84878618021fc6fb558bce855099985ac665e5d3ea4a74f46ca7f2c67d67196c，19 项通过 testzip 与逐项 SHA 核验。