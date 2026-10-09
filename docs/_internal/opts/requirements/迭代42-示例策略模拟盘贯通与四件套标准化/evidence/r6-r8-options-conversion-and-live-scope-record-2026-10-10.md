# 迭代42 R6–R8 — 期权示例四件套化与 live 层范围修订记录（2026-10-10）

状态：**四件套化完成并离线验收**；live 层为**证据化 BLOCKED（集成轮待建）**——这是 R6
侦察后对迭代计划 R6–R8 的**范围修订**（依据目标授权"按行业最佳实践改进优化迭代计划"
与计划既有的"证据化 BLOCKED + 如实写明翻转所需变更与复验范围"条款）。

## 范围修订依据（侦察结论）

014_1/014_2/015 的策略合同（`execution_timing.py` + `ctp_options_*_strategy.py`）要求：

- **feed 密封的 closed-bar 证据**：每腿 `BarEvidence`（clock_domain/clock_mode/
  clock_mapping/candidate_id/rules_hash 绑定）在数据行推进前经 `notify_bar` 进入
  `MultiLegBarBarrier`；证据 provider 必须与 store 事件的 `clock_domain_id`/`rules_hash`
  逐项一致；
- **运行域非合成 `ClockMapping` + `clock_provider`**：执行窗口 1s/60s 门控与
  持有投影消费该时钟；
- **写能力 adapter**：历史上仅存在只读工程观察 seam（014_1 `simnow_adapter.py`
  1743 行、015 `engineering_smoke.py` 863 行，均注入式零写）；写路径从未实现。

因此 live 集成需要一个**专用 adapter 轮**（tick/bar 证据 provider + clock mapping +
三腿 registered-sim 写桥 + drill 触发 + 真实合约映射）。本迭代无此预算；**拒绝
降级为 raw-line 回放合同并伪装 live 验收**——`--live` 在任何网络/凭据/provider 之前
fail-closed，输出精确集成需求与翻转路径。

## 交付（本轮）

- 三个目录四件套化：`README.md` + `config.yaml`（冻结段不动）+ `<name>_strategy.py`
  （原名已符合约定，未动）+ `run.py`（新标准入口：dry / `--replay` / `--live`）；
  旧 `run.py` → `legacy_runner.py`（冻结引擎，供入口、`run_runtime.py`、
  `simnow_launcher.py` 与测试复用）。
- `--live --allow-write`：证据化 BLOCKED（`live_adapter_not_integrated` +
  `integration_requirements` + `flip_path` + 零网络/零写计数）；无 `--allow-write`
  时 REJECTED（`write_consent_missing`）。
- 登记回放路由修复：三目录 `run_runtime.py` 改为引用 `legacy_runner`；015
  `simnow_launcher.py` 懒导入同改。
- 测试：13 个单测文件（option 族）+ 2 个集成文件导入锚点迁移到 `legacy_runner`；
  两个 run.py 内容合同测试重写为新四文件契约（旧 CLI flag 在框架导入前拒绝）。

## 离线验收（实际执行）

| 项 | 结果 |
| --- | --- |
| dry（三目录） | exit 0：配置校验通过；live 层 = `BLOCKED_PENDING_LIVE_ADAPTER`（含集成需求清单） |
| `--replay`（014_1 no_edge / 014_2 no_edge / 015 默认 valid_cohort） | 均 `LOCAL_REPLAY_PASS`（零网络零写） |
| 登记回放（`bt-runtime run`，三目录） | 均 exit 0，`LOCAL_REPLAY_PASS`（015 保留 `hft_status=FAIL/NOT_ADMITTED`） |
| 单测 | `pytest tests/unit -k ctp_options` = **583 passed**（含 015 的 113 项主套件、014_1/014_2 全部 fixture/timing/adapter/native-chain 套件） |
| 集成 | 014_1/014_2/015 的 native-broker-chain 与既有基线**逐项一致**（低频频 18 failed、高频 2 failed，均为 HEAD 基线既有、环境相关，见下） |
| Lint | ruff（三入口与全部改动测试文件）clean |

基线既有失败（与 HEAD 逐项 diff 一致，非本轮引入）：`test_ctp_options_lowfreq_native_broker_chain.py`
（18）与 `test_ctp_options_highfreq_native_broker_chain.py`（2）在本机 anaconda 环境下失败
（FakeBtApiClient 链路的完成事实注入用例）；留待 R9 基线清单统一处置。

## 翻转路径（下一 adapter 轮工作项）

1. 三目录共用：feed 密封证据 provider（逐腿 `BarEvidence`，绑定事件
   clock_domain/generation/rules/candidate）+ run 级 `ClockMapping`/`clock_provider`
   （非合成、覆盖有界窗口）+ 策略 live 参数（`require_feed_bar_evidence=True`、
   `bar_evidence_clock_mode='live'`、`bar_evidence_clock_domain`）。
2. `RegisteredSimStore` 三腿武装模板（future+call+put）——现有多腿武装机制已支持 N 腿。
3. 一次性 engineering drill 触发（天然进场需 40×15min 窗口/预热）。
4. 014_2 真实合约映射（替换 `F_LOCAL`）；SA/FG C/P/F 合约与行权价只读回读。
5. 落地后复验：dry/`--replay` 回归 + SimNow 时段内三腿 drill 往返（与 R1/R4/R5 串行）。

## 证据层级

本记录为**离线/源码级**证据（dry、回放、登记回放、583 项单测、ruff 与基线对照）；
不构成账户、provider 或成交结论。期权 live 层在本迭代保持 BLOCKED。
