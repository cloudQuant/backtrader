# G4 假关闭并发测试同步修复复核

**局部接受：**修改仅限两份隔离测试文件。假 API 在真正完成 `RegisterSpi(None)` 与 `Release()` 时发出同步事件，测试等待事件后仍断言原有精确调用顺序和退休会话状态；生产 SDK client 字节未变。冻结快照 267 份 payload 哈希匹配，作者重复目标 45 次通过、焦点 56 项通过；root 以精确来源独立复跑 `56 passed`。

root 首轮缺少主仓 `backtrader_runtime` 的 PYTHONPATH 导致一个导入失败，已保留在机器记录并以显式来源复跑。历史 62/1 并发失败证据不覆盖。此修复仅使 fake 测试确定；真实 native Join/Release 与 G1 服务链未验收，G4 仍 `BLOCKED`，`NO_WRITE / LIVE_NO_GO` 不变。

[机器记录](ctp-g4-cleanup-test-sync-independent-review-2026-09-27.json)与[原始归档](ctp-g4-cleanup-test-sync-independent-review-2026-09-27.raw.zip)保存快照清单、变更源码及双方日志；归档 SHA-256 `9e4be4d28fa623c86b735df89de9b6c58f51b3b65dd135b738fd4e9de34ac58b`，共 9 项。
