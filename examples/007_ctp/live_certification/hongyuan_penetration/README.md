# 宏源期货 穿透式认证场景集（历史 source，当前禁用）

这 33 个场景仍保留为历史认证设计和后续 managed migration 的测试素材，但当前代码包含
旧的 direct CTP/SimNow provider、报单和撤单路径。它们不属于 Iteration 41 的受管执行
入口，不能用于账户、沙盒或生产验收。

所有 `run_case.py`、`run_all.py` 和 `cases/*.py` 直启路径现在都会在 Backtrader、CTP
或 provider 导入前 fail-closed。旧参数（包括 `--list`、场景 ID、`--all`、
`--report-root`）也不能恢复 direct child process。真实认证操作是 `NOT_SUPPORTED`，直到
独立的 managed TestExecutionProfile、账户预算/TTL、清理对账和 provider admission 都
完成审查。

当前唯一可运行的 Iteration 41 路径是 007 的本地零 I/O migration report：

```bash
bt-runtime bootstrap --strategy-dir examples/007_ctp/runtime
bt-runtime run --strategy-dir examples/007_ctp/runtime
```

`runtime/config.yaml` 必须存在且由 Git 忽略。缺少时返回 `CONFIG_REQUIRED`；已有文件
不会被 bootstrap 覆盖（`CONFIG_EXISTS`）。输出 `LOCAL_REPLAY_ONLY` 仅证明 config gate
与 no-action probe；它不是 CTP 连通、SimNow/宏源账户、报撤单、成交、PnL 或实盘准入证据。

## 历史目录结构

```bash
hongyuan_penetration/
├── README.md
├── .env.example         # 凭证配置示例

├── run_case.py          # 统一运行器（支持单个/批量/全部）

├── run_all.py           # 快捷全量运行

├── common/
│   ├── config.py        # 宏源期货环境配置与凭据

│   ├── result.py        # PASS/FAIL/BLOCKED 结果模型

│   ├── runtime.py       # Store/Broker/Feed 初始化 & 子进程入口

│   └── helpers.py       # 日志读取、证据收集工具

├── cases/
│   ├── C01_connect_and_login.py
│   ├── T01_open_order.py
│   ├── T02_close_order.py
│   ├── T03_cancel_order.py
│   ├── M01_connection_success_display.py
│   ├── M02_disconnect_display.py
│   ├── M03_reconnect_success.py
│   ├── M04_order_count_stats.py
│   ├── M05_cancel_count_stats.py
│   ├── O01_repeat_open_order.py         (选测)
│   ├── O02_repeat_close_order.py        (选测)
│   ├── O03_repeat_cancel_order.py       (选测)
│   ├── TH01_order_threshold_setting.py
│   ├── TH02_order_threshold_alert.py
│   ├── TH03_total_threshold_setting.py
│   ├── TH04_total_threshold_alert.py
│   ├── TH05_repeat_threshold_setting.py (选测)
│   ├── TH06_repeat_threshold_alert.py   (选测)
│   ├── V01_invalid_instrument.py
│   ├── V02_invalid_price_tick.py
│   ├── V03_exceed_max_volume.py
│   ├── E01_insufficient_funds.py
│   ├── E02_insufficient_position.py
│   ├── E03_market_state_error.py
│   ├── EM01_restrict_trading.py
│   ├── EM02_pause_strategy.py
│   ├── EM03_force_logout.py
│   ├── B01_batch_cancel_partial.py
│   ├── B02_batch_cancel_pending.py
│   ├── L01_trade_info_log.py
│   ├── L02_system_run_log.py
│   ├── L03_monitor_info_log.py
│   └── L04_error_info_log.py
└── reports/
    └── latest/           # 最近一次运行的结果
        ├── summary.json  # 33 场景汇总
        └── C01/
            ├── result.json
            ├── stdout.log
            └── logs/
                ├── system.log
                ├── monitor.log
                ├── error.log
                └── order.log

```bash

## 33 场景清单

### 连通性 (1)

| ID | 名称 | 必做 |

|----|------|------|

| C01 | 验证登录测试账号通过柜台认证并完成账号登录 | ✓ |

### 基础交易功能 (3)

| ID | 名称 | 必做 |

|----|------|------|

| T01 | 验证能正常下达开仓指令 | ✓ |

| T02 | 验证能正常下达平仓指令 | ✓ |

| T03 | 验证能正常下达撤单指令 | ✓ |

### 系统连接异常监测 (3)

| ID | 名称 | 必做 |

|----|------|------|

| M01 | 验证连接成功时能正常显示连接成功 | ✓ |

| M02 | 验证连接断开时能正常显示连接断开 | ✓ |

| M03 | 验证连接断开后能正常显示重连成功 | ✓ |

### 报撤单笔数监测 (2)

| ID | 名称 | 必做 |

|----|------|------|

| M04 | 验证能正常统计报单笔数 | ✓ |

| M05 | 验证能正常统计撤单笔数 | ✓ |

### 重复报单监测 (3, 选测)

| ID | 名称 | 必做 |

|----|------|------|

| O01 | 验证能统计重复开仓单报单笔数 | 选测 |

| O02 | 验证能统计重复平仓单报单笔数 | 选测 |

| O03 | 验证能统计重复撤单报单笔数 | 选测 |

### 阈值设置及预警 (6, 其中 2 选测)

| ID | 名称 | 必做 |

|----|------|------|

| TH01 | 验证提供报单笔数统计阈值设置功能 | ✓ |

| TH02 | 验证报单笔数达到或超过阈值时会预警 | ✓ |

| TH03 | 验证提供报撤单总数统计与阈值设置功能 | ✓ |

| TH04 | 验证报撤单总数达到或超过阈值时会预警 | ✓ |

| TH05 | 验证提供重复报单笔数统计与阈值设置功能 | 选测 |

| TH06 | 验证重复报单笔数达到或超过阈值时会预警 | 选测 |

### 错误防范 (3)

| ID | 名称 | 必做 |

|----|------|------|

| V01 | 验证订单合约代码错误时系统能检查并拒绝报单 | ✓ |

| V02 | 验证订单价格最小变动价位错误时系统能检查并拒绝报单 | ✓ |

| V03 | 验证订单委托数量超过单笔最大委托数量时系统能检查并拒绝报单 | ✓ |

### 错误提示 (3)

| ID | 名称 | 必做 |

|----|------|------|

| E01 | 验证系统能接收并展示柜台返回的资金不足错误码 | ✓ |

| E02 | 验证系统能接收并展示柜台返回的持仓不足错误码 | ✓ |

| E03 | 验证系统能接收并展示柜台返回的市场状态错误码 | ✓ |

### 应急处理 (3)

| ID | 名称 | 必做 |

|----|------|------|

| EM01 | 验证系统可通过限制账号交易权限方式暂停交易 | ✓ |

| EM02 | 验证系统可通过暂停策略执行方式暂停交易 | ✓ |

| EM03 | 验证系统可通过强制账号退出方式暂停交易 | ✓ |

### 批量撤单 (2)

| ID | 名称 | 必做 |

|----|------|------|

| B01 | 验证系统支持将多笔部分成交报单进行批量撤单 | ✓ |

| B02 | 验证系统支持将多笔已报单进行批量撤单 | ✓ |

### 日志记录 (4)

| ID | 名称 | 必做 |

|----|------|------|

| L01 | 验证系统日志中会记录交易信息 | ✓ |

| L02 | 验证系统日志中会记录系统运行信息 | ✓ |

| L03 | 验证系统日志中会记录监测信息 | ✓ |

| L04 | 验证系统日志中会记录错误提示信息 | ✓ |

## 结果状态

| 状态 | 退出码 | 含义 |

|------|--------|------|

| `PASS` | 0 | 场景验证通过 |

| `FAIL` | 1 | 场景验证失败（代码或逻辑错误） |

| `BLOCKED` | 2 | 外部条件不满足（仿真环境不稳定、市场关闭等） |

## 已知高风险场景

以下场景在宏源仿真环境下可能无法稳定复现，会输出 `BLOCKED` 并记录证据：

- **M02 / M03**：断开与重连
- **E01 / E02 / E03**：远端错误码（使用本地校验兜底）
- **EM03**：强制账号退出
- **B01**：部分成交后批量撤单
