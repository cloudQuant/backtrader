# G1 output-channel r4：局部独立验收

独立复制并逐字节复核四份冻结源码/测试，Windows 焦点 `20 passed / 0 failed`。测试覆盖 r3 的伪造 outer-result 拒绝、同次运行的 exact result/request/worker 句柄绑定、worker 退出确认、构造失败清理及本机 near-63KiB 管道排空。

只接受输出通道 helper 的本地合同；尚未接成 coordinator+worker 的 Job、独立 receipt-writer Job、真实 Session0 token 交付、受保护部署或 native CTP。G1 仍 `NOT_PASSED`。

[机器记录](ctp-g1-output-channel-r4-independent-review-2026-09-27.json)与[原始归档](ctp-g1-output-channel-r4-independent-review-2026-09-27.raw.zip) SHA-256 `b7f0c4771c3a8755aa716451b323f9d91b73d1f32cda11ece178a4f0574ec5df`，9 项。
