# R11 — 010_live_examples 整目录退役轮（2026-10-11）

状态：**完成待提交**。范围 = 用户判定 `examples/010_live_examples` 为垃圾内容后，
选择"整目录删除并重接"。本轮不保留该目录的任何一路由，注册表由 **13 → 11**，
`iteration41-replay` 集合由 8 → 7，登记离线冒烟不再出现 shadow 跳过项。

## 删除清单（19 个跟踪文件 + 2 个本地忽略配置）

**整目录 `examples/010_live_examples/`（17 个跟踪文件，约 2,980 行 Python）**

- 退役 SimNow 簇：`test_simnow_ctp.py`(803)、`test_simnow_trade_logger_certification.py`(391)、
  `conftest.py`(209)、`fake_btapi.py`(218，`tests/fixtures/fake_btapi.py` 的逐字节副本)、
  `btapi/__init__.py`+`btapi/test_btapi_placeholders.py`(24)、`run_runtime.py`(142)、`runtime/`
- OKX 公共阴影簇：`run_okx_shadow_runtime.py`(721)、`live_mixbroker_okx_demo.py`(275)、
  `runtime-okx-shadow/`
- 未登记示例与包件：`live_tick_demo.py`(197，纯本地 mock tick 演示，除一份旧文档外零引用)、
  `README.md`、`__init__.py`
- 本地忽略配置 `runtime/config.yaml`、`runtime-okx-shadow/config.yaml`：删除前核对
  `secrets_ref: none`、无凭证、无端点值，且由 `bt-runtime bootstrap` 从已跟踪
  `config.example.yaml` 完全可重建，故未另做备份。

**依赖测试**

- `tests/unit/test_live_mixbroker_okx_demo.py`（5 测试，直接 `exec_module` 载入被删 demo）

## 代码编辑（重接）

- `backtrader_runtime/inventory.py`：删 4 个 010 常量（两条 runtime dir + 两条 strategy id）、
  2 个 `RegisteredRuntime`（含 shadow 的 `bootstrap_parameters`）、`ITERATION41_REPLAY_RUNTIME_SET`
  去掉 010 id（同 013_3/014x 轮的关键坑：只删注册不删 set 成员会构造即 ValueError）、
  `iteration41_runtime_registry()` 注册 13→11。
- `backtrader_runtime/__init__.py`：移除 3 个导入 + 3 个 `__all__` 条目（导入面已回读校验）。
- `backtrader_runtime/cli.py`：删除仅由被删 shadow runner 触发的操作语汇——
  `install_reviewed_public_shadow_dependencies`（其命令指向已移除的 packaging extra）与
  `inspect_public_market_session` 两个分支，并从 `provider_io_may_have_started` 白名单移除
  `provider_dependency_*`/`provider_origin_untrusted`/`strategy_callback_*` 五个已无 raiser 的
  reason 名（`capability_dependency_missing` 与 CTP 项保留）。
- `setup.py`：删除 `okx-public-shadow` extras（`ccxt==4.5.83`/`aiohttp==3.14.3`），全仓已无消费者。
- `scripts/ci/smoke_iteration41_registered_offline.py`：去掉 shadow 注册导入与 `SKIP_SHADOW`
  特判，docstring 改为"不跑 private-read 或 live 路由"。
- `scripts/verify_iteration41_writer_dispositions.py`：默认归属前缀表去掉
  `examples/010_live_examples/`（`examples/007_ctp/` 保留）。
- `examples/iteration41-runtime-inventory.json`：删 `public_market_shadow_contract` 与整个
  `public_market_shadow_entrypoints` 段、`iteration41_entrypoints` 的 010 记录（8→7）、
  `legacy_entrypoints` 两条 010 退役行（25→23）；scope 文案改写为"seven ordinary replay
  entrypoints"并移除 010 措辞。JSON 已 `json.load` 回读校验结构。
- `tests/unit/runtime/test_runtime_config.py`：注册数 13→11、`normal_replays` 8→7（去 010 项）、
  删除整段 shadow 注册断言块。
- `tests/unit/runtime/test_runtime_runner.py`：两处 13→11、删除 shadow runner_module 与
  in-registrations 断言。
- `tests/unit/runtime/test_runtime_operator_guidance.py`：删除
  `test_run_failure_after_dispatch_does_not_claim_offline_execution`（钉住已移除的 shadow 分支）。
- `tests/unit/test_examples_self_contained.py`：`OPTIONAL_EXAMPLE_MODULES` 去 010/ccxt 例外、
  `VENDORED_COPIES` 去 `010_live_examples/fake_btapi.py` 别名（canonical
  `tests/fixtures/fake_btapi.py` 仍在役并被 tests 直接引用）。
- `AGENTS.md`：注册数 13→11（两处）、replay 8→7、删除 public shadow 与
  `LiveMultiSymbolStrategy.notify_orderbook` 现状描述，改为 010 目录退役注记 +
  "无 `simulation/shadow` 注册、`okx-public-shadow` extra 同步移除"；冒烟脚本描述改为
  "注册前过滤、跳过 private-read 与 live"。

## 验证（本轮全部在改动后实跑，`C:/anaconda3/python.exe`，`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`）

| 项目 | 结果 |
| --- | --- |
| `tests/unit/runtime` 全量 | **746 passed / 23 skipped / 0 failed**（1 既有 warning；上轮 747，-1 = 本轮删除的 shadow 指导测试） |
| 三个直接改动测试文件聚合 | 119 passed / 13 skipped / 0 failed |
| 守卫+示例聚焦集（self-contained/component-boundaries/fingerprint/front-failure-evidence） | 81 passed + 3 failed = **既有基线**（000 optional16 组件导入、013_1/013_2 `ctp_example_support.py` 字节漂移 ×2） |
| 登记离线冒烟 | **8 passed / 1 failed / 9 selected / 2 skipped**（1 failed = `mechanical_managed_replay_l2` 缺 `bt_api_risk` capability 的既有 SDK-源码基线；shadow 跳过项已消失） |
| 注册表完整性 | `iteration41_runtime_registry()` 11 注册、replay set 7、`backtrader_runtime.__all__` 无缺失符号、注册面零 010 残留 |
| 已删目录 CLI 行为 | `bt-runtime doctor --strategy-dir examples/010_live_examples/runtime` → `runtime_not_registered` / 建议 `review_registration`（fail-closed，不回退发现） |
| ruff（全部改动 .py） | All checks passed |
| `py_compile`（全部改动 .py） | 全绿 |
| `black --check -l 100` | 本机 black 过旧（不支持 py312 target），未拆行差异为**既有全仓基线**（未改动的 `backtrader_runtime/config.py` 同样报 reformat）；本轮改动 hunk 未引入新差异，`smoke_...py` 完全干净 |

全量 `tests/unit`（去 strategies）后台复跑结果见提交前补充；首个失败
`tests/unit/brokers/test_btapibroker_arbitrage.py::test_store_rechecks_approval_immediately_before_async_sdk_write`
的依赖面（`backtrader/`、`tests/unit/brokers/`）本轮零改动且 `git status` 干净，属 HEAD 既有失败。

## 备注与遗留

- **迭代41 历史文档未改写**：`docs/_internal/.../迭代41-.../README.md` 第 127 行仍写"1 条公开
  OKX `simulation/shadow`"，`templates/README.md` 亦把 010 列为 legacy no-action 之一。沿用
  014x/013_3 轮约定：已关闭迭代的需求记录属历史证据，不改写；现状口径以 `AGENTS.md` 为准。
- **既有陈旧指针（本轮之前即存在，未修）**：`examples/iteration41-runtime-inventory.json`
  的 007 legacy 记录仍把 `verification_tests` 指向不存在的
  `tests/unit/runtime/test_iteration41_legacy_ctp_007_010_gate.py`；原 shadow 记录同样指向
  不存在的 `tests/unit/test_iteration41_okx_public_shadow_runtime.py`（后者随本轮删除）。
  `tests/unit/scripts/test_verify_iteration41_writer_dispositions.py` 6 项失败源于
  `scripts/collect_iteration41_writer_inventory.py` 已不在跟踪面（HEAD 亦无），与本轮无关。
- 被删的公共盘口阴影路由是全仓唯一的 `simulation/shadow` 注册；配置 schema 仍接受
  `simulation/shadow` 模式/预设词表，但注册表内已无对应路由，任何 shadow 配置都会在
  注册查找处 fail-closed。若将来需要公开行情观察能力，应作为新的、独立评审的注册路由重建。
- 000/007 认证套件已实际覆盖 SimNow 与 OKX/Binance 的公开与账户只读面，本轮删除不减少
  任何已验收能力。正式三场所计数（12 PASS / 3 BLOCKED / 84 NOT_RUN）与 optional 0/16 不受影响。
