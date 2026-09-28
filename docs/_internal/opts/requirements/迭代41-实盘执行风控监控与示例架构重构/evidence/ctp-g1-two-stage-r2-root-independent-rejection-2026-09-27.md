# G1 双阶段 r2 root 独立复测反例（2026-09-27）

裁决：`INDEPENDENT_SUITE_NOT_CLEAN / G1_REMAINS_CLOSED`。r2 冻结 manifest SHA-256 `fb9e8c0e1e36f9411371712a7cdc90888ce6d8e49b5da63f8662a9665ea66a81` 的 36/36 项大小/摘要吻合；root 将 18 项源码/测试复制到独立目录后再次核对，并用相同 Python 3.11.5、禁插件自动加载和禁 bytecode 条件运行。

角色/bootstrap/进程焦点独立运行是 `33 passed / 1 failed`。失败项的真实 Windows 惰性进程返回 `state=exited`、`reason=launcher_exited_job_empty`、`launcher_exit_code=2`、Job 已空、coordinator frame 存在；frame 内是 `state=unknown`、`reason=worker_failed`，没有 worker observation。测试正确不将其视作 clean success，但 else 分支错误地限定 outer state 必须是 `failed` 或 `unknown`，未覆盖“进程已退出且 Job 已空，但退出码非零”的分支。单节点重跑 `1 passed`，这次为 `state=failed / descendant_or_job_state_unconfirmed`；时序敏感。服务双阶段焦点另为 `5 passed / 42 deselected`。作者 `34 passed` 的记录仍保留，但不能替代本次独立失败。

root QA 回执 SHA-256 `e7363efebb7f7f68214998fc4ad78341639a8bde45f624a8cd1559f7c49fa981`。[原始归档](ctp-g1-two-stage-r2-root-independent-rejection-2026-09-27.raw.zip)保存冻结 manifest、关键源码/测试、生成 bootstrap、初次失败和重跑日志及两个 outer 结果，共 21 项；ZIP 完整性和内部摘要通过，SHA-256 `f689391e8de54e98b8af00c139b0466a3dc446c557890c92047445d52ed4684b`。冻结 r2 未被修改。

该反例要求后续 r3 明确拒绝非零退出码所伴随的 frame，并修正进程测试分类。成功路径仍只有合成 worker/Job 事实，prewarm、watchdog 自身同步创建和清理、真实服务部署及 CTP native close 尚无完整整命令监督；普通 preflight 保持关闭。
