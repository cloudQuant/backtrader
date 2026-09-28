# r2b I22 纯 query/evidence 测试切片（隔离副本）

**结论范围：`FAKE_LOCAL / OFFLINE` 测试接缝；不构成 SDK、Actor、CTP 或生产准入。** 本报告只覆盖原 `tests.unit.stores.test_btapistore_iteration22` 失败样本中的 1 个 query/evidence nodeid。它不改变 Store、默认路由、账户权限或任何生产源码。

## 输入与隔离

- r2b 候选根：`D:\temp\iteration41-ctp-account-actor-main-store-wiring-candidate-20260927-r2b`。
- r2b `backtrader/stores/btapistore.py` SHA-256：`24F8199E199BBE84BBB113C3EDBBEE9E71D4736FDD8573297E24EAD3298F2518`。
- QA 副本的 `backtrader` 树中 481 个 `.py` 文件与 r2b 候选逐字节相同；Store 文件哈希相同。测试输入原文件 SHA-256：`30EEAA2C9816E6D0792E801A6EA2A8960CC1BCAA3728679111318E5178AFA49D`。
- 修改和运行均在 `D:\temp\iteration41-ctp-query-pure-seam-r2b-20260927`。没有编辑主仓、r2b/r2c 候选源码，未导入/调用真实 CTP SDK、provider、网络、私密配置或账户。
- 原失败分组来源为只读 I22 分析：`analysis-summary.json` SHA-256 `EE60B8A12C5C76035EF7A4A649F50261D17A7B68FF60A3668C28C49528EEB9D0`；原分组 158 条，nodeid 唯一。

## 最小迁移

- 保留原 nodeid `tests/unit/stores/test_btapistore_iteration22.py::test_nested_query_failure_cannot_be_overridden_by_outer_success_fields`（原函数约第 3429 行）。测试原有核心断言仍在：外层成功字段不能覆盖嵌套的 timeout/incomplete 结果，`result["complete"] is False` 且 completion validator 返回 `False`。另外增加一个完整 typed dict envelope 经 normalizer 后接受的正例。
- 为绕过已经有意 fail-closed 的 CTP Store 构造 gate，该用例现在直接调用既有类方法 `BtApiStore._normalise_ctp_query_result`（r2b 源约 9132 行）和 `BtApiStore._ctp_query_result_complete`（约 9205 行）。没有 `BtApiStore(provider="ctp_gateway")`、`make_store` 或 Store 实例。
- 新增 `test_btapistore_ctp_query_evidence_pure.py`：1 个完整 envelope 正例 + 17 个带语义名称的单字段反例。这些名称描述可审查的证据不变量（terminal callback、timeout、provider error、身份/代次、请求类型与 records schema），不是代码分支覆盖计数。输入是固定字符串/普通 `dict` 的合成结果，不是受信 SDK/Actor evidence。
- 因此原 158 条中本次只迁移 1 条，**157 条未迁移 nodeid** 原样保存在 [`remaining-157-unmigrated-nodeids.csv`](remaining-157-unmigrated-nodeids.csv)。该清单按原分析中 query/preflight/scope/quote/settlement evidence 语义组生成，不对其余 38 个 lifecycle/authorization 与 4 个 identity nodeid 作重新分类。

## 复跑与路由负测

- Windows Python `C:\anaconda3\python.exe`，对新增纯测试和迁移 nodeid 独立运行：**19 passed**；pytest autoload 被禁用并显式 `-p no:asyncio`。日志有既有 Quandl deprecation 与未注册 `performance` marker 两类 warning。
- 首次使用全局 pytest 插件自动加载在 collection 阶段失败：`pytest_asyncio` 0.23.0 访问 `Package.obj`，exit 2；保留于 `qa-autoload-failure.log`。显式禁用该插件后测试通过。此为隔离 harness/插件兼容问题，不是测试断言失败。
- [`qa_guarded_runner.py`](qa_guarded_runner.py) 的 import finder 阻止 `bt_api_py` 与 `_ctp` 导入；成功运行日志 [`qa-guarded-run.log`](qa-guarded-run.log) 记录 0 次尝试、0 个已加载模块。
- r2b 候选的 3 个惰性构造探针分别覆盖显式 `ctp_gateway`（源码 3688–3690）、`btapi` + `exchange_kwargs.CTP___FUTURE` 嵌套 CTP（3692–3705）、环境变量 `BT_STORE_PROVIDER=ctp_gateway`。三者均在 Store 构造完成前拒绝；trap API 属性读取 0、调用 0。环境变量例返回 `store route ambiguous for account actor handoff`，仍是拒绝结果。
- [`query-evidence-test-seam.patch`](query-evidence-test-seam.patch) 只包含两个测试文件。以原测试文件 SHA 为输入，`git apply --check` 与应用复现均通过；需要 `core.autocrlf=false` 才能精确保留混合换行字节。[`verify_slice.py`](verify_slice.py) 重核输入 hash、481 个源码文件逐字节相同、迁移 nodeid 无 Store 构造调用，并检查应用后的文件精确匹配。补丁 SHA-256 见 `SHA256SUMS.txt`。

## 裁决与边界

该切片恢复了一个查询完成契约的纯单元测试，不是对原 158 条或整份 I22 的修复。它不执行 query producer、Store 内 query orchestration、session/account provenance、时效/新鲜度、Actor 权威判定或 provider 读写；纯 dict 也不能提升准入。合并前需确认目标源码具有上述 r2b 方法和 fail-closed 路由边界，并继续把其余 157 项迁到纯 evidence/service 接口或真正的受控 Actor 合同；不得通过放开 CTP Store 构造、skip/xfail、删除断言或 caller fake 授权来让旧集变绿。
