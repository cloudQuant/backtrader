# I13 / I15 外层父进程信任根与一次性只读诊断设计（2026-09-25）

状态：**PARTIAL_OFFLINE_SOURCE_GATE / OUTER_LAUNCHER_NOT_IMPLEMENTED / NO_WRITE / LIVE_NO_GO**。本页定义 I13 MD-only 与 I15 TD-only 一次性诊断的外层启动与验收边界；未登记的 `scripts/ctp_i13_i15_sealed_import.py` 已把 Windows file-ID lease 接入离线 manifest seal 和 source loader，但未接候选 supervisor 或 operator 入口。定向测试仅用临时假源树，没有打开真实配置、marker、SDK、网络或 provider。现有 I13/I15 候选均不得因本页而启动。

## 设计结论

两种诊断共用一个 stdlib-only 父进程 launcher 和相同的信任建立次序。入口必须直接运行一个独立审阅并部署在仓库外的 launcher，通过固定的 CPython 3.11.5 no-system venv 解释器，以 **-I -S -B -X pycache_prefix=unique-absent-absolute-path** 启动；该 prefix 必须在启动前不存在，并位于受管理员/部署 ACL 控制、非信任主体不可写的临时父目录下。launcher 在导入任何 **backtrader_runtime** 前，仅用标准库读取外部锚定的源清单摘要、检查完整 Python 源闭包、当前进程 import 状态与解释器路径；检查通过后先安装严格的 source-only finder，再加载受 sealed source 保护的候选 supervisor。顺序固定为：

**launcher 信任根与解释器 → 源清单核验 → Windows source/artifact lease → PyYAML 精确制品核验 → sealed config / credential-free front precheck → metadata-only Job → 对应候选独立 marker → 候选 worker Job → 关闭、收拢与 value-free receipt**

任何一个前置门槛失败都不得触碰候选 marker；metadata-only Job 失败也不得读取或预留 marker。marker 成功预留之后，无论 worker 是否真正开始 SDK 操作，该候选本次尝试都已消费，不允许重置或重试。

## 当前代码状态与待解决项

- **backtrader_runtime/ctp_i13_source_identity_pin.py** 当前仍是全零摘要，**backtrader_runtime/ctp_i13_source_manifest.json** 不在当前 source tree。I13 的值脱敏 SDK wheel 与投影器已有离线审计，但这不提供主仓源清单 pin。
- **backtrader_runtime/ctp_i15_source_identity_pin.py** 当前的 **I15_REVIEWED_SOURCE_MANIFEST_SHA256** 为 **None**，**backtrader_runtime/ctp_i15_source_manifest.json** 也不在当前 source tree。I15 supervisor 会 fail closed；I12 的 artifact pin 不能替代 I15 的主仓源身份。
- I13 当前 supervisor 作为 **backtrader_runtime** 子模块导入之后才获取 source lease。它生成的 child bootstrap 也来自已导入模块；因此该检查不能作为首次导入前的信任根。I13 source-only loader 会编译 **.py**，但仍需按清单核对每次实际加载的 bytes，并由 finder 对 manifest 外模块 fail closed。
- I15 当前 child bootstrap 已设计为先校验源清单、再安装可逐文件 hash 校验的 source-only loader；但 parent 自身仍先导入 **backtrader_runtime**，不满足 whole-parent 的 pre-import 要求。I15 的 **discover_i15_source_files()** 当前经 artifact provenance helper 校验可被当前解释器加载的 **.pyc**。外层 source-only launcher 可以安全忽略 checkout 缓存，但必须增加一个窄的、显式受证 launch-mode 分支；普通 import / 普通 verifier 调用仍执行当前缓存校验。
- I13/I15 parent 都通过 **backtrader_runtime/config.py::_load_strict_yaml()** 读取 sealed YAML，该 loader 会 import PyYAML。因此候选 import closure 不仅含 runtime source、CPython stdlib 和 CTP/base SDK，还包含 PyYAML 的 wheel、installed RECORD、origin 与其 native/传递依赖身份；固定安装根不能只约束 CTP 包。
- source-only launch mode 下，**.pyc** 是不可执行输入：**-B** 只禁止写缓存，不能单独阻止读缓存。loader 必须从经 hash 校验的 **.py** bytes 直接 **compile()**，完全不调用默认 **SourceFileLoader.get_code()** 或 **get_data()** 的缓存路径。source tree 中允许存在位于合法 **__pycache__** 下的 **.pyc**，包括 magic 与当前解释器相同、内容陈旧或恶意的缓存；finder/loader 不得打开它们。包树中的 **.pyd**、**.so**、**.dll**、**.dylib**、不规则 cache 路径、reparse point 和任何非清单 Python import source 一律拒绝。普通非 source-only 路径不得放宽缓存策略。
- 初始 workspace source inventory 曾发现 163 个 checkout **.pyc**。正式验收前应重新统计；数量不影响安全结论，source-only import path 对缓存的不可达性才是验收条件。

## 外层 launcher 与信任锚

launcher 必须位于 **backtrader_runtime** 之外，也不能只存在于当前可编辑 checkout。不能把“launcher 自己写着自己的 SHA-256”当作 launcher 信任证明：若 launcher、pin 与 manifest 都可由同一未受信任目录一起修改，攻击者可以同步替换三者。

可接受的部署根是管理员控制的仓库外只读目录，或由受信任的原生启动器 / OS 应用控制策略固定的 launcher 发布物。部署记录至少锚定 launcher 精确字节摘要、launcher 发布版本、I13 和 I15 各自的 source manifest 摘要及 pin-source 摘要、固定 venv 与 Python runtime 身份。部署目录必须由独立于 checkout 写权限的主体维护；launcher 使用 Windows security descriptor / ACL 检查（stdlib **ctypes** 调 Win32 API 可实现）拒绝允许当前运行身份或不受信任主体改写/替换的部署。stdlib Python 不能凭自身验证自身真实性。

若只做一次性、人工审阅的只读诊断，可以采用受审 shell 命令桥接：trusted caller 持有从独立 review receipt 得到的 launcher SHA-256 与固定路径，先以只读方式打开并捕获 launcher 原始 bytes，核对摘要，然后把同一份捕获 bytes 作为 **python -I -S -B -X pycache_prefix=... -c** 的源码输入执行；唯一 prefix 必须先由受控父目录下的随机名确定并确认不存在。launcher 必须由该 inline bootstrap 对捕获 bytes **compile/exec**，不得再按路径打开自身。这样解决“脚本先执行、后自哈希”和 hash 到第二次打开之间的 TOCTOU。摘要值和 caller 命令仍须从仓库外的已审来源取得；若它们也从同一个可编辑 checkout 读取，则没有新增信任。该桥接仅适用于人工监督、一次性验收，不是日常 operator 入口；日常入口应部署成受签名 / 固定 pin 的发布物或管理员控制的只读安装。通过同身份启动的恶意进程、管理员或内核仍在威胁边界之外。

该模型保护受支持入口免受 checkout 改动、当前目录、Python 环境变量、**.pth** 和已安装的 site customization 影响。它不声称能对抗管理员、内核、受信任 launcher 部署主体或拥有同等权限且可改写信任根的进程。若没有外部可验证的 launcher 锚点，必须停在 **trust_root_unavailable**，不能用运行时代码自证后继续。

launcher 采用固定 candidate enum，只允许 **i13_md** 或 **i15_td**；不能从 CLI、环境变量或 config 传入任意 Python 模块、脚本路径、marker 路径或 interpreter。启动器从固定外部 trust descriptor 取候选的根目录、manifest digest、candidate pin 和固定 venv facts。描述文件格式需 canonical、长度有界、字段集合严格，摘要比较用 **hmac.compare_digest**。两候选都必须有非零 lowercase SHA-256；缺失、全零、未知 schema、重复/排序异常、路径越界或不匹配均早期拒绝。

descriptor 还须固定并核验 `backtrader_runtime` package 根与 `examples/013_3_sa_midfreq_simnow/runtime-ctp-private` 注册目录在同一个受审 source root 下的相对布局，以及 registry 使用的精确目录和策略身份。当前 `inventory.py` 从自身 `__file__` 推导 `SOURCE_ROOT`；只把 runtime wheel 安装到 site-packages 会改变该根，不能由 wheel SHA 自动证明 private registration 仍指向预期目录。若改走 wheel 发布，必须额外提供外部 pin 的 registration/source-root binding，或保留 package 与 examples 相对布局的受审 staging snapshot；布局/路径不符时在 config、socket、marker 前拒绝。

## 解释器、启动环境与 import 路径

Windows 受支持调用使用固定绝对路径的 venv **python.exe**，并验证该解释器及其 venv 根、**pyvenv.cfg**、基础 runtime 路径均为普通目录/文件，不含 reparse point。launcher 校验 CPython 精确版本、架构、**python.exe**、所需 runtime DLL 和完整 stdlib / stdlib zip 的固定身份；这些文件由管理员只读 ACL 或等价部署 pin 防止替换。**pyvenv.cfg** 必须确认 **include-system-site-packages = false**、固定 **home** 与版本。解释器、stdlib 或基础 runtime 身份无法验证时不继续。

以最小 allowlist 创建 child environment，仅保留运行 Windows/CPython 所需的 **SYSTEMROOT** / **WINDIR**、窄化的 **PATH**、owner-protected **TEMP** / **TMP** 和任务必须的 sealed binding。不得继承 **PYTHONPATH**、**PYTHONHOME**、**PYTHONUSERBASE**、任意 DLL search path 或 caller 工作目录。子进程用精确解释器绝对路径和 **-I -S -B**；每个 child 重新验证 flags、解释器身份、**sys.modules**、**sys.meta_path**、**sys.path_hooks** 与 **sys.path**。

**-S** 的作用是关闭 site 初始化；**-I** 关闭环境和 user-site 注入；**-B** 不写 pyc。三者都不能单独证明模块来自受信任源码，故启动后仍必须安装 source-only finder。开始前确认没有 **backtrader**、**backtrader_runtime**、**sitecustomize**、**usercustomize** 预载入，没有额外 finder/hook；只允许 CPython 当前启动时预期的 frozen/builtin/path finders。启动状态与预期不同则退出，不尝试清理已有可疑状态后接着运行。

外层 parent、metadata Job 与 worker 都必须在解释器启动命令中预先加入独立、随机且启动前不存在的 **-X pycache_prefix=...**，并保留 **-B**。不能只在 Python 已经启动后设置 prefix：bootstrap 执行 **hashlib**、**json** 等标准库之前，CPython 就可能尝试读取安装目录已有的同 magic **.pyc**。prefix 所在临时父目录必须由 launcher 私有化，避免其他进程在检查后向该唯一目录投放缓存；每个进程启动后立即断言 **sys.pycache_prefix** 精确等于传入路径，prefix 未被预先创建或填充。此项只旁路标准缓存目录中的缓存查找；不得把它当作 CPython、stdlib 源码或任意 sys.path 上 sourceless **.pyc** 的完整 pin。部署 pin / ACL 还必须覆盖整个 CPython stdlib 与 stdlib zip，并拒绝或证明不可达任何 legacy 顶层 **module.pyc**。fake 验收需分别尝试恶意 **__pycache__** 缓存和 legacy 顶层 **.pyc**；前者不能通过原缓存路径执行，后者必须由受 pin 的 stdlib 根、source-first 行为或显式拒绝规则证明不可达。若当前 CPython 不能证明缓存旁路覆盖启动会用到的所有 stdlib 缓存路径，替代方案是把精确 CPython 标准库 / zip 标准库整体加入 source/hash manifest 并置于不可改写 ACL 下；不能假设 **-B** 本身阻止读取标准库缓存。

同时 pin 固定 CPython executable、base runtime DLL 与 stdlib 路径。标准库 **.py** / zip 导入的 origin 必须来自 pin 根或明确列出的 CPython frozen/builtin module；不允许从工作目录、user site、其他 Python 安装或临时目录解析。启动失败前的 inline caller 本身也必须使用该唯一 pycache prefix，因为它负责第一次标准库导入与捕获 launcher bytes。

## 清单校验、缓存旁路与 source-only finder

外部 trust descriptor 为每个候选指定准确 manifest bytes 的 SHA-256。launcher 直接读取 manifest，不 import runtime pin 模块来获取摘要。launcher 对 JSON / schema 作严格验证，形成唯一 relative_path 到 sha256 映射，并检查：

1. manifest bytes 摘要与外部 pin 完全一致；每个路径是规范相对 POSIX 路径，拒绝绝对路径、点目录、父目录、反斜杠、重复项、重复 key、未知字段和非 lowercase SHA。
2. **backtrader_runtime** 下实际可导入 **.py** 集合与 manifest 一致，所有 bytes 摘要匹配。candidate pin 模块若因 self-hash 周期从其自己的 manifest 排除，则必须由外部 trust descriptor 单独 pin；其后导入的常量还要等于 descriptor 的候选摘要。
3. 包树不含 native extension、reparse point、符号链接或不规则文件/目录；**.pyc** 仅能处于标准 **__pycache__** 结构，而且不进入 importer 的候选集合。
4. 初次核验完成后，对 **backtrader_runtime** 根目录、每一级父目录、manifest、pin 文件和每个清单源码文件建立 Windows deny-write/delete source lease。获取全部句柄后重跑完整 manifest、inventory 和 hash 检查。任一句柄无法获取、文件身份变化、活动写句柄冲突或 lease 不能跨越整个流程保留时，失败关闭。

每个 Windows lease 句柄都要记录 **GetFileInformationByHandleEx(FileIdInfo)** 返回的 volume serial 与 volume file ID。每次 loader 解析 source pathname 时，应以 no-follow 方式打开该路径，确认 newly opened handle 的 volume/file ID 与 lease 中对应的对象相同，并从该已核对的 handle 读取 bytes；读取前后再次核对 handle ID、文件类型、长度和 hash。父目录路径组件也要与持有的目录 handle ID 对应。不能只比较路径字符串或对路径 **lstat** 后重新调用 **read_bytes()**，否则 lease 可能锁住旧对象而 loader 读到替换后的新对象。文件系统不支持稳定 volume/file ID，或无法将加载路径绑定到 leased handle 时，拒绝候选或先复制到已 seal 的不可变 staging root。

安装在 **sys.meta_path[0]** 的 finder 只处理 **backtrader_runtime** 名称空间；对其他名称返回标准查找路径，对 **backtrader** 核心包、**backtrader_runtime** 清单外的名称和非标识符拒绝，而不能返回 **None** 让稍后的 **PathFinder** 兜底。package **__path__** 只指向 sealed 包目录。loader 在每次 import 时按清单路径以 no-follow/身份前后复核方式读取源 bytes，重新计算 SHA-256，匹配后直接编译该 bytes 并执行；模块 **__cached__** 必须为 **None**。不能把“启动时 hash 通过”当作之后导入无需复核。

当前 I13/I15 candidate dependency closure 使用 **backtrader_runtime**、CPython stdlib、PyYAML 与固定的 SDK；不需要 import Backtrader 核心包。仓库其他 runtime fixture 确有独立的 **backtrader** imports，但它们不属于这两个只读候选的允许 import closure。fresh-process import trace / finder audit 必须证明两个入口在 artifact preflight、front precheck 与 worker 中都没有 import **backtrader**。因此本设计对 **backtrader** 核心包明确 fail closed，不会导致当前候选的已知合法依赖失效。若后续实现发现某条必要路径确实需要该包，应另行 pin 精确 Backtrader source closure 或 installed wheel + RECORD/origin root，再更新 finder allowlist 和独立评审；不得移除 deny 规则或委托普通 PathFinder。

父进程在 seal 后再次扫描 exact source inventory；source lease 尽量阻止新增或替换目录项，但不能把目录 handle 的语义当作唯一防线。finder 对新增 sibling 即使尚未做第二次全树扫描也必须因为不在 manifest allowlist 而拒绝；正式负测必须覆盖新增 sibling、seal 后修改源文件，以及“lease 仍持旧 file ID、pathname 已指向新 file ID”三种竞态。parent 每一阶段返回前核验 import origins、已加载文件摘要、source inventory 与 lease 仍有效。

I15 的窄缓存旁路只允许在上述 bootstrap 已成功、首位 sealed finder 已安装、同一 source lease 已持有的 source-only launch mode 中生效。建议增加不可误用的显式 proof/context 参数给 I15 cache validator：它只跳过 **.pyc** 内容与 magic 校验，不跳过目录结构、reparse 检查、exact **.py** inventory/hash、native artifact 拒绝，也不改变普通 **verify_i15_source_identity()** 路径。I13 的 source verifier 如需兼容同一缓存也要使用相同窄语义。没有 launcher proof 时，I13/I15 原有严格缓存检查保持原样。

## **-S** 下 no-system venv 的 installation-root 绑定

在受支持 CPython 3.11 下，**-S** 会让 venv 的 site 初始化不运行；不可假设 **sys.prefix** 或 **sysconfig** 自动指向 venv，也不能从用户环境推导安装根。launcher 从外部 pin 的 venv 根导出唯一 **Lib/site-packages** 绝对路径；验证路径每个组件无 reparse point、**pyvenv.cfg** 标明 no-system、该目录确属指定 venv。source finder 装好之后，才把此单一路径显式追加到 **sys.path** 一次。再验证没有其他 venv、base、user 或 checkout package 目录可解析受信任运行时/SDK。

artifact verifier 与 capability-origin resolver 的安装根都要被绑定到这个 exact **site-packages**，并拒绝从 Python base **site-packages**、**AppData**、工作目录或 **PYTHONPATH** 接受模块。SDK / base distributions 通过固定 wheel hash、版本、完整 wheel RECORD、受控安装后的 RECORD 和 direct-url 来源验证；worker 导入后还要验证 **module.__file__** 和 native **.pyd** 的实际路径落在精确根内并与 RECORD 哈希一致。不能因为 venv 有 no-system 设置就假设它之后没有被改写；可以对已安装文件/目录一并取得 deny-write/delete lease，或要求独立 ACL 锁定并在 metadata Job 与 worker 启动前后重复完整 artifact 验证。

至少对 PyYAML 也执行上述精确 pin：固定 wheel identity、版本、wheel hash、installed RECORD、direct-url 来源及实际 **yaml** / 可选 native **yaml._yaml** origin；递归记录该环境内其余允许 import 的 wheel/依赖，拒绝仅因位于同一个 site-packages 就被动接纳的未审 distribution。父进程 config loader 导入 PyYAML 的事实意味着它属于父进程 source trust closure；不能把 PyYAML 留到 marker 后才验证。

固定安装根和 wheel/RECORD pin 之外，还须在首次 PyYAML/SDK import 前拒绝 RECORD 外可导入的 `.py`、`.pyc`、`.pyd`、`.pth`、同名顶层模块及包内新增文件；尤其覆盖旧式顶层 `module.pyc` 和包内无对应受审源码的 loose `.pyc`。`-X pycache_prefix` 只隔离标准缓存查找，不能独自阻止 SourcelessFileLoader 读取额外文件。可通过扫描 exact site-packages 可导入 inventory，或安装只允许精确 wheel manifest 中 `.py`/`.pyd` 的 finder 并阻止 PathFinder 回退实现。fake 负测须在 site-packages 顶层及 `yaml/` 包内各放 sentinel，证明它不执行，且拒绝发生于 config parse、socket、marker 和 provider 前。

**-S** 下不执行 **.pth** 文件；仍应 fake 负测确认 **.pth** 中 import sentinel 不会运行。bootstrap 显式禁止 **sitecustomize** / **usercustomize** module 预载入和显式导入。若 CTP extension 需要 DLL search path，只允许来自已 pin venv 的固定目录与 Windows system directory；不能从当前目录、任意 PATH 或用户可写目录装载 DLL。

## 配置、pair seal 与阶段顺序

源与解释器门槛通过、PyYAML 及其安装文件已精确 pin 并持有 source/artifact lease 后，才 import sealed I13/I15 supervisor 并允许加载 sealed config。两个候选都从同一个受保护的 canonical **ctp:** config 形成一个 parent-side seal：config digest、registration/effective digest、ordered candidate-pair list digest、selected pair index 与该完整 MD/TD pair digest。父进程对密封列出的 whole pairs 运行有界、无凭据 TCP 前置检查；按现有固定 score 规则从配置候选中选 pair，平分时以原配置索引稳定打破平局。不得根据 **CTP_SET1** / **CTP_SET2** 名称、set label、日历、时刻、环境变量、CLI 或静态 SimNow 地址表选择前置。

metadata-only Job 与 worker 均收到同一个 binding 摘要 / selected index，并重新加载同一 config、重算 sealed facts、确认精确 pair。父进程选择后，worker 只验证该 pair，不重复探测后换选，也不接受一半 pair 或从另一个 set 拼接。config、registration、candidate 列表、pair 任一字节不同即拒绝。pair binding 中无需向 receipt 输出地址或账号；receipt 仅回显固定状态和必要的候选索引。

前置顺序不可交换：

1. 固定 trust root、interpreter 和 source manifest 检查，安装 source-only finder，并获取 source / venv lease。用 stdlib metadata/RECORD reader 在首次调用 config loader 前核验固定 PyYAML wheel SHA、installed RECORD digest、distribution version、direct-url/origin 与全部允许依赖；随后才允许从固定 site-packages 导入 PyYAML，并核验 **yaml** 与可选 **yaml._yaml** 的实际 origin。PyYAML 来源失败时不 parse config、不做 socket precheck、不启动 Job，也不触碰 marker。
2. 重新加载 sealed config，做 credential-free pair 前置检查。超时或选 pair 失败时，不启动 metadata Job，不读写任何 I13/I15 marker。
3. 启动独立 metadata-only Windows Job。其 fixed command 只做固定 SDK/base 的 artifact metadata、wheel/installed RECORD、来源及 origin 检查；不得解析 credential、import CTP native SDK、建立 socket/provider session、调用 TD/MD API 或触碰候选 marker。必须看到 child 创建、Job assignment、恢复、exit 0、严格 value-free metadata receipt 和 Job empty，且 containment 为 verified。失败或不确定时不读写候选 marker。
4. 再验证 parent source/artifact leases、manifest、loaded origins、venv root/artifact seal 及 config/pair binding；完成后只访问当前候选的独立 one-shot marker。I13 marker 与 I15 marker 永远不同，不读写或重置 I10/I11/I12 marker。I15 可以复用经审查的 I12 无状态只读查询 adapter / artifact predicate，但不等于复用其 attempt marker。
5. 建立 I13 MD-only 或 I15 TD-only worker Job。worker 先重新验 source manifest / importer / 同一 config-pair seal / artifact pin，随后才允许它自己的候选只读操作。parent 保持 source lease、artifact root lease 与 Job 控制到 Job empty 或明确失败收尾。
6. 只在候选完整成功谓词、native close receipt 与 Windows Job 收拢证据同时匹配时报告候选只读完成。失败、unknown、Join pending、receipt 矛盾、超时、Job 未 empty 或 retained control 一律不能成功；绝不推导账户可交易、可结算或任何写入授权。

父进程 monotonic budget 从 launcher 起点覆盖源扫描、lease、precheck、metadata Job、marker、worker、terminate 和 cleanup；socket 逐次 timeout 取剩余预算。该预算是协作式检查与阶段预算，不能抢占卡在文件系统或同步 Windows API 的 parent 线程，也不能仅靠 child Job 保证 launcher 按时返回，所以它不证明 whole-parent hard deadline。若验收需要硬上限，必须由独立于 launcher 的 watchdog / 外层 Windows Job containment 覆盖 launcher 与全部后代，并证明超时能终止全树、释放 source/artifact lease 和 Job 控制；否则 receipt 只能报告 checkpoint 观察到 budget expiry，不能承诺整个命令的返回时间。尚无该 outer watchdog 证据时，不得将候选包装为 ordinary CLI preflight 或据此开放默认 route。

## Fake-only 负测与验收矩阵

完整验收负测只用临时 source tree、临时 venv/site-packages、合成 manifest、假的 socket 和可注入的 Job runner；必须在 fresh **python -I -S -B -X pycache_prefix=<unique-absent-path>** subprocess 覆盖 bootstrap，并在启动前验证 prefix 不存在、启动后验证 **sys.pycache_prefix** 精确匹配且没有缓存写入。还要验证 pinned stdlib 根中的 **__pycache__** 缓存 lookup 被旁路、legacy 顶层 **.pyc** 不可达；不得读取真实私有 config、marker、凭据或 SDK，不得网络访问。一次性 launcher 桥接还要单独测试：正确 pin 的捕获 bytes 正常执行；错误 pin 在任何 launcher 语句执行前失败；捕获之后替换磁盘路径仍只执行捕获的旧 bytes、不二次打开；引用 symlink/reparse path 时拒绝。下表是完整验收矩阵；当前只运行了其中 source seal/loader/cache 与 lease 的 9 项 fake 测试，没有运行外部 launcher、完整 stdlib/PyYAML/SDK 制品或 Job/marker 流程。

| 面向 | fake 负测 | 必须观察到的结果 |
|---|---|---|
| launcher 信任 | 修改 launcher bytes、替换 trust descriptor、候选 manifest pin 为 **None** / 全零 / 错值 | 在任何 runtime import、front probe、Job、marker 之前 fail closed |
| manifest 语法 | 重复 key/path、未排序或重复 path、路径穿越、反斜杠、未知字段、超限文件、遗漏或额外 **.py** | exact source identity rejection；无 precheck / Job / marker |
| 首次导入次序 | fresh subprocess 在启动时塞入 runtime/site module、第三方 meta finder 或 path hook；伪造 **sitecustomize**、**usercustomize**、可执行 **.pth** | launcher 拒绝污染状态；site hook sentinel 计数保持 0；runtime 未提前导入 |
| checkout 与 stdlib stale bytecode | 写入当前 CPython magic 的恶意/陈旧 checkout **.pyc**，以及 stdlib 下 **__pycache__/hashlib.*.pyc** 与 legacy **hashlib.pyc** / **json.pyc**；source bytes 与 pin 正常 | 每个进程启动时已带唯一 absent pycache prefix 与 **-B**；prefix 正确且未被填入，stdlib module origins 来自 pinned root；缓存旁路、完整 stdlib pin/ACL 与 legacy cache 拒绝共同证明 pyc sentinel 不运行；source-only 模式执行清单 **.py** 行为，checkout pyc 未被打开；普通 verifier 无 proof 时仍按原合同拒绝不匹配 cache |
| PyYAML origin/cache | 把恶意 **yaml.py** 放在 CWD、checkout 或另一 site-packages；置入当前 magic 的旧 **yaml** pyc；换 PyYAML wheel / installed RECORD / optional **yaml._yaml** origin | import 只能来自 pin 的 no-system venv root，wheel/installed RECORD 与 native extension hash 匹配；shadow module 与 pyc sentinel 不运行；摘要不匹配时在 marker 前拒绝 |
| native/import 绕路 | 包树加入 **.pyd**/**.dll**、cache 外 **.pyc**、reparse point、清单外 **.py**，以及伪造 **backtrader** package | 在 import/候选 precheck 前 fail closed；finder 绝不对清单外路径委托 PathFinder |
| source TOCTOU | 首次 seal 后、模块首次 import 前改写已 pin **.py**；seal 后新增 **backtrader_runtime/rogue.py** 并尝试导入；替换父目录或文件 identity | loader hash 拒绝已改源码；新增 sibling 即使目录 scan 尚未复跑也因 allowlist 被拒；lease/identity 复核检测目录替换；无 marker/provider call |
| 父进程 lease | 模拟已有写句柄、deny-write/delete handle 无法取得、子目录增项/rename、持有 lease 后通过 rename/reparse 将 pathname 指到不同 volume/file ID | lease 获取或重核失败，precheck 不开始；每个载入路径的 opened-handle ID 必须匹配已持有 lease ID；lease 一直保持到 worker/metadata Job 收尾和 import-origin 最终检查 |
| **-S** venv binding | 错 interpreter/version/arch、**include-system-site-packages=true**、home 不符、用户/base decoy SDK、重复 sys.path root、任意 PATH/DLL dir | source imports 之前拒绝；或 artifact verifier 拒绝错误 origin；仅 exact site-packages root 可解析 pinned distribution |
| front→metadata→marker | fake precheck 失败 / deadline 到期；metadata Job exit 非 0、receipt 矛盾、未 assigned/未 empty、containment unknown | 保持调用顺序证据；后续阶段不运行，候选 marker read/write 调用数均为 0 |
| marker 边界 | I13/I15 candidate marker 已存在；在 temp 目录分别运行 I13/I15 latch；运行 I15 时放置 I12 sentinel marker | 当前候选拒绝/消费一次；只变化当前 candidate marker；另一个 candidate 及 I12 sentinel 字节完全不变 |
| 同配置同 pair | config digest、ordered candidates、registration、selected index 或任一 endpoint 在 metadata/worker 边界改变；前置后某 pair 可达性改变 | metadata/worker 拒绝，不重选 pair；原 parent seal 不变；worker SDK call 计数为 0 |
| 禁止 set/time 选择 | fake pairs 带有伪造 SET1/SET2 label、env/clock/calendar 值和不同 RTT；反复变更 label/time | 选取只依赖 sealed candidate 集与规定 probe score/固定 tie-break；child 只验证原选择 |
| 候选能力范围 | I13 fake trace 只启用 MD login/subscribe/tick；I15 fake factory 只启用 TD identity/七查询 | I13 任何 TD query 构造失败测试；I15 任何 MdClient/subscribe 构造失败测试；两者的 order/cancel/settlement write counters 固定为 0 |
| 收尾与 receipt | Join pending、Release 缺失、close unknown/exception、Job 未 empty、超时后 retained handle、值类型/字段越界 | **incomplete** / **unknown** / fail closed；不提升为候选成功，不泄露敏感值 |

I13 完成谓词还要求正面的身份验证、精确订阅 ACK、matching same-TradingDay tick、独立值脱敏 SDK receipt 与完整 Release/Join/线程退出；Job empty 不能代替 native close。I15 完成谓词要求 TD identity、七项只读查询终包/过滤范围检查、完整 Release/Join/线程退出及 Job 收拢；费率交易所为空时只能投影为 **unverified**。两个候选都要求 order submission、cancel、settlement/write 调用计数为零。

通过 fake-only 测试只证明实现合同与失败顺序，不能替代真实 Windows Job API 测试、实际 SDK callback/native Join 供应商语义或 provider/session readiness。

## 制品 pin 的后续步骤

1. 在 I13/I15 SDK 和主仓代码全部冻结后，生成规范、可复现的完整 package source manifest；将候选 pin 文件列入独立外部 trust descriptor，避免 self-hash 循环。分别固化非零 I13/I15 manifest digest，并对 pin source、launcher、python runtime 发布身份独立审阅。任何源变更都要重算、更新并重新独立审查摘要。
2. 对 I13：保留现有 clean-clone I13 SDK source commit 与 reproducible wheel 证据；重新确认 source commit、版本、wheel digest、embedded RECORD、独立安装后的完整 RECORD、**direct_url.json**、**bt_api_base** 配对 wheel 与全部运行期依赖都一致。现有 I13 wheel 审计可作为证据输入，仍需完成 outer launcher source pin / installed-root 结合审计。
3. 对 I15：只引用 I12 已有的精确 CTP/base artifact contract，不把 I12 诊断结果当 I15 session 证据。重新审查 I15 需要的 CTP/base wheels、完整 RECORD、PEP 610 来源、版本/commit、native payload 和依赖；修复 **discover_i15_source_files()** 的 launch-mode cache 分支后做独立源码审查。
4. 建立一次性、no-system CPython 3.11.5 venv，使用绝对解释器路径安装精确 wheel 集；记录 interpreter binary/version/arch、**pyvenv.cfg**、venv 根与 site-packages 根、CTP/base/PyYAML 及全套允许 distribution versions、wheel SHA、installed RECORD SHA、每个 origin 与 **pip check** 结果。运行期启动必须在 **-S** 中显式绑定同一个根，不能依赖 **sys.prefix** / **sysconfig** 自动识别；父进程标准库缓存通过唯一 absent pycache prefix 旁路或整套 stdlib pin/只读 ACL 验证。
5. 由独立 reviewer 复核 launcher 的信任锚、manifest closure、cache bypass 的窄范围、source/artifact leases、config/pair seal、Job/marker 次序、fake 负测结果和无秘密 receipt。只有全部通过，才可另行评估一个明确的 I13 或 I15 one-shot 真实只读诊断；该审阅不登记默认 route、不授予订单、撤单或结算能力。

## 参考实现与复核入口

- I13：**backtrader_runtime/ctp_i13_source_identity.py**、**backtrader_runtime/ctp_i13_md_oneshot_supervisor.py**、**tests/unit/runtime/test_ctp_i13_md_oneshot_supervisor.py**、**evidence/ctp-i13-md-observability-design-2026-09-25.md**。
- I15：**backtrader_runtime/ctp_i15_source_identity.py**、**backtrader_runtime/ctp_i15_source_identity_pin.py**、**backtrader_runtime/ctp_i15_td_only_readonly.py**、**tests/unit/runtime/test_ctp_i15_source_identity.py**、**tests/unit/runtime/test_ctp_i15_td_only_readonly.py**、**evidence/ctp-i12-td-readonly-design-review-2026-09-25.md**。
- 外层 Job 语义：**backtrader_runtime/ctp_readonly_job_supervisor.py**；artifact contract 需与 **backtrader_runtime/ctp_artifact_provenance.py** 独立 pin 一并审查。

## 离线 sealed-import 切片进度（2026-09-25）

主仓新增未登记的 `scripts/ctp_i13_i15_sealed_import.py` 与 `tests/unit/scripts/test_ctp_i13_i15_sealed_import.py`。它限定 CPython 3.11.5 `-I -S -B` 离线导入，先捕获固定 bootstrap 模块对象，再以 source manifest/hash 检查候选导入；`__main__` 别名及快照外的 stdlib 模块缓存均拒绝，sealed finder 不向 `PathFinder` 回退快照外的 stdlib 名称。独立 reviewer 用带真实 `fractions` `ModuleSpec`、loader、origin 的伪缓存复现负测，现于 entrypoint 前以 `bootstrap_module_outside_snapshot` fail closed；`__main__` 入口以 `bootstrap_runtime_module_invalid` 拒绝。Windows source file-ID lease 已接入 manifest seal 和 source loader：持有 manifest、清单源码与 pin 源的句柄，重读完整清单与源码；loader 每次从经 file-ID、长度、hash 核验的句柄取 bytes，并直接编译相同 bytes，不走 pyc。一次 reviewer 复现发现合法 sealed spec 可伪造未执行的 `sys.modules` 模块；当前 finder 增加 in-progress/executed 对象身份记录，伪模块不再通过 checked import，包嵌套导入与执行异常清理有 fake 测试。Windows lease 关闭失败时 poison 并保留句柄待显式重试；原生 open 成功与 Python 登记之间的极端 OOM 清理窗口仍属未覆盖的可用性边界。整个脚本定向 fake 测试 `9 passed`、Ruff 通过，未使用账号、config、marker 或 provider。

这只是 stdlib bootstrap、manifest seal、source lease 与 loader 的局部实现，不是可调用的 I13/I15 supervisor。它尚无外部发布身份与 descriptor、受审完整 stdlib/dependency closure、解释器/PyYAML/SDK wheel pin、no-system venv root 绑定及 marker/Job 顺序，因此不得启用真实诊断。快照外合法 stdlib 依赖当前也会按设计 fail closed；必须先明确列入受审快照，不能放宽 finder 让普通导入兜底。原始 `importlib.import_module()` 可直接返回已缓存模块，正式调用者必须使用 checked import 边界；外层 launcher 尚未实现时不把此 helper 当作可信启动入口。

**Windows 租约边界：** 独立负测在 source lease 持有期间仍能取得包目录的 `FILE_WRITE_ATTRIBUTES` 和 `GENERIC_WRITE` 句柄。根据 [Microsoft `CreateFile` share-mode 文档](https://learn.microsoft.com/windows/win32/api/fileapi/nf-fileapi-createfilea)及 [`FSCTL_SET_REPARSE_POINT` 权限文档](https://learn.microsoft.com/windows/win32/api/winioctl/ni-winioctl-fsctl_set_reparse_point)，不能把这组 share flags 描述为目录元数据不可改写。本切片的较窄保证来自每次重新打开时检查组件的 reparse 属性和 file ID、从精确句柄读取并校验 hash、然后编译同一份 bytes；它不能替代配置修改与原生报撤单之间的可线性化动作锁，也不能证明外层源码路径在整个进程中静止。
