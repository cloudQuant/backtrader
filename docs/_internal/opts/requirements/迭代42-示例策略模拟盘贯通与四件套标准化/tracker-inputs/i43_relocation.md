# R2 — `examples/unified/` 搬迁、注册/属性同步与 folder-manifest 重绑（2026-10-11）

比较基准：`r0-baseline-freeze-2026-10-11.md` §3 + 本文 §5 新增冻结的两项基线。主仓基线提交 `a290dc459`（R1）。

## 1. 范围

9 个目录 `git mv` 进 `examples/unified/`：`012_1`、`012_2`、`013_1`、`013_2`、`013_3`、`014_1`、`014_2`、`015`、`007_ctp`。
同步面：`backtrader_runtime/inventory.py`（8 个目录常量 + 7 个 `runner_module`）、`.gitattributes`（6 条活跃规则改前缀）、
根 `.gitignore`（6 条 007 规则改前缀）、`examples/iteration41-runtime-inventory.json`（30 条 `path`）、
两个 012_x folder-local manifest 重绑、以及 tests/scripts 的路径与 dotted 模块引用。

## 2. 机械重写分三遍（含我自己引入的两个缺陷）

| 遍 | 覆盖形式 | 结果 |
|---|---|---|
| 1 | 被移动子树内的**祖先跨越定位** + 代码里 `"examples" / "<目录>"` 字面量 | 祖先表达式全部 +1 层（53 处 `parents[N]`，无 `parents[0]` 误伤；私有件 `runtime-ctp-private/state/run_readonly_preflight_bounded.py` 按 `SKIP_PARTS` 排除）；`_REPO_ROOT = _EXAMPLES_ROOT.parent.parent`（007_ctp 13 处）、`REPO_CANONICAL_MANIFEST = HERE.parent`（012_x 2 处）、`BACKTRADER_ARTIFACT_TARGET = HERE.parent.parent`（015）单独显式修正 |
| 2 | `examples/<目录>`、`examples.<目录>` 字面 token（tests/scripts/backtrader_runtime/examples 内 .py/.json/.yaml/.md + 根 `.gitignore`） | 413 处替换（64 文件） |
| 3 | **变量基址**形式 `EXAMPLES / "<目录>"`（无 `"examples"` 字面量，第 2 遍命中不到） | 23 处（3 文件）；另手工修 2 处 `EXAMPLES / strategy_id` 动态路径 |

引入并已修的自身缺陷（记录以免后续轮重犯）：

1. **`rf"...\b"` 里的 `\\b`**：f-串原始前缀下 `\\b` 是"反斜杠+b"正则，要求文本里真有 `\b` 字面量 →
   第 2 遍的两个 pattern 实际匹配 0 处却报"成功"。靠 `runner_module` 未变的观测发现，补第 3 遍与逐处验证。
2. **替换串写 `\"unified\"`**：把反斜杠原样插进源码，19 个文件出现 `/ \"unified\" / ` 的非法 Python。
   先误用 shell 内嵌 Python 修复（grep 传参被 Windows 引号规则吃掉，报 0 repaired），
   再误让修复脚本遍历到 `.venv` 且遇非 UTF-8 文件崩溃；最终按字节替换 + 显式排除 `.venv/build/logs/docs` 完成，
   `compileall` 与全部门禁复跑验证。
3. **越界改动两类文件，已回退**：`AGENTS.md`（历史叙述段落，只应在 R6 追加现状）；
   iter27 历史验收材料（`scripts/run_iter27_*`、`scripts/fixtures/iter27_*`、`tests/fixtures/iter27_mf_t1`）
   与已红的 writer-disposition 对（`scripts/verify_iteration41_writer_dispositions.py` 及其测试）。
   并发会话的 3 个在编文件（`ctp_configured_front_check.py`、`ctp_simnow_operator.py`、
   `test_ctp_simnow_config_operator_route.py`）确认**未被本轮改写**（索引内 0 条，仍在 worktree 未暂存）。

## 3. Manifest 处置（本轮关键判断）

- **folder-local（012_1/012_2）**：因 `run.py` 字节变化必然失效，用仓库自带工具受控重绑
  `python scripts/refresh_cross_exchange_local_manifests.py`（其 `folder_path` 基准同步改为
  `EXAMPLES / "unified" / folder`）。结果：`--check` = `up to date`，且用 `legacy_runner._canonical_hash`
  复算两行 `candidate_sha256` 均**自洽**。SHA-256 前缀（旧→新）：
  `012_1` manifest `62ada147…`→`35b72561…`，`012_2` `7b7c58aa…`→`de330c22…`；
  驱动指纹来源 `012_1/run.py` `e5183319…`→`f1839f08…`。语义不变项：strategy ID、风险参数、准入状态、
  `resolved_example_path="."`、approval 语义（新指纹不继承旧签名授权）。
- **根 canonical manifest**：我一度把 `resolved_example_path` 改为 `unified/012_…`，这会使该文件自带的
  `candidate_sha256` 失去自洽，而 `load_candidate()` 是**先验指纹、后验路径**——等于把 demo 模式验证从
  "路径已迁移"变成"指纹不匹配"，且该文件的 `demo_approval` 以 `receipt_path`+`receipt_sha256` 绑定 hash-bound 工件。
  **已回退为 HEAD 原字节**（复算自洽 ✔）。当前诚实状态：canonical 的 `resolved_example_path` 指向迁移前的目录名，
  demo 模式按 `manifest resolves to a different example` 干净 fail-closed；approval 仍 `NOT_APPROVED`，
  `manifest_status` 不变。真正的重绑（重算两行 `candidate_sha256` + 重发 NOT_APPROVED receipt 绑定）
  属**需用户拍板的治理动作**，不塞进搬迁轮，登记为独立轮次。
- 012_x 六文件的 `.gitattributes` LF 钉随路径改写，字节口径由 `--check` 与 manifest 自洽共同佐证。

## 4. 私有件与产物台账（只列名，未读内容）

随目录**物理移动**的 Git 忽略项（`git mv` 整目录移动的必然结果）：
`examples/unified/013_3_sa_midfreq_simnow/runtime-ctp-private/{config.yaml,state/**}`（含
`state/run_readonly_preflight_bounded.py`，其内含 `parents[2]` 仓库根假设，**搬迁后失效，须由受控流程重新生成**，
本轮不改不读）、各例 `runtime/config.yaml` 本地件（012_1/012_2/013_1/013_2/015/007_ctp）、
`013_3/reports/verify-supervisor-state/journal.jsonl` 等。空窗校验：新路径
`git check-ignore` 对 013_3 私有 config、000 suite 私有 config、007 `runtime-production/config.yaml` 均为 IGNORED ✔。
已消耗 claim/generation/journal 未复位、未删除。

## 5. 门禁结果（逐项 vs 基线）

| 门禁 | 基线 | R2 实测 | 判定 |
|---|---|---|---|
| 登记离线冒烟 | 8 passed / 0 failed / 2 skipped | **8 / 0 / 2**（中途曾 6/2，因 folder-manifest 待重绑；重绑后回基线） | ✔ |
| `tests/unit/runtime` + 三守卫文件 | runtime 746/23；守卫 81+3 | **826 passed / 3 failed / 23 skipped**，3 项为同名既有红 | ✔ 无新增 |
| `tests/integration` + 加密性能文件 | **22 failed / 288 passed**（本文新冻结；R0 未覆盖，用 HEAD 临时 detached worktree 实跑取得） | **20 failed，与基线做节点级集合差：新增 0**，基线中 2 个 `real_rule_projection` 节点现通过 | ✔ |
| `tests/unit -k "ctp or cross_exchange or examples or iteration42 or iter27 or self_similarity or fnn"` | **70 failed**（同 worktree；含缺 Git 忽略本地件导致的额外失败，不能当门） | **11 failed / 1986 passed**，11 项全部同时出现在 worktree 失败集内 | ✔ 零新增（本文新冻结该子集在主树上的失败清单） |
| `tests/functional/strategies`（1,286） | 1286 passed（R1） | **1286 passed**（301.92s，`-p xdist -n 8`） | ✔ |
| 8 个 unified 目录 `dry` / `--replay` | 迭代 42 记录全绿 | **8/8 退出 0**（013_3/014_x/015=LOCAL_REPLAY_PASS，012_x=FORMULA_CHECK_PASS） | ✔ |
| `ruff check examples` | 176 errors | **176** | 未增加 |
| `compileall backtrader_runtime tests scripts examples/unified` | — | 通过 | ✔ |
| `git diff --cached --check` | — | clean | ✔ |

方法论：并发会话下不能用"全绿"当门，故本轮改用**临时 detached worktree（HEAD）+ 失败节点集合差**判定新增回归，
worktree 用毕即 `git worktree remove`，未留残余（其余 worktree 属历史会话，未触碰）。
另需记录：一条滞留后台策略回归与本轮编辑并发跑完（1286 passed，32 分钟），其结果**不归属 R2**，故 R2 重跑了一遍干净口径。

## 6. 遗留与新发现

1. **canonical manifest 受控重绑**：见 §3，需用户拍板；在此之前 012_x 的 demo 通道保持 fail-closed。
2. **`examples/unified/007_ctp/live_certification/` 在磁盘上不存在**，但 `inventory.py` 仍注册
   `example.007_ctp.simnow_penetration.ctp_private` 指向它、AGENTS 也如此描述；根 `.gitignore` 的 6 条相关规则
   本就指向缺失目录（本轮仅随之改前缀）。需 R6 判定是"缺失未创建"还是"已迁往 000"，不能靠批量删规则凑测试。
3. `007_ctp` 的 `ctp_bbroker_*`/`ctp_tickbroker_*` 子例仍被 `legacy_direct_execution_error` 封死，未因本轮分派变化。
4. `tests/functional/strategies` 三处内联 `repo_root / "examples" / filename` 数据搜索仍有效（CSV 未动），R4 移数据时同步。
5. writer-disposition 测试在 HEAD 已红（collector 缺失），本轮已回退对其文件的改写，继续不作门。
