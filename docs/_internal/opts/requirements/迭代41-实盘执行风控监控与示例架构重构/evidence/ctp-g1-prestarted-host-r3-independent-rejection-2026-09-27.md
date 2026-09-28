# G1 预启动 host r3：独立截止反例（2026-09-27）

裁决：`FAKE_MODEL_ONLY / HARD_DEADLINE_REJECTED / G1_NOT_PASSED`。

候选 r3 manifest SHA-256 为 `548cb59b4437c0784a75c186a714c180ce0305c9df8b3f5213321610d9f9b01a`。独立 QA 核验 31 项冻结候选/源码/证据摘要，原六项测试通过；另外 17 项 QA 模块测试通过，其中五项定向反例过滤运行 `5 passed / 12 deselected`。其 JSON 回执 SHA-256 为 `00001c61fff1311b34edb79d118f44e8aeb8cbbfae3d7bb9f17f6323a8992dad`。root 将 QA 冻结源码、测试、日志、回执与候选 manifest 的 28 项文件逐项哈希封存于[原始归档](ctp-g1-prestarted-host-r3-independent-rejection-2026-09-27.raw.zip)，ZIP 完整性与内部摘要通过；归档 SHA-256 为 `152fd0d5cd30ab1f195684844c86a77a650db9bb222861e325f832425e30687d`。QA 消息中的 Markdown 回执哈希少写一个 `c`；实际文件 SHA-256 是 `50e6c0fcbc5b42e4ac4552d8e391d6d4a344bde73746868da84807742f2d6764`，归档使用实际哈希。

独立假后端复现三处截止问题：`poll_host_ready()` 在启动截止之后才返回 true 时，r3 仍报告 ready；同步 `terminate_job()` 与 `release_controls()` 可阻塞到请求截止之后才让 helper 返回。另两项负测确认释放失败保留 `UNKNOWN` 与 host 引用、并发双请求只发送一帧。这些局部 fail-closed 行为不修复越时返回。

候选没有真实 Windows Job/named-pipe 后端，也没有从服务 listener 调用该 helper 的接线；同步 prewarm/CreateProcess 仍在请求期限外。QA 时主仓 guardian 文件同时由另一开发切片修改，其哈希与 manifest 的 `main_current` 栏不同；冻结候选源码仍匹配 manifest，主仓漂移没有计入候选缺陷。r4 修复和独立复测前不得宣称整命令硬截止，普通 CTP `preflight` 继续关闭。
