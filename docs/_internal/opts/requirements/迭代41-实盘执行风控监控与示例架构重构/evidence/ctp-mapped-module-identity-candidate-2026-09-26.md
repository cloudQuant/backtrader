# 已映射 CTP 模块身份回执候选（2026-09-26）

此文件和隔离工作树 `D:\source_code\backtrader-md-root-cause` 本地提交 `a3b3fd891d10ed7e70f6ec1dfea17e7a8abd876d` 中的 `backtrader_runtime/ctp_mapped_module_identity.py` 是离线候选；没有接入主仓 I13/I15 child、supervisor、默认 CLI 或任何常规入口。提交尚未发布到共享远端。真实 OS module-map 查询需要在已运行 child 自身内进行。本候选没有调用 Windows API；真实调用延后到未来独立 G1 诊断门接受之后。

Windows backend 的设计使用当前进程的 `K32EnumProcessModulesEx` / `K32GetModuleFileNameExW` 列出已映射模块并匹配精确 DLL basename；不主动调用 `LoadLibrary`、CTP API、socket、DNS，也不从 PATH、`sys.path`、SDK目录或搜索顺序推断 DLL。查询模块表的路径可以是实际运行模块来源的系统观察，但文件核验仍有以下边界，不能作为严格离线或原子身份凭证：

- `GetDriveTypeW` 只检查盘符根。helper 未逐组件检查 reparse point、junction、symlink 或其他 ancestor redirect；盘符看起来是 fixed volume，不排除路径祖先把文件 I/O 导向网络位置。因此代码没有证明“绝无网络目标”。
- `CreateFileW` 当前允许 share read/write/delete。其他写者或删除/替换路径的操作可能与读取并发。前后 file ID、大小和 last-write 字段相同，只能发现部分变化，不构成不可变文件锁或原子快照；同大小修改、时间戳恢复等情形未被排除。本候选不擅自收窄 share flags，因为没有真实 Windows 语义验收。
- 回执不输出原始路径，但 `loaded_path_sha256` 是无密钥、确定性的 UTF-16LE 路径 SHA-256。它可被候选路径字典匹配，也能跨运行关联；“pathless”不等于匿名或不可关联。
- 文件 ID/hash 是模块表查询后，从 loader 回报路径打开的文件句柄所得；它不证明该文件对象就是当前映射 image section 的 backing object，也不哈希重定位后的进程内存。文件被映射后路径若发生替换，路径哈希仍指原报告字符串而文件身份/hash可能指后来的对象。
- FileVersion/ProductVersion 暂标 `unavailable_not_collected`。

代码在固定盘符根检查失败、模块表或路径不可读、重复 basename、文件不可读等情况下输出固定不可用/歧义状态。即使状态为 `observed_at_path`，也应按上面范围解释，不可宣称网络目标、并发变更、映射后替换或原子性已被排除。

当前焦点测试全部注入 fake backend，未调用该 Windows backend，不启动 CTP/native、不访问网络、不使用已消耗 marker。焦点测试：16 passed；Ruff clean。它们只覆盖 DTO、固定错误分类、basename 校验、可重复路径摘要和 fake 文件身份，不验证 Windows loader、reparse、共享语义、文件锁或原子快照。
