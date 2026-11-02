# 迭代 52：`bt-api-runtime 0.1.15` / `bt-api-run-contract 0.1.5` 安装层验收（2026-10-31）

- 仓库/分支：Backtrader `dev` `89d8e8bd5efcca5db2a1c61e32a6568136968255`（本文档不提交）；
  runtime/contract 仓 `dev` `e3dc76270ec64ba56c74e4c2af156fa306333908`（父 `220a24f`，见 §2.3）；
  base 仓 `dev` `afcaf29edda1f0038ed01285c0682c0129294fa1`
- 证据等级：**仅 INSTALLED 层**（冻结 wheel → 独立 venv → 安装消费）。本轮没有对仓库源码跑测试套件，
  没有真实账户、没有 provider 网络 I/O，也没有运行任何 `DirectBacktraderSession.run()`。
- 明确不声称：**不声称 PAPER_ACCOUNT**，不声称 provider 就绪、写授权、结算或场所穿透通过。
  本文所有 `PASS` 都是“离线安装消费/离线诊断”语义，不是账户或交易验收。
- 未读取任何真实 `.env`、私有 `config.yaml`、凭据或账户数据；CLI/消费者脚本只使用本文 §5 的临时 schema-v2 配置。

## 1. 范围与非目标

本轮只回答一件事：**新版本 wheel 在“没有父解释器 site-packages 兜底”的干净环境里能否被正确安装、被正确识别、被正确消费**。

包含：

1. 四个 wheel 的构建、字节尺寸与 SHA-256；构建可重复性（载荷 vs zip 时间戳）。
2. `D:/temp/i52-installed-015/venv`（`include-system-site-packages = false`）安装四个 wheel + 第三方依赖。
3. `pip check`、`pip show`、RECORD 全行哈希复核、distribution/模块 origin 隔离证明。
4. `bt-api-runtime` console script 的 `--version` / `validate` / `doctor`。
5. 安装包内 `DirectBacktraderSession` 的插件门禁（`risk: true` 必须在凭据/传输之前失败）。

非目标（明确不做）：真实账户登录、paper/live 会话运行、SDK/provider 导入、写路径、`PAPER_ACCOUNT` 记账、
旧 runtime 退役判定、dependency-closed 离线 wheelhouse。

## 2. Wheel 构建

### 2.1 构建方式与源

为遵守“不修改仓库源码、仓库内不产生构建产物”，四个包都先用 `git archive HEAD` 导出到
`D:/temp/i52-installed-015/src/`，再在导出副本里构建。仓库工作区未被写入（`build/`、`*.egg-info`、
`__pycache__` 等既有未跟踪目录未被使用，也不是输入）。Backtrader 工作区存在与本任务无关的既存改动
（`M .gitignore`、`M docs/.gitignore` 与若干未跟踪文件），wheel 只包含 `HEAD` 提交内容，不含这些工作区改动。

| 包 | 源（`git archive HEAD` 导出目录） | 构建命令 | 退出码 |
| --- | --- | --- | --- |
| bt-api-run-contract | `src/bt_api_runtime_repo/contracts` | `python -m pip wheel . --no-deps -w <wheelhouse>` | 0 |
| bt-api-runtime | `src/bt_api_runtime_repo/runtime` | 同上 | 0 |
| bt_api_base | `src/bt_api_base_repo` | 同上 | 0 |
| back-trader-python | `src/backtrader`（Backtrader HEAD） | `python -m pip wheel . --no-deps --no-build-isolation -w <wheelhouse>` | 0 |

- 解释器：`C:/anaconda3/python.exe`（CPython 3.11.5，pip 26.0.1）。
- 前三个包使用默认构建隔离（`setuptools>=61`/`wheel` 由 pip 在隔离环境准备）；
  Backtrader 使用 `--no-build-isolation`（基环境 `setuptools 75.8.0` / `wheel 0.43.0`）。
  这是本轮唯一的构建参数差异，记录在此以免被误读为同一构建配方。
- 版本自证：`runtime/pyproject.toml` `version = "0.1.15"`，`contracts/pyproject.toml` `version = "0.1.5"`，
  `bt_api_base/pyproject.toml` `version = "0.15.8"`，`backtrader/version.py` `__version__ = "1.4.0"`。

### 2.2 产物（首次构建，安装所用）

wheelhouse：`D:/temp/i52-installed-015/wheelhouse/`

| Wheel | 字节 | SHA-256 |
| --- | ---: | --- |
| `bt_api_run_contract-0.1.5-py3-none-any.whl` | 15,612 | `be1a719de514716c95995ca17bd5b8325355bbabaa914c87b775a5ab587b2e1b` |
| `bt_api_runtime-0.1.15-py3-none-any.whl` | 38,680 | `49989afbe239f5765f9034742e6ad149b5305479c3aedf35451b467484992a91` |
| `bt_api_base-0.15.8-py3-none-any.whl` | 153,545 | `1704bf997e05fcae16428f43155d35c70b914088985d07ef825d9a5f4b9c16a3` |
| `back_trader_python-1.4.0-py3-none-any.whl` | 2,683,022 | `536e38ef861107135ee2fbcc92d50bf4ec9f9ac72025f937cd8649c7b3c39b42` |

### 2.3 构建可重复性（限制，必须记录）

同一源、同一解释器二次构建到 `wheelhouse-rebuild/`（四个构建退出码均为 0）。结果：

- 四个 wheel 的**成员名集合完全一致，成员内容哈希逐一一致（0 处内容差异）**；
- 但四个 wheel 的**整体 SHA-256 都不相同**（例：runtime 首建 `49989afb…`，重建 `055dd77e…`）。

原因已定位：setuptools/wheel 写入 zip 时携带构建时刻（同包成员 `date_time` 首建 `03:22:14`、重建 `03:30:14`），
载荷字节不变。因此本文的 wheel SHA-256 是**单次构建身份**，不是可复现构建身份；不能把它当作跨机器可复算的
制品指纹，只能当作“本轮安装的确实是这四个文件”的绑定。要跨机器复现需要 `SOURCE_DATE_EPOCH`/固定时间戳策略，
不在本轮范围。

### 2.4 运行时源码与 `220a24f` 的关系

任务给定的 0.1.15 提交是 `220a24f`；导出构建时仓 HEAD 为 `e3dc7627`（`220a24f` 的后继）。
`git diff --stat 220a24f..HEAD` 只有 `runtime/tests/test_direct_isolation.py`（+219 行测试），
`runtime/src/**` 与 `contracts/src/**` 未变化。因此本次 wheel 的**运行时载荷等同于 `220a24f`**，
只是同仓 HEAD 多了未打包的测试文件。导出只取 `HEAD` 提交内容，仓内未提交改动不参与构建（见 §4.4 末段）。

## 3. 隔离安装环境

```text
C:/anaconda3/python.exe -m venv D:/temp/i52-installed-015/venv
```

`venv/pyvenv.cfg`：

```text
home = C:\anaconda3
include-system-site-packages = false
version = 3.11.5
```

venv 内解释器 `Python 3.11.5`，pip `23.2.1`。安装命令（退出码 0）：

```text
D:/temp/i52-installed-015/venv/Scripts/python.exe -m pip install \
  D:/temp/i52-installed-015/wheelhouse/bt_api_run_contract-0.1.5-py3-none-any.whl \
  D:/temp/i52-installed-015/wheelhouse/bt_api_base-0.15.8-py3-none-any.whl \
  D:/temp/i52-installed-015/wheelhouse/back_trader_python-1.4.0-py3-none-any.whl \
  D:/temp/i52-installed-015/wheelhouse/bt_api_runtime-0.1.15-py3-none-any.whl
```

`pip` 记录 `direct_url.json`（`file:///D:/temp/i52-installed-015/wheelhouse/...whl`，`archive_info.hash`
与 §2.2 一致），说明安装来源确实是本轮构建的 wheel，而不是任何索引上的同名包。

### 3.1 依赖来源（网络 vs 本地）

- 第三方依赖**全部来自网络 PyPI**（安装日志：`Downloading` 39 行、`Using cached` 10 行 = 49 个，
  本地路径 `Processing d:\temp` 0 行、本地 `Building wheel for` 0 行）。
- 四个本地 wheel 以文件路径安装；其余 **49** 个 distribution 由 pip 从 PyPI 解析下载，
  **没有**任何依赖由父解释器 `C:\anaconda3\Lib\site-packages` 提供（§3.2 证明）。
- 安装计数自证：`Successfully installed` 共 **53** 项 = 4 个本地 wheel + 49 个 PyPI 包；
  `pip list` 为 **55** 项，多出的 `pip 23.2.1`、`setuptools 65.5.0` 来自 `venv` 引导，不是本轮安装的依赖。
- 因此本轮是“INSTALLED + 网络依赖解析”，**不是**离线 wheelhouse 验收；没有 `--no-index`，也没有冻结
  `constraints`/`requirements` 锁文件。这是本层最大的残余限制。

### 3.2 隔离证明

`tools/verify_isolation.py`（退出码 0）输出要点：

```text
sys_prefix D:\temp\i52-installed-015\venv
purelib D:\temp\i52-installed-015\venv\Lib\site-packages
base_prefix C:\anaconda3
foreign_site_packages_entries []
dist_count 55
dists_outside_venv []
module numpy origin=D:\temp\i52-installed-015\venv\Lib\site-packages\numpy\__init__.py inside_venv=True
module pandas origin=...\venv\Lib\site-packages\pandas\__init__.py inside_venv=True
module yaml origin=...\venv\Lib\site-packages\yaml\__init__.py inside_venv=True
module requests origin=...\venv\Lib\site-packages\requests\__init__.py inside_venv=True
module backtrader origin=...\venv\Lib\site-packages\backtrader\__init__.py inside_venv=True
module bt_api_base origin=...\venv\Lib\site-packages\bt_api_base\__init__.py inside_venv=True
module bt_api_run_contract origin=...\venv\Lib\site-packages\bt_api_run_contract\__init__.py inside_venv=True
module bt_api_runtime origin=...\venv\Lib\site-packages\bt_api_runtime\__init__.py inside_venv=True
module matplotlib / scipy / pydantic origin=...\venv\Lib\site-packages\... inside_venv=True
sys_path_site_packages ['D:\\temp\\i52-installed-015\\venv\\Lib\\site-packages']
```

即：`sys.path` 中只有一个 site-packages（venv 自己的），55 个 distribution 的 `dist-info` 全部位于 venv 内，
11 个关键模块 origin 全部位于 venv 内。**没有任何依赖只由父解释器 site-packages 满足。**

### 3.3 解析到的依赖版本（`pip list`，55 项）

关键版本：`numpy 1.26.4`（Backtrader `numpy<2.0` 上限生效）、`pandas 3.0.6`、`pyarrow 25.0.1`
（base 的 `pyarrow<26` 上限生效）、`PyYAML 6.0.3`、`pydantic 2.14.2`、`requests 2.34.2`、
`websockets 17.4`、`matplotlib 3.11.2`、`scipy 1.17.1`、`statsmodels 0.15.0`、`httpx 0.28.1`、
`aiohttp 3.14.5`、`python-rapidjson 1.25`、`packaging 26.3`、`pytz 2026.6`。

`numpy 1.26.4 + pandas 3.0.6 + pyarrow 25.0.1` 是 pip 在当前索引上组合出的最新可行解（非本轮指定），
说明“依赖上限能约束到可用解”，但也说明依赖面会随索引漂移——与 §3.1 的“无锁文件”限制同源。

## 4. 安装消费证明

### 4.1 `pip show`

| 发行 | 版本 | Location | Requires |
| --- | --- | --- | --- |
| bt-api-runtime | 0.1.15 | `D:\temp\i52-installed-015\venv\Lib\site-packages` | back-trader-python, bt-api-run-contract, bt_api_base |
| bt-api-run-contract | 0.1.5 | 同上 | PyYAML |
| bt_api_base | 0.15.8 | 同上 | aiohttp, httpx, numpy, packaging, pandas, pyarrow, pydantic, python-dotenv, python-rapidjson, pytz, pyyaml, requests, typing-extensions, websocket-client, websockets |
| back-trader-python | 1.4.0 | 同上 | matplotlib, numpy, pandas, pytz, PyYAML, scipy, statsmodels |

声明依赖与 pyproject 一致（`bt-api-runtime` 要求 `back-trader-python>=1.4.0`、`bt-api-run-contract==0.1.5`、
`bt_api_base>=0.15.8`），且 0.1.5 是**精确钉死**，安装到的正是 0.1.5。

### 4.2 `pip check`（退出码 0）

```text
No broken requirements found.
```

### 4.3 RECORD 全行哈希复核

工具 `tools/verify_record.py`（退出码 0）对 `dist-info/RECORD` 每一行做 `sha256`（urlsafe-base64 去填充）
+ 字节数双重校验：

| 发行 | RECORD 行数 | 通过校验（有哈希） | 无哈希行 | 失败 | RECORD 自身 SHA-256 |
| --- | ---: | ---: | ---: | ---: | --- |
| bt-api-runtime 0.1.15 | **21** | **14** | 7 | **0** | `0375ca3c0d85afc63950987a06495ae04c79a7e4caeadcf11bb8a757dd2dbf6f` |
| bt-api-run-contract 0.1.5 | **15** | **10** | 5 | **0** | `f5de608e7d5242a461660f66ddfbf9b9f922c592b948b1d95fc0e1a9becb5496` |

“无哈希行”构成（逐行枚举，非省略）：

- runtime：`bt_api_runtime-0.1.15.dist-info/RECORD`（自引用，标准规定无哈希）+ 6 个 pip 安装期生成的
  `bt_api_runtime/__pycache__/*.cpython-311.pyc`。
- contract：`bt_api_run_contract-0.1.5.dist-info/RECORD` + 4 个 `__pycache__/*.cpython-311.pyc`。

行数可对齐解释：wheel 内 RECORD 为 11（runtime）/ 8（contract）行；pip 安装时重写 RECORD，追加
`INSTALLER`、`REQUESTED`、`direct_url.json`（3 行）与 `../../Scripts/bt-api-runtime.exe`（runtime 独有 1 行），
并为已编译字节码追加 6 / 4 行无哈希 `.pyc` ⇒ 11+3+1+6 = 21、8+3+4 = 15。

补充（同工具，同一标准，退出码 0）：`bt_api_base 0.15.8` 200 行（103 有哈希 / 97 无哈希，其中 96 个 `.pyc`）、
`back-trader-python 1.4.0` 1343 行（678 有哈希 / 665 无哈希，其中 664 个 `.pyc`），两包失败行均为 **0**。

### 4.4 安装文件与提交源码一致（含行尾说明）

对 `bt_api_runtime/*.py`（6 个）与 `bt_api_run_contract/*.py`（4 个）做两步比对：

1. **安装文件 vs `git archive HEAD` 导出文件**：SHA-256 **10/10 完全相同**，例如

```text
MATCH bt_api_runtime/direct_backtrader.py 64b65492daa0782905cde6b9bebf9d5095c6e05e2364e627baab668c4be22eac
MATCH bt_api_runtime/cli.py               27044d9375a4419ee09e523e3f22bc99db8cc146c216c31bbdfa2155d90beba6
MATCH bt_api_run_contract/parser.py       04d5544d4f9426e2d8ee7b92aa774a190ad7334e66f41f5664b5704239f9de26
```

2. **导出文件 vs git blob**：该仓 `core.autocrlf=true` 且无 `.gitattributes`，所以 `git archive` 会把文本文件
   LF→CRLF（`direct_backtrader.py` 946 处 CRLF）。把导出字节 `CRLF→LF` 归一后与 `git show e3dc7627:<path>`
   的 blob 逐字节比较：**10/10 相同**。

结论：安装消费的代码就是提交 `e3dc7627`（运行时载荷等同 `220a24f`）的文本内容，差异只在行尾（LF→CRLF），
不是被修改过的副本。附带提示：此后 runtime 工作区出现本任务之外的未提交 `direct_backtrader.py` 修改与新增测试，
它们**没有**进入本次导出/构建，也不在本 wheel 中。

### 4.5 导入 origin 与惰性边界

```text
runtime_file  D:\temp\i52-installed-015\venv\Lib\site-packages\bt_api_runtime\__init__.py
contract_file D:\temp\i52-installed-015\venv\Lib\site-packages\bt_api_run_contract\__init__.py
runtime_version  0.1.15
contract_version 0.1.5
```

`import bt_api_runtime` 后：`backtrader` / `bt_api_py` / `bt_api_run_contract` 均**未**被加载（`root_lazy_ok True True True`）；
`import bt_api_runtime.cli` 后 `backtrader` / `bt_api_py` 仍未加载（`cli_lazy_ok True True`）。
另外确认重量级依赖在安装环境中可正常导入：`import backtrader` → `1.4.0`（在 `pandas 3.0.6` / `numpy 1.26.4` 上），
`import bt_api_base` 成功。

## 5. 离线 CLI（临时 schema-v2 配置）

临时配置 `D:/temp/i52-installed-015/config/paper_disabled_plugins.yaml`：`schema_version: 2`、`mode: paper`、
`environment: paper`、九个符号引用（`strategy/provider/endpoint/account/credential/scope/product/data_source/clock`，
全部形如 `provider/i52_b4_installed`，无真实场所名）、`plugins` 四个全部 `false`、
`requested_capabilities: market.read + account.read + orders.paper.write`、`strategy_parameters.window: 20`。
文件只存在于 `D:/temp`；本轮未读取任何真实 `.env` 或私有配置。

| 命令 | 退出码 | 关键输出 |
| --- | ---: | --- |
| `venv/Scripts/bt-api-runtime.exe --version` | 0 | `bt-api-runtime 0.1.15` |
| `venv/Scripts/python.exe -m bt_api_runtime --version` | 0 | `bt-api-runtime 0.1.15` |
| `... bt-api-runtime.exe validate --config <tmp>` | 0 | `"status": "PASS"` |
| `... bt-api-runtime.exe doctor --config <tmp>` | 0 | `"status": "PASS_WITH_NOT_CHECKED"` |

`doctor` 的 10 项检查（顺序即输出顺序）：

```text
config_parse PASS | mode PASS | environment PASS | read_capabilities PASS | write_capability PASS
plugins PASS (enabled=[])
topology NOT_CHECKED (topology_not_in_schema_v2)
trusted_registry NOT_CHECKED (trusted_registry_not_supplied)
credentials NOT_CHECKED (offline_command)
network NOT_CHECKED (offline_command)

"not_checked": ["topology", "trusted_registry", "credentials", "network"]
"status": "PASS_WITH_NOT_CHECKED"
```

`validate` 输出同构但**不含** `plugins` 检查（`include_plugins=False` 是 CLI 现有设计），
`plan.references` 只回显符号名与 `strategy_parameters` 类型（`{"window": "int"}`），不输出参数值。

补充负向观察（CLI 侧同一门禁，`config/paper_risk_enabled.yaml` 把 `risk` 置 `true`）：

- `validate --config` → 退出码 0（`validate` 设计上不评估插件）；
- `doctor --config` → 退出码 **2**，`"status": "BLOCKED"`，
  `{"code": "plugin_composition_unavailable", "enabled": ["risk"], "name": "plugins", "status": "BLOCKED"}`。
  这与 §6 的构造期门禁一致：CLI 不会把启用插件的配置当作可装配。

## 6. 安装包消费：`DirectBacktraderSession` 插件门禁

`tools/i52_b4_consumer.py`（退出码 0）只从安装包导入
`DirectBacktraderSession / DirectCredentials / DirectProviderProfile / DirectSessionError / DirectWriteGrant`，
`plan` 由安装包内 `bt_api_run_contract.parse_config` 解析（与 CLI 同一解析器）。

| 用例 | 配置 | 期望 | 实测 |
| --- | --- | --- | --- |
| A | `plugins: runtime: false, risk: false` | 构造成功 | `CONSTRUCTED_OK DirectBacktraderSession`；`factory_calls []` |
| B | `plugins: runtime: false, risk: true` | 抛 `DirectSessionError("plugin_composition_unavailable")` | `DirectSessionError` / `plugin_composition_unavailable` / `code_is_plugin_gate True`；`factory_calls []` |

“凭据/传输之前”的三条直接证据：

1. 用例 B 传入的是**故意无法解析的**凭据集合（`DirectCredentials({"I52_B4_UNRELATED": "placeholder"})`），
   profile 要求的两个字段都不存在；如果门禁在凭据解析之后，错误码会是 `missing_credential_value`。
   实测得到的是 `plugin_composition_unavailable` ⇒ 门禁先于凭据解析。
2. 用例 B 注入的 `store_factory` / `cerebro_factory` 一旦被调用就会 `raise AssertionError`；
   两个用例的 `factory_calls` 都是 `[]` ⇒ 未进入 Store/Cerebro 装配，也就没有 SDK/provider 传输。
3. 进程内已加载模块中，`backtrader`、`bt_api_py`、`bt_api_ctp`、`bt_api_execution`、`requests` **均未加载**；
   探针清单里唯一出现的是 stdlib `socket`（不是 provider/SDK 模块）。

用例 A 只做构造，不调用 `run()/store_config()`，因此本轮没有产生会话、订单、行情或账户读取。

## 7. 命令与退出码汇总

| # | 命令 | 退出码 |
| ---: | --- | ---: |
| 1 | `pip wheel . --no-deps`（contracts） | 0 |
| 2 | `pip wheel . --no-deps`（runtime） | 0 |
| 3 | `pip wheel . --no-deps`（bt_api_base） | 0 |
| 4 | `pip wheel . --no-deps --no-build-isolation`（backtrader） | 0 |
| 5 | `python -m venv D:/temp/i52-installed-015/venv` | 0 |
| 6 | `venv/Scripts/python.exe -m pip install <4 wheels>` | 0 |
| 7 | `venv/Scripts/python.exe -m pip check` | 0 |
| 8 | `venv/Scripts/python.exe -m pip show <4 dists>` | 0 |
| 9 | `venv/Scripts/python.exe tools/verify_record.py <4 dists>` | 0 |
| 10 | `venv/Scripts/python.exe tools/verify_isolation.py` | 0 |
| 11 | `venv/Scripts/python.exe tools/i52_b4_consumer.py` | 0 |
| 12 | `venv/Scripts/bt-api-runtime.exe --version` | 0 |
| 13 | `venv/Scripts/python.exe -m bt_api_runtime --version` | 0 |
| 14 | `venv/Scripts/bt-api-runtime.exe validate --config <paper tmp>` | 0 |
| 15 | `venv/Scripts/bt-api-runtime.exe doctor --config <paper tmp>` | 0 |
| 16 | `venv/Scripts/bt-api-runtime.exe validate --config <risk tmp>` | 0（设计如此） |
| 17 | `venv/Scripts/bt-api-runtime.exe doctor --config <risk tmp>` | 2（`plugin_composition_unavailable`） |

## 8. 残余限制

1. **依赖来自网络**：49 个第三方 distribution 由 PyPI 实时解析（无 `--no-index`、无锁文件、无 constraints）。
   同一份四 wheel 在不同时间可能解析出不同依赖版本（本轮 pandas 3.0.6 / pyarrow 25.0.1 / numpy 1.26.4 即索引当前解）。
   因此本轮是 INSTALLED + 在线依赖解析，**不是** dependency-closed 离线 wheelhouse 验收。
2. **wheel 哈希不可复现**：内容一致但 zip 时间戳不同导致整体 SHA-256 不同（§2.3）。哈希只能绑定“本轮安装的四个文件”。
3. **未验证 `bt_api_py` / provider SDK**：本环境没有把 `bt_api_py`、`bt_api_ctp`、`bt_api_execution` 安装成 distribution，
   也没有导入它们；`bt_api_base` 虽随 wheel 安装，但本轮没有调用其网络/账户能力。
4. **未运行会话**：`DirectBacktraderSession` 只验证到“构造 + 门禁”，`run()`、真实 Store/Broker、订单、账户读取、
   `PAPER_ACCOUNT` 记账全部未执行、也未声称。
5. **RECORD 中的 `.pyc` 行无哈希**：pip 安装期编译产物按标准以空哈希记录，本文按“无哈希行”如实计数，
   未把它们算作“通过校验”。同样，`RECORD` 自引用行按标准无哈希。
6. **CLI 语义**：`PASS_WITH_NOT_CHECKED` 只表示“离线配置结构与能力声明通过，且明确列出未覆盖项”，
   `not_checked` 中的 topology / trusted_registry / credentials / network **仍是未覆盖**，不是“通过”。
7. **`validate` 不评估插件**：启用插件的配置在 `validate` 下仍返回 PASS（CLI 现状），门禁在 `doctor` 与构造期；
   这一不对称已在 §5 记录，未在本轮修改代码。

## 9. 本轮结论（安装层）

- `bt-api-run-contract 0.1.5`、`bt-api-runtime 0.1.15`、`bt_api_base 0.15.8`、`back-trader-python 1.4.0`
  四个 wheel 在 `include-system-site-packages = false` 的独立 venv 中安装成功，`pip check` 干净，
  55 个 distribution 全部位于 venv，无父解释器 site-packages 参与。
- `bt-api-runtime` / `bt-api-run-contract` 的 RECORD 全行复核为 21/15 行、失败 0；安装源码字节与提交一致（10/10）。
- console script 报 `0.1.15`；`validate`/`doctor` 均退出 0，`doctor` 为 `PASS_WITH_NOT_CHECKED`
  且四项 `not_checked` 与预期完全一致。
- 安装包内 `DirectBacktraderSession` 在 `risk: true` 时以 `plugin_composition_unavailable` 在凭据与传输之前失败；
  `runtime: false` 时可正常构造；两者都没有触达 Store/Cerebro/SDK/provider。
- **F18 安装层：本切片 PASS（在线依赖解析前提下的 INSTALLED 层）**；`PAPER_ACCOUNT`、provider 就绪、
  写授权、旧 runtime 退役仍不成立。

## 10. 复现材料位置（均在 `D:/temp`，不入库）

| 路径 | SHA-256 |
| --- | --- |
| `D:/temp/i52-installed-015/wheelhouse/*.whl` | 见 §2.2 |
| `D:/temp/i52-installed-015/config/paper_disabled_plugins.yaml` | 587 字节（内容见 §5） |
| `D:/temp/i52-installed-015/config/paper_risk_enabled.yaml` | 586 字节（`risk: true` 变体） |
| `D:/temp/i52-installed-015/tools/verify_record.py` | RECORD 全行校验器 |
| `D:/temp/i52-installed-015/tools/verify_isolation.py` | venv 隔离证明 |
| `D:/temp/i52-installed-015/tools/i52_b4_consumer.py` | 插件门禁消费者探针 |
| `D:/temp/i52-installed-015/logs/install.log` | `715b06dd29ccef40b4544b996aec247b57f7c752663715f42092b46c53c17ca9` |
| `D:/temp/i52-installed-015/logs/pip-check.log` | `672aec65a45bed50e70229c70934a7eebf0462595c459b83023027645d57cccf` |
| `D:/temp/i52-installed-015/logs/pip-show.log` | `644a967c83a93023d1862c540b299fa57858cc69908e7d66961d92c5f846f430` |
| `D:/temp/i52-installed-015/logs/pip-list.log` | `bafe9d8fbda8b38b239bebe6398e12556896fa103db9b36ee7c2b1344f52dcf9` |
| `D:/temp/i52-installed-015/logs/record-check.log` | `3168e515f2b27ff6c45edb5ea77f1bb919ae72086c0cb1d88eeb2e89b9f39454` |
| `D:/temp/i52-installed-015/logs/isolation.log` | `31a89d5e4c755a4757f636736a496c9fb7aa96de68eae3d9c05c69b34e275ed0` |
| `D:/temp/i52-installed-015/logs/consumer.log` | `810db8ee71ac56cf4d6abcb17ad4887f55089143c194eabdf8b822e252255258` |
| `D:/temp/i52-installed-015/logs/cli-version.log` | `f23f5d9f8c51e7ebbac7d1a7ce02f8158001d6b85088d4f0cb33560372c742b2` |
| `D:/temp/i52-installed-015/logs/cli-validate.log` | `1d9812d86400d706ee8c8cb11ce41fbfa7d9793decb4d0fb9928eba5da52af82` |
| `D:/temp/i52-installed-015/logs/cli-doctor.log` | `79dd915887978095c0e15e98cf3d3a2433508be4e7219bed58b95a4fb04eb715` |
| `D:/temp/i52-installed-015/logs/cli-validate-risk.log` | `d0091239c4874d9830dce9d8bf0de4030a2a7433fc380f44ba13d45be56ca9d3` |
| `D:/temp/i52-installed-015/logs/cli-doctor-risk.log` | `6cd5db2fbeb50383a98891b81e93134939ab351b85976e0abefc337c3d6c2131` |

未提交任何代码；未修改任何仓库源文件；仓库内未产生构建产物。

仓库约定提示：根 `.gitignore` 第 174–177 行明确说明 `evidence/` 下的新文件默认被忽略、入库需 `git add -f`，
因此本文件当前是磁盘上的未跟踪（忽略）文件；本轮按要求**不执行** `git add -f`，也不提交。
