# G1 inert 监督链独立复验（2026-09-26）

## 结论

七模块完整焦点由独立 QA 执行：**95 passed、0 failed、0 error、0 skipped**，
57.09 秒，exit 0。唯一 warning 是该 pytest 环境已有的
`asyncio_default_fixture_loop_scope` 未知配置项。使用 CPython 3.11.5、pytest 8.2.2，
关闭插件自动加载、串行执行、新 basetemp。

范围为固定 inert sleep/setup/worker/close 阶段的 Windows 进程监督和清理，
包括 parent launcher、sealed import、outer watchdog、guardian、guardian service、
Job backend 和 inert deadline supervisor 的测试。**G1 仍为 NOT_PASSED**；
普通 preflight、真实 CTP/native close、受信部署根与整个命令的实际接线均未验收。

## 修改与历史失败

监督器候选源文件在本轮测试修复期间保持冻结：

- `scripts/ctp_i13_i15_inert_deadline_supervisor.py`：
  `0810739298df61c62fdabaf3aa3a0387d87b8efc78fe4751bbdf4f1bbf05109`。
- `scripts/ctp_i13_i15_inert_parent.py`：
  `fd0a0e35ea34a2c3be9fc26902aea49593a470e3025c1aa9dd8798b3ed025117`。

测试修复包含：将“文件已出现”改为截止内读到完整 JSON；在首次 Job 状态不确定、
随后保守终止并确认清空时，严格检查 `failed` 原因、终止结果和清理事实；保留
自然退出正例。另补固定阶段名、PID 和单调时间的诊断日志，以及有长度上限的
stdout/stderr 尾部，没有输出 argv 或测试 HMAC key，也没有放宽原有 10/12 秒等待。

此前的 **93 passed / 2 failed** 完整运行仍保留：一个 owner IPC 结果未在预算内出现，
另一个 service 的 child-active marker 未按时出现；当时缺阶段日志，原因未判明。
不能归因为宿主噪声，孤立重跑通过也未作为整组通过替代。另有更早 JSON marker
半写可见性错误和保守 cleanup 分支错误；这些原始文件的路径、hash 和修复范围
均在下方 JSON 中。本次是诊断补齐后的完整七模块复验，没有删除这些历史记录。

## 证据

- [命令、版本、五个变更文件 hash 和历史失败清单](ctp-inert-supervisor-95-review-2026-09-26.json)，
  SHA-256 `e96ca49566e23411f5e5b60e28b323279e880a7fa9a65079cc895d71619b4294`。
- [JUnit](ctp-inert-supervisor-95-review-2026-09-26.junit.xml)，SHA-256
  `568987168767772353ede67cead6a30c6779971db716bbbcc89efa3e95b9e7e3`。
- [pytest 输出](ctp-inert-supervisor-95-review-2026-09-26.log)。
- [十份阶段日志](ctp-inert-supervisor-95-review-2026-09-26-phases.zip)，SHA-256
  `2c588d8094a6a2f76b3c5cf1641875ff6ab110cb7524c0f3acd1fe809deba043`。

根代理重新解析 JUnit、核对五个变更文件及十份阶段日志 hash，并确认日志每条仅包含
固定 phase、monotonic_ns、pid 字段。这里没有声称所有依赖源码的运行前后清单已冻结；
最终主仓统一验收仍需独立完整来源记录。

外部 service 身份、descriptor 签名/ACL、部署与重启策略没有落实。
最外 supervisor 内同步 Win32 调用阻塞、系统停调或休眠也不在当前硬截止证明内。
没有使用私有配置、一次性真实 marker 或 provider；此结果不提供交易授权。
