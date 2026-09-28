# G1 预启动 host r4：局部分类修复与独立负测（2026-09-27）

裁决：`LOCAL_FAKE_CLASSIFICATION_PASS / HARD_DEADLINE_NOT_PASSED / G1_NOT_PASSED`。

r4 manifest SHA-256 为 `ddc2965ce0595ce70f9c3152925a16799b1e67ea326e7c13392863210ffc4de1`。独立 QA 验证 manifest、候选文件、r3 反例、日志及 QA 副本 43 项哈希/大小；候选 pytest 与 unittest 各 `14/14`，另有同步卡住负测 `3/3`，合并 pytest `17/17`。QA JSON 回执 SHA-256 为 `4161fb2ba0d79a1ff440e4c38e19212d0c585657535f800ba593b4e95e51c51b`。root 核验 r4 manifest、候选/历史 QA 文件与独立回执后，将 41 份文件封存于[原始归档](ctp-g1-prestarted-host-r4-independent-review-2026-09-27.raw.zip)；ZIP 完整性和内部逐项摘要通过，归档 SHA-256 为 `2e570aac81a807069d55ff1c722fc9f9178620d40077780bb8e36670f48cde69`。

r3 的[晚到反例](ctp-g1-prestarted-host-r3-independent-rejection-2026-09-27.md)在 r4 中改为保守结果：`poll_host_ready()` 越过启动截止后不交付 host；同步 `terminate_job()` 或 `release_controls()` 晚返回时报告 UNKNOWN，不将迟到回执算作按时观察。释放失败保留 UNKNOWN；双请求只发送一次假帧。

独立阻塞探针同时证明，假 `terminate_job()` 与 `release_controls()` 在本线程阻塞时，调用者仍活过请求截止；解除阻塞后才返回 UNKNOWN。迟到终止路径虽保留 host 引用，但因截止后未转移托管，`controls_retained=false`。这不满足调用者硬返回期限，必须由另一个受信运行进程监督该 supervisor 并接管或终止其 Job。r4 没有真实 Windows Job/named-pipe 后端或 guardian listener 接线；同步 prewarm/CreateProcess 也在请求期限外。普通 CTP `preflight` 仍关闭。
