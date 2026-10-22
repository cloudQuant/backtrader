# R8 — 015 期权 tick 高频观察层改造与运行记录（2026-10-10）

范围：`examples/015_ctp_options_highfreq` 按四件套标准收敛；策略为**决策专用**
（普通意图只记录、从不提交订单），按 R7/R8 计划修正案采用 **live 观察层**（零写），
`--allow-write` 明确 BLOCKED。本记录含首轮真实运行、发现并修复的看门狗一次性
停机缺陷、以及准入边界的诚实标注与翻转路径。

## 变更

- `run.py`：标准三模式入口。dry = 配置/就绪检查（`live_tier.status=OBSERVATION_ONLY`）；
  `--replay` 复用冻结 tick/cohort 回放；`--live` = 观察层（真实直连 registered-sim 链：
  front 选择 → Store 登录/查询预检 → 3 × `BtApiFeed` tick 分发（`dispatch_ticks=True`）
  → 真实 cohort 策略）。PASS = 每条腿 ≥1 真实 tick 且零写；证据
  `evidence/live-*/{run.json,strategy_report.json}`。
- `config.yaml`：追加 `live_adapter`（schema 1）：真实一篮子 CZCE.FG701 / FG701C970 /
  FG701P970（与 fixtures bundle 一致）、5 组 MD/TD front、`instrument_metadata`
  （FG tick 1.0 / 期权 0.5，mult 20）、`policy.allow_write=false`、`run_seconds 600`、
  `min_ticks_per_leg 1`。
- `legacy_runner.py`：`load_config` 剥离 `live_adapter`（冻结回放键集不变）。
- `simnow_direct.py`：与 013_3 canonical 字节一致的副本；漂移守卫扩至第五份
  （`test_iteration42_simnow_multiarm.py` 9 条断言）。
- 测试适配：dry 断言改为 `OBSERVATION_ONLY` + 写层 BLOCKED；入口 importlib/sys.path
  断言按已验收口径收窄（允许 canonical fence 与 `importlib.util.find_spec`）。

## 首轮真实运行与看门狗缺陷修复（重要工程事实）

首轮 `--live --run-seconds 60` 在准入后进入 RUNNING 但**不返回**（>10 分钟）。
faulthandler 栈转储定位（值无关）：主线程正常循环于 feed 轮询；**看门狗线程已退出**。
根因：`--run-seconds` 是含准入的总预算，而本机 04:5x 仅 7x24 可达，其余 4 组前置
每侧 3 样本 ×3s 连接超时 ≈ +70s；60s 预算在准入尚未结束时到期 → 一次性
`cerebro.runstop()` 在 run 作用域激活前被调用，被 lifecycle 设计**忽略**
（"no active run → ignore"），且看门狗不再重试 → run 永久运行。

修复（已入库）：
1. **看门狗持续压停**：deadline 后循环调用 `cerebro.runstop()` 直到 run 真正返回
   （丢失的单次停机不再可能）；
2. **准入后预算检查**：run 前若总预算已耗尽，直接
   `BLOCKED / observation_window_exhausted_before_run`（含窗口秒数），不再启动无意义窗口。

（014_1/014_2/013_x 观察窗口均为 1800–3000s，准入 ≈20–75s，未触发该缺陷；同模式
加固留待 R9 台账逐项评估，不属本轮范围。）

## 离线验证（全绿）

- 干跑：`python run.py` = DRY/OBSERVATION_ONLY/exit 0；`--replay` = `LOCAL_REPLAY_PASS`；
  `--live`（3.14 无写授权）= BLOCKED `live_tier_requires_python_3_11`；
  `--live --allow-write` = BLOCKED `write_tier_not_implemented_for_decision_only_strategy`。
- 测试：`test_ctp_options_highfreq_example.py` **113 passed**；其余 015 组
  （artifact/engineering_observation/engineering_smoke/environment/fixture_evidence/
  live_layers）**98 passed / 1 skipped**；multiarm 漂移守卫（含 015 第五副本）全绿；
  Ruff 全绿。

## 真实观察运行（2026-10-10 05:32–05:36 北京，7x24 环境）

命令（anaconda 3.11 + dev SDK，零写）：
`C:/anaconda3/python.exe run.py --live --run-seconds 240`

结果：**OBSERVATION_PASS**（exit 0，240.3s 有界返回，run_error=null）。

| 事实 | 值 |
| --- | --- |
| front 选择 | index 4（7x24）唯一 eligible（MD/TD 3/3，whitelisted，≈0.39s）；4 组标准前置时段外不可达 |
| 登录/预检 | read-only ready；account 1 行 / positions 1 行；三腿 metadata 与配置一致（tick 1.0/0.5/0.5，mult 20）；7x24 无涨跌停价 |
| 真实 tick（按腿） | FG701 **151**、FG701C970 **13**、FG701P970 **1** → 每条腿 ≥1 ✓ |
| 策略回调 | tick 165；全部先记到达再准入（L1/L2 先于决策） |
| 准入事实 | `reject_counts = {TRUSTED_NOW_INVALID: 165}`；`cohort_decisions=0`；`execution_eligible_ticks=0`；`clock_rejection.latched=false` |
| 写入 | `order_write=0`；意图 0；外部写入无路径 |
| 证据 | `examples/015_ctp_options_highfreq/evidence/live-20261009T213253Z-39d69fb7/`（git-ignored） |

## 准入边界（诚实标注）与翻转路径

策略的 cohort 合同要求每个 tick 携带 `ctp.quote.v2` 证据与同一时钟域的决策边界时间
（`cohort_decision_now_*`，`validate_ctp_quote` 对 schema 严格校验）。直连 CTP tick
源（store 打标lane）**不产出**该证明——本迭代不伪造：真实 tick 全部以
`TRUSTED_NOW_INVALID` 记录为到达+拒绝事实，`cohort_decisions` 保持 0，HFT 标签保持
`FAIL/NOT_ADMITTED`（本迭代不做 HFT 延迟认证）。翻转 = 生产 v2 证明与校准决策边界
时钟的专用适配轮（与 014_1 R6 记录同源结论）；周一 13:45 标准前置窗口复跑
（`--run-seconds 300`），预期 tick 更密、观察结论不变（准入边界与前置无关）。

## 判定

- 观察层验收成立：真实 tick 经标准入口贯通（每条腿 ≥1），零写，有界返回，
  准入事实完整；`OBSERVATION_PASS` 不含任何 HFT/盈利/执行结论。
- 本轮同时修复了 live 入口的看门狗停机缺陷（对全部使用同模式的示例具有防护意义）。
