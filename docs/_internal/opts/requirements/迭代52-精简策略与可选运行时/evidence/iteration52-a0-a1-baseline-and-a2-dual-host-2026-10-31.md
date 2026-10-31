# 迭代 52：A0 总清单、A1 重基线及 A2 双 Host 控制面测试验收（2026-10-31）

- 仓库/分支：Backtrader `dev`
- 父提交：`f6e0fe02bc4a09803b95f7d960117cf4ff5f56bc`
- 本轮范围：文档 A0/A1 基线整理；`tests/test_service_read_proxy_integration.py` 的 I52 A2 双 Host 只读控制面测试修正
- 证据等级：SOURCE + 真实本地双 ServiceHost + 真实 CURVE/ZMQ + 合成 provider 叶子；不是 provider 账户验收

## 1. A2 双 Host 控制面测试

原交接说明记录：该测试草稿访问不存在的 `RegisteredBinding.peer` 属性，最近一次运行状态 `UNKNOWN`，且未记录子进程退出码。

本轮按公开合同修正：

- `RegisteredBinding` 不提供 `peer`；账户侧使用 `runtime.account_binding_view(mount, account_ref, required_operations=...)`，其字段为 `account_ref` 等，不含 peer。
- 行情侧使用 `runtime.market_binding_view(mount, required_operations=...)`，其 `peer: WireIdentity` 与 `market_endpoint` 是公开字段。
- 保留原有 `RegisteredBinding` 的 mount/service_id/operations/run_id 断言；仅把不可用的 `.peer` 断言替换为公开 view 断言。
- 测试自身的 `finally` 已记录并校验每个 spawn 子进程的 PID/退出码/正常关闭；本轮通过说明清理路径可观察且未强制清理。

执行命令：

```bash
PYTHONPATH="D:/bt_api_py/bt_api/bt_api_runtime/runtime/src;D:/bt_api_py/bt_api/bt_api_runtime/contracts/src" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/Scripts/python.exe -m pytest \
  tests/test_service_read_proxy_integration.py -q -p no:cacheprovider
```

结果：`5 passed, 1 warning in 16.02s`。warning 为既有 `asyncio_default_fixture_loop_scope` 配置项；本文件在无插件自动加载模式下运行。

边界：

- 该测试的账户/行情 Host 为真实 `ServiceHost`/`ServiceClientRuntime`，provider 是合成叶子；CURVE 密钥本地生成，SQLite 为临时目录。
- 它证明双 Host 发现/注册/公开 binding view/无业务调用/正常关闭，不证明真实 provider 账户、授权或写入。
- 由于测试导入 `bt_api_run_contract`/`bt_api_runtime`，运行需要对应源码根；这与本仓既有 SDK 集成测试的源码根做法一致。

## 2. A0 总清单

新增 `A0-总清单与验收索引.md`，把既有 20 份 A0 记录合并为单一登记表：

- 旧 runtime 模块/CLI/资源/配置面 69 行；示例与入口 18 行；三场所 99 案按 venue 块登记并指向逐案文档；Optional16 16 行；延期资产 15 行。
- `A0-OPEN-01…25` 明确列出未闭合项。
- 四项 A0 验收标准中 #1–#3 仍 OPEN（唯一 owner 仍存在“待指定/UNRESOLVED”，99 案正式状态未重新核验，延期保留位置仍待落地），#4 CLOSED。
- 版本/HEAD 事实以本轮实测重基线：contract 0.1.5、runtime 0.1.12、Backtrader `f6e0fe02bc4a0980…`、SDK `c68b8dff…`、runtime 子仓 `4236fa7c…`。
- 该文档是清点整合，不新增能力或正式 PASS。

## 3. A1 合同重基线

`A1-统一配置与适配器合同.md` 做机械式事实更新并追加“修订记录”：

- contract 0.1.4→0.1.5、runtime 0.1.4→0.1.12、runtime HEAD `7b05ffc6`→`4236fa7c…`、SDK HEAD `2b603535`→`c68b8dff…`。
- `f6f70ca4` 更正为 bt_api_runtime 历史提交，不是 SDK 提交；`df0e0b887`/`0f88508d3` 标为历史快照。
- 测试计数更新为当前 57（contract）与 148 collected/passed（runtime，含 53+38 参数化）；旧的 56 项/55 passed 保留为历史。
- 保留并强化“permit 未实现、无 CLI、无 topology 选择、无 managed/write 路径、仅只读装配”的边界声明。
- 结论：A1 合同在 source/fake 层可冻结，但实现缺口（permit/CLI/topology/managed/write）仍 OPEN，转入 B 轮。

## 4. 未纳入本轮

- 未修改任何运行时代码；未运行真实 provider 账户；未新增正式 case PASS。
- 历史 tracker 状态不变：99 案历史聚合仍为 12 PASS / 3 BLOCKED / 84 NOT_RUN，Optional16 0/16。
- A0 未闭合项、A1 实现缺口、后续 B/C/D 轮次见 `A0-总清单与验收索引.md` 与 `A1-统一配置与适配器合同.md` 修订记录。

## 5. 下一轮

B1：在 `bt_api_runtime` 合同/运行时补齐 validate/doctor 诊断、topology 显式选择与 fail-closed、插件启停语义、run identity 绑定，并完成首个直接 paper 写链路的最小装配（见计划修订记录）。
