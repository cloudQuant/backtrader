# 穿透式验收用例

每个用例目录只保留 `<ID>_strategy.py` 和 `run.py`；全部用例共用本目录的 `config.yaml`。配置文件含账户资料时由 Git 忽略，不要提交凭据。

```text
config.yaml
cases/<ID>/<ID>_strategy.py
cases/<ID>/run.py
```

在本目录执行 `python cases/C01/run.py` 会以本地 BackBroker 和内存行情运行 Cerebro，检查策略是否能启动并处理数据。输出中的 `case_observed` 仅表示本地观察结果；`certification` 始终是 `BLOCKED`，不能算作 SimNow 或宏源柜台验收通过。

`python cases/C01/run.py --live` 在导入交易 SDK 前返回 `BLOCKED`。当前没有已注册的受管认证运行器，无法从这些入口登录柜台或报撤单。

新增只读准入检查，在仓库根目录执行：

```powershell
python examples/000_live_certification/simnow_penetration/preflight.py
python examples/000_live_certification/simnow_penetration/preflight.py --profile set1_group1
```

检查只输出 `.env` 中七个 `CTP_*` 账户/前置变量的存在状态、显式选择的前置配对检查、当前运行时注册状态及已安装 SDK 版本/文件身份检查；不会输出变量值或将 `.env` 加入进程环境。`.env` 必须受 Git 忽略且未跟踪，并且是大小受限的普通文件。`--profile` 可选 `set1_group1`、`set1_group2`、`set2_7x24`，用于比对当前源码中的历史配对表；这不是对最新官方地址或未来可达性的证明。未选择时返回 `explicit_simnow_profile_required`，不会自动选取其他前置。

此 000 套件没有代码注册，因此检查会报告 `suite_not_registered`，并在读取私有 `config.yaml` 前停止配置检查。SDK 文件检查使用当前源码已注册只读路径的精确 pin，不能用版本号代替 wheel/RECORD 校验，也不授权任何实验候选。检查不会导入交易 SDK、加载原生库、联网、登录、订阅或报撤单。全部结果始终为 `BLOCKED`，退出码 2，`NO_WRITE / LIVE_NO_GO`，真实通过用例为 0；通过本地存在性或文件检查不能计作 33 个真实用例通过。

宏源账户资料保存在仓库根目录受 Git 忽略的 `.env` 中：`HONGYUAN_USER_ID`、`HONGYUAN_PASSWORD`、`HONGYUAN_APP_ID`、`HONGYUAN_AUTH_CODE`，另以 `HONGYUAN_USER_PRODUCT_INFO` 和 `HONGYUAN_CONNECTION_MODE` 记录产品信息与直连方式。当前 `run.py` 不会自动加载 `.env`，后两个字段也未接入运行器。
