# CTP I4 一枪式 MD 只读候选：离线制品证据（2026-09-25）

本记录只证明本机离线源码、wheel、安装来源与假客户端合同，不证明 SimNow 已登录、订阅、收到 tick，也不授予报单、撤单、结算或生产写入权限。I4 诊断未注册到默认 CLI/runner；默认 I2 SimNow 私有预检仍为只读。

| 项目 | 已核验值 |
| --- | --- |
| 隔离 SDK 源码提交 | `809239fdc0b7982d3512f4289e3e8dbcbd43a523`，工作树干净；两位独立复核者核对该精确 SHA |
| CTP wheel | `bt_api_ctp-2.0.3+iteration41.i4-cp311-cp311-win_amd64.whl`；SHA-256 `96f8c874871b6f571e3abb14bf25b32a4ccb133ca09e51767584e5c03682283e` |
| I4 安装 CTP RECORD | SHA-256 `327998c95de9c3a69ac9cb40444361822c8602e30975067705a750c782ffbd6f` |
| base wheel | `bt_api_base-0.15.5-py3-none-any.whl`；SHA-256 `1c1129444d8659f4dfe7b72f716872a63dddf13c1c935865e1d2568800d0d64d` |
| I4 安装 base RECORD | SHA-256 `aa91bfa982d473eb2b8ce59192196f87a84e7c9c19aafd8e961c73e5ea87ce90`；使用 I4 独立 pin，不更改 I2 pin |
| 安装与来源 | `D:\c41sdki4_audit\install-i4-runtime-venv-v2` 的 verifier `verification_status=passed`，优化级别 0，wheel/RECORD、`direct_url`、Python 模块路径、原生 x64 扩展均通过 |
| 离线测试 | SDK 源码焦点 85 通过，源码 CTP 套件 623 通过、1 项网络测试未运行；安装后精确两文件焦点 85 通过；主仓 I4 组合焦点 66 通过。所有这些均无 provider 连接或写入。 |

原始本机审计文件位于 `D:\c41sdki4_audit\i4-build-manifest.json`、`i4-artifact-verification.json`、`i4-focused-tests.log` 和 `i4-focused-junit.xml`。构建使用固定提交和两名复核者的本地清单；清单是本机审查记录，不是外部签名或账户授权。wheel 和 base 包在本机隔离 venv 安装，`bt_api_ctp` 与 `bt_api_base` 的 import origin 必须落在该 venv。第一次安装被 PowerShell 对 pip 弃用提示的 stderr 处理提前中断，留下未安装 SDK 包的 v1 venv；成功的审计安装只使用新的 v2 venv，未将 v1 视为证据。

主仓 `ctp_artifact_provenance.py` 对 I4 使用独立 pin 表和独立 verifier；I2 注册预检的 base/CTP pin 没有改变。I4 组合在 TCP 探测前校验初始制品，在选定 sealed config 中的整组 MD/TD 后再次校验，在读取凭据前完成制品门；SDK 导入只发生在凭据封闭校验后。尚未记录真实 MD 登录响应、精确订阅确认、匹配 tick 和完整原生停止回执；这些须另行逐项裁决，不能凭上述离线 PASS 推断。
