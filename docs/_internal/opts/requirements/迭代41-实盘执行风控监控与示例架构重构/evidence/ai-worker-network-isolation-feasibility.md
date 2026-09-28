# AI worker OS 网络隔离可行性与验收提案

状态：`READ_ONLY_FEASIBILITY_AUDIT / PROPOSAL_ONLY / NOT_RUN / LIVE_NO_GO`。本记录依据 2026-09-23 对三个 AI 产品工作树的只读检查整理；没有连接 provider，没有读取私有 `.env`/`config.yaml` 值，也没有修改产品代码。下述平台后端是候选方案，尚未实现或验收。

## 当前执行边界

| 产品 | 候选执行入口 | 当前控制与缺口 |
| --- | --- | --- |
| `backtrader-agent`（`D:/source_code/backtrader-agent`） | `src/backtrader_agent/runner/execute.py:152` 的 `_execute_profile`；正常 run 在 `:926`，sweep 在 `src/backtrader_agent/sweep_run.py:564` 复用该入口。 | 固定参数、最小环境、timeout 和 POSIX resource limits；validator 对常见危险 import（含 `socket`）和动态执行作静态拒绝。仍是普通本机 Python 子进程。 |
| `backtrader-skills`（`D:/source_code/backtrader-skills`） | `src/backtrader_skills/runner.py:277` 的 `_run_mode` / `:308` 的 `subprocess.run`；`child_runner.py:41`、`:48` 动态加载获准生成的策略类。 | `python -I`、筛选过的环境、`NO_PROXY=*` 和静态 forbidden-import 检查。`NO_PROXY`、隔离模式导入与静态校验均不限制 socket；没有候选进程组或 OS 网络沙箱。 |
| `backtrader-mcp`（`D:/source_code/backtrader-mcp`） | `src/backtrader_mcp/jobs.py:519` 启动受信 worker；`src/backtrader_mcp/worker.py:575` / `:610` 启动候选。 | worker 有最小环境、进程组和 POSIX resource-limit 路径，validator 静态拒绝常见网络/进程/文件系统引用。Python socket monkeypatch 测试只覆盖校验/准备路径，不覆盖候选进程。README 也明确 AST 与 subprocess 不是 OS sandbox。 |

三者能拒绝已知源代码模式、固定执行参数或限制进程时长，但候选仍以本机进程运行；任意动态 Python、依赖副作用和子进程不能因此被证明为零网络。最小环境、`NO_PROXY`、拒绝 `socket` import、网络计数为零或 fake-provider 测试，都不能代替 OS 强制边界。

## 建议的 fail-closed 部署合同

provider-capable 部署将候选执行标记为 `network_isolation_required`。只有平台启动器完成预检并实际将候选及全部后代放入无网络边界后，才允许创建/启动运行任务或消费一次性运行授权。缺少后端、内核功能、平台组件或验证失败时，返回稳定的 `ISOLATION_UNAVAILABLE` / `NOT_SUPPORTED`；继续允许生成、静态 review 和数据准备，禁止候选 run/test。不得静默回退到普通子进程，也不得提供生产 profile 的绕过开关。

候选只获得只读 strategy/runtime/data 输入与一个受限结果目录。受保护 `config.yaml`、credentials、provider SDK secrets、代理变量、worker 控制句柄、宿主 socket 和 provider 连接均不进入候选环境或可见文件系统。provider-capable 的可信 runtime 单独读取配置并拥有 provider authority；若候选需要实时数据或订单意图，未来只能通过窄化、类型化、逐请求校验的 IPC 能力接口交互，不能提供通用 TCP/HTTP proxy。当前三个产品的候选均在自己的 Backtrader 离线运行路径执行，还没有这种隔离的 provider/runtime IPC 架构。

## 平台后端候选（提案，未实现）

- **Linux：**优先用 rootless OCI runner 显式设置 `--network=none`，或经验证的 `bubblewrap --unshare-net` / 独立 network namespace 启动器。Linux network namespace 隔离网络设备、路由和 protocol stack；Docker `none` driver 留有隔离的 loopback。启动器须丢弃 capabilities、关闭未授权句柄、隔离 PID/挂载视图，不挂载宿主 Unix sockets；输入/runtime/data 只读挂载，结果目录单独可写。预置可能要求管理员安装/配置容器运行时或启用 unprivileged user namespaces；机器不满足先决条件则拒绝运行。[Linux network namespaces](https://www.man7.org/linux/man-pages/man7/network_namespaces.7.html) · [Docker `none` network](https://docs.docker.com/engine/network/drivers/none/)
- **Windows：**优先评估原生 AppContainer launcher：使用无 network capabilities 的 AppContainer identity、显式继承句柄清单、候选专属文件 ACL 与 kill-on-close Job Object；把 config/secrets 所在目录排除在 identity 授权之外。另一候选是 Windows Sandbox 配置 `<Networking>Disable</Networking>`，仅映射只读输入和窄结果目录；其 CLI 从 Windows 11 24H2 提供，但官方说明 `exec` 当前不支持进程 I/O，需用受控文件交换。需要桌面/Hyper-V 功能、系统配置与真实 Windows 验收。Microsoft 文档列出的 Windows Server containers 默认 outbound policy 为 allow all；未单独配置并实测的 Windows 容器不合格。[AppContainer](https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer) · [Windows Sandbox 配置](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-configure-using-wsb-file) · [Sandbox CLI](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-cli) · [Windows container network isolation](https://learn.microsoft.com/en-us/virtualization/windowscontainers/container-networking/network-isolation-security)

这些后端只描述可评估的技术路线，不代表产品具备相应支持、权限或安全验收。普通 Windows Firewall 按 Python 可执行文件建规则不足以覆盖候选另外启动的程序；POSIX session/process group、resource limits 与 AST 规则也不构成网络边界。

## OS 级验收要求

1. **拒绝失败关闭：**模拟缺少/损坏启动器、关闭 user namespace、无可用 AppContainer/Sandbox 时，候选代码不启动，运行授权不消费、任务不进入 runnable 状态；结果清楚记录 `ISOLATION_UNAVAILABLE`。常规 author/review/data preparation 仍可用。
2. **对抗性网络探针：**在一次隔离候选和它启动的 Python/系统子进程中尝试 IPv4、IPv6、TCP、UDP/DNS、raw socket，以及直接连接宿主上的测试 sentinel。sentinel 必须没有收到数据；受信宿主 worker 对同一 fake provider sentinel 的访问仍可成功。对取消/timeout 另验证脱离普通 process group 的后代仍留在无网边界且被清理。
3. **核验实际 OS 状态：**Linux 检查候选的 network namespace inode 与宿主不同、除隔离 loopback 外无接口/路由，并确认没有挂载宿主代理/IPC socket；Windows 检查实际 AppContainer identity 与 network-capability 集合，或核对运行中的 Sandbox 确实采用 network-disabled 配置。只检查命令行、环境变量、静态报告或 monkeypatch 不通过本项。
4. **配置与文件边界：**只用合成 canary config/credential 测试候选不能枚举或打开受保护目录、不能取得 provider handles/environment；核对候选可见挂载仅含约定的只读输入/runtime/data 与独立结果目录。不得把真实私有配置内容放进验收日志。
5. **功能与平台证据：**受限候选仍能用注册 CSV 完成 runonce/runnext 并产出符合 schema 的结果；分别在实际 Linux 与 Windows 隔离主机执行 OS 级探针和端到端 worker 测试。跨平台 helper 单测、CI 模拟分支和本机 fake-provider 结果仅作补充，不能将未运行平台标记 PASS。

当前上述 OS 级验收均为 `NOT_RUN`。任何可能触达 CTP/provider 的 AI candidate/runtime 保持 `LIVE_NO_GO`，直到启动器实现、两个平台真实验收及独立部署审查完成。
