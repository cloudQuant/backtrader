# OKX 穿透式在线验收

本目录按 `simnow_penetration` 的逐案例形式组织，但只运行严格的真实场所认证，不包含离线 smoke、模拟行情或本地 `BackBroker` 替代结论。

```text
okx_penetration/
  README.md
  config.example.yaml
  _certification/             # 本交易所私有的严格运行时
  cases/<ID>/<ID>_strategy.py # 案例动作、风险与证据字段合同
  cases/<ID>/run.py           # 仅运行该 ID
```

`_certification` 定义 33 个案例的授权、真实回执、独立事件、完整快照、清理对账和脱敏哈希证据校验合同；不引用 `000_live_certification` 根目录或任何兄弟交易所目录。因此可以把整个 `okx_penetration` 目录复制到其他位置使用。仍需 Python、PyYAML，以及配置指定的真实受管 HTTPS 桥或 Python backend；当前没有随目录提供已经受审部署的 OKX adapter，缺少它时结果必须是 `BLOCKED`，不是 `PASS`。

当前显式选择 `topology.transport: direct` 或 `gateway_zmq`，无论 execution/risk/monitor 如何组合，都会在读取凭据和创建 backend 前返回 `BLOCKED`；这些真实路线尚未实现。未声明 topology 的旧通用桥接入口在证据中标为 `legacy_generic_bridge`，不得当作直连或可选组件的验收结果。

复制 `config.example.yaml` 到仓库外的私有路径，替换场所标的、引用、快照等占位符，并通过环境变量提供 endpoint、token 和 account。不要把真实 URL、密钥或账户值写入此目录。运行单个只读案例：

```powershell
python cases/C01/run.py --config D:/private-cert/okx.yaml --evidence-dir D:/certification-evidence/okx-C01
```

每个 `run.py` 固定绑定其目录名对应的案例，故不接受 `--case` 或 `--all`。批量验收应由调用方逐个启动明确的案例入口并分别保存证据。

写入和高风险案例在示例配置中默认禁用，且三项 policy 授权均为 `false`。启用写入须同时修改私有配置、传入命令行开关，并给出精确确认短语，例如 `okx:demo:WRITE`；危险操作还需 `--allow-dangerous` 和 `okx:demo:DANGEROUS`，生产环境另需 `--allow-production-write`。执行前必须核对标的白名单、动作/数量/名义价值上限、参考价偏差、合约规格和清理目标。

只有真实 OKX 回执、独立查询或订阅事件、账户身份绑定及最终状态全部一致时，案例才可为 `PASS`。脚本启动、配置解析、桥接器自报成功、静态检查、`BLOCKED` 或 `FAILED` 都不代表验收通过。受管 backend 是信任边界，必须单独审查和固定部署；`close` 只允许释放本地传输资源，不得借机撤单、平仓、断开交易场所会话或修改控制状态。

环境变量模板使用 `BT_API_PENETRATION_OKX_ENDPOINT`、`BT_API_PENETRATION_OKX_TOKEN` 和 `BT_API_PENETRATION_OKX_ACCOUNT` 等名称；变量值只在运行时读取并写入前经过脱敏处理。

## 直接模拟盘账户预检

`direct_preflight.py` 可以独立检查 OKX 模拟盘 HTTPS 连接和账户认证。它只发送
`GET /api/v5/public/time` 和签名的 `GET /api/v5/account/config`，每个请求都带
`x-simulated-trading: 1`。每次 socket 操作超时为 5 秒，CLI 子进程总期限为 20 秒
（强制终止清理最多另需约 2 秒）；不重试、不跟随重定向、不使用环境代理。

脚本默认从 checkout 根目录已忽略的 `.env` 读取 `OKX_DEMO_API_KEY`、
`OKX_DEMO_SECRET`、`OKX_DEMO_PASSPHRASE`，支持简单的无引号或成对引号赋值，
不进行变量展开，也不读取生产密钥或继承同名环境变量。可用 `--env-file` 指定
仓库外的私有文件。输出仅包含固定状态、区域、域名与枚举账户模式；账户 ID、
原始响应、API 错误消息、密钥和签名都不输出或保存。

必须先确认账户所属区域，然后同时显式提供 `--region` 和 `--endpoint`：

| 区域 | 允许的 HTTPS origin |
| --- | --- |
| `global` | `https://openapi.okx.com` 或 `https://www.okx.com` |
| `us` | `https://us.okx.com` |
| `eea` | `https://eea.okx.com` |

下面示例只适用于已经确认的 global 账户，不能据此推定当前账户区域：

```powershell
python direct_preflight.py --region global --endpoint https://openapi.okx.com
```

区域与域名必须精确匹配，脚本不会猜测区域、切换站点或回退到生产环境。
`PREFLIGHT_OK` / exit 0 仅表示两项只读请求完成且模拟盘账户配置有效。
它不确认 SWAP 交易资格、余额、交易权限或任何认证案例通过；结果始终包含
`certification_status: NOT_RUN` 和 `certification_cases_passed: 0`。
受管 adapter、独立观察与完整 33 项案例的要求仍适用。失败或缺少配置为
`BLOCKED` / exit 2。

依据：[OKX REST 认证与模拟盘文档](https://www.okx.com/docs-v5/en/)、
[OKX 官方区域兼容说明](https://github.com/okx/agent-trade-kit/blob/github-main/docs/site-compatibility.md)。
