# AC41-63 受控 writer 路径独立审查（10/389 切片）

日期：2026-09-27。范围是冻结的静态候选 inventory、默认 runtime 注册，以及 Store/gateway/CLI 的一个 10 项高风险切片。该报告是路径收敛证据，不构成 389 项关闭、账户准入、G4/F14/生产接受或 CTP 写入许可。

## 冻结输入与复现

- 静态输入来自 `iteration41-writer-inventory-independent-qa-20260927` 的冻结 source manifest，SHA-256 `423CB56E86375019307D252AD774706A259161D7D4EF7B605410EDB0FC889FC6`。
- 候选 JSON SHA `FACBBC93067D77A317E3A0ABDE5EF89BC77BD53E4A4EB18722B51124E3E20780`；disposition JSON SHA `95116E8866A50D645664764856F1CEB6E855B3D05E540F7E38D59F30EA65C7FD`。输入副本和 `verify_inputs.py` 在本目录 `input/` 与根目录。
- 计数复核：349 个 Python 文件、327 个 writer 候选、62 个 dynamic 候选、0 parse error、389 条 disposition；全部仍为 `REVIEW_REQUIRED / NOT_AVAILABLE`，总体 `NOT_CLOSED_STATIC_REVIEW_REQUIRED`。本次审查其中 10 条，余下 **379 条没有审查**。
- 主树基线文件 SHA：`inventory.py` `0EBC77EFD22E21B299E794E09C8CB879899B5DC4EFD3302E86D2D9C626B0F6CB`，`cli.py` `BCA2632E261FE2B663008E8B0758C2C932DF917F9376E9B90230848B41EF5EF4`，`runner.py` `F80C4DE5C8E981F73B2C05930BB5F772F631099CE3A8291AF94E7BAC0DCB6AFD`，Store `btapistore.py` `DBA2989252DB76FE010FBEE7CAACDCDBA34A9B951E3702724156482B67FAE826`，`managed_execution.py` `1C31F89412E8E1177EB2E27389C62B50E074361EF808098846C06704F18440C5`。
- Store 方法 fake 探针从上述冻结文件 AST 中直接编译目标函数；它将底层 delegate 替换为立即抛出 `BaseException` 的 inert fake，并在 fake call boundary 停止。它不是完整 Store 构造生命周期或 provider 可达性模拟。运行脚本 `run_slice_probe.py`，主树 stdout `main-probe.log`，r2a stdout `r2a-probe.log`。
- 所有 environment probe 都使用合成 Mapping；未读取系统环境、私有配置、凭据、账号或 runtime config。没有导入 CTP/native、真实 bt_api_py、连接网络或执行真实 submit/cancel。

## 默认注册 CLI 与直接 Python API

默认 `inventory.py` 中 013_3 CTP private 注册只有 `simulation/sandbox`、无 capabilities、`runner_module=None`、`sandbox_write_policy="deny"`；`live/managed_live_direct` 标为 unavailable。

默认 CTP private `preflight` 的惰性负测返回 exit 2 和 `ctp_simnow_preflight_supervisor_required`。`validate_runtime_config` 与 provider-preflight dispatcher 均设为 fail trap，未触发；对该 runtime 目录的 config 打开拦截为 0 次；SDK 模块加载数为 0。`runner.dispatch_registered_runtime` 的 live-profile 与 unavailable-sandbox 两个 inert EffectiveConfig 负测都在读取 `profile.runner_module`/导入 runner 前拒绝。

范围要区分：`run` 分支先在 `cli.py:1523` 调用 `validate_runtime_config`，再在 `1524` 检查 profile dispatch。因而 `preflight` 的“配置未读取”结果不应推广到所有 CLI 子命令；`run` 可读取 YAML 后拒绝，但仍未到 runner/provider dispatch。

同一代码的公开 Python Store API 是另一条边界。本次从冻结 Store AST 执行了公开 `submit_order/cancel_order` 和私有 `_submit_order_legacy/_cancel_order_ref_legacy` 四条方法链；四条均进入 inert fake API delegate 并在调用首行停止。主树 `submit_order` 在 adapter 为 `None` 时直接转入 legacy dispatcher (`btapistore.py:7714-25`)；legacy submit/cancel 的 CTP 阻断只适用于“已挂 managed adapter”的情况 (`7913-16`, `8221-24`)，无 adapter 路径继续 `_ensure_api_ready` 并调用 `api.submit_order/cancel_order` (`7906-43`, `8219-49`)。因此，默认 CLI route 当前 fail-closed，**不等于公共 Python Store API 已全局 fail-closed**。

Store 构造源码顺序也不是“先 CTP gate 再读取一切”：`_resolve_provider` 读 `BT_STORE_PROVIDER` (`3768-72`)，generic `require_managed_execution_adapter` 读取调用方 `submit_order` 属性 (`3502`; helper `managed_execution.py:801-08`)，后续读取 CTP authorization config/environment 名称 (`3513-23`) 和 `api.exchange_kwargs` (`3537-39`)，再执行 CTP typed-adapter gate (`3541-45`)。直接 Python API 可传入属性有副作用的对象；默认 CLI 注册不从配置构造此类任意 Python 对象。此项是按精确源码顺序静态审查；探针没有读取实际 credential/env 值。

合成 environment 路径用主树原 AST 复现：调用方 `provider="ctp"`，合成 `BT_STORE_PROVIDER=okx_gateway` 与 `BT_GATEWAY_EXCHANGE_TYPE=BINANCE`，解析结果为 gateway/non-CTP。没有构造 client 或触发 writer。这只证明直接 Python Store 的路由标识可被环境改写；它不证明向 CTP 发单，也不属于默认 CLI CTP 路由。`BT_STORE_PROVIDER=ctp_gateway` 配 CTP exchange 仍会按 CTP 分类，别将所有 gateway override 统称为绕过。

## 10 条 inventory 候选逐项结论

| ID / 源码点 | 探针证据 | 当前结论 |
|---|---|---|
| `i41-writer-6b64c967597ca9a30e13` — `btapistore.py:7938` legacy `api.submit_order` | 冻结 AST；公开与私有方法两条 fake 边界均到达 | 主树直接 Python API 的无 adapter CTP legacy writer 未在方法内全局关闭；默认注册 CLI 不到达它 |
| `i41-writer-ed12303a6c97d433f979` — `btapistore.py:8245` legacy `api.cancel_order` | 同上，fake cancel trap | 同上；私有 helper 可直接调用 |
| `i41-writer-e25ef08c3d066b243298` — `btapistore.py:3327` gateway wrapper submit delegate | 冻结 AST，fake client trap | wrapper 方法本身没有 actor/route recheck；需要调用链所有者界定谁持有该 wrapper |
| `i41-writer-8f9ca48eab400d71e549` — `btapistore.py:3341` wrapper `create_order → submit_order` | 冻结 AST，fake submit trap | 同一直接 delegate 面；主树/r2a 均无 wrapper 内 gate |
| `i41-writer-8739a8fd4212eca086b0` — `btapistore.py:3353` gateway wrapper cancel delegate | 冻结 AST，fake cancel trap | wrapper 方法本身无 route/auth gate；未接真实 gateway |
| `i41-writer-f8f51de9f2f4a3fdf72c` — `btapistore.py:7735` managed adapter submit | 静态候选；本轮未调用 arbitrary adapter | 在非 CTP managed 分支调用 adapter；CTP 分支走 typed CTP adapter。注入对象可执行属性/方法，默认 CLI 不传 Python 对象；具体 adapter authority 未在本切片接受 |
| `i41-writer-b71354cccd4aa34361ee` — `btapistore.py:1764` lazy `bt_api_py` import | 冻结函数 AST，importlib trap 收到唯一请求 `bt_api_py` 并在载入前拒绝 | import 被 `_ensure_api_ready` 路径按需触发；主树无 adapter legacy CTP 路径可进入。真实 SDK 未加载 |
| `i41-writer-fbe05d71d70ed65a9838` — `btapistore.py:1935` typed native-method reflection | 静态候选；未实例化 native wrapper | 当 typed method+capability 不可用时源码回退到 `trader_client.api.ReqOrderInsert` (`1935-41`)；SDK build 内部 fail-closed 行为未独立核实，保留未解决 |
| `i41-writer-174e9667065d97aae5dd` — `runner.py:1144` dynamic import | 默认 dispatcher live/unavailable 两个 fake policy cases 均拒绝，import trap 0 次 | 只证明受 `dispatch_registered_runtime` 保护的默认 runner 路径；私有 helper 单独调用/其它注册场景未覆盖 |
| `i41-writer-7d767677b3f095e8da32` — `runner.py:1081` `exec(code, module.__dict__)` | 静态定位；默认 CTP live/unavailable gate 不到达该 loader | 上下文有 `_read_trusted_runner_source`、来源路径检查后才 exec (`1048-81`)；仅表明候选执行边界处于 reviewed runner loader，未做本轮运行时来源链审计 |

CLI private preflight gate 是上述 10 条之外的 default-route 审查点，不计入 389 的切片分子。

## r2a 只读复核（补充）

r2a manifest sidecar/hash一致，完整 `verify_manifest.py` 输出 `VERIFIED_PAYLOADS=679 / MANIFEST_AND_PAYLOADS_PASS`。r2a Store SHA `18A02F00EC3B2031932284C9E855395C1C70C3E448DBAFCD054E4F079048C4D0`；manifest SHA `5AD9CCE0851FBEBD9AC07D520919B7A02F793AB99A133CF96E91F58CEDE405FB`；two-file patch SHA `7708DF2F0923B74E5F95315390580EB417E9CA05CFA4C6FE41422BC410908E99`。

实际调用 r2a `BtApiStore(provider="ctp", api/api_cls/config/adapter=object-trap, autostart=True)` 在 constructor 第一处显式 provider gate 返回 `external account actor unavailable`；env trap 和每个 caller-object trap 均零读取。这与其 `btapistore.py:3678-80` 一致。

在携带 actor-only marker 的惰性最小 shell 上，从 r2a AST 直接执行 `_submit_order_legacy`、`_cancel_order_ref_legacy`、`_submit_ctp_managed_order`、`_cancel_managed`，四条均在函数开头拒绝、fake API call 为 0 (`8338-50`, `8679-87`, `8195-99`, `8527-32`)。这不是一条构造成功的 actor 生命周期测试；作者已有的 route/focus 套件是不同证据。

r2a 的 `CtpGatewayClientWrapper` 仍由三个方法直接委托 client (`3496`, `3510`, `3522`)。本轮从 r2a 冻结 AST 调用这三方法均命中 fake client；wrapper 不携带 Store 的 actor-only route recheck。因此 **r2a Store actor route 内部 helper 已加 gate，不代表独立 gateway wrapper 的 public Python delegate 已封闭**。r2b wrapper 修订当前状态不在本次审查范围内，也不据此给出 r2b 结论。

## 裁决与限制

default registered CTP CLI 的 `preflight` 边界在本切片中 fail-closed；direct `BtApiStore`/gateway Python object surfaces 仍有未关闭的直接调用边，不能由 default CLI 负测推导为不可达。r2a 显式 CTP constructor 与 actor-only Store 内部方法门槛在惰性复核中工作，但独立 gateway wrapper 仍委托。

这只是候选路径收敛证据。所有 389 disposition 保持 review-required；本报告只审查 10 条候选及一个额外 CLI gate。原生反射/SDK fallback、所有 adapter composition、其余 379 条 candidate、完整进程运行轨迹、F14、账户/provider 路由和生产行为均未验证。默认 CTP write route 仍 CLOSED。
