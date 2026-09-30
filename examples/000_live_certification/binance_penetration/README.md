# Binance 穿透式在线验收

本目录按 `simnow_penetration` 的逐案例形式组织，但只运行严格的真实场所认证，不包含离线 smoke、模拟行情或本地 `BackBroker` 替代结论。

```text
binance_penetration/
  README.md
  config.example.yaml
  _certification/             # 本交易所私有的严格运行时
  cases/<ID>/<ID>_strategy.py # 案例动作、风险与证据字段合同
  cases/<ID>/run.py           # 仅运行该 ID
```

`_certification` 定义 33 个案例的授权、真实回执、独立事件、完整快照、清理对账和脱敏哈希证据校验合同；不引用 `000_live_certification` 根目录或任何兄弟交易所目录。因此可以把整个 `binance_penetration` 目录复制到其他位置使用。仍需 Python、PyYAML，以及配置指定的真实受管 HTTPS 桥或 Python backend；当前没有随目录提供已经受审部署的 Binance adapter，缺少它时结果必须是 `BLOCKED`，不是 `PASS`。

当前显式选择 `topology.transport: direct` 或 `gateway_zmq`，无论 execution/risk/monitor 如何组合，都会在读取凭据和创建 backend 前返回 `BLOCKED`；这些真实路线尚未实现。未声明 topology 的旧通用桥接入口在证据中标为 `legacy_generic_bridge`，不得当作直连或可选组件的验收结果。

复制 `config.example.yaml` 到仓库外的私有路径，替换场所标的、引用、快照等占位符，并通过环境变量提供 endpoint、token 和 account。不要把真实 URL、密钥或账户值写入此目录。运行单个只读案例：

```powershell
python cases/C01/run.py --config D:/private-cert/binance.yaml --evidence-dir D:/certification-evidence/binance-C01
```

每个 `run.py` 固定绑定其目录名对应的案例，故不接受 `--case` 或 `--all`。批量验收应由调用方逐个启动明确的案例入口并分别保存证据。

写入和高风险案例在示例配置中默认禁用，且三项 policy 授权均为 `false`。启用写入须同时修改私有配置、传入命令行开关，并给出精确确认短语，例如 `binance:demo:WRITE`；危险操作还需 `--allow-dangerous` 和 `binance:demo:DANGEROUS`，生产环境另需 `--allow-production-write`。执行前必须核对标的白名单、动作/数量/名义价值上限、参考价偏差、合约规格和清理目标。

只有真实 Binance 回执、独立查询或订阅事件、账户身份绑定及最终状态全部一致时，案例才可为 `PASS`。脚本启动、配置解析、桥接器自报成功、静态检查、`BLOCKED` 或 `FAILED` 都不代表验收通过。受管 backend 是信任边界，必须单独审查和固定部署；`close` 只允许释放本地传输资源，不得借机撤单、平仓、断开交易场所会话或修改控制状态。

环境变量模板使用 `BT_API_PENETRATION_BINANCE_ENDPOINT`、`BT_API_PENETRATION_BINANCE_TOKEN` 和 `BT_API_PENETRATION_BINANCE_ACCOUNT` 等名称；变量值只在运行时读取并写入前经过脱敏处理。

## USDⓈ-M demo 账户只读直连预检

从仓库根目录执行 `python examples/000_live_certification/binance_penetration/direct_preflight.py`。
此独立入口只读取根目录已被 Git 忽略的 `.env` 中的 `BINANCE_DEMO_API_KEY` 和
`BINANCE_DEMO_SECRET`，仅支持字面量 HMAC 密钥；不执行或展开 `.env` 内容，也不使用其他环境密钥。
它只向固定 `https://demo-fapi.binance.com/fapi/v3/account` 发送一次签名 GET。
TLS 证书和主机名校验开启，不读取代理环境、不跟随重定向、不重试或回退生产站点。
套接字超时 5 秒，子进程总等待上限 20 秒（超时后终止并回收，最多另等 4.2 秒），响应体上限 256 KiB。

标准输出仅为允许字段组成的 JSON，包含连接、签名账户查询和固定 demo 环境绑定的独立观测；
不输出密钥、签名、响应原文、余额、仓位、账户标识或服务端错误消息。
`preflight=OBSERVED` / exit 0 仅说明当次只读账户查询得到符合结构的响应；其他情况为
`BLOCKED` / exit 2。无论结果如何，`strict_case_results=NOT_EVALUATED` 且
`strict_cases_passed=0`：它不执行订单或撤单，也不作为 33 个案例任何一个的 `PASS`，
不证明交易权限、账户身份的独立绑定、后续可达性或完整认证。

端点、签名和账户查询依据 2026-09-30 查阅的 Binance 官方文档：
[General Info / Testnet 与 HMAC 签名](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/general-info)、
[Account Information V3](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/account)。
