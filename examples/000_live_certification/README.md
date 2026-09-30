# 交易场所穿透式在线认证

本目录按“一个交易场所一个完整套件”组织。13 个新增交易场所都采用与 `simnow_penetration` 相同的逐案例外形：`cases/<ID>/<ID>_strategy.py` 保存该案例的动作、风险和证据合同，`cases/<ID>/run.py` 只运行该 ID。每个交易所目录还内置自己的 `_certification` 严格 live 运行时，不引用本目录根部或其他交易所目录中的共享代码，整目录复制出去仍可使用。

既有 `simnow_penetration` 和 `hongyuan_penetration` 保持原状。新增套件没有离线 smoke、模拟行情或本地 `BackBroker` 认证模式，也不会把静态检查换算成真实场所结论。

## 交易场所目录

本轮 Binance USDⓈ-M、OKX SWAP 和 SimNow 的开发/验收范围及 99 案例前置条件见
[迭代 41 三场所计划](../../docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/000三场所模拟穿透开发与验收.md)。
三套件新增的只读/离线预检入口分别在各自 README 中说明；预检不替代下文的
严格案例运行时，目前没有任何真实案例 `PASS`。

| 交易场所 | 套件说明 | 示例单案入口 |
| --- | --- | --- |
| OKX | [okx_penetration](okx_penetration/README.md) | [C01](okx_penetration/cases/C01/run.py) |
| Binance | [binance_penetration](binance_penetration/README.md) | [C01](binance_penetration/cases/C01/run.py) |
| Bitget | [bitget_penetration](bitget_penetration/README.md) | [C01](bitget_penetration/cases/C01/run.py) |
| Bybit | [bybit_penetration](bybit_penetration/README.md) | [C01](bybit_penetration/cases/C01/run.py) |
| Coinbase | [coinbase_penetration](coinbase_penetration/README.md) | [C01](coinbase_penetration/cases/C01/run.py) |
| dYdX | [dydx_penetration](dydx_penetration/README.md) | [C01](dydx_penetration/cases/C01/run.py) |
| Gate.io | [gateio_penetration](gateio_penetration/README.md) | [C01](gateio_penetration/cases/C01/run.py) |
| HTX | [htx_penetration](htx_penetration/README.md) | [C01](htx_penetration/cases/C01/run.py) |
| Hyperliquid | [hyperliquid_penetration](hyperliquid_penetration/README.md) | [C01](hyperliquid_penetration/cases/C01/run.py) |
| IB Web | [ib_web_penetration](ib_web_penetration/README.md) | [C01](ib_web_penetration/cases/C01/run.py) |
| MT5 | [mt5_penetration](mt5_penetration/README.md) | [C01](mt5_penetration/cases/C01/run.py) |
| Kraken | [kraken_penetration](kraken_penetration/README.md) | [C01](kraken_penetration/cases/C01/run.py) |
| MEXC | [mexc_penetration](mexc_penetration/README.md) | [C01](mexc_penetration/cases/C01/run.py) |

每套目录结构如下：

```text
<venue>_penetration/
  README.md
  config.example.yaml
  _certification/
    backends.py
    cases.py
    cli.py
    config.py
    evidence.py
    models.py
    runner.py
  cases/
    B01/B01_strategy.py + run.py
    ...
    V03/V03_strategy.py + run.py
```

`_certification` 是套件内置实现，不是跨目录依赖。它负责 schema v2 配置、命令行双重授权、runner 预先展开的逐笔操作、账户/环境 attestation、真实回执、独立事件、不确定派发的 reconcile、完整订单/持仓/余额/成交/账本快照、精确清理白名单、最终状态对账以及脱敏哈希证据链。

## 运行单个案例

先将对应目录的 `config.example.yaml` 复制到仓库外私有路径，替换非敏感占位符，并通过环境变量提供真实 endpoint、token 和 account。每个入口已固定自己的案例 ID，不接受 `--case` 或 `--all`：

```powershell
cd examples/000_live_certification/okx_penetration
python cases/C01/run.py `
  --config D:/private-cert/okx.yaml `
  --evidence-dir D:/certification-evidence/okx-C01
```

调用方如需多个案例，应逐个运行明确入口并分别保存证据。READ 案例只读取已有的真实外部证据；WRITE/DANGEROUS 案例仅能执行预先固化且受数量、价格、标的、目标和累计预算约束的动作。示例配置默认禁用全部写入和危险案例，并关闭 `allow_write`、`allow_dangerous`、`allow_production_write`。

开启写入还需相应命令行开关及精确短语：

```text
<venue>:<environment>:WRITE
<venue>:<environment>:DANGEROUS
<venue>:<environment>:PRODUCTION_WRITE
<venue>:<environment>:PRODUCTION_DANGEROUS
```

## PASS 边界

当前目录不包含已受审并部署的交易场所 adapter，也没有任何 live 结果。缺少 backend、凭证、账户绑定、产品规格、参考价、独立事件、完整分页快照或可靠 cleanup 时必须为 `BLOCKED`；不一致或残留风险为 `FAILED`。只有真实场所回执、独立查询/订阅证据、身份绑定和最终对账全部成立，案例才可判为 `PASS`。

若提供方违反 client order ID 唯一性、为同一个 runner ID 创建多笔远程订单，脚本不会擅自扩大原计划的撤单权限；案例会 `FAILED`，证据会保留异常和最终快照，残留订单必须由人工按交易场所原始记录处置。

HTTPS 桥和 Python factory 都是信任边界；字段齐全不能抵抗恶意 backend 伪造整套证据。实际使用前必须独立审查并固定部署 adapter。`close_semantics=local_transport_only`：关闭运行器只能释放本地资源，不得借机撤单、平仓、断开交易场所会话或修改权限、阈值等控制状态。
