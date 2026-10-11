# R3 — `examples/live/000_live_certification/` 搬迁与根定位适配（2026-10-11）

比较基准：`r0-baseline-freeze-2026-10-11.md` §3 + `r2-…-2026-10-11.md` §5。基线提交 `db5ad2b21`（R2）。

## 1. 范围与唯一映射

`examples/000_live_certification/**` → `examples/live/000_live_certification/**`，内部拓扑一字不变：
三场所 × 33 例（`{binance,okx,simnow}_penetration/cases/<ID>/{config.yaml,<ID>_strategy.py,run.py}`）+
`optional16/`（唯一映射 `examples/live/000_live_certification/optional16/`，**不拆到 `live/optional16/`**，
因其 `run_matrix.py:43-44` 与 `gateway_server.py:67-68` 依赖与 `binance_penetration` 的相邻关系）。

## 2. 私有件优先处理（评审 P2 10，无空窗）

顺序严格为"先加新规则 → 移动 → 验忽略 → 删旧规则"：

1. 预加 7 条 `examples/live/000_live_certification/**` 规则（`*_penetration/config.yaml`、`secrets.yaml`、`reports/` 等）。
2. `git mv` 整目录。
3. `git check-ignore -q` 对新路径逐场所验证：binance / okx / simnow 三个 suite-root 私有 `config.yaml` 全部 **IGNORED** ✔；
   `git status` 无 `??` 私有件（`R` 项均为受跟踪的 scenario-only 用例 config）。
4. 删除 7 条旧前缀规则后再次验证仍 IGNORED ✔。私有件内容全程未读、未输出、未入库。

随目录物理移动的忽略项按名登记（不读内容）：各 suite-root `config.yaml`、`cases/*/evidence/`、`__pycache__/`。

## 3. 根定位适配（实测只有 4 处真正逃出套件）

程序化判定每条 `parents[N]` 的移动前指向，结果 **108 条中仅 4 条逃出**，其余 104 条是套件内部定位，按评审意见**不改写**：

| 文件 | 改动 |
|---|---|
| `{binance,okx,simnow}_penetration/certlib/envfile.py:14` | `parents[4] / ".env"` → `parents[5]`（3 处） |
| `optional16/run_matrix.py:251` | `repo_root` 的 `parents[3]` → `parents[4]` |

实证：`default_env_path()` 对三个场所均返回 `D:/source_code/backtrader/.env`（等于仓库根，未读其内容）；
`cases/C01/run.py` 在 suite-root cwd 与在外层 cwd 用绝对路径调用，均 `status: DRY`、exit 0；
99 个 case runner 的 `CASE_DIR.parents[1]` 定位在内部拓扑不变时继续有效。

## 4. 其它同步面

- `.gitattributes`：17 条 `examples/000_live_certification/**` 规则改前缀；`git check-attr eol` 在新路径仍解析为
  `crlf`（以 `simnow_penetration/cases/C01/C01_strategy.py` 抽样验证）。
- `tests/unit/test_iteration42_component_boundaries.py:45`、`tests/unit/test_iteration42_optional16_mount_smoke.py:31`：
  后者的路径是 `"examples" / "000_live_certification"` **分段字面量**，连续 token 替换命中不到（第五类漏网形式），已显式修。
- 套件内 `README.md`（000 与 optional16）的用法路径更新。

## 5. 越界改动的回退（本轮自记，同 R2 教训）

扫描脚本按文件名过滤冻结件不够，仍扫到了这些**已回退为 HEAD 原字节**的冻结/历史材料：

- `scripts/run_simnow_c01_native_td_read_{v12,v17,v19,v20_r1,v20_r2}_root_activation_r*.py`（5 个冻结 Root 激活脚本，
  一次性 marker/claim 已消耗，保留旧路径字节，由未来版本承接）；
- `scripts/fixtures/iter27_hf_t1/v1/*.json`、`tests/fixtures/iter27_mf_t1`、`scripts/run_iter27_*`（iter27 历史验收材料）；
- `CHANGELOG.md`（历史条目）、`AGENTS.md`（第三次被目录级扫描波及，回退；本轮起在脚本里显式排除该两个文件）；
- `backtrader.egg-info/SOURCES.txt`：属可再生构建元数据且未被跟踪，不入库。

**R1 的一处遗漏也在本轮补修**：A 类 7 个文件的 docstring 用法示例仍写 `examples/0XX_…`
（R1 的 token 清单只含 unified 九个目录）。已补 `examples/backtest/…`，并复跑 `011/tick_backtest.py` exit 0。

## 6. 门禁结果

| 门禁 | 基线 | R3 实测 |
|---|---|---|
| 守卫+边界+挂载（3 文件） | 81+3 / 边界绿 / 挂载绿 | **77 passed / 3 failed**，3 项为同名既有红 |
| `tests/unit/runtime` + 上述三守卫（合并跑） | runtime 746/23 | **823 passed / 3 failed / 23 skipped** |
| `tests/unit/test_proxy_env_isolation.py`（conftest 被改动后） | — | **2 passed** |
| optional16 干矩阵 | 32/32 DRY | **32/32 DRY**（`--out` 指向套件外，受跟踪的 `acceptance-matrix.json` 未被覆盖，`git status` 仅显示其为改名项） |
| `ruff check examples` | 176 | **176** |
| 私有忽略 | — | 三个 suite-root 私有 config 新路径 **IGNORED**，删旧规则后复验仍 IGNORED |
| 000 用例 DRY 自检 | — | binance/simnow 用例 `status: DRY` exit 0；跨 cwd 绝对路径调用 exit 0 |

## 7. 与计划的两处现实差异（登记）

1. **`tests/unit/live_certification` 已不存在**（迭代 42 退役轮删除）。因此 R3 的验收不能按计划原文跑"该目录全量"，
   实际活跃引用面只有 `tests/unit/test_iteration42_{component_boundaries,optional16_mount_smoke}.py` 两个文件；
   99 例的判据面由 `test_examples_self_contained` 的用例级参数与各例 DRY 承担。
2. 计划写"内部零改动"，实为"99 例 ID/判据/内部拓扑不变 + **4 处根定位适配**"，已按评审 P1 05 落地。

遗留：iter27 与 Root 激活脚本的旧路径引用属冻结材料，R6 的活跃范围悬空扫描须显式区分这四类角色，不得为满足测试而改写。
