# G1 output-channel r6：post-resume 局部独立验收

独立复制、逐字节核对五份冻结源码/测试，Windows watchdog 与输出通道焦点 `56 passed / 0 failed`。新增 post-resume hook 在确认 ResumeThread 后、第一次 poll 前只执行一次；回调拒绝、异常或截止时进入 UNKNOWN/清理，不能发布 frame。r4 的来源绑定、进程退出、Job 清空、EOF/close 与构造失败清理合同继续覆盖，r6 额外拒绝 timed-out 结果读帧。

该局部验收不证明 service 的完整两 Job 监管、Session0 token 转移、受保护部署或 native CTP。G1 仍 `NOT_PASSED`。[机器记录](ctp-g1-output-channel-r6-post-resume-independent-review-2026-09-27.json)与[原始归档](ctp-g1-output-channel-r6-post-resume-independent-review-2026-09-27.raw.zip) SHA-256 `cf42a4a5a7340315ee568c04be236c760b14d23f31812009151eb66229a66764`，10 项。
