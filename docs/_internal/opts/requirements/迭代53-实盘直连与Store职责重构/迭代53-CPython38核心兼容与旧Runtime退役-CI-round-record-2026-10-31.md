# 迭代 53：CPython 3.8 核心兼容与旧 Runtime 退役 CI 记录

日期：2026-10-31

## 范围与结果

修复 Backtrader `dev` 分支的 CPython 3.8 CI 调用链。原 `scripts/ci/run_iteration41_cpython38_core_runtime.py` 固定收集 `tests/unit/runtime/` 下五个测试；这些测试随迭代 53 退役旧 runtime 后已归档，当前目录不存在。工作流另外有两个同样指向已归档测试的专用 job。

当前 harness 改为运行活动的核心错误层、Backtrader-owned CTP managed-order 合同和 harness 自身合同测试。运行前先检查活动源码根下旧导入名的包目录和模块文件两种形式：`backtrader_runtime/`、`backtrader_runtime.py`、`backtrader/runtime/`、`backtrader/runtime.py`；若任一存在，则写出明确失败状态并在 pytest 启动前退出。历史源码仍留在 `archive/iteration53/`，不参与默认收集。

CPython 3.8 专用 job 现在安装 Backtrader 基础依赖、不安装 SDK extras，并运行上述当前测试。工作流 `test-summary` 继续要求该 job 和 `wheel-consumer` 成功；wheel-consumer 仍负责检查构建后的发布包及安装树不包含退役 `backtrader_runtime` 包。

两个失效的历史覆盖已从活动 workflow 与 summary 依赖中移除：

- POSIX runtime-directory job 原来调用已归档 `test_runtime_runner.py` 的两个 filesystem case。
- Windows CTP private smoke job 原来调用已归档的旧 runtime CLI 测试。

Windows smoke 辅助脚本保持原样、未修改，当前 harness 文档明确其为历史工具且不由活动 CI 调用。以上历史覆盖没有被替换或伪称为当前 direct CTP 验收。

## 本轮文件

- `.github/workflows/test.yml`
- `scripts/ci/run_iteration41_cpython38_core_runtime.py`
- `tests/unit/scripts/test_run_iteration41_cpython38_core_runtime.py`
- `docs/_internal/opts/requirements/迭代53-实盘直连与Store职责重构/迭代53-CPython38核心兼容与旧Runtime退役-CI-round-record-2026-10-31.md`

未修改 `scripts/ci/run_iteration41_ctp_private_windows_smoke.py`、release wheel verifier 或 wheel verifier 测试。未恢复任何已删除的 live/账户测试。

## 验证

本地环境为 Windows CPython 3.11.5；没有本地 CPython 3.8 执行证据。完整选定测试命令：

```powershell
$env:PYTEST_ADDOPTS = ''
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
python -m pytest -q -p no:asyncio tests/unit/core/test_errors.py tests/unit/stores/test_ctp_managed_order_contract.py tests/unit/scripts/test_run_iteration41_cpython38_core_runtime.py
```

结果：48 passed，1 条现有 `PytestConfigWarning`（禁用插件自动加载时，`asyncio_default_fixture_loop_scope` 配置项未知）。针对 harness 工具合同的单独复跑为 11 passed、同一条警告。

另行验证：

- workflow YAML 可解析；11 个 job 的 `needs` 均指向已定义 job。
- `git diff --check` 对本轮三个代码/工作流文件通过。
- 临时目录测试实际创建并分别检测上述四种目录/文件导入路径。
- Windows smoke 辅助脚本相对 HEAD 无差异；workflow 不再含旧 `tests/unit/runtime/` 收集路径或两个退役 job 名。
- 独立复审对路径检测及临时源码路径测试给出 GO。

## 证据边界与交付状态

此轮只验证了当前 Python 3.11.5 上的本地选定测试和工作流结构；未在 CPython 3.8 本机或 GitHub Actions runner 实际执行新 job。没有运行账户、provider、live、网关或 SDK 行为，也没有增加正式账户验收结果。

仓库：`D:/source_code/backtrader`，分支 `dev`。记录时 HEAD：`47e33a3f56570cc4b69f01d9270670b4a86e466d`。本轮未暂存、未提交；其他工作区修改保留。