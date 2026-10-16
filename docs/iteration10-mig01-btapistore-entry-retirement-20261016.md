# Iteration10 MIG01：Backtrader 旧 gateway 入口退役

本轮在 Backtrader `dev`、基线 `edfb4ddb64ee42e0d1f90d7a111def63447ccd67` 上，将 `BtApiStore` 的 `gateway`、`forwarding` 及 `*_gateway` 旧入口改为早期迁移拒绝，避免创建 API 或触发写调用；提示使用现有 Service/client 配置。正常 direct 初始化和 direct API 注入仍保留，历史 fixtures 与仍被其他 provider 使用的 base 接口树不删除。只覆盖五个已验收源码/测试文件；本记录与它们组成待提交的六文件范围。

Root 固定源 R2 在 90 个参数化 case 中通过 88 个，另外两个均是 `test_ctp_forwarding_store_direct_writes_fail_closed_before_api` 的参数实例：`object.__new__` 构造缺少 `_service_read_only`，在到达既有 CTP 拒绝守卫前触发 `AttributeError`。R2 保留原始结果和两条既有 warning（Quandl deprecation、未注册的 `performance` marker）。随后 R3 只运行这两个参数实例；在忠实的 direct Store/API 构造后模拟 backend 变更，两例均通过，pytest exit 0、3.84 秒，并保留一条 Quandl warning。R3 的 58 个固定源 pin 和 Backtrader HEAD 前后不变；相对 R2，测试文件中目标函数之外的字节完全一致。R2 与 R3 合计覆盖 90 个唯一 case，其中 88 个在 R2 通过，另外 2 个在 R3 通过；这不是一次 90-case 全绿运行。R1、R2 原始失败输出均保留。

R2/R3 输出分别保存在 `D:/temp/iteration10-mig01-entry-retirement-bt-root-20261016-r2` 和 `...-r3`；R3 spec 在 `D:/bt_api_py/.codex-tmp/iteration10-mig01-entry-retirement-bt-root-20261016-r3.json`。证据为固定来源 fake/source 测试，不包含 Host、provider 或账户验收。

这只是 Backtrader `BtApiStore` 入口的一段退役，不是 MIG01 完成或正式 PASS。旧运行目录、base 接口树及历史 fixtures 保留；其它 SDK 导出/运行器消费者、构建与 wheel 依赖闭包、隔离安装和正常调用扫描仍待逐项迁移与验收。
