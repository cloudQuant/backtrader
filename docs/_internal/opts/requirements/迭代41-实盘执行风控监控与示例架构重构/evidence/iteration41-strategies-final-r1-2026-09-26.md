# Iteration 41 完整策略回归 R1（2026-09-26）

**结果：1,286 passed，0 failed，0 skipped，耗时 296.75 秒。** 测试命令为 `python -m pytest tests/functional/strategies -n 8 -q`，并保存独立 JUnit、临时目录和导入审计日志；完整参数及环境见原始记录。

运行使用隔离 venv 内的 Python 3.11.5、pytest 8.2.2 和 xdist 3.8.0；已补齐策略所需的 torch/seaborn。两份 input manifest 记录的 1,944 份核心代码、策略、数据、fixture 与测试配置完全一致，根代理再次核对全部文件 SHA-256。两份 environment 记录除生成时间外相同，但都生成于 pytest 结束后；其 before/after 文件名不能证明运行前环境采集。该范围不含正在并行修改的 runtime 集成代码，不能替代后续整合回归。

主进程与八个 worker 共九份 guard 日志仅有启动事件，未记录 SDK 来源导入、native、外网、受保护配置或来源越界事件。这个结论限于 harness 观测范围；未连接真实 provider。源码映射与 metadata shim 明确标为 source-only，不能作为已安装制品证据。

保留全部 4,165 条警告：3 条 pandas FutureWarning、4,159 条 statsmodels FutureWarning、3 条 loky 核数回退警告。JUnit 时间为 296.585 秒，pytest 控制台总时间为 296.75 秒。根代理复核记录和输入哈希，未重复运行本轮测试。


## 原始证据

- [机器回执](iteration41-strategies-final-r1-2026-09-26.json)
- [原始证据包](iteration41-strategies-final-r1-2026-09-26.raw.zip)，SHA-256 `7031e7eacab5778145f1a717a6a0f3ec25fb6ef08a9950d27a4beb59de5a8276`。

## 采集时序澄清

作者确认 input-before 清单在 13:52:04 UTC 写完，pytest 于 13:53:38 UTC 开始，JUnit 于 13:58:34 UTC 完成，input-after 清单于 13:58:58 UTC 写入。文件系统时间与该顺序一致，输入哈希也相同；这些时间不是可信签名时间线。两份环境清单均为运行后采集，此限制保留。
