# 迭代 52：离线 validate/doctor CLI 与 0.1.14 安装消费（2026-10-31）

- 仓库/分支：Backtrader `dev`（本记录提交）；runtime 子仓 `dev` `b78d2f4`；SDK 父仓 `dev` `b20f2c95`
- 证据等级：SOURCE + INSTALLED（runtime 0.1.14/contract 0.1.5/Backtrader/base wheel 安装消费）
- 不改变：`validate/doctor` 不是运行模式、不授予运行或写权限；生产写入未授权；SimNow 未验收；旧 runtime 未退役

## 1. CLI 交付

`bt_api_runtime.cli`（0.1.14，`bt-api-runtime` console script + `python -m bt_api_runtime`）：

```text
bt-api-runtime validate --config <config.yaml>
bt-api-runtime doctor   --config <config.yaml>
bt-api-runtime --version
```

- 唯一解析入口仍是 `bt_api_run_contract` schema-v2 parser；不做第二套 YAML。
- `validate`：输出 `status/plan/checks` JSON；包含 mode/environment、九个符号引用、插件开关、请求能力、策略参数 **名与类型**（不输出值）；配置非法/缺失/schema 非 v2/延期模式 → exit 2 和有限 code。
- `doctor`：额外检查 enabled plugins；任何 enabled 插件 → `BLOCKED / plugin_composition_unavailable`；未覆盖项明确列入 `not_checked`（topology、trusted registry、credentials、network），总体状态为 `PASS_WITH_NOT_CHECKED`，不冒充装配或账户就绪。
- 导入边界：`import bt_api_runtime.cli` 不加载 Backtrader、`bt_api_py`、provider；不读凭据、不联网、不读私有配置。
- 不新增运行模式；`doctor` 输出不是 permit、不是写授权。

## 2. 测试

| 层 | 命令/范围 | 结果 |
| --- | --- | --- |
| CLI source | `runtime/tests/test_cli.py` | **5 passed**（paper 通过、重复键/延期模式阻断、doctor not_checked、enabled plugin 阻断、惰性导入） |
| Runtime source | `runtime/tests` | **163 passed**（含 direct session 11 + CLI 5） |
| Contract installed | `contracts/tests`（`-o pythonpath=`） | **57 passed** |
| Direct session installed | `runtime/tests/test_direct_backtrader.py`（安装包） | **11 passed** |
| Installed CLI | `bt-api-runtime validate/doctor --config .../052_provider_demo_roundtrip/config.yaml` | validate exit 0；doctor `PASS_WITH_NOT_CHECKED`、exit 0 |

## 3. 0.1.14 安装证据

- Wheel：`bt_api_runtime-0.1.14-py3-none-any.whl`，SHA-256
  `0b0a1fd264d7d111da72485ae4b0c8dea473fc3bb1aef640b32e8441573f58d6`
- 环境：`D:/temp/i52-installed`（Python 3.11.5，`--system-site-packages`；未使用仓内 runtime/contract 源码）。
- `bt-api-runtime 0.1.14` 安装于 venv site-packages；RECORD **13 行全部匹配**，3/3 依赖满足；`bt-api-run-contract 0.1.5` RECORD 9 行匹配；Backtrader 742 行、base 118 行匹配。
- 安装 origin 与惰性导入：runtime/contract 指向 venv；import runtime 后 backtrader/bt_api_py 均未加载。
- 边界：依赖闭包复用系统 site-packages，不是完全离线 wheelhouse；SDK 未安装为 distribution。

## 4. 状态与下一步

- F01/F03：CLI 诊断与 `not_checked` 输出已交付；topology/permissions/run identity/schema v3、trusted registry 和 permit 仍未实现，保持 PARTIAL。
- F18：0.1.14 安装消费证据已补齐；旧 runtime 退役仍 BLOCKED。
- 下一优先：A0 未闭合项收敛；随后 SimNow registered-sim 适配（F20 第三场所）或 028 迁移。
