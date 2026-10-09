# R3 验收记录：012_2 四件套化 + 双所 Demo 门（2026-10-09/10）

状态：**实现与迁移完成；Demo 成交往返 = 证据化 BLOCKED（候选研究状态结构门，按设计）**。

## 本轮范围

- 012_2 标准四件套：`run.py`（dry / `--replay` / `--live --allow-write --mechanical-smoke`）、
  `config.yaml`（新增 `entry` 段）、`event_driven_strategy.py`（原 strategy.py）、`README.md`（重写）；
  旧引擎 → `legacy_runner.py`（导入/校验适配）。
- manifest 刷新链：canonical（`strategy_module`、runner/strategy/config 哈希、candidate_sha256）
  + folder-local（`--check` 通过）；`.gitattributes` 路径更新。
- 测试更新：8 个 012 相关测试文件（含 `tests/performance/test_cross_exchange_event_path.py`
  与 `tests/unit/strategies/test_012_2_event_cross_exchange.py`）的模块路径与策略文件名锚点。

## 门结果

| 项 | 结果 | 证据 |
| --- | --- | --- |
| dry | DRY（config+entry+凭据 env 名；零网络） | 输出 JSON |
| replay | FORMULA_CHECK_PASS（0 网络/0 写单） | `evidence/replay-*/report.json` |
| 测试切片（8 文件 466 项） | 465 passed / 1 failed（012_1 基线时间门，见 r2 记录） | 会话日志 |
| refresh `--check` | 两目录 up to date | — |
| Ruff | run.py clean | — |
| Demo 链路 | store 构建/准入通过 → **执行门拒绝** | `evidence/live-20261009T191708Z-7c59c5fd/run.json` |

## Demo BLOCKED：`execution requires immutable direction/first-venue/fee/depth/latency path models`

- 事实：`event_path_models_from_candidate()` 在 `research_status != "PASS"` 时返回空；
  `_run_network_impl` 对 `paper-live/demo` 强制要求非空路径模型 → 本候选
  （`RESEARCH_REJECTED` + `HFT_FAILED`）**按设计不可执行**；manifest
  `event_path_models=None`。这正是 AGENTS/迭代21 记录的
  `HFT FAIL/NOT_ADMITTED`（需端到端延迟、队列与真实成交证据方可准入）。
- **翻转路径**：完成迭代21/30 的 HFT 路径模型准入流程（产出 OOS 方向/首场所/费率/深度/
  延迟模型并置 `research_status=PASS`，刷新 manifest）→ 原命令直接复跑；
  属研究/取证治理工作，不在迭代42 范围。
- 本轮为此门补充了**结构证据**（此前该门在示例层不可达；四件套入口与 manifest 链已就绪）。

## 附带修正

- 012_1 README 按既有测试契约补齐免责声明与 `python -m examples...run` 调用形式（R2 收尾项）。
