# G4 假 native 关闭阻塞与 Windows Job containment 独立复核

**局部接受：**在两种假阻塞（`RegisterSpi(None)`、`Release()`）下，原探针与独立等价复跑均观察到超时、Job 终止调用成功、子进程退出及 Job 清空。独立复跑使用纯 Python 子进程，未加载 SDK 或 `_ctp`。原 SDK 焦点 28 项通过；更宽一轮保留 `62 passed / 1 failed / 1 deselected`，未伪装为全绿。

e75 的 `stop_and_wait(timeout)` 在计时 Join 之前同步执行关闭调用，故该 timeout 不覆盖卡住的 `RegisterSpi(None)`或 `Release()`。本地 Job containment 只是超时后的隔离能力，不是 clean native close。没有真实 CTP mapped-module、会话、原生 Join/Release 回执或完整 G1 服务链；G4 仍 `BLOCKED`，默认 `NO_WRITE / LIVE_NO_GO` 不变。

[机器记录](ctp-g4-fake-stop-job-containment-independent-review-2026-09-27.json)与[原始归档](ctp-g4-fake-stop-job-containment-independent-review-2026-09-27.raw.zip)保存两方脚本、测试日志、源码及二进制摘要；归档 SHA-256 `aafcd870ba307b2e29a3ac4e60bca547640c8c98f66549a0adde18d7e3639a87`，共 23 项。
