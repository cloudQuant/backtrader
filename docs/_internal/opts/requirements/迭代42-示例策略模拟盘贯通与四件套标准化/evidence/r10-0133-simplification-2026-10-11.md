# R10 — 013_3 精简轮：退役登记路由与历史工具（2026-10-11）

状态：**完成并提交**。范围 = 用户指示删除 013_3 的 C（迭代41 登记路由源树件）与 D（迭代22
离线工具/监督器）；B（运行必需模块）经依赖核验全部保留。

## 删除清单

**D（离线工具/监督器，零入口引用；含 3 个专属测试）**

- `admission_receipt_tool.py`（28KB，迭代22 receipt 签名工具）
- `operator_readiness.py`（26KB，操作员自检）
- `pilot_supervisor.py`（50KB，有界会话监督器）
- `tests/unit/test_ctp_sa_admission_receipt_tool.py`、`test_ctp_sa_pilot_supervisor.py`、
  `test_iter22_operator_readiness.py`

**C（迭代41 登记路由的源树侧）**

- `run_runtime.py`（LOCAL_REPLAY_ONLY 基础路由入口）
- `run_managed_replay_runtime.py`（受管 L2 兼容入口）
- `runtime/`（config.example.yaml + 本地 config.yaml/reports 生成物）
- `runtime-managed-replay/`（config.example.yaml + 本地 config.yaml）

**明确保留**：`runtime-ctp-private/`（周一时段验收与 front-check 依赖的受保护私有配置）、
包内离线 L2 fixture（`backtrader_runtime._iteration41_l2_fixture`，独立注册表）、
机械化管理回放登记（另一示例），以及全部 B 类模块。

## 登记面同步

- `backtrader_runtime/inventory.py`：删 2 个注册（013_3 基础 / 013_3 源 managed）、2 个目录常量；
  `iteration41_runtime_registry()` 17→15；`ITERATION41_REPLAY_RUNTIME_SET` 与
  `ITERATION41_MANAGED_REPLAY_RUNTIME_SET` 移除被删成员的 id（否则注册表构造即
  `runtime set references an unregistered runtime identity`）；保留 013_3 managed **runtime id**
  （包内注册表继续使用）与 `..._CTP_PRIVATE_*`。
- `backtrader_runtime/__init__.py`：移除 3 个已删名前缀的导入与 `__all__` 条目。
- `backtrader_runtime/runner.py`：`_managed_l2_required_capability_modules` 受审清单 4→3。
- `examples/iteration41-runtime-inventory.json`：移除 2 条已删 entrypoint；`run.py` 的
  `iteration41_replacement` 置 null 并注明退役；scope 文案 "eleven→ten / two→one"。
- `AGENTS.md`：默认注册表 17→15（11→10 非受管、2→1 源 managed），两处现状句同步。
- `examples/013_3_sa_midfreq_simnow/README.md`：内部模块表更新 + 退役清单段。

## 验收（本轮）

| 项 | 结果 |
| --- | --- |
| `tests/unit/runtime` | **747 passed / 23 skipped / 0 failed**（删 3 测试文件、修 4 处计数/参数与 3 处 registry 断言后） |
| 全仓 collection | 7,200 tests collected（无删除残留 ImportError） |
| 013_3 `run.py` dry / `--replay` | `DRY` / **`LOCAL_REPLAY_PASS`**（三模式不受影响；`--live` 路径本就不依赖被删文件） |
| 登记离线冒烟 | **11 passed / 1 failed(既有 mechanical SDK-source 基线) / 12 selected / 3 skipped**（12/2→11/1 按删路由数平移） |

## 附注

- 013_3 目录仍存有非 .py 历史工件（`ctp-deployment-profiles.example.yaml`、
  `env.broker-production.NOT-SUPPORTED.example`、`fixtures/`、`reports/`），不在 C/D 范围；
  `fixtures/` 与 `--replay` 实现相关，改名前需单独核验。
- 同类 C/D 面在 014_1/014_2/015（simnow_adapter/simnow_launcher/engineering_smoke 历史 seam）
  与其他目录 `run_runtime.py` 上仍存在，可循本轮的登记面清理模式做后续统一轮。
- 本记录随后续同 HEAD 验证（周一）更新；不影响任何 windows/Monday 验收流程。
