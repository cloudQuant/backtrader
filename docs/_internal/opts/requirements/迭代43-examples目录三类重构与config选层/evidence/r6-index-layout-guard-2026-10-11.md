# R6：索引、能力登记表、布局守卫与 AGENTS 现状（2026-10-11）

范围：新增 `examples/README.md`、`tests/unit/test_iteration43_example_layout_boundaries.py`，
AGENTS.md 现状修正，本轮记录。示例源码与 `backtrader_runtime/` 未改。

## 1. `examples/README.md`

三类定义与判定规则、支持目录清单（`_support/ data/ output/ logs/ __pycache__/ test_results/` 不得成为
示例运行依赖）、四件套标准与退出码、unified 九目录逐例能力登记（离线入口 / 选层 / live 无写授权 /
live 写通道 / 复制到别处），backtest 十一目录的数据边界登记（小数据随目录、大数据 fail-closed 点名），
live 套件的内部拓扑说明，§4 旧→新路径映射与"本迭代刻意不做"的六项归属。

表内每个格子都来自本轮实测，不来自计划：选层与 `entry_tier` 见
`r5a-tier-dispatch-015-template-2026-10-11.md`、`r5a-tier-dispatch-remaining-entries-2026-10-11.md`；
无写观察与 `live_observation_unavailable` 见 `r5b-live-observation-2026-10-11.md`；
复制即可运行的 exit/点名结果见 `r7-copy-out-self-containment-2026-10-11.md` §5。

## 2. 布局守卫 `test_iteration43_example_layout_boundaries.py`（14 项）

静态、不跑示例，把 R1–R7 建立的形状钉成契约：

1. `examples/` 顶层只允许三类目录 + 支持目录 + 点开头工具目录 + **显式登记的 11 个散落脚本/文件**
   （新增未登记项即失败；7 个根脚本的入目录化已登记为后续轮，不是本文件的例外）；
2. 三类目录都非空、类别目录不嵌套、`live/` 下只有 `000_live_certification`；
3. live 套件的 `optional16` 必须与三场所套件相邻，三场所各 33 个 case 目录（不得被拆散或漏例）；
4. 每个有 `run.py` 的 unified 目录必须自带 `entry_tier.py` 且与权威文件同摘要，README 必含
   「运行层选择（迭代 43）」且同时出现 `entry_tier` 与 `tier`（两字段之别不得丢）；`007_ctp` 无 `run.py`，
   以带原因 skip 记录，不算通过也不算失败；
5. 任何示例目录不得 `import examples.…` / `examples._support`（否则复制出去必炸）——AST 全树扫；
6. `<leaf>/data/*` 必须有仓库原名（`tests/datas/` 或 `examples/data/`），002 自生成 fixture 显式点名例外；
7. `git ls-files examples` 里不得出现 `.env` 或含 `secrets` 的文件。

首版漏登记 `examples/.gitignore` 与 `.benchmarks/` 导致自伤一次红；按 R6 计划口径
（顶层白名单含 `.gitignore`，可重建/工具目录不以物理干净为条件）修正。

## 3. AGENTS.md

- `Repository layout` 的 examples 段改为现状（三类 + `_support` + `data`），
  并保留 `strategy-candidate-manifest.json` 仍在根、`strategy_candidate_approval.py` 已在 `_support` 的事实；
- 迭代 42 段之后**追加** Iteration 43 现状段：布局与索引位置、选层契约（CLI 只降不升、缺省逐字兼容、
  下单仍需 `--allow-write` 与原准入）、`entry_tier` 与结果层级 `tier` 之别、四个新观察会话与两个
  `live_observation_unavailable`、可移植性守卫的两类断言语义与 011 假通过修复、
  提交链、仍守住的冻结门禁数字、以及六项"刻意不做"。历史段落不改写。

## 4. 门禁与全量回归归因

- 布局守卫 **14 passed / 1 skipped（007_ctp 无 run.py）**；`ruff check` 本轮新增/修改文件全清；
  `ruff check examples` 维持 176；
- 复跑：`tests/unit/runtime` **746 / 23 / 0**、登记离线冒烟 **8 / 0 / 2**、
  迭代 43 五份测试 **118 passed / 3 skipped**、复制守卫 + 自包含 **84 passed / 3 既有红**（见 R7 §5）。
- 本迭代收官前跑一次 `tests/unit + tests/integration` 全量（xdist -n 8）：
  **5703 passed / 48 failed / 65 skipped / 4 errors**（632s）。为把"是否本轮引入"钉死，
  另开 detached 工作树到迭代 42 收口提交 `de3b65719` 逐文件对比：

| 文件 | 本轮树 | `de3b65719` 基线树 | 判定 |
|---|---|---|---|
| `tests/integration/test_ctp_options_{low,high}freq_native_broker_chain.py` | 20 failed | **20 failed，失败节点集合逐条相同**（`comm` 双向差集为空） | 既有红，零新增回归 |
| `tests/unit/scripts/test_verify_iteration41_writer_dispositions.py` + `tests/unit/core/test_sizer_allocation.py` + `tests/unit/scripts/test_run_iteration41_direct_benchmark.py` | 7 failed + 4 errors | **7 failed + 4 errors** | 既有红（writer-disposition 缺 collector、sizer 需 SDK 源根） |
| `tests/unit/test_examples_self_contained.py[000_live_certification]` | 1 failed | 1 failed（R0 即登记） | 既有红 |

  对比工作树用完已 `git worktree remove`。结论：迭代 43 的 R5a/R5b/R7/R6 **未引入任何新回归**，
  也不把上述既有红当作本轮通过条件。

## 5. 收口状态

迭代 43 计划内 R0–R7 全部落地：三类目录（R1–R4）、config 选层（R5a）、无写 live 观察与诚实标注（R5b）、
复制即可运行与数据边界（R7）、索引 + 守卫 + AGENTS（R6）。
计划显式排除的事项与既有红项在 §4 各记录的"刻意不做/仍未做"里逐项登记归属。
