# 52-F06 / F20 live 配置与权限隔离边界（2026-10-31）

状态：**PASS（LIVE-BOUNDARY）**。本证据只覆盖 production 绑定配置的解析、账户/凭据/引用隔离和未授权拒绝；没有任何生产账户连接、凭据或写入。

## 1. 交付

| 文件 | 作用 |
| --- | --- |
| `examples/unified/052_provider_demo_roundtrip/config.live.yaml` | production 绑定模板：`mode/environment: live`，provider/endpoint/account/credential/scope 与 Demo 全部分离，凭据只给变量名（`BINANCE_PROD_*`），写能力声明为 `orders.live.write` |
| `examples/unified/052_provider_demo_roundtrip/run.py` | 凭据引用由配置的 `credential_*_env` 决定；live 使用 production profile 且不共享 Demo ledger；grant 的 `allow_live_write` 固定为 false |
| `tests/unit/test_iteration52_live_boundary.py` | 4 项边界合同测试 |

## 2. 实测命令与结果

解释器：`C:/anaconda3/python.exe`（3.11.5），工作目录为示例目录。

```
python run.py --config config.live.yaml --live
# exit 2, BLOCKED, reason=write_not_authorized

python run.py --config config.live.yaml --live --allow-write \
  --env-file <仅含 BINANCE_DEMO_* 的临时文件>
# exit 2, BLOCKED, reason=credentials_unavailable

python run.py --config config.live.yaml --live --allow-write \
  --env-file <仅含 BINANCE_PROD_* 假值的临时文件>
# exit 1, FAILED, reason=live_write_not_authorized
# started=false / store_started=false / broker_started=false
```

三条路径分别证明：未显式授予写权限时在读取凭据前拒绝；演示凭据名不能流入 production 配置；即使 production 变量名解析成功，缺少 live 写授权时仍在 Store/Broker/传输之前拒绝。没有读取 checkout `.env`，没有网络或 provider 调用，没有任何订单。

证据 JSON（示例目录 `evidence/`，git-ignored）：

| 文件 | SHA-256 |
| --- | --- |
| `20261031T032820Z_052_binance_demo_roundtrip_BLOCKED.json` | `882452edebf3bc3fdf89880d90d22d337554ed878dd41f941711167c9c886378` |
| `20261031T032821Z_052_binance_demo_roundtrip_BLOCKED.json` | `332ced6dfccbfff06c439253f2482ebb5cae4d77846756e17b6a87a2765f6f73` |
| `20261031T032822Z_052_binance_demo_roundtrip_FAILED.json` | `1c13972e89d4b5f1b8f8c279d9cff62f53416301eb28d1a36ba08c4a256e3d79` |

## 3. 测试

```
python -m pytest tests/unit/test_iteration52_live_boundary.py -q -p no:asyncio
# 4 passed
```

覆盖：两个模板的引用/凭据/能力互斥；无写授权在凭据前拒绝；demo 凭据名不能用于 live；production 凭据名解析后仍被 live 写授权拒绝且无启动；证据不含凭据值。

注：仓库现有 `pytest-asyncio` 插件与当前 pytest 组合在收集包级节点时会报 `'Package' object has no attribute 'obj'`，本组测试使用 `-p no:asyncio`；该环境问题与本次改动无关。

## 4. 边界

- 未提供、未读取、未连接任何生产账户；production 写仍未授权。
- `config.live.yaml` 只是安全边界模板，不是可执行生产运行配置；真正生产准入需要独立 permit/凭据与独立授权（F14 仍未闭合）。
- 运行时 grant 目前只是调用方注入的有界声明，没有可信 issuer 签名；该限制不因本证据改变。
