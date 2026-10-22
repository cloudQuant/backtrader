# 来源路径前置检查 r0

外层进程退出 1，未收集或运行测试。子进程导入成功（退出 0），
`source-origin.txt` 保存实际导入路径。检查工具使用未规范化的 `/var/folders/...`
导出根目录与规范化后的 `/private/var/folders/...` 比较，导致
`Path(origin.strip()).resolve().is_relative_to(source)` 断言失败。

修正仅为在创建临时目录后调用 `.resolve()`。父目录里的完整源码验收来自
修正后新的导出目录，旧前置输出保留在此。
