# R10b — 014_1/014_2 精简轮：退役登记路由、启动器与工程观察链（2026-10-11）

状态：**完成并提交**。范围 = 用户指示"把你研究可以删除的、退役的给删除和退役了"，
对象为 014_1/014_2 的 C 类残留（迭代41 登记回放路由）、退役启动器与
仅测试可达的 SimNow 工程观察链（`simnow_adapter.py`）。策略域模块
（`legacy_runner.py` 回放引擎、`execution_timing.py`、`features.py`、
`fq2_fixture.py`、`execution_fixture.py`）与 `run.py` 标准面保持不动。

## 删除清单（14 文件 + 2 目录）

**C（迭代41 登记路由的源树侧）**

- `run_runtime.py`（base 入口）、`runtime/`（.gitignore + config.example.yaml；
  本地 156B `config.yaml` 已先备份至 `D:/temp/iter42_014x_runtime_configs_backup_20261011/`
  后随目录删除）——两个目录同式

**退役启动器（自述 Retired、examples/测试全仓零引用）**

- `simnow_launcher.py`

**工程观察链（仅测试可达：调用方=测试 + 已退役启动器/dead `_legacy_main`）**

- `simnow_adapter.py`
- `tests/unit/test_ctp_options_lowfreq_adapter.py`（6 测试）
- `tests/unit/test_ctp_options_lowfreq_engineering_observation.py`（27）
- `tests/unit/test_ctp_options_midfreq_engineering_observation.py`（23）
- `tests/unit/test_ctp_options_midfreq_simnow.py`（18）

**明确保留**：`run.py`（dry/replay/live 唯一入口）、`legacy_runner.py`（含
config-first 脚本栅栏，其排序契约被 `test_ctp_options_lowfreq_example.py:70-77`
钉住）、`execution_timing.py`、014_2 的 `features.py`/`fq2_fixture.py`/
`execution_fixture.py`、策略文件（含 014_2 策略的 `engineering_observation`
模式语义——live 观察层由 `run.py` 严格链驱动，字符串保留）。

## 代码编辑

- `legacy_runner.py` ×2：移除 `simnow_adapter` import 块与
  `run_simnow_engineering_smoke`/`run_engineering_smoke`/
  `run_engineering_observation` 包装函数；014_1 的 dead `_legacy_main` 三元式
  改为 `run_replay(...) if ... else _blocked_report(...)` 并移除 `--purpose`；
  014_2 移除 dead 分支的 engineering_smoke 段与 `--purpose` 选项；
  014_1 移除不再使用的 `deepcopy` import；两文件 docstring 更新为
  "栅栏保留、路由已退役、直接脚本调用 fail-closed、run.py 为唯一入口"。
  **栅栏本体（`_run_config_first_cli`/`main`/`__main__` + `backtrader_runtime.legacy`
  import）保持原样**——退役后 no-arg 调用干净退出 2（`runtime_not_registered`），
  带参调用仍被拒。
- `scripts/run_iter27_fq3_independent_acceptance.py`：SOURCE_PATHS 移除
  `simnow_adapter.py` 行（保持脚本对当前树的哈希绑定可运行；
  `test_iter28_fingerprint_probe.py` 的 AST 子集断言不受影响）。
- README ×2：模块表移除退役三行/五处引用；新增"2026-10-11 精简轮退役"段；
  014_1 的 "live 层状态（BLOCKED）" 陈旧节改写为 R6 严格实况（`8c067982b`：
  run 域 ClockMapping/密封 BarEvidence/registered-sim 直连/三腿 arm 切换/drill；
  时段内正式验收），删除 `bt-runtime run` 登记路径引用。

## 登记面同步

- `backtrader_runtime/inventory.py`：删 014_1/014_2 的 runtime dir 常量、strategy
  id、2 个注册；`ITERATION41_REPLAY_RUNTIME_SET` 移除 2 个 id（**关键坑同 013_3 轮**：
  只删注册不删 set 成员 → 构造即 ValueError）；`iteration41_runtime_registry()`
  15→13 注册。
- `backtrader_runtime/__init__.py`：移除 6 个导入 + `__all__` 条目。
- `examples/iteration41-runtime-inventory.json`：`iteration41_entrypoints` 10→8
  （删 2 行）；legacy_entrypoints 两行 `iteration41_replacement` 置 null + 退役注；
  scope 文案 "ten→eight"。
- `AGENTS.md`：两处 15→13、10 nonmanaged→8、seven→five。
- `tests/unit/runtime/test_runtime_config.py`：注册数 15→13、normal_replays
  10→8（去 014 两项）、移除 014_1 require 块与导入、monkeypatch 用例改用 015。
- `tests/unit/runtime/test_runtime_runner.py`：13 ×2；fresh-process 参数
  014_1→015。

## 验证（本轮全部在改动后实跑）

| 项目 | 结果 |
| --- | --- |
| `tests/unit/runtime` 全量 | **747 passed / 23 skipped / 0 failed**（1 既有 warning） |
| 直接受影响两文件 | 103 passed / 13 skipped |
| 示例+守卫聚焦集（example/timing/fq2/self-contained/component-boundaries/fingerprint/multiarm/front-failure） | 205 passed + 3 failed = **既有基线**（000 optional16 组件导入、013_x ctp_example_support CRLF 字节 ×2） |
| `tests/unit -k ctp_options` | **469 passed / 0 failed** |
| `-k "ctp_options or iteration42 or ctp_sa"` 聚合 | 743 passed / 1 failed = 既有基线（identity-drift，SDK 源码不在该进程 sys.path） |
| 登记离线冒烟 | **9 passed / 1 failed / 10 selected / 3 skipped**（1 failed=既有 mechanical L2 SDK-source 基线） |
| 014_1 dry / replay | `DRY` exit 0 / `LOCAL_REPLAY_PASS` exit 0 |
| 014_2 dry / replay | `DRY` exit 0 / `LOCAL_REPLAY_PASS` exit 0 |
| `legacy_runner.py` 直接脚本（两目录） | no-arg → exit 2 `runtime_not_registered`；带参 → exit 2（fail-closed） |
| ruff / py_compile（全部改动的 .py） | 全绿 |

## 备注

- **015 的同模式件未在本轮**：015 的 `simnow_launcher.py` 被 2 个测试引用
  （`test_ctp_options_highfreq_artifact.py`/`_environment.py`），其
  `run_engineering_observation` 链与 adapter（无独立 adapter 文件）仍在役
  ——需专门评估后处理。
- **其余 `run_runtime.py` 副本**（007/010/012_1/012_2/013_1/013_2/015）仍注册在案
  （8 个 replay 入口），留作后续轮逐目录评估；本轮只处理 014_1/014_2。
- 被删测试文件的覆盖（fail-closed adapter 契约、工程观察）为退役特性，
  其安全行为不再有活跃入口依赖。
