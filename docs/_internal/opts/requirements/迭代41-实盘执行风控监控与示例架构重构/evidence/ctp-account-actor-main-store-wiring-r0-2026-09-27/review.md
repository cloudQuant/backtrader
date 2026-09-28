# CTP AccountActorPort Store wiring r0 — 候选证据与独立归档重放

**状态：`AUTHOR_CANDIDATE / NO_WRITE`。** 这是待审查的隔离 Store 接线候选，不是已合入实现，不开放默认 CTP 路由，不构成生产接纳。

## 输入、补丁与冻结哈希

- Main-base `backtrader/stores/btapistore.py`：SHA-256 `dba2989252db76fe010fbee7caacdcdba34a9b951e3702724156482b67fae826`，780,123 bytes。
- 候选 `btapistore.py`：SHA-256 `e41dd9189059911a180e7fb27bde546cb90a1f7bd2a0c59df6ed624f12c3e179`。
- 冻结 r4 actor DTO/port 模块：SHA-256 `e0d3147ec7ce867ec96f29e5dc3e8c4a9343b6ef2845b03e712a7676c9c55a48`。
- 新候选测试：SHA-256 `19afe01afbe3679018a861ca00c16f5aa0ddd1f4c32823b52812bccce6ccfcdf`。
- 三文件补丁 `candidate-r0.patch`：SHA-256 `c1bab0ae9d94c7d428ffa436934c9cee91f51e94c8461e23d20f5a56269004f9`。补丁在独立临时 Git 仓库中以 `git -c core.autocrlf=false apply --whitespace=nowarn` 成功检查和应用，三项输出文件哈希与冻结候选一致；复现日志为 `patch-apply-smoke.output.txt`。
- 两个补丁哈希差异及同 base EOL 重放记录：patch-format-comparison.md；旧文本模式 patch 4b208cc… 在 core.autocrlf=false 无法 apply，	rue 时只把 actor module 转成 CRLF（规范化内容相同但 raw SHA 不同）。归档 patch c1bab0… 在 true/false 两设置下均逐字节复现三文件候选 SHA。
- 候选 ZIP `candidate-r0.raw.zip`：SHA-256 `9d3453faa8093d4b8e01fd14aeffb400b3e2e72a6d7de5babaa6f9f37b654ebf`。ZIP CRC 检查通过，615 个成员；`candidate-manifest.json` SHA-256 `ef68998d2b8b75a2125f85bb5720c2e8ba737c818b9d76217767b627cb8b6d14`，列出 613 个 payload。独立提取后逐个核对大小与 SHA-256，613/613 全部一致，sidecar 通过。

## 候选行为与负测范围

Store 在解析 provider / 环境覆盖、访问注入的 `api.exchange_kwargs`、转换凭据字段、解析或导入 SDK、构造 client/native wrapper、autostart 之前检查分离的 route descriptor。未知/冲突 provider、CTP forwarding/gateway/嵌套 route 和原始 `api`/`api_cls` 注入被 fail-close；route 容器被快照，派发前复核 Store 私有 route/backend，避免 caller 变更后沿用旧分类。

没有显式传入 typed actor port、context 与 fake replay ledger 时，不存在 actor 回退。候选只允许明确提供的 fake port 接收 typed submit/cancel intent，核对单次 receipt；actor-only `start`、autostart、legacy submit/cancel、SDK queue、本地 client 与 forwarding 构造拒绝。测试覆盖属性 trap、凭据转换 trap、环境 provider 改写、原始对象注入、嵌套 selector、unknown provider、mutable route、receipt 篡改和 command replay。默认 runtime registry/CLI 与 runtime live guard 源未更改。

## 测试证据

- 候选边界测试 + 拷贝的默认 live-dispatch guard：**11 passed**，1 个既有 Quandl deprecation warning；日志 `candidate-focused.output.txt`。
- 主树既有 managed Store、managed execution、live-dispatch guard：**30 passed**，1 个 pytest asyncio 配置 warning；日志 `main-related-tests.output.txt`。
- 最新冻结 ZIP 的独立提取重放：**11 passed**；日志 `archive-smoke-pytest.output.txt`。
- 候选 Store/actor DTO/新测试 Ruff（使用主仓 `pyproject.toml`）：pass，日志 `candidate-ruff.output.txt`；归档重放 Ruff：pass，日志 `archive-smoke-ruff.output.txt`。
- 三个 Python 文件 `py_compile`：pass，日志 `archive-smoke-pycompile.output.txt`。
- r4 输入 manifest 九项 payload 及 route-classifier AST 等价核验：pass，日志 `upstream-r4-verification.output.txt`。

这不是全 `tests/unit/stores` 回归。无证据排除所有普通非 CTP Store 兼容影响。

## 兼容范围收窄与外部阻塞

候选有意拒绝 raw `api` / `api_cls`、含歧义/未知 selector 的旧构造、CTP forwarding/gateway 绕路，以及 actor-only 的启动和旧本地发单入口。这会收窄历史 Store 用法；需独立评估普通非 CTP 兼容性后才能考虑合并，不应为扩大兼容而放松 CTP 拒绝顺序。

r4 DTO/context/epoch/digest 可由本地 caller 选择，digest 无密钥，replay ledger 仅为进程内 fake；receipt 只绑定单次命令，不带 fresh 当前授权/version 查询。这里没有外部认证的 account actor、每动作当前 session/epoch 校验、durable idempotency、跨主机 account fence 或同 session read/callback snapshot。因此，**真实生产接纳需要外部认证且权威的 AccountActorPort service**（或等价地提供完整这些契约的 service）；本地测试 port 或普通 broker/gateway 本身不足以授予该能力。候选不缓存旧授权态，不把 `QUEUED` 或旧 receipt 当作后续动作许可。

无 CTP/provider、凭据、native SDK、网络、真实 broker 或 gateway 被调用。没有真实账户操作。G1/G5/F14 与生产 acceptance 均未通过或未声称。候选和其 ZIP 仅是 `AUTHOR_CANDIDATE / NO_WRITE` 证据。



