# ADR-41-17 (PROPOSED / NOT_ACCEPTED): 启动封存的 CTP run-scope 与 session 非热重载

**状态：** `PROPOSED / NOT_ACCEPTED`。本文件只提出替代配置变更语义的设计选项；不关闭现有 P2，不替换当前硬验收或 xfail，不开放 SimNow、production、runner 或任何写入口。默认仍为 `NO_WRITE / LIVE_NO_GO`。
**日期：** 2026-09-26
**范围：** 评估是否把同一受保护 `config.yaml` 定义为启动时选择一个不可变 run-scope 的输入，并在该 session 内禁止热重载，从而移除每个动作再次读取配置文件的语义要求。

## 要评审的决定

迭代41的目标仍是同一个受保护 canonical `ctp:` `config.yaml`、同一个最终受管 CTP runner；`runtime.mode/preset` 只在启动时选择本次 session 的 sandbox 或 live profile。生产不是第二份配置，也不是第二套 runner。候选模式切换流程是：旧 session 完整停止并关闭、所有原生资源确认静止、旧 session 的账本没有未决或 `UNKNOWN` 命令，runtime-wide 活跃租约释放；操作者随后修改同一文件；新启动再解析新的 mode/preset。修改文件本身不切换已经运行的 session。

这与现有合同存在实质差异：当前 [同配置共享 runner 合同](CTP同配置共享Runner开发与验收.md)要求运行中配置修改使旧 seal/approval 失效；[AC41-37 配置动作验收](验收文档.md)要求在最后重封与 fake native dispatch 间并发修改文件时旧 scope 零派发；[TC83-I-OPS](验收用例与基准.md)要求每个敏感动作前重新读取磁盘。当前严格 xfail `test_profile_config_change_after_final_check_blocks_native_dispatch`（submit/cancel）也在证明该动作级变更失效合同仍未满足。**本提案不改变这些条款；在明确批准并完成迁移前，它们和 xfail 仍然有效。**

若安全要求是“文件一改，当前 session 的下一动作必须立即失效”，本方案不兼容该要求；应保留现有合同并实现一个真正受信的配置变更与动作派发共同仲裁边界。普通文件重封、文件身份复查、POSIX/Windows 文件锁或本机 lease 都不能单独证明该边界。本 ADR 也不把这种 lease 描述成跨平台、跨用户或跨主机互斥。

## 候选语义（须单独批准）

1. **启动快照是唯一配置采纳点。** 受管 worker 在启动边界读取同一受保护文件，将同一组已读取字节解析为配置并创建不可变 run-scope。绑定至少覆盖 runtime identity/registration/profile、`mode/preset`、配置与 effective digest、canonical `ctp:` 全部候选 pair 及本次精确 pair、账号和合约/hedge scope、受审制品 pin、credential-binding tag/key id、随机或持久化的 session generation，以及固定 `valid_until`。快照、日志、审批与收据不包含原始凭证；不得接受调用方自报的 digest、generation 或 grant。
2. **启动读必须取得稳定字节视图。** 当前 loader 的 handle/path/file-identity 检查不能自动证明同一文件被原位并发写入时读到的是一个一致版本。实现前须定义可信配置发布/读取边界，并证明 worker 解析和 seal 的确是同一组完整字节；若并发原位写入可能产生混合内容而实现无法排除，启动必须拒绝。双读相同、普通文件锁或只检查路径/文件 ID不应被写成线性化证明。原子替换、同 inode 写入、截断后重写和 reparse/path 替换均需分别测试。
3. **session 内不热重载。** 启动后 config 文件变化不改变当前 profile、凭证绑定、候选集或动作范围；当前 session 的动作仍只能在它创建时封存的 scope 内由其他逐动作门控判定。配置改动只能由下一次新 session 采纳。session 的绝对期限在启动时固定，新的短期动作审批不得延长它。若要在期限前紧急撤销，必须有独立受信撤销通道；当前没有该通道，不得假称文件编辑可即时撤销。
4. **动作批准仍逐次校验。** 不重读配置不等于放松动作门控。每个一次性审批仍须绑定 session generation、封存 scope、精确 intent/request/目标、可信时间与短 TTL；worker 还须检查风险/监控、持久化 claim、连接代次与交易日、外部 writer fence 和 SDK 一次性 action scope。native queue receipt 仍不等于 provider ACK，未知派发仍不得重试。
5. **runtime-wide 单活是独立前置。** 现有账号级 lease 不足以阻止同一 runtime identity 在不同账号或 mode 下并行启动。新设计须有持久化、受信的 runtime-identity-wide session 生命周期/单活边界，覆盖 native construction、运行、停止、资源静止证明、journal close 与恢复；另一个账号的启动也必须检查上一 session 的 close 状态和未决/`UNKNOWN`。native Join pending、关闭不确定、worker 遗失或 lease 状态不明时，runtime 状态应被 poison 并拒绝新启动，直到受信恢复完成。这个本地单活边界与外部账户级 writer fence 是两项不同证据，前者不证明跨主机/外部 writer 排他。
6. **重新启动废止全部旧审批。** 新 session 必须得到新 generation/approval domain；审批验证方与耐久账本共同拒绝旧 generation 的 receipt，即使配置字节后来恢复原值也一样。更换 mode/account/front/contract 或凭证只在旧 session 完全结束且其全部命令确定终态后，由同一路径的新启动采纳。旧 scope 的历史账本必须保留供审计，不允许重命名账号/更换 config 绕过 UNKNOWN。

上述快照/审批语义不取代真实账户隔离、provider session/readiness、账户状态完整性、生产 artifact/account admission、F14、风险监控或逐动作批准。生产 mode 即使能被同一文件解析，也仍须在缺少独立准入时于 credential、SDK、network、runner 和 native dispatch 前拒绝。

## 需要批准后才可替换的现行条款

| 现行条款 | 当前含义 | 若本 ADR 获批并实现，需改写为 |
| --- | --- | --- |
| `CTP同配置共享Runner开发与验收.md`「操作者合同」：运行中修改配置使旧 seal/approval 失效 | 编辑文件可使活动 session 的后续动作失效 | session scope 在启动时封存；编辑只影响下一次启动。紧急即时撤销必须走独立受信 revocation channel。 |
| `验收文档.md` AC41-37 §“S/P 共用的配置动作验收” | 对最后重封至 native dispatch 之间的文件/路径 mutation 做 race 负测；必须由同一 trusted fence 控制变更和 native 动作 | 移除动作级磁盘 mutation 负测作为本语义的验收；以稳定启动快照、活动 session 不重载、runtime-wide 单活、关闭/UNKNOWN 清零后才接受下一快照的竞态测试替代。仍需覆盖稳定快照自身的并发读写/替换。 |
| `验收用例与基准.md` TC83-I-OPS | 每个敏感动作前 fresh disk reread 同一配置及 selected pair | 改为验证动作完全绑定启动快照且逐动作审批精确绑定 generation/scope；动作路径不再把文件 reread 当作 scope 撤销机制。 |
| `tests/unit/runtime/test_ctp_simulation_execution.py::test_profile_config_change_after_final_check_blocks_native_dispatch` submit/cancel strict xfail | session 内 final-check 后配置变更必须阻止 native dispatch；当前 P2 的证据 | 在正式迁移完成前保持原样。迁移后才可改为 fake test：活动 session 修改文件不会改变其封存 scope；第二 session 因单活 lease 被拒绝；旧 session close + 未决/UNKNOWN 清零后，同路径新启动采纳合成新 mode；默认 live 仍在外部 I/O 前拒绝。 |
| `tests/unit/runtime/test_ctp_credential_binding.py` 中 config/credential rotation stale-binding 负测 | fresh action binding 重新读取并拒绝变化后的配置/凭证 | 明确区分启动前变更（影响新快照）与活动 session 内轮换（不热重载，下一 session 才生效）；action grant 继续校验当前 generation。紧急凭证撤销另需独立 revocation 测试。 |

此表只是迁移清单，不是对上述文件或测试的当前修改授权。特别是，不能仅删除 xfail 或把它改成通过测试来宣称 P2 关闭。

## 若获批的实现和 QA 顺序

1. **先决策，再改合同。** 由 config/security、runtime、execution、风险与独立 QA 维护者明确接受“不支持活动 session 热撤销”的语义和应急撤销缺口；同步修订本表列出的 AC、TC、状态标签与操作手册。未完成前保留当前合同、xfail 与 `NO_WRITE`。
2. **实现稳定启动快照。** 将受信 worker 接到一个能证明字节一致性的 config publisher/reader；同一字节对象既参与解析也参与 seal。fake tests 并发注入同 inode 写入、截断重写、原子 replace、目录/路径重定向、读取期间修改和完整无变化读取；不能区分稳定版本时全部 startup fail-closed。验证快照中无秘密明文，并验证 scope 字段变化逐一改变 digest。
3. **实现 runtime identity 单活生命周期。** 测试同一 runtime identity、不同 account/mode、不同进程并发打开只允许一个；第二次启动不得通过新 journal/account path 绕过。覆盖启动崩溃、native Join pending、stop timeout、未能证明 callback quiescence、账本 close 失败、遗留 `UNKNOWN` 和恢复成功/失败。锁的覆盖范围和平台/文件系统须明确；不支持或不能证明的环境直接拒绝，不宣称 POSIX/Windows 通用互斥。
4. **绑定固定 session deadline。** 使用独立审查的可信时钟/期限源，在启动时确定不可延长的 `valid_until`；测试过期在 reservation 前、SDK action gate 前和 native 调用前均拒绝，动作审批续发不能延长 session。时钟回拨、缺失或状态恢复不明时 fail-closed。
5. **迁移审批与凭证绑定。** 把审批、credential-binding tag/key id、session registration 和 journal scope 绑定到新 generation。测试旧 session 审批在新 session 一律失败、相同配置重启也不能复用；活动 session 内凭证轮换不改变快照，正常关闭后新启动使用新值；没有独立可信撤销源时不得声称可以即时撤销。所有 fake 观察保持凭证/SDK/network/native/write 计数为零。
6. **替换竞态验收并跑完整回归。** 在 fake worker 中打开 sandbox session 后编辑同一 config，证明原 session 只会使用旧封存 profile，且不能启动并行的新 live session；模拟未决/`UNKNOWN` 必须阻止切换。只有在原 session native 资源静止、账本全部终态、lease 正常释放后，才允许同一路径下一个 session 读到合成新 mode/preset。默认 live registration 仍须在 credentials、SDK、network、runner 和 native dispatch 前拒绝。随后才按批准后的新语义替换动作级 xfail/TC，并运行 runtime、integration、static route-audit suites。

## 当前 disposition 与未解决边界

在 ADR 决定前，原始 P2 仍为 OPEN，`test_profile_config_change_after_final_check_blocks_native_dispatch` 仍保持 strict xfail；不能用启动快照提案、Windows lease、普通重封或这份文档抵销。当前代码中的 `_ctp_credential_binding`、managed execution/session admission 与 approval/Store 仍按现有 fresh-config/scope 语义审查；本提案没有改它们。

即使将来接受，也必须证明可信启动快照和 runtime-wide 单活生命周期。若无法控制配置发布者，无法判定读到的字节是否为稳定版本，或无法在不同账号/worker 崩溃间保持单活恢复状态，本方案不可实施为可写路由，应继续 fail closed。立即配置撤销、外部账户 writer fence、共同账户快照以及回调/Join 的原生生命周期证明仍是独立问题。

## 相关记录

- [同配置共享 runner 合同](CTP同配置共享Runner开发与验收.md)
- [AC41-37 配置动作验收](验收文档.md)
- [验收用例与基准](验收用例与基准.md)
- [能力评估与 ADR 索引](能力评估与ADR索引.md)
- [配置动作线性化代码注记](../../../../../backtrader_runtime/ctp_config_action_linearization.py)（实现路径说明，不是信任证明）
