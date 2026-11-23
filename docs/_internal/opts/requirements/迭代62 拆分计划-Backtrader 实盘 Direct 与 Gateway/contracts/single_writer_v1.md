# 合同冻结件：单写者作用域与并发栅栏合同 v1（T-014）

> 日期：2026-11-23　状态：**FROZEN_V1**
> 依据：已确认 `D62S-09a`、`D62-05`、`D63-02/08`、`D65-13`；关联需求 `R62S-13`；关联验收 `S-04`。

## 1. 四层作用域与写者栅栏表

| 层级 | 唯一写者作用域 | 冻结机制 | 残余边界声明 |
| --- | --- | --- | --- |
| **进程层（`D62S-09a`）** | 操作系统进程 | `ProcessModeFence`（同进程默认单实盘模式，跨模式构造抛 `PROCESS_MODE_CONFLICT`） | 测试夹具通过受控 `reset()` 隔离，生产路径不可重置 |
| **Direct 策略进程** | 策略目录 `<strategy_dir>`（`D62-05` 单策略独占账户） | `state/run.lock` 文件锁 + `state/identity.json` 不可变 `mode: "direct"` | 不防其他目录/主机/手工终端登录（操作层残余风险） |
| **Gateway 账户 owner** | `账户 × 场所 × route`（`D63-02/08`） | 每账户唯一独立 Gateway 实例；同主机 SQLite lease / `HostAccountRegistry`；跨主机互斥以 SDK `bt_api_py.account_writer_authority` TTL 租约为候选 | 同库 SQLite lease 仅约束本机协作进程；**跨主机非协作实例与外部手工终端列为操作层残余边界**，不用 fake 测试冒充全局防线 |
| **Gateway 策略与 Execution** | 策略：`账户 × 策略`（2026-11-14 禁双活）；Execution：`账户`（`D65-13` 每账户一进程） | Gateway 服务端单调代次策略租约 + 本地 `state/run.lock` + `identity.json mode: "gateway"`；Execution 每账户独立进程日志锁 | 多策略共享同一账户级 Gateway 交易 owner，严禁退化为每策略一个 TD writer |
