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
- **翻转路径（零代码改动）**：运营/用户重发 `qualification-v3.json` 的有效期窗口
  （或明确授权 operator 过期豁免的代码变更），刷新 canonical/local manifest 后，
  原命令 `python run.py --live --allow-write --mechanical-smoke --run-seconds 600` 直接复跑。
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
