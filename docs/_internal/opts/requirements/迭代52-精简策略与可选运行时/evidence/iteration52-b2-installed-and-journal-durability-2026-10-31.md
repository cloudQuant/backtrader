# 迭代 52：安装层证据与 journal 终态持久化修复（2026-10-31）

- 仓库/分支：Backtrader `dev`（HEAD `5c7d0d66c` + 本文档提交）；SDK `dev` `4e15913f`；runtime 子仓 `5078776`
- 证据等级：INSTALLED（runtime/contract/Backtrader/base wheel 安装消费，部分依赖复用系统 site-packages）+ 真实 OKX SWAP Demo paper 重验收
- 不改变生产写入未授权、SimNow 未验收、旧 runtime 未退役的边界

## 1. 安装层证据

### 1.1 Wheel 与哈希

在 `D:/temp/i52-wheels/` 构建：

| Wheel | SHA-256 |
| --- | --- |
| `bt_api_runtime-0.1.13-py3-none-any.whl` | `78f7c1367dbeefe7a2dae723c1fdb7c09953a3db8dba6e6168d8377bb7c46b5c` |
| `bt_api_run_contract-0.1.5-py3-none-any.whl` | `bb3888a96d4b9de8fee933d8b5dcbdd82142919c9c8c87df2284334c441a1f5f` |
| `back_trader_python-1.4.0-py3-none-any.whl` | `9ff18364c1e488ea1ca152a6d0e7aa79905e492efda6986fde934307d9f9ac98` |
| `bt_api_base-0.15.8-py3-none-any.whl` | `0b288c0c0e1279f8908ea79fcf60d5188825cfd2937b78ef1c2702c0b01cb0fc` |

### 1.2 隔离消费环境

`D:/temp/i52-installed/`（Python 3.11.5，`--system-site-packages`，未使用仓内 runtime/contract 源码）：

- 四个 distribution 均从上述 wheel 安装：
  - `bt-api-runtime 0.1.13` → `D:\temp\i52-installed\Lib\site-packages\bt_api_runtime\__init__.py`
  - `bt-api-run-contract 0.1.5` → 同 env
  - `back-trader-python 1.4.0` → 同 env
  - `bt-api-base 0.15.8` → 同 env
- scoped 依赖检查（按环境 marker 过滤）：
  - runtime 3/3、contract 1/1、Backtrader 7/7、base 15/15 全部满足；无 bad。
- RECORD SHA-256 校验：
  - runtime 9 行、contract 9 行、Backtrader 742 行、base 8 行，全部匹配，0 bad。
- 惰性导入：
  - `import bt_api_runtime` 后 `backtrader`、`bt_api_py` 均未加载；runtime/contract origin 指向安装目录。
- 测试：
  - `runtime/tests/test_direct_backtrader.py`：**11 passed**（安装包 + 安装 Backtrader）。
  - `contracts/tests`（`-o pythonpath=` 禁用源码路径）：**57 passed**。

### 1.3 边界

- 依赖闭包复用系统 site-packages（PyYAML、numpy、pandas 等），不是完全离线的 dependency-closed wheelhouse。
- `bt_api_py` 未安装为 distribution；provider/Runtime 完整消费仍以 dev 源码和真实 Demo 为准。
- 因此 F18 安装层记为 **PARTIAL**：新 runtime/contract 的 wheel/RECORD/origin/消费已验证；旧 runtime 退役与完整 SDK 组合仍 BLOCKED。

## 2. SDK journal 终态持久化修复（`4e15913f`）

### 2.1 根因

`_ExecutionSession.poll_due` 的到点查询只更新内存 `state` 和 broker 队列，不写 journal。Broker 可从查询/成交得到 Completed，但进程重启后旧 journal 仍把该订单当 UNKNOWN，导致后续写被 `unresolved_or_undurable_journal` 拒绝。此前 iteration-52 运行时用 provider-confirmed 查询恢复补偿。

### 2.2 修复

- 对查询结果与上次状态做**语义签名**比较（status/filled/avg_price/order_id/client_order_id/terminal_confirmed/execution_unknown/fee flags）。
- 签名变化时通过正常 `event()` 路径确认并 journal 终态，再入 broker pending 队列；无变化不重复写。
- 新增 `test_due_query_terminal_confirmation_is_durable_across_restart`：未知订单经到点查询确认后，**关闭并重开 journal**，`unknown_ids=[]` 且不交易阻断。

### 2.3 回归

`tests/bt_api_contract/test_execution_session.py`：**182 passed, 2 skipped, 1 failed**。唯一失败 `test_service_order_entry_preserves_mt5_generic_close_intent_and_rejects_native_fields` 在修复前源码同样失败（已用未改源码复现），属既有问题。

## 3. 真实 OKX 重验收（修复后）

- run id：`i52-okx-demo-20261031T013833Z-6cda90e0`
- 证据：`examples/unified/052_provider_demo_roundtrip/evidence/20261031T013900Z_052_okx_demo_roundtrip_PASS.json`
  （SHA-256 `4b125f915c65c8b65eb9da93c51d779780654deae313792c60eddb5d200ef363`）
- 开仓 Completed：0.19 contracts，均价 77456.19，手续费 0.073583 USDT；
  平仓 Completed：-0.19 contracts，均价 77451.10，手续费 0.073579 USDT。
- store：submit 2 / active 0 / unknown [] / evidence_complete true。
- shutdown：broker PASS、store PASS、`unknown_recovery {unknown_before: 0, recovered: 0}`。
- 运行后新进程只读 preflight：`preflight_ok`、reconcile 无 positions/open orders/unknown/active，确认 journal 终态**跨进程持久**。
- 注意：该笔 close 的 broker `order.info.execution_unknown` 仍为 true（broker 本地通知对象未回写晚到确认）；但 SDK journal、store summary 与新进程 preflight 均为 clean。该投影滞后是后续 UI/状态回写细节，不是 journal 缺口。


## 3.4 执行维护入口与晚到确认回写

在 journal 持久化修复之后，补充 live feed 阻塞时可独立驱动的执行维护路径：

- SDK `BtApi.poll_execution_maintenance(exchange_name)`：驱动到点订单查询、返回 pending 的规范化订单更新，不消费行情、不提交/重试/撤单。
- Store `BtApiStore.poll_execution_maintenance()`：与 `_drain_sdk_events` 共用 `_sdk_event_drain_lock`，把到点查询更新送入 broker 更新队列；`_drain_sdk_events` 本身拆为持锁包装与 `_drain_sdk_events_locked`。
- runtime `_IdlePump` 的 `on_idle` 改为 `_pump_maintenance`：先驱动 Store 维护，再执行 provider-confirmed 恢复。

验证：

- SDK `test_poll_execution_maintenance_delivers_and_persists_terminal_query`：到点查询更新返回 terminal、journal 重启后 unknown 为空。
- SDK execution-session 全套：**183 passed, 2 skipped, 1 failed**（失败项 `...mt5_generic_close...` 在未改源码上同样失败）。
- Backtrader `tests/integration/test_btapi_execution_session.py`：**2 passed**。
- runtime：**159 passed**。
- 真实 OKX 重跑：run id `i52-okx-demo-20261031T014230Z-ec45db47`，证据 `20261031T014257Z_052_okx_demo_roundtrip_PASS.json`（SHA-256 `4764439c60619b4228b41c75d0574eff200c5775323d641c10bc9ee2d9bf8598`）；submit 2、unknown []、store summary evidence_complete true、shutdown PASS。

**残余缺口**：该笔 close 的 broker `order.info.execution_unknown` 仍为 true。原因是 broker 只在 `next()` 消费更新队列时回写 order.info，而策略在停机前未再驱动 `broker.next()`；SDK journal、Store summary 与新进程 preflight 均为 clean。此为客户/UI 投影滞后，已记录为 F09 未完成项，不以假值清除。

## 4. 当前状态与下一步

- F20 仍为 Binance + OKX 两个真实场所；SimNow 未执行，保持 PARTIAL 2/3。
- due-query 维护入口已接到运行泵；下一优先是补 Broker 本地 order.info 的晚到确认回写（需要在停机前有界驱动一次 broker.next 或等价投影），并确认不引入并发消费。
- 随后：SimNow registered-sim 适配、028 迁移、完整 dependency-closed wheelhouse、A0 未闭合项与 R10。
