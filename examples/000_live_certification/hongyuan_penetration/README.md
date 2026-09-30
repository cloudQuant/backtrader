# 穿透式验收用例

每个用例目录只保留 `<ID>_strategy.py` 和 `run.py`；全部用例共用本目录的 `config.yaml`。配置文件含账户资料时由 Git 忽略，不要提交凭据。

```text
config.yaml
cases/<ID>/<ID>_strategy.py
cases/<ID>/run.py
```

在本目录执行 `python cases/C01/run.py` 会以本地 BackBroker 和内存行情运行 Cerebro，检查策略是否能启动并处理数据。输出中的 `case_observed` 仅表示本地观察结果；`certification` 始终是 `BLOCKED`，不能算作 SimNow 或宏源柜台验收通过。

`python cases/C01/run.py --live` 在导入交易 SDK 前返回 `BLOCKED`。当前没有已注册的受管认证运行器，无法从这些入口登录柜台或报撤单。

宏源账户资料保存在仓库根目录受 Git 忽略的 `.env` 中：`HONGYUAN_USER_ID`、`HONGYUAN_PASSWORD`、`HONGYUAN_APP_ID`、`HONGYUAN_AUTH_CODE`，另以 `HONGYUAN_USER_PRODUCT_INFO` 和 `HONGYUAN_CONNECTION_MODE` 记录产品信息与直连方式。当前 `run.py` 不会自动加载 `.env`，后两个字段也未接入运行器。
