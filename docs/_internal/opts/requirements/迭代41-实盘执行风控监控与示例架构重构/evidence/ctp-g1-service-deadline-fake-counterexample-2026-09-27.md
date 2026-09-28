# G1 服务端整命令截止反例

**拒绝当前整命令 hard deadline 声明：**精确来源的假服务探针在 worker Job 已空、控制句柄已释放后，让同步 `create_receipt` 跨过请求 deadline 并持续阻塞；独立 250 ms 监督等待后 handler 线程仍活跃。放行假调用后 handler 返回 `observed`，但没有迟到 pipe 响应。root 在独立目录重跑得到相同关键字段。

静态调用序还表明 anchor/dependency 身份校验和部分启动设置发生在 worker watchdog 外。测试完全使用 fake OS/服务接口，没有真实 SCM、Job、CTP、网络或私有配置；不能据此声称真实服务进程可被外部终止。普通 CTP `preflight` 继续 fail-closed，G1 未通过。

[机器记录](ctp-g1-service-deadline-fake-counterexample-2026-09-27.json)与[原始归档](ctp-g1-service-deadline-fake-counterexample-2026-09-27.raw.zip)保存精确源码、脚本及两份复跑；归档 SHA-256 `8458cb2dafda5e7af082ae502b87671608f897ab9433dcb450e4a9a1663ceceb`，共 11 项。
