# R2 验收记录：012_1 四件套化 + 双所 Demo 链（2026-10-09/10）

状态：**实现与迁移完成；Demo 成交往返 = 证据化 BLOCKED（资格工件窗口过期，翻转路径明确）**。

## 本轮范围

- 012_1 标准四件套：`run.py`（dry / `--replay` / `--live --allow-write --mechanical-smoke`）、
  `config.yaml`（新增 `entry` 段：venue/凭据 env 名/policy/timeouts/边界标记）、
  `cross_exchange_strategy.py`（原 strategy.py；数字前缀目录不能作 Python module 名，故用描述名）、
  `README.md`（重写）；旧引擎 → `legacy_runner.py`。
- manifest 刷新链：canonical（`strategy_module`、runner/strategy/config 哈希、candidate_sha256）
  + folder-local（refresh 脚本，`--check` 通过）；`.gitattributes` 路径更新。
- 测试更新：7 个 012 相关测试文件的模块路径/策略文件名/runner 哈希来源锚点。

## 门结果

| 项 | 结果 | 证据 |
| --- | --- | --- |
| dry | DRY（config+entry+5 个 Demo 凭据 env 名；零网络） | 输出 JSON |
| replay | FORMULA_CHECK_PASS（0 网络/0 写单） | `evidence/replay-*/report.json` |
| 测试切片（7 文件） | 382 passed / 1 failed（失败为基线时间门：资格窗过期，见下） | 会话日志 |
| refresh `--check` | 两目录 up to date | — |
| Ruff | run.py / legacy_runner.py clean | — |
| Demo 链路 | 传输层打通：store 构建 → get_account 通过 → admission → 时长下限（≥435s 校验生效） → **资格门拒绝** | `evidence/live-20261009T190823Z-2e8090a1/run.json` |

## Demo BLOCKED：`model_qualification_expired`

- 事实：`qualification-v3.json` 冻结窗口 `valid_from=1788796200 → valid_until=1791388200`
  （≈2026-09-08 → **2026-10-07**，UTC）；准入按设计 fail-closed
  （operator 覆盖仅含校准契约不一致，不含过期）。
- 影响：`--mechanical-smoke`（含 600s 合规时长）在 store 之前被拒；
  同一路径下其余环节都已验证可达。
- **翻转路径（零代码改动，2026-10-10 复核精确化）**：运营/用户按研究治理流程重发
  `012_1/qualification-v3.json` 的有效期窗口后，按以下顺序操作：
  1. 更新 canonical `examples/strategy-candidate-manifest.json` 中该候选的
     `qualification_artifact.sha256` 为新文件哈希，并重算 `candidate_sha256`
     （=canonical JSON〔sort_keys、紧凑分隔符、ensure_ascii=False〕去掉 `candidate_sha256`
     与 `demo_approval` 后的 sha256）；`runner/strategy/config_sha256` 仅在对应文件字节
     变化时更新（窗口重发不涉及）。
  2. `python scripts/refresh_cross_exchange_local_manifests.py`（写模式）刷新两目录
     folder-local 清单（`--check` 只验证不写；**canonical 由人工治理编辑，脚本永不改写它**）。
  3. 原命令 `python run.py --live --allow-write --mechanical-smoke --run-seconds 600` 直接复跑；
     `test_local_admission_manifests_are_current` 与 refresh `--check` 应保持绿。
  **契约哈希无需改动（已核实）**：`qualification_contract_sha256(rules, risk, 买venue, 卖venue)`
  只绑定合约规则/风险模型/方向，不含窗口字段——窗口重发不影响它。
- 治理说明：该工件为迭代21 冻结研究工件（`RESEARCH_REJECTED`，校准训练用），
  窗口变更属研究治理动作，本迭代不擅自修改（与 R1 的时段门同类：时间型外部约束）。

## 修复缺陷（本轮真实验证）

1. **代理注入缺陷（自引入）**：新 run.py 曾把 checkout `.env` 全量注入进程环境（含
   `HTTP(S)_PROXY=http://127.0.0.1:15732`），SDK httpx `trust_env` 据此走本机代理导致
   Demo REST 传输失败（`get_account RequestFailedError`）。修正为**不注入进程环境**
   （凭据经 `env_file` 参数解析）；修复后 `get_account` 通过。
2. 旧引擎自校验 `entrypoint == __file__` 与标准布局冲突 → 放宽为目录内校验（哈希仍全验）。
3. manifest/`.gitattributes`/7 个测试的路径与哈希绑定全面对齐新布局；
   `load_config` 允许新 `entry.yaml` 段（候选绑定字段不变）。
4. 另记录：urllib 默认 UA 被 OKX WAF 403（SDK 用 httpx，默认 UA 正常，无需改动 SDK）。

## 基线项（非本轮引入）

- `test_012_1_operator_demo_override_loads_original_training_artifact_with_mismatch_evidence`：
  自 2026-10-07 起因真实时钟晚于工件窗口而失败（时间炸弹），与迁移无关；
  待资格工件窗口重发后自然恢复。

## 追加：翻转验收完成 — MECHANICAL_DEMO_SMOKE_PASS（2026-10-10 本轮）

按上述翻转路径重发窗口、修复阻断缺陷后，真实 Demo 机械冒烟通过。

### 重发与链刷新

- `012_1/qualification-v3.json` 窗口重发为 `valid_from=1791590400 → valid_until=1794182400`
  （2026-10-10 → 2026-11-09 UTC）；契约哈希不变（已核实）。新文件 sha256 =
  `da8363391ae3ab25c7df32c238a4440fe36970d64686b7bcdb67327299e39ee2`。
- canonical `qualification_artifact.sha256`、`candidate_sha256`（float 修复后为
  `877a2c3194fc48d18dfef0144c47ecc59969247ff20e3aa85b25cac676a1bac7`）与
  folder-local 清单同步刷新；refresh `--check` 绿。

### 阻断缺陷链（全部定位并修复）

1. **前基线形态**（阻止初次冒烟）：store 修复 A+B + 限定码 + 3 个回归（`54bf59b2d`）。
2. **Decimal/float 提交边界**：策略提交 `size/price` 显式 `float()`（`e4f990758`）；
   修复后出现首次真实成交（4 笔，含 2 开仓），暴露第 3 项。
3. **SDK 竞态 `reconciliation_errors`（-2013 粘性）**：轮询在订单提交在途窗口
   按 client id 查询 → Binance `-2013`；订单完成后不再轮询 → 错误永久残留 →
   broker 停机 `remote_flat_proven=false`（证据 `live-20261010T072540Z-7c4eb44b`：
   `reconciliation_errors={'161007659700':'-2013','161408116000':'-2013'}`）。
   SDK 修复（`D:/bt_api_py` `_execution_session.py`）：
   - 新状态 `next_poll = now + order_poll_interval`（提交在途窗口不轮询）；
   - `_record` 收到 venue 身份/终态更新时清除陈旧 `reconciliation_error`；
   - replay 水合保留“重启立即对账”语义（`next_poll=0.0`）。
4. **SDK 费用标志跨重启复活**：completed 行持久化 `fee_unresolved=True`，而 trade
   行未持久化 `fee_resolved` → 重启后 `fee_unresolved_orders` 复活 → 启动就绪门
   `demo reconciliation evidence is incomplete`（证据 `live-20261010T074659Z-bf18ab50`）。
   SDK 修复：trade 行持久化两个标志；replay 双向重建（`fee_resolved` 可清除）；
   旧格式 trade 行按 `commission_source == "exchange"` 忠实重建（与实时变更同构）。

- 回归：SDK `tests/bt_api_contract/test_execution_session.py` 183 passed / 2 skipped
  （新增 5 项：在途不轮询、-2013 竞态清除、费用重开重建 ×2、未解决负例）；主仓
  store `test_btapistore_iteration21.py` 122 passed；012 系全切片
  （66/86/128/43/43/43）绿；只读探针 `READINESS-PASS`
  （`fee_unresolved_orders=[]`、`unknown_ids=[]`、`evidence_errors=[]`、
  `proof_snapshot=true`）。

### 真实验收结果

- 运行 `live-20261010T075052Z-447e9a10`：`MECHANICAL_DEMO_SMOKE_PASS`（exit 0）。
  - 开仓 2 笔（okx sell 0.01 / binance buy 0.010，`alpha_intent_history_used=false`）；
    fills=4；`account_risk_evidence_complete=true`；
  - `broker_shutdown = PASS / reason=remote_flat_proven / remote_flat_proven=true`，
    active/local/remote/unknown 全 0；store `shutdown_state=PASS`；
  - `mechanical_smoke.state=FLAT_RECONCILED`；边界
    `MECHANICAL_DEMO_SMOKE_NOT_RESEARCH_NOT_PROFITABILITY`。
- 中间失败记录保留不改写：`7c4eb44b`（-2013 竞态）、`bf18ab50`（费用标志复活）。

### 边界

不构成策略有效性、盈利或生产准入证据；候选研究状态与 HFT 标注不变。
