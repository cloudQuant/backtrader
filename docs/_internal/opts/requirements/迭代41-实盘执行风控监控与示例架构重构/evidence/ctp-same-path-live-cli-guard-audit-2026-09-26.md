# 同路径 CTP mode 切换与默认 CLI 拒绝审计（2026-09-26）

状态：`OFFLINE_SYNTHETIC_AUDIT / DEFAULT_LIVE_CLOSED / NO_WRITE`。本页记录只读代码审计、临时合成配置 CLI 调用和已有离线测试。未打开默认受保护 `config.yaml`，未使用私有账户/凭据/地址，未访问 SDK、provider 或网络，也未修改默认 registry、runner 或写入路由。

## 默认 registry 与拒绝顺序

审计入口为 `iteration41_runtime_registry()` 返回的默认 Iteration 41 registry。013_3 code-owned registration 只有 `simulation/sandbox` profile：能力为空、approval receipt 为空、runner 为空、`sandbox_write_policy="deny"`；同一 registration 将 `live/managed_live_direct` 列为 `managed_live_direct_profile_unavailable`。registry 构造检查该精确 shape，并要求绑定与 sandbox-only profile 相符（`backtrader_runtime/inventory.py:154-181`、`backtrader_runtime/registry.py:653-714`）。`resolve_runtime_config()` 在参数/secret policy 与有效配置封签之前检查 unavailable mode profile 并拒绝（`backtrader_runtime/registry.py:1431-1439`）。

针对真实默认注册目录，只调用了 `cli.main(["preflight", "--strategy-dir", str(registration.runtime_dir)], registry=default_registry, environ={})`。返回 exit 2、reason `ctp_simnow_preflight_supervisor_required`、`offline=true`、`provider_preflight_started=false`，`backtrader_runtime.runner` 未导入。CLI 在进入配置校验前按 runtime ID 关闭普通 CTP preflight（`backtrader_runtime/cli.py:1481-1497`）；因此此调用没有读取受保护配置。

## 同一临时配置路径切换

为不接触私有配置，仓库测试 `tests/unit/runtime/test_ctp_same_path_cli_gate.py::test_default_ctp_profile_rejects_same_path_live_cli_before_side_effects` 从默认 registration/profile 与 code-owned readonly binding 建立临时目录副本；副本只改 runtime directory，其 profile facts 保持默认值。测试在同一个临时 `config.yaml` 路径先写入合成 `simulation/sandbox`，随后只切换 mode/preset 为 `live/managed_live_direct`，并调用 CLI `main()`：

```text
main(["run", "--strategy-dir", TEMP_DIR])
main(["run", "--strategy-dir", TEMP_DIR, "--confirm-live"])
main(["check-ctp-fronts", "--strategy-dir", TEMP_DIR])
main(["doctor", "--strategy-dir", TEMP_DIR])
```

其中 `TEMP_DIR` 是 pytest 一次性临时目录，只保存合成配置。sandbox `run` 返回 exit 2 / `profile_dispatch_unavailable`（默认 profile 没有 runner）。切到 live 后：`run` 与 `check-ctp-fronts` 均返回 exit 2 / `managed_live_direct_profile_unavailable`；`doctor` 返回 exit 2，错误诊断标为 offline 并保留 live-unavailable reason。自动化测试对 dispatch、credential resolver、runner import、SDK import、socket connect/DNS 设拒绝桩，并断言计数均为 0。该测试不运行 `preflight`；默认 registration 的实际 CLI preflight 早拒结果是前述单独的离线观测。

默认 live `run`/`doctor` 没有对真实 runtime directory 执行，因为那会加载受保护配置。默认 registry 的 live rejection 由 registry profile declaration、resolver 检查顺序及临时 clone 的 CLI 调用共同验证；默认目录只用于提前关闭的 `preflight`。

## 同文件切换后的 receipt 与 seal

已有非授权 `ctp_mode_scope` contract 在同一合成路径先绑定 `simulation/sandbox`，再重写为 `live/managed_live_direct`。旧 effective/scope 经新文件重新校验时被拒绝；新 scope 的 config/effective/profile/scope digest 均变化，mode profile 的测试 receipt 也分别绑定各自 profile。Scope DTO 所有 provider、credential、execution、write、submit、cancel 和 arming authority 均为 false。相关证据在 `tests/unit/runtime/test_ctp_mode_scope.py::test_same_canonical_config_path_binds_simulation_and_live_profiles` 与 `::test_forged_effective_and_old_profile_receipt_are_rejected`。这些是合成 receipt/digest 的防误复用合同，不是 SimNow provider receipt，也不授予 session 或交易权限。默认 registry 没有 live profile/receipt，因此默认路径下不存在可复用为 live 的 sandbox receipt。

同文件生产 action scope 的离线负测还改变账号、前置或合约字段后，旧 scope/approval 在 trust-source 调用前被拒绝：`tests/unit/runtime/test_ctp_production_action_binding.py::test_old_production_action_scope_is_rejected_after_same_file_change`。此 synthetic live profile 不属于默认 registration，也不打开默认写路由。

## 可复现离线测试

通过的 focused suite：

```powershell
python -m pytest -p no:asyncio tests/unit/runtime/test_ctp_same_path_cli_gate.py tests/unit/runtime/test_ctp_mode_scope.py tests/unit/runtime/test_ctp_sandbox_readonly_admission.py tests/unit/runtime/test_runtime_profiles.py::test_profile_cli_keeps_unavailable_live_before_any_dispatch tests/unit/runtime/test_runtime_profiles.py::test_confirmed_synthetic_live_profile_stops_before_runner_import -q --tb=short
python -m ruff check tests/unit/runtime/test_ctp_same_path_cli_gate.py
```

结果：`38 passed, 1 existing PytestConfigWarning`；Ruff `All checks passed!`。本机默认 pytest plugin auto-load 组合在一次未禁用 asyncio plugin 的初始收集时因 `pytest_asyncio`/pytest collector API 不兼容而报 `Package` 缺少 `obj`；同步目标用例在 `-p no:asyncio` 下通过。该环境配置 warning 和 plugin 收集问题均不是产品代码测试失败。

没有发现从同路径 mode/preset 修改到 live 的 CLI 绕过，不需要代码修补。当前默认状态仍为 `simulation/sandbox` 零写、普通 preflight fail-closed、`live/managed_live_direct` unavailable；本审计不证明 native/provider readiness，不启用 live runner、credentials、SDK、socket 或任何写入。
