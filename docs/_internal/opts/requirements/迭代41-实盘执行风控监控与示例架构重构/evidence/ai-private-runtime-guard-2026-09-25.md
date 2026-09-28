# AI 离线产品对 CTP 私有 runtime 的路径保护（2026-09-25）

状态：`LOCAL_STATIC_GUARD_PASS / AI_CTP_RUNTIME_NO_GO`。`backtrader-agent`、`backtrader-skills` 与 `backtrader-mcp` 仍是离线策略生成、评审和测试产品，不是 Iter41 CTP runner。本轮三仓都补了私有 runtime 的静态路径边界；没有让 AI 产品读取受保护的 `config.yaml` 或 `.env`，也没有 provider、SDK、网络或交易写入。

Agent 在 `src/backtrader_agent/protected_paths.py` 新增仅看文件名与 metadata 的保护检查，并把它放在 engine inspection、CLI validate、sweep prepare、run/sweep 解析和实际 child start 之前。Skills 在 `src/backtrader_skills/protected_paths.py` 及 runner/CLI 边界做同类检查。只含 tracked `README.md`/`.gitignore` 的干净 `runtime-ctp-private` 目录仍允许普通离线 runonce/runnext；直接把它当执行目标、目录内出现 `config.yaml`/`secrets.yaml` 等受保护文件，或遇到危险 reparse/junction/alias 时拒绝，且不打开配置内容。Agent 的 sweep 测试改用只含 Backtrader 包和干净目录占位的临时 staging，避免把本机真实私有配置误当普通离线 fixture。

独立复核没有发现修复版残余 P1/P2。Agent `tests/test_protected_paths.py` 为 14 passed，sweep prepare/run/CLI 三个定向集 3 passed，私有配置拒绝及干净 checkout 的 runonce/runnext 两项 2 passed；随后完整 `tests/test_sweep.py` 在修复 fixture 后于本机 exit 0，只有既有依赖弃用和 engine provenance warnings。Skills 的 runner、CLI guard 与双模式定向用例 9 passed；其旧的 protected runtime 父目录 junction 漏口已通过 `examples` 下 reparse fail-closed 修复。作者还运行了针对性 Ruff、格式、manifest（77 files）与 diff 检查。

MCP 在 `src/backtrader_mcp/protected_paths.py` 及 `jobs.py`、`catalog.py`、`changes.py` 补相同 metadata-only 拒绝：策略目录写入、source catalog refresh/inspect、runtime prepare/start、worker 读取 draft/dataset 与启动候选子进程之前均复查。私有 runtime 下出现 `config.yaml`、`secrets.yaml`、`.env*`，或遇到 Windows reparse/指向私有、外部或 dangling 的 alias 时，均在内容读取、哈希、审批消耗、写入或 Popen 前拒绝。只含 `README.md`/`.gitignore` 的干净 placeholder 可通过。作者聚焦组合 `72 passed`，Ruff、格式和 diff 检查通过；独立 reviewer 用 fake tmp_path 复核边界 `22 passed`，Ruff/py_compile 通过，没有发现静态威胁模型内的 P1/P2。测试未访问真实配置或 provider。

此保护是静态路径门，只覆盖已命名的私有配置格式和受支持入口。检查与后续读取/写入/Popen 之间没有跨进程原子文件 lease；它不能隔离任意动态 Python 对 checkout 根 `.env`、文件系统或网络的访问，也不能替代部署级 OS 文件/网络隔离或使 AI 可连接 CTP。任何 AI→受管 runtime 接入在独立服务端准入、外部部署验证和负测完成前保持 `NO_GO`；SimNow 与生产仍只使用同一受保护 `config.yaml` 和受审 runtime 入口。
