# ctp_007 gateway 策略 live 启动验收（2026-11-19）

> 用户诉求：验收 `examples/live/007_ctp/*_gateway` 策略能否正常运行（不是 direct 策略）。
> 结论：把 `sa_dual_ma_gateway` 从 `BLOCKED` 一路推进到"策略侧全部就绪、正在连接 Gateway 服务"，
> 打通了 5 个 POSIX-only 安全门 + 全套自洽身份配置；最终阻塞是**没有真实运行的 Gateway 服务**
>（运营部署输入，非策略代码问题）。

## 1. 策略侧的门，逐个打通（本轮实质进展）

| # | 阻塞点 | 修复 | 验证 |
|---|---|---|---|
| 1 | `_open_key` `KEY_PLATFORM_UNSUPPORTED` | Windows 分支复用 `read_bounded_windows`（no-follow/owner/TOCTOU 等价），POSIX 不变 | key loader 2 passed |
| 2 | `prepare_gateway_state` `STATE_SETUP_PLATFORM_UNSUPPORTED` | 新增 `_prepare_gateway_state_windows`（owner-only ACL + reparse 拒绝 + 两级 reservation 防重试），POSIX 不变 | `--first-init` 生成 UUID4 identity |
| 3 | `verify_gateway_preparation` 同一门（marker 读取） | 新增 `_verify_new_identity_marker_windows`（read_bounded_windows + JSON/UUID 校验） | upgrade 通过 |
| 4 | `GATEWAY_STATE_UPGRADE_REQUIRED` | 走 `--upgrade-state`，pending v1→v6 | `RESOLVE OK` |
| 5 | `_open_gateway_execution_db` `GATEWAY_EXECUTION_STATE_PATH_INVALID` | 新增 `_gateway_state_dir_trusted` / `_gateway_db_identity` 的 Windows 等价（inspect_owner + lstat st_dev/st_ino，避免 Windows 重开句柄冲突），POSIX 不变 | Store/Broker 创建 OK |

附带：state setup 的 ACL 顺序修正（先 `_set_owner_only_acl` 再校验）、empty 前置移到 initialize 之前。

## 2. 自洽本地测试身份（全部合成，非真实授权）

- first-init 生成 strategy UUID4：`1045f61a-88f7-47a0-b3ed-ed2c915ae10a`（写入 `state/identity.json`）。
- 生成 9 个 CURVE Z85 密钥对到 `state/keys/`（3 个 profile × server_public/client_public/client_secret；client secret 与 public 配对已断言）。
- config 占位符全部替换为自洽值：11×strategy UUID、grant `exec-grant-v1`、delegation `delegation-local-1`、build `build-local-1`、position ref `sa701-position`、8×交易日 `20261231`、4×截止 `2026-12-31T15:00:00+08:00`。
- `validate_config` 通过、`binding.strategy_scope` == identity UUID、`resolve_resources` OK（state + keys 全部有效）。
- 配置测试后已恢复原始占位符状态（git status 干净）；`state/`、`state/keys/` 保留为本地测试 identity。

## 3. 实测推进轨迹

```
run.py --dry-run                    → PASS (11/11 gateway 策略)
run.py --run-seconds 10             → BLOCKED / GATEWAY_RESOURCES_UNAVAILABLE (密钥门)
   修复门1后 first-init             → UUID4 生成
   upgrade-state + 门2/3            → RESOLVE OK / state v6
run.py --run-seconds 10             → CRASHED / GATEWAY_RUN_FAILED (stage=run)
   store.start() 诊断               → GATEWAY_EXECUTION_STATE_PATH_INVALID (门5)
   修复门5后 store.start()          → START_TIMEOUT_CLEANUP_PENDING
```

最后 `store.start()` 到达 `api.start()` → `ThreadedRuntimeError: START_TIMEOUT_CLEANUP_PENDING`：
策略在连接 config 指定的 Gateway 服务 `tcp://127.0.0.1:12345/12346`（Risk `12355`、Execution `12365`）时超时——
这四个端口本机全部 closed，没有服务在监听。

## 4. 最终阻塞：无真实 Gateway 服务（运营部署输入）

- 11 个 gateway config 都指向固定端口 12345/12346（Gateway RPC/行情）、12355（Risk）、12365（Execution）。
- 五服务 harness（`win11_five_service_acceptance`）的 gateway 是 dry-run + 合成进程，端口随机、无行情端口，且 `with` 结束即退出，不能承接策略。
- 真实 CTP Gateway 需要受保护 resource bundle：`ctp_gateway_local_profile._protected_json`（POSIX-only，绝对路径 `/` 开头）+ SimNow 账户凭据 + clock（SNTP）+ returns + OS 用户隔离；并需把我生成的策略 UUID 与 9 个公钥注册进 bundle 的 principals/grants。
- 也要把同一 UUID/公钥注册到 Risk（`_iter64_risk_fixture.py:984-1030` 形态）与 Execution（`execution_parent_service_host.py:128-191` 形态）。
- 这些是运营级部署输入，不是代码/配置技巧能替代；本机 `.env` 有 SimNow 凭据，但完整 bundle + 身份注册 + 服务常驻是独立工程。

## 5. 验收结论与边界
- ✅ 11 个 gateway 策略 dry-run 全 PASS。
- ✅ `sa_dual_ma_gateway` 策略侧全部就绪：state/identity、CURVE 密钥、config 自洽身份、Store/Broker 创建、推进到连接 Gateway 服务。
- ✅ 5 个 Windows POSIX 门完成等价适配，强度不降低，POSIX 路径不变；直接相关测试通过。
- ⛔ gateway 策略"正常运行"的最终一步需要真实常驻 Gateway（+Risk+Execution）服务及身份注册，属运营部署，本机当前无此服务。
- 本轮未放宽除已授权 Windows 等价适配外的任何 fail-closed 门；临时 config 已恢复；未提交/push。

## 6. 下一步（需用户提供或授权）
要真正跑通，需二选一：
1. 用户提供一个已配置、常驻、端口匹配的 Gateway（+Risk+Execution）服务，并把本策略 UUID/公钥注册进去；
2. 授权搭建本地 SimNow Gateway 运营环境（构造受保护 bundle、注册身份、移植 `_protected_json` 到 Windows、常驻四服务）——这是独立的大工程。
