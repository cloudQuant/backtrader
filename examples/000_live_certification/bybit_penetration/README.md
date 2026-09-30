# Bybit 穿透式在线验收

本目录按 `simnow_penetration` 的逐案例形式组织，但只运行严格的真实场所认证，不包含离线 smoke、模拟行情或本地 `BackBroker` 替代结论。

```text
bybit_penetration/
  README.md
  config.example.yaml
  _certification/             # 本交易所私有的严格运行时
  cases/<ID>/<ID>_strategy.py # 案例动作、风险与证据字段合同
  cases/<ID>/run.py           # 仅运行该 ID
```

`_certification` 完整包含 33 个案例所需的授权、真实回执、独立事件、完整快照、清理对账和脱敏哈希证据链；不引用 `000_live_certification` 根目录或任何兄弟交易所目录。因此可以把整个 `bybit_penetration` 目录复制到其他位置使用。仍需 Python、PyYAML，以及配置指定的真实受管 HTTPS 桥或 Python backend；当前没有随目录提供已经受审部署的 Bybit adapter，缺少它时结果必须是 `BLOCKED`，不是 `PASS`。

复制 `config.example.yaml` 到仓库外的私有路径，替换场所标的、引用、快照等占位符，并通过环境变量提供 endpoint、token 和 account。不要把真实 URL、密钥或账户值写入此目录。运行单个只读案例：

```powershell
python cases/C01/run.py --config D:/private-cert/bybit.yaml --evidence-dir D:/certification-evidence/bybit-C01
```

每个 `run.py` 固定绑定其目录名对应的案例，故不接受 `--case` 或 `--all`。批量验收应由调用方逐个启动明确的案例入口并分别保存证据。

写入和高风险案例在示例配置中默认禁用，且三项 policy 授权均为 `false`。启用写入须同时修改私有配置、传入命令行开关，并给出精确确认短语，例如 `bybit:demo:WRITE`；危险操作还需 `--allow-dangerous` 和 `bybit:demo:DANGEROUS`，生产环境另需 `--allow-production-write`。执行前必须核对标的白名单、动作/数量/名义价值上限、参考价偏差、合约规格和清理目标。

只有真实 Bybit 回执、独立查询或订阅事件、账户身份绑定及最终状态全部一致时，案例才可为 `PASS`。脚本启动、配置解析、桥接器自报成功、静态检查、`BLOCKED` 或 `FAILED` 都不代表验收通过。受管 backend 是信任边界，必须单独审查和固定部署；`close` 只允许释放本地传输资源，不得借机撤单、平仓、断开交易场所会话或修改控制状态。

环境变量模板使用 `BT_API_PENETRATION_BYBIT_ENDPOINT`、`BT_API_PENETRATION_BYBIT_TOKEN` 和 `BT_API_PENETRATION_BYBIT_ACCOUNT` 等名称；变量值只在运行时读取并写入前经过脱敏处理。
