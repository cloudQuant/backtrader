# R12 — ctp_options_simnow 源树 managed L2 路由退役轮（B 轮，2026-10-11）

状态：**完成待提交**。范围 = 用户指示"继续迭代41的 `ctp_options_simnow` 路由退役"，即
`69117d467`（A 轮，仅删 test-only 工程链）明确留给独立一轮的 **B 轮**：默认注册表里最后一条
`offline_managed_execution` 源树 CLI 路由。包内两个 package-owned L2 fixture 保持不动。

## 删除清单（4 个跟踪文件 + 1 个本地忽略配置）

- `examples/ctp_options_simnow_managed_replay_runtime.py`（73 行）——薄兼容封装，整份委托给
  `backtrader_runtime/_iteration41_l2_fixture/mechanical_p1b`
- `examples/ctp_options_simnow_managed_replay_runtime/`：`README.md`、`.gitignore`、
  `config.example.yaml`；本地 `config.yaml`（178B）删前核实 `secrets_ref: none`、无凭证、
  且由 `bt-runtime bootstrap` 从 code-owned 默认值可重建，故未另备份（该目录随注册项一并退役，
  不再需要 bootstrap）

## 明确保留

- `backtrader_runtime/_iteration41_l2_fixture/mechanical_p1b.py` 及其 `runtimes/mechanical_p1b/config.yaml`
  （P1-B 三腿 `MechanicalCycle` 假场所实现、合成成交/`actual_fills=0` 分离、UNKNOWN 重启冻结等
  全部语义都在这里）
- `ITERATION41_CTP_MECHANICAL_MANAGED_REPLAY_RUNTIME_ID` / `_STRATEGY_ID` 两个常量
  （被包内 fixture 注册复用，非源树专属）
- `_MANAGED_REPLAY_CAPABILITY_MODULES`、`MANAGED_WRITE_CAPABILITIES`
- 独立注册表 `iteration41_l2_fixture_registry()`（013_3 + mechanical_p1b 两条包 fixture）与
  `iteration41_backtest_fixture_registry()`

## 代码编辑（重接）

- `backtrader_runtime/inventory.py`：删 `..._RUNTIME_DIR` 常量、`..._REGISTRATION` 注册、
  默认注册表元组成员，并**整条删除 `ITERATION41_MANAGED_REPLAY_RUNTIME_SET`**（其唯一成员即本路由）
  及其在 `runtime_sets` 的出现（同前几轮关键坑：只删注册不删集合成员会构造即 ValueError；
  只删集合成员不删 `runtime_sets` 会残留空名）；`iteration41_l2_fixture_registry` docstring
  "remaining eleven source examples" → **nine**。默认注册 **11 → 10**。
- `backtrader_runtime/__init__.py`：移除 3 个导入 + 3 个 `__all__` 条目
  （`_REGISTRATION`、`_RUNTIME_DIR`、`MANAGED_REPLAY_RUNTIME_SET`；保留仍存在的 ID/STRATEGY 导出）。
- `backtrader_runtime/runner.py`：`_managed_l2_required_capability_modules` 的受审注册三元组
  → **二元组**（只剩两条包 fixture），docstring "three" → "two"。
- `backtrader_runtime/_iteration41_l2_fixture/mechanical_p1b.py`：删除
  `_SOURCE_COMPAT_RUNNER_MODULE`（指向已退役源树封装）与其四行注释，守卫由
  `runner_module in (__name__, <compat>)` **收紧为 `== __name__`**（接受集只减不增）。
  注：这与 013_3 fixture 的既有形态略有差异——后者在 `1f84c04df` 退役源路由时直接去掉了
  `runner_module` 条件；本轮选择保留正向身份检查而非删除。
- `examples/iteration41-runtime-inventory.json`：删除整个 `managed_replay_l2_entrypoints` 段
  （唯一记录即本路由）；`scope_limitations` 文案改为"seven ordinary replay entrypoints，
  两条包 owned offline L2 fixture 属独立 l2-wheel-fixture 注册表、非源树示例路由"。
  该段的 `verification_tests` 指向从未存在的
  `tests/integration/test_iteration41_ctp_mechanical_managed_replay_l2.py`（陈旧指针，随本轮消失）。
- `tests/unit/runtime/test_runtime_config.py`：注册数 11→10；managed 断言整块改写为
  **默认注册表零 `offline_managed_execution`**，并删除
  `require_runtime_set("iteration41-managed-replay-l2")` 断言（该集合已不存在）。
- `tests/unit/runtime/test_runtime_runner.py`：两处 11→10。
- `AGENTS.md`：三处现状口径——默认注册 11→10 与路由构成、Iter 41 inventory 计数与退役括注、
  Tests 段"managed L2 replay 需要本地 SDK 源码在 PYTHONPATH"改写为"该类源树 CLI 路由已退役"。
- `scripts/ci/smoke_iteration41_registered_offline.py` **无需改动**：它本就按
  `("simulation","replay")` + 有 runner 选取，退役项自动不再入选。

## 运营面后果（需明确知晓）

**P1-B 机械假场所轨此后没有任何 CLI 入口**。它只能由代码显式注入
`iteration41_l2_fixture_registry()` 后 `main(["run", "--strategy-dir", <包内 fixture 目录>], registry=...)`
调用（这正是其现有测试的调用方式）。默认 `bt-runtime run` 对该目录返回
`runtime_not_registered`（已实测）。若将来需要操作员可跑，需一条新的、独立评审的注册路由——
不得靠 fallback 或 override 复活。

## 验证（本轮全部在改动后实跑，`C:/anaconda3/python.exe` + `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`）

| 项目 | 结果 |
| --- | --- |
| `tests/unit/runtime` 全量 | **746 passed / 23 skipped / 0 failed**（1 既有 warning） |
| `tests/unit -k "ctp_options or mechanical or l2 or managed_replay"` | **364 passed / 4956 deselected / 0 failed** |
| 登记离线冒烟 | **8 passed / 0 failed / 8 selected / 2 skipped**——本轮首次全绿（此前那 1 项 FAIL 正是这条源树 managed L2 的缺 SDK capability 基线） |
| 包内 fixture 守卫 | 经 l2 fixture 注册表实际 dispatch：到达 `capability_dependency_missing` / `runtime.capabilities.bt_api_risk`，即**身份守卫接受自身注册**，未退化为 `offline_managed_registration_required`；环境缺 SDK 属既有基线 |
| 已删目录 CLI 行为 | `bt-runtime run --strategy-dir examples/ctp_options_simnow_managed_replay_runtime` → `runtime_not_registered` + `review_registration`（fail-closed，无发现回退） |
| 注册表完整性回读 | 默认 10 注册、replay set 7、默认注册表 `offline_managed_execution` 零命中、`iteration41_l2_fixture_registry()` 仍为两条包 runner、`backtrader_runtime.__all__` 无缺失符号 |
| 残留引用扫描 | 代码/清单中仅剩有意的 `PACKAGE_*` fixture 命名；源树路由名零残留（AGENTS 退役注记除外） |
| ruff / `py_compile`（全部改动 .py） | 全绿 |

## 遗留

- 015 的 `simnow_launcher.py`（2 个测试引用）与其 engineering observation 链。
- 其余 `run_runtime.py` 副本（007/012_1/012_2/013_1/013_2/015）仍注册在案。
- `simnow_direct` / `account_lock` 六份副本的长期归属=执行/风控/网关组件（迭代43 议题）。
- 包 fixture 仍沿用 `example.ctp_options_simnow.*` 身份串，而源示例目录已不存在；
  这是 code-owned fixture 标识，改名会牵动 `iteration41_l2_fixture_registry` 与测试，非本轮范围。
- 迭代41 历史需求文档（含 `迭代41-.../README.md` 的注册构成句）沿用前几轮约定不改写。
