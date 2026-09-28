# V19 账户账本路径与旧实现切换合同

**状态：开发合同，2026-09-26。** 本页记录共享 CTP 候选的实施决定，不是生产部署、历史账本迁移或交易准入回执。实现和独立测试正在进行；默认注册与写入入口仍关闭。

## 一个账户路径

公开组合工厂自行创建 `SqliteExecutionStore`，不接受调用方传入 Store、数据库路径、状态根目录或账户指纹。先重新验证受保护配置，再通过现有 `_simnow_legacy_admission_account_digest` 推导历史路径键，并取得现有 `CtpAccountFlowLease`：

```text
_prepare_state_root()/flow-locks/<legacy-account-digest>.lock
_prepare_state_root()/journals/<legacy-account-digest>.sqlite3
```

simulation 和 production 使用同一推导与同一账本位置。此前为新实现另设 account-ref 文件名的想法不采用，避免旧日志仍有未决状态时另建账户账本。历史路径键来自 BrokerID/UserID 的旧摘要；完整、精确的 canonical account-ref 另存为不可变账本身份。旧摘要碰撞必须导致身份不符拒绝，不能合并账户。

内部测试可以使用明确隔离的 Store 注入接缝；该接缝不构成公开部署工厂。

## 打开顺序与持久身份

1. 在持有旧账户 flow lease 后，调用执行库新增的 `open_ctp_account_store(path, scope)`。
2. 执行库在普通构造器和 schema DDL 前识别文件。旧 `_ExecutionJournal`、未知非空 schema、错误账户、memory/URI 或不确定状态均拒绝。不得删除、重建、清空或忽略旧历史来取得新权限。
3. 新账本持久保存 mode-independent 的精确账户身份。已有 V19 账本必须匹配该身份；没有身份的旧文件不能仅凭正确文件名获得许可。
4. 已有合法 V19 的 WAL/SHM 不是旧账本的证明。身份读取须反映已提交 WAL 内容；无法验证、需要不确定恢复或有冲突时拒绝。SQLite 的只读连接可能涉及 SHM，因此“DDL 前检查”不应被误述为所有文件绝对零写。
5. 成功打开后仍须通过 V19 账户 family owner、writer lease、callback owner、session 和逐动作许可。打开文件不授权会话或请求。

旧 `_ExecutionJournal` 入口也须在 `PRAGMA journal_mode=WAL` 和建表前识别并拒绝新账本，防止之后在同一文件初始化第二套订单表。新实现拒绝旧历史，旧实现拒绝新格式；自动迁移和回退均不在本合同内。

## 证明范围

主仓工厂负责唯一代码路径和创建对象的来源；执行库负责精确账户身份、持久状态与事务拒绝。stdlib sqlite3 不公开其已打开连接的底层 OS 文件句柄，`PRAGMA database_list`、路径和文件 stat 不能独立证明恶意复制或替换不会分叉。

现有 `_prepare_state_root` 也尚未证明 Windows 祖先目录/DACL/文件句柄保护。本合同仅处理本机受信组合的错误路径与历史旁路；不建立跨用户、跨主机账户 writer fence，也不替代 F14 外部账户控制。任意文件克隆、人工删除和 hostile in-process Python 均不由此获得安全声明。

## 必需验证

- 同一合成账户切换 mode/preset 后仍定位同一个文件；账户身份和旧 owner 权限不能跨环境复用。
- 旧 journal、旧 WAL/SHM、未知 schema、错误账户、无身份 V19 和不确定读取均在 SDK/client 构造前拒绝，并保存原历史。
- 新工厂创建后，旧入口不得建立 `ctp_sim_*` 表；旧入口已有历史时，新工厂不得建立新的执行表。
- 有效 V19 WAL 中的身份被检查；错误主文件/WAL 组合拒绝。
- 原账户锁覆盖分类、创建、owner acquisition 和 session 生命周期；不确定关闭不释放为可重试状态。
- 独立 QA 分别记录 V19 核心与此新增工厂的冻结源码、测试输入和结果，不把先前核心测试数字套用于新增 API。

截至本记录，以上新工厂用例尚未形成独立验收回执。
