# R0 — 迭代 43 环境与失败基线冻结（2026-10-11）

本轮零代码改动。目的：先冻结可复现环境与既有失败，再规定后续轮次的"无新增回归"条件；不把"全绿"当作已具备的起点。

## 1. 环境与提交基线

| 项 | 实测值 |
|---|---|
| 主仓 | `dev` HEAD `322e501c1`（前置 `de3b65719` 源树 managed L2 退役、`94039354e` `010_live_examples` 整目录退役） |
| SDK | `D:/bt_api_py` `dev` `5163cbb7`（工作区 3 处脏，本迭代不触碰） |
| 解释器 | `C:/anaconda3/python.exe` → CPython **3.11.5** |
| pytest | **8.0.0**（仓库地板 ≥8.2 的既有约定在本机为 8.0.0，冒烟/回归结论以本环境口径记录） |
| 运行口径 | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`（与迭代 42 r11/r12 记录同口径） |
| 跟踪面 | `git ls-files examples` = **591**（后续 rename 覆盖率分母） |
| 既有无关脏项（保留不动，不入本轮提交） | `D 0`、`M backtrader_runtime/ctp_configured_front_check.py`、`M backtrader_runtime/ctp_simnow_operator.py`、`M tests/unit/runtime/test_ctp_simnow_config_operator_route.py`、未跟踪的 迭代1 `evidence/` |

## 2. 默认注册表（实核 10 条）

取 `backtrader_runtime.inventory.iteration41_runtime_registry()`：

```
example.012_1.midfreq_cross_exchange            simulation/replay
example.012_2.event_driven_cross_exchange       simulation/replay
example.013_1.midfreq_cross_arbitrage           simulation/replay
example.013_2.highfreq_calendar_arbitrage       simulation/replay
example.013_3.sa_midfreq_simnow.ctp_private     simulation/sandbox（私有只读，无 runner）
example.007_ctp.simnow_penetration.ctp_private  simulation/sandbox（私有只读，无 runner）
example.015.ctp_options_highfreq                simulation/replay
example.sample.ctp_legacy                       simulation/replay
example.007_ctp.legacy_direct                   simulation/replay
backtrader.iteration41.local_backtest_fixture   backtest/local_backtest（包内件，不在 examples 下）
```

后续轮次引用注册数前一律重新实测（本日内已出现 17→15→13→11→10 的波动）。

## 3. 冻结门禁基线（本轮全部实跑）

| 门禁 | 基线结果 | 备注 |
|---|---|---|
| `pytest tests/unit/runtime -q` | **746 passed / 23 skipped / 0 failed**，1 既有 warning，20.88s | 后续轮要求同数或仅因删除测试而减少，且必须逐项解释 |
| `C:/anaconda3/python.exe scripts/ci/smoke_iteration41_registered_offline.py` | **8 passed / 0 failed / 8 selected / 2 skipped**（2 项 = 私有只读 `SKIP_PRIVATE_READ_ONLY`） | r12 起首次全绿；r11 的 `8/1/2` 已被取代 |
| 守卫+示例聚焦：`test_examples_self_contained.py` + `test_iteration42_component_boundaries.py` + `test_iteration42_live_front_failure_evidence.py` + `tests/unit/scripts/test_iter28_fingerprint_probe.py` | **81 passed / 3 failed** | 3 项既有红，见 §3.1，逐条白名单 |
| `ruff check examples` | **176 errors**（48 fixable） | 本轮与后续只要求**不增加**该计数；`ruff check backtrader` 与 `ruff check backtrader_runtime` 均为 clean，作为硬门 |
| `make format-check` | **不可执行** | 本机 `python -m black --version` 报 `black, 0.0`（占位实现），且 `pyproject.toml` 的 `target-version = py312` 被其拒绝。因此本轮不以 black 为门，改以 `ruff check` 计数 + `git diff --check` 为增量门；**禁止**顺手格式化任何字节钉死材料 |
| `git diff --check` | clean（本轮仅新增两份文档；其中记录内 Markdown 硬换行与 EOF 空行不视为回归，沿用迭代 42 既有处置） | 混合 eol 属既有事实，保留原始字节 |

### 3.1 三项既有红（逐条，后续轮必须保持"不新增、不消失、不转 skip"）

| 节点 | 实测原因 |
|---|---|
| `test_examples_self_contained.py::test_example_folder_is_self_contained[000_live_certification]` | `optional16/components.py` import `bt_api_monitor`、`bt_api_risk`；`optional16/gateway_server.py` import `bt_api_transport_zmq`（迭代 41 组件正例矩阵的既有设计，非本轮引入） |
| `test_vendored_support_copy_matches_its_canonical_source[ctp_example_support.py0]` | `013_1` 副本与 canonical 字节漂移，首个差异在 index 525：`\r` vs ` `（CRLF/LF） |
| `...[ctp_example_support.py1]` | `013_2` 副本同类 CRLF/LF 漂移 |

R1 改造自包含发现规则时**不得**通过放宽 `_example_import_violations` 或忽略 vendored 比对把这 3 项转为绿；如需处理 CRLF 漂移，属独立轮次并单独验收。

## 4. 能力登记表（R0 交付；按可运行能力而非 import 关键词归类）

"离线入口"= 无 provider 网络可跑通的路径；"写"= 真实/模拟账户下单能力；"当前可用性"标注证据来源与验证轮次。

| 条目 | 类别 | 离线入口 | 在线入口 | 写 | 当前可用性 | 最小启动命令 | 验证轮次 |
|---|---|---|---|---|---|---|---|
| `001_multi_extend_data` | backtest | `run.py`（+`config.yaml`） | 无 | 无 | 可运行 | `python run.py` | R1 实测 |
| `002_hft_alignment_demo` | backtest | `run_backtrader.py` / `run_hftbacktest.py` / `compare.py` / `compare_all.py`（`common.py` 共享；无 config.yaml） | 无 | 无 | 多教学入口，非四件套 | `python run_backtrader.py` | R1 实测 |
| `003_hft_notebook_examples` | backtest | 同 002 + `prepare_data.py` | 无 | 无 | **`prepare_data.py:29` 有 `data.binance.vision` 下载能力**；`data/` 被 Git 忽略 | 必须 skip-download 或本地 fixture；缺数据明确拒绝，离线 sweep 禁止自动联网 | R1 实测 |
| `004_midfreq_demo` `005_midfreq_arbitrage` | backtest | `run.py`（内存 `MixBroker`） | 无 | 无 | 可运行（模拟撮合属正常回测） | `python run.py` | R1 实测 |
| `006_plots` | backtest | 4 个绘图/报表脚本 | 无 | 无 | 可运行 | `python example_plotly_charts.py` | R1 实测 |
| `008_dual_side` `009_trade_logger` `011_hft_backtest` | backtest | 各自 2–3 个脚本 | 无 | 无 | 可运行 | `python <script>.py` | R1 实测 |
| `016_self_similarity` | backtest | `run.py`（`--mode backtest\|optimize`，缺省取 config `mode`） | 无 | 无 | 被策略回归 `test_0201_self_similarity.py:23` 按 `examples.016_self_similarity.run` import | `python run.py` | R1 实测（含策略回归全量） |
| `017_fnn_embedding` | backtest | `run.py`（`--mode backtest\|optimize\|diagnose`、`--retrain`）+ `models/` | 无 | 无 | 被 `test_0202_fnn_embedding.py:24` import | `python run.py` | R1 实测（含策略回归全量） |
| `012_1` `012_2` | unified | `run.py` 默认 dry；`--replay`=公式/冻结 fixture（**非**完整历史回测） | `--live`（`run.py:167/168`，无 `--allow-write` 即 `write_consent_missing` → BLOCKED） | 有界 Demo 写 | 迭代 42 已双 Demo 门关闭（`447e9a10` / `f28557f7`） | `C:/anaconda3/python.exe run.py --replay` | R2 复跑 dry+replay；R5b 补无写观察 |
| `013_1` `013_2` `013_3` | unified | dry / `--replay` 冻结 fixture | `--live` 要求写授权（`run.py:510/511/472` 起） | 有界 SimNow 写 drill | 013_2 `3583ad31`、013_1 `7e938fc7` 真实往返 PASS | `C:/anaconda3/python.exe run.py --replay` | R2 复跑；R5b 补无写观察 |
| `014_1` | unified | dry / `--replay` | `--live` 严格写 adapter | 有界写 | 写 drill 未达时段验收 | 同上 | R2 复跑；R5b 补无写观察 |
| `014_2` `015` | unified | dry / `--replay` | `--live` **无写观察层**（`--allow-write` 显式拒绝） | 无 | 015 观察层真实 PASS（`39d69fb7`）；014_2 陈旧钟 BLOCKED | `C:/anaconda3/python.exe run.py --live --run-seconds 900` | R2 复跑；R5a 可直接接 config-live |
| `007_ctp` | unified（受限） | 仅登记 `example.007_ctp.legacy_direct` 的 replay 路由；5 组 `ctp_*_examples/backtest/run.py` 已封死 `legacy_direct_execution_error` | **无可用 live 入口**（`live/run.py:68` 的 `--dry-run` 声明不生效） | 无 | 冒烟 8/0/2 内 PASS | 由 `bt-runtime` 登记路由驱动 | R2 复跑冒烟；不得借 R5a 复活 |
| `000_live_certification`（3×33） | live | `cases/<ID>/run.py` 干跑自检 | `--live`（`certlib/runner.py:29-31`） | config `policy.allow_write` + `--allow-write`（`runner.py:156`） | 迭代 41 交付 98/99 PASS | `C:/anaconda3/python.exe cases/C01/run.py` | R3 |
| `000_live_certification/optional16` | live（组件矩阵 harness） | `run_matrix.py --dry`（默认） | `--live` | `--allow-write` | 迭代 41 真实 16 拓扑矩阵 PASS | **`--dry` 必须显式带套件外 `--out`**（`:46 DEFAULT_OUT` 为受跟踪文件，`:268` 写入） | R3 |
| `sample/` `sample.py` | 支持 fixture | 零 I/O 迁移 profile | 无 | 无 | 冒烟内 PASS | 登记路由驱动 | R4 |
| `backtest_examples/` | — | 空目录 | — | — | 无跟踪内容 | — | R6 删除 |
| 已退役：`010_live_examples`、`ctp_options_simnow_managed_replay_runtime{/, .py}`、013_3/014_x 的 `run_runtime.py`+`runtime/` | — | — | — | — | 已由 `94039354e`/`de3b65719`/`1f84c04df`/`b021efc42` 删除 | — | **移出搬迁清单，不重建** |

## 5. 唯一映射表（公开条目 100% 覆盖）

见 `迭代计划.md` §4。要点：`optional16` 的唯一目标是 `examples/live/000_live_certification/optional16/`（**不是** `live/optional16/`），以保持 `run_matrix.py:43-44` 与 `gateway_server.py:67-68` 对 `binance_penetration` 的相邻依赖。

## 6. 公开 / 私有 / 可重建迁移边界

| 类别 | 清单 | 处理方式 |
|---|---|---|
| Git 跟踪 | 591 个 examples 路径；含 `examples/.gitignore`（262B）、`examples/012_1/.gitattributes`（3 条）、`.gitattributes` 根文件 23 条 examples 规则（其中 **10 条目标已不存在**） | `git mv` + rename 检测；活跃属性规则随迁移改前缀并验 checkout 字节 == index blob；历史/失效规则单列，不批量删除凑测试 |
| 被忽略的私有件 | `examples/000_live_certification/*_penetration/config.yaml`、`.../secrets.yaml`、`examples/013_3_sa_midfreq_simnow/runtime-ctp-private/config.yaml`、根 `.env`、各 `evidence/`/`reports/`/`runtime*/config.yaml` 本地件 | **不入 Git、不读内容、不输出值**；由原受控流程迁移；每轮验新路径访问规则、缺文件即拒绝、旧路径不被隐式尝试；规则先加新再删旧，`git check-ignore -v` 双向验空窗 |
| 可重建产物 | `__pycache__/`、`logs/`、`output/`、生成的 `reports/`、模型缓存、journal | 不递归删除；已消耗 claim/generation/结果/保留 host 维持原限制，重组不得为其"清理以便重跑" |

## 7. 对评审自身数字的修正（已核源码）

- `.gitattributes` examples 规则：实为**根文件 23 条 / 10 条失效**（评审写 56/41）。
- 登记离线冒烟基线：r12 起 **8/0/2 全绿**（评审引用的 r11 `8/1/2` 已被取代）。
- 补充：8 个 unified 入口均无 `--dry`（全仓仅 `optional16/run_matrix.py:180`）；`entry` 已是 `012_1/config.yaml:49` 的既有顶层段名；本机 black 为 `0.0` 占位实现。

## 8. R0 结论与 R1 入口条件

环境、注册集合、四类门禁基线与 3 项既有红均已冻结并可直接复跑；`docs/_internal` 历史证据只读、仅靠映射表说明的原则不变。R1 可开始，其验收以本文 §3 为"无新增回归"的比较基准，A 类各目录的最小启动命令在 R1 内逐条实测回填。
