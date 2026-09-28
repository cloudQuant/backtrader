# R3r3 唯一版本迁移隔离探针（2026-09-27）

裁决：`VERSION_MIGRATION_FEASIBILITY_ONLY / COMPOSITE_NOT_RELEASED / NO_WRITE / LIVE_NO_GO`。

隔离探针把 Execution R3r3 标为 `0.2.1`、parent 76 标为 `0.15.6`，分别从两份源码副本双构建 wheel。Execution 两份 wheel 字节一致，SHA-256 `0bdc90ea7cbd20c7b9856a608b9d355bb1f1e1a4f7d71aca575bb0ff1517a308`；parent 两份字节一致，SHA-256 `d37b734dc4cf908d1518651d38a936504b02f7a71754ec66ef53324fcc1e1dcc`。隔离目标安装的 RECORD、导入来源与 `pip check` 均通过；旧 `.2.0` 身份和混用摘要的负测通过。主工作树和默认 pin 未由此探针修改。

Execution 安装 wheel 包测试为 `284 passed / 2 provider-blocked skipped`；parent 假客户端焦点为 `356 passed / 2 POSIX skipped`。主仓隔离 overlay 为 `77 passed / 1 skipped / 16 failed`：14 项因未合入 V21 account-family-owner 接线，2 项因 parent 撤单发行器/控制端缺失。因而此探针不能作为统一 R3r3+V21 或 parent 控制端发行验收，更不能作为 CTP 写入或实盘准入。网络守卫在测试 lane 没有非回环连接；单独的守卫负测故意触发并阻断一次 DNS/连接尝试。没有原生 CTP 导入或私有配置读取。

root 对最终回执 SHA-256 `fee30bdafbbb928bc843918eb5e32bf967b18df9a623385542f1fbeebddcefd3`、四份 wheel 摘要及所归档文件逐项复核。[原始归档](ctp-r3r3-unique-version-migration-probe-2026-09-27.raw.zip)保存 28 项回执、manifest、JUnit、日志和两轮 wheel；ZIP 完整性及内部摘要通过，归档 SHA-256 为 `1b67dc089479788f7ad1a219e2a92e478e003e7384c286aa738ecd851c16a457`。
