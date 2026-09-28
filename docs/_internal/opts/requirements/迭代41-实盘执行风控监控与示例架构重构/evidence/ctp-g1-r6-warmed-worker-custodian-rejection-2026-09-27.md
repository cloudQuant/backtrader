# G1 r6 预热 worker/custodian 假模型独立拒绝（2026-09-27）

裁决：`REJECTED_FOR_HARD_WHOLE_COMMAND_DEADLINE / G1_REMAINS_CLOSED`。r6 尝试让 custodian 在准入前持有 fake worker、Job 和控制 token，worker ready 后才接受单次请求。冻结候选的 pytest、unittest 各 `20 passed`，但同步 `put_nowait` 在等待结果前运行；注入的队列入列卡住使调用者在 180 ms 截止后仍阻塞 70 ms，释放后返回 `UNKNOWN` 并保留控制。这一状态分类是 fail-closed，不能补足整命令调用返回的硬截止。

独立 QA 核对候选 manifest `3053ce67aea77fa7b1486837adbdd20d4de86343182e687d4c511ebcec1380e7`、冻结回执 `646e4817126272f263f3681ffeb6c994497f633a255daf72196e41187f6ea017`，以及 18/18 个声明 payload；另在独立副本复跑 pytest `20 passed`、unittest `20 passed`、py_compile 和 Ruff。负探针再次观察到 55 ms 逾期、`UNKNOWN` 和保留控制。独立 QA 回执 SHA-256 为 `7909a5f6f9281e442d2b9bba44ac2401df6c659c440a67505ab9d1eda9f4cd00`。

root 对原始候选与 QA 回执逐项复核大小/摘要，并将 37 项文件封存到[原始归档](ctp-g1-r6-warmed-worker-custodian-rejection-2026-09-27.raw.zip)；ZIP 完整性及内部摘要通过，归档 SHA-256 为 `b4b79a7cf2c99b45c70d338cb9ef275bdab1eb4b6619dfc77876d488de53c1fb`。该实验全是 Python 惰性假模型，没有真实 Windows Job/service、CTP、provider、凭据或默认 preflight；不得作为 G1 正面验收。下一候选需要受信进程外 custodian 在整个请求截止内提供可观测的进程/Job 持有、退出和清理证据。
