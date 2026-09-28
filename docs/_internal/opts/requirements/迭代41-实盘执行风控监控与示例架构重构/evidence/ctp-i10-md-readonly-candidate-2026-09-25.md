# CTP I10 MD 一次性只读候选：离线制品与组合边界（2026-09-25）

状态：`SUPERVISED_FRONT_SELECTION_REJECTED / NO_WRITE / LIVE_NO_GO`。I10 的一次真实受监督只读尝试在 front selection 阶段拒绝，未解析凭据、未导入/构造行情 SDK 客户端、未登录、未订阅或收到 tick；本页不能作为账户、原生有序关闭、报单或撤单的验收证据。SimNow 与未来生产仍共用 `examples/013_3_sa_midfreq_simnow/runtime-ctp-private/config.yaml` 和 canonical `ctp:` 字段；默认 CTP route 仍仅允许 sandbox 只读预检，未登记 I10，也未登记任何实盘写入路由。

## 冻结源码与 wheel

隔离 SDK 源码 commit 为 `a6253a58b1ebca11f58c8836fbed757d0daf7582`，版本 `2.0.3+iteration41.i10`。I10 修复 one-shot MD 登录和订阅调用的原生提交竞态：只有严格 `int 0` 返回才发布成功状态；早到有效 ACK/首 tick 在回调内复制成 owned scalar snapshot 并延迟交付，失败、stop、断连或 generation 变化清除暂存。独立静态复核未发现可阻断问题。源码五文件 MD 聚焦套件 `171 passed`，Ruff 与 diff 检查通过；这仍是离线 fake 合同。

两次独立 clean-clone build 的 wheel 字节及 87 个归档成员完全相同；wheel SHA-256 为 `e81bd7fcba8f0aaf823af9efcca565622a55842ed3bce970994f483f4f3188c4`，**wheel 内嵌** `RECORD` SHA-256 为 `0f7f5724ed45f98a491f8f6bcc767f9825551a8e0753f0911a40e993a9c23911`。两份独立 `--target` 安装各从本身目录加载包及原生扩展，五文件 fake suite 各 `171 passed`；其**安装后** `RECORD` 哈希分别为 `c0cd1f19a6af3f2bab0fc98042b5042e620565b67751bae362bf5d697649d673` 和 `cb768050b6f1a15c300591f3eae51e1ed9b4a7301a311817f88b285d85c40be2`，差异来自 pip 的 `direct_url.json` 来源路径。主仓校验器的 `record_sha256` 核验安装后的文件，不能填入 wheel 内嵌哈希；这两次临时安装也不是部署 pin。完整本机审计见 `D:\temp\i10-final-wheel-repro-20260925\I10-final-wheel-repro-receipt.md`。

## 后续只读接入门

受控 CPython 3.11 no-system-site-packages venv 的 I10 独立 installed `RECORD` pin 已加入主仓，仅用于未注册的一次性 MD 只读候选；`bt_api_base` installed `RECORD` 为 `47994f991fee3266e62fb368fe167dc1f188eceecfddac6ccc06dad2604e9762`，I10 CTP 为固定 wheel-A 来源的 `c0cd1f19a6af3f2bab0fc98042b5042e620565b67751bae362bf5d697649d673`。该 venv 中文件清单、metadata、direct URL、import spec 和原生扩展文件校验通过，I10/既有 provenance 测试合计 `44 passed`。另一个独立 no-system-site-packages venv `D:\temp\i10-runtime-env-20260925` 用冻结离线 wheelhouse 补齐依赖，`pip check` 通过，`python -I` 成功从该 venv 导入 `bt_api_base`、`bt_api_ctp` 与 native `.pyd`；安装后 `RECORD` 与已固定 pin 一致。主仓 I10 provenance gate 在此环境中用合成 front 离线实测为 `I10_PIN_PASS`。该 venv 因冻结 wheelhouse 不含 pytest，包内 fake 测试明确 `NOT_RUN`；其他两份独立 target 安装的各 `171 passed` 不能冒充此环境的测试。非秘密元数据收据位于 `D:\temp\i10-runtime-env-20260925\verification-receipt.json`。

I10 adapter、独立 latch、exact sealed-config 组合、固定 Windows Job 子进程与严格值脱敏 receipt 已完成离线实现和审阅；下文记录其一次真实受监督尝试。该诊断的范围仅为单合约 MD 登录、订阅和首 tick，不调用真实 TD、下单、撤单或结算 API。即使未来 MD 观察成功，也不证明账户、结算或交易 ready，更不开放默认 runner。

受支持的 I10 operator 入口先持久预留专用 latch，再用固定 Windows Job 启动只读 child；child body 自身在配置/凭据/SDK 前核对 Job 成员关系和 canonical marker。独立审查发现并修复了普通直接调用绕过；修复后完整 runtime suite 为 `1493 passed, 25 skipped, 1 existing PytestConfigWarning`。此 one-shot 保证仅覆盖代码拥有的 operator 入口，不声称防御拥有同一 Windows 用户权限、能直接调用私有 Python 函数或 SDK 的主动对抗者；该用户本来就可读取其受保护的凭据并绕开本程序。Job 的 45 秒是 child deadline，父进程为确认退出和 Job 清空还可等待有界 grace。独立审查确认正常监督路径未见新增阻断项，但未把同用户任意 Python 执行视为可隔离威胁。

## 一次真实受监督观察

在受保护的同一份配置仍为 `simulation/sandbox` 且 I10 marker 尚不存在时，受支持的 I10 operator 入口仅运行一次。父回执为 `exit_code=2 / rejected / child_diagnostic_rejected`；子回执为 `rejected / front_selection_rejected / front_selection`，登录身份状态 `unavailable`，订阅、tick 和关闭字段均为 `null`。Windows Job 的 `job_empty_observed=true`、`containment=verified`；这是**进程 containment**，不是 SDK 原生有序关闭，因为 SDK 从未进入。专用 marker 已消耗，不能将本次拒绝改写成成功或重跑 I10。

随后独立进行的无凭据、无 SDK TCP 复核仅探测 sealed `config.yaml` 中的 5 组候选：每一组的 MD、TD 各 3 次均为 `TimeoutError`，无可选 pair；第 5 组额外 10 秒单次探测也分别超时。公共 TCP 控制地址 `1.1.1.1:443` 与 `8.8.8.8:53` 能连接，因此本机不是完全断网；这不能证明 CTP 前置自身故障，亦可能是时段或到 CTP 的网络路径限制。受保护文件中显式包含[SimNow 官方产品页](https://www.simnow.com.cn/product.action)列出的 7x24 MD/TD pair；程序没有用官方地址表替代用户配置，也没有按时间或 set 名称选路。官方页说明该环境面向 API 测试且不提供结算，其服务窗口并非任意时间始终开放；本次拒绝发生时未据此推断失败原因。继续保持 `NO_WRITE / LIVE_NO_GO`。

在 I10 child body 的直接调用门修复前，主仓 runtime 全套曾为 `1473 passed, 25 skipped, 1 existing PytestConfigWarning`（exit 0）；修复后的最新结果为上文 `1493 passed, 25 skipped`。旧 I9 只有 wheel 构建证据，未形成受控 installed pin；其校验入口已改为在检查 installed distribution 前 fail closed。
