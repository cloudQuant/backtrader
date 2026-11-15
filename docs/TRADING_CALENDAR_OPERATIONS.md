# 交易日历运维指南（迭代 67，2026-11-15）

本文说明 CTP 交易日历的目录、版本指针、发布模式、公告输入、每日 20:30 检查、三平台计划任务、
锁与部分失败处理、备份回滚和禁止事项。它面向运营和开发人员，不授予任何账户、下单或交易权限。

## 0. 状态与边界（先读）

| 项目 | 当前状态 |
| --- | --- |
| 本地版本仓、`CURRENT.json` 指针、单写者锁、回执 | 已实现（SDK `trading_calendar_store`），POSIX 本地文件系统，未在 Windows 验证 |
| 合成包内种子 `seed-2026-2027-v1` | 已实现，显式安装；`SYNTHETIC_MOCK`，不是交易所事实；安装同时发布覆盖声明（`DECLARED_UNVERIFIED`），其 `SYNTH_*` 作用域可按 `SIMULATION_ONLY` 只读查询 |
| 每日检查入口 `trading_calendar_schedule_once` | 已实现，`SIMULATION_ONLY`，未接真实 20:30 操作系统调度 |
| 通知入口 `trading_calendar_notify_cli` | 已实现，SMTP 传输显式配置；服务器接受不等于送达 |
| 人工审核确认 | 已有模拟确认路径；网页/统一界面归迭代 69 |
| 人工待审切换自动后的重采集（D67-27） | **GAP**，未完成 |
| 真实六所、当年和下一年真实来源 | **GAP**，当前为 AKShare/明确 mock；真实覆盖待后续 Opendata |
| Windows 文件锁、路径、计划任务 | **GAP**，67.09 处理；当前本地锁要求 POSIX `flock` |
| 真实账户、真实 SMTP、交易授权证据 | 无；本文和示例都不产生这些证据 |

所有输出都带 `environment: SIMULATION_ONLY`、`source_authentication: NOT_PROVEN` 等标签。标签是边界说明，
不是形式主义：任何“成功”都只表示本地协作进程之间的一致记录，不表示来源可信、版本已绑定、邮件已送达或可以交易。
完整背景见[迭代计划](_internal/opts/requirements/迭代67-交易日历数据文件化与每日更新/迭代计划.md)和
[开发交接说明](_internal/opts/requirements/迭代67-交易日历数据文件化与每日更新/迭代67开发交接说明-2026-11-15.md)。

## 1. 目录布局与所有权

示例配置的 `calendars.root` 是外层日历根；CTP 的 store 根固定为其下的 `ctp/`。下文的 `<store>` 都指
`<calendars.root>/ctp/`，它是 SDK 版本仓和更新工具的直接根目录，也是 `--root` / `--calendar-root` 的取值。

```text
<calendars.root>/
  ctp/                                  # <store>，CTP store 根
    CURRENT.json                        # 指针：当前已提交发布记录及摘要；只经原子替换更新
    versions/                           # 不可变版本内容，文件名 <version_id>.json
    publications/                       # 不可变发布记录，文件名 <publication_id>.json
    receipts/                           # 提交回执，文件名 <publication_id>.json
    .lock                               # 单写者锁；运行时只读打开
    REVIEW_POLICY.json                  # 审核策略（auto / manual 及修订号）
    REVIEW_POLICY_INITIALIZED.json      # 策略初始化标记；缺失或与策略不一致时拒绝
    observation-runs/                   # 采集运行记录（工具写入）
    detail-collections/                 # 明细采集记录（工具写入）
    supplement-captures/                # 公告补充的不可变捕获（工具写入）
    schedule-once-pending.json          # 每日检查的未决/结果记录
    schedule-once-ledger.sqlite3        # 每日检查账本（操作身份、状态、日期索引）
    schedule-once-*.json                # 初始化、迁移与账本标记
```

- 计划文档早前候选布局中的 `inbox/`、`sources/`、`staging/`、`reports/` 并非全部落地；不要手工创建这些目录
  并期望程序使用。以实际代码创建的目录为准。
- 写入者：SDK store（`CURRENT.json`、`versions/`、`publications/`、`receipts/`、审核策略）、更新/采集工具
  （其余目录与账本）。读取者：策略、Feed、Store 只读端口。
- 策略和 Feed 不读取上述文件路径或内容（INV67-09）；它们只调用 Store 的只读查询。把文件路径、YAML 或
  `CURRENT.json` 直接交给策略不是受支持的用法。
- 同一主机的多个策略可以指向同一个 `<calendars.root>`；运行时只读，更新工具是唯一写者。
- 根目录建议放在本地磁盘。网络共享盘上的重命名、`flock` 和文件身份语义不满足当前模型。

## 2. 版本、发布记录与 `CURRENT.json`

1. 一次发布是一个不可变组合版本：`versions/<version_id>.json` 保存完整内容，`publications/<publication_id>.json`
   保存发布记录与摘要，`receipts/<publication_id>.json` 在提交后写入；三者属于同一版本，不能混用不同版本的文件。
2. `CURRENT.json` 是唯一指针，经原子替换指向一个已提交发布记录；它还带指针摘要。写入顺序保证读者只看到旧版或新版，
   不会看到半写版本。
3. 无实质变化时结果是 `SAME`，不生成新版本、不产生新的发布通知。
4. 同名版本不可覆盖；`versions/`、`publications/`、`receipts/` 一经写入不可修改。历史是追加式的。
5. 文件时间戳和“预写时间”不是发布时刻的证明。回执缺失时，历史时刻可能不确定；需要时按原发布 ID 核验，
   不要用文件 mtime 补一个时间。
6. store 不提供“丢失 `CURRENT.json` 的自动恢复”。不要手写或拼接指针，也不要从候选目录复制一个指针。

运行时观察到的 `CURRENT` 是未经认证的本地状态。`TradingCalendarStatusReader.status()` 返回
`OBSERVED_UNAUTHENTICATED` 只表示当前指针、发布记录和回执彼此一致；其 `bound` 目前报告
`NOT_BOUND` / `RUNTIME_BINDING_NOT_IMPLEMENTED`。Feed 自己的绑定状态（`trading_calendar_binding()`）
在成功读取后才是 `BOUND`。

## 3. 配置键与路径规则

示例（22 个 007 实盘配置都使用这个形状）：

```yaml
calendars:
  root: ../calendars          # 相对本 config.yaml 所在目录；也可写绝对路径
  # review_mode: manual       # 可选；auto | manual，缺省 auto。未知键拒绝
```

解析器约定（`bt_api_py/trading_calendar_config.py`、Backtrader `parse_direct_calendar_status`）：

| 规则 | 说明 |
| --- | --- |
| 键集合 | `calendars` 只允许 `root`、`review_mode`；其他键报 `calendar_config_unknown_field` |
| `root` | 非空字符串；相对路径相对 `config.yaml` 所在目录，不依赖当前工作目录；SDK 会展开 `~`；**不展开环境变量** |
| 绝对路径 | 允许；示例只写相对路径，避免把生产路径写进仓库 |
| `root: package_seed` | 解析器接受；007 的 direct/Gateway 运行入口在 live 启动和 `--dry-run` 中都明确拒绝（`calendar_package_seed_unsupported`，退出码 2），不回退旧内置常量 |
| 未配置 | 按 D67-01 执行：007 的 Gateway 与 direct（写入准入开启）入口在 live 启动时以 `calendar_root_unconfigured` 拒绝（退出码 2），发生在读取凭据、解析资源、创建 Store/Broker 之前；拒绝不联网、不读日历目录。`--dry-run` 只报告同一码并以 0 退出。D67-01 未覆盖的“非 Gateway 且未开启 direct 写入准入”也按示例的 fail-closed 保守处理拒绝 |
| `review_mode` | `auto` 或 `manual`；显式写出时来源记为 `explicit`，否则为默认 `auto` |
| CTP store 根 | 恒为 `<root>/ctp`；更新工具、审核和备份都使用这个目录 |
| Windows | 盘符、UNC、大小写和长路径尚未验证（67.09）；本地锁当前要求 POSIX |

`--dry-run` 只报告、不启动任何组件（D67-01）：配置了根时 direct 输出
`Calendar: external directory configured; local status only`，Gateway 输出
`"calendar": "external_directory_configured_not_bound"`；未配置时 direct 输出
`Calendar: calendar_root_unconfigured; live start will be refused (dry-run only reports)`，
Gateway 在 `"calendar": "calendar_root_unconfigured"` 中报告，二者都以 0 退出；配置值非法时以 2 报告。
这些都只证明配置被解析，不证明目录存在、`CURRENT` 已发布或时段可用于交易。

## 4. 自动发布与人工审核

发布策略由 store 的 `REVIEW_POLICY.json` 决定，不能通过改文件“临时切换”。

### 4.1 自动模式（`auto`）

1. 采集、校验、比较候选与当前版本。
2. 无实质变化：`SAME`，不发布，不刷新“最近成功发布”。
3. 有实质变化且校验通过：在 store 锁内以 `CURRENT` 前置条件提交，写入版本、发布记录和回执。
4. 冲突、完整性不足或任一必需范围失败：不发布；逐所失败不会把整次检查记为成功。
5. 提交结果不明：按原 operation/publication ID 核验；不要新建 ID 重试，也不要手工改 `CURRENT`。

### 4.2 人工模式（`manual`）

1. 生成候选并标记 `PENDING_REVIEW`（退出码 10），保留候选、差异和来源。
2. 提醒邮件只提醒，不批准、不发布。SMTP 服务器接受不等于收件人收到。
3. 一名审核人核对具体候选后确认，记录审核人、确认时间、候选摘要，并立即尝试发布。
4. 确认后若候选、配置、当前版本或审核策略已变化，必须重新校验；旧确认不得复用。
5. 切换模式：人工待审切换为自动后，下一次检查应重新采集并按当前模式处理，不能直接发布旧候选。
   该行为（D67-27）当前**未完成**；出现旧 `PENDING_REVIEW` 时按下面第 8 节核验原 ID，不要清空 pending 或重置账本。

### 4.3 常用只读/核验命令

```bash
# 每日检查（等价于计划任务要执行的动作；见第 6 节）
python -m bt_api_py.trading_calendar_schedule_once --action run \
    --config /ABS/PATH/schedule.json --trusted-local-posix

# 只读：查看当前待审操作（没有时返回 NONE，退出 0）
python -m bt_api_py.trading_calendar_schedule_once --action inspect-active \
    --root /ABS/PATH/calendars/ctp --trusted-local-posix

# 只读：按原 operation ID 查看一次操作
python -m bt_api_py.trading_calendar_schedule_once --action inspect \
    --root /ABS/PATH/calendars/ctp --operation-id <operation_id> --trusted-local-posix

# 结果不明时按原 ID 核验（不要先重跑更新）
python -m bt_api_py.trading_calendar_schedule_once --action reconcile \
    --root /ABS/PATH/calendars/ctp --operation-id <operation_id> --trusted-local-posix

# 只读：枚举已提交的终态发布；有截断或无法重验的行时报 INCOMPLETE
python -m bt_api_py.trading_calendar_schedule_once --action scan-publications \
    --root /ABS/PATH/calendars/ctp --trusted-local-posix

# 只读：最近两个交易日是否都没有成功检查（退出码 10 为告警）
python -m bt_api_py.trading_calendar_schedule_once --action check-health \
    --root /ABS/PATH/calendars/ctp --venue SHFE --trusted-local-posix
```

退出码约定（`schedule_once`）：`0` 表示 `COMMITTED` / `SAME` / `ALREADY_COMPLETED` /
`LOCAL_HISTORICAL_RECORD_ONLY`（`inspect-active` 的 `NONE` 也是 0）；`10` 表示 `PENDING_REVIEW`；`25` 表示
其余未知或失败；`130` 表示中断且已输出作用域报告。

`check-health` 的交易日来自 store 的 `CURRENT`，不来自星期或本机挂钟：连续两个交易日都 `NO_SUCCESS` 时返回
`WARNING` / `TWO_CONSECUTIVE_TRADING_DAYS_NO_SUCCESS`（退出 10）；历史不足或不确定时返回
`UNKNOWN` / `CHECK_HISTORY_UNCERTAIN`。告警不阻止继续使用已有有效日历，也不是交易禁令。

## 5. 公告补充输入模板（YAML）

交易所公告需要人工补充时，使用与日历快照相同的四层 YAML。它是**未经验证的候选输入**：不认证来源、
不推断 UTC、不解决冲突、也不发布。字段集合是严格的，额外键、重复键、YAML 锚点和别名都会被拒绝。

```yaml
# 顶层只允许这四个键，缺一不可。
sources:
  - id: "EXCHANGE.NOTICE.20261115"
    description: "公告标题 / 文号 / 链接 / 核对说明（不要写账号、密钥或私人信息）"

trading_days:
  - venue: "SHFE"                    # SHFE | INE | CZCE | DCE | CFFEX | GFEX
    day: "2026-11-16"                # 引号 YYYY-MM-DD
    status: "closed"                 # open | closed
    source_ids: ["EXCHANGE.NOTICE.20261115"]

trading_hours:
  - venue: "SHFE"
    kind: "future"                   # future | option
    product: "RB"                    # 示例占位，必须替换为实际品种标识
    contracts: ["RB2701"]
    valid_from: "2026-01-01"
    valid_to: "2026-12-31"
    day_windows:
      - {id: "day_am", phase: "continuous", start: "09:00", end: "11:30", end_day_offset: 0}
      - {id: "day_pm", phase: "continuous", start: "13:30", end: "15:00", end_day_offset: 0}
    night_windows:
      - {id: "night", phase: "continuous", start: "21:00", end: "01:00", end_day_offset: 1}
    night_mappings:
      - {trading_day: "2026-11-16", start_date: "2026-11-15",
         source_ids: ["EXCHANGE.NOTICE.20261115"]}
    source_ids: ["EXCHANGE.NOTICE.20261115"]
    windows_complete: true            # 作者声明，不是验证结论
    exceptions_complete: false        # 作者声明，不是验证结论

exceptions:
  - venue: "SHFE"
    kind: "future"
    product: "RB"
    contract: "RB2701"                # null 表示该品种整体
    trading_day: "2026-11-16"
    action: "cancel_window"           # close_day | cancel_window | interrupt_window
    window_id: "night"                # close_day 时必须为 null
    source_ids: ["EXCHANGE.NOTICE.20261115"]
```

字段规则：

| 层 / 子结构 | 精确键 | 约束 |
| --- | --- | --- |
| `sources[]` | `id`, `description` | id 匹配 `[A-Za-z0-9][A-Za-z0-9_.-]{0,127}`；描述非空、不超过 4096 字符 |
| `trading_days[]` | `venue`, `day`, `status`, `source_ids` | status 为 `open` / `closed`；日期必须是引号字符串 |
| `trading_hours[]` | `venue`, `kind`, `product`, `contracts`, `valid_from`, `valid_to`, `day_windows`, `night_windows`, `night_mappings`, `source_ids`, `windows_complete`, `exceptions_complete` | `contracts` 非空且不重复；`valid_from <= valid_to`；完整性必须是显式布尔值 |
| 窗口 | `id`, `phase`, `start`, `end`, `end_day_offset` | phase 为 `continuous` / `auction`；时间 `HH:MM` 引号字符串；日盘 offset 必须为 0 |
| `night_mappings[]` | `trading_day`, `start_date`, `source_ids` | 交易日必须在生效期内；`start_date < trading_day`；自然日归属必须显式写 |
| `exceptions[]` | `venue`, `kind`, `product`, `contract`, `trading_day`, `action`, `window_id`, `source_ids` | `close_day` 不得带窗口；`cancel_window` / `interrupt_window` 必须带窗口 |
| `interrupt_window` 附加 | `exception_schema`, `start_utc`, `end_utc` | schema 固定 `bt_api.calendar-window-interruption/1`；`source_ids` 必须恰好是 `["MOCK.simulation_only"]`（仅模拟） |

- 时间窗口以 `end_day_offset` 表达跨午夜：日盘 `0` 且 `end > start`；夜盘 `1` 且 `end < start`。
  周五夜盘归属周一等安排必须由公告或模拟映射明确写出，不能用“前一天”或统一周末公式推断。
- `source_ids` 必须引用已声明的 source；未被引用的 source 会在检查结果中列为 `unused`，不会被自动删除。
- `windows_complete` / `exceptions_complete` 是作者声明。即使观察结果出现 `COMPLETE`，也只表示结构完整，
  `sources_verified` 仍为 false，不能单独作为自动发布依据。
- 公告原件和捕获记录不得包含账号、密钥、口令或私人信息。

使用前先做只读检查（不读 `CURRENT`、不联网、不发布）：

```bash
python -m bt_api_py.trading_calendar_check \
    --config /ABS/PATH/config.yaml \
    --calendar-root /ABS/PATH/calendars/ctp \
    --supplement /ABS/PATH/supplement.yaml \
    --gateway-enabled            # 或 --direct-write-enabled
```

报告会给出 `config_status`、`supplement_status`、各层计数、`unused_source_count`、目录与输入稳定性标签；
`review` 和 `publication` 永远是 `NOT_PERFORMED` / `NOT_ATTEMPTED`。需要留存时先做不可变捕获
（`observation-run` 的 `--capture-supplement`），不要直接编辑已捕获的文件。

## 6. 每日检查（默认 20:30 Asia/Shanghai）

D67-19：默认每天北京时间 **20:30** 触发一次检查，周末和节假日也运行；部署时可配置时间。触发不能依赖
可能陈旧的本地日历。应用内没有调度器，由 cron/systemd timer、launchd 或 Windows 任务计划程序调用；
20:30 只是检查触发时间，不证明来源已更新、审核已完成或交易日已经切换。

### 6.1 检查配置（JSON）

`trading_calendar_schedule_once` 的 `--config` 是一个受保护的 JSON 文件（owner-only、普通文件、非符号链接、
绝对路径、不含 `..`、不超过 64 KiB）：

```json
{
  "schema": "bt_api.calendar-schedule-once-config/1",
  "environment": "SIMULATION_ONLY",
  "root": "/ABS/PATH/calendars/ctp",
  "job_key": "daily-ctp",
  "original_run_id": "<已有的初始化运行 UUID hex>",
  "scopes": [
    {
      "contract": "RB2701",
      "target": {
        "venue": "SHFE",
        "kind": "future",
        "product": "SYNTH_SHFE_FUTURE",
        "mock_contract": "SYNTH_SHFE_FUTURE_MAIN",
        "valid_from": "2026-12-31",
        "valid_to": "2027-01-04"
      },
      "assumptions": {
        "DAY":   {"phase": "continuous", "timezone": "Asia/Shanghai"},
        "NIGHT": {"phase": "continuous", "timezone": "Asia/Shanghai"}
      },
      "alignment": "REPEAT_OVER_MOCK_OWNER_DAY_MAPPING",
      "timeout": 2
    }
  ],
  "budget_seconds": 60,
  "supplement": "/ABS/PATH/supplement.yaml"
}
```

约束：`scopes` 为 2–8 个且不能重叠（上面的模板只展示一项，实际配置必须补足）；每项精确使用上列键；`alignment` 目前只接受
`REPEAT_OVER_MOCK_OWNER_DAY_MAPPING`（模拟 owner-day 映射）；`budget_seconds` 为 0–600；`supplement` 可选，
但必须是绝对路径。**这份示例是当前的 SIMULATION_ONLY 形状，`SYNTH_*` 不是真实品种覆盖**；真实六所 scope
配置仍属 GAP，不能把示例中的名字当作交易所事实。

### 6.2 检查结果

- 成功后输出 JSON 并返回 0：`COMMITTED`（有实质变化）、`SAME`（无变化）、`ALREADY_COMPLETED` 或
  `LOCAL_HISTORICAL_RECORD_ONLY`。
- `PENDING_REVIEW` 返回 10，等待人工确认；此时不要启动第二次检查操作。
- `UNKNOWN`、锁冲突、配置/账本异常返回 25；先按原 operation ID 核验，不要自动重试。
- 完成或复核输出含 `original_config_sha256` / `current_config_sha256`、
  `original_scopes_sha256` / `current_scopes_sha256`，用于证明本次使用的配置与原始操作是否一致。

### 6.3 通知（独立进程）

```bash
python -m bt_api_py.trading_calendar_notify_cli \
    --calendar-root /ABS/PATH/calendars/ctp \
    --journal-path /ABS/PATH/notifications.sqlite3 \
    --smtp-config /ABS/PATH/smtp.json \
    --schedule-active \
    --trusted-local-posix
```

事件选择（五选一）：`--review-id`（人工提醒，需同时给 `--run-id`、`--review-sha256` 和
`--simulation-clock-config`）、`--publication-id`、`--schedule-active`、`--schedule-operation-id`、
`--scan-missed`。`--scan-missed` 是显式、幂等的补发扫描：
按原 review/publication ID 和北京时间自然日去重，不会把未知结果标记为已发送，也不会重发。
SMTP 配置文件为 owner-only JSON，允许键 `enabled`、`host`、`port`、`timeout`、`sender`、`recipients`、
`username`、`password`、`security`；字段不会出现在日志或 repr。`--dry-run` 只判断是否具备发送条件。
退出码：`ACCEPTED`、重复且账本为 `ACCEPTED`、`DRY_RUN_ELIGIBLE` 时为 0，其余为 1。
`ACCEPTED` 只表示 SMTP 服务器接受，不表示送达；失败或结果不明不回滚已发布版本，也不抹除待审状态。

## 7. 三平台计划任务样例（20:30）

以下样例使用同一检查命令，时间统一为北京时间 20:30。**这些是部署形状，不是已验收证据**：真实 20:30
调度、非上海主机时区和 Windows 行为仍待 67.09 与 D67-19 的验证；当前检查/通知入口在非 POSIX 平台会返回
`UNSUPPORTED_FILESYSTEM`。

### 7.1 Linux / systemd

```ini
# /etc/systemd/system/bt-calendar.service
[Unit]
Description=CTP trading-calendar daily check (SIMULATION_ONLY)
After=network-online.target

[Service]
Type=oneshot
User=btcal
ExecStart=/ABS/PATH/python -m bt_api_py.trading_calendar_schedule_once \
    --action run --config /ABS/PATH/schedule.json --trusted-local-posix
StandardOutput=append:/VAR/LOG/bt-calendar.log
StandardError=append:/VAR/LOG/bt-calendar.log
```

```ini
# /etc/systemd/system/bt-calendar.timer
[Unit]
Description=Run the CTP calendar check daily at 20:30 Asia/Shanghai

[Timer]
OnCalendar=*-*-* 20:30:00 Asia/Shanghai
Persistent=false
Unit=bt-calendar.service

[Install]
WantedBy=timers.target
```

`Persistent=false` 是保守选择：错过的运行不会被 systemd 在开机时补跑；由下一次 `check-health` 报告，
而不是隐式重放一个可能过时的检查。启用：`systemctl daemon-reload && systemctl enable --now bt-calendar.timer`。
若发行版 systemd 不支持带时区的 `OnCalendar`，必须以其他方式把主机时区或等效触发时间固定为北京时间并验证。

### 7.2 Linux / cron

```cron
# 仅在 cron 明确支持 CRON_TZ 时使用；不支持时按主机时区换算并在部署时验证。
CRON_TZ=Asia/Shanghai
30 20 * * * cd /ABS/PATH && /ABS/PATH/python -m bt_api_py.trading_calendar_schedule_once \
    --action run --config /ABS/PATH/schedule.json --trusted-local-posix \
    >> /ABS/PATH/logs/calendar.log 2>&1
```

不要加 `@reboot`、`* * * * *` 或失败自动重跑。cron 只负责按时启动一次检查，结果和失败处理见第 8 节。

### 7.3 macOS / launchd

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.example.bt-calendar-daily</string>
  <key>ProgramArguments</key>
  <array>
    <string>/ABS/PATH/python</string>
    <string>-m</string>
    <string>bt_api_py.trading_calendar_schedule_once</string>
    <string>--action</string><string>run</string>
    <string>--config</string><string>/ABS/PATH/schedule.json</string>
    <string>--trusted-local-posix</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>20</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardOutPath</key><string>/ABS/PATH/logs/calendar.out</string>
  <key>StandardErrorPath</key><string>/ABS/PATH/logs/calendar.err</string>
</dict>
</plist>
```

`StartCalendarInterval` 使用主机本地时区，没有每任务时区字段。非上海主机必须先把主机时区设为
`Asia/Shanghai`，或换算成等效的本地时间并验证；否则 20:30 不是北京时间。加载：
`launchctl bootstrap gui/$(id -u) /ABS/PATH/com.example.bt-calendar-daily.plist`。不要配置 `RunAtLoad`。

### 7.4 Windows / 任务计划程序

```bat
schtasks /Create /TN "BT Calendar Daily" /SC DAILY /ST 20:30 ^
  /TR "\"C:\ABS\PATH\python.exe\" -m bt_api_py.trading_calendar_schedule_once --action run --config C:\ABS\PATH\schedule.json --trusted-local-posix" ^
  /RU <运营账号> /RP *
```

任务计划程序按主机本地时区执行；非中国标准时间主机须调整 `/ST` 或系统时区并验证。当前 SDK 的本地 store
使用 POSIX `flock`、`O_NOFOLLOW` 和目录文件描述符，Windows 会明确报告不支持；**该样例只表达目标部署形状，
不是已验证的 Windows 能力**。67.09 完成跨平台适配前，不要把 Windows 计划任务当作可用方案。

## 8. 锁、并发与部分失败

### 8.1 单写者锁

- `<store>/.lock` 是单写者锁。第二个写者不会排队或等待成功，而是失败；不要删除、截断或用 `touch` 绕过锁文件。
- 运行进程只以只读方式打开锁和 `CURRENT.json`；不要在运行期间执行发布、备份恢复或手工替换目录。
- 锁释放后 `CURRENT` 仍可能变化。读者的一次观察带 `state_freshness: NOT_GUARANTEED_AFTER_LOCK_RELEASE`；
  Feed 绑定后的 `STALE` 也是这个语义，不是读取错误，更不是“日历说休市”。

### 8.2 部分失败

| 情形 | 处理 |
| --- | --- |
| 某个交易所/范围采集失败 | 整体检查不算成功；不发布，不刷新成功时间；其他范围的成功不能掩盖它 |
| 明确、可证明的临时失败且未留下记录 | 允许有界重试（最多 3 次，缺省 2 次）；每次重试使用同一观察身份 |
| `UNKNOWN` / `ATTEMPT_UNKNOWN` / `COMMIT_UNKNOWN` | **绝不自动重试**；按原 ID 核验 |
| 提交点前后失败 | 先 `inspect` / `reconcile` 原 operation ID；只有能证明未提交或已提交时才继续 |
| 待审候选一直存在 | `inspect-active` 查看；新检查返回 `PENDING_REVIEW`，不创建第二个操作 |
| 跨午夜/跨日期的操作 | 不允许并行；以账本唯一约束为准，不手工改日期 |
| 连续两个交易日没有成功检查 | `check-health` 告警（退出 10）；先查采集、来源、锁与配置，仍不确定则保持 `UNKNOWN` |

### 8.3 邮件失败

- 已提交 `IN_FLIGHT` 记录但结果不明的，保持 `UNKNOWN`，不重发；包括另一个进程仍在运行时。
- 能证明发送前已 `NOT_SENT` 的，才可通过条件事务重试。
- `REFUSED` / `PARTIAL_REFUSAL` 不改写发布；人工决定是否用 `--scan-missed` 补发已知遗漏事件。
- 邮件失败不回滚版本，也不抹除 `PENDING_REVIEW`；反过来，发布成功也不能把未发送的提醒当成已发送。

## 9. 备份、回滚与恢复

### 9.1 备份

1. 停止所有更新、通知和审核写入者；确认没有活动锁和 pending 操作（`inspect-active`）。
2. 整体复制 `<store>`，保留文件权限与目录结构：`CURRENT.json`、`versions/`、`publications/`、`receipts/`、
   审核策略文件、账本和 pending 记录必须成套；只复制 `CURRENT.json` 不是备份。
3. 如果通知/审计需要，同时备份通知 journal（`--journal-path`）和外部日志；它们与 store 是独立证据。
4. 备份完成后用只读命令核验（Store 的 `trading_calendar_status()`、`scan-publications`、`inspect`），记录结果。
5. 备份是证据副本，不是修改历史的许可证。

### 9.2 回滚

- 优先方式：在**所有写入者停止**的前提下，用一份内部一致的备份整体替换 store；随后重新核验 `CURRENT`、
  回执、账本和待审状态。
- store 不提供丢失 `CURRENT` 的自动恢复，也不支持手工编辑指针。恢复后如果无法证明一致性，保持 `UNKNOWN`
  并升级处理；不要用“看起来正确”的文件拼一个版本。
- 已发布版本是追加式历史。回滚不会让已经绑定旧版本的读者自动切换；策略进程应在交易日切换时重读，
  或在停止后重启，不能假设回滚立即生效。
- 不要把旧备份中的候选、review ID、publication ID 直接拿来复用；恢复后重新执行只读核验。

## 10. 不要做

- 不要手工编辑 `CURRENT.json`，不要手工复制候选到 `versions/`，不要修改 `publications/` 或 `receipts/`。
- 不要删除 `.lock`、pending、账本或审核策略来“解锁”；先证明没有写入者。
- 不要在 `UNKNOWN`、`IN_FLIGHT` 或结果不明时自动重发、重试或新建 ID。
- 不要把 mock、合成种子、示例配置或 dry-run 输出当成交易所事实、真实覆盖或交易授权。
- 不要让策略读取日历文件路径/内容，也不要在运行进程内写 store。
- 不要在网络共享盘、被其他程序替换目录的情况下运行本地 store。
- 不要用本地日历、文件 mtime 或星期规则决定是否触发每日检查。
- 不要在配置、公告 YAML、说明或日志里写账号、密钥、口令、私人路径或未脱敏的来源内容。
- 不要根据本文档或 007 示例执行下单、改单、撤单或账户操作。

## 11. 故障码速查

| 码 | 含义 | 建议动作 |
| --- | --- | --- |
| `calendar_root_unconfigured` | 未配置 `calendars.root`；007 的 Gateway/direct 入口（direct 写入准入开启）在 live 启动时拒绝，未开启写入准入的未配置也按示例 fail-closed 拒绝 | 添加显式根并 `--dry-run`；不要用 `package_seed` 代替 |
| `calendar_package_seed_unsupported` | 007 运行入口不接受 `root: package_seed`（live 与 `--dry-run` 都拒绝） | 改用外部目录；种子安装只用于本地开发 |
| `calendar_config_invalid` / `calendar_config_unknown_field` / `calendar_review_mode_invalid` | 配置不可解析或含未知键/非法模式 | 按第 3 节修正；不要放宽解析器 |
| `CURRENT_UNAVAILABLE` | 没有可读取且一致的 `CURRENT`/回执 | 检查 store 完整性；不要猜测或手写指针 |
| `ROUTE_UNCONFIGURED` | 查询使用的 route 未配置 | 使用配置中完全一致的 route 名 |
| `COVERAGE_UNAVAILABLE` / `SCOPE_OR_DATA_UNAVAILABLE` | 日期/品种/合约不在覆盖或数据不可用（包内种子只声明 2026-01-01..2027-12-31 的六个交易所） | 保持 `UNKNOWN`；经审核补充来源后再发布 |
| `CALENDAR_SCOPE_UNAVAILABLE` | venue/kind/product/contract 未给全 | 调用时显式传入作用域，或配置 `feed.calendar_*` |
| `TRADING_DAY_REQUIRED` | 没有可绑定的交易日 | 由提供方/BT 确认的 `datetime.date` 显式提供 |
| `TRADING_DAY_REGRESSION` | 请求早于已绑定交易日 | 不倒退；检查调用方日期来源 |
| `STALE` | 日切重读失败，保留旧版本 | 保留旧版本并报告；不要当作休市或重新推断 |
| `CONFIGURATION_CHANGED` | 读取期间版本/配置变化 | 重新读取；不要混用版本 |
| `PENDING_REVIEW` | 人工模式等待确认 | `inspect-active` 查看；确认具体候选；不要并行新操作 |
| `UNKNOWN`（检查/通知） | 结果不明 | 按原 ID `inspect` / `reconcile`；禁止自动重试 |
| `TWO_CONSECUTIVE_TRADING_DAYS_NO_SUCCESS` | 最近两个交易日无成功检查 | 查采集/来源/锁；不是交易禁令 |
| `CHECK_HISTORY_UNCERTAIN` / `INSUFFICIENT_TRADING_DAYS` | 历史不足或无法证明 | 不用推测补数；保持告警/未知 |
| `PUBLICATION_SCAN_LIMIT_REACHED` | 只读发布枚举达到上限 | 提高显式上限或分批核验；不要跳过 |
| `UNSUPPORTED_FILESYSTEM` | 非 POSIX 或缺少必要文件语义 | 换受支持平台；Windows 适配见 67.09 |
| `ARGUMENT_OR_CONFIG_UNAVAILABLE` | 通知参数/SMTP 配置不可读 | 修正权限和配置；不要发送 |

## 12. 每日与每次发布的检查清单

**每日 20:30 检查**

1. 计划任务确实在北京时间 20:30 启动（非上海主机已核对时区）。
2. 检查输出为 0（`COMMITTED` / `SAME` / `ALREADY_COMPLETED` / `LOCAL_HISTORICAL_RECORD_ONLY`）。
3. 10（`PENDING_REVIEW`）时安排审核人，不让第二次检查覆盖原操作。
4. 25/`UNKNOWN` 时先按原 ID `inspect`/`reconcile`，不要重跑。
5. 每周至少运行一次 `check-health`；连续两交易日无成功时按第 8.2 节处理。
6. 通知失败独立记录；不因邮件失败回滚日历，也不把未送达当作已提醒。

**人工审核 / 每次发布**

1. 用 `trading_calendar_check` 检查配置和公告 YAML；确认没有未知键、未引用来源或未声明完整性。
2. 查看候选差异和来源；确认只影响目标交易所、品种、日期和窗口。
3. 确认人、确认时间、候选摘要写入记录；确认后配置/候选变化则重新校验。
4. 发布后只读核验 `CURRENT`、回执和 `scan-publications`；需要时发送通知。
5. 运行进程按交易日切换重读；不要强制重启来“让新版本生效”而跳过核验。

**升级 / 平台变更**

1. 先停止所有写入者并整体备份；记录当前 `version_id`、`publication_id` 和审核策略。
2. 在隔离目录验证新版本、路径、锁和通知；不要把测试数据装进生产根。
3. Windows/UNC/长路径、非上海时区和网络盘必须单独验证，未验证就保持不支持。

## 13. 相关文件

- 迭代计划与决定：`docs/_internal/opts/requirements/迭代67-交易日历数据文件化与每日更新/迭代计划.md`
- 开发交接与 GAP：`docs/_internal/opts/requirements/迭代67-交易日历数据文件化与每日更新/迭代67开发交接说明-2026-11-15.md`
- 示例与运行期边界：`examples/live/007_ctp/README.md`
- Backtrader 只读查询：`backtrader/feeds/btapifeed.py`（`trading_session`、`trading_windows`、
  `refresh_trading_calendar`、`trading_calendar_binding`）、`backtrader/stores/btapistore.py`
  （`trading_calendar_status`、`trading_calendar_query`）
- 配置解析：`backtrader/service/trading_calendar_config.py`、`bt_api_py/trading_calendar_config.py`
- 版本仓与发布：`bt_api_py/trading_calendar_store.py`、`bt_api_py/trading_calendar_package_seed.py`
- 每日检查/通知：`bt_api_py/trading_calendar_schedule_once.py`、`bt_api_py/trading_calendar_notify_cli.py`、
  `bt_api_py/trading_calendar_check.py`、`bt_api_py/trading_calendar_coverage_cli.py`
