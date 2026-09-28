# G1 token/control r2 独立复核

**局部合同通过，完整 G1 未通过。**冻结源码 73 项和独立 QA 85 项经 root 重算摘要且无额外文件；独立 origin-guarded Windows 聚焦 `60 passed / 0 skipped`。真实当前进程烟测只做 64 次 `TOKEN_QUERY`，本地命名管道只读取合成一帧并核对服务 PID 与 EOF。额外 fake 探针验证 ctypes SID 缓冲区存活、越界指针在读取前拒绝以及截断 SID 的有界读取。撤销失败只通过注入哨兵检查 fail-stop 顺序。

未调用真实 `DuplicateTokenEx`、`SetTokenInformation`、SCM 或 CTP。`_OwnerTokenControlServer` 尚无完整构造与调用，coordinator/worker/receipt-writer 双 Job 和整命令硬截止未证实。此前有释放后指针问题的 r1 快照已撤回，此结论只针对修复后的 r2。普通 CLI `preflight` 继续 fail-closed，`NO_WRITE / LIVE_NO_GO`。

[机器记录](ctp-g1-token-control-r2-independent-review-2026-09-27.json)与[原始归档](ctp-g1-token-control-r2-independent-review-2026-09-27.raw.zip)包含源码、日志、脚本与独立 QA；归档 SHA-256 `a95a40e7b1ce1272045a2e453381f9fe3b07efbf57c92065076d6a424efe2957`，共 160 项。
