# R5a-2：其余七个 unified 入口接入 config 选层（2026-10-11）

承接 `r5a-tier-dispatch-015-template-2026-10-11.md`（提交 `f2c048a5b`）。本轮把同一模板
复制到其余 7 个 `examples/unified/*/run.py`，并把 §5.1 真值表固化为仓库内可重复执行的守卫。
范围仅 `examples/`、`tests/unit/` 与本轮记录；`backtrader_runtime/` 未改动。

## 1. 改动清单

| 文件 | 动作 |
|---|---|
| `examples/unified/{012_1,012_2,013_1,013_2,013_3,014_1,014_2}/run.py` | `--dry` 进互斥组；导入本目录 `entry_tier`；`run_dry(tier_evidence=None)` / `run_replay(..., tier_evidence=None)`；dry/replay 报告加 `tier` + `write_grant_result`；`main()` 在**任何 handler 之前**判层，冲突/非法即 BLOCKED，否则按 `effective_tier` 分发并把决策挂到 `args.tier_decision` |
| 同上 7 目录 `entry_tier.py` | `examples/_support/entry_tier.py` 的逐字节副本（新增，入漂移守卫） |
| `examples/unified/{014_1,014_2}/legacy_runner.py` | 严格回放校验前把 `entry` 与既有 `live_adapter` 一起投影掉（015 的 R5a-1 先例） |
| `examples/unified/{8 个}/README.md` | 追加「运行层选择（迭代 43）」小节：真值表、`backtest` 别名、非法即 BLOCKED、证据字段、自带副本；并逐例写清 live 通道的前置条件与 012_x 的清单重签要求 |
| `examples/unified/{012_1,012_2}/strategy-candidate-manifest.json` | `python scripts/refresh_cross_exchange_local_manifests.py` 重签发（见 §4） |
| `tests/unit/test_iteration43_entry_tier_dispatch.py` | 新增 73 项派发守卫（见 §3） |
| `tests/unit/test_examples_self_contained.py` | `VENDORED_COPIES` 的 tier helper 条目改为按 `unified/*/entry_tier.py` 发现登记，新增副本无需再改表 |

`run_live` 的内部证据接线**不在本轮**：其 `tier` / `write_grant_result` 与无写观察通道一起在 R5b 落。
本轮只把决策挂到 `args.tier_decision`，各例 live 通道自身的写授权判据一字未改。

## 2. 真值表（8 入口 × 11 行，在临时副本原地复跑；固定为 §末的派发守卫）

无声明行（`absent/*`）与降级行（`live + --replay` → `cli_override`）在 6 个可整体复制的入口全部按预期通过；
上调（`dry|replay` + `--live`）与非法（`tier: nonsense` / `entry:` 空 / `entry: not-a-mapping`）一律
`BLOCKED` 且 `write_grant_result=not_evaluated_tier_unresolved`。015/013_x/014_x 的
`tier: replay|backtest` 无 flag 直接得到 `LOCAL_REPLAY_PASS` + `config_default`。

两处实测发现（都已固化进守卫）：

1. **014_1/014_2 的严格回放校验会拒绝 `entry`** —— 报 `configuration fields are not the declared
   schema`（014_1）与 `config has unknown keys ['entry']`（014_2）。按 015 先例在 `legacy_runner.load_config`
   投影掉 `entry` 后，同一声明的 `LOCAL_REPLAY_PASS` 通过。013_1/013_2/013_3 无此问题（其加载链本就不做
   根键全等校验），故**不为此改写它们的校验器**。
2. **012_x 声明 `entry.tier` 需先重签目录内清单**：`config.yaml` 字节被 `strategy-candidate-manifest.json`
   绑定，任何未重签的声明都会让 handler 以 `RunnerSourceBindingError: runner source fingerprint mismatch`
   拒绝。判层门本身在 012_x 工作正常（冲突/非法行在到达校验前就 BLOCKED）。本轮**不**在任何
   `config.yaml` 写入声明（见 §5），012_x 的该约束写入其 README。

`tests/unit/test_iteration43_entry_tier_dispatch.py` 覆盖：门（8 入口 × 5 组声明/flag 组合，断言
BLOCKED + reason + 证据 + 未出现任何 live 前置标记）、无声明的 dry/无 flag 行（8 入口，仓库内跑）、
声明选层与降级行（6 入口的暂存副本，replay 执行行按 3 例抽样）、live 通道到达证明
（014_2/015 用 `--allow-write` 探活，落在 `run_live` 第一条语句的零写拒绝上）、
`entry` 投影不放宽严格键集的正/负例（014_1/014_2/015 加 `bogus_iteration43_key` 仍被拒）、
以及 8 份副本与权威文件的逐字节相等。

## 3. 门禁（全部对照 R0/R2 冻结基线，不预设全绿）

| 检查 | 基线 | 本轮 |
|---|---|---|
| `tests/unit/runtime` | 746 passed / 23 skipped / 0 failed | **746 / 23 / 0**（20.21s） |
| `scripts/ci/smoke_iteration41_registered_offline.py` | 8 / 0 / 2 selected 8 skipped 2 | **8 passed / 0 failed / 2 skipped** |
| `ruff check examples` | 176 | **176**（无增量）；本轮改动的 11 个文件单独 `ruff check` = All checks passed |
| 自包含 + tier + 012_x 单元（4 文件） | 81 passed / 3 failed（既有红） | **305 passed / 3 failed / 3 skipped**，3 项即 R0 命名的既有红（000 optional16 导入 `bt_api_monitor`/`bt_api_risk`；两处 `ctp_example_support.py` CRLF 漂移） |
| `tests/integration/test_cross_exchange_*`（2 文件） | 未冻结 | **134 passed**，含重签后清单与批准状态（`NOT_APPROVED` 不变） |
| `refresh_cross_exchange_local_manifests.py --check` | up to date | 重签发后 **up to date**（退出 0） |

新增 3 项 skipped 是 replay 执行行的抽样（`013_2`/`014_2`/`015` 未取 replay 样本），非回归。

## 4. 012_x 清单重绑台账（旧 → 新，仅两字段变化）

| 目录 | `runner_sha256` 旧 | 新 | `candidate_sha256` 旧 | 新 |
|---|---|---|---|---|
| `012_1_midfreq_cross_exchange` | `f1839f08…1dcb1fc2` | `2ca13e2f…212f5ff057` | `758724414f…9e8c2a22a` | `7e37f462…d4cae82bf` |
| `012_2_event_driven_cross_exchange` | `9bcf6bb2…186009665` | `0bfa9531…43314c8285` | `1d6086fa…f4f938ad0` | `7050af7b…1cb3d72a5` |

`strategy_sha256`、`config_sha256`、candidate ID、风险参数与 `demo_approval`（`NOT_APPROVED`，
`receipt_path/receipt_sha256` 仍为 null）逐项未变；仓库根 canonical manifest 未被改写。
新指纹不继承任何旧签名授权。原因：本轮按 §5.1 修改了这两个 `run.py` 的字节。

## 5. 本轮刻意不做

- **不向任何 `config.yaml` 写入 `entry.tier` 声明**。缺省即真值表第一行，逐字保留迭代 42 的全部
  文档化命令（含 `--live`、`--live --allow-write`）；声明是运营者的一次显式编辑，README 已给片段。
  若要仓库默认就选层，那是独立一轮：013_x/014_x/015 只需加声明并复跑守卫，012_x 还必须重签清单。
- 不动 `run_live` 内部（R5b），不动 `backtrader_runtime`，不改注册表与 runtime 授权边界。
- 不修 R0 命名的既有红；017 `train_report.jsonl` 未被本轮任何测试写入（未跑策略回归）。

## 6. 自查发现（自伤记录，务必保留）

1. 首版补丁脚本用未锚定的 `" = {\n"` 搜索插入点，且**不限制在函数体内**，把
   `tier`/`write_grant_result` 插进了 `run_live` 的 `summary` 里，并留下未定义的
   `tier_evidence` 引用（`py_compile` 不能发现，只有 live 行会触发 NameError）。已把搜索
   改为函数体内定位（先找 `report|summary|payload = {`，找不到才取该函数最后一次 `_json_print` 的字典），
   并去掉对 `run_live` 的编辑；7 个 `run.py` 全部回退到 HEAD 字节后重打。
2. 模板串从 `.format` 改成 `.replace` 时忘了把 `{{ }}` 还原，5 个文件写入了 Python 集合字面量
   （语法合法、运行期 TypeError）。`py_compile` 全绿也没接住，是真值表跑出来的。已定点收敛并在模板里改正。
   教训：这类脚本的验收必须是**执行行为**，不是编译。
3. 上一轮记录（R5a-1 §2）声称 015 README 已补 `--dry` 与 `entry.tier` 契约，实际该提交只改了
   `legacy_runner.py` 的命令行归属一处；本轮给 8 个 README（含 015）真正补上了该小节。记录以事实为准。

## 7. 下一步

R5b：为 6 个缺无写观察通道的入口新增独立 `run_live_observe()`（未补齐者返回
`live_observation_unavailable`），并把 `args.tier_decision` 的证据写进 live summary；
用 fake provider 叶子在真实加载方式下验连接/订阅或查询/超时/正常关闭，以写调用陷阱证明
submit/cancel 均未进入。
