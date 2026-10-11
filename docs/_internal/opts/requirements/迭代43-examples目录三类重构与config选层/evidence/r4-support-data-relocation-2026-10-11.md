# R4 — `examples/_support/` 与 `examples/data/` 归位（2026-10-11）

比较基准：R0 §3 + R2 §5 + R3 §6。基线提交 `021663e1d`（R3）。

## 1. 移动清单

`examples/_support/`：`clean_bond_data.py`、`cross_exchange_replay_rules.py`、`strategy_candidate_approval.py`、
`demo-approval-trust-root.pem`、`iteration41-runtime-inventory.json`、`sample.py`、`sample/`（含其本地 runtime 目录）。
`examples/data/`：`113013.csv`、`bond_index_000000.csv`、`DOGEUSDT_15m_20200710_20260126.csv`、`113013_strategy_result.png`。

搬迁后 `examples/` 根只剩：`__init__.py`、三类目录、`_support/`、`data/`、被忽略的 `logs/`、
7 个待四件套化的根单文件脚本（R6 处置）、以及 `strategy-candidate-manifest.json`（见 §2）。

## 2. 有意不移动：canonical 准入 manifest

`examples/strategy-candidate-manifest.json` **保留在 examples 根**。理由与 R2 §3 同源：它的每行候选以
`resolved_example_path` 参与 `candidate_sha256` 指纹，且 `demo_approval` 以 `receipt_path` + `receipt_sha256`
绑定该指纹；移动文件必然改写 `resolved_example_path`，进而要求重算指纹并使既有 NOT_APPROVED receipt 绑定失效。
`_support/strategy_candidate_approval.py:32` 的 `CANONICAL_MANIFEST_RELATIVE_PATH = "examples/strategy-candidate-manifest.json"`
因此保持不变，`legacy_runner` 的 `REPO_CANONICAL_MANIFEST` 仍指向 examples 根，链路自洽。
真正的受控重绑（含 receipt 重发）作为**需用户拍板的独立治理轮**继续挂账。

## 3. 消费者同步（含五类引用形式）

本轮暴露出"路径引用"至少有五种写法，单一 token 替换必然漏：连续字符串、引号内 dotted 名、
`from examples.X import` 语句式、`"examples" / "x"` 分段式、`Path(__file__).parents[N] / "examples" / "x"`，
外加测试内**合成假树的写入侧与读取侧必须成对**。逐项修正：

| 位置 | 改动 |
|---|---|
| `backtrader_runtime/evidence_bundle.py:41` | 清单工件路径改指 `_support/` |
| `backtrader_runtime/inventory.py:89,247` | `ITERATION41_SAMPLE_RUNTIME_DIR` 加 `_support` 层；`runner_module="examples._support.sample"`；**strategy id `example.sample.ctp_legacy` 作为标识符不变** |
| `examples/_support/strategy_candidate_approval.py:85-86` | 自引用模块名常量改 `examples._support.strategy_candidate_approval` |
| `examples/unified/012_1|012_2/strategy_candidate_approval.py` | folder-local 副本与 canonical **同批同改**，保持逐字节一致的漂移契约 |
| `tests/integration/test_cerebro_iter28_provenance.py:7`、`test_cross_exchange_demo_contract.py:23,27,192,888`、`test_cross_exchange_real_rule_replay.py:25` | 语句式/分段式 import 与假树路径；假树补建 `_support/` 目录（只建 `receipts/` 会让写侧 FileNotFoundError，一度连带 130+ 节点全红） |
| `tests/unit/test_examples_self_contained.py` | vendored 映射的 canonical 侧改 `_support/`；`NON_EXAMPLE_DIRS` 增加 `_support`、`data`，避免把支持件当示例叶子 |
| `tests/unit/runtime/test_runtime_runner.py:1299,1315` | sample 迁移后的假 cwd 路径与 SOURCE_ROOT 断言 |
| `scripts/iter28_fingerprint_probe.py:21,39` | 指纹探针的 APPROVAL 常量与 import |
| 数据搜索路径：`examples/backtest/001_multi_extend_data/run.py:41`、`tests/functional/strategies/{special/test_02_multi_extend_data,order_types/test_05_stop_order_strategy,trend_following/test_03_two_ma}.py` | `repo_root / "examples" / filename` → `repo_root / "examples" / "data" / filename`（单一位置，不留悬空旧位） |
| `examples/bollinger_band_strategy_{test,train}.py` | `BASE_DIR / "DOGEUSDT…"` → `BASE_DIR / "data" / "DOGEUSDT…"` |

`tests/functional/strategies/misc/test_1[67]_cb_*.py` 命中的是同名局部函数 `clean_bond_data()`，不是 import，未改。

## 4. 有意保留旧路径的材料（四角色登记）

- 冻结脚本：`scripts/run_simnow_c01_native_td_read_{v12,v17,v19,v20_*}_root_activation_r*.py`、
  `scripts/run_iter27_*` 与 `scripts/fixtures/iter27_*`、`tests/fixtures/iter27_mf_t1`（含 `frozen_oracle.py:13` 的
  `examples/014_2_…` 硬路径）。这些按"冻结测试材料/历史证据"保留旧字节，由未来新版本承接；R6 的悬空扫描只覆盖活跃范围。
- 历史文档：`CHANGELOG.md`、`AGENTS.md`（R6 统一追加现状说明）。
- `backtrader.egg-info/SOURCES.txt`：未跟踪的可再生构建元数据，不入库。

## 5. 门禁结果

| 门禁 | 基线 | R4 实测 |
|---|---|---|
| 登记离线冒烟 | 8 / 0 / 2 | **8 passed / 0 failed / 2 skipped**（sample 路由迁移后仍 PASS） |
| `tests/unit/runtime` + 三守卫 | runtime 746/23；守卫 81+3 | **823 passed / 3 failed / 23 skipped**，3 项同名既有红 |
| `tests/integration` | 22 failed（HEAD worktree 基线）；R2 树 20 | **20 failed，节点级集合差：新增 0**（2 个基线红项现通过）。中途一次修 trust_path 未建目录导致 151 红，补目录后回到 20 |
| 受影响策略测试（misc/special/trend_03/order_types_05/time_based） | — | **103 passed** |
| `tests/functional/strategies` 全量 | 1286 passed | **1286 passed / 0 failed**（249.12s） |
| `ruff check examples` | 176 | **176** |
| 数据驱动根脚本 `bollinger_band_strategy_test.py` | — | exit 0（新 `data/` 路径生效） |

跟踪产物保护：策略回归再次追加的 `017/reports/train_report.jsonl` 每次运行后都还原为 HEAD 字节再提交。

## 6. 遗留

1. canonical manifest 受控重绑（需用户批准，含 receipt 重发）。
2. `sample/` 已入 `_support`，其注册仍为 `example.sample.ctp_legacy` replay 路由，语义未变；R6 README 需说明它是支持件而非示例。
3. iter27/Root 激活脚本的旧路径按冻结件保留，R6 守卫须区分角色。
