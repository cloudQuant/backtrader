# CTP I12 TD-only 只读候选（2026-09-25）

状态：`OFFLINE_DESIGN_REVIEW / FAKE_TESTS_ONLY / NO_WRITE / LIVE_NO_GO`。本页记录 I12 adapter、独立 latch、固定 Windows Job 组合入口、TD artifact verifier 与 fake-only tests 的设计复核；它不记录真实运行。其后唯一 I12 supervised one-shot 已执行，结果另见[I12 真实诊断记录](ctp-i12-td-only-diagnostic-2026-09-25.md)。未建立成功 TD session 或 query，默认 inventory/runtime route 未注册。

## 历史证据边界

H2 和 I2 曾完成七类 TD 查询并收到终包，但 native `Join` 未完成，完整只读 preflight 因关闭不完整而拒绝。I2 的 instruments 查询有 83 行同交易所结果；margin/commission 的 `ExchangeID` 为空，范围仍是 `unverified`。这些查询不是原子账户快照、结算确认、账户验收、交易 readiness 或写入准入。I11 后续 MD-only 受监督尝试也以 `native_join_pending` 结束；它只说明那次 MD close 未完成，不是 I12 TD 结果。详见[历史脱敏摘要](validation-summary-2026-09-24.md#latest-checkpoint-i2-current-config-official-td-retry-and-md-only-diagnostic-2026-09-24)与[I11 记录](ctp-i11-md-diagnostic-2026-09-25.md)。

## 候选实现与调用边界

`ctp_i12_td_only_readonly.py` 只使用 `CtpSdkReadOnlySessionFactory` 的 TD `open_read_only`、identity、七查询 snapshot 和 close contract；没有 MD client 登录/订阅路径，也没有 settlement、order 或 cancel 操作。`CtpSdkReadOnlySessionFactory` 固定查询 account、positions、orders、trades、instruments、margin rates、commission rates；SDK native query certificate 缺少终包、scope、代次或其他完整条件时不会得到完整 snapshot。费率交易所范围只投影 `exact` 或 `unverified`。

受支持入口的顺序为：无凭据 sealed-config/pair 传输前检；校验 fixed isolated-venv 命令；再由 metadata-only Windows Job 检查 I12 独立 artifact pin；只有此前都成功才读取/预留 I12 latch 并启动受监督 TD child。父 selector 对 sealed config 的候选 whole-pairs 做有界、未认证 TCP 探测；child 只对父进程选中的同一 pair 复检。每次 pair 探测都包括 MD 与 TD endpoint，且沿用现有 whole-pair 选择策略；MD endpoint 的证据仅是传输可达性。I12 native/API 工作严格 TD-only：不构造 `MdClient`，不登录 MD，不订阅行情。artifact preflight 只读安装 metadata/RECORD，不导入 SDK 或 TD/resolver 模块，不读 credentials，也不消费 I12 marker。child fresh seal 后重查同一 config digest、registration digest、pair index 和 pair；随后再次运行 I12 artifact verifier，通过后才导入 credential resolver、解析凭据并构造 TD-only factory。precheck 或 artifact pin 失败不读取或写入 I12 marker。

I12 marker 是 `ctp_i12_td_only_latch.py` 内独立定义的 one-shot marker。Child 只接受固定 Job 命令、精确 I12 Job membership 和专属 marker；attempt 只在 parent artifact-only preflight 通过后预留。marker 不会重置或引用 I10/I11 marker。未来也只有明确的 I12 operator 入口能启动该候选；它不在默认 runtime registry/CLI 路由中。

child 回执严格通过 `ValueFreeReceiptSchema`，仅含固定枚举/布尔值。所有七查询、TD identity、费率范围、零写计数、可信完整 close 和 Job 退出/清理同时为正证据时，父进程才返回 `td_readonly_complete`。完整 close 要证明 native Release、Join（或明确无需 Join）、线程退出、无超时和 stop 返回成功。完整且一致的 typed close 明确报告 Join pending 时，结果是 `incomplete / native_join_pending`；缺字段、矛盾、ordinary exception 或旧 thread fallback 都是 `unknown`，不会推断为 pending 或成功。完成回执仍将账户 readiness、交易 readiness、settlement call 和 order submission authorization 固定为 false。Job empty 只证明进程 containment，不证明 native Release/Join。

## I12 artifact pin

I12 有独立 `CTP_I12_TD_ONLY_READONLY_ARTIFACT_PINS` 和 `verify_ctp_i12_td_only_readonly_artifact_provenance_for_fronts()`；I10 MD-only verifier 没有被调用，也不能外推成 TD 许可。两个 I12 pin 绑定同一受控 CPython 3.11.5 no-system-site-packages venv 的 base/CTP wheel 与安装后 `RECORD`：`bt_api_base` installed `RECORD` SHA-256 `47994f991fee3266e62fb368fe167dc1f188eceecfddac6ccc06dad2604e9762`；CTP source commit `a6253a58b1ebca11f58c8836fbed757d0daf7582`、version `2.0.3+iteration41.i10`、reproduced wheel SHA-256 `e81bd7fcba8f0aaf823af9efcca565622a55842ed3bce970994f483f4f3188c4`、受控 installed `RECORD` SHA-256 `c0cd1f19a6af3f2bab0fc98042b5042e620565b67751bae362bf5d697649d673`。CTP installed hash 包含固定安装来源 `direct_url.json`，不同 clean-clone target 的 installed `RECORD` 不可替代该受控安装 pin。wheel 内嵌 `RECORD` 也不能作为代码 pin。I12 表和 verifier 是独立授权边界；artifact identity 本身不授权任何 provider session、结算或写操作。详见[I10 clean-clone wheel receipt](ctp-i10-md-readonly-candidate-2026-09-25.md)。

## 离线验证与未完成事项

`tests/unit/runtime/test_ctp_i12_td_only_readonly.py`：`14 passed`；与 close projection suite 合并为 `45 passed`；新 I12 文件及 artifact provenance 定向 Ruff clean，`py_compile` 通过。fresh `python -I` 负测确认导入 operator module 不加载 credential resolver、SDK-backed read-only factory、TD preflight/admission 或 I12 latch；模拟 credential-free precheck 拒绝时没有 resolver import/call、marker read/write 或 runner 调用。fake-only tests 覆盖独立 pin/verifier、精确 configured MD/TD pair 选择、无 MD SDK import/construction、同配置/pair child binding、完整成功投影、明确 Join pending、unknown/ordinary close exception、query failure、父进程 Job/close 条件和临时目录 one-shot latch 隔离。pytest 有一条现存 `asyncio_default_fixture_loop_scope` 未识别选项 warning。

本页的 fake tests 不证明 vendor callback/Join 语义。后来唯一 I12 one-shot 使用 Windows Job 并消耗独立 marker，但在 `sdk_artifact` 以 `runtime_policy_rejected` 结束；login 未观察、TD queries 未验证、close 未尝试。离线源码检查发现与该阶段相吻合的 Mapping/`CtpConfiguredFrontPair` 类型缺陷候选；原始 child exception 未保留，不能将其称为真实运行唯一根因已证明。真实结果详见[I12 诊断记录](ctp-i12-td-only-diagnostic-2026-09-25.md)。I12 marker 不重置或重试，默认 `NO_WRITE / LIVE_NO_GO` 保持。
